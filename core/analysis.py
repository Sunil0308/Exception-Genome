import json
from pathlib import Path

from core.database import DEFAULT_DB, connect
from core.service_graph import build_graph
from core.exception_genome import generate
from core.correlation_engine import correlate
from core.root_cause_agent import DeterministicRootCauseAgent
from simulator.incident_scenarios import INCIDENT_ID, get_scenario
from simulator.engine import propagation_order


def read_analysis(db, incident_id=None):
    tables = {
        'exception_genomes': 'exception_genomes g JOIN exceptions e ON e.id=g.exception_id',
        'correlation_clusters': 'correlation_clusters c',
        'root_cause_analyses': 'root_cause_analyses r JOIN correlation_clusters c ON c.id=r.cluster_id',
    }
    result = {}
    for name, source in tables.items():
        alias = source.split()[1]
        field = 'e.incident_id' if name == 'exception_genomes' else 'c.incident_id'
        sql = f'SELECT {alias}.payload FROM {source}'
        order = {'exception_genomes': 'g.exception_id', 'correlation_clusters': 'c.id',
                 'root_cause_analyses': 'r.cluster_id'}[name]
        if incident_id:
            rows = db.execute(sql + f' WHERE {field}=? ORDER BY {order}', (incident_id,))
        else:
            rows = db.execute(sql + f' ORDER BY {order}')
        result[name] = [json.loads(row[0]) for row in rows]
    return result


def load(path=DEFAULT_DB, incident_id=None):
    with connect(path) as db:
        return read_analysis(db, incident_id)


def ready(state, incident_id):
    incident = next((row for row in state['incidents'] if row['id'] == incident_id), None)
    scenario = get_scenario(incident_id)
    if incident is None or scenario is None:
        return False
    expected = propagation_order(build_graph(state['services']), scenario)
    observed = {row['service_id'] for row in state['exceptions']
                if row['incident_id'] == incident_id and row['status'] == 'ACTIVE'}
    return incident['simulation_step'] == len(expected) and observed == set(expected)


def analyse(incident_id=INCIDENT_ID, path=DEFAULT_DB, progress=lambda message: None):
    # Existing Python callers passed a database Path as the first argument.
    if isinstance(incident_id, Path):
        path, incident_id = incident_id, INCIDENT_ID
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        state = {table: [dict(r) for r in db.execute('SELECT * FROM ' + table)]
                 for table in ('services', 'incidents')}
        state['exceptions'] = [dict(r) for r in db.execute(
            'SELECT * FROM exceptions WHERE incident_id=? ORDER BY timestamp,id', (incident_id,))]
        if not ready(state, incident_id):
            raise ValueError('Unknown incident or incomplete incident propagation')
        existing = read_analysis(db, incident_id)
        prior = existing['root_cause_analyses']
        if prior and all(row.get('analysis_id') for row in prior):
            return existing
        if prior:
            # Upgrade diagnoses persisted before incident-scoped analysis.
            cluster_ids = [(row['id'],) for row in existing['correlation_clusters']]
            db.executemany('DELETE FROM root_cause_analyses WHERE cluster_id=?', cluster_ids)
            db.executemany('DELETE FROM cluster_members WHERE cluster_id=?', cluster_ids)
            db.executemany('DELETE FROM correlation_clusters WHERE id=?', cluster_ids)
            db.execute('DELETE FROM exception_genomes WHERE exception_id IN '
                       '(SELECT id FROM exceptions WHERE incident_id=?)', (incident_id,))
        graph = build_graph(state['services'])
        progress('Extracting operational fingerprints...')
        genomes = [generate(row, graph) for row in state['exceptions'] if row['status'] == 'ACTIVE']
        progress('Comparing dependencies, event timelines and causal error families...')
        clusters = correlate(genomes, graph, incident_id)
        progress('Testing root-cause candidates...')
        agent = DeterministicRootCauseAgent()
        for genome in genomes:
            db.execute('INSERT INTO exception_genomes VALUES (?,?)',
                       (genome.exception_id, json.dumps(genome.to_dict())))
            db.execute('UPDATE exceptions SET genome_signature=? WHERE id=?',
                       (genome.genome_signature, genome.exception_id))
        for cluster in clusters:
            result = agent.analyze([g for g in genomes if g.exception_id in cluster['members']], graph)
            if cluster['assignment_status'] == 'SINGLETON' and result['confidence'] < 0.65:
                cluster['assignment_status'] = 'UNASSIGNED'
            from core.operational_memory import similar_cases
            matches = similar_cases(db, [g.to_dict() for g in genomes if g.exception_id in cluster['members']], result)
            if matches:
                result['historical_matches'] = matches
            result['diagnosis_outcome'] = (
                'NO_CONFIDENT_ROOT_CAUSE' if result['confidence'] < 0.75 or cluster['assignment_status'] == 'AMBIGUOUS_CLUSTER' else 'ROOT_CAUSE_CANDIDATE'
            )
            result.update(analysis_id='RCA-' + cluster['id'], cluster_id=cluster['id'],
                          incident_id=incident_id, diagnosis_version=1)
            db.execute('INSERT INTO correlation_clusters VALUES (?,?,?)',
                       (cluster['id'], incident_id, json.dumps(cluster)))
            db.executemany('INSERT INTO cluster_members VALUES (?,?)',
                           [(cluster['id'], member) for member in cluster['members']])
            db.execute('INSERT INTO root_cause_analyses VALUES (?,?)', (cluster['id'], json.dumps(result)))
            from core.review import audit_event
            for action, artifact, data in (
                ('GENOME_ANALYSIS', cluster['id'], {'members': cluster['members']}),
                ('CLUSTER_ASSIGNMENT', cluster['id'], cluster),
                ('ROOT_CAUSE_ANALYSIS', result['analysis_id'], result),
            ):
                audit_event(db, incident_id, cluster['id'], action, artifact, data)
        db.execute("UPDATE incidents SET status='DIAGNOSED' WHERE id=?", (incident_id,))
        return read_analysis(db, incident_id)






