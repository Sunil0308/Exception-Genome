"""Explicit policy for synthetic actions understood by the planner."""
from dataclasses import dataclass


ACTIVATE = 'ACTIVATE_APPROVED_CREDENTIAL_REFERENCE'
RESTART = 'RESTART_SINGLE_SERVICE'
ROTATE = 'ROTATE_OR_CREATE_CREDENTIAL'


@dataclass(frozen=True)
class ActionDefinition:
    action_type: str
    name: str
    description: str
    permitted_target_types: tuple
    autonomy_class: str
    reversibility: bool
    maximum_allowed_scope: int
    requires_simulation: bool
    required_evidence: tuple
    allowed_parameters: tuple
    forbidden_parameters: tuple
    rollback_action: str
    default_risk: str
    autonomous_execution_permitted: bool


AUTONOMY_CLASSES = {
    'A0': 'Advisory only', 'A1': 'Controlled / Reversible',
    'A2': 'Conditional', 'A3': 'Prohibited autonomously',
}
SECRET_FIELDS = ('password', 'secret', 'credential_value', 'token')
ACTION_REGISTRY = {
    action.action_type: action for action in (
        ActionDefinition(ACTIVATE, 'Activate approved reference',
                         'Select an existing approved synthetic configuration identifier.',
                         ('SERVICE',), 'A1', True, 1, True,
                         ('credential_expiry', 'failed_change', 'approved_replacement'),
                         ('credential_version',), SECRET_FIELDS, 'RESTORE_PREVIOUS_REFERENCE', 'MODERATE', True),
        ActionDefinition(RESTART, 'Restart single service', 'Temporarily interrupt one service.',
                         ('SERVICE',), 'A2', False, 1, True, ('restart_authorization',),
                         (), SECRET_FIELDS, 'ESCALATE_SERVICE_INTERRUPTION', 'HIGH', False),
        ActionDefinition('RETRY_FAILED_JOB', 'Retry failed job', 'Request a retry of an identified job.',
                         ('JOB',), 'A2', False, 1, True, ('job_idempotency',),
                         ('job_id',), SECRET_FIELDS, 'ESCALATE_JOB_FAILURE', 'MODERATE', False),
        ActionDefinition('NO_ACTION', 'No action', 'Record an advisory proposal.',
                         (), 'A0', False, 0, False, (), (), SECRET_FIELDS, '', 'NONE', False),
        ActionDefinition('ESCALATE', 'Escalate', 'Request human review.',
                         (), 'A0', False, 0, False, (), (), SECRET_FIELDS, '', 'NONE', False),
        ActionDefinition(ROTATE, 'Rotate or create credential', 'Credential creation and rotation are prohibited.',
                         ('SERVICE',), 'A3', False, 0, False, (), (), SECRET_FIELDS, '', 'HIGH', False),
    )
}

