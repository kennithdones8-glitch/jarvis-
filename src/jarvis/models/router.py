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

from dataclasses import dataclass, field
from typing import Iterable, Literal

from ..core.audit import AuditLog
from ..core.killswitch import KillSwitch
from ..core.tools import ApprovalRequired
from .egress import BudgetExceeded, EgressDenied, EgressGate
from .types import ChatRequest, ChatResponse, ModelInfo, Provider, ProviderError

CAPABILITIES = frozenset({"chat", "plan", "code", "summarize", "classify", "json", "extract"})


@dataclass(frozen=True)
class Need:
    capability: str = "chat"
    min_quality: int = 1
    prefer: Literal["quality", "speed"] = "quality"
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
    def __init__(self, message: str, reasons: dict[str, str]):
        super().__init__(message)
        self.reasons = reasons


class ModelRouter:
    def __init__(self, local: Iterable[Provider], gate: EgressGate):
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
                    reason = unavailable_reason or "model not installed/available"
                elif location == "cloud" and not self.gate.budget.allows(self.gate.budget.estimate(info, request)):
                    reason = "would exceed budget"
                if reason:
                    rejected[key] = reason
                    continue
                # Local-first: any local model that meets the need outranks every cloud model.
                primary, secondary = (info.quality, info.speed) if need.prefer == "quality" else (info.speed, info.quality)
                score = (100 if location == "local" else 0) + primary * 10 + secondary
                ok.append(Candidate(name, mid, location, info, score))

        if not ok:
            raise NoModelAvailable("no approved model satisfies this request", rejected)
        ok.sort(key=lambda c: c.score, reverse=True)
        return Route(tuple(ok), rejected)


class ModelService:
    def __init__(self, router: ModelRouter, audit: AuditLog, killswitch: KillSwitch, *, max_attempts: int = 3):
        self.router = router
        self.audit = audit
        self.killswitch = killswitch
        self.max_attempts = max_attempts

    def complete(self, need: Need, request: ChatRequest, *, purpose: str, task_id: str | None = None,
                 step_id: str | None = None) -> ChatResponse:
        self.killswitch.check()
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
        raise NoModelAvailable("every candidate model failed", {**route.rejected, **failures})
