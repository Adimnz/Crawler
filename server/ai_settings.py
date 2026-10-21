"""Owner-controlled OpenAI credentials; secrets never enter application records.

Windows credentials are protected for the current OS user with DPAPI. Other
platforms use an owner-readable server file. Environment credentials continue
to work without creating a settings file.
"""
from __future__ import annotations

import base64
import ctypes
import json
import os
from pathlib import Path
import re
import tempfile
import threading

from .ai import AI
from .connectors import ConnectorError
from .storage import now_ms


def _dpapi(value, decrypt=False):
    """Use the current user's Windows vault; never fall back to plaintext."""
    class Blob(ctypes.Structure):
        _fields_ = [("size", ctypes.c_ulong), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = ctypes.create_string_buffer(value)
    source = Blob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if decrypt:
        operation = crypt.CryptUnprotectData
        operation.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                              ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(Blob)]
        arguments = (ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target))
    else:
        operation = crypt.CryptProtectData
        operation.argtypes = [ctypes.POINTER(Blob), ctypes.c_wchar_p, ctypes.c_void_p,
                              ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(Blob)]
        arguments = (ctypes.byref(source), "Crawler OpenAI connection", None, None, None, 1, ctypes.byref(target))
    operation.restype = ctypes.c_int
    if not operation(*arguments):
        raise ValueError("The operating system could not protect the OpenAI connection")
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(ctypes.cast(target.data, ctypes.c_void_p))


class AISettings:
    def __init__(self, service, directory=None):
        self.service = service
        self.path = Path(directory if directory is not None else service.db.directory) / "openai-settings.json"
        self.lock = threading.RLock()
        self.last_test = None
        self.storage = "Environment" if service.ai.key else "Not configured"
        self.load_error = False
        self.disabled = False
        if self.path.exists():
            try:
                if self.path.is_symlink() or self.path.stat().st_size > 24000:
                    raise ValueError("Invalid server settings file")
                if os.name != "nt":
                    os.chmod(self.path, 0o600)
                saved = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(saved, dict) or saved.get("version") != 1:
                    raise ValueError("Unsupported server settings file")
                self.disabled = saved.get("disabled") is True
                model = self._model(saved.get("model", ""), allow_empty=self.disabled)
                automatic = saved.get("automaticAnalysis") is True and not self.disabled
                if self.disabled:
                    key = ""
                elif saved.get("protection") == "windows-dpapi" and os.name == "nt":
                    key = _dpapi(base64.b64decode(saved["protectedKey"], validate=True), decrypt=True).decode("utf-8")
                elif saved.get("protection") == "owner-file" and os.name != "nt":
                    key = saved["key"]
                else:
                    raise ValueError("Saved connection belongs to a different operating system")
                if key:
                    self._key(key)
                self._apply(key, model, automatic)
                self.storage = self._storage() if key else "Disconnected"
            except Exception:
                # A corrupt or transferred credential file must not silently
                # re-enable paid automatic work through environment fallback.
                self._apply("", "", False)
                self.load_error = True
                self.storage = "Unavailable"

    @staticmethod
    def _model(value, allow_empty=False):
        if not isinstance(value, str):
            raise ValueError("Enter an OpenAI model ID")
        value = value.strip()
        if allow_empty and not value:
            return ""
        if not value or len(value) > 200 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/@+-]*", value):
            raise ValueError("Enter a valid OpenAI model ID")
        return value

    @staticmethod
    def _key(value):
        # Avoid assumptions about vendor key prefixes or fixed key lengths.
        if not isinstance(value, str) or not 8 <= len(value) <= 4096 or any(ord(char) <= 32 or ord(char) > 126 for char in value):
            raise ValueError("Enter an API key without spaces or control characters")
        return value

    @staticmethod
    def _storage():
        return "Windows DPAPI" if os.name == "nt" else "Owner-only server file"

    def _apply(self, key, model, automatic):
        # Replace the adapter as one reference so running requests keep their
        # original credentials while new work uses the saved connection.
        adapter = AI(self.service.network)
        adapter.key, adapter.model = key, model
        self.service.ai = adapter
        self.service.auto_ai = bool(automatic and key and model)

    def _save(self, key, model, automatic, disabled=False):
        saved = {"version": 1, "model": model, "automaticAnalysis": bool(automatic), "disabled": bool(disabled)}
        try:
            if key:
                if os.name == "nt":
                    saved.update(protection="windows-dpapi", protectedKey=base64.b64encode(_dpapi(key.encode("utf-8"))).decode("ascii"))
                else:
                    saved.update(protection="owner-file", key=key)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(prefix=".openai-settings-", suffix=".tmp", dir=self.path.parent)
            try:
                if os.name != "nt":
                    os.fchmod(descriptor, 0o600)
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    descriptor = None
                    json.dump(saved, handle, ensure_ascii=False, allow_nan=False)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, self.path)
            finally:
                if descriptor is not None:
                    os.close(descriptor)
                if os.path.exists(temporary):
                    os.unlink(temporary)
        except Exception:
            raise ValueError("The OpenAI connection could not be saved securely on this server") from None

    def status(self):
        with self.lock:
            result = {"keyConfigured": bool(self.service.ai.key), "configured": bool(self.service.ai.ready),
                      "model": self.service.ai.model or "", "automaticAnalysis": bool(self.service.auto_ai),
                      "storage": self.storage, "lastTest": dict(self.last_test) if self.last_test else None}
            if self.load_error:
                result["message"] = "Saved OpenAI settings could not be loaded. Reconnect OpenAI."
            return result

    def configure(self, body):
        if not isinstance(body, dict):
            raise ValueError("OpenAI settings must be an object")
        with self.lock:
            disconnect = body.get("disconnect") is True
            if "automaticAnalysis" in body and not isinstance(body["automaticAnalysis"], bool):
                raise ValueError("Automatic research must be enabled or disabled")
            if disconnect:
                model, key, automatic = self.service.ai.model, "", False
            else:
                model = self._model(body.get("model", self.service.ai.model))
                supplied_key = body.get("apiKey", "")
                if not isinstance(supplied_key, str):
                    raise ValueError("Enter an API key")
                key = self._key(supplied_key.strip()) if supplied_key.strip() else self.service.ai.key
                if not key:
                    raise ValueError("Enter an OpenAI API key to connect")
                automatic = body.get("automaticAnalysis", self.service.auto_ai)
            self._save(key, model, automatic, disabled=disconnect)
            self._apply(key, model, automatic)
            self.storage = self._storage() if key else "Disconnected"
            self.disabled, self.load_error, self.last_test = disconnect, False, None
            self.service.db.audit("OpenAI connection changed", "openai", {"configured": bool(key), "automaticAnalysis": bool(automatic), "model": model})
            return self.status()

    @staticmethod
    def _failure(error, action="connection"):
        """Classify transport failures without reflecting provider content."""
        status = getattr(error, "status", None)
        if status not in {400, 401, 403, 404, 408, 409, 429, 500, 502, 503, 504}:
            status = None
        reason = error
        timed_out = False
        for _ in range(4):
            if isinstance(reason, TimeoutError):
                timed_out = True
                break
            reason = getattr(reason, "__cause__", None)
            if reason is None:
                break
        if status == 401:
            code, message = "invalid_key", "OpenAI rejected this API key. Check or replace the API key."
        elif status == 403:
            code, message = "access_denied", "This OpenAI project does not have permission for this request. Check project and model access."
        elif status == 404:
            code, message = "model_unavailable", "The selected OpenAI model is unavailable to this project. Choose another model."
        elif status == 429:
            code, message = "usage_limit", "OpenAI rate or usage limit reached. Check API billing and usage limits, then retry."
        elif timed_out or status in {408, 504}:
            code, message = "timeout", "OpenAI took too long to respond. Check the server connection or try another model."
        elif status and status >= 500:
            code, message = "provider_unavailable", "OpenAI is temporarily unavailable. Retry shortly."
        elif status == 400:
            code, message = "request_unsupported", "This OpenAI model did not accept the research request. Choose a model that supports Responses and structured outputs."
        else:
            code = "connection_failed"
            message = "OpenAI connection failed. Check the API key, model access, billing, and server network, then retry."
        if action == "models" and status == 404:
            code, message = "models_unavailable", "OpenAI's model list is unavailable. Retry shortly."
        result = {"ok": False, "at": now_ms(), "message": message, "errorCode": code}
        if status:
            result["status"] = status
        return result

    def _candidate(self, body):
        """Resolve proposed credentials while the caller holds the short lock."""
        if not isinstance(body, dict):
            raise ValueError("OpenAI settings must be an object")
        if "automaticAnalysis" in body and not isinstance(body["automaticAnalysis"], bool):
            raise ValueError("Automatic research must be enabled or disabled")
        model = self._model(body.get("model", self.service.ai.model))
        supplied_key = body.get("apiKey", "")
        if not isinstance(supplied_key, str):
            raise ValueError("Enter an API key")
        key = self._key(supplied_key.strip()) if supplied_key.strip() else self.service.ai.key
        if not key:
            raise ValueError("Enter an OpenAI API key to connect")
        adapter = AI(self.service.network)
        adapter.key, adapter.model = key, model
        return adapter, body.get("automaticAnalysis", self.service.auto_ai)

    def available_models(self, api_key=None):
        """List account-visible text model candidates; do not imply capability."""
        with self.lock:
            if api_key is not None and not isinstance(api_key, str):
                raise ValueError("Enter an API key")
            key = self._key(api_key.strip()) if api_key and api_key.strip() else self.service.ai.key
            if not key:
                raise ValueError("Enter an API key before loading available models")
            selected = self.service.ai.model or ""
        try:
            response = self.service.network.json("https://api.openai.com/v1/models", {"Authorization": "Bearer " + key}, None)
            if not isinstance(response, dict) or not isinstance(response.get("data"), list):
                raise ValueError("Invalid model list")
        except Exception as error:
            failure = self._failure(error, "models")
            safe = ConnectorError(failure["message"])
            safe.status, safe.code = failure.get("status"), failure["errorCode"]
            raise safe from None
        excluded = re.compile(r"(?:^|[-_:/])(?:audio|realtime|image|images|embedding|embeddings|video|moderation|transcribe|transcription|speech|tts|whisper|dall-e|sora|instruct|babbage|davinci|curie|ada)(?:$|[-_:/\d])", re.I)
        models = set()
        for item in response["data"][:2000]:
            if not isinstance(item, dict):
                continue
            model = item.get("id")
            try:
                model = self._model(model)
            except ValueError:
                continue
            if key in model or excluded.search(model) or model.lower().startswith(("babbage", "davinci", "curie", "ada-")):
                continue
            models.add(model)
        return {"models": [{"id": model} for model in sorted(models, key=str.casefold)], "selectedModel": selected,
                "capabilityNote": "These model IDs are available to this API key. Connect verifies Responses and structured output support for the selected model."}

    def _check(self, adapter):
        """Make one bounded API request without holding the settings lock."""
        payload = {"model": adapter.model, "store": False, "max_output_tokens": 2048,
                       "input": "Return the connection status.",
                       "text": {"format": {"type": "json_schema", "name": "connection_check", "strict": True,
                                "schema": {"type": "object", "properties": {"status": {"type": "string", "enum": ["connected"]}},
                                           "required": ["status"], "additionalProperties": False}}}}
        try:
            response = self.service.network.json("https://api.openai.com/v1/responses",
                {"Authorization": "Bearer " + adapter.key, "Content-Type": "application/json"}, payload)
            if isinstance(response, dict) and response.get("status") == "incomplete":
                return {"ok": False, "at": now_ms(), "errorCode": "response_incomplete",
                        "message": "OpenAI did not finish the connection check. Retry or choose another model."}
            if not isinstance(response, dict) or response.get("status") != "completed":
                raise ValueError("Incomplete connection check")
            outputs = response.get("output")
            if not isinstance(outputs, list):
                raise ValueError("Invalid connection check")
            texts = []
            for output in outputs:
                if not isinstance(output, dict) or not isinstance(output.get("content"), list):
                    continue
                texts.extend(content["text"] for content in output["content"] if isinstance(content, dict)
                             and content.get("type") == "output_text" and isinstance(content.get("text"), str))
            if json.loads("".join(texts)) != {"status": "connected"}:
                raise ValueError("Invalid connection check")
            return {"ok": True, "at": now_ms(), "message": "OpenAI Responses API connection verified."}
        except Exception as error:
            # Never expose provider response bodies, URLs, or exceptions;
            # vendor messages can contain submitted credentials.
            return self._failure(error)

    @staticmethod
    def _settings_changed():
        return {"ok": False, "at": now_ms(), "errorCode": "settings_changed",
                "message": "OpenAI settings changed during the connection check. Retry with the current settings."}

    def test_connection(self, body=None):
        with self.lock:
            current = self.service.ai
            adapter = self._candidate(body)[0] if body is not None else current
            if not adapter.ready:
                raise ValueError("Connect an API key and model before testing OpenAI")
        checked = self._check(adapter)
        with self.lock:
            if self.service.ai is not current:
                checked = self._settings_changed()
            elif adapter.key == current.key and adapter.model == current.model:
                self.last_test = checked
            return {**self.status(), "connectionTest": checked}

    def connect(self, body):
        """Verify first; persist and enable automatic work only after success."""
        with self.lock:
            adapter, automatic = self._candidate(body)
            current = self.service.ai
        checked = self._check(adapter)
        with self.lock:
            if self.service.ai is not current:
                checked = self._settings_changed()
            if checked["ok"]:
                self._save(adapter.key, adapter.model, automatic)
                self._apply(adapter.key, adapter.model, automatic)
                self.storage = self._storage()
                self.disabled, self.load_error, self.last_test = False, False, checked
                self.service.db.audit("OpenAI connection verified", "openai", {"configured": True, "automaticAnalysis": bool(automatic), "model": adapter.model})
            return {**self.status(), "connectionTest": checked}
