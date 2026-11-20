import gc
import json
import sqlite3
import tempfile
import unittest
import warnings
from dataclasses import replace
from pathlib import Path
from core.database import initialize,connect,snapshot,reset
from core.service_graph import build_graph,analytical_figure
from core.exception_genome import generate
from core.correlation_engine import correlate,pair_score
from core.root_cause_agent import DeterministicRootCauseAgent
from core.analysis import analyse,load
from simulator.incident_scenarios import start,advance

class Phase3Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'operations.db'
        initialize(self.path)
        start(self.path)
        for _ in range(23):
            advance(self.path)
        self.state = snapshot(self.path)
        self.graph = build_graph(self.state['services'])
        self.genomes = [generate(e,self.graph) for e in self.state['exceptions']]

    def test_23_exceptions_and_metadata(self):
        self.assertEqual(len(self.genomes),23)
        for e in self.state['exceptions']:
            self.assertTrue(e['upstream_dependency'])
            self.assertTrue(json.loads(e['dependency_path']))
            self.assertTrue(e['last_success_timestamp'])
            self.assertTrue(json.loads(e['recent_change_event']))
            self.assertTrue(json.loads(e['evidence_sources']))

    def test_deterministic_fingerprint_not_exception_id(self):
        e = self.state['exceptions'][0]
        a = generate(e,self.graph)
        b = generate(dict(e,id='OTHER'),self.graph)
        self.assertEqual(a.genome_signature,b.genome_signature)
        self.assertEqual(a.to_dict(),generate(e,self.graph).to_dict())
        changed = generate(dict(e,authentication_context='UNKNOWN'),self.graph)
        self.assertNotEqual(a.genome_signature,changed.genome_signature)

    def test_varied_messages_one_cluster(self):
        self.assertGreater(len({e['error_message'] for e in self.state['exceptions']}),15)
        clusters = correlate(self.genomes,self.graph)
        self.assertEqual(len(clusters),1)
        self.assertEqual(len(clusters[0]['members']),23)
        self.assertEqual(clusters[0]['primary_dependency'],'datahub')
        self.assertEqual(clusters[0]['domains'],5)
        self.assertEqual(clusters[0]['historical_similarity'],'NO_HISTORY')

    def test_score_derived_from_components(self):
        cluster = correlate(self.genomes,self.graph)[0]
        self.assertAlmostEqual(cluster['score'],sum(cluster['signals'].values()))
        self.assertGreaterEqual(cluster['score'],90)
        self.assertLessEqual(cluster['score'],98)
        for pair in cluster['pair_evidence']:
            self.assertEqual(pair['score'],sum(pair['signals'].values()))

    def test_time_alone_does_not_cluster(self):
        unrelated = replace(self.genomes[1],service_id='auth',exception_id='OTHER',
                            root_dependency_candidates=['auth'],upstream_dependencies=[],recent_change_event={})
        self.assertEqual(len(correlate([self.genomes[0],unrelated],self.graph)),2)

    def test_distant_symptom_not_joined(self):
        distant = replace(self.genomes[1],timestamp='2026-11-17T12:00:00')
        self.assertEqual(len(correlate([self.genomes[0],distant],self.graph)),2)

    def test_missing_change_lowers_score(self):
        reduced = [replace(g,recent_change_event={},change_event_type='UNKNOWN') for g in self.genomes]
        baseline = pair_score(self.genomes[0],self.genomes[1],self.graph,self.genomes)
        missing = pair_score(reduced[0],reduced[1],self.graph,reduced)
        self.assertEqual(baseline['score']-missing['score'],20)

    def test_datahub_strongest_candidate(self):
        result = DeterministicRootCauseAgent().analyze(self.genomes,self.graph)
        self.assertEqual(result['root_cause_service_id'],'datahub')
        self.assertNotEqual(result['root_cause_service_id'],'auth')
        self.assertIn('expired',result['root_cause'])
        self.assertEqual(len(result['causal_chain']),22)
        self.assertTrue(result['supporting_evidence'])
        self.assertEqual(len(result['alternative_hypotheses']),2)
        self.assertAlmostEqual(result['confidence']*100,sum(result['confidence_breakdown'].values()))
        self.assertFalse(result['conflicting_evidence'])

    def test_missing_expiry_is_not_asserted(self):
        reduced = [replace(g,authentication_context='UNKNOWN') for g in self.genomes]
        result = DeterministicRootCauseAgent().analyze(reduced,self.graph)
        self.assertIn('not confirmed',result['root_cause'])
        self.assertTrue(result['conflicting_evidence'])
        self.assertLess(result['confidence'],.98)

    def test_backwards_timeline_is_counter_evidence(self):
        changed = [replace(g,timestamp='2026-11-17T08:58:00') if g.service_id=='revenue' else g for g in self.genomes]
        result = DeterministicRootCauseAgent().analyze(changed,self.graph)
        self.assertTrue(result['conflicting_evidence'])
        self.assertLess(result['confidence'],.98)

    def test_analysis_persists_and_is_idempotent(self):
        result = analyse(self.path)
        initialize(self.path)
        self.assertEqual(load(self.path),result)
        self.assertEqual(analyse(self.path),result)
        state = snapshot(self.path)
        self.assertEqual(state['incidents'][0]['status'],'DIAGNOSED')
        self.assertEqual([s['status'] for s in state['services']],[s['status'] for s in self.state['services']])
        self.assertTrue(all(e['genome_signature'] for e in state['exceptions']))
        self.assertTrue(all(e['status']=='ACTIVE' for e in state['exceptions']))

    def test_reset_clears_analysis(self):
        analyse(self.path)
        reset(self.path)
        self.assertTrue(all(not rows for rows in load(self.path).values()))
        with connect(self.path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM cluster_members').fetchone()[0],0)

    def test_early_analysis_rejected(self):
        reset(self.path)
        start(self.path)
        advance(self.path)
        with self.assertRaises(ValueError):
            analyse(self.path)
        self.assertFalse(load(self.path)['root_cause_analyses'])

    def test_connections_close_on_success_and_failure(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always',ResourceWarning)
            with connect(self.path) as db:
                db.execute('SELECT 1')
            with self.assertRaises(sqlite3.ProgrammingError):
                db.execute('SELECT 1')
            try:
                with connect(self.path) as failed:
                    failed.execute("UPDATE incidents SET status='WRONG'")
                    raise RuntimeError('rollback')
            except RuntimeError:
                pass
            with self.assertRaises(sqlite3.ProgrammingError):
                failed.execute('SELECT 1')
            self.assertEqual(snapshot(self.path)['incidents'][0]['status'],'ACTIVE')
            gc.collect()
            self.assertFalse([w for w in caught if issubclass(w.category,ResourceWarning)])

    def test_migration_preserves_legacy_rows(self):
        legacy = Path(self.temp.name)/'legacy.db'
        with connect(legacy) as db:
            db.executescript('''CREATE TABLE exceptions (
            id TEXT PRIMARY KEY,incident_id TEXT,service_id TEXT,timestamp TEXT,error_code TEXT,
            error_category TEXT,error_message TEXT,severity TEXT,business_impact TEXT,status TEXT DEFAULT 'ACTIVE');
            INSERT INTO exceptions VALUES ('OLD','INC-2026-001','datahub','2026-11-17T09:00:10',
            'AUTH-401-DH','AUTHENTICATION','Original message','CRITICAL','Original impact','ACTIVE');''')
        initialize(legacy)
        initialize(legacy)
        rows = snapshot(legacy)['exceptions']
        self.assertEqual(rows[0]['error_message'],'Original message')
        self.assertTrue(rows[0]['evidence_sources'])
        self.assertEqual(rows[0]['authentication_context'],'UNKNOWN')

    def test_analytical_graph_keeps_all_nodes(self):
        graph = analytical_figure(self.state['services'],'datahub')
        self.assertEqual(sum(len(t.x) for t in graph.data),24)
        self.assertEqual(len(graph.layout.annotations),len(self.graph.edges))

    def test_no_later_phase_surface(self):
        with connect(self.path) as db:
            names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertFalse(names & {'simulations','prevention_actions'})
        root = Path(__file__).resolve().parents[1]
        for filename in ('production_executor.py',):
            self.assertFalse((root/'core'/filename).exists())

if __name__=='__main__':
    unittest.main()



