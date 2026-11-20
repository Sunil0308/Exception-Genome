# Exception Genome Phase 6

The simulator now distinguishes shared, isolated, concurrent and uncertain operational failures. It supports a reviewer-authorised Merchant Settlement restart and learns from completed DataHub cases. All actions remain local synthetic operations.

## Project tree and changes

| Area | Files |
|---|---|
| Entry and documentation | `app.py`, `AGENTS.md`, `README.md`, `Phase_4_Report.md`, `Phase_5_Report.md`, `Phase_6_Report.md`, `requirements.txt`, `.streamlit/config.toml` |
| Existing core extended | `core/analysis.py`, `correlation_engine.py`, `database.py`, `exception_genome.py`, `execution_engine.py`, `execution_readiness.py`, `impact_simulator.py`, `recovery_engine.py`, `resolution_contract.py`, `root_cause_agent.py`, `safety_gate.py`, `verification_engine.py` |
| Existing core retained | `core/action_registry.py`, `incident_closure.py`, `models.py`, `phase4_store.py`, `phase5_store.py`, `rollback_engine.py`, `service_graph.py` |
| New core modules | `core/audit.py`, `review.py`, `operational_memory.py`, `prevention_engine.py` |
| Simulator | Modified `simulator/engine.py` and `incident_scenarios.py`. Topology comes from `data/seed_services.json`. |
| UI | New `ui/audit_view.py`, `memory_view.py`, `review_centre.py`. Updated Command Centre, Exception Genome, Incident Investigation, Resolution Centre, execution view and shared components. |
| Tests | New `tests/test_phase6.py`, existing foundation, Phase 3–5 and Streamlit suites. The earlier boundary assertions were updated to allow the Phase 6 memory modules. |

## Analysis and scenario design

The analyser processes exceptions by incident ID. A cluster must have a witnessed upstream event, a compatible causal error path, at least 75 pair points against the leading member, and at most 180 seconds to each existing member. Pair points come from shared dependencies, time, error compatibility, recorded change and witnessed dependency direction. 90 or higher is labelled high correlation. When an exception qualifies for competing groups, it appears separately as `AMBIGUOUS_CLUSTER`. Single-member assignments default to `SINGLETON` and become `UNASSIGNED` below 65 evidence points. A diagnosis below 75 points or a competing grouping yields `NO_CONFIDENT_ROOT_CAUSE`. The DataHub autonomous gate retains its higher existing thresholds.

| Demo | Result |
|---|---|
| Shared root cause | 23 DataHub-related exceptions in one high-confidence cluster |
| Isolated failure | One Merchant Settlement exception with a local job diagnostic and no shared root cause |
| Concurrent failures | Two independent pairs, Scheduler with Batch Processing Engine and Event Bus with Notification Service. The seed graph contains four affected services across the two branches. |
| Ambiguous evidence | Revenue reporting exception with possible local and upstream causes, and insufficient corroboration |
| Recurrence | DataHub propagation under a new incident ID, with historical matches if a prior case exists |

Exception Genome and Resolution Centre let operators select assignments. Each assignment can keep its own contract version and gate records within the incident. The supported executable flows are the single-assignment DataHub and Merchant cases. Multi-cluster execution is explicitly blocked at the executor because independent cluster verification and shared incident closure are still pending.

## Human Review and execution

Review cases are derived from current diagnosis, safety, sandbox and execution records. Decisions are persisted with synthetic role, rationale, evidence snapshot, incident and cluster IDs, the exact contract hash and a deterministic decision hash. Reviewers can record rejection, escalation, a request for more evidence, or a no-action disposition. The demo can append an incomplete diagnostic probe after an evidence request. It versions the diagnosis, retains the prior evidence in the audit trail and supersedes the contract and downstream artifacts. The incomplete probe leaves the diagnosis uncertain.

A2 restart authority is restricted to the single affected Merchant Settlement service with the expected local worker evidence. It requires a technical Safety Gate pass apart from SG-009, a passing projection tied to that evaluation, and a reviewer approval bound to the contract, policy evaluation, simulation and input-state digest. Execution revalidates all bindings and the recorded readiness receipt under the write lock. A stale or prohibited action remains blocked. A3 actions allow rejection or escalation. Independent verification checks service health, the synthetic settlement output, exception ownership and closure, dependencies, unaffected services and scope. It then uses the existing closure guard.

## Memory, similarity and prevention

Completed verified cases and failed remediation outcomes are recorded in `operational_memory`. Failed verification and rollback remain visible as negative history. A stable pattern ID groups matching root dependency, service and domain sets, topology, error families, recorded change and authentication context. Similarity requires the same root dependency and scores exact matches across eight equal-weight fields, including Genome signatures. Scores and prior outcomes are advisory and do not satisfy safety, sandbox or verification.

Pattern counts and success rates are derived from actual case records. The Prevention Engine requires three verified matching credential-expiry cases by default and suppresses recommendations when matching failed history exists. The resulting preventive control is advisory. It proposes validating an approved replacement before expiry and scheduling controlled activation.

## Schema, audit and analytics

Phase 6 adds `operational_memory`, `review_decisions`, `analysis_events` and `archived_audit` with additive migrations. Pattern metrics and prevention advice are derived on read. The audit view combines detection and exception rows, persisted diagnosis and clustering events, Phase 4 controls, human decisions, Phase 5 execution checkpoints, rollback, closure and memory. It supports incident, cluster, actor, action, decision, result, date and contract hash filters, with expandable evidence details. Historic event details are copied into the audit archive on the memory-preserving reset.

Command Centre offers scenario and incident selection, a composite service map, and database-derived open and completed outcomes, verification failure and rollback counts, patterns and exception compression. Rates use incident outcomes, with exceptions counted separately. **Reset current scenario and keep memory** clears the live demo environment while retaining historical memory and archived audit. **Reset synthetic demo** is the full reset.

## Run and demonstrate

From the project directory with Python 3.10+ and dependencies installed:

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

1. **A · Shared root cause.** Full reset. Choose **DataHub Credential Failure** and click **Simulate Incident**. Wait for 23 exceptions, then click **Analyse Exception Genomes**. In **Resolution Centre**, generate the contract, evaluate safety, run impact simulation, execute, wait for recovery and run independent verification. Check the verified entry in **Operational Memory**.
2. **B · Isolated failure.** Reset and choose **Merchant Settlement Local Job Failure**. Simulate and analyse. Inspect the singleton in **Exception Genome**. Generate its contract, evaluate safety and run impact simulation. In **Review Centre**, choose a synthetic role, select **APPROVE CONTROLLED ACTION**, and enter the rationale. Return to **Resolution Centre**, execute, and run independent verification after recovery.
3. **C · Concurrent failures.** Reset and choose **Concurrent Operations Incident**. Simulate and analyse. In **Exception Genome**, inspect the Scheduler and Event Bus assignments in turn. In **Resolution Centre**, select each assignment to inspect or generate its own contract.
4. **D · Ambiguous evidence.** Reset and choose **Ambiguous Dependency Failure**. Simulate and analyse. Review the competing possibilities, then open **Review Centre**. Record **REQUEST MORE EVIDENCE**, click **Simulate diagnostic evidence arriving**, and inspect the newer diagnosis. The incomplete probe leaves the case open.
5. **E · Recurrence.** After a successful DataHub run, use **Reset current scenario and keep memory**. Choose **DataHub recurrence** and simulate and analyse. Inspect previous outcomes in **Exception Genome**, then repeat the full governed path. After three matching verified DataHub cases with no contradictory failed history, inspect **Preventive recommendation** under **Operational Memory**.

## Limitations and test scope

The concurrent fixture has four exceptions because the two chosen branches each contain a root and one downstream service in the seed topology. Cluster execution and closure are supported for single-assignment incidents. Multi-cluster incidents support analysis and scoped contract and policy records. The current-scenario reset clears the shared live simulator state, so it can clear multiple live incidents in one operation. Reviewer no-action and escalation are recorded dispositions. They do not perform manual remediation or create independently verified closures. Evidence intake currently demonstrates an inconclusive probe rather than a new evidence source that changes candidate ranking. Pattern aggregation and prevention recommendations are calculated from persisted memory on read. The app is still a synthetic single-workspace prototype.

Phase 6 unit tests exercise isolated authority, stale reviewer approval, independent verification, separate clusters and contracts, ambiguous evidence versioning, repeated cases and prevention threshold, negative history, audit preservation and both reset modes. Existing Streamlit tests cover the earlier phases and the DataHub execution and rollback paths.



| Test command | Result |
|---|---|
| `python -m unittest discover -s tests -v` | 51 passed in 127.075 seconds |
| `python -W error::ResourceWarning -m unittest discover -s tests -v` | 51 passed in 127.087 seconds |

A separate Streamlit AppTest smoke check opened the new pages and verified that submitting Merchant Settlement reviewer approval exposed the controlled execution button. Validation used Python 3.13.13 and Streamlit 1.58.0 with isolated SQLite databases. Full suite logs are included in the archive.
