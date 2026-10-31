"""Orchestrator: interpret → plan → (owner reviews) → execute under permissions → verify → report.

Planning, permission checks, execution and verification are separate stages owned by separate
code: the planner proposes, the permission engine decides, the task engine executes durably,
and a deterministic verifier checks the result on disk.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from ..core.kernel import Kernel
from ..core.tasks import StepState, Verification
from .compose import ComposeTool
from .planner import Plan, Planner, describe_args
from .refs import resolve_step_args

DEFAULT_NOTES = "~/Documents/JARVIS/Notes"


def writes_verified(task: dict[str, Any], steps: list[dict[str, Any]]) -> Verification:
    """Every step finished, and every file JARVIS wrote is on disk with exactly the content it wrote."""
    evidence: dict[str, Any] = {"files": [], "incomplete_steps": []}
    ok = True
    for s in steps:
        if s["state"] not in (StepState.DONE, StepState.SKIPPED):
            evidence["incomplete_steps"].append(s["idx"])
            ok = False
        if s["tool"] == "fs" and s["action"] == "write" and s["state"] == StepState.DONE and s["result"]:
            path = Path(s["result"]["path"])
            actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
            match = actual == s["result"].get("sha256")
            evidence["files"].append({"path": str(path), "exists": actual is not None, "content_matches": match})
            ok = ok and match
    return Verification(ok, evidence)


class Orchestrator:
    def __init__(self, kernel: Kernel, *, notes_dir: str = DEFAULT_NOTES):
        self.kernel = kernel
        if kernel.registry.get("llm") is None:
            kernel.registry.register(ComposeTool(kernel.models).spec())
        kernel.engine.arg_resolver = resolve_step_args
        kernel.engine.verifiers.setdefault("writes_verified", writes_verified)
        self.notes_dir = str(Path(notes_dir).expanduser())
        self.planner = Planner(kernel.models, kernel.registry, roots=[str(r) for r in kernel.policy.roots],
                               notes_dir=self.notes_dir)

    def plan(self, request: str) -> Plan:
        plan = self.planner.plan(request)
        self.kernel.audit.record("orchestrator.planned", actor="system", kind=plan.kind, goal=plan.goal,
                                 model=plan.model, attempts=plan.attempts, message=plan.message,
                                 steps=[f"{s.tool}.{s.action} {describe_args(s.args)}" for s in plan.steps])
        return plan

    def submit(self, request: str, plan: Plan, *, actor: str = "user", runner: str = "cli") -> str:
        """``runner`` names the process that drives the task, so two processes never run the same one."""
        if plan.kind != "plan":
            raise ValueError(f"cannot submit a {plan.kind} result")
        return self.kernel.tasks.create(request, goal=plan.goal or request, steps=plan.steps, actor=actor,
                                        context={"verifier": "writes_verified", "planner": plan.model,
                                                 "runner": runner})

    def preview_args(self, task_id: str, step_id: str) -> dict[str, Any]:
        """The exact arguments a step will run with (references filled in) — shown when asking for approval."""
        steps = self.kernel.tasks.steps(task_id)
        step = next(s for s in steps if s["id"] == step_id)
        return resolve_step_args(step, steps)

    def report(self, task_id: str) -> dict[str, Any]:
        task = self.kernel.tasks.get(task_id)
        steps = self.kernel.tasks.steps(task_id)
        answer = next((s["result"]["text"] for s in reversed(steps)
                       if s["tool"] == "llm" and s["state"] == StepState.DONE and s["result"]), None)
        return {
            "task_id": task_id, "state": task["state"], "goal": task["goal"], "error": task["error"],
            "next_action": task["next_action"],
            "steps": [{"n": s["idx"], "state": s["state"], "description": s["description"],
                       "error": s["error"]} for s in steps],
            "evidence": (task["result"] or {}).get("evidence"),
            "final_text": answer,
        }


__all__ = ["Orchestrator", "Plan", "writes_verified"]
