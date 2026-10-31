"""Model configuration (``jarvis.toml`` in the data directory). Strictly validated; holds no secrets."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .router import CAPABILITIES
from .types import Category, ModelInfo


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    kind: str
    enabled: bool
    models: dict[str, ModelInfo]
    host: str | None = None
    base_url: str | None = None
    api_key_secret: str | None = None
    data_use_note: str = ""
    command: str = "claude"


@dataclass(frozen=True)
class ModelConfig:
    monthly_limit_usd: float = 0.0
    local_only_categories: tuple[str, ...] = ()
    providers: tuple[ProviderConfig, ...] = field(default_factory=tuple)
    searxng_url: str | None = None
    routing_mode: str = "local_first"
    memory: dict[str, Any] = field(default_factory=dict)
    backup: dict[str, Any] = field(default_factory=dict)
    remote: dict[str, Any] = field(default_factory=dict)
    proactive: dict[str, Any] = field(default_factory=dict)
    voice: dict[str, Any] = field(default_factory=dict)


def _check_keys(where: str, data: dict[str, Any], allowed: set[str]) -> None:
    extra = set(data) - allowed
    if extra:
        raise ConfigError(f"{where}: unknown keys {sorted(extra)}")


def _model(where: str, raw: dict[str, Any]) -> ModelInfo:
    _check_keys(where, raw, {"id", "capabilities", "context_tokens", "quality", "speed",
                             "input_cost_per_mtok", "output_cost_per_mtok"})
    caps = frozenset(raw.get("capabilities", []))
    if not caps or caps - CAPABILITIES:
        raise ConfigError(f"{where}: capabilities must be a non-empty subset of {sorted(CAPABILITIES)}")
    for k in ("quality", "speed"):
        if not 1 <= int(raw.get(k, 0)) <= 5:
            raise ConfigError(f"{where}: {k} must be 1–5")
    costs = [float(raw.get("input_cost_per_mtok", 0)), float(raw.get("output_cost_per_mtok", 0))]
    if any(c < 0 for c in costs):
        raise ConfigError(f"{where}: costs cannot be negative")
    return ModelInfo(id=str(raw["id"]), capabilities=caps, context_tokens=int(raw["context_tokens"]),
                     quality=int(raw["quality"]), speed=int(raw["speed"]),
                     input_cost_per_mtok=costs[0], output_cost_per_mtok=costs[1])


def parse_model_config(data: dict[str, Any]) -> ModelConfig:
    _check_keys("jarvis.toml", data, {"budget", "privacy", "providers", "search", "routing", "memory", "backup",
                                      "remote", "proactive", "voice"})
    voice = data.get("voice", {})
    _check_keys("[voice]", voice, {"enabled", "server", "whisper_binary", "model", "language", "threads"})
    from .providers import is_loopback_url
    if not is_loopback_url(str(voice.get("server", "http://127.0.0.1:8178"))):
        raise ConfigError("[voice]: server must be on this Mac (http://127.0.0.1:PORT) — audio never leaves it")
    if not re.fullmatch(r"[a-z]{2}|auto", str(voice.get("language", "en"))):
        raise ConfigError("[voice]: language must be a two-letter code like 'en', or 'auto'")
    if not 1 <= int(voice.get("threads", 4)) <= 16:
        raise ConfigError("[voice]: threads must be 1–16")
    proactive = data.get("proactive", {})
    _check_keys("[proactive]", proactive, {"enabled", "briefing_time", "quiet_hours", "approval_reminder_min"})
    from ..proactive import validate
    try:
        proactive = validate(proactive)
    except (ValueError, TypeError) as exc:
        raise ConfigError(f"[proactive]: {exc}") from None
    remote = data.get("remote", {})
    _check_keys("[remote]", remote, {"enabled", "hostname"})
    if remote.get("enabled") and not str(remote.get("hostname", "")).endswith(".ts.net"):
        raise ConfigError("[remote]: hostname must be your Mac's Tailscale name (….ts.net)")
    backup = data.get("backup", {})
    _check_keys("[backup]", backup, {"auto", "keep", "dir"})
    if not 1 <= int(backup.get("keep", 14)) <= 365:
        raise ConfigError("[backup]: keep must be between 1 and 365")
    memory = data.get("memory", {})
    _check_keys("[memory]", memory, {"enabled", "extract", "exclude_topics", "recall_limit"})
    if not isinstance(memory.get("exclude_topics", []), list):
        raise ConfigError("[memory]: exclude_topics must be a list of words")
    routing = data.get("routing", {})
    _check_keys("[routing]", routing, {"mode"})
    if routing.get("mode", "local_first") not in ("local_first", "best", "hybrid"):
        raise ConfigError("[routing]: mode must be 'local_first', 'best' or 'hybrid'")
    search = data.get("search", {})
    _check_keys("[search]", search, {"searxng_url"})
    budget = data.get("budget", {})
    _check_keys("[budget]", budget, {"monthly_limit_usd"})
    privacy = data.get("privacy", {})
    _check_keys("[privacy]", privacy, {"local_only_categories"})
    local_only = tuple(privacy.get("local_only_categories", []))
    for c in local_only:
        try:
            Category(c)
        except ValueError:
            raise ConfigError(f"[privacy]: unknown category {c!r}") from None

    providers = []
    for name, raw in data.get("providers", {}).items():
        where = f"[providers.{name}]"
        _check_keys(where, raw, {"kind", "enabled", "host", "base_url", "api_key_secret", "data_use_note", "models",
                                 "command"})
        kind = raw.get("kind")
        if kind not in ("ollama", "openai_compat", "claude_code"):
            raise ConfigError(f"{where}: kind must be 'ollama', 'openai_compat' or 'claude_code'")
        if kind == "openai_compat" and not (raw.get("base_url") and raw.get("api_key_secret")):
            raise ConfigError(f"{where}: base_url and api_key_secret are required")
        models = {}
        for i, m in enumerate(raw.get("models", [])):
            info = _model(f"{where} model {i}", m)
            models[info.id] = info
        providers.append(ProviderConfig(
            name=name, kind=kind, enabled=bool(raw.get("enabled", False)), models=models,
            host=raw.get("host", "http://127.0.0.1:11434"), base_url=raw.get("base_url"),
            api_key_secret=raw.get("api_key_secret"), data_use_note=raw.get("data_use_note", ""),
            command=str(raw.get("command", "claude")),
        ))
    limit = float(budget.get("monthly_limit_usd", 0.0))
    if limit < 0:
        raise ConfigError("[budget]: monthly_limit_usd cannot be negative")
    return ModelConfig(monthly_limit_usd=limit, local_only_categories=local_only, providers=tuple(providers),
                       searxng_url=search.get("searxng_url"), routing_mode=routing.get("mode", "local_first"),
                       memory=dict(memory), backup=dict(backup), remote=dict(remote), proactive=proactive, voice=dict(voice))


def load_model_config(path: str | Path) -> ModelConfig:
    path = Path(path)
    if not path.exists():
        return ModelConfig()
    with open(path, "rb") as fh:
        return parse_model_config(tomllib.load(fh))
