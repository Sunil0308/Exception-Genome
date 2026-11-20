# Exception Genome Phase 4

## Project structure and architecture

| Path | Responsibility |
|---|---|
| `app.py` | Streamlit entry point and workspace navigation |
| `simulator/incident_scenarios.py`, `simulator/engine.py` | Scenario registry and incident propagation |
| `core/analysis.py`, `core/exception_genome.py` | Incident-scoped analysis and Exception Genome fingerprints |
| `core/correlation_engine.py`, `core/root_cause_agent.py` | Directional event correlation and deterministic diagnosis |
| `core/service_graph.py`, `core/models.py` | Dependency graph and service models |
| `core/action_registry.py`, `core/resolution_contract.py` | Action policy, deterministic proposal translation and versioned contracts |
| `core/safety_gate.py`, `core/impact_simulator.py`, `core/execution_readiness.py` | Policy rules, isolated projections and readiness |
| `core/database.py`, `core/phase4_store.py` | SQLite schema, persistence, hashes, audit events and demo reset |
| `ui/command_centre.py`, `ui/resolution_centre.py` | Live incident summary, trust chain and contract review |
| `ui/genome_view.py`, `ui/incident_investigation.py`, `ui/components.py` | Investigation and evidence views |
| `data/seed_services.json`, `.streamlit/config.toml`, `requirements.txt` | Demo topology, display settings and runtime dependencies |
| `tests/test_foundation.py`, `tests/test_phase3.py`, `tests/test_phase4.py`, `tests/test_ui.py` | Unit and Streamlit integration coverage |

### Incident analysis

`analyse(incident_id)` resolves `get_scenario(incident_id)`, reads only that incident’s exception rows, and verifies that its observed active services match the scenario’s propagation set before analysis. Cluster identifiers use `EG-{incident_id}-{sequence}` and diagnosis identifiers derive from their cluster. A legacy diagnosis can be regenerated through **Analyse Exception Genomes**. Existing Python callers passing a database `Path` as the first argument still work.

| Upstream family | Additional allowed downstream families |
|---|---|
| Authentication failure | Upstream data unavailable, dependency failure, missing source data, processing blocked |
| Upstream data unavailable | Missing source data, dependency failure, processing blocked |
| Dependency failure | Processing blocked |
| Processing blocked | None |
| Missing source data | None |

Identical known families are compatible along a directed dependency path with plausible event order. Siblings earn no direct causal error points without such a path. The correlation engine requires a witnessed common cause, a supported link to the group’s first symptom and a bounded event window. The existing signal weights remain in use.

### Action Registry

| Action | Class | Target and maximum scope | Risk | Autonomous policy |
|---|---|---|---|---|
| `ACTIVATE_APPROVED_CREDENTIAL_REFERENCE` | A1 controlled and reversible | One service configuration | Moderate | Eligible after evidence, rollback and simulation checks |
| `RESTART_SINGLE_SERVICE` | A2 conditional | One service | High | Human authority required. Isolated Auth restart preset available for the demo |
| `RETRY_FAILED_JOB` | A2 conditional | One job | Moderate | Human authority required |
| `NO_ACTION` | A0 advisory | Zero | None | Advisory |
| `ESCALATE` | A0 advisory | Zero | None | Human review |
| `ROTATE_OR_CREATE_CREDENTIAL` | A3 prohibited autonomously | Zero | High | Blocked |

Each definition also declares reversibility, simulation requirement, required evidence, allowed and forbidden parameters and rollback action. For the flagship contract, the only parameter is `credential_version`. The registry holds the identifiers `DH-v17` and `DH-v18` with approval, validity, active state and creation time. `DH-v17` starts active and expired. `DH-v18` starts approved, valid and inactive. The diagnosis recommendation is displayed separately from the deterministic proposal.

### Resolution Contract and hash

| Section | Contract fields |
|---|---|
| Identity | `contract_id`, `incident_id`, `cluster_id`, `analysis_id`, `created_at`, `contract_version`, `contract_hash`, `status` |
| Diagnosis | `root_cause`, `root_cause_service`, `root_cause_evidence_score`, `correlation_score` |
| Frozen evidence | `evidence_snapshot` holds the diagnosis result, genome signatures, source service and exception rows, failed change, affected-service count, contradictions, alternative hypotheses and snapshot time |
| Action and policy | `proposed_action`, `action_type`, `target_service`, `action_parameters`, `autonomy_class`, `risk_class` |
| Conditions and rollback | `required_preconditions`, `expected_postconditions`, `rollback_plan` |
| Authority | `authority_scope`, `maximum_blast_radius` |

SHA-256 covers sorted, compact UTF-8 JSON of the safety-relevant fields. Record IDs, creation and snapshot timestamps, the version counter, status and the hash itself are excluded. The diagnosis, evidence, proposal, parameters, preconditions, expected outcomes, classification, authority and rollback are included. Identical current content reuses the existing contract. A material change creates a new per-incident version and marks the old decisions stale. UUIDs and incident prefixes distinguish contracts and decision records.

### Safety Gate

Both evidence thresholds are strictly greater than 90 out of 100. The gate derives its outcome from observed evidence, rule severity and the registry. A blocking failure yields `BLOCKED`. Review-only failures yield `HUMAN_REVIEW_REQUIRED`. Fully satisfied applicable rules yield `APPROVED` for simulation.

| Rule | Check |
|---|---|
| SG-001 | Traceable diagnosis and unique strongest candidate |
| SG-002 | Current contract version, diagnosis and frozen evidence match |
| SG-003 | SHA-256 integrity |
| SG-004 | Root-cause evidence exceeds configured threshold |
| SG-005 | Correlation exceeds configured threshold |
| SG-006 | Conflicting evidence is available and clear |
| SG-007 | Target equals diagnosed root service |
| SG-008 | Action exists in registry |
| SG-009 | Registry permits controlled autonomy and classifications match |
| SG-010 | Exact parameter allowlist and synthetic identifiers |
| SG-011 | Inactive approved replacement exists for the service |
| SG-012 | Replacement status is valid |
| SG-013 | Active reference is approved and expired, authentication is expired and the service is failed |
| SG-014 | No equivalent activation is present in the synthetic configuration |
| SG-015 | Authority is limited to the declared configuration target |
| SG-016 | Rollback restores the observed previous reference and requires escalation on unexpected behaviour |
| SG-017 | Structured evidence and action-specific requirements are complete |
| SG-018 | The incident remains diagnosed and operationally unresolved |

### Impact Sandbox and readiness

The sandbox deep-copies the incident, service topology, exception evidence and synthetic references. It models reference activation, then visits the DAG in dependency order. It projects recovery only for affected downstream symptoms whose required dependencies are healthy and whose failure fits the diagnosed chain. An independent active exception or failed required dependency can keep a service unresolved. A projected root failure, new failure, unexpected impact or policy violation prevents a passing result. Missing topology or an unmodelled action can produce `INCONCLUSIVE`. Input and output fingerprints use deterministic state digests.

The safe path requires a current recorded approval. The blocked Authentication Service restart has a dedicated demonstration entry point. It projects the Auth outage in isolation and exposes the additional dependency impact while leaving DataHub unresolved.

Readiness checks a current, intact contract, up-to-date diagnosis, recorded deterministic approval, a passing sandbox run tied to that approval and contract hash, and a matching operational fingerprint. A superseded contract, changed evidence, changed operational state or inconclusive result cannot support readiness.

### SQLite and audit

The Phase 4 tables are `resolution_contracts`, `safety_evaluations`, `impact_simulations`, `execution_readiness`, `approved_resource_references` and `phase4_audit_events`. Foreign keys connect contracts to incident and diagnosis rows and decision artifacts to contracts. Identifiers, status, contract hash and version are searchable columns. JSON payloads retain structured artifacts. Audit events record contract creation, version generation, policy evaluations and failed rules, simulation start and completion, and readiness determination. Demo reset clears the incident’s decision history along with Phase 1–3 demo records.

## Run and demonstrate

From the project directory with Python 3.10+ installed:

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

1. In **Command Centre**, select **Reset synthetic demo** if you need a fresh healthy baseline. Select **Simulate Incident** and wait until all **23** exceptions are active.
2. Select **Analyse Exception Genomes**. Verify one cluster and **DataHub API** as the root cause.
3. Open **Resolution Centre**. Keep **Approved reference activation** selected and click **Generate Resolution Contract**. Compare the analysis recommendation with the controlled action. Inspect the version, SHA-256 hash, evidence snapshot, authority and rollback.
4. Click **Evaluate Safety Gate**. Verify **18 / 18** rules pass and **Approved for impact simulation** appears.
5. Click **Run Impact Simulation**. Verify **23 / 23 projected recovery** with zero unresolved services, new failures, unexpected impacts or policy violations. Read the **READY FOR CONTROLLED EXECUTION** card.
6. Return briefly to **Command Centre** to show that service failures remain and all **23** exceptions are still **ACTIVE**.
7. Return to **Resolution Centre**, choose **Aggressive shared authentication restart**, generate the new contract and evaluate safety again. Inspect the blocking rules and the disabled ordinary simulation control.
8. Click **Run isolated unsafe demonstration**. Verify **FAIL**, one new projected Authentication Service failure and no projected root-cause resolution. Check that all **23** exceptions remain **ACTIVE** in Command Centre.

## Validation and limitations

New tests cover two incidents and unique analytical IDs, directional and sibling evidence, hash determinism and content changes, frozen evidence, forbidden model requests and out-of-scope proposals, stale decisions, missing evidence, dependency-based recovery, unsuccessful and inconclusive projections, operational state isolation and readiness. The existing Streamlit scenario now exercises both Phase 4 candidates. The prior phase-boundary test still excludes later-phase tables and engines.

The analyzer uses a deterministic demo recommendation. The planner models approved reference activation, and the sandbox also models the isolated restart demonstration. Retry and advisory registry entries define policy without a recovery model. Required dependencies are binary in this synthetic topology. The SHA-256 digest binds a decision to content and assumes trusted application and SQLite access. The demo has no executor, live reference switch, exception closure, post-action verification, Operational Memory or Prevention Engine. Execution is intentionally disabled in Phase 4.


| Command | Result |
|---|---|
| `python -m unittest discover -s tests -v` | 28 passed in 49.799 seconds |
| `python -W error::ResourceWarning -m unittest discover -s tests -v` | 28 passed in 50.088 seconds |

Tests ran with the installed Python 3.13.13 interpreter, Streamlit 1.58.0 and isolated SQLite databases. Streamlit emitted its normal bare-mode ScriptRunContext notices. The full logs are included in the source archive. Streamlit AppTest exercised the controls. Browser appearance was not manually reviewed.

Observed flagship metrics were 98.0/100 root-cause evidence and 96.8/100 correlation. The approved reference contract passed 18 rules and projected 23 recoveries. The unsafe restart was blocked and projected one new Authentication Service failure. Both decisions left the 23 live exceptions active and the incident operationally unresolved.
