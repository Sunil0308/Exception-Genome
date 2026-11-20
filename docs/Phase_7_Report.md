# Exception Genome Phase 7

## Architecture

Streamlit and FastAPI use the same Python domain modules and SQLite database. The shared application entry points are in `services/workflow.py`. API routing, schema validation, optional mutation authentication and request receipts are in `api/main.py` and `api/schemas.py`. Neither interface implements a second safety policy or executor.

Added structured intake in `core/evidence_intake.py`, API integration tests in `tests/test_phase7.py`, and the [API contract](API_CONTRACT.md) and [future integration handoff](N8N_HANDOFF.md). Updated the contract, review, sandbox, execution, recovery, verification, closure, memory and audit paths for assignment scope. The Streamlit Resolution Centre routes its execution and recovery controls to the same application entry points.

## Assignment scope and closure

The Scheduler and Event Bus assignments in the concurrent fixture now support A2 synthetic component restarts. Their policy approvals and simulations bind to separate contract hashes. Execution accepts an explicit cluster ID, verifies its receipt under the domain write lock and selects only the cluster's exceptions and services for recovery. Each restart affects its selected component. Recovery follows that component's dependency branch.

The app persists execution and verification per assignment. One assignment can verify while the other stays open. Aggregate closure requires completed and verified executions tied to current contracts for all assignments, recovered service health and resolved exception rows. The mixed fixture includes a Scheduler cluster and a Merchant singleton. The singleton remains independently reviewable and verifiable.

A2 assignments require human authority. Any changed operational state can stale a broader digest, including a change to a sibling assignment. Re-evaluate and reapprove the next assignment if that happens. Only one recovery or verification is in flight per multi-assignment incident.

## Structured evidence

The synthetic dependency probe requires a recorded evidence request. Its structured payload records the actual topology relationship, source health at time of failure, symptom timestamp, probe reliability and provenance. The diagnosis score is recalculated from topology, timing and observed upstream health. In the ambiguous demo, the probe identifies a DataHub upstream timeout and reaches 85 points. Remediation still needs evidence specific to an allowlisted action. The old diagnosis remains in audit, and superseded contracts, gate results, simulations and readiness receipts retain their history.

## HTTP contract and runtime

See [API_CONTRACT.md](API_CONTRACT.md) for routes and response fields. The workflow endpoint exposes next actions by assignment, with execution IDs on assignment detail. POSTs support optional idempotency receipts in SQLite. A repeated key with a different request yields 409. Domain execution and verification also retain their existing idempotency guards. An expected contract hash and input-state digest can reject stale requests. The execution path validates them under its write lock.

| Variable | Purpose |
|---|---|
| `EXCEPTION_GENOME_DB` | Override the shared database file for both interfaces |
| `EXCEPTION_GENOME_API_KEY` | Optional local demo mutation key, sent as `X-API-Key` |
| `EXCEPTION_GENOME_DEMO_MODE` | `true` by default. Set `false` to disable synthetic scenario and failure-injection mutations |
| `EXCEPTION_GENOME_TEST_IN_MEMORY_LOOP` | Test-only event loop option for Windows sandboxes where loopback sockets are unavailable |

Run from the project directory with Python 3.10+ and dependencies installed.

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

Run Streamlit and Uvicorn in separate terminals with the same database setting. For local development, `python -m uvicorn api.main:app --reload` also works. Read `/docs` for interactive API examples.

## Demo sequence

1. **DataHub flagship.** Start, advance and analyse the DataHub fixture. Generate contract, evaluate safety, simulate, execute, advance recovery and verify. Confirm closure and memory.
2. **Human-reviewed singleton.** Run Merchant Settlement. Complete the gate and impact simulation. Record a synthetic reviewer approval, then run execution, recovery and verification.
3. **Independent assignments.** Run concurrent Scheduler and Event Bus. Finish the first assignment and confirm the sibling's exceptions remain active. Finish the second assignment to close the incident. Repeat with the mixed fixture to demonstrate the independent singleton lifecycle.
4. **Evidence changes diagnosis.** Start the ambiguous fixture. Request evidence, submit the demo dependency probe, then compare the prior and current diagnosis and check the audit trail.
5. **Rollback.** Select synthetic verification failure on DataHub execution. Recovery can finish, but verification fails and rollback leaves the incident open for review.

## Limits and integration readiness

Use one API worker. Domain transitions use SQLite write locks. Generic HTTP receipt writes follow domain commits, so a crash between a mutation and its receipt can require the client to fetch current state before retrying. For non-execution endpoints, API-level optimistic prechecks use a separate read from the domain mutation. Revalidation inside the core services remains authoritative. The multi-cluster demo still uses the four services in the existing concurrent fixture. The API key and simulated reviewer identities are for this local demonstration. No n8n workflow, network-side integration or production deployment is included.


## Validation

| Command | Result |
|---|---|
| `python -m unittest discover -s tests -v` | 57 passed in 162.924 seconds |
| `python -W error::ResourceWarning -m unittest discover -s tests -v` | 57 passed in 162.661 seconds |
| Targeted FastAPI TestClient suite | 6 passed in 20.005 seconds |

The suite used Python 3.13.13, FastAPI 0.129.0 and Streamlit 1.58.0. It tested HTTP behavior via the in-process ASGI transport, including optimistic conflicts, idempotency, DataHub closure, review-authorised restarts, sibling isolation, structured evidence and verification rollback. Streamlit navigation and legacy flows ran through AppTest. A live Uvicorn TCP listener was not verified in this sandbox. Full logs are under validation in the archive.
