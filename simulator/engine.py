import json
from datetime import datetime, timedelta
import networkx as nx
from core.database import connect, snapshot
from core.service_graph import build_graph
from core.exception_genome import metadata
from simulator.incident_scenarios import INCIDENT_ID

def propagation_order(graph, scenario):
    if scenario.propagation_rule == 'isolated':
        return [scenario.source_service]
    if scenario.propagation_rule != 'descendants':
        raise ValueError('Unsupported propagation rule')
    sources = {scenario.source_service, *scenario.additional_sources}
    affected = sources.union(*(nx.descendants(graph, source) for source in sources if source not in scenario.sources_without_change))
    return [n for n in nx.topological_sort(graph) if n in affected]

def start(path, scenario):
    with connect(path) as db:
        db.execute("INSERT OR IGNORE INTO incidents (id,title,status,started_at,simulation_step) VALUES (?,?,'ACTIVE',?,0)",
                   (scenario.incident_id, scenario.title, scenario.start_time))
        for source in (scenario.source_service, *scenario.additional_sources):
            change = dict(scenario.recent_change, service_id=source) if scenario.recent_change and source not in scenario.sources_without_change else {}
            db.execute('UPDATE services SET recent_change=? WHERE id=?', (json.dumps(change), source))

def advance(path, scenario):
    graph = build_graph(snapshot(path)['services'])
    order = propagation_order(graph, scenario)
    with connect(path) as db:
        incident = db.execute('SELECT * FROM incidents WHERE id=?', (scenario.incident_id,)).fetchone()
        if incident is None or incident['simulation_step'] >= len(order):
            return False
        step = incident['simulation_step']
        service_id = order[step]
        service = graph.nodes[service_id]
        source = service_id in (scenario.source_service, *scenario.additional_sources)
        at = (datetime.fromisoformat(scenario.start_time) + timedelta(seconds=scenario.first_delay + step*scenario.timing_interval)).isoformat()
        prefix, fallback = scenario.domain_templates[service['domain']]
        code, message = scenario.exception_templates.get(service_id, (f'{prefix}-{step:03d}', f"{service['name']}: {fallback}"))
        status = 'FAILED' if source or service['domain'] in scenario.failed_domains else 'DEGRADED'
        row = dict(id=(f'EX-{step+1:03d}' if scenario.incident_id == INCIDENT_ID else f'EX-{scenario.incident_id}-{step+1:03d}'),incident_id=scenario.incident_id,service_id=service_id,
                   timestamp=at,error_code=code,error_category='AUTHENTICATION' if source and scenario.triggering_event == 'CREDENTIAL_EXPIRED' else 'DEPENDENCY',
                   error_message=message,severity=scenario.severity_rules['source' if source else 'downstream'],
                   business_impact=f"{service['name']} operational output delayed")
        row.update(metadata(row, graph))
        db.execute('UPDATE services SET status=?,health_state=?,error_state=? WHERE id=?', (status,status,message,service_id))
        db.execute('INSERT INTO exceptions (' + ','.join(row) + ') VALUES (' + ','.join('?' for _ in row) + ')', tuple(row.values()))
        db.execute('UPDATE incidents SET simulation_step=simulation_step+1 WHERE id=?', (scenario.incident_id,))
    return True






