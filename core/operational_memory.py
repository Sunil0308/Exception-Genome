"""Historical evidence from completed synthetic cases."""
import json

from core.phase4_store import canonical, digest, now
from core.resolution_contract import current_contract, read_context


def initialize_memory(db):
    db.execute("""CREATE TABLE IF NOT EXISTS operational_memory (
        id TEXT PRIMARY KEY, incident_id TEXT NOT NULL, cluster_id TEXT NOT NULL,
        pattern_id TEXT NOT NULL, outcome TEXT NOT NULL, created_at TEXT NOT NULL,
        payload TEXT NOT NULL, UNIQUE(incident_id,cluster_id))""")


def fingerprint(genomes, root):
    return dict(root_dependency=root.get('root_cause_service_id'),
                normalized_error_families=sorted({g['normalized_error_family'] for g in genomes}),
                affected_services=sorted({g['service_id'] for g in genomes}),
                affected_domains=sorted({g['domain'] for g in genomes}),
                change_event_type=sorted({g['change_event_type'] for g in genomes}),
                authentication_context=sorted({g['authentication_context'] for g in genomes}),
                topology=sorted({tuple(g['dependency_path']) for g in genomes}),
                signatures=sorted({g['genome_signature'] for g in genomes}))


def record_completed_case(db, execution, verification):
    incident_id = execution['incident_id']
    context = read_context(db, incident_id)
    contract = current_contract(db, incident_id, execution.get('cluster_id'))
    if not contract or not contract.evidence_snapshot or not contract.root_cause or not execution['action_applied']:
        return
    verified = verification['status'] == 'VERIFIED' and (context['incident']['status'] == 'RESOLVED' or (execution.get('multi_assignment') and execution['status'] == 'COMPLETED'))
    if not verified and context['incident']['status'] != 'HUMAN_REVIEW_REQUIRED' and execution['status'] != 'ESCALATED':
        return
    evidence = contract.evidence_snapshot
    genomes = [g for g in context['analysis']['exception_genomes']
               if g['exception_id'] in evidence['genome_signatures']]
    features = fingerprint(genomes, evidence['diagnosis'])
    pattern = 'PAT-' + digest({k: v for k, v in features.items() if k != 'signatures'})[:16]
    identity = 'MEM-' + digest([incident_id, contract.cluster_id])[:20]
    outcome = 'VERIFIED SUCCESS' if verified else 'FAILED REMEDIATION'
    timestamp = now()
    data = dict(memory_id=identity, source_incident_id=incident_id, source_cluster_id=contract.cluster_id,
                genome_pattern=features, pattern_id=pattern, root_cause=contract.root_cause,
                evidence_summary=evidence['diagnosis']['supporting_evidence'], resolution_action=contract.action_type,
                action_parameters_without_secrets={k: v for k, v in contract.action_parameters.items()
                                                  if k == 'credential_version'},
                autonomy_path=contract.autonomy_class, human_review_required=bool(execution.get('review_decision_id')) or not verified,
                execution_result=execution['result'], verification_result=verification['status'],
                rollback_result=execution['rollback_status'], final_outcome=outcome,
                created_at=timestamp, last_seen=timestamp, success_count=int(verified),
                failure_count=int(not verified), pattern_version=1)
    db.execute('INSERT OR IGNORE INTO operational_memory VALUES (?,?,?,?,?,?,?)',
               (identity, incident_id, contract.cluster_id, pattern, outcome, timestamp, canonical(data)))


def history(db):
    return [json.loads(row[0]) for row in db.execute(
        'SELECT payload FROM operational_memory ORDER BY created_at DESC,id')]


def patterns(records):
    groups = {}
    for record in records:
        group = groups.setdefault(record['pattern_id'], dict(pattern_id=record['pattern_id'],
                                  root_cause=record['root_cause'], occurrences=0, verified=0, failed=0,
                                  last_seen=record['last_seen'], records=[]))
        group['occurrences'] += 1
        group['verified'] += record['success_count']
        group['failed'] += record['failure_count']
        group['last_seen'] = max(group['last_seen'], record['last_seen'])
        group['records'].append(record)
    for group in groups.values():
        group['success_rate'] = group['verified'] / group['occurrences']
    return list(groups.values())


def similar_cases(db, genomes, root):
    features = json.loads(canonical(fingerprint(genomes, root)))
    matches = []
    rates = {group['pattern_id']: group['success_rate'] for group in patterns(history(db))}
    for record in history(db):
        candidate = record['genome_pattern']
        if candidate['root_dependency'] != features['root_dependency']:
            continue
        same = [key for key in features if features[key] == candidate[key]]
        score = 100 * len(same) / len(features)
        if score >= 50:
            matches.append(dict(memory_id=record['memory_id'], similarity_score=score,
                                matched_evidence=same, different_evidence=sorted(set(features) - set(same)),
                                historical_outcome=record['final_outcome'], previous_action=record['resolution_action'],
                                previous_verification_result=record['verification_result'],
                                previous_success_rate=rates[record['pattern_id']]))
    return sorted(matches, key=lambda row: (-row['similarity_score'], row['memory_id']))



