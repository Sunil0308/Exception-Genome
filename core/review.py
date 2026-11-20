"""Persist synthetic reviewer decisions for cases that need investigation."""
import json

from core.phase4_store import canonical, digest, identifier, now
from core.resolution_contract import current_contract

REVIEWERS = ('Operations Reviewer', 'Senior Operations Reviewer', 'Risk Reviewer')
APPROVE = "APPROVE CONTROLLED ACTION"
DECISIONS = ('REJECT ACTION', 'REQUEST MORE EVIDENCE', 'ESCALATE', 'CLOSE AS NO ACTION REQUIRED')


def initialize_review(db):
    db.execute("""CREATE TABLE IF NOT EXISTS analysis_events (
        id INTEGER PRIMARY KEY, incident_id TEXT NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
        cluster_id TEXT, created_at TEXT NOT NULL, action TEXT NOT NULL,
        artifact TEXT NOT NULL, payload TEXT NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS review_decisions (
        id TEXT PRIMARY KEY, incident_id TEXT NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
        cluster_id TEXT NOT NULL REFERENCES correlation_clusters(id), created_at TEXT NOT NULL,
        payload TEXT NOT NULL)""")


def cases(db):
    result = []
    for row in db.execute("""SELECT r.payload AS diagnosis,i.status,i.started_at FROM root_cause_analyses r
                                JOIN correlation_clusters c ON c.id=r.cluster_id
                                JOIN incidents i ON i.id=c.incident_id"""):
        diagnosis = json.loads(row['diagnosis'])
        if not diagnosis.get('cluster_id') or row['status'] == 'RESOLVED':
            continue
        incident_id = diagnosis['incident_id']
        contract = current_contract(db, incident_id, diagnosis['cluster_id'])
        if contract and contract.cluster_id != diagnosis['cluster_id']:
            contract = None
        reason = 'Insufficient diagnostic evidence' if diagnosis.get('diagnosis_outcome') == 'NO_CONFIDENT_ROOT_CAUSE' else ''
        if diagnosis['root_cause_service_id'] == 'merchant' and 'local processing worker' in diagnosis['root_cause']:
            reason = 'Conditional service restart requires human authority'
        if row['status'] == 'HUMAN_REVIEW_REQUIRED':
            reason = 'Execution outcome requires human review'
        if contract:
            for table, statuses in (
                ('safety_evaluations', {'BLOCKED', 'HUMAN_REVIEW_REQUIRED'}),
                ('impact_simulations', {'FAIL', 'INCONCLUSIVE'}),
            ):
                status = db.execute(f'SELECT status FROM {table} WHERE contract_id=? ORDER BY rowid DESC LIMIT 1',
                                    (contract.contract_id,)).fetchone()
                if status and status[0] in statuses:
                    reason = f'{table.replace("_", " ")} · {status[0]}'
        attempt = db.execute(
            'SELECT e.payload FROM executions e JOIN resolution_contracts c ON c.id=e.contract_id '
            'WHERE e.incident_id=? AND c.cluster_id=? ORDER BY e.rowid DESC LIMIT 1',
            (incident_id, diagnosis['cluster_id'])).fetchone()
        attempt = json.loads(attempt[0]) if attempt else None
        if attempt and attempt.get('status') in ('BLOCKED', 'FAILED', 'ROLLED_BACK', 'ESCALATED'):
            reason = attempt.get('failure_reason') or attempt['status']
        if not reason:
            continue
        verification = db.execute('SELECT payload FROM verification_results WHERE execution_id=?',
                                  (attempt['execution_id'],)).fetchone() if attempt else None
        latest = db.execute('SELECT payload FROM review_decisions WHERE cluster_id=? ORDER BY rowid DESC LIMIT 1',
                            (diagnosis['cluster_id'],)).fetchone()
        status = json.loads(latest[0])['decision'] if latest else 'OPEN'
        if status == APPROVE and not current_approval(db, contract):
            status = 'OPEN'
        result.append(dict(review_id='REV-' + diagnosis['cluster_id'], incident_id=incident_id,
                           cluster_id=diagnosis['cluster_id'], reason=reason, created_at=row['started_at'],
                           severity='HIGH', current_status=status,
                                                      execution=attempt, verification=json.loads(verification[0]) if verification else None,
                           diagnosis=diagnosis, contract_id=contract.contract_id if contract else None,
                           contract_hash=contract.contract_hash if contract else None))
    return result


def decide(db, review_id, reviewer, decision, reason):
    if reviewer not in REVIEWERS or decision not in (*DECISIONS, APPROVE) or not reason.strip():
        raise ValueError('Select a supported decision and provide its rationale.')
    case = next((case for case in cases(db) if case['review_id'] == review_id), None)
    if not case or case['current_status'] not in ('OPEN', 'REQUEST MORE EVIDENCE'):
        raise ValueError('This review case is no longer open.')
    contract = current_contract(db, case['incident_id'], case['cluster_id'])
    if contract and contract.cluster_id == case['cluster_id'] and contract.autonomy_class == 'A3':
        if decision not in ('ESCALATE', 'REJECT ACTION'):
            raise ValueError('A prohibited action can only be rejected or escalated.')
    approval_scope = technical_review(db, contract) if decision == APPROVE else None
    if decision == APPROVE and not approval_scope:
        raise ValueError('Approval requires a current eligible A2 contract and passing projection.')
    record = dict(approval_scope=approval_scope, review_decision_id=identifier('DEC', case['incident_id']),
                  review_id=review_id, incident_id=case['incident_id'], cluster_id=case['cluster_id'],
                  contract_id=case['contract_id'], contract_hash=case['contract_hash'], reviewer_identity=reviewer,
                  decision=decision, reason=reason.strip(), created_at=now(), evidence_snapshot=case['diagnosis'])
    record['decision_hash'] = digest({key: val for key, val in record.items()
                                      if key not in ('created_at', 'review_decision_id')})
    db.execute('INSERT INTO review_decisions VALUES (?,?,?,?,?)', (
        record['review_decision_id'], case['incident_id'], case['cluster_id'], record['created_at'], canonical(record)))
    return record


def append_diagnostic_record(db, review_id, observation):
    case = next((row for row in cases(db) if row['review_id'] == review_id), None)
    if not case or case['current_status'] != 'REQUEST MORE EVIDENCE' or not observation.strip():
        raise ValueError('Request more evidence before recording a new observation.')
    previous = case['diagnosis']
    root = dict(previous)
    version = root['diagnosis_version'] + 1
    root['supporting_evidence'] = [*root['supporting_evidence'], observation.strip()]
    root['diagnosis_version'] = version
    root['analysis_id'] = f"RCA-{case['cluster_id']}-V{version}"
    db.execute('UPDATE root_cause_analyses SET payload=? WHERE cluster_id=?', (canonical(root), case['cluster_id']))
    audit_event(db, case['incident_id'], case['cluster_id'], 'DIAGNOSIS_VERSIONED', root['analysis_id'],
                {'version': version, 'observation': observation.strip(), 'previous': previous})
    if case['contract_id']:
        contract_id = case['contract_id']
        db.execute("UPDATE resolution_contracts SET status='SUPERSEDED' WHERE id=?", (contract_id,))
        for table in ('safety_evaluations', 'impact_simulations', 'execution_readiness'):
            db.execute(f"UPDATE {table} SET status='STALE' WHERE contract_id=?", (contract_id,))
    return root


def audit_event(db, incident_id, cluster_id, action, artifact, evidence):
    db.execute('INSERT INTO analysis_events VALUES (NULL,?,?,?,?,?,?)',
               (incident_id, cluster_id, now(), action, artifact, canonical(evidence)))



def technical_review(db, contract):
    from core.action_registry import RESTART
    from core.impact_simulator import review_simulation_eligible
    from core.phase4_store import latest
    from core.resolution_contract import read_context
    from core.safety_gate import assess

    if not contract or contract.action_type != RESTART or contract.target_service not in ('merchant', 'scheduler', 'event_bus'):
        return None
    assessment = assess(contract, contract, read_context(db, contract.incident_id))
    gate = latest(db, 'safety_evaluations', contract.contract_id)
    simulation = latest(db, 'impact_simulations', contract.contract_id)
    if not (review_simulation_eligible(gate, assessment) and simulation
            and simulation['record_status'] == simulation['result'] == 'PASS'
            and not simulation['demonstration_only']
            and simulation['evaluation_id'] == gate['evaluation_id']
            and simulation['contract_hash'] == contract.contract_hash
            and simulation['input_state_digest'] == assessment['input_state_digest']):
        return None
    return dict(input_state_digest=assessment['input_state_digest'],
                evaluation_id=gate['evaluation_id'], simulation_id=simulation['simulation_id'])


def current_approval(db, contract):
    scope = technical_review(db, contract)
    if not scope:
        return None
    row = db.execute('SELECT payload FROM review_decisions WHERE cluster_id=? ORDER BY rowid DESC LIMIT 1',
                     (contract.cluster_id,)).fetchone()
    if not row:
        return None
    record = json.loads(row[0])
    verified_hash = digest({k: v for k, v in record.items()
                            if k not in ('created_at', 'review_decision_id', 'decision_hash')})
    if (record['decision'] == APPROVE and record['contract_id'] == contract.contract_id
            and record['contract_hash'] == contract.contract_hash and record['approval_scope'] == scope
            and record['reviewer_identity'] in REVIEWERS and record['decision_hash'] == verified_hash):
        return record
    return None




