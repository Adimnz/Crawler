"""Isolated search experience fixture. No external requests or paid AI calls."""
from pathlib import Path
import json
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.connectors import ConnectorError
from server.http import AppServer
from server.service import ResearchService
from server.storage import now_ms

DAY = 86400000
TEST_KEY = "sk-test-fixture-connection-secret"
MARKET_QUERY = "regional credit"


class SearchNetwork:
    market_document = None

    def fetch(self, *_args, **_kwargs):
        raise ConnectorError("External requests are disabled in the search browser fixture")

    def allowed(self, *_args, **_kwargs):
        return False

    def json(self, url, headers=None, body=None):
        body = body or {}
        if url == "https://api.openai.com/v1/responses" and self.market_document:
            schema_name = body.get("text", {}).get("format", {}).get("name")
            if schema_name == "topic_research_plan" and MARKET_QUERY in str(body.get("input", "")).casefold():
                result = {"title": "Regional credit research", "searchTerms": ["regional credit", "funding conditions"],
                          "questions": ["What original disclosures connect funding conditions to lenders and borrowers?"],
                          "assetTypes": ["companies", "markets", "financial institutions"], "regions": []}
                return self.structured_response(result)
            if schema_name == "market_topic_research":
                document = self.market_document
                def evidence(quote):
                    assert quote in document["text"]
                    return [{"documentId": document["id"], "version": document["version"], "quote": quote}]
                bank_quote = "Fixture Regional Bank reports that changing funding conditions affect its lending operations."
                market_quote = "Fixture Treasury Council reports that regional credit markets face changing funding conditions."
                company_quote = "Fixture Manufacturers Ltd reports that financing costs influence its capital spending plans."
                result = {
                    "summary": [{"text": "The retained disclosures connect regional credit conditions to lender funding and manufacturer financing costs.", "evidence": evidence(market_quote)}],
                    "drivers": [{"text": "Funding conditions warrant monitoring alongside lender and borrower disclosures.", "evidence": evidence(bank_quote)}],
                    "risks": [{"text": "The direction and size of any financing impact still require additional evidence.", "evidence": evidence(company_quote)}],
                    "subjects": [
                        {"name": "Fixture Manufacturers Ltd", "kind": "company", "connection": "The disclosure identifies financing costs as relevant to its capital spending.", "watchFor": "What does the next capital spending disclosure report?", "evidence": evidence(company_quote)},
                        {"name": "regional credit markets", "kind": "market", "connection": "The source describes changing funding conditions in this market.", "watchFor": "What do original credit and funding releases report next?", "evidence": evidence(market_quote)},
                        {"name": "Fixture Regional Bank", "kind": "financial_institution", "connection": "The bank disclosure connects funding conditions to lending operations.", "watchFor": "What does the next lending and funding disclosure report?", "evidence": evidence(bank_quote)},
                    ],
                    "nextQuestions": ["Which current lending and issuance releases confirm whether funding conditions changed?"],
                }
                return self.structured_response(result)
            if any(tool.get("type") == "web_search" for tool in body.get("tools", [])):
                return {"status": "completed", "output": [{"type": "web_search_call", "status": "completed", "action": {"sources": []}}]}
        if url == "https://api.openai.com/v1/models":
            if (headers or {}).get("Authorization") != "Bearer " + TEST_KEY:
                error = ConnectorError("Synthetic API key was rejected")
                error.status, error.code = 401, "invalid_api_key"
                raise error
            return {"object": "list", "data": [{"id": model, "object": "model"} for model in (
                "fixture-research-model", "fixture-unsupported-model", "fixture-delayed-model", "text-embedding-3-small",
            )]}
        # Only a synthetic connection check is admitted. Research tools and
        # connector requests never leave this process.
        if url == "https://api.openai.com/v1/responses" and body.get("text", {}).get("format", {}).get("name") == "connection_check":
            if (headers or {}).get("Authorization") != "Bearer " + TEST_KEY:
                raise ConnectorError("Synthetic connection credentials were not forwarded")
            if body.get("model") == "fixture-unsupported-model":
                error = ConnectorError("Synthetic model does not support the connection check")
                error.status, error.code = 400, "unsupported_parameter"
                raise error
            if body.get("model") not in {"fixture-research-model", "fixture-delayed-model"}:
                raise ConnectorError("Synthetic connection model was not forwarded")
            if body.get("model") == "fixture-delayed-model":
                time.sleep(3)
            return {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": '{"status":"connected"}'}]}]}
        raise ConnectorError("External research is disabled in the search browser fixture")

    @staticmethod
    def structured_response(result):
        return {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(result)}]}]}


def populate(service):
    at = now_ms() - 10000
    office = service.add_source({"id": "fixture-office", "name": "Offline Fixture Research Office", "url": "https://fixture.example/research", "kind": "rss", "tier": "primary", "enabled": True, "language": "en", "family": "Offline Fixture Office", "permissions": "Synthetic isolated browser test records only"})
    market = service.add_source({"id": "fixture-market", "name": "Offline Fixture Market", "url": "https://market.fixture.example/observations", "kind": "json", "tier": "primary", "enabled": True, "family": "Offline Fixture Market", "permissions": "Synthetic observations only", "config": {"recordType": "observation"}})
    equity = {"id": "equity:NASDAQ:FIXT", "name": "Fixture Equity Laboratory", "ticker": "FIXT", "exchange": "NASDAQ", "assetClass": "equity", "identityVerified": True, "identitySource": "https://data.sec.gov/submissions/CIK0000009999.json", "identityCheckedAt": at, "cik": "0000009999"}
    crypto = {"id": "crypto:coingecko:fixture-token", "name": "Fixture Digital Token", "ticker": "FXD", "assetClass": "crypto", "identityVerified": True, "identitySource": "https://api.coingecko.com/api/v3/coins/fixture-token", "identityCheckedAt": at, "providerId": "fixture-token"}
    service.investments.accept_assets([equity, crypto], market)
    for asset in (equity, crypto):
        stored = service.db.get("asset", asset["id"])
        stored["firstSeen"] = at - 35 * DAY
        service.db.put("asset", asset["id"], stored)
        document = service.ingest(office, {"title": asset["name"] + " publishes a synthetic disclosure", "text": asset["name"] + " reports a documented synthetic development for this browser fixture. This fixture supplies no real investment information.", "url": "https://fixture.example/" + ("company-report" if asset is equity else "token-report"), "publishedAt": at - DAY, "entities": [{"id": asset["id"], "name": asset["name"], "type": asset["assetClass"]}], "companyId": asset.get("cik", "")})
        claim = next(c for c in service.db.list("claim") if c["documentId"] == document["id"])
        service.review_claim({"id": claim["id"], "status": "Verified", "rationale": "Synthetic fixture disclosure checked directly.", "evidence": [{"documentId": document["id"], "relation": "supports"}], "directEvidenceReviewed": True, "additionalReview": True})
        for days_ago in (35, 0):
            service.observation(market, {"assetId": asset["id"], "metric": "price_usd", "value": 100, "unit": "USD", "currency": "USD", "frequency": "daily", "adjustment": "raw", "observedAt": at - days_ago * DAY}, at=at)
    return {"equityId": equity["id"], "cryptoId": crypto["id"]}


def add_stale_candidate(service):
    at = now_ms()
    office, market = service.db.get("source", "fixture-office"), service.db.get("source", "fixture-market")
    asset = {"id": "equity:NASDAQ:FIXS", "name": "Fixture Equity Laboratory Legacy Review", "ticker": "FIXS", "exchange": "NASDAQ", "assetClass": "equity", "identityVerified": True, "identitySource": "https://data.sec.gov/submissions/CIK0000009998.json", "identityCheckedAt": at, "cik": "0000009998"}
    service.investments.accept_assets([asset], market)
    stored = service.db.get("asset", asset["id"])
    stored["firstSeen"] = at - 35 * DAY
    service.db.put("asset", asset["id"], stored)
    document = service.ingest(office, {"title": "Fixture Equity Laboratory Legacy Review reports a synthetic disclosure", "text": "Fixture Equity Laboratory Legacy Review publishes this synthetic research disclosure. Its current market data is intentionally unavailable in this browser fixture.", "url": "https://fixture.example/legacy-report", "publishedAt": at - DAY, "entities": [{"id": asset["id"], "name": asset["name"], "type": "equity"}], "companyId": asset["cik"]})
    claim = next(c for c in service.db.list("claim") if c["documentId"] == document["id"])
    service.review_claim({"id": claim["id"], "status": "Verified", "rationale": "Synthetic fixture disclosure checked directly.", "evidence": [{"documentId": document["id"], "relation": "supports"}], "directEvidenceReviewed": True, "additionalReview": True})
    for days_ago in (35, 3):
        service.observation(market, {"assetId": asset["id"], "metric": "price_usd", "value": 20, "unit": "USD", "currency": "USD", "frequency": "daily", "adjustment": "raw", "observedAt": at - days_ago * DAY}, at=at)
    service.investments.cycle("Synthetic stale candidate")
    assert not service.investments.profile(asset["id"])["profile"]["qualified"]
    assert service.investments.profile("equity:NASDAQ:FIXT")["profile"]["qualified"]
    return asset["id"]


def add_market_research(service):
    """A retained source supports research without any identified instrument."""
    office = service.db.get("source", "fixture-office")
    document = service.ingest(office, {"title": "Regional credit conditions: synthetic lender and manufacturer disclosures",
        "text": "Fixture Treasury Council reports that regional credit markets face changing funding conditions. "
                "Fixture Regional Bank reports that changing funding conditions affect its lending operations. "
                "Fixture Manufacturers Ltd reports that financing costs influence its capital spending plans. "
                "These are synthetic source statements for an isolated browser test.",
        "url": "https://fixture.example/regional-credit-report", "publishedAt": now_ms() - DAY})
    service.network.market_document = document
    checked = service.ai_settings.connect({"apiKey": TEST_KEY, "model": "fixture-research-model", "automaticAnalysis": False})
    assert checked["connectionTest"]["ok"] and not service.auto_ai
    return document


def main():
    # Environment credentials must never change an isolated browser test.
    for key in ("OPENAI_API_KEY", "OPENAI_MODEL", "CRAWLER_AUTO_AI", "S3_BUCKET", "DATABASE_URL"):
        os.environ.pop(key, None)
    with tempfile.TemporaryDirectory(prefix="crawler-search-browser-") as directory:
        service = ResearchService(directory, network=SearchNetwork(), seed=False, dsn="")
        server = None
        try:
            fixture = populate(service)
            stale_id = add_stale_candidate(service)
            if "--market-research" in sys.argv:
                market_document = add_market_research(service)
                fixture.update(marketDocumentId=market_document["id"], marketQuery=MARKET_QUERY)
            # Run the application's real job worker, without scheduling external
            # source polls or provider discovery.
            worker = threading.Thread(target=service.worker, daemon=True)
            service.threads.append(worker)
            worker.start()
            server = AppServer(("127.0.0.1", 0), service, Path(__file__).resolve().parents[1], auth_token="")

            def shutdown():
                sys.stdin.readline()
                server.shutdown()

            threading.Thread(target=shutdown, daemon=True).start()
            print(json.dumps({"port": server.server_port, "staleId": stale_id, **fixture}), flush=True)
            server.serve_forever(poll_interval=.05)
        finally:
            if server:
                server.server_close()
            service.close()


if __name__ == "__main__":
    main()
