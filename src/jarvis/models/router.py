"""Model router and model service.

The router filters every configured model by hard constraints (capability, quality floor,
context size, availability, local-only data, budget) and ranks the survivors local-first:
a cloud model is chosen only when no local model meets the need (raise ``min_quality`` to
ask for a stronger model). Every
rejection is recorded with its reason. The service tries the ranked candidates in order:
local models are called directly, cloud models only through the egress gate. An approval
request is never "worked around" by trying another provider; it pauses the task.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from typing import Iterable, Literal

from ..core.audit import AuditLog
from ..core.killswitch import KillSwitch
from ..core.tools import ApprovalRequired
from .egress import BudgetExceeded, EgressDenied, EgressGate
from .types import Category, ChatRequest, ChatResponse, Message, ModelInfo, Provider, ProviderError, UsageLimited

CAPABILITIES = frozenset({"chat", "plan", "code", "summarize", "classify", "json", "extract"})


@dataclass(frozen=True)
class Need:
    capability: str = "chat"
    min_quality: int = 1
    # "auto": quality when routing mode is "best", speed when it is "local_first".
    prefer: Literal["quality", "speed", "auto"] = "quality"
    local_only: bool = False

    def __post_init__(self) -> None:
        if self.capability not in CAPABILITIES:
            raise ValueError(f"unknown capability {self.capability!r}")


@dataclass(frozen=True)
class Candidate:
    provider: str
    model: str
    location: str
    info: ModelInfo
    score: float


@dataclass(frozen=True)
class Route:
    candidates: tuple[Candidate, ...]
    rejected: dict[str, str] = field(default_factory=dict)

    @property
    def rationale(self) -> str:
        c = self.candidates[0]
        return (f"{c.provider}/{c.model} ({c.location}, quality {c.info.quality}, speed {c.info.speed}); "
                f"{len(self.candidates) - 1} fallback(s), {len(self.rejected)} excluded")


class NoModelAvailable(RuntimeError):
    def __init__(self, message: str, reasons: dict[str, str], *, unavailable: bool = False):
        super().__init__(message)
        self.reasons = reasons
        # True when a model that would have qualified was down/limited (so a fallback makes sense),
        # as opposed to every model being excluded by the rules (local-only data, budget, quality).
        self.unavailable = unavailable


ROUTING_MODES = ("local_first", "best", "hybrid")

TRIAGE_PROMPT = """Classify how demanding the user's message is for an AI assistant. Reply with exactly one word:
SIMPLE - greetings, small talk, quick facts, short rewrites, simple arithmetic
MEDIUM - explanations, summaries, everyday advice, moderate writing
HARD - multi-step reasoning, coding, analysis, planning, long or careful writing, high-stakes questions"""


class ModelRouter:
    """``local_first``: any capable local model outranks every cloud model.
    ``best``: the most capable available model wins; local models are the fallback.
    ``hybrid``: like best, but ModelService first triages chat locally so only demanding requests use
    the cloud, and picks the lightest cloud model that is good enough (saves plan usage)."""

    def __init__(self, local: Iterable[Provider], gate: EgressGate, *, mode: str = "local_first"):
        if mode not in ROUTING_MODES:
            raise ValueError(f"routing mode must be one of {ROUTING_MODES}")
        self.mode = mode
        self.local = {p.name: p for p in local}
        if any(p.location != "local" for p in self.local.values()):
            raise ValueError("cloud providers must be registered with the egress gate")
        self.gate = gate

    def route(self, need: Need, request: ChatRequest) -> Route:
        local_only = need.local_only or self.gate.sensitivity.has_local_only(request)
        needed_context = request.estimated_input_tokens() + request.max_tokens
        rejected: dict[str, str] = {}
        ok: list[Candidate] = []

        sources = [(p.name, "local", p.models, p.available_models) for p in self.local.values()]
        sources += [(s.name, "cloud", s.models, lambda n=s.name: self.gate.available_models(n))
                    for s in self.gate.summaries()]
        for name, location, models, available_fn in sources:
            try:
                available = available_fn()
                unavailable_reason = None
            except ProviderError as exc:
                available, unavailable_reason = set(), str(exc)
            for mid, info in models.items():
                key = f"{name}/{mid}"
                reason = None
                if need.capability not in info.capabilities:
                    reason = f"lacks capability '{need.capability}'"
                elif info.quality < need.min_quality:
                    reason = f"quality {info.quality} below required {need.min_quality}"
                elif info.context_tokens < needed_context:
                    reason = f"context {info.context_tokens} < needed ~{needed_context}"
                elif location == "cloud" and local_only:
                    reason = "request contains local-only data"
                elif unavailable_reason or mid not in available:
                    reason = f"unavailable: {unavailable_reason or 'model not installed'}"
                elif location == "cloud" and not self.gate.budget.allows(self.gate.budget.estimate(info, request)):
                    reason = "would exceed budget"
                if reason:
                    rejected[key] = reason
                    continue
                prefer = need.prefer if need.prefer != "auto" else ("speed" if self.mode == "local_first" else "quality")
                primary, secondary = (info.quality, info.speed) if prefer == "quality" else (info.speed, info.quality)
                local_bonus = 100 if location == "local" and self.mode == "local_first" else 0
                score = local_bonus + primary * 10 + secondary + (0.5 if location == "local" else 0)
                ok.append(Candidate(name, mid, location, info, score))

        if not ok:
            raise NoModelAvailable("no approved model satisfies this request", rejected,
                                   unavailable=any(r.startswith("unavailable") for r in rejected.values()))
        ok.sort(key=lambda c: c.score, reverse=True)
        return Route(tuple(ok), rejected)


class ModelService:
    def __init__(self, router: ModelRouter, audit: AuditLog, killswitch: KillSwitch, *, max_attempts: int = 3):
        self.router = router
        self.audit = audit
        self.killswitch = killswitch
        self.max_attempts = max_attempts

    def complete(self, need: Need, request: ChatRequest, *, purpose: str, task_id: str | None = None,
                 step_id: str | None = None, allow_fallback: bool = True) -> ChatResponse:
        """``allow_fallback``: if the chosen tier is unavailable (e.g. Claude's usage limit), answer with a
        local model and say so. Background tasks pass False and instead wait for the reset (UsageLimited)."""
        self.killswitch.check()
        need = self._apply_hybrid(need, request, task_id)
        try:
            return self._complete(need, request, purpose=purpose, task_id=task_id, step_id=step_id)
        except NoModelAvailable as exc:
            limited = self.router.gate.limited_until()
            if need.local_only or not (exc.unavailable or limited):
                raise
            if not allow_fallback:
                if limited:
                    raise UsageLimited("Claude is at its usage limit", limited) from exc
                raise
            local_need = Need(need.capability, min_quality=1, prefer="speed", local_only=True)
            try:
                r = self._complete(local_need, request, purpose=purpose, task_id=task_id, step_id=step_id)
            except NoModelAvailable:
                raise exc from None
            until = f" until about {time.strftime('%H:%M', time.localtime(limited))}" if limited else ""
            cloud_errors = [msg for key, msg in exc.reasons.items() if key.split("/")[0] in self.router.gate.provider_names()
                            and not msg.startswith(("lacks", "quality", "context", "would exceed", "request contains"))]
            detail = cloud_errors[0].removeprefix("unavailable: ")[:200] if cloud_errors else "it was unavailable"
            why = f"Claude is at its usage limit{until}" if limited else f"the cloud model failed: {detail}"
            note = f"Answered locally — {why}."
            self.audit.record("model.fallback", task_id=task_id, model=f"{r.provider}/{r.model}", reason=why)
            return replace(r, note=note)

    def _apply_hybrid(self, need: Need, request: ChatRequest, task_id: str | None) -> Need:
        if self.router.mode != "hybrid" or need.prefer != "auto" or need.local_only:
            return need
        level = self.triage(request, task_id) if need.capability == "chat" else "medium"
        if level == "simple":
            return replace(need, local_only=True, prefer="speed")
        if level == "medium":  # lightest cloud model that is clearly better than local (e.g. Haiku)
            return replace(need, min_quality=max(need.min_quality, 4), prefer="speed")
        return replace(need, min_quality=max(need.min_quality, 5), prefer="quality")

    def triage(self, request: ChatRequest, task_id: str | None = None) -> str:
        """Rate the latest user message SIMPLE / MEDIUM / HARD with a fast local model (never leaves the Mac)."""
        last = next((m.content for m in reversed(request.messages) if m.role == "user"), "")[:1500]
        word = ""
        try:
            r = self._complete(Need("classify", prefer="speed", local_only=True), ChatRequest((
                Message("system", TRIAGE_PROMPT, Category.SYSTEM_PROMPT),
                Message("user", last, Category.CONVERSATION)), max_tokens=4, temperature=0.0),
                purpose="triage", task_id=task_id, step_id=None)
            word = (r.text.strip().split() or [""])[0].strip(".:,*").upper()
        except (NoModelAvailable, ProviderError):
            pass
        level = {"SIMPLE": "simple", "MEDIUM": "medium", "HARD": "hard"}.get(word, "medium")
        self.audit.record("model.triage", task_id=task_id, level=level, raw=word[:20])
        return level

    def _complete(self, need: Need, request: ChatRequest, *, purpose: str, task_id: str | None,
                  step_id: str | None) -> ChatResponse:
        try:
            route = self.router.route(need, request)
        except NoModelAvailable as exc:
            self.audit.record("model.no_route", task_id=task_id, need=need.__dict__, reasons=exc.reasons)
            raise
        self.audit.record("model.route", task_id=task_id, need=need.__dict__, rationale=route.rationale,
                          candidates=[f"{c.provider}/{c.model}" for c in route.candidates],
                          excluded=route.rejected)
        failures: dict[str, str] = {}
        for cand in route.candidates[: self.max_attempts]:
            key = f"{cand.provider}/{cand.model}"
            try:
                if cand.location == "local":
                    self.killswitch.check()
                    response = self.router.local[cand.provider].chat(cand.model, request)
                    self.audit.record("model.local_call", task_id=task_id, model=key, purpose=purpose,
                                      chars=request.chars(), input_tokens=response.usage.input_tokens,
                                      output_tokens=response.usage.output_tokens,
                                      latency_s=round(response.latency_s, 3))
                else:
                    response = self.router.gate.send(cand.provider, cand.model, request, purpose=purpose,
                                                      task_id=task_id, step_id=step_id)
                return response
            except ApprovalRequired:
                raise
            except (ProviderError, EgressDenied) as exc:
                failures[key] = str(exc)
                self.audit.record("model.attempt_failed", task_id=task_id, model=key, error=str(exc),
                                  budget=isinstance(exc, BudgetExceeded))
        raise NoModelAvailable("every candidate model failed", {**route.rejected, **failures}, unavailable=True)
