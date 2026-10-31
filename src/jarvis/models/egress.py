"""Egress gate: the only path by which content can reach a cloud model.

The gate sits below the orchestrator and holds the cloud provider objects itself; callers
pass a provider *name*. For every send it enforces, in order:

  1. emergency stop
  2. provider is configured and enabled
  3. no local-only data in the request
  4. no secret-looking content in the request
  5. budget guard (default monthly limit: $0)
  6. privacy authorisation: every PRIVATE data category needs either a standing grant for
     (category, provider) or a single-use approval bound to this exact request
  7. emergency stop again, then send, then record cost and audit

Sensitivity defaults are fixed in code; configuration can only make categories stricter.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from ..core.approvals import Approvals
from ..core.audit import AuditLog
from ..core.db import Database
from ..core.killswitch import KillSwitch
from ..core.permissions import Decision, Effect, Tier
from ..core.redact import redact_text
from ..core.tools import ApprovalRequired
from ..core.util import canonical_json, new_id, now_iso, sha256_hex
from .types import Category, ChatRequest, ChatResponse, Message, ModelInfo, Provider, ProviderError, Sensitivity

EGRESS_TOOL = "egress"

DEFAULT_SENSITIVITY: dict[Category, Sensitivity] = {
    Category.SYSTEM_PROMPT: Sensitivity.PUBLIC,
    Category.WEB_CONTENT: Sensitivity.PUBLIC,
    Category.CONVERSATION: Sensitivity.PRIVATE,
    Category.FILE_CONTENT: Sensitivity.PRIVATE,
    Category.MEMORY: Sensitivity.PRIVATE,
    Category.PROJECT: Sensitivity.PRIVATE,
    Category.SCREENSHOT: Sensitivity.PRIVATE,
}


class EgressDenied(RuntimeError):
    pass


class BudgetExceeded(EgressDenied):
    pass


class SensitivityPolicy:
    def __init__(self, *, local_only: Iterable[str] = (), private: Iterable[str] = ()):
        self.levels = dict(DEFAULT_SENSITIVITY)
        for name in private:
            cat = Category(name)
            self.levels[cat] = max(self.levels[cat], Sensitivity.PRIVATE)
        for name in local_only:
            self.levels[Category(name)] = Sensitivity.LOCAL_ONLY

    def of(self, message: Message) -> Sensitivity:
        return Sensitivity.LOCAL_ONLY if message.local_only else self.levels[message.category]

    def has_local_only(self, request: ChatRequest) -> bool:
        return any(self.of(m) is Sensitivity.LOCAL_ONLY for m in request.messages)


class BudgetGuard:
    def __init__(self, db: Database, *, monthly_limit_usd: float = 0.0):
        if monthly_limit_usd < 0:
            raise ValueError("budget cannot be negative")
        self.db = db
        self.monthly_limit_usd = monthly_limit_usd

    @staticmethod
    def estimate(info: ModelInfo, request: ChatRequest) -> float:
        return (request.estimated_input_tokens() * info.input_cost_per_mtok
                + request.max_tokens * info.output_cost_per_mtok) / 1_000_000

    @staticmethod
    def actual(info: ModelInfo, response: ChatResponse) -> float:
        return (response.usage.input_tokens * info.input_cost_per_mtok
                + response.usage.output_tokens * info.output_cost_per_mtok) / 1_000_000

    def spent_this_month(self) -> float:
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        row = self.db.one("SELECT COALESCE(SUM(cost_usd), 0) FROM model_usage WHERE ts LIKE ?", (f"{month}%",))
        return float(row[0])

    def allows(self, estimate: float) -> bool:
        return estimate <= 0 or self.spent_this_month() + estimate <= self.monthly_limit_usd

    def check(self, estimate: float) -> None:
        if not self.allows(estimate):
            raise BudgetExceeded(
                f"estimated ${estimate:.4f} would exceed the monthly limit of ${self.monthly_limit_usd:.2f}"
                f" (spent ${self.spent_this_month():.4f})"
            )

    def usage_since(self, provider: str, seconds: float) -> dict[str, int]:
        since = datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() - seconds, timezone.utc).isoformat(
            timespec="microseconds")
        row = self.db.one("SELECT COUNT(*), COALESCE(SUM(input_tokens + output_tokens), 0) FROM model_usage "
                          "WHERE provider = ? AND ts >= ?", (provider, since))
        return {"calls": int(row[0]), "tokens": int(row[1])}

    def record(self, response: ChatResponse, cost: float, task_id: str | None) -> None:
        with self.db.tx() as conn:
            conn.execute(
                "INSERT INTO model_usage (ts, provider, model, task_id, input_tokens, output_tokens, cost_usd)"
                " VALUES (?,?,?,?,?,?,?)",
                (now_iso(), response.provider, response.model, task_id, response.usage.input_tokens,
                 response.usage.output_tokens, cost),
            )


class EgressGrants:
    """Standing authorisations: 'category X may be sent to provider Y' (user-created, revocable)."""

    def __init__(self, db: Database, audit: AuditLog):
        self.db = db
        self.audit = audit

    def grant(self, *, category: str, provider: str, by: str, expires_at: str | None = None) -> str:
        if not by.startswith("user"):
            raise PermissionError("only a user may create an egress grant")
        Category(category)
        gid = new_id("grant")
        with self.db.tx() as conn:
            conn.execute("INSERT INTO egress_grants (id, category, provider, created_at, created_by, expires_at)"
                         " VALUES (?,?,?,?,?,?)", (gid, category, provider, now_iso(), by, expires_at))
            self.audit.record("egress.grant_created", actor=by, grant_id=gid, category=category, provider=provider,
                              expires_at=expires_at)
        return gid

    def revoke(self, grant_id: str, *, by: str) -> None:
        if not by.startswith("user"):
            raise PermissionError("only a user may revoke an egress grant")
        with self.db.tx() as conn:
            cur = conn.execute("UPDATE egress_grants SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
                               (now_iso(), grant_id))
            if cur.rowcount != 1:
                raise KeyError(grant_id)
            self.audit.record("egress.grant_revoked", actor=by, grant_id=grant_id)

    def active(self, category: str, provider: str) -> bool:
        row = self.db.one(
            "SELECT 1 FROM egress_grants WHERE category = ? AND provider = ? AND revoked_at IS NULL"
            " AND (expires_at IS NULL OR expires_at > ?)", (category, provider, now_iso()))
        return row is not None

    def list(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.query("SELECT * FROM egress_grants ORDER BY created_at")]


@dataclass(frozen=True)
class ProviderSummary:
    name: str
    location: str
    models: dict[str, ModelInfo]
    data_use_note: str


class EgressGate:
    def __init__(self, db: Database, audit: AuditLog, approvals: Approvals, killswitch: KillSwitch,
                 providers: Iterable[Provider], *, sensitivity: SensitivityPolicy, budget: BudgetGuard):
        self._providers = {p.name: p for p in providers}
        if any(p.location != "cloud" for p in self._providers.values()):
            raise ValueError("the egress gate only manages cloud providers")
        self.audit = audit
        self.approvals = approvals
        self.killswitch = killswitch
        self.sensitivity = sensitivity
        self.budget = budget
        self.grants = EgressGrants(db, audit)

    def summaries(self) -> list[ProviderSummary]:
        return [ProviderSummary(p.name, p.location, dict(p.models), p.data_use_note) for p in self._providers.values()]

    def usage_summary(self) -> list[dict[str, Any]]:
        """Per cloud provider: calls and tokens in the last 5 hours, and any known limit."""
        out = []
        for p in self._providers.values():
            limited = getattr(p, "limited_until", None)
            out.append({"provider": p.name, **self.budget.usage_since(p.name, 5 * 3600),
                        "limited_until": limited if limited and limited > datetime.now(timezone.utc).timestamp() else None})
        return out

    def limited_until(self) -> float | None:
        known = [u["limited_until"] for u in self.usage_summary() if u["limited_until"]]
        return max(known) if known else None

    def available_models(self, provider: str) -> set[str]:
        return self._providers[provider].available_models()

    def send(self, provider: str, model: str, request: ChatRequest, *, purpose: str,
             task_id: str | None = None, step_id: str | None = None) -> ChatResponse:
        self.killswitch.check()
        p = self._providers.get(provider)
        info = p.models.get(model) if p else None
        if p is None or info is None:
            self._deny(task_id, provider, model, "provider or model is not enabled")

        levels = [(m.category, self.sensitivity.of(m)) for m in request.messages]
        if any(level is Sensitivity.LOCAL_ONLY for _, level in levels):
            self._deny(task_id, provider, model, "request contains local-only data")
        if any(redact_text(m.content) != m.content for m in request.messages):
            self._deny(task_id, provider, model, "request contains secret-looking content")

        estimate = self.budget.estimate(info, request)
        try:
            self.budget.check(estimate)
        except BudgetExceeded as exc:
            self.audit.record("egress.denied", task_id=task_id, provider=provider, model=model, reason=str(exc))
            raise

        digest = sha256_hex(canonical_json({
            "provider": provider, "model": model, "max_tokens": request.max_tokens, "json": request.json_mode,
            "messages": [[m.role, m.category.value, m.content] for m in request.messages],
        }))
        private = sorted({c.value for c, level in levels if level is Sensitivity.PRIVATE})
        ungranted = [c for c in private if not self.grants.active(c, provider)]
        approval_id = None
        if ungranted:
            resource = ",".join(ungranted)
            if self.approvals.is_rejected(task_id=task_id, tool=EGRESS_TOOL, action=provider, resource=resource):
                self._deny(task_id, provider, model, "you rejected sending this data to this provider in this task")
            approval_id = self.approvals.find_usable(task_id=task_id, tool=EGRESS_TOOL, action=provider,
                                                     resource=resource, digest=digest)
            if approval_id is None:
                decision = Decision(Effect.CONFIRM, Tier.EXTERNAL, "private data would leave this Mac",
                                    resource=resource)
                aid = self.approvals.request(
                    task_id=task_id, step_id=step_id, tool=EGRESS_TOOL, action=provider, digest=digest,
                    decision=decision, summary=self._summary(p, model, request, ungranted, purpose, estimate),
                )
                raise ApprovalRequired(aid, decision)

        self.killswitch.check()
        if approval_id:
            self.approvals.consume(approval_id)
        self.audit.record("egress.send", task_id=task_id, provider=provider, model=model, purpose=purpose,
                          categories=sorted({c.value for c, _ in levels}), chars=request.chars(),
                          request_sha256=digest, estimated_cost_usd=estimate, approval_id=approval_id)
        try:
            response = p.chat(model, request)
        except ProviderError as exc:
            self.audit.record("egress.error", task_id=task_id, provider=provider, model=model, error=str(exc),
                              retryable=exc.retryable)
            raise
        cost = self.budget.actual(info, response)
        self.budget.record(response, cost, task_id)
        self.audit.record("egress.received", task_id=task_id, provider=provider, model=model,
                          input_tokens=response.usage.input_tokens, output_tokens=response.usage.output_tokens,
                          cost_usd=cost, latency_s=round(response.latency_s, 3))
        return response

    def _deny(self, task_id: str | None, provider: str, model: str, reason: str) -> None:
        self.audit.record("egress.denied", task_id=task_id, provider=provider, model=model, reason=reason)
        raise EgressDenied(reason)

    @staticmethod
    def _summary(p: Provider, model: str, request: ChatRequest, categories: list[str], purpose: str,
                 estimate: float) -> str:
        cost = "free" if estimate <= 0 else f"est. ${estimate:.4f}"
        return (f"Send {request.chars():,} characters of {', '.join(categories)} to {p.name}/{model} "
                f"({cost}) — purpose: {purpose}. Provider data use: {p.data_use_note}.")
