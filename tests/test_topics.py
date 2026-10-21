"""Topic curation uses synthetic, offline instruments and source records."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import analysis as a
from server.service import ResearchService
from server.storage import now_ms
from server.topics import TopicResearch


class OfflineNetwork:
    def __init__(self):
        self.calls = []
        self.pages = {}

    def allowed(self, url):
        self.calls.append(("robots", url))
        return url in self.pages

    def fetch(self, url, **kwargs):
        self.calls.append(("fetch", url))
        if url not in self.pages: raise AssertionError("No external request is authorized by this fixture")
        return self.pages[url], {"content-type": "text/html; charset=utf-8"}, url


class FakeAI:
    ready, model = True, "offline-test-model"

    def __init__(self):
        self.plans = self.discoveries = self.assessments = 0
        self.sources = []
        self.terms = ["nuclear energy"]
        self.subject_names = [("Photon Systems", "company"), ("Mineral Systems", "company")]

    def plan_topic(self, query):
        self.plans += 1
        return {"title": "Nuclear energy research", "searchTerms": self.terms,
                "questions": ["What source evidence supports topic relevance?"], "assetTypes": ["equity"], "regions": []}

    def discover_topic(self, query, terms):
        self.discoveries += 1
        return {"sources": self.sources}

    def coordinate(self, task, callback, max_rounds):
        self.assessments += 1
        return {"facts": [], "limitations": ["Offline test assessment"], "questions": []}

    def structured(self, name, schema, instructions, data):
        if name != "market_topic_research": raise AssertionError("Unexpected offline AI request")
        self.assessments += 1
        records = data["records"]
        first = records[0]
        quote = first["text"].split(". ")[0] + ("." if ". " in first["text"] else "")
        evidence = [{"documentId": first["id"], "version": first["version"], "quote": quote}]
        subjects = []
        for subject, kind in self.subject_names:
            doc = next((row for row in records if subject in row["text"]), None)
            if not doc: continue
            source_quote = next((part + "." for part in doc["text"].split(". ") if subject in part), doc["text"])
            if source_quote not in doc["text"]: source_quote = doc["text"]
            subjects.append({"name": subject, "kind": kind, "connection": "The source reports a topic-related development involving " + subject + ".",
                "watchFor": "What new source reports change the situation for " + subject + "?",
                "evidence": [{"documentId": doc["id"], "version": doc["version"], "quote": source_quote}]})
        return {"summary": [{"text": "The collected source describes developments to monitor.", "evidence": evidence}],
                "drivers": [], "risks": [], "subjects": subjects, "nextQuestions": ["Which new original sources change the topic outlook?"]}

    def translate(self, *_): raise AssertionError("Background enrich jobs are not run by this test")


class TopicTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.network = OfflineNetwork()
        self.s = ResearchService(self.temporary.name, network=self.network, seed=False, dsn="")
        self.s.auto_ai = False
        self.topics = TopicResearch(self.s)
        self.at = now_ms() - 2000
        self.source = self.s.add_source({"id": "fixture-filings", "name": "Offline filings", "url": "https://data.sec.gov/submissions/CIK0000000001.json",
            "kind": "sec", "enabled": True, "tier": "primary", "permissions": "Synthetic tests only"})
        self.market = self.s.add_source({"id": "fixture-market", "name": "Offline market", "url": "https://market.example/fixture",
            "kind": "json", "enabled": True, "tier": "primary", "permissions": "Synthetic tests only", "config": {"recordType": "observation"}})

    def tearDown(self):
        self.s.close()
        self.temporary.cleanup()

    def asset(self, name="Photon Systems", ticker="PHOT", topic="nuclear energy", stale=False):
        asset_id = "equity:NASDAQ:" + ticker
        asset = {"id": asset_id, "name": name, "ticker": ticker, "exchange": "NASDAQ", "cik": "0000000001" if ticker == "PHOT" else "0000000002",
            "assetClass": "equity", "identityVerified": True, "identitySource": "https://data.sec.gov/submissions/CIK0000000001.json",
            "sector": "Fixture industry", "country": "Fixture location"}
        self.s.investments.accept_assets([asset], self.source)
        saved = self.s.db.get("asset", asset_id)
        saved["firstSeen"] = self.at - 20 * a.DAY
        self.s.db.put("asset", asset_id, saved)
        document = self.s.ingest(self.source, {"title": name + " publishes a fixture disclosure", "text": name + " supplies " + topic + " monitoring equipment in this synthetic disclosure. This fixture does not describe a real investment.",
            "url": "https://www.sec.gov/Archives/edgar/data/" + ticker + "/fixture.htm", "publishedAt": self.at - a.DAY,
            "companyId": asset_id, "filingType": "8-K", "entities": [{"id": asset_id, "name": name, "type": "equity"}]}, at=self.at)
        for age in (12 * a.DAY, 3 * a.DAY if stale else 0):
            self.s.observation(self.market, {"assetId": asset_id, "metric": "price_usd", "value": 10,
                "observedAt": self.at - age, "unit": "USD", "currency": "USD", "frequency": "daily", "adjustment": "split-adjusted"}, at=self.at)
        self.s.investments.cycle("Offline topic test")
        return asset_id, document

    def complete(self, query):
        topic = self.topics.create(query)
        result = self.topics.run(topic["id"])
        self.s.db.finish_job(topic["jobId"])
        return result

    def test_create_is_durable_and_immediate_without_provider_requests(self):
        topic = self.topics.create("Nuclear energy")
        self.assertEqual(topic["state"], "Queued")
        self.assertEqual(topic["entries"], [])
        self.assertEqual(self.s.db.get_job(topic["jobId"])["kind"], "topic-research")
        self.assertEqual(self.network.calls, [])
        self.assertEqual(self.topics.create(" nuclear  ENERGY ")["id"], topic["id"])
        self.assertEqual(len(self.topics.list()), 1)

    def test_curation_includes_only_assets_with_selected_topic_evidence(self):
        wanted, doc = self.asset()
        unrelated, _ = self.asset("Mineral Systems", "MINR", "lithium extraction")
        result = self.complete("Nuclear energy")
        self.assertEqual(result["state"], "Monitoring")
        self.assertEqual([r["assetId"] for r in result["entries"]], [wanted])
        self.assertNotIn(unrelated, [r["assetId"] for r in result["entries"] + result["candidates"]])
        row = result["entries"][0]
        self.assertIn(row["reason"], doc["text"])
        self.assertEqual(row["topicMatch"][0]["version"], doc["version"])
        self.assertEqual(result["qualifiedCount"], 1)
        self.assertNotIn("weight", row)

    def test_stale_market_data_retains_topic_candidate_but_withholds_monitoring_entry(self):
        asset_id, _ = self.asset(stale=True)
        result = self.complete("nuclear energy")
        self.assertEqual(result["entries"], [])
        self.assertEqual(result["candidates"][0]["assetId"], asset_id)
        self.assertFalse(result["candidates"][0]["qualified"])
        self.assertTrue(any("stale" in gap.lower() for gap in result["candidates"][0]["qualificationGaps"]))

    def test_ai_hints_are_not_accepted_as_topic_exposure_or_qualification(self):
        self.asset(topic="lithium extraction")
        ai = FakeAI()
        ai.terms = ["lithium extraction"]
        self.s.ai, self.s.auto_ai = ai, True
        result = self.complete("nuclear energy")
        self.assertEqual(result["entries"], [])
        self.assertEqual(len(result["candidates"]), 1)
        self.assertIn("requires review", result["candidates"][0]["relevanceMethod"])
        self.assertFalse(result["candidates"][0]["qualified"])

    def test_literal_query_terms_cannot_bypass_topic_match_threshold(self):
        item = {"query": "Fixture Equity Laboratory", "planMethod": "Literal topic parsing",
                "plan": {"searchTerms": ["fixture", "equity", "laboratory"]}}
        unrelated = {"text": "Fixture Digital Token has published a protocol disclosure."}
        self.assertFalse(self.topics._match(unrelated, item)["matches"])
        self.assertTrue(self.topics._match({"text": "Fixture Equity Laboratory reports a development."}, item)["matches"])

    def test_ai_hint_using_only_one_original_word_cannot_bypass_threshold(self):
        item = {"query": "nuclear energy infrastructure", "planMethod": "AI research plan",
                "plan": {"searchTerms": ["energy", "renewable monitoring"]}}
        self.assertFalse(self.topics._match({"text": "A household energy bill was published."}, item)["matches"])
        candidate = self.topics._match({"text": "Renewable monitoring equipment was disclosed."}, item)
        self.assertTrue(candidate["matches"])
        self.assertFalse(candidate["literal"])

    def test_ai_plan_and_unchanged_assessment_are_not_repeated_on_refresh(self):
        self.asset()
        ai = FakeAI()
        self.s.ai, self.s.auto_ai = ai, True
        result = self.complete("nuclear energy")
        self.topics.run(result["id"])
        self.assertEqual(ai.plans, 1)
        self.assertEqual(ai.discoveries, 1)
        self.assertEqual(ai.assessments, 1)

    def test_empty_topic_has_explicit_missing_evidence_state(self):
        result = self.complete("Deep ocean monitoring")
        self.assertEqual(result["state"], "Needs evidence")
        self.assertEqual(result["entries"], [])
        self.assertEqual(result["evidence"], [])
        self.assertTrue(any("No matching collected source evidence" in row for row in result["limitations"]))

    def test_source_correction_revises_topic_membership_and_retains_history(self):
        asset_id, doc = self.asset()
        first = self.complete("nuclear energy")
        self.s.ingest(self.source, {**doc, "text": "Photon Systems corrects its fixture disclosure: the supplier covers ordinary household equipment."})
        second = self.topics.run(first["id"])
        self.assertEqual(second["entries"], [])
        self.assertEqual(second["candidates"], [])
        self.assertEqual(second["version"], first["version"] + 1)
        self.assertIn("no longer", " ".join(second["whatChanged"]))
        self.assertEqual(self.s.db.get("topicRevision", first["id"] + ":v1")["entries"][0]["assetId"], asset_id)
        self.assertEqual(len(self.topics.get(first["id"])["revisions"]), 2)

    def test_paused_topic_never_schedules_research(self):
        item = self.topics.create("nuclear energy")
        self.s.db.finish_job(item["jobId"])
        self.topics.configure(item["id"], {"enabled": False})
        with patch("server.topics.now_ms", return_value=now_ms() + 2 * a.DAY):
            self.assertEqual(self.topics.refresh_due(), [])
        self.assertEqual(self.topics.run(item["id"])["state"], "Paused")

    def test_due_refresh_queues_once_and_keeps_current_evidence(self):
        self.asset()
        item = self.complete("nuclear energy")
        with patch("server.topics.now_ms", return_value=item["nextRefreshAt"] + 1):
            self.topics.refresh_due()
            self.topics.refresh_due()
        current = self.topics.get(item["id"])
        self.assertEqual(current["state"], "Queued")
        self.assertEqual(len(current["entries"]), 1)
        queued = [job for job in self.s.db.jobs("queued", 1000) if job["kind"] == "topic-research"]
        self.assertEqual(len(queued), 1)

    def test_actual_fetched_source_not_search_snippet_becomes_evidence(self):
        ai = FakeAI()
        url = "https://public.example/nuclear-energy"
        ai.sources = [{"url": url, "title": "Invented search title", "snippet": "Never source evidence"}]
        self.network.pages[url] = b"<html><head><title>Actual publisher title</title></head><body><p>A synthetic nuclear energy research project examines monitoring equipment. This is original page text for an offline test.</p></body></html>"
        self.s.ai, self.s.auto_ai = ai, True
        result = self.complete("nuclear energy")
        self.assertEqual(result["evidence"][0]["title"], "Actual publisher title")
        doc = self.s.db.get("document", result["evidence"][0]["id"])
        self.assertNotIn("Never source evidence", doc["text"])
        self.assertTrue(doc["publishedEstimated"])
        source = self.s.db.get("source", doc["sourceId"])
        self.assertFalse(source["enabled"])
        self.assertEqual(result["discoveryLinks"][0]["status"], "Original source retrieved; claims unverified")
        self.assertEqual(result["entries"], [])
        self.assertTrue(all(c["status"] == "Unverified" for c in self.s.db.latest("claim", 100)))

    def test_robots_denial_retains_only_discovery_link_without_ingestion(self):
        ai = FakeAI()
        ai.sources = [{"url": "https://public.example/blocked", "title": "Search context only"}]
        self.s.ai, self.s.auto_ai = ai, True
        result = self.complete("nuclear energy")
        self.assertEqual(self.s.db.count("document"), 0)
        self.assertTrue(result["discoveryLinks"][0]["discoveryOnly"])
        self.assertEqual(result["discoveryLinks"][0]["status"], "Collection disallowed by robots.txt")
        self.assertFalse(any(call[0] == "fetch" for call in self.network.calls))

    def test_ai_failure_keeps_deterministic_research_working(self):
        self.asset()
        ai = FakeAI()
        def fail(*_args, **_kwargs): raise RuntimeError("Fixture unavailable")
        ai.plan_topic = ai.discover_topic = ai.coordinate = ai.structured = fail
        self.s.ai, self.s.auto_ai = ai, True
        result = self.complete("nuclear energy")
        self.assertEqual(len(result["entries"]), 1)
        self.assertEqual(result["planMethod"], "Literal topic parsing")
        self.assertIn("unavailable", " ".join(result["limitations"]))

    def test_short_ai_topic_and_invalid_queries_are_handled(self):
        self.assertEqual(self.topics.create("AI")["query"], "AI")
        for query in ("", " ", "create a portfolio", "x", "z" * 1201):
            with self.assertRaises(ValueError): self.topics.create(query)
        with self.assertRaises(ValueError): self.topics.create({"query": "nuclear energy", "refreshMinutes": 1})

    def test_relevant_evidence_changes_coalesce_a_followup_without_paid_calls(self):
        asset_id, doc = self.asset()
        topic = self.complete("nuclear energy")
        initial_jobs = len(self.s.db.jobs("queued", 1000))
        changed_at = now_ms()
        with patch("server.topics.now_ms", return_value=changed_at):
            self.topics.evidence_changed(document_id=doc["id"])
        with patch("server.topics.now_ms", return_value=changed_at + 5000):
            self.topics.evidence_changed(asset_id=asset_id)
        current = self.topics.get(topic["id"])
        self.assertEqual(current["nextRefreshAt"], changed_at + 30000)
        self.assertEqual(len(self.s.db.jobs("queued", 1000)), initial_jobs)
        self.topics.configure(topic["id"], {"enabled": False})
        self.assertEqual(self.topics.evidence_changed(document_id=doc["id"]), [])

    def test_assessment_is_withheld_if_source_changes_while_ai_runs(self):
        _, doc = self.asset()
        ai = FakeAI()
        self.s.ai, self.s.auto_ai = ai, True
        def revise_during_ai(task, callback, max_rounds):
            current = self.s.db.get("document", doc["id"])
            self.s.ingest(self.source, {**current, "text": current["text"] + " A source correction was appended during investigation."})
            return {"facts": [{"text": "A stale source assertion"}]}
        ai.coordinate = revise_during_ai
        item = self.topics.create("nuclear energy")
        result = self.topics._assessment(item, [(doc, {"literal": True})], "offline-fingerprint")
        self.assertNotIn("assessment", result)
        self.assertIn("stale assessment was withheld", result["assessmentWarning"])

    def test_ingestion_consumed_during_research_does_not_trigger_another_refresh(self):
        asset_id, doc = self.asset()
        topic = self.complete("nuclear energy")
        original_refresh = self.topics._refresh_sources
        def collect_during_research(item, matched):
            current = self.s.db.get("document", doc["id"])
            updated = self.s.ingest(self.source, {**current, "text": current["text"] + " The supplier added monitoring equipment to its fixture catalog."})
            self.topics.evidence_changed(document_id=updated["id"])
            self.s.observation(self.market, {"assetId": asset_id, "metric": "price_usd", "value": 12,
                "observedAt": now_ms() - 1000, "unit": "USD", "currency": "USD", "frequency": "daily", "adjustment": "split-adjusted"})
            self.topics.evidence_changed(asset_id=asset_id)
            return [], []
        self.topics._refresh_sources = collect_during_research
        try: refreshed = self.topics.run(topic["id"])
        finally: self.topics._refresh_sources = original_refresh
        self.assertEqual(refreshed["pendingEvidenceChanges"], {})
        self.assertEqual(refreshed["nextRefreshAt"], refreshed["lastRunAt"] + refreshed["refreshMinutes"] * 60000)

    def test_source_revision_after_final_snapshot_retains_one_followup(self):
        _, doc = self.asset()
        topic = self.complete("nuclear energy")
        original_curate = self.topics._curate
        def revise_after_snapshot(item, matched):
            rows = original_curate(item, matched)
            current = self.s.db.get("document", doc["id"])
            updated = self.s.ingest(self.source, {**current, "text": current["text"] + " An additional correction arrived after the curation snapshot."})
            self.topics.evidence_changed(document_id=updated["id"])
            return rows
        self.topics._curate = revise_after_snapshot
        try: refreshed = self.topics.run(topic["id"])
        finally: self.topics._curate = original_curate
        self.assertTrue(refreshed["pendingEvidenceChanges"])
        self.assertLessEqual(refreshed["nextRefreshAt"], refreshed["lastRunAt"] + 30000)

    def research_document(self, text=None):
        return self.s.ingest(self.source, {"title": "Nuclear energy research bulletin", "url": "https://public.example/topic-report",
            "text": text or "Aurora Devices reports nuclear energy equipment demand. Civic Reserve describes financing conditions and interest-rate uncertainty.",
            "publishedAt": self.at, "entities": [{"id": "research:company:Aurora", "name": "Aurora Devices", "type": "company"},
                {"id": "research:institution:Civic", "name": "Civic Reserve", "type": "financial_institution"}]})

    def research_ai(self):
        ai = FakeAI()
        ai.subject_names = [("Aurora Devices", "company"), ("Civic Reserve", "financial_institution")]
        self.s.ai = ai
        return ai

    def test_manual_search_uses_openai_with_background_ai_off_and_no_market_data(self):
        self.research_document()
        ai = self.research_ai()
        self.s.auto_ai = False
        topic = self.complete("nuclear energy")
        self.assertEqual(topic["state"], "Monitoring")
        self.assertEqual(topic["entries"], [])
        self.assertEqual(self.s.db.count("asset"), 0)
        self.assertEqual(topic["marketResearch"]["method"], "OpenAI source research")
        self.assertEqual({r["name"] for r in topic["watchSubjects"]}, {"Aurora Devices", "Civic Reserve"})
        self.assertEqual(ai.assessments, 1)
        self.assertEqual(ai.plans, 1)
        self.assertIsNone(topic["manualAiRequest"])
        self.assertFalse(self.s.auto_ai)

    def test_scheduled_refresh_respects_background_ai_off_after_manual_search(self):
        doc = self.research_document()
        ai = self.research_ai()
        topic = self.complete("nuclear energy")
        self.s.ingest(self.source, {**doc, "text": doc["text"] + " The bulletin adds a new research update."})
        self.topics.refresh(topic["id"], manual=False)
        updated = self.topics.run(topic["id"])
        self.assertEqual(ai.assessments, 1)
        self.assertEqual(updated["marketResearch"]["method"], "Collected source research")
        self.assertIsNone(updated.get("manualAiRequest"))

    def test_duplicate_completed_search_retries_missing_ai_report_and_debounces_pending(self):
        self.research_document()
        ai = self.research_ai()
        original = ai.structured
        def fail(*_args, **_kwargs): raise RuntimeError("Offline synthesis unavailable")
        ai.structured = fail
        first = self.complete("nuclear energy")
        self.assertEqual(first["marketResearch"]["method"], "Collected source research")
        ai.structured = original
        retry = self.topics.create("Nuclear Energy")
        again = self.topics.create(" nuclear energy ")
        self.assertEqual(retry["id"], first["id"])
        self.assertNotEqual(retry["jobId"], first["jobId"])
        self.assertEqual(again["jobId"], retry["jobId"])
        result = self.topics.run(retry["id"])
        self.assertEqual(result["marketResearch"]["method"], "OpenAI source research")
        self.assertEqual(ai.assessments, 1)

    def test_watch_subject_followups_are_linked_and_source_corrections_remove_linkage(self):
        doc = self.research_document()
        self.research_ai()
        topic = self.complete("nuclear energy")
        followup = self.s.ingest(self.source, {"title": "Aurora Devices update", "text": "Aurora Devices describes a components production delay in its next supplier update.",
            "url": "https://public.example/company-update", "publishedAt": self.at})
        pending = self.topics.get(topic["id"])
        self.assertLess(pending["nextRefreshAt"], topic["nextRefreshAt"])
        self.assertIn(followup["id"], [d["id"] for d, _ in self.topics._matching_documents(pending)])
        self.s.ingest(self.source, {**doc, "text": "The nuclear energy bulletin corrects earlier company identification. No named company or financial institution is supported by this revised source."})
        result = self.topics.run(topic["id"])
        self.assertEqual(result["watchSubjects"], [])
        self.assertNotIn(followup["id"], [d["id"] for d in result["evidence"]])

    def test_stale_report_preserves_manual_ai_intent_for_a_fresh_followup(self):
        doc = self.research_document()
        ai = self.research_ai()
        original = ai.structured
        def revise_during_report(*args, **kwargs):
            report = original(*args, **kwargs)
            current = self.s.db.get("document", doc["id"])
            self.s.ingest(self.source, {**current, "text": current["text"] + " An updated source paragraph arrived during synthesis."})
            return report
        ai.structured = revise_during_report
        stale = self.complete("nuclear energy")
        self.assertIsNone(stale["marketResearch"])
        self.assertTrue(stale["marketResearchStale"])
        self.assertTrue(stale["manualAiRequest"])
        self.assertLessEqual(stale["nextRefreshAt"], stale["lastRunAt"] + 30000)
        ai.structured = original
        updated = self.topics.run(stale["id"])
        self.assertEqual(updated["marketResearch"]["method"], "OpenAI source research")
        self.assertIsNone(updated["manualAiRequest"])
        self.assertEqual(ai.assessments, 2)

    def test_report_is_revalidated_after_financial_cycle_before_publication(self):
        doc = self.research_document()
        self.research_ai()
        cycle = self.s.investments.cycle
        def revised_cycle(reason):
            result = cycle(reason)
            current = self.s.db.get("document", doc["id"])
            self.s.ingest(self.source, {**current, "text": current["text"] + " A source correction arrived after report generation."})
            return result
        self.s.investments.cycle = revised_cycle
        try: result = self.complete("nuclear energy")
        finally: self.s.investments.cycle = cycle
        self.assertIsNone(result["marketResearch"])
        self.assertEqual(result["watchSubjects"], [])
        self.assertTrue(result["manualAiRequest"])
        self.assertLessEqual(result["nextRefreshAt"], result["lastRunAt"] + 30000)

    def test_paused_monitor_allows_one_manual_research_without_resuming_background_work(self):
        self.research_document()
        ai = self.research_ai()
        first = self.complete("nuclear energy")
        self.topics.configure(first["id"], {"enabled": False})
        retry = self.topics.refresh(first["id"])
        self.assertTrue(retry["manualAiRequest"])
        result = self.topics.run(retry["id"])
        self.assertEqual(result["state"], "Paused")
        self.assertFalse(result["enabled"])
        self.assertIsNone(result["manualAiRequest"])
        self.assertEqual(result["marketResearch"]["method"], "OpenAI source research")
        self.assertEqual(ai.assessments, 1)

    def test_manual_request_arriving_during_scheduled_run_is_preserved(self):
        doc = self.research_document()
        ai = self.research_ai()
        first = self.complete("nuclear energy")
        self.s.ingest(self.source, {**doc, "text": doc["text"] + " The next source version adds a topic update."})
        queued = self.topics.refresh(first["id"], manual=False)
        original = self.topics._refresh_sources
        def request_during_refresh(item, matched):
            self.topics.refresh(item["id"], manual=True)
            return [], []
        self.topics._refresh_sources = request_during_refresh
        try: automatic = self.topics.run(first["id"])
        finally: self.topics._refresh_sources = original
        self.assertTrue(automatic["manualAiRequest"])
        self.assertEqual(ai.assessments, 1)
        self.assertLessEqual(automatic["nextRefreshAt"], automatic["lastRunAt"] + 1000)
        self.s.db.finish_job(queued["jobId"])
        manual = self.topics.run(first["id"])
        self.assertIsNone(manual["manualAiRequest"])
        self.assertEqual(manual["marketResearch"]["method"], "OpenAI source research")
        self.assertEqual(ai.assessments, 2)

    def test_empty_archive_surfaces_sanitized_planning_and_discovery_auth_errors(self):
        ai = self.research_ai()
        def rejected(*_args, **_kwargs):
            failure = RuntimeError("private-provider-response sk-secret-not-for-display")
            failure.status = 401
            raise failure
        ai.plan_topic = ai.discover_topic = rejected
        result = self.complete("nuclear energy")
        self.assertEqual(result["state"], "Needs evidence")
        self.assertEqual(result["evidence"], [])
        for key in ("planError", "discoveryError"):
            self.assertEqual(result[key]["errorCode"], "invalid_key")
            self.assertEqual(result[key]["status"], 401)
            self.assertIn("API key", result[key]["message"])
        self.assertNotIn("sk-secret", str(result))
        self.assertNotIn("private-provider-response", str(result))
        ai.plan_topic = FakeAI.plan_topic.__get__(ai)
        ai.discover_topic = FakeAI.discover_topic.__get__(ai)
        self.topics.refresh(result["id"])
        recovered = self.topics.run(result["id"])
        self.assertIsNone(recovered["planError"])
        self.assertIsNone(recovered["discoveryError"])

    def test_failed_web_search_is_actionable_cached_in_background_and_retried_manually(self):
        ai = self.research_ai()
        self.s.auto_ai = True
        attempts = []
        def unsupported(*_args, **_kwargs):
            attempts.append("failed")
            failure = RuntimeError("unsafe-provider-body sk-never-display")
            failure.status = 400
            raise failure
        ai.discover_topic = unsupported
        failed = self.complete("nuclear energy")
        self.assertEqual(failed["discoveryError"]["status"], 400)
        self.assertIn("web search", failed["discoveryError"]["message"])
        self.assertIn("feed", failed["discoveryError"]["message"])
        self.assertNotIn("sk-never", str(failed))
        self.topics.run(failed["id"])
        self.assertEqual(attempts, ["failed"])
        def corrected(*_args, **_kwargs):
            attempts.append("succeeded")
            return []
        ai.discover_topic = corrected
        self.topics.refresh(failed["id"])
        recovered = self.topics.run(failed["id"])
        self.assertEqual(attempts, ["failed", "succeeded"])
        self.assertIsNone(recovered["discoveryError"])
        self.topics.refresh(recovered["id"])
        self.topics.run(recovered["id"])
        self.assertEqual(attempts, ["failed", "succeeded"])


if __name__ == "__main__":
    unittest.main()
