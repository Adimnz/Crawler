"""HTTP capacity and recommendation latency under controlled server contention."""
import concurrent.futures
import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from server.http import AppServer
from server.service import ResearchService

class HTTPStabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.s=ResearchService(self.tmp.name,seed=False,dsn='')
        with patch.dict(os.environ,{'CRAWLER_HTTP_CONNECTIONS':'2'}):
            self.server=AppServer(('127.0.0.1',0),self.s,Path(__file__).resolve().parents[1],auth_token='')
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.release=threading.Event()
    def tearDown(self):
        self.release.set();self.server.shutdown();self.server.server_close();self.s.close();self.tmp.cleanup()
    def get(self,path):
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
        try:
            conn.request('GET',path);response=conn.getresponse();return response.status,response.read(),dict(response.getheaders())
        finally:conn.close()
    def test_health_and_stylesheet_remain_available_when_normal_slots_are_full(self):
        barrier=threading.Barrier(3)
        def blocked_health():
            barrier.wait(timeout=3);self.release.wait(4);return {'service':'trend-crawler'}
        self.s.health=blocked_health
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(self.get,'/api/operations') for _ in range(2)]
            try:
                barrier.wait(timeout=3)
                status,body,_=self.get('/api/ready')
                self.assertEqual(status,200,body)
                self.assertTrue(json.loads(body)['ready'])
                self.assertEqual(self.get('/CRAWLER/css/styles.css')[0],200)
            finally:self.release.set()
            for future in futures:self.assertEqual(future.result()[0],200)

    def test_recommendation_http_read_queues_once_and_never_takes_calculation_lock(self):
        topic=self.s.topics.create('synthetic research')
        detail=self.s.network_research.create_board('local-owner',{'topicId':topic['id']})
        board_id=detail['board']['id']
        with self.s.recommendations.lock:
            first=self.get('/api/board-recommendations?boardId='+board_id)
            second=self.get('/api/board-recommendations?boardId='+board_id)
        self.assertEqual(first[0],202)
        self.assertTrue(json.loads(first[1])['refreshing'])
        self.assertEqual(second[0],202)
        jobs=[j for j in self.s.db.jobs('queued',100) if j['kind']=='recommendation-review']
        self.assertEqual(len(jobs),1)
        self.s.run_job(jobs[0]);self.s.db.finish_job(jobs[0]['id'])
        ready=self.get('/api/board-recommendations?boardId='+board_id)
        self.assertEqual(ready[0],200)
        self.assertFalse(json.loads(ready[1])['refreshing'])
        self.assertEqual(self.get('/api/ready')[0],200)

    def test_market_data_uses_collected_prices_without_fabricating_ohlc(self):
        from server.storage import now_ms
        at=now_ms()-1000
        self.s.db.put('asset','equity:NASDAQ:FIX',{'id':'equity:NASDAQ:FIX','assetClass':'equity','identityVerified':True,'ticker':'FIX','name':'Fixture'})
        self.s.db.put('source','fixture',{'id':'fixture','enabled':True,'tier':'primary'})
        for i in range(2):
            self.s.db.put('observation',str(i),{'id':str(i),'assetId':'equity:NASDAQ:FIX','sourceId':'fixture','metric':'adjusted_close','value':100+i,'currency':'USD','unit':'USD','observedAt':at+i,'retrievedAt':at,'canonical':True,'adjustment':'dividend-adjusted'})
        status,body,_=self.get('/api/market-data?symbol=FIX&type=stock')
        self.assertEqual(status,200)
        data=json.loads(body);self.assertEqual(data['quotes'][0]['price'],101)
        self.assertEqual(len(data['points']),2)
        self.assertNotIn('o',data['points'][0]);self.assertNotIn('h',data['points'][0])

    def test_source_health_writes_do_not_invalidate_recommendation_inputs(self):
        self.s.db.put('source','fixture',{'id':'fixture','enabled':True,'tier':'primary'})
        count=self.s.db.kind_revisions.get('sourceConfiguration')
        self.s.db.put('source','fixture',{'id':'fixture','enabled':True,'tier':'primary','health':{'ok':True},'nextPollAt':123})
        self.assertEqual(self.s.db.kind_revisions.get('sourceConfiguration'),count)
        self.s.db.put('source','fixture',{'id':'fixture','enabled':False,'tier':'primary'})
        self.assertGreater(self.s.db.kind_revisions.get('sourceConfiguration'),count)

    def test_archive_size_does_not_multiply_subject_citation_queries(self):
        topic=self.s.topics.create('battery')
        names=['Factory Alpha','Factory Beta','Factory Gamma','Factory Delta','Factory Epsilon']
        self.s.db.put('document','citation',{'id':'citation','version':1,'sourceId':'fixture','text':'; '.join(names),'title':'Cited names'})
        topic=self.s.topics._update(topic['id'],watchSubjects=[{'name':name,'evidence':[{'documentId':'citation','version':1,'quote':name}]} for name in names])
        for i in range(100):self.s.db.put('document',str(i),{'id':str(i),'version':1,'sourceId':'fixture','text':'Unrelated archive record.','title':'Other coverage'})
        detail={'board':{'topicId':topic['id']},'graph':{'nodes':[],'edges':[]}}
        with patch.object(self.s.db,'get',wraps=self.s.db.get) as reads:self.s.recommendations._context(detail)
        self.assertLessEqual(sum(c.args[0]=='document' for c in reads.call_args_list),len(names)+1)
