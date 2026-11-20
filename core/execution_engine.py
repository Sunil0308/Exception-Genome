"""Controlled writes to the local synthetic simulator."""
import sqlite3
from typing import TypedDict

from core.action_registry import ACTION_REGISTRY, ACTIVATE, RESTART
from core.database import DEFAULT_DB, connect
from core.execution_readiness import READY, read_decision
from core.phase4_store import canonical, digest, identifier, latest, now
from core.phase5_store import OUTPUTS, execution, log, operational_state, save, set_incident
from core.resolution_contract import current_contract, contract_hash, read_context

from core.review import current_approval

NORMAL = 'NORMAL'
DEMO_FAILURE = 'SYNTHETIC_VERIFICATION_FAILURE'
ACTOR = 'EXECUTION_ENGINE'


class Execution(TypedDict):
    execution_id: str
    incident_id: str
    contract_id: str | None
    contract_hash: str | None
    safety_evaluation_id: str | None
    simulation_id: str | None
    readiness_id: str | None
    action_type: str | None
    target_service: str | None
    action_parameters: dict
    previous_state_snapshot: dict
    started_at: str
    completed_at: str | None
    status: str
    result: str | None
    failure_reason: str | None
    rollback_required: bool
    rollback_status: str | None
    state_digest_before: str
    state_digest_after: str | None
    mode: str
    affected_services: list[str]
    action_applied: bool
    recovery_step: int


def validation_reason(db, contract, context, expected_hash):
    incident = context['incident']
    if incident['status'] == 'RESOLVED':
        return 'INCIDENT_ALREADY_RESOLVED'
    if contract is None:
        return 'CONTRACT_MISSING'
    if contract.status != 'CURRENT' or contract_hash(contract) != contract.contract_hash or (
        expected_hash is not None and expected_hash != contract.contract_hash
    ):
        return 'CONTRACT_STALE'
    action = ACTION_REGISTRY.get(contract.action_type)
    human_restart = contract.action_type == RESTART and contract.target_service in ('merchant', 'scheduler', 'event_bus')
    if not (human_restart or (action and action.autonomous_execution_permitted
                              and action.autonomy_class == 'A1' and contract.action_type == ACTIVATE)):
        return 'ACTION_NOT_AUTHORISED'
    if contract.target_service != contract.root_cause_service:
        return 'TARGET_MISMATCH'
    if incident['status'] != 'DIAGNOSED':
        return 'INCIDENT_NOT_EXECUTION_ELIGIBLE'
    ready = read_decision(db, contract.incident_id, contract.cluster_id)
    gate, simulation = ready.get('safety'), ready.get('simulation')
    if simulation and simulation['input_state_digest'] != digest(context):
        return 'STATE_CHANGED_AFTER_SIMULATION'
    if human_restart and not current_approval(db, contract):
        return 'HUMAN_APPROVAL_REQUIRED'
    if ready['safety_status'] != ('HUMAN_REVIEW_REQUIRED' if human_restart else 'APPROVED') or not gate:
        return 'SAFETY_APPROVAL_STALE' if gate else 'SAFETY_APPROVAL_MISSING'
    if ready['simulation_status'] != 'PASS' or not simulation:
        return 'SIMULATION_STALE' if simulation else 'SIMULATION_MISSING'
    if ready['status'] != READY:
        return 'READINESS_NOT_CURRENT'
    receipt = latest(db, 'execution_readiness', contract.contract_id)
    if not (receipt and receipt['status'] == receipt['record_status'] == READY
            and receipt['input_state_digest'] == ready['input_state_digest']
            and receipt['evaluation_id'] == gate['evaluation_id']
            and receipt['simulation_id'] == simulation['simulation_id']):
        return 'READINESS_NOT_RECORDED'
    return None


def activate(db, contract, record):
    target = contract.target_service
    if contract.action_type == RESTART:
        from core.recovery_engine import enter_recovery
        name, expected = OUTPUTS[target]
        db.execute('INSERT INTO operational_outputs VALUES (?,?,?,?,?,?,?)',
                   (contract.incident_id, target, name, 'MISSING', expected, now(), ACTOR))
        enter_recovery(db, record, target)
        return
    old = contract.rollback_plan['credential_version']
    new = contract.action_parameters['credential_version']
    for reference, before, after, status in ((old, 1, 0, 'EXPIRED'), (new, 0, 1, 'VALID')):
        updated = db.execute('UPDATE approved_resource_references SET active=? '
                             'WHERE reference_id=? AND service_id=? AND active=? AND approved=1 AND status=?',
                             (after, reference, target, before, status))
        if updated.rowcount != 1:
            raise ValueError(f'Reference {reference} no longer meets the action precondition')
    for service, (label, expected) in OUTPUTS.items():
        if service in record['affected_services']:
            db.execute('INSERT INTO operational_outputs VALUES (?,?,?,?,?,?,?)',
                       (contract.incident_id, service, label, 'VALID' if service == target else 'MISSING',
                        expected, now(), ACTOR))
    from core.recovery_engine import enter_recovery
    enter_recovery(db, record, target)


def execute_controlled(incident_id, path=DEFAULT_DB, *, expected_hash=None, mode=NORMAL, cluster_id=None, expected_state_digest=None):
    if mode not in (NORMAL, DEMO_FAILURE):
        raise ValueError('Unsupported synthetic execution mode')
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        context = read_context(db, incident_id)
        if expected_state_digest and digest(context) != expected_state_digest:
            return {'status': 'BLOCKED', 'result': 'EXECUTION_BLOCKED', 'failure_reason': 'STATE_CHANGED'}
        if not context['incident']:
            return {'status': 'BLOCKED', 'result': 'EXECUTION_BLOCKED', 'failure_reason': 'INCIDENT_NOT_FOUND'}
        multi = len(context['analysis']['correlation_clusters']) > 1
        contract = current_contract(db, incident_id, cluster_id)
        prior = execution(db, incident_id, cluster_id)
        if prior and prior['contract_hash'] == (expected_hash or (contract and contract.contract_hash)):
            return dict(prior, duplicate=True)
        reason = ('MULTI_CLUSTER_EXECUTION_NOT_SUPPORTED' if multi and cluster_id is None
                  else validation_reason(db, contract, context, expected_hash))
        if multi and not reason:
            current = execution(db, incident_id)
            if current and current['status'] in ('RECOVERING', 'AWAITING_VERIFICATION'):
                reason = 'ANOTHER_ASSIGNMENT_IN_PROGRESS'
        if prior and not reason:
            reason = 'ACTION_ALREADY_EXECUTED'
        record = Execution(
            execution_id=identifier('EXE', incident_id), incident_id=incident_id,
            contract_id=contract.contract_id if contract else None,
            contract_hash=contract.contract_hash if contract else None,
            safety_evaluation_id=None, simulation_id=None, readiness_id=None,
            action_type=contract.action_type if contract else None,
            target_service=contract.target_service if contract else None,
            action_parameters=contract.action_parameters if contract else {},
            previous_state_snapshot={}, started_at=now(), completed_at=None, status='VALIDATING',
            result=None, failure_reason=None, rollback_required=False, rollback_status=None,
            state_digest_before=digest(context), state_digest_after=None, mode=mode, affected_services=[],
            action_applied=False, recovery_step=0,
        )
        key = None if reason else digest([
            incident_id, contract.contract_hash, contract.action_type, contract.target_service, contract.action_parameters,
        ])
        db.execute('INSERT INTO executions VALUES (?,?,?,?,?,?)',
                   (record['execution_id'], incident_id, record['contract_id'], key,
                    record['status'], canonical(record)))
        log(db, record, ACTOR, 'EXECUTION_VALIDATION_STARTED')
        if reason:
            record.update(status='BLOCKED', result='EXECUTION_BLOCKED', failure_reason=reason, completed_at=now())
            save(db, record)
            log(db, record, ACTOR, 'EXECUTION_BLOCKED', decision=reason)
            return record
        decision = read_decision(db, incident_id, cluster_id)
        authority = current_approval(db, contract) if contract.action_type == RESTART else None
        if authority:
            record['review_decision_id'] = authority['review_decision_id']
        receipt = latest(db, 'execution_readiness', contract.contract_id)
        before = operational_state(db, incident_id)
        record.update(cluster_id=contract.cluster_id, multi_assignment=multi)
        record.update(safety_evaluation_id=decision['safety']['evaluation_id'],
                      simulation_id=decision['simulation']['simulation_id'], readiness_id=receipt['readiness_id'],
                      previous_state_snapshot=before, state_digest_before=digest(before),
                      affected_services=sorted({row['service_id'] for row in context['exceptions']
                                                if row['id'] in contract.evidence_snapshot['genome_signatures']}),
                      status='EXECUTING')
        log(db, record, ACTOR, 'EXECUTION_VALIDATION_PASSED', decision=READY)
        if not multi:
            set_incident(db, incident_id, 'EXECUTING')
        save(db, record)
        log(db, record, ACTOR, 'CONTROLLED_ACTION_STARTED')
        db.execute('SAVEPOINT activate_reference')
        try:
            activate(db, contract, record)
        except (sqlite3.Error, ValueError) as error:
            partial = operational_state(db, incident_id)['references'] != before['references']
            db.execute('ROLLBACK TO activate_reference')
            db.execute('RELEASE activate_reference')
            if not multi:
                set_incident(db, incident_id, 'EXECUTION_FAILED')
            record.update(status='FAILED', result='EXECUTION_FAILED', failure_reason=str(error),
                          completed_at=now(), rollback_required=partial,
                          rollback_status='ROLLBACK_COMPLETED' if partial else None,
                          state_digest_after=digest(operational_state(db, incident_id)))
            if partial:
                log(db, record, 'ROLLBACK_ENGINE', 'ROLLBACK_STARTED', evidence={'scope': 'activation savepoint'})
                log(db, record, 'ROLLBACK_ENGINE', 'ROLLBACK_COMPLETED', result='ATOMIC_SAVEPOINT_RESTORED')
                db.execute('INSERT INTO rollback_records VALUES (?,?,?)',
                           (record['execution_id'], 'ROLLBACK_COMPLETED',
                            canonical({'method': 'activation savepoint', 'restored_digest': record['state_digest_after']})))
            log(db, record, ACTOR, 'EXECUTION_FAILED', result=str(error))
        else:
            db.execute('RELEASE activate_reference')
            if not multi:
                set_incident(db, incident_id, 'RECOVERING')
            record.update(status='RECOVERING', result='ACTION_APPLIED', action_applied=True,
                          state_digest_after=digest(operational_state(db, incident_id)))
            log(db, record, ACTOR, 'CONTROLLED_RESTART_APPLIED' if contract.action_type == RESTART else 'APPROVED_REFERENCE_ACTIVATED', result='APPLIED',
                evidence=contract.action_parameters)
        save(db, record)
        return record








