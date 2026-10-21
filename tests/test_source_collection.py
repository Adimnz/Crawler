"""Feed integrity, deduplication, access checks and bounded collection jobs."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.connectors import collect, feed_records, ConnectorError, DEFAULT_SOURCES
from server.service import ResearchService
from server.storage import now_ms

XML = b'<rss><channel><item><title>Bank launches climate fund</title><link>https://publisher.example/one</link><description>The bank reports a new climate investment fund.</description></item></channel></rss>'


class Network:
    def __init__(self): self.headers = []; self.status = 200; self.data = XML; self.resolved = None; self.denied = None
    def allowed(self, url): return url != self.denied
    def fetch(self, url, headers=None, **kwargs):
        self.headers.append(headers or {})
        return (b'' if self.status == 304 else self.data), {'status': self.status, 'etag': '"fixture-v1"'}, self.resolved or url


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.net = Network()
        self.s = ResearchService(self.tmp.name, self.net, seed=False, dsn='')
        self.source = self.s.add_source({'id':'fixture','name':'Publisher','url':'https://publisher.example/feed','kind':'rss','enabled':True})
    def tearDown(self): self.s.close(); self.tmp.cleanup()

    def test_conditional_fetch_keeps_originals_and_avoids_reanalysis(self):
        self.s.poll_source('fixture'); jobs = len(self.s.db.jobs(limit=1000))
        self.net.status = 304
        h = self.s.poll_source('fixture')
        self.assertEqual(self.net.headers[-1]['If-None-Match'], '"fixture-v1"')
        self.assertEqual(h['status'], 'not-modified'); self.assertEqual(h['totalItems'], 1)
        self.assertEqual(self.s.db.count('document'), 1); self.assertEqual(len(self.s.db.jobs(limit=1000)), jobs)
        self.assertTrue(self.s.objects.get(h['rawObjectKey']))

    def test_identical_feed_does_not_reindex_or_schedule_jobs(self):
        self.s.poll_source('fixture'); jobs = len(self.s.db.jobs(limit=1000))
        with patch.object(self.s, 'ingest', side_effect=AssertionError('Unchanged item indexed')):
            h = self.s.poll_source('fixture')
        self.assertEqual(h['lastPoll']['unchanged'], 1)
        self.assertEqual(len(self.s.db.jobs(limit=1000)), jobs)

    def test_revision_and_rejected_item_have_separate_counts(self):
        self.s.poll_source('fixture')
        self.net.data = XML.replace(b'new climate', b'revised climate').replace(b'</channel>', b'<item><title>Broken</title><link>javascript:alert(1)</link></item></channel>')
        h = self.s.poll_source('fixture')
        self.assertEqual(h['lastPoll']['revised'], 1); self.assertEqual(h['lastPoll']['rejected'], 1)
        self.assertEqual(self.s.db.latest('document',1)[0]['version'], 2)

    def test_discovery_and_community_stay_out_of_evidence(self):
        for role in ('discovery','community'):
            self.s.add_source({**self.source,'contentRole':role})
            self.net.data = XML.replace(b'/one', ('/'+role).encode())
            h = self.s.poll_source('fixture')
            self.assertEqual(h['lastPoll']['leads'], 1)
        self.assertEqual(self.s.db.count('document'), 0); self.assertEqual(self.s.db.count('claim'), 0)
        self.assertEqual(self.s.db.count('feedLead'), 2)
        self.assertTrue(all(item['discoveryOnly'] for item in self.s.source_items('fixture')['items']))

    def test_redirect_permissions_and_html_pages_are_not_healthy_feeds(self):
        self.net.resolved = self.net.denied = 'https://restricted.example/feed'
        with self.assertRaises(ConnectorError): self.s.poll_source('fixture')
        health = self.s.db.get('source','fixture')['health']
        self.assertFalse(health['ok']); self.assertGreater(health['retryAt'], now_ms()+300000)
        self.net.resolved = self.net.denied = None; self.net.data = b'<html><body>Sign in</body></html>'
        with self.assertRaises(ConnectorError): self.s.poll_source('fixture')

    def test_queue_is_deduplicated_and_respects_provider_cooldown(self):
        source = self.s.db.get('source','fixture'); source['health']={'retryAt':now_ms()+3600000}
        self.s.db.put('source','fixture',source)
        one=self.s.queue_source_poll('fixture'); two=self.s.queue_source_poll('fixture',manual=True)
        self.assertEqual(one,two); self.assertGreater(self.s.db.get_job(one)['available_at'],now_ms()+3500000)

    def test_catalogue_migrates_only_known_urls_and_keeps_paused_choices(self):
        self.s.add_source({'id':'yahoo-finance','name':'Yahoo Finance','url':'https://finance.yahoo.com/news/rssindex','enabled':False})
        self.s.add_source({'id':'bbc','name':'My BBC endpoint','url':'https://custom.example/my-feed','enabled':False})
        migrated=ResearchService(self.tmp.name,self.net,seed=True,dsn='')
        self.assertIn('/rss/2.0/',migrated.db.get('source','yahoo-finance')['url'])
        self.assertFalse(migrated.db.get('source','yahoo-finance')['enabled'])
        self.assertEqual(migrated.db.get('source','bbc')['url'],'https://custom.example/my-feed')
        self.assertGreaterEqual(migrated.db.count('source'),50); migrated.close()

    def test_known_legacy_http_links_are_upgraded_with_raw_attribution(self):
        xml=XML.replace(b'https://publisher.example/one',b'http://www.democracynow.org/story')
        self.assertEqual(feed_records(xml,{}),[])
        records=feed_records(xml,{'config':{'httpsArticleHosts':['www.democracynow.org']}})
        self.assertEqual(records[0]['url'],'https://www.democracynow.org/story')
        self.assertEqual(records[0]['raw']['url'],'http://www.democracynow.org/story')

    def test_public_discussion_api_links_are_encoded_and_stay_leads(self):
        source=next(s for s in DEFAULT_SOURCES if s['id']=='hn-api')
        self.net.json=lambda *args,**kwargs: {'hits':[{'objectID':'123&redirect=bad','title':'Finance discussion','created_at':'2025-01-01T00:00:00Z'}]}
        record=collect(source,self.net)['documents'][0]
        self.assertEqual(record['url'],'https://news.ycombinator.com/item?id=123%26redirect%3Dbad')
        self.s.add_source(source);self.s.poll_source('hn-api')
        self.assertEqual(self.s.db.count('document'),0)
        self.assertEqual(self.s.source_items('hn-api')['total'],1)

    def test_interactive_jobs_get_priority_without_starving_old_work(self):
        poll=self.s.db.enqueue('poll',{'sourceId':'fixture'})
        topic=self.s.db.enqueue('topic-research',{'topicId':'test'})
        self.assertEqual(self.s.db.claim_job()['id'],topic)
        with self.s.db.connection() as conn:
            self.s.db.execute(conn,'UPDATE jobs SET available_at=? WHERE id=?',(now_ms()-130000,poll))
        self.s.db.enqueue('network-research',{'taskId':'test'})
        self.assertEqual(self.s.db.claim_job()['id'],poll)

    def test_reserved_research_worker_cannot_be_taken_by_feed_backfill(self):
        poll=self.s.db.enqueue('poll',{'sourceId':'fixture'})
        topic=self.s.db.enqueue('topic-research',{'topicId':'test'})
        self.assertEqual(self.s.db.claim_job(kinds=('topic-research',))['id'],topic)
        self.assertIsNone(self.s.db.claim_job(kinds=('topic-research',)))
        self.assertEqual(self.s.db.claim_job(exclude_kinds=('topic-research',))['id'],poll)


if __name__ == '__main__': unittest.main()
