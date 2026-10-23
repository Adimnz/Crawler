"""Synthetic offline fixtures: these returns are never product demo data."""
import math
import random
import tempfile
import unittest
from unittest.mock import patch
from server.service import ResearchService
from server.recommendations import evaluate_prices, POLICY, _estimate
from server.storage import now_ms
from server import analysis as a


def prices(n=1100, backfill=False):
    # Smooth repeating regimes let the fixed analogue model be tested against
    # an unconditional baseline without selecting parameters to fit an asset.
    end=now_ms()-a.HOUR
    start=end-(n-1)*a.DAY
    rng=random.Random(71)
    value=100
    result=[]
    for i in range(n):
        value*=math.exp(.0015+.007*math.sin(i/36)+rng.gauss(0,.001))
        at=start+i*a.DAY
        result.append({'id':'p'+str(i),'sourceId':'market','assetId':'crypto:coingecko:fixture',
                       'metric':'price_usd','value':value,'unit':'USD','currency':'USD','frequency':'daily','adjustment':'raw',
                       'observedAt':at,'retrievedAt':end if backfill else at+1000,'availableAt':at+1000,
                       'sourceUrl':'https://provider.example/fixture'})
    return result


class PriceModelTests(unittest.TestCase):
    def test_chronology_is_purged_and_outputs_finite_ranges(self):
        result=evaluate_prices(prices(), now_ms(), 10)
        self.assertGreater(result['validation']['samples'],20)
        self.assertTrue(all(f['lastTrainingOutcomeAvailableAt']<f['decisionAt']<f['entryAt']<f['exitAt'] for f in result['validation']['folds']))
        forecast=result['forecast']
        self.assertLessEqual(forecast['p10Percent'],forecast['medianPercent'])
        self.assertLessEqual(forecast['medianPercent'],forecast['p90Percent'])
        windows=result['outcomeSamples']
        self.assertTrue(all(x['exitAt']<=y['entryAt'] for x,y in zip(windows,windows[1:])))

    def test_backfill_does_not_create_point_in_time_validation(self):
        result=evaluate_prices(prices(backfill=True),now_ms(),10)
        self.assertEqual(result['pointInTimeSamples'],0)
        self.assertIsNone(result['validation'])
        self.assertNotEqual(result['status'],'Eligible entry signal')

    def test_future_rows_cannot_change_an_earlier_assessment(self):
        rows=prices()
        at=rows[800]['retrievedAt']
        one=evaluate_prices(rows,at,10)
        rows[-1]['value']=1e100
        two=evaluate_prices(rows,at,10)
        self.assertEqual(one['forecast'],two['forecast'])
        self.assertEqual(one['validation'],two['validation'])

    def test_costs_are_explicit_and_reduce_every_historical_return(self):
        rows=prices()
        gross=evaluate_prices(rows,now_ms(),0)
        net=evaluate_prices(rows,now_ms(),100)
        self.assertAlmostEqual(gross['forecast']['medianPercent']-net['forecast']['medianPercent'],1)
        missing=evaluate_prices(rows,now_ms())
        self.assertNotEqual(missing['status'],'Eligible entry signal')
        self.assertTrue(any('fees' in reason for reason in missing['blockers']))
        with self.assertRaises(ValueError): evaluate_prices(rows,now_ms(),float('nan'))

    def test_stale_gappy_and_raw_equity_histories_are_withheld(self):
        rows=prices()
        self.assertNotEqual(evaluate_prices(rows,now_ms()+3*a.DAY,0)['status'],'Eligible entry signal')
        for r in rows:r['assetId']='equity:NASDAQ:FIX'
        self.assertIsNone(evaluate_prices(rows,now_ms(),0)['forecast'])
        gappy=prices()[::5]
        self.assertEqual(evaluate_prices(gappy,now_ms(),0)['pointInTimeSamples'],0)

    def test_live_quote_can_withdraw_an_older_daily_entry(self):
        rows=prices(1000)
        live={**rows[-1], 'id':'live', 'frequency':'snapshot', 'observedAt':now_ms()-1000, 'retrievedAt':now_ms()-500, 'availableAt':now_ms()-500, 'value':rows[-1]['value']*.9}
        result=evaluate_prices(rows+[live],now_ms(),10)
        self.assertEqual(result['latestQuote']['id'],'live')
        self.assertNotEqual(result['status'],'Eligible entry signal')
        self.assertTrue(any('newer market quote' in b for b in result['blockers']))

    def test_comparable_current_provider_disagreement_blocks_an_entry(self):
        rows=prices(1000)
        second={**rows[-1], 'id':'other-provider', 'sourceId':'other-market','value':rows[-1]['value']*1.1}
        result=evaluate_prices(rows+[second],now_ms(),10)
        self.assertTrue(any('providers disagree' in b for b in result['blockers']))

    def test_features_outside_observed_training_range_are_not_supported(self):
        training=[{'id':str(i),'features':[i/100,i/200],'returnPercent':1+i/100} for i in range(30)]
        self.assertFalse(_estimate(training,[10,20])['withinObservedFeatureRange'])

    def test_declared_history_cap_is_visible(self):
        result=evaluate_prices(prices(1600),now_ms(),0)
        self.assertEqual(result['usedHistorySessions'],POLICY['maximumHistorySessions'])
        self.assertEqual(result['excludedOlderSessions'],100)


class BoardRecommendationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.s=ResearchService(self.tmp.name,seed=False,dsn='')
        self.s.auto_ai=False
        source={'id':'market','kind':'json','name':'Synthetic primary','enabled':True,'tier':'primary','url':'https://fixture.example/feed'}
        self.s.db.put('source','market',source)
        self.topic=self.s.topics.create('fixture battery research')
        self.s.topics._update(self.topic['id'],state='Monitoring',pendingEvidenceChanges={},evidence=[])
        self.detail=self.s.network_research.create_board('alice',{'topicId':self.topic['id']})
        self.board_id=self.detail['board']['id']
        self.s.db.put('asset','crypto:coingecko:fixture',{'id':'crypto:coingecko:fixture','assetClass':'crypto','identityVerified':True,'name':'Fixture Coin','ticker':'FIX'})
        self.doc={'id':'article','version':1,'sourceId':'market','source':'Synthetic primary','title':'Fixture battery research','text':'Fixture Coin supplies fixture battery research.','url':'https://fixture.example/article','entities':[]}
        self.s.db.put('document','article',self.doc)
        self.s.recommendations.configure({'roundTripCostBps':10})
        for row in prices(1000):self.s.db.put('observation',row['id'],row)

    def tearDown(self):
        self.s.close();self.tmp.cleanup()

    def test_candidates_derive_from_sources_and_cache_is_private(self):
        result=self.s.recommendations.board('alice',self.board_id)
        self.assertEqual([r['assetId'] for r in result['assets']],['crypto:coingecko:fixture'])
        self.assertTrue(result['assets'][0]['topicEvidence'])
        self.assertEqual(result['assets'][0]['status'],'Eligible entry signal')
        self.assertIsNotNone(result['assets'][0]['potentialReturn'])
        self.assertEqual(self.s.recommendations.board('alice',self.board_id)['revision'],result['revision'])
        with self.assertRaises(ValueError):self.s.recommendations.board('bob',self.board_id)

    def test_new_contradiction_invalidates_cached_signal_immediately(self):
        one=self.s.recommendations.board('alice',self.board_id)
        self.s.db.put('claim','conflict',{'id':'conflict','documentId':'article','status':'Disputed'})
        two=self.s.recommendations.board('alice',self.board_id)
        self.assertIsNotNone(one['assets'][0]['potentialReturn'])
        self.assertGreater(two['revision'],one['revision'])
        self.assertIsNone(two['assets'][0]['potentialReturn'])
        self.assertIn('conflict',two['assets'][0]['conflictIds'])

    def test_revised_price_and_disabled_source_change_assessment(self):
        one=self.s.recommendations.board('alice',self.board_id)
        row=self.s.db.get('observation','p999');row['value']*=.75
        self.s.db.put('observation',row['id'],row)
        two=self.s.recommendations.board('alice',self.board_id)
        self.assertNotEqual(one['assets'][0]['dataFingerprint'],two['assets'][0]['dataFingerprint'])
        source=self.s.db.get('source','market');source['enabled']=False;self.s.db.put('source','market',source)
        three=self.s.recommendations.board('alice',self.board_id)
        self.assertIsNone(three['assets'][0]['market'])
        self.assertIsNone(three['assets'][0]['potentialReturn'])

    def test_new_branch_direction_can_add_an_unrelated_named_asset(self):
        branch=self.s.topics.create({'query':'fixture robotics','embedded':True})
        board=self.s.db.get('researchBoard',self.board_id);board['branchTopics']=[branch['id']];self.s.db.put('researchBoard',self.board_id,board)
        self.s.db.put('asset','crypto:coingecko:robot',{'id':'crypto:coingecko:robot','assetClass':'crypto','identityVerified':True,'name':'Robot Coin'})
        self.s.db.put('document','robot',{'id':'robot','version':1,'sourceId':'market','source':'Primary','title':'Robotics','text':'Robot Coin supplies fixture robotics.','url':'https://fixture.example/robot'})
        result=self.s.recommendations.board('alice',self.board_id)
        self.assertIn('crypto:coingecko:robot',[r['assetId'] for r in result['assets']])
        self.assertEqual(result['coverage']['branchesIncluded'],2)

    def test_reported_measurement_revision_updates_context_without_inventing_a_return_effect(self):
        at=now_ms()-1000
        row={'id':'revenue','assetId':'crypto:coingecko:fixture','metric':'revenue','value':100,'unit':'USD','currency':'USD','sourceId':'market','observedAt':at,'retrievedAt':at}
        self.s.db.put('observation',row['id'],row)
        one=self.s.recommendations.board('alice',self.board_id)
        row['value']=80;self.s.db.put('observation',row['id'],row)
        two=self.s.recommendations.board('alice',self.board_id)
        self.assertEqual(two['assets'][0]['contextObservations'][0]['value'],80)
        self.assertGreater(two['revision'],one['revision'])
        self.assertEqual(two['assets'][0]['potentialReturn'],one['assets'][0]['potentialReturn'])

    def test_ticker_only_quote_does_not_resolve_a_topic_asset(self):
        doc={**self.doc,'text':'$FIX supplies fixture battery research.'};self.s.db.put('document',doc['id'],doc)
        result=self.s.recommendations.board('alice',self.board_id)
        self.assertTrue(any('ticker-only' in b for b in result['assets'][0]['blockers']))
        self.assertEqual(result['eligibleCount'],0)

    def test_background_review_coalesces_changed_inputs(self):
        self.s.recommendations.board('alice',self.board_id)
        row=self.s.db.get('observation','p999');row['value']*=1.05;self.s.db.put('observation',row['id'],row)
        self.assertEqual(len(self.s.recommendations.queue_due(now_ms()+61000)),1)
        self.assertEqual(self.s.recommendations.queue_due(now_ms()+61000),[])

    def test_clock_alone_expires_entry(self):
        self.assertEqual(self.s.recommendations.board('alice',self.board_id)['eligibleCount'],1)
        with patch('server.recommendations.now_ms',return_value=now_ms()+48*a.HOUR):
            expired=self.s.recommendations.board('alice',self.board_id)
        self.assertEqual(expired['eligibleCount'],0)
        self.assertIsNone(expired['assets'][0]['potentialReturn'])

    def test_topic_pause_withdraws_entry_and_keeps_append_only_revisions(self):
        one=self.s.recommendations.board('alice',self.board_id)
        self.s.topics._update(self.topic['id'],enabled=False)
        two=self.s.recommendations.board('alice',self.board_id)
        self.assertTrue(any('stopped' in x for x in two['assets'][0]['blockers']))
        self.assertIsNotNone(self.s.db.get('recommendationRevision',self.board_id+':'+str(one['revision'])))


class RecommendationRaceTests(unittest.TestCase):
    setUp=BoardRecommendationTests.setUp
    tearDown=BoardRecommendationTests.tearDown
    def test_concurrent_input_revision_withholds_all_returns(self):
        original=self.s.recommendations._build
        def changed(*args):
            result=original(*args)
            self.s.db.put('claim','late-conflict',{'id':'late-conflict','documentId':'article','status':'Disputed'})
            return result
        self.s.recommendations._build=changed
        result=self.s.recommendations.board('alice',self.board_id)
        self.assertEqual(result['status'],'Review required')
        self.assertEqual(result['eligibleCount'],0)
        self.assertTrue(all(r['potentialReturn'] is None for r in result['assets']))
