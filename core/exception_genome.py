"""Structured operational fingerprints, not biological genomes."""
import hashlib
import json
from dataclasses import dataclass, asdict
from datetime import datetime
import networkx as nx

def decode(value, default):
    try:
        return json.loads(value) if isinstance(value,str) else value or default
    except (ValueError,TypeError):
        return default

def metadata(exception, graph):
    service = graph.nodes[exception['service_id']]
    ancestry = nx.ancestors(graph,exception['service_id']) | {exception['service_id']}
    changes = []
    for node in sorted(ancestry):
        raw = graph.nodes[node].get('recent_change')
        if raw:
            change = decode(raw, {'service_id':node,'type':'UNKNOWN','description':raw})
            if isinstance(change,dict):
                changes.append((node,change))
    root, change = changes[0] if len(changes)==1 else (None,{})
    route = nx.shortest_path(graph,root,exception['service_id']) if root else []
    auth = 'CREDENTIAL_EXPIRED' if exception['error_category']=='AUTHENTICATION' and change.get('credential_state')=='EXPIRED' else (
        'UPSTREAM_AUTH_FAILURE' if root and change.get('type')=='CREDENTIAL_ROTATION_FAILED' else 'UNKNOWN')
    return dict(upstream_dependency=root or '',dependency_path=json.dumps(route),
                last_success_timestamp=service.get('last_success'),recent_change_event=json.dumps(change),
                authentication_context=auth,retry_count=0,
                evidence_sources=json.dumps(['service_health','dependency_graph','exception_timeline'] + (['change_event'] if change else [])))

def normalize(exception):
    prefix = exception['error_code'].split('-')[0]
    return {'AUTH':'AUTHENTICATION_FAILURE','SRC':'UPSTREAM_DATA_UNAVAILABLE','REC':'MISSING_SOURCE_DATA',
            'REF':'UPSTREAM_DATA_UNAVAILABLE','CUS':'UPSTREAM_DATA_UNAVAILABLE','EXP':'MISSING_SOURCE_DATA',
            'MS':'PROCESSING_BLOCKED','SET':'PROCESSING_BLOCKED','DEP':'DEPENDENCY_FAILURE'}.get(prefix,
            'AUTHENTICATION_FAILURE' if exception['error_category']=='AUTHENTICATION' else 'DEPENDENCY_FAILURE')

@dataclass
class ExceptionGenome:
    exception_id: str
    service_id: str
    service_name: str
    domain: str
    timestamp: str
    error_code: str
    error_category: str
    normalized_error_family: str
    upstream_dependencies: list
    dependency_path: list
    root_dependency_candidates: list
    last_success_timestamp: str
    recent_change_event: dict
    change_event_type: str
    authentication_context: str
    retry_count: int
    severity: str
    business_impact: str
    evidence_sources: list
    temporal_bucket: str
    genome_signature: str = ''

    def to_dict(self):
        return asdict(self)

def generate(exception, graph):
    node = exception['service_id']
    service = graph.nodes[node]
    ancestry = nx.ancestors(graph,node) | {node}
    change = decode(exception.get('recent_change_event'),{})
    time = datetime.fromisoformat(exception['timestamp'])
    bucket = time.replace(minute=(time.minute//5)*5,second=0,microsecond=0).isoformat()
    genome = ExceptionGenome(exception['id'],node,service['name'],service['domain'],exception['timestamp'],
        exception['error_code'],exception['error_category'],normalize(exception),sorted(graph.predecessors(node)),
        decode(exception.get('dependency_path'),[]),sorted(ancestry),exception.get('last_success_timestamp'),
        change,change.get('type','UNKNOWN'),exception.get('authentication_context','UNKNOWN'),exception.get('retry_count',0),
        exception['severity'],exception['business_impact'],decode(exception.get('evidence_sources'),[]),bucket)
    features = [genome.normalized_error_family,sorted(n for n in ancestry if graph.in_degree(n)==0),
                change.get('service_id'),genome.change_event_type,bucket,genome.authentication_context]
    genome.genome_signature = 'EG-' + hashlib.sha256(json.dumps(features,sort_keys=True).encode()).hexdigest()[:16]
    return genome

