"""Synthetic investigative networks, ownership isolation and saved layouts."""
from pathlib import Path
import copy
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.service import ResearchService
from server.storage import now_ms
from server.research_network import BoardConflict


class Offline:
    def fetch(self, *_args, **_kwargs): raise AssertionError("No external fixture requests")


class GraphAI:
    ready, model = True, "synthetic-network"
    def __init__(self, result): self.result, self.calls = result, 0
    def structured(self, name, schema, instructions, data):
        assert name == "investigative_network"
        self.calls += 1
        return copy.deepcopy(self.result)


class NetworkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.s = ResearchService(self.tmp.name, network=Offline(), seed=False, dsn="")
        self.s.auto_ai = False
        self.n = self.s.network_research
        self.source = self.s.add_source({"id": "fixture-wire", "name": "Fixture Wire", "kind": "rss", "url": "https://fixture.example/feed", "enabled": False})
        self.quote = "Orion Airworks manufactures the Kite drone. Morgan Vale owns Orion Airworks and Orion Sensors."
        self.doc = self.s.ingest(self.source, {"title": "Synthetic drone disclosure", "text": self.quote,
            "url": "https://fixture.example/disclosure", "publishedAt": now_ms() - 10000})
        self.topic = {"id": "topic-fixture-drones", "query": "Drones", "title": "Drones", "state": "Monitoring", "evidence": [self.doc], "entries": [], "candidates": [], "watchSubjects": [], "version": 1}
        self.s.db.put("topicPortfolio", self.topic["id"], self.topic)
        cite = {"documentId": self.doc["id"], "version": 1, "quote": self.quote}
        self.result = {"entities": [{"ref": ref, "name": name, "type": kind, "evidence": [cite], "attributes": []} for ref, name, kind in
            (("company", "Orion Airworks", "company"), ("owner", "Morgan Vale", "person"), ("other", "Orion Sensors", "company"), ("product", "Kite", "product"))],
            "relationships": [{"from": "company", "to": "owner", "type": "owned_by", "claim": self.quote, "evidence": [cite]},
                              {"from": "product", "to": "company", "type": "manufactured_by", "claim": self.quote, "evidence": [cite]}],
            "questions": [{"entityRef": "company", "question": "Which public supplier agreements have been disclosed?"}]}
        self.s.ai = GraphAI(self.result)

    def tearDown(self):
        self.s.close()
        self.tmp.cleanup()

    def board(self, owner="alice"):
        self.n.build(self.topic["id"], True)
        return self.n.create_board(owner, {"topicId": self.topic["id"]})

    def test_manufacturer_and_ownership_are_source_backed_and_reported(self):
        graph = self.n.build(self.topic["id"], True)
        self.assertTrue(any(e["type"] == "manufactured_by" for e in graph["edges"]))
        self.assertTrue(any(e["type"] == "owned_by" for e in graph["edges"]))
        self.assertFalse(any(e["status"] == "Verified" for e in graph["edges"]))
        self.assertFalse(any(n.get("ticker") or n.get("assetId") for n in graph["nodes"]))
        self.assertTrue(any(n["type"] == "question" for n in graph["nodes"]))

    def test_automatic_discovery_is_bounded_and_stops_when_ai_is_disabled(self):
        self.s.auto_ai = True
        detail = self.board()
        tasks = detail["tasks"]
        self.assertTrue(tasks)
        self.assertLessEqual(len(tasks), 2)
        self.assertTrue(all(task["automatic"] and task["depth"] == 2 for task in tasks))
        self.assertEqual(len(self.n.create_board("alice", {"topicId": self.topic["id"]})["tasks"]), len(tasks))
        self.s.auto_ai = False
        for task in tasks:
            self.assertEqual(self.n.run_task(task["id"])["status"], "Paused")
            self.assertNotIn("childTopicId", self.s.db.get("researchTask", task["id"]))

    def test_common_ownership_does_not_admit_an_unsupported_supplier_link(self):
        self.result["relationships"].append({**self.result["relationships"][0], "from": "company", "to": "other", "type": "supplied_by"})
        graph = self.n.build(self.topic["id"], True)
        self.assertFalse(any(e["type"] == "supplied_by" for e in graph["edges"]))
        self.assertEqual(graph["rejectedAssertions"], 1)

    def test_denied_supplier_statement_is_not_an_affirmative_edge(self):
        self.quote = "Orion Sensors does not supply Orion Airworks."
        self.doc = self.s.ingest(self.source, {**self.doc, "text": self.quote})
        cite = {"documentId": self.doc["id"], "version": self.doc["version"], "quote": self.quote}
        self.result["entities"] = [{"ref": ref, "name": name, "type": "company", "evidence": [cite], "attributes": []}
            for ref, name in (("company", "Orion Airworks"), ("other", "Orion Sensors"))]
        self.result["relationships"] = [{"from": "company", "to": "other", "type": "supplied_by", "claim": self.quote, "evidence": [cite]}]
        graph = self.n.build(self.topic["id"], True)
        self.assertFalse(any(edge["type"] == "supplied_by" for edge in graph["edges"]))

    def test_fetched_page_byline_is_credited_without_organization_or_recommendation_inference(self):
        from server.topics import _PageTitle
        parser = _PageTitle()
        parser.feed('<title>Original story</title><meta name="author" content="Mira Lee"><meta property="article:published_time" content="2026-01-01T12:00:00Z">'
            '<script type="application/ld+json">{"@graph":[{"@type":"NewsArticle","author":[{"@type":"Person","name":"Mira Lee"}]},'
            '{"@type":"Organization","name":"Publisher","author":"Unrelated Name"}]}</script>')
        self.assertEqual(parser.authors, ["Mira Lee"])
        self.assertEqual(parser.published, "2026-01-01T12:00:00Z")

    def test_atom_multiple_bylines_retain_names_without_concatenated_emails(self):
        from server.connectors import feed_records
        records = feed_records(b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Original drone story</title>'
            b'<link href="https://fixture.example/story"/><author><name>Mira Lee</name><email>not-a-name@example.test</email></author>'
            b'<author><name>Ravi Chen</name></author><summary>A drone company disclosure.</summary></entry></feed>', {})
        self.assertEqual(records[0]["authors"], ["Mira Lee", "Ravi Chen"])

    def test_unsupported_entity_and_numeric_attribute_are_withheld(self):
        self.result["entities"].append({"ref": "fake", "name": "Invented Lender", "type": "financial_institution", "evidence": self.result["entities"][0]["evidence"], "attributes": []})
        self.result["entities"][0]["attributes"] = [{"field": "Revenue", "value": "999 billion USD", "evidence": self.result["entities"][0]["evidence"]}]
        graph = self.n.build(self.topic["id"], True)
        self.assertFalse(any(n["label"] == "Invented Lender" for n in graph["nodes"]))
        self.assertEqual(next(n for n in graph["nodes"] if n["label"] == "Orion Airworks")["attributes"], [])

    def test_wrong_source_version_cannot_supply_entities_or_edges(self):
        for item in self.result["entities"]: item["evidence"][0]["version"] = 99
        graph = self.n.build(self.topic["id"], True)
        self.assertFalse(any(n["type"] == "company" for n in graph["nodes"]))

    def test_bylines_are_preserved_per_article_and_missing_author_stays_missing(self):
        second_source = self.s.add_source({"id": "fixture-business", "name": "Fixture Business", "kind": "rss", "url": "https://business.example/feed", "enabled": False})
        other = self.s.ingest(second_source, {"title": "Separate drone report", "text": "Orion Airworks has disclosed a drone product.", "url": "https://business.example/article", "authors": ["Mira Lee"]})
        self.topic["evidence"].append(other)
        self.s.db.put("topicPortfolio", self.topic["id"], self.topic)
        graph = self.n.build(self.topic["id"])
        bylines = [e for e in graph["edges"] if e["type"] == "authored_by"]
        self.assertEqual(len(bylines), 1)
        self.assertEqual(bylines[0]["from"], "network-" + other["id"])
        self.assertEqual(next(n for n in graph["nodes"] if n["id"] == "network-" + self.doc["id"])["authors"], [])

    def test_author_correction_creates_source_revision(self):
        first = self.s.ingest(self.source, {**self.doc, "authors": ["First Author"]})
        second = self.s.ingest(self.source, {**first, "authors": ["Correct Author"]})
        self.assertEqual(second["version"], first["version"] + 1)
        self.assertEqual(second["authors"][0]["name"], "Correct Author")

    def test_review_requires_current_evidence_and_source_revision_invalidates_review(self):
        detail = self.board()
        edge = next(e for e in detail["graph"]["edges"] if e["type"] == "owned_by")
        reviewed = self.n.review_edge(edge["id"], "owner", "Verified", "Reviewed the original public ownership disclosure.")
        self.assertTrue(reviewed["lastVerifiedAt"])
        self.assertEqual(next(e for e in self.n.board("alice", detail["board"]["id"])["graph"]["edges"] if e["id"] == edge["id"])["status"], "Verified")
        self.s.ingest(self.source, {**self.doc, "text": self.quote + " A correction has been appended."})
        stale = next(e for e in self.n.board("alice", detail["board"]["id"])["graph"]["edges"] if e["id"] == edge["id"])
        self.assertEqual(stale["status"], "Review required")
        self.assertIsNone(stale["lastVerifiedAt"])
        with self.assertRaises(ValueError): self.n.review_edge(edge["id"], "owner", "Verified", "Attempt to reuse stale source evidence.")

    def test_private_boards_reject_another_owner_everywhere(self):
        detail = self.board()
        board = detail["board"]
        self.assertEqual(self.n.list_boards("bob"), [])
        for action in (lambda: self.n.board("bob", board["id"]), lambda: self.n.save_board("bob", {"id": board["id"], "baseVersion": 1}), lambda: self.n.board_action("bob", {"id": board["id"], "action": "delete"})):
            with self.assertRaises(ValueError): action()

    def test_personal_nodes_and_edges_cannot_promote_claims_or_mutate_canonical_graph(self):
        detail = self.board()
        root = detail["graph"]["rootId"]
        original = copy.deepcopy(detail["graph"])
        saved = self.n.save_board("alice", {"id": detail["board"]["id"], "baseVersion": 1,
            "manualNodes": [{"id": "manual-test", "label": "My supplier hypothesis", "type": "company", "status": "Verified", "origin": "system"}],
            "manualEdges": [{"id": "manual-link", "from": root, "to": "manual-test", "type": "supplied_by", "status": "Verified", "claim": "Personal hypothesis", "citations": ["https://fixture.example/disclosure"]}]})
        self.assertEqual(saved["board"]["manualNodes"][0]["status"], "User assertion")
        self.assertEqual(saved["board"]["manualEdges"][0]["evidence"], [])
        self.assertEqual(saved["graph"]["nodes"], original["nodes"])
        self.assertFalse(self.s.db.get("networkEntity", "manual-test"))

    def test_layout_notes_and_expansion_state_restore_across_new_service_instances(self):
        detail = self.board()
        board_id, root = detail["board"]["id"], detail["graph"]["rootId"]
        saved = self.n.save_board("alice", {"id": board_id, "baseVersion": 1, "layout": {root: {"x": 123, "y": -55}}, "notes": {root: "My private observation"}, "pinned": [root], "collapsed": [root], "viewport": {"x": 50, "y": 60, "zoom": .7}})
        other = ResearchService(self.tmp.name, network=Offline(), seed=False, dsn="")
        try:
            reopened = other.network_research.board("alice", board_id)["board"]
            self.assertEqual(reopened["layout"], saved["board"]["layout"])
            self.assertEqual(reopened["notes"][root], "My private observation")
            self.assertEqual(reopened["viewport"]["zoom"], .7)
            self.assertEqual(reopened["collapsed"], [root])
        finally: other.close()

    def test_stale_saves_fail_instead_of_overwriting_another_session(self):
        detail = self.board()
        self.n.save_board("alice", {"id": detail["board"]["id"], "baseVersion": 1, "title": "First save"})
        with self.assertRaises(BoardConflict): self.n.save_board("alice", {"id": detail["board"]["id"], "baseVersion": 1, "title": "Lost update"})

    def test_duplicate_and_revision_restore_keep_personal_edits(self):
        detail = self.board()
        board_id = detail["board"]["id"]
        self.n.save_board("alice", {"id": board_id, "baseVersion": 1, "notes": {"note": "Original note"}, "folder": "Supply research"})
        duplicate = self.n.board_action("alice", {"id": board_id, "action": "duplicate"})
        self.assertEqual(duplicate["board"]["notes"]["note"], "Original note")
        self.n.save_board("alice", {"id": board_id, "baseVersion": 2, "notes": {"note": "Changed note"}})
        restored = self.n.board_action("alice", {"id": board_id, "action": "restore", "version": 2})
        self.assertEqual(restored["board"]["notes"]["note"], "Original note")
        self.assertEqual(restored["board"]["version"], 4)

    def test_source_updates_preserve_layout_and_notes_and_notify_owner(self):
        detail = self.board()
        board_id, root = detail["board"]["id"], detail["graph"]["rootId"]
        self.n.save_board("alice", {"id": board_id, "baseVersion": 1, "layout": {root: {"x": 22, "y": 33}}, "notes": {root: "Retain my context"}})
        revised = self.s.ingest(self.source, {**self.doc, "text": self.quote + " More corporate information was disclosed."})
        self.topic["evidence"] = [revised]
        self.s.db.put("topicPortfolio", self.topic["id"], self.topic)
        self.n.build(self.topic["id"])
        board = self.n.board("alice", board_id)["board"]
        self.assertEqual(board["layout"][root]["x"], 22)
        self.assertEqual(board["notes"][root], "Retain my context")
        self.assertTrue(self.n.personal("alice")["notifications"])
        self.assertEqual(self.n.personal("bob")["notifications"], [])

    def test_private_company_portfolio_has_reason_and_graph_links_without_market_price(self):
        detail = self.board()
        node = next(n for n in detail["graph"]["nodes"] if n["label"] == "Orion Airworks")
        portfolio = self.n.portfolio("alice", {"title": "Drone companies", "boardId": detail["board"]["id"], "nodeId": node["id"], "reason": "Follow disclosed ownership"})
        self.assertEqual(portfolio["items"][0]["reason"], "Follow disclosed ownership")
        self.assertIsNone(portfolio["items"][0]["assetId"])
        self.assertNotIn("price", portfolio["items"][0])
        with self.assertRaises(ValueError): self.n.portfolio("bob", {"id": portfolio["id"], "title": "Stolen"})

    def test_canonical_ids_are_shared_but_layouts_are_private(self):
        alice, bob = self.board(), self.board("bob")
        self.assertEqual({n["id"] for n in alice["graph"]["nodes"]}, {n["id"] for n in bob["graph"]["nodes"]})
        self.n.save_board("alice", {"id": alice["board"]["id"], "baseVersion": 1, "notes": {"private": "Alice only"}})
        self.assertEqual(self.n.board("bob", bob["board"]["id"])["board"]["notes"], {})

    def test_task_queue_deduplicates_and_pause_cancel_prevent_provider_work(self):
        detail = self.board()
        values = {"boardId": detail["board"]["id"], "nodeId": detail["graph"]["rootId"], "focus": "ownership"}
        task = self.n.request_task("alice", values)
        self.assertEqual(task["id"], self.n.request_task("alice", values)["id"])
        count = self.s.ai.calls
        self.n.board_action("alice", {"id": detail["board"]["id"], "action": "pause"})
        self.assertEqual(self.n.run_task(task["id"])["status"], "Paused")
        self.assertEqual(self.s.ai.calls, count)
        self.n.board_action("alice", {"id": detail["board"]["id"], "action": "cancel"})
        self.assertEqual(self.n.run_task(task["id"])["status"], "Cancelled")
        with self.assertRaises(ValueError): self.n.request_task("alice", {**values, "depth": 4})
        with self.assertRaises(ValueError): self.n.request_task("alice", {**values, "automatic": True})

    def test_inspection_preserves_claim_history_and_private_company_data_gaps(self):
        detail = self.board()
        node = next(n for n in detail["graph"]["nodes"] if n["label"] == "Orion Airworks")
        inspected = self.n.inspect("alice", detail["board"]["id"], node["id"])
        self.assertTrue(inspected["claims"])
        self.assertIsNone(inspected["financialProfile"])
        self.assertTrue(inspected["sourceHistory"])

    def test_delete_personal_data_leaves_other_users_and_public_evidence_intact(self):
        alice, bob = self.board(), self.board("bob")
        self.n.save_board("alice", {"id": alice["board"]["id"], "baseVersion": 1, "notes": {"private": "Delete this"}})
        self.n.delete_personal("alice")
        self.assertEqual(self.n.list_boards("alice"), [])
        self.assertFalse(any(r["ownerId"] == "alice" for r in self.s.db.latest("boardRevision", 100)))
        self.assertTrue(self.n.board("bob", bob["board"]["id"]))
        self.assertTrue(self.s.db.get("document", self.doc["id"]))


if __name__ == "__main__": unittest.main()
