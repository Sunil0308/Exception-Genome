# Exception Genome · Phase 7

Synthetic operational exception investigation, governed execution, and independently verified incident closure. The [Phase 6 report](Phase_6_Report.md) contains both demo paths, the current project tree, and validation results.

## Setup and run

Python 3.10+ with dependencies installed:

```powershell
cd C:\Codex\OCBC
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

SQLite initialises and migrates automatically. Existing records are preserved. The application uses `data/operations.sqlite3`. Source archives exclude the runtime database so a fresh extraction starts healthy.

## Project tree

See [Phase_6_Report.md](Phase_6_Report.md) for the current tree.

## Foundation cleanup

The connection context manager wraps the transaction and closes in `finally`, including rollback paths. Existing commit/rollback semantics are preserved. Command Centre rendering moved into `ui/command_centre.py`. The scenario dataclass owns source, change event, error templates, severity, failure rules and timing; `simulator/engine.py` owns generic descendant propagation. Existing `start()` and `advance()` imports remain valid.

The 24-node topology is unchanged. DataHub and 22 descendants produce 23 active exceptions. Authentication Service remains healthy. First failure is 09:00:10, followed by eight-second simulated increments; UI ticks remain 0.7 seconds. Fixed scenario timestamps are synthetic, not current monitoring time.

## Schema and migration

`services`, `incidents`, and all original exception columns are preserved. `exceptions` gains:

- `upstream_dependency` TEXT: common upstream change source when unambiguous.
- `dependency_path` TEXT: JSON path from that source to the affected service.
- `last_success_timestamp` TEXT.
- `recent_change_event` TEXT: structured JSON change record.
- `authentication_context` TEXT.
- `retry_count` INTEGER, default 0.
- `evidence_sources` TEXT: JSON source labels.
- `genome_signature` TEXT: populated by analysis.

Existing `business_impact` and `severity` remain unchanged. Migration checks `PRAGMA table_info` before adding columns. Existing rows receive context from recorded service state and graph where available; old free-text change records remain UNKNOWN rather than being presented as confirmed credential evidence. Reset and simulate again to generate the full new structured evidence.

New tables:

| Table | Key and contents |
|---|---|
| exception_genomes | exception_id FK/PK; complete genome JSON |
| correlation_clusters | cluster id PK; incident FK; score, signals and cluster evidence JSON |
| cluster_members | cluster/exception composite PK and foreign keys |
| root_cause_analyses | cluster FK/PK; result JSON including confidence, alternatives and causal paths |

Completed analysis writes these tables and DIAGNOSED status in one transaction. Reload/reinitialisation reuses saved results. Reset deletes children before parents. No execution or memory tables exist.

## Fingerprints and normalization

SHA-256 fingerprints encode normalized error family, graph roots, change source/type, five-minute scenario-time bucket and authentication context. Exception IDs are excluded. Hash equality is not the clustering test: related but distinct symptoms can have different hashes, with their shared features compared explicitly.

Code prefixes map to families: AUTH → AUTHENTICATION_FAILURE; SRC/REF/CUS → UPSTREAM_DATA_UNAVAILABLE; REC/EXP → MISSING_SOURCE_DATA; SET → PROCESSING_BLOCKED; DEP → DEPENDENCY_FAILURE. Compatibility follows the upstream-to-downstream causal family table and the observed order of failures. Messages themselves are not compared.

## Exact correlation formula

For each pair, score = A + B + C + D + E (maximum 100):

| Signal | Points |
|---|---|
| A — shared dependency | 35 if a shared graph root exists; otherwise 30 for a common direct dependency; otherwise 25 for a common ancestor; otherwise 0 |
| B — temporal proximity | 20 for gap <=30s; 18 for <=90s; 15 for <=180s; otherwise 0 |
| C — error relationship | 15 if a dependency path, event order and directional compatibility all support a causal link; otherwise 0 |
| D — recent change | 20 for equal non-UNKNOWN structured changes, each occurring 0–600s before its exception; otherwise 0 |
| E — graph direction | 10 when a common ancestor has an observed exception no later than both pair members; otherwise 0 |
| F — historical similarity | NO_HISTORY; zero weight |

Exceptions are processed in timestamp/ID order. A new member needs a witnessed common cause, a causal link to the earliest observed member scoring at least 75, and a time gap of at most 180 seconds to every member.

A cluster score is the arithmetic mean of the pair scores from its earliest observed member to every other member. Signal breakdowns are averaged the same way. Singleton groups score 0. HIGH CORRELATION means >=90.

Flagship calculation over 22 source-to-descendant pairs:

- Shared dependency: 35
- Timeline: (3×20 + 8×18 + 11×15) / 22 = 16.772727...
- Error relationship: 15
- Shared change: 20
- Direction: 10
- Total: 96.772727... / 100 (displayed 96.8)

These values arise from the recorded timestamps and topology. There is no hardcoded final percentage.

## Root-cause scoring

Every service is ranked, including healthy Authentication Service. For N exception genomes and a candidate:

- Topology = 35 × (self plus descendants covered) / N.
- Timeline = 20 × (covered exceptions occurring at/after the candidate exception) / N, only if the candidate is an earliest observed failure; otherwise 0.
- Change Event = 20 when the candidate has a known, timely change recorded against itself; otherwise 0.
- Error Evidence = 15 × compatible covered exceptions / N, only when the candidate itself reports authentication failure; otherwise 0.
- Contradictions = max(0, 8 − 4K), where K counts healthy candidate state, a preceding failure elsewhere, and incomplete topology coverage.

Total divided by 100 produces the `confidence` field. A precise expired-credential conclusion additionally requires explicit CREDENTIAL_EXPIRED context and a timely CREDENTIAL_ROTATION_FAILED event. If absent, the conclusion is qualified and contradiction points lose another four, floored at zero.

Flagship: 35 + 20 + 20 + 15 + 8 = 98. Absence of contradictions earns only 8/10 because observational consistency is not certainty. These are heuristic evidence scores, not statistical probabilities. The deterministic analyser implements an interface that a future LLM adapter could share; no external API is required.

## Demo

1. Launch and observe 24 healthy services and zero exceptions (use Reset if an old run is stored).
2. Press Simulate Incident. Watch 23 exceptions propagate; Pause and Resume remain available.
3. Observe the different raw errors. Root causes identified remains zero.
4. After propagation finishes, press Analyse Exception Genomes. Status messages track analysis without artificial sleeps.
5. Observe DIAGNOSED, one cluster and one root-cause candidate. Services stay affected; exceptions stay active.
6. Open Exception Genome. Compare domain symptom cards, inspect a fingerprint, inspect signal scores and see the 23 → 1 → 1 summary.
7. Inspect the directional analytical graph. DataHub is highlighted; all original edges remain.
8. Open Incident Investigation for chronological events, evidence, candidate rankings, alternative explanations, contradictions and causal paths.
9. Read the recommendation-only label. No execution control exists.
10. Open Resolution Centre and follow the [Phase 4 demo](Phase_4_Report.md).

## Tests

```powershell
python -m unittest discover -s tests -v
python -W error::ResourceWarning -m unittest discover -s tests -v
```

Coverage: unchanged Phase 1–2 lifecycle; 23 enriched exceptions; varied raw messages; deterministic signatures independent of IDs; graph ancestry; one 23-member cluster; score arithmetic; unrelated/distant exceptions rejected; missing-change penalty; DataHub ranking; healthy Authentication alternative; evidence and causal chains; missing-expiry qualification; contradictory timeline; persistence/idempotency; reset; early-analysis rejection; legacy migration; connection close/rollback; all analytical graph edges; absence of later-phase surfaces; Streamlit start/pause/resume/analyse/navigation/reset integration.

## Known limitations

- One synthetic scenario and a single-user shared SQLite database. Concurrent demos are not supported.
- Propagation ticks while Command Centre is open, preserving the original behaviour. Finish propagation there before navigating to investigation.
- Analysis is fast; status messages are retained in the status panel but intentionally have no artificial delays.
- Fixed family compatibility and heuristic weights are tailored to the demonstrated operations failure; not validated for production banking incidents.
- Historical similarity is NO_HISTORY. The lab uses deterministic analysis, synthetic execution, and independent verification. See the Phase 5 report for the demo limits.
- Evidence uses synthetic source labels, topology, timestamp and change records; it is not real telemetry. Healthy Authentication Service is an observed state, not a continuously sampled availability guarantee.
- Legacy free-text evidence is not invented during migration. Exact diagnosis can be less confident until Reset creates a fresh structured run.
- Fingerprint five-minute buckets may split similar hashes at boundaries; correlation uses exact time gaps rather than hash equality.

## Validation result

See [Phase_6_Report.md](Phase_6_Report.md) for current validation.


## Phase 7 API

Install the shared dependencies from requirements.txt. Run Streamlit with
`python -m streamlit run app.py` and the HTTP interface in a separate terminal with
`python -m uvicorn api.main:app --host 127.0.0.1 --port 8000`.

Use the same EXCEPTION_GENOME_DB setting in both terminals if overriding the default database.
See [API_CONTRACT.md](API_CONTRACT.md), [N8N_HANDOFF.md](N8N_HANDOFF.md) and
[Phase_7_Report.md](Phase_7_Report.md) for configuration, demo sequences and limits.

