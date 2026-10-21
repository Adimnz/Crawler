"""Autonomous research tests use invented instruments and offline source fixtures."""
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
from server.http import AppServer
from server.investment import SECTION_NAMES
from server.service import ResearchService
from server.storage import now_ms


class OfflineNetwork:
    def __init__(self):
        self.urls = []

    def allowed(self, url):
        return True

    def fetch(self, url, **kwargs):
        self.urls.append(url)
        if "company_tickers_exchange.json" in url:
            payload = {"fields": ["cik", "name", "ticker", "exchange"], "data": [[123, "Example Acme Corporation", "EXAC", "Nasdaq"]]}
        elif "/coins/list" in url:
            payload = []
        else:
            raise AssertionError("No external fixture authorized for " + url)
        return json.dumps(payload).encode(), {"content-type": "application/json"}, url


class InvestmentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.network = OfflineNetwork()
        self.s = ResearchService(self.temporary.name, self.network, seed=False, dsn="")
        self.s.auto_ai = False
        self.at = now_ms() - 2000
        self.source = self.s.add_source({"id": "official-filings", "name": "Fixture filings", "url": "https://data.sec.gov/submissions/CIK0000000123.json",
                                        "kind": "sec", "enabled": True, "tier": "primary", "permissions": "Offline fixtures only", "family": "SEC"})
        self.market = self.s.add_source({"id": "authorized-market", "name": "Fixture market", "url": "https://market.example/prices",
                                        "kind": "json", "enabled": True, "tier": "primary", "permissions": "Offline fixtures only"})
        self.asset_id = "equity:NASDAQ:EXAC"

    def tearDown(self):
        self.s.close()
        self.temporary.cleanup()

    def asset(self, **changes):
        item = {"id": self.asset_id, "name": "Example Acme Corporation", "ticker": "EXAC", "exchange": "NASDAQ", "cik": "0000000123",
                "assetClass": "equity", "identityVerified": True, "identitySource": "https://data.sec.gov/submissions/CIK0000000123.json",
                "sector": "Fixture industry", "country": "Fixture jurisdiction", **changes}
        self.s.investments.accept_assets([item], self.source)
        stored = self.s.db.get("asset", item["id"])
        if stored:
            stored["firstSeen"] = self.at - 10 * a.DAY
            self.s.db.put("asset", stored["id"], stored)
        return stored

    def document(self, **changes):
        return self.s.ingest(self.source, {"title": "Example Acme Corporation files a fixture disclosure", "text": "Example Acme Corporation filed a public fixture disclosure. The record describes a reported company development.",
                             "url": "https://www.sec.gov/Archives/edgar/data/123/fixture.htm", "publishedAt": self.at - a.DAY,
                             "companyId": self.asset_id, "filingType": "8-K", "entities": [{"id": self.asset_id, "name": "Example Acme Corporation", "type": "equity"}], **changes}, at=self.at)

    def price(self, age=0, value=12, **changes):
        observed = self.at - age
        return self.s.observation(self.market, {"assetId": self.asset_id, "metric": "price_usd", "value": value, "observedAt": observed,
                                 "availableAt": observed, "unit": "USD", "currency": "USD", "adjustment": "split-adjusted", "frequency": "daily", **changes}, at=self.at)

    def cycle(self, at=None):
        with patch("server.investment.now_ms", return_value=at or self.at):
            return self.s.investments.cycle("Fixture evidence changed")

    def qualified(self):
        self.asset()
        doc = self.document()
        self.price(age=10 * a.DAY)
        self.price()
        self.cycle()
        return doc, self.s.investments.profile(self.asset_id)["profile"]

    def test_autonomous_cycle_creates_persistent_profile_and_six_watch_portfolios(self):
        _, profile = self.qualified()
        self.assertTrue(profile["qualified"])
        self.assertEqual(profile["status"], "Qualified for monitoring")
        self.assertEqual(set(profile["sections"]), set(SECTION_NAMES))
        self.assertEqual(profile["sections"]["Valuation"]["status"], "Data unavailable")
        overview = self.s.investments.overview()
        self.assertEqual(len(overview["portfolios"]), 6)
        self.assertTrue(any(e["assetId"] == self.asset_id for p in overview["portfolios"] for e in p["entries"]))
        self.assertEqual(self.s.db.count("assetProfile"), 1)
        self.assertIn("Monitor", overview["operation"]["stages"])

    def test_profile_survives_restart_without_a_browser(self):
        _, profile = self.qualified()
        self.s.close()
        self.s = ResearchService(self.temporary.name, self.network, seed=False, dsn="")
        restored = self.s.investments.profile(self.asset_id)["profile"]
        self.assertEqual(restored["sourceFingerprint"], profile["sourceFingerprint"])
        self.assertEqual(restored["version"], 1)

    def test_workers_build_profiles_from_ingestion_without_a_browser_or_manual_cycle(self):
        self.asset()
        for source in (self.source, self.market):
            source["nextPollAt"] = now_ms() + a.DAY
            self.s.db.put("source", source["id"], source)
        self.document()
        self.price(age=10 * a.DAY)
        self.price()
        self.s.start(workers=1)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and not self.s.db.get("assetProfile", self.asset_id):
            time.sleep(.05)
        profile = self.s.db.get("assetProfile", self.asset_id)
        self.assertIsNotNone(profile)
        self.assertTrue(profile["qualified"], profile["qualificationGaps"])

    def test_bare_ticker_mentions_never_create_verified_identity_or_profile(self):
        self.document(title="A ticker mention", text="An unqualified $EXAC symbol appeared in a news discussion without a verified issuer identity.")
        self.cycle()
        self.assertEqual(self.s.investments.overview()["profiles"], [])
        self.assertTrue(any(e["type"] == "unresolved" for e in self.s.db.latest("entity")))

    def test_untrusted_identity_is_not_admitted_as_a_provider_verified_asset(self):
        self.assertIsNone(self.asset(identitySource="https://invented.example/company"))
        self.assertIsNone(self.asset(identityVerified=False))
        self.assertEqual(self.s.db.count("asset"), 0)

    def test_market_evidence_trigger_and_real_observation_period_are_independent_gates(self):
        self.asset()
        self.document()
        self.cycle()
        first = self.s.investments.profile(self.asset_id)["profile"]
        self.assertFalse(first["qualified"])
        self.assertTrue(any("market price" in gap for gap in first["qualificationGaps"]))
        self.price()
        self.cycle()
        second = self.s.investments.profile(self.asset_id)["profile"]
        self.assertTrue(any("Observation period incomplete" in gap for gap in second["qualificationGaps"]))
        self.price(age=10 * a.DAY)
        self.cycle()
        self.assertTrue(self.s.investments.profile(self.asset_id)["profile"]["qualified"])

    def test_market_data_alone_does_not_qualify_an_asset_for_monitoring(self):
        self.asset()
        self.price(age=10 * a.DAY)
        self.price()
        self.cycle()
        profile = self.s.investments.profile(self.asset_id)["profile"]
        self.assertEqual(profile["status"], "Under investigation")
        self.assertIn("Independent research trigger: Data unavailable", profile["qualificationGaps"])

    def test_source_disable_stale_prices_review_and_removal_are_deterministic(self):
        self.qualified()
        self.cycle(self.at + 2 * a.DAY)
        self.assertEqual(self.s.investments.profile(self.asset_id)["profile"]["status"], "Review required")
        self.cycle(self.at + 10 * a.DAY)
        self.assertEqual(self.s.investments.profile(self.asset_id)["profile"]["status"], "Removed")
        self.assertTrue(any(e["status"] == "Removed" for p in self.s.investments.overview()["portfolios"] for e in p["entries"]))

    def test_disabled_or_nonprimary_market_source_cannot_satisfy_current_price_gate(self):
        self.qualified()
        self.s.toggle_source(self.market["id"], False)
        self.cycle()
        self.assertFalse(self.s.investments.profile(self.asset_id)["profile"]["marketFresh"])

    def test_source_correction_retains_profile_revisions_and_reopens_research(self):
        doc, first = self.qualified()
        self.s.ingest(self.source, {**doc, "text": "Example Acme Corporation corrected the earlier fixture company disclosure.", "raw": {"correction": True}}, at=self.at + 100)
        self.cycle(self.at + 100)
        current = self.s.investments.profile(self.asset_id)["profile"]
        historical = self.s.investments.profile(self.asset_id, self.at)["profile"]
        self.assertEqual(historical["version"], first["version"])
        self.assertEqual(historical["sourceHistory"][0]["version"], 1)
        self.assertEqual(current["sourceHistory"][0]["version"], 2)
        self.assertEqual(current["status"], "Review required")
        self.assertTrue(current["whatChanged"])

    def test_financial_revisions_preserve_values_available_at_earlier_dates(self):
        t0 = self.at - 10 * a.DAY
        original = self.s.observation(self.market, {"assetId": "economic:FRED:FIXTURE", "metric": "level", "observedAt": t0 - a.DAY, "availableAt": t0, "value": 100, "unit": "index"}, at=t0)
        self.s.observation(self.market, {"assetId": "economic:FRED:FIXTURE", "metric": "level", "observedAt": t0 - a.DAY, "availableAt": t0 + a.DAY, "value": 102, "unit": "index"}, at=t0 + a.DAY)
        earlier = self.s.investments._observations("economic:FRED:FIXTURE", t0 + 1000)
        current = self.s.investments._observations("economic:FRED:FIXTURE", t0 + 2 * a.DAY)
        self.assertEqual([r["value"] for r in earlier], [100])
        self.assertEqual([r["value"] for r in current], [102])
        self.assertEqual(earlier[0]["originalObservationId"], original["id"])

    def test_reports_publish_attributed_records_and_do_not_invent_documented_exposure(self):
        doc, _ = self.qualified()
        report = self.s.investments.overview()["reports"][0]
        self.assertEqual(report["whatHappened"][0]["documentId"], doc["id"])
        self.assertEqual(report["whatHappened"][0]["status"], "Attributed source extract")
        self.assertEqual(report["documentedExposure"], [])
        self.assertIn(self.asset_id, report["mentionedAssets"])
        self.assertNotIn("expectedReturn", json.dumps(report))

    def test_co_mentions_do_not_become_policy_or_macroeconomic_exposure(self):
        self.qualified()
        profile = self.s.investments.profile(self.asset_id)["profile"]
        self.assertNotIn("macro", profile["themes"])
        self.assertNotIn("policy", profile["themes"])

    def test_confirmed_exposure_loses_documented_status_after_source_revision(self):
        doc, _ = self.qualified()
        relation = self.s.add_relationship({"from": self.asset_id, "to": "economic:fixture-rate", "type": "rate-exposure", "evidence": [doc["id"]],
                                           "confirmed": True, "reviewed": True, "validFrom": self.at - a.DAY})
        self.cycle()
        self.assertIn("macro", self.s.investments.profile(self.asset_id)["profile"]["themes"])
        self.s.ingest(self.source, {**doc, "text": "Example Acme Corporation corrected and withdrew its earlier reported rate exposure.", "raw": {"exposureWithdrawn": True}}, at=self.at + 100)
        self.cycle(self.at + 100)
        current = self.s.investments.profile(self.asset_id)["profile"]
        self.assertNotIn(relation["id"], [r["id"] for r in current["sections"]["Economic exposure"]["items"]])
        self.assertNotIn("macro", current["themes"])

    def test_policy_proposal_remains_a_proposal_and_historical_metadata_is_preserved(self):
        self.asset()
        doc = self.document(text="Example Acme Corporation was mentioned in an agency proposal. The proposal is open for public consultation.")
        record = self.s.investments.policy_record({"documentId": doc["id"], "status": "Proposal", "jurisdiction": "Fixture jurisdiction", "reviewed": True,
                                                 "quote": "The proposal is open for public consultation.", "eventAt": self.at - a.DAY})
        self.assertEqual(record["policyRecord"]["status"], "Proposal")
        self.assertEqual(record["version"], 2)
        self.assertNotIn("policyRecord", self.s.db.versions(doc["id"])[0])

    def test_policy_records_require_review_quote_date_and_effective_date(self):
        doc = self.document()
        valid = {"documentId": doc["id"], "status": "Proposal", "jurisdiction": "Fixture jurisdiction", "reviewed": True, "quote": doc["text"], "eventAt": self.at - a.DAY}
        for changes in ({"reviewed": False}, {"quote": "An invented policy quote."}, {"eventAt": now_ms() + a.DAY}, {"status": "Enacted law"}):
            with self.assertRaises(ValueError):
                self.s.investments.policy_record({**valid, **changes})

    def test_model_assessment_cannot_upgrade_profile_or_watch_portfolio(self):
        self.asset()
        self.document()
        self.cycle()
        before = self.s.investments.profile(self.asset_id)["profile"]
        self.s.auto_ai, self.s.ai.key, self.s.ai.model = True, "fixture", "fixture-model"
        self.s.ai.coordinate = lambda *args: {"facts": [], "qualified": True, "status": "Qualified for monitoring", "inventedPrice": 123456}
        self.s.investments.coordinate(self.asset_id, before["version"])
        after = self.s.investments.profile(self.asset_id)["profile"]
        self.assertEqual(after, before)
        self.assertEqual(after["status"], "Under investigation")
        self.assertFalse(after["qualified"])

    def test_stale_coordinator_assessment_is_withheld_when_profile_changes_during_call(self):
        doc, before = self.qualified()
        self.s.auto_ai, self.s.ai.key, self.s.ai.model = True, "fixture", "fixture-model"
        def delayed_assessment(*args):
            self.s.ingest(self.source, {**doc, "text": "Example Acme Corporation issued a material correction of the fixture disclosure.", "raw": {"correction": 2}}, at=self.at + 100)
            self.cycle(self.at + 100)
            return {"facts": [{"text": "Stale research from before the correction."}]}
        self.s.ai.coordinate = delayed_assessment
        self.s.investments.coordinate(self.asset_id, before["version"])
        self.assertIsNone(self.s.db.get("coordinatorRun", self.asset_id + ":" + str(before["version"])))

    def test_coordinator_rechecks_financial_observations_even_before_the_next_cycle(self):
        _, before = self.qualified()
        self.s.auto_ai, self.s.ai.key, self.s.ai.model = True, "fixture", "fixture-model"
        def delayed_assessment(task, execute_tool):
            execute_tool("get_market_history", {"instrument_id": self.asset_id, "date_range": ""})
            self.s.observation(self.market, {"assetId": self.asset_id, "metric": "price_usd", "value": 9, "observedAt": self.at,
                                           "availableAt": self.at, "unit": "USD", "currency": "USD", "adjustment": "split-adjusted", "frequency": "daily"}, at=self.at + 100)
            return {"facts": []}
        self.s.ai.coordinate = delayed_assessment
        self.s.investments.coordinate(self.asset_id, before["version"])
        self.assertIsNone(self.s.db.get("coordinatorRun", self.asset_id + ":" + str(before["version"])))

    def test_coordinator_rechecks_tool_evidence_outside_the_profile_source_set(self):
        _, before = self.qualified()
        external = self.s.ingest(self.market, {"title": "A separate economic agency announcement", "text": "A separate economic agency published an economic fixture release with no issuer references.",
                                             "url": "https://agency.example/external-release", "publishedAt": self.at - a.DAY}, at=self.at)
        self.s.auto_ai, self.s.ai.key, self.s.ai.model = True, "fixture", "fixture-model"
        def delayed_assessment(task, execute_tool):
            execute_tool("retrieve_source_document", {"source_id": external["id"]})
            self.s.ingest(self.market, {**external, "text": "The separate economic agency corrected its published fixture release.", "raw": {"corrected": True}}, at=self.at + 100)
            return {"facts": []}
        self.s.ai.coordinate = delayed_assessment
        self.s.investments.coordinate(self.asset_id, before["version"])
        self.assertIsNone(self.s.db.get("coordinatorRun", self.asset_id + ":" + str(before["version"])))

    def test_invalid_availability_timestamp_cannot_poison_research_cycles(self):
        with self.assertRaises(ValueError):
            self.s.observation(self.market, {"assetId": self.asset_id, "metric": "price_usd", "value": 12,
                                           "observedAt": self.at, "availableAt": "not-a-timestamp", "unit": "USD"}, at=self.at)
        self.assertEqual(self.s.investments._observations(), [])

    def test_automatic_ai_remains_off_without_explicit_server_opt_in(self):
        self.qualified()
        self.s.ai.key, self.s.ai.model = "fixture", "fixture-model"
        self.s.auto_ai = False
        self.cycle()
        self.assertFalse(any(job["kind"] == "coordinate-research" for job in self.s.db.jobs(limit=1000)))

    def test_discovery_queries_only_the_enabled_provider_family(self):
        self.document(title="Unrelated issuer record", text="A report about an unrelated company without any catalogue match.")
        with patch.dict(os.environ, {"SEC_USER_AGENT": "FixtureCrawler fixture@example.com", "COINGECKO_API_KEY": "fixture-key"}):
            self.s.investments.discover()
        self.assertTrue(any("sec.gov" in url for url in self.network.urls))
        self.assertFalse(any("coingecko.com" in url for url in self.network.urls))

    def test_discovery_with_no_enabled_provider_performs_no_network_access(self):
        self.s.toggle_source(self.source["id"], False)
        self.document()
        self.s.investments.discover()
        self.assertEqual(self.network.urls, [])
        self.assertEqual(self.s.investments.overview()["discovery"]["discovered"], 0)

    def test_original_tool_evidence_and_derived_research_remain_separate(self):
        doc, _ = self.qualified()
        found = self.s.investments.tool("retrieve_source_document", {"source_id": doc["id"]})
        self.assertEqual(found["evidence"][0]["text"], doc["text"])
        derived = self.s.investments.tool("get_existing_research", {"instrument_id": self.asset_id})
        self.assertEqual(derived["evidence"], [])
        self.assertIn("derived", derived["result"]["evidenceWarning"])

    def test_financial_statement_period_limit_keeps_all_metrics_in_each_selected_period(self):
        for year in (2024, 2025):
            for metric, value in (("revenue", 100), ("net_income", 5)):
                self.s.observation(self.market, {"assetId": self.asset_id, "metric": metric, "value": value, "observedAt": self.at - (2026 - year) * a.DAY,
                                               "availableAt": self.at, "unit": "USD", "currency": "USD", "accountingBasis": "US GAAP", "periodType": "annual",
                                               "periodStart": str(year) + "-01-01", "periodEnd": str(year) + "-12-31"}, at=self.at)
        latest = self.s.investments.tool("get_financial_statements", {"company_id": self.asset_id, "periods": 1})["evidence"]
        self.assertEqual({r["metric"] for r in latest}, {"revenue", "net_income"})
        self.assertEqual({r["periodEnd"] for r in latest}, {"2025-12-31"})


class InvestmentAPITests(unittest.TestCase):
    def test_new_research_mutations_inherit_owner_and_csrf_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            service = ResearchService(directory, OfflineNetwork(), seed=False, dsn="")
            server = AppServer(("127.0.0.1", 0), service, Path(__file__).resolve().parents[1], auth_token="fixture-owner-token")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            def request(path, headers=None):
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                connection.request("POST", path, body=json.dumps({}), headers={"Content-Type": "application/json", **(headers or {})})
                response = connection.getresponse()
                status = response.status
                response.read()
                connection.close()
                return status
            try:
                for route in ("/api/investment/rules", "/api/investment/run", "/api/investment/discover", "/api/policy-records", "/api/observations"):
                    self.assertEqual(request(route), 401)
                    self.assertEqual(request(route, {"Authorization": "Bearer fixture-owner-token", "Origin": "https://untrusted.example"}), 403)
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                connection.request("POST", "/api/login", body=json.dumps({"token": "fixture-owner-token"}), headers={"Content-Type": "application/json"})
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                cookie = response.getheader("Set-Cookie").split(";")[0]
                response.read()
                connection.close()
                for route in ("/api/investment/rules", "/api/investment/run", "/api/investment/discover", "/api/policy-records", "/api/observations"):
                    self.assertEqual(request(route, {"Cookie": cookie}), 403)
                self.assertEqual(service.db.count("assetProfile"), 0)
                self.assertEqual(service.db.jobs(), [])
            finally:
                server.shutdown()
                server.server_close()
                service.close()


if __name__ == "__main__":
    unittest.main()
