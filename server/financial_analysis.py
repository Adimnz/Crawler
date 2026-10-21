"""Evidence-bound financial calculations; no estimates or model-produced numbers.

Observation contract extends the service's observations with ``unit``, ``currency``,
``accountingBasis``, ``periodStart``/``periodEnd`` and ``periodType`` for statements.
Daily prices also declare ``frequency='daily'`` and an explicit ``adjustment``.
Revised records may share an ID: availability gates historical selection, then known
source release/revision chronology determines the newest available revision. Fetch
order never overrides an explicit filing date. Supply original revisions for replay.
"""
from __future__ import annotations

from collections import defaultdict
import datetime as dt
import hashlib
import math
import statistics
import time

DAY = 86400000
PRICE_METRICS = {"price", "price_usd", "close", "adjusted_close", "total_return_index"}
DURATION_TYPES = {"annual", "quarterly", "year-to-date"}
ADJUSTMENTS = {"split-adjusted", "dividend-adjusted", "total-return", "not-applicable", "raw"}
FINANCIAL_METRICS = {"revenue", "gross_profit", "operating_income", "net_income", "operating_cash_flow", "capital_expenditure", "assets", "liabilities", "current_assets", "current_liabilities", "cash", "equity", "debt", "total_debt", "debt_current", "debt_noncurrent", "eps_diluted", "shares_outstanding"}


def _timestamp(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(value):
        return int(value)
    if isinstance(value, str):
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
            return int(parsed.replace(tzinfo=parsed.tzinfo or dt.timezone.utc).timestamp() * 1000)
        except (ValueError, OverflowError):
            return None
    return None


def _now(at):
    value = _timestamp(at) if at is not None else int(time.time() * 1000)
    if value is None:
        raise ValueError("as-of time must be a UTC timestamp or ISO date")
    return value


def _period_type(row):
    return {"quarter": "quarterly", "year": "annual", "ytd": "year-to-date"}.get(str(row.get("periodType", "")).lower(), str(row.get("periodType", "")).lower())


def _currency(row):
    # The explicit metric name itself specifies the currency for legacy quotes.
    return str(row.get("currency") or ("USD" if row.get("metric") == "price_usd" else "")).upper()


SOURCE_CHRONOLOGY_KEYS = ("revisionAt", "vintageAt", "releasedAt", "filedAt", "revisionDate", "vintageDate", "filedDate", "releaseDate")


def _source_date(value):
    parsed = _timestamp(value)
    # Date-only releases cannot establish intraday availability. Use the end of
    # that UTC day, as the SEC/FRED connectors do when exact times are absent.
    if parsed is not None and isinstance(value, str) and len(value) == 10:
        parsed += DAY - 1
    return parsed


def _availability(row):
    dates = [_timestamp(row.get("retrievedAt"))]
    for key in ("availableAt", *SOURCE_CHRONOLOGY_KEYS):
        if row.get(key) is not None:
            date = _source_date(row[key])
            if date is None:
                return None
            dates.append(date)
    return max(dates) if all(value is not None for value in dates) else None


def _revision_rank(row):
    """Order available revisions by source chronology, with fetches as ties only.

    ``availableAt`` is a fallback when a provider supplies no explicit release or
    revision date. It can reflect a conservative local availability boundary, so
    it must not supersede an actual filed/revised timestamp merely because an old
    filing was fetched later. Without either, the observed period plus retrieval
    order is the only chronology present in the source contract.
    """
    dates = [_source_date(row[key]) for key in SOURCE_CHRONOLOGY_KEYS if row.get(key) is not None]
    chronology = max(dates) if dates else _source_date(row.get("availableAt"))
    if chronology is None:
        chronology = row["observedAt"]
    # A shared dataset vintage must not mask distinct filing/revision dates.
    # Compare remaining source chronology before falling back to fetch order.
    details = tuple(_source_date(row[key]) if row.get(key) is not None else -1 for key in SOURCE_CHRONOLOGY_KEYS)
    return (chronology, details, row["_available"], str(row.get("revisionId", "")), str(row["id"]))


def _prepare(observations, at):
    rows, exclusions = {}, []
    for original in observations:
        row = dict(original)
        reason = None
        observed = _timestamp(row.get("observedAt"))
        available = _availability(row)
        try:
            value = float(row.get("value"))
        except (ValueError, TypeError, OverflowError):
            value = float("nan")
        if not row.get("id") or not row.get("sourceId") or ":" not in str(row.get("assetId", "")):
            reason = "Missing observation identifier, source, or namespaced instrument identity."
        elif isinstance(row.get("value"), bool) or not math.isfinite(value):
            reason = "Non-finite or non-numeric source value."
        elif observed is None or available is None:
            reason = "Missing or invalid observation/availability timestamps."
        elif observed > at or available > at:
            reason = "Observation or revision was not available at the assessment date."
        elif _timestamp(row.get("periodEnd")) is not None and _timestamp(row.get("periodEnd")) > at:
            reason = "The reporting period had not ended at the assessment date."
        elif not row.get("canonical", True) or row.get("removed"):
            reason = "Observation was removed or is non-canonical."
        if reason:
            exclusions.append({"inputId": row.get("id"), "reason": reason})
            continue
        row.update(value=value, observedAt=observed, _available=available)
        row["_start"], row["_end"] = _timestamp(row.get("periodStart")), _timestamp(row.get("periodEnd"))
        period_key = (row["_start"], row["_end"], _period_type(row)) if row["_end"] is not None else (observed,)
        key = (row["assetId"], row.get("metric"), row["sourceId"], str(row.get("unit", "")), _currency(row), row.get("accountingBasis"), row.get("adjustment"), row.get("concept"), period_key)
        current = rows.get(key)
        if current is None or _revision_rank(row) > _revision_rank(current):
            rows[key] = row
    return list(rows.values()), exclusions


def _input(row):
    keys = ("id", "assetId", "sourceId", "metric", "value", "unit", "currency", "observedAt", "retrievedAt", "availableAt", *SOURCE_CHRONOLOGY_KEYS, "revisionId", "periodStart", "periodEnd", "periodType", "accountingBasis", "adjustment", "session", "frequency", "sourceUrl", "accessionNumber", "concept")
    return {key: row[key] for key in keys if key in row}


def _stale(row, at):
    configured = row.get("freshnessMs")
    if isinstance(configured, (int, float)) and not isinstance(configured, bool) and math.isfinite(configured) and configured > 0:
        maximum = configured
    elif row.get("metric") in PRICE_METRICS or row.get("metric") == "market_cap":
        maximum = 10 * 60000
    else:
        annual = _period_type(row) == "annual" or (_period_type(row) == "instant" and row.get("fiscalPeriod") == "FY")
        maximum = (450 if annual else 150) * DAY
    return at - (row.get("_end") or row["observedAt"]) > maximum


def _metric(name, value, unit, formula, inputs, at, period=None, limitations=None):
    if not math.isfinite(value):
        return None
    unique = {str(row["id"]) + "|" + str(row["_available"]): row for row in inputs}
    records = list(unique.values())
    signature = "|".join([name, *(str(row["id"]) + ":" + str(row["_available"]) for row in records)])
    heads = {}
    for row in records:
        key = row["assetId"], row.get("metric")
        if key not in heads or row["observedAt"] > heads[key]["observedAt"]:
            heads[key] = row
    stale = any(_stale(row, at) for row in heads.values())
    notes = list(limitations or [])
    if any(str(row["assetId"]).startswith("crypto:") and row.get("adjustment") == "raw" for row in records):
        notes.append("Uses unadjusted provider crypto prices; token redenominations, distributions, and supply events are not normalized. This is a nominal price comparison, not a total-return calculation.")
    if stale:
        notes.append("At least one current input is stale under its declared or default freshness window.")
    return {"id": "calculation-" + hashlib.sha256(signature.encode()).hexdigest()[:24], "metric": name, "assetId": records[0]["assetId"], "value": value, "unit": unit,
            "formula": formula, "inputIds": list(dict.fromkeys(row["id"] for row in records)), "inputs": [_input(row) for row in records],
            "period": period or {"start": min(row.get("_start") or row["observedAt"] for row in records), "end": max(row.get("_end") or row["observedAt"] for row in records)},
            "observedAt": max(row["observedAt"] for row in records), "retrievedAt": max(row["_available"] for row in records), "asOf": at,
            "stale": stale, "limitations": notes, "method": "deterministic-application-calculation"}


def _financial_context(row):
    return (row["assetId"], row["sourceId"], row.get("unit"), _currency(row), row.get("accountingBasis"), row.get("_start"), row.get("_end"), _period_type(row))


def _financial_valid(row):
    period = _period_type(row)
    return bool(row.get("unit") and _currency(row) and row.get("accountingBasis") and row.get("_end") is not None and
                (period == "instant" or (period in DURATION_TYPES and row.get("_start") is not None and row["_end"] > row["_start"])))


def _pick(rows, metric):
    selected = [row for row in rows if row.get("metric") == metric]
    if not selected:
        return None
    if len({row["value"] for row in selected}) > 1:
        return None
    return max(selected, key=lambda row: row["_available"])


def _financial_groups(rows):
    groups = defaultdict(list)
    for row in rows:
        if row.get("metric") in FINANCIAL_METRICS and _financial_valid(row):
            groups[_financial_context(row)].append(row)
    return groups


def _prices(rows, at):
    selected = [row for row in rows if row.get("metric") in PRICE_METRICS and row["value"] > 0]
    if not selected:
        return [], "No positive, source-backed price observations."
    if len({row["assetId"] for row in selected}) != 1:
        return [], "Pass exactly one resolved instrument per price history."
    signatures = defaultdict(list)
    for row in selected:
        adjustment = str(row.get("adjustment", "")).lower()
        if adjustment not in ADJUSTMENTS or not _currency(row) or not row.get("unit") or row.get("frequency") != "daily":
            continue
        if adjustment in {"not-applicable", "raw"} and not str(row["assetId"]).startswith("crypto:"):
            continue
        signatures[(row["sourceId"], row.get("metric"), row["unit"], _currency(row), adjustment)].append(row)
    if not signatures:
        return [], "Comparable daily history requires unit, currency, frequency='daily', and an explicit price adjustment methodology."
    # Never silently combine providers or differently adjusted histories.
    history = max(signatures.values(), key=lambda group: (max(row["observedAt"] for row in group), len(group)))
    sessions = {}
    for row in history:
        session = row.get("session") or row.get("sessionDate") or dt.datetime.fromtimestamp(row["observedAt"] / 1000, dt.timezone.utc).date().isoformat()
        try:
            session = dt.date.fromisoformat(str(session)[:10]).isoformat()
        except ValueError:
            continue
        current = sessions.get(session)
        if current is None or (row["observedAt"], row["_available"]) > (current["observedAt"], current["_available"]):
            sessions[session] = {**row, "_session": session}
    return sorted(sessions.values(), key=lambda row: row["_session"]), None


def _daily_gap(left, right):
    """Conservative UTC interval bounds; longer missing stretches are withheld."""
    gap = (right["observedAt"] - left["observedAt"]) / DAY
    maximum = 1.25 if str(left["assetId"]).startswith("crypto:") else 4.25
    return .75 <= gap <= maximum


def build_financial_metrics(observations, at=None):
    """Return calculable metrics, their exact inputs, and explicit missing-data reasons.

    Ratios use the same provider, accounting basis, currency, units and reporting
    period. Growth uses reported comparable periods, never estimated interim data.
    ``Data unavailable`` is a status, never represented by a made-up zero.
    """
    at = _now(at)
    rows, exclusions = _prepare(observations, at)
    output, missing = [], []
    assets = sorted({row["assetId"] for row in rows})

    def add(name, value, unit, formula, inputs, period=None, limitations=None):
        result = _metric(name, value, unit, formula, inputs, at, period, limitations)
        if result:
            output.append(result)

    def unavailable(asset, metric, reason):
        missing.append({"assetId": asset, "metric": metric, "status": "Data unavailable", "reason": reason})

    for asset in assets:
        asset_rows = [row for row in rows if row["assetId"] == asset]
        # A total-return index supports comparative returns, but its index level
        # is not an instrument's cash price.
        prices = [row for row in asset_rows if row.get("metric") in PRICE_METRICS - {"total_return_index"} and row["value"] > 0]
        if prices:
            latest = max(prices, key=lambda row: (row["observedAt"], row["_available"]))
            add("latest_price", latest["value"], latest.get("unit") or _currency(latest) or "source unit unavailable", "Latest available provider price; no transformation", [latest], limitations=["A provider observation is not a verified live executable quote."])
        else:
            unavailable(asset, "latest_price", "No positive source-backed price observation.")
        financial = _financial_groups(asset_rows)
        for context, group in financial.items():
            period_type = context[-1]
            for name, numerator, denominator in (("gross_margin_percent", "gross_profit", "revenue"), ("operating_margin_percent", "operating_income", "revenue"), ("net_margin_percent", "net_income", "revenue"), ("current_ratio", "current_assets", "current_liabilities")):
                if (name == "current_ratio") != (period_type == "instant"):
                    continue
                left, right = _pick(group, numerator), _pick(group, denominator)
                if left and right and right["value"] > 0:
                    percent = name.endswith("percent")
                    add(name, left["value"] / right["value"] * (100 if percent else 1), "%" if percent else "ratio", f"{numerator} / {denominator}" + (" * 100" if percent else ""), [left, right])
            if period_type in DURATION_TYPES:
                cashflow, capex = _pick(group, "operating_cash_flow"), _pick(group, "capital_expenditure")
                if cashflow and capex and capex["value"] >= 0:
                    add("free_cash_flow", cashflow["value"] - capex["value"], context[2], "operating_cash_flow - capital_expenditure (positive cash outflow convention)", [cashflow, capex], limitations=["Free cash flow uses this stated formula; issuer definitions may differ."])
            if period_type == "instant":
                debt = _pick(group, "total_debt") or _pick(group, "debt")
                debt_inputs = [debt] if debt else [_pick(group, "debt_current"), _pick(group, "debt_noncurrent")]
                if all(row is not None for row in debt_inputs):
                    # Ordinary addition can represent overflow as infinity, which
                    # the result contract rejects, instead of crashing a worker.
                    debt_value = sum(row["value"] for row in debt_inputs)
                    assets_row, cash_row = _pick(group, "assets"), _pick(group, "cash")
                    if debt_value >= 0 and assets_row and assets_row["value"] > 0:
                        add("debt_to_assets", debt_value / assets_row["value"], "ratio", "(total_debt or debt_current + debt_noncurrent) / assets", [*debt_inputs, assets_row])
                    if debt_value >= 0 and cash_row and cash_row["value"] >= 0:
                        add("net_debt", debt_value - cash_row["value"], context[2], "(total_debt or debt_current + debt_noncurrent) - cash", [*debt_inputs, cash_row])

        # Compare the latest reported period with a genuinely comparable earlier
        # period; the source concept cannot change silently between periods.
        growth_groups = defaultdict(list)
        for row in asset_rows:
            if row.get("metric") in FINANCIAL_METRICS and _financial_valid(row) and _period_type(row) in {"annual", "quarterly"}:
                growth_groups[(row["metric"], row["sourceId"], row.get("unit"), _currency(row), row.get("accountingBasis"), _period_type(row), row.get("concept"))].append(row)
        for key, group in growth_groups.items():
            current = max(group, key=lambda row: (row["_end"], row["_available"]))
            duration = current["_end"] - current["_start"]
            for interval, lower, upper in (("yoy", 330, 400), ("qoq", 70, 110)):
                if interval == "qoq" and key[5] != "quarterly":
                    continue
                prior = [row for row in group if lower * DAY <= current["_end"] - row["_end"] <= upper * DAY and row["_end"] < current["_start"] and abs((row["_end"] - row["_start"]) - duration) <= max(7 * DAY, duration * .12) and row["value"] > 0]
                if prior:
                    previous = max(prior, key=lambda row: (row["_end"], row["_available"]))
                    add(key[0] + "_growth_" + interval + "_percent", (current["value"] / previous["value"] - 1) * 100, "%", "(current reported value / comparable previous reported value - 1) * 100", [previous, current], limitations=["Reported-period comparison; no forecast or causal inference."])

        # Explicit market capitalization is required: multiplying an old share
        # count by a current quote would assert an unverified current share count.
        market_caps = [row for row in asset_rows if row.get("metric") == "market_cap" and row["value"] > 0 and row.get("unit") and _currency(row)]
        if market_caps:
            cap = max(market_caps, key=lambda row: (row["observedAt"], row["_available"]))
            for metric, denominator, kind in (("price_to_reported_annual_earnings", "net_income", "annual"), ("price_to_reported_annual_sales", "revenue", "annual"), ("price_to_reported_book", "equity", "instant")):
                candidates = [row for row in asset_rows if row.get("metric") == denominator and _financial_valid(row) and _period_type(row) == kind and row["value"] > 0 and row["_end"] <= cap["observedAt"] and row.get("unit") == cap.get("unit") and _currency(row) == _currency(cap)]
                if candidates:
                    latest_end = max(row["_end"] for row in candidates)
                    candidates = [row for row in candidates if row["_end"] == latest_end]
                    if len({row["value"] for row in candidates}) == 1:
                        denominator_row = max(candidates, key=lambda row: row["_available"])
                        add(metric, cap["value"] / denominator_row["value"], "ratio", "latest sourced market_cap / " + denominator + " for stated reported period", [cap, denominator_row], limitations=["Uses the stated reported period, not estimated trailing or forward results."])

        history, reason = _prices(asset_rows, at)
        if len(history) >= 2:
            first, last = history[0], history[-1]
            add("observed_window_return_percent", (last["value"] / first["value"] - 1) * 100, "%", "(last price / first price - 1) * 100; adjustment methodology recorded in inputs", [first, last], limitations=["Return covers only the stated available history; treatment of dividends follows the source adjustment."])
        else:
            unavailable(asset, "observed_window_return_percent", reason or "At least two comparable daily sessions are required.")
        if len(history) >= 21:
            log_returns = [math.log(right["value"]) - math.log(left["value"]) for left, right in zip(history, history[1:])]
            # Reject histories with missing long stretches rather than annualize
            # multi-week returns as though they were consecutive daily returns.
            crypto = asset.startswith("crypto:")
            valid_gaps = all(_daily_gap(left, right) for left, right in zip(history, history[1:]))
            if valid_gaps:
                annual_sessions = 365 if crypto else 252
                add("annualized_realized_volatility_percent", statistics.stdev(log_returns) * math.sqrt(annual_sessions) * 100, "%", f"sample_stdev(log(P[t]/P[t-1])) * sqrt({annual_sessions}) * 100", history, limitations=[f"Historical sample volatility; {annual_sessions} daily sessions per year is a disclosed annualization convention, not a prediction."])
            else:
                unavailable(asset, "annualized_realized_volatility_percent", "Daily history has gaps incompatible with the stated annualization frequency.")
        else:
            unavailable(asset, "annualized_realized_volatility_percent", "At least 21 comparable daily prices (20 returns) are required.")
        produced = {metric["metric"] for metric in output if metric["assetId"] == asset}
        for expected in ("net_margin_percent", "free_cash_flow", "debt_to_assets", "current_ratio", "revenue_growth_yoy_percent", "price_to_reported_annual_earnings"):
            if expected not in produced:
                unavailable(asset, expected, "Required same-period, unit, currency, accounting-basis and source inputs are missing, conflicting, or not comparable.")
    return {"asOf": at, "metrics": output, "missingData": missing, "exclusions": exclusions, "status": "Calculated" if output else "Data unavailable"}


def _aligned_returns(asset_observations, benchmark_observations, at):
    asset, excluded_asset = _prepare(asset_observations, at)
    benchmark, excluded_benchmark = _prepare(benchmark_observations, at)
    asset, error_a = _prices(asset, at)
    benchmark, error_b = _prices(benchmark, at)
    exclusions = excluded_asset + excluded_benchmark
    if error_a or error_b or not asset or not benchmark:
        return [], error_a or error_b or "Comparable price histories are unavailable.", exclusions
    if asset[0]["assetId"] == benchmark[0]["assetId"]:
        return [], "Asset and benchmark must be different resolved instruments.", exclusions
    if _currency(asset[0]) != _currency(benchmark[0]) or asset[0].get("adjustment") != benchmark[0].get("adjustment"):
        return [], "Asset and benchmark require the same currency and compatible adjustment methodologies.", exclusions
    left = {(a["_session"], b["_session"]): (a, b) for a, b in zip(asset, asset[1:])}
    right = {(a["_session"], b["_session"]): (a, b) for a, b in zip(benchmark, benchmark[1:])}
    output = []
    for start, end in sorted(left.keys() & right.keys()):
        a, b = left[(start, end)]
        c, d = right[(start, end)]
        if not _daily_gap(a, b) or not _daily_gap(c, d):
            continue
        asset_return, benchmark_return = b["value"] / a["value"] - 1, d["value"] / c["value"] - 1
        if not math.isfinite(asset_return) or not math.isfinite(benchmark_return):
            return [], "Source values yield an unrepresentable return; calculation withheld.", exclusions
        output.append({"start": start, "end": end, "assetReturn": asset_return, "benchmarkReturn": benchmark_return, "assetStart": a, "assetEnd": b, "benchmarkStart": c, "benchmarkEnd": d})
    return output, None, exclusions


def correlate_market_returns(asset_observations, benchmark_observations, at=None, min_samples=20):
    """Pearson correlation on returns with exactly aligned start/end sessions."""
    at = _now(at)
    minimum = max(20, int(min_samples))
    aligned, error, exclusions = _aligned_returns(asset_observations, benchmark_observations, at)
    result = {"asOf": at, "status": "Data unavailable", "metrics": [], "samples": len(aligned), "exclusions": exclusions,
              "limitations": ["Observed correlation does not establish causation or predict future co-movement."]}
    if error or len(aligned) < minimum:
        return {**result, "reason": error or f"At least {minimum} aligned daily returns are required."}
    a = [row["assetReturn"] for row in aligned]
    b = [row["benchmarkReturn"] for row in aligned]
    if statistics.pstdev(a) == 0 or statistics.pstdev(b) == 0:
        return {**result, "reason": "Correlation is undefined for a constant return series."}
    value = statistics.correlation(a, b)
    inputs = [row[key] for row in aligned for key in ("assetStart", "assetEnd", "benchmarkStart", "benchmarkEnd")]
    metric = _metric("observed_return_correlation", value, "correlation", "Pearson correlation of simple returns for identical source session pairs", inputs, at, {"start": aligned[0]["start"], "end": aligned[-1]["end"]}, result["limitations"])
    metric["benchmarkId"] = aligned[0]["benchmarkStart"]["assetId"]
    return {**result, "status": "Calculated", "metrics": [metric], "sessionPairs": [{"start": row["start"], "end": row["end"]} for row in aligned]}


def event_study(asset_observations, benchmark_observations, event_at, at=None, before=5, after=5):
    """Descriptive before/after benchmark comparison, with no causal attribution.

    The first daily source observation at/after the event starts the event
    window. ``after`` includes that session; ``before`` counts earlier returns.
    Matching source session dates are required, so partial cross-market windows
    are withheld. The caller must supply the evidenced event timestamp.
    """
    at, event = _now(at), _timestamp(event_at)
    before, after = max(1, int(before)), max(1, int(after))
    result = {"asOf": at, "eventAt": event, "status": "Data unavailable", "metrics": [], "limitations": ["Observed changes following an announcement do not establish that the announcement caused them."]}
    if event is None or event > at:
        return {**result, "reason": "An evidenced event timestamp available at the assessment date is required."}
    aligned, error, exclusions = _aligned_returns(asset_observations, benchmark_observations, at)
    result["exclusions"] = exclusions
    if error:
        return {**result, "reason": error}
    first = next((index for index, row in enumerate(aligned) if row["assetEnd"]["observedAt"] >= event), None)
    if first is None or first < before or len(aligned) - first < after:
        return {**result, "reason": "Insufficient aligned pre-event and post-event daily sessions."}
    pre, post = aligned[first - before:first], aligned[first:first + after]
    selected = pre + post
    # Missing paired sessions are not bridged into an apparently complete study.
    if any(left["end"] != right["start"] for left, right in zip(selected, selected[1:])):
        return {**result, "reason": "The event window contains unaligned or missing source sessions."}
    output = []
    for label, window in (("pre_event", pre), ("event_window", post)):
        first, last = window[0], window[-1]
        asset_return = last["assetEnd"]["value"] / first["assetStart"]["value"] - 1
        benchmark_return = last["benchmarkEnd"]["value"] / first["benchmarkStart"]["value"] - 1
        inputs = [row[key] for row in window for key in ("assetStart", "assetEnd", "benchmarkStart", "benchmarkEnd")]
        period = {"start": first["start"], "end": last["end"], "sessions": len(window)}
        for metric, value, unit, formula in ((label + "_return_percent", asset_return * 100, "%", "(last asset price / first asset price - 1) * 100; adjustment methodology recorded in inputs"),
                                              (label + "_benchmark_return_percent", benchmark_return * 100, "%", "(last benchmark price / first benchmark price - 1) * 100; adjustment methodology recorded in inputs"),
                                              (label + "_abnormal_return_percentage_points", (asset_return - benchmark_return) * 100, "percentage points", "observed asset window return minus benchmark window return; market-adjusted descriptive comparison"),
                                              (label + "_cumulative_abnormal_return_percentage_points", math.fsum(row["assetReturn"] - row["benchmarkReturn"] for row in window) * 100, "percentage points", "sum of aligned daily(asset simple return - benchmark simple return) * 100")):
            calculation = _metric(metric, value, unit, formula, inputs, at, period, result["limitations"])
            if calculation:
                calculation["benchmarkId"] = first["benchmarkStart"]["assetId"]
                output.append(calculation)
    return {**result, "status": "Calculated", "metrics": output, "method": "Market-adjusted descriptive event comparison; no fitted expected-return model or causal conclusion."}


def evaluate_threshold_history(observations, threshold_percent, at=None, outcome_sessions=5, min_samples=20):
    """Replay an explicit absolute daily-price-change threshold on observed data.

    Every crossing retains its measured subsequent source sessions when those
    sessions were already available at ``at``. Outcomes may overlap and are not
    independent trials. No success probability or future return is estimated.
    """
    at = _now(at)
    if isinstance(threshold_percent, bool):
        raise ValueError("threshold_percent must be a positive finite number")
    threshold = float(threshold_percent)
    if not math.isfinite(threshold) or threshold <= 0:
        raise ValueError("threshold_percent must be a positive finite number")
    horizon, minimum = int(outcome_sessions), max(20, int(min_samples))
    if not 1 <= horizon <= 252:
        raise ValueError("outcome_sessions must be between 1 and 252")
    prepared, exclusions = _prepare(observations, at)
    history, error = _prices(prepared, at)
    result = {"asOf": at, "thresholdPercent": threshold, "outcomeSessions": horizon, "status": "Data unavailable",
              "evaluatedIntervals": max(0, len(history) - 1), "crossings": [], "exclusions": exclusions,
              "method": "Historical replay of absolute consecutive daily source-price change against the configured threshold.",
              "limitations": ["Historical threshold crossings and measured subsequent returns do not estimate future outcomes or establish causation.", "Outcome windows can overlap; observations are not independent trials.", "Evaluation covers only retrieved provider sessions and is not a completeness or investment-performance claim."]}
    if error or len(history) < minimum + 1:
        return {**result, "reason": error or f"At least {minimum + 1} comparable daily price observations are required."}
    crossings, evaluated = [], 0
    for index, (previous, current) in enumerate(zip(history, history[1:]), 1):
        if not _daily_gap(previous, current):
            continue
        evaluated += 1
        change = (current["value"] / previous["value"] - 1) * 100
        if not math.isfinite(change) or abs(change) < threshold:
            continue
        measured = _metric("historical_daily_threshold_crossing_percent", change, "%", "(current source-session price / preceding source-session price - 1) * 100", [previous, current], at,
                           {"start": previous["_session"], "end": current["_session"]})
        crossing = {"observedAt": current["observedAt"], "session": current["_session"], "measurement": measured,
                    "outcomeStatus": "Data unavailable", "outcome": None}
        if index + horizon < len(history) and all(_daily_gap(left, right) for left, right in zip(history[index:index + horizon], history[index + 1:index + horizon + 1])):
            final = history[index + horizon]
            outcome = _metric("historical_observed_subsequent_return_percent", (final["value"] / current["value"] - 1) * 100, "%",
                              "(price after the stated number of retrieved source sessions / crossing-session price - 1) * 100", [current, final], at,
                              {"start": current["_session"], "end": final["_session"], "sessions": horizon}, result["limitations"])
            if outcome:
                crossing.update(outcomeStatus="Observed", outcome=outcome)
        crossings.append(crossing)
    return {**result, "status": "Calculated", "evaluatedIntervals": evaluated, "crossings": crossings, "crossingCount": len(crossings),
            "samplesWithObservedOutcome": sum(row["outcomeStatus"] == "Observed" for row in crossings),
            "period": {"start": history[0]["_session"], "end": history[-1]["_session"]}}
