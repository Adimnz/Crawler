"""Offline synthetic asset server used only by investment-browser.cjs.

No workers or provider requests are started. Every name, figure and identity in
this module is a test fixture, never an example published by the application.
"""
from pathlib import Path
import datetime as dt
import json
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.service import ResearchService
from server.http import AppServer
from server.storage import now_ms

DAY = 86400000


class OfflineNetwork:
    def fetch(self, *_args, **_kwargs):
        raise AssertionError("The isolated investment fixture must not request external data")

    def json(self, *_args, **_kwargs):
        raise AssertionError("The isolated investment fixture must not request external data")

    def allowed(self, *_args, **_kwargs):
        return False


def populate(service):
    at = now_ms() - 10000
    office = service.add_source({"id": "fixture-office", "name": "Offline Fixture Research Office", "url": "https://fixture.example/research", "kind": "rss", "tier": "primary", "enabled": True, "language": "en", "family": "Offline Fixture Office", "permissions": "Synthetic isolated browser test records only"})
    market = service.add_source({"id": "fixture-market", "name": "Offline Fixture Licensed Market", "url": "https://market.fixture.example/observations", "kind": "json", "tier": "primary", "enabled": True, "family": "Offline Fixture Market", "permissions": "Synthetic isolated browser test observations only"})
    equity = {"id": "equity:NASDAQ:FIXT", "name": "Fixture Equity Laboratory", "ticker": "FIXT", "exchange": "NASDAQ", "assetClass": "equity", "identityVerified": True, "identitySource": "https://data.sec.gov/submissions/CIK0000009999.json", "identityCheckedAt": at, "sector": "Fixture research", "country": "United States", "cik": "0000009999"}
    crypto = {"id": "crypto:coingecko:fixture-token", "name": "Fixture Digital Token", "ticker": "FXD", "assetClass": "crypto", "identityVerified": True, "identitySource": "https://api.coingecko.com/api/v3/coins/fixture-token", "identityCheckedAt": at, "providerId": "fixture-token", "chain": "Fixture network", "country": "Data unavailable"}
    service.investments.accept_assets([equity, crypto], market)
    for asset in (equity, crypto):
        saved = service.db.get("asset", asset["id"])
        saved["firstSeen"] = at - 35 * DAY
        service.db.put("asset", asset["id"], saved)
    text = "Fixture Equity Laboratory reports a documented revenue increase for this synthetic test. The fixture policy proposal describes reporting requirements for the company."
    company = service.ingest(office, {"title": "Fixture Equity Laboratory publishes its synthetic reporting update", "text": text, "url": "https://fixture.example/company-report", "publishedAt": at - DAY, "entities": [{"id": equity["id"], "name": equity["name"], "type": "equity"}], "companyId": equity["cik"], "policyRecord": {"jurisdiction": "Fixture jurisdiction", "status": "Proposal", "eventAt": at - DAY, "quote": "The fixture policy proposal describes reporting requirements for the company.", "reviewedAt": at}})
    token = service.ingest(office, {"title": "Fixture Digital Token records a synthetic protocol disclosure", "text": "Fixture Digital Token has published a protocol disclosure for this synthetic browser test. This record supplies no real financial recommendation.", "url": "https://fixture.example/token-report", "publishedAt": at - DAY, "entities": [{"id": crypto["id"], "name": crypto["name"], "type": "crypto"}]})
    for document in (company, token):
        claim = next(c for c in service.db.list("claim") if c["documentId"] == document["id"])
        service.review_claim({"id": claim["id"], "status": "Verified", "rationale": "Directly checked synthetic fixture record; no real-world fact asserted.", "evidence": [{"documentId": document["id"], "relation": "supports"}], "directEvidenceReviewed": True, "additionalReview": True, "reviewer": "Offline fixture analyst"})
    for kind in ("regulatory-exposure", "economic-exposure"):
        service.add_relationship({"from": equity["id"], "to": "fixture:policy-or-economy", "type": kind, "evidence": [company["id"]], "confirmed": True, "reviewed": True, "validFrom": at - DAY})
    for asset in (equity, crypto):
        for index in range(40):
            observed = at - (39 - index) * DAY
            value = 100 + index if asset is equity else 10 + index * .1
            if asset is crypto and index == 39:
                value = 18
            service.observation(market, {"assetId": asset["id"], "metric": "price_usd", "value": value, "unit": "USD", "currency": "USD", "frequency": "daily", "adjustment": "split-adjusted" if asset is equity else "raw", "observedAt": observed, "session": dt.datetime.fromtimestamp(observed / 1000, dt.timezone.utc).date().isoformat()}, at=at)
    year = dt.datetime.now(dt.timezone.utc).year - 1
    for period_year, revenue, earnings in ((year - 1, 100, 20), (year, 120, 30)):
        end = f"{period_year}-12-31"
        for metric, value in (("revenue", revenue), ("net_income", earnings), ("operating_cash_flow", earnings + 10), ("capital_expenditure", 5)):
            service.observation(office, {"assetId": equity["id"], "metric": metric, "value": value, "unit": "USD", "currency": "USD", "accountingBasis": "us-gaap", "periodStart": f"{period_year}-01-01", "periodEnd": end, "periodType": "annual", "observedAt": int(dt.datetime.fromisoformat(end).replace(tzinfo=dt.timezone.utc).timestamp() * 1000), "sourceUrl": company["url"]}, at=at)
    service.investments.cycle("Initial isolated browser fixture")
    first_profile = service.investments.profile(equity["id"])["profile"]
    assert first_profile["qualified"], first_profile["qualificationGaps"]
    time.sleep(.005)
    service.observation(market, {"assetId": equity["id"], "metric": "price_usd", "value": 150, "unit": "USD", "currency": "USD", "frequency": "daily", "adjustment": "split-adjusted", "observedAt": at, "session": dt.datetime.fromtimestamp(at / 1000, dt.timezone.utc).date().isoformat()}, at=now_ms())
    service.investments.cycle("Synthetic quoted-price revision")
    latest = service.investments.profile(equity["id"])["profile"]
    assert latest["version"] >= 2 and latest["assessedAt"] > first_profile["assessedAt"]
    return {"equityId": equity["id"], "cryptoId": crypto["id"], "firstRevisionAt": first_profile["assessedAt"], "latestRevisionAt": latest["assessedAt"], "latestVersion": latest["version"], "documentCount": 2, "firstPrice": 139, "latestPrice": 150}


def main():
    with tempfile.TemporaryDirectory(prefix="crawler-investment-browser-") as directory:
        service = ResearchService(directory, network=OfflineNetwork(), seed=False, dsn="")
        server = None
        try:
            fixture = populate(service)
            server = AppServer(("127.0.0.1", 0), service, Path(__file__).resolve().parents[1], auth_token="")
            # Graceful stdin shutdown lets TemporaryDirectory clean up on Windows.
            def shutdown():
                sys.stdin.readline()
                server.shutdown()
            threading.Thread(target=shutdown, daemon=True).start()
            print(json.dumps({"port": server.server_port, **fixture}), flush=True)
            server.serve_forever(poll_interval=.05)
        finally:
            if server:
                server.server_close()
            service.close()


if __name__ == "__main__":
    main()
