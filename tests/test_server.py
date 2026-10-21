"""Run: python -m unittest discover -s CRAWLER/tests -p test_server.py -v"""
import datetime as dt
import http.client
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import analysis as a
from server.ai import AI
from server.connectors import ConnectorError, feed_records, validate_public_url, collect
from server.http import AppServer
from server.service import ResearchService
from server.storage import now_ms


class FixtureNetwork:
    def allowed(self, url):
        return True

    def fetch(self, url, headers=None, **kwargs):
        date = dt.datetime.now(dt.timezone.utc).strftime('%a, %d %b %Y %H:%M:%S GMT')
        content = f'<rss><channel><item><title>NVIDIA announces semiconductor supply investment</title><link>https://evidence.example/article</link><description>Company says investment increased by 12 percent this year.</description><pubDate>{date}</pubDate></item></channel></rss>'.encode()
        return content, {'content-type': 'application/rss+xml'}, url


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.service = ResearchService(self.temporary.name, FixtureNetwork(), seed=False, dsn='')
        self.source = self.service.add_source({'name': 'Original Research', 'url': 'https://evidence.example/feed', 'kind': 'rss', 'enabled': True, 'permissions': 'Test fixtures only', 'tier': 'primary', 'family': 'Original Research', 'language': 'en', 'region': 'North America', 'geographyVerified': True})

    def tearDown(self):
        self.service.close()
        self.temporary.cleanup()

    def document(self, **kwargs):
        return self.service.ingest(self.source, {'title': 'NVIDIA semiconductor exports increase by 12 percent', 'text': 'NVIDIA semiconductor exports increase by 12 percent. The original agency record describes the published manufacturing requirements.', 'url': 'https://evidence.example/article', 'publishedAt': now_ms() - 1000, **kwargs})

    def test_original_versions_and_replay_exclude_future_corrections(self):
        at = now_ms() - 10000
        first = self.service.ingest(self.source, {'title': 'NVIDIA semiconductor export proposal published', 'text': 'The agency published a semiconductor export proposal.', 'url': 'https://evidence.example/revision', 'publishedAt': at - 1000, 'raw': {'value': 'original'}}, at=at)
        second = self.service.ingest(self.source, {'title': first['title'], 'text': 'The agency corrected the semiconductor export proposal.', 'url': first['url'], 'publishedAt': at - 1000, 'raw': {'value': 'corrected'}}, at=at + 5000)
        self.assertEqual(second['version'], 2)
        replay = self.service.replay(at + 1000)
        self.assertEqual(replay['documents'][0]['version'], 1)
        self.assertIn('published', replay['documents'][0]['text'])
        self.assertEqual(json.loads(self.service.objects.get(first['objectKey']))['value'], 'original')

    def test_raw_duplicates_do_not_generate_versions(self):
        doc = self.document()
        self.document()
        self.assertEqual(len(self.service.db.versions(doc['id'])), 1)

    def test_source_commit_can_repair_an_interrupted_index_without_a_fake_version(self):
        original = self.service.db.put
        failed = False
        def interrupted(kind, *args, **kwargs):
            nonlocal failed
            if kind == 'event' and not failed:
                failed = True
                raise RuntimeError('Simulated interruption')
            return original(kind, *args, **kwargs)
        with patch.object(self.service.db, 'put', side_effect=interrupted):
            with self.assertRaises(RuntimeError):
                self.document()
        repaired = self.document()
        self.assertEqual(repaired['version'], 1)
        self.assertEqual(repaired['indexedVersion'], 1)
        self.assertEqual(len(self.service.db.versions(repaired['id'])), 1)
        self.assertIsNotNone(self.service.db.get('event', repaired['eventId']))

    def test_replay_reconstructs_review_state_between_two_assessments(self):
        at = now_ms() - 10000
        doc = self.service.ingest(self.source, {'title': 'An original research record', 'text': 'An original research record describes a proposed manufacturing schedule.', 'url': 'https://evidence.example/history', 'publishedAt': at - 1000}, at=at)
        claim = self.service.dossier(document_id=doc['id'])['claims'][0]
        claim.update(status='Contradicted', rationale='Later conflicting evidence', updatedAt=at + 3000)
        claim['history'] = [
            {'id': claim['id'], 'eventId': doc['eventId'], 'documentId': doc['id'], 'text': claim['text'], 'createdAt': at, 'at': at, 'status': 'Unverified', 'supersededAt': at + 1000},
            {'id': claim['id'], 'eventId': doc['eventId'], 'documentId': doc['id'], 'text': claim['text'], 'createdAt': at, 'at': at + 1000, 'status': 'Verified', 'rationale': 'Original direct evidence', 'supersededAt': at + 3000}
        ]
        self.service.db.put('claim', claim['id'], claim)
        replay = self.service.replay(at + 2000)
        restored = next(c for c in replay['claims'] if c['id'] == claim['id'])
        self.assertEqual(restored['status'], 'Verified')
        self.assertEqual(restored['rationale'], 'Original direct evidence')
        self.assertNotIn('history', restored)

    def test_translation_preserves_originals_and_reconciles_semantic_events(self):
        original = self.document()
        foreign = self.service.ingest(self.source, {'title': 'NVIDIA presenta cambios de exportaci\u00f3n para la industria', 'text': 'NVIDIA presenta cambios de exportaci\u00f3n para la industria. El documento original permanece disponible.', 'url': 'https://evidence.example/spanish', 'publishedAt': original['publishedAt'], 'language': 'es'})
        self.assertNotEqual(original['eventId'], foreign['eventId'])
        self.service.ai.translate = lambda doc: {'language': 'es', 'title': original['title'], 'text': original['text'], 'derived': True, 'model': 'fixture-model'}
        self.service.ai.extract = lambda doc: [{'text': doc['text'], 'quote': doc['text']}]
        self.service.ai.embed = lambda text: [1.0, 0.0]
        self.service.enrich(foreign['id'], 1)
        translated = self.service.db.get('document', foreign['id'])
        self.assertEqual(translated['title'], foreign['title'])
        self.assertEqual(translated['eventId'], original['eventId'])
        self.assertEqual(translated['translation']['title'], original['title'])
        self.assertEqual(len(self.service.db.versions(foreign['id'])), 1)

    def test_100_syndicated_publishers_are_one_candidate_chain(self):
        docs = [{'id': str(i), 'family': str(i), 'title': 'The same semiconductor supply story appeared today'} for i in range(100)]
        self.assertEqual(len(a.reporting_chains(docs)), 1)

    def test_extracted_claims_remain_unverified(self):
        doc = self.document()
        claims = self.service.dossier(document_id=doc['id'])['claims']
        self.assertTrue(claims)
        self.assertTrue(all(c['status'] == 'Unverified' and c['quote'] in doc['text'] for c in claims))

    def test_numerical_conflict_is_a_review_candidate(self):
        claims = [{'id': 'a', 'documentId': 'one', 'text': 'Company exports increased by 12 percent during the annual period.'}, {'id': 'b', 'documentId': 'two', 'text': 'Company exports increased by 27 percent during the annual period.'}]
        result = a.candidate_contradictions(claims)
        self.assertEqual(result[0]['status'], 'Needs review')

    def test_verified_requires_explicit_direct_evidence(self):
        doc = self.document()
        claim = self.service.dossier(document_id=doc['id'])['claims'][0]
        with self.assertRaisesRegex(ValueError, 'direct evidence'):
            self.service.review_claim({'id': claim['id'], 'status': 'Verified', 'rationale': 'Many copies exist.'})
        result = self.service.review_claim({'id': claim['id'], 'status': 'Verified', 'rationale': 'Direct record reviewed.', 'directEvidenceReviewed': True, 'evidence': [{'documentId': doc['id'], 'relation': 'supports'}]})
        self.assertEqual(result['status'], 'Verified')

    def test_correction_invalidates_prior_review(self):
        doc = self.document()
        claim = self.service.dossier(document_id=doc['id'])['claims'][0]
        self.service.review_claim({'id': claim['id'], 'status': 'Verified', 'rationale': 'Record reviewed.', 'directEvidenceReviewed': True, 'evidence': [{'documentId': doc['id'], 'relation': 'supports'}]})
        self.document(text='NVIDIA corrected its previous semiconductor export statement.')
        self.assertTrue(self.service.db.get('claim', claim['id'])['reviewRequired'])

    def test_source_outage_and_browser_gaps_prevent_normal_baselines(self):
        at = now_ms()
        docs = [{'title': 'Some event', 'publishedAt': at - 1000, 'family': 'one'}]
        spans = [{'start': at - 2 * a.DAY, 'end': at}]
        self.assertTrue(a.analyze_trend(docs, at, spans, 1)['baselineAvailable'])
        self.assertFalse(a.analyze_trend(docs, at, spans, .1)['baselineAvailable'])
        self.assertFalse(a.analyze_trend(docs, at, [{'start': at - 10000, 'end': at}], 1)['baselineAvailable'])

    def test_entities_and_blockchain_transactions_are_namespaced(self):
        at = now_ms() - 1000
        one = self.service.observation(self.source, {'assetId': 'crypto:ethereum:0xabc', 'metric': 'transfer', 'value': 7, 'observedAt': at, 'transactionHash': 'tx', 'blockHash': 'block-a'})
        two = self.service.observation(self.source, {'assetId': 'crypto:solana:0xabc', 'metric': 'transfer', 'value': 7, 'observedAt': at, 'transactionHash': 'tx', 'blockHash': 'block-a'})
        self.assertNotEqual(one['id'], two['id'])
        self.service.observation(self.source, {**one, 'blockHash': 'block-b'})
        self.assertEqual(self.service.db.count('observation'), 2)
        self.assertEqual(self.service.db.count('observationRevision'), 1)

    def test_stale_measurements_are_flagged(self):
        self.service.observation(self.source, {'assetId': 'equity:NASDAQ:NVDA', 'metric': 'price_usd', 'value': 50, 'observedAt': now_ms() - a.DAY})
        result = a.quantitative(self.service.db.latest('observation'), now_ms())
        self.assertTrue(result[0]['stale'])
        with self.assertRaises(ValueError):
            self.service.observation(self.source, {'assetId': 'NVDA', 'value': 50, 'observedAt': now_ms()})

    def test_recovered_source_does_not_hide_a_previous_window_outage(self):
        at = now_ms()
        source = self.service.db.get('source', self.source['id'])
        source.update(createdAt=at - 3 * a.DAY, interval=a.DAY, health={'ok': True, 'checkedAt': at})
        self.service.db.put('source', source['id'], source)
        self.service.db.put('healthSample', 'failed', {'sourceId': source['id'], 'checkedAt': at - 2 * a.DAY, 'ok': False, 'interval': a.DAY})
        self.service.db.put('healthSample', 'recovered', {'sourceId': source['id'], 'checkedAt': at - a.DAY, 'ok': True, 'interval': a.DAY})
        result = self.service.provider_coverage(at)
        self.assertEqual(result['previous'], 0)
        self.assertEqual(result['current'], 1)

    def test_graph_traversal_separates_hypothesis_from_confirmed_relation(self):
        doc = self.document()
        graph = self.service.graph(doc['eventId'])
        self.assertIn('equity:NASDAQ:NVDA', [n['id'] for n in graph['nodes']])
        self.assertTrue(graph['hypotheses'])
        with self.assertRaisesRegex(ValueError, 'explicit analyst review'):
            self.service.add_relationship({'from': 'a', 'to': 'b', 'type': 'supplies', 'confirmed': True, 'evidence': [doc['id']]})

    def test_disconfirmation_queues_only_registered_sources(self):
        doc = self.document()
        result = self.service.investigate(doc['eventId'])
        self.assertTrue(result['questions'])
        self.assertEqual(len(result['followupJobs']), 1)
        self.assertEqual(self.service.db.get_job(result['followupJobs'][0])['payload']['sourceId'], self.source['id'])

    def test_forecast_original_is_preserved_and_brier_is_descriptive(self):
        forecast = self.service.forecast({'statement': 'A record will be published.', 'assumptions': 'A review proceeds.', 'dueAt': now_ms() + a.DAY, 'probability': .8})
        result = self.service.resolve_forecast(forecast['id'], {'outcome': 'Occurred', 'evidence': 'https://evidence.example/record'})
        self.assertEqual(result['statement'], forecast['statement'])
        self.assertAlmostEqual(a.evaluate_forecasts([result])[0]['brierScore'], .04)
        self.assertFalse(a.evaluate_forecasts([result])[0]['calibrated'])
        with self.assertRaisesRegex(ValueError, 'already resolved'):
            self.service.resolve_forecast(forecast['id'], {'outcome': 'Did not occur', 'evidence': 'rewrite'})

    def test_queue_retries_and_dead_letters_are_recoverable(self):
        job_id = self.service.db.enqueue('poll', {'sourceId': self.source['id']}, 'unique', max_attempts=1)
        self.assertEqual(self.service.db.enqueue('poll', {}, 'unique'), job_id)
        job = self.service.db.claim_job()
        self.service.db.fail_job(job, 'HTTP 429', retry_after=120)
        self.assertEqual(self.service.db.get_job(job_id)['state'], 'dead')
        self.assertTrue(self.service.db.retry_job(job_id))
        self.assertEqual(self.service.db.get_job(job_id)['attempts'], 0)

    def test_hash_chained_audit_detects_tampering(self):
        self.document()
        self.assertTrue(self.service.db.verify_audit()['valid'])
        with self.service.db.connection() as conn:
            self.service.db.execute(conn, "UPDATE audit SET detail=?", ('tampered',))
        self.assertFalse(self.service.db.verify_audit()['valid'])

    def test_workers_collect_and_generate_scheduled_briefs_without_a_browser(self):
        schedule = self.service.schedule_brief({'hours': 1})
        schedule['nextRunAt'] = now_ms() - 1
        self.service.db.put('schedule', schedule['id'], schedule)
        self.service.start(2)
        deadline = time.time() + 6
        while time.time() < deadline and (not self.service.db.count('document') or not self.service.db.count('brief')):
            time.sleep(.1)
        self.assertEqual(self.service.db.count('document'), 1)
        self.assertEqual(self.service.db.count('brief'), 1)

    def test_followup_research_uses_saved_context_and_links_records(self):
        self.document()
        first = self.service.research('What NVIDIA semiconductor developments should I watch?', 'test', use_ai=False)
        self.assertTrue(first['assertions'])
        second = self.service.research('What changed?', 'test', use_ai=False)
        self.assertTrue(second['documents'])
        self.assertEqual(len(self.service.db.get('memory', 'test')['turns']), 2)

    def test_media_provenance_does_not_claim_authenticity(self):
        doc = self.service.import_document({'sourceId': self.source['id'], 'title': 'Imported media reference', 'description': 'An analyst-described scene, not an authenticity verdict.', 'url': 'https://evidence.example/media', 'contentType': 'image/png', 'contentBase64': 'aW1hZ2U='})
        self.assertEqual(doc['mediaProvenance']['authenticity'], 'Unknown')


class InputAndAITests(unittest.TestCase):
    def test_xml_entities_are_not_parsed(self):
        with self.assertRaisesRegex(ConnectorError, 'entities'):
            feed_records(b'<!DOCTYPE rss [<!ENTITY bad SYSTEM "file:///etc/passwd">]><rss/>', {})

    def test_private_network_and_unsafe_schemes_are_blocked(self):
        resolver = lambda *args, **kw: [(None, None, None, None, ('127.0.0.1', 443))]
        with self.assertRaisesRegex(ConnectorError, 'Private'):
            validate_public_url('https://internal.example/', resolver)
        for url in ['file:///secret', 'http://example.com', 'https://user:pass@example.com']:
            with self.assertRaises(ConnectorError):
                validate_public_url(url, resolver)

    def test_ai_rejects_unknown_citations_and_nonexistent_quote_spans(self):
        ai = AI(FixtureNetwork())
        ai.model, ai.key = 'fixture-model', 'never-a-real-key'
        ai.structured = lambda *args: {'assertions': [{'text': 'Supported report', 'documentIds': ['doc'], 'quotes': ['Original source quote']}, {'text': 'Invented claim', 'documentIds': ['unknown'], 'quotes': ['no']}, {'text': 'Invented quote', 'documentIds': ['doc'], 'quotes': ['not in source']}], 'uncertainties': [], 'nextQuestions': []}
        result = ai.answer('question', [{'id': 'doc', 'text': 'Original source quote', 'title': 'Title', 'source': 'Publisher', 'publishedAt': 1}], [])
        self.assertEqual(len(result['assertions']), 1)
        self.assertIn('2 unsupported', result['uncertainties'][0])


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.service = ResearchService(self.temporary.name, FixtureNetwork(), seed=False, dsn='')
        self.server = AppServer(('127.0.0.1', 0), self.service, Path(__file__).resolve().parents[1], auth_token='owner-test-token')
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_port

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.service.close()
        self.temporary.cleanup()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        connection.request(method, path, body=json.dumps(body) if body is not None else None, headers={'Content-Type': 'application/json', **(headers or {})})
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def test_owner_auth_and_csrf_are_required_for_mutations(self):
        status, _, _ = self.request('GET', '/api/sources')
        self.assertEqual(status, 401)
        status, headers, data = self.request('POST', '/api/login', {'token': 'owner-test-token'})
        cookie = headers['Set-Cookie'].split(';')[0]
        csrf = json.loads(data)['csrf']
        self.assertEqual(status, 200)
        status, _, _ = self.request('POST', '/api/briefs', {}, {'Cookie': cookie})
        self.assertEqual(status, 403)
        status, _, _ = self.request('POST', '/api/briefs', {}, {'Cookie': cookie, 'X-Crawler-CSRF': csrf})
        self.assertEqual(status, 200)

    def test_env_and_server_sources_are_not_served(self):
        for path in ['/CRAWLER/.env', '/CRAWLER/server/service.py', '/CRAWLER/data/research.sqlite3']:
            self.assertEqual(self.request('GET', path)[0], 404)
        self.assertEqual(self.request('GET', '/CRAWLER/index.html')[0], 200)

    def test_dns_rebinding_and_cross_origin_writes_are_rejected(self):
        self.assertEqual(self.request('GET', '/api/health', headers={'Host': 'attacker.example'})[0], 403)
        self.assertEqual(self.request('POST', '/api/login', {'token': 'owner-test-token'}, {'Origin': 'https://attacker.example'})[0], 403)


if __name__ == '__main__':
    unittest.main()
