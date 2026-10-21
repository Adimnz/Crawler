"""Deterministic research calculations. Popularity is never treated as factual proof."""
from __future__ import annotations

from collections import Counter, defaultdict
import datetime as dt
import hashlib
import math
import re
import statistics
from urllib.parse import urlsplit, parse_qsl, urlencode, urlunsplit

HOUR = 3600000
DAY = 24 * HOUR
STOP = set("the and for from that this with into about said says have has had are was were will would could after before amid over under its their they not news update a an of to in on at by as is it el la los las del por para una uno con que des les dans une sur aux est le du un et die der das und von den zu".split())
DOMAINS = {
    "Politics": r"\b(election|congress|parliament|president|legislation|regulat\w*|sanction\w*|tariff\w*|government|pol[ií]tica|gobierno)\b",
    "Crypto": r"\b(crypto\w*|bitcoin|ethereum|blockchain|stablecoin|defi|token\w*|btc|eth|solana)\b",
    "Technology": r"\b(ai|artificial intelligence|chip\w*|semiconductor\w*|technology|software|cyber\w*|nvidia|tecnolog\w*)\b",
    "Economics": r"\b(inflation|employment|gdp|econom\w*|central bank|federal reserve|unemployment|inflaci[oó]n)\b",
    "Science": r"\b(research\w*|scient\w*|study|clinical|vaccine|health|climate|ciencia|salud)\b",
    "Equities": r"\b(stock\w*|shares|earnings|nasdaq|ipo|revenue|merger|acciones|bolsa)\b",
    "Trade": r"\b(trade|shipping|logistics|oil|gas|energy|commodit\w*|export\w*|comercio)\b"
}
REGIONS = {"North America": r"\b(united states|canada|mexico|congress|federal reserve|estados unidos)\b", "Europe": r"\b(europe\w*|ecb|britain|ukraine|german\w*|france|russia\w*)\b", "Asia Pacific": r"\b(china|chinese|japan\w*|india|taiwan|korea|australia|singapore)\b", "Middle East": r"\b(israel|iran|saudi|gaza|lebanon)\b", "Africa": r"\b(africa\w*|nigeria|kenya|egypt|ethiopia)\b", "Latin America": r"\b(brazil|brasil|argentina|chile|colombia|per[uú]|am[eé]rica latina)\b"}
ALIASES = {"nvidia": ("equity:NASDAQ:NVDA", "NVIDIA", "equity"), "microsoft": ("equity:NASDAQ:MSFT", "Microsoft", "equity"), "tesla": ("equity:NASDAQ:TSLA", "Tesla", "equity"), "bitcoin": ("crypto:coingecko:bitcoin", "Bitcoin", "crypto"), "ethereum": ("crypto:coingecko:ethereum", "Ethereum", "crypto"), "federal reserve": ("agency:US:FederalReserve", "Federal Reserve", "agency"), "european central bank": ("agency:EU:ECB", "European Central Bank", "agency")}


def digest(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


def canonical_url(url):
    parsed = urlsplit(str(url))
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        return ""
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parsed.query) if not re.match(r"utm_|fbclid|gclid", k, re.I)))
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, query, ""))


def tokens(text):
    return [word for word in re.findall(r"[^\W_]+", str(text).lower()) if len(word) > 2 and word not in STOP]


def cosine(left, right):
    if isinstance(left, dict):
        dot = sum(value * right.get(key, 0) for key, value in left.items())
        norm = math.sqrt(sum(v * v for v in left.values()) * sum(v * v for v in right.values()))
    else:
        if len(left) != len(right):
            return 0
        dot = sum(a * b for a, b in zip(left, right))
        norm = math.sqrt(sum(a * a for a in left) * sum(b * b for b in right))
    return dot / norm if norm else 0


def text_similarity(left, right):
    return cosine(Counter(tokens(left)), Counter(tokens(right)))


def categories(text):
    return [name for name, pattern in DOMAINS.items() if re.search(pattern, text, re.I)]


def regions(text):
    return [name for name, pattern in REGIONS.items() if re.search(pattern, text, re.I)]


def entities(text, declared=None):
    result = {}
    for entity in declared or []:
        if isinstance(entity, dict) and re.fullmatch(r"[\w-]+:[^\s]+", str(entity.get("id", ""))):
            result[entity["id"]] = {"id": entity["id"], "name": str(entity.get("name", entity["id"]))[:150], "type": entity.get("type", "declared"), "method": "source-declared"}
    for name, (key, label, kind) in ALIASES.items():
        if re.search(r"\b" + re.escape(name) + r"\b", text, re.I):
            result[key] = {"id": key, "name": label, "type": kind, "method": "explicit-name-match"}
    # Bare tickers remain unresolved mentions; they are never merged into a chain or exchange asset.
    for ticker in re.findall(r"\$([A-Z][A-Z0-9]{1,9})\b", text):
        key = "unresolved:ticker:" + ticker
        result[key] = {"id": key, "name": ticker, "type": "unresolved", "method": "ticker-mention"}
    return list(result.values())


def extract_claims(text, document_id, event_id, at):
    sentences = re.split(r"(?<=[.!?。])\s+|\n+", text)
    selected = [sentence.strip() for sentence in sentences if len(sentence.strip()) >= 25][:12]
    return [{"id": "claim-" + digest(document_id + "|" + sentence)[:24], "eventId": event_id, "documentId": document_id, "text": sentence[:1800], "quote": sentence[:1800], "status": "Unverified", "method": "sentence-extraction", "createdAt": at, "updatedAt": at, "highConsequence": bool(re.search(r"\b(fraud|election|war|vaccine|death|bankruptcy|buy|sell|criminal)\b", sentence, re.I)), "reviewRequired": True} for sentence in selected]


def candidate_contradictions(claims):
    results = []
    # Same subject/units, differing numbers or explicit negation. These are review tasks, not verdicts.
    for i, left in enumerate(claims[:120]):
        for right in claims[i + 1:120]:
            if left["documentId"] == right["documentId"]:
                continue
            numbers_left = re.findall(r"\b\d+(?:[.,]\d+)?\s*(?:%|percent|million|billion|trillion|basis points|dollars|euros)\b|\b\d+(?:\.\d+)?%", left["text"], re.I)
            numbers_right = re.findall(r"\b\d+(?:[.,]\d+)?\s*(?:%|percent|million|billion|trillion|basis points|dollars|euros)\b|\b\d+(?:\.\d+)?%", right["text"], re.I)
            a = re.sub(r"\d+(?:[.,]\d+)?", "NUMBER", left["text"])
            b = re.sub(r"\d+(?:[.,]\d+)?", "NUMBER", right["text"])
            overlap = text_similarity(a, b)
            numeric = overlap >= .82 and numbers_left and numbers_right and numbers_left != numbers_right
            negation = overlap >= .88 and bool(re.search(r"\b(not|never|denied|false)\b", left["text"], re.I)) != bool(re.search(r"\b(not|never|denied|false)\b", right["text"], re.I))
            if numeric or negation:
                results.append({"leftClaimId": left["id"], "rightClaimId": right["id"], "documentIds": [left["documentId"], right["documentId"]], "kind": "Possible numerical conflict" if numeric else "Possible negation conflict", "status": "Needs review", "reason": "Check measurement periods, units, attributed speakers, and context before treating this as a contradiction."})
    return results[:30]


def reporting_chains(documents):
    groups = []
    for doc in documents:
        found = [group for group in groups if any(doc.get("family") == other.get("family") or text_similarity(doc["title"], other["title"]) >= .93 or (doc.get("originUrl") and doc["originUrl"] == other.get("originUrl")) for other in group)]
        if not found:
            groups.append([doc])
        else:
            found[0].append(doc)
            for group in found[1:]:
                found[0].extend(group)
                groups.remove(group)
    return groups


def coverage_fraction(spans, start, end):
    intervals = sorted((max(start, span["start"]), min(end, span["end"])) for span in spans if span["end"] > start and span["start"] < end)
    total, boundary = 0, start
    for left, right in intervals:
        total += max(0, right - max(boundary, left))
        boundary = max(boundary, right)
    return min(1, total / max(1, end - start))


def analyze_trend(documents, at, coverage, source_health):
    current = [d for d in documents if at - DAY <= d["publishedAt"] <= at]
    previous = [d for d in documents if at - 2 * DAY <= d["publishedAt"] < at - DAY]
    current_coverage = coverage_fraction(coverage, at - DAY, at)
    prior_coverage = coverage_fraction(coverage, at - 2 * DAY, at - DAY)
    available = current_coverage >= .95 and prior_coverage >= .95 and source_health >= .7
    ratio = len(current) / max(1, len(previous)) if available else None
    buckets = [sum(1 for doc in documents if at - (i + 1) * HOUR <= doc["publishedAt"] < at - i * HOUR) for i in range(24)]
    # Compare the same UTC hour/day-of-week in prior weeks only when collection actually covered it.
    seasonal = []
    for week in range(1, 9):
        right = at - week * 7 * DAY
        if coverage_fraction(coverage, right - HOUR, right) >= .95:
            seasonal.append(sum(1 for doc in documents if right - HOUR <= doc["publishedAt"] < right))
    anomaly = None
    if len(seasonal) >= 3:
        median = statistics.median(seasonal)
        mad = statistics.median(abs(value - median) for value in seasonal)
        anomaly = (buckets[0] - median) / max(1, 1.4826 * mad)
    chains = reporting_chains(current)
    momentum = min(100, round(18 * math.log2(len(current) + 1) + (12 * math.log2(ratio + 1) if ratio is not None else 0)))
    active_days = len({doc["publishedAt"] // DAY for doc in documents if at - 30 * DAY < doc["publishedAt"] <= at})
    lifecycle = "Structural" if active_days >= 14 and len(chains) >= 3 and available else "Cooling" if ratio is not None and ratio < .7 else "Emerging" if ratio is not None and ratio >= 1.5 else "Watch for confirmation" if len(chains) >= 2 else "Early signal"
    return {"momentum": momentum, "currentRecords": len(current), "previousRecords": len(previous) if available else None, "acceleration": ratio, "coverage": round(current_coverage, 3), "baselineCoverage": round(prior_coverage, 3), "baselineAvailable": available, "seasonalSamples": len(seasonal), "robustSeasonalZ": round(anomaly, 3) if anomaly is not None else None, "activeDays": active_days, "candidateChains": len(chains), "lifecycle": lifecycle, "hourly": list(reversed(buckets)), "method": "UTC hourly counts; equal-day baseline requires 95% uptime, a stable source set, and 70% provider availability across both windows; seasonal anomaly uses covered same-weekday/hour samples."}


def quantitative(observations, at, max_age=600000):
    """Provider-specific diagnostics from comparable, then-available observations.

    Statement levels and volumes are never treated as price returns. Revisions
    replace a logical sample rather than increasing its sample count. Metadata
    gaps keep source values visible while withholding derived diagnostics.
    """
    def stamp(value):
        if isinstance(value, bool): return None
        if isinstance(value, (int, float)) and math.isfinite(value): return int(value)
        if isinstance(value, str):
            try:
                parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
                return int(parsed.replace(tzinfo=parsed.tzinfo or dt.timezone.utc).timestamp() * 1000)
            except (ValueError, OverflowError): pass
        return None

    at = stamp(at)
    if at is None: return []
    price_metrics = {"price", "price_usd", "close", "adjusted_close", "total_return_index"}
    adjustments = {"split-adjusted", "dividend-adjusted", "total-return", "not-applicable"}
    fields = ("assetId", "metric", "sourceId", "unit", "currency", "adjustment", "frequency", "marketSession", "sampling", "accountingBasis", "periodType", "concept", "seasonalAdjustment", "timeZone")
    groups = defaultdict(dict)
    for original in observations:
        if not isinstance(original, dict) or not original.get("id") or not original.get("sourceId") or ":" not in str(original.get("assetId", "")) or not original.get("metric"):
            continue
        observed, retrieved = stamp(original.get("observedAt")), stamp(original.get("retrievedAt"))
        if observed is None or retrieved is None or observed > at or retrieved > at: continue
        superseded = stamp(original.get("supersededAt"))
        if original.get("supersededAt") is not None and (superseded is None or superseded <= at): continue
        release_times = [observed]
        malformed = False
        for key in ("availableAt", "filedAt", "releasedAt", "revisionAt", "vintageAt", "vintageDate", "revisionDate", "realtimeStart"):
            if original.get(key) is None: continue
            date = stamp(original[key])
            if date is None or date > at:
                malformed = True
                break
            release_times.append(date)
        if malformed: continue
        if original.get("periodEnd") is not None and (stamp(original["periodEnd"]) is None or stamp(original["periodEnd"]) > at): continue
        try:
            value = float(original.get("value"))
        except (ValueError, TypeError, OverflowError): continue
        if isinstance(original.get("value"), bool) or not math.isfinite(value): continue
        row = {**original, "value": value, "observedAt": observed, "retrievedAt": retrieved,
               "unit": str(original.get("unit") or original.get("units") or ""),
               "currency": str(original.get("currency") or ("USD" if original.get("metric") == "price_usd" else "")).upper(),
               "_available": max(retrieved, *release_times)}
        # Source release/vintage takes precedence when multiple revisions were
        # downloaded together; retrieval time alone cannot identify the latest.
        rank = (max(release_times), retrieved, str(original.get("revisionId", "")), str(original["id"]))
        series = tuple(str(row.get(key) or "") for key in fields)
        period = (str(row.get("periodStart", "")), str(row.get("periodEnd", ""))) if row.get("periodEnd") else (observed,)
        current = groups[series].get(period)
        if current is None or rank > current[0]: groups[series][period] = (rank, row)
    output = []
    for series, samples in groups.items():
        rows = sorted((pair[1] for pair in samples.values() if pair[1].get("canonical", True) and not pair[1].get("removed")), key=lambda row: (stamp(row.get("periodEnd")) or row["observedAt"], row["observedAt"]))
        if not rows: continue
        latest = rows[-1]
        selected = rows[-60:]
        values = [row["value"] for row in selected]
        baseline = values[:-1]
        median = statistics.median(baseline) if baseline else None
        mad = statistics.median(abs(value - median) for value in baseline) if baseline else 0
        age = at - latest["observedAt"]
        warnings = []
        if age > max_age:
            warnings.append("Provider observation is delayed or historical; not a live quote.")
        metadata = bool(latest["unit"] and latest.get("frequency"))
        if latest["metric"] in price_metrics:
            metadata = metadata and bool(latest["currency"] and latest.get("adjustment") in adjustments)
        elif latest.get("periodEnd") and latest.get("periodType") not in {"economic", "instant"}:
            metadata = metadata and bool(latest.get("accountingBasis") and latest.get("periodType"))
        inputs = [{key: row[key] for key in ("id", "sourceId", "value", "unit", "currency", "observedAt", "retrievedAt", "periodStart", "periodEnd") if key in row} | {"availableAt": row["_available"]} for row in selected]
        robust_z, robust_method = None, None
        if metadata and len(baseline) >= 10:
            denominator = max(mad * 1.4826, abs(median) * .001, .000001)
            score = (values[-1] - median) / denominator if all(math.isfinite(value) for value in (median, mad, denominator)) else float("nan")
            if math.isfinite(score):
                robust_z = round(score, 3)
                robust_method = {"formula": "(latest - median(prior samples)) / max(1.4826 * MAD(prior samples), 0.001 * abs(median), 0.000001)",
                                 "unit": "standardized distance", "inputIds": [row["id"] for row in selected], "inputs": inputs,
                                 "baselineMedian": median, "baselineMAD": mad, "baselineSamples": len(baseline), "assessedAt": at}
        daily = latest.get("frequency") == "daily" and latest["metric"] in price_metrics and metadata
        if daily:
            maximum_gap = 26 * HOUR if latest["assetId"].startswith("crypto:") else 4 * DAY
            daily = all(18 * HOUR <= right["observedAt"] - left["observedAt"] <= maximum_gap for left, right in zip(selected, selected[1:]))
        volatility, volatility_method = None, None
        if daily and len(values) >= 11 and all(value > 0 for value in values):
            returns = [math.log(right) - math.log(left) for left, right in zip(values, values[1:])]
            volatility = statistics.pstdev(returns)
            volatility_method = {"formula": "population standard deviation of log(P_t / P_(t-1))", "unit": "log return per observed daily session",
                                 "inputIds": [row["id"] for row in selected], "inputs": inputs, "returnSamples": len(returns),
                                 "period": {"start": selected[0]["observedAt"], "end": latest["observedAt"]}, "annualized": False, "assessedAt": at}
        if not metadata: warnings.append("Comparable units, sampling, or adjustment metadata are missing; derived diagnostics withheld.")
        output.append({"assetId": latest["assetId"], "metric": latest["metric"], "value": latest["value"], "observedAt": latest["observedAt"], "retrievedAt": latest["retrievedAt"],
                       "stale": age > max_age, "ageMs": age, "samples": len(rows), "robustZ": robust_z, "returnVolatility": volatility,
                       "warnings": warnings, "sourceId": latest["sourceId"], "unit": latest["unit"], "currency": latest["currency"],
                       "series": dict(zip(fields, series)), "robustZMethod": robust_method, "returnVolatilityMethod": volatility_method})
    return output


def evaluate_forecasts(forecasts):
    cohorts = defaultdict(list)
    for forecast in forecasts:
        if forecast.get("outcome") in {"Occurred", "Did not occur"} and isinstance(forecast.get("probability"), (float, int)):
            cohorts[forecast.get("cohort", "default")].append(forecast)
    results = []
    for cohort, rows in cohorts.items():
        brier = statistics.mean((row["probability"] - (row["outcome"] == "Occurred")) ** 2 for row in rows)
        rate = statistics.mean(row["outcome"] == "Occurred" for row in rows)
        benchmark = statistics.mean((rate - (row["outcome"] == "Occurred")) ** 2 for row in rows)
        bins = []
        for slot in range(5):
            selected = [row for row in rows if min(4, int(row["probability"] * 5)) == slot]
            if selected:
                bins.append({"lower": slot / 5, "upper": (slot + 1) / 5, "n": len(selected), "meanForecast": statistics.mean(row["probability"] for row in selected), "observedRate": statistics.mean(row["outcome"] == "Occurred" for row in selected)})
        results.append({"cohort": cohort, "samples": len(rows), "brierScore": brier, "baseRateBrier": benchmark, "reliabilityBins": bins, "calibrated": False, "note": "Descriptive evaluation, not prospective calibration. Held-out comparable outcomes and sufficient bin counts are required before publishing predictive probabilities."})
    return results
