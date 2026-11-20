import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
import os
from core.models import Service, Status

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = Path(os.environ["EXCEPTION_GENOME_DB"]) if os.environ.get("EXCEPTION_GENOME_DB") else ROOT / 'data' / 'operations.sqlite3'


@contextmanager
def connect(path=DEFAULT_DB):
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA foreign_keys=ON')
        with db:
            yield db
    finally:
        db.close()


def initialize(path=DEFAULT_DB):
    with connect(path) as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS services (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, domain TEXT NOT NULL,
          dependencies TEXT NOT NULL, status TEXT NOT NULL, health_state TEXT NOT NULL,
          last_success TEXT, recent_change TEXT, error_state TEXT);
        CREATE TABLE IF NOT EXISTS incidents (
          id TEXT PRIMARY KEY, title TEXT NOT NULL, status TEXT NOT NULL,
          started_at TEXT NOT NULL, simulation_step INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS exceptions (
          id TEXT PRIMARY KEY, incident_id TEXT NOT NULL REFERENCES incidents(id),
          service_id TEXT NOT NULL REFERENCES services(id), timestamp TEXT NOT NULL,
          error_code TEXT NOT NULL, error_category TEXT NOT NULL,
          error_message TEXT NOT NULL, severity TEXT NOT NULL, business_impact TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'ACTIVE', UNIQUE(incident_id, service_id));
        ''')
        columns = {r['name'] for r in db.execute('PRAGMA table_info(exceptions)')}
        for name, definition in {
            'upstream_dependency': "TEXT DEFAULT ''", 'dependency_path': "TEXT DEFAULT '[]'",
            'last_success_timestamp': 'TEXT', 'recent_change_event': "TEXT DEFAULT '{}'",
            'authentication_context': "TEXT DEFAULT 'UNKNOWN'", 'retry_count': 'INTEGER DEFAULT 0',
            'evidence_sources': "TEXT DEFAULT '[]'", 'genome_signature': 'TEXT',
        }.items():
            if name not in columns:
                db.execute(f'ALTER TABLE exceptions ADD COLUMN {name} {definition}')
        db.executescript('''
        CREATE TABLE IF NOT EXISTS exception_genomes (
          exception_id TEXT PRIMARY KEY REFERENCES exceptions(id), payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS correlation_clusters (
          id TEXT PRIMARY KEY, incident_id TEXT NOT NULL REFERENCES incidents(id), payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS cluster_members (
          cluster_id TEXT REFERENCES correlation_clusters(id), exception_id TEXT REFERENCES exceptions(id),
          PRIMARY KEY(cluster_id, exception_id));
        CREATE TABLE IF NOT EXISTS root_cause_analyses (
          cluster_id TEXT PRIMARY KEY REFERENCES correlation_clusters(id), payload TEXT NOT NULL);
        ''')
        from core.phase4_store import initialize_phase4, seed_references
        initialize_phase4(db)
        from core.phase5_store import initialize_phase5
        initialize_phase5(db)
        from core.operational_memory import initialize_memory
        initialize_memory(db)
        from core.review import initialize_review
        initialize_review(db)
        from core.evidence_intake import initialize_evidence
        initialize_evidence(db)
        db.execute('CREATE TABLE IF NOT EXISTS archived_audit (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        for service in json.loads((ROOT / 'data/seed_services.json').read_text()):
            model = Service(**service)
            db.execute('INSERT OR IGNORE INTO services VALUES (?,?,?,?,?,?,?,?,?)',
                       (model.id, model.name, model.domain,
                        json.dumps(model.dependencies), Status.HEALTHY.value, Status.HEALTHY.value,
                        '2026-11-17T08:55:00', None, None))
        seed_references(db)
        from core.exception_genome import metadata
        from core.service_graph import build_graph
        graph = build_graph([dict(r) for r in db.execute('SELECT * FROM services')])
        for row in db.execute("SELECT * FROM exceptions WHERE evidence_sources='[]'").fetchall():
            context = metadata(dict(row), graph)
            db.execute('UPDATE exceptions SET ' + ','.join(f'{k}=?' for k in context) + ' WHERE id=?',
                       (*context.values(), row['id']))


def snapshot(path=DEFAULT_DB):
    with connect(path) as db:
        return {table: [dict(row) for row in db.execute('SELECT * FROM ' + table)]
                for table in ('services', 'incidents', 'exceptions')}


def reset(path=DEFAULT_DB, *, preserve_memory=False):
    with connect(path) as db:
        if preserve_memory:
            from core.audit import live_timeline
            from core.phase4_store import canonical, digest
            for event in live_timeline(db):
                if event['source'] != 'operational_memory':
                    db.execute('INSERT OR IGNORE INTO archived_audit VALUES (?,?)',
                               (digest(event), canonical(event)))
        else:
            db.execute('DELETE FROM operational_memory')
            db.execute('DELETE FROM archived_audit')
        db.execute('DELETE FROM review_decisions')
        db.execute('DELETE FROM executions')
        db.execute('DELETE FROM operational_outputs')
        db.execute('DELETE FROM resolution_contracts')
        db.execute("UPDATE approved_resource_references SET active=0 WHERE service_id='datahub'")
        db.execute("UPDATE approved_resource_references SET active=1 WHERE reference_id='DH-v17'")
        for table in ('root_cause_analyses', 'cluster_members', 'correlation_clusters', 'exception_genomes'):
            db.execute('DELETE FROM ' + table)
        db.execute('DELETE FROM exceptions')
        db.execute('DELETE FROM incidents')
        db.execute("UPDATE services SET status='HEALTHY', health_state='HEALTHY', "
                   "last_success='2026-11-17T08:55:00', recent_change=NULL, error_state=NULL")







