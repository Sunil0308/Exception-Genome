"""Restore the scoped snapshot and escalate an unverified synthetic change."""
import sqlite3

from core.action_registry import ACTION_REGISTRY, ACTIVATE
from core.phase4_store import canonical, digest, now
from core.phase5_store import execution, log, operational_state, save, set_incident
from core.resolution_contract import contract_hash, current_contract

ACTOR = 'ROLLBACK_ENGINE'


def restore(db, record, contract, before):
    target, incident_id = record['target_service'], record['incident_id']
    previous = {row['reference_id']: row for row in before['references'] if row['service_id'] == target}
    old = contract.rollback_plan['credential_version']
    new = record['action_parameters']['credential_version']
    live = operational_state(db, incident_id)
    live_refs = {row['reference_id']: row for row in live['references'] if row['service_id'] == target}
    if not (previous.get(old, {}).get('active') == 1 and previous.get(new, {}).get('active') == 0
            and live_refs == {key: dict(row, active=int(key == new)) for key, row in previous.items()}):
        raise ValueError('Live reference configuration diverged from the applied change')
    touched = set(record['affected_services'])
    independent = {row['service_id'] for row in live['exceptions'] if row['incident_id'] != incident_id
                   and row['status'] != 'RESOLVED'}
    if independent & touched:
        raise ValueError('Independent failure overlaps the rollback scope')
    db.execute('UPDATE approved_resource_references SET active=0 WHERE service_id=?', (target,))
    db.execute('UPDATE approved_resource_references SET active=1 WHERE reference_id=?', (old,))
    services = [row for row in before['services'] if row['id'] in touched]
    for row in services:
        db.execute('UPDATE services SET status=?,health_state=?,last_success=?,error_state=? WHERE id=?',
                   (row['status'], row['health_state'], row['last_success'], row['error_state'], row['id']))
    live_exceptions = {row['id']: row for row in live['exceptions'] if row['incident_id'] == incident_id}
    for row in before['exceptions']:
        if row['incident_id'] == incident_id and row['service_id'] in touched:
            current = live_exceptions.get(row['id'], {})
            status = 'REOPENED' if current.get('status') in ('RECOVERING', 'RESOLVED') else row['status']
            db.execute('UPDATE exceptions SET status=? WHERE id=? AND incident_id=?', (status, row['id'], incident_id))
    db.execute('DELETE FROM operational_outputs WHERE incident_id=?', (incident_id,))
    for row in before['outputs']:
        db.execute('INSERT INTO operational_outputs VALUES (?,?,?,?,?,?,?)',
                   tuple(row[key] for key in ('incident_id', 'service_id', 'output_type', 'current_state',
                                              'expected_state', 'updated_at', 'source')))
    restored = operational_state(db, incident_id)
    if ([row for row in restored['references'] if row['service_id'] == target] != list(previous.values())
            or any({key: row[key] for key in ('status', 'health_state', 'last_success', 'error_state')}
                   != {key: next(old_row for old_row in services if old_row['id'] == row['id'])[key]
                       for key in ('status', 'health_state', 'last_success', 'error_state')}
                   for row in restored['services'] if row['id'] in touched)
            or restored['outputs'] != before['outputs']):
        raise ValueError('Restored configuration or service state did not match the snapshot')


def rollback(db, record):
    incident_id = record['incident_id']
    contract = current_contract(db, incident_id)
    before = record['previous_state_snapshot']
    set_incident(db, incident_id, 'ROLLBACK_IN_PROGRESS')
    log(db, record, ACTOR, 'ROLLBACK_STARTED')
    db.execute('SAVEPOINT scoped_rollback')
    try:
        action = ACTION_REGISTRY[ACTIVATE]
        if not (record['action_applied'] and record['rollback_required'] and before
                and digest(before) == record['state_digest_before']
                and record['action_type'] == ACTIVATE and action.reversibility
                and contract and contract.contract_id == record['contract_id']
                and contract_hash(contract) == contract.contract_hash == record['contract_hash']
                and contract.authority_scope.get('targets') == [record['target_service']]
                and contract.rollback_plan.get('action') == action.rollback_action
                and contract.rollback_plan.get('target_service') == record['target_service']
                and execution(db, incident_id)['execution_id'] == record['execution_id']):
            raise ValueError('Rollback snapshot, authority or execution identity is invalid')
        restore(db, record, contract, before)
    except (ValueError, KeyError, sqlite3.Error) as error:
        db.execute('ROLLBACK TO scoped_rollback')
        record.update(status='ESCALATED', rollback_status='ROLLBACK_FAILED', rollback_reason=str(error))
    else:
        record.update(status='ROLLED_BACK', rollback_status='ROLLBACK_COMPLETED', rollback_reason=None,
                      rollback_required=False)
    db.execute('RELEASE scoped_rollback')
    set_incident(db, incident_id, 'HUMAN_REVIEW_REQUIRED')
    record['state_digest_after'] = digest(operational_state(db, incident_id))
    db.execute('INSERT INTO rollback_records VALUES (?,?,?)', (
        record['execution_id'], record['rollback_status'],
        canonical({'completed_at': now(), 'reason': record['rollback_reason'],
                   'state_digest': record['state_digest_after']})))
    save(db, record)
    log(db, record, ACTOR, record['rollback_status'], result=record['rollback_status'],
        evidence={'reason': record['rollback_reason']})
    log(db, record, 'SYSTEM', 'HUMAN_REVIEW_REQUIRED', decision='HUMAN_REVIEW_REQUIRED')
    return record

