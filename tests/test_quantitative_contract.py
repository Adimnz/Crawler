"""Legacy diagnostic calculations must obey the same source-data contract."""
import math
from pathlib import Path
import statistics
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.analysis import DAY, HOUR, quantitative


class QuantitativeContractTests(unittest.TestCase):
    at = 1792440000000

    def row(self, index, **changes):
        observed = self.at - (12 - index) * DAY
        return {"id": "sample-" + str(index), "assetId": "equity:FIXTURE:COMPANY", "metric": "price_usd", "sourceId": "provider-one",
                "value": 100 + index, "observedAt": observed, "retrievedAt": observed, "availableAt": observed,
                "unit": "USD", "currency": "USD", "adjustment": "split-adjusted", "frequency": "daily", "timeZone": "UTC", **changes}

    def history(self, **changes):
        return [self.row(index, **changes) for index in range(13)]

    def test_different_providers_units_adjustments_and_sessions_never_mix(self):
        rows = self.history()
        for changes in ({"sourceId": "provider-two"}, {"unit": "EUR", "currency": "EUR"}, {"adjustment": "raw"}, {"marketSession": "extended"}):
            rows.extend(self.history(**changes))
        result = quantitative(rows, self.at)
        self.assertEqual(len(result), 5)
        self.assertEqual({item["samples"] for item in result}, {13})
        self.assertEqual(sum(item["returnVolatility"] is not None for item in result), 4)

    def test_only_explicit_comparable_daily_prices_produce_return_volatility(self):
        for metric in ("volume", "revenue", "net_income", "level", "debt"):
            result = quantitative(self.history(metric=metric), self.at)[0]
            self.assertIsNone(result["returnVolatility"])
        self.assertIsNotNone(quantitative(self.history(), self.at)[0]["returnVolatility"])

    def test_missing_units_adjustment_or_daily_sampling_withhold_price_diagnostics(self):
        for changes in ({"unit": ""}, {"adjustment": None}, {"frequency": "snapshot"}, {"adjustment": "raw"}):
            result = quantitative(self.history(**changes), self.at)[0]
            self.assertIsNone(result["returnVolatility"])
        result = quantitative(self.history(unit="", adjustment=None), self.at)[0]
        self.assertIsNone(result["robustZ"])
        self.assertIn("withheld", " ".join(result["warnings"]))

    def test_future_retrieval_release_and_vintage_are_not_available_historically(self):
        rows = [self.row(0), self.row(1, retrievedAt=self.at + 1), self.row(2, availableAt=self.at + 1),
                self.row(3, vintageDate="2030-01-01"), self.row(4, observedAt=self.at + 1)]
        result = quantitative(rows, self.at)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["samples"], 1)
        self.assertEqual(result[0]["value"], 100)

    def test_latest_release_wins_when_vintages_were_downloaded_together(self):
        first = self.row(0, retrievedAt=self.at, availableAt=self.at - 3 * DAY, vintageDate="2026-10-01", value=100)
        revised = {**first, "id": "revision-new", "value": 102, "availableAt": self.at - DAY, "vintageDate": "2026-10-15"}
        result = quantitative([revised, first], self.at)[0]
        self.assertEqual(result["value"], 102)
        self.assertEqual(result["samples"], 1)

    def test_superseded_records_remain_available_only_before_the_correction(self):
        first = self.row(0, supersededAt=self.at - DAY, value=100)
        revised = {**self.row(0), "id": "revision-new", "value": 103, "retrievedAt": self.at - DAY, "availableAt": self.at - DAY}
        before = quantitative([first, revised], self.at - 2 * DAY)[0]
        after = quantitative([first, revised], self.at)[0]
        self.assertEqual(before["value"], 100)
        self.assertEqual(after["value"], 103)

    def test_statement_period_types_accounting_bases_and_concepts_stay_distinct(self):
        rows = []
        for changes in ({"periodType": "annual", "accountingBasis": "US GAAP"}, {"periodType": "quarterly", "accountingBasis": "US GAAP"},
                        {"periodType": "annual", "accountingBasis": "IFRS"}, {"periodType": "annual", "accountingBasis": "US GAAP", "concept": "AlternativeRevenue"}):
            rows.extend(self.history(metric="revenue", **changes))
        result = quantitative(rows, self.at)
        self.assertEqual(len(result), 4)
        self.assertTrue(all(item["returnVolatility"] is None for item in result))

    def test_revision_copies_do_not_inflate_sample_counts(self):
        rows = self.history()
        rows += [{**row, "id": row["id"] + "-revision", "value": row["value"] + 1, "retrievedAt": self.at} for row in rows]
        self.assertEqual(quantitative(rows, self.at)[0]["samples"], 13)

    def test_intraday_or_discontinuous_samples_do_not_masquerade_as_daily_returns(self):
        rows = [self.row(index, observedAt=self.at - (12 - index) * HOUR, retrievedAt=self.at - (12 - index) * HOUR, availableAt=self.at - (12 - index) * HOUR) for index in range(13)]
        self.assertIsNone(quantitative(rows, self.at)[0]["returnVolatility"])
        rows = [self.row(index, observedAt=self.at - (12 - index) * 7 * DAY, retrievedAt=self.at - (12 - index) * 7 * DAY, availableAt=self.at - (12 - index) * 7 * DAY) for index in range(13)]
        self.assertIsNone(quantitative(rows, self.at)[0]["returnVolatility"])

    def test_nonpositive_price_does_not_silently_compress_the_return_series(self):
        rows = self.history()
        rows[5]["value"] = 0
        result = quantitative(rows, self.at)[0]
        self.assertIsNone(result["returnVolatility"])

    def test_numeric_outputs_preserve_formula_inputs_units_and_sample_window(self):
        rows = self.history()
        result = quantitative(rows, self.at)[0]
        expected = statistics.pstdev(math.log(right["value"] / left["value"]) for left, right in zip(rows, rows[1:]))
        self.assertAlmostEqual(result["returnVolatility"], expected)
        for key in ("robustZMethod", "returnVolatilityMethod"):
            self.assertEqual(result[key]["inputIds"], [row["id"] for row in rows])
            self.assertTrue(result[key]["formula"])
            self.assertTrue(result[key]["unit"])
            self.assertEqual(len(result[key]["inputs"]), 13)
        self.assertFalse(result["returnVolatilityMethod"]["annualized"])
        self.assertEqual(result["returnVolatilityMethod"]["period"]["end"], self.at)

    def test_noncanonical_latest_revision_invalidates_the_earlier_sample(self):
        old = self.row(0, value=100)
        removed = {**old, "id": "removed-revision", "canonical": False, "removed": True, "retrievedAt": self.at, "availableAt": self.at}
        self.assertEqual(quantitative([old, removed], self.at), [])

    def test_malformed_or_nonfinite_observations_are_ignored_without_poisoning_other_sources(self):
        invalid = [self.row(1, value=value) for value in (True, None, "invalid", float("nan"), float("inf"))]
        invalid += [self.row(2, availableAt="not-a-date"), self.row(3, assetId="TICKER"), self.row(4, sourceId="")]
        result = quantitative([self.row(0), *invalid], self.at)[0]
        self.assertEqual(result["samples"], 1)
        self.assertTrue(result["stale"])


if __name__ == "__main__":
    unittest.main()
