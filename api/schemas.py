from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class StateRequest(BaseModel):
    expected_contract_hash: str | None = Field(default=None, min_length=64, max_length=64)
    expected_state_digest: str | None = Field(default=None, min_length=64, max_length=64)


class ExecutionRequest(StateRequest):
    mode: Literal['NORMAL', 'SYNTHETIC_VERIFICATION_FAILURE'] = 'NORMAL'


class ReviewRequest(StateRequest):
    reviewer_identity: Literal['Operations Reviewer', 'Senior Operations Reviewer', 'Risk Reviewer']
    decision: Literal['APPROVE CONTROLLED ACTION', 'REJECT ACTION', 'REQUEST MORE EVIDENCE',
                      'ESCALATE', 'CLOSE AS NO ACTION REQUIRED']
    reason: str = Field(min_length=1, max_length=1000)

    @model_validator(mode='before')
    @classmethod
    def normalize_reviewer(cls, values):
        if isinstance(values, dict) and 'reviewer_identity' not in values and 'reviewer_role' in values:
            return dict(values, reviewer_identity=values['reviewer_role'])
        return values

    @field_validator('decision', mode='before')
    @classmethod
    def normalize_decision(cls, value):
        return value.replace('_', ' ') if isinstance(value, str) else value


class HealthResponse(BaseModel):
    application: str
    demo_mode: bool
    status: str
    database_status: str
    version: str
    mode: str


class IncidentSummary(BaseModel):
    id: str
    title: str
    status: str
    started_at: str
    simulation_step: int
    resolved_at: str | None = None


class WorkflowAssignment(BaseModel):
    assignment_id: str
    status: str
    next_actions: list[str]
    next_allowed_actions: list[str]
    contract_hash: str | None = None


class WorkflowResponse(BaseModel):
    current_stage: str
    incident_id: str
    status: str
    assignments: list[WorkflowAssignment]
    next_actions: list[str]
    next_allowed_actions: list[str]




