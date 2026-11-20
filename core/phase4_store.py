"""SQLite persistence for the Phase 4 decision trail."""
import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4


def now():
    return datetime.now(timezone.utc).isoformat()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def identifier(prefix, incident_id):
    return f'{prefix}-{incident_id}-{uuid4().hex}'


def initialize_phase4(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS approved_resource_references (
          reference_id TEXT PRIMARY KEY, service_id TEXT NOT NULL REFERENCES services(id),
          status TEXT NOT NULL, approved INTEGER NOT NULL CHECK(approved IN (0,1)),
          active INTEGER NOT NULL CHECK(active IN (0,1)), created_at TEXT NOT NULL);
        CREATE UNIQUE INDEX IF NOT EXISTS active_reference_by_service
          ON approved_resource_references(service_id) WHERE active=1;
        CREATE TABLE IF NOT EXISTS resolution_contracts (
          id TEXT PRIMARY KEY, incident_id TEXT NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
          cluster_id TEXT NOT NULL REFERENCES root_cause_analyses(cluster_id),
          version INTEGER NOT NULL, contract_hash TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL,
          UNIQUE(incident_id, version));
        CREATE TABLE IF NOT EXISTS safety_evaluations (
          id TEXT PRIMARY KEY, contract_id TEXT NOT NULL REFERENCES resolution_contracts(id) ON DELETE CASCADE,
          contract_hash TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS impact_simulations (
          id TEXT PRIMARY KEY, contract_id TEXT NOT NULL REFERENCES resolution_contracts(id) ON DELETE CASCADE,
          contract_hash TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS execution_readiness (
          id TEXT PRIMARY KEY, contract_id TEXT NOT NULL REFERENCES resolution_contracts(id) ON DELETE CASCADE,
          contract_hash TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS phase4_audit_events (
          id INTEGER PRIMARY KEY, incident_id TEXT NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
          contract_id TEXT NOT NULL REFERENCES resolution_contracts(id) ON DELETE CASCADE,
          event_type TEXT NOT NULL, occurred_at TEXT NOT NULL, payload TEXT NOT NULL);
    """)


def seed_references(db):
    db.executemany('INSERT OR IGNORE INTO approved_resource_references VALUES (?,?,?,?,?,?)', (
        ('DH-v17', 'datahub', 'EXPIRED', 1, 1, '2026-11-01T08:00:00'),
        ('DH-v18', 'datahub', 'VALID', 1, 0, '2026-11-17T08:58:00'),
    ))


def audit(db, contract, event_type, details):
    db.execute('INSERT INTO phase4_audit_events VALUES (NULL,?,?,?,?,?)',
               (contract.incident_id, contract.contract_id, event_type, now(), canonical(details)))


def persist(db, table, record_id, contract, status, payload):
    db.execute(f'INSERT INTO {table} VALUES (?,?,?,?,?)',
               (record_id, contract.contract_id, contract.contract_hash, status, canonical(payload)))


def latest(db, table, contract_id):
    row = db.execute(f'SELECT status,payload FROM {table} WHERE contract_id=? ORDER BY rowid DESC LIMIT 1',
                     (contract_id,)).fetchone()
    return dict(json.loads(row['payload']), record_status=row['status']) if row else None

