# Exception Genome Phase 5

Phase 5 extends the local SQLite simulator from readiness through controlled execution, dependency recovery, independent verification, and either incident closure or rollback with escalation. The only executable action activates an existing approved synthetic reference. The simulator stores reference identifiers and their status metadata.

## Project tree

```text
AGENTS.md
app.py
README.md
Phase_4_Report.md
Phase_5_Report.md
requirements.txt
.streamlit/config.toml
core/
  __init__.py
  action_registry.py
  analysis.py
  correlation_engine.py
  database.py
  exception_genome.py
  execution_engine.py
  execution_readiness.py
  impact_simulator.py
  incident_closure.py
  models.py
  phase4_store.py
  phase5_store.py
  recovery_engine.py
  resolution_contract.py
  rollback_engine.py
  root_cause_agent.py
  safety_gate.py
  service_graph.py
  verification_engine.py
data/seed_services.json
simulator/
  __init__.py
  engine.py
  incident_scenarios.py
ui/
  __init__.py
  command_centre.py
  components.py
  controlled_execution.py
  genome_view.py
  incident_investigation.py
  resolution_centre.py
tests/
  test_foundation.py
  test_phase3.py
  test_phase4.py
  test_phase5.py
  test_ui.py
validation/
  phase5_standard.txt
  phase5_resourcewarning.txt
```

| Change | Files |
|---|---|
| Added | `core/execution_engine.py`, `core/recovery_engine.py`, `core/verification_engine.py`, `core/incident_closure.py`, `core/rollback_engine.py`, `core/phase5_store.py`, `ui/controlled_execution.py`, `tests/test_phase5.py`, this report |
| Modified | `app.py`, `README.md`, `core/database.py`, `core/resolution_contract.py`, `simulator/engine.py`, `ui/resolution_centre.py`, `ui/command_centre.py`, `tests/test_phase3.py`, `tests/test_ui.py` |

## Controlled execution and idempotency

An explicit Streamlit action calls `execute_controlled` with the incident ID and the contract hash shown to the operator. The engine acquires a SQLite `BEGIN IMMEDIATE` lock and revalidates the following against the database.

| Requirement | Example refusal reason |
|---|---|
| Existing, unresolved and diagnosed incident | `INCIDENT_NOT_FOUND`, `INCIDENT_ALREADY_RESOLVED`, `INCIDENT_NOT_EXECUTION_ELIGIBLE` |
| Current contract, displayed hash and recalculated SHA-256 agree | `CONTRACT_MISSING`, `CONTRACT_STALE` |
| A1 executable action and correct target | `ACTION_NOT_AUTHORISED`, `TARGET_MISMATCH` |
| Current approved Safety Gate, including fresh diagnosis, evidence, action allowlist, target, parameters, authority and rollback checks | `SAFETY_APPROVAL_MISSING`, `SAFETY_APPROVAL_STALE`, `READINESS_NOT_CURRENT` |
| Passing, nondemonstration simulation references the same approved evaluation and contract | `SIMULATION_MISSING`, `SIMULATION_STALE` |
| Current operational digest matches the simulation input | `STATE_CHANGED_AFTER_SIMULATION` |
| Latest durable `READY_FOR_CONTROLLED_EXECUTION` receipt matches the same policy, simulation and input snapshot | `READINESS_NOT_RECORDED` |
| Equivalent execution has not already occurred | Existing execution returned with a duplicate marker, or `ACTION_ALREADY_EXECUTED` |

A unique SHA-256 key covers incident, contract hash, action, target and canonical parameters. Serialized validation and activation keep repeated requests from writing the same change twice. The engine records the complete pre-execution snapshot and authorization artifact IDs before changing `DH-v17` to inactive and `DH-v18` to active. Conditional SQL confirms that the previous version was approved and expired, and that the replacement was already approved and valid. The transaction records a valid DataHub authentication output and moves DataHub into `RECOVERING`. SQL errors during activation restore the savepoint. A failure during a later recovery transaction rolls back that wave, then attempts to compensate the committed activation from the stored snapshot.

## Recovery and lifecycle

Each recovery transaction re-reads the service DAG and current incident and exception states. The action must still support valid root authentication. A candidate must belong to the approved affected set, fit the root or downstream failure evidence, have healthy required parents, and have no separate unresolved incident exception. A wave completes only previously recovering eligible services, then starts newly eligible services in topological order. The next wave finishes those services. Phase 5 records counts from the database, and the UI advances persisted waves on fragment ticks. Reopening the app continues from the latest committed wave.

| Entity | Success path | Failure path |
|---|---|---|
| Service | `FAILED` or `DEGRADED` → `RECOVERING` → `HEALTHY` | Restore affected service fields from the pre-action snapshot where rollback is permitted |
| Exception | `ACTIVE` → `RECOVERING` → `RESOLVED` | Reopen recovered or recovering exceptions after rollback. Open counts include `ACTIVE`, `RECOVERING`, `REOPENED` and `ESCALATED` |
| Incident | `DIAGNOSED` → recorded readiness → `EXECUTING` → `RECOVERING` → `AWAITING_VERIFICATION` → `RESOLVED` | Record blocked attempts, mark action or verification failures, and persist `HUMAN_REVIEW_REQUIRED` when rollback is attempted |
| Execution | `VALIDATING` → `EXECUTING` → `RECOVERING` → `AWAITING_VERIFICATION` → `COMPLETED` | `BLOCKED`, `FAILED`, `ROLLED_BACK` or `ESCALATED` |

Readiness is stored as a Phase 4 receipt and displayed on the incident summary. Keeping the underlying pre-execution incident state as `DIAGNOSED` preserves the existing Phase 4 operational digest. Activation and rollback use short atomic SQLite transactions, so transient transaction states are captured as audit events.

## Operational indicators and independent verification

The incident-scoped `operational_outputs` rows identify a service, indicator type, expected and actual state, timestamp and source. DataHub authentication becomes `VALID` after reference activation. Other output rows begin as `MISSING` and recovery updates them only once the relevant service meets its dependency conditions.

`run_verification` reads persisted references, health, topology, exceptions and outputs. It compares them with the approved contract, the scoped pre-execution snapshot and the expected operational indicators. The execution result flag plays no part in these comparisons.

| Check | Expected |
|---|---|
| V-001 | Approved and valid `DH-v18` is active |
| V-002 | Previous `DH-v17` is inactive |
| V-003 | DataHub authentication is `VALID` |
| V-004 | DataHub is `HEALTHY` |
| V-005 | Every approved affected service is healthy |
| V-006 | No additional failed service |
| V-007 | Required upstream dependencies are healthy |
| V-008 | Every expected incident exception is resolved |
| V-009 | Daily Revenue Report is `AVAILABLE` |
| V-010 | Daily Reconciliation Engine is `SUCCESSFUL` |
| V-011 | Merchant Settlement is `PROCESSING` |
| V-012 | Statement Generator is `AVAILABLE` |
| V-013 | Finance Export is `COMPLETE` |
| V-014 | No unresolved downstream failures or dependencies |
| V-015 | Current contract, reference changes, topology, unaffected services, diagnosis and incident membership match the approved scope |

Every check stores its expected state, observed state, result, evidence source and failure reason. Any mandatory `FAIL` yields `FAILED`. Missing required observations yield `INCONCLUSIVE` unless another check already failed. All fifteen must pass for `VERIFIED`.

### Closure and rollback

The closure guard requires a completed execution tied to the current contract, no pending rollback, a stored `VERIFIED` result, all fifteen persisted passing rules and no open incident exceptions. It rechecks the current operational digest in the same transaction. Only then does it write `RESOLVED`, `resolved_at`, `resolution_execution_id`, `verification_id` and `final_state_digest`.

Failed or inconclusive verification requests rollback. The rollback engine checks snapshot integrity, the reversible action definition, contract scope, rollback instruction and latest execution identity. It refuses to overwrite a diverged reference configuration or an overlapping independent failure. It restores the reference activation flags and affected service fields from the snapshot, restores the previous operational outputs, reopens affected exceptions and independently compares the restored scope against the snapshot. It records `ROLLBACK_COMPLETED` or `ROLLBACK_FAILED`. Both leave the incident unresolved with `HUMAN_REVIEW_REQUIRED`.

The labelled synthetic failure mode leaves the Daily Revenue Report output at `MISSING` after its service recovers. Verification runs the same rules for both modes and detects the V-009 mismatch from the live output row.

## Schema and audit

| Table | Purpose |
|---|---|
| `executions` | Incident and contract links, idempotency key, status, authorization receipt IDs, action and parameters, snapshot, timestamps, digests and rollback fields |
| `execution_steps` | Timestamped execution, recovery, verification, rollback and escalation events |
| `operational_outputs` | Expected and observed synthetic indicator by incident and service |
| `verification_results` | One stored verification per execution, overall outcome, operational digest and recovery counts |
| `verification_checks` | Individual check evidence, expected and actual values, outcome and failure reason |
| `rollback_records` | Rollback result, scope outcome and restored-state digest |

Migrations create the new tables, add nullable closure fields to `incidents` and preserve the Phase 4 incident payload shape for existing fingerprints. Foreign keys link artifacts and support demo reset. `execution_steps` records timestamp, incident and execution IDs, deterministic actor, action, source, decision, result, contract hash and state digest. Events cover validation start and outcome, action start and activation, service and exception entry and completion, recovery completion or failure, all verification rules and overall outcome, incident closure, rollback start and outcome, and escalation. The actors are `EXECUTION_ENGINE`, `RECOVERY_ENGINE`, `VERIFICATION_ENGINE`, `ROLLBACK_ENGINE` and `SYSTEM`.

## Run and demonstrate

From the project directory with Python 3.10+ and dependencies available:

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

### Successful case

1. In **Command Centre**, click **Reset synthetic demo** and confirm 24 healthy services.
2. Click **Simulate Incident**, wait for 23 exceptions, then click **Analyse Exception Genomes**. Confirm one cluster and DataHub API as the root cause.
3. Open **Resolution Centre**. Select **Approved reference activation** and click **Generate Resolution Contract**, **Evaluate Safety Gate**, and **Run Impact Simulation**. Confirm readiness and the 23/23 projection.
4. Leave **Execution mode** on **Normal** and click **Execute Controlled Remediation**. Inspect the execution ID, contract hash, applied reference and recovering services. The graph and counts track persisted changes.
5. Wait for **AWAITING VERIFICATION**. Recovery can clear the 23 exception rows before the incident closes.
6. Click **Run Independent Verification**. Inspect all 15 expected-versus-actual checks and confirm **RESOLUTION VERIFIED** and **RESOLVED**.
7. Return to **Command Centre**. Confirm 24 healthy services and zero open exceptions.

### Verification-failure case

1. Reset and repeat the same simulation, diagnosis, contract, safety and sandbox steps.
2. Select **Synthetic verification-failure demonstration** and click **Execute Controlled Remediation**.
3. At **AWAITING VERIFICATION**, click **Run Independent Verification**. V-009 shows **AVAILABLE** expected and **MISSING** observed even though the remediation ran and the services recovered.
4. Confirm **VERIFICATION FAILED**, **ROLLBACK COMPLETED**, and **HUMAN REVIEW REQUIRED**. Command Centre displays 23 reopened exceptions. The expired `DH-v17` reference is active again in the synthetic configuration.

## Validation and limits

New unit cases cover missing readiness, tampered and superseded authorization, A2 and A3 rejection, stale artifacts and operational drift, persistence and duplicate execution, graph-driven transitions, unaffected services, live verification, evidence gaps, successful closure, snapshot rollback, rollback refusal, atomic write failures, recovery compensation, audits and reset. Streamlit AppTest exercises the approved normal and verification-failure paths alongside the existing Phase 4 sandbox rejection path. The Phase 3 boundary test was updated to exclude engines deliberately introduced by Phase 5 and continues to guard later phases.

This is a single synthetic scenario in a local Streamlit and SQLite application. Recovery advances while Command Centre or Resolution Centre is open and resumes when a view is reopened. Output checks read simulator indicators. There is no production connector, n8n, FastAPI, Operational Memory, Prevention Engine or full Human Review workflow. The source archive omits mutable demo databases and older ZIP packages.


| Test command | Result |
|---|---|
| `python -m unittest discover -s tests -v` | 44 passed in 93.671 seconds |
| `python -W error::ResourceWarning -m unittest discover -s tests -v` | 44 passed in 93.780 seconds |

Validation used Python 3.13.13 and Streamlit 1.58.0 with isolated SQLite databases. Both full logs are in the archive under `validation/`. Streamlit emitted its normal AppTest bare-mode ScriptRunContext notices. The UI was exercised through AppTest. Manual browser appearance was outside that verification.

Observed success was 23 recovered services, 15 passing checks, zero open exceptions and a resolved incident. The failure demonstration produced V-009 `AVAILABLE` versus `MISSING`, restored the previous reference, reopened 23 exceptions and persisted `HUMAN_REVIEW_REQUIRED`.
