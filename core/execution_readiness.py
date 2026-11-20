"""Combine current evidence and persisted decision records into a readiness status."""
from core.database import DEFAULT_DB, connect
from core.impact_simulator import sandbox_eligible
from core.phase4_store import audit, identifier, latest, now, persist
from core.resolution_contract import current_contract, read_context
from core.safety_gate import assess
from core.review import current_approval

READY = 'READY_FOR_CONTROLLED_EXECUTION'


def read_decision(db, incident_id, cluster_id=None):
    contract = current_contract(db, incident_id, cluster_id)
    if contract is None:
        return dict(status='NOT_READY', contract=None, reason='Generate a Resolution Contract first.')
    context = read_context(db, incident_id)
    policy = assess(contract, contract, context)
    gate = latest(db, 'safety_evaluations', contract.contract_id)
    simulation = latest(db, 'impact_simulations', contract.contract_id)
    state_digest = policy['input_state_digest']
    gate_current = bool(gate and gate['record_status'] == gate['decision']
                        and gate['contract_hash'] == contract.contract_hash
                        and gate['input_state_digest'] == state_digest
                        and gate['policy_version'] == policy['policy_version'])
    simulation_current = bool(simulation and simulation['record_status'] == simulation['result']
                              and simulation['contract_hash'] == contract.contract_hash
                              and simulation['input_state_digest'] == state_digest
                              and gate_current and simulation['evaluation_id'] == gate['evaluation_id'])
    integrity = policy['rules'][2]['result'] == 'PASS'
    diagnosis_current = all(policy['rules'][i]['result'] == 'PASS' for i in (0, 1))
    status, reason = 'NOT_READY', 'A current Safety Gate approval and passing Impact Sandbox result are required.'
    if not integrity or not diagnosis_current:
        status, reason = 'BLOCKED', 'Contract integrity or current diagnosis check failed.'
    elif current_approval(db, contract):
        status, reason = READY, 'Current synthetic reviewer approval supplies A2 authority.'
    elif gate_current and gate['decision'] in ('BLOCKED', 'HUMAN_REVIEW_REQUIRED'):
        status, reason = gate['decision'], 'See the Safety Gate rule outcomes.'
    elif not sandbox_eligible(contract, gate, policy):
        if gate:
            reason = 'Current state or policy differs from the evaluated snapshot. Reassess safety.'
    elif simulation_current and simulation['result'] == 'FAIL':
        status, reason = 'BLOCKED', simulation['reason']
    elif simulation_current and simulation['result'] == 'PASS' and not simulation['demonstration_only']:
        status, reason = READY, 'Contract, policy approval, projection and operational state all match.'
    elif simulation and not simulation_current:
        reason = 'The projection is stale. Reassess safety and simulate the current state.'
    return dict(status=status, reason=reason, contract=contract, safety=gate, simulation=simulation,
                safety_status=gate['decision'] if gate_current else 'STALE' if gate else 'PENDING',
                simulation_status=simulation['result'] if simulation_current else 'STALE' if simulation else 'PENDING',
                integrity=integrity, diagnosis_current=diagnosis_current, input_state_digest=state_digest)


def execution_readiness(incident_id, path=DEFAULT_DB, *, cluster_id=None):
    with connect(path) as db:
        db.execute('BEGIN')
        return read_decision(db, incident_id, cluster_id)


def record_readiness(incident_id, path=DEFAULT_DB, *, cluster_id=None):
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        decision = read_decision(db, incident_id, cluster_id)
        contract = decision['contract']
        if contract:
            for table in ('safety_evaluations', 'impact_simulations', 'execution_readiness'):
                db.execute(f"UPDATE {table} SET status='STALE' WHERE contract_id=? AND "
                           "json_extract(payload,'$.input_state_digest') IS NOT ?",
                           (contract.contract_id, decision['input_state_digest']))
            record_id = identifier('READY', incident_id)
            payload = {key: val for key, val in decision.items() if key not in ('contract', 'safety', 'simulation')}
            payload.update(readiness_id=record_id, determined_at=now(),
                           evaluation_id=(decision['safety'] or {}).get('evaluation_id'),
                           simulation_id=(decision['simulation'] or {}).get('simulation_id'))
            persist(db, 'execution_readiness', record_id, contract, decision['status'], payload)
            audit(db, contract, 'READINESS_DETERMINED', payload)
        return decision




