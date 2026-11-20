"""Append authenticated-by-the-demo probe observations and version the diagnosis."""
import json
from datetime import datetime, timedelta

import networkx as nx

from core.phase4_store import canonical, identifier, now
from core.review import audit_event, cases
from core.service_graph import build_graph
from core.resolution_contract import read_context


def initialize_evidence(db):
    db.execute("""CREATE TABLE IF NOT EXISTS intake_evidence (
        id TEXT PRIMARY KEY, incident_id TEXT NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
        assignment_id TEXT NOT NULL REFERENCES correlation_clusters(id) ON DELETE CASCADE,
        version INTEGER NOT NULL, payload TEXT NOT NULL, UNIQUE(assignment_id,version))""")


def evidence_records(db, incident_id):
    return [json.loads(row[0]) for row in db.execute(
        'SELECT payload FROM intake_evidence WHERE incident_id=? ORDER BY assignment_id,version', (incident_id,))]


def demo_dependency_probe(db, incident_id, assignment_id):
    case = next((r for r in cases(db) if r['review_id'] == 'REV-' + assignment_id
                 and r['incident_id'] == incident_id), None)
    if not case or case['current_status'] != 'REQUEST MORE EVIDENCE':
        raise ValueError('EVIDENCE_REQUEST_REQUIRED')
    context = read_context(db, incident_id)
    if context['incident'].get('status') != 'DIAGNOSED':
        raise ValueError('INCIDENT_NOT_DIAGNOSED')
    old = case['diagnosis']
    if old.get('diagnosis_outcome') != 'NO_CONFIDENT_ROOT_CAUSE':
        raise ValueError('DEMO_PROBE_NOT_APPLICABLE')
    cluster = next(row for row in context['analysis']['correlation_clusters'] if row['id'] == assignment_id)
    observed = [row for row in context['exceptions'] if row['id'] in cluster['members']]
    graph = build_graph(context['services'])
    if len(observed) != 1:
        raise ValueError('DEMO_PROBE_REQUIRES_ISOLATED_SYMPTOM')
    symptom = observed[0]
    candidates = sorted(graph.predecessors(symptom['service_id']))
    if len(candidates) != 1:
        raise ValueError('DEMO_PROBE_REQUIRES_ONE_DIRECT_UPSTREAM')
    upstream = candidates[0]
    symptom_at = datetime.fromisoformat(symptom['timestamp'])
    version = old['diagnosis_version'] + 1
    record = dict(evidence_id=identifier('EVD', incident_id), incident_id=incident_id,
                  assignment_id=assignment_id, evidence_type='DEPENDENCY_PROBE',
                  source='SYNTHETIC_DEPENDENCY_TRACE', timestamp=now(), reliability='HIGH',
                  created_by='DEMO_SIMULATOR', version=version,
                  structured_payload=dict(source_service=upstream, source_health_at_failure='FAILED',
                                          observed_at=(symptom_at - timedelta(seconds=3)).isoformat(),
                                          symptom_service=symptom['service_id'],
                                          symptom_timestamp=symptom['timestamp'], diagnostic='UPSTREAM_TIMEOUT'))
    db.execute('INSERT INTO intake_evidence VALUES (?,?,?,?,?)',
               (record['evidence_id'], incident_id, assignment_id, version, canonical(record)))
    probe = record['structured_payload']
    criteria = {
        'Dependency topology': 35 if nx.has_path(graph, probe['source_service'], probe['symptom_service']) else 0,
        'Timing': 20 if probe['observed_at'] < probe['symptom_timestamp'] else 0,
        'Structured upstream observation': 30 if probe['source_health_at_failure'] == 'FAILED'
                                                     and record['reliability'] == 'HIGH' else 0,
    }
    score = sum(criteria.values())
    updated = dict(old, diagnosis_version=version, analysis_id=f'RCA-{assignment_id}-V{version}',
                   root_cause_service_id=upstream, root_cause_service=graph.nodes[upstream]['name'],
                   root_cause=f"{graph.nodes[upstream]['name']} upstream timeout supported by dependency trace",
                   diagnosis_outcome='ROOT_CAUSE_CANDIDATE' if score >= 75 else 'NO_CONFIDENT_ROOT_CAUSE',
                   confidence=score / 100, confidence_breakdown=criteria,
                   supporting_evidence=[*old['supporting_evidence'], f"Structured trace {record['evidence_id']}"],
                   conflicting_evidence=['Service recovery action requires separately verified operational evidence.'],
                   recommended_action='Review the upstream timeout and collect action-specific evidence.')
    db.execute('UPDATE root_cause_analyses SET payload=? WHERE cluster_id=?', (canonical(updated), assignment_id))
    contract_ids = [r[0] for r in db.execute('SELECT id FROM resolution_contracts WHERE cluster_id=? AND status=?',
                                            (assignment_id, 'CURRENT'))]
    for contract_id in contract_ids:
        db.execute("UPDATE resolution_contracts SET status='SUPERSEDED' WHERE id=?", (contract_id,))
        for table in ('safety_evaluations', 'impact_simulations', 'execution_readiness'):
            db.execute(f"UPDATE {table} SET status='STALE' WHERE contract_id=?", (contract_id,))
    audit_event(db, incident_id, assignment_id, 'EVIDENCE_INTAKE', record['evidence_id'], record)
    audit_event(db, incident_id, assignment_id, 'DIAGNOSIS_VERSIONED', updated['analysis_id'],
                {'previous': old, 'current': updated, 'superseded_contracts': contract_ids})
    return dict(evidence=record, previous_diagnosis=old, diagnosis=updated, superseded_contracts=contract_ids)

