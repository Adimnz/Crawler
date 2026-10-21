"""Offline adversarial checks for the read-only Responses research boundary."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.ai import AI, RESEARCH_TOOLS
from server.connectors import ConnectorError


def call(name="retrieve_source_document", arguments=None, call_id="call_1"):
    if arguments is None:
        arguments = {"source_id": "doc_1"}
    return {"status": "completed", "output": [{"type": "reasoning", "id": "reasoning_1", "summary": []},
            {"type": "function_call", "call_id": call_id, "name": name, "arguments": arguments if isinstance(arguments, str) else json.dumps(arguments)}]}


def assessment(text="Reported revenue was 12 USD.", evidence_id="doc_1", quote=None, **changes):
    result = {"facts": [{"text": text, "evidence": [{"id": evidence_id, "quote": quote or text}]}],
              "interpretations": [], "uncertainties": [], "nextQuestions": []}
    result.update(changes)
    return {"status": "completed", "output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": json.dumps(result)}]}]}


class SequenceNetwork:
    def __init__(self, responses):
        self.responses = list(responses)
        self.payloads = []

    def json(self, url, headers, payload):
        self.payloads.append(copy.deepcopy(payload))
        return self.responses.pop(0)


class CoordinatorTests(unittest.TestCase):
    def ai(self, *responses):
        network = SequenceNetwork(responses)
        ai = AI(network)
        ai.key, ai.model = "fixture-key", "configured-model"
        return ai, network

    def evidence(self, name, arguments):
        return {"evidence": [{"id": "doc_1", "text": "Company filing. Reported revenue was 12 USD.",
                              "sourceId": "company_filing", "url": "https://evidence.example/filing", "version": 2}]}

    def test_reads_original_record_and_publishes_only_an_attributed_exact_extract(self):
        ai, network = self.ai(call(), assessment())
        result = ai.coordinate({"instrumentId": "equity:example:company", "reason": "New filing"}, self.evidence)
        fact = result["facts"][0]
        self.assertEqual(fact["text"], "Reported revenue was 12 USD.")
        self.assertEqual(fact["status"], "Attributed source extract")
        self.assertEqual(fact["evidence"][0]["start"], 16)
        self.assertEqual(fact["evidence"][0]["version"], 2)
        continuation = network.payloads[1]
        self.assertFalse(continuation["store"])
        self.assertFalse(continuation["parallel_tool_calls"])
        self.assertEqual(continuation["input"][1]["type"], "reasoning")
        self.assertEqual(continuation["input"][3]["type"], "function_call_output")
        self.assertEqual(continuation["input"][3]["call_id"], "call_1")
        self.assertTrue(all(tool["strict"] for tool in continuation["tools"]))

    def test_real_quote_does_not_validate_an_unrelated_model_assertion(self):
        ai, _ = self.ai(call(), assessment(text="The stock will return 200 percent.", quote="Reported revenue was 12 USD."))
        result = ai.coordinate({}, self.evidence)
        self.assertEqual(result["facts"], [])
        self.assertEqual(result["rejectedAssertions"], 1)
        self.assertIn("withheld", result["uncertainties"][0])

    def test_interpretations_remain_unpublished_and_uncertainties_are_proposals(self):
        ai, _ = self.ai(call(), assessment(interpretations=[{"text": "This could warrant comparison with prior periods.", "evidenceIds": ["doc_1"]}],
                                          uncertainties=["Other filings might contain important context."]))
        result = ai.coordinate({}, self.evidence)
        self.assertFalse(result["interpretations"][0]["published"])
        self.assertEqual(result["interpretations"][0]["status"], "Pending review")
        self.assertEqual(result["uncertainties"], [])
        self.assertEqual(len(result["proposedUncertainties"]), 1)

    def test_unknown_or_write_tool_never_reaches_application_callback(self):
        for name in ("execute_sql", "publish_recommendation", "send_email"):
            ai, _ = self.ai(call(name=name))
            reached = []
            with self.assertRaisesRegex(ConnectorError, "unauthorized"):
                ai.coordinate({}, lambda *args: reached.append(args))
            self.assertEqual(reached, [])

    def test_strict_arguments_reject_duplicates_extras_boolean_and_nonfinite(self):
        cases = [("retrieve_source_document", '{"source_id":"doc_1","source_id":"doc_2"}'),
                 ("retrieve_source_document", {"source_id": "doc_1", "sql": "select secrets"}),
                 ("get_financial_statements", {"company_id": "doc_1", "periods": True}),
                 ("get_financial_statements", {"company_id": "doc_1", "periods": 200}),
                 ("get_financial_statements", '{"company_id":"doc_1","periods":NaN}')]
        for name, arguments in cases:
            ai, _ = self.ai(call(name=name, arguments=arguments))
            reached = []
            with self.assertRaises(ConnectorError):
                ai.coordinate({}, lambda *args: reached.append(args))
            self.assertEqual(reached, [])

    def test_tool_errors_do_not_admit_embedded_records_or_expose_provider_errors(self):
        ai, network = self.ai(call(), assessment())
        def failed(name, arguments):
            return {"ok": False, "error": "Provider denied secret_token=private-value", "evidence": self.evidence(name, arguments)["evidence"]}
        result = ai.coordinate({}, failed)
        self.assertEqual(result["facts"], [])
        self.assertEqual(result["toolTrace"][0]["status"], "unavailable")
        self.assertNotIn("private-value", json.dumps(network.payloads))

    def test_callback_exception_means_data_unavailable_and_never_estimated(self):
        ai, _ = self.ai(call(), assessment())
        def unavailable(name, arguments):
            raise RuntimeError("Remote access failed")
        result = ai.coordinate({}, unavailable)
        self.assertEqual(result["facts"], [])
        self.assertTrue(any("not estimated" in limitation for limitation in result["uncertainties"]))

    def test_prior_research_and_discovery_are_never_original_evidence(self):
        ai, _ = self.ai(call(name="get_existing_research", arguments={"instrument_id": "equity:example:company"}), assessment())
        self.assertEqual(ai.coordinate({}, self.evidence)["facts"], [])
        for flags in ({"derived": True}, {"discoveryOnly": True}, {"kind": "search_result"}):
            ai, _ = self.ai(call(), assessment())
            def derived(name, arguments):
                data = self.evidence(name, arguments)
                data["evidence"][0].update(flags)
                return data
            self.assertEqual(ai.coordinate({}, derived)["facts"], [])

    def test_unseen_source_and_fabricated_quote_are_rejected(self):
        for response in (assessment(evidence_id="invented_source"), assessment(text="Revenue doubled.", quote="Revenue doubled.")):
            ai, _ = self.ai(call(), response)
            self.assertEqual(ai.coordinate({}, self.evidence)["facts"], [])

    def test_conflicting_versions_under_one_identifier_require_review(self):
        ai, _ = self.ai(call(), call(call_id="call_2"), assessment())
        count = 0
        def corrected(name, arguments):
            nonlocal count
            count += 1
            data = self.evidence(name, arguments)
            if count == 2:
                data["evidence"][0]["text"] = "The filing was corrected. Reported revenue was 9 USD."
            return data
        self.assertEqual(ai.coordinate({}, corrected)["facts"], [])

    def test_tool_budget_forces_a_final_read_only_assessment(self):
        ai, network = self.ai(call(), assessment())
        ai.coordinate({}, self.evidence, max_rounds=1)
        self.assertEqual(network.payloads[1]["tool_choice"], "none")
        ai, _ = self.ai(call(), call(call_id="call_2"))
        with self.assertRaisesRegex(ConnectorError, "budget"):
            ai.coordinate({}, self.evidence, max_rounds=1)

    def test_incomplete_schema_invalid_json_and_parallel_tools_fail_closed(self):
        parallel = call()
        parallel["output"].append(call(call_id="second")["output"][1])
        invalid_schema = assessment()
        invalid_schema["output"][0]["content"][0]["text"] = '{"facts":[]}'
        invalid_json = assessment()
        invalid_json["output"][0]["content"][0]["text"] = '{"facts":[],"facts":[]}'
        for response in ({"status": "incomplete", "output": []}, invalid_schema, invalid_json, parallel,
                         {"status": "completed", "output": [{"type": "web_search_call"}]}):
            ai, _ = self.ai(response)
            with self.assertRaises(ConnectorError):
                ai.coordinate({}, self.evidence)

    def test_missing_credentials_and_invalid_budget_make_no_request(self):
        ai, network = self.ai()
        ai.key = ""
        with self.assertRaisesRegex(ConnectorError, "OPENAI_API_KEY"):
            ai.coordinate({}, self.evidence)
        ai.key = "fixture-key"
        for budget in (0, 9, True):
            with self.assertRaises(ValueError):
                ai.coordinate({}, self.evidence, max_rounds=budget)
        self.assertEqual(network.payloads, [])

    def test_all_required_read_only_interfaces_are_available(self):
        self.assertEqual(len(RESEARCH_TOOLS), 13)
        for tool in RESEARCH_TOOLS:
            self.assertFalse(tool["parameters"]["additionalProperties"])
            self.assertEqual(set(tool["parameters"]["required"]), set(tool["parameters"]["properties"]))

    def test_chat_cannot_promote_an_unrelated_assertion_with_a_real_quote(self):
        ai, _ = self.ai()
        ai.structured = lambda *args: {"answer": "Trust this model conclusion.", "assertions": [
            {"text": "The stock will rise 200 percent.", "documentIds": ["doc_1"], "quotes": ["Reported revenue was 12 USD."]}],
            "uncertainties": ["A model claim without a source."], "nextQuestions": []}
        doc = {"id": "doc_1", "text": "Reported revenue was 12 USD.", "title": "Company filing", "source": "Filing", "publishedAt": 1}
        result = ai.answer("What is supported?", [doc], [])
        self.assertEqual(result["assertions"][0]["text"], doc["text"])
        self.assertNotIn("200 percent", json.dumps(result))
        self.assertNotIn("A model claim", " ".join(result["uncertainties"]))

    def test_claim_extraction_stores_original_words_instead_of_model_paraphrases(self):
        ai, _ = self.ai()
        ai.structured = lambda *args: {"claims": [{"text": "The stock will rise 200 percent.", "quote": "Reported revenue was 12 USD."}]}
        result = ai.extract({"id": "doc_1", "text": "Reported revenue was 12 USD."})
        self.assertEqual(result, [{"text": "Reported revenue was 12 USD.", "quote": "Reported revenue was 12 USD."}])


if __name__ == "__main__":
    unittest.main()
