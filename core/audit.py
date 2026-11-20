"""Read existing artifacts and lifecycle records as a single ordered timeline."""
import json


def live_timeline(db):
    events = []
    for row in db.execute('SELECT * FROM incidents'):
        events.append(dict(timestamp=row['started_at'], incident_id=row['id'], actor='SIMULATOR',
                           action='INCIDENT_DETECTED', source='incidents', artifact=row['id']))
    for row in db.execute('SELECT * FROM exceptions'):
        events.append(dict(timestamp=row['timestamp'], incident_id=row['incident_id'], actor='SIMULATOR',
                           action='EXCEPTION_GENERATED', source='exceptions', artifact=row['id']))
    queries = (
        ("SELECT a.*,c.cluster_id,c.contract_hash FROM phase4_audit_events a JOIN resolution_contracts c ON c.id=a.contract_id",
         'occurred_at', 'event_type', 'PHASE_4', 'contract_id', 'phase4_audit_events'),
        ('SELECT * FROM execution_steps', 'timestamp', 'action', None, 'execution_id', 'execution_steps'),
        ('SELECT * FROM analysis_events', 'created_at', 'action', 'ANALYSER', 'artifact', 'analysis_events'),
        ('SELECT * FROM review_decisions', 'created_at', None, 'REVIEWER', 'id', 'review_decisions'),
        ('SELECT * FROM operational_memory', 'created_at', None, 'SYSTEM', 'id', 'operational_memory'),
    )
    for sql, time, action, actor, artifact, source in queries:
        for item in db.execute(sql):
            row = dict(item)
            evidence = json.loads(row.get('payload') or row.get('evidence') or '{}')
            events.append(dict(timestamp=row[time], incident_id=row['incident_id'],
                               cluster_id=row.get('cluster_id'), actor=evidence.get('reviewer_identity', actor or row.get('actor')),
                               action=row[action] if action else 'REVIEW_DECISION' if actor == 'REVIEWER' else 'MEMORY_CREATED',
                               source=source, artifact=row[artifact], decision=row.get('decision') or evidence.get('decision'),
                               result=row.get('result') or evidence.get('result') or row.get('outcome'),
                               contract_hash=row.get('contract_hash') or evidence.get('contract_hash'), evidence=evidence))
    from core.operational_memory import history, patterns
    from core.prevention_engine import recommendations
    for group in patterns(history(db)):
        for insight in recommendations([group]):
            record = max(group['records'], key=lambda row: row['created_at'])
            events.append(dict(timestamp=record['created_at'], incident_id=record['source_incident_id'],
                               cluster_id=record['source_cluster_id'], actor='PREVENTION_ENGINE',
                               action='PREVENTION_INSIGHT', source='operational_memory',
                               artifact=insight['prevention_id'], result='ADVISORY', evidence=insight))
    return sorted(events, key=lambda row: (row['timestamp'], row['incident_id']))

def timeline(db):
    archived = [json.loads(row[0]) for row in db.execute('SELECT payload FROM archived_audit')]
    return sorted([*archived, *live_timeline(db)], key=lambda row: (row['timestamp'], row['incident_id']))
