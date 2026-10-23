"""Bounded, server-side financial collection from identified public data providers.

Provider identifiers, filing periods, publication availability and vintage dates stay
attached to every value. These connectors report data; they do not infer exposure or
make investment recommendations. Callers persist the returned raw provider payloads.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import re
import time
from urllib.parse import quote, urlencode

from .connectors import ConnectorError, strip_html, timestamp


SEC_TICKERS = "https://www.sec.gov/files/company_tickers_exchange.json"
SEC_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
FRED_OBSERVATIONS = "https://api.stlouisfed.org/fred/series/observations"
FRED_SERIES = "https://api.stlouisfed.org/fred/series"
COINGECKO = "https://api.coingecko.com/api/v3"

# Alternatives remain distinct concepts. The financial calculator must select
# compatible concepts and periods rather than summing overlapping disclosure tags.
SEC_CONCEPTS = {
    "us-gaap": {
        "revenue": ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet", "RevenueFromContractWithCustomerIncludingAssessedTax"),
        "net_income": ("NetIncomeLoss", "ProfitLoss"),
        "gross_profit": ("GrossProfit",),
        "operating_income": ("OperatingIncomeLoss",),
        "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",),
        "capital_expenditure": ("PaymentsToAcquirePropertyPlantAndEquipment",),
        "assets": ("Assets",),
        "current_assets": ("AssetsCurrent",),
        "liabilities": ("Liabilities",),
        "current_liabilities": ("LiabilitiesCurrent",),
        "debt_current": ("LongTermDebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent"),
        "debt_noncurrent": ("LongTermDebtNoncurrent",),
        "cash": ("CashAndCashEquivalentsAtCarryingValue",),
        "equity": ("StockholdersEquity",),
        "shares_outstanding": ("CommonStockSharesOutstanding",),
        "eps_diluted": ("EarningsPerShareDiluted",),
    },
    "ifrs-full": {
        "revenue": ("Revenue",), "net_income": ("ProfitLoss",),
        "gross_profit": ("GrossProfit",), "operating_income": ("ProfitLossFromOperatingActivities",),
        "operating_cash_flow": ("CashFlowsFromUsedInOperatingActivities",),
        "capital_expenditure": ("PurchaseOfPropertyPlantAndEquipment",),
        "assets": ("Assets",), "current_assets": ("CurrentAssets",),
        "liabilities": ("Liabilities",), "current_liabilities": ("CurrentLiabilities",),
        "cash": ("CashAndCashEquivalents",), "equity": ("Equity",),
        "eps_diluted": ("DilutedEarningsLossPerShare",),
    },
    "dei": {"shares_outstanding": ("EntityCommonStockSharesOutstanding",)},
}


def _now():
    return int(time.time() * 1000)


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _date(value, default=None):
    try:
        return dt.date.fromisoformat(str(value)).isoformat()
    except (TypeError, ValueError):
        return default


def _available(date):
    """A date-only release becomes available at the end of that UTC date."""
    parsed = timestamp(_date(date))
    return parsed + 86400000 - 1 if parsed is not None else None


def _json(network, url, headers=None, limit=6 * 1024 * 1024):
    data, metadata, resolved = network.fetch(url, headers=headers or {}, limit=limit)
    try:
        payload = json.loads(data)
    except (TypeError, ValueError) as exc:
        raise ConnectorError("Financial provider did not return valid JSON") from exc
    if not isinstance(payload, (dict, list)):
        raise ConnectorError("Financial provider returned an invalid data structure")
    return payload, data, metadata, resolved


def _sec_headers():
    identity = os.getenv("SEC_USER_AGENT", "").strip()
    if len(identity) < 8 or not re.search(r"[^\s@]+@[^\s@]+\.[^\s@]+", identity) or "\n" in identity or "\r" in identity:
        raise ConnectorError("SEC_USER_AGENT must identify the application and a contact email")
    return {"User-Agent": identity, "Accept": "application/json"}


def _cached(network, name, loader, ttl=86400):
    cache = getattr(network, "_financial_cache", None)
    if cache is None:
        cache = {}
        network._financial_cache = cache
    cached = cache.get(name)
    if cached and cached[0] > time.monotonic() - ttl:
        return cached[1]
    value = loader()
    cache[name] = (time.monotonic(), value)
    return value


def _exchange(value):
    # Exchange labels are normalized only when the provider names the exchange.
    text = str(value or "").strip().upper()
    return {"NASDAQ": "NASDAQ", "NYSE": "NYSE", "NYSE AMERICAN": "NYSEAMERICAN", "CBOE": "CBOE", "OTC": "OTC"}.get(text, re.sub(r"[^A-Z0-9]", "", text))


def _equity(name, ticker, exchange, cik, source_url):
    ticker, exchange = str(ticker or "").upper().strip(), _exchange(exchange)
    if not name or not exchange or not re.fullmatch(r"[A-Z0-9][A-Z0-9.\-]{0,19}", ticker):
        return None
    return {"id": f"equity:{exchange}:{ticker}", "assetClass": "equity", "name": str(name), "ticker": ticker,
            "exchange": exchange, "cik": str(cik).zfill(10), "identityVerified": True,
            "identitySource": source_url, "identityCheckedAt": _now(), "identityScope": "Current provider association; historical identity and listing status require separate verification"}


def _ticker_catalogue(network):
    payload, _, _, _ = _json(network, SEC_TICKERS, _sec_headers())
    if not isinstance(payload, dict) or not isinstance(payload.get("fields"), list) or not isinstance(payload.get("data"), list):
        raise ConnectorError("SEC instrument catalogue has an unexpected structure")
    result = []
    for values in payload["data"]:
        if not isinstance(values, list):
            continue
        row = dict(zip(payload["fields"], values))
        cik = str(row.get("cik", ""))
        if not re.fullmatch(r"\d{1,10}", cik):
            continue
        asset = _equity(row.get("name"), row.get("ticker"), row.get("exchange"), cik, SEC_TICKERS)
        if asset:
            result.append(asset)
    return result


def _name_key(value):
    value = re.sub(r"[^a-z0-9]+", " ", str(value).lower()).strip()
    return re.sub(r"\s+(?:incorporated|corporation|holdings|company|limited|ltd|corp|inc|plc|co)(?:\s+(?:inc|ltd|corp|co))?$", "", value).strip()


def _trigger_ids(asset, documents):
    key = _name_key(asset["name"])
    raw_ticker = str(asset.get("ticker", ""))
    ticker = re.escape(raw_ticker)
    pattern = re.compile(r"(?:\$" + ticker + r"\b|\(" + ticker + r"\)|(?:NASDAQ|NYSE|NYSEAMERICAN|CBOE|OTC)\s*:\s*" + ticker + r"\b)", re.I) if ticker else None
    result = []
    for doc in documents:
        # A collection cycle can scan thousands of catalogue rows. Normalize the
        # bounded evidence set once and reject absent names before regex work.
        words = doc.get("_searchWords")
        if words is not None and (not key or key.split()[0] not in words) and raw_ticker.lower() not in words:
            continue
        text = doc.get("_searchText") or str(doc.get("title", "")) + " " + str(doc.get("text", ""))
        normalized = doc.get("_searchNormalized") or " " + _name_key(text) + " "
        named = len(key) >= 5 and (" " + key + " ") in normalized
        explicit_ticker = pattern.search(text) if pattern else False
        if (named or explicit_ticker) and doc.get("id"):
            result.append(str(doc["id"]))
    return result


def _coin_headers():
    key = os.getenv("COINGECKO_API_KEY", "").strip()
    return {"x-cg-demo-api-key": key} if key else {}


def _coin_identity(payload, requested_id, source_url):
    if not isinstance(payload, dict) or payload.get("id") != requested_id or not payload.get("name") or not payload.get("symbol"):
        raise ConnectorError("CoinGecko returned a different or incomplete instrument identity")
    contracts = {str(chain): str(contract) for chain, contract in payload.get("platforms", {}).items() if chain and contract} if isinstance(payload.get("platforms"), dict) else {}
    return {"id": "crypto:coingecko:" + requested_id, "providerId": requested_id, "name": payload["name"], "ticker": str(payload["symbol"]).upper(),
            "assetClass": "crypto", "chain": payload.get("asset_platform_id") or None, "contracts": contracts,
            "identityVerified": True, "identitySource": source_url, "identityCheckedAt": _now(),
            "identityScope": "Provider asset identity; listed platform contracts remain separate chain identities"}


def discover_instruments(documents, network, limit=6, *, providers=None):
    """Find explicit issuer/asset mentions against official catalogues, never fuzzy guesses.

    SEC discovery runs only with an identified SEC_USER_AGENT; optional crypto
    catalogue discovery runs only when COINGECKO_API_KEY is configured. Callers
    restrict ``providers`` to the enabled provider set (``sec``, ``coingecko``).
    An empty set makes no requests. The result
    identifies mentions, not a verified economic or political exposure.
    """
    documents, limit = list(documents)[:200], max(0, min(20, int(limit)))
    providers = {"sec", "coingecko"} if providers is None else set(providers)
    if not documents or not limit:
        return []
    prepared = []
    for doc in documents:
        text = (str(doc.get("title", "")) + " " + str(doc.get("text", "")))[:32000]
        normalized = " " + _name_key(text) + " "
        prepared.append({"id": doc.get("id"), "_searchText": text, "_searchNormalized": normalized, "_searchWords": set(normalized.split())})
    documents = prepared
    result = []
    if "sec" in providers and os.getenv("SEC_USER_AGENT"):
        for asset in _cached(network, "sec-tickers", lambda: _ticker_catalogue(network)):
            triggers = _trigger_ids(asset, documents)
            if triggers:
                result.append({**asset, "triggerDocumentIds": triggers, "discoveryMethod": "Explicit issuer name or qualified ticker in collected evidence"})
                if len(result) >= limit:
                    return result
    if "coingecko" in providers and os.getenv("COINGECKO_API_KEY") and len(result) < limit:
        catalogue = _cached(network, "coingecko-list", lambda: _json(network, COINGECKO + "/coins/list?include_platform=false", _coin_headers())[0])
        if not isinstance(catalogue, list):
            raise ConnectorError("CoinGecko instrument catalogue has an unexpected structure")
        for coin in catalogue[:30000]:
            if not isinstance(coin, dict) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,99}", str(coin.get("id", ""))):
                continue
            triggers = _trigger_ids({"name": coin.get("name", ""), "ticker": ""}, documents)
            if not triggers:
                continue
            url = COINGECKO + "/coins/" + coin["id"] + "?localization=false&tickers=false&market_data=false&community_data=false&developer_data=false"
            payload = _cached(network, "coin-identity:" + coin["id"], lambda: _json(network, url, _coin_headers())[0])
            result.append({**_coin_identity(payload, coin["id"], url), "triggerDocumentIds": triggers, "discoveryMethod": "Explicit asset name in collected evidence"})
            if len(result) >= limit:
                break
    return result


def _filing_url(cik, accession, document=None):
    if not re.fullmatch(r"\d{10}-\d{2}-\d{6}", str(accession)):
        return None
    root = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{str(accession).replace('-', '')}/"
    if document:
        parts = str(document).split("/")
        if any(part in {"", ".", ".."} for part in parts):
            return None
        return root + "/".join(quote(part, safe="-_.") for part in parts)
    return root + str(accession) + "-index.html"


def _period(row):
    start, end = _date(row.get("start")), _date(row.get("end"))
    days = (dt.date.fromisoformat(end) - dt.date.fromisoformat(start)).days + 1 if start and end else None
    if not start:
        period = "instant"
    elif days is not None and 330 <= days <= 400:
        period = "annual"
    elif days is not None and 60 <= days <= 120:
        period = "quarterly"
    elif days is not None and 121 <= days <= 329:
        period = "year-to-date"
    else:
        period = "other"
    return start, end, days, period


def _collect_sec(source, network):
    config, headers = source.get("config", {}), _sec_headers()
    cik = str(config.get("cik", "")).strip()
    requested_ticker = str(config.get("ticker", "")).upper().strip()
    if not cik and requested_ticker:
        matches = [item for item in _cached(network, "sec-tickers", lambda: _ticker_catalogue(network)) if item["ticker"] == requested_ticker and (not config.get("exchange") or item["exchange"] == _exchange(config["exchange"]))]
        if len(matches) != 1:
            raise ConnectorError("SEC ticker lookup is missing or ambiguous; provide a verified CIK and exchange")
        cik = matches[0]["cik"]
    if not re.fullmatch(r"\d{1,10}", cik):
        raise ConnectorError("SEC source requires a numeric CIK or an unambiguous official ticker")
    cik = cik.zfill(10)
    submissions_url = SEC_SUBMISSIONS.format(cik=cik)
    submissions, _, _, _ = _json(network, submissions_url, headers)
    if not isinstance(submissions, dict) or str(submissions.get("cik", "")).lstrip("0") != cik.lstrip("0"):
        raise ConnectorError("SEC submissions returned a different issuer identity")
    tickers, exchanges = submissions.get("tickers", []), submissions.get("exchanges", [])
    assets = []
    for ticker, exchange in zip(tickers, exchanges):
        if requested_ticker and str(ticker).upper() != requested_ticker:
            continue
        if config.get("exchange") and _exchange(exchange) != _exchange(config["exchange"]):
            continue
        asset = _equity(submissions.get("name"), ticker, exchange, cik, submissions_url)
        if asset:
            assets.append(asset)
    if len(assets) != 1:
        raise ConnectorError("Issuer listing identity is missing or ambiguous; configure a ticker and exchange confirmed by SEC submissions")
    asset = assets[0]
    asset.update({"sic": submissions.get("sic"), "sicDescription": submissions.get("sicDescription"), "sector": submissions.get("sicDescription") or None,
                  "fiscalYearEnd": submissions.get("fiscalYearEnd"), "incorporationJurisdiction": submissions.get("stateOfIncorporation") or None})
    # Incorporation and mailing addresses are not asserted to be revenue geography.
    recent = submissions.get("filings", {}).get("recent", {})
    documents, filing_availability = [], {}
    filing_count = min(200, max(1, int(config.get("filingLimit", 50))))
    if isinstance(recent, dict):
        for index, accession in enumerate(recent.get("accessionNumber", [])[:1000]):
            row = {name: values[index] for name, values in recent.items() if isinstance(values, list) and index < len(values)}
            filing_date = _date(row.get("filingDate"))
            accepted = timestamp(row.get("acceptanceDateTime"))
            available = accepted if accepted is not None else _available(filing_date)
            filing_availability[accession] = available
            if len(documents) >= filing_count:
                continue
            url = _filing_url(cik, accession, row.get("primaryDocument"))
            if not url or not filing_date:
                continue
            form = str(row.get("form", "Unknown"))
            title = f"{asset['name']} files {form} with the SEC on {filing_date}"
            documents.append({"title": title, "text": title + ". Filing metadata only; the full filing body has not been collected.",
                              "url": url, "publishedAt": accepted or timestamp(filing_date), "publishedEstimated": accepted is None, "availableAt": available,
                              "language": "en", "assetIds": [asset["id"]], "recordType": "filing", "filingForm": form,
                              "entities": [{"id": asset["id"], "name": asset["name"], "type": "equity"}], "companyId": asset["id"], "filingType": form,
                              "reportDate": _date(row.get("reportDate")), "accessionNumber": accession, "raw": row})
    facts_url = SEC_FACTS.format(cik=cik)
    facts, _, metadata, resolved = _json(network, facts_url, headers, limit=24 * 1024 * 1024)
    if not isinstance(facts, dict) or str(facts.get("cik", "")).lstrip("0") != cik.lstrip("0"):
        raise ConnectorError("SEC financial facts returned a different issuer identity")
    observations = []
    seen = set()
    for taxonomy, metrics in SEC_CONCEPTS.items():
        taxonomy_facts = facts.get("facts", {}).get(taxonomy, {})
        for metric, concepts in metrics.items():
            for priority, concept in enumerate(concepts):
                item = taxonomy_facts.get(concept, {})
                for unit, rows in item.get("units", {}).items():
                    # Recent filings include comparative years. All overlapping concepts
                    # and revised filings keep their own provenance and availability.
                    for row in rows[-1500:]:
                        value, filed = _number(row.get("val")), _date(row.get("filed"))
                        start, end, days, period = _period(row)
                        accession = row.get("accn")
                        url = _filing_url(cik, accession)
                        if value is None or not end or not filed or not url:
                            continue
                        available = filing_availability.get(accession) or _available(filed)
                        identity = (metric, taxonomy, concept, unit, start, end, filed, accession, value)
                        if identity in seen:
                            continue
                        seen.add(identity)
                        currency = unit.split("/", 1)[0] if re.fullmatch(r"[A-Z]{3}(?:/shares)?", unit) else None
                        observations.append({"assetId": asset["id"], "assetClass": "equity", "metric": metric, "value": value,
                                             "observedAt": timestamp(end), "availableAt": available, "filedAt": available, "filedDate": filed,
                                             "periodStart": start, "periodEnd": end, "periodDays": days, "periodType": period,
                                             "unit": unit, "units": unit, "currency": currency, "accountingBasis": taxonomy,
                                             "taxonomy": taxonomy, "concept": concept, "conceptPriority": priority,
                                             "fiscalYear": row.get("fy"), "fiscalPeriod": row.get("fp"), "frame": row.get("frame"), "filingForm": row.get("form"),
                                             "accessionNumber": accession, "sourceUrl": url, "providerUrl": facts_url, "provider": "SEC EDGAR",
                                             "revisionKey": ":".join(map(str, identity[:-1])), "publicationPrecision": "timestamp" if accession in filing_availability and filing_availability[accession] != _available(filed) else "date"})
    observations.sort(key=lambda row: (row["availableAt"], row["observedAt"], row["metric"], row["conceptPriority"]))
    return {"assets": assets, "documents": documents, "observations": observations,
            "raw": json.dumps({"submissions": submissions, "companyfacts": facts}, ensure_ascii=False).encode(),
            "metadata": {**metadata, "provider": "SEC EDGAR", "filingBodiesCollected": False, "olderSubmissionsNotRequested": bool(submissions.get("filings", {}).get("files")),
                         "conceptCoverage": "Selected standard taxonomy facts; custom tags and segment disclosures require separate filing research"}, "resolvedUrl": resolved}


def _collect_fred(source, network):
    key = os.getenv("FRED_API_KEY", "").strip()
    if not key:
        raise ConnectorError("FRED_API_KEY is not configured")
    config = source.get("config", {})
    series = str(config.get("series", "CPIAUCSL")).strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", series):
        raise ConnectorError("FRED series identifier is invalid")
    today = dt.datetime.now(dt.timezone.utc).date()
    start = _date(config.get("observationStart"), (today - dt.timedelta(days=3653)).isoformat())
    realtime_start = _date(config.get("realtimeStart"), "1776-07-04")
    realtime_end = _date(config.get("realtimeEnd"), today.isoformat())
    identity_payload, _, _, _ = _json(network, FRED_SERIES + "?" + urlencode({"series_id": series, "api_key": key, "file_type": "json"}))
    identities = identity_payload.get("seriess", []) if isinstance(identity_payload, dict) else []
    if not identities or identities[0].get("id") != series:
        raise ConnectorError("FRED returned a different or missing series identity")
    identity = identities[0]
    asset_id, public_url = "economic:fred:" + series, "https://fred.stlouisfed.org/series/" + quote(series, safe="")
    asset = {"id": asset_id, "assetClass": "economic", "name": identity.get("title", series), "ticker": series, "providerId": series,
             "identityVerified": True, "identitySource": public_url, "identityCheckedAt": _now(), "unit": identity.get("units"),
             "frequency": identity.get("frequency"), "seasonalAdjustment": identity.get("seasonal_adjustment")}
    pages, observations, count = [], [], None
    page_size, max_pages = 2000, min(5, max(1, int(config.get("maxPages", 3))))
    for page in range(max_pages):
        query = {"series_id": series, "api_key": key, "file_type": "json", "output_type": 1, "units": "lin", "sort_order": "desc",
                 "realtime_start": realtime_start, "realtime_end": realtime_end, "observation_start": start, "limit": page_size, "offset": page * page_size}
        payload, _, _, _ = _json(network, FRED_OBSERVATIONS + "?" + urlencode(query))
        if not isinstance(payload, dict):
            raise ConnectorError("FRED observations returned an unexpected structure")
        pages.append(payload)
        count = payload.get("count")
        rows = payload.get("observations", [])
        if not isinstance(rows, list):
            raise ConnectorError("FRED observations must be an array")
        for row in rows:
            value, date, vintage = _number(row.get("value")), _date(row.get("date")), _date(row.get("realtime_start"))
            end = _date(row.get("realtime_end"))
            if value is None or not date or not vintage or not end:
                continue
            observations.append({"assetId": asset_id, "assetClass": "economic", "metric": "level", "value": value, "observedAt": timestamp(date),
                                 "periodStart": date, "periodEnd": date, "periodType": "economic", "unit": identity.get("units", "Data unavailable"),
                                 "units": identity.get("units", "Data unavailable"), "frequency": identity.get("frequency"),
                                 "seasonalAdjustment": identity.get("seasonal_adjustment"), "realtimeStart": vintage, "realtimeEnd": end,
                                 "vintageDate": vintage, "revisionDate": vintage, "availableAt": _available(vintage), "publicationPrecision": "date",
                                 "sourceUrl": public_url, "provider": "FRED / ALFRED", "seriesId": series,
                                 "revisionKey": f"{series}:{date}:{vintage}"})
        if len(rows) < page_size or isinstance(count, int) and (page + 1) * page_size >= count:
            break
    fetched = sum(len(page.get("observations", [])) for page in pages)
    return {"assets": [asset], "documents": [], "observations": observations, "raw": json.dumps({"series": identity_payload, "pages": pages}).encode(),
            "metadata": {"provider": "FRED / ALFRED", "vintagesPreserved": True, "observationStart": start, "realtimeStart": realtime_start,
                         "realtimeEnd": realtime_end, "availableRows": count, "fetchedRows": fetched, "truncated": isinstance(count, int) and fetched < count,
                         "availabilityNote": "Release dates have no intraday publication time; availability uses end of UTC date"}, "resolvedUrl": public_url}


def _collect_coin(source, network):
    config, headers = source.get("config", {}), _coin_headers()
    coin_id = str(config.get("id") or config.get("providerId") or "").strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,99}", coin_id):
        raise ConnectorError("CoinGecko asset source requires a provider asset ID")
    url = COINGECKO + "/coins/" + coin_id + "?localization=false&tickers=false&market_data=true&community_data=false&developer_data=false"
    payload, _, metadata, resolved = _json(network, url, headers)
    asset = _coin_identity(payload, coin_id, url)
    market = payload.get("market_data", {})
    at = timestamp(market.get("last_updated") or payload.get("last_updated"))
    observations = []
    fields = {"price_usd": (market.get("current_price", {}).get("usd"), "USD"),
              "market_cap": (market.get("market_cap", {}).get("usd"), "USD"),
              "volume_24h": (market.get("total_volume", {}).get("usd"), "USD"),
              "circulating_supply": (market.get("circulating_supply"), "tokens"), "total_supply": (market.get("total_supply"), "tokens"),
              "max_supply": (market.get("max_supply"), "tokens")}
    if at is not None:
        for metric, (value, unit) in fields.items():
            value = _number(value)
            if value is not None:
                observations.append({"assetId": asset["id"], "assetClass": "crypto", "metric": metric, "value": value, "observedAt": at,
                                     "availableAt": at, "unit": unit, "units": unit, "currency": "USD" if unit == "USD" else None,
                                     "sourceUrl": url, "provider": "CoinGecko", "adjustment": "raw", "sampling": "provider snapshot", "frequency": "snapshot"})
    chart = None
    if config.get("history", True):
        days = min(365, max(1, int(config.get("historyDays", 90))))
        chart_url = COINGECKO + "/coins/" + coin_id + "/market_chart?" + urlencode({"vs_currency": "usd", "days": days, "interval": "daily"})
        chart, _, _, _ = _json(network, chart_url, headers)
        if not isinstance(chart, dict):
            raise ConnectorError("CoinGecko price history returned an unexpected structure")
        for key, metric in (("prices", "price_usd"), ("market_caps", "market_cap"), ("total_volumes", "volume_24h")):
            for pair in chart.get(key, [])[:1000]:
                if not isinstance(pair, list) or len(pair) != 2:
                    continue
                value, observed = _number(pair[1]), timestamp(pair[0])
                if value is None or observed is None:
                    continue
                observations.append({"assetId": asset["id"], "assetClass": "crypto", "metric": metric, "value": value, "observedAt": observed,
                                     # Historical API retrieval does not establish when a value
                                     # was first published. Never use it as point-in-time proof.
                                     # The service assigns and preserves first retrievedAt.
                                     # Omitting an invented provider publication timestamp
                                     # also prevents identical re-polls appearing revised.
                                     "unit": "USD", "units": "USD", "currency": "USD", "sourceUrl": chart_url,
                                     "provider": "CoinGecko", "adjustment": "raw", "sampling": "daily provider sample", "frequency": "daily",
                                     "historicalAvailabilityUnknown": True, "availabilityBasis": "First local retrieval; original provider publication time unknown"})
    asset.update({"categories": payload.get("categories", []), "officialLinks": payload.get("links", {}).get("homepage", [])})
    return {"assets": [asset], "documents": [], "observations": observations, "raw": json.dumps({"asset": payload, "history": chart}).encode(),
            "metadata": {**metadata, "provider": "CoinGecko", "historyIsDailySample": bool(chart), "marketDataTimestampAvailable": at is not None,
                         "contractsAreProviderAssertions": True}, "resolvedUrl": resolved}


def _collect_fred_many(source, network):
    """A small configured series bundle shares a bounded collection request budget."""
    config = source.get("config", {})
    configured = config.get("series")
    if not isinstance(configured, list):
        return _collect_fred(source, network)
    series = list(dict.fromkeys(str(item).strip() for item in configured))
    if not series or len(series) > 4:
        raise ConnectorError("A FRED bundle requires one to four series; register additional bundles separately")
    # At most eight provider calls per bundled job: metadata plus one page per
    # series for a four-series bundle. Detail requests remain bounded individually.
    maximum_pages = max(1, 4 // len(series))
    pages = min(maximum_pages, max(1, int(config.get("maxPages", maximum_pages))))
    results = [_collect_fred({**source, "config": {**config, "series": item, "maxPages": pages}}, network) for item in series]
    return {"assets": [item for result in results for item in result["assets"]], "documents": [],
            "observations": [item for result in results for item in result["observations"]],
            "raw": json.dumps({"series": [json.loads(result["raw"]) for result in results]}).encode(),
            "resolvedUrl": FRED_OBSERVATIONS,
            "metadata": {"provider": "FRED / ALFRED", "vintagesPreserved": True, "series": [{"id": series[index], **result["metadata"]} for index, result in enumerate(results)],
                         "truncated": any(result["metadata"]["truncated"] for result in results), "pagesPerSeries": pages}}


def _collect_equity_daily(source, network):
    """Adjusted daily equity prices; identity comes from the SEC catalogue.

    Historical values have unknown original-publication availability and cannot
    become point-in-time backtests merely because the provider supplies a date.
    """
    config = source.get("config", {})
    symbol = str(config.get("ticker", "")).upper()
    asset_id = str(config.get("assetId", ""))
    matches = [asset for asset in _ticker_catalogue(network) if asset.get("ticker") == symbol and asset["id"] == asset_id]
    if len(matches) != 1: raise ConnectorError("Choose an SEC-resolved assetId and its exact ticker before collecting daily prices")
    asset = matches[0]
    secret = os.getenv("ALPHAVANTAGE_API_KEY", "")
    if not secret: raise ConnectorError("Configure ALPHAVANTAGE_API_KEY on the server")
    base = "https://www.alphavantage.co/query"
    # The secret is request-only: stored source URLs and metadata never contain it.
    try:
        overview, _, _, _ = _json(network, base + "?" + urlencode({"function":"OVERVIEW", "symbol":symbol, "apikey":secret}))
        if overview.get("Symbol") != symbol or not overview.get("Currency"):
            raise ConnectorError("Provider identity/currency data are unavailable, rate limited or ambiguous")
        outputsize = config.get("outputsize", "compact")
        if outputsize not in {"compact", "full"}: raise ConnectorError("outputsize must be compact or full")
        payload, _, _, _ = _json(network, base + "?" + urlencode({"function":"TIME_SERIES_DAILY_ADJUSTED", "symbol":symbol, "outputsize":outputsize, "apikey":secret}))
    except Exception:
        raise ConnectorError("Adjusted daily equity collection failed; check provider entitlement, rate limits and server credentials") from None
    if payload.get("Meta Data", {}).get("2. Symbol") != symbol:
        raise ConnectorError("Adjusted daily provider response has no matching symbol; check API entitlement or rate limits")
    series = payload.get("Time Series (Daily)")
    if not isinstance(series, dict): raise ConnectorError("Adjusted daily history is unavailable")
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    observations = []
    source_url = base + "?" + urlencode({"function":"TIME_SERIES_DAILY_ADJUSTED", "symbol":symbol, "outputsize":outputsize})
    for session, values in sorted(series.items())[-1500:]:
        value = _number(values.get("5. adjusted close"))
        if not _date(session) or session >= today or value is None or value <= 0: continue
        observations.append({"assetId":asset_id,"assetClass":"equity","metric":"adjusted_close", "value":value,
            "unit":overview["Currency"],"currency":overview["Currency"], "frequency":"daily", "adjustment":"dividend-adjusted",
            "session":session,"observedAt":timestamp(session + "T23:59:59Z"), "sourceUrl":source_url,
            "historicalAvailabilityUnknown":True,"availabilityBasis":"First local retrieval; original publication time unknown",
            "provider":"Alpha Vantage","adjustedPriceNotExecutable":True})
    return {"assets":[asset],"documents":[],"observations":observations,
            "raw":json.dumps({"overview":overview,"daily":payload}).encode(),"resolvedUrl":source_url,
            "metadata":{"provider":"Alpha Vantage", "backfilled":True,"adjustments":"splits and cash dividends", "sessionsReceived":len(series),"sessionsStored":len(observations)}}


def collect_financial_source(source, network):
    """Return assets/documents/observations/raw using the normal connector convention."""
    kind = source.get("kind")
    if kind == "equity_daily":
        return _collect_equity_daily(source, network)
    if kind == "sec":
        return _collect_sec(source, network)
    if kind in {"fred_vintages", "alfred"}:
        return _collect_fred_many(source, network)
    if kind == "coingecko_asset":
        return _collect_coin(source, network)
    raise ConnectorError("Unsupported financial connector type")

