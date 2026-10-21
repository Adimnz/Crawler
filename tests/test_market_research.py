"""Offline proof of useful synthesis and its original-source boundaries."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.market_research import research_topic
from server.connectors import ConnectorError


COMPANY = "Atlas Manufacturers reports expanding factory investment for regional infrastructure demand."
MARKET = "Regional credit markets face refinancing constraints and rising funding costs."
BANK = "Atlas Regional Bank reports new lending facilities for infrastructure suppliers."


def document(identity="source-one", text=None, **changes):
    return {"id": identity, "version": 3, "title": "Infrastructure and financing disclosure", "url": "https://original.example/" + identity,
            "source": "Original Disclosure Office", "text": text or " ".join((COMPANY, MARKET, BANK)), "publishedAt": 1,
            "entities": [], **changes}


def citation(quote=COMPANY, **changes):
    return {"documentId": "source-one", "version": 3, "quote": quote, **changes}


def finding(text="The disclosure links factory expansion with infrastructure demand, making supplier investment a useful monitoring theme.", quote=COMPANY):
    return {"text": text, "evidence": [citation(quote)]}


def subject(name="Atlas Manufacturers", kind="company", quote=COMPANY):
    return {"name": name, "kind": kind, "connection": "The source describes " + name + " in its infrastructure discussion.",
            "watchFor": "What changes in documented infrastructure exposure should be monitored?", "evidence": [citation(quote)]}


def report(**changes):
    return {"summary": [finding()], "drivers": [finding("The lending disclosure suggests financing availability warrants monitoring.", BANK)],
            "risks": [finding("The source reports refinancing constraints that could complicate infrastructure funding.", MARKET)],
            "subjects": [subject(), subject("Regional credit markets", "market", MARKET), subject("Atlas Regional Bank", "financial_institution", BANK)],
            "nextQuestions": ["Which original disclosures confirm financing availability?"], **changes}


class AI:
    ready, model = True, "fixture-research-model"

    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result or report(), error, []

    def structured(self, name, schema, instructions, data):
        self.calls.append({"name": name, "schema": schema, "instructions": instructions, "data": data})
        if self.error:
            raise self.error
        return copy.deepcopy(self.result)


class MarketResearchTests(unittest.TestCase):
    def test_readable_generated_analysis_and_three_subject_kinds_without_asset_gates(self):
        ai = AI()
        result = research_topic(ai, "infrastructure investment", [document()])
        self.assertEqual(result["method"], "OpenAI source research")
        self.assertEqual(result["model"], ai.model)
        self.assertEqual(result["sourceCount"], 1)
        self.assertEqual(result["summary"][0]["label"], "AI analysis")
        self.assertNotEqual(result["summary"][0]["text"], COMPANY)
        self.assertEqual({item["kind"] for item in result["subjects"]}, {"company", "market", "financial_institution"})
        self.assertTrue(all(item["id"].startswith("research-subject-") for item in result["subjects"]))
        self.assertNotIn("qualified", result["subjects"][0])
        self.assertNotIn("ticker", result["subjects"][0])
        evidence = result["summary"][0]["evidence"][0]
        self.assertEqual(evidence, {**citation(), "url": "https://original.example/source-one", "title": "Infrastructure and financing disclosure"})
        self.assertTrue(any("unverified" in item for item in result["limitations"]))
        self.assertEqual(ai.calls[0]["name"], "market_topic_research")
        self.assertFalse(ai.calls[0]["schema"]["additionalProperties"])

    def test_every_quote_and_source_version_is_locally_validated(self):
        invalid = [finding("Unseen source", COMPANY), finding("Wrong revision", COMPANY), finding("Fabricated source quote", COMPANY), finding("Wrong version type", COMPANY)]
        invalid[0]["evidence"][0]["documentId"] = "invented-source"
        invalid[1]["evidence"][0]["version"] = 2
        invalid[2]["evidence"][0]["quote"] = "This was never in the original document."
        invalid[3]["evidence"][0]["version"] = 3.0
        result = research_topic(AI(report(drivers=invalid)), "infrastructure", [document()])
        self.assertTrue(all(item["label"] == "Source extract" for item in result["drivers"]))
        self.assertTrue(any("4 model item(s)" in item for item in result["limitations"]))

    def test_real_quote_does_not_admit_a_subject_missing_from_the_quote(self):
        subjects = [subject("Imaginary Investment Bank", "financial_institution"), subject("Atlas", "company", MARKET)]
        result = research_topic(AI(report(subjects=subjects)), "infrastructure", [document()])
        self.assertEqual(result["subjects"], [])
        self.assertTrue(any("2 model item(s)" in item for item in result["limitations"]))

    def test_quoted_subject_matching_uses_name_boundaries_and_case_insensitivity(self):
        result = research_topic(AI(report(subjects=[subject("atlas manufacturers"), subject("Manufact", "company")])), "infrastructure", [document()])
        self.assertEqual([item["name"] for item in result["subjects"]], ["atlas manufacturers"])

    def test_numeric_forecasts_invented_tickers_and_unsupported_numbers_are_withheld(self):
        invalid = [finding("The stock could rise 20% from this announcement."), finding("Monitor $FAKE because this investment is expanding."),
                   finding("The company reports 100 factories."), finding("The price target is 50 dollars."), finding("Buy these shares for infrastructure exposure.")]
        result = research_topic(AI(report(summary=invalid)), "infrastructure", [document()])
        self.assertTrue(all(item["label"] == "Source extract" for item in result["summary"]))
        combined = str(result["summary"])
        self.assertNotIn("$FAKE", combined)
        self.assertNotIn("20%", combined)
        self.assertTrue(any("5 model item(s)" in item for item in result["limitations"]))

    def test_source_reported_numbers_are_retained_without_new_calculations(self):
        quote = "Atlas Manufacturers reports 20 factories serving infrastructure projects."
        item = finding("The filing reports 20 factories associated with infrastructure projects.", quote)
        result = research_topic(AI(report(summary=[item], drivers=[], risks=[], subjects=[])), "infrastructure", [document(text=quote)])
        self.assertEqual(result["summary"][0]["label"], "AI analysis")
        self.assertIn("20 factories", result["summary"][0]["text"])

    def test_monitoring_question_can_ask_about_next_period_without_inventing_a_ticker(self):
        original = subject()
        original["watchFor"] = "What will the 2027 disclosure report about infrastructure exposure?"
        result = research_topic(AI(report(subjects=[original], nextQuestions=["Which 2027 sources update these reports?", "What does $FAKE disclose?"])), "infrastructure", [document()])
        self.assertEqual(len(result["subjects"]), 1)
        self.assertIn("2027", result["subjects"][0]["watchFor"])
        self.assertEqual(result["nextQuestions"], ["Which 2027 sources update these reports?"])

    def test_no_ai_still_produces_source_extracts_and_declared_watch_subjects(self):
        doc = document(entities=[{"id": "equity:fixture:ATLAS", "name": "Atlas Manufacturers", "type": "equity"},
                                 {"id": "bank:fixture:atlas", "name": "Atlas Regional Bank", "type": "bank"},
                                 {"id": "unresolved:ticker:FAKE", "name": "FAKE", "type": "unresolved"}])
        result = research_topic(None, "infrastructure", [doc])
        self.assertEqual(result["method"], "Collected source research")
        self.assertIsNone(result["model"])
        self.assertTrue(result["summary"])
        self.assertTrue(result["drivers"])
        self.assertTrue(result["risks"])
        self.assertEqual({item["name"] for item in result["subjects"]}, {"Atlas Manufacturers", "Atlas Regional Bank"})
        self.assertTrue(all(item["label"] == "Source extract" for item in result["summary"]))

    def test_background_fallback_keeps_valid_previously_researched_subjects_without_ai_calls(self):
        original = document()
        previous = research_topic(AI(), "infrastructure", [original])
        disabled = AI()
        disabled.ready = False
        refreshed = research_topic(disabled, "infrastructure", [original], previous)
        self.assertEqual(disabled.calls, [])
        self.assertEqual(refreshed["method"], "Collected source research")
        self.assertEqual({item["id"] for item in refreshed["subjects"]}, {item["id"] for item in previous["subjects"]})
        self.assertTrue(all(item["provenance"] == "Previously researched; source unchanged" for item in refreshed["subjects"]))
        self.assertTrue(all(item["evidence"][0]["version"] == original["version"] for item in refreshed["subjects"]))
        declared = document(entities=[{"name": "Atlas Manufacturers", "type": "equity"}])
        deduplicated = research_topic(None, "infrastructure", [declared], previous)
        self.assertEqual(len([item for item in deduplicated["subjects"] if item["name"] == "Atlas Manufacturers"]), 1)
        failed = research_topic(AI(error=TimeoutError("Offline fixture")), "infrastructure", [original], previous)
        self.assertEqual(len(failed["subjects"]), len(previous["subjects"]))
        self.assertEqual(failed["aiError"]["errorCode"], "timeout")

    def test_previous_watch_subjects_are_dropped_when_original_versions_change_or_disappear(self):
        previous = research_topic(AI(), "infrastructure", [document()])
        for originals in ([document(version=4)], [document(text="This corrected disclosure no longer names those subjects.")], [],
                          [document("another-original", text=COMPANY)]):
            with self.subTest(originals=originals):
                refreshed = research_topic(None, "infrastructure", originals, previous)
                self.assertEqual(refreshed["subjects"], [])

    def test_ai_failure_falls_back_without_leaking_provider_error(self):
        ai = AI(error=RuntimeError("Private provider error api_key=secret-example"))
        result = research_topic(ai, "infrastructure", [document()])
        self.assertEqual(result["method"], "Collected source research")
        self.assertTrue(result["summary"])
        self.assertNotIn("secret-example", str(result))
        self.assertTrue(any("unavailable" in item for item in result["limitations"]))
        self.assertEqual(result["aiError"]["errorCode"], "invalid_research_response")

    def test_provider_authentication_and_quota_failures_have_actionable_safe_errors(self):
        for status, code in ((401, "invalid_key"), (403, "access_denied"), (429, "usage_limit"), (404, "model_unavailable")):
            with self.subTest(status=status):
                error = ConnectorError("Provider body exposed api_key=private-fixture-key", status=status)
                result = research_topic(AI(error=error), "infrastructure", [document()])
                self.assertEqual(result["method"], "Collected source research")
                self.assertTrue(result["summary"])
                self.assertEqual(result["aiError"]["errorCode"], code)
                self.assertEqual(result["aiError"]["status"], status)
                self.assertNotIn("private-fixture-key", str(result))
                self.assertNotIn("Provider body", str(result))
                self.assertIn(result["aiError"]["message"], result["limitations"][-1])

    def test_timeout_and_structured_parse_failures_are_distinguished_without_provider_content(self):
        result = research_topic(AI(error=TimeoutError("secret=private-fixture-key")), "infrastructure", [document()])
        self.assertEqual(result["aiError"]["errorCode"], "timeout")
        self.assertNotIn("private-fixture-key", str(result))
        try:
            json.loads("invalid response with private-fixture-key")
        except json.JSONDecodeError as cause:
            error = ConnectorError("Invalid structured response private-fixture-key")
            error.__cause__ = cause
        result = research_topic(AI(error=error), "infrastructure", [document()])
        self.assertEqual(result["aiError"]["errorCode"], "invalid_research_response")
        self.assertNotIn("private-fixture-key", str(result))

    def test_discovery_derived_records_and_conflicting_source_ids_cannot_be_evidence(self):
        ai = AI()
        documents = [document(derived=True), document("candidate", discoveryOnly=True), document("old-analysis", kind="research"),
                     document("conflicted", text=COMPANY), document("conflicted", text=MARKET), document("unsafe", url="javascript:alert(1)")]
        result = research_topic(ai, "infrastructure", documents)
        self.assertEqual(result["sourceCount"], 0)
        self.assertEqual(result["summary"], [])
        self.assertEqual(ai.calls, [])

    def test_previous_research_is_bounded_non_citable_context(self):
        previous = {"summary": [{"text": "Previous derived interpretation", "evidence": [citation()]}],
                    "subjects": [{"name": "Previous company", "evidence": [citation()]}]}
        ai = AI()
        research_topic(ai, "infrastructure", [document()], previous)
        context = ai.calls[0]["data"]["previous"]
        self.assertTrue(context["derivedContextOnly"])
        self.assertEqual(context["previousSummary"], ["Previous derived interpretation"])
        self.assertNotIn("evidence", str(context))
        self.assertIn("untrusted", ai.calls[0]["instructions"])
        self.assertIn("Previous research is derived", ai.calls[0]["instructions"])

    def test_malformed_model_payload_and_unusable_synthesis_return_useful_fallback(self):
        for result in ({"summary": []}, report(summary="wrong type"), report(summary=[], drivers=[], risks=[], subjects=[], nextQuestions=[])):
            with self.subTest(result=result):
                report_result = research_topic(AI(result), "infrastructure", [document()])
                self.assertEqual(report_result["method"], "Collected source research")
                self.assertTrue(report_result["summary"])
                self.assertEqual(report_result["aiError"]["errorCode"], "invalid_research_response")

    def test_context_and_output_are_bounded_and_subject_ids_are_stable(self):
        ai = AI()
        documents = [document("source-" + str(index), text=COMPANY + " padding " * 2000) for index in range(20)]
        result = research_topic(ai, "infrastructure", documents)
        self.assertEqual(result["sourceCount"], 12)
        self.assertTrue(all(len(record["text"]) <= 6500 for record in ai.calls[0]["data"]["records"]))
        first = research_topic(AI(), "infrastructure", [document()])
        second = research_topic(AI(), "infrastructure finance", [document()])
        self.assertEqual(first["subjects"][0]["id"], second["subjects"][0]["id"])


if __name__ == "__main__":
    unittest.main()
