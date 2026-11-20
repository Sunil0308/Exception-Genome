"""Deterministic policy evaluation using the persisted diagnosis and observed state."""
from dataclasses import asdict
from math import isfinite

from core.action_registry import ACTION_REGISTRY, ACTIVATE, RESTART
from core.database import DEFAULT_DB, connect
from core.exception_genome import decode
from core.phase4_store import audit, digest, identifier, now, persist
from core.resolution_contract import (
    POSTCONDITIONS, PRECONDITIONS, contract_hash, current_contract, evidence_for, read_context,
)

ROOT_THRESHOLD = 90
CORRELATION_THRESHOLD = 90
POLICY_VERSION = 1


def score_exceeds(value, threshold):
    return type(value) in (float, int) and isfinite(value) and threshold < value <= 100


def assess(contract, current, context):
    evidence = evidence_for(context, contract.cluster_id)
    incident, diagnosis = context['incident'], evidence['diagnosis']
    observed_snapshot = dict(contract.evidence_snapshot)
    observed_snapshot.pop('snapshot_at', None)
    same_evidence = observed_snapshot == evidence
    action = ACTION_REGISTRY.get(contract.action_type)
    target = contract.target_service
    active = next((r for r in context['references'] if r['service_id'] == target and r['active'] == 1), {})
    replacement = next((r for r in context['references'] if r['service_id'] == target
                        and r['reference_id'] == contract.action_parameters.get('credential_version')), {})
    activation = contract.action_type == ACTIVATE
    ranking = diagnosis.get('candidate_ranking') or []
    source = evidence['source_exception']
    change = evidence['change_event']
    local_restart = contract.action_type == RESTART and target in ('merchant', 'scheduler', 'event_bus')
    restart_evidence = (
        source.get('status') == 'ACTIVE' and evidence['root_service_state'].get('status') == 'FAILED'
        and diagnosis.get('diagnosis_outcome') == 'ROOT_CAUSE_CANDIDATE'
        and contract.autonomy_class == 'A2' and action.default_risk == contract.risk_class
        and (
            (target == 'merchant' and evidence['affected_service_count'] == 1
             and source.get('error_code') == 'MS-JOB-502' and not change)
            or (target in ('scheduler', 'event_bus') and evidence['affected_service_count'] > 1
                and change.get('type') == 'COMPONENT_FAILURE' and change.get('service_id') == target)
        )
    ) if local_restart else False
    rules = []

    def rule(number, name, description, condition, observed, *, applicable=True, severity='BLOCKING'):
        rules.append(dict(rule_id=f'SG-{number:03d}', name=name, description=description, severity=severity,
                          result=('NOT_APPLICABLE' if not applicable else 'PASS' if condition else 'FAIL'),
                          evidence=observed, failure_reason=description if applicable and not condition else ''))

    rule(1, 'Diagnosis exists', 'A traceable diagnosis with a unique strongest candidate is required.',
         bool(diagnosis.get('analysis_id') and ranking and ranking[0].get('service_id') == diagnosis.get('root_cause_service_id')
              and (len(ranking) == 1 or (score_exceeds(ranking[0].get('score'), 0) and score_exceeds(ranking[1].get('score'), -1)
                  and ranking[0]['score'] > ranking[1]['score']))), ranking[:2])
    rule(2, 'Diagnosis and contract current', 'The current contract must match the incident diagnosis and frozen evidence.',
         bool(current and current.status == 'CURRENT' and current.contract_id == contract.contract_id
              and current.contract_version == contract.contract_version
              and current.contract_hash == contract.contract_hash and same_evidence
              and diagnosis.get('analysis_id') == contract.analysis_id
              and diagnosis.get('root_cause') == contract.root_cause
              and diagnosis.get('root_cause_service_id') == contract.root_cause_service),
         {'analysis_id': diagnosis.get('analysis_id'), 'evidence_current': same_evidence,
          'current_version': current.contract_version if current else None})
    try:
        valid_hash = contract_hash(contract) == contract.contract_hash
    except (TypeError, ValueError):
        valid_hash = False
    rule(3, 'Contract integrity', 'The SHA-256 digest must match the contract content.', valid_hash, contract.contract_hash)
    score = diagnosis.get('confidence')
    root_score = round(score * 100, 6) if type(score) in (int, float) else None
    rule(4, 'Root evidence above threshold', f'A root-cause evidence score above {ROOT_THRESHOLD} is required.',
         score_exceeds(root_score, 75 if local_restart else ROOT_THRESHOLD) and contract.root_cause_evidence_score == root_score, root_score)
    correlation = evidence['correlation_score']
    rule(5, 'Correlation above threshold', f'A verified correlation score above {CORRELATION_THRESHOLD} is required.',
         score_exceeds(correlation, CORRELATION_THRESHOLD) and contract.correlation_score == correlation, correlation, applicable=not local_restart)
    rule(6, 'Contradiction check', 'Conflict evidence must be available and contain no material contradictions.',
         evidence['conflicting_evidence'] == [], evidence['conflicting_evidence'])
    rule(7, 'Verified target', 'Action target must match the verified root-cause service.',
         bool(target and target == diagnosis.get('root_cause_service_id')), {'proposed': target, 'verified': diagnosis.get('root_cause_service_id')})
    rule(8, 'Registered action', 'Action type must exist in the registry.', action is not None, contract.action_type)
    advisory = contract.action_type in ('ESCALATE', 'NO_ACTION')
    rule(9, 'Controlled autonomy', 'Action is prohibited from autonomous execution or its policy classification does not match.',
         bool(action and action.autonomous_execution_permitted and action.reversibility and action.requires_simulation
              and action.autonomy_class == contract.autonomy_class and action.default_risk == contract.risk_class),
         asdict(action) if action else None, severity='REVIEW' if advisory or restart_evidence else 'BLOCKING')
    params = contract.action_parameters
    rule(10, 'Parameter allowlist', 'Parameters must match the action allowlist and contain only synthetic identifiers.',
         bool(action and set(params) == set(action.allowed_parameters)
              and not set(params).intersection(action.forbidden_parameters)
              and all(isinstance(value, str) and value for value in params.values())),
         {'parameter_names': sorted(params), 'allowed': action.allowed_parameters if action else ()})
    rule(11, 'Replacement approved', 'An approved replacement reference must exist for the declared service.',
         replacement.get('approved') == 1 and replacement.get('active') == 0, replacement, applicable=activation)
    rule(12, 'Replacement valid', 'Replacement reference status must be VALID.',
         replacement.get('status') == 'VALID', replacement.get('status'), applicable=activation)
    rule(13, 'Active reference expired', 'The active approved reference and failed service must confirm expired authentication.',
         active.get('status') == 'EXPIRED' and active.get('approved') == 1
         and source.get('authentication_context') == 'CREDENTIAL_EXPIRED'
         and evidence['root_service_state'].get('status') == 'FAILED',
         {'active_reference': active, 'authentication_context': source.get('authentication_context'),
          'service_status': evidence['root_service_state'].get('status')}, applicable=activation)
    equivalent = replacement.get('active') == 1
    rule(14, 'No equivalent remediation', 'An equivalent remediation is active or its current state is unknown.',
         bool(active and not equivalent), {'active_reference': active.get('reference_id'), 'replacement_active': equivalent},
         applicable=activation)
    scope = contract.authority_scope
    scope_ok = (scope == {'target_type': 'SERVICE', 'targets': [target], 'surface': 'SYNTHETIC_SERVICE_CONFIGURATION'}
                and bool(action and 'SERVICE' in action.permitted_target_types
                         and contract.maximum_blast_radius == 1 <= action.maximum_allowed_scope))
    rule(15, 'Authority scope', 'Action authority must cover only the registered single-service configuration.',
         scope_ok or (advisory and scope == {'targets': []} and contract.maximum_blast_radius == 0),
         scope)
    rollback = contract.rollback_plan
    rule(16, 'Rollback defined', 'Rollback must restore the observed previous reference and require escalation on unexpected behaviour.',
         bool(active and action and rollback == {
             'action': action.rollback_action, 'credential_version': active['reference_id'],
             'target_service': target, 'escalate_on_unexpected_behavior': True}),
         rollback, applicable=activation)
    complete = bool(evidence['genome_signatures'] and all(evidence['genome_signatures'].values())
                    and len(evidence['genome_signatures']) == evidence['affected_service_count']
                    and evidence['alternative_hypotheses'] and contract.evidence_snapshot.get('snapshot_at'))
    credentials_complete = (change.get('type') == 'CREDENTIAL_ROTATION_FAILED'
                            and change.get('service_id') == target and change.get('credential_state') == 'EXPIRED'
                            and source.get('status') == 'ACTIVE' and bool(change.get('timestamp'))
                            and decode(evidence['root_service_state'].get('recent_change'), {}) == change
                            and tuple(contract.required_preconditions) == PRECONDITIONS
                            and tuple(contract.expected_postconditions) == POSTCONDITIONS)
    policy_evidence = {
        'restart_authorization': restart_evidence,
        'credential_expiry': active.get('status') == 'EXPIRED' and source.get('authentication_context') == 'CREDENTIAL_EXPIRED',
        'failed_change': credentials_complete, 'approved_replacement': replacement.get('approved') == 1,
    }
    rule(17, 'Required evidence complete', 'Required structured evidence or action-specific evidence is missing.',
         bool(complete and action and all(policy_evidence.get(key, False) for key in action.required_evidence)),
         {'genome_count': len(evidence['genome_signatures']), 'change_event': change,
          'policy_evidence': policy_evidence, 'required': action.required_evidence if action else ()})
    rule(18, 'Incident unresolved', 'Incident must still be diagnosed with active exceptions.',
         incident.get('id') == contract.incident_id and incident.get('status') == 'DIAGNOSED'
         and any(row['status'] == 'ACTIVE' for row in evidence['incident_exceptions']),
         {'incident_status': incident.get('status'), 'active_exceptions': sum(
             row['status'] == 'ACTIVE' for row in evidence['incident_exceptions'])})
    failures = [row for row in rules if row['result'] == 'FAIL']
    decision = ('BLOCKED' if any(row['severity'] == 'BLOCKING' for row in failures)
                else 'HUMAN_REVIEW_REQUIRED' if failures else 'APPROVED')
    return dict(contract_id=contract.contract_id, contract_hash=contract.contract_hash,
                decision=decision, rules=rules, input_state_digest=digest(context),
                policy_version=POLICY_VERSION)


def evaluate_safety_gate(incident_id, path=DEFAULT_DB, *, cluster_id=None):
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        contract = current_contract(db, incident_id, cluster_id)
        if contract is None:
            raise ValueError('Generate a Resolution Contract first.')
        evaluation = assess(contract, contract, read_context(db, incident_id))
        record_id = identifier('SG', incident_id)
        evaluation.update(evaluation_id=record_id, evaluated_at=now())
        persist(db, 'safety_evaluations', record_id, contract, evaluation['decision'], evaluation)
        audit(db, contract, 'SAFETY_EVALUATION_PERFORMED', {'evaluation_id': record_id, 'decision': evaluation['decision']})
        for rule in evaluation['rules']:
            if rule['result'] == 'FAIL':
                audit(db, contract, 'SAFETY_RULE_BLOCKED', {'evaluation_id': record_id, **rule})
        return evaluation





