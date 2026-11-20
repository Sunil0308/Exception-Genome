"""Isolated projection of operational impact. No operational writes."""
from copy import deepcopy

import networkx as nx

from core.action_registry import ACTIVATE, RESTART
from core.database import DEFAULT_DB, connect
from core.exception_genome import normalize
from core.phase4_store import audit, digest, identifier, latest, now, persist
from core.resolution_contract import contract_hash, current_contract, read_context
from core.safety_gate import assess
from core.service_graph import build_graph


def sandbox_eligible(contract, evaluation, assessment):
    return bool(evaluation and evaluation['record_status'] == evaluation['decision']
                and evaluation['contract_hash'] == contract.contract_hash
                and evaluation['input_state_digest'] == assessment['input_state_digest']
                and evaluation['policy_version'] == assessment['policy_version']
                and evaluation['decision'] == assessment['decision'] == 'APPROVED')


def unsafe_demo_contract(contract):
    return (contract.action_type == RESTART and contract.target_service == 'auth'
            and contract.proposed_action == 'Aggressive shared authentication restart'
            and contract.action_parameters == {} and contract_hash(contract) == contract.contract_hash)


def project(contract, context, violations=()):
    sandbox = deepcopy(context)
    services = {row['id']: row for row in sandbox['services']}
    before = {key: row['status'] for key, row in services.items()}
    active_rows = [row for row in sandbox['exceptions'] if row['status'] == 'ACTIVE']
    members = set(contract.evidence_snapshot['genome_signatures'])
    affected = {row['service_id'] for row in active_rows if row['id'] in members}
    independent = {row['service_id'] for row in active_rows if row['id'] not in members}
    policy_violations = list(violations)
    root_id, target = contract.root_cause_service, contract.target_service
    result, reason = 'INCONCLUSIVE', 'Required services, incident evidence or action model unavailable.'
    try:
        graph = build_graph(sandbox['services'])
    except (ValueError, TypeError):
        graph = None
    if (graph is not None and set(graph) == set(services) and affected <= set(services)
            and root_id in affected and target in services
            and all(status in {'HEALTHY', 'DEGRADED', 'FAILED'} for status in before.values())):
        recovered_root = False
        causal_data_errors = {'UPSTREAM_DATA_UNAVAILABLE', 'DEPENDENCY_FAILURE',
                              'MISSING_SOURCE_DATA', 'PROCESSING_BLOCKED'}
        downstream_symptoms = {row['service_id'] for row in active_rows
                               if row['incident_id'] == contract.incident_id
                               and row['authentication_context'] == 'UPSTREAM_AUTH_FAILURE'
                               and normalize(row) in causal_data_errors}
        if contract.action_type == ACTIVATE and target == root_id:
            refs = sandbox['references']
            old = next((r for r in refs if r['service_id'] == target and r['active'] == 1), {})
            replacement = next((r for r in refs if r['service_id'] == target
                                and r['reference_id'] == contract.action_parameters.get('credential_version')), {})
            if (old.get('status') == 'EXPIRED' and replacement.get('status') == 'VALID'
                    and replacement.get('approved') == 1 and replacement.get('active') == 0
                    and all(before[parent] == 'HEALTHY' for parent in graph.predecessors(target))
                    and target not in independent):
                old['active'], replacement['active'] = 0, 1
                services[target]['authentication_condition'] = 'VALID'
                services[target]['status'] = 'HEALTHY'
                recovered_root = True
        elif (contract.action_type == RESTART and target == root_id and target in ('merchant', 'scheduler', 'event_bus')
              and target in affected and affected <= (nx.descendants(graph, target) | {target})
              and target not in independent and all(before[parent] == 'HEALTHY' for parent in graph.predecessors(target))):
            services[target]['status'] = 'HEALTHY'
            recovered_root = True
        elif unsafe_demo_contract(contract):
            services[target]['status'] = 'FAILED'
        for service in nx.topological_sort(graph):
            if service == target:
                continue
            dependencies_satisfied = all(services[parent]['status'] == 'HEALTHY'
                                         for parent in graph.predecessors(service))
            if not dependencies_satisfied and before[service] == 'HEALTHY' and (
                    contract.action_type != RESTART or unsafe_demo_contract(contract)):
                services[service]['status'] = 'DEGRADED'
            elif (dependencies_satisfied and recovered_root and (service in downstream_symptoms or (contract.action_type == RESTART and service in affected))
                  and service not in independent and nx.has_path(graph, target, service)):
                services[service]['status'] = 'HEALTHY'
        if recovered_root or contract.action_type == ACTIVATE or unsafe_demo_contract(contract):
            result, reason = 'FAIL', 'The projection leaves unresolved services or introduces dependency or policy impact.'

    after = {key: row['status'] for key, row in services.items()}
    recoveries = sorted(service for service in affected if service in after and after[service] == 'HEALTHY'
                        and before[service] != 'HEALTHY')
    unresolved = sorted(affected - set(recoveries))
    new_failures = sorted(service for service in before
                          if before[service] != 'FAILED' and after[service] == 'FAILED')
    unexpected = sorted(service for service in before if service not in affected and before[service] != after[service])
    if result == 'FAIL' and root_id in recoveries and not any((unresolved, new_failures, unexpected, policy_violations)):
        result, reason = 'PASS', 'All affected services are eligible for projected recovery.'
    return dict(
        contract_id=contract.contract_id, contract_hash=contract.contract_hash,
        input_state_digest=digest(context), output_state_digest=digest(sandbox),
        action=contract.action_type, target=target, projected_recoveries=recoveries,
        projected_unresolved=unresolved, new_failures=new_failures, policy_violations=policy_violations,
        unexpected_impacts=unexpected, root_cause_resolved=root_id in recoveries,
        projected_service_states={key: {'before': status, 'projected': after[key]} for key, status in before.items()},
        result=result, reason=reason,
    )


def review_simulation_eligible(evaluation, assessment):
    return bool(evaluation and evaluation['record_status'] == 'HUMAN_REVIEW_REQUIRED'
                and evaluation['decision'] == assessment['decision'] == 'HUMAN_REVIEW_REQUIRED'
                and evaluation['contract_hash'] == assessment['contract_hash']
                and evaluation['input_state_digest'] == assessment['input_state_digest']
                and evaluation['policy_version'] == assessment['policy_version']
                and [r['rule_id'] for r in assessment['rules'] if r['result'] == 'FAIL'] == ['SG-009'])

def run_impact_simulation(incident_id, path=DEFAULT_DB, *, unsafe_demo=False, cluster_id=None):
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        contract = current_contract(db, incident_id, cluster_id)
        if contract is None:
            raise ValueError('Generate a Resolution Contract first.')
        context = read_context(db, incident_id)
        assessment = assess(contract, contract, context)
        evaluation = latest(db, 'safety_evaluations', contract.contract_id)
        demo_allowed = (unsafe_demo and unsafe_demo_contract(contract) and evaluation
                        and evaluation['decision'] == assessment['decision'] == 'BLOCKED'
                        and evaluation['contract_hash'] == contract.contract_hash
                        and evaluation['input_state_digest'] == assessment['input_state_digest'])
        review_allowed = contract.action_type == RESTART and review_simulation_eligible(evaluation, assessment)
        if not (demo_allowed or review_allowed or sandbox_eligible(contract, evaluation, assessment)):
            raise ValueError('A current Safety Gate decision is required for this simulation.')
        simulation_id = identifier('SIM', incident_id)
        started_at = now()
        audit(db, contract, 'IMPACT_SIMULATION_STARTED', {'simulation_id': simulation_id})
        failures = [row['rule_id'] for row in assessment['rules'] if row['result'] == 'FAIL' and not (review_allowed and row['rule_id'] == 'SG-009')]
        output = project(contract, context, failures)
        output.update(simulation_id=simulation_id, started_at=started_at, completed_at=now(),
                      evaluation_id=evaluation['evaluation_id'], demonstration_only=bool(demo_allowed))
        persist(db, 'impact_simulations', simulation_id, contract, output['result'], output)
        audit(db, contract, 'IMPACT_SIMULATION_COMPLETED', {'simulation_id': simulation_id, 'result': output['result']})
        return output





