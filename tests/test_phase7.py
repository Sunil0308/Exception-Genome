import asyncio
import os
import selectors
import time
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from api.main import build_app


class PollingSelector(selectors.SelectSelector):
    def select(self, timeout=None):
        if timeout != 0:
            time.sleep(min(timeout, 0.005) if timeout is not None else 0.005)
        return []


class InMemoryTestLoop(asyncio.SelectorEventLoop):
    """Test-only fallback for Windows sandboxes without a loopback wake socket."""

    def __init__(self):
        super().__init__(PollingSelector())

    def _make_self_pipe(self):
        self._ssock = None
        self.call_later(0.005, self._poll)

    def _poll(self):
        self.call_later(0.005, self._poll)

    def _close_self_pipe(self):
        pass

    def _write_to_self(self):
        pass


class ApiWorkflowTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        options = {'loop_factory': InMemoryTestLoop} if os.environ.get('EXCEPTION_GENOME_TEST_IN_MEMORY_LOOP') == '1' else {}
        self.client = self.enterContext(TestClient(
            build_app(Path(folder.name) / 'test.db', api_key='demo-test-key'), backend_options=options))
        self.headers = {'X-API-Key': 'demo-test-key'}

    def call(self, url, body=None, key=None, expected=200):
        headers = dict(self.headers)
        if key:
            headers['Idempotency-Key'] = key
        response = self.client.post(url, json=body, headers=headers)
        self.assertEqual(response.status_code, expected, response.text[:1500])
        return response.json()

    def prepare(self, scenario):
        incident_id = self.call(f'/demo/scenarios/{scenario}/start', expected=201)['id']
        for _ in range(25):
            if not self.call(f'/demo/incidents/{incident_id}/advance')['advanced']:
                break
        base = f'/incidents/{incident_id}'
        data = self.call(base + '/analyse')
        return base, data['correlation_clusters']

    def resolve(self, base, cluster, *, review=False, mode='NORMAL'):
        path = base + '/assignments/' + cluster['id']
        contract = self.call(path + '/contract', expected=201)
        binding = {'expected_contract_hash': contract['contract_hash']}
        self.call(path + '/safety', binding)
        self.assertEqual(self.call(path + '/simulate-impact', binding)['result'], 'PASS')
        if review:
            reviewers = '/reviews/REV-' + cluster['id'] + '/decision'
            self.call(path + '/execute', binding, expected=409)
            self.call(reviewers, dict(binding, reviewer_identity='Operations Reviewer',
                                      decision='APPROVE CONTROLLED ACTION', reason='Synthetic projection checked'),
                      key=cluster['id'] + '-approval', expected=201)
        result = self.call(path + '/execute', dict(binding, mode=mode), key=cluster['id'] + '-execute')
        self.assertEqual(self.call(path + '/execute', dict(binding, mode=mode),
                                   key=cluster['id'] + '-execute')['execution_id'], result['execution_id'])
        execution = '/executions/' + result['execution_id']
        for _ in range(25):
            if self.call(execution + '/advance')['status'] == 'AWAITING_VERIFICATION':
                break
        return self.call(execution + '/verify')

    def test_health_auth_and_stale_contract(self):
        self.assertEqual(self.client.get('/health').json()['status'], 'ok')
        self.assertEqual(self.client.post('/demo/reset/full').status_code, 401)
        base, clusters = self.prepare('merchant-local-job')
        url = base + '/assignments/' + clusters[0]['id'] + '/contract'
        first = self.call(url, key='contract-replay', expected=201)
        self.assertEqual(first, self.call(url, key='contract-replay', expected=201))
        error = self.call(url, {'expected_contract_hash': '0' * 64}, key='contract-replay', expected=409)
        self.assertEqual(error['error']['code'], 'IDEMPOTENCY_CONFLICT')
        error = self.call(url, {'expected_contract_hash': '0' * 64}, expected=409)
        self.assertEqual(error['error']['code'], 'CONTRACT_STALE')

    def test_datahub_workflow_and_memory(self):
        base, clusters = self.prepare('datahub-credential')
        self.assertEqual(self.resolve(base, clusters[0])['status'], 'VERIFIED')
        self.assertEqual(self.client.get(base).json()['status'], 'RESOLVED')
        self.assertEqual(len(self.client.get('/memory').json()), 1)

    def test_isolated_and_concurrent_review_workflows(self):
        base, clusters = self.prepare('merchant-local-job')
        verified = self.resolve(base, clusters[0], review=True)
        self.assertEqual(verified['status'], 'VERIFIED', [r['name'] for r in verified['checks'] if r['result'] != 'PASS'])
        self.call('/demo/reset/current')
        base, clusters = self.prepare('concurrent-operations')
        self.assertEqual(len(clusters), 2)
        verified = self.resolve(base, clusters[0], review=True)
        self.assertEqual(verified['status'], 'VERIFIED', [r['name'] for r in verified['checks'] if r['result'] != 'PASS'])
        self.assertNotEqual(self.client.get(base).json()['status'], 'RESOLVED')
        statuses = {row['id']: row['status'] for row in self.client.get(base + '/exceptions').json()}
        self.assertTrue(all(statuses[member] == 'ACTIVE' for member in clusters[1]['members']))
        self.assertEqual(self.resolve(base, clusters[1], review=True)['status'], 'VERIFIED')
        self.assertEqual(self.client.get(base).json()['status'], 'RESOLVED')

    def test_correlated_cluster_and_singleton_close_independently(self):
        base, clusters = self.prepare('mixed-operations')
        pair, singleton = sorted(clusters, key=lambda r: -len(r['members']))
        self.assertEqual((len(pair['members']), singleton['assignment_status']), (2, 'SINGLETON'))
        self.assertEqual(self.resolve(base, pair, review=True)['status'], 'VERIFIED')
        self.assertNotEqual(self.client.get(base).json()['status'], 'RESOLVED')
        self.assertEqual(self.resolve(base, singleton, review=True)['status'], 'VERIFIED')
        self.assertEqual(self.client.get(base).json()['status'], 'RESOLVED')

    def test_evidence_changes_ambiguous_diagnosis(self):
        base, clusters = self.prepare('ambiguous-report')
        assignment = clusters[0]['id']
        url = base + '/assignments/' + assignment
        self.call(url + '/request-evidence', {'reviewer_identity': 'Risk Reviewer',
                                            'decision': 'REQUEST MORE EVIDENCE', 'reason': 'Trace needed'}, expected=201)
        change = self.call('/demo' + url + '/evidence/DEPENDENCY_PROBE', expected=201)
        self.assertEqual(change['previous_diagnosis']['diagnosis_outcome'], 'NO_CONFIDENT_ROOT_CAUSE')
        self.assertEqual(change['diagnosis']['diagnosis_outcome'], 'ROOT_CAUSE_CANDIDATE')
        self.assertEqual(len(self.client.get(base + '/evidence').json()), 1)

    def test_verification_failure_and_rollback_are_visible(self):
        base, clusters = self.prepare('datahub-credential')
        self.assertEqual(self.resolve(base, clusters[0], mode='SYNTHETIC_VERIFICATION_FAILURE')['status'], 'FAILED')
        self.assertEqual(self.client.get(base).json()['status'], 'HUMAN_REVIEW_REQUIRED')
        self.assertTrue(self.client.get('/audit', params={'action': 'ROLLBACK_COMPLETED'}).json())





