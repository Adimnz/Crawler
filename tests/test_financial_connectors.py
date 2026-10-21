"""Provider-contract tests with offline SEC, ALFRED and CoinGecko fixtures."""
import copy
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.connectors import ConnectorError, timestamp
from server.financial_connectors import collect_financial_source, discover_instruments


CATALOGUE = {"fields": ["cik", "name", "ticker", "exchange"], "data": [
    [1234, "EXAMPLE TECHNOLOGIES INC", "EXM", "Nasdaq"],
    [5678, "EXAMPLE OTHER CORP", "OTH", "NYSE"],
    [9876, "A COMPANY INC", "A", "NYSE"],
]}
SUBMISSIONS = {"cik": "0000001234", "name": "EXAMPLE TECHNOLOGIES INC", "tickers": ["EXM"], "exchanges": ["Nasdaq"],
               "sic": "3571", "sicDescription": "Electronic Computers", "stateOfIncorporation": "DE", "fiscalYearEnd": "1231",
               "filings": {"recent": {"accessionNumber": ["0000001234-26-000001", "0000001234-25-000001"],
                                       "filingDate": ["2026-02-01", "2025-02-01"], "acceptanceDateTime": ["2026-02-01T18:42:00Z", None],
                                       "reportDate": ["2025-12-31", "2024-12-31"], "form": ["10-K", "10-K"],
                                       "primaryDocument": ["example-20251231.htm", "example-20241231.htm"]}, "files": [{"name": "older.json"}]}}


def row(value, start="2025-01-01", end="2025-12-31", filed="2026-02-01", accession="0000001234-26-000001", **kwargs):
    return {"val": value, "start": start, "end": end, "filed": filed, "accn": accession, "fy": 2025, "fp": "FY", "form": "10-K", **kwargs}


FACTS = {"cik": 1234, "entityName": "EXAMPLE TECHNOLOGIES INC", "facts": {"us-gaap": {
    "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [row(120), row(100, start="2024-01-01", end="2024-12-31", filed="2025-02-01", accession="0000001234-25-000001"),
                                                                                     row(102, start="2024-01-01", end="2024-12-31")]}},
    "NetIncomeLoss": {"units": {"USD": [row(24)]}},
    "Assets": {"units": {"USD": [{"val": 500, "end": "2025-12-31", "filed": "2026-02-01", "accn": "0000001234-26-000001"}]}},
    "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [row(12, start="2025-01-01", end="2025-06-30", fp="Q2"), row(7, start="2025-04-01", end="2025-06-30", fp="Q2")]}},
    "EarningsPerShareDiluted": {"units": {"USD/shares": [row(2.5)]}},
}}}
COIN = {"id": "example-coin", "symbol": "EXC", "name": "Example Coin", "asset_platform_id": "ethereum", "platforms": {"ethereum": "0x123", "polygon-pos": "0x456"},
        "last_updated": "2026-02-02T10:00:00Z", "categories": ["Platform"], "links": {"homepage": ["https://coin.example/"]},
        "market_data": {"current_price": {"usd": 10}, "market_cap": {"usd": 10000}, "total_volume": {"usd": 1200}, "circulating_supply": 1000, "total_supply": 1200, "max_supply": None}}
FRED_SERIES = {"seriess": [{"id": "TEST", "title": "Test Economic Series", "units": "Index", "frequency": "Monthly", "seasonal_adjustment": "Not Seasonally Adjusted"}]}
FRED_ROWS = {"count": 3, "observations": [
    {"date": "2025-01-01", "value": "100", "realtime_start": "2025-02-01", "realtime_end": "2025-02-28"},
    {"date": "2025-01-01", "value": "101", "realtime_start": "2025-03-01", "realtime_end": "9999-12-31"},
    {"date": "2025-02-01", "value": ".", "realtime_start": "2025-03-01", "realtime_end": "9999-12-31"},
]}


class FixtureNetwork:
    def __init__(self):
        self.calls = []
        self.submissions = copy.deepcopy(SUBMISSIONS)
        self.facts = copy.deepcopy(FACTS)
        self.coin = copy.deepcopy(COIN)
        self.fred = copy.deepcopy(FRED_ROWS)

    def fetch(self, url, headers=None, **kwargs):
        self.calls.append((url, headers, kwargs))
        path = urlsplit(url).path
        if path.endswith("company_tickers_exchange.json"):
            payload = CATALOGUE
        elif "/submissions/" in path:
            payload = self.submissions
        elif "/companyfacts/" in path:
            payload = self.facts
        elif path == "/fred/series":
            payload = copy.deepcopy(FRED_SERIES)
            payload["seriess"][0]["id"] = parse_qs(urlsplit(url).query)["series_id"][0]
        elif path.endswith("/observations"):
            payload = self.fred
        elif path.endswith("/coins/list"):
            payload = [{"id": "example-coin", "symbol": "exc", "name": "Example Coin"}]
        elif path.endswith("/market_chart"):
            payload = {"prices": [[timestamp("2025-01-01"), 5], [timestamp("2025-01-02"), 6]], "market_caps": [], "total_volumes": []}
        elif "/coins/" in path:
            payload = self.coin
        else:
            raise AssertionError("Unexpected fixture URL: " + url)
        return json.dumps(payload).encode(), {"content-type": "application/json"}, url


class FinancialConnectorTests(unittest.TestCase):
    def setUp(self):
        self.network = FixtureNetwork()
        self.environment = patch.dict(os.environ, {"SEC_USER_AGENT": "Crawler Research test@example.com", "FRED_API_KEY": "test-fred-key", "COINGECKO_API_KEY": ""})
        self.environment.start()

    def tearDown(self):
        self.environment.stop()

    def sec(self, **config):
        return collect_financial_source({"kind": "sec", "config": {"cik": "1234", "ticker": "EXM", "exchange": "NASDAQ", **config}}, self.network)

    def test_discovery_matches_official_names_and_qualified_tickers_not_common_bare_symbols(self):
        result = discover_instruments([{"id": "one", "title": "Example Technologies reports earnings"}, {"id": "two", "text": "A study about markets mentions NASDAQ:EXM."}], self.network)
        self.assertEqual([item["id"] for item in result], ["equity:NASDAQ:EXM"])
        self.assertEqual(result[0]["triggerDocumentIds"], ["one", "two"])
        self.assertEqual(result[0]["identitySource"], "https://www.sec.gov/files/company_tickers_exchange.json")
        discover_instruments([{"id": "three", "text": "$EXM changed."}], self.network)
        self.assertEqual(len(self.network.calls), 1, "provider catalogue should be cached")

    def test_discovery_uses_only_configured_providers_and_limits_results(self):
        with patch.dict(os.environ, {"SEC_USER_AGENT": "", "COINGECKO_API_KEY": ""}):
            self.assertEqual(discover_instruments([{"id": "one", "title": "Example Technologies earnings"}], self.network), [])
        self.assertEqual(self.network.calls, [])
        self.assertEqual(len(discover_instruments([{"id": "one", "title": "Example Technologies and Example Other announce earnings"}], self.network, limit=1)), 1)

    def test_discovery_never_accesses_disabled_provider_even_if_credentials_exist(self):
        documents = [{"id": "one", "title": "Example Technologies and Example Coin announce earnings"}]
        with patch.dict(os.environ, {"COINGECKO_API_KEY": "test-key"}):
            self.assertEqual(discover_instruments(documents, self.network, providers=set()), [])
            self.assertEqual(self.network.calls, [])
            assets = discover_instruments(documents, self.network, providers={"coingecko"})
            self.assertEqual([asset["id"] for asset in assets], ["crypto:coingecko:example-coin"])
            self.assertTrue(all("coingecko.com" in call[0] for call in self.network.calls))

    def test_sec_requires_contact_user_agent_before_any_network_requests(self):
        with patch.dict(os.environ, {"SEC_USER_AGENT": "TrendCrawler"}):
            with self.assertRaisesRegex(ConnectorError, "contact email"):
                self.sec()
        self.assertEqual(self.network.calls, [])

    def test_sec_identity_must_match_provider_and_cannot_be_supplied_by_configuration(self):
        with self.assertRaisesRegex(ConnectorError, "identity is missing or ambiguous"):
            self.sec(ticker="MADEUP")
        self.network.submissions["cik"] = 9999
        with self.assertRaisesRegex(ConnectorError, "different issuer"):
            self.sec()

    def test_sec_preserves_report_periods_restatements_units_and_actual_filing_availability(self):
        result = self.sec()
        self.assertEqual(result["assets"][0]["id"], "equity:NASDAQ:EXM")
        rows = [item for item in result["observations"] if item["metric"] == "revenue"]
        self.assertEqual(len(rows), 3)
        original = next(item for item in rows if item["value"] == 100)
        revised = next(item for item in rows if item["value"] == 102)
        self.assertEqual(original["periodEnd"], revised["periodEnd"])
        self.assertNotEqual(original["revisionKey"], revised["revisionKey"])
        self.assertEqual(original["availableAt"], timestamp("2025-02-02") - 1)
        self.assertEqual(revised["availableAt"], timestamp("2026-02-01T18:42:00Z"))
        self.assertEqual(revised["unit"], "USD")
        self.assertEqual(revised["accountingBasis"], "us-gaap")
        self.assertEqual(revised["periodType"], "annual")
        self.assertIn("000000123426000001", revised["sourceUrl"])
        self.assertEqual(json.loads(result["raw"])["companyfacts"], self.network.facts)
        self.assertFalse(result["metadata"]["filingBodiesCollected"])

    def test_sec_does_not_label_ytd_cash_flow_as_a_standalone_quarter(self):
        rows = [item for item in self.sec()["observations"] if item["metric"] == "operating_cash_flow"]
        self.assertEqual({item["periodType"] for item in rows}, {"quarterly", "year-to-date"})
        self.assertEqual(next(item for item in rows if item["periodType"] == "year-to-date")["periodDays"], 181)

    def test_sec_metadata_documents_link_to_original_filings_and_preserve_metadata_limit(self):
        result = self.sec(filingLimit=1)
        self.assertEqual(len(result["documents"]), 1)
        self.assertTrue(result["documents"][0]["url"].endswith("example-20251231.htm"))
        self.assertEqual(result["documents"][0]["assetIds"], ["equity:NASDAQ:EXM"])
        self.assertEqual(result["documents"][0]["filingForm"], "10-K")
        self.assertIn("metadata only", result["documents"][0]["text"])
        self.assertTrue(result["metadata"]["olderSubmissionsNotRequested"])

    def test_fred_preserves_multiple_vintages_and_their_known_availability(self):
        result = collect_financial_source({"kind": "fred_vintages", "config": {"series": "TEST"}}, self.network)
        rows = result["observations"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["observedAt"], rows[1]["observedAt"])
        self.assertNotEqual(rows[0]["vintageDate"], rows[1]["vintageDate"])
        self.assertEqual(rows[0]["realtimeEnd"], "2025-02-28")
        self.assertEqual(rows[1]["availableAt"], timestamp("2025-03-02") - 1)
        self.assertEqual(rows[0]["sourceUrl"], "https://fred.stlouisfed.org/series/TEST")
        self.assertNotIn("test-fred-key", json.dumps(result, default=str))
        query = parse_qs(urlsplit(self.network.calls[1][0]).query)
        self.assertEqual(query["realtime_start"], ["1776-07-04"])
        self.assertEqual(query["output_type"], ["1"])

    def test_fred_does_not_claim_complete_history_after_reaching_bounded_page_limit(self):
        self.network.fred = {"count": 7000, "observations": [copy.deepcopy(FRED_ROWS["observations"][0]) for _ in range(2000)]}
        result = collect_financial_source({"kind": "alfred", "config": {"series": "TEST", "maxPages": 1}}, self.network)
        self.assertTrue(result["metadata"]["truncated"])
        self.assertEqual(result["metadata"]["fetchedRows"], 2000)
        self.assertEqual(len(self.network.calls), 2)

    def test_fred_series_bundle_preserves_series_identity_and_limits_request_budget(self):
        result = collect_financial_source({"kind": "fred_vintages", "config": {"series": ["ONE", "TWO", "THREE", "FOUR"], "maxPages": 5}}, self.network)
        self.assertEqual({item["assetId"] for item in result["observations"]}, {"economic:fred:" + series for series in ("ONE", "TWO", "THREE", "FOUR")})
        self.assertEqual(result["metadata"]["pagesPerSeries"], 1)
        self.assertEqual(len(self.network.calls), 8)
        self.assertEqual(len(json.loads(result["raw"])["series"]), 4)
        with self.assertRaisesRegex(ConnectorError, "one to four"):
            collect_financial_source({"kind": "fred_vintages", "config": {"series": []}}, self.network)

    def test_crypto_identity_keeps_contracts_separate_and_does_not_invent_unbounded_supply(self):
        result = collect_financial_source({"kind": "coingecko_asset", "config": {"id": "example-coin", "history": False}}, self.network)
        asset = result["assets"][0]
        self.assertEqual(asset["id"], "crypto:coingecko:example-coin")
        self.assertEqual(asset["contracts"], {"ethereum": "0x123", "polygon-pos": "0x456"})
        self.assertNotIn("max_supply", [item["metric"] for item in result["observations"]])
        self.network.coin["id"] = "other-coin"
        with self.assertRaisesRegex(ConnectorError, "different or incomplete"):
            collect_financial_source({"kind": "coingecko_asset", "config": {"id": "example-coin"}}, self.network)

    def test_crypto_history_retains_daily_sample_and_retrieval_availability(self):
        result = collect_financial_source({"kind": "coingecko_asset", "config": {"id": "example-coin"}}, self.network)
        historical = [item for item in result["observations"] if item.get("historicalAvailabilityUnknown")]
        self.assertEqual(len(historical), 2)
        self.assertTrue(all("availableAt" not in item for item in historical), "the service preserves first local retrieval instead of inventing publication times")
        self.assertTrue(all(item["sampling"] == "daily provider sample" and item["adjustment"] == "raw" for item in historical))
        self.assertEqual(len(self.network.calls), 2)

    def test_crypto_discovery_verifies_each_catalogue_match_with_asset_details(self):
        with patch.dict(os.environ, {"SEC_USER_AGENT": "", "COINGECKO_API_KEY": "test-coin-key"}):
            result = discover_instruments([{"id": "one", "text": "Example Coin announces a supply change."}], self.network)
        self.assertEqual(result[0]["id"], "crypto:coingecko:example-coin")
        self.assertTrue(result[0]["identityVerified"])
        self.assertEqual(len(self.network.calls), 2)
        self.assertNotIn("test-coin-key", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
