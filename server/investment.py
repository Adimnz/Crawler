"""Evidence-bound autonomous asset research. Model output cannot change qualification rules."""
from __future__ import annotations

from collections import Counter
import json
import math
import os
import statistics
from urllib.parse import urlsplit

from . import analysis as a
from .storage import now_ms, identifier, dumps
from .financial_analysis import build_financial_metrics, correlate_market_returns, event_study, evaluate_threshold_history


THEMES = (
    ("growth", "Documented Growth"), ("policy", "Political and Regulatory Exposure"),
    ("macro", "Global Economic Exposure"), ("activity", "Unusual Market Activity"),
    ("digital", "Digital Asset Intelligence"), ("research", "Research Opportunities"),
)
DEFAULT_RULES = {"enabled": True, "observationDays": 7, "marketMaxAgeHours": 24,
                 "triggerMaxAgeDays": 30, "reviewGraceDays": 7, "priceAnomalyPercent": 8,
                 "volumeMultiple": 3, "minimumHistorySamples": 20, "cycleMinutes": 5,
                 "discoveryEnabled": True}
SECTION_NAMES = ["Identity", "Market performance", "Financial health", "Growth", "Valuation",
                 "Market position", "Economic exposure", "Political exposure", "Recent developments",
                 "Positive indicators", "Negative indicators", "Research conclusion", "Monitoring criteria", "Source history"]


class InvestmentEngine:
    def __init__(self, service):
        self.s = service
        self.db = service.db

    def rules(self):
        return {**DEFAULT_RULES, **(self.db.get("setting", "investment-rules") or {})}

    def configure(self, values):
        rules = self.rules()
        bounds = {"observationDays": (1, 365), "marketMaxAgeHours": (1, 168), "triggerMaxAgeDays": (1, 365),
                  "reviewGraceDays": (1, 90), "priceAnomalyPercent": (.1, 100), "volumeMultiple": (1.1, 100),
                  "minimumHistorySamples": (10, 365), "cycleMinutes": (1, 1440)}
        for key, (low, high) in bounds.items():
            if key in values:
                value = float(values[key])
                if not math.isfinite(value) or not low <= value <= high:
                    raise ValueError(key + " is outside its supported range")
                rules[key] = value if key in {"priceAnomalyPercent", "volumeMultiple"} else int(value)
        for key in ("enabled", "discoveryEnabled"):
            if key in values:
                rules[key] = bool(values[key])
        self.db.put("setting", "investment-rules", rules)
        self.db.audit("Autonomous research rules changed", "investment-rules", rules)
        self.queue("Research rules changed")
        return rules

    def queue(self, reason, evidence_id=""):
        if self.rules()["enabled"]:
            return self.db.enqueue("research-cycle", {"reason": reason, "evidenceId": evidence_id},
                                   "research-cycle:" + str(now_ms() // 60000))

    def accept_assets(self, assets, source):
        """Only connector-produced identities, never a model or manual ticker guess."""
        for asset in assets[:100]:
            url = asset.get("identitySource", "")
            host = urlsplit(url).hostname or ""
            trusted = host in {"www.sec.gov", "data.sec.gov", "api.coingecko.com", "pro-api.coingecko.com"}
            if not trusted or not asset.get("identityVerified") or not asset.get("id"):
                continue
            existing = self.db.get("asset", asset["id"]) or {}
            item = {**existing, **asset, "triggerDocumentIds": sorted(set(existing.get("triggerDocumentIds", []) + asset.get("triggerDocumentIds", []))),
                    "sourceId": existing.get("sourceId", source["id"]), "firstSeen": existing.get("firstSeen", now_ms())}
            item["updatedAt"] = existing.get("updatedAt", now_ms()) if all(existing.get(k) == v for k, v in item.items()) else now_ms()
            self.db.put("asset", item["id"], item)

    def _observations(self, asset_id=None, at=None):
        at = at or now_ms()
        rows = self.db.latest("observation", 50000)
        # All source revisions remain independently retrievable; newest available revision wins in calculations.
        rows += self.db.latest("observationVintage", 50000)
        return [row for row in rows if (asset_id is None or row.get("assetId") == asset_id)
                and row.get("retrievedAt", 0) <= at and row.get("availableAt", row.get("observedAt", 0)) <= at
                and row.get("observedAt", 0) <= at
                and (not row.get("supersededAt") or row["supersededAt"] > at) and row.get("canonical", True)]

    def policy_record(self, values):
        document = self.db.get("document", values.get("documentId", ""))
        statuses = {"Attributed statement", "Proposal", "Passed bill", "Enacted law", "Proposed rule", "Final rule", "Government contract", "Opinion"}
        if not document or values.get("status") not in statuses or not str(values.get("jurisdiction", "")).strip():
            raise ValueError("Choose a collected document, procedural status, and jurisdiction")
        quote = str(values.get("quote", ""))
        if not quote.strip() or quote not in document["text"] or not values.get("reviewed"):
            raise ValueError("A policy record needs an exact source quote and recorded procedural review")
        from .connectors import timestamp
        event_at = timestamp(values.get("eventAt"))
        if not event_at or event_at > now_ms(): raise ValueError("Record the supported event date")
        if values["status"] in {"Enacted law", "Final rule"} and not values.get("effectiveDate"):
            raise ValueError("Record the effective date, or keep the procedural status under review")
        record = {"status": values["status"], "jurisdiction": str(values["jurisdiction"])[:200], "eventAt": event_at,
                  "effectiveDate": values.get("effectiveDate"), "remainingSteps": str(values.get("remainingSteps", ""))[:1000], "quote": quote,
                  "reviewedAt": now_ms(), "reviewer": str(values.get("reviewer", "Local analyst"))[:120]}
        # Preserve metadata as a new source version instead of rewriting historical evidence.
        source = self.db.get("source", document["sourceId"])
        raw = json.loads(self.s.objects.get(document["objectKey"]))
        updated = self.s.ingest(source, {**document, "policyRecord": record, "raw": {"original": raw, "policyReview": record}})
        self.queue("Policy procedure reviewed", document["id"])
        return updated

    def _documents(self, asset):
        explicit = set(asset.get("triggerDocumentIds", []))
        return [d for d in self.db.latest("document", 10000) if d["id"] in explicit
                or any(e["id"] == asset["id"] for e in d.get("entities", []))
                or (asset.get("cik") and str(asset["cik"]).lstrip("0") == str(d.get("companyId", "")).lstrip("0"))]

    def _anomaly(self, rows, rules):
        price_rows = [r for r in rows if r.get("metric") in {"price", "price_usd", "close", "adjusted_close"}
                      and (self.db.get("source", r.get("sourceId", "")) or {}).get("enabled")
                      and (self.db.get("source", r.get("sourceId", "")) or {}).get("tier") == "primary"]
        groups = {}
        for row in price_rows:
            key = tuple(row.get(k) for k in ("assetId", "sourceId", "metric", "unit", "currency", "adjustment", "frequency"))
            groups.setdefault(key, {})[row["observedAt"]] = row
        groups = {key: group for key, group in groups.items() if key[-1] == "daily" and len(group) >= rules["minimumHistorySamples"]}
        prices = sorted(max(groups.values(), key=lambda g: max(g), default={}).values(), key=lambda r: r["observedAt"])
        findings = []
        if len(prices) >= rules["minimumHistorySamples"]:
            previous, current = prices[-2:]
            compatible = all(current.get(k) and current.get(k) == previous.get(k) for k in ("currency", "unit", "adjustment"))
            max_gap = 28 * a.HOUR if current["assetId"].startswith("crypto:") else 102 * a.HOUR
            if compatible and current.get("frequency") == "daily" and (current.get("adjustment") != "raw" or current["assetId"].startswith("crypto:")) and previous["value"] > 0 and 20 * a.HOUR <= current["observedAt"] - previous["observedAt"] <= max_gap:
                change = (current["value"] / previous["value"] - 1) * 100
                if abs(change) >= rules["priceAnomalyPercent"]:
                    findings.append({"type": "price-anomaly", "text": "Observed price change exceeded the configured threshold.", "value": change,
                                     "unit": "%", "formula": "100 × (latest / preceding − 1)", "evidenceIds": [previous["id"], current["id"]], "at": current["observedAt"]})
        volume_groups = {}
        for row in rows:
            source = self.db.get("source", row.get("sourceId", "")) or {}
            if row.get("metric") in {"volume", "volume_usd", "volume_24h", "volume_24h_usd"} and source.get("enabled") and source.get("tier") == "primary":
                key = tuple(row.get(k) for k in ("sourceId", "metric", "unit", "currency", "frequency", "marketSession"))
                volume_groups.setdefault(key, {})[row["observedAt"]] = row
        volume_groups = {key: group for key, group in volume_groups.items() if key[-2] == "daily" and len(group) > rules["minimumHistorySamples"]}
        volumes = sorted(max(volume_groups.values(), key=lambda g: max(g), default={}).values(), key=lambda r: r["observedAt"])
        if len(volumes) > rules["minimumHistorySamples"]:
            baseline, current = volumes[-rules["minimumHistorySamples"]-1:-1], volumes[-1]
            if current.get("unit") and current.get("currency") and current.get("frequency") == "daily" and all(r.get("unit") == current.get("unit") and r.get("metric") == current.get("metric") and r["value"] >= 0 for r in baseline):
                median = statistics.median(r["value"] for r in baseline)
                if median > 0 and current["value"] / median >= rules["volumeMultiple"]:
                    findings.append({"type": "volume-anomaly", "text": "Observed volume exceeded the configured multiple of the prior sample median.", "value": current["value"] / median,
                                     "unit": "×", "formula": "latest volume / median(prior samples)", "evidenceIds": [r["id"] for r in baseline] + [current["id"]], "at": current["observedAt"]})
        return findings

    def _profile(self, asset, at):
        rules = self.rules()
        old = self.db.get("assetProfile", asset["id"])
        docs = self._documents(asset)
        doc_ids = {d["id"] for d in docs}
        observations = self._observations(asset["id"], at)
        calculations = build_financial_metrics(observations, at=at)
        metrics = calculations.get("metrics", [])
        claims = [c for c in self.db.latest("claim", 20000) if c.get("documentId") in doc_ids]
        reviewed = [c for c in claims if c.get("status") in {"Verified", "Corroborated"} and not c.get("reviewRequired")]
        conflicts = [c for c in claims if c.get("status") in {"Disputed", "Contradicted", "Retracted", "Misleading"} or c.get("reviewRequired") and c.get("history")]
        relationships = [r for r in self.db.latest("relationship", 10000) if r.get("confirmed") and asset["id"] in {r["from"], r["to"]}
                         and r.get("validFrom", 0) <= at and (not r.get("validTo") or r["validTo"] >= at)
                         and r.get("evidence") and all(self.db.get("document", doc_id) and r.get("evidenceVersions", {}).get(doc_id) == self.db.get("document", doc_id)["version"] for doc_id in r["evidence"])]
        prices = [r for r in observations if r.get("metric") in {"price", "price_usd", "close", "adjusted_close"} and (self.db.get("source", r["sourceId"]) or {}).get("enabled")
                  and (self.db.get("source", r["sourceId"]) or {}).get("tier") == "primary"]
        latest = max(prices, key=lambda r: r["observedAt"], default=None)
        market_ok = bool(latest and latest["value"] > 0 and 0 <= at - latest["observedAt"] <= rules["marketMaxAgeHours"] * a.HOUR)
        anomalies = [finding for finding in self._anomaly(observations, rules) if at - rules["triggerMaxAgeDays"] * a.DAY <= finding["at"] <= at]
        triggers = [{"type": "reviewed-development", "text": c["text"], "evidenceIds": [c["documentId"]] + [e["documentId"] for e in c.get("evidence", [])], "at": c.get("updatedAt", 0)} for c in reviewed]
        triggers += [{"type": "filing", "text": "New company filing recorded by SEC EDGAR.", "evidenceIds": [d["id"]], "at": d["publishedAt"]} for d in docs if d.get("filingType") and urlsplit(d["url"]).hostname in {"www.sec.gov", "data.sec.gov"}]
        triggers += anomalies
        triggers = [t for t in triggers if at - rules["triggerMaxAgeDays"] * a.DAY <= t["at"] <= at]
        first_observed = min([r["observedAt"] for r in prices] or [at])
        observed_days = (at - max(asset["firstSeen"], first_observed)) / a.DAY
        gaps = []
        if not asset.get("identityVerified"): gaps.append("Instrument identity is unverified")
        if not market_ok: gaps.append("Reliable current market price: Data unavailable or stale")
        if not triggers: gaps.append("Independent research trigger: Data unavailable")
        if observed_days < rules["observationDays"]: gaps.append("Observation period incomplete: %.1f of %s days" % (max(0, observed_days), rules["observationDays"]))
        if conflicts: gaps.append("Contradictory, revised, or retracted evidence requires review")
        missing = calculations.get("missingData", [])
        risk_inventory = gaps + ["Missing or incompatible measurements are excluded from calculations.", "Reported source statements may require independent verification."]
        qualified = not gaps
        prior_state = old.get("status") if old else None
        review_since = old.get("reviewSince") if old and prior_state in {"Review required", "Removed"} else at
        if qualified:
            status = "Continued monitoring" if prior_state in {"Qualified for monitoring", "Continued monitoring"} else "Qualified for monitoring"
        elif prior_state in {"Qualified for monitoring", "Continued monitoring", "Review required", "Removed"}:
            status = "Removed" if prior_state == "Removed" or at - review_since >= rules["reviewGraceDays"] * a.DAY else "Review required"
        else: status = "Under investigation"
        growth = [m for m in metrics if "growth" in m.get("metric", "") and not m.get("stale")]
        positive = [m for m in growth if m["value"] > 0]
        negative = [m for m in growth if m["value"] < 0]
        policy = [r for r in relationships if r["type"] in {"political-exposure", "regulatory-exposure", "government-contract"}
                  and any(self.db.get("document", eid).get("policyRecord") for eid in r["evidence"])]
        macro = [r for r in relationships if r["type"] in {"economic-exposure", "currency-exposure", "rate-exposure"}]
        themes = ["research"]
        if positive: themes.append("growth")
        if policy: themes.append("policy")
        if macro: themes.append("macro")
        if anomalies: themes.append("activity")
        if asset.get("assetClass") == "crypto": themes.append("digital")
        evidence = [{"id": d["id"], "title": d["title"], "url": d["url"], "source": d["source"], "publishedAt": d["publishedAt"], "retrievedAt": d["retrievedAt"], "version": d["version"]} for d in docs]
        monitor = [{"condition": "Current price age exceeds %sh" % rules["marketMaxAgeHours"], "action": "Review required"},
                   {"condition": "No valid trigger within %s days" % rules["triggerMaxAgeDays"], "action": "Review required"},
                   {"condition": "New filing, source correction, contradictory review, or changed financial period", "action": "Recalculate and retain a new revision"},
                   {"condition": "Qualification gates remain unmet for %s days" % rules["reviewGraceDays"], "action": "Remove from monitoring"}]
        sections = {name: {"status": "Data unavailable", "items": []} for name in SECTION_NAMES}
        def section(name, items):
            sections[name] = {"status": "Available" if items else "Data unavailable", "items": items}
        section("Identity", [asset])
        section("Market performance", ([latest] if latest else []) + [m for m in metrics if any(t in m.get("metric", "") for t in ("return", "volatility", "price"))])
        section("Financial health", sorted([r for r in observations if r.get("periodEnd")], key=lambda r: str(r["periodEnd"]), reverse=True)[:60])
        section("Growth", growth)
        section("Valuation", [m for m in metrics if any(t in m.get("metric", "") for t in ("valuation", "price_earnings", "price_to", "pe_ratio"))])
        section("Market position", [r for r in relationships if r["type"] in {"competitor", "product", "geographic-exposure", "ownership", "supplier", "customer"}])
        section("Economic exposure", macro)
        section("Political exposure", policy)
        section("Recent developments", evidence[:20])
        section("Positive indicators", positive)
        section("Negative indicators", negative + [{"text": c["text"], "status": c["status"], "evidenceIds": [c["documentId"]]} for c in conflicts])
        section("Research conclusion", [{"text": "Meets the configured monitoring gates." if qualified else "Monitoring qualification withheld. " + "; ".join(gaps), "evidenceIds": sorted({eid for t in triggers for eid in t["evidenceIds"]})}])
        section("Monitoring criteria", monitor)
        section("Source history", evidence)
        result = {"id": asset["id"], "asset": asset, "status": status, "assessedAt": at, "reviewSince": review_since if not qualified else None,
                  "metrics": metrics, "calculations": calculations, "sections": sections, "triggers": triggers, "risks": risk_inventory,
                  "missingData": missing, "qualificationGaps": gaps, "qualified": qualified, "themes": themes, "observedDays": max(0, observed_days),
                  "marketFresh": market_ok, "sourceHistory": evidence, "sourceFingerprint": a.digest(dumps({"asset": {k:v for k,v in asset.items() if k not in {"updatedAt", "identityCheckedAt"}}, "documents": [(d["id"], d["version"]) for d in docs], "observations": sorted((r["id"], r["value"], r.get("availableAt", 0)) for r in observations), "claims": [(c["id"], c.get("updatedAt"), c["status"]) for c in claims], "relationships": relationships, "rules": rules})),
                  "monitoringCriteria": monitor, "anomalies": anomalies,
                  "thresholdHistory": evaluate_threshold_history(observations, rules["priceAnomalyPercent"], at=at, min_samples=rules["minimumHistorySamples"])}
        availability = lambda p: dumps({"themes": p.get("themes"), "qualified": p.get("qualified"), "triggerIds": [t["evidenceIds"] for t in p.get("triggers", [])], "staleMetrics": [(m["metric"], m.get("stale")) for m in p.get("metrics", [])]})
        material = not old or old.get("sourceFingerprint") != result["sourceFingerprint"] or old.get("status") != status or old.get("marketFresh") != market_ok or availability(old) != availability(result)
        if not material:
            return old
        result["version"] = (old or {}).get("version", 0) + 1
        changed = []
        if not old: changed.append("Initial profile created from available source records.")
        else:
            if old["status"] != status: changed.append("Research status changed from " + old["status"] + " to " + status + ".")
            metric_key = lambda m: (m["metric"], dumps(m.get("period", {})), m.get("assetId"))
            old_values = {metric_key(m): m["value"] for m in old.get("metrics", [])}
            display = lambda value: format(value, ".6g") if isinstance(value, (int, float)) else str(value)
            for m in metrics:
                if old_values.get(metric_key(m)) != m["value"]: changed.append(m["metric"] + ": " + display(old_values.get(metric_key(m), "Data unavailable")) + " → " + display(m["value"]) + " " + m.get("unit", ""))
            if old.get("sourceFingerprint") != result["sourceFingerprint"]: changed.append("Underlying evidence, source revisions, relationships, or monitoring rules changed; gates recalculated.")
            if old.get("marketFresh") != market_ok: changed.append("Underlying market observation freshness changed.")
        result["whatChanged"] = changed
        revision_id = asset["id"] + ":v" + str(result["version"])
        self.db.put("profileRevision", revision_id, {**result, "revisionId": revision_id})
        self.db.put("assetProfile", asset["id"], result)
        self.db.audit("Asset research revised", asset["id"], {"version": result["version"], "status": status, "whatChanged": changed})
        return result

    def _portfolios(self, profiles, at):
        result = []
        for theme_id, name in THEMES:
            entries = []
            for p in profiles:
                entry_id = theme_id + "|" + p["id"]
                existing = self.db.get("portfolioEntry", entry_id)
                relevant = theme_id in p["themes"]
                if not relevant and not existing: continue
                entry = {"id": entry_id, "assetId": p["id"], "themeId": theme_id, "status": p["status"] if relevant else "Removed",
                         "profileVersion": p["version"], "reason": p["sections"]["Research conclusion"]["items"][0]["text"] if relevant else "Evidence no longer meets this theme's criteria.",
                         "triggerEvidence": sorted({eid for t in p["triggers"] for eid in t["evidenceIds"]}), "risks": p["risks"], "monitoringCriteria": p["monitoringCriteria"],
                         "firstSeen": (existing or {}).get("firstSeen", at), "updatedAt": at}
                if not existing or any(existing.get(k) != entry[k] for k in ("status", "profileVersion", "reason")):
                    self.db.put("portfolioRevision", identifier("portfolio-revision"), entry)
                self.db.put("portfolioEntry", entry_id, entry)
                entries.append(entry)
            active = [e for e in entries if e["status"] in {"Qualified for monitoring", "Continued monitoring"}]
            assets = [p["asset"] for p in profiles if any(e["assetId"] == p["id"] for e in active)]
            sector = Counter(asset.get("sector") or "Data unavailable" for asset in assets)
            geography = Counter(asset.get("country") or "Data unavailable" for asset in assets)
            shared_exposures = Counter()
            for p in profiles:
                if not any(e["assetId"] == p["id"] for e in active): continue
                for exposure in {r["type"] + ": " + (r["to"] if r["from"] == p["id"] else r["from"]) for name in ("Economic exposure", "Political exposure", "Market position") for r in p["sections"][name]["items"]}:
                    shared_exposures[exposure] += 1
            correlations = []
            for i, left in enumerate(assets[:12]):
                for right in assets[i+1:12]:
                    comparison = correlate_market_returns(self._observations(left["id"], at), self._observations(right["id"], at), at=at)
                    correlations.append({"left": left["id"], "right": right["id"], "result": comparison})
            result.append({"id": theme_id, "name": name, "entries": entries, "qualifiedCount": len(active), "sectorCounts": dict(sector), "geographyCounts": dict(geography),
                           "correlations": correlations, "sharedExposures": dict(shared_exposures), "sharedRisks": ["Sector and geography counts reflect verified provider classifications; unknown classifications are shown explicitly.", "Pairwise return correlations describe the stated sample and do not establish causation."], "purpose": "Research watch portfolio; no holdings, allocation weights, targets, or expected returns."})
        return result

    def cycle(self, reason="Scheduled evidence and freshness review"):
        if not self.rules()["enabled"]: return self.overview()
        with self.s.lock:
            at = now_ms()
            profiles = [self._profile(asset, at) for asset in self.db.latest("asset", 500)]
            portfolios = self._portfolios(profiles, at)
            self.db.put("investmentState", "current", {"lastRunAt": at, "reason": reason, "portfolios": portfolios})
            self.cross_reports(profiles, at)
            self.db.put("operation", "autonomous-research", {"lastRunAt": at, "reason": reason, "profiles": len(profiles), "status": "Completed",
                         "stages": ["Observe", "Detect", "Investigate", "Correlate", "Evaluate", "Profile", "Curate", "Monitor"]})
        # Paid coordination runs only with the existing explicit server opt-in.
        if self.s.auto_ai and self.s.ai.ready:
            for profile in profiles[:6]:
                key = profile["id"] + ":" + str(profile["version"])
                if not self.db.get("coordinatorRun", key):
                    self.db.enqueue("coordinate-research", {"assetId": profile["id"], "version": profile["version"]}, "coordinate:" + key)
        return self.overview()

    def cross_reports(self, profiles, at):
        for event in self.db.latest("event", 40):
            if event.get("mergedInto"): continue
            docs = [d for d in self.db.latest("document", 3000) if d["eventId"] == event["id"]]
            if not docs: continue
            linked = [p for p in profiles if any(d["id"] in {e["id"] for e in p["sourceHistory"]} for d in docs)]
            signature = a.digest(dumps({"docs": [(d["id"], d["version"]) for d in docs], "profiles": [(p["id"], p["version"]) for p in linked]}))
            old = self.db.get("crossMarketReport", event["id"])
            if old and old["signature"] == signature: continue
            record = {"id": event["id"], "title": event["title"], "createdAt": at, "version": (old or {}).get("version", 0) + 1, "signature": signature,
                      "whatHappened": [{"text": d["text"][:500], "attribution": d["source"], "documentId": d["id"], "url": d["url"], "publishedAt": d["publishedAt"], "status": "Attributed source extract"} for d in docs[:8]],
                      "financialObservations": [{"assetId": p["id"], "metrics": p["metrics"]} for p in linked],
                      "documentedExposure": [r for p in linked for name in ("Market position", "Economic exposure", "Political exposure") for r in p["sections"][name]["items"]],
                      "mentionedAssets": [p["id"] for p in linked], "monitoringCandidates": [p["id"] for p in linked if p["qualified"]],
                      "uncertainties": ["Text mentions alone do not establish financial exposure or causation."] + [gap for p in linked for gap in p["qualificationGaps"]],
                      "nextVerificationTriggers": [c for p in linked for c in p["monitoringCriteria"]],
                      "whatChanged": ["Initial report from the checked source set." if not old else "Collected sources, revisions, or linked asset assessments changed."]}
            self.db.put("crossMarketReport", event["id"], record)
            self.db.put("crossMarketRevision", event["id"] + ":v" + str(record["version"]), record)
            if linked:
                self.db.enqueue("investigate", {"eventId": event["id"]}, "autonomous-investigation:" + event["id"] + ":" + signature)

    def overview(self):
        state = self.db.get("investmentState", "current") or {}
        profiles = self.db.latest("assetProfile", 500)
        return {"rules": self.rules(), "lastRunAt": state.get("lastRunAt"), "operation": self.db.get("operation", "autonomous-research"),
                "profiles": [{k: p[k] for k in ("id", "asset", "status", "version", "assessedAt", "marketFresh", "qualified", "themes", "qualificationGaps", "whatChanged")} for p in profiles],
                "portfolios": state.get("portfolios", [{"id": key, "name": name, "entries": [], "qualifiedCount": 0} for key, name in THEMES]),
                "reports": self.db.latest("crossMarketReport", 20), "discovery": self.db.get("operation", "asset-discovery"),
                "limitations": ["Automatic identity discovery needs SEC_USER_AGENT or COINGECKO_API_KEY and an enabled provider.", "Only independently enforced gates admit an asset to monitoring.", "No new verified evidence found refers only to sources checked."]}

    def profile(self, asset_id, as_of=None):
        versions = [p for p in self.db.latest("profileRevision", 10000) if p["id"] == asset_id and (not as_of or p["assessedAt"] <= as_of)]
        versions.sort(key=lambda p: p["version"], reverse=True)
        if not versions: raise ValueError("Asset profile not found at the requested date")
        return {"profile": versions[0], "revisions": [{"version": p["version"], "assessedAt": p["assessedAt"], "status": p["status"], "whatChanged": p["whatChanged"]} for p in versions]}

    def study(self, asset_id, benchmark_id, document_id):
        document = self.db.get("document", document_id)
        if not document or document.get("publishedEstimated"):
            raise ValueError("Choose a collected document with a supported publication timestamp")
        event_at = document.get("eventAt") or document.get("policyRecord", {}).get("eventAt") or document["publishedAt"]
        result = event_study(self._observations(asset_id), self._observations(benchmark_id), event_at)
        result["eventReference"] = {"documentId": document_id, "sourceVersion": document["version"], "url": document["url"],
                                    "timestampBasis": "Recorded event date" if document.get("eventAt") or document.get("policyRecord") else "Source publication timestamp"}
        return result

    def report(self, event_id, as_of=None):
        versions = [r for r in self.db.latest("crossMarketRevision", 10000) if r["id"] == event_id and (not as_of or r["createdAt"] <= as_of)]
        versions.sort(key=lambda r: r["version"], reverse=True)
        if not versions: raise ValueError("Cross-market report not found at the requested date")
        return {"report": versions[0], "revisions": [{"version": r["version"], "createdAt": r["createdAt"], "whatChanged": r["whatChanged"]} for r in versions]}

    def discover(self):
        from .financial_connectors import discover_instruments
        if not self.rules()["discoveryEnabled"]: return
        providers = [s for s in self.db.list("source") if s.get("enabled") and s["kind"] in {"sec", "coingecko_asset", "coingecko"} and not s["id"].startswith("auto-provider-")]
        if not providers:
            self.db.put("operation", "asset-discovery", {"checkedAt": now_ms(), "status": "Enable an SEC or CoinGecko connector for automatic identity discovery.", "discovered": 0})
            return
        docs = self.db.latest("document", 100)
        assets = discover_instruments(docs, self.s.network, limit=6, providers={"sec" if p["kind"] == "sec" else "coingecko" for p in providers})
        for asset in assets:
            kind = "sec" if asset.get("cik") else "coingecko_asset"
            provider = next((p for p in providers if p["kind"] == kind or kind == "coingecko_asset" and p["kind"] == "coingecko"), None)
            if not provider: continue
            self.accept_assets([asset], provider)
            config = {"cik": asset["cik"], "ticker": asset["ticker"], "exchange": asset.get("exchange")} if kind == "sec" else {"id": asset.get("providerId")}
            source_id = "auto-provider-" + a.digest(asset["id"])[:20]
            if not self.db.get("source", source_id):
                source = self.s.add_source({"id": source_id, "kind": kind, "name": "Research data · " + asset["name"], "url": "https://data.sec.gov/api/xbrl/companyfacts/CIK" + str(asset["cik"]).zfill(10) + ".json" if kind == "sec" else "https://api.coingecko.com/api/v3/coins/" + asset["providerId"], "config": config, "enabled": True, "tier": "primary", "family": provider.get("family", provider["name"]), "permissions": provider.get("permissions", "Configured provider research access"), "interval": 86400000 if kind == "sec" else 3600000})
                self.db.enqueue("poll", {"sourceId": source["id"]}, "discover-poll:" + source["id"])
        self.db.put("operation", "asset-discovery", {"checkedAt": now_ms(), "status": "Checked configured official identity providers", "discovered": len(assets), "checkedDocumentIds": [d["id"] for d in docs]})
        self.queue("Identity discovery completed")

    def tool(self, name, args):
        """Read-only coordinator tools return local canonical evidence, never generated facts."""
        documents = self.db.latest("document", 10000)
        evidence = []
        result = {}
        if name == "search_news":
            terms = a.tokens(args.get("query", ""))
            evidence = [{**d, "text": d["text"][:2500]} for d in documents if all(t in (d["title"] + " " + d["text"]).lower() for t in terms) and (not args.get("region") or args["region"].lower() in dumps(d.get("regions", [])).lower())][:20]
        elif name == "retrieve_source_document":
            doc = self.db.get("document", args["source_id"])
            evidence = [doc] if doc else []
        elif name == "get_company_filings":
            evidence = [d for d in documents if d.get("companyId") == args["company_id"] and (not args.get("filing_type") or d.get("filingType") == args["filing_type"])][:30]
        elif name == "get_policy_records":
            evidence = [d for d in documents if d.get("policyRecord", {}).get("jurisdiction", "").lower() == args.get("jurisdiction", "").lower() and args.get("topic", "").lower() in d["text"].lower()][:30]
        elif name in {"get_market_history", "get_financial_statements", "get_economic_series", "get_crypto_metrics"}:
            asset_id = args.get("instrument_id") or args.get("company_id") or args.get("series_id") or args.get("asset_id")
            if name == "get_economic_series" and ":" not in asset_id:
                asset_id = "economic:fred:" + asset_id
            rows = sorted(self._observations(asset_id), key=lambda r: (r["observedAt"], r["retrievedAt"]))
            if name == "get_market_history": rows = [r for r in rows if r.get("metric", "").startswith(("price", "volume")) or r.get("metric") in {"close", "adjusted_close"}]
            if name == "get_financial_statements":
                rows = [r for r in rows if r.get("periodEnd")]
                period_key = lambda row: (str(row.get("periodEnd", "")), str(row.get("periodStart", "")), str(row.get("periodType", "")))
                periods = sorted({period_key(r) for r in rows}, reverse=True)[:max(1, min(100, int(args.get("periods", 12))))]
                rows = [r for r in rows if period_key(r) in periods]
            if args.get("vintage"): rows = [r for r in rows if r.get("vintageDate") == args["vintage"]]
            if args.get("network"): rows = [r for r in rows if r.get("chain") == args["network"]]
            for row in rows[-200:]: evidence.append({**row, "text": "Recorded observation: " + dumps(row)})
        elif name == "find_related_entities": result = self.s.graph(args["event_id"])
        elif name in {"get_existing_research", "compare_research_versions"}:
            existing = self.profile(args.get("instrument_id") or args.get("profile_id"))
            result = {"profile": {key: existing["profile"][key] for key in ("id", "asset", "status", "version", "assessedAt", "whatChanged", "qualificationGaps", "monitoringCriteria")}, "revisions": existing["revisions"][:30]}
            result["evidenceWarning"] = "Existing research is derived context, not source evidence."
        elif name == "calculate_financial_metrics":
            rows = [r for r in self._observations() if r["id"] in args["dataset_ids"]]
            calculated = build_financial_metrics(rows)
            brief_metric = lambda m: {key: m[key] for key in ("metric", "assetId", "value", "unit", "formula", "inputIds", "period", "stale") if key in m}
            result = {"metrics": [brief_metric(m) for m in calculated["metrics"]], "missingData": calculated["missingData"]}
            evidence = [{"id": "calculation-" + a.digest(dumps(m))[:24], "text": "Deterministic calculation: " + dumps(brief_metric(m)), "inputIds": m.get("inputIds", []), "retrievedAt": now_ms()} for m in calculated.get("metrics", [])]
        elif name == "validate_evidence_claim":
            claim = self.db.get("claim", args["claim_id"])
            valid = bool(args["evidence_ids"] and claim and not claim.get("reviewRequired") and claim.get("status") in {"Verified", "Corroborated"} and set(args["evidence_ids"]).issubset({e["documentId"] for e in claim.get("evidence", [])}))
            result = {"valid": valid, "claim": claim, "method": "Recorded analyst review and evidence linkage; no automatic truth verdict."}
        else: raise ValueError("Unknown read-only research tool")
        date_range = args.get("date_range", "")
        if date_range:
            try:
                start, end = date_range.split("/")
                from .connectors import timestamp
                lo, hi = timestamp(start), timestamp(end)
                if lo is None or hi is None: raise ValueError()
                evidence = [r for r in evidence if lo <= r.get("observedAt", r.get("publishedAt", 0)) <= hi]
            except ValueError: return {"error": "date_range must use ISO start/end", "evidence": []}
        checked = len(evidence)
        fields = {"id", "title", "text", "sourceId", "source", "url", "publishedAt", "retrievedAt", "observedAt", "version", "unit", "currency", "formula", "inputIds", "metric", "value", "periodStart", "periodEnd", "periodType", "availableAt", "vintageDate"}
        bounded, budget = [], len(dumps(result))
        for record in evidence:
            item = {key: value for key, value in record.items() if key in fields}
            size = len(dumps(item))
            if len(bounded) >= 120 or budget + size > 90000: break
            bounded.append(item)
            budget += size
        return {"result": result, "evidence": bounded, "checkedRecords": checked, "truncated": len(bounded) < checked, "scope": "Locally retrieved authorized records only; bounded tool response"}

    def coordinate(self, asset_id, version):
        if not self.s.auto_ai or not self.s.ai.ready: return
        profile = self.profile(asset_id)["profile"]
        if profile["version"] != version: return
        snapshots = {}
        def snapshot_record(record_id):
            for kind in ("document", "observation", "observationVintage"):
                record = self.db.get(kind, record_id)
                if record:
                    snapshots[(kind, record_id)] = a.digest(dumps(record))
                    break
        # Bind all numeric inputs before the call, even when a model skips a data tool.
        for row in self._observations(asset_id): snapshot_record(row["id"])
        def execute_tool(name, arguments):
            response = self.tool(name, arguments)
            for record in response.get("evidence", []):
                snapshot_record(record["id"])
                for record_id in record.get("inputIds", []): snapshot_record(record_id)
            return response
        result = self.s.ai.coordinate({"instrumentId": asset_id, "profileVersion": version, "question": "Investigate changes, contradictions, financial measurements, documented exposures, and missing evidence. Research eligibility is decided by application gates.", "evidenceIds": [d["id"] for d in profile["sourceHistory"]]}, execute_tool)
        # Assessments are append-only and separate from facts and qualification state.
        with self.s.lock:
            current = self.profile(asset_id)["profile"]
            changed = current["version"] != version or any(not self.db.get("document", d["id"]) or self.db.get("document", d["id"])["version"] != d["version"] for d in profile["sourceHistory"])
            if any(a.digest(dumps(self.db.get(kind, record_id))) != digest for (kind, record_id), digest in snapshots.items()):
                changed = True
            for fact in result.get("facts", []):
                for reference in fact.get("evidence", []):
                    record = self.db.get("document", reference.get("id", "")) or self.db.get("observation", reference.get("id", ""))
                    if record and (reference.get("version") is not None and reference["version"] != record.get("version") or reference.get("retrievedAt") is not None and reference["retrievedAt"] != record.get("retrievedAt")):
                        changed = True
            if changed:
                self.db.audit("Stale AI assessment withheld", asset_id, {"profileVersion": version})
                return
            self.db.put("coordinatorRun", asset_id + ":" + str(version), {"assetId": asset_id, "profileVersion": version, "createdAt": now_ms(), "assessment": result})
