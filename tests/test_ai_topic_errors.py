"""Topic failures retain actionable status without exposing provider content."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.ai import AI
from server.connectors import ConnectorError


class FailedNetwork:
    error = None

    def json(self, *_args, **_kwargs):
        raise self.error


class TopicErrorTests(unittest.TestCase):
    def test_provider_status_is_preserved_and_response_text_is_redacted(self):
        network = FailedNetwork()
        ai = AI(network)
        ai.key, ai.model = "offline-secret-key", "offline-model"
        for method in (ai.plan_topic, ai.discover_topic):
            for status in (400, 401, 403, 404, 429, 503):
                network.error = ConnectorError("private provider content offline-secret-key", status=status)
                with self.subTest(method=method.__name__, status=status), self.assertRaises(ConnectorError) as caught:
                    method("regional credit")
                self.assertEqual(caught.exception.status, status)
                self.assertNotIn("private provider content", str(caught.exception))
                self.assertNotIn(ai.key, str(caught.exception))

    def test_timeout_status_survives_topic_wrapper(self):
        network = FailedNetwork()
        network.error = TimeoutError("private transport content")
        ai = AI(network)
        ai.key, ai.model = "offline-key", "offline-model"
        for method in (ai.plan_topic, ai.discover_topic):
            with self.subTest(method=method.__name__), self.assertRaises(ConnectorError) as caught:
                method("regional credit")
            self.assertEqual(caught.exception.status, 408)
            self.assertNotIn("private transport content", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
