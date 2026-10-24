"""Same-origin local web app and JSON API, with optional owner authentication."""
from __future__ import annotations

import base64
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import ipaddress
import json
import sys
import mimetypes
import os
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import urlsplit, parse_qs, unquote

from . import analysis
from .connectors import ConnectorError
from .storage import now_ms
from .research_network import BoardConflict


class AppServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 32

    def handle_error(self, request, client_address):
        # Browsers abort sockets when pages navigate or requests are cancelled; that is not a server fault.
        if isinstance(sys.exc_info()[1], (ConnectionError, TimeoutError)):
            return
        super().handle_error(request, client_address)

    def process_request(self, request, client_address):
        # ThreadingHTTPServer otherwise creates an unbounded thread per connection.
        recovery = False
        pool = self.http_slots
        if not pool.acquire(blocking=False):
            pool = self.recovery_slots
            recovery = True
        else:
            pool = None
        if pool is not None and not pool.acquire(blocking=False):
            try:
                request.settimeout(0.5)
                payload = b'{"error":"Research server is busy. Retry shortly.","code":"SERVER_BUSY","retryAfterMs":3000}'
                response = (b"HTTP/1.1 503 Service Unavailable\r\n"
                            b"Content-Type: application/json\r\n"
                            b"Cache-Control: no-store\r\n"
                            b"Retry-After: 3\r\n"
                            b"Connection: close\r\n"
                            + b"Content-Length: " + str(len(payload)).encode() + b"\r\n\r\n" + payload)
                request.sendall(response)
            except OSError:
                pass
            finally:
                self.shutdown_request(request)
            return
        with self.http_lane_lock:
            self.http_lanes[request] = (self.recovery_slots if recovery else self.http_slots, recovery)
        request.settimeout(10)
        try:
            super().process_request(request, client_address)
        except BaseException:
            with self.http_lane_lock: lane = self.http_lanes.pop(request)
            lane[0].release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            with self.http_lane_lock: lane = self.http_lanes.pop(request, None)
            if lane: lane[0].release()

    def finish_request(self, request, client_address):
        with self.http_lane_lock: recovery = self.http_lanes[request][1]
        (RecoveryHandler if recovery else Handler)(request, client_address, self)

    def http_load(self):
        with self.http_lane_lock:
            return {"active": len(self.http_lanes), "normalLimit": self.http_limit, "recoveryLimit": 2}

    def __init__(self, address, service, root, auth_token=None):
        self.service = service
        self.root = Path(root).resolve()
        self.auth_token = auth_token if auth_token is not None else os.getenv("CRAWLER_AUTH_TOKEN", "")
        bind_host = address[0]
        if bind_host not in {"127.0.0.1", "localhost", "::1"} and not self.auth_token:
            raise ValueError("A non-loopback server requires CRAWLER_AUTH_TOKEN")
        self.allowed_hosts = {"127.0.0.1", "localhost", "::1", bind_host, *filter(None, os.getenv("CRAWLER_ALLOWED_HOSTS", "").split(","))}
        self.sessions, self.session_lock = {}, threading.Lock()
        self.stopping = threading.Event()
        self.http_limit = max(2, min(32, int(os.getenv("CRAWLER_HTTP_CONNECTIONS", "8"))))
        self.http_slots = threading.BoundedSemaphore(self.http_limit)
        self.recovery_slots = threading.BoundedSemaphore(2)
        self.http_lanes, self.http_lane_lock = {}, threading.Lock()
        super().__init__(address, Handler)

    def initiate_shutdown(self):
        """Request shutdown without blocking the HTTP handler or signal handler."""
        if self.stopping.is_set():
            return False
        self.stopping.set()
        self.service.stop_event.set()
        threading.Thread(target=self.shutdown, name="crawler-http-shutdown", daemon=True).start()
        return True


class Handler(BaseHTTPRequestHandler):
    server_version = "TrendCrawler/2"

    def log_message(self, fmt, *args):
        # Request bodies, credentials, provider URLs and query strings are never logged.
        pass

    def json(self, value, status=200, cookie=None):
        data = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        if cookie:
            for item in cookie if isinstance(cookie, list) else [cookie]: self.send_header("Set-Cookie", item)
        self.end_headers()
        self.wfile.write(data)

    def session(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except Exception:
            pass
        session_id = cookie.get("crawler_session")
        session_id = session_id.value if session_id else None
        with self.server.session_lock:
            existing = self.server.sessions.get(session_id)
            if existing and existing["expires"] > time.time():
                return session_id, existing, None
            if len(self.server.sessions) > 1000:
                self.server.sessions = {key: value for key, value in self.server.sessions.items() if value["expires"] > time.time()}
            session_id = secrets.token_urlsafe(32)
            session = {"csrf": secrets.token_urlsafe(32), "authorized": not bool(self.server.auth_token), "expires": time.time() + 43200}
            self.server.sessions[session_id] = session
        secure = "; Secure" if self.headers.get("X-Forwarded-Proto") == "https" else ""
        return session_id, session, "crawler_session=" + session_id + "; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200" + secure

    def valid_origin(self):
        try:
            host = urlsplit("//" + self.headers.get("Host", "")).hostname
        except ValueError:
            return False
        if host not in self.server.allowed_hosts:
            return False
        # Email verification/recovery links arrive as cross-site document navigations.
        # Serving a public page is safe; APIs and all mutations keep the origin checks.
        public_navigation = self.command == "GET" and not urlsplit(self.path).path.startswith("/api/") and self.headers.get("Sec-Fetch-Mode") == "navigate" and self.headers.get("Sec-Fetch-Dest") == "document"
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            if not public_navigation: return False
        origin = self.headers.get("Origin")
        if origin and urlsplit(origin).netloc != self.headers.get("Host") and not public_navigation:
            return False
        return True

    def authorization(self, session):
        bearer = self.headers.get("Authorization", "")
        return bool(self.server.auth_token and bearer.startswith("Bearer ") and hmac.compare_digest(bearer[7:], self.server.auth_token)) or session["authorized"]

    def account_session(self):
        if hasattr(self, "_account"): return self._account
        cookie = SimpleCookie()
        try: cookie.load(self.headers.get("Cookie", ""))
        except Exception: pass
        value = cookie.get("crawler_account")
        self._account = self.server.service.accounts.session(value.value if value else None)
        return self._account

    def principal(self, session):
        account = self.account_session()
        if account:
            if self.server.service.accounts.public(account)["needsMfa"]: raise PermissionError("Complete multifactor verification to open private research")
            return account["user"]["id"]
        if self.authorization(session): return "local-owner"
        raise PermissionError("Sign in to open your private research")

    def is_owner(self, session):
        bearer = self.headers.get("Authorization", "")
        valid_bearer = bool(self.server.auth_token and bearer.startswith("Bearer ") and hmac.compare_digest(bearer[7:], self.server.auth_token))
        return valid_bearer or self.authorization(session) and not self.account_session()

    def private_read(self, path, session):
        service = self.server.service
        query = parse_qs(urlsplit(self.path).query)
        value = lambda name, default="": query.get(name, [default])[0]
        owner = self.principal(session)
        if path == "/api/boards": return service.network_research.board(owner, value("id")) if value("id") else {"boards": service.network_research.list_boards(owner)}
        if path == "/api/my-research": return service.network_research.personal(owner)
        if path == "/api/my-research/export": return service.network_research.export_personal(owner)
        if path == "/api/network-node": return service.network_research.inspect(owner, value("boardId"), value("id"))
        if path == "/api/board-recommendations": return service.recommendations.view(owner, value("boardId"), full=value("full")=="1")
        raise ValueError("Unknown private research route")

    def private_post(self, path, body, session):
        network, owner = self.server.service.network_research, self.principal(session)
        if path == "/api/boards":
            if self.account_session() and not any(r["ownerId"] == owner and r["topicId"] == body.get("topicId") for r in self.server.service.db.latest("accountTopic", 10000)):
                raise ValueError("Start this topic from your own research search first")
            return network.create_board(owner, body)
        if path == "/api/boards/save": return network.save_board(owner, body)
        if path == "/api/boards/action": return network.board_action(owner, body)
        if path == "/api/portfolios": return network.portfolio(owner, body)
        if path == "/api/my-research": return network.personal_action(owner, body)
        if path == "/api/network/research":
            self.server.service.accounts.limit(owner, "research")
            return network.request_task(owner, body)
        raise ValueError("Unknown private research operation")

    def do_GET(self):
        path = urlsplit(self.path).path
        if not self.valid_origin():
            self.json({"error": "Untrusted request origin or host"}, 403)
            return
        if not path.startswith("/api/"):
            self.static(path)
            return
        _, session, cookie = self.session()
        if path == "/api/session":
            account = self.account_session()
            account_state = self.server.service.accounts.public(account)
            self.json({"csrf": session["csrf"], "authorized": self.is_owner(session) or bool(account and not account_state["needsMfa"]), "ownerAuthorized": self.is_owner(session),
                       "authenticationRequired": bool(self.server.auth_token), "accountConfigured": account_state["configured"], "user": account_state["user"]}, cookie=cookie)
            return
        if path == "/api/accounts":
            self.json(self.server.service.accounts.public(self.account_session()), cookie=cookie)
            return
        if path == "/api/ready":
            service = self.server.service
            stopping = self.server.stopping.is_set()
            self.json({"service": "trend-crawler", "ready": not stopping, "http": self.server.http_load(), "status": "stopping" if stopping else "running", "ai": {"configured": service.ai.ready, "model": service.ai.model or None, "automaticAnalysis": service.auto_ai}}, status=503 if stopping else 200, cookie=cookie)
            return
        if self.server.stopping.is_set():
            self.json({"error": "Research server is shutting down", "status": "stopping"}, 503, cookie)
            return
        if path == "/api/health":
            try:
                self.json(self.server.service.health(), cookie=cookie)
            except Exception:
                self.json({"service": "trend-crawler", "ready": False, "error": "Research storage is temporarily unavailable"}, 503, cookie)
            return
        if path in {"/api/boards", "/api/my-research", "/api/my-research/export", "/api/network-node", "/api/board-recommendations"}:
            try:
                result = self.private_read(path, session)
                self.json(result, status=202 if result.get("refreshing") else 200, cookie=cookie)
            except PermissionError as exc: self.json({"error": str(exc)}, 401, cookie)
            except (ValueError, KeyError) as exc: self.json({"error": str(exc)}, 400, cookie)
            except Exception: self.json({"error": "Private research could not be loaded"}, 500, cookie)
            return
        account = self.account_session()
        public_reads = {"/api/source-items", "/api/sources", "/api/documents", "/api/events", "/api/investment", "/api/topics", "/api/ai/settings", "/api/asset-profile", "/api/cross-market-report", "/api/observations", "/api/market-data", "/api/asset-assessments", "/api/dossier", "/api/graph", "/api/document-versions", "/api/event-study"}
        account_allowed = bool(account and not self.server.service.accounts.public(account)["needsMfa"] and path in public_reads)
        if not self.is_owner(session) and not account_allowed:
            self.json({"error": "Owner sign-in is required"}, 401, cookie)
            return
        query = parse_qs(urlsplit(self.path).query)
        value = lambda name, default="": query.get(name, [default])[0]
        service = self.server.service
        try:
            if path == "/api/sources":
                result = {"sources": [service.public_source(source) for source in service.db.list("source")]}
            elif path == "/api/source-items":
                result = service.source_items(value("id"))
            elif path == "/api/documents":
                result = service.documents(int(value("after", 0)), value("afterId"), max(1, min(500, int(value("limit", 300)))))
            elif path == "/api/events":
                result = {"events": [event for event in service.db.latest("event", 1000) if not event.get("mergedInto")]}
            elif path == "/api/investment":
                result = service.investments.overview()
            elif path == "/api/topics":
                if account:
                    subscriptions = {r["topicId"]: r for r in service.db.latest("accountTopic", 10000) if r["ownerId"] == account["user"]["id"]}
                    owned_ids = set(subscriptions)
                    owned_ids.update(b["topicId"] for b in service.network_research.list_boards(account["user"]["id"]))
                    if value("id") and value("id") not in owned_ids: raise ValueError("Research topic not found")
                    def personal_topic(row):
                        return {**row, "enabled": subscriptions.get(row["id"], {}).get("enabled", True)}
                    result = personal_topic(service.topics.get(value("id"))) if value("id") else {"topics": [personal_topic(r) for r in service.topics.list() if r["id"] in owned_ids]}
                else: result = service.topics.get(value("id")) if value("id") else {"topics": service.topics.list()}
            elif path == "/api/ai/settings":
                result = service.ai_settings.status()
            elif path == "/api/ai/models":
                result = service.ai_settings.available_models()
            elif path == "/api/asset-profile":
                result = service.investments.profile(value("id"), int(value("at")) if value("at") else None)
            elif path == "/api/cross-market-report":
                result = service.investments.report(value("id"), int(value("at")) if value("at") else None)
            elif path == "/api/market-data":
                result = service.market_data(value("symbol"),value("type"))
            elif path == "/api/observations":
                result = {"observations": service.investments._observations(value("assetId") or None, int(value("at")) if value("at") else None)}
            elif path == "/api/asset-assessments":
                result = {"assessments": [r for r in service.db.latest("coordinatorRun", 500) if r["assetId"] == value("id")]}
            elif path == "/api/event-study":
                result = service.investments.study(value("assetId"), value("benchmarkId"), value("documentId"))
            elif path == "/api/dossier":
                result = service.dossier(value("documentId") or None, value("eventId") or None)
            elif path == "/api/graph":
                result = service.graph(value("start"), int(value("depth", 2)), int(value("asOf")) if value("asOf") else None)
            elif path == "/api/workspace":
                result = service.workspace()
            elif path == "/api/operations":
                result = {"health": service.health(), "jobs": service.db.jobs(limit=100), "auditIntegrity": service.db.verify_audit(), "scheduler": service.db.get("operation", "scheduler")}
            elif path == "/api/metrics":
                result = {"observations": analysis.quantitative(service.db.latest("observation", 20000), now_ms()), "forecastEvaluation": analysis.evaluate_forecasts(service.db.latest("forecast", 5000))}
            elif path == "/api/replay":
                result = service.replay(int(value("at", 0)))
            elif path == "/api/document-versions":
                result = {"versions": service.db.versions(value("id"))}
            elif path == "/api/raw":
                doc = service.db.get("document", value("id"))
                if not doc:
                    raise ValueError("Document not found")
                result = {"documentId": doc["id"], "version": doc["version"], "raw": json.loads(service.objects.get(doc["objectKey"]))}
            elif path == "/api/export":
                result = {"schema": "trend-crawler/server-3", "exportedAt": now_ms(), "documents": service.db.latest("document", 20000), "sources": [service.public_source(source) for source in service.db.list("source")], "claims": service.db.latest("claim", 20000), "workspace": service.workspace(), "relationships": service.db.latest("relationship", 20000), "investment": service.investments.overview(), "profileRevisions": service.db.latest("profileRevision", 20000), "observations": service.db.latest("observation", 20000), "observationVintages": service.db.latest("observationVintage", 20000), "reportRevisions": service.db.latest("crossMarketRevision", 20000), "auditIntegrity": service.db.verify_audit(), "limits": {"recordsPerCollection": 20000}}
                result.update(topics=service.topics.list(), topicRevisions=service.db.latest("topicRevision", 20000))
            else:
                self.json({"error": "Unknown API route"}, 404)
                return
            self.json(result, cookie=cookie)
        except (ValueError, KeyError) as exc:
            self.json({"error": str(exc)}, 400)
        except ConnectorError as exc:
            self.json({"error": str(exc), "errorCode": getattr(exc, "code", "provider_error")}, 502)
        except Exception:
            self.json({"error": "Research service could not complete this request"}, 500)

    def do_POST(self):
        if not self.valid_origin():
            # Consume ordinary rejected JSON bodies before closing the HTTP/1.0
            # connection, preventing a TCP reset from hiding the 403 response.
            try:
                length = max(0, min(65536, int(self.headers.get("Content-Length", "0"))))
                self.connection.settimeout(2)
                if length:
                    self.rfile.read(length)
            except (ValueError, OSError):
                pass
            self.json({"error": "Untrusted request origin or host"}, 403)
            return
        path = urlsplit(self.path).path
        _, session, cookie = self.session()
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            self.json({"error": "Requests must use application/json"}, 415)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 12 * 1024 * 1024:
                self.json({"error": "Request body is missing or too large"}, 413)
                return
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError("JSON request body must be an object")
        except (ValueError, UnicodeError):
            self.json({"error": "Invalid JSON request"}, 400)
            return
        if path == "/api/login":
            if self.server.auth_token and not hmac.compare_digest(str(body.get("token", "")), self.server.auth_token):
                self.json({"error": "Owner token was not accepted"}, 401, cookie)
                return
            session["authorized"] = True
            self.json({"authorized": True, "csrf": session["csrf"]}, cookie=cookie)
            return
        bearer_value = self.headers.get("Authorization", "")
        bearer = bool(self.server.auth_token and bearer_value.startswith("Bearer ") and hmac.compare_digest(bearer_value[7:], self.server.auth_token))
        if not path.startswith("/api/accounts/") and not self.authorization(session) and not self.account_session():
            self.json({"error": "Sign in to access research"}, 401, cookie)
            return
        if not bearer and not hmac.compare_digest(self.headers.get("X-Crawler-CSRF", ""), session["csrf"]):
            self.json({"error": "A valid same-origin session token is required"}, 403, cookie)
            return
        if path == "/api/control/shutdown":
            if not self.is_owner(session):
                self.json({"error": "Only the server owner can stop research services"}, 403, cookie)
                return
            self.json({"status": "stopping", "message": "Stopping research services. Open browser tabs will show the offline state."}, cookie=cookie)
            self.server.initiate_shutdown()
            return
        if self.server.stopping.is_set():
            self.json({"error": "Research server is shutting down", "status": "stopping"}, 503, cookie)
            return
        service = self.server.service
        if path.startswith("/api/accounts/"):
            try:
                service.accounts.limit(self.client_address[0], path)
                action = path.rsplit("/", 1)[-1]
                if action == "setup":
                    if not self.is_owner(session): raise PermissionError("Server owner sign-in is required to configure accounts")
                    result, account_token = service.accounts.setup(body), None
                else:
                    public_url = os.getenv("CRAWLER_PUBLIC_URL") or ("https" if self.headers.get("X-Forwarded-Proto") == "https" else "http") + "://" + self.headers.get("Host", "")
                    result, account_token = service.accounts.action(action, body, self.account_session(), callback=public_url.rstrip("/") + "/CRAWLER/account.html?view=callback")
                cookies = [cookie] if cookie else []
                if account_token is not None:
                    session["csrf"] = secrets.token_urlsafe(32)
                    result["csrf"] = session["csrf"]
                    secure = "; Secure" if self.headers.get("X-Forwarded-Proto") == "https" else ""
                    persistent = "; Max-Age=2592000" if body.get("remember") else ""
                    if account_token == "": persistent = "; Max-Age=0"
                    cookies.append("crawler_account=" + account_token + "; HttpOnly; SameSite=Lax; Path=/" + persistent + secure)
                self.json(result, cookie=cookies)
            except PermissionError as exc: self.json({"error": str(exc)}, 403, cookie)
            except ValueError as exc: self.json({"error": str(exc)}, 400, cookie)
            except Exception: self.json({"error": "Account operation could not complete"}, 500, cookie)
            return
        if path in {"/api/boards", "/api/boards/save", "/api/boards/action", "/api/portfolios", "/api/my-research", "/api/network/research"}:
            try: self.json(self.private_post(path, body, session), cookie=cookie)
            except PermissionError as exc: self.json({"error": str(exc)}, 401, cookie)
            except BoardConflict as exc: self.json({"error": str(exc), "conflict": True}, 409, cookie)
            except (ValueError, KeyError) as exc: self.json({"error": str(exc)}, 400, cookie)
            except Exception: self.json({"error": "Private research could not be updated"}, 500, cookie)
            return
        account = self.account_session()
        account_topics = bool(account and not service.accounts.public(account)["needsMfa"] and path in {"/api/topics", "/api/topics/refresh", "/api/topics/toggle", "/api/topics/delete"})
        if not self.is_owner(session) and not account_topics:
            self.json({"error": "Owner sign-in is required"}, 401, cookie)
            return
        try:
            if path == "/api/sources":
                result = service.add_source(body)
            elif path == "/api/sources/toggle":
                result = service.toggle_source(body.get("id", ""), body.get("enabled"))
            elif path == "/api/sources/poll":
                source = service.db.get("source", body.get("id", ""))
                if not source or not source.get("enabled"):
                    raise ValueError("Enable the registered source before polling it")
                result = {"jobId": service.queue_source_poll(source["id"], manual=True)}
            elif path == "/api/sources/poll-all":
                result = {"jobIds": [service.queue_source_poll(s["id"], manual=True) for s in service.db.list("source") if s.get("enabled")]}
            elif path == "/api/documents/import":
                result = service.import_document(body)
            elif path == "/api/documents/fetch":
                source = service.db.get("source", body.get("sourceId", ""))
                if not source or not source.get("allowFullText"):
                    raise ValueError("Enable permitted full-document collection for this source first")
                result = {"jobId": service.db.enqueue("fetch-document", {"sourceId": source["id"], "url": str(body.get("url", ""))})}
            elif path == "/api/documents/enrich":
                doc = service.db.get("document", body.get("id", ""))
                if not doc or not service.ai.ready:
                    raise ValueError("Select a collected document and configure server AI first")
                result = {"jobId": service.db.enqueue("enrich", {"documentId": doc["id"], "version": doc["version"]})}
            elif path == "/api/claims/review":
                result = service.review_claim(body)
            elif path == "/api/research":
                result = service.research(body.get("question", ""), body.get("conversationId", "default"), bool(body.get("useAI", True)))
            elif path == "/api/topics":
                service.accounts.limit(account["user"]["id"] if account else self.client_address[0], "research")
                result = service.topics.create(body)
                if account:
                    owner = account["user"]["id"]
                    link_id = analysis.digest(owner + result["id"])
                    service.db.put("accountTopic", link_id, {"id": link_id, "ownerId": owner, "topicId": result["id"], "enabled": True})
            elif path == "/api/topics/refresh":
                if account and not any(r["ownerId"] == account["user"]["id"] and r["topicId"] == body.get("id") for r in service.db.latest("accountTopic", 10000)): raise ValueError("Research topic not found")
                result = service.topics.refresh(body.get("id", ""))
            elif path == "/api/topics/delete":
                owner = self.principal(session)
                if account and not any(r["ownerId"] == owner and r["topicId"] == body.get("id") for r in service.db.latest("accountTopic", 10000)) and not any(b["topicId"] == body.get("id") for b in service.network_research.list_boards(owner)):
                    raise ValueError("Research topic not found")
                result = service.topics.delete(body.get("id", ""), owner)
            elif path == "/api/topics/toggle":
                if account:
                    link_id = analysis.digest(account["user"]["id"] + str(body.get("id", "")))
                    link = service.db.get("accountTopic", link_id)
                    if not link or link["ownerId"] != account["user"]["id"]: raise ValueError("Research topic not found")
                    link["enabled"] = body.get("enabled") is True
                    service.db.put("accountTopic", link_id, link)
                    if link["enabled"]: service.topics.configure(link["topicId"], {"enabled": True})
                    else: service.topics.stop(link["topicId"], account["user"]["id"])
                    result = {**service.topics.get(link["topicId"]), "enabled": link["enabled"]}
                else: result = service.topics.configure(body.get("id", ""), {"enabled": True}) if body.get("enabled") else service.topics.stop(body.get("id", ""))
            elif path == "/api/recommendations/settings":
                result = service.recommendations.configure(body)
            elif path == "/api/ai/settings":
                result = service.ai_settings.configure(body)
            elif path == "/api/ai/connect":
                result = service.ai_settings.connect(body)
            elif path == "/api/ai/models":
                result = service.ai_settings.available_models(body.get("apiKey"))
            elif path == "/api/ai/test":
                result = service.ai_settings.test_connection()
            elif path == "/api/investment/rules":
                result = service.investments.configure(body)
            elif path == "/api/investment/run":
                result = {"jobId": service.db.enqueue("research-cycle", {"reason": "Requested evidence review"})}
            elif path == "/api/investment/discover":
                result = {"jobId": service.db.enqueue("discover-assets", {})}
            elif path == "/api/policy-records":
                result = service.investments.policy_record(body)
            elif path == "/api/investigate":
                if not service.db.get("event", body.get("eventId", "")):
                    raise ValueError("Collected event not found")
                result = {"jobId": service.db.enqueue("investigate", {"eventId": body["eventId"]})}
            elif path == "/api/relationships":
                result = service.add_relationship(body)
            elif path == "/api/network/review":
                result = service.network_research.review_edge(body.get("id", ""), "server-owner", body.get("status", "Reported"), body.get("reason", ""))
            elif path == "/api/monitors":
                result = service.create_monitor(body)
            elif path == "/api/monitors/toggle":
                monitor = service.db.get("monitor", body.get("id", ""))
                if not monitor:
                    raise ValueError("Monitor not found")
                monitor["enabled"] = bool(body.get("enabled"))
                result = service.db.put("monitor", monitor["id"], monitor)
            elif path == "/api/forecasts":
                result = service.forecast(body)
            elif path == "/api/forecasts/resolve":
                result = service.resolve_forecast(body.get("id", ""), body)
            elif path == "/api/briefs":
                result = service.brief()
            elif path == "/api/briefs/schedule":
                result = service.schedule_brief(body)
            elif path == "/api/schedules/toggle":
                schedule = service.db.get("schedule", body.get("id", ""))
                if not schedule:
                    raise ValueError("Brief schedule not found")
                schedule["enabled"] = bool(body.get("enabled"))
                result = service.db.put("schedule", schedule["id"], schedule)
            elif path == "/api/workspace":
                result = service.save_workspace(body)
            elif path == "/api/jobs/retry":
                result = {"retried": service.db.retry_job(body.get("id", ""))}
            elif path == "/api/observations":
                source = service.db.get("source", body.get("sourceId", ""))
                if not source:
                    raise ValueError("Registered observation source not found")
                result = service.observation(source, body)
            else:
                self.json({"error": "Unknown API route"}, 404)
                return
            self.json(result, cookie=cookie)
        except (ValueError, KeyError) as exc:
            self.json({"error": str(exc)}, 400)
        except ConnectorError as exc:
            self.json({"error": str(exc), "errorCode": getattr(exc, "code", "provider_error")}, 502)
        except Exception:
            self.json({"error": "Research service could not complete this request"}, 500)

    def static(self, url_path):
        path = unquote(url_path)
        if path in {"/", "/CRAWLER", "/CRAWLER.html"}:
            self.send_response(302)
            self.send_header("Location", "/CRAWLER/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path == "/CRAWLER/":
            path = "/CRAWLER/index.html"
        if not path.startswith("/CRAWLER/"):
            self.send_error(404)
            return
        relative = path[len("/CRAWLER/"):]
        filename = (self.server.root / relative).resolve()
        if not filename.is_relative_to(self.server.root) or filename.suffix.lower() not in {".html", ".css", ".js", ".svg", ".png", ".jpg", ".webp", ".ico", ".woff2"} or any(part.startswith(".") for part in Path(relative).parts) or relative.startswith(("server/", "tests/", "data/")):
            self.send_error(404)
            return
        try:
            content = filename.read_bytes()
        except OSError:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", (mimetypes.guess_type(filename)[0] or "application/octet-stream") + ("; charset=utf-8" if filename.suffix in {".html", ".js", ".css"} else ""))
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self' https: wss:; img-src 'self' data: https:; font-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(content)





class RecoveryHandler(Handler):
    """Two reserved handlers serve health and static assets, never heavy API work."""
    def busy(self):
        self.json({"error":"Research server is busy. Retry shortly.", "code":"SERVER_BUSY", "retryAfterMs":3000},503)
    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/api/ready" or not path.startswith("/api/"):
            return super().do_GET()
        self.busy()
    def do_POST(self):
        self.busy()
