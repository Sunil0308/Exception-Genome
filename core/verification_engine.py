"""Compare the approved postconditions with persisted operational evidence."""
import json

import networkx as nx

from core.database import DEFAULT_DB, connect
from core.incident_closure import close_verified_incident
from core.operational_memory import record_completed_case
from core.phase4_store import canonical, digest, identifier, now
from core.phase5_store import OUTPUTS, execution, log, operational_state, save, set_incident, verification_digest
from core.resolution_contract import POSTCONDITIONS, contract_hash, current_contract
from core.rollback_engine import rollback
from core.service_graph import build_graph

ACTOR = 'VERIFICATION_ENGINE'


def verify_state(contract, record, state):
    before = record['previous_state_snapshot']
    target = record['target_service']
    incident_id = record['incident_id']
    affected = set(record['affected_services'])
    services = {row['id']: row for row in state['services']}
    baseline = {row['id']: row for row in before['services']}
    current = {row['reference_id']: row for row in state['references']}
    outputs = {row['service_id']: row for row in state['outputs']}
    exceptions = {row['id']: row['status'] for row in state['exceptions'] if row['incident_id'] == incident_id and row['service_id'] in affected}
    expected_ids = {row['id'] for row in before['exceptions'] if row['incident_id'] == incident_id and row['service_id'] in affected}
    states = {key: services.get(key, {}).get('status') for key in sorted(affected)}
    checks = []

    def check(number, name, expected, actual, *, known=True):
        result = 'INCONCLUSIVE' if not known else 'PASS' if expected == actual else 'FAIL'
        checks.append(dict(verification_rule_id=f'V-{number:03d}', name=name, expected=expected,
                           actual=actual, result=result, evidence={'source': 'SYNTHETIC_SQLITE'},
                           failure_reason={'FAIL': 'Observed state differs from expected state.',
                                           'INCONCLUSIVE': 'Required observation is missing.'}.get(result, '')))

    if record['action_type'] == 'RESTART_SINGLE_SERVICE':
        state_output = outputs.get(target, {}).get('current_state')
        graph = build_graph(state['services'])
        dependencies = {node: graph.nodes[node].get('status') for child in affected for node in graph.predecessors(child)}
        checks_to_run = (
            ('Affected services recovered', dict.fromkeys(affected, 'HEALTHY'), states),
            ('Service recovered', 'HEALTHY', states.get(target)),
            ('Operational output', OUTPUTS[target][1], state_output),
            ('Incident exception resolved', {'RESOLVED'}, set(exceptions.values())),
            ('Exception ownership', expected_ids, set(exceptions)),
            ('Other service states unchanged', True, all(services.get(k) == v for k, v in baseline.items() if k not in affected)),
            ('Required dependencies healthy', dict.fromkeys(dependencies, 'HEALTHY'), dependencies),
            ('Reference configuration unchanged', before['references'], state['references']),
            ('Diagnosis unchanged', before['analysis'], state['analysis']),
            ('Approved scope', [target], contract.authority_scope.get('targets') if contract else None),
            ('Current contract', record['contract_hash'], contract_hash(contract) if contract else None),
            ('Snapshot integrity', record['state_digest_before'], digest(before)),
            ('Synthetic restart authorised', True, bool(record.get('review_decision_id'))),
            ('Affected service topology unchanged', {k: baseline[k]['dependencies'] for k in affected},
             {k: services[k]['dependencies'] for k in affected}),
            ('Service population unchanged', set(baseline), set(services)),
        )
        for number, (name, expected, actual) in enumerate(checks_to_run, 1):
            check(number, name, sorted(expected) if isinstance(expected, set) else expected,
                  sorted(actual) if isinstance(actual, set) else actual, known=actual is not None)
        return checks

    new = record['action_parameters']['credential_version']
    prior_active = [row['reference_id'] for row in before['references']
                    if row['service_id'] == target and row['active'] == 1]
    replacement = current.get(new, {})
    previous = current.get(prior_active[0], {}) if len(prior_active) == 1 else {}
    check(1, f'{new} approved, valid and active', [1, 1, 'VALID'],
          [replacement.get(key) for key in ('active', 'approved', 'status')], known=bool(replacement))
    check(2, 'Previous reference inactive', 0, previous.get('active'), known=bool(previous))
    auth = outputs.get(target, {}).get('current_state')
    check(3, 'DataHub authentication', 'VALID', auth, known=auth is not None)
    check(4, 'DataHub health', 'HEALTHY', states.get(target), known=states.get(target) is not None)
    check(5, 'Affected service health', {key: 'HEALTHY' for key in states}, states,
          known=bool(states) and all(states.values()))
    new_failures = sorted(key for key, row in services.items() if row['status'] == 'FAILED'
                          and baseline.get(key, {}).get('status') != 'FAILED')
    check(6, 'Additional service failures', [], new_failures, known=baseline.keys() == services.keys())
    try:
        graph = build_graph(state['services'])
        graph_known = set(graph) == set(services) and affected <= set(graph)
        ancestors = set().union(*(nx.ancestors(graph, node) for node in affected)) if graph_known else set()
        blocked = sorted(node for node in ancestors if services[node]['status'] != 'HEALTHY')
        downstream = nx.descendants(graph, target) if graph_known and target in graph else set()
    except (ValueError, TypeError):
        graph_known, blocked, downstream = False, [], set()
    check(7, 'Required dependency connectivity', [], blocked, known=graph_known)
    check(8, 'Incident exceptions cleared', {key: 'RESOLVED' for key in sorted(expected_ids)}, exceptions,
          known=bool(expected_ids) and expected_ids <= exceptions.keys())
    for number, service in enumerate(('revenue', 'daily_recon', 'merchant', 'statement', 'finance'), 9):
        name, expected = OUTPUTS[service]
        observed = outputs.get(service, {}).get('current_state')
        check(number, name, expected, observed, known=observed is not None)
    downstream_issues = sorted(
        {node for node in downstream if services[node]['status'] != 'HEALTHY'}
        | {row['service_id'] for row in state['exceptions']
           if row['service_id'] in downstream and row['status'] != 'RESOLVED'})
    check(14, 'Downstream dependencies unresolved', [], downstream_issues, known=graph_known)
    expected_refs = {row['reference_id']: (dict(row, active=int(row['reference_id'] == new))
                                           if row['service_id'] == target else row) for row in before['references']}
    scope_checks = {
        'contract': bool(contract and contract.status == 'CURRENT' and contract.contract_id == record['contract_id']
                         and contract_hash(contract) == contract.contract_hash == record['contract_hash']
                         and contract.authority_scope.get('targets') == [target]
                         and tuple(contract.expected_postconditions) == POSTCONDITIONS
                         and contract.action_parameters == record['action_parameters']),
        'reference_configuration': expected_refs == current,
        'topology': baseline.keys() == services.keys() and all(
            row['dependencies'] == services[key]['dependencies'] for key, row in baseline.items()),
        'unaffected_services': all(services.get(key) == row for key, row in baseline.items() if key not in affected),
        'analysis_evidence': state['analysis'] == before['analysis'],
        'snapshot_integrity': digest(before) == record['state_digest_before'],
        'incident_membership': affected == {row['service_id'] for row in before['exceptions']
                                            if row['incident_id'] == incident_id and row['service_id'] in affected},
    }
    check(15, 'Approved operational scope', dict.fromkeys(scope_checks, True), scope_checks)
    return checks


def run_verification(incident_id, path=DEFAULT_DB, *, cluster_id=None):
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        record = execution(db, incident_id, cluster_id)
        if not record:
            raise ValueError('Controlled recovery has not started')
        existing = read_verification(db, record['execution_id'])
        if existing:
            return existing
        if record['status'] != 'AWAITING_VERIFICATION':
            raise ValueError('Independent verification requires completed recovery stages')
        state = operational_state(db, incident_id)
        state_hash = verification_digest(state)
        log(db, record, ACTOR, 'VERIFICATION_STARTED', state_digest=state_hash)
        checks = verify_state(current_contract(db, incident_id, record.get('cluster_id')), record, state)
        outcomes = {row['result'] for row in checks}
        status = 'FAILED' if 'FAIL' in outcomes else 'INCONCLUSIVE' if 'INCONCLUSIVE' in outcomes else 'VERIFIED'
        result = dict(verification_id=identifier('VER', incident_id), execution_id=record['execution_id'],
                      incident_id=incident_id, contract_hash=record['contract_hash'], status=status,
                      state_digest=state_hash, checks=checks, completed_at=now(),
                      affected_count=len(record['affected_services']),
                      recovered_count=sum(row['status'] == 'RESOLVED' for row in state['exceptions']
                                          if row['incident_id'] == incident_id and row['service_id'] in record['affected_services']))
        verification_id = result['verification_id']
        db.execute('INSERT INTO verification_results VALUES (?,?,?,?,?)',
                   (verification_id, record['execution_id'], status, state_hash, canonical(result)))
        for check in checks:
            db.execute('INSERT INTO verification_checks VALUES (?,?,?,?)',
                       (verification_id, check['verification_rule_id'], check['result'], canonical(check)))
            action = {'PASS': 'VERIFICATION_RULE_PASSED', 'FAIL': 'VERIFICATION_RULE_FAILED',
                      'INCONCLUSIVE': 'VERIFICATION_RULE_INCONCLUSIVE'}[check['result']]
            log(db, record, ACTOR, action, result=check['result'], evidence=check, state_digest=state_hash)
        log(db, record, ACTOR, 'VERIFICATION_COMPLETED', decision=status, state_digest=state_hash)
        record.update(status='COMPLETED', state_digest_after=digest(state))
        save(db, record)
        if status == 'VERIFIED':
            if not close_verified_incident(db, record, result):
                raise ValueError('Verification artifact failed the closure guard')
        elif record.get('multi_assignment'):
            record.update(status='ESCALATED', failure_reason=f'VERIFICATION_{status}')
            save(db, record)
            log(db, record, 'SYSTEM', 'HUMAN_REVIEW_REQUIRED', decision='HUMAN_REVIEW_REQUIRED')
        else:
            set_incident(db, incident_id, 'VERIFICATION_FAILED')
            record.update(rollback_required=True, failure_reason=f'VERIFICATION_{status}')
            save(db, record)
            rollback(db, record)
        record_completed_case(db, record, result)
        return result


def read_verification(db, execution_id):
    row = db.execute('SELECT payload FROM verification_results WHERE execution_id=?', (execution_id,)).fetchone()
    return json.loads(row[0]) if row else None






