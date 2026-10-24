"""Supabase Auth adapter. Passwords and provider tokens never enter research data."""
from __future__ import annotations

import base64
from collections import defaultdict, deque
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
import threading
import time
from urllib.parse import quote, urlsplit

from .ai_settings import _dpapi
from .connectors import ConnectorError
from .storage import now_ms

class AccountAuth:
    def __init__(self, service, directory):
        self.s, self.directory = service, Path(directory)
        self.lock = threading.RLock()
        self.url = os.getenv("SUPABASE_URL", "").rstrip("/")
        self.key = os.getenv("SUPABASE_PUBLISHABLE_KEY", os.getenv("SUPABASE_ANON_KEY", ""))
        self.admin_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
        self.sessions, self.limits = {}, defaultdict(deque)
        try:
            config = self._read("account-settings.json")
            if config: self.url, self.key = config["url"], config["key"]
            self.sessions = self._read("account-sessions.json") or {}
        except Exception:
            self.sessions = {}

    @property
    def configured(self):
        return bool(self.url and self.key)

    def _read(self, filename):
        path = self.directory / filename
        if not path.exists(): return None
        if path.is_symlink() or path.stat().st_size > 8 * 1024 * 1024: raise ValueError("Invalid account settings")
        value = json.loads(path.read_text(encoding="utf-8"))
        if os.name == "nt":
            return json.loads(_dpapi(base64.b64decode(value["protected"], validate=True), decrypt=True))
        os.chmod(path, 0o600)
        return value

    def _write(self, filename, value):
        content = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
        if os.name == "nt": content = json.dumps({"protected": base64.b64encode(_dpapi(content)).decode()}).encode()
        self.directory.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".account-", dir=self.directory)
        try:
            if os.name != "nt": os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = None
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.directory / filename)
        finally:
            if descriptor is not None: os.close(descriptor)
            if os.path.exists(temporary): os.unlink(temporary)

    def limit(self, remote, action):
        with self.lock:
            at = time.time()
            if len(self.limits) > 10000: self.limits = defaultdict(deque, {k: v for k, v in self.limits.items() if v and v[-1] > at - 300})
            attempts = self.limits[(remote, action)]
            while attempts and attempts[0] < at - 300: attempts.popleft()
            if len(attempts) >= (30 if action == "research" else 8): raise ValueError("Too many attempts. Wait five minutes and try again.")
            attempts.append(at)

    def provider(self, method, path, body=None, token=None, url=None, key=None, api="auth/v1"):
        project, publishable = (url or self.url), (key or self.key)
        if not project or not publishable: raise ValueError("Connect your Supabase project in Account setup first")
        headers = {"apikey": publishable, "Content-Type": "application/json"}
        if token: headers["Authorization"] = "Bearer " + token
        try:
            data, _, resolved = self.s.network.fetch(project + "/" + api + "/" + path.lstrip("/"), headers=headers, method=method,
                body=json.dumps(body).encode() if body is not None else None, limit=512000)
            if urlsplit(resolved).netloc != urlsplit(project).netloc: raise ValueError("Unexpected account provider redirect")
            return json.loads(data) if data else {}
        except ConnectorError as exc:
            status = getattr(exc, "status", None)
            message = "Account request failed. Check the email, password or verification code and your project's email settings."
            if status == 429: message = "Supabase's account rate limit was reached. Wait before retrying."
            elif status in {401, 403}: message = "Account credentials or verification were not accepted. Sign in again or check the project configuration."
            elif status == 404: message = "This account operation is unavailable. Check the Supabase project and the account-deletion SQL migration."
            elif status and status >= 500: message = "The account provider is temporarily unavailable. Retry shortly."
            raise ValueError(message) from None
        except (OSError, ValueError, TypeError):
            raise ValueError("The account provider did not complete this request. Check the connection and try again.") from None

    def setup(self, values):
        url = str(values.get("projectURL", self.url)).rstrip("/")
        parsed = urlsplit(url)
        key = values.get("publishableKey") or self.key
        if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(".supabase.co") or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password or parsed.port not in (None, 443):
            raise ValueError("Enter the https://project-ref.supabase.co project URL")
        if not isinstance(key, str) or not 16 <= len(key) <= 6000 or any(c.isspace() for c in key) or key.startswith("sb_secret_"):
            raise ValueError("Use the project's publishable or anon key, not its secret service key")
        if key.count(".") == 2:
            try:
                payload = json.loads(base64.urlsafe_b64decode(key.split(".")[1] + "==="))
            except (ValueError, TypeError):
                payload = {}
            if payload.get("role") == "service_role": raise ValueError("Use the project's publishable or anon key, not its secret service key")
        self.provider("GET", "settings", url=url, key=key)
        with self.lock:
            self._write("account-settings.json", {"url": url, "key": key})
            self.url, self.key = url, key
        return self.public()

    @staticmethod
    def email(value):
        if not isinstance(value, str) or not re.fullmatch(r"[^\s@]{1,120}@[^\s@]{1,120}\.[^\s@]{2,80}", value): raise ValueError("Enter a valid email address")
        return value.strip()

    @staticmethod
    def password(value):
        if not isinstance(value, str) or not 12 <= len(value) <= 1024: raise ValueError("Use a password with at least 12 characters")
        return value

    @staticmethod
    def _user(user):
        return {"id": user["id"], "email": user.get("email", ""), "displayName": str(user.get("user_metadata", {}).get("display_name", ""))[:150],
                "emailVerified": bool(user.get("email_confirmed_at") or user.get("confirmed_at")), "createdAt": user.get("created_at")}

    @staticmethod
    def _aal(token):
        try:
            segment = token.split(".")[1]
            return json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))).get("aal", "aal1")
        except Exception: return "aal1"

    def establish(self, response, remember=False):
        access, refresh = response.get("access_token"), response.get("refresh_token")
        if not isinstance(access, str) or not isinstance(refresh, str) or max(len(access), len(refresh)) > 20000: raise ValueError("Sign in after confirming your email address")
        # Authenticate against the provider; never trust a client-supplied user ID or decoded JWT identity.
        user = self.provider("GET", "user", token=access)
        if not user.get("id") or not self._user(user)["emailVerified"]: raise ValueError("Verify your email address before opening private research")
        token = secrets.token_urlsafe(40)
        key = hashlib.sha256(token.encode()).hexdigest()
        at = time.time()
        session = {"id": key, "user": user, "access": access, "refresh": refresh, "providerExpires": at + min(86400, max(30, int(response.get("expires_in", 3600)))),
                   "expires": at + (30 * 86400 if remember else 43200), "createdAt": now_ms(), "checkedAt": at, "remember": bool(remember)}
        with self.lock:
            self.sessions = {k: v for k, v in self.sessions.items() if v["expires"] > at}
            self.sessions[key] = session
            self._write("account-sessions.json", self.sessions)
        return token, session

    def session(self, token):
        if not token or not self.configured: return None
        key = hashlib.sha256(token.encode()).hexdigest()
        with self.lock:
            session = self.sessions.get(key)
            if not session or session["expires"] < time.time(): return None
            if session["providerExpires"] < time.time() + 60:
                try:
                    refreshed = self.provider("POST", "token?grant_type=refresh_token", {"refresh_token": session["refresh"]})
                    session.update(access=refreshed["access_token"], refresh=refreshed["refresh_token"], providerExpires=time.time() + int(refreshed.get("expires_in", 3600)))
                    session["user"] = self.provider("GET", "user", token=session["access"])
                    session["checkedAt"] = time.time()
                    self._write("account-sessions.json", self.sessions)
                except Exception:
                    self.sessions.pop(key, None)
                    self._write("account-sessions.json", self.sessions)
                    return None
            elif session.get("checkedAt", 0) < time.time() - 60:
                try:
                    session["user"] = self.provider("GET", "user", token=session["access"])
                    session["checkedAt"] = time.time()
                except ValueError: return None
            return session if self._user(session["user"])["emailVerified"] else None

    def public(self, session=None):
        factors = [f for f in (session or {}).get("user", {}).get("factors", []) if f.get("factor_type") == "totp"]
        needs_mfa = bool(any(f.get("status") == "verified" for f in factors) and self._aal(session["access"]) != "aal2") if session else False
        return {"configured": self.configured, "projectURL": self.url, "provider": "Supabase Auth", "user": self._user(session["user"]) if session else None,
                "needsMfa": needs_mfa, "factors": [{k: f.get(k) for k in ("id", "friendly_name", "status")} for f in factors],
                "sessions": [{"id": key, "current": key == session["id"], "createdAt": value["createdAt"], "expiresAt": int(value["expires"] * 1000)} for key, value in self.sessions.items() if session and value["user"]["id"] == session["user"]["id"] and value["expires"] > time.time()]}

    def action(self, action, values, session=None, callback=""):
        if action == "register":
            if values.get("password") != values.get("confirmPassword"): raise ValueError("Passwords do not match")
            if values.get("acceptTerms") is not True: raise ValueError("Accept the account terms to register")
            name = str(values.get("displayName", "")).strip()
            if not 1 <= len(name) <= 150: raise ValueError("Enter a display name")
            self.provider("POST", "signup?redirect_to=" + quote(callback, safe=""), {"email": self.email(values.get("email")), "password": self.password(values.get("password")), "data": {"display_name": name}})
            return {"message": "Check your email to verify your account, then sign in."}, None
        if action == "login":
            password = values.get("password")
            if not isinstance(password, str) or not 1 <= len(password) <= 1024: raise ValueError("Enter your password")
            response = self.provider("POST", "token?grant_type=password", {"email": self.email(values.get("email")), "password": password})
            token, created = self.establish(response, values.get("remember") is True)
            return self.public(created), token
        if action in {"recover", "resend"}:
            self.provider("POST", ("recover" if action == "recover" else "resend") + "?redirect_to=" + quote(callback, safe=""), {"email": self.email(values.get("email")), **({"type": "signup"} if action == "resend" else {})})
            return {"message": "If the account is eligible, a verification email has been sent."}, None
        if action == "verify":
            kind = values.get("type", "signup")
            if kind not in {"signup", "recovery", "email_change"}: raise ValueError("Invalid verification type")
            body = {"type": kind}
            if values.get("tokenHash"): body["token_hash"] = str(values["tokenHash"])[:2048]
            else: body.update(email=self.email(values.get("email")), token=str(values.get("code", ""))[:2048])
            token, created = self.establish(self.provider("POST", "verify", body), False)
            return {**self.public(created), "recovery": kind == "recovery"}, token
        if action == "callback":
            # Implicit email callbacks carry tokens only in the URL fragment;
            # the page removes it immediately and exchanges them for an HttpOnly cookie.
            token, created = self.establish({"access_token": values.get("accessToken"), "refresh_token": values.get("refreshToken"), "expires_in": 3600})
            return self.public(created), token
        if not session: raise ValueError("Sign in to manage your account")
        if action not in {"mfa-challenge", "mfa-verify", "logout"} and self.public(session)["needsMfa"]: raise ValueError("Complete multifactor verification first")
        access, user = session["access"], session["user"]
        if action == "logout":
            scope = "global" if values.get("allSessions") else "others" if values.get("others") else "local"
            self.provider("POST", "logout?scope=" + scope, {}, token=access)
            with self.lock:
                self.sessions = {k: v for k, v in self.sessions.items() if not (v["user"]["id"] == user["id"] and (scope == "global" or scope == "local" and k == session["id"] or scope == "others" and k != session["id"]))}
                self._write("account-sessions.json", self.sessions)
            return {"signedOut": scope != "others", "message": "Sessions updated"}, "" if scope != "others" else None
        if action == "revoke-session":
            target = self.sessions.get(str(values.get("sessionId", "")))
            if not target or target["user"]["id"] != user["id"]: raise ValueError("Session not found")
            self.provider("POST", "logout?scope=local", {}, token=target["access"])
            with self.lock:
                self.sessions.pop(target["id"], None)
                self._write("account-sessions.json", self.sessions)
            return {"revoked": True}, "" if target["id"] == session["id"] else None
        if action in {"profile", "password"}:
            if action == "profile":
                name = str(values.get("displayName", "")).strip()
                if not 1 <= len(name) <= 150: raise ValueError("Enter a display name")
                body = {"data": {**user.get("user_metadata", {}), "display_name": name}}
            else:
                if values.get("password") != values.get("confirmPassword"): raise ValueError("Passwords do not match")
                body = {"password": self.password(values.get("password"))}
                if values.get("currentPassword"): body["current_password"] = str(values["currentPassword"])
                if values.get("nonce"): body["nonce"] = str(values["nonce"])[:30]
            session["user"] = self.provider("PUT", "user", body, token=access)
            with self.lock: self._write("account-sessions.json", self.sessions)
            return self.public(session), None
        if action == "reauthenticate":
            self.provider("GET", "reauthenticate", token=access)
            return {"message": "Check your email for a security confirmation code."}, None
        if action == "mfa-enroll":
            result = self.provider("POST", "factors", {"factor_type": "totp", "friendly_name": "Research Network authenticator"}, token=access)
            return {"factorId": result.get("id"), "secret": result.get("totp", {}).get("secret"), "uri": result.get("totp", {}).get("uri")}, None
        if action in {"mfa-challenge", "mfa-verify", "mfa-remove"}:
            factor = str(values.get("factorId", ""))
            if not re.fullmatch(r"[A-Za-z0-9-]{1,100}", factor): raise ValueError("Choose an authentication factor")
            if action == "mfa-remove":
                self.provider("DELETE", "factors/" + factor, token=access)
                result = {"message": "Authenticator removed"}
            elif action == "mfa-challenge": result = self.provider("POST", "factors/" + factor + "/challenge", {}, token=access)
            else:
                result = self.provider("POST", "factors/" + factor + "/verify", {"challenge_id": str(values.get("challengeId", ""))[:100], "code": str(values.get("code", ""))[:12]}, token=access)
                if result.get("access_token"):
                    session.update(access=result["access_token"], refresh=result.get("refresh_token", session["refresh"]), providerExpires=time.time() + int(result.get("expires_in", 3600)))
            session["user"] = self.provider("GET", "user", token=session["access"])
            with self.lock: self._write("account-sessions.json", self.sessions)
            return {**self.public(session), **({"challengeId": result.get("id")} if action == "mfa-challenge" else {})}, None
        if action == "delete":
            if values.get("confirmation") != user.get("email"): raise ValueError("Type your account email to confirm deletion")
            if self.admin_key: self.provider("DELETE", "admin/users/" + quote(user["id"], safe=""), token=self.admin_key)
            else: self.provider("POST", "delete_own_account", {}, token=access, api="rest/v1/rpc")
            self.s.network_research.delete_personal(user["id"])
            with self.lock:
                self.sessions = {k: v for k, v in self.sessions.items() if v["user"]["id"] != user["id"]}
                self._write("account-sessions.json", self.sessions)
            return {"deleted": True}, ""
        raise ValueError("Unknown account operation")
