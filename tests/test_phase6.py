import tempfile
import unittest
from pathlib import Path

from core.analysis import analyse
from core.audit import timeline
from core.database import connect, initialize, reset, snapshot
from core.execution_engine import DEMO_FAILURE, execute_controlled
from core.execution_readiness import READY, record_readiness
from core.impact_simulator import run_impact_simulation
from core.operational_memory import history, patterns
from core.prevention_engine import recommendations
from core.recovery_engine import advance_recovery
from core.resolution_contract import create_contract
from core.review import APPROVE, append_diagnostic_record, cases, decide
from core.safety_gate import evaluate_safety_gate
from core.verification_engine import run_verification
from simulator.incident_scenarios import AMBIGUOUS, CONCURRENT, DATAHUB, MERCHANT, advance, get_scenario, start


class Phase6Tests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'scenario.db'
        initialize(self.path)

    def diagnose(self, scenario):
        start(self.path, scenario)
        while advance(self.path, scenario):
            pass
        return analyse(scenario.incident_id, self.path)

    def authorize(self, scenario):
        incident_id = scenario.incident_id
        create_contract(incident_id, self.path)
        gate = evaluate_safety_gate(incident_id, self.path)
        projection = run_impact_simulation(incident_id, self.path)
        self.assertEqual(projection['result'], 'PASS')
        return gate

    def finish(self, incident_id):
        result = execute_controlled(incident_id, self.path)
        self.assertEqual(result['status'], 'RECOVERING', result.get('failure_reason'))
        for _ in range(25):
            if advance_recovery(incident_id, self.path)['status'] == 'AWAITING_VERIFICATION':
                break
        verification = run_verification(incident_id, self.path)
        self.assertEqual(verification['status'], 'VERIFIED', [
            (r['name'], r['actual']) for r in verification['checks'] if r['result'] != 'PASS'])
        return verification

    def test_isolated_restart_requires_current_human_authority(self):
        diagnosis = self.diagnose(MERCHANT)
        incident_id = MERCHANT.incident_id
        self.assertEqual(diagnosis['correlation_clusters'][0]['assignment_status'], 'SINGLETON')
        self.assertEqual(self.authorize(MERCHANT)['decision'], 'HUMAN_REVIEW_REQUIRED')
        self.assertEqual(execute_controlled(incident_id, self.path)['failure_reason'], 'HUMAN_APPROVAL_REQUIRED')
        before = snapshot(self.path)
        with connect(self.path) as db:
            case = cases(db)[0]
            approval = decide(db, case['review_id'], 'Operations Reviewer', APPROVE, 'Evidence and projection checked')
            self.assertEqual(approval['contract_hash'], case['contract_hash'])
        self.assertEqual(record_readiness(incident_id, self.path)['status'], READY)
        self.finish(incident_id)
        after = snapshot(self.path)
        self.assertEqual([r for r in before['services'] if r['id'] != 'merchant'],
                         [r for r in after['services'] if r['id'] != 'merchant'])
        self.assertEqual(after['incidents'][0]['status'], 'RESOLVED')
        with connect(self.path) as db:
            self.assertIn('REVIEW_DECISION', {e['action'] for e in timeline(db)})

    def test_concurrent_sources_remain_separate(self):
        analysis = self.diagnose(CONCURRENT)
        self.assertEqual(sorted(len(c['members']) for c in analysis['correlation_clusters']), [2, 2])
        self.assertEqual({root['root_cause_service_id'] for root in analysis['root_cause_analyses']},
                         {'event_bus', 'scheduler'})

    def test_cluster_contract_artifacts_are_separate(self):
        diagnosed = self.diagnose(CONCURRENT)
        incident_id = CONCURRENT.incident_id
        left, right = [row['id'] for row in diagnosed['correlation_clusters']]
        a = create_contract(incident_id, self.path, cluster_id=left)
        b = create_contract(incident_id, self.path, cluster_id=right)
        self.assertNotEqual(a.contract_hash, b.contract_hash)
        gate = evaluate_safety_gate(incident_id, self.path, cluster_id=left)
        self.assertEqual(gate['contract_id'], a.contract_id)
        self.assertEqual(execute_controlled(incident_id, self.path)['failure_reason'],
                         'MULTI_CLUSTER_EXECUTION_NOT_SUPPORTED')

    def test_approval_becomes_stale_after_state_drift(self):
        self.diagnose(MERCHANT)
        self.authorize(MERCHANT)
        with connect(self.path) as db:
            case = cases(db)[0]
            decide(db, case['review_id'], 'Operations Reviewer', APPROVE, 'Evidence and projection checked')
        self.assertEqual(record_readiness(MERCHANT.incident_id, self.path)['status'], READY)
        with connect(self.path) as db:
            db.execute("UPDATE services SET status='FAILED' WHERE id='auth'")
        self.assertEqual(execute_controlled(MERCHANT.incident_id, self.path)['status'], 'BLOCKED')

    def test_ambiguous_diagnosis_and_versioned_evidence(self):
        analysis = self.diagnose(AMBIGUOUS)
        root = analysis['root_cause_analyses'][0]
        self.assertEqual(root['diagnosis_outcome'], 'NO_CONFIDENT_ROOT_CAUSE')
        contract = create_contract(AMBIGUOUS.incident_id, self.path)
        self.assertEqual(contract.action_type, 'ESCALATE')
        with connect(self.path) as db:
            case = cases(db)[0]
            decide(db, case['review_id'], 'Risk Reviewer', 'REQUEST MORE EVIDENCE', 'Need upstream traces')
            version = append_diagnostic_record(db, case['review_id'], 'Probe returned incomplete upstream traces.')
            self.assertEqual(version['diagnosis_version'], 2)
            self.assertEqual(db.execute('SELECT status FROM resolution_contracts').fetchone()[0], 'SUPERSEDED')
        self.assertEqual(execute_controlled(AMBIGUOUS.incident_id, self.path)['status'], 'BLOCKED')

    def test_recurrence_uses_real_verified_occurrences_and_requires_safety(self):
        for index, scenario in enumerate((DATAHUB, get_scenario('INC-REC-005'), get_scenario('INC-REC-006')), 1):
            diagnosis = self.diagnose(scenario)
            if index > 1:
                self.assertEqual(diagnosis['root_cause_analyses'][0]['historical_matches'][0]['similarity_score'], 100)
                self.assertEqual(execute_controlled(scenario.incident_id, self.path)['status'], 'BLOCKED')
            self.authorize(scenario)
            self.assertEqual(record_readiness(scenario.incident_id, self.path)['status'], READY)
            self.finish(scenario.incident_id)
            reset(self.path, preserve_memory=True)
            with connect(self.path) as db:
                aggregated = patterns(history(db))
                self.assertEqual(aggregated[0]['verified'], index)
                self.assertEqual(bool(recommendations(aggregated)), index >= 3)
        reset(self.path)
        with connect(self.path) as db:
            self.assertEqual(history(db), [])

    def test_failed_verification_remains_negative_history_and_audit(self):
        incident = DATAHUB.incident_id
        self.diagnose(DATAHUB)
        self.authorize(DATAHUB)
        record_readiness(incident, self.path)
        self.assertEqual(execute_controlled(incident, self.path, mode=DEMO_FAILURE)['status'], 'RECOVERING')
        for _ in range(25):
            if advance_recovery(incident, self.path)['status'] == 'AWAITING_VERIFICATION':
                break
        self.assertEqual(run_verification(incident, self.path)['status'], 'FAILED')
        reset(self.path, preserve_memory=True)
        with connect(self.path) as db:
            memory = history(db)[0]
            self.assertEqual(memory['success_count'], 0)
            self.assertEqual(memory['rollback_result'], 'ROLLBACK_COMPLETED')
            actions = {event['action'] for event in timeline(db)}
            self.assertTrue({'INCIDENT_DETECTED', 'GENOME_ANALYSIS', 'ROOT_CAUSE_ANALYSIS',
                             'VERIFICATION_RULE_FAILED', 'ROLLBACK_COMPLETED', 'MEMORY_CREATED'} <= actions)
