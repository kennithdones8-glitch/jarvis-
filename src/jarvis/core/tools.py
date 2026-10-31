"""Tool registry and the tool gateway.

``ToolGateway.invoke`` is the single path from the orchestrator (or anything else) to a
tool handler. Every call: checks the emergency stop, looks up the declared action, asks
the permission engine, enforces approvals, re-checks the stop, runs the handler with a
timeout and output limit, and audits each stage with redacted arguments.
"""

from __future__ import annotations

import concurrent.futures as cf
from dataclasses import dataclass, field
from typing import Any, Callable

from .approvals import Approvals, args_hash
from .audit import AuditLog
from .killswitch import EmergencyStop, KillSwitch
from .permissions import Decision, Effect, PermissionEngine, ResourceKind, Tier
from .util import canonical_json, sha256_hex

RECONCILE_DONE, RECONCILE_NOT_DONE, RECONCILE_UNKNOWN = "done", "not_done", "unknown"
AUDIT_INLINE_CHARS = 256


def summarize_for_audit(value: Any) -> Any:
    """Keep the audit trail useful without copying bulk content (file bodies, page text) into it."""
    if isinstance(value, str) and len(value) > AUDIT_INLINE_CHARS:
        return {"chars": len(value), "sha256": sha256_hex(value), "head": value[:80]}
    if isinstance(value, dict):
        return {k: summarize_for_audit(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [summarize_for_audit(v) for v in value]
    return value


@dataclass(frozen=True)
class CallContext:
    task_id: str | None
    step_id: str | None
    op_id: str | None
    resource: str | None


@dataclass(frozen=True)
class ActionSpec:
    tier: Tier
    resource_arg: str | None = None
    resource_kind: ResourceKind | None = None
    idempotent: bool = True
    timeout_s: float = 30.0
    max_output_bytes: int = 1_000_000
    # Given (args, op_id), report whether a possibly-interrupted call actually took effect.
    reconcile: Callable[[dict[str, Any], str], str] | None = None


Handler = Callable[[str, dict[str, Any], CallContext], Any]


@dataclass
class ToolSpec:
    name: str
    description: str
    actions: dict[str, ActionSpec]
    handler: Handler = field(repr=False)


class ToolError(RuntimeError):
    """A tool failed. ``retryable``: safe to try again. ``outcome_unknown``: it may have taken effect."""

    def __init__(self, message: str, *, retryable: bool = False, outcome_unknown: bool = False,
                 retry_after: float | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.outcome_unknown = outcome_unknown
        # Unix time before which retrying is pointless (e.g. a usage limit). The engine waits without
        # spending an attempt, because nothing happened.
        self.retry_after = retry_after


class ToolTimeout(ToolError):
    def __init__(self, message: str):
        super().__init__(message, retryable=True, outcome_unknown=True)


class PermissionDenied(RuntimeError):
    def __init__(self, message: str, decision: Decision | None = None):
        super().__init__(message)
        self.decision = decision


class ApprovalRequired(RuntimeError):
    def __init__(self, approval_id: str, decision: Decision):
        super().__init__(f"approval required ({approval_id}): {decision.reason}")
        self.approval_id = approval_id
        self.decision = decision


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"tool {spec.name!r} already registered")
        for name, act in spec.actions.items():
            if act.resource_kind is not None and act.resource_arg is None:
                raise ValueError(f"{spec.name}.{name}: resource_kind requires resource_arg")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def action(self, tool: str, action: str) -> ActionSpec | None:
        spec = self._tools.get(tool)
        return spec.actions.get(action) if spec else None

    def names(self) -> list[str]:
        return sorted(self._tools)


class ToolGateway:
    def __init__(
        self,
        registry: ToolRegistry,
        permissions: PermissionEngine,
        approvals: Approvals,
        audit: AuditLog,
        killswitch: KillSwitch,
        *,
        max_workers: int = 8,
    ):
        self.registry = registry
        self.permissions = permissions
        self.approvals = approvals
        self.audit = audit
        self.killswitch = killswitch
        self._pool = cf.ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="jarvis-tool")

    def invoke(
        self,
        tool: str,
        action: str,
        args: dict[str, Any],
        *,
        task_id: str | None = None,
        step_id: str | None = None,
        op_id: str | None = None,
        summary: str | None = None,
    ) -> Any:
        self.killswitch.check()
        spec = self.registry.get(tool)
        act = spec.actions.get(action) if spec else None
        if spec is None or act is None:
            self.audit.record("permission.denied", task_id=task_id, tool=tool, action=action, reason="unknown tool or action")
            raise PermissionDenied(f"unknown tool or action: {tool}.{action}")
        if not isinstance(args, dict):
            raise PermissionDenied("tool arguments must be an object")

        resource = args.get(act.resource_arg) if act.resource_arg else None
        decision = self.permissions.evaluate(
            tool=tool, action=action, tier=act.tier, resource_kind=act.resource_kind, resource=resource
        )
        digest = args_hash(tool, action, args)
        self.audit.record(
            "permission.check", task_id=task_id, step_id=step_id, tool=tool, action=action,
            resource=decision.resource, tier=int(decision.tier), effect=decision.effect.value,
            rule=decision.rule_id, reason=decision.reason,
        )
        if decision.effect is Effect.DENY:
            raise PermissionDenied(decision.reason, decision)

        # A rejection blocks any further mutation of that resource in the task, even via a tool
        # whose standing policy would otherwise allow it.
        if decision.tier > Tier.READ and self.approvals.is_rejected(
            task_id=task_id, tool=tool, action=action, resource=decision.resource
        ):
            self.audit.record("permission.denied", task_id=task_id, tool=tool, action=action,
                              resource=decision.resource, reason="previously rejected in this task")
            raise PermissionDenied("you rejected an action on this resource earlier in this task", decision)

        approval_id = None
        if decision.effect is Effect.CONFIRM:
            self.killswitch.check()
            approval_id = self.approvals.claim(
                task_id=task_id, tool=tool, action=action, resource=decision.resource, digest=digest
            )
            if approval_id is None:
                aid = self.approvals.request(
                    task_id=task_id, step_id=step_id, tool=tool, action=action, digest=digest, decision=decision,
                    summary=summary or f"{tool}.{action} on {decision.resource or '(no resource)'}",
                )
                raise ApprovalRequired(aid, decision)

        try:
            self.killswitch.check()
        except EmergencyStop:
            if approval_id:
                self.approvals.restore(approval_id)  # not used after all; still valid when you resume
            raise

        ctx = CallContext(task_id=task_id, step_id=step_id, op_id=op_id, resource=decision.resource)
        self.audit.record("tool.start", task_id=task_id, step_id=step_id, op_id=op_id, tool=tool, action=action,
                          args=summarize_for_audit(args))
        future = self._pool.submit(spec.handler, action, args, ctx)
        try:
            result = future.result(timeout=act.timeout_s)
        except cf.TimeoutError:
            # The worker thread cannot be killed; tools doing slow I/O must enforce their own deadlines.
            self.audit.record("tool.timeout", task_id=task_id, step_id=step_id, op_id=op_id, timeout_s=act.timeout_s)
            raise ToolTimeout(f"{tool}.{action} timed out after {act.timeout_s}s") from None
        except (ApprovalRequired, EmergencyStop):
            raise  # nothing left the machine / the stop interrupted it; the task pauses either way
        except ToolError as exc:
            self.audit.record("tool.error", task_id=task_id, step_id=step_id, op_id=op_id, error=str(exc),
                              retryable=exc.retryable, outcome_unknown=exc.outcome_unknown)
            raise
        except Exception as exc:
            self.audit.record("tool.error", task_id=task_id, step_id=step_id, op_id=op_id,
                              error=f"{type(exc).__name__}: {exc}", outcome_unknown=True)
            raise ToolError(f"{type(exc).__name__}: {exc}", outcome_unknown=True) from exc

        encoded = canonical_json(result)
        if len(encoded.encode("utf-8")) > act.max_output_bytes:
            self.audit.record("tool.error", task_id=task_id, step_id=step_id, op_id=op_id, error="output limit exceeded")
            raise ToolError(f"{tool}.{action} output exceeded {act.max_output_bytes} bytes")
        self.audit.record("tool.result", task_id=task_id, step_id=step_id, op_id=op_id,
                          result=summarize_for_audit(result))
        return result

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
