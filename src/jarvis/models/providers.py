"""Provider adapters.

``OllamaProvider`` talks to a local Ollama server and refuses any non-loopback host, so it
can never become an unaudited path to the network. ``OpenAICompatProvider`` covers cloud
services exposing the OpenAI chat-completions API (Groq, OpenRouter, Gemini's compatible
endpoint, …). Cloud providers are only ever constructed inside the egress gate.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from .http import request_json
from .secrets import SecretStore
from .types import ChatRequest, ChatResponse, ModelInfo, ProviderError, ProviderUnavailable, Usage, UsageLimited


# Load settings only from the (empty) working folder — not from ~/.claude/settings.json, whose "env" or
# "apiKeyHelper" entries could otherwise switch Claude Code to API-key billing. The sign-in itself is
# stored separately (macOS Keychain), so the Pro login keeps working. Verify on the Mac.
SETTINGS_ISOLATION = ("--setting-sources", "project")


class Cancelled(ProviderError):
    """The call was stopped (emergency stop) before it finished."""

    def __init__(self, message: str):
        super().__init__(message, retryable=False)


def run_tracked(args: list[str], *, input: str, timeout: float, cwd: Path, env: dict[str, str],
                cancel_check=None, poll_s: float = 0.5) -> subprocess.CompletedProcess:
    """Like subprocess.run, but the child runs in its own process group and is killed (with any
    children it started) if ``cancel_check()`` turns true — e.g. the emergency stop — or the deadline
    passes. The stop is read from the shared database, so a stop pressed in any JARVIS process works."""
    import signal

    proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, cwd=cwd, env=env, start_new_session=True)
    deadline = time.monotonic() + timeout
    data: str | None = input

    def kill() -> None:
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(proc.pid, sig)
            except (ProcessLookupError, PermissionError):
                return
            try:
                proc.wait(timeout=2)
                return
            except subprocess.TimeoutExpired:
                continue

    while True:
        try:
            out, err = proc.communicate(input=data, timeout=poll_s)
            return subprocess.CompletedProcess(args, proc.returncode, out, err)
        except subprocess.TimeoutExpired:
            data = None  # stdin was already sent
        if cancel_check is not None:
            try:
                stop = cancel_check()
            except Exception:
                stop = False
            if stop:
                kill()
                raise Cancelled("stopped by the emergency stop")
        if time.monotonic() > deadline:
            kill()
            raise subprocess.TimeoutExpired(args, timeout)


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
    streams = True  # can show its reply as it's written

    def __init__(self, name: str, host: str, models: dict[str, ModelInfo], *, timeout: float = 600.0,
                 cache_s: float = 30.0, keep_alive: str = "30m"):
        if not is_loopback_url(host):
            raise ValueError(f"local provider {name} must use a loopback host, got {host!r}")
        self.name = name
        self.host = host.rstrip("/")
        self.models = models
        self.timeout = timeout
        self.keep_alive = keep_alive
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

    def chat(self, model: str, request: ChatRequest, on_token=None) -> ChatResponse:
        """``on_token(text)`` gets each piece of the reply as Ollama writes it (for live display). The reply itself
        is the same either way. If ``on_token`` raises (emergency stop, the viewer left), generation stops."""
        payload = {
            "model": model,
            "messages": _wire_messages(request),
            "stream": on_token is not None,
            "options": {"temperature": request.temperature, "num_predict": request.max_tokens},
            # Keep the model in memory between requests; reloading costs ~10 s on an Intel CPU.
            "keep_alive": self.keep_alive,
        }
        if request.json_mode:
            payload["format"] = "json"
        started = time.monotonic()
        if on_token is not None:
            text, data = self._stream(payload, on_token)
        else:
            data = request_json("POST", f"{self.host}/api/chat", payload, timeout=self.timeout)
            try:
                text = data["message"]["content"]
            except (KeyError, TypeError):
                raise ProviderError("unexpected response shape from Ollama") from None
        return ChatResponse(
            text=text, provider=self.name, model=model, latency_s=time.monotonic() - started,
            usage=Usage(int(data.get("prompt_eval_count") or 0), int(data.get("eval_count") or 0)),
        )


    def _stream(self, payload: dict, on_token) -> tuple[str, dict]:
        import urllib.error
        import urllib.request

        req = urllib.request.Request(f"{self.host}/api/chat", data=json.dumps(payload).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # loopback: never via a proxy
        parts: list[str] = []
        size, final = 0, {}
        try:
            with opener.open(req, timeout=self.timeout) as resp:
                for line in resp:
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        raise ProviderError("unexpected streamed response from Ollama") from None
                    piece = (chunk.get("message") or {}).get("content") or ""
                    if piece:
                        size += len(piece)
                        if size > MAX_STREAM_CHARS:
                            raise ProviderError("Ollama's reply was too long")
                        parts.append(piece)
                        try:
                            on_token(piece)
                        except BaseException as exc:  # the viewer left, or the emergency stop: not Ollama's fault
                            raise _Aborted(exc) from None
                    if chunk.get("done"):
                        final = chunk
                        break
        except _Aborted as stop:
            raise stop.reason from None  # never retried with another model
        except urllib.error.HTTPError as exc:
            raise ProviderError(f"HTTP {exc.code} from provider", retryable=exc.code == 429 or exc.code >= 500) from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            raise ProviderUnavailable(f"provider unreachable: {getattr(exc, 'reason', exc)}") from None
        return "".join(parts), final


MAX_STREAM_CHARS = 200_000


class _Aborted(Exception):
    def __init__(self, reason: BaseException):
        super().__init__(str(reason))
        self.reason = reason


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


class ClaudeCodeProvider:
    """Claude through the official Claude Code CLI, using the owner's Claude Pro login.

    Claude is used purely as a brain: every built-in tool, MCP server and slash command is
    disabled, so it cannot read files, run commands or browse — JARVIS's own tools (and its
    permission engine) do all acting. API-key variables are removed from the environment so the
    CLI can only use the subscription login and never bills an API account. The prompt goes over
    stdin; the working directory is an empty folder so no project instructions are picked up.
    """

    location: Literal["local", "cloud"] = "cloud"
    _STRIP_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "CLAUDE_CODE_USE_BEDROCK",
                  "CLAUDE_CODE_USE_VERTEX")

    def __init__(self, name: str, models: dict[str, ModelInfo], *, workdir: str | Path, command: str = "claude",
                 timeout: float = 300.0, data_use_note: str = ""):
        from dataclasses import replace as _replace

        self.name = name
        # Claude Code can search and read the web, so every Claude model is research-capable.
        self.models = {k: _replace(v, capabilities=v.capabilities | {"research"}) for k, v in models.items()}
        self.command = command
        self.workdir = Path(workdir)
        self.timeout = timeout
        self.data_use_note = data_use_note or "Anthropic, via your Claude Pro plan (Anthropic's consumer terms apply)"
        # While the plan limit is in force, don't call Claude at all (saves time and noise).
        self.limited_until: float | None = None
        # Set by the kernel to "is the emergency stop engaged?" so running calls can be killed.
        self.cancel_check = None
        # A sign-in problem is remembered on disk (each CLI run is a new process), so JARVIS doesn't ask
        # you to approve sending something that can't be sent anyway.
        self._status_file = self.workdir / ".claude-status.json"

    def _blocked(self) -> str | None:
        try:
            status = json.loads(self._status_file.read_text())
        except (OSError, ValueError):
            return None
        return status.get("reason") if status.get("until", 0) > time.time() else None

    def _remember_blocked(self, reason: str, seconds: float = 600) -> None:
        self.workdir.mkdir(parents=True, exist_ok=True)
        self._status_file.write_text(json.dumps({"reason": reason, "until": time.time() + seconds}))

    def clear_status(self) -> None:
        self._status_file.unlink(missing_ok=True)

    @staticmethod
    def parse_reset(message: str, now: float | None = None) -> float | None:
        """Best-effort reset time from Claude Code's limit message ('…|1700000000' or '… resets 3pm')."""
        now = time.time() if now is None else now
        if m := re.search(r"\|(\d{9,11})\b", message):
            return float(m.group(1))
        if m := re.search(r"resets?\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", message, re.IGNORECASE):
            hour, minute, ampm = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
            if ampm == "pm" and hour < 12:
                hour += 12
            if ampm == "am" and hour == 12:
                hour = 0
            local = time.localtime(now)
            target = time.mktime((local.tm_year, local.tm_mon, local.tm_mday, hour, minute, 0, 0, 0, -1))
            return target if target > now else target + 86400
        return None
    def _binary(self) -> str:
        found = shutil.which(self.command)
        if not found:
            raise ProviderUnavailable("Claude Code is not installed (the `claude` command was not found)")
        return found

    def available_models(self) -> set[str]:
        self._binary()
        if blocked := self._blocked():
            raise ProviderUnavailable(f"{blocked} (fix it, then run `jarvis use-claude on`)")
        if self.limited_until and time.time() < self.limited_until:
            raise UsageLimited("Claude is at its usage limit", self.limited_until)
        return set(self.models)

    def research(self, model: str, request: ChatRequest) -> ChatResponse:
        return research_on(self, model, request)

    @staticmethod
    def _split(request: ChatRequest) -> tuple[str, str]:
        system = "\n\n".join(m.content for m in request.messages if m.role == "system")
        if request.json_mode:
            system += "\n\nReply with one JSON object only — no prose, no code fences."
        turns = [m for m in request.messages if m.role != "system"]
        if len(turns) == 1:
            return system, turns[0].content
        transcript = "\n\n".join(f"[{'Owner' if m.role == 'user' else 'You'}]: {m.content}" for m in turns)
        return system, f"Conversation so far:\n\n{transcript}\n\nReply to the owner's last message."

    def chat(self, model: str, request: ChatRequest) -> ChatResponse:
        binary = self._binary()
        system, prompt = self._split(request)
        args = [binary, "-p", "--output-format", "json", "--model", model,
                "--tools", "", "--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence",
                *SETTINGS_ISOLATION,
                "--system-prompt", system or "You are a helpful assistant."]
        env = {k: v for k, v in os.environ.items() if k not in self._STRIP_ENV}
        self.workdir.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        try:
            proc = run_tracked(args, input=prompt, timeout=self.timeout, cwd=self.workdir, env=env,
                               cancel_check=self.cancel_check)
        except subprocess.TimeoutExpired:
            raise ProviderError(f"Claude Code did not answer within {self.timeout:.0f}s", retryable=True) from None
        except OSError as exc:
            raise ProviderUnavailable(f"could not start Claude Code: {exc}") from None
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            tail = (proc.stderr or proc.stdout or "").strip()[-300:]
            if "login" in tail.lower() or "auth" in tail.lower():
                self._remember_blocked(f"Claude Code is not signed in: {tail[:120]}")
                raise ProviderUnavailable(f"Claude Code is not logged in — run `claude` once and sign in ({tail})") from None
            raise ProviderError(f"Claude Code failed (exit {proc.returncode}): {tail}", retryable=False) from None
        text = data.get("result") if isinstance(data, dict) else None
        if not isinstance(data, dict) or data.get("is_error") or not isinstance(text, str):
            message = str((data or {}).get("result") or (data or {}).get("subtype") or "unknown error")[:300]
            lowered = message.lower()
            if "limit" in lowered:
                reset = self.parse_reset(message)
                if reset is not None and reset <= time.time():
                    reset = None  # a reset time in the past is meaningless; treat as unknown
                # Unknown reset time: back off for 15 minutes before trying Claude again.
                self.limited_until = reset or time.time() + 900
                raise UsageLimited(f"Claude usage limit reached: {message}", reset)
            if "login" in lowered or "auth" in lowered or "credit" in lowered:
                self._remember_blocked(f"Claude Code is not signed in: {message}")
                raise ProviderUnavailable(f"Claude unavailable: {message}")
            raise ProviderError(f"Claude Code error: {message}", retryable=False)
        usage = data.get("usage") or {}
        return ChatResponse(
            text=text, provider=self.name, model=model, latency_s=time.monotonic() - started,
            usage=Usage(int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0)),
        )


URL_RE = re.compile(r"https?://[^\s<>()\[\]\"'`]+")


def normalise_url(url: str) -> str:
    url = url.rstrip(".,;:!?)]}>*_'\"").split("#", 1)[0]
    return url[:-1] if url.endswith("/") else url


def research_on(provider: "ClaudeCodeProvider", model: str, request: ChatRequest) -> ChatResponse:
    """Run a research turn with ONLY Claude Code's read-only web tools enabled.

    Returns the answer plus evidence: the searches made, the pages read, every URL seen in tool
    results, and which cited URLs were actually seen (verified) versus not (unverified)."""
    binary = provider._binary()
    system, prompt = provider._split(request)
    args = [binary, "-p", "--output-format", "stream-json", "--verbose", "--model", model,
            "--tools", "WebSearch,WebFetch", "--allowedTools", "WebSearch,WebFetch", "--permission-mode", "dontAsk",
            "--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence", *SETTINGS_ISOLATION,
            "--system-prompt", system or "You are a careful research assistant."]
    env = {k: v for k, v in os.environ.items() if k not in provider._STRIP_ENV}
    provider.workdir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    try:
        proc = run_tracked(args, input=prompt, timeout=max(provider.timeout, 600), cwd=provider.workdir, env=env,
                           cancel_check=provider.cancel_check)
    except subprocess.TimeoutExpired:
        raise ProviderError("Claude research did not finish in time", retryable=True) from None
    except OSError as exc:
        raise ProviderUnavailable(f"could not start Claude Code: {exc}") from None

    searches: list[str] = []
    fetched: list[str] = []
    seen: set[str] = set()
    result: dict[str, Any] | None = None
    for line in proc.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = event.get("type")
        if kind == "result":
            result = event
            continue
        for block in (event.get("message") or {}).get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                inp = block.get("input") or {}
                if block.get("name") == "WebSearch" and isinstance(inp.get("query"), str):
                    searches.append(inp["query"])
                if block.get("name") == "WebFetch" and isinstance(inp.get("url"), str):
                    fetched.append(inp["url"])
                    seen.add(normalise_url(inp["url"]))
            elif block.get("type") == "tool_result":
                content = block.get("content")
                text = content if isinstance(content, str) else json.dumps(content)
                seen.update(normalise_url(u) for u in URL_RE.findall(text))
    if result is None:
        tail = (proc.stderr or proc.stdout or "").strip()[-300:]
        if "login" in tail.lower():
            provider._remember_blocked(f"Claude Code is not signed in: {tail[:120]}")
            raise ProviderUnavailable(f"Claude Code is not signed in — run `claude` and /login ({tail})")
        raise ProviderError(f"Claude research failed (exit {proc.returncode}): {tail}")
    text = result.get("result")
    if result.get("is_error") or not isinstance(text, str):
        message = str(result.get("result") or result.get("subtype") or "unknown error")[:300]
        if "limit" in message.lower():
            reset = provider.parse_reset(message)
            reset = reset if reset and reset > time.time() else None
            provider.limited_until = reset or time.time() + 900
            raise UsageLimited(f"Claude usage limit reached: {message}", reset)
        raise ProviderError(f"Claude research error: {message}")
    cited = list(dict.fromkeys(normalise_url(u) for u in URL_RE.findall(text)))
    sources = [{"url": u, "verified": u in seen} for u in cited]
    usage = result.get("usage") or {}
    return ChatResponse(
        text=text, provider=provider.name, model=model, latency_s=time.monotonic() - started,
        usage=Usage(int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0)),
        meta={"searches": searches, "fetched": fetched, "sources": sources,
              "verified_sources": sum(1 for s in sources if s["verified"])},
    )
