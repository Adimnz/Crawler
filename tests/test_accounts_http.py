"""Account cookies, provider-verified identity and HTTP ownership boundaries."""
from pathlib import Path
import http.cookiejar
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from network_fixture import Network
from test_accounts import AuthProvider
from server.http import AppServer
from server.service import ResearchService


class AccountHTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.network = Network()
        self.s = ResearchService(self.tmp.name, network=self.network, seed=False, dsn="")
        self.s.accounts.url, self.s.accounts.key = "https://fixtureproject.supabase.co", "fixture-public-key"
        self.server = AppServer(("127.0.0.1", 0), self.s, Path(__file__).resolve().parents[1], auth_token="fixture-owner")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:" + str(self.server.server_port)
    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.s.close()
        self.tmp.cleanup()
    def client(self):
        cookies = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(cookies))
        return {"opener": opener, "cookies": cookies}
    def request(self, client, path, body=None, csrf=True):
        headers = {"Content-Type": "application/json"}
        if csrf and client.get("csrf"): headers["X-Crawler-CSRF"] = client["csrf"]
        request = urllib.request.Request(self.base + "/api/" + path, data=json.dumps(body).encode() if body is not None else None, headers=headers)
        try: response = client["opener"].open(request, timeout=5)
        except urllib.error.HTTPError as error: response = error
        with response:
            value = json.loads(response.read())
            if value.get("csrf"): client["csrf"] = value["csrf"]
            return response.status, value, response.headers
    def login(self, name):
        client = self.client()
        self.request(client, "session")
        status, value, _ = self.request(client, "accounts/login", {"email": name + "@example.test", "password": "fixture-password-123", "remember": True})
        self.assertEqual(status, 200)
        return client, value

    def test_rotated_csrf_httponly_cookie_and_no_provider_tokens_in_api(self):
        client = self.client()
        self.request(client, "session")
        old = client["csrf"]
        status, result, headers = self.request(client, "accounts/login", {"email": "alice@example.test", "password": "fixture-password-123", "remember": True})
        self.assertEqual(status, 200)
        self.assertNotEqual(client["csrf"], old)
        cookie = next(c for c in headers.get_all("Set-Cookie") if c.startswith("crawler_account="))
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)
        self.assertIn("Max-Age=2592000", cookie)
        self.assertNotIn("refresh-token", json.dumps(result))
        client["csrf"] = old
        self.assertEqual(self.request(client, "topics", {"query": "Drones"})[0], 403)

    def test_private_topics_boards_and_exports_are_account_scoped(self):
        alice, _ = self.login("alice")
        bob, _ = self.login("bob")
        status, topic, _ = self.request(alice, "topics", {"query": "Drones"})
        self.assertEqual(status, 200)
        status, board, _ = self.request(alice, "boards", {"topicId": topic["id"]})
        self.assertEqual(status, 200)
        board_id = board["board"]["id"]
        for path in ("boards?id=" + board_id, "topics?id=" + topic["id"], "network-node?boardId=" + board_id + "&id=" + board["graph"]["rootId"]):
            self.assertEqual(self.request(bob, path)[0], 400)
        self.assertEqual(self.request(bob, "boards", {"topicId": topic["id"]})[0], 400)
        self.assertEqual(self.request(bob, "boards/save", {"id": board_id, "baseVersion": 1, "title": "Other account"})[0], 400)
        self.assertEqual(self.request(bob, "my-research/export")[1]["boards"], [])
        self.request(alice, "topics/toggle", {"id": topic["id"], "enabled": False})
        self.assertFalse(self.request(alice, "topics?id=" + topic["id"])[1]["enabled"])
        self.assertEqual(self.request(self.client(), "boards?id=" + board_id)[0], 401)

    def test_members_cannot_change_collectors_ai_settings_or_evidence_reviews(self):
        client, _ = self.login("alice")
        for path in ("sources", "ai/settings", "network/review", "documents/import", "relationships"):
            self.assertEqual(self.request(client, path, {})[0], 401, path)
        for path in ("export", "workspace", "jobs", "ai/models"):
            self.assertEqual(self.request(client, path)[0], 401, path)
        self.assertEqual(self.request(client, "accounts/setup", {})[0], 403)

    def test_mfa_blocks_private_research_until_provider_verifies_second_factor(self):
        provider = AuthProvider()
        provider.user["factors"] = [{"id": "fixture-factor", "factor_type": "totp", "status": "verified"}]
        self.network.providers["alice"] = provider
        client, state = self.login("alice")
        self.assertTrue(state["needsMfa"])
        self.assertFalse(self.request(client, "session")[1]["authorized"])
        self.assertEqual(self.request(client, "my-research")[0], 401)
        challenge = self.request(client, "accounts/mfa-challenge", {"factorId": "fixture-factor"})[1]
        self.assertEqual(self.request(client, "accounts/mfa-verify", {"factorId": "fixture-factor", "challengeId": challenge["challengeId"], "code": "123456"})[0], 200)
        self.assertEqual(self.request(client, "my-research")[0], 200)

    def test_logout_revokes_local_session_and_protected_files_are_not_static_assets(self):
        client, _ = self.login("alice")
        self.assertEqual(self.request(client, "accounts/logout", {})[0], 200)
        self.assertEqual(self.request(client, "my-research")[0], 401)
        for filename in ("account-settings.json", "account-sessions.json"):
            try: client["opener"].open(self.base + "/CRAWLER/data/" + filename)
            except urllib.error.HTTPError as error:
                self.assertEqual(error.code, 404)
                error.close()
            else: self.fail("Protected account storage was served")

    def test_email_callback_navigation_is_allowed_but_cross_site_api_access_is_rejected(self):
        client = self.client()
        headers = {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"}
        with client["opener"].open(urllib.request.Request(self.base + "/CRAWLER/account.html?view=callback", headers=headers)) as response:
            self.assertEqual(response.status, 200)
        try: client["opener"].open(urllib.request.Request(self.base + "/api/accounts", headers=headers))
        except urllib.error.HTTPError as error:
            self.assertEqual(error.code, 403)
            error.close()
        else: self.fail("Cross-site API access was allowed")


if __name__ == "__main__": unittest.main()
