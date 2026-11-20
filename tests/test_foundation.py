import tempfile
import unittest
from pathlib import Path
import networkx as nx
from core.database import initialize, snapshot, reset
from core.service_graph import build_graph, figure
from simulator.incident_scenarios import start, advance


class FoundationTests(unittest.TestCase):
    def test_persistent_incident_lifecycle(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'test.db'
            initialize(path)
            initial = snapshot(path)
            self.assertEqual(len(initial['services']),24)
            self.assertFalse(initial['incidents'])
            graph = build_graph(initial['services'])
            self.assertEqual(len(nx.descendants(graph,'datahub')),22)
            self.assertTrue(nx.is_directed_acyclic_graph(graph))
            start(path)
            start(path)
            self.assertTrue(advance(path))
            first = snapshot(path)
            self.assertEqual(first['exceptions'][0]['service_id'],'datahub')
            initialize(path)
            self.assertEqual(len(snapshot(path)['exceptions']),1)
            for _ in range(22):
                self.assertTrue(advance(path))
            self.assertFalse(advance(path))
            state = snapshot(path)
            self.assertEqual(len(state['exceptions']),23)
            self.assertEqual(len(state['incidents']),1)
            self.assertEqual(state['incidents'][0]['status'],'ACTIVE')
            self.assertEqual([s['id'] for s in state['services'] if s['status']=='HEALTHY'],['auth'])
            self.assertTrue(figure(state['services']).data)
            reset(path)
            self.assertFalse(snapshot(path)['exceptions'])
            self.assertTrue(all(s['status']=='HEALTHY' for s in snapshot(path)['services']))


if __name__ == '__main__':
    unittest.main()
