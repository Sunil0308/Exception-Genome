"""Advance committed recovery waves using actual service and dependency state."""
import sqlite3

import networkx as nx

from core.database import DEFAULT_DB, connect
from core.phase4_store import digest, now
from core.phase5_store import execution, log, operational_state, save, set_incident
from core.rollback_engine import rollback
from core.service_graph import build_graph

ACTOR = 'RECOVERY_ENGINE'


def enter_recovery(db, record, service_id):
    db.execute("UPDATE services SET status='RECOVERING', health_state='RECOVERING' WHERE id=?", (service_id,))
    db.execute("UPDATE exceptions SET status='RECOVERING' WHERE incident_id=? AND service_id=? "
               "AND status IN ('ACTIVE','REOPENED')", (record['incident_id'], service_id))
    for action in ('SERVICE_ENTERED_RECOVERY', 'EXCEPTION_ENTERED_RECOVERY'):
        log(db, record, ACTOR, action, evidence={'service_id': service_id},
            state_digest=digest(operational_state(db, record['incident_id'])))


def advance_recovery(incident_id, path=DEFAULT_DB, *, cluster_id=None):
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        record = execution(db, incident_id, cluster_id)
        if not record or record['status'] != 'RECOVERING':
            return record
        db.execute('SAVEPOINT recovery_wave')
        try:
            result = advance_wave(db, record)
        except (sqlite3.Error, ValueError, KeyError, nx.NetworkXException) as error:
            db.execute('ROLLBACK TO recovery_wave')
            db.execute('RELEASE recovery_wave')
            record = execution(db, incident_id, cluster_id)
            record.update(status='FAILED', result='EXECUTION_FAILED', completed_at=now(),
                          failure_reason=str(error), rollback_required=True)
            save(db, record)
            if not record.get('multi_assignment'):
                set_incident(db, incident_id, 'EXECUTION_FAILED')
            log(db, record, ACTOR, 'RECOVERY_FAILED', result=str(error))
            if record.get('multi_assignment'):
                return record
            return rollback(db, record)
        db.execute('RELEASE recovery_wave')
        return result


def advance_wave(db, record):
    incident_id = record['incident_id']
    state = operational_state(db, incident_id)
    graph = build_graph(state['services'])
    target = record['target_service']
    refs = [r for r in state['references'] if r['service_id'] == target and r['active'] == 1]
    root_valid = record['action_type'] == 'RESTART_SINGLE_SERVICE' or bool(len(refs) == 1 and refs[0]['reference_id'] == record['action_parameters']['credential_version']
                      and refs[0]['status'] == 'VALID' and refs[0]['approved'] == 1
                      and any(row['service_id'] == target and row['current_state'] == 'VALID' for row in state['outputs']))
    unresolved = {'ACTIVE', 'RECOVERING', 'REOPENED', 'ESCALATED'}
    independent = {row['service_id'] for row in state['exceptions']
                   if row['incident_id'] != incident_id and row['status'] in unresolved}
    own = {row['service_id']: row for row in state['exceptions'] if row['incident_id'] == incident_id}
    affected = set(record['affected_services'])

    def eligible(node):
        return (root_valid and node in affected and node in own and node not in independent
                and (node == target or ((record['action_type'] == 'RESTART_SINGLE_SERVICE' or own[node]['authentication_context'] == 'UPSTREAM_AUTH_FAILURE')
                                        and nx.has_path(graph, target, node)))
                and all(graph.nodes[parent]['status'] == 'HEALTHY' for parent in graph.predecessors(node)))

    order = list(nx.topological_sort(graph))
    completing = [node for node in order if node in own and own[node]['status'] == 'RECOVERING' and eligible(node)]
    for node in completing:
        db.execute("UPDATE services SET status='HEALTHY',health_state='HEALTHY',last_success=?,error_state=NULL WHERE id=?",
                   (now(), node))
        graph.nodes[node]['status'] = 'HEALTHY'
        db.execute("UPDATE exceptions SET status='RESOLVED' WHERE incident_id=? AND service_id=?", (incident_id, node))
        if not (node == 'revenue' and record['mode'] == 'SYNTHETIC_VERIFICATION_FAILURE'):
            db.execute('UPDATE operational_outputs SET current_state=expected_state,updated_at=?,source=? '
                       'WHERE incident_id=? AND service_id=?', (now(), ACTOR, incident_id, node))
        else:
            log(db, record, ACTOR, 'SYNTHETIC_OUTPUT_FAILURE_INJECTED', evidence={'service_id': node})
        for action in ('SERVICE_RECOVERED', 'EXCEPTION_RESOLVED'):
            log(db, record, ACTOR, action, evidence={'service_id': node},
                state_digest=digest(operational_state(db, incident_id)))
    starting = [node for node in order if node in own and own[node]['status'] in ('ACTIVE', 'REOPENED')
                and graph.nodes[node]['status'] in ('FAILED', 'DEGRADED') and eligible(node)]
    for node in starting:
        enter_recovery(db, record, node)
    record['recovery_step'] += 1
    if not starting:
        record.update(status='AWAITING_VERIFICATION', completed_at=now())
        if not record.get('multi_assignment'):
            set_incident(db, incident_id, 'AWAITING_VERIFICATION')
        log(db, record, ACTOR, 'RECOVERY_COMPLETED', result='AWAITING_VERIFICATION',
            evidence={'unresolved_services': sorted(node for node in affected if graph.nodes[node]['status'] != 'HEALTHY')},
            state_digest=digest(operational_state(db, incident_id)))
    record['state_digest_after'] = digest(operational_state(db, incident_id))
    save(db, record)
    return record




