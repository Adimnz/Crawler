"""Deterministic financial evidence, period comparability and replay checks."""
import datetime as dt
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.financial_analysis import build_financial_metrics, correlate_market_returns, event_study, evaluate_threshold_history

DAY = 86400000


def date(value):
    return int(dt.datetime.fromisoformat(value).replace(tzinfo=dt.timezone.utc).timestamp() * 1000)


AS_OF = date("2026-04-15")


def observation(metric, value, **values):
    return {"id": metric + "-" + str(value), "assetId": "equity:NASDAQ:TEST", "sourceId": "filings", "metric": metric, "value": value, "unit": "USD", "currency": "USD", "accountingBasis": "us-gaap", "periodType": "annual", "periodStart": "2025-01-01", "periodEnd": "2025-12-31", "observedAt": date("2025-12-31"), "retrievedAt": date("2026-02-15"), "availableAt": date("2026-02-14"), **values}


def metrics(rows, at=AS_OF):
    return {row["metric"]: row for row in build_financial_metrics(rows, at)["metrics"]}


def prices(asset="equity:NASDAQ:TEST", count=40, multiplier=1, **overrides):
    output = []
    # Deterministically varied daily observations, including declared session dates.
    for index in range(count):
        timestamp = AS_OF - (count - index - 1) * DAY
        output.append({"id": asset + "-" + str(index), "assetId": asset, "sourceId": "licensed-market", "metric": "adjusted_close", "value": (100 + index + (index % 4) * 2) * multiplier, "observedAt": timestamp, "retrievedAt": timestamp, "unit": "USD/share", "currency": "USD", "frequency": "daily", "session": dt.datetime.fromtimestamp(timestamp / 1000, dt.timezone.utc).date().isoformat(), "adjustment": "split-adjusted", **overrides})
    return output


class FinancialAnalysisTests(unittest.TestCase):
    def test_statement_metrics_preserve_formulas_periods_and_exact_inputs(self):
        rows = [observation("revenue", 100), observation("net_income", 20), observation("operating_cash_flow", 30), observation("capital_expenditure", 8)]
        values = metrics(rows)
        self.assertEqual(values["net_margin_percent"]["value"], 20)
        self.assertEqual(values["free_cash_flow"]["value"], 22)
        self.assertEqual(values["free_cash_flow"]["unit"], "USD")
        self.assertEqual(values["free_cash_flow"]["inputIds"], ["operating_cash_flow-30", "capital_expenditure-8"])
        self.assertEqual(values["net_margin_percent"]["inputs"][0]["sourceId"], "filings")
        self.assertEqual(values["net_margin_percent"]["period"]["end"], date("2025-12-31"))
        self.assertFalse(values["net_margin_percent"]["stale"])

    def test_ratios_require_matching_period_currency_unit_accounting_and_source(self):
        for changed in ({"currency": "EUR"}, {"unit": "USD thousands"}, {"accountingBasis": "ifrs"}, {"periodStart": "2025-04-01"}, {"sourceId": "other-provider"}):
            with self.subTest(changed=changed):
                values = metrics([observation("revenue", 100), observation("net_income", 20, **changed)])
                self.assertNotIn("net_margin_percent", values)
        no_basis = observation("net_income", 20)
        no_basis.pop("accountingBasis")
        self.assertNotIn("net_margin_percent", metrics([observation("revenue", 100), no_basis]))

    def test_nonpositive_denominator_and_unknown_capex_sign_are_withheld(self):
        values = metrics([observation("revenue", 0), observation("net_income", 20), observation("operating_cash_flow", 30), observation("capital_expenditure", -8)])
        self.assertNotIn("net_margin_percent", values)
        self.assertNotIn("free_cash_flow", values)

    def test_debt_components_current_ratio_and_net_debt_require_same_instant(self):
        instant = {"periodType": "instant", "periodStart": None}
        values = metrics([observation(metric, value, **instant) for metric, value in (("assets", 100), ("debt_current", 10), ("debt_noncurrent", 20), ("cash", 8), ("current_assets", 40), ("current_liabilities", 20))])
        self.assertAlmostEqual(values["debt_to_assets"]["value"], .3)
        self.assertEqual(values["net_debt"]["value"], 22)
        self.assertEqual(values["current_ratio"]["value"], 2)

    def test_reported_growth_rejects_incomparable_interim_periods(self):
        current = observation("revenue", 120)
        previous = observation("revenue", 100, id="revenue-prior", periodStart="2024-01-01", periodEnd="2024-12-31", observedAt=date("2024-12-31"), retrievedAt=date("2025-02-15"), availableAt=date("2025-02-14"))
        self.assertAlmostEqual(metrics([current, previous])["revenue_growth_yoy_percent"]["value"], 20)
        self.assertNotIn("revenue_growth_yoy_percent", metrics([current, {**previous, "periodType": "year-to-date", "periodStart": "2024-07-01"}]))
        self.assertNotIn("revenue_growth_yoy_percent", metrics([current, {**previous, "value": -100}]))

    def test_replay_uses_available_revision_and_excludes_future_release(self):
        original = observation("revenue", 100, id="revenue-versioned")
        revised = {**original, "value": 80, "retrievedAt": AS_OF + DAY, "availableAt": AS_OF + DAY}
        earnings = observation("net_income", 20)
        self.assertEqual(metrics([original, revised, earnings])["net_margin_percent"]["value"], 20)
        future = metrics([original, revised, earnings], AS_OF + 2 * DAY)
        self.assertEqual(future["net_margin_percent"]["value"], 25)
        unpublished = {**original, "availableAt": AS_OF + DAY}
        self.assertNotIn("net_margin_percent", metrics([unpublished, earnings]))

    def test_source_filing_chronology_wins_over_reversed_or_equal_retrieval_order(self):
        older = observation("revenue", 100, id="z-old-filing", concept="Revenue", filedAt=date("2026-02-14"), availableAt=date("2026-02-14"), retrievedAt=date("2026-04-14"))
        newer = observation("revenue", 80, id="a-new-filing", concept="Revenue", filedAt=date("2026-03-15"), availableAt=date("2026-03-15"), retrievedAt=date("2026-03-16"))
        earnings = observation("net_income", 20)
        for shared_vintage in (False, True):
            for same_retrieval in (False, True):
                previous = {**older, "retrievedAt": newer["retrievedAt"]} if same_retrieval else dict(older)
                revised = dict(newer)
                if shared_vintage:
                    previous["vintageDate"] = revised["vintageDate"] = "2026-04-14"
                for rows in ([previous, revised, earnings], [revised, previous, earnings]):
                    with self.subTest(shared_vintage=shared_vintage, equal_retrieval=same_retrieval, first=rows[0]["id"]):
                        margin = metrics(rows)["net_margin_percent"]
                        self.assertEqual(margin["value"], 25)
                        self.assertIn("a-new-filing", margin["inputIds"])
                        self.assertNotIn("z-old-filing", margin["inputIds"])

    def test_known_vintage_and_revision_dates_cannot_be_overridden_by_later_fetch(self):
        for field in ("vintageDate", "revisionDate", "revisionAt"):
            old_date = date("2026-02-14") if field.endswith("At") else "2026-02-14"
            new_date = date("2026-03-15") if field.endswith("At") else "2026-03-15"
            older = observation("revenue", 100, id="old-vintage", concept="Revenue", retrievedAt=date("2026-04-14"), **{field: old_date})
            newer = observation("revenue", 80, id="new-vintage", concept="Revenue", retrievedAt=date("2026-03-16"), **{field: new_date})
            margin = metrics([newer, older, observation("net_income", 20)])["net_margin_percent"]
            with self.subTest(chronology_field=field):
                self.assertEqual(margin["value"], 25)
                self.assertEqual(next(row for row in margin["inputs"] if row["metric"] == "revenue")[field], new_date)

    def test_future_revision_chronology_is_gated_even_when_already_retrieved(self):
        older = observation("revenue", 100, id="old-filing", filedAt=date("2026-02-14"), retrievedAt=date("2026-02-15"))
        unreleased = observation("revenue", 80, id="future-filing", filedAt=date("2026-03-15"), retrievedAt=date("2026-03-01"))
        before = metrics([older, unreleased, observation("net_income", 20)], at=date("2026-03-10"))["net_margin_percent"]
        self.assertEqual(before["value"], 20)
        self.assertNotIn("future-filing", before["inputIds"])
        # A date-only vintage supplies no intraday release time, so it cannot be
        # used at the start of that day merely because it was fetched earlier.
        same_day = observation("revenue", 80, id="date-only-vintage", vintageDate="2026-04-15", retrievedAt=date("2026-04-14"))
        self.assertEqual(metrics([older, same_day, observation("net_income", 20)])["net_margin_percent"]["value"], 20)

    def test_provenance_removed_and_nonfinite_inputs_are_rejected(self):
        rows = [observation("revenue", float("nan")), observation("revenue", 100, canonical=False), observation("net_income", 20, sourceId=""), observation("assets", True)]
        result = build_financial_metrics(rows, AS_OF)
        self.assertEqual(result["metrics"], [])
        self.assertEqual(len(result["exclusions"]), 4)
        self.assertEqual(result["status"], "Data unavailable")

    def test_future_reporting_period_is_not_accepted_from_an_early_timestamp(self):
        future = observation("revenue", 100, periodEnd="2026-12-31")
        result = build_financial_metrics([future, observation("net_income", 20)], AS_OF)
        self.assertNotIn("net_margin_percent", {row["metric"] for row in result["metrics"]})
        self.assertIn("period had not ended", result["exclusions"][0]["reason"])

    def test_price_freshness_independent_of_assessment_timestamp(self):
        old = prices(count=3)[-1]
        old.update(observedAt=AS_OF - DAY, retrievedAt=AS_OF)
        value = metrics([old])["latest_price"]
        self.assertTrue(value["stale"])
        self.assertEqual(value["observedAt"], AS_OF - DAY)

    def test_market_metrics_require_explicit_compatible_adjusted_daily_history(self):
        values = metrics(prices())
        self.assertIn("observed_window_return_percent", values)
        self.assertGreater(values["annualized_realized_volatility_percent"]["value"], 0)
        self.assertFalse(values["annualized_realized_volatility_percent"]["stale"])
        for invalid in ({"adjustment": "raw"}, {"currency": ""}, {"frequency": "intraday"}):
            with self.subTest(invalid=invalid):
                output = metrics(prices(**invalid))
                self.assertIn("latest_price", output)
                self.assertNotIn("observed_window_return_percent", output)
                self.assertNotIn("annualized_realized_volatility_percent", output)

    def test_explicit_raw_crypto_history_retains_unadjusted_price_limitations(self):
        raw = prices("crypto:coingecko:bitcoin", adjustment="raw")
        values = metrics(raw)
        self.assertIn("observed_window_return_percent", values)
        self.assertIn("annualized_realized_volatility_percent", values)
        self.assertTrue(any("redenominations" in text for text in values["observed_window_return_percent"]["limitations"]))
        self.assertTrue(all(row["adjustment"] == "raw" for row in values["observed_window_return_percent"]["inputs"]))
        comparison = correlate_market_returns(raw, prices("crypto:coingecko:ethereum", adjustment="raw"), AS_OF)
        self.assertEqual(comparison["status"], "Calculated")
        self.assertTrue(any("nominal price" in text for text in comparison["metrics"][0]["limitations"]))
        self.assertNotIn("observed_window_return_percent", metrics(prices(adjustment="raw")))

    def test_total_return_index_is_not_published_as_a_cash_market_price(self):
        rows = prices(metric="total_return_index", adjustment="total-return", unit="index points")
        values = metrics(rows)
        self.assertIn("observed_window_return_percent", values)
        self.assertNotIn("latest_price", values)

    def test_threshold_replay_preserves_crossings_and_only_observed_outcomes(self):
        rows = prices()
        result = evaluate_threshold_history(rows, 2, AS_OF, outcome_sessions=5)
        self.assertEqual(result["status"], "Calculated")
        self.assertGreater(result["crossingCount"], 0)
        self.assertGreater(result["samplesWithObservedOutcome"], 0)
        self.assertTrue(any(row["outcomeStatus"] == "Data unavailable" for row in result["crossings"]))
        for crossing in result["crossings"]:
            self.assertGreaterEqual(abs(crossing["measurement"]["value"]), 2)
            self.assertEqual(len(crossing["measurement"]["inputIds"]), 2)
            if crossing["outcome"]:
                self.assertLessEqual(crossing["outcome"]["observedAt"], AS_OF)
        earlier = evaluate_threshold_history(rows, 2, AS_OF - 10 * DAY)
        self.assertLess(earlier["evaluatedIntervals"], result["evaluatedIntervals"])
        self.assertEqual(evaluate_threshold_history(rows[:10], 2, AS_OF)["status"], "Data unavailable")

    def test_daily_calculations_do_not_treat_monthlong_gaps_as_one_day(self):
        left, right = prices(), prices("equity:NYSE:BENCH")
        left = left[:10] + left[25:]
        right = right[:10] + right[25:]
        self.assertNotIn("annualized_realized_volatility_percent", metrics(left))
        comparison = correlate_market_returns(left, right, AS_OF)
        self.assertEqual(comparison["samples"], len(left) - 2)
        replay = evaluate_threshold_history(left, 2, AS_OF)
        self.assertEqual(replay["evaluatedIntervals"], len(left) - 2)
        self.assertTrue(any(row["outcomeStatus"] == "Data unavailable" for row in replay["crossings"]))

    def test_valuation_uses_sourced_market_cap_and_labels_reported_period(self):
        cap = observation("market_cap", 1000, observedAt=AS_OF, retrievedAt=AS_OF, availableAt=AS_OF, periodStart=None, periodEnd=None, accountingBasis=None, periodType=None)
        values = metrics([cap, observation("net_income", 100)])
        self.assertEqual(values["price_to_reported_annual_earnings"]["value"], 10)
        self.assertIn("reported period", values["price_to_reported_annual_earnings"]["formula"])
        self.assertNotIn("price_to_reported_annual_earnings", metrics([observation("net_income", 100), *prices()]))

    def test_correlation_aligns_exact_session_pairs_and_preserves_benchmark(self):
        left, right = prices(), prices("equity:NYSE:BENCH", multiplier=2)
        result = correlate_market_returns(left, right, AS_OF)
        self.assertEqual(result["status"], "Calculated")
        self.assertEqual(result["samples"], 39)
        self.assertAlmostEqual(result["metrics"][0]["value"], 1)
        self.assertEqual(result["metrics"][0]["benchmarkId"], "equity:NYSE:BENCH")
        del right[10]
        fewer = correlate_market_returns(left, right, AS_OF)
        self.assertEqual(fewer["samples"], 37)
        result = correlate_market_returns(left, prices("equity:NYSE:BENCH", adjustment="dividend-adjusted"), AS_OF)
        self.assertEqual(result["status"], "Data unavailable")

    def test_correlation_requires_sample_size_and_nonconstant_returns(self):
        self.assertEqual(correlate_market_returns(prices(count=10), prices("equity:NYSE:B", count=10), AS_OF)["status"], "Data unavailable")
        flat = [{**row, "value": 100} for row in prices("equity:NYSE:B")]
        result = correlate_market_returns(prices(), flat, AS_OF)
        self.assertEqual(result["status"], "Data unavailable")
        self.assertIn("constant", result["reason"])

    def test_event_study_is_aligned_sourced_and_descriptive(self):
        left, right = prices(), prices("equity:NYSE:BENCH", multiplier=2)
        result = event_study(left, right, AS_OF - 10 * DAY, AS_OF)
        self.assertEqual(result["status"], "Calculated")
        values = {row["metric"]: row for row in result["metrics"]}
        self.assertEqual(values["event_window_abnormal_return_percentage_points"]["value"], 0)
        self.assertIn("do not establish", result["limitations"][0])
        self.assertEqual(values["event_window_return_percent"]["period"]["sessions"], 5)
        self.assertGreaterEqual(len(values["event_window_return_percent"]["inputs"]), 12)
        self.assertEqual(event_study(left, right, AS_OF + DAY, AS_OF)["status"], "Data unavailable")

    def test_event_window_missing_session_and_incomplete_post_period_are_withheld(self):
        left, right = prices(), prices("equity:NYSE:BENCH")
        self.assertEqual(event_study(left, right, AS_OF - DAY, AS_OF)["status"], "Data unavailable")
        del right[30]
        result = event_study(left, right, AS_OF - 10 * DAY, AS_OF)
        self.assertEqual(result["status"], "Data unavailable")
        self.assertIn("missing", result["reason"])


if __name__ == "__main__":
    unittest.main()
