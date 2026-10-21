"""Regression checks for responsive OpenAI setup and verified connection saves."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.ai import AI
from server.ai_settings import AISettings
from server.connectors import ConnectorError
from server.storage import Database


KEY = "sk-new-connection-fixture-not-a-live-secret"
MODEL = "fixture-text-model"


class Network:
    def __init__(self):
        self.calls = []
        self.error = None
        self.started, self.release = threading.Event(), threading.Event()
        self.block = False
        self.models = {"object": "list", "data": [{"id": MODEL}]}
        self.response = {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": '{"status":"connected"}'}]}]}

    def json(self, url, headers=None, body=None):
        self.calls.append({"url": url, "body": body, "keyMatches": headers.get("Authorization") == "Bearer " + KEY})
        self.started.set()
        if self.block and not self.release.wait(3):
            raise TimeoutError("Fixture request timed out")
        if self.error:
            raise self.error
        return self.models if url.endswith("/models") else self.response


class OpenAIConnectionTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {"OPENAI_API_KEY": "", "OPENAI_MODEL": "", "CRAWLER_AUTO_AI": "false"})
        self.environment.start()
        self.temporary = tempfile.TemporaryDirectory()
        self.network = Network()
        self.service = SimpleNamespace(db=Database(self.temporary.name), network=self.network, ai=AI(self.network), auto_ai=False)
        self.settings = AISettings(self.service)

    def tearDown(self):
        self.network.release.set()
        self.temporary.cleanup()
        self.environment.stop()

    def saved(self):
        return self.settings.configure({"apiKey": KEY, "model": MODEL, "automaticAnalysis": False})

    def body(self):
        return {"apiKey": KEY, "model": MODEL, "automaticAnalysis": True}

    def test_model_dropdown_comes_from_actual_key_model_endpoint_without_saving_key(self):
        ids = ["gpt-6-astra", "gpt-6-luna", "gpt-6.1-sol", "ft:gpt-6.1-sol:project:research", "text-embedding-3-small",
               "gpt-image-1", "gpt-audio", "gpt-realtime", "omni-moderation-latest", "whisper-1", "tts-1-hd",
               "gpt-4o-mini-transcribe", "gpt-4o-mini-tts", "dall-e-3", "sora-2", "babbage-002", "text-davinci-003"]
        self.network.models["data"] = [{"id": model, "owned_by": KEY} for model in ids] + [{"id": "bad\nmodel"}, {"id": KEY}, None]
        result = self.settings.available_models(KEY)
        self.assertEqual({item["id"] for item in result["models"]}, set(ids[:4]))
        self.assertIn("verifies", result["capabilityNote"])
        self.assertEqual(result["selectedModel"], "")
        self.assertNotIn(KEY, json.dumps(result))
        self.assertFalse(self.settings.path.exists())
        call = self.network.calls[-1]
        self.assertEqual(call["url"], "https://api.openai.com/v1/models")
        self.assertIsNone(call["body"])
        self.assertTrue(call["keyMatches"])

    def test_models_use_saved_secret_and_report_selected_model(self):
        self.saved()
        result = self.settings.available_models()
        self.assertEqual(result["selectedModel"], MODEL)
        self.assertEqual(result["models"], [{"id": MODEL}])
        self.assertTrue(self.network.calls[-1]["keyMatches"])

    def test_missing_key_rejects_model_loading_before_network(self):
        with self.assertRaises(ValueError):
            self.settings.available_models()
        self.assertEqual(self.network.calls, [])

    def test_model_error_is_sanitized_and_preserves_provider_status(self):
        error = ConnectorError("Provider body key=" + KEY)
        error.status = 401
        self.network.error = error
        with self.assertRaises(ConnectorError) as raised:
            self.settings.available_models(KEY)
        self.assertEqual(raised.exception.status, 401)
        self.assertEqual(raised.exception.code, "invalid_key")
        self.assertNotIn(KEY, str(raised.exception))
        self.assertFalse(self.settings.path.exists())

    def test_successful_connection_verifies_before_saving_and_enabling_automatic_work(self):
        result = self.settings.connect(self.body())
        self.assertTrue(result["connectionTest"]["ok"])
        self.assertTrue(result["lastTest"]["ok"])
        self.assertTrue(result["automaticAnalysis"])
        self.assertTrue(self.settings.path.exists())
        self.assertEqual(self.service.ai.key, KEY)
        self.assertNotIn(KEY, json.dumps(result))
        payload = self.network.calls[-1]["body"]
        self.assertFalse(payload["store"])
        self.assertGreaterEqual(payload["max_output_tokens"], 2048)
        self.assertEqual(payload["text"]["format"]["name"], "connection_check")

    def test_failed_new_connection_never_persists_or_enables_automatic_work(self):
        self.network.error = TimeoutError("Timed out with key=" + KEY)
        result = self.settings.connect(self.body())
        self.assertFalse(result["connectionTest"]["ok"])
        self.assertEqual(result["connectionTest"]["errorCode"], "timeout")
        self.assertFalse(result["configured"])
        self.assertFalse(result["automaticAnalysis"])
        self.assertIsNone(result["lastTest"])
        self.assertFalse(self.settings.path.exists())
        self.assertEqual(self.service.ai.key, "")
        self.assertNotIn(KEY, json.dumps(result))

    def test_failed_replacement_keeps_the_previous_saved_connection(self):
        self.saved()
        before = self.settings.path.read_bytes()
        self.network.error = TimeoutError("No response")
        result = self.settings.connect({**self.body(), "apiKey": "a-different-fixture-key", "model": "another-model"})
        self.assertFalse(result["connectionTest"]["ok"])
        self.assertEqual(self.service.ai.key, KEY)
        self.assertEqual(self.service.ai.model, MODEL)
        self.assertFalse(self.service.auto_ai)
        self.assertEqual(self.settings.path.read_bytes(), before)

    def test_connection_errors_distinguish_permission_limit_missing_model_and_timeouts(self):
        self.saved()
        for status, code in ((401, "invalid_key"), (403, "access_denied"), (404, "model_unavailable"),
                             (429, "usage_limit"), (503, "provider_unavailable"), (408, "timeout"), (400, "request_unsupported")):
            with self.subTest(status=status):
                error = ConnectorError("Provider key=" + KEY)
                error.status = status
                self.network.error = error
                result = self.settings.test_connection()
                self.assertFalse(result["lastTest"]["ok"])
                self.assertEqual(result["lastTest"]["errorCode"], code)
                self.assertEqual(result["lastTest"]["status"], status)
                self.assertNotIn(KEY, json.dumps(result))

    def test_status_and_disconnect_remain_responsive_during_network_check(self):
        self.saved()
        self.network.block = True
        results = []
        testing = threading.Thread(target=lambda: results.append(self.settings.test_connection()))
        testing.start()
        self.assertTrue(self.network.started.wait(1))
        status_results = []
        reading = threading.Thread(target=lambda: status_results.append(self.settings.status()))
        reading.start()
        reading.join(.5)
        try:
            self.assertFalse(reading.is_alive(), "A remote OpenAI check blocked local status loading")
            self.assertTrue(status_results[0]["configured"])
            self.settings.configure({"disconnect": True})
        finally:
            self.network.release.set()
            testing.join(2)
            reading.join(2)
        self.assertFalse(testing.is_alive())
        self.assertEqual(results[0]["connectionTest"]["errorCode"], "settings_changed")
        self.assertFalse(self.settings.status()["configured"])
        self.assertIsNone(self.settings.status()["lastTest"])

    def test_verified_connection_does_not_overwrite_settings_changed_while_waiting(self):
        self.network.block = True
        results = []
        testing = threading.Thread(target=lambda: results.append(self.settings.connect(self.body())))
        testing.start()
        self.assertTrue(self.network.started.wait(1))
        self.settings.configure({"disconnect": True})
        self.network.release.set()
        testing.join(2)
        self.assertFalse(testing.is_alive())
        self.assertEqual(results[0]["connectionTest"]["errorCode"], "settings_changed")
        self.assertFalse(self.service.ai.ready)
        self.assertFalse(self.service.auto_ai)
        self.assertTrue(json.loads(self.settings.path.read_text())["disabled"])

    def test_provisional_connection_check_does_not_save_or_stamp_another_configuration(self):
        self.saved()
        result = self.settings.test_connection({**self.body(), "model": "proposed-model"})
        self.assertTrue(result["connectionTest"]["ok"])
        self.assertIsNone(result["lastTest"])
        self.assertEqual(self.service.ai.model, MODEL)
        self.assertFalse(self.service.auto_ai)


if __name__ == "__main__":
    unittest.main()
