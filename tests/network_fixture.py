"""Synthetic board, Auth and OpenAI contracts. All requests stay in process."""
from pathlib import Path
import base64
import json
import os
import sys
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.connectors import ConnectorError
from server.http import AppServer
from server.service import ResearchService
from server.storage import now_ms
from test_accounts import AuthProvider, token
from test_network import GraphAI


class Network:
    def __init__(self):
        self.providers = {}
    def allowed(self, *_args): return False
    def fetch(self, url, headers=None, method="GET", body=None, **kwargs):
        if "supabase.co/" not in url: raise ConnectorError("External requests disabled")
        content = json.loads(body) if body else {}
        name = content.get("email", "alice@example.test").split("@")[0]
        authorization = (headers or {}).get("Authorization", "")
        if authorization:
            try: name = json.loads(base64.urlsafe_b64decode(authorization.split(".")[1] + "==="))["sub"]
            except Exception: raise ConnectorError("Invalid synthetic token", status=401)
        if name not in {"alice", "bob"}: raise ConnectorError("Invalid synthetic account", status=401)
        if name not in self.providers:
            provider = AuthProvider()
            provider.user.update(id="fixture-" + name, email=name + "@example.test", user_metadata={"display_name": name.title()})
            self.providers[name] = provider
        provider = self.providers[name]
        forwarded = dict(headers or {})
        if authorization: forwarded["Authorization"] = "Bearer " + token("aal2" if provider.verified else "aal1")
        data, response_headers, resolved = provider.fetch(url, forwarded, method, body, **kwargs)
        result = json.loads(data)
        if result.get("access_token"): result["access_token"] = token("aal2" if provider.verified and "grant_type=password" not in url else "aal1", name)
        return json.dumps(result).encode(), response_headers, resolved


class ResearchAI(GraphAI):
    key = "fixture-only-never-real"
    def plan_topic(self, _query): return {"title": "Drones", "searchTerms": ["drone", "Orion Airworks"], "questions": [], "assetTypes": [], "regions": []}
    def discover_topic(self, *_args): return {"sources": []}
    def structured(self, name, schema, instructions, data):
        if name == "investigative_network": return super().structured(name, schema, instructions, data)
        if name == "market_topic_research":
            cite = self.result["entities"][0]["evidence"]
            return {"summary": [{"text": cite[0]["quote"], "evidence": cite}], "drivers": [], "risks": [], "subjects": [
                {"name": "Orion Airworks", "kind": "company", "connection": "Synthetic source disclosure", "watchFor": "Original corporate records", "evidence": cite}], "nextQuestions": []}
        raise ValueError("Unsupported synthetic model request")


def populate(service):
    source = service.add_source({"id": "fixture-wire", "name": "Fixture Wire", "kind": "rss", "url": "https://fixture.example/feed", "enabled": True})
    quote = "Orion Airworks manufactures the Kite drone. Morgan Vale owns Orion Airworks and Orion Sensors."
    doc = service.ingest(source, {"title": "Synthetic drone disclosure", "text": quote,
        "url": "https://fixture.example/disclosure", "publishedAt": now_ms()-10000, "authors": ["Mira Lee"]})
    other_source = service.add_source({"id": "fixture-registry", "name": "Fixture Registry", "kind": "rss", "url": "https://registry.example/feed", "enabled": False, "tier": "primary"})
    finance = service.ingest(other_source, {"title": "Orion Airworks drone business record", "text": "Orion Airworks reports revenue of UAH 100 million for FY2025. Orion Airworks is a private company.",
        "url": "https://registry.example/orion", "publishedAt": now_ms()-20000})
    cite = {"documentId": doc["id"], "version": doc["version"], "quote": quote}
    fcite = {"documentId": finance["id"], "version": finance["version"], "quote": finance["text"]}
    result = {"entities": [{"ref": ref, "name": name, "type": kind, "evidence": [cite], "attributes": [
        {"field": "Reported revenue and period", "value": "UAH 100 million for FY2025", "evidence": [fcite]}] if ref == "company" else []}
        for ref, name, kind in (("company", "Orion Airworks", "company"), ("owner", "Morgan Vale", "person"), ("other", "Orion Sensors", "company"), ("product", "Kite", "product"))],
        "relationships": [{"from": "company", "to": "owner", "type": "owned_by", "claim": quote, "evidence": [cite]},
                          {"from": "product", "to": "company", "type": "manufactured_by", "claim": quote, "evidence": [cite]}],
        "questions": [{"entityRef": "company", "question": "Which public supplier agreements have been disclosed?"}]}
    service.ai = ResearchAI(result)
    service.auto_ai = False
    topic = service.topics.create({"query": "Drones"})
    service.topics.run(topic["id"])
    service.network_research.build(topic["id"], True)
    service.accounts.url = "https://fixtureproject.supabase.co"
    service.accounts.key = "fixture-publishable-key"
    return {"topicId": topic["id"], "documentId": doc["id"]}


def main():
    for key in ("OPENAI_API_KEY", "OPENAI_MODEL", "CRAWLER_AUTO_AI", "S3_BUCKET", "DATABASE_URL", "SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY", "SUPABASE_SERVICE_ROLE_KEY"):
        os.environ.pop(key, None)
    with tempfile.TemporaryDirectory(prefix="crawler-network-browser-") as directory:
        service = ResearchService(directory, network=Network(), seed=False, dsn="")
        server = None
        try:
            fixture = populate(service)
            worker = threading.Thread(target=service.worker, daemon=True)
            service.threads.append(worker)
            worker.start()
            server = AppServer(("127.0.0.1", 0), service, Path(__file__).resolve().parents[1], auth_token="")
            def shutdown():
                sys.stdin.readline()
                server.shutdown()
            threading.Thread(target=shutdown, daemon=True).start()
            print(json.dumps({"port": server.server_port, **fixture}), flush=True)
            server.serve_forever(poll_interval=.05)
        finally:
            if server: server.server_close()
            service.close()


if __name__ == "__main__": main()
