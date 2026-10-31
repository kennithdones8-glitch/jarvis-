"""Model-layer types: messages tagged with data categories, model capability records, errors."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import Any, Literal, Protocol


class Category(StrEnum):
    """What kind of data a message carries. Drives the privacy gate."""

    SYSTEM_PROMPT = "system_prompt"   # JARVIS's own instructions
    CONVERSATION = "conversation"     # what you said / JARVIS replied
    FILE_CONTENT = "file_content"
    MEMORY = "memory"
    PROJECT = "project"
    WEB_CONTENT = "web_content"       # text fetched from public web pages
    SCREENSHOT = "screenshot"


class Sensitivity(IntEnum):
    PUBLIC = 0
    PRIVATE = 1
    LOCAL_ONLY = 2


@dataclass(frozen=True)
class Message:
    role: Literal["system", "user", "assistant"]
    content: str
    category: Category = Category.CONVERSATION
    # A caller can only ever raise sensitivity for a message, never lower it.
    local_only: bool = False


@dataclass(frozen=True)
class ChatRequest:
    messages: tuple[Message, ...]
    max_tokens: int = 1024
    temperature: float = 0.2
    json_mode: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "messages", tuple(self.messages))
        if not self.messages:
            raise ValueError("a request needs at least one message")
        if not 1 <= self.max_tokens <= 32_768:
            raise ValueError("max_tokens out of range")

    def chars(self) -> int:
        return sum(len(m.content) for m in self.messages)

    def estimated_input_tokens(self) -> int:
        return self.chars() // 4 + 4 * len(self.messages)


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True)
class ChatResponse:
    text: str
    provider: str
    model: str
    usage: Usage = field(default_factory=Usage)
    latency_s: float = 0.0
    cost_usd: float = 0.0
    note: str | None = None  # e.g. "answered locally — Claude is at its usage limit"


@dataclass(frozen=True)
class ModelInfo:
    id: str
    capabilities: frozenset[str]
    context_tokens: int
    quality: int                       # 1–5, relative reasoning/planning ability
    speed: int                         # 1–5, relative responsiveness on *this* hardware
    input_cost_per_mtok: float = 0.0   # USD per million tokens; 0 for local / free tier
    output_cost_per_mtok: float = 0.0


class ProviderError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class ProviderUnavailable(ProviderError):
    def __init__(self, message: str):
        super().__init__(message, retryable=True)


class UsageLimited(ProviderUnavailable):
    """The provider's plan limit is reached. ``reset_at`` is a Unix time when known."""

    def __init__(self, message: str, reset_at: float | None = None):
        super().__init__(message)
        self.reset_at = reset_at


class InvalidModelOutput(ValueError):
    pass


class Provider(Protocol):
    name: str
    location: Literal["local", "cloud"]
    models: dict[str, ModelInfo]
    data_use_note: str

    def available_models(self) -> set[str]: ...

    def chat(self, model: str, request: ChatRequest) -> ChatResponse: ...


def parse_json_output(text: str, required: tuple[str, ...] = ()) -> dict[str, Any]:
    """Validate model output instead of trusting it. Accepts a bare object or one fenced in ```json."""
    body = text.strip()
    if body.startswith("```"):
        body = body.strip("`")
        body = body[4:] if body.lower().startswith("json") else body
    try:
        value = json.loads(body)
    except json.JSONDecodeError as exc:
        raise InvalidModelOutput(f"model did not return valid JSON: {exc}") from None
    if not isinstance(value, dict):
        raise InvalidModelOutput("model JSON output must be an object")
    missing = [k for k in required if k not in value]
    if missing:
        raise InvalidModelOutput(f"model JSON output missing keys: {missing}")
    return value
