"""Research application: collection, analysis, investigations, monitoring, and governance."""
from __future__ import annotations

import base64
from collections import Counter, deque
import datetime as dt
import io
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time
from urllib.parse import urlsplit

from . import analysis as a
from .ai import AI
from .connectors import Network, ConnectorError, DEFAULT_SOURCES, collect, strip_html, timestamp
from .storage import Database, ObjectStore, now_ms, identifier, dumps
from .investment import InvestmentEngine
from .ai_settings import AISettings
from .topics import TopicResearch
from .research_network import ResearchNetwork
from .accounts import AccountAuth


class ResearchService:
    def __init__(self, directory, network=None, seed=True, dsn=None):
        self.db = Database(directory, dsn=dsn if dsn is not None else os.getenv("DATABASE_URL"))
        self.objects = ObjectStore(Path(directory) / "objects")
        self.network = network or Network()
        self.ai = AI(self.network)
        self.stop_event, self.lock = threading.Event(), threading.RLock()
        self.threads = []
        self.started_at = now_ms()
        self.last_write = max([d.get("updatedAt", 0) for d in self.db.latest("document", 1)] or [0])
        self.auto_ai = os.getenv("CRAWLER_AUTO_AI", "false").lower() == "true"
        self.investments = InvestmentEngine(self)
        self.ai_settings = AISettings(self, directory)
        self.topics = TopicResearch(self)
        self.network_research = ResearchNetwork(self)
        self.accounts = AccountAuth(self, directory)
        if seed:
            for source in DEFAULT_SOURCES:
                if not self.db.get("source", source["id"]):
                    self.add_source({**source, "permissions": "Feed links and supplied summaries only; review provider terms for retention and commercial use.", "allowFullText": False})

    def health(self):
        return {"service": "trend-crawler", "version": 2, "startedAt": self.started_at, "workers": sum(t.is_alive() for t in self.threads),
                "storage": "PostgreSQL" if self.db.postgres else "SQLite WAL", "objects": "S3" if self.objects.bucket else "Content-addressed local objects",
                "ai": {"configured": self.ai.ready, "model": self.ai.model or None, "automaticAnalysis": self.auto_ai},
                "investment": {"profiles": self.db.count("assetProfile"), "secConfigured": bool(os.getenv("SEC_USER_AGENT")), "fredConfigured": bool(os.getenv("FRED_API_KEY")), "cryptoConfigured": bool(os.getenv("COINGECKO_API_KEY"))},
                "documents": self.db.count("document"), "sources": self.db.count("source"), "claims": self.db.count("claim"),
                "queued": len(self.db.jobs("queued", 1000)), "deadLetters": len(self.db.jobs("dead", 1000))}

    def add_source(self, values):
        url = str(values.get("url", ""))
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Enter a public HTTPS source URL without credentials")
        if values.get("kind", "rss") not in {"rss", "json", "fred", "coingecko", "sec", "fred_vintages", "coingecko_asset"}:
            raise ValueError("Choose a supported RSS, JSON, SEC, FRED, or CoinGecko connector")
        name = str(values.get("name", "")).strip()[:120]
        if not name:
            raise ValueError("Source name is required")
        for other in self.db.list("source"):
            if other["url"] == url and other["id"] != values.get("id"):
                if not (other["kind"] == values.get("kind") == "sec" and other.get("config", {}).get("ticker") != values.get("config", {}).get("ticker")):
                    raise ValueError("This source URL is already registered")
        existing = self.db.get("source", values.get("id", "")) or {}
        source = {**existing, **{key: values[key] for key in ("url", "kind", "family", "language", "region", "category", "permissions", "allowFullText", "geographyVerified", "config", "credentialEnv", "credentialHeader", "credentialPrefix") if key in values},
                  "id": existing.get("id") or values.get("id") or identifier("source"), "name": name,
                  "tier": values.get("tier", existing.get("tier", "regional")), "enabled": bool(values.get("enabled", existing.get("enabled", False))),
                  "interval": max(60000, min(86400000, int(values.get("interval", existing.get("interval", 300000))))),
                  "createdAt": existing.get("createdAt", now_ms()), "updatedAt": now_ms(), "nextPollAt": existing.get("nextPollAt", 0)}
        if source.get("allowFullText") and not str(source.get("permissions", "")).strip():
            raise ValueError("Record collection permissions before enabling full-document retrieval")
        self.db.put("source", source["id"], source)
        self.db.audit("Source configured", source["id"], {"name": name, "enabled": source["enabled"], "credentialConfigured": bool(source.get("credentialEnv") and os.getenv(source["credentialEnv"]))})
        return self.public_source(source)

    def public_source(self, source):
        # Only environment variable names and configuration state are exposed, never values.
        return {**source, "credentialConfigured": bool(source.get("credentialEnv") and os.getenv(source["credentialEnv"]))}

    def toggle_source(self, source_id, enabled):
        source = self.db.get("source", source_id)
        if not source:
            raise ValueError("Source not found")
        source.update(enabled=bool(enabled), nextPollAt=0, updatedAt=now_ms())
        self.db.put("source", source_id, source)
        self.db.audit("Source polling changed", source_id, {"enabled": bool(enabled)})
        return self.public_source(source)

    def _event(self, title, text, published, entities, embedding=None, exclude_id=None, default_id=None):
        best, score = None, .68
        ids = {entity["id"] for entity in entities if entity["type"] != "unresolved"}
        for doc in self.db.latest("document", 600):
            if doc["id"] == exclude_id:
                continue
            if abs(doc["publishedAt"] - published) > 3 * a.DAY:
                continue
            other_ids = {entity["id"] for entity in doc.get("entities", []) if entity["type"] != "unresolved"}
            if ids and other_ids and not ids.intersection(other_ids):
                continue
            overlap = a.text_similarity(title, doc.get("translation", {}).get("title") or doc["title"])
            if embedding and doc.get("embedding"):
                overlap = max(overlap, a.cosine(embedding, doc["embedding"]) if a.cosine(embedding, doc["embedding"]) >= .88 else 0)
            if overlap > score:
                score, best = overlap, doc["eventId"]
        return best or default_id or "event-" + a.digest(title + "|" + str(published))[:24]

    def ingest(self, source, record, at=None):
        at = at or now_ms()
        title, text, url = str(record.get("title", "")).strip()[:1500], str(record.get("text", "")).strip()[:60000], a.canonical_url(record.get("url", ""))
        if not title or not text or not url.startswith("https://"):
            raise ValueError("Document needs a title, source text, and HTTPS source URL")
        published = timestamp(record.get("publishedAt"), at)
        if published > at + 120000:
            raise ValueError("Document publication time is in the future")
        document_id = "document-" + a.digest(url)[:32]
        raw = record.get("raw", {"title": title, "text": text, "url": url})
        raw_bytes = dumps(raw).encode()
        credited = record.get("authors", record.get("author", []))
        if isinstance(credited, str): credited = [credited]
        authors = [{"name": (v.get("name", "") if isinstance(v, dict) else str(v)).strip()[:200], "attribution": "Publisher-supplied metadata"} for v in credited[:8]] if isinstance(credited, list) else []
        authors = [author for author in authors if author["name"]]
        content_hash = a.digest(dumps({"title": title, "text": text, "raw": raw, "authors": authors}))
        with self.lock:
            existing = self.db.get("document", document_id)
            if existing and existing["contentHash"] == content_hash:
                return self._index_document(existing) if existing.get("indexedVersion") != existing["version"] else existing
            object_key = self.objects.put(raw_bytes)
            entity_list = a.entities(text, record.get("entities"))
            self.last_write = max(at, self.last_write + 1)
            document = {"id": document_id, "title": title, "text": text, "url": url, "sourceId": source["id"], "source": source["name"],
                        "family": source.get("family", source["name"]), "tier": source.get("tier", "regional"), "language": record.get("language") or source.get("language", "unknown"),
                        "publisherRegion": source.get("region", ""), "publisherGeographyVerified": bool(source.get("geographyVerified")), "regions": a.regions(text),
                        "categories": sorted(set(a.categories(text) + ([source["category"]] if source.get("category") else []))), "entities": entity_list,
                        "publishedAt": published, "publishedEstimated": bool(record.get("publishedEstimated", record.get("publishedAt") is None)),
                        "retrievedAt": at, "firstRetrievedAt": existing.get("firstRetrievedAt", existing["retrievedAt"]) if existing else at,
                        "updatedAt": self.last_write, "eventAt": record.get("eventAt"), "correctedAt": at if existing else None,
                        "version": existing["version"] + 1 if existing else 1, "indexedVersion": 0, "contentHash": content_hash, "objectKey": object_key,
                        "eventId": existing["eventId"] if existing else self._event(title, text, published, entity_list), "originUrl": record.get("originUrl"), "authors": authors,
                        "mediaProvenance": record.get("mediaProvenance", {"status": "Not inspected", "authenticity": "Unknown"})}
            for field in ("companyId", "filingType", "accessionNumber", "policyRecord", "sourceUpdatedAt"):
                if field in record:
                    document[field] = record[field]
            self.db.version(document, object_key)
            return self._index_document(document)

    def _index_document(self, document):
        """Idempotent indexing repairs an interruption after the atomic source commit."""
        document_id, at = document["id"], document["retrievedAt"]
        if document["version"] > 1:
            for relation in self.db.latest("relationship", 20000):
                if relation.get("confirmed") and document_id in relation.get("evidence", []):
                    relation.update(confirmed=False, reviewRequired=True, invalidatedAt=at, confidence="Source changed; exposure needs renewed review")
                    self.db.put("relationship", relation["id"], relation)
            for claim in self.db.list("claim", 20000):
                dependent = claim.get("documentId") == document_id or any(link.get("documentId") == document_id for link in claim.get("evidence", []))
                if dependent and claim.get("sourceRevisions", {}).get(document_id) != document["version"]:
                    claim.setdefault("history", []).append({**{k: v for k, v in claim.items() if k != "history"}, "at": claim.get("updatedAt", claim["createdAt"]), "supersededAt": at, "version": document["version"] - 1})
                    claim.setdefault("sourceRevisions", {})[document_id] = document["version"]
                    claim.update(status="Developing", reviewRequired=True, updatedAt=at)
                    self.db.put("claim", claim["id"], claim)
            self.db.audit("Source revised", document_id, {"version": document["version"], "dependentClaims": "Flagged for review"})
        for claim in a.extract_claims(document["text"], document_id, document["eventId"], at):
            claim["sourceVersion"] = document["version"]
            if not self.db.get("claim", claim["id"]):
                self.db.put("claim", claim["id"], claim)
        event = self.db.get("event", document["eventId"]) or {"id": document["eventId"], "title": document["title"], "firstSeen": at, "history": []}
        event.update(updatedAt=at, lastSeen=at)
        self.db.put("event", event["id"], event)
        for entity in document["entities"]:
            self.db.put("entity", entity["id"], {**entity, "updatedAt": at})
            relation_id = "relationship-" + a.digest(document_id + entity["id"])[:28]
            previous = self.db.get("relationship", relation_id)
            relationship = {"id": relation_id, "from": entity["id"], "to": event["id"], "type": "mentioned-in", "confirmed": False, "evidence": [document_id], "validFrom": document["publishedAt"], "validTo": None, "createdAt": previous["createdAt"] if previous else at, "confidence": "Text match; relationship semantics unreviewed"}
            self.db.put("relationship", relationship["id"], relationship)
        if self.auto_ai and self.ai.ready:
            self.db.enqueue("enrich", {"documentId": document_id, "version": document["version"]}, "enrich:" + document_id + ":" + str(document["version"]))
        self.db.enqueue("analyze", {"eventId": event["id"]}, "analyze:" + event["id"] + ":" + str(at // 10000))
        document["indexedVersion"] = document["version"]
        self.db.put("document", document_id, document, at=document["updatedAt"])
        self.investments.queue("Source revision" if document["version"] > 1 else "New source evidence", document_id)
        self.topics.evidence_changed(document_id=document_id, source_id=document["sourceId"])
        return document

    def enrich(self, doc_id, version):
        doc = self.db.get("document", doc_id)
        if not doc or doc["version"] != version:
            return
        changes = {}
        if doc["language"] not in {"en", "en-US", "en-GB"}:
            changes["translation"] = {**self.ai.translate(doc), "createdAt": now_ms(), "sourceVersion": version}
        extracted = self.ai.extract(doc)
        for item in extracted:
            claim = {"id": "ai-claim-" + a.digest(doc_id + item["quote"])[:24], "text": item["text"], "quote": item["quote"], "documentId": doc_id, "eventId": doc["eventId"], "method": "AI extraction with validated quote", "status": "Unverified", "reviewRequired": True, "createdAt": now_ms(), "updatedAt": now_ms()}
            if not self.db.get("claim", claim["id"]):
                self.db.put("claim", claim["id"], claim)
        changes["embedding"] = self.ai.embed(changes.get("translation", {}).get("title", doc["title"]) + " " + doc["text"][:2000])
        # Do not overwrite a source revision that arrived while the provider request was running.
        with self.lock:
            current = self.db.get("document", doc_id)
            if current["version"] == version:
                self.last_write = max(now_ms(), self.last_write + 1)
                translated_title = changes.get("translation", {}).get("title", current["title"])
                grouped_event = self._event(translated_title, current["text"], current["publishedAt"], current["entities"], changes["embedding"], exclude_id=doc_id, default_id=current["eventId"])
                if grouped_event != current["eventId"]:
                    for claim in self.db.latest("claim", 20000):
                        if claim.get("documentId") == doc_id:
                            claim.setdefault("history", []).append({**{k: v for k, v in claim.items() if k != "history"}, "at": claim.get("updatedAt", claim["createdAt"]), "supersededAt": now_ms()})
                            claim.update(eventId=grouped_event, updatedAt=now_ms())
                            self.db.put("claim", claim["id"], claim)
                    changes["eventId"] = grouped_event
                    self.db.audit("Semantic event grouping revised", doc_id, {"previousEvent": current["eventId"], "eventId": grouped_event, "derived": True})
                    if not any(d["id"] != doc_id and d["eventId"] == current["eventId"] for d in self.db.latest("document", 20000)):
                        old_event = self.db.get("event", current["eventId"])
                        if old_event:
                            old_event["mergedInto"] = grouped_event
                            self.db.put("event", old_event["id"], old_event)
                current.update(**changes, analyzedAt=now_ms(), updatedAt=self.last_write)
                self.db.put("document", doc_id, current, at=self.last_write)
                self.db.put("enrichment", doc_id + ":" + str(now_ms()), {"documentId": doc_id, "sourceVersion": version, "createdAt": now_ms(), **changes})

    def documents(self, after=0, after_id="", limit=300):
        page = self.db.page("document", after, after_id, limit)
        return {"documents": [row["payload"] for row in page], "cursor": {"at": page[-1]["updatedAt"], "id": page[-1]["id"]} if page else {"at": after, "id": after_id}, "hasMore": len(page) == limit}

    def source_health(self):
        enabled = [s for s in self.db.list("source") if s.get("enabled")]
        if not enabled:
            return 0
        return sum(bool(s.get("health", {}).get("ok")) and now_ms() - s.get("health", {}).get("checkedAt", 0) < max(s["interval"] * 3, 900000) for s in enabled) / len(enabled)

    def provider_coverage(self, at, window=a.DAY):
        sources = [source for source in self.db.list("source") if source.get("enabled")]
        samples = self.db.latest("healthSample", 50000)
        spans_by_source = {}
        for source in sources:
            checks = sorted((sample for sample in samples if sample["sourceId"] == source["id"] and sample["checkedAt"] <= at), key=lambda sample: sample["checkedAt"])
            spans = []
            for index, check in enumerate(checks):
                if check["ok"]:
                    until = min(at, check["checkedAt"] + check["interval"] * 3, checks[index + 1]["checkedAt"] if index + 1 < len(checks) else at)
                    spans.append({"start": check["checkedAt"], "end": until})
            spans_by_source[source["id"]] = spans
        complete_source_set = bool(sources) and all(source["createdAt"] <= at - 2 * window for source in sources)
        current = sum(a.coverage_fraction(spans, at - window, at) for spans in spans_by_source.values()) / max(1, len(sources))
        previous = sum(a.coverage_fraction(spans, at - 2 * window, at - window) for spans in spans_by_source.values()) / max(1, len(sources))
        return {"current": round(current, 4), "previous": round(previous, 4), "stableSourceSet": complete_source_set}

    def analyze_event(self, event_id, at=None):
        at = at or now_ms()
        docs = [d for d in self.db.latest("document", 20000) if d["eventId"] == event_id and d["retrievedAt"] <= at]
        coverage = self.db.get("setting", "coverage") or {"spans": []}
        provider_coverage = self.provider_coverage(at)
        comparable_health = min(self.source_health(), provider_coverage["current"], provider_coverage["previous"]) if provider_coverage["stableSourceSet"] else 0
        result = a.analyze_trend(docs, at, coverage["spans"], comparable_health)
        result["providerCoverage"] = provider_coverage
        event = self.db.get("event", event_id)
        if not event:
            raise ValueError("Event not found")
        if not event.get("analysis") or event["analysis"]["lifecycle"] != result["lifecycle"]:
            event.setdefault("history", []).append({"at": at, "lifecycle": result["lifecycle"], "recordCount": len(docs)})
        event.update(analysis=result, analyzedAt=at)
        self.db.put("event", event_id, event)
        return result

    def dossier(self, document_id=None, event_id=None):
        doc = self.db.get("document", document_id) if document_id else None
        event_id = event_id or (doc or {}).get("eventId")
        event = self.db.get("event", event_id or "")
        if event and event.get("mergedInto"):
            event_id = event["mergedInto"]
            event = self.db.get("event", event_id)
        if not event:
            raise ValueError("Collected event not found")
        docs = [d for d in self.db.latest("document", 20000) if d["eventId"] == event_id]
        claims = [c for c in self.db.latest("claim", 20000) if c["eventId"] == event_id]
        contradictions = a.candidate_contradictions(claims)
        entity_ids = {e["id"] for d in docs for e in d.get("entities", [])}
        metrics = [m for m in a.quantitative(self.db.latest("observation", 20000), now_ms()) if m["assetId"] in entity_ids]
        known_regions = {region for d in docs for region in d.get("regions", [])}
        local_regions = {d["publisherRegion"] for d in docs if d.get("publisherGeographyVerified")}
        gaps = []
        missing = known_regions - local_regions
        if missing:
            gaps.append("Verified local publisher coverage is missing for: " + ", ".join(sorted(missing)))
        if not any(d["tier"] == "primary" for d in docs):
            gaps.append("No linked primary record.")
        if len({d["language"] for d in docs}) < 2:
            gaps.append("Only one source language is represented.")
        if any(d.get("language") != "en" and not d.get("translation") for d in docs):
            gaps.append("Some original-language records have no English translation; originals remain available.")
        investigations = [r for r in self.db.latest("investigation", 500) if r["eventId"] == event_id]
        return {"event": event, "documents": docs, "claims": claims, "contradictions": contradictions, "trend": self.analyze_event(event_id), "coverageGaps": gaps,
                "reportingChains": [[d["id"] for d in group] for group in a.reporting_chains(docs)], "metrics": metrics,
                "graph": self.graph(event_id), "investigations": investigations, "relationshipsAreCausal": False}

    def observation(self, source, values, at=None):
        at = at or now_ms()
        asset_id = str(values.get("assetId", ""))
        if ":" not in asset_id:
            raise ValueError("Observation assetId must include its namespace")
        raw_value = values.get("value")
        try:
            value = float(raw_value)
        except (ValueError, TypeError):
            value = float("nan")
        if isinstance(raw_value, bool) or not math.isfinite(value):
            raise ValueError("Observation value must be a finite number")
        observed = timestamp(values.get("observedAt"))
        if observed is None or observed > at + 120000:
            raise ValueError("Observation needs a valid provider timestamp")
        values = dict(values)
        if values.get("availableAt") is not None:
            available = timestamp(values["availableAt"])
            if isinstance(values["availableAt"], bool) or available is None:
                raise ValueError("Observation availability needs a valid timestamp")
            values["availableAt"] = available
        transaction = values.get("transactionHash")
        if transaction:
            key = asset_id + "|" + transaction + "|" + str(values.get("logIndex", 0)) + "|" + str(values.get("metric", "value"))
        else:
            key = asset_id + "|" + str(values.get("metric", "value")) + "|" + str(observed) + "|" + source["id"] + "|" + str(values.get("periodStart", "")) + "|" + str(values.get("periodEnd", "")) + "|" + str(values.get("unit", "")) + "|" + str(values.get("vintageDate", "")) + "|" + str(values.get("revisionKey", ""))
        record_id = "observation-" + a.digest(key)[:32]
        existing = self.db.get("observation", record_id)
        record = {**values, "id": record_id, "sourceId": source["id"], "observedAt": observed, "retrievedAt": at, "canonical": not bool(values.get("removed")), "value": value,
                  "originalValue": values.get("originalValue", raw_value), "timeZone": values.get("timeZone", "UTC"), "sourceUrl": values.get("sourceUrl", source["url"]), "providerId": values.get("providerId", source.get("family", source["id"]))}
        if existing and all(existing.get(k) == v for k, v in record.items() if k != "retrievedAt"):
            return existing
        if existing and transaction and existing.get("blockHash") != values.get("blockHash"):
            self.db.put("observationRevision", identifier("reorg"), {"original": existing, "replacement": record, "at": at})
            self.db.audit("Chain reorganization", record_id, {"oldBlockHash": existing.get("blockHash"), "newBlockHash": values.get("blockHash")})
        if existing and not transaction and existing.get("value") != value:
            self.db.put("observationRevision", identifier("revision"), {"original": existing, "replacement": record, "at": at})
        if existing:
            vintage_id = record_id + ":" + str(existing["retrievedAt"])
            self.db.put("observationVintage", vintage_id, {**existing, "id": vintage_id, "originalObservationId": record_id, "supersededAt": at})
        self.db.put("observation", record_id, record)
        self.investments.queue("Financial observation or revision", record_id)
        self.topics.evidence_changed(asset_id=asset_id, source_id=source["id"])
        return record

    def graph(self, start, depth=2, as_of=None):
        at = as_of or now_ms()
        edges = [r for r in self.db.latest("relationship", 10000) if r["createdAt"] <= at and r.get("validFrom", 0) <= at and (not r.get("validTo") or r["validTo"] >= at)]
        frontier, seen, found = deque([(start, 0)]), {start}, []
        while frontier and len(seen) < 100:
            node, distance = frontier.popleft()
            if distance >= min(3, max(1, depth)):
                continue
            for edge in edges:
                if node not in {edge["from"], edge["to"]}:
                    continue
                if not any(item["id"] == edge["id"] for item in found):
                    found.append(edge)
                other = edge["to"] if node == edge["from"] else edge["from"]
                if other not in seen:
                    seen.add(other)
                    frontier.append((other, distance + 1))
        return {"nodes": [{"id": key, **(self.db.get("entity", key) or {"name": (self.db.get("event", key) or {}).get("title", key), "type": "event"})} for key in seen], "relationships": found, "depth": min(3, max(1, depth)), "hypotheses": [r["id"] for r in found if not r.get("confirmed")]}

    def add_relationship(self, values):
        evidence = [doc_id for doc_id in values.get("evidence", []) if self.db.get("document", doc_id)]
        if not evidence or not values.get("from") or not values.get("to") or not values.get("type"):
            raise ValueError("Relationship needs entities/events, a relation type, and collected evidence IDs")
        if values.get("confirmed") and not values.get("reviewed"):
            raise ValueError("Confirmed relationships require explicit analyst review")
        if values.get("quote") and not any(str(values["quote"]).strip() and str(values["quote"]) in self.db.get("document", doc_id)["text"] for doc_id in evidence):
            raise ValueError("The supporting quote must occur in the linked source record")
        record = {"id": identifier("relationship"), "from": str(values["from"])[:200], "to": str(values["to"])[:200], "type": str(values["type"])[:100], "evidence": evidence, "evidenceVersions": {doc_id: self.db.get("document", doc_id)["version"] for doc_id in evidence}, "confirmed": bool(values.get("confirmed")), "confidence": str(values.get("confidence", "Hypothesis")), "validFrom": int(values.get("validFrom") or now_ms()), "validTo": values.get("validTo"), "createdAt": now_ms()}
        self.db.put("relationship", record["id"], record)
        self.db.audit("Relationship reviewed", record["id"], record)
        self.investments.queue("Documented exposure changed", record["id"])
        return record

    def review_claim(self, values):
        claim = self.db.get("claim", values.get("id", ""))
        if not claim:
            raise ValueError("Extracted claim not found")
        status = values.get("status")
        if status not in {"Verified", "Corroborated", "Developing", "Unverified", "Disputed", "Misleading", "Contradicted", "Retracted"} or not str(values.get("rationale", "")).strip():
            raise ValueError("Choose an evidence status and explain the assessment")
        evidence = values.get("evidence", [])
        documents = [self.db.get("document", link.get("documentId", "")) for link in evidence]
        if any(doc is None for doc in documents):
            raise ValueError("Every evidence link must reference a collected record")
        support = [doc for doc, link in zip(documents, evidence) if link.get("relation") == "supports"]
        if status == "Verified" and (not support or not values.get("directEvidenceReviewed")):
            raise ValueError("Verification requires supporting direct evidence reviewed by an analyst")
        if status == "Corroborated" and (len(a.reporting_chains(support)) < 2 or not values.get("independenceReviewed")):
            raise ValueError("Corroboration requires two candidate chains and an independence review")
        if status in {"Disputed", "Contradicted"} and not any(link.get("relation") == "contradicts" for link in evidence):
            raise ValueError("Link the contradicting evidence")
        if status in {"Retracted", "Misleading"} and not evidence:
            raise ValueError("Link the publisher correction or contextual evidence")
        if claim.get("highConsequence") and status in {"Verified", "Corroborated"} and not values.get("additionalReview"):
            raise ValueError("High-consequence claims need an additional recorded review")
        claim.setdefault("history", []).append({**{k: v for k, v in claim.items() if k != "history"}, "at": claim.get("updatedAt", claim["createdAt"]), "supersededAt": now_ms()})
        claim.update(status=status, rationale=str(values["rationale"])[:4000], evidence=evidence, reviewRequired=False, updatedAt=now_ms(), reviewer=str(values.get("reviewer", "Local analyst"))[:120], additionalReview=bool(values.get("additionalReview")), directEvidenceReviewed=bool(values.get("directEvidenceReviewed")), independenceReviewed=bool(values.get("independenceReviewed")))
        self.db.put("claim", claim["id"], claim)
        self.db.audit("Claim reviewed", claim["id"], {"status": status, "rationale": claim["rationale"], "evidence": evidence})
        if status == "Retracted":
            removed_ids = {link["documentId"] for link in evidence}
            for dependent in self.db.latest("claim", 20000):
                if dependent["id"] != claim["id"] and (dependent.get("documentId") in removed_ids or any(link.get("documentId") in removed_ids for link in dependent.get("evidence", []))):
                    dependent.setdefault("history", []).append({**{k: v for k, v in dependent.items() if k != "history"}, "at": dependent.get("updatedAt", dependent["createdAt"]), "supersededAt": now_ms(), "reason": "Dependent source was retracted"})
                    dependent.update(status="Developing", reviewRequired=True, updatedAt=now_ms())
                    self.db.put("claim", dependent["id"], dependent)
        self.investments.queue("Claim review or contradiction", claim["id"])
        return claim

    def investigate(self, event_id):
        dossier = self.dossier(event_id=event_id)
        docs = dossier["documents"]
        questions = ["What direct evidence would disprove the central reported statement?", "Which original record supports the numbers, dates, and attributed statements?", "Are reporting chains independently investigated or syndicated?"]
        if dossier["coverageGaps"]:
            questions += dossier["coverageGaps"]
        candidate_docs = []
        event_text = " ".join(doc["title"] for doc in docs[:5])
        for doc in self.db.latest("document", 3000):
            if doc["eventId"] != event_id and a.text_similarity(event_text, doc["title"]) > .3:
                candidate_docs.append({"documentId": doc["id"], "title": doc["title"], "reason": "Related collected record; inspect for disconfirming or primary evidence"})
        # Follow-up collection is bounded to registered, enabled sources; never arbitrary model URLs.
        enabled = [s for s in self.db.list("source") if s.get("enabled")]
        relevant = [s for s in enabled if s.get("tier") == "primary" or s.get("category") in {category for doc in docs for category in doc["categories"]}]
        job_ids = [self.db.enqueue("poll", {"sourceId": source["id"]}, "investigate:" + event_id + ":" + source["id"] + ":" + str(now_ms() // 600000)) for source in relevant[:4]]
        result = {"id": identifier("investigation"), "eventId": event_id, "createdAt": now_ms(), "questions": questions, "candidateEvidence": candidate_docs[:15], "followupJobs": job_ids, "conclusion": "Open investigation; collection and comparison do not establish truth."}
        self.db.put("investigation", result["id"], result)
        self.db.audit("Disconfirmation investigation started", event_id, {"questions": len(questions), "followupJobs": len(job_ids)})
        return result

    def research(self, question, conversation_id="default", use_ai=True):
        question = str(question).strip()[:1000]
        if not question:
            raise ValueError("Enter a research question")
        conversation_id = re.sub(r"[^a-zA-Z0-9_-]", "", str(conversation_id))[:100] or "default"
        memory = self.db.get("memory", conversation_id) or {"turns": [], "topic": ""}
        followup = bool(re.match(r"(?i)^(what changed|what about|and |why |show (the )?(evidence|sources)|what would)", question))
        terms = a.tokens(question + (" " + memory["topic"] if followup else ""))
        generic = set("what which should watch happening developments evidence sources verification independent primary about changed show research strongest arguments against interpretation".split())
        terms = [word for word in terms if word not in generic]
        documents = self.db.latest("document", 10000)
        scored = [(sum(1 for word in terms if word in a.tokens(doc["title"] + " " + doc["text"][:2000] + " " + dumps(doc.get("translation", {})))), doc) for doc in documents]
        selected = [doc for score, doc in sorted(scored, key=lambda pair: (pair[0], pair[1]["publishedAt"]), reverse=True) if score > 0][:12] if terms else documents[:12]
        if re.search(r"\bprimary\b", question, re.I):
            selected = [doc for doc in selected if doc["tier"] == "primary"]
        if selected and self.ai.ready and use_ai:
            result = self.ai.answer(question, selected, memory["turns"])
        else:
            result = {"answer": "Collected evidence matching your question." if selected else "Insufficient evidence in the collected records to answer this question.",
                      "assertions": [{"text": "Reported by " + doc["source"] + ": " + doc["title"], "documentIds": [doc["id"]], "quotes": [doc["title"] if doc["title"] in doc["text"] else doc["text"][:200]]} for doc in selected[:6]],
                      "uncertainties": ["These are attributed source statements, not independently verified conclusions."] + ([] if self.ai.ready else ["AI is not configured; using deterministic retrieval."]),
                      "nextQuestions": ["Which original records support these statements?", "What evidence would invalidate this interpretation?"], "model": None}
        result.update(documents=[{"id": d["id"], "title": d["title"], "url": d["url"], "source": d["source"], "eventId": d["eventId"]} for d in selected], conversationId=conversation_id)
        memory["topic"] = " ".join(terms[:12])
        memory["turns"] = (memory["turns"] + [{"question": question, "at": now_ms(), "documentIds": [d["id"] for d in selected]}])[-30:]
        self.db.put("memory", conversation_id, memory)
        self.db.put("research", identifier("research"), {"at": now_ms(), "question": question, "result": result})
        return result

    def create_monitor(self, values):
        query = str(values.get("query", "")).strip()[:400]
        if not query:
            raise ValueError("Enter a topic or a monitoring question")
        # Natural-language convenience remains deterministic and the parsed rule is visible/editable.
        threshold = re.search(r"(?:momentum|score)\s*(?:above|over|>=|greater than)?\s*(\d{1,3})", query, re.I)
        clean_query = re.sub(r"(?i)^(?:alert me|notify me|watch|monitor)(?: when| if| for)?\s*", "", query)
        clean_query = re.sub(r"(?i)\s+(?:with |when )?momentum\s*(?:above|over|>=|greater than)?\s*\d{1,3}.*$", "", clean_query)
        record = {"id": identifier("monitor"), "query": str(values.get("topic") or clean_query), "originalQuestion": query, "minMomentum": max(0, min(100, int(values.get("minMomentum", threshold.group(1) if threshold else 0)))), "enabled": True, "createdAt": now_ms(), "lastMatches": []}
        self.db.put("monitor", record["id"], record)
        self.db.audit("Monitor created", record["id"], record)
        return record

    def evaluate_monitors(self):
        events = [event for event in self.db.latest("event", 3000) if not event.get("mergedInto")]
        for monitor in self.db.list("monitor"):
            if not monitor["enabled"]:
                continue
            found = [event["id"] for event in events if all(term in (event["title"] + " " + dumps(event.get("analysis", {}))).lower() for term in a.tokens(monitor["query"])) and event.get("analysis", {}).get("momentum", 0) >= monitor["minMomentum"]]
            new = [event for event in found if event not in monitor.get("lastMatches", [])]
            for event_id in new:
                notification = {"id": identifier("notification"), "monitorId": monitor["id"], "eventId": event_id, "title": "Monitor match: " + monitor["query"], "createdAt": now_ms(), "read": False}
                self.db.put("notification", notification["id"], notification)
            monitor.update(lastMatches=found, checkedAt=now_ms())
            self.db.put("monitor", monitor["id"], monitor)

    def forecast(self, values):
        statement, assumptions = str(values.get("statement", "")).strip(), str(values.get("assumptions", "")).strip()
        due = int(values.get("dueAt", 0))
        probability = values.get("probability")
        if not statement or not assumptions or due <= now_ms():
            raise ValueError("Enter a measurable scenario, its assumptions, and a future review date")
        if probability is not None and (not isinstance(probability, (int, float)) or not 0 <= probability <= 1):
            raise ValueError("Optional analyst probability must be between zero and one")
        record = {"id": identifier("forecast"), "eventId": values.get("eventId"), "statement": statement[:3000], "assumptions": assumptions[:3000], "dueAt": due, "createdAt": now_ms(), "probability": probability, "cohort": str(values.get("cohort", "default"))[:100], "outcome": "Pending", "confidence": "Analyst scenario; uncalibrated"}
        self.db.put("forecast", record["id"], record)
        self.db.audit("Forecast recorded", record["id"], record)
        return record

    def resolve_forecast(self, record_id, values):
        with self.lock:
            record = self.db.get("forecast", record_id)
            if not record or record.get("resolvedAt"):
                raise ValueError("Forecast is unavailable or already resolved")
            if values.get("outcome") not in {"Occurred", "Did not occur", "Inconclusive"} or not str(values.get("evidence", "")).strip():
                raise ValueError("Record an outcome and supporting evidence references")
            record.update(outcome=values["outcome"], resolution=str(values["evidence"])[:4000], resolvedAt=now_ms())
            self.db.put("forecast", record_id, record)
            self.db.audit("Forecast outcome recorded", record_id, {"outcome": record["outcome"], "evidence": record["resolution"]})
            return record

    def brief(self, schedule_id=None):
        events = sorted((event for event in self.db.latest("event", 3000) if not event.get("mergedInto")), key=lambda event: event.get("analysis", {}).get("momentum", 0), reverse=True)[:12]
        at = now_ms()
        sections = []
        docs = self.db.latest("document", 20000)
        for event in events:
            evidence = [doc for doc in docs if doc["eventId"] == event["id"]][:4]
            sections.append({"eventId": event["id"], "title": event["title"], "lifecycle": event.get("analysis", {}).get("lifecycle", "Unassessed"), "momentum": event.get("analysis", {}).get("momentum"), "sources": [{"id": d["id"], "source": d["source"], "url": d["url"]} for d in evidence], "watchNext": "Check the original record, independent investigation, and subsequent measurable updates."})
        record = {"id": identifier("brief"), "createdAt": at, "scheduleId": schedule_id, "sections": sections, "note": "Evidence-linked collection brief. Inclusion measures attention, not truth or a trade recommendation."}
        self.db.put("brief", record["id"], record)
        return record

    def schedule_brief(self, values):
        hours = max(1, min(720, int(values.get("hours", 24))))
        record = {"id": identifier("schedule"), "name": str(values.get("name", "Intelligence brief"))[:120], "hours": hours, "enabled": True, "nextRunAt": now_ms() + hours * a.HOUR, "createdAt": now_ms()}
        self.db.put("schedule", record["id"], record)
        return record

    def replay(self, at):
        if at > now_ms() or at <= 0:
            raise ValueError("Choose a past timestamp for historical replay")
        documents = self.db.replay(at)
        enrichments = sorted((item for item in self.db.latest("enrichment", 20000) if item["createdAt"] <= at), key=lambda item: item["createdAt"])
        for document in documents:
            for item in enrichments:
                if item["documentId"] == document["id"] and item["sourceVersion"] == document["version"]:
                    document.update({key: item[key] for key in ("translation", "embedding", "eventId") if key in item})
        claims = []
        for claim in self.db.latest("claim", 20000):
            if claim["createdAt"] > at:
                continue
            if claim.get("updatedAt", claim["createdAt"]) > at:
                history = [h for h in claim.get("history", []) if h["at"] <= at]
                if history:
                    claim = {**history[-1]}
                    claim.pop("supersededAt", None)
                else:
                    claim = {key: claim[key] for key in ("id", "eventId", "documentId", "text", "quote", "createdAt", "method") if key in claim}
                    claim.update(status="Unverified", rationale="No reviewed assessment was available at the replay time.")
            claim = {key: value for key, value in claim.items() if key != "history"}
            claims.append(claim)
        visible_ids = {doc["id"] for doc in documents}
        claims = [c for c in claims if c.get("documentId") in visible_ids]
        return {"asOf": at, "documents": documents, "claims": claims, "graph": [r for r in self.db.latest("relationship", 10000) if r["createdAt"] <= at and all(doc_id in visible_ids for doc_id in r["evidence"])], "note": "Uses the latest source version retrieved at or before the requested time. Later translations, AI enrichment, and reviews are excluded."}

    def import_document(self, values):
        source = self.db.get("source", values.get("sourceId", ""))
        if not source:
            raise ValueError("Select a registered source and record its collection permissions")
        if not source.get("permissions"):
            raise ValueError("Source permissions are not recorded")
        content_type = values.get("contentType", "text/plain")
        if values.get("contentBase64"):
            try:
                data = base64.b64decode(values["contentBase64"], validate=True)
            except ValueError as exc:
                raise ValueError("Invalid base64 document") from exc
        else:
            data = str(values.get("text", "")).encode()
        if len(data) > 8 * 1024 * 1024:
            raise ValueError("Document exceeds 8 MB limit")
        provenance = {"sha256": hashlib.sha256(data).hexdigest(), "contentType": content_type, "status": "Metadata recorded; authenticity unknown", "authenticity": "Unknown"}
        if content_type == "application/pdf":
            try:
                from pypdf import PdfReader
            except ImportError as exc:
                raise ValueError("PDF parsing requires: pip install pypdf") from exc
            pdf = PdfReader(io.BytesIO(data))
            if pdf.is_encrypted or len(pdf.pages) > 100:
                raise ValueError("Encrypted PDFs and PDFs over 100 pages are not accepted")
            text = " ".join(page.extract_text() or "" for page in pdf.pages)[:60000]
            provenance["metadata"] = {str(k): str(v)[:1000] for k, v in (pdf.metadata or {}).items()}
        elif content_type.startswith("image/") or content_type.startswith("video/"):
            tool = os.getenv("C2PA_TOOL")
            if tool:
                with tempfile.NamedTemporaryFile(suffix=".asset", delete=False) as handle:
                    handle.write(data)
                    filename = handle.name
                try:
                    response = subprocess.run([tool, filename, "--json"], capture_output=True, timeout=20, check=False)
                    provenance["credentials"] = json.loads(response.stdout.decode()) if response.returncode == 0 else {"status": "Validator could not validate this asset"}
                    provenance["status"] = "C2PA validator inspected; content truth is not established"
                finally:
                    Path(filename).unlink(missing_ok=True)
            provenance["objectKey"] = self.objects.put(data)
            text = str(values.get("description", ""))
            if not text:
                raise ValueError("Media records need an analyst description; no visual authenticity conclusion is inferred")
        elif content_type in {"text/plain", "text/html", "application/json"}:
            text = data.decode("utf-8", "replace")
            if content_type == "text/html":
                text = strip_html(text)
        else:
            raise ValueError("Supported formats: text, HTML, JSON, PDF, images, and video provenance records")
        provenance["originalObjectKey"] = self.objects.put(data)
        return self.ingest(source, {"title": values.get("title"), "text": text, "url": values.get("url"), "publishedAt": values.get("publishedAt"), "language": values.get("language", source.get("language")), "mediaProvenance": provenance, "raw": {"objectKey": provenance["originalObjectKey"], "contentType": content_type, "suppliedMetadata": values.get("metadata", {})}})

    def fetch_document(self, source_id, url):
        source = self.db.get("source", source_id)
        if not source or not source.get("allowFullText") or not source.get("permissions"):
            raise ValueError("Full-document retrieval is not enabled for this source")
        if urlsplit(url).hostname != urlsplit(source["url"]).hostname:
            raise ValueError("Document must be on the registered source's hostname")
        if not self.network.allowed(url):
            raise ConnectorError("Document collection is disallowed by robots.txt")
        data, metadata, resolved = self.network.fetch(url)
        if urlsplit(resolved).hostname != urlsplit(source["url"]).hostname:
            raise ValueError("Document redirected outside the registered provider")
        content_type = metadata.get("content-type", "text/html").split(";")[0]
        return self.import_document({"sourceId": source_id, "url": resolved, "title": urlsplit(resolved).path.rsplit("/", 1)[-1] or source["name"], "contentType": content_type, "contentBase64": base64.b64encode(data).decode()})

    def workspace(self):
        return {"monitors": self.db.list("monitor"), "notifications": self.db.latest("notification", 100), "forecasts": self.db.latest("forecast", 500), "forecastEvaluation": a.evaluate_forecasts(self.db.latest("forecast", 5000)), "briefs": self.db.latest("brief", 30), "schedules": self.db.list("schedule"), "saved": self.db.get("setting", "workspace") or {"saved": [], "notes": {}}, "audit": self.db.audit_entries(100)}

    def save_workspace(self, values):
        record = {"saved": list(dict.fromkeys(str(value)[:200] for value in values.get("saved", [])))[:1000], "notes": {str(key)[:200]: str(value)[:20000] for key, value in values.get("notes", {}).items()}, "updatedAt": now_ms()}
        self.db.put("setting", "workspace", record)
        return record

    def heartbeat(self, at=None):
        at = at or now_ms()
        record = self.db.get("setting", "coverage") or {"spans": []}
        spans = record["spans"]
        if spans and at - spans[-1]["end"] < 90000:
            spans[-1]["end"] = at
        else:
            spans.append({"start": at, "end": at})
        record["spans"] = [span for span in spans if span["end"] >= at - 366 * a.DAY]
        self.db.put("setting", "coverage", record)

    def poll_source(self, source_id):
        source = self.db.get("source", source_id)
        if not source or not source.get("enabled"):
            return
        if source["kind"] == "sec" and source.get("config", {}).get("discoveryOnly"):
            self.investments.discover()
            result = {"raw": b'{"scope":"Official identity catalogue discovery only"}'}
        elif source["kind"] in {"sec", "fred_vintages", "coingecko_asset"}:
            from .financial_connectors import collect_financial_source
            result = collect_financial_source(source, self.network)
        else:
            result = collect(source, self.network)
        raw_key = self.objects.put(result["raw"])
        self.investments.accept_assets(result.get("assets", []), source)
        before = self.db.count("document")
        for record in result.get("documents", []):
            self.ingest(source, record)
        for observation in result.get("observations", []):
            self.observation(source, observation)
        added = self.db.count("document") - before
        source = self.db.get("source", source_id)
        health = source.get("health", {"checks": 0, "successes": 0})
        health.update(ok=True, checkedAt=now_ms(), lastSuccess=now_ms(), checks=health.get("checks", 0) + 1, successes=health.get("successes", 0) + 1, rawObjectKey=raw_key, error="")
        self.db.put("healthSample", identifier("health"), {"sourceId": source_id, "checkedAt": health["checkedAt"], "ok": True, "interval": source["interval"]})
        source.update(health=health, nextPollAt=now_ms() + (max(60000, source["interval"] // 2) if added > 15 else source["interval"] if added else min(86400000, max(source["interval"], min(3600000, source["interval"] * 2)))))
        self.db.put("source", source_id, source)
        self.investments.queue("Provider collection completed", source_id)
        self.topics.evidence_changed(source_id=source_id)

    def run_job(self, job):
        payload = job["payload"]
        if job["kind"] == "poll":
            self.poll_source(payload["sourceId"])
        elif job["kind"] == "analyze":
            self.analyze_event(payload["eventId"])
        elif job["kind"] == "enrich":
            self.enrich(payload["documentId"], payload["version"])
        elif job["kind"] == "investigate":
            self.investigate(payload["eventId"])
        elif job["kind"] == "brief":
            self.brief(payload.get("scheduleId"))
        elif job["kind"] == "fetch-document":
            self.fetch_document(payload["sourceId"], payload["url"])
        elif job["kind"] == "research-cycle":
            self.investments.cycle(payload.get("reason", "Evidence changed"))
        elif job["kind"] == "discover-assets":
            self.investments.discover()
        elif job["kind"] == "coordinate-research":
            self.investments.coordinate(payload["assetId"], payload["version"])
        elif job["kind"] == "topic-research":
            self.topics.run(payload["topicId"])
        elif job["kind"] == "network-index":
            self.network_research.build(payload["topicId"], use_ai=payload.get("useAI", False))
        elif job["kind"] == "network-research":
            self.network_research.run_task(payload["taskId"])
        else:
            raise ValueError("Unsupported job type")

    def _renew_job_lease(self, job_id, finished):
        while not finished.wait(30):
            if self.stop_event.is_set(): return
            try:
                if not self.db.renew_job(job_id): return
            except Exception:
                # A database outage leaves the last lease recoverable.
                continue

    def worker(self):
        while not self.stop_event.is_set():
            try:
                job = self.db.claim_job()
            except Exception:
                self.stop_event.wait(2)
                continue
            if not job:
                self.stop_event.wait(.5)
                continue
            finished = threading.Event()
            lease = threading.Thread(target=self._renew_job_lease, args=(job["id"], finished), name="crawler-job-lease", daemon=True)
            lease.start()
            try:
                self.run_job(job)
                self.db.finish_job(job["id"])
            except Exception as exc:
                # Errors must not include provider URLs, keys, or raw response bodies.
                message = str(exc) if isinstance(exc, (ConnectorError, ValueError)) else type(exc).__name__ + ": service job failed"
                try:
                    self.db.fail_job(job, message, getattr(exc, "retry_after", None))
                except Exception:
                    # A lost database connection leaves the lease recoverable.
                    self.stop_event.wait(2)
                    continue
                if job["kind"] == "poll":
                    source = self.db.get("source", job["payload"]["sourceId"])
                    if source:
                        health = source.get("health", {})
                        health.update(ok=False, checkedAt=now_ms(), checks=health.get("checks", 0) + 1, error=message)
                        self.db.put("healthSample", identifier("health"), {"sourceId": source["id"], "checkedAt": health["checkedAt"], "ok": False, "interval": source["interval"]})
                        source.update(health=health, nextPollAt=now_ms() + min(3600000, source["interval"] * 2 ** job["attempts"]))
                        self.db.put("source", source["id"], source)
            finally:
                finished.set()
                lease.join(timeout=.2)

    def scheduler(self):
        last_heartbeat = last_monitor = last_analysis = last_research = last_discovery = 0
        while not self.stop_event.is_set():
            at = now_ms()
            try:
                if at - last_heartbeat >= 30000:
                    self.heartbeat(at)
                    last_heartbeat = at
                for source in self.db.list("source"):
                    if not source.get("enabled") or source.get("nextPollAt", 0) > at:
                        continue
                    pending = self.db.get_job(source.get("inFlight", ""))
                    if pending and pending["state"] in {"queued", "running"}:
                        continue
                    source["inFlight"] = self.db.enqueue("poll", {"sourceId": source["id"]}, "poll:" + source["id"] + ":" + str(at // 1000))
                    source["nextPollAt"] = at + source["interval"]
                    self.db.put("source", source["id"], source)
                for schedule in self.db.list("schedule"):
                    if schedule["enabled"] and schedule["nextRunAt"] <= at:
                        self.db.enqueue("brief", {"scheduleId": schedule["id"]}, "brief:" + schedule["id"] + ":" + str(schedule["nextRunAt"]))
                        schedule["nextRunAt"] = at + schedule["hours"] * a.HOUR
                        self.db.put("schedule", schedule["id"], schedule)
                if at - last_monitor >= 30000:
                    self.evaluate_monitors()
                    self.topics.refresh_due()
                    last_monitor = at
                if at - last_analysis >= 300000:
                    for event in self.db.latest("event", 300):
                        if event.get("lastSeen", 0) > at - 7 * a.DAY:
                            self.db.enqueue("analyze", {"eventId": event["id"]}, "periodic-analysis:" + event["id"] + ":" + str(at // 300000))
                    last_analysis = at
                rules = self.investments.rules()
                if rules["enabled"] and at - last_research >= rules["cycleMinutes"] * 60000:
                    self.investments.queue("Scheduled evidence and freshness review")
                    last_research = at
                if rules["enabled"] and rules["discoveryEnabled"] and at - last_discovery >= a.HOUR:
                    self.db.enqueue("discover-assets", {}, "discover-assets:" + str(at // a.HOUR))
                    last_discovery = at
            except Exception:
                try:
                    self.db.put("operation", "scheduler", {"at": at, "error": "Scheduler iteration failed; retrying"})
                except Exception:
                    pass
            self.stop_event.wait(1)

    def start(self, workers=3):
        for index in range(max(1, min(12, workers))):
            thread = threading.Thread(target=self.worker, name="crawler-worker-" + str(index), daemon=True)
            thread.start()
            self.threads.append(thread)
        scheduler = threading.Thread(target=self.scheduler, name="crawler-scheduler", daemon=True)
        scheduler.start()
        self.threads.append(scheduler)

    def close(self):
        self.stop_event.set()
        for thread in self.threads:
            thread.join(timeout=2)
