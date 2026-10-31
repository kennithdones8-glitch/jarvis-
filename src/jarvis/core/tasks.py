"""Persistent task engine.

- Explicit task state machine; every transition is versioned and audited.
- Write-ahead execution: a step is durably marked ``started`` (with an operation id)
  *before* its tool runs, so after a crash we know which calls may have happened.
- Checkpoint after every completed step.
- Bounded retries with exponential backoff, only when safe.
- Recovery never blindly re-runs a non-idempotent step: it reconciles (if the tool can)
  or marks the step ``uncertain`` and blocks the task for a user decision.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Callable, Iterable

from .audit import AuditLog
from .db import Database
from .killswitch import EmergencyStop, KillSwitch
from .tools import (
    RECONCILE_DONE,
    RECONCILE_NOT_DONE,
    ApprovalRequired,
    PermissionDenied,
    ToolError,
    ToolGateway,
)
from .util import canonical_json, new_id, now_iso


class TaskState(StrEnum):
    QUEUED = "queued"
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    RUNNING = "running"
    PAUSED = "paused"
    BLOCKED = "blocked"
    RECOVERING = "recovering"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepState(StrEnum):
    PENDING = "pending"
    STARTED = "started"
    DONE = "done"
    FAILED = "failed"
    UNCERTAIN = "uncertain"
    SKIPPED = "skipped"


S = TaskState
TERMINAL = frozenset({S.COMPLETED, S.FAILED, S.CANCELLED})
TRANSITIONS: dict[TaskState, frozenset[TaskState]] = {
    S.QUEUED: frozenset({S.PLANNING, S.RUNNING, S.PAUSED, S.CANCELLED}),
    S.PLANNING: frozenset({S.QUEUED, S.RUNNING, S.AWAITING_APPROVAL, S.BLOCKED, S.PAUSED, S.RECOVERING, S.FAILED, S.CANCELLED}),
    S.AWAITING_APPROVAL: frozenset({S.RUNNING, S.PAUSED, S.FAILED, S.CANCELLED}),
    S.RUNNING: frozenset({S.VERIFYING, S.AWAITING_APPROVAL, S.PAUSED, S.BLOCKED, S.RECOVERING, S.FAILED, S.CANCELLED}),
    S.PAUSED: frozenset({S.QUEUED, S.CANCELLED}),
    S.BLOCKED: frozenset({S.QUEUED, S.FAILED, S.CANCELLED}),
    S.RECOVERING: frozenset({S.QUEUED, S.BLOCKED, S.FAILED, S.CANCELLED}),
    S.VERIFYING: frozenset({S.COMPLETED, S.FAILED, S.RUNNING, S.PAUSED, S.BLOCKED, S.RECOVERING, S.CANCELLED}),
    S.COMPLETED: frozenset(),
    S.FAILED: frozenset(),
    S.CANCELLED: frozenset(),
}
# States in which a crashed process may have left work half-done.
INTERRUPTIBLE = (S.PLANNING, S.RUNNING, S.VERIFYING, S.RECOVERING)


class InvalidTransition(RuntimeError):
    pass


class ConcurrentModification(RuntimeError):
    pass


@dataclass
class StepSpec:
    description: str
    tool: str
    action: str
    args: dict[str, Any] = field(default_factory=dict)
    depends_on: list[int] = field(default_factory=list)
    max_attempts: int = 3


@dataclass(frozen=True)
class Verification:
    ok: bool
    evidence: dict[str, Any]


Verifier = Callable[[dict[str, Any], list[dict[str, Any]]], Verification]


def all_steps_done(task: dict[str, Any], steps: list[dict[str, Any]]) -> Verification:
    missing = [s["idx"] for s in steps if s["state"] not in (StepState.DONE, StepState.SKIPPED)]
    return Verification(not missing, {"steps": len(steps), "incomplete_steps": missing})


_JSON_TASK = ("context", "result")
_JSON_STEP = ("args", "depends_on", "result")


def _decode(row: Any, json_fields: Iterable[str]) -> dict[str, Any]:
    out = dict(row)
    for f in json_fields:
        if out.get(f) is not None:
            out[f] = json.loads(out[f])
    return out


class TaskStore:
    def __init__(self, db: Database, audit: AuditLog):
        self.db = db
        self.audit = audit

    # ---- tasks -------------------------------------------------------------------------
    def create(
        self,
        request: str,
        *,
        goal: str | None = None,
        steps: Iterable[StepSpec] = (),
        priority: int = 50,
        context: dict[str, Any] | None = None,
        actor: str = "user",
    ) -> str:
        steps = list(steps)
        tid = new_id("task")
        ts = now_iso()
        with self.db.tx() as conn:
            conn.execute(
                "INSERT INTO tasks (id, request, goal, state, priority, context, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (tid, request, goal or request, S.QUEUED, priority, canonical_json(context or {}), ts, ts),
            )
            self._insert_steps(conn, tid, steps)
            self.audit.record("task.created", actor=actor, task_id=tid, request=request, goal=goal or request,
                              priority=priority, plan=[asdict(s) for s in steps])
        return tid

    def _insert_steps(self, conn: Any, tid: str, steps: list[StepSpec]) -> None:
        for idx, spec in enumerate(steps):
            if any(not isinstance(d, int) or d < 0 or d >= idx for d in spec.depends_on):
                raise ValueError(f"step {idx}: depends_on must reference earlier steps")
            if spec.max_attempts < 1:
                raise ValueError(f"step {idx}: max_attempts must be >= 1")
            conn.execute(
                "INSERT INTO steps (id, task_id, idx, description, tool, action, args, depends_on, state, max_attempts)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (new_id("step"), tid, idx, spec.description, spec.tool, spec.action, canonical_json(spec.args),
                 canonical_json(spec.depends_on), StepState.PENDING, spec.max_attempts),
            )

    def get(self, tid: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM tasks WHERE id = ?", (tid,))
        if row is None:
            raise KeyError(tid)
        return _decode(row, _JSON_TASK)

    def list(self, states: Iterable[TaskState] | None = None, *, limit: int = 200) -> list[dict[str, Any]]:
        if states is None:
            rows = self.db.query("SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,))
        else:
            states = list(states)
            marks = ",".join("?" * len(states))
            rows = self.db.query(
                f"SELECT * FROM tasks WHERE state IN ({marks}) ORDER BY priority DESC, created_at LIMIT ?",
                (*states, limit),
            )
        return [_decode(r, _JSON_TASK) for r in rows]

    def transition(self, tid: str, to: TaskState, *, actor: str = "system", reason: str | None = None,
                   **fields: Any) -> None:
        allowed = {"next_action", "error", "result", "control"}
        if set(fields) - allowed:
            raise ValueError(f"cannot set {sorted(set(fields) - allowed)} via transition")
        with self.db.tx() as conn:
            row = conn.execute("SELECT state, version FROM tasks WHERE id = ?", (tid,)).fetchone()
            if row is None:
                raise KeyError(tid)
            frm = TaskState(row["state"])
            if to not in TRANSITIONS[frm]:
                raise InvalidTransition(f"task {tid}: {frm} -> {to} is not allowed")
            if to in TERMINAL or to in (S.QUEUED, S.RUNNING):
                fields.setdefault("next_action", None)
            sets = ["state = ?", "version = version + 1", "updated_at = ?"]
            params: list[Any] = [to.value, now_iso()]
            for key, value in fields.items():
                sets.append(f"{key} = ?")
                params.append(canonical_json(value) if key == "result" and value is not None else value)
            cur = conn.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id = ? AND version = ?",
                               (*params, tid, row["version"]))
            if cur.rowcount != 1:
                raise ConcurrentModification(tid)
            self.audit.record("task.state", actor=actor, task_id=tid, frm=frm.value, to=to.value, reason=reason,
                              **{k: v for k, v in fields.items() if k in ("error", "next_action")})

    def set_next_action(self, tid: str, text: str | None) -> None:
        with self.db.tx() as conn:
            conn.execute("UPDATE tasks SET next_action = ?, version = version + 1, updated_at = ? WHERE id = ?",
                         (text, now_iso(), tid))

    def set_control(self, tid: str, control: str | None, *, actor: str) -> None:
        with self.db.tx() as conn:
            conn.execute("UPDATE tasks SET control = ?, version = version + 1, updated_at = ? WHERE id = ?",
                         (control, now_iso(), tid))
            self.audit.record("task.control", actor=actor, task_id=tid, control=control)

    # ---- steps -------------------------------------------------------------------------
    def steps(self, tid: str) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM steps WHERE task_id = ? ORDER BY idx", (tid,))
        return [_decode(r, _JSON_STEP) for r in rows]

    def step(self, step_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM steps WHERE id = ?", (step_id,))
        if row is None:
            raise KeyError(step_id)
        return _decode(row, _JSON_STEP)

    def update_step(self, step_id: str, **fields: Any) -> None:
        if not fields:
            return
        sets, params = [], []
        for key, value in fields.items():
            if key not in {"state", "result", "error", "not_before", "finished_at", "started_at", "attempts"}:
                raise ValueError(f"cannot update step field {key}")
            sets.append(f"{key} = ?")
            params.append(canonical_json(value) if key == "result" and value is not None else value)
        with self.db.tx() as conn:
            conn.execute(f"UPDATE steps SET {', '.join(sets)} WHERE id = ?", (*params, step_id))

    def start_step(self, step_id: str, op_id: str) -> int:
        """Durably record that a step is about to run. Returns the attempt number."""
        with self.db.tx() as conn:
            conn.execute(
                "UPDATE steps SET state = ?, op_id = COALESCE(op_id, ?), attempts = attempts + 1,"
                " started_at = ?, not_before = NULL WHERE id = ?",
                (StepState.STARTED, op_id, now_iso(), step_id),
            )
            return conn.execute("SELECT attempts FROM steps WHERE id = ?", (step_id,)).fetchone()["attempts"]

    def unstart_step(self, step_id: str) -> None:
        """Undo ``start_step`` when the gateway refused before the tool ran."""
        with self.db.tx() as conn:
            conn.execute(
                "UPDATE steps SET state = ?, attempts = MAX(attempts - 1, 0), started_at = NULL WHERE id = ?",
                (StepState.PENDING, step_id),
            )

    # ---- checkpoints -------------------------------------------------------------------
    def checkpoint(self, tid: str, step_id: str | None, data: dict[str, Any]) -> None:
        with self.db.tx() as conn:
            conn.execute("INSERT INTO checkpoints (task_id, step_id, ts, data) VALUES (?,?,?,?)",
                         (tid, step_id, now_iso(), canonical_json(data)))

    def latest_checkpoint(self, tid: str) -> dict[str, Any] | None:
        """Newest readable checkpoint; corrupt entries are skipped (step rows remain the source of truth)."""
        for row in self.db.query("SELECT * FROM checkpoints WHERE task_id = ? ORDER BY id DESC", (tid,)):
            try:
                data = json.loads(row["data"])
            except (json.JSONDecodeError, TypeError):
                continue
            return {"ts": row["ts"], "step_id": row["step_id"], "data": data}
        return None


class TaskEngine:
    def __init__(
        self,
        store: TaskStore,
        gateway: ToolGateway,
        killswitch: KillSwitch,
        audit: AuditLog,
        *,
        verifiers: dict[str, Verifier] | None = None,
        backoff_base: float = 2.0,
        backoff_cap: float = 300.0,
        clock: Callable[[], float] = time.time,
        arg_resolver: Callable[[dict[str, Any], list[dict[str, Any]]], dict[str, Any]] | None = None,
    ):
        self.store = store
        self.gateway = gateway
        self.killswitch = killswitch
        self.audit = audit
        self.verifiers: dict[str, Verifier] = {"all_steps_done": all_steps_done, **(verifiers or {})}
        self.backoff_base = backoff_base
        self.backoff_cap = backoff_cap
        self.clock = clock
        # Fills references to earlier step results into a step's args just before it runs, so
        # approvals are bound to the real content being written or sent.
        self.arg_resolver = arg_resolver
        self._active: set[str] = set()
        self._active_lock = threading.Lock()

    # ---- user controls -----------------------------------------------------------------
    def cancel(self, tid: str, *, actor: str = "user") -> None:
        state = TaskState(self.store.get(tid)["state"])
        if state in TERMINAL:
            raise InvalidTransition(f"task {tid} is already {state}")
        if self._is_active(tid):
            self.store.set_control(tid, "cancel", actor=actor)  # the running loop stops after the current step
            return
        self._cancel_now(tid, actor=actor)

    def pause(self, tid: str, *, actor: str = "user") -> None:
        state = TaskState(self.store.get(tid)["state"])
        if state in (S.PAUSED,) or state in TERMINAL:
            raise InvalidTransition(f"task {tid} is {state}")
        if self._is_active(tid):
            self.store.set_control(tid, "pause", actor=actor)
            return
        if state in (S.RECOVERING, S.BLOCKED):
            raise InvalidTransition(f"task {tid} is {state}; resolve it before pausing")
        self.store.transition(tid, S.PAUSED, actor=actor, reason="paused by user", control=None)

    def resume(self, tid: str, *, actor: str = "user") -> None:
        task = self.store.get(tid)
        state = TaskState(task["state"])
        if state not in (S.PAUSED, S.BLOCKED):
            raise InvalidTransition(f"task {tid} is {state}, not paused or blocked")
        if any(s["state"] == StepState.UNCERTAIN for s in self.store.steps(tid)):
            raise InvalidTransition("task has uncertain steps; resolve them with resolve_uncertain() first")
        self.store.transition(tid, S.QUEUED, actor=actor, reason="resumed by user", control=None)

    def resolve_uncertain(self, tid: str, step_id: str, *, happened: bool, actor: str = "user") -> None:
        """The user tells us whether an interrupted, non-idempotent operation actually took effect."""
        step = self.store.step(step_id)
        if step["task_id"] != tid or step["state"] != StepState.UNCERTAIN:
            raise InvalidTransition("step is not uncertain")
        if happened:
            self.store.update_step(step_id, state=StepState.DONE, result={"confirmed_by": actor}, finished_at=now_iso())
        else:
            self.store.update_step(step_id, state=StepState.PENDING, error=None)
        self.audit.record("step.resolved", actor=actor, task_id=tid, step_id=step_id, happened=happened)
        if TaskState(self.store.get(tid)["state"]) is S.BLOCKED and not any(
            s["state"] == StepState.UNCERTAIN for s in self.store.steps(tid)
        ):
            self.store.transition(tid, S.QUEUED, actor=actor, reason="uncertain steps resolved")

    def emergency_stop(self, *, by: str, reason: str) -> None:
        self.killswitch.engage(by=by, reason=reason)
        for task in self.store.list([S.QUEUED, S.RUNNING, S.AWAITING_APPROVAL]):
            if task["state"] == S.RUNNING and not self._is_active(task["id"]):
                self.store.transition(task["id"], S.PAUSED, actor=by, reason="emergency stop")

    # ---- recovery ----------------------------------------------------------------------
    def recover(self) -> list[str]:
        """Run at startup. Reconcile tasks a previous process left mid-flight."""
        recovered = []
        for task in self.store.list(INTERRUPTIBLE):
            tid = task["id"]
            if self._is_active(tid):
                continue
            if task["state"] != S.RECOVERING:
                self.store.transition(tid, S.RECOVERING, reason="process restarted while task was in flight")
            uncertain = []
            for step in self.store.steps(tid):
                if step["state"] != StepState.STARTED:
                    continue
                outcome = self._reconcile(step)
                if outcome == RECONCILE_DONE:
                    self.store.update_step(step["id"], state=StepState.DONE, result={"reconciled": True},
                                           finished_at=now_iso())
                elif outcome == RECONCILE_NOT_DONE:
                    self.store.update_step(step["id"], state=StepState.PENDING)
                else:
                    self.store.update_step(step["id"], state=StepState.UNCERTAIN,
                                           error="interrupted; outcome unknown")
                    uncertain.append(step)
                self.audit.record("step.reconciled", task_id=tid, step_id=step["id"], op_id=step["op_id"],
                                  outcome=outcome)
            if uncertain:
                self.store.transition(
                    tid, S.BLOCKED, reason="interrupted operation may or may not have completed",
                    next_action="confirm whether: " + "; ".join(s["description"] for s in uncertain),
                )
            else:
                self.store.transition(tid, S.QUEUED, reason="recovered; resuming from first incomplete step")
            recovered.append(tid)
        return recovered

    def _reconcile(self, step: dict[str, Any]) -> str:
        act = self.gateway.registry.action(step["tool"], step["action"])
        if act is None:
            return "unknown"
        if act.reconcile is not None:
            try:
                outcome = act.reconcile(step["args"], step["op_id"])
            except Exception:
                outcome = "unknown"
            return outcome if outcome in (RECONCILE_DONE, RECONCILE_NOT_DONE) else "unknown"
        return RECONCILE_NOT_DONE if act.idempotent else "unknown"

    # ---- execution ---------------------------------------------------------------------
    def run(self, tid: str, *, max_iterations: int = 10_000) -> TaskState:
        with self._active_lock:
            if tid in self._active:
                raise RuntimeError(f"task {tid} is already running in this process")
            self._active.add(tid)
        try:
            for _ in range(max_iterations):
                if not self._advance(tid):
                    break
            return TaskState(self.store.get(tid)["state"])
        finally:
            with self._active_lock:
                self._active.discard(tid)

    def _is_active(self, tid: str) -> bool:
        with self._active_lock:
            return tid in self._active

    def _advance(self, tid: str) -> bool:
        """Make one unit of progress. Returns False when the caller should stop looping."""
        task = self.store.get(tid)
        state = TaskState(task["state"])
        if state in TERMINAL or state in (S.PAUSED, S.BLOCKED, S.RECOVERING, S.PLANNING):
            return False

        if task["control"] == "cancel":
            self._cancel_now(tid, actor="user")
            return False
        if task["control"] == "pause" and state in (S.RUNNING, S.QUEUED, S.AWAITING_APPROVAL, S.VERIFYING):
            self.store.transition(tid, S.PAUSED, actor="user", reason="paused by user", control=None)
            return False

        if self.killswitch.engaged():
            if state in (S.RUNNING, S.VERIFYING):
                self.store.transition(tid, S.PAUSED, reason="emergency stop engaged")
            return False

        if state is S.QUEUED:
            self.store.transition(tid, S.RUNNING, reason="started")
            return True
        if state is S.AWAITING_APPROVAL:
            if self.gateway.approvals.pending(task_id=tid):
                return False
            self.store.transition(tid, S.RUNNING, reason="approval decided")
            return True
        if state is S.VERIFYING:
            self._verify(task)
            return True

        steps = self.store.steps(tid)
        if all(s["state"] in (StepState.DONE, StepState.SKIPPED) for s in steps):
            self.store.transition(tid, S.VERIFYING, reason="all steps finished")
            return True

        step = self._next_runnable(steps)
        if step is None:
            if any(s["state"] == StepState.UNCERTAIN for s in steps):
                self.store.transition(tid, S.BLOCKED, reason="operation outcome unknown",
                                      next_action="confirm whether the uncertain step took effect")
            elif any(s["state"] == StepState.FAILED for s in steps):
                self.store.transition(tid, S.FAILED, reason="a step failed", error=task["error"] or "a step failed")
            elif any(s["state"] == StepState.PENDING and s["not_before"] for s in steps):
                return False  # waiting for a retry backoff; the scheduler will call run() again
            else:
                self.store.transition(tid, S.FAILED, reason="no runnable step", error="unsatisfiable step dependencies")
            return True

        self._execute(tid, step, steps)
        return True

    def _next_runnable(self, steps: list[dict[str, Any]]) -> dict[str, Any] | None:
        finished = {s["idx"] for s in steps if s["state"] in (StepState.DONE, StepState.SKIPPED)}
        now = self.clock()
        for s in steps:
            if s["state"] != StepState.PENDING:
                continue
            if not all(d in finished for d in s["depends_on"]):
                continue
            if s["not_before"] is not None and s["not_before"] > now:
                continue
            return s
        return None

    def _execute(self, tid: str, step: dict[str, Any], steps: list[dict[str, Any]]) -> None:
        act = self.gateway.registry.action(step["tool"], step["action"])
        args = step["args"]
        if self.arg_resolver is not None:
            try:
                args = self.arg_resolver(step, steps)
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                self.store.update_step(step["id"], state=StepState.FAILED, error=f"bad step reference: {exc}",
                                       finished_at=now_iso())
                self.store.transition(tid, S.FAILED, reason="bad step reference", error=f"step {step['idx']}: {exc}")
                return
        op_id = step["op_id"] or new_id("op")
        attempt = self.store.start_step(step["id"], op_id)  # durable before the call
        try:
            result = self.gateway.invoke(step["tool"], step["action"], args, task_id=tid,
                                         step_id=step["id"], op_id=op_id, summary=step["description"])
        except ApprovalRequired as exc:
            self.store.unstart_step(step["id"])
            self.store.transition(tid, S.AWAITING_APPROVAL, reason=exc.decision.reason,
                                  next_action=f"approve or reject {exc.approval_id}: {step['description']}")
        except EmergencyStop:
            self.store.unstart_step(step["id"])
            self.store.transition(tid, S.PAUSED, reason="emergency stop engaged")
        except PermissionDenied as exc:
            self.store.update_step(step["id"], state=StepState.FAILED, error=f"permission denied: {exc}",
                                   finished_at=now_iso())
            self.store.transition(tid, S.FAILED, reason="permission denied", error=f"step {step['idx']}: {exc}")
        except ToolError as exc:
            if exc.outcome_unknown and (act is None or not act.idempotent):
                self.store.update_step(step["id"], state=StepState.UNCERTAIN, error=str(exc))
                self.store.transition(tid, S.BLOCKED, reason="operation outcome unknown",
                                      next_action=f"confirm whether '{step['description']}' took effect (op {op_id})")
            elif exc.retry_after is not None:
                self.store.unstart_step(step["id"])
                self.store.update_step(step["id"], not_before=exc.retry_after, error=str(exc))
                when = time.strftime("%H:%M", time.localtime(exc.retry_after))
                self.store.set_next_action(tid, f"waiting until {when}: {exc}")
                self.audit.record("step.waiting", task_id=tid, step_id=step["id"], until=exc.retry_after, error=str(exc))
            elif exc.retryable and attempt < step["max_attempts"]:
                delay = min(self.backoff_cap, self.backoff_base * (2 ** (attempt - 1)))
                self.store.update_step(step["id"], state=StepState.PENDING, error=str(exc),
                                       not_before=self.clock() + delay)
                self.audit.record("step.retry_scheduled", task_id=tid, step_id=step["id"], attempt=attempt,
                                  delay_s=delay, error=str(exc))
            else:
                why = "retry limit reached" if exc.retryable else "non-retryable error"
                self.store.update_step(step["id"], state=StepState.FAILED, error=str(exc), finished_at=now_iso())
                self.store.transition(tid, S.FAILED, reason=why, error=f"step {step['idx']}: {exc}")
        else:
            self.store.update_step(step["id"], state=StepState.DONE, result=result, error=None, finished_at=now_iso())
            if step.get("not_before"):  # it had been waiting (e.g. for a usage reset); clear the notice
                self.store.set_next_action(tid, None)
            self.store.checkpoint(tid, step["id"], {"completed_step": step["idx"], "op_id": op_id})

    def _verify(self, task: dict[str, Any]) -> None:
        tid = task["id"]
        name = task["context"].get("verifier", "all_steps_done")
        verifier = self.verifiers.get(name)
        steps = self.store.steps(tid)
        if verifier is None:
            outcome = Verification(False, {"error": f"unknown verifier {name!r}"})
        else:
            try:
                outcome = verifier(task, steps)
            except Exception as exc:
                outcome = Verification(False, {"error": f"verifier raised {type(exc).__name__}: {exc}"})
        self.audit.record("task.verified", task_id=tid, verifier=name, ok=outcome.ok, evidence=outcome.evidence)
        if outcome.ok:
            self.store.transition(tid, S.COMPLETED, reason="verified", result={"evidence": outcome.evidence})
        else:
            self.store.transition(tid, S.FAILED, reason="verification failed", error="verification failed",
                                  result={"evidence": outcome.evidence})

    def _cancel_now(self, tid: str, *, actor: str) -> None:
        self.gateway.approvals.expire_for_task(tid)
        done = [s["idx"] for s in self.store.steps(tid) if s["state"] == StepState.DONE]
        self.store.checkpoint(tid, None, {"cancelled": True, "completed_steps": done})
        self.store.transition(tid, S.CANCELLED, actor=actor, reason="cancelled by user", control=None)
