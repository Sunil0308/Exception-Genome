"""Persistence and synthetic output definitions for the controlled workflow."""
import json

from core.phase4_store import canonical, digest, now

OUTPUTS = {
    'datahub': ('DataHub Authentication', 'VALID'),
    'revenue': ('Daily Revenue Report', 'AVAILABLE'),
    'daily_recon': ('Daily Reconciliation Engine', 'SUCCESSFUL'),
    'scheduler': ('Scheduler output', 'AVAILABLE'),
    'event_bus': ('Event stream', 'AVAILABLE'),
    'merchant': ('Merchant Settlement', 'PROCESSING'),
    'statement': ('Statement Generator', 'AVAILABLE'),
    'finance': ('Finance Export', 'COMPLETE'),
}


def initialize_phase5(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS executions (
            id TEXT PRIMARY KEY, incident_id TEXT NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
            contract_id TEXT REFERENCES resolution_contracts(id) ON DELETE CASCADE,
            execution_key TEXT UNIQUE, status TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS execution_steps (
            id INTEGER PRIMARY KEY, execution_id TEXT NOT NULL REFERENCES executions(id) ON DELETE CASCADE,
            incident_id TEXT NOT NULL REFERENCES incidents(id), timestamp TEXT NOT NULL,
            actor TEXT NOT NULL, action TEXT NOT NULL, source TEXT NOT NULL,
            decision TEXT, result TEXT, contract_hash TEXT, state_digest TEXT, evidence TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS operational_outputs (
            incident_id TEXT REFERENCES incidents(id) ON DELETE CASCADE,
            service_id TEXT REFERENCES services(id), output_type TEXT NOT NULL,
            current_state TEXT NOT NULL, expected_state TEXT NOT NULL, updated_at TEXT NOT NULL,
            source TEXT NOT NULL, PRIMARY KEY(incident_id,service_id));
        CREATE TABLE IF NOT EXISTS verification_results (
            id TEXT PRIMARY KEY, execution_id TEXT UNIQUE NOT NULL REFERENCES executions(id) ON DELETE CASCADE,
            status TEXT NOT NULL, state_digest TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS verification_checks (
            verification_id TEXT REFERENCES verification_results(id) ON DELETE CASCADE,
            rule_id TEXT, result TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(verification_id,rule_id));
        CREATE TABLE IF NOT EXISTS rollback_records (
            execution_id TEXT PRIMARY KEY REFERENCES executions(id) ON DELETE CASCADE,
            status TEXT NOT NULL, payload TEXT NOT NULL);
    """)
    columns = {row['name'] for row in db.execute('PRAGMA table_info(incidents)')}
    for name in ('resolved_at', 'resolution_execution_id', 'verification_id', 'final_state_digest'):
        if name not in columns:
            db.execute(f'ALTER TABLE incidents ADD COLUMN {name} TEXT')


def execution(db, incident_id, cluster_id=None):
    sql = ("SELECT e.payload FROM executions e LEFT JOIN resolution_contracts c ON c.id=e.contract_id "
           "WHERE e.incident_id=? AND e.status!='BLOCKED'")
    params = (incident_id,)
    if cluster_id is not None:
        sql += ' AND c.cluster_id=?'
        params += (cluster_id,)
    row = db.execute(sql + ' ORDER BY e.rowid DESC LIMIT 1', params).fetchone()
    return json.loads(row[0]) if row else None

def save(db, record):
    db.execute('UPDATE executions SET status=?,payload=? WHERE id=?',
               (record['status'], canonical(record), record['execution_id']))


def log(db, record, actor, action, *, decision=None, result=None, evidence=None, state_digest=None):
    db.execute('INSERT INTO execution_steps VALUES (NULL,?,?,?,?,?,?,?,?,?,?,?)',
               (record['execution_id'], record['incident_id'], now(), actor, action,
                'SYNTHETIC_SQLITE', decision, result, record['contract_hash'],
                state_digest or record['state_digest_after'] or record['state_digest_before'],
                canonical(evidence or {})))


def operational_state(db, incident_id):
    from core.resolution_contract import read_context
    state = read_context(db, incident_id)
    incident = db.execute('SELECT * FROM incidents WHERE id=?', (incident_id,)).fetchone()
    if incident:
        state['incident'] = dict(incident)
    state['outputs'] = [dict(row) for row in db.execute(
        'SELECT * FROM operational_outputs WHERE incident_id=? ORDER BY service_id', (incident_id,))]
    return state


def verification_digest(state):
    # Closure metadata changes after successful verification. Operational evidence does not.
    incident = {key: state['incident'].get(key) for key in ('id', 'started_at', 'simulation_step')}
    return digest(dict(state, incident=incident))


def set_incident(db, incident_id, status):
    db.execute('UPDATE incidents SET status=? WHERE id=?', (status, incident_id))





