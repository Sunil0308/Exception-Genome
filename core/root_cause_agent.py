"""Analysis interface can be implemented by a later LLM adapter using this same result schema."""
from typing import Protocol
from datetime import datetime
import networkx as nx
from core.correlation_engine import compatible, timely_change

class RootCauseAnalyzer(Protocol):
    def analyze(self, genomes, graph) -> dict: ...

class DeterministicRootCauseAgent:
    def analyze(self,genomes,graph):
        if not genomes:
            raise ValueError('No evidence to analyse')
        first = min(g.timestamp for g in genomes)
        ranked = []
        for node in graph:
            own = next((g for g in genomes if g.service_id==node),None)
            covered = [g for g in genomes if g.service_id==node or nx.has_path(graph,node,g.service_id)]
            descendants = [g for g in covered if g.service_id!=node]
            contradictions = []
            if graph.nodes[node]['status']=='HEALTHY':
                contradictions.append('Candidate service is healthy in the observed state.')
            if own and own.timestamp>first:
                contradictions.append('Another affected service failed before this candidate.')
            if len(covered)<len(genomes):
                contradictions.append('Candidate cannot explain all affected services through dependency ancestry.')
            timeline = sum(g.timestamp>=own.timestamp for g in covered)/len(genomes) if own else 0
            error = sum(compatible(own.normalized_error_family,g.normalized_error_family) for g in covered)/len(genomes) if own else 0
            parts = {'Topology':35*len(covered)/len(genomes),
                     'Timeline':20*timeline if own and own.timestamp==first else 0,
                     'Change Event':20 if own and timely_change(own) and own.recent_change_event.get('service_id')==node else 0,
                     'Error Evidence':15*error if own and own.normalized_error_family=='AUTHENTICATION_FAILURE' else 0,
                     'Contradictions':max(0,8-4*len(contradictions))}
            ranked.append({'service_id':node,'service':graph.nodes[node]['name'],'score':sum(parts.values()),
                           'breakdown':parts,'conflicts':contradictions})
        ranked.sort(key=lambda r:(-r['score'],r['service_id']))
        winner = ranked[0]
        node = winner['service_id']
        own = next((g for g in genomes if g.service_id==node),None)
        descendants = [g for g in genomes if g.service_id!=node and nx.has_path(graph,node,g.service_id)]
        precise = bool(own and own.authentication_context=='CREDENTIAL_EXPIRED'
                       and own.change_event_type=='CREDENTIAL_ROTATION_FAILED' and timely_change(own))
        root = (f"{winner['service']} service credential expired following unsuccessful credential rotation" if precise
                else f"Suspected upstream failure at {winner['service']}; credential expiry is not confirmed")
        evidence = [f"{winner['service']} {'is' if own and own.timestamp==first else 'is not'} the earliest observed failed service.",
                    f"{len(descendants)} affected services are descendants of {winner['service']}.",
                    f"{sum(g.timestamp>own.timestamp for g in descendants) if own else 0} downstream failures follow the candidate failure."]
        if own:
            evidence.append(f"Source error family: {own.normalized_error_family}; authentication context: {own.authentication_context}.")
            evidence.append(f"{sum(compatible(own.normalized_error_family,g.normalized_error_family) for g in descendants)} downstream symptoms have explicitly compatible dependency/data error families.")
            if timely_change(own):
                delay = (datetime.fromisoformat(own.timestamp)-datetime.fromisoformat(own.recent_change_event['timestamp'])).total_seconds()
                evidence.append(f"First candidate failure occurs {delay:g} seconds after the recorded change event.")
        healthy_auth = [s['name'] for _,s in graph.nodes(data=True) if s['name']=='Authentication Service' and s['status']=='HEALTHY']
        alternatives = [{'hypothesis':'Independent simultaneous failures','evidence_against':
                         f'{len(descendants)} affected services share the candidate ancestry and a bounded failure timeline.'}]
        if healthy_auth:
            evidence.append('Authentication Service remains healthy in observed service state.')
            alternatives.append({'hypothesis':'Authentication Service outage','evidence_against':
                                 'Authentication Service remains healthy; this weakens a platform-wide authentication outage hypothesis.'})
        conflicts = list(winner['conflicts'])
        local_worker = bool(own and len(genomes) == 1 and own.error_code == 'MS-JOB-502'
                            and not own.recent_change_event and not conflicts)
        if local_worker:
            root = f"{winner['service']} local processing worker failure"
            winner['breakdown']['Error Evidence'] = 15
            winner['score'] = sum(winner['breakdown'].values())
            evidence.append('The local worker diagnostic is present without an observed upstream failure.')
        component_failure = bool(own and descendants and not conflicts and timely_change(own)
                                 and own.change_event_type == 'COMPONENT_FAILURE'
                                 and own.recent_change_event.get('service_id') == node)
        if component_failure:
            root = f"{winner['service']} component failure"
            winner['breakdown']['Error Evidence'] = 15 * sum(
                compatible(own.normalized_error_family, g.normalized_error_family)
                for g in descendants) / len(descendants)
            winner['score'] = sum(winner['breakdown'].values())
        if not precise and not local_worker and not component_failure:
            for upstream in graph.predecessors(node):
                alternatives.append({'hypothesis': graph.nodes[upstream]['name'] + ' upstream failure',
                                     'evidence_against': 'No corroborating upstream failure record is available.'})
            alternatives.append({'hypothesis': 'Local failure at ' + winner['service'],
                                 'evidence_against': 'No confirmed local diagnostic event is available.'})
            conflicts.append('Structured credential-expiry or failed-rotation evidence is missing; exact cause is unconfirmed.')
            winner['breakdown']['Contradictions'] = max(0,winner['breakdown']['Contradictions']-4)
            winner['score'] = sum(winner['breakdown'].values())
        return dict(root_cause_service=winner['service'],root_cause_service_id=node,root_cause=root,
                    confidence=winner['score']/100,confidence_breakdown=winner['breakdown'],
                    affected_services=len({g.service_id for g in genomes}),supporting_evidence=evidence,
                    conflicting_evidence=conflicts,alternative_hypotheses=alternatives,candidate_ranking=ranked,
                    causal_chain=[{'path':[graph.nodes[n]['name'] for n in nx.shortest_path(graph,node,g.service_id)],
                                   'exception_id':g.exception_id,'timestamp':g.timestamp} for g in descendants],
                    recommended_action=f"Restore valid authentication for {winner['service']} with an approved replacement and reassess downstream connectivity" if precise else 'Review a controlled restart of the local worker' if local_worker else 'Collect dependency health and change evidence',
                    risk='NOT ASSESSED',mode='DETERMINISTIC DEMO MODE')




