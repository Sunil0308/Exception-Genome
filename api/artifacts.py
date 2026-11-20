"""Public schemas for simulator evidence and decision artifacts."""
from typing import Any

from pydantic import BaseModel, ConfigDict


class Artifact(BaseModel):
    model_config = ConfigDict(extra='allow')


class AssignmentSummary(Artifact):
    assignment_id: str
    incident_id: str
    cluster: dict[str, Any]
    diagnosis: dict[str, Any] | None
    execution_id: str | None = None


class ExceptionSummary(BaseModel):
    id: str
    incident_id: str
    service_id: str
    status: str
    error_code: str
    error_message: str
    error_category: str
    severity: str
    timestamp: str
    authentication_context: str


class ResolutionContractResponse(Artifact):
    contract_id: str
    cluster_id: str
    contract_hash: str
    status: str
    action_type: str


class SafetyEvaluationResponse(Artifact):
    evaluation_id: str
    contract_id: str
    contract_hash: str
    overall_result: str
    rules: list[dict[str, Any]]


class ImpactSimulationResponse(Artifact):
    simulation_id: str
    contract_hash: str
    result: str
    input_state_digest: str
    readiness: str


class ExecutionResponse(Artifact):
    execution_id: str
    incident_id: str
    contract_hash: str
    status: str


class VerificationResponse(Artifact):
    verification_id: str
    execution_id: str
    status: str
    checks: list[dict[str, Any]]

