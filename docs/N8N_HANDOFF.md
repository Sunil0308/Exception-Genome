# Exception Genome future n8n handoff

Base URL `http://127.0.0.1:8000` for a workflow client on the same machine. OpenAPI is at `/openapi.json`. The simulator uses the same SQLite database as Streamlit. This handoff documents the interface only.

1. Start an authorised demo with `POST /demo/scenarios/{scenario_id}/start`. Use the returned incident ID. Advance synthetic propagation until `advanced` is false.
2. Call `POST /incidents/{incident_id}/analyse` and inspect the incident workflow endpoint and assignments. Branch on the server-emitted next actions. Keep one workflow item per assignment.
3. Create a scoped contract and carry its exact hash to subsequent requests. Evaluate safety. An approved decision can proceed to simulation. For eligible A2 cases, run the simulation and wait for a human decision. Negative or uncertain decisions pause or escalate.
4. Confirm the impact result is `PASS`. If human authority is required, wait for a recorded approval bound to the same contract, policy, simulation and state. The workflow client must never substitute its own approval.
5. Execute using the current contract hash. Persist the returned execution ID. Advance only that execution until status is `AWAITING_VERIFICATION`. Use a distinct idempotency key for each intended advancement.
6. Run verification. `VERIFIED` closes the assignment. Read incident status separately because other assignments may still be active. `FAILED` or `INCONCLUSIVE` requires inspecting audit and review records before taking another action.
7. Fetch `/audit` by incident and `/memory` for completed historical evidence. Review prevention recommendations as advisory material.

Use a stable unique idempotency key for each logical mutation and reuse it across transport retries only. On 409, fetch current state and stop automatic retries until the contract or authority has been refreshed. On 422, fix the request. Treat 401 or disabled demo mutations as configuration errors. Reset endpoints are synthetic demo controls and are not part of an ordinary incident workflow. See [API_CONTRACT.md](API_CONTRACT.md) for endpoint details.

