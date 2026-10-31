"""Model configuration (``jarvis.toml`` in the data directory). Strictly validated; holds no secrets."""

from __future__ import annotations

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
    _check_keys("jarvis.toml", data, {"budget", "privacy", "providers", "search", "routing"})
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
                       searxng_url=search.get("searxng_url"), routing_mode=routing.get("mode", "local_first"))


def load_model_config(path: str | Path) -> ModelConfig:
    path = Path(path)
    if not path.exists():
        return ModelConfig()
    with open(path, "rb") as fh:
        return parse_model_config(tomllib.load(fh))
