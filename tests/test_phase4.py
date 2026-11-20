import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from core.action_registry import ROTATE
from core.analysis import analyse, load, ready
from core.correlation_engine import compatible, pair_score
from core.database import connect, initialize, snapshot
from core.exception_genome import generate
from core.execution_readiness import READY, execution_readiness, record_readiness
from core.impact_simulator import project, run_impact_simulation
from core.phase4_store import canonical
from core.resolution_contract import contract_hash, create_contract, read_context
from core.safety_gate import assess, evaluate_safety_gate
from core.service_graph import build_graph
from simulator.incident_scenarios import DATAHUB, INCIDENT_ID, SCENARIOS, advance, start


class Phase4Tests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'phase4.db'
        initialize(self.path)
        start(self.path)
        while advance(self.path):
            pass

    def plan(self):
        analyse(INCIDENT_ID, self.path)
        return create_contract(INCIDENT_ID, self.path)

    def context(self):
        with connect(self.path) as db:
            return read_context(db, INCIDENT_ID)

    def test_analysis_is_incident_scoped_and_ids_are_unique(self):
        scenario = replace(DATAHUB, incident_id='INC-OTHER', scenario_id='other')
        with patch.dict(SCENARIOS, {scenario.incident_id: scenario}):
            start(self.path, scenario)
            self.assertFalse(ready(snapshot(self.path), scenario.incident_id))
            while advance(self.path, scenario):
                pass
            self.assertTrue(ready(snapshot(self.path), scenario.incident_id))
            other = analyse(scenario.incident_id, self.path)
            flagship = analyse(INCIDENT_ID, self.path)
            for result, incident_id in ((other, scenario.incident_id), (flagship, INCIDENT_ID)):
                self.assertEqual(len(result['exception_genomes']), 23)
                self.assertEqual(len(result['correlation_clusters']), 1)
                self.assertIn(incident_id, result['correlation_clusters'][0]['id'])
                self.assertIn(incident_id, result['root_cause_analyses'][0]['analysis_id'])
            ids = lambda result: {g['exception_id'] for g in result['exception_genomes']}
            self.assertFalse(ids(other) & ids(flagship))

    def test_directional_compatibility(self):
        self.assertTrue(compatible('AUTHENTICATION_FAILURE', 'MISSING_SOURCE_DATA'))
        self.assertFalse(compatible('MISSING_SOURCE_DATA', 'AUTHENTICATION_FAILURE'))
        self.assertFalse(compatible('PROCESSING_BLOCKED', 'UPSTREAM_DATA_UNAVAILABLE'))
        state = snapshot(self.path)
        graph = build_graph(state['services'])
        genomes = [generate(row, graph) for row in state['exceptions']]
        root = next(g for g in genomes if g.service_id == 'datahub')
        symptom = next(g for g in genomes if g.service_id == 'revenue')
        self.assertEqual(pair_score(root, symptom, graph, genomes)['signals']['error_relationship'], 15)
        left = next(g for g in genomes if g.service_id == 'daily_recon')
        right = next(g for g in genomes if g.service_id == 'revenue')
        self.assertEqual(pair_score(left, right, graph, genomes)['signals']['error_relationship'], 0)
        invalid = replace(root, normalized_error_family='MISSING_SOURCE_DATA')
        backward = replace(root, timestamp='2026-11-17T09:02:00')
        for candidate in (invalid, backward):
            self.assertEqual(pair_score(candidate, symptom, graph, genomes)['signals']['error_relationship'], 0)

    def test_contract_freezes_evidence_and_hash_is_deterministic(self):
        contract = self.plan()
        self.assertEqual(contract.analysis_id, load(self.path, INCIDENT_ID)['root_cause_analyses'][0]['analysis_id'])
        self.assertEqual(contract.evidence_snapshot['affected_service_count'], 23)
        self.assertEqual(len(contract.evidence_snapshot['genome_signatures']), 23)
        self.assertEqual(contract, create_contract(INCIDENT_ID, self.path))
        updated_time = replace(contract, created_at='different',
                               evidence_snapshot=dict(contract.evidence_snapshot, snapshot_at='different'))
        self.assertEqual(contract_hash(updated_time), contract.contract_hash)
        for altered in (replace(contract, proposed_action='Different action'),
                        replace(contract, action_parameters={'credential_version': 'DH-other'}),
                        replace(contract, evidence_snapshot=dict(contract.evidence_snapshot, affected_service_count=22))):
            self.assertNotEqual(contract_hash(altered), contract.contract_hash)

    def test_gate_rejects_prohibited_wrong_target_reference_scope_and_missing_evidence(self):
        contract = self.plan()
        context = self.context()
        gate = evaluate_safety_gate(INCIDENT_ID, self.path)
        self.assertEqual(gate['decision'], 'APPROVED')
        self.assertEqual([r['result'] for r in gate['rules']], ['PASS'] * 18)
        for changes, expected_rule in (
            ({'action_type': ROTATE}, 'SG-009'),
            ({'target_service': 'auth'}, 'SG-007'),
            ({'action_parameters': {'credential_version': 'DH-unknown'}}, 'SG-011'),
            ({'authority_scope': dict(contract.authority_scope, targets=['datahub', 'auth'])}, 'SG-015'),
            ({'evidence_snapshot': {}}, 'SG-017'),
        ):
            with self.subTest(rule=expected_rule):
                modified = replace(contract, **changes)
                modified = replace(modified, contract_hash=contract_hash(modified))
                report = assess(modified, modified, context)
                self.assertEqual(report['decision'], 'BLOCKED')
                self.assertIn(expected_rule, {r['rule_id'] for r in report['rules'] if r['result'] == 'FAIL'})
        self.assertEqual(assess(replace(contract, proposed_action='tampered'), contract, context)['rules'][2]['result'], 'FAIL')

    def test_analysis_request_for_rotation_becomes_blocked_contract(self):
        analyse(INCIDENT_ID, self.path)
        root = load(self.path, INCIDENT_ID)['root_cause_analyses'][0]
        root.update(recommended_action='Create a new credential', recommended_action_type=ROTATE)
        with connect(self.path) as db:
            db.execute('UPDATE root_cause_analyses SET payload=? WHERE cluster_id=?',
                       (canonical(root), root['cluster_id']))
        contract = create_contract(INCIDENT_ID, self.path)
        self.assertEqual(contract.action_type, ROTATE)
        self.assertEqual(evaluate_safety_gate(INCIDENT_ID, self.path)['decision'], 'BLOCKED')

    def test_sandbox_and_readiness_leave_operational_database_unchanged(self):
        contract = self.plan()
        before = self.context()
        self.assertEqual(execution_readiness(INCIDENT_ID, self.path)['status'], 'NOT_READY')
        with self.assertRaises(ValueError):
            run_impact_simulation(INCIDENT_ID, self.path)
        evaluate_safety_gate(INCIDENT_ID, self.path)
        self.assertEqual(execution_readiness(INCIDENT_ID, self.path)['status'], 'NOT_READY')
        simulation = run_impact_simulation(INCIDENT_ID, self.path)
        self.assertEqual(simulation['result'], 'PASS')
        self.assertEqual(len(simulation['projected_recoveries']), 23)
        self.assertEqual(simulation['contract_hash'], contract.contract_hash)
        for field in ('projected_unresolved', 'new_failures', 'unexpected_impacts', 'policy_violations'):
            self.assertEqual(simulation[field], [])
        self.assertEqual(record_readiness(INCIDENT_ID, self.path)['status'], READY)
        self.assertEqual(self.context(), before)
        self.assertEqual(sum(r['status'] == 'ACTIVE' for r in before['exceptions']), 23)
        self.assertEqual(sum(r['status'] in ('FAILED', 'DEGRADED') for r in before['services']), 23)
        with connect(self.path) as db:
            events = {r[0] for r in db.execute('SELECT event_type FROM phase4_audit_events')}
        self.assertEqual(events, {'RESOLUTION_CONTRACT_CREATED', 'CONTRACT_VERSION_GENERATED',
                                  'SAFETY_EVALUATION_PERFORMED', 'IMPACT_SIMULATION_STARTED',
                                  'IMPACT_SIMULATION_COMPLETED', 'READINESS_DETERMINED'})

    def test_alternate_failed_dependency_leaves_service_unresolved(self):
        contract = self.plan()
        context = self.context()
        auth = next(row for row in context['services'] if row['id'] == 'auth')
        auth['status'] = 'FAILED'
        downstream = next(row for row in context['services'] if row['id'] == 'revenue')
        downstream['dependencies'] = json.dumps(sorted(set(json.loads(downstream['dependencies'])) | {'auth'}))
        result = project(contract, context)
        self.assertEqual(result['result'], 'FAIL')
        self.assertIn('revenue', result['projected_unresolved'])

    def test_unsafe_candidate_supersedes_artifacts_and_fails_in_isolation(self):
        old = self.plan()
        evaluate_safety_gate(INCIDENT_ID, self.path)
        run_impact_simulation(INCIDENT_ID, self.path)
        unsafe = create_contract(INCIDENT_ID, self.path, unsafe_demo=True)
        self.assertGreater(unsafe.contract_version, old.contract_version)
        self.assertNotEqual(unsafe.contract_hash, old.contract_hash)
        self.assertEqual(execution_readiness(INCIDENT_ID, self.path)['status'], 'NOT_READY')
        with connect(self.path) as db:
            for table in ('safety_evaluations', 'impact_simulations'):
                self.assertEqual(db.execute(f'SELECT status FROM {table}').fetchone()[0], 'STALE')
        evaluation = evaluate_safety_gate(INCIDENT_ID, self.path)
        self.assertEqual(evaluation['decision'], 'BLOCKED')
        before = self.context()
        with self.assertRaises(ValueError):
            run_impact_simulation(INCIDENT_ID, self.path)
        unsafe_projection = run_impact_simulation(INCIDENT_ID, self.path, unsafe_demo=True)
        self.assertEqual(unsafe_projection['result'], 'FAIL')
        self.assertFalse(unsafe_projection['root_cause_resolved'])
        self.assertIn('auth', unsafe_projection['new_failures'])
        self.assertEqual(execution_readiness(INCIDENT_ID, self.path)['status'], 'BLOCKED')
        self.assertEqual(before, self.context())

    def test_inconclusive_is_never_ready_and_changed_state_stales_projection(self):
        self.plan()
        evaluate_safety_gate(INCIDENT_ID, self.path)
        result = run_impact_simulation(INCIDENT_ID, self.path)
        with connect(self.path) as db:
            db.execute("UPDATE impact_simulations SET status='INCONCLUSIVE',payload=?",
                       (canonical(dict(result, result='INCONCLUSIVE')),))
        self.assertEqual(execution_readiness(INCIDENT_ID, self.path)['status'], 'NOT_READY')
        with connect(self.path) as db:
            db.execute("UPDATE services SET status='FAILED' WHERE id='auth'")
        state = execution_readiness(INCIDENT_ID, self.path)
        self.assertEqual(state['simulation_status'], 'STALE')
        self.assertEqual(state['safety_status'], 'STALE')
        self.assertNotEqual(state['status'], READY)
        record_readiness(INCIDENT_ID, self.path)
        with connect(self.path) as db:
            self.assertEqual(db.execute('SELECT status FROM impact_simulations').fetchone()[0], 'STALE')




