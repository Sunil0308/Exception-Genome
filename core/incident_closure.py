"""Close only against a persisted, current independent verification artifact."""
import json

from core.phase4_store import now
from core.phase5_store import log, operational_state, verification_digest
from core.resolution_contract import contract_hash, current_contract


def close_verified_incident(db, record, verification):
    incident_id = record['incident_id']
    state = operational_state(db, incident_id)
    contract = current_contract(db, incident_id, record.get('cluster_id'))
    persisted = db.execute('SELECT * FROM verification_results WHERE id=? AND execution_id=?',
                           (verification['verification_id'], record['execution_id'])).fetchone()
    checks = db.execute('SELECT rule_id,result FROM verification_checks WHERE verification_id=?',
                        (verification['verification_id'],)).fetchall()
    if not (record['status'] == 'COMPLETED' and record['completed_at'] and not record['rollback_required']
            and state['incident']['status'] == ('DIAGNOSED' if record.get('multi_assignment') else 'AWAITING_VERIFICATION')
            and contract and contract.status == 'CURRENT' and contract.contract_id == record['contract_id']
            and contract_hash(contract) == contract.contract_hash == record['contract_hash']
            and persisted and persisted['status'] == 'VERIFIED'
            and json.loads(persisted['payload']) == verification
            and persisted['state_digest'] == verification_digest(state)
            and {row['rule_id'] for row in checks} == {f'V-{n:03d}' for n in range(1, 16)}
            and all(row['result'] == 'PASS' for row in checks)
            and all(row['status'] == 'RESOLVED' for row in state['exceptions'] if row['incident_id'] == incident_id and row['service_id'] in record['affected_services'])):
        return False
    if record.get('multi_assignment'):
        log(db, record, 'SYSTEM', 'ASSIGNMENT_RESOLVED', decision='RESOLVED',
            state_digest=persisted['state_digest'], evidence={'assignment_id': record['cluster_id']})
        from core.phase5_store import execution
        ready = []
        services = {row['id']: row['status'] for row in state['services']}
        for cluster in state['analysis']['correlation_clusters']:
            scoped = execution(db, incident_id, cluster['id'])
            current = current_contract(db, incident_id, cluster['id'])
            passed = db.execute("SELECT 1 FROM verification_results WHERE execution_id=? AND status='VERIFIED'",
                                (scoped['execution_id'],)).fetchone() if scoped else None
            ready.append(bool(passed and current and scoped['status'] == 'COMPLETED'
                              and current.contract_hash == scoped['contract_hash']
                              and current.status == 'CURRENT' and contract_hash(current) == current.contract_hash
                              and all(services.get(k) == 'HEALTHY' for k in scoped['affected_services'])))
        if not all(ready) or any(row['status'] != 'RESOLVED' for row in state['exceptions']
                                 if row['incident_id'] == incident_id):
            return True
    db.execute("UPDATE incidents SET status='RESOLVED',resolved_at=?,resolution_execution_id=?,verification_id=?,"
               "final_state_digest=? WHERE id=?", (now(), record['execution_id'], verification['verification_id'],
                                                    persisted['state_digest'], incident_id))
    log(db, record, 'SYSTEM', 'INCIDENT_RESOLVED', decision='RESOLVED',
        state_digest=persisted['state_digest'], evidence={'verification_id': verification['verification_id']})
    return True


