"""Local API for the synthetic Exception Genome workflow."""
from contextlib import asynccontextmanager
from dataclasses import asdict
import hmac
import json
import os
from threading import RLock

from fastapi import Body, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from api.artifacts import (
    AssignmentSummary, ExceptionSummary, ExecutionResponse, ImpactSimulationResponse,
    ResolutionContractResponse, SafetyEvaluationResponse, VerificationResponse,
)
from api.schemas import ExecutionRequest, HealthResponse, IncidentSummary, ReviewRequest, StateRequest, WorkflowResponse
from core.database import initialize
from core.phase4_store import canonical, digest
from services import workflow as flow

VERSION = '7.0'
ASSIGNMENT = '/incidents/{incident_id}/assignments/{assignment_id}'


def build_app(path=flow.DEFAULT_DB, *, api_key=None, demo=None):
    key = os.environ.get('EXCEPTION_GENOME_API_KEY') if api_key is None else api_key
    demo_enabled = os.environ.get('EXCEPTION_GENOME_DEMO_MODE', 'true').lower() == 'true' if demo is None else demo
    lock = RLock()

    @asynccontextmanager
    async def lifespan(app):
        initialize(path)
        with flow.connect(path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS api_receipts (
                key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, status INTEGER NOT NULL, payload TEXT NOT NULL)""")
        yield

    app = FastAPI(title='Exception Genome', version=VERSION, lifespan=lifespan)

    def error(status, code, message, details=None):
        return JSONResponse(status_code=status, content={'error': {
            'code': code, 'message': message, 'details': details or {},
        }})

    @app.exception_handler(KeyError)
    async def missing(request, exc):
        return error(404, 'NOT_FOUND', f'Unknown identifier: {exc.args[0]}')

    @app.exception_handler(ValueError)
    async def conflicted(request, exc):
        message = str(exc)
        code = message if message.isupper() and ' ' not in message else 'WORKFLOW_CONFLICT'
        return error(409, code, message)

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        detail = [{'field': list(item['loc']), 'message': item['msg']} for item in exc.errors()]
        return error(422, 'INVALID_REQUEST', 'Request validation failed.', {'fields': detail})

    @app.middleware('http')
    async def mutation_controls(request: Request, call_next):
        if request.method not in ('POST', 'PATCH', 'PUT', 'DELETE'):
            return await call_next(request)
        if key and not hmac.compare_digest(request.headers.get('x-api-key', '').encode(), key.encode()):
            return error(401, 'UNAUTHORISED', 'A valid demo API key is required.')
        if request.url.path.startswith('/demo/') and not demo_enabled:
            return error(403, 'DEMO_DISABLED', 'Synthetic scenario mutations are disabled.')
        return await call_next(request)

    def mutate(key, operation, arguments, callback, status=200):
        with lock:
            if key:
                if len(key) > 160 or not key.strip():
                    return error(400, 'INVALID_IDEMPOTENCY_KEY', 'Use a non-empty key up to 160 characters.')
                fingerprint = digest([operation, arguments])
                with flow.connect(path) as db:
                    record = db.execute('SELECT * FROM api_receipts WHERE key=?', (key,)).fetchone()
                if record:
                    if record['fingerprint'] != fingerprint:
                        return error(409, 'IDEMPOTENCY_CONFLICT', 'This idempotency key belongs to a different request.')
                    return JSONResponse(json.loads(record['payload']), status_code=record['status'])
            payload = callback()
            if key:
                with flow.connect(path) as db:
                    db.execute('INSERT INTO api_receipts VALUES (?,?,?,?)', (key, fingerprint, status, canonical(payload)))
            return JSONResponse(json.loads(canonical(payload)), status_code=status)

    @app.get('/health', response_model=HealthResponse)
    def health():
        with flow.connect(path) as db:
            db.execute('SELECT 1').fetchone()
        return dict(status='ok', database_status='connected', version=VERSION,
                    mode='demo' if demo_enabled else 'restricted', application='Exception Genome', demo_mode=demo_enabled)

    @app.get('/incidents', response_model=list[IncidentSummary])
    def incidents():
        return flow.snapshot(path)['incidents']

    @app.get('/incidents/{incident_id}')
    def incident(incident_id: str):
        row = flow.incident(incident_id, path)
        detail = assignments(incident_id)
        exception_rows = exceptions(incident_id)
        return dict(row, incident=row, assignments=detail,
                    exception_counts=dict(total=len(exception_rows),
                                          active=sum(r['status'] != 'RESOLVED' for r in exception_rows)),
                    workflow=flow.workflow_status(incident_id, path))

    @app.get('/incidents/{incident_id}/exceptions', response_model=list[ExceptionSummary])
    def exceptions(incident_id: str):
        flow.incident(incident_id, path)
        return [r for r in flow.snapshot(path)['exceptions'] if r['incident_id'] == incident_id]

    @app.get('/incidents/{incident_id}/assignments', response_model=list[AssignmentSummary])
    def assignments(incident_id: str):
        flow.incident(incident_id, path)
        return [flow.assignment(incident_id, r['id'], path)
                for r in flow.load(path, incident_id)['correlation_clusters']]

    @app.get(ASSIGNMENT, response_model=AssignmentSummary)
    def assignment(incident_id: str, assignment_id: str):
        return flow.assignment(incident_id, assignment_id, path)

    @app.get('/incidents/{incident_id}/workflow', response_model=WorkflowResponse)
    def workflow(incident_id: str):
        return flow.workflow_status(incident_id, path)

    @app.get('/demo/scenarios')
    def scenarios():
        return [dict(scenario_id=s.scenario_id, incident_id=s.incident_id, title=s.title)
                for s in flow.SCENARIOS.values()]

    @app.post('/demo/scenarios/{scenario_id}/start', status_code=201)
    def start(scenario_id: str, idempotency_key: str | None = Header(default=None)):
        return mutate(idempotency_key, 'start', scenario_id, lambda: flow.start_scenario(scenario_id, path), 201)

    @app.post('/demo/incidents/{incident_id}/advance')
    def advance(incident_id: str, idempotency_key: str | None = Header(default=None)):
        return mutate(idempotency_key, 'advance_scenario', incident_id, lambda: flow.advance_scenario(incident_id, path))

    @app.post('/demo/reset/current')
    @app.post('/demo/reset/full')
    def reset(request: Request, idempotency_key: str | None = Header(default=None)):
        preserve = request.url.path.endswith('/current')
        def perform():
            flow.reset(path, preserve_memory=preserve)
            with flow.connect(path) as db:
                db.execute('DELETE FROM api_receipts')
            return {'reset': 'current' if preserve else 'full', 'preserved_memory': preserve}
        return mutate(idempotency_key, 'reset', preserve, perform)

    @app.post('/incidents/{incident_id}/analyse')
    def analyse(incident_id: str, idempotency_key: str | None = Header(default=None)):
        flow.incident(incident_id, path)
        return mutate(idempotency_key, 'analyse', incident_id, lambda: flow.analyse(incident_id, path))

    def scoped(operation, incident_id, assignment_id, request, key, callback, status=200):
        def perform():
            flow.assignment(incident_id, assignment_id, path)
            flow.check_expectations(incident_id, assignment_id, request.expected_contract_hash,
                                    request.expected_state_digest, path)
            return callback()
        return mutate(key, operation, [incident_id, assignment_id, request.model_dump()], perform, status)

    @app.post(ASSIGNMENT + '/contract', status_code=201, response_model=ResolutionContractResponse)
    def contract(incident_id: str, assignment_id: str, body: StateRequest = Body(default=StateRequest()),
                 idempotency_key: str | None = Header(default=None)):
        return scoped('contract', incident_id, assignment_id, body, idempotency_key,
                      lambda: asdict(flow.create_contract(incident_id, path, cluster_id=assignment_id)), 201)

    @app.post(ASSIGNMENT + '/safety', response_model=SafetyEvaluationResponse)
    def safety(incident_id: str, assignment_id: str, body: StateRequest = Body(default=StateRequest()),
               idempotency_key: str | None = Header(default=None)):
        def evaluate():
            result = flow.evaluate_safety_gate(incident_id, path, cluster_id=assignment_id)
            return dict(result, overall_result=result['decision'])
        return scoped('safety', incident_id, assignment_id, body, idempotency_key,
                                            evaluate)

    @app.post(ASSIGNMENT + '/simulate-impact', response_model=ImpactSimulationResponse)
    def simulate(incident_id: str, assignment_id: str, body: StateRequest = Body(default=StateRequest()),
                 idempotency_key: str | None = Header(default=None)):
        def perform():
            result = flow.run_impact_simulation(incident_id, path, cluster_id=assignment_id)
            result['readiness'] = flow.record_readiness(incident_id, path, cluster_id=assignment_id)['status']
            return result
        return scoped('simulate', incident_id, assignment_id, body, idempotency_key, perform)

    @app.get('/reviews')
    def reviews():
        with flow.connect(path) as db:
            return flow.cases(db)

    @app.get('/reviews/{review_id}')
    def review(review_id: str):
        found = next((r for r in reviews() if r['review_id'] == review_id), None)
        if found is None:
            raise KeyError(review_id)
        return found

    def decide(review_id, body):
        case = review(review_id)
        flow.check_expectations(case['incident_id'], case['cluster_id'], body.expected_contract_hash,
                                body.expected_state_digest, path)
        with flow.connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            result = flow.decide(db, review_id, body.reviewer_identity, body.decision, body.reason)
        if body.decision == 'APPROVE CONTROLLED ACTION':
            flow.record_readiness(case['incident_id'], path, cluster_id=case['cluster_id'])
        return result

    @app.post('/reviews/{review_id}/decision', status_code=201)
    def review_decision(review_id: str, body: ReviewRequest, idempotency_key: str | None = Header(default=None)):
        return mutate(idempotency_key, 'review', [review_id, body.model_dump()], lambda: decide(review_id, body), 201)

    @app.post(ASSIGNMENT + '/request-evidence', status_code=201)
    def request_evidence(incident_id: str, assignment_id: str, body: ReviewRequest,
                         idempotency_key: str | None = Header(default=None)):
        flow.assignment(incident_id, assignment_id, path)
        if body.decision != 'REQUEST MORE EVIDENCE':
            return error(400, 'INVALID_DECISION', 'This route only records requests for evidence.')
        return review_decision('REV-' + assignment_id, body, idempotency_key)

    @app.get('/incidents/{incident_id}/evidence')
    def evidence(incident_id: str):
        flow.incident(incident_id, path)
        with flow.connect(path) as db:
            return flow.evidence_records(db, incident_id)

    @app.post('/demo/incidents/{incident_id}/assignments/{assignment_id}/evidence/{evidence_type}', status_code=201)
    def inject(incident_id: str, assignment_id: str, evidence_type: str,
               idempotency_key: str | None = Header(default=None)):
        flow.assignment(incident_id, assignment_id, path)
        if evidence_type.upper() != 'DEPENDENCY_PROBE':
            raise KeyError(evidence_type)
        return mutate(idempotency_key, 'inject', [incident_id, assignment_id],
                      lambda: flow.inject_probe(incident_id, assignment_id, path), 201)

    @app.post(ASSIGNMENT + '/execute', response_model=ExecutionResponse)
    def execute(incident_id: str, assignment_id: str, body: ExecutionRequest = Body(default=ExecutionRequest()),
                idempotency_key: str | None = Header(default=None)):
        if body.mode != 'NORMAL' and not demo_enabled:
            return error(403, 'DEMO_DISABLED', 'Failure injection is disabled.')
        def perform():
            with flow.connect(path) as db:
                contract = flow.current_contract(db, incident_id, assignment_id)
            if not contract:
                raise flow.Conflict('CONTRACT_MISSING')
            result = flow.execute_controlled(incident_id, path, expected_hash=body.expected_contract_hash or contract.contract_hash,
                                             mode=body.mode, cluster_id=assignment_id,
                                             expected_state_digest=body.expected_state_digest)
            if result['status'] == 'BLOCKED':
                raise flow.Conflict(result['failure_reason'])
            return {k: v for k, v in result.items() if k != 'previous_state_snapshot'}
        return scoped('execute', incident_id, assignment_id, body, idempotency_key, perform)

    @app.post('/executions/{execution_id}/advance', response_model=ExecutionResponse)
    @app.post('/executions/{execution_id}/verify', response_model=VerificationResponse)
    def progress(execution_id: str, request: Request, idempotency_key: str | None = Header(default=None)):
        verify = request.url.path.endswith('/verify')
        operation = 'verify' if verify else 'advance_recovery'
        def perform():
            record = flow.execution_record(execution_id, path)
            with flow.connect(path) as db:
                from core.phase5_store import execution
                current = execution(db, record['incident_id'], record.get('cluster_id'))
            if not current or current['execution_id'] != execution_id:
                raise flow.Conflict('EXECUTION_STALE')
            result = (flow.run_verification if verify else flow.advance_recovery)(record['incident_id'], path, cluster_id=record.get('cluster_id'))
            payload = {k: v for k, v in result.items() if k != 'previous_state_snapshot'}
            if verify:
                final = flow.execution_record(execution_id, path)
                payload.update(result=result['status'], rollback_status=final['rollback_status'],
                               incident_status=flow.incident(record['incident_id'], path)['status'])
            return payload
        return mutate(idempotency_key, operation, execution_id, perform)

    @app.get('/memory')
    def memory():
        with flow.connect(path) as db:
            return flow.history(db)

    @app.get('/memory/patterns')
    def patterns():
        groups = flow.patterns(memory())
        return {'patterns': groups, 'recommendations': flow.recommendations(groups)}

    @app.get('/memory/patterns/{pattern_id}')
    def pattern(pattern_id: str):
        found = next((r for r in patterns()['patterns'] if r['pattern_id'] == pattern_id), None)
        if found is None:
            raise KeyError(pattern_id)
        return found

    @app.get('/audit')
    def audit(incident_id: str | None = None, assignment_id: str | None = None,
              actor: str | None = None, action: str | None = None,
              result: str | None = None, contract_hash: str | None = None):
        with flow.connect(path) as db:
            events = flow.timeline(db)
        filters = dict(incident_id=incident_id, cluster_id=assignment_id, actor=actor, action=action, result=result, contract_hash=contract_hash)
        return [row for row in events if all(value is None or row.get(key) == value for key, value in filters.items())]

    @app.get('/dashboard/summary')
    def summary():
        state = flow.snapshot(path)
        records = memory()
        data = flow.load(path)
        clusters = data['correlation_clusters']
        groups = flow.patterns(records)
        reviewed = len({r['incident_id'] for r in reviews()})
        total = len(state['incidents'])
        resolved = {r['id'] for r in state['incidents'] if r['status'] == 'RESOLVED'}
        human = {r['source_incident_id'] for r in records if r['human_review_required']} & resolved
        metrics = dict(human_review_count=reviewed,
                       verification_failures=sum(r['failure_count'] for r in records),
                       rollbacks=sum(r['rollback_result'] == 'ROLLBACK_COMPLETED' for r in records),
                       root_causes_identified=len(data['root_cause_analyses']),
                       compression_metrics=dict(exceptions=sum(len(r['members']) for r in clusters),
                                                assignments=len(clusters),
                                                multi_member_clusters=sum(len(r['members']) > 1 for r in clusters)),
                       autonomous_resolution_rate=(len(resolved) - len(human)) / total if total else 0,
                       human_reviewed_resolution_rate=len(human) / total if total else 0,
                       recurring_patterns=[r['pattern_id'] for r in groups if r['occurrences'] > 1],
                       prevention_recommendations=flow.recommendations(groups))
        return dict(**metrics, active_incidents=sum(row['status'] != 'RESOLVED' for row in state['incidents']),
                    resolved_incidents=sum(row['status'] == 'RESOLVED' for row in state['incidents']),
                    active_exceptions=sum(row['status'] != 'RESOLVED' for row in state['exceptions']),
                    verified_history=len({row['source_incident_id'] for row in memory() if row['success_count']}))

    return app


app = build_app()






