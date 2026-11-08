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

import re
import time
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Literal

from ..core.audit import AuditLog
from ..core.killswitch import KillSwitch
from ..core.tools import ApprovalRequired
from .egress import BudgetExceeded, EgressDenied, EgressGate
from .providers import Cancelled
from .types import Category, ChatRequest, ChatResponse, Message, ModelInfo, Provider, ProviderError, UsageLimited

# "reasoning": a model kept for maths, logic and code only (owner's choice, 0.19.1). It is never picked for everyday
# chat, planning or tools, so a big slow model can be installed without slowing everything else down.
CAPABILITIES = frozenset({"chat", "plan", "code", "summarize", "classify", "json", "extract", "research", "reasoning"})


@dataclass(frozen=True)
class Need:
    capability: str = "chat"
    min_quality: int = 1
    # "auto": quality when routing mode is "best", speed when it is "local_first".
    prefer: Literal["quality", "speed", "auto"] = "quality"
    local_only: bool = False
    # The caller chose speed on purpose (the owner's Quick mode): no automatic upgrade to a stronger local model.
    keep_speed: bool = False
    # Set by ModelService when the question is maths, logic or code that will be answered on this Mac: try a local
    # "reasoning" model first, if one is installed, then the usual choice.
    reasoning: bool = False
    # The answer must read JARVIS's worked-out facts or combine several memories: where routing would pick the
    # fastest local model ("auto" in local-first, or a "simple" chat in hybrid), pick the strongest local one
    # instead. It never moves an answer to the cloud. Real failures (hard set, smarter-v2): the 3B dropped a
    # reminder JARVIS had listed as due today, and couldn't link two memories that were both in front of it.
    careful: bool = False

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


# Signs a request needs the strongest model, whatever a small model thinks ("no downgrades").
HARD_SIGNALS = re.compile(
    r"```|\b(prove|proof|derive|debug|refactor|algorithm|complexity|step[- ]by[- ]step|trade-?offs?|analy[sz]e|"
    r"analysis|strategy|architecture|contract|legal|lawsuit|medical|diagnos\w*|tax(es)?|invest\w*|mortgage|"
    r"compare and|pros and cons)\b", re.I)


def hard_signals(text: str) -> bool:
    """Deterministic: code, reasoning words, high-stakes topics, several questions, a puzzle with several conditions,
    or a long request."""
    from ..orchestrator.answer_checks import is_puzzle  # plain regexes; no import cycle

    return bool(HARD_SIGNALS.search(text)) or text.count("?") >= 3 or len(text) > 1200 or is_puzzle(text)


# Hard set (smarter-v2): "what time does it arrive?" and "on which weekday ...?" weren't seen as maths, so the
# 14B never got them. Still needs two or more numbers, so "what time is my dentist?" isn't caught.
WORD_PROBLEM = re.compile(r"\b(how (many|much|long|far|old)|calculate|work out|what is the (total|difference|average)"
                          r"|what time (does|do|will|is|would)|(which|what) (week)?day|(which|what) date|when (does|will))\b",
                          re.I)
NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


def needs_reasoning(text: str) -> bool:
    """Work a small local model often gets wrong: anything ``hard_signals`` flags, a word problem with numbers, or a
    request to write code. Used only to pick the *stronger local* model; it never sends anything to the cloud."""
    from ..codecheck import wants_code  # plain regexes; no import cycle

    return (hard_signals(text) or wants_code(text)
            or (len(NUMBER.findall(text)) >= 2 and bool(WORD_PROBLEM.search(text))))


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
                prefer = need.prefer if need.prefer != "auto" else (
                    "speed" if self.mode == "local_first" and not need.careful else "quality")
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

    def research(self, request: ChatRequest, *, purpose: str = "web research", deep: bool = False,
                 task_id: str | None = None, step_id: str | None = None) -> ChatResponse:
        """Answer using live web search and page reading (cloud only — local models can't browse).
        Never falls back to a local model: an answer without the web would be a different thing."""
        self.killswitch.check()
        need = Need("research", min_quality=5 if deep else 4, prefer="quality" if deep else "speed")
        try:
            return self._complete(need, request, purpose=purpose, task_id=task_id, step_id=step_id, op="research")
        except NoModelAvailable as exc:
            if limited := self.router.gate.limited_until():
                raise UsageLimited("Claude is at its usage limit", limited) from exc
            raise

    def complete(self, need: Need, request: ChatRequest, *, purpose: str, task_id: str | None = None,
                 step_id: str | None = None, allow_fallback: bool = True, on_token=None,
                 level: str | None = None, on_event=None) -> ChatResponse:
        """``allow_fallback``: if the chosen tier is unavailable (e.g. Claude's usage limit), answer with a
        local model and say so. Background tasks pass False and instead wait for the reset (UsageLimited)."""
        self.killswitch.check()
        need = self._apply_hybrid(need, request, task_id, level)
        need = self._strong_local_for_reasoning(need, request, task_id)
        if need.reasoning:
            r = self._try_reasoning_model(need, request, purpose=purpose, task_id=task_id, step_id=step_id,
                                          on_token=on_token, on_event=on_event)
            if r is not None:
                return r
        try:
            return self._complete(need, request, purpose=purpose, task_id=task_id, step_id=step_id, on_token=on_token,
                                  on_event=on_event)
        except NoModelAvailable as exc:
            limited = self.router.gate.limited_until()
            if need.local_only or not (exc.unavailable or limited):
                raise
            if not allow_fallback:
                if limited:
                    raise UsageLimited("Claude is at its usage limit", limited) from exc
                raise
            local_need = self._strong_local_for_reasoning(
                Need(need.capability, min_quality=1, prefer="speed", local_only=True, keep_speed=need.keep_speed),
                request, task_id)
            r = None
            if local_need.reasoning:  # Claude unavailable for a maths/code question: the best local answer, not the fastest
                r = self._try_reasoning_model(local_need, request, purpose=purpose, task_id=task_id, step_id=step_id,
                                              on_token=on_token, on_event=on_event)
            try:
                r = r or self._complete(local_need, request, purpose=purpose, task_id=task_id, step_id=step_id,
                                   on_token=on_token, on_event=on_event)
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

    def warm_local(self) -> dict[str, Any]:
        """Load every installed local model into memory, fastest first (owner's choice, 0.19.1): the first question
        after JARVIS starts no longer waits 10-30 s for a model to load. Nothing is generated or sent anywhere; an
        engaged emergency stop skips it. Recorded in the audit log (model names and seconds only)."""
        if self.killswitch.engaged():
            return {}
        done: dict[str, Any] = {}
        for provider in self.router.local.values():
            warm = getattr(provider, "warm", None)
            if warm is None:
                continue
            try:
                installed = provider.available_models()
            except ProviderError as exc:
                done[provider.name] = f"unavailable: {str(exc)[:120]}"
                continue
            # A reasoning-only model is big and only for maths/code: loaded when first asked, not at start, so it
            # doesn't take 9 GB of memory on a day it isn't needed.
            everyday = [m for m in installed if provider.models[m].capabilities != frozenset({"reasoning"})]
            for mid in sorted(everyday, key=lambda m: -provider.models[m].speed):
                if self.killswitch.engaged():
                    break
                try:
                    done[f"{provider.name}/{mid}"] = round(warm(mid), 1)
                except ProviderError as exc:
                    done[f"{provider.name}/{mid}"] = f"failed: {str(exc)[:120]}"
        self.audit.record("models.warmed", models=done)
        return done

    def _strong_local_for_reasoning(self, need: Need, request: ChatRequest, task_id: str | None) -> Need:
        """When a chat answer will come from this Mac anyway (local_first, or kept local), maths, logic and code go to
        the strongest local model instead of the fastest (owner's choice, 0.18.3): slower, but right more often. Only
        the choice between local models changes; whether anything may go to the cloud never does."""
        if need.capability != "chat" or need.prefer == "quality" or need.keep_speed:
            return need
        if not (need.local_only or self.router.mode == "local_first"):
            return need
        last = next((m.content for m in reversed(request.messages) if m.role == "user"), "")
        if not needs_reasoning(last[:4000]):
            return need
        self.audit.record("model.reasoning_local", task_id=task_id)
        return replace(need, prefer="quality", reasoning=True)

    def chat_stays_local(self, message: str, *, local_only: bool = False, level: str | None = None) -> bool:
        """Whether a "balanced"/"deep" chat is sure to be answered on this Mac: asked to, no cloud model configured,
        or hybrid routing with the goal reader's "simple" rating (the same rule ``_apply_hybrid`` applies). Used to
        decide whether extra local-only context may be added; if it's ever wrong, that context still can't leave
        (it is marked local_only, so routing keeps the request here)."""
        if local_only or not self.router.gate.summaries():
            return True
        return self.router.mode == "hybrid" and level == "simple" and not hard_signals(message)

    def has_local(self, capability: str) -> bool:
        """Whether any configured local model has ``capability`` (installed or not: routing checks that)."""
        return any(capability in info.capabilities for p in self.router.local.values() for info in p.models.values())

    def _try_reasoning_model(self, need: Need, request: ChatRequest, **kw) -> ChatResponse | None:
        """A maths/logic/code question kept on this Mac goes to a local "reasoning" model when one is installed.
        None (and the usual local choice is used) when there is none, it isn't installed, or it fails. Only the
        choice between local models changes: this never sends anything anywhere."""
        if not self.has_local("reasoning"):
            return None
        try:
            return self._complete(replace(need, capability="reasoning", local_only=True, min_quality=1), request, **kw)
        except NoModelAvailable as exc:
            self.audit.record("model.reasoning_unavailable", task_id=kw.get("task_id"),
                              reasons={k: v[:120] for k, v in list(exc.reasons.items())[:6]})
            return None

    def _apply_hybrid(self, need: Need, request: ChatRequest, task_id: str | None, level: str | None = None) -> Need:
        """``level``: already rated by the caller (e.g. the goal reader), so no second local call."""
        if self.router.mode != "hybrid" or need.prefer != "auto" or need.local_only:
            return need
        if need.capability != "chat":
            level = "medium"
        elif level not in ("simple", "medium", "hard"):
            level = self.triage(request, task_id)
        else:
            last = next((m.content for m in reversed(request.messages) if m.role == "user"), "")
            if hard_signals(last):
                level = "hard"
            self.audit.record("model.triage", task_id=task_id, level=level, raw="goal reader")
        if level == "simple":
            return replace(need, local_only=True, prefer="quality" if need.careful else "speed")
        if level == "medium":  # lightest cloud model that is clearly better than local (e.g. Haiku)
            return replace(need, min_quality=max(need.min_quality, 4), prefer="speed")
        return replace(need, min_quality=max(need.min_quality, 5), prefer="quality")

    def triage(self, request: ChatRequest, task_id: str | None = None) -> str:
        """Rate the latest user message SIMPLE / MEDIUM / HARD with a fast local model (never leaves the Mac)."""
        last = next((m.content for m in reversed(request.messages) if m.role == "user"), "")[:1500]
        if hard_signals(last):  # no downgrades: obvious hard work never depends on a small model's guess
            self.audit.record("model.triage", task_id=task_id, level="hard", raw="signals")
            return "hard"
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
                  step_id: str | None, op: str = "chat", on_token=None, on_event=None) -> ChatResponse:
        """``on_token``: show the reply as it's written, for providers that can (display only).
        ``on_event(dict)``: told which model is about to answer, before each attempt, so a viewer can show it
        (and discard words from an attempt that failed). Display only; never changes routing."""
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
            if on_event is not None:
                streams = (bool(getattr(self.router.local.get(cand.provider), "streams", False))
                           if cand.location == "local" else self.router.gate.can_stream(cand.provider))
                on_event({"stage": "generating", "model": key, "location": cand.location,
                          "streams": on_token is not None and op != "research" and streams})
            try:
                if cand.location == "local":
                    self.killswitch.check()
                    provider = self.router.local[cand.provider]
                    if on_token is not None and getattr(provider, "streams", False):
                        response = provider.chat(cand.model, request, on_token=on_token)
                    else:
                        response = provider.chat(cand.model, request)
                    self.audit.record("model.local_call", task_id=task_id, model=key, purpose=purpose,
                                      chars=request.chars(), input_tokens=response.usage.input_tokens,
                                      output_tokens=response.usage.output_tokens,
                                      latency_s=round(response.latency_s, 3))
                else:
                    response = self.router.gate.send(cand.provider, cand.model, request, purpose=purpose,
                                                      task_id=task_id, step_id=step_id, research=op == "research",
                                                      on_token=on_token if op != "research" else None)
                return response
            except ApprovalRequired:
                raise
            except Cancelled:
                self.killswitch.check()  # raises EmergencyStop if that's why we were cancelled
                raise
            except (ProviderError, EgressDenied) as exc:
                failures[key] = str(exc)
                self.audit.record("model.attempt_failed", task_id=task_id, model=key, error=str(exc),
                                  budget=isinstance(exc, BudgetExceeded))
        raise NoModelAvailable("every candidate model failed", {**route.rejected, **failures}, unavailable=True)
