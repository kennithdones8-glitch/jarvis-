"""Provider adapters.

``OllamaProvider`` talks to a local Ollama server and refuses any non-loopback host, so it
can never become an unaudited path to the network. ``OpenAICompatProvider`` covers cloud
services exposing the OpenAI chat-completions API (Groq, OpenRouter, Gemini's compatible
endpoint, …). Cloud providers are only ever constructed inside the egress gate.
"""

from __future__ import annotations

import ipaddress
import time
from typing import Literal
from urllib.parse import urlsplit

from .http import request_json
from .secrets import SecretStore
from .types import ChatRequest, ChatResponse, ModelInfo, ProviderError, ProviderUnavailable, Usage


def is_loopback_url(url: str) -> bool:
    host = urlsplit(url).hostname
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host or "").is_loopback
    except ValueError:
        return False


def _wire_messages(request: ChatRequest) -> list[dict[str, str]]:
    return [{"role": m.role, "content": m.content} for m in request.messages]


class OllamaProvider:
    location: Literal["local", "cloud"] = "local"
    data_use_note = "runs on this Mac; nothing leaves the machine"

    def __init__(self, name: str, host: str, models: dict[str, ModelInfo], *, timeout: float = 600.0,
                 cache_s: float = 30.0):
        if not is_loopback_url(host):
            raise ValueError(f"local provider {name} must use a loopback host, got {host!r}")
        self.name = name
        self.host = host.rstrip("/")
        self.models = models
        self.timeout = timeout
        self._cache_s = cache_s
        self._cached: tuple[float, set[str]] | None = None

    def available_models(self) -> set[str]:
        """Configured models that are actually installed in Ollama."""
        if self._cached and time.monotonic() - self._cached[0] < self._cache_s:
            return self._cached[1]
        tags = request_json("GET", f"{self.host}/api/tags", timeout=5)
        installed = {m.get("name") for m in tags.get("models", [])} | {m.get("model") for m in tags.get("models", [])}
        found = {mid for mid in self.models if mid in installed or f"{mid}:latest" in installed}
        self._cached = (time.monotonic(), found)
        return found

    def chat(self, model: str, request: ChatRequest) -> ChatResponse:
        payload = {
            "model": model,
            "messages": _wire_messages(request),
            "stream": False,
            "options": {"temperature": request.temperature, "num_predict": request.max_tokens},
        }
        if request.json_mode:
            payload["format"] = "json"
        started = time.monotonic()
        data = request_json("POST", f"{self.host}/api/chat", payload, timeout=self.timeout)
        try:
            text = data["message"]["content"]
        except (KeyError, TypeError):
            raise ProviderError("unexpected response shape from Ollama") from None
        return ChatResponse(
            text=text, provider=self.name, model=model, latency_s=time.monotonic() - started,
            usage=Usage(int(data.get("prompt_eval_count") or 0), int(data.get("eval_count") or 0)),
        )


class OpenAICompatProvider:
    location: Literal["local", "cloud"] = "cloud"

    def __init__(self, name: str, base_url: str, models: dict[str, ModelInfo], *, api_key_secret: str,
                 secrets: SecretStore, data_use_note: str = "", timeout: float = 120.0):
        if urlsplit(base_url).scheme != "https" and not is_loopback_url(base_url):
            raise ValueError(f"cloud provider {name} must use https")
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.models = models
        self.api_key_secret = api_key_secret
        self.secrets = secrets
        self.data_use_note = data_use_note or "check this provider's data-use terms"
        self.timeout = timeout

    def _key(self) -> str:
        key = self.secrets.get(self.api_key_secret)
        if not key:
            raise ProviderUnavailable(f"no API key stored for {self.name} (secret '{self.api_key_secret}')")
        return key

    def available_models(self) -> set[str]:
        self._key()
        return set(self.models)

    def chat(self, model: str, request: ChatRequest) -> ChatResponse:
        payload = {
            "model": model,
            "messages": _wire_messages(request),
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        if request.json_mode:
            payload["response_format"] = {"type": "json_object"}
        started = time.monotonic()
        data = request_json("POST", f"{self.base_url}/chat/completions", payload,
                            headers={"Authorization": f"Bearer {self._key()}"}, timeout=self.timeout)
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            raise ProviderError("unexpected response shape from provider") from None
        usage = data.get("usage") or {}
        return ChatResponse(
            text=text, provider=self.name, model=model, latency_s=time.monotonic() - started,
            usage=Usage(int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)),
        )
