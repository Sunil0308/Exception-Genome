Continue the existing OCBC Exception Genome project.

Phases 1 through 6 are complete and working.

DO NOT rebuild the application.

DO NOT remove existing Streamlit functionality.

DO NOT weaken any existing safety, review, simulation, verification, rollback or audit controls.

DO NOT implement n8n yet.

This is the FINAL CODEX PHASE before n8n integration.

PHASE 7

Goals:

1. Complete multi-cluster execution and closure.
2. Make evidence-request workflows genuinely capable of changing diagnosis.
3. Finalise cluster-level lifecycle isolation.
4. Add a FastAPI service layer over the existing engine.
5. Make the Streamlit UI and API use the same underlying business logic.
6. Add API idempotency and state validation.
7. Add integration tests.
8. Produce a stable API contract for n8n.
9. Freeze the Codex product after completion.

The finished architecture will be:

Streamlit
    |
    v
Shared Python Domain Services
    ^
    |
FastAPI
    |
    v
Future n8n Workflow

Streamlit and FastAPI must call the same core logic.

Do NOT duplicate the Exception Genome logic inside the API.


==================================================
PART 1 - FIX MULTI-CLUSTER EXECUTION
==================================================

Phase 6 currently supports analysis and scoped contracts for multi-cluster incidents but blocks execution.

Complete this.

A multi-cluster incident may contain:

Cluster A

Cluster B

Singleton C

Each assignment must have its own independent lifecycle.

Example:

INC-2026-003

Cluster A:
Scheduler-related failures

Cluster B:
Event Bus-related failures

Possible singleton:
unrelated local issue

Each assignment must independently support:

DIAGNOSIS

RESOLUTION CONTRACT

SAFETY GATE

IMPACT SANDBOX

AUTHORITY

EXECUTION

RECOVERY

VERIFICATION

CLOSURE


==================================================
PART 2 - CLUSTER LIFECYCLE MODEL
==================================================

Create a proper persisted lifecycle for an assignment or cluster.

Suggested states:

UNDIAGNOSED

DIAGNOSED

REVIEW_REQUIRED

READY_FOR_EXECUTION

EXECUTING

RECOVERING

AWAITING_VERIFICATION

RESOLVED

FAILED

ROLLED_BACK

ESCALATED

UNRESOLVED

The incident state must be calculated from its assignments.

Do not let one resolved cluster mark the entire incident resolved.


==================================================
PART 3 - INCIDENT AGGREGATION RULES
==================================================

For multi-assignment incidents:

Incident may become RESOLVED only when every required assignment is in a terminal acceptable state.

Acceptable successful terminal state:

RESOLVED

If one cluster is:

HUMAN_REVIEW_REQUIRED

the incident remains unresolved.

If one cluster is:

FAILED

the incident remains unresolved.

If one singleton is unresolved:

the incident remains unresolved.

Calculate incident status from assignment states.

Do not manually hardcode incident status transitions.


==================================================
PART 4 - CLUSTER ISOLATION
==================================================

A contract for Cluster A must never:

- authorise Cluster B
- change Cluster B services
- close Cluster B exceptions
- reuse Cluster B simulation
- reuse Cluster B reviewer approval
- reuse Cluster B verification
- reuse Cluster B execution readiness

All artifacts must bind to:

incident_id

assignment_id or cluster_id

contract_hash

relevant state digest

Test cross-cluster isolation aggressively.


==================================================
PART 5 - MULTI-CLUSTER EXECUTION DEMO
==================================================

Use INC-2026-003.

Preserve the existing two independent branches.

Add safe synthetic remediation models for both branches if necessary.

Example:

Cluster A

Root:
Scheduler

Action:
RESTART_SINGLE_SERVICE or appropriate registered synthetic action

Authority:
A2 human-controlled if required

Cluster B

Root:
Event Bus

Action:
RESTART_SINGLE_SERVICE or another suitable allowlisted synthetic action

Authority:
A2 if appropriate

Do not downgrade risk merely to simplify the demo.

The presenter should be able to:

1. analyse INC-2026-003
2. see two clusters
3. resolve Cluster A
4. observe Cluster B still active
5. resolve Cluster B
6. verify both independently
7. see incident become RESOLVED only after both are verified


==================================================
PART 6 - SINGLETON WITHIN MULTI-INCIDENT
==================================================

Support an incident containing:

one correlated cluster

plus

one singleton exception

The singleton must retain its own lifecycle.

The incident must not close until the singleton has an acceptable terminal outcome.

This demonstrates:

many alerts do not necessarily equal one cluster.


==================================================
PART 7 - REAL EVIDENCE INTAKE
==================================================

Phase 6 request-more-evidence currently appends an inconclusive probe.

Upgrade this.

Create a structured evidence intake mechanism.

Possible evidence types:

SERVICE_HEALTH_RECORD

DEPENDENCY_PROBE

CHANGE_EVENT_RECORD

AUTHENTICATION_DIAGNOSTIC

JOB_HISTORY

OUTPUT_STATE

REFERENCE_STATUS

SIMULATED_OPERATOR_NOTE

Evidence must contain:

evidence_id

incident_id

assignment_id

evidence_type

source

timestamp

structured_payload

reliability

created_by

version


==================================================
PART 8 - EVIDENCE VERSIONING
==================================================

Evidence must be append-only.

Do not overwrite old evidence.

When new evidence arrives:

1. persist it
2. create a new analysis version
3. rerun correlation or diagnosis as required
4. compare old and new diagnosis
5. invalidate stale contracts
6. invalidate stale Safety Gate evaluations
7. invalidate stale simulations
8. invalidate stale reviewer approvals
9. invalidate stale readiness receipts

All invalidation must be traceable in the audit log.


==================================================
PART 9 - AMBIGUOUS SCENARIO RESOLUTION
==================================================

Upgrade INC-2026-004.

Initial state:

two plausible causes

insufficient evidence

NO_CONFIDENT_ROOT_CAUSE

Then allow reviewer to request additional evidence.

Simulate a meaningful new evidence record.

Example:

Dependency probe shows:

Reference Data Service is healthy.

Batch Processing Engine failed before the reporting service.

This should materially change the evidence.

The new analysis should:

reduce confidence in Reference Data Service

increase confidence in Batch Processing Engine

If the resulting score crosses the configured diagnosis threshold:

create a new confident diagnosis version.

Display:

PREVIOUS DIAGNOSIS

AMBIGUOUS

NEW DIAGNOSIS

Batch Processing Engine

Confidence:
calculated value

Do not hardcode the final score.


==================================================
PART 10 - STALE ARTIFACT VISIBILITY
==================================================

When evidence changes:

old contracts

old safety evaluations

old simulations

old review decisions

must remain visible historically but clearly marked:

STALE

or

SUPERSEDED

Do not delete them.

The UI should make it obvious why a previous approval is no longer valid.


==================================================
PART 11 - FINAL DOMAIN SERVICE LAYER
==================================================

Before adding FastAPI, create a thin application/service layer.

Suggested:

services/

incident_service.py

analysis_service.py

resolution_service.py

review_service.py

execution_service.py

memory_service.py

audit_service.py

These services should orchestrate calls into existing core modules.

They must NOT duplicate business rules.

Example:

analysis_service.analyse_incident(incident_id)

should internally use:

core.analysis

core.correlation_engine

core.root_cause_agent

etc.

Streamlit should gradually call these services.

FastAPI must call the same services.


==================================================
PART 12 - FASTAPI
==================================================

Add FastAPI.

Suggested structure:

api/

__init__.py

main.py

schemas.py

dependencies.py

routes/

health.py

incidents.py

analysis.py

resolution.py

reviews.py

execution.py

memory.py

audit.py

Use:

FastAPI

Pydantic

Existing SQLite database

Do not create a second database.


==================================================
PART 13 - API PRINCIPLES
==================================================

The API is an interface to the existing system.

It must NOT contain:

duplicated correlation logic

duplicated Safety Gate rules

duplicated execution logic

duplicated verification logic

duplicated memory logic

Routes call the shared service/domain layer.


==================================================
PART 14 - HEALTH ENDPOINT
==================================================

Create:

GET /health

Return:

status

application

version

database_status

demo_mode

Example:

{
  "status": "ok",
  "application": "Exception Genome",
  "version": "1.0",
  "database_status": "connected",
  "demo_mode": true
}


==================================================
PART 15 - INCIDENT ENDPOINTS
==================================================

Create:

GET /incidents

Return incidents and useful summary state.

GET /incidents/{incident_id}

Return:

incident

assignments

exception counts

status

diagnosis summary

execution state

verification state

GET /incidents/{incident_id}/exceptions

GET /incidents/{incident_id}/assignments


==================================================
PART 16 - DEMO SCENARIO ENDPOINTS
==================================================

Create:

GET /demo/scenarios

Return available synthetic scenarios.

POST /demo/scenarios/{scenario_id}/start

This triggers the existing synthetic simulator.

Do not create new simulation logic inside FastAPI.

Return:

incident_id

scenario

status

started_at

POST /demo/reset/current

POST /demo/reset/full

Clearly keep these endpoints under:

/demo

because they are hackathon-only controls.


==================================================
PART 17 - INCIDENT PROGRESSION ENDPOINT
==================================================

The current Streamlit simulator advances progressively.

Expose a deterministic progression endpoint if necessary:

POST /demo/incidents/{incident_id}/advance

or equivalent service function.

It must advance the same persisted simulator state used by Streamlit.

Do not create a separate API-only simulation.


==================================================
PART 18 - ANALYSIS ENDPOINT
==================================================

Create:

POST /incidents/{incident_id}/analyse

Return:

analysis_version

assignments

clusters

singletons

unassigned

ambiguous assignments

root-cause results

confidence

supporting evidence

contradictory evidence

historical matches

Do not execute remediation.


==================================================
PART 19 - ASSIGNMENT ENDPOINTS
==================================================

Use assignment-scoped routes where appropriate.

Example:

GET /incidents/{incident_id}/assignments/{assignment_id}

POST /incidents/{incident_id}/assignments/{assignment_id}/contract

POST /incidents/{incident_id}/assignments/{assignment_id}/safety

POST /incidents/{incident_id}/assignments/{assignment_id}/simulate-impact

This is necessary for multi-cluster incidents.


==================================================
PART 20 - RESOLUTION CONTRACT API
==================================================

Create:

POST /incidents/{incident_id}/assignments/{assignment_id}/contract

Return:

contract_id

contract_version

contract_hash

diagnosis

action

target

parameters

preconditions

expected_postconditions

rollback

authority

risk

status


==================================================
PART 21 - SAFETY API
==================================================

Create:

POST /incidents/{incident_id}/assignments/{assignment_id}/safety

Return:

evaluation_id

contract_id

contract_hash

overall_result

rules

Rules must include:

rule_id

name

result

evidence

failure_reason


==================================================
PART 22 - IMPACT SIMULATION API
==================================================

Create:

POST /incidents/{incident_id}/assignments/{assignment_id}/simulate-impact

Return:

simulation_id

contract_hash

result

projected_recoveries

projected_unresolved

new_failures

unexpected_impacts

policy_violations

input_state_digest

Do not mutate live state.


==================================================
PART 23 - REVIEW API
==================================================

Create:

GET /reviews

GET /reviews/{review_id}

POST /reviews/{review_id}/decision

Accepted decision values must use existing deterministic eligibility logic.

Input example:

{
  "reviewer_role": "Operations Reviewer",
  "decision": "APPROVE_CONTROLLED_ACTION",
  "reason": "..."
}

Do not trust the client to decide whether a button/action is allowed.

Revalidate server-side.


==================================================
PART 24 - EVIDENCE API
==================================================

Create:

GET /incidents/{incident_id}/evidence

POST /incidents/{incident_id}/assignments/{assignment_id}/request-evidence

For the synthetic demo:

POST /demo/incidents/{incident_id}/assignments/{assignment_id}/evidence/{evidence_type}

This may simulate supported diagnostic evidence arriving.

Do not allow arbitrary unsafe code or arbitrary database mutation through evidence payloads.


==================================================
PART 25 - EXECUTION API
==================================================

Create:

POST /incidents/{incident_id}/assignments/{assignment_id}/execute

Input should include:

contract_hash

Execution engine must still independently revalidate everything.

Do not accept:

safety_passed = true

simulation_passed = true

from the client.

The backend determines those states itself.

Return:

execution_id

status

action

target

current_stage

blocked_reason if applicable


==================================================
PART 26 - RECOVERY ADVANCEMENT API
==================================================

If recovery requires progressive advancement:

POST /executions/{execution_id}/advance

The endpoint must call existing persisted recovery logic.

Repeated calls must be safe and idempotent.

Do not recover services twice.


==================================================
PART 27 - VERIFICATION API
==================================================

Create:

POST /executions/{execution_id}/verify

Return:

verification_id

result

checks

incident_status

rollback_status if relevant

A successful execution response must not influence verification result.

Verification uses actual state.


==================================================
PART 28 - MEMORY API
==================================================

Create:

GET /memory

GET /memory/patterns

GET /memory/patterns/{pattern_id}

Return:

occurrences

verified successes

failed remediations

similarity evidence

prevention recommendation if available

Read-only API for Phase 7.

Do not expose an endpoint that lets callers manually create successful memory records.


==================================================
PART 29 - AUDIT API
==================================================

Create:

GET /audit

Support query parameters:

incident_id

assignment_id

actor

action

result

contract_hash

Return unified chronological audit events.


==================================================
PART 30 - DASHBOARD SUMMARY API
==================================================

Create:

GET /dashboard/summary

Return database-derived metrics used by Command Centre.

Include:

active_incidents

active_exceptions

resolved_incidents

human_review_count

verification_failures

rollbacks

root_causes_identified

compression_metrics

autonomous_resolution_rate

human_reviewed_resolution_rate

recurring_patterns

prevention_recommendations

Do not fabricate savings.


==================================================
PART 31 - API RESPONSE ENVELOPE
==================================================

Use consistent error responses.

Example:

{
  "error": {
    "code": "CONTRACT_STALE",
    "message": "The Resolution Contract no longer matches the current diagnosis.",
    "details": {}
  }
}

Use proper HTTP status codes.

Examples:

200 success

201 created

400 invalid request

404 not found

409 stale state or workflow conflict

422 schema validation

Do not return HTTP 200 for every failure.


==================================================
PART 32 - API IDEMPOTENCY
==================================================

For state-changing operations such as:

contract generation

review decisions

execution

verification

support an idempotency strategy.

Use either:

Idempotency-Key header

or deterministic existing identifiers where appropriate.

Repeated equivalent calls must not produce duplicate executions or duplicate approvals.


==================================================
PART 33 - OPTIMISTIC STATE VALIDATION
==================================================

Where useful, state-changing API requests may accept:

expected_contract_hash

expected_state_digest

or equivalent.

The backend must reject stale requests with:

409 CONFLICT

This protects future n8n workflows from acting on stale state.


==================================================
PART 34 - API SECURITY MODEL
==================================================

This remains a local synthetic hackathon prototype.

Do not implement real OAuth.

Do not implement production credentials.

However, create a lightweight demo API key option.

Example environment variable:

EXCEPTION_GENOME_API_KEY

If configured:

require:

X-API-Key

for mutating endpoints.

If not configured in local development:

allow demo mode.

Document clearly:

DEMO SECURITY ONLY

Do not claim production security.


==================================================
PART 35 - CONFIGURATION
==================================================

Use environment configuration.

Suggested:

EXCEPTION_GENOME_DB

EXCEPTION_GENOME_API_KEY

EXCEPTION_GENOME_DEMO_MODE

EXCEPTION_GENOME_HOST

EXCEPTION_GENOME_PORT

Do not hardcode machine-specific paths.


==================================================
PART 36 - PYDANTIC SCHEMAS
==================================================

Create proper request/response models.

Do not expose raw SQLite rows directly.

Use typed schemas for important objects.

Examples:

IncidentSummary

AssignmentSummary

AnalysisResult

ResolutionContractResponse

SafetyEvaluationResponse

ImpactSimulationResponse

ReviewDecisionRequest

ExecutionResponse

VerificationResponse

MemoryPatternResponse

AuditEventResponse


==================================================
PART 37 - OPENAPI
==================================================

FastAPI should expose standard:

/docs

and:

/openapi.json

Ensure route names and descriptions are readable.

The future n8n integration will use this API contract.


==================================================
PART 38 - STREAMLIT SHARED LOGIC
==================================================

Refactor only where necessary.

Streamlit must continue working.

Do not rewrite Streamlit to call FastAPI over HTTP.

Both Streamlit and FastAPI should call shared Python service functions directly.

Architecture:

Streamlit

calls

services/

calls

core/

FastAPI

calls

services/

calls

core/

This avoids unnecessary local HTTP dependencies.


==================================================
PART 39 - CONCURRENCY
==================================================

API requests may overlap.

Preserve existing SQLite transaction protections.

State-changing operations must remain safe against:

duplicate requests

concurrent execution requests

concurrent reviewer decisions

stale simulation

stale contract

Use the existing locking/idempotency strategy where possible.


==================================================
PART 40 - N8N READINESS
==================================================

Do NOT create n8n workflows yet.

But make the API easy for n8n to use.

Important responses should expose simple top-level fields.

Example safety response:

{
  "overall_result": "APPROVED"
}

Example simulation:

{
  "result": "PASS"
}

Example readiness:

{
  "status": "READY_FOR_CONTROLLED_EXECUTION"
}

Example verification:

{
  "result": "VERIFIED"
}

Future n8n IF/Switch nodes should not have to parse complicated nested structures merely to choose the next branch.


==================================================
PART 41 - WORKFLOW STATUS ENDPOINT
==================================================

Create:

GET /incidents/{incident_id}/workflow

Return a concise current workflow state.

Example:

{
  "incident_id": "INC-2026-001",
  "status": "AWAITING_VERIFICATION",
  "current_stage": "VERIFICATION",
  "assignments": [
    {
      "assignment_id": "...",
      "status": "AWAITING_VERIFICATION"
    }
  ],
  "next_allowed_actions": [
    "VERIFY"
  ]
}

This will be especially useful for n8n.


==================================================
PART 42 - NEXT ACTIONS MUST BE SERVER DERIVED
==================================================

The API should expose:

next_allowed_actions

derived from actual state.

Do not let n8n or Streamlit independently guess the workflow rules.

Examples:

GENERATE_CONTRACT

EVALUATE_SAFETY

RUN_IMPACT_SIMULATION

REQUEST_HUMAN_REVIEW

EXECUTE

ADVANCE_RECOVERY

VERIFY

NO_ACTION

This makes the core product the source of truth.


==================================================
PART 43 - API INTEGRATION TESTS
==================================================

Use FastAPI TestClient.

Add end-to-end API tests.

At minimum:

1. health endpoint works

2. scenario list works

3. start DataHub scenario

4. progress to 23 exceptions

5. analyse through API

6. retrieve 1 cluster

7. generate contract

8. safety passes

9. sandbox passes

10. workflow status reports readiness

11. execute through API

12. advance recovery

13. verify through API

14. incident resolves

15. memory appears

16. reset preserving memory

17. recurrence returns historical match

18. isolated scenario enters human-review path

19. reviewer decision through API enables valid A2 action

20. invalid reviewer decision rejected

21. stale contract returns conflict

22. stale simulation rejected

23. duplicate execution remains idempotent

24. verification failure triggers rollback

25. ambiguous scenario returns no confident root cause

26. evidence request works

27. new evidence versions diagnosis

28. previous contract becomes stale

29. concurrent scenario creates multiple assignments

30. Cluster A can resolve independently

31. Cluster B remains active after A resolves

32. incident remains unresolved until all assignments complete

33. audit API contains complete trust chain

34. dashboard metrics update

35. API never exposes secret values


==================================================
PART 44 - EXISTING TESTS
==================================================

Preserve every existing Phase 1-6 test.

Run:

python -m unittest discover -s tests -v

Run:

python -W error::ResourceWarning -m unittest discover -s tests -v

Also run new API integration tests.

Everything must pass.


==================================================
PART 45 - FASTAPI RUN COMMAND
==================================================

Support:

python -m uvicorn api.main:app --reload

Document production-like local command without reload:

python -m uvicorn api.main:app --host 127.0.0.1 --port 8000

Streamlit remains:

python -m streamlit run app.py


==================================================
PART 46 - FINAL LOCAL ARCHITECTURE DEMO
==================================================

At Phase 7 completion, both applications should be able to run against the same SQLite state:

Terminal 1:

python -m streamlit run app.py

Terminal 2:

python -m uvicorn api.main:app --host 127.0.0.1 --port 8000

Actions triggered through API must appear in Streamlit.

Actions triggered through Streamlit must appear through API reads.

There must not be separate state stores.


==================================================
PART 47 - FINAL CODEX DEMO
==================================================

Demonstrate:

DEMO 1

Shared DataHub root cause through Streamlit.

DEMO 2

Same workflow fully through FastAPI endpoints.

DEMO 3

Isolated Merchant failure requiring human approval.

DEMO 4

Concurrent Scheduler and Event Bus clusters resolving independently.

DEMO 5

Ambiguous diagnosis becoming confident after new evidence.

DEMO 6

Operational Memory recurrence.

DEMO 7

Verification failure and rollback.

All using the same backend state model.


==================================================
PART 48 - FINAL DOCUMENTATION
==================================================

Update README.md.

Add:

Architecture

Streamlit setup

FastAPI setup

Database setup

Environment variables

API authentication demo mode

API route summary

Workflow state model

Scenario list

Testing

n8n integration readiness

Do NOT add actual n8n setup yet.


==================================================
PART 49 - API CONTRACT DOCUMENT
==================================================

Create:

API_CONTRACT.md

Include every endpoint.

For each endpoint show:

method

path

purpose

request body

important response fields

possible workflow errors

example successful JSON

example error JSON

Mark endpoints especially intended for future n8n integration.


==================================================
PART 50 - N8N_HANDOFF DOCUMENT
==================================================

Create:

N8N_HANDOFF.md

Do not build n8n.

Document only:

1. base API URL

2. recommended workflow sequence

3. endpoint used at each step

4. field n8n should branch on

5. expected values

6. error handling expectations

7. idempotency recommendations

8. human-review branch behaviour

9. verification branch behaviour

10. reset/demo endpoints

Recommended future sequence:

Trigger

POST scenario/start or receive external incident

Analyse

Check root-cause result

Generate contract

Evaluate Safety Gate

Branch

Run Impact Simulation

Branch

Human Review if required

Execution

Recovery

Verification

Close or Review

This document is the handoff to the next stage.


==================================================
PART 51 - STRICT BOUNDARY
==================================================

DO NOT IMPLEMENT:

n8n workflow JSON

n8n nodes

n8n credentials

webhooks specifically tied to n8n

real OCBC integration

real banking data

real secrets

production deployment

external cloud services

Phase 7 ends with a stable API that n8n can call later.


==================================================
PART 52 - COMPLETION CRITERIA
==================================================

Phase 7 is complete only when:

1. all Phase 1-6 tests still pass

2. multi-cluster execution works independently

3. incident closure waits for all required assignments

4. ambiguous evidence can become a confident diagnosis after meaningful new evidence

5. stale downstream artifacts are invalidated

6. Streamlit still works

7. FastAPI runs

8. API and Streamlit share the same database and domain logic

9. full DataHub workflow can be driven through API

10. isolated human-review workflow can be driven through API

11. multi-cluster workflow can be driven through API

12. verification failure and rollback work through API

13. Operational Memory is visible through API

14. audit is visible through API

15. workflow status endpoint exposes next allowed actions

16. API state-changing calls are idempotent

17. stale requests fail safely

18. no secrets are exposed

19. API_CONTRACT.md exists

20. N8N_HANDOFF.md exists

21. no n8n implementation exists


==================================================
PART 53 - COMPLETION REPORT
==================================================

When finished create:

Phase_7_Report.md

Include:

- architecture
- files added
- files modified
- multi-cluster lifecycle changes
- evidence-intake changes
- service layer design
- FastAPI architecture
- endpoint list
- idempotency model
- concurrency protections
- workflow status model
- environment variables
- tests
- test results
- Streamlit run command
- FastAPI run command
- demo sequences
- known limitations
- readiness for n8n

Also create:

Exception_Genome_Phase_7.zip

containing the complete project.

After Phase 7:

STOP.

Do not implement n8n.

The Codex build is considered complete after Phase 7.