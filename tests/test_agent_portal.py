"""Deterministic progress, owner isolation, evidence organization and worker lanes."""
import tempfile
import threading
import unittest
from unittest.mock import patch

from server.activity import JobInterrupted
from server.service import ResearchService
from server.storage import now_ms


class AgentPortalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.s = ResearchService(self.tmp.name, seed=False, dsn="")
        self.source = self.s.add_source({"id": "fixture", "name": "Synthetic source", "kind": "rss", "url": "https://example.test/feed", "enabled": True})
        self.topic = self.s.topics.create("synthetic batteries")
        self.board = self.s.network_research.create_board("alice", {"topicId": self.topic["id"]})["board"]
        self.board_id = self.board["id"]

    def tearDown(self):
        self.s.close()
        self.tmp.cleanup()

    def article(self, slug, text):
        return self.s.ingest(self.source, {"title": "Synthetic " + slug, "text": text, "url": "https://example.test/" + slug})

    def seeded_portfolio(self):
        asset = {"id": "equity:fixture:acme", "name": "Acme Power", "ticker": "ACME", "assetClass": "equity", "identityVerified": True}
        self.s.db.put("asset", asset["id"], asset)
        self.s.db.put("researchPortfolio", "user-portfolio", {"id": "user-portfolio", "ownerId": "alice", "title": "My interests", "items": [{"assetId": asset["id"], "nodeId": "my-node", "boardId": self.board_id}]})
        return asset

    def test_live_progress_reports_completed_stages_and_completes_only_after_work(self):
        ready, release = threading.Event(), threading.Event()
        job_id = self.s.db.enqueue("fixture", {"ownerId": "alice", "boardId": self.board_id})
        job = self.s.db.claim_job(kinds=("fixture",))
        def work(_job):
            self.s.activity.report("Checking original source versions", 1, 4, completed_items=2, total_items=8)
            ready.set()
            release.wait(3)
        with patch.object(self.s, "_execute_job", side_effect=work):
            thread = threading.Thread(target=self.s.run_job, args=(job,))
            thread.start()
            try:
                self.assertTrue(ready.wait(2))
                row = next(r for r in self.s.activity.feed("alice", self.board_id)["tasks"] if r["id"] == job_id)
                self.assertEqual((row["status"], row["percent"]), ("Running", 25))
                self.assertEqual(row["events"][-1]["completedItems"], 2)
                with self.assertRaises(ValueError): self.s.activity.feed("bob", self.board_id)
            finally:
                release.set(); thread.join(3)
        self.assertEqual(self.s.db.get("taskProgress", job_id)["percent"], 100)

    def test_failed_and_time_budget_attempts_never_report_completion(self):
        job_id = self.s.db.enqueue("fixture", {"ownerId": "alice", "boardId": self.board_id})
        job = self.s.db.claim_job(kinds=("fixture",))
        def work(_job):
            self.s.activity.report("Checking sources", 1, 4)
            self.s.activity.local.started -= self.s.activity.budget_seconds + 1
            self.s.activity.check()
        with patch.object(self.s, "_execute_job", side_effect=work), self.assertRaises(JobInterrupted): self.s.run_job(job)
        value = self.s.db.get("taskProgress", job_id)
        self.assertEqual(value["status"], "Retrying")
        self.assertEqual(value["percent"], 25)
        self.assertFalse(any(e["percent"] == 100 for e in value["events"]))

    def test_recommendation_reads_expose_queue_and_real_assessment_progress(self):
        pending = self.s.recommendations.view("alice", self.board_id)
        self.assertEqual(pending["progress"]["percent"], 0)
        job = self.s.db.claim_job(kinds=("recommendation-review",))
        self.s.run_job(job); self.s.db.finish_job(job["id"])
        progress = self.s.db.get("taskProgress", job["id"])
        self.assertEqual(progress["percent"], 100)
        self.assertIn("Screening collected topic and branch evidence", [e["message"] for e in progress["events"]])
        self.assertFalse(self.s.recommendations.view("alice", self.board_id)["refreshing"])

    def test_organization_follows_verified_portfolio_assets_and_is_idempotent(self):
        asset = self.seeded_portfolio()
        doc = self.article("asset", "Acme Power reports a new synthetic battery manufacturing investment.")
        self.article("ticker-only", "ACME price rumor without an identified company.")
        self.s.db.put("asset", "unverified", {"id": "unverified", "name": "Rumor Token", "assetClass": "crypto", "identityVerified": False})
        self.s.organizer.run("alice", self.board_id)
        data = self.s.organizer.personal("alice")
        self.assertEqual([r["documentId"] for r in data["watchlists"][0]["articles"]], [doc["id"]])
        generated = [p for p in self.s.db.matching("researchPortfolio", "ownerId", "alice") if p.get("createdBy")]
        favorites = [i for p in generated for i in p["items"]]
        self.assertEqual([i["assetId"] for i in favorites], [asset["id"]])
        self.assertTrue(favorites[0]["favorite"])
        self.assertEqual(favorites[0]["evidence"][0]["quote"], "Acme Power")
        actions = self.s.db.count("agentAction")
        self.s.organizer.run("alice", self.board_id)
        self.assertEqual(self.s.db.count("agentAction"), actions)
        self.assertEqual(self.s.organizer.personal("bob")["watchlists"], [])
        self.assertTrue(self.s.db.verify_audit()["valid"])

    def test_changed_evidence_withdraws_tags_favorites_and_emits_monitor_notice(self):
        self.seeded_portfolio()
        doc = self.article("changed", "Acme Power reports synthetic battery costs.")
        self.s.organizer.run("alice", self.board_id)
        self.article("changed", "Correction: this report concerns an unrelated private company.")
        self.s.organizer.run("alice", self.board_id)
        data = self.s.organizer.personal("alice")
        self.assertFalse(data["articleTags"])
        self.assertEqual(data["watchlists"][0]["articles"], [])
        self.assertTrue(self.s.db.matching("researchNotification", "ownerId", "alice"))
        self.assertTrue(all(not p["items"] for p in self.s.db.matching("researchPortfolio", "ownerId", "alice") if p.get("createdBy")))

    def test_undo_is_owner_scoped_and_does_not_recreate_the_action(self):
        self.seeded_portfolio(); self.article("undo", "Acme Power supplies synthetic batteries.")
        self.s.organizer.run("alice", self.board_id)
        action = next(a for a in self.s.db.matching("agentAction", "ownerId", "alice") if a["kind"] == "researchWatchlist")
        with self.assertRaises(ValueError): self.s.organizer.undo("bob", action["id"])
        self.s.organizer.undo("alice", action["id"])
        self.s.organizer.run("alice", self.board_id)
        self.assertIsNone(self.s.db.get("researchWatchlist", action["targetId"]))
        self.assertTrue(self.s.db.verify_audit()["valid"])

    def test_user_edits_and_pause_are_respected(self):
        self.seeded_portfolio(); self.article("edit", "Acme Power supplies synthetic batteries.")
        self.s.organizer.run("alice", self.board_id)
        action = next(a for a in self.s.db.matching("agentAction", "ownerId", "alice") if a["kind"] == "researchPortfolio")
        self.s.network_research.portfolio("alice", {"id": action["targetId"], "title": "My edited title"})
        with self.assertRaises(ValueError): self.s.organizer.undo("alice", action["id"])
        self.s.organizer.run("alice", self.board_id)
        self.assertEqual(self.s.db.get("researchPortfolio", action["targetId"])["title"], "My edited title")
        self.s.organizer.policy("alice", self.board_id, enabled=False)
        self.assertFalse(self.s.organizer.queue("alice", self.board_id)["queued"])

    def test_source_changes_during_scan_withhold_all_organization(self):
        self.seeded_portfolio(); self.article("race", "Acme Power reports synthetic batteries.")
        original = self.s.db.scan
        def scan(kind, *args, **kwargs):
            for row in original(kind, *args, **kwargs):
                yield row
                if kind == "document": self.s.toggle_source(self.source["id"], False)
        with patch.object(self.s.db, "scan", side_effect=scan): self.s.organizer.run("alice", self.board_id)
        self.assertEqual(self.s.db.count("agentAction"), 0)

    def test_unchanged_inputs_do_not_schedule_repeated_archive_scans(self):
        self.seeded_portfolio(); self.article("stable", "Acme Power reports synthetic batteries.")
        self.s.organizer.run("alice", self.board_id)
        state = self.s.db.get("agentOrganizationJob", self.board_id)
        self.s.db.put("agentOrganizationJob", self.board_id, {**state, "checkedAt": now_ms()-120000})
        self.assertEqual(self.s.organizer.queue_due(), [])
        self.article("new", "Acme Power publishes another synthetic report.")
        self.assertTrue(self.s.organizer.queue_due())

    def test_personal_deletion_removes_agent_records_and_keeps_other_owners(self):
        self.seeded_portfolio(); self.article("delete", "Acme Power reports synthetic batteries.")
        self.s.organizer.run("alice", self.board_id)
        self.s.db.put("researchTag", "bob-tag", {"id": "bob-tag", "ownerId": "bob", "active": True})
        self.s.network_research.delete_personal("alice")
        for kind in ("researchPortfolio", "researchWatchlist", "researchMonitor", "researchTag", "agentAction", "agentPolicy", "agentOrganizationJob"):
            self.assertFalse([r for r in self.s.db.scan(kind) if r.get("ownerId") == "alice"], kind)
        self.assertIsNotNone(self.s.db.get("researchTag", "bob-tag"))

    def test_collection_runs_while_analysis_is_occupied(self):
        analysis_started, release, collected = threading.Event(), threading.Event(), threading.Event()
        def execute(job):
            if job["kind"] == "recommendation-review": analysis_started.set(); release.wait(4)
            elif job["kind"] == "poll": collected.set()
        self.s.db.enqueue("recommendation-review", {"ownerId": "alice", "boardId": self.board_id})
        with patch.object(self.s, "_execute_job", side_effect=execute):
            self.s.start(2)
            try:
                self.assertTrue(analysis_started.wait(2))
                self.s.db.enqueue("poll", {"sourceId": self.source["id"]})
                self.assertTrue(collected.wait(2), "Collection starved behind an analysis job")
            finally: release.set(); self.s.close()
