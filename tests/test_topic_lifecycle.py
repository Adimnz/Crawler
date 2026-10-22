"""Cancellation and deletion must survive worker completion and shared accounts."""
import tempfile
import unittest
from server.service import ResearchService

class TopicLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.s = ResearchService(self.tmp.name, seed=False, dsn="")
        self.s.auto_ai = False
        self.topic = self.s.topics.create('fixture manufacturing costs')

    def tearDown(self):
        self.s.close()
        self.tmp.cleanup()

    def test_stop_cancels_board_and_preserves_collected_evidence(self):
        detail = self.s.network_research.create_board('local-owner', {'topicId': self.topic['id']})
        self.s.db.put('document', 'retained', {'id': 'retained', 'text': 'Original source'})
        stopped = self.s.topics.stop(self.topic['id'])
        self.assertFalse(stopped['enabled'])
        self.assertEqual(self.s.topics.run(self.topic['id'])['state'], 'Paused')
        board = self.s.db.get('researchBoard', detail['board']['id'])
        self.assertEqual(board['expansionState'], 'cancelled')
        self.assertIsNotNone(self.s.db.get('document', 'retained'))

    def test_deleted_topic_cannot_be_resurrected_by_inflight_worker(self):
        self.s.topics.delete(self.topic['id'])
        self.s.topics._update(self.topic['id'], state='Monitoring', enabled=True)
        completed = self.s.topics._complete(self.topic['id'], {}, {}, state='Monitoring', nextRefreshAt=0)
        self.assertTrue(completed['deleted'])
        self.assertEqual(self.s.topics.list(), [])
        self.assertEqual(self.s.topics.refresh_due(), [])
        self.assertEqual(self.s.network_research.build(self.topic['id'])['nodes'], [])

    def test_account_removal_preserves_other_subscribers(self):
        for owner in ['alice', 'bob']:
            self.s.db.put('accountTopic', owner, {'id': owner, 'topicId': self.topic['id'], 'ownerId': owner, 'enabled': True})
        self.s.topics.delete(self.topic['id'], 'alice')
        self.assertIsNone(self.s.db.get('accountTopic', 'alice'))
        self.assertTrue(self.s.topics.get(self.topic['id'])['enabled'])
        self.assertIsNotNone(self.s.db.get('accountTopic', 'bob'))

    def test_stop_during_plan_does_not_continue_to_collection(self):
        def plan(item, **kwargs):
            self.s.topics.stop(item['id'])
            return item
        self.s.topics._plan = plan
        self.s.topics._refresh_sources = lambda *args: self.fail('Stopped topic collected more sources')
        self.assertEqual(self.s.topics.run(self.topic['id'])['state'], 'Paused')
