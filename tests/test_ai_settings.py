"""Offline credential boundaries and topic-planning/discovery contracts."""
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.ai import AI
from server.ai_settings import AISettings
from server.connectors import ConnectorError
from server.storage import Database


KEY = "sk-fixture-private-key-never-returned"
MODEL = "configured-research-model"


def completed(value):
    return {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(value)}]}]}


class Network:
    def __init__(self, response=None, error=None):
        self.response = response or completed({"status": "connected"})
        self.error = error
        self.calls = []

    def json(self, url, headers, payload):
        self.calls.append((url, headers, payload))
        if self.error:
            raise self.error
        return self.response


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {"OPENAI_API_KEY": "", "OPENAI_MODEL": "", "CRAWLER_AUTO_AI": "false"})
        self.environment.start()
        self.temp = tempfile.TemporaryDirectory()
        self.network = Network()
        self.service = SimpleNamespace(db=Database(self.temp.name), network=self.network, ai=AI(self.network), auto_ai=False)
        self.settings = AISettings(self.service)

    def tearDown(self):
        self.temp.cleanup()
        self.environment.stop()

    def connect(self, **changes):
        return self.settings.configure({"apiKey": KEY, "model": MODEL, "automaticAnalysis": True, **changes})

    def test_save_restores_private_credentials_without_exposing_any_fragment(self):
        status = self.connect()
        self.assertTrue(status["configured"])
        self.assertTrue(status["automaticAnalysis"])
        self.assertEqual(self.service.ai.key, KEY)
        self.assertNotIn(KEY, json.dumps(status))
        self.assertNotIn("never-returned", json.dumps(status))
        self.assertNotIn(KEY, json.dumps(self.service.db.audit_entries()))
        self.assertFalse(self.service.db.count("openaiSettings"))
        if os.name == "nt":
            self.assertNotIn(KEY, self.settings.path.read_text())
            self.assertEqual(status["storage"], "Windows DPAPI")
        else:
            self.assertEqual(stat.S_IMODE(self.settings.path.stat().st_mode), 0o600)
        self.service.ai.key = ""
        AISettings(self.service)
        self.assertEqual(self.service.ai.key, KEY)
        self.assertTrue(self.service.auto_ai)

    def test_blank_key_keeps_existing_secret_and_model_change_resets_test(self):
        self.connect()
        self.settings.test_connection()
        status = self.settings.configure({"apiKey": "", "model": "new-accessible-model", "automaticAnalysis": False})
        self.assertEqual(self.service.ai.key, KEY)
        self.assertEqual(status["model"], "new-accessible-model")
        self.assertFalse(self.service.auto_ai)
        self.assertIsNone(status["lastTest"])

    def test_connection_check_calls_responses_and_rejects_uncompleted_success(self):
        self.connect()
        status = self.settings.test_connection()
        self.assertTrue(status["lastTest"]["ok"])
        url, headers, payload = self.network.calls[-1]
        self.assertEqual(url, "https://api.openai.com/v1/responses")
        self.assertEqual(headers["Authorization"], "Bearer " + KEY)
        self.assertFalse(payload["store"])
        self.assertEqual(payload["max_output_tokens"], 2048)
        self.assertEqual(payload["text"]["format"]["name"], "connection_check")
        self.network.response = {"status": "incomplete", "output": []}
        self.assertFalse(self.settings.test_connection()["lastTest"]["ok"])
        self.network.response = completed({"status": "connected", "secret": KEY})
        status = self.settings.test_connection()
        self.assertFalse(status["lastTest"]["ok"])
        self.assertNotIn(KEY, json.dumps(status))

    def test_remote_exception_is_sanitized(self):
        self.connect()
        self.network.error = RuntimeError("Provider rejected api_key=" + KEY)
        status = self.settings.test_connection()
        self.assertFalse(status["lastTest"]["ok"])
        self.assertNotIn(KEY, json.dumps(status))

    def test_disconnection_survives_environment_fallback_and_restart(self):
        self.connect()
        with patch.dict(os.environ, {"OPENAI_API_KEY": "another-env-secret", "OPENAI_MODEL": MODEL}):
            status = self.settings.configure({"disconnect": True})
            self.assertFalse(status["configured"])
            self.assertFalse(status["automaticAnalysis"])
            self.service.ai = AI(self.network)
            AISettings(self.service)
            self.assertFalse(self.service.ai.ready)
            self.assertEqual(self.service.ai.key, "")
            self.assertNotIn(KEY, self.settings.path.read_text())

    def test_environment_credentials_are_available_without_persisting_them(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": KEY, "OPENAI_MODEL": MODEL}):
            self.service.ai = AI(self.network)
            settings = AISettings(self.service)
            self.assertTrue(settings.status()["configured"])
            self.assertEqual(settings.status()["storage"], "Environment")
            settings.test_connection()
            self.assertFalse(settings.path.exists())

    def test_invalid_values_never_change_credentials_or_echo_secret(self):
        self.connect()
        for change in ({"apiKey": "bad\r\nKey"}, {"model": "bad\nmodel"}, {"automaticAnalysis": "true"}, {"model": ""}, {"apiKey": None}):
            with self.assertRaises(ValueError) as error:
                self.connect(**change)
            self.assertNotIn(KEY, str(error.exception))
            self.assertEqual(self.service.ai.key, KEY)
            self.assertEqual(self.service.ai.model, MODEL)

    def test_corrupt_settings_disable_paid_work_instead_of_falling_back(self):
        self.connect()
        self.settings.path.write_text("invalid " + KEY)
        with patch.dict(os.environ, {"OPENAI_API_KEY": KEY, "OPENAI_MODEL": MODEL}):
            self.service.ai = AI(self.network)
            settings = AISettings(self.service)
            self.assertFalse(settings.status()["configured"])
            self.assertFalse(self.service.auto_ai)
            self.assertNotIn(KEY, json.dumps(settings.status()))
            self.assertEqual(settings.status()["storage"], "Unavailable")

    def test_failed_storage_is_safe_and_preserves_current_connection(self):
        self.connect()
        old_adapter = self.service.ai
        with patch("server.ai_settings.os.replace", side_effect=OSError("bad secret " + KEY)):
            with self.assertRaises(ValueError) as error:
                self.settings.configure({"model": "another-model"})
        self.assertNotIn(KEY, str(error.exception))
        self.assertIs(self.service.ai, old_adapter)
        self.assertFalse(list(Path(self.temp.name).glob(".openai-settings-*.tmp")))


class TopicAITests(unittest.TestCase):
    def adapter(self, response):
        network = Network(response)
        adapter = AI(network)
        adapter.key, adapter.model = KEY, MODEL
        return adapter, network

    def plan(self):
        return {"title": "Renewable energy", "searchTerms": ["renewable energy disclosures", "grid investment"],
                "questions": ["Which filings document exposure?"], "assetTypes": ["equity"], "regions": ["Global"]}

    def test_topic_plan_is_structured_bounded_and_has_no_holdings(self):
        adapter, network = self.adapter(completed(self.plan()))
        result = adapter.plan_topic("renewable energy")
        self.assertEqual(result, self.plan())
        self.assertNotIn("holdings", result)
        payload = network.calls[0][2]
        self.assertEqual(payload["text"]["format"]["name"], "topic_research_plan")
        self.assertTrue(payload["text"]["format"]["strict"])
        self.assertFalse(payload["store"])

    def test_unbounded_or_extra_plan_fields_are_rejected_locally(self):
        for change in ({"holdings": ["invented"]}, {"searchTerms": ["x"] * 9}, {"questions": ["x" * 241]}, {"title": ""}, {"regions": "Global"}):
            adapter, _ = self.adapter(completed({**self.plan(), **change}))
            with self.assertRaises(ConnectorError):
                adapter.plan_topic("energy")

    def test_source_discovery_uses_only_actual_search_annotations_and_sources(self):
        response = {"status": "completed", "output": [
            {"type": "web_search_call", "status": "completed", "action": {"type": "search", "sources": [
                {"type": "url", "url": "https://publisher.example/disclosure"},
                {"type": "url", "url": "http://unsafe.example/"},
                {"type": "url", "url": "https://127.0.0.1/private"},
                {"type": "url", "url": "https://localhost/private"},
                {"type": "url", "url": "https://user:secret@publisher.example/private"}]}},
            {"type": "message", "content": [{"type": "output_text", "text": "Invented model URL: https://fake.example/fiction",
                "annotations": [{"type": "url_citation", "url": "https://publisher.example/disclosure", "title": "Original filing"},
                                {"type": "url_citation", "url": "https://regulator.example/release", "title": "Official release"}]}]}]}
        adapter, network = self.adapter(response)
        result = adapter.discover_topic("energy", ["grid investment"])
        self.assertEqual(len(result), 2)
        self.assertTrue(all(item["discoveryOnly"] for item in result))
        self.assertEqual(result[0]["title"], "Original filing")
        self.assertNotIn("fake.example", json.dumps(result))
        self.assertTrue(network.calls[0][2]["tools"])
        self.assertEqual(network.calls[0][2]["max_tool_calls"], 2)

    def test_model_links_without_completed_web_search_are_rejected(self):
        adapter, _ = self.adapter(completed({"url": "https://imaginary.example"}))
        with self.assertRaisesRegex(ConnectorError, "web search"):
            adapter.discover_topic("energy")


if __name__ == "__main__":
    unittest.main()
