# Exception Genome API contract

Local synthetic API at `http://127.0.0.1:8000`. OpenAPI is served at `/openapi.json`, with interactive documentation at `/docs`. JSON responses contain the relevant artifact directly. Errors use an `error` object with `code`, `message` and `details`.

## Request conventions

Set `X-API-Key` on mutations when the server has a demo key configured. Supply `Idempotency-Key` on retryable POSTs. Use a fresh key per intended operation or tick. An exact replay returns the stored response. Reusing a key with different input returns 409. For assignment mutations, send `expected_contract_hash` and optionally `expected_state_digest` to assert the artifact or input state. Omit the contract hash when generating the first contract.

| Method and path | Purpose and input | Response and common conflicts |
|---|---|---|
| GET /health | Connectivity check | status, database_status, version, mode |
| GET /incidents | Incident summaries | id, title, status, started_at, simulation_step |
| GET /incidents/{incident_id} | One incident | Same fields, with resolved_at when present |
| GET /incidents/{incident_id}/exceptions | Exception status and synthetic evidence | List with id, service_id, status, error code |
| GET /incidents/{incident_id}/assignments | List assignments | assignment_id, cluster, diagnosis |
| GET /incidents/{incident_id}/assignments/{assignment_id} | Scoped assignment | assignment_id, incident_id, cluster, diagnosis |
| GET /incidents/{incident_id}/workflow | **Workflow integration** | Incident status, assignment statuses and server-derived next actions |
| GET /demo/scenarios | Discover demo fixtures | scenario_id, incident_id, title |
| POST /demo/scenarios/{scenario_id}/start | Start a fixture. Empty body | 201 incident summary |
| POST /demo/incidents/{incident_id}/advance | Advance one propagation tick | advanced, incident |
| POST /demo/reset/current | Reset the simulator and retain memory | reset, preserved_memory |
| POST /demo/reset/full | Reset simulator and history | reset, preserved_memory |
| POST /incidents/{incident_id}/analyse | Analyse complete propagation | exception_genomes, correlation_clusters, root_cause_analyses. 409 when propagation is incomplete |
| POST /incidents/{incident_id}/assignments/{assignment_id}/contract | Create or reuse a scoped contract. Optional state assertions | 201 contract_id, contract_hash, evidence_snapshot, action_type, status |
| POST /incidents/{incident_id}/assignments/{assignment_id}/safety | Evaluate gate. Optional state assertions | evaluation_id, contract_hash, decision, rules |
| POST /incidents/{incident_id}/assignments/{assignment_id}/simulate-impact | Project scoped impact. Optional state assertions | simulation_id, input_state_digest, result, projected changes, readiness. 409 when gate is ineligible |
| GET /reviews | List open and recorded reviews | review ID, assignment, reason and current status |
| GET /reviews/{review_id} | Review evidence and status | Same review fields |
| POST /reviews/{review_id}/decision | Synthetic reviewer identity, decision, reason and optional assertions | 201 review_decision_id, decision_hash. 409 for ineligible approval |
| GET /incidents/{incident_id}/evidence | Append-only structured intake evidence | evidence ID, assignment, type, version, structured payload |
| POST /incidents/{incident_id}/assignments/{assignment_id}/request-evidence | Review body with decision REQUEST MORE EVIDENCE | 201 decision record |
| POST /demo/incidents/{incident_id}/assignments/{assignment_id}/evidence/DEPENDENCY_PROBE | Simulate structured evidence after request | 201 evidence and prior/current diagnoses. 409 when request or fixture preconditions are missing |
| POST /incidents/{incident_id}/assignments/{assignment_id}/execute | State assertions and optional mode | execution_id, status, contract hash. 409 on stale or blocked authority |
| POST /executions/{execution_id}/advance | Persist one recovery wave | execution_id, status, recovery_step |
| POST /executions/{execution_id}/verify | Independently verify actual state | verification_id, status, checks, affected/recovered totals |
| GET /memory | Historical case evidence | Memory and outcome records |
| GET /memory/patterns | Pattern aggregation and advisory prevention | patterns, recommendations |
| GET /memory/patterns/{pattern_id} | One pattern | pattern ID, occurrences, verified and failed counts, success rate |
| GET /audit | Optional incident, assignment, actor and action filters | Chronological artifact-linked events |
| GET /dashboard/summary | Simulator metrics | active/resolved incidents, active exceptions and verified history count |

### Examples

```json
{"reviewer_identity":"Operations Reviewer","decision":"APPROVE CONTROLLED ACTION","reason":"Reviewed simulator evidence and impact projection"}
```

```json
{"status":"ok","database_status":"connected","version":"7.0","mode":"demo"}
```

```json
{"error":{"code":"CONTRACT_STALE","message":"CONTRACT_STALE","details":{}}}
```

404 indicates an unknown resource. 409 indicates a state, authority, or idempotency conflict. 422 indicates an invalid request body. A safety or verification evaluation may legitimately return 200 with a negative artifact result. Read the decision or status before continuing.

