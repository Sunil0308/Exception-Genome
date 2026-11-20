from datetime import datetime
from itertools import combinations
import networkx as nx

# Keys are upstream causes. Values are plausible downstream symptoms.
CAUSAL_ERRORS = {
    'AUTHENTICATION_FAILURE': {'UPSTREAM_DATA_UNAVAILABLE', 'DEPENDENCY_FAILURE',
                               'MISSING_SOURCE_DATA', 'PROCESSING_BLOCKED'},
    'UPSTREAM_DATA_UNAVAILABLE': {'MISSING_SOURCE_DATA', 'DEPENDENCY_FAILURE', 'PROCESSING_BLOCKED'},
    'DEPENDENCY_FAILURE': {'PROCESSING_BLOCKED'},
    'PROCESSING_BLOCKED': set(),
    'MISSING_SOURCE_DATA': set(),
}
WEIGHTS = {'shared_dependency':35,'temporal_proximity':20,'error_relationship':15,'recent_change':20,'dependency_direction':10}

def seconds(a,b):
    return abs((datetime.fromisoformat(a)-datetime.fromisoformat(b)).total_seconds())

def compatible(a,b):
    return a in CAUSAL_ERRORS and (a == b or b in CAUSAL_ERRORS[a])

def timely_change(g):
    change = g.recent_change_event
    if not change.get('timestamp') or g.change_event_type=='UNKNOWN':
        return False
    delta = (datetime.fromisoformat(g.timestamp)-datetime.fromisoformat(change['timestamp'])).total_seconds()
    return 0 <= delta <= 600

def pair_score(a,b,graph,genomes):
    common = set(a.root_dependency_candidates) & set(b.root_dependency_candidates)
    direct = set(a.upstream_dependencies) & set(b.upstream_dependencies)
    gap = seconds(a.timestamp,b.timestamp)
    same_change = (a.recent_change_event==b.recent_change_event and timely_change(a) and timely_change(b))
    # A common observed upstream failure must precede both symptoms.
    direction = any(g.service_id in common and g.timestamp<=min(a.timestamp,b.timestamp)
                    for g in genomes)
    family_match = any(
        source.service_id != target.service_id
        and source.timestamp <= target.timestamp
        and nx.has_path(graph, source.service_id, target.service_id)
        and compatible(source.normalized_error_family, target.normalized_error_family)
        for source, target in ((a, b), (b, a))
    )
    parts = {
        'shared_dependency':35 if any(graph.in_degree(n)==0 for n in common) else 30 if direct else 25 if common else 0,
        'temporal_proximity':20 if gap<=30 else 18 if gap<=90 else 15 if gap<=180 else 0,
        'error_relationship':15 if family_match else 0,
        'recent_change':20 if same_change else 0,
        'dependency_direction':10 if direction else 0,
    }
    return {'a':a.exception_id,'b':b.exception_id,'signals':parts,'score':sum(parts.values()),
            'common_dependencies':sorted(common),'gap_seconds':gap,'historical_similarity':'NO_HISTORY'}

def correlate(genomes,graph,incident_id=None):
    pairs = {frozenset((a.exception_id,b.exception_id)):pair_score(a,b,graph,genomes)
             for a,b in combinations(genomes,2)}
    groups = []
    ambiguous = set()
    for genome in sorted(genomes,key=lambda g:(g.timestamp,g.exception_id)):
        eligible_groups = []
        for group in groups:
            if group[0].exception_id in ambiguous:
                continue
            common = set(genome.root_dependency_candidates).intersection(*(set(g.root_dependency_candidates) for g in group))
            links = [pairs[frozenset((genome.exception_id,g.exception_id))] for g in group]
            # Siblings can share a witnessed cause without a causal edge between them.
            witnessed = any(
                source.service_id in common and all(
                    source is member or (
                        source.timestamp <= member.timestamp
                        and source.service_id != member.service_id
                        and nx.has_path(graph, source.service_id, member.service_id)
                        and compatible(source.normalized_error_family, member.normalized_error_family)
                    ) for member in [*group, genome]
                ) for source in genomes
            )
            if (witnessed and links[0]['score'] >= 75 and links[0]['signals']['error_relationship']
                    and all(p['gap_seconds'] <= 180 for p in links)):
                eligible_groups.append(group)
        if len(eligible_groups) == 1:
            eligible_groups[0].append(genome)
        else:
            groups.append([genome])
            if eligible_groups:
                ambiguous.add(genome.exception_id)
    results = []
    for index,group in enumerate(groups,1):
        first = min(group,key=lambda g:(g.timestamp,g.exception_id))
        common = set.intersection(*(set(g.root_dependency_candidates) for g in group))
        primary = min(common,key=lambda n:(0 if n==first.service_id else 1,graph.in_degree(n),n)) if common else None
        # Score all members against the earliest observed member, avoiding an opaque average over siblings.
        links = [pairs[frozenset((first.exception_id,g.exception_id))] for g in group if g!=first]
        signals = {key:sum(p['signals'][key] for p in links)/len(links) if links else 0 for key in WEIGHTS}
        score = sum(signals.values())
        changes = {str(g.recent_change_event) for g in group}
        results.append(dict(id=f'EG-{incident_id}-{index:03d}' if incident_id else f'EG-{index:03d}',members=[g.exception_id for g in group],
            primary_dependency=primary,first_failure=first.service_id,
            common_change=first.recent_change_event if len(changes)==1 else {},
            time_span_seconds=seconds(min(g.timestamp for g in group),max(g.timestamp for g in group)),
            different_error_codes=len({g.error_code for g in group}),domains=len({g.domain for g in group}),
            signals=signals,score=score,status='HIGH CORRELATION' if score>=90 else 'LIMITED CORRELATION',
            pair_evidence=links,historical_similarity='NO_HISTORY',
            assignment_status='AMBIGUOUS_CLUSTER' if first.exception_id in ambiguous else
                              'CORRELATED_CLUSTER' if len(group) > 1 else 'SINGLETON'))
    return results


