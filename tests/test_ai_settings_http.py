"""HTTP owner, CSRF, origin, and credential boundaries for search setup."""
import http.client
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.http import AppServer
from server.service import ResearchService


KEY = "sk-http-fixture-credential-never-a-real-key"
OWNER = "fixture-owner-access-token"
MODEL = "fixture-research-model"
MUTATIONS = ("/api/ai/settings", "/api/ai/test", "/api/topics", "/api/topics/refresh", "/api/topics/toggle")


class ConnectionNetwork:
    def __init__(self):
        self.calls = []
        self.fail = False

    def json(self, url, headers=None, body=None):
        # No feed, model research, or live network access is allowed by this
        # fixture. Only the explicit connection-check action may use an API.
        if url != "https://api.openai.com/v1/responses" or body.get("text", {}).get("format", {}).get("name") != "connection_check":
            raise AssertionError("Unexpected network call in credential boundary test")
        self.calls.append({"url": url, "body": body, "authorizationMatched": headers.get("Authorization") == "Bearer " + KEY})
        if self.fail:
            raise RuntimeError("Provider body contained key=" + KEY)
        return {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": '{"status":"connected"}'}]}]}


class AISettingsHTTPTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {"OPENAI_API_KEY": "", "OPENAI_MODEL": "", "CRAWLER_AUTO_AI": "false"})
        self.environment.start()
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "application"
        self.root.mkdir()
        (self.root / "index.html").write_text("<!doctype html><title>Fixture crawler</title>", encoding="utf-8")
        self.network = ConnectionNetwork()
        self.service = ResearchService(self.root / "data", self.network, seed=False, dsn="")
        self.server = AppServer(("127.0.0.1", 0), self.service, self.root, auth_token=OWNER)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_port

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.service.close()
        self.temporary.cleanup()
        self.environment.stop()

    def request(self, method, route, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request(method, route, body=json.dumps(body) if body is not None else None,
                           headers={"Content-Type": "application/json", **(headers or {})})
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def login(self):
        status, headers, data = self.request("POST", "/api/login", {"token": OWNER})
        self.assertEqual(status, 200)
        return {"Cookie": headers["Set-Cookie"].split(";")[0], "X-Crawler-CSRF": json.loads(data)["csrf"],
                "Origin": "http://127.0.0.1:" + str(self.port)}

    def configure(self, headers=None):
        return self.request("POST", "/api/ai/settings", {"apiKey": KEY, "model": MODEL, "automaticAnalysis": False}, headers or self.login())

    def assert_private(self, response):
        self.assertNotIn(KEY.encode(), response[2])
        self.assertNotIn(b"credential-never-a-real-key", response[2])

    def test_all_settings_and_topic_routes_require_owner_authorization(self):
        for route in ("/api/ai/settings", "/api/topics", "/api/topics?id=unavailable"):
            with self.subTest(route=route, method="GET"):
                self.assertEqual(self.request("GET", route)[0], 401)
                self.assertEqual(self.request("GET", route, headers={"Authorization": "Bearer incorrect"})[0], 401)
        for route in MUTATIONS:
            with self.subTest(route=route, method="POST"):
                result = self.request("POST", route, {"apiKey": KEY, "query": "solar energy"})
                self.assertEqual(result[0], 401)
                self.assert_private(result)
        self.assertFalse(self.service.ai_settings.path.exists())
        self.assertEqual(self.service.db.count("topicPortfolio"), 0)
        self.assertEqual(self.service.db.jobs(), [])
        self.assertEqual(self.network.calls, [])

    def test_every_mutation_requires_csrf_for_an_owner_cookie(self):
        owner = self.login()
        for route in MUTATIONS:
            for headers in ({"Cookie": owner["Cookie"]}, {**owner, "X-Crawler-CSRF": "incorrect"}):
                with self.subTest(route=route, headers=list(headers)):
                    result = self.request("POST", route, {"apiKey": KEY, "query": "solar energy"}, headers)
                    self.assertEqual(result[0], 403)
                    self.assert_private(result)
        self.assertFalse(self.service.ai_settings.path.exists())
        self.assertEqual(self.service.db.jobs(), [])
        self.assertEqual(self.network.calls, [])

    def test_owner_credentials_do_not_bypass_origin_or_host_checks(self):
        bearer = {"Authorization": "Bearer " + OWNER}
        for route in MUTATIONS:
            for violation in ({"Origin": "https://untrusted.example"}, {"Sec-Fetch-Site": "cross-site"}, {"Host": "untrusted.example"}):
                with self.subTest(route=route, violation=violation):
                    result = self.request("POST", route, {"apiKey": KEY, "query": "solar energy"}, {**bearer, **violation})
                    self.assertEqual(result[0], 403)
                    self.assert_private(result)
        for route in ("/api/ai/settings", "/api/topics"):
            self.assertEqual(self.request("GET", route, headers={**bearer, "Host": "untrusted.example"})[0], 403)
            self.assertEqual(self.request("GET", route, headers={**bearer, "Origin": "https://untrusted.example"})[0], 403)
        self.assertFalse(self.service.ai_settings.path.exists())
        self.assertEqual(self.network.calls, [])

    def test_local_owner_can_save_and_run_the_real_connection_check_contract(self):
        owner = self.login()
        result = self.configure(owner)
        self.assertEqual(result[0], 200)
        self.assert_private(result)
        saved = json.loads(result[2])
        self.assertTrue(saved["configured"])
        self.assertTrue(saved["keyConfigured"])
        self.assertFalse(saved["automaticAnalysis"])
        self.assertEqual(saved["model"], MODEL)
        self.assertIsNone(saved["lastTest"])
        self.assertEqual(self.network.calls, [])
        self.assertTrue(self.service.ai_settings.path.exists())
        if os.name == "nt":
            self.assertEqual(saved["storage"], "Windows DPAPI")
            self.assertNotIn(KEY, self.service.ai_settings.path.read_text())
        result = self.request("POST", "/api/ai/test", {}, owner)
        self.assertEqual(result[0], 200)
        self.assertTrue(json.loads(result[2])["lastTest"]["ok"])
        self.assert_private(result)
        self.assertEqual(len(self.network.calls), 1)
        call = self.network.calls[0]
        self.assertTrue(call["authorizationMatched"])
        self.assertFalse(call["body"]["store"])
        self.assertEqual(call["body"]["model"], MODEL)
        self.assertLessEqual(call["body"]["max_output_tokens"], 2048)
        result = self.request("GET", "/api/ai/settings", headers=owner)
        self.assertEqual(result[0], 200)
        self.assertEqual(result[1]["Cache-Control"], "no-store")
        self.assertTrue(json.loads(result[2])["lastTest"]["ok"])
        self.assert_private(result)

    def test_saved_file_export_and_normal_status_routes_never_return_key(self):
        owner = self.login()
        self.assertEqual(self.configure(owner)[0], 200)
        for route in ("/api/ai/settings", "/api/health", "/api/export", "/api/operations", "/api/workspace", "/api/topics"):
            with self.subTest(route=route):
                result = self.request("GET", route, headers=owner)
                self.assertEqual(result[0], 200)
                self.assert_private(result)
        # Exercise a real existing saved file, plus aliases and path traversal.
        # Authorization does not expand the static file allowlist.
        for route in ("/CRAWLER/data/openai-settings.json", "/CRAWLER/openai-settings.json", "/CRAWLER/server/ai_settings.py",
                      "/CRAWLER/.env", "/CRAWLER/data/../data/openai-settings.json", "/CRAWLER/data%2fopenai-settings.json",
                      "/CRAWLER/%2e%2e/application/data/openai-settings.json", "/openai-settings.json"):
            with self.subTest(route=route):
                result = self.request("GET", route, headers=owner)
                self.assertEqual(result[0], 404)
                self.assert_private(result)
        self.assertEqual(self.request("GET", "/CRAWLER/index.html")[0], 200)
        result = self.request("GET", "/api/raw?id=openai-settings", headers=owner)
        self.assertEqual(result[0], 400)
        self.assert_private(result)

    def test_connection_failure_and_invalid_settings_return_sanitized_errors(self):
        owner = self.login()
        self.assertEqual(self.configure(owner)[0], 200)
        self.network.fail = True
        result = self.request("POST", "/api/ai/test", {}, owner)
        self.assertEqual(result[0], 200)
        self.assertFalse(json.loads(result[2])["lastTest"]["ok"])
        self.assert_private(result)
        result = self.request("POST", "/api/ai/settings", {"apiKey": KEY, "model": "bad\nmodel", "automaticAnalysis": False}, owner)
        self.assertEqual(result[0], 400)
        self.assert_private(result)
        self.assertEqual(self.service.ai.model, MODEL)
        self.assertEqual(self.service.ai.key, KEY)
        self.assert_private(self.request("GET", "/api/export", headers=owner))

    def test_owner_can_create_read_refresh_and_pause_topic_portfolio(self):
        owner = self.login()
        self.assertEqual(self.configure(owner)[0], 200)
        result = self.request("POST", "/api/topics", {"query": "solar energy", "refreshMinutes": 60}, owner)
        self.assertEqual(result[0], 200)
        self.assert_private(result)
        topic = json.loads(result[2])
        self.assertEqual(topic["query"], "solar energy")
        self.assertEqual(topic["state"], "Queued")
        result = self.request("GET", "/api/topics?id=" + topic["id"], headers=owner)
        self.assertEqual(result[0], 200)
        self.assertEqual(json.loads(result[2])["id"], topic["id"])
        result = self.request("GET", "/api/topics", headers=owner)
        self.assertEqual(len(json.loads(result[2])["topics"]), 1)
        self.assertEqual(self.request("POST", "/api/topics/refresh", {"id": topic["id"]}, owner)[0], 200)
        result = self.request("POST", "/api/topics/toggle", {"id": topic["id"], "enabled": False}, owner)
        self.assertEqual(result[0], 200)
        self.assertFalse(json.loads(result[2])["enabled"])
        self.assertEqual(self.network.calls, [])


if __name__ == "__main__":
    unittest.main()
