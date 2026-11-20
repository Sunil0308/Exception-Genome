import tempfile
import unittest
from pathlib import Path

from core.action_registry import ROTATE
from core.analysis import analyse, load
from core.database import connect, initialize, reset, snapshot
from core.execution_engine import DEMO_FAILURE, execute_controlled
from core.execution_readiness import READY, record_readiness
from core.impact_simulator import run_impact_simulation
from core.phase4_store import canonical
from core.phase5_store import execution, operational_state, save
from core.recovery_engine import advance_recovery
from core.resolution_contract import create_contract
from core.safety_gate import evaluate_safety_gate
from core.verification_engine import read_verification, run_verification
from simulator.incident_scenarios import INCIDENT_ID, advance, start


class Phase5Tests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'demo.db'
        initialize(self.path)
        start(self.path)
        while advance(self.path):
            pass
        analyse(INCIDENT_ID, self.path)

    def sql(self, statement, params=()):
        with connect(self.path) as db:
            return [dict(row) for row in db.execute(statement, params)]

    def state(self):
        with connect(self.path) as db:
            return operational_state(db, INCIDENT_ID)

    def prepare(self):
        contract = create_contract(INCIDENT_ID, self.path)
        evaluate_safety_gate(INCIDENT_ID, self.path)
        run_impact_simulation(INCIDENT_ID, self.path)
        self.assertEqual(record_readiness(INCIDENT_ID, self.path)['status'], READY)
        return contract

    def execute(self, **options):
        return execute_controlled(INCIDENT_ID, self.path, **options)

    def tick(self):
        return advance_recovery(INCIDENT_ID, self.path)

    def finish_recovery(self):
        for _ in range(30):
            if self.tick()['status'] == 'AWAITING_VERIFICATION':
                return
        self.fail('Dependency recovery did not terminate')

    def verify(self):
        return run_verification(INCIDENT_ID, self.path)

    def test_readiness_is_mandatory_and_must_be_recorded(self):
        self.assertEqual(self.execute()['failure_reason'], 'CONTRACT_MISSING')
        create_contract(INCIDENT_ID, self.path)
        self.assertEqual(self.execute()['failure_reason'], 'SAFETY_APPROVAL_MISSING')
        evaluate_safety_gate(INCIDENT_ID, self.path)
        self.assertEqual(self.execute()['failure_reason'], 'SIMULATION_MISSING')
        run_impact_simulation(INCIDENT_ID, self.path)
        self.assertEqual(self.execute()['failure_reason'], 'READINESS_NOT_RECORDED')

    def test_contract_hash_changes_and_a2_actions_are_blocked(self):
        old = self.prepare()
        create_contract(INCIDENT_ID, self.path, unsafe_demo=True)
        self.assertEqual(self.execute(expected_hash=old.contract_hash)['failure_reason'], 'CONTRACT_STALE')
        self.assertEqual(self.execute()['failure_reason'], 'ACTION_NOT_AUTHORISED')

    def test_a3_action_is_blocked(self):
        root = load(self.path, INCIDENT_ID)['root_cause_analyses'][0]
        root['recommended_action_type'] = ROTATE
        self.sql('UPDATE root_cause_analyses SET payload=? WHERE cluster_id=?',
                 (canonical(root), root['cluster_id']))
        create_contract(INCIDENT_ID, self.path)
        self.assertEqual(self.execute()['failure_reason'], 'ACTION_NOT_AUTHORISED')

    def test_changed_operational_state_blocks_execution(self):
        self.prepare()
        self.sql("UPDATE services SET status='FAILED' WHERE id='auth'")
        self.assertEqual(self.execute()['failure_reason'], 'STATE_CHANGED_AFTER_SIMULATION')
        self.assertEqual([row['reference_id'] for row in self.state()['references'] if row['active']], ['DH-v17'])

    def test_stale_safety_artifact_blocks_execution(self):
        self.prepare()
        self.sql("UPDATE safety_evaluations SET status='STALE'")
        self.assertEqual(self.execute()['failure_reason'], 'SAFETY_APPROVAL_STALE')

    def test_stale_simulation_blocks_execution(self):
        self.prepare()
        self.sql("UPDATE impact_simulations SET status='STALE'")
        self.assertEqual(self.execute()['failure_reason'], 'SIMULATION_STALE')

    def test_action_is_idempotent_and_persisted(self):
        contract = self.prepare()
        before = self.state()
        result = self.execute(expected_hash=contract.contract_hash)
        self.assertEqual(result['status'], 'RECOVERING')
        self.assertEqual(result['previous_state_snapshot'], before)
        self.assertTrue(all(result[key] for key in ('safety_evaluation_id', 'simulation_id', 'readiness_id')))
        self.assertEqual(self.execute()['execution_id'], result['execution_id'])
        self.assertTrue(self.execute()['duplicate'])
        with connect(self.path) as db:
            self.assertEqual(execution(db, INCIDENT_ID), result)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM executions').fetchone()[0], 1)
            columns = {r[1] for r in db.execute('PRAGMA table_info(approved_resource_references)')}
        self.assertEqual(columns, {'reference_id', 'service_id', 'status', 'approved', 'active', 'created_at'})
        after = self.state()
        self.assertEqual({row['reference_id']: row['active'] for row in after['references']},
                         {'DH-v17': 0, 'DH-v18': 1})
        status = {row['id']: row['status'] for row in after['services']}
        self.assertEqual(status['datahub'], 'RECOVERING')
        self.assertEqual(status['gateway'], 'DEGRADED')
        self.assertNotEqual(after['incident']['status'], 'RESOLVED')
        self.assertEqual(after['analysis'], before['analysis'])

    def test_recovery_uses_dependency_waves_and_reconnects(self):
        self.prepare()
        self.execute()
        previous = self.state()
        self.assertEqual(sum(row['status'] == 'RECOVERING' for row in previous['exceptions']), 1)
        record = self.tick()
        self.assertEqual(record['recovery_step'], 1)
        current = self.state()
        states = {row['id']: row for row in current['services']}
        self.assertEqual(states['datahub']['status'], 'HEALTHY')
        self.assertEqual(states['gateway']['status'], 'RECOVERING')
        self.assertNotEqual(states['fast']['status'], 'HEALTHY')
        self.assertEqual(states['auth'], next(row for row in previous['services'] if row['id'] == 'auth'))
        self.assertEqual(sum(row['status'] == 'RESOLVED' for row in current['exceptions']), 1)
        with connect(self.path) as db:
            self.assertEqual(execution(db, INCIDENT_ID)['recovery_step'], 1)
        self.finish_recovery()
        final = self.state()
        self.assertEqual(final['incident']['status'], 'AWAITING_VERIFICATION')
        self.assertTrue(all(row['status'] == 'RESOLVED' for row in final['exceptions']))

    def test_failed_dependency_prevents_recovery_and_closure(self):
        self.prepare()
        self.execute()
        self.sql("UPDATE services SET status='FAILED' WHERE id='auth'")
        self.finish_recovery()
        self.assertNotEqual(next(row for row in self.state()['services'] if row['id'] == 'gateway')['status'],
                            'HEALTHY')
        result = self.verify()
        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(self.state()['incident']['status'], 'HUMAN_REVIEW_REQUIRED')
        self.assertEqual(next(row for row in self.state()['services'] if row['id'] == 'auth')['status'], 'FAILED')

    def test_independent_verification_closes_and_persists(self):
        self.prepare()
        result = self.execute()
        with self.assertRaises(ValueError):
            self.verify()
        self.finish_recovery()
        with connect(self.path) as db:
            record = execution(db, INCIDENT_ID)
            record['result'] = 'UNTRUSTED_EXECUTION_RESULT'
            save(db, record)
        verified = self.verify()
        self.assertEqual(verified['status'], 'VERIFIED')
        self.assertEqual(sum(row['result'] == 'PASS' for row in verified['checks']), 15)
        self.assertEqual(verified['recovered_count'], 23)
        final = self.state()
        self.assertEqual(final['incident']['status'], 'RESOLVED')
        self.assertEqual(final['incident']['resolution_execution_id'], result['execution_id'])
        self.assertEqual(final['incident']['final_state_digest'], verified['state_digest'])
        self.assertFalse([row for row in final['exceptions'] if row['status'] != 'RESOLVED'])
        self.assertTrue(all(row['status'] == 'HEALTHY' for row in final['services']))
        with connect(self.path) as db:
            self.assertEqual(read_verification(db, result['execution_id']), verified)
        self.assertEqual(self.verify(), verified)

    def test_missing_output_is_inconclusive_and_never_closes(self):
        self.prepare()
        self.execute()
        self.finish_recovery()
        self.sql("DELETE FROM operational_outputs WHERE service_id='revenue'")
        self.assertEqual(self.verify()['status'], 'INCONCLUSIVE')
        self.assertEqual(self.state()['incident']['status'], 'HUMAN_REVIEW_REQUIRED')

    def test_failed_output_uses_snapshot_to_roll_back_and_escalate(self):
        self.prepare()
        before = self.state()
        self.execute(mode=DEMO_FAILURE)
        self.finish_recovery()
        self.assertTrue(all(row['status'] == 'HEALTHY' for row in self.state()['services']))
        result = self.verify()
        self.assertEqual(result['status'], 'FAILED')
        check = result['checks'][8]
        self.assertEqual((check['verification_rule_id'], check['expected'], check['actual']),
                         ('V-009', 'AVAILABLE', 'MISSING'))
        after = self.state()
        for key in ('services', 'references', 'outputs', 'analysis'):
            self.assertEqual(before[key], after[key])
        self.assertTrue(all(row['status'] == 'REOPENED' for row in after['exceptions']))
        self.assertEqual(after['incident']['status'], 'HUMAN_REVIEW_REQUIRED')
        self.assertIsNone(after['incident']['resolved_at'])
        events = {row['action'] for row in self.sql('SELECT action FROM execution_steps')}
        self.assertTrue({'EXECUTION_VALIDATION_STARTED', 'EXECUTION_VALIDATION_PASSED',
                         'CONTROLLED_ACTION_STARTED', 'APPROVED_REFERENCE_ACTIVATED',
                         'SERVICE_ENTERED_RECOVERY', 'SERVICE_RECOVERED', 'EXCEPTION_ENTERED_RECOVERY',
                         'EXCEPTION_RESOLVED', 'RECOVERY_COMPLETED', 'VERIFICATION_STARTED',
                         'VERIFICATION_RULE_PASSED', 'VERIFICATION_RULE_FAILED', 'VERIFICATION_COMPLETED',
                         'ROLLBACK_STARTED', 'ROLLBACK_COMPLETED', 'HUMAN_REVIEW_REQUIRED'} <= events)

    def test_rollback_rejects_divergent_configuration(self):
        self.prepare()
        self.execute(mode=DEMO_FAILURE)
        self.finish_recovery()
        self.sql("UPDATE approved_resource_references SET approved=0 WHERE reference_id='DH-v18'")
        self.assertEqual(self.verify()['status'], 'FAILED')
        self.assertEqual(self.sql('SELECT status FROM rollback_records')[0]['status'], 'ROLLBACK_FAILED')
        self.assertEqual(self.state()['incident']['status'], 'HUMAN_REVIEW_REQUIRED')

    def test_activation_transaction_rolls_back_partial_changes(self):
        self.prepare()
        for reference, partial in (('DH-v17', False), ('DH-v18', True)):
            with self.subTest(reference=reference):
                with connect(self.path) as db:
                    db.execute('DELETE FROM executions')
                    db.execute("UPDATE incidents SET status='DIAGNOSED'")
                    db.execute('DROP TRIGGER IF EXISTS fail_reference')
                    db.execute(f"""CREATE TRIGGER fail_reference BEFORE UPDATE ON approved_resource_references
                        WHEN OLD.reference_id='{reference}'
                        BEGIN SELECT RAISE(ABORT, 'synthetic write failure'); END""")
                before = self.state()
                result = self.execute()
                self.assertEqual(result['status'], 'FAILED')
                self.assertEqual(result['rollback_required'], partial)
                for key in ('references', 'services', 'exceptions', 'outputs', 'analysis'):
                    self.assertEqual(self.state()[key], before[key])
                self.assertEqual(self.state()['incident']['status'], 'EXECUTION_FAILED')

    def test_failed_recovery_wave_compensates_committed_activation(self):
        self.prepare()
        before = self.state()
        self.execute()
        self.sql("""CREATE TRIGGER fail_datahub_health BEFORE UPDATE ON services
                    WHEN OLD.id='datahub' AND NEW.status='HEALTHY'
                    BEGIN SELECT RAISE(ABORT, 'synthetic recovery failure'); END""")
        record = self.tick()
        self.assertEqual(record['result'], 'EXECUTION_FAILED')
        self.assertEqual(record['rollback_status'], 'ROLLBACK_COMPLETED')
        self.assertEqual(self.state()['incident']['status'], 'HUMAN_REVIEW_REQUIRED')
        for key in ('references', 'services', 'outputs'):
            self.assertEqual(self.state()[key], before[key])

    def test_reset_restores_healthy_baseline_and_clears_phase5(self):
        self.prepare()
        self.execute()
        self.finish_recovery()
        self.verify()
        reset(self.path)
        for table in ('executions', 'execution_steps', 'operational_outputs', 'verification_results',
                      'verification_checks', 'rollback_records'):
            self.assertEqual(self.sql(f'SELECT * FROM {table}'), [])
        state = snapshot(self.path)
        self.assertEqual(len(state['services']), 24)
        self.assertTrue(all(row['status'] == 'HEALTHY' for row in state['services']))
        self.assertEqual(state['exceptions'], [])
        self.assertEqual([row['reference_id'] for row in self.state()['references'] if row['active']], ['DH-v17'])
        root = Path(__file__).resolve().parents[1]
        self.assertFalse(any((root / name).exists() for name in (
            'n8n', 'production_integration')))





