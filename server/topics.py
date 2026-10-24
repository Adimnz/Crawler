"""Persistent, bounded topic research. A search plan never establishes an asset exposure."""
from __future__ import annotations

from collections import Counter
from html.parser import HTMLParser
import json
import math
import re
from urllib.parse import urlsplit

from . import analysis as a
from .connectors import strip_html
from .storage import now_ms, identifier, dumps


_REQUEST_WORDS = set("find show look search tell give create build curate curated watch portfolio portfolios invest investment investing stock stocks company companies assets asset topic research information learn monitor monitoring want interested please need start where help can how".split())
_ACTIVE = {"Qualified for monitoring", "Continued monitoring"}
_PURPOSE = "Research watch portfolio. Entries are monitoring subjects; no purchases, allocation weights, targets, or expected returns."


def _normal(value):
    return " ".join(re.findall(r"[^\W_]+", str(value).casefold()))


def _terms(query):
    words = re.findall(r"[^\W_]+", str(query).casefold())
    selected = [w for w in words if len(w) >= 2 and w not in a.STOP and w not in _REQUEST_WORDS]
    return list(dict.fromkeys(selected))[:18]


def _contains(text, term):
    return " " + _normal(term) + " " in " " + _normal(text) + " "


class _PageTitle(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.inside, self.parts = False, []
        self.authors, self.published, self.modified = [], None, None
        self.json_parts, self.in_json = [], False

    def handle_starttag(self, tag, attrs):
        if tag == "title": self.inside = True
        fields = dict(attrs)
        if tag == "meta":
            key, value = (fields.get("name") or fields.get("property") or "").casefold(), fields.get("content", "").strip()
            if key in {"author", "byl", "parsely-author", "dc.creator"} and value and len(value) <= 200:
                self.authors.append(value)
            if key == "article:published_time": self.published = value
            if key == "article:modified_time": self.modified = value
        if tag == "script" and fields.get("type") == "application/ld+json":
            self.in_json, self.json_parts = True, []

    def handle_endtag(self, tag):
        if tag == "title": self.inside = False
        if tag == "script" and self.in_json:
            self.in_json = False
            try:
                content = json.loads("".join(self.json_parts))
                objects = content if isinstance(content, list) else [content]
                objects += [item for obj in objects if isinstance(obj, dict) for item in obj.get("@graph", []) if isinstance(item, dict)]
                for obj in objects[:100]:
                    if not isinstance(obj, dict): continue
                    kinds = obj.get("@type", [])
                    if isinstance(kinds, str): kinds = [kinds]
                    if not any(kind in {"Article", "NewsArticle", "ReportageNewsArticle", "AnalysisNewsArticle", "BlogPosting"} for kind in kinds): continue
                    authors = obj.get("author", [])
                    if not isinstance(authors, list): authors = [authors]
                    for author in authors:
                        name = author.get("name") if isinstance(author, dict) else author
                        if isinstance(name, str) and 1 <= len(name) <= 200: self.authors.append(name)
                    self.published = self.published or obj.get("datePublished")
                    self.modified = self.modified or obj.get("dateModified")
            except (ValueError, TypeError): pass
            self.authors = list(dict.fromkeys(self.authors))[:10]

    def handle_data(self, data):
        if self.inside: self.parts.append(data)
        if self.in_json: self.json_parts.append(data)


class TopicResearch:
    def __init__(self, service):
        self.s, self.db = service, service.db

    def _read(self, topic_id):
        item = self.db.get("topicPortfolio", topic_id)
        if not item: raise ValueError("Topic portfolio not found")
        return item

    def _update(self, topic_id, **changes):
        with self.s.lock:
            item = self._read(topic_id)
            if item.get("deleted"): return item
            item.update(changes, updatedAt=now_ms())
            self.db.put("topicPortfolio", topic_id, item)
        return item

    def get(self, topic_id):
        item = self._read(topic_id)
        revisions = [r for r in self.db.latest("topicRevision", 3000) if r["id"] == topic_id]
        item["revisions"] = [{key: r.get(key) for key in ("version", "lastRunAt", "whatChanged", "qualifiedCount", "candidateCount")} for r in revisions[:30]]
        return item

    def list(self):
        return [t for t in self.db.latest("topicPortfolio", 200) if not t.get("embedded") and not t.get("deleted")]

    def create(self, query):
        values = query if isinstance(query, dict) else {"query": query}
        text = str(values.get("query", "")).strip()
        if not 2 <= len(text) <= 1200 or not _terms(text):
            raise ValueError("Enter a research topic between 2 and 1200 characters")
        interval = self._interval(values.get("refreshMinutes", 60))
        topic_id = "topic-" + a.digest(_normal(text))[:28]
        with self.s.lock:
            existing = self.db.get("topicPortfolio", topic_id)
            if existing and not existing.get("deleted"): return self.refresh(topic_id, manual=True)
            at = now_ms()
            item = {"id": topic_id, "query": text, "title": text[:140], "state": "Queued", "status": "Queued",
                    "progress": "Waiting for the research worker", "enabled": True, "refreshMinutes": interval,
                    "createdAt": at, "updatedAt": at, "nextRefreshAt": at + interval * 60000,
                    "lastRunAt": None, "version": 0, "entries": [], "candidates": [], "evidence": [],
                    "qualifiedCount": 0, "candidateCount": 0, "questions": [], "whatChanged": [], "watchSubjects": [], "marketResearch": None,
                    "manualAiRequest": {"token": identifier("manual-research"), "requestedAt": at},
                    "limitations": ["Research is queued. Assets appear only when collected source records support a topic match."],
                    "purpose": _PURPOSE, "embedded": values.get("embedded") is True}
            self.db.put("topicPortfolio", topic_id, item)
            item["jobId"] = self.db.enqueue("topic-research", {"topicId": topic_id}, "topic-initial:" + topic_id)
            self.db.put("topicPortfolio", topic_id, item)
            self.db.audit("Topic research requested", topic_id, {"query": text, "refreshMinutes": interval})
        return item

    @staticmethod
    def _interval(value):
        try: interval = float(value)
        except (ValueError, TypeError) as exc: raise ValueError("Refresh interval must be between 5 and 1440 minutes") from exc
        if not math.isfinite(interval) or not 5 <= interval <= 1440:
            raise ValueError("Refresh interval must be between 5 and 1440 minutes")
        return int(interval)

    def stop(self, topic_id, owner="local-owner"):
        """Stop personal branch work; preserve shared research for other subscribers."""
        with self.s.lock:
            item = self._read(topic_id)
            for board in self.s.network_research.list_boards(owner):
                if board["topicId"] == topic_id:
                    self.s.network_research.board_action(owner, {"id": board["id"], "action": "cancel"})
            others = [r for r in self.db.latest("accountTopic", 10000) if r["topicId"] == topic_id and r["ownerId"] != owner and r.get("enabled", True)]
            if not others: item = self.configure(topic_id, {"enabled": False})
            return {**item, "enabled": False}

    def delete(self, topic_id, owner="local-owner"):
        with self.s.lock:
            self.stop(topic_id, owner)
            for board in self.s.network_research.list_boards(owner):
                if board["topicId"] == topic_id: self.s.network_research.delete_board(owner, board["id"])
            for row in self.db.latest("accountTopic", 10000):
                if row["topicId"] == topic_id and row["ownerId"] == owner: self.db.delete("accountTopic", row["id"])
            shared = any(r["topicId"] == topic_id for r in self.db.latest("accountTopic", 10000)) or any(b["topicId"] == topic_id for b in self.db.latest("researchBoard", 10000))
            if not shared:
                # A tombstone prevents an in-flight worker from resurrecting a deleted topic.
                self.db.put("topicPortfolio", topic_id, {"id": topic_id, "deleted": True, "enabled": False, "state": "Deleted", "status": "Deleted", "manualAiRequest": None})
                self.db.delete("networkGraph", topic_id)
            self.db.audit("Topic removed from workspace", topic_id, {"ownerId": owner})
            return {"deleted": True, "id": topic_id}

    def configure(self, topic_id, values):
        item = self._read(topic_id)
        changes = {}
        if "refreshMinutes" in values: changes["refreshMinutes"] = self._interval(values["refreshMinutes"])
        if "enabled" in values:
            changes["enabled"] = bool(values["enabled"])
            if changes["enabled"]:
                changes.update(state="Monitoring" if item.get("evidence") or item.get("watchSubjects") else "Needs evidence", nextRefreshAt=now_ms())
            else: changes.update(state="Paused", progress="Automatic topic research paused", manualAiRequest=None)
            changes["status"] = changes["state"]
        if changes.get("refreshMinutes"):
            changes["nextRefreshAt"] = now_ms() + changes["refreshMinutes"] * 60000
        result = self._update(topic_id, **changes)
        self.db.audit("Topic research settings changed", topic_id, {k: result[k] for k in ("enabled", "refreshMinutes")})
        return result

    def refresh(self, topic_id, manual=True):
        with self.s.lock:
            item = self._read(topic_id)
            if item.get("deleted"): raise ValueError("Topic was deleted; start a new search")
            if not item.get("enabled", True) and not (manual or item.get("manualAiRequest")): return item
            pending = self.db.get_job(item.get("jobId", ""))
            request = item.get("manualAiRequest")
            if pending and pending["state"] in {"queued", "running"}:
                if manual and not request:
                    return self._update(topic_id, manualAiRequest={"token": identifier("manual-research"), "requestedAt": now_ms()},
                                        nextRefreshAt=min(item.get("nextRefreshAt", now_ms()), now_ms()))
                return item
            job_id = self.db.enqueue("topic-research", {"topicId": topic_id}, identifier("topic-refresh"))
            return self._update(topic_id, state="Queued", status="Queued", progress="Waiting for the research worker", jobId=job_id,
                                manualAiRequest={"token": identifier("manual-research"), "requestedAt": now_ms()} if manual else request,
                                nextRefreshAt=now_ms() + item.get("refreshMinutes", 60) * 60000)

    def refresh_due(self):
        at, queued = now_ms(), []
        for item in self.list():
            if (item.get("enabled", True) or item.get("manualAiRequest")) and item.get("nextRefreshAt", 0) <= at:
                queued.append(self.refresh(item["id"], manual=False))
        return queued

    def evidence_changed(self, document_id=None, asset_id=None, source_id=None):
        """Coalesce relevant ingestion bursts; a scheduler queues the durable follow-up."""
        document = self.db.get("document", document_id) if document_id else None
        at, changed = now_ms(), []
        for item in self.list():
            if not item.get("enabled", True): continue
            linked_assets = {r["assetId"] for r in item.get("entries", []) + item.get("candidates", [])}
            evidence_ids = {d["id"] for d in item.get("evidence", [])}
            context = {**item, "_subjectNames": self._subject_names(item)}
            relevant = bool(document and (document["id"] in evidence_ids or self._match(document, context)["matches"]))
            relevant = relevant or bool(asset_id and asset_id in linked_assets)
            relevant = relevant or bool(source_id and source_id in item.get("pendingProviderSources", []))
            if relevant:
                with self.s.lock:
                    current = self._read(item["id"])
                    changes = dict(current.get("pendingEvidenceChanges", {}))
                    token = identifier("evidence-change")
                    if document:
                        changes["document:" + document["id"]] = {"documentId": document["id"], "version": document["version"], "at": at, "token": token}
                    if asset_id:
                        profile = self.db.get("assetProfile", asset_id) or {}
                        changes["asset:" + asset_id] = {"assetId": asset_id, "profileVersion": profile.get("version", 0), "at": at, "token": token}
                    if source_id:
                        changes["source:" + source_id] = {"sourceId": source_id, "at": at, "token": token}
                    changed.append(self._update(item["id"], evidenceChangedAt=at, pendingEvidenceChanges=changes,
                        nextRefreshAt=min(current.get("nextRefreshAt", at + 30000), at + 30000)))
        return changed

    def _plan(self, item, use_ai=None):
        use_ai = self.s.auto_ai and self.s.ai.ready if use_ai is None else use_ai
        if item.get("plan") and (item.get("planMethod") == "AI research plan" and item.get("planModel") == getattr(self.s.ai, "model", None) or not use_ai):
            return item
        plan = {"title": item["query"][:140], "searchTerms": _terms(item["query"]),
                "questions": ["What is happening, and which original sources explain it?",
                              "Which companies, markets, and financial institutions are connected?",
                              "What could change the outlook, and what should I watch next?"],
                "assetTypes": [], "regions": []}
        method, warning = "Literal topic parsing", None
        error = item.get("planError") if not use_ai else None
        if use_ai and callable(getattr(self.s.ai, "plan_topic", None)):
            try:
                proposal = self.s.ai.plan_topic(item["query"])
                if isinstance(proposal, dict):
                    for key in ("searchTerms", "questions", "assetTypes", "regions"):
                        rows = proposal.get(key, [])
                        plan[key] = [str(v)[:200] for v in rows[:8] if isinstance(v, str) and v.strip()] if isinstance(rows, list) else []
                    plan["title"] = str(proposal.get("title") or plan["title"])[:140]
                    method = "AI research plan"
            except Exception as exc:
                error = self._ai_failure(exc)
                warning = "AI topic planning was unavailable; literal topic matching remains active."
        return self._update(item["id"], plan=plan, planMethod=method, planModel=getattr(self.s.ai, "model", None) if method == "AI research plan" else None,
                            title=plan["title"], questions=plan["questions"], planWarning=warning, planError=error)

    @staticmethod
    def _ai_failure(error, discovery=False):
        from .ai_settings import AISettings
        result = AISettings._failure(error)
        if discovery and result.get("status") == 400:
            result["message"] = "The selected OpenAI model did not accept web search. Choose a model that supports web search, or add a relevant feed."
        return result

    def _subject_names(self, item):
        names = []
        for subject in item.get("watchSubjects", [])[:18]:
            name = str(subject.get("name", "")).strip()
            if len(_normal(name)) < 3: continue
            for reference in subject.get("evidence", []):
                doc = self.db.get("document", reference.get("documentId", ""))
                quote = reference.get("quote")
                if doc and doc["version"] == reference.get("version") and isinstance(quote, str) and quote and quote in doc["text"] and _contains(doc["text"], name):
                    names.append(name)
                    break
        return list(dict.fromkeys(names))

    def _match(self, document, item):
        text = document.get("title", "") + " " + document.get("text", "")
        terms = _terms(item["query"])
        matched = [term for term in terms if _contains(text, term)]
        needed = max(1, math.ceil(len(terms) * .6))
        literal = len(matched) >= needed
        # Literal parsing cannot bypass the original multi-term threshold. AI
        # expansions are discovery candidates only, and must add actual scope.
        hints = [term for term in item.get("plan", {}).get("searchTerms", [])
                 if item.get("planMethod") == "AI research plan" and set(_terms(term)) - set(terms) and _contains(text, term)]
        subjects = [name for name in item.get("_subjectNames", []) if _contains(text, name)]
        return {"score": len(matched) * 4 + len(hints) + bool(subjects), "literal": literal, "subjectContext": bool(subjects),
                "terms": matched if literal else hints or subjects, "matches": literal or bool(hints) or bool(subjects)}

    def _matching_documents(self, item):
        item = {**item, "_subjectNames": self._subject_names(item)}
        matched = [(d, self._match(d, item)) for d in self.db.latest("document", 10000)]
        matched = [(doc, match) for doc, match in matched if match["matches"]]
        matched.sort(key=lambda pair: (pair[1]["literal"], pair[1]["score"], pair[0].get("publishedAt", 0)), reverse=True)
        return matched[:150]

    def _refresh_sources(self, item, matched):
        wanted = {d["sourceId"] for d, _ in matched}
        categories = set(a.categories(item["query"]))
        enabled = [s for s in self.db.list("source") if s.get("enabled") and s.get("kind") in {"rss", "json"}
                   and s.get("config", {}).get("recordType") != "observation"]
        enabled.sort(key=lambda s: (s["id"] in wanted, s.get("category") in categories), reverse=True)
        if matched: enabled = [s for s in enabled if s["id"] in wanted or s.get("category") in categories]
        checked, warnings = [], []
        for source in enabled[:2]:
            if source.get("nextPollAt", 0) > now_ms(): continue
            try:
                self.s.poll_source(source["id"])
                checked.append({"id": source["id"], "name": source["name"], "status": "Collected"})
            except Exception:
                checked.append({"id": source["id"], "name": source["name"], "status": "Collection unavailable"})
                warnings.append("A configured source could not be refreshed; only retained records from that source were checked.")
        return checked, warnings

    def _web_discovery(self, item, use_ai=None, manual=False):
        """Only fetched original pages become documents; search snippets never do."""
        use_ai = self.s.auto_ai and self.s.ai.ready if use_ai is None else use_ai
        ready = use_ai and callable(getattr(self.s.ai, "discover_topic", None))
        model = getattr(self.s.ai, "model", None)
        cached = now_ms() - item.get("discoveryAt", 0) < a.HOUR
        cached_failure = bool(item.get("discoveryError"))
        if not ready or cached and (not cached_failure or item.get("discoveryModel") == model and not manual):
            return item
        links, warnings, error = [], [], None
        try:
            result = self.s.ai.discover_topic(item["query"], item.get("plan", {}).get("searchTerms", []))
            candidates = result.get("sources", []) if isinstance(result, dict) else result
            feed_leads = [lead for lead in self.db.latest("feedLead", 500)
                          if lead.get("contentRole") == "discovery" and self._match({**lead, "text": lead.get("summary", "")}, item)["matches"]][:3]
            candidates = feed_leads + (candidates if isinstance(candidates, list) else [])
            seen = set()
            for candidate in (candidates if isinstance(candidates, list) else [])[:12]:
                if not isinstance(candidate, dict): continue
                url = str(candidate.get("url", ""))
                parsed = urlsplit(url)
                if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443): continue
                canonical = a.canonical_url(url)
                if canonical in seen: continue
                seen.add(canonical)
                link = {"url": canonical, "title": str(candidate.get("title") or parsed.hostname)[:300],
                        "discoveryOnly": True, "status": "Not retrieved"}
                links.append(link)
                if len(links) > 4: continue
                try:
                    if not self.s.network.allowed(canonical):
                        link["status"] = "Collection disallowed by robots.txt"
                        continue
                    data, headers, resolved = self.s.network.fetch(canonical, limit=1024 * 1024)
                    if len(data) > 1024 * 1024: raise ValueError("Page exceeds collection limit")
                    if resolved != canonical and not self.s.network.allowed(resolved):
                        link["status"] = "Redirect collection disallowed by robots.txt"
                        continue
                    content_type = headers.get("content-type", "").lower()
                    if not any(v in content_type for v in ("text/html", "application/xhtml+xml", "text/plain")):
                        link["status"] = "Unsupported document format"
                        continue
                    content = data.decode("utf-8", "replace")
                    metadata = {}
                    if "text/plain" in content_type:
                        title, text = (content.splitlines() or [parsed.hostname])[0][:300], content.strip()
                    else:
                        parser = _PageTitle()
                        parser.feed(content)
                        metadata = {"authors": parser.authors, "publishedAt": parser.published, "sourceUpdatedAt": parser.modified}
                        title = " ".join(parser.parts).strip()[:300] or urlsplit(resolved).hostname
                        text = strip_html(content)
                    if len(text) < 80 or not self._match({"title": title, "text": text}, item)["matches"]:
                        link["status"] = "No usable matching source text"
                        continue
                    origin = "https://" + urlsplit(resolved).hostname + "/"
                    source_id = "topic-page-" + a.digest(origin)[:24]
                    source = self.db.get("source", source_id)
                    if not source:
                        # Existing publisher sources keep their own identity and collection policy.
                        source = next((s for s in self.db.list("source") if s.get("url") == origin), None)
                    if not source:
                        source = self.s.add_source({"id": source_id, "name": urlsplit(resolved).hostname, "url": origin,
                            "kind": "json", "enabled": False, "tier": "regional", "family": urlsplit(resolved).hostname,
                            "permissions": "Public page retrieved for user-requested autonomous topic research; robots allowed; provider reuse terms apply.",
                            "allowFullText": False})
                    document = self.s.ingest(source, {"title": title, "text": text, "url": resolved, "publishedEstimated": not bool(metadata.get("publishedAt")), **metadata,
                        "raw": {"url": resolved, "contentType": content_type, "originalPage": content}})
                    link.update(title=document["title"], documentId=document["id"], sourceVersion=document["version"],
                                status="Original source retrieved; claims unverified", discoveryOnly=False)
                except Exception:
                    link["status"] = "Source could not be retrieved safely"
        except Exception as exc:
            error = self._ai_failure(exc, discovery=True)
            warnings.append("AI web discovery was unavailable; retained and configured sources remain in scope.")
        return self._update(item["id"], discoveryAt=now_ms(), discoveryModel=model,
                            discoveryLinks=links, discoveryWarnings=warnings, discoveryError=error)

    def _discover_assets(self, matched):
        from .financial_connectors import discover_instruments
        providers = [s for s in self.db.list("source") if s.get("enabled") and s.get("kind") in {"sec", "coingecko_asset", "coingecko"}
                     and not s["id"].startswith("auto-provider-")]
        if not providers or not matched: return []
        provider_kinds = {"sec" if p["kind"] == "sec" else "coingecko" for p in providers}
        assets = discover_instruments([d for d, _ in matched], self.s.network, limit=6, providers=provider_kinds)
        pending = []
        for asset in assets:
            kind = "sec" if asset.get("cik") else "coingecko_asset"
            provider = next((p for p in providers if p["kind"] == kind or kind == "coingecko_asset" and p["kind"] == "coingecko"), None)
            if not provider: continue
            self.s.investments.accept_assets([asset], provider)
            config = {"cik": asset["cik"], "ticker": asset["ticker"], "exchange": asset.get("exchange")} if kind == "sec" else {"id": asset.get("providerId")}
            source_id = "auto-provider-" + a.digest(asset["id"])[:20]
            source = self.db.get("source", source_id)
            if not source:
                source = self.s.add_source({"id": source_id, "kind": kind, "name": "Research data · " + asset["name"],
                    "url": "https://data.sec.gov/api/xbrl/companyfacts/CIK" + str(asset["cik"]).zfill(10) + ".json" if kind == "sec" else "https://api.coingecko.com/api/v3/coins/" + asset["providerId"],
                    "config": config, "enabled": True, "tier": "primary", "family": provider.get("family", provider["name"]),
                    "permissions": provider.get("permissions", "Configured provider research access"), "interval": 86400000 if kind == "sec" else 3600000})
            if source.get("enabled") and source.get("nextPollAt", 0) <= now_ms():
                self.db.enqueue("poll", {"sourceId": source_id}, "topic-provider:" + source_id + ":" + str(now_ms() // a.HOUR))
                pending.append(source_id)
        return pending

    @staticmethod
    def _asset_mentioned(passage, asset, provider_linked=False):
        if asset.get("name") and _contains(passage, asset["name"]): return True
        if provider_linked:
            # This alias is used only after an official catalogue linked this very document.
            words = _normal(asset.get("name", "")).split()
            legal_suffixes = {"inc", "incorporated", "corp", "corporation", "co", "company", "limited", "ltd", "plc", "sa", "nv", "holdings"}
            while len(words) > 1 and words[-1] in legal_suffixes: words.pop()
            if words and _contains(passage, " ".join(words)): return True
        ticker = re.escape(str(asset.get("ticker", "")))
        return bool(ticker and re.search(r"(?:\$|\b(?:NASDAQ|NYSE|AMEX)\s*:\s*)" + ticker + r"\b", passage, re.I))

    def _topic_evidence(self, profile, matched, item):
        asset, result = profile["asset"], []
        linked = {r["id"] for r in profile.get("sourceHistory", [])}
        relationships = [r for r in self.db.latest("relationship", 10000) if r.get("confirmed") and not r.get("reviewRequired")
                         and r.get("validFrom", 0) <= now_ms() and (not r.get("validTo") or r["validTo"] >= now_ms())
                         and asset["id"] in {r.get("from"), r.get("to")}]
        related = {eid for r in relationships for eid in r.get("evidence", [])
                   if self.db.get("document", eid) and r.get("evidenceVersions", {}).get(eid) == self.db.get("document", eid)["version"]}
        for doc, match in matched:
            if doc["id"] not in linked | related: continue
            # Source ownership is supported by provider IDs; article entity tags alone do not establish exposure.
            company_id = str(doc.get("companyId", ""))
            owned = company_id == asset["id"] or bool(asset.get("cik") and company_id.lstrip("0") == str(asset["cik"]).lstrip("0"))
            passages = re.split(r"(?<=[.!?])\s+|[\r\n]+", doc.get("text", ""))
            literal = []
            hinted = []
            for passage in passages:
                passage_match = self._match({"text": passage}, item)
                if not passage_match["matches"]: continue
                if not (owned or doc["id"] in related or self._asset_mentioned(passage, asset, doc["id"] in asset.get("triggerDocumentIds", []))): continue
                row = {"documentId": doc["id"], "version": doc["version"], "quote": passage[:1800], "terms": passage_match["terms"],
                       "basis": "Reviewed relationship evidence" if doc["id"] in related else "Literal source wording; topic relevance is a text-match heuristic",
                       "literal": passage_match["literal"]}
                (literal if passage_match["literal"] else hinted).append(row)
            result.extend((literal or hinted)[:2])
        return result[:8]

    def _curate(self, item, matched):
        item = {**item, "_subjectNames": self._subject_names(item)}
        entries, candidates = [], []
        for profile in self.db.latest("assetProfile", 500):
            support = self._topic_evidence(profile, matched, item)
            if not support: continue
            literal = any(row["literal"] for row in support)
            asset = profile["asset"]
            qualified = bool(literal and profile.get("qualified") and profile.get("status") in _ACTIVE)
            row = {"assetId": profile["id"], "name": asset.get("name", profile["id"]), "ticker": asset.get("ticker", ""),
                   "assetClass": asset.get("assetClass", ""), "sector": asset.get("sector") or "Data unavailable",
                   "country": asset.get("country") or "Data unavailable", "status": profile["status"], "qualified": qualified,
                   "profileVersion": profile["version"], "reason": support[0]["quote"], "evidenceIds": sorted({r["documentId"] for r in support}),
                   "topicMatch": support, "relevanceMethod": "Literal source text matching" if literal else "AI search expansion; topic relationship requires review",
                   "qualificationGaps": profile.get("qualificationGaps", []) + ([] if literal else ["Original topic relationship needs verification"]),
                   "risks": profile.get("risks", []), "monitoringCriteria": profile.get("monitoringCriteria", []),
                   "whatChanged": profile.get("whatChanged", [])}
            (entries if qualified else candidates).append(row)
        entries.sort(key=lambda row: (-len(row["evidenceIds"]), row["name"].casefold()))
        candidates.sort(key=lambda row: (-len(row["evidenceIds"]), row["name"].casefold()))
        return entries[:40], candidates[:40]

    def _market_report(self, item, matched, use_ai, manual=False):
        from .market_research import research_topic
        documents = [doc for doc, _ in matched]
        fingerprint = a.digest(dumps({"query": item["query"], "documents": [(d["id"], d["version"], d.get("contentHash")) for d in documents]}))
        previous = item.get("marketResearch")
        model = getattr(self.s.ai, "model", None) if use_ai else None
        same_sources = previous is not None and item.get("marketResearchFingerprint") == fingerprint
        accepted_ai = previous and previous.get("method") == "OpenAI source research" and previous.get("model") == model
        same_attempt = item.get("marketResearchAttemptModel") == model
        if same_sources and (not use_ai or accepted_ai or same_attempt and not manual):
            return {"marketResearch": previous, "watchSubjects": previous.get("subjects", []),
                    "marketResearchFingerprint": fingerprint, "marketResearchAttemptModel": item.get("marketResearchAttemptModel"),
                    "marketResearchWarning": None, "marketResearchStale": False}
        snapshots = {doc["id"]: (doc["version"], doc.get("contentHash")) for doc in documents}
        report = research_topic(self.s.ai if use_ai else None, item["query"], documents, previous=previous)
        stale = []
        for document_id, bound in snapshots.items():
            current = self.db.get("document", document_id)
            if not current or (current["version"], current.get("contentHash")) != bound:
                stale.append(document_id)
        if stale:
            for document_id in stale: self.evidence_changed(document_id=document_id)
            return {"marketResearch": None, "watchSubjects": [], "marketResearchFingerprint": None,
                    "marketResearchAttemptModel": model, "marketResearchStale": True,
                    "marketResearchWarning": "Source evidence changed during research; the stale report was withheld and a follow-up is scheduled."}
        return {"marketResearch": report, "watchSubjects": report.get("subjects", []),
                "marketResearchFingerprint": fingerprint, "marketResearchAttemptModel": model,
                "marketResearchWarning": None, "marketResearchStale": False}

    def _stale_report_documents(self, report):
        stale, checked = set(), {}
        if not report: return stale
        for field in ("summary", "drivers", "risks", "subjects"):
            for finding in report.get(field, []):
                for reference in finding.get("evidence", []):
                    document_id = reference.get("documentId", "")
                    if document_id not in checked: checked[document_id] = self.db.get("document", document_id)
                    document = checked[document_id]
                    if not document or document["version"] != reference.get("version") or not reference.get("quote") or reference["quote"] not in document["text"]:
                        stale.add(document_id)
        return stale

    def _assessment(self, item, matched, fingerprint):
        if not (self.s.auto_ai and self.s.ai.ready and callable(getattr(self.s.ai, "coordinate", None))): return {}
        if item.get("assessmentFingerprint") == fingerprint: return {}
        try:
            snapshots = {("document", doc["id"]): a.digest(dumps(doc)) for doc, _ in matched}
            document_ids = {doc["id"] for doc, _ in matched}
            for profile in self.db.latest("assetProfile", 500):
                if not any(d["id"] in document_ids for d in profile.get("sourceHistory", [])): continue
                snapshots[("assetProfile", profile["id"])] = a.digest(dumps(profile))
                for row in self.s.investments._observations(profile["id"]):
                    kind = "observation" if self.db.get("observation", row["id"]) else "observationVintage"
                    snapshots[(kind, row["id"])] = a.digest(dumps(row))
            def execute_tool(name, arguments):
                response = self.s.investments.tool(name, arguments)
                for record in response.get("evidence", []):
                    for record_id in [record.get("id", "")] + record.get("inputIds", []):
                        for kind in ("document", "observation", "observationVintage"):
                            current = self.db.get(kind, record_id)
                            if current:
                                snapshots.setdefault((kind, record_id), a.digest(dumps(current)))
                                break
                return response
            assessment = self.s.ai.coordinate({"topic": item["query"], "researchPlan": item.get("plan"),
                "question": "Investigate this topic using the supplied read-only tools. Compare current evidence, contradictions, risks and missing data. Topic membership and monitoring eligibility are determined by application rules.",
                "evidenceIds": [d["id"] for d, _ in matched[:30]]}, execute_tool, max_rounds=4)
            if any(a.digest(dumps(self.db.get(kind, record_id))) != digest for (kind, record_id), digest in snapshots.items()):
                return {"assessmentWarning": "Source evidence changed during AI investigation; the stale assessment was withheld."}
            return {"assessment": assessment, "assessmentFingerprint": fingerprint, "model": getattr(self.s.ai, "model", None)}
        except Exception:
            return {"assessmentWarning": "AI investigation was unavailable; source-based curation continues."}

    def _unconsumed_changes(self, changes, matched, entries, candidates, item, cycle_started):
        """Keep a follow-up only for inputs that this curation did not consume."""
        item = {**item, "_subjectNames": self._subject_names(item)}
        documents = {doc["id"]: doc["version"] for doc, _ in matched}
        profiles = {row["assetId"]: row["profileVersion"] for row in entries + candidates}
        remaining = {}
        for key, event in changes.items():
            consumed = False
            if event.get("documentId"):
                doc = self.db.get("document", event["documentId"])
                consumed = bool(doc and doc["version"] == event["version"] and
                    (documents.get(doc["id"]) == doc["version"] or not self._match(doc, item)["matches"]))
            elif event.get("assetId"):
                profile = self.db.get("assetProfile", event["assetId"]) or {}
                used_version = profiles.get(event["assetId"])
                consumed = bool(used_version and used_version == profile.get("version") and used_version > event.get("profileVersion", 0))
                if event["assetId"] not in profiles and event.get("at", 0) <= cycle_started:
                    consumed = profile.get("version", 0) > event.get("profileVersion", 0)
            elif event.get("sourceId"):
                # Individual document/asset changes retain their own version
                # checks. A completed collection before this cycle is consumed.
                consumed = event.get("at", 0) <= cycle_started
            if not consumed: remaining[key] = event
        return remaining

    def _complete(self, topic_id, checked_changes, remaining_changes, used_request_token=None, **changes):
        with self.s.lock:
            current = self._read(topic_id)
            if current.get("deleted") or not current.get("enabled", True) and not current.get("manualAiRequest"): return current
            pending = dict(current.get("pendingEvidenceChanges", {}))
            for key, event in checked_changes.items():
                # A newer event arriving during finalization must remain due.
                if key not in remaining_changes and pending.get(key) == event:
                    pending.pop(key, None)
            if pending:
                changes["nextRefreshAt"] = min(changes["nextRefreshAt"], current.get("nextRefreshAt", now_ms() + 30000), now_ms() + 30000)
            request = current.get("manualAiRequest")
            if request and request.get("token") == used_request_token and not changes.get("marketResearchStale"):
                changes["manualAiRequest"] = None
            elif request and request.get("token") != used_request_token:
                # Manual intent arriving after a scheduled run began remains
                # available for the next worker; it never enables paid polling.
                changes["nextRefreshAt"] = min(changes["nextRefreshAt"], now_ms())
            if not current.get("enabled", True): changes.update(state="Paused", status="Paused")
            return self._update(topic_id, **changes, pendingEvidenceChanges=pending)

    def run(self, topic_id):
        item = self._read(topic_id)
        request = item.get("manualAiRequest") or {}
        request_token = request.get("token")
        if not item.get("enabled", True) and not request_token: return item
        use_ai = bool(self.s.ai.ready and (request_token or self.s.auto_ai))
        started = now_ms()
        self._update(topic_id, state="Researching", status="Researching", progress="Interpreting your topic and checking sources", researchStartedAt=started)
        try:
            item = self._plan(item, use_ai=use_ai)
            current = self._read(topic_id)
            if not current.get("enabled", True) and not (request_token and (current.get("manualAiRequest") or {}).get("token") == request_token): return current
            matched = self._matching_documents(item)
            checked, warnings = self._refresh_sources(item, matched)
            self._update(topic_id, progress="Researching original sources and identifying relevant instruments")
            item = self._web_discovery(self._read(topic_id), use_ai=use_ai, manual=bool(request_token))
            current = self._read(topic_id)
            if not current.get("enabled", True) and not (request_token and (current.get("manualAiRequest") or {}).get("token") == request_token): return current
            matched = self._matching_documents(item)
            try: pending = self._discover_assets(matched)
            except Exception:
                pending = []
                warnings.append("Official instrument discovery was unavailable; no unverified identities were admitted.")
            self._update(topic_id, progress="Explaining the topic and identifying companies, markets, and institutions to watch")
            research_changes = self._market_report(item, matched, use_ai, manual=bool(request_token))
            item = {**item, **research_changes}
            current = self._read(topic_id)
            if current.get("deleted") or not current.get("enabled", True) and not current.get("manualAiRequest"): return current
            cycle_started = now_ms()
            self.s.investments.cycle("Topic research: " + item["query"][:160])
            # Filings may have been collected concurrently while provider work was queued.
            matched = self._matching_documents(item)
            self._update(topic_id, progress="Checking related financial profiles")
            entries, candidates = self._curate(item, matched)
            report = research_changes.get("marketResearch")
            stale_report_documents = self._stale_report_documents(report)
            if stale_report_documents:
                for document_id in stale_report_documents: self.evidence_changed(document_id=document_id)
                research_changes.update(marketResearch=None, watchSubjects=[], marketResearchFingerprint=None, marketResearchStale=True,
                    marketResearchWarning="Source evidence changed before publication; the stale report was withheld and a follow-up is scheduled.")
                item.update(research_changes)
                matched = self._matching_documents(item)
                entries, candidates = self._curate(item, matched)
            safe_entries = []
            for entry in entries:
                changed = any(not (self.db.get("document", ref["documentId"]) or {}).get("version") == ref["version"] for ref in entry.get("topicMatch", []))
                if changed:
                    entry = {**entry, "qualified": False, "status": "Review required",
                        "qualificationGaps": entry.get("qualificationGaps", []) + ["Source evidence changed; reassessment pending"]}
                    candidates.append(entry)
                else: safe_entries.append(entry)
            entries = safe_entries
            evidence = [{key: doc.get(key) for key in ("id", "title", "url", "source", "sourceId", "publishedAt", "publishedEstimated", "retrievedAt", "version")} for doc, _ in matched[:60]]
            fingerprint = a.digest(dumps({"documents": [(doc["id"], doc["version"]) for doc, _ in matched],
                                        "profiles": [(row["assetId"], row["profileVersion"], row["qualified"]) for row in entries + candidates]}))
            report = research_changes.get("marketResearch")
            report_digest = a.digest(dumps(report))
            at = now_ms()
            limitations = ["Topic matching uses exact source wording. A mention does not independently establish financial exposure or causation.",
                          "Topic subjects are linked to source citations. Financial profile qualification separately uses identity, market-data, trigger, observation-period, and risk gates.",
                          "No new evidence found means only the sources checked; missing measurements remain Data unavailable."]
            if not evidence: limitations.insert(0, "No matching collected source evidence is available. Research will continue as sources become available.")
            if evidence and not entries: limitations.insert(0, "Topic research is available. Financial monitoring entries require separate verified identity and market-data checks.")
            if pending: limitations.append("Provider data collection is queued for discovered instruments; this portfolio will be reassessed automatically.")
            if not self.s.ai.ready: limitations.append("Connect OpenAI for source-linked explanations, topic discovery, and companies, markets, and institutions to watch.")
            elif not self.s.auto_ai: limitations.append("Automatic paid AI analysis is off. Searches and manual refreshes still use your connected OpenAI model.")
            if research_changes.get("marketResearchWarning"): limitations.append(research_changes["marketResearchWarning"])
            limitations.extend(warnings + item.get("discoveryWarnings", []))
            if item.get("planWarning"): limitations.append(item["planWarning"])
            old = self._read(topic_id)
            before = {row["assetId"]: row for row in old.get("entries", []) + old.get("candidates", [])}
            after = {row["assetId"]: row for row in entries + candidates}
            changed = []
            if not old.get("version"): changed.append("Initial topic research completed within the checked source set.")
            for key in after.keys() - before.keys(): changed.append(after[key]["name"] + " was identified in topic evidence.")
            for key in before.keys() - after.keys(): changed.append(before[key]["name"] + " no longer has matching current topic evidence.")
            for key in after.keys() & before.keys():
                if (after[key]["status"], after[key]["qualified"]) != (before[key]["status"], before[key]["qualified"]):
                    changed.append(after[key]["name"] + ": monitoring status or topic qualification changed.")
            if old.get("sourceFingerprint") != fingerprint and old.get("version"):
                changed.append("Collected source records, revisions, or linked asset assessments changed.")
            if old.get("marketResearchDigest") != report_digest and old.get("version"):
                changed.append("The topic explanation or sourced subjects to watch changed.")
            material = old.get("sourceFingerprint") != fingerprint or old.get("marketResearchDigest") != report_digest or not old.get("version")
            version = old.get("version", 0) + int(material)
            state = "Monitoring" if evidence or report and (report.get("summary") or report.get("subjects")) else "Needs evidence"
            if not old.get("enabled", True): state = "Paused"
            next_refresh = at + (min(5, old.get("refreshMinutes", 60)) if pending else old.get("refreshMinutes", 60)) * 60000
            remaining_changes = self._unconsumed_changes(old.get("pendingEvidenceChanges", {}), matched, entries, candidates, item, cycle_started)
            if remaining_changes:
                next_refresh = min(next_refresh, old.get("nextRefreshAt", at + 30000))
            if research_changes.get("marketResearchStale"):
                next_refresh = min(next_refresh, at + 30000)
            result = self._complete(topic_id, old.get("pendingEvidenceChanges", {}), remaining_changes, used_request_token=request_token, **research_changes,
                assessment=None, assessmentFingerprint=None, model=report.get("model") if report else None, marketResearchDigest=report_digest,
                questions=report.get("nextQuestions", []) if report and report.get("nextQuestions") else item.get("questions", []),
                state=state, status=state, progress="Research ready; monitoring the topic for changes" if state == "Monitoring" else "Checking sources for information about your topic",
                entries=entries, candidates=candidates, evidence=evidence, qualifiedCount=len(entries), candidateCount=len(candidates),
                sectorCounts=dict(Counter(r["sector"] for r in entries)), geographyCounts=dict(Counter(r["country"] for r in entries)),
                checkedSources=checked, pendingProviderSources=pending, limitations=list(dict.fromkeys(limitations)),
                lastRunAt=at, nextRefreshAt=next_refresh,
                sourceFingerprint=fingerprint, version=version,
                whatChanged=changed or ["No material change found within the checked source set."], error=None)
            if result.get("deleted") or not result.get("enabled", True) and not result.get("manualAiRequest"): return result
            if material:
                self.db.put("topicRevision", topic_id + ":v" + str(version), result)
                self.db.audit("Topic watch portfolio revised", topic_id, {"version": version, "qualified": len(entries), "candidates": len(candidates)})
            self.s.network_research.topic_completed(result, use_ai=use_ai and not result.get("marketResearchStale"))
            return result
        except Exception:
            current = self._read(topic_id)
            if current.get("deleted") or not current.get("enabled", True) and not current.get("manualAiRequest"): return current
            self._update(topic_id, state="Failed", status="Failed", progress="Research will retry automatically", error="Topic research could not complete; retained evidence remains available.")
            raise

