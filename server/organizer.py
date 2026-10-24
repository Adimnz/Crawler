"""Owner-scoped, evidence-grounded research organization with reversible actions."""
from __future__ import annotations

import hashlib
import re
import threading

from .storage import dumps, identifier, now_ms


def stable(*parts):
    return "agent-" + hashlib.sha256(dumps(parts).encode()).hexdigest()[:28]


def fingerprint(value):
    return hashlib.sha256(dumps(value).encode()).hexdigest()


class AgentOrganizer:
    def __init__(self, service):
        self.s, self.db = service, service.db
        self.lock = threading.RLock()

    def _signature(self, board):
        return fingerprint([self.s.last_write, [self.db.kind_revisions.get(k, 0) for k in
                            ("sourceConfiguration", "asset", "researchPortfolio", "networkGraph")], board.get("branchTopics", [])])

    def policy(self, owner, board_id, enabled=None):
        self.s.network_research._owned("researchBoard", board_id, owner)
        key = stable(owner, board_id, "policy")
        value = self.db.get("agentPolicy", key) or {"id": key, "ownerId": owner, "boardId": board_id, "enabled": True}
        if enabled is not None:
            value.update(enabled=enabled is True, updatedAt=now_ms())
            self.db.put("agentPolicy", key, value)
            self.db.audit("Agent organization policy changed", board_id, {"ownerId": owner, "enabled": value["enabled"]})
        return value

    def queue(self, owner, board_id):
        board = self.s.network_research._owned("researchBoard", board_id, owner)
        if board.get("archived") or board.get("expansionState") != "running" or not self.policy(owner, board_id)["enabled"]:
            return {"queued": False, "message": "Resume this board and enable agent organization first."}
        with self.lock:
            prior = self.db.get("agentOrganizationJob", board_id) or {}
            job = self.db.get_job(prior.get("jobId", ""))
            if job and job["state"] in {"queued", "running"}: return {"queued": True, "jobId": job["id"]}
            job_id = self.db.enqueue("agent-organize", {"ownerId": owner, "boardId": board_id}, identifier("organize"))
            self.db.put("agentOrganizationJob", board_id, {"id": board_id, "ownerId": owner, "jobId": job_id})
            return {"queued": True, "jobId": job_id}

    def queue_due(self):
        states = {r["id"]: r for r in self.db.scan("agentOrganizationJob")}
        boards = sorted(self.db.scan("researchBoard"), key=lambda b: states.get(b["id"], {}).get("checkedAt", 0))
        queued = []
        for board in boards:
            prior = states.get(board["id"], {})
            if now_ms() - prior.get("checkedAt", 0) < 60000: continue
            if prior.get("inputSignature") == self._signature(board): continue
            result = self.queue(board["ownerId"], board["id"])
            if result["queued"]: queued.append(result["jobId"])
            if len(queued) == 4: break
        return queued

    def _change(self, kind, value, reason, evidence):
        key = value["id"]
        before = self.db.get(kind, key)
        if before and (before.get("agentManaged") is False or before.get("createdBy") != "research-agent"): return False
        marker = self.db.get("agentSuppression", stable(value["ownerId"], kind, key))
        if marker: return False
        value = {**value, "createdBy": "research-agent", "agentManaged": True}
        if before == value: return False
        action_id = identifier("agent-action")
        # Record intent first: an interrupted mutation is still attributable in the hash chain.
        audit = self.db.audit("Research agent organization", key, {"ownerId": value["ownerId"], "boardId": value["boardId"],
                              "actionId": action_id, "kind": kind, "reason": reason, "evidence": evidence})
        self.db.put(kind, key, value)
        self.db.put("agentAction", action_id, {"id": action_id, "ownerId": value["ownerId"], "boardId": value["boardId"],
                    "kind": kind, "targetId": key, "reason": reason, "evidence": evidence, "at": now_ms(),
                    "auditHash": audit["entry_hash"], "before": before, "afterFingerprint": fingerprint(value), "undone": False})
        return True

    def undo(self, owner, action_id):
        with self.lock:
            action = self.s.network_research._owned("agentAction", action_id, owner)
            if action.get("undone"): return {"undone": True}
            current = self.db.get(action["kind"], action["targetId"])
            if fingerprint(current) != action["afterFingerprint"]:
                raise ValueError("This record changed after the agent action. Review the newer action before undoing it.")
            self.db.audit("Research agent action undone", action["targetId"], {"ownerId": owner, "actionId": action_id})
            if action["before"] is None: self.db.delete(action["kind"], action["targetId"])
            else: self.db.put(action["kind"], action["targetId"], action["before"])
            self.db.put("agentSuppression", stable(owner, action["kind"], action["targetId"]), {"id": stable(owner, action["kind"], action["targetId"]), "ownerId": owner})
            action.update(undone=True, undoneAt=now_ms())
            self.db.put("agentAction", action_id, action)
            return {"undone": True}

    def run(self, owner, board_id):
        board = self.s.network_research._owned("researchBoard", board_id, owner)
        if board.get("archived") or board.get("expansionState") != "running" or not self.policy(owner, board_id)["enabled"]: return
        input_signature = self._signature(board)
        self.s.activity.report("Reviewing the board and your watch portfolios", 0, 4)
        topic_ids = [board["topicId"]] + board.get("branchTopics", [])[:30]
        topics = [self.db.get("topicPortfolio", tid) or {} for tid in topic_ids]
        graphs = [self.db.get("networkGraph", tid) or {} for tid in topic_ids]
        refs = {}
        candidates = {}
        for graph in graphs:
            for node in graph.get("nodes", []):
                if node.get("assetId"): candidates.setdefault(node["assetId"], []).extend(node.get("evidence", []))
                for ref in node.get("evidence", []): refs[ref["documentId"]] = ref
        for topic in topics:
            for entry in topic.get("entries", []) + topic.get("candidates", []):
                candidates.setdefault(entry["assetId"], []).extend(entry.get("topicMatch", []))
            for ref in topic.get("evidence", []): refs[ref["id"]] = {"documentId": ref["id"], "version": ref["version"]}
        # User portfolios can direct collection relevance; asset identities must already be verified.
        for portfolio in self.db.matching("researchPortfolio", "ownerId", owner, 1000):
            if portfolio.get("archived") or portfolio.get("createdBy") == "research-agent": continue
            for item in portfolio.get("items", []):
                if item.get("assetId"): candidates.setdefault(item["assetId"], [])
        assets = {aid: self.db.get("asset", aid) for aid in candidates}
        assets = {aid: asset for aid, asset in assets.items() if asset and asset.get("identityVerified") and asset.get("assetClass") in {"equity", "crypto"}}
        sources = {s["id"]: s for s in self.db.scan("source")}
        documents, asset_evidence = {}, {aid: [] for aid in assets}
        self.s.activity.report("Finding articles linked to sourced research and watched assets", 1, 4)
        for index, doc in enumerate(self.db.scan("document")):
            if index % 64 == 0: self.s.activity.check()
            if not sources.get(doc.get("sourceId"), {}).get("enabled") or doc.get("retracted") or doc.get("removed"): continue
            ref = refs.get(doc["id"])
            matched = []
            for aid, asset in assets.items():
                name = str(asset.get("name", "")).strip()
                # Names, not ambiguous ticker substrings, support article relevance.
                name_match = re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", doc.get("text", ""), re.I) if len(name) >= 4 else None
                named = bool(name_match)
                issuer = bool(asset.get("cik") and str(doc.get("companyId", "")).lstrip("0") == str(asset["cik"]).lstrip("0"))
                if named or issuer and doc.get("text"):
                    matched.append(aid)
                    asset_evidence[aid].append({"documentId": doc["id"], "version": doc["version"], "sourceId": doc["sourceId"], "quote": name_match.group(0) if named else doc.get("text", "")[:300]})
            if matched or ref and ref.get("version") == doc["version"]:
                documents[doc["id"]] = {"documentId": doc["id"], "version": doc["version"], "title": doc.get("title"), "url": doc.get("url"),
                    "source": doc.get("source"), "publishedAt": doc.get("publishedAt"), "assetIds": matched,
                    "reason": "Names a portfolio instrument" if matched else "Cited by this topic's research"}
        # Recheck the policy after collection, so a pause during a scan takes effect.
        with self.lock:
            board = self.s.network_research._owned("researchBoard", board_id, owner)
            if board.get("expansionState") != "running" or board.get("archived") or not self.policy(owner, board_id)["enabled"]: return
            if self._signature(board) != input_signature:
                self.s.activity.report("Source inputs changed during screening; organization will be reassessed", 2, 4)
                return
            self.s.activity.report("Organizing cited articles and verified asset favorites", 2, 4)
            base = {"ownerId": owner, "boardId": board_id}
            evidence = [{"documentId": d["documentId"], "version": d["version"]} for d in documents.values()][:200]
            reading = sorted(documents.values(), key=lambda d: (d.get("publishedAt") or 0, d["documentId"]), reverse=True)[:200]
            version_fingerprint = fingerprint(sorted((d["documentId"], d["version"]) for d in documents.values()))
            # A watch portfolio holds research interests; quantities, orders and returns are never inferred.
            for asset_class, title in (("equity", "Stocks"), ("crypto", "Crypto")):
                items = [{"nodeId": "network-instrument-" + aid, "assetId": aid, "label": asset["name"], "type": "instrument", "boardId": board_id,
                          "favorite": True, "reason": "Source-linked research interest; investment eligibility is assessed separately",
                          "evidence": asset_evidence[aid][:12]} for aid, asset in assets.items() if asset["assetClass"] == asset_class and asset_evidence[aid]]
                key = stable(owner, board_id, asset_class)
                if items or self.db.get("researchPortfolio", key):
                    self._change("researchPortfolio", {**base, "id": key, "title": title+" · "+board["title"],
                        "description": "Agent research watch portfolio. No position or buy instruction is implied.", "folder": "Agent research", "items": items}, "Grouped source-linked "+asset_class+" research interests", evidence)
            self._change("researchWatchlist", {**base, "id": stable(owner, board_id, "articles"), "title": board["title"]+" · reading list",
                "articles": reading,
                "matchedCount": len(documents)}, "Updated relevant articles from the board and your portfolios", evidence)
            self.s.activity.report("Updating monitors, article tags and the action audit", 3, 4)
            monitor_id = stable(owner, board_id, "monitor")
            old_monitor = self.db.get("researchMonitor", monitor_id)
            changed = self._change("researchMonitor", {**base, "id": monitor_id, "query": board["title"], "enabled": True,
                "assetIds": sorted(aid for aid in assets if asset_evidence[aid]), "matches": sorted(documents),
                "evidenceFingerprint": version_fingerprint, "rule": "Current source versions cited by this board or naming its watched instruments"}, "Established a source-change monitor", evidence)
            if changed and old_monitor and old_monitor.get("evidenceFingerprint") != version_fingerprint:
                key = stable(owner, board_id, version_fingerprint, "notice")
                preferences = self.db.get("researchPreferences", owner) or {}
                if preferences.get("notifications", True):
                    self.db.put("researchNotification", key, {"id": key, **base, "at": now_ms(), "read": False,
                        "message": "Agent evidence monitor updated: " + board["title"], "monitorId": monitor_id})
            wanted_tags = set()
            for doc in reading:
                key = stable(owner, board_id, doc["documentId"], "tag")
                wanted_tags.add(key)
                self._change("researchTag", {**base, "id": key, "documentId": doc["documentId"], "version": doc["version"],
                    "tag": "Portfolio watch" if doc["assetIds"] else "Topic research", "topic": board["title"], "active": True}, doc["reason"], [{"documentId": doc["documentId"], "version": doc["version"]}])
            for tag in self.db.matching("researchTag", "ownerId", owner, 10000):
                if tag.get("boardId") == board_id and tag.get("active") and tag["id"] not in wanted_tags:
                    self._change("researchTag", {**tag, "active": False}, "Source support changed; article tag withdrawn", [])
            prior = self.db.get("agentOrganizationJob", board_id) or {"id": board_id, "ownerId": owner}
            self.db.put("agentOrganizationJob", board_id, {**prior, "checkedAt": now_ms(), "matchedArticles": len(documents), "inputSignature": self._signature(board)})

    def personal(self, owner, full=False):
        kinds = {"watchlists": "researchWatchlist", "monitors": "researchMonitor", "articleTags": "researchTag"}
        result = {name: [r for r in self.db.scan(kind) if r.get("ownerId") == owner] if full else self.db.matching(kind, "ownerId", owner, 2000) for name, kind in kinds.items()}
        for monitor in result["monitors"]:
            board = self.db.get("researchBoard", monitor["boardId"]) or {}
            monitor["effectiveEnabled"] = bool(board.get("expansionState") == "running" and not board.get("archived") and self.policy(owner, board["id"])["enabled"] and monitor["enabled"]) if board else False
        if not full: result["articleTags"] = [t for t in result["articleTags"] if t.get("active")]
        actions = [r for r in self.db.scan("agentAction") if r.get("ownerId") == owner] if full else self.db.matching("agentAction", "ownerId", owner, 50)
        result["agentActions"] = actions if full else [{k: v for k, v in row.items() if k not in {"before", "afterFingerprint"}} for row in actions]
        return result
