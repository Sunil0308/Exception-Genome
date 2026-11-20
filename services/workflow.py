"""Application entry points shared by the local interfaces."""
import json

from core.analysis import analyse, load, ready
from core.audit import timeline
from core.database import DEFAULT_DB, connect, reset, snapshot
from core.execution_engine import execute_controlled
from core.execution_readiness import read_decision, record_readiness
from core.impact_simulator import review_simulation_eligible, run_impact_simulation
from core.operational_memory import history, patterns
from core.phase4_store import latest
from core.prevention_engine import recommendations
from core.recovery_engine import advance_recovery
from core.resolution_contract import create_contract, current_contract, read_context
from core.review import append_diagnostic_record, cases, decide, technical_review
from core.safety_gate import assess, evaluate_safety_gate
from core.verification_engine import run_verification
from simulator.incident_scenarios import SCENARIOS, advance, get_scenario, start


class Conflict(ValueError):
    pass


def incident(incident_id, path=DEFAULT_DB):
    row = next((r for r in snapshot(path)['incidents'] if r['id'] == incident_id), None)
    if row is None:
        raise KeyError(incident_id)
    return row


def assignment(incident_id, assignment_id, path=DEFAULT_DB):
    incident(incident_id, path)
    data = load(path, incident_id)
    row = next((r for r in data['correlation_clusters'] if r['id'] == assignment_id), None)
    if row is None:
        raise KeyError(assignment_id)
    root = next((r for r in data['root_cause_analyses'] if r['cluster_id'] == assignment_id), None)
    with connect(path) as db:
        from core.phase5_store import execution
        run = execution(db, incident_id, assignment_id)
        contracts = [dict(item) for item in db.execute(
            'SELECT id,version,contract_hash,status FROM resolution_contracts WHERE cluster_id=? ORDER BY version',
            (assignment_id,))]
    return dict(assignment_id=assignment_id, incident_id=incident_id, cluster=row, diagnosis=root,
                execution_id=run['execution_id'] if run else None, contract_history=contracts)


def start_scenario(scenario_id, path=DEFAULT_DB):
    scenario = next((s for s in SCENARIOS.values() if s.scenario_id == scenario_id), None)
    scenario = scenario or get_scenario(scenario_id)
    if scenario is None:
        raise KeyError(scenario_id)
    start(path, scenario)
    return incident(scenario.incident_id, path)


def advance_scenario(incident_id, path=DEFAULT_DB):
    incident(incident_id, path)
    scenario = get_scenario(incident_id)
    return dict(advanced=advance(path, scenario), incident=incident(incident_id, path))


def execution_record(execution_id, path=DEFAULT_DB):
    with connect(path) as db:
        row = db.execute('SELECT payload FROM executions WHERE id=?', (execution_id,)).fetchone()
    if not row:
        raise KeyError(execution_id)
    return json.loads(row[0])


def workflow_status(incident_id, path=DEFAULT_DB):
    state = snapshot(path)
    row = incident(incident_id, path)
    response = dict(incident_id=incident_id, status=row['status'], assignments=[], next_actions=[])
    if row['status'] == 'ACTIVE':
        response['next_actions'] = ['ANALYSE'] if ready(state, incident_id) else ['ADVANCE_SCENARIO']
    with connect(path) as db:
        data = load(path, incident_id)
        for cluster in data['correlation_clusters']:
            cluster_id = cluster['id']
            contract = current_contract(db, incident_id, cluster_id)
            diagnostic = next(r for r in data['root_cause_analyses'] if r['cluster_id'] == cluster_id)
            stage, actions = 'DIAGNOSED', []
            from core.phase5_store import execution
            run = execution(db, incident_id, cluster_id)
            if row['status'] == 'DIAGNOSED' and run:
                stage = 'RESOLVED' if run['status'] == 'COMPLETED' else run['status']
                actions = {'RECOVERING': ['ADVANCE_RECOVERY'], 'AWAITING_VERIFICATION': ['VERIFY'],
                           'ESCALATED': ['REVIEW'], 'FAILED': ['REVIEW']}.get(stage, [])
            elif row['status'] == 'DIAGNOSED':
                if diagnostic.get('diagnosis_outcome') == 'NO_CONFIDENT_ROOT_CAUSE':
                    actions = ['REQUEST_EVIDENCE']
                elif not contract or contract.status != 'CURRENT':
                    actions = ['GENERATE_CONTRACT']
                else:
                    decision = read_decision(db, incident_id, cluster_id)
                    stage = decision['status']
                    context = read_context(db, incident_id)
                    gate = decision['safety']
                    if stage == 'READY_FOR_CONTROLLED_EXECUTION':
                        actions = ['EXECUTE']
                    elif not gate or decision['safety_status'] == 'STALE':
                        actions = ['EVALUATE_SAFETY']
                    elif decision['safety_status'] == 'APPROVED' and decision['simulation_status'] in ('PENDING', 'STALE'):
                        actions = ['SIMULATE_IMPACT']
                    elif review_simulation_eligible(gate, assess(contract, contract, context)):
                        actions = ['REVIEW'] if technical_review(db, contract) else ['SIMULATE_IMPACT']
                    else:
                        actions = ['REVIEW']
            else:
                stage = row['status']
                actions = {'RECOVERING': ['ADVANCE_RECOVERY'], 'AWAITING_VERIFICATION': ['VERIFY'],
                           'HUMAN_REVIEW_REQUIRED': ['REVIEW']}.get(stage, [])
            response['assignments'].append(dict(assignment_id=cluster_id, status=stage, next_actions=actions,
                                                contract_hash=contract.contract_hash if contract else None,
                                                next_allowed_actions=actions))
    response['next_allowed_actions'] = sorted(set(response['next_actions']).union(
        action for row in response['assignments'] for action in row['next_actions']))
    response['current_stage'] = response['status']
    return response


def check_expectations(incident_id, assignment_id, expected_hash, expected_digest, path=DEFAULT_DB):
    from core.phase4_store import digest
    with connect(path) as db:
        contract = current_contract(db, incident_id, assignment_id)
        if expected_hash and (not contract or contract.status != 'CURRENT' or contract.contract_hash != expected_hash):
            raise Conflict('CONTRACT_STALE')
        if expected_digest and expected_digest != digest(read_context(db, incident_id)):
            raise Conflict('STATE_CHANGED')



from core.evidence_intake import demo_dependency_probe, evidence_records


def inject_probe(incident_id, assignment_id, path=DEFAULT_DB):
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        return demo_dependency_probe(db, incident_id, assignment_id)



