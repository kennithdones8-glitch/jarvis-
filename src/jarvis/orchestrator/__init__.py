"""Orchestrator: interpret → plan → (owner reviews) → execute under permissions → verify → report.

Planning, permission checks, execution and verification are separate stages owned by separate
code: the planner proposes, the permission engine decides, the task engine executes durably,
and a deterministic verifier checks the result on disk.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from ..core.kernel import Kernel
from ..core.tasks import StepState, Verification
from .compose import ComposeTool
from .research import ResearchTool
from .planner import Plan, Planner, describe_args
from .refs import resolve_step_args

DEFAULT_NOTES = "~/Documents/JARVIS/Notes"
# "my dentist appointment tomorrow": the words before the event word say which one (checked against the calendar).
PREMISE = re.compile(r"\b(?:my|the|our)\s+(?P<what>(?:[A-Za-z]+\s+){1,3}?)(?P<kind>appointment|meeting|call|interview|"
                     r"booking|lesson|class|session)s?\b", re.I)
VAGUE = {"next", "upcoming", "first", "last", "big", "usual", "weekly", "daily", "new", "important", "own", "a", "an"}
# A task that refers to an existing appointment, meeting or reminder: planned with it looked up first.
LOOK_FIRST = re.compile(r"\b(my|the|our)\s+(?:\w+\s+){0,3}?(appointments?|meetings?|events?|calls?|reminders?|"
                        r"bookings?|flights?|lunch|dinner|interview)\b", re.I)


def writes_verified(task: dict[str, Any], steps: list[dict[str, Any]]) -> Verification:
    """Every step finished, and every file JARVIS wrote is on disk with exactly the content it wrote.
    If the task did web research, every written file must cite at least one source the research
    actually saw (so a "sourced brief" can't silently lose or invent its sources)."""
    evidence: dict[str, Any] = {"files": [], "incomplete_steps": []}
    verified_urls = {src["url"] for s in steps if s["tool"] == "research" and s["state"] == StepState.DONE
                     and isinstance(s["result"], dict) for src in s["result"].get("sources", []) if src.get("verified")}
    researched = any(s["tool"] == "research" for s in steps)
    ok = True
    for s in steps:
        if s["state"] not in (StepState.DONE, StepState.SKIPPED):
            evidence["incomplete_steps"].append(s["idx"])
            ok = False
        if s["tool"] == "fs" and s["action"] == "write" and s["state"] == StepState.DONE and s["result"]:
            path = Path(s["result"]["path"])
            actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
            match = actual == s["result"].get("sha256")
            record = {"path": str(path), "exists": actual is not None, "content_matches": match}
            if researched:
                body = path.read_text(errors="replace") if actual else ""
                cited = sorted(u for u in verified_urls if u in body)
                record["verified_sources_cited"] = len(cited)
                ok = ok and bool(cited)
            evidence["files"].append(record)
            ok = ok and match
    return Verification(ok, evidence)


def research_available(kernel: Kernel) -> bool:
    """Web research needs a cloud model that can browse (Claude via Claude Code)."""
    return any("research" in info.capabilities for s in kernel.models.router.gate.summaries()
               for info in s.models.values())


class Orchestrator:
    def __init__(self, kernel: Kernel, *, notes_dir: str = DEFAULT_NOTES):
        self.kernel = kernel
        if kernel.registry.get("llm") is None:
            kernel.registry.register(ComposeTool(kernel.models).spec())
        if kernel.registry.get("research") is None and research_available(kernel):
            kernel.registry.register(ResearchTool(kernel.models).spec())
        kernel.engine.arg_resolver = resolve_step_args
        kernel.engine.verifiers.setdefault("writes_verified", writes_verified)
        from .criteria import make_verifier
        kernel.engine.verifiers.setdefault("mission_verified", make_verifier(kernel.registry, writes_verified))
        self.notes_dir = str(Path(notes_dir).expanduser())
        self.planner = Planner(kernel.models, kernel.registry, roots=[str(r) for r in kernel.policy.roots],
                               notes_dir=self.notes_dir)

    def plan(self, request: str, *, local_only: bool = False, earlier: str | None = None) -> Plan:
        """``earlier``: what happened on a failed first attempt (a replan), so the new plan doesn't redo what's done."""
        if question := self.premise_question(request):
            plan = Plan("clarify", message=question, model="jarvis (calendar check)")
            self.kernel.audit.record("orchestrator.premise_checked", actor="system", asked=True)
            return plan
        facts = self.look_first(request)
        if earlier:
            from ..models import Message
            note = ("A first attempt at this request failed. What happened:\n" + earlier
                    + "\nPlan only what is still needed: don't repeat steps that are already done, and avoid what failed.")
            facts = (Message(facts.role, facts.content + "\n\n" + note, facts.category, local_only=facts.local_only)
                     if facts is not None else Message("user", note))
        plan = self.planner.plan(request, local_only=local_only, facts=facts)
        self.kernel.audit.record("orchestrator.planned", actor="system", kind=plan.kind, goal=plan.goal,
                                 model=plan.model, attempts=plan.attempts, message=plan.message,
                                 steps=[f"{s.tool}.{s.action} {describe_args(s.args)}" for s in plan.steps])
        return plan

    def premise_question(self, request: str) -> str | None:
        """A question when a task names an appointment on a day it isn't on. Real failure (hard set, smarter-v2):
        "a reminder ... before my dentist appointment tomorrow" was planned even with the calendar in front of the
        planner (the appointment was the day after). Checked here in code, read-only: the calendar for the day the
        request names must have an event with that word in its title; if not, JARVIS asks, and says where the
        nearest one is. Never raises; anything it can't check (no calendar access, no day named) plans as before."""
        from datetime import datetime, timedelta

        from .lookup import named_days
        m = PREMISE.search(request or "")
        if not m:
            return None
        words = [w for w in re.findall(r"[a-z]+", m.group("what").lower()) if w not in VAGUE]
        days = named_days(request)
        if not words or not days:
            return None
        day = days[0]
        start = datetime(day.year, day.month, day.day).astimezone()
        events = self._read_calendar(start - timedelta(days=7), start + timedelta(days=15))
        if events is None:
            return None

        def matches(e: dict) -> bool:
            title = str(e.get("title", "")).lower()
            return any(re.search(rf"\b{re.escape(w)}", title) for w in words)

        def when(e: dict) -> datetime | None:
            try:
                return datetime.fromisoformat(str(e["start"]).replace("Z", "+00:00")).astimezone()
            except (KeyError, ValueError):
                return None
        hits = [(t, e) for e in events if matches(e) and (t := when(e))]
        if any(t.date() == day for t, _ in hits):
            return None
        thing = f"{' '.join(words)} {m.group('kind').lower()}"
        said = f"{day:%A %d %B}"
        if hits:
            t, e = min(hits, key=lambda h: abs((h[0].date() - day).days))
            return (f"I can't see a {thing} on {said}. There's \u201c{e.get('title')}\u201d on {t:%A %d %B at %H:%M}. "
                    "Is that the one you mean?")
        return f"I can't see a {thing} on {said}, or in the two weeks around it. When is it?"

    def _read_calendar(self, start, end) -> list[dict] | None:
        """Calendar events, read-only and only when the permission engine allows it without asking; else None."""
        from ..core.killswitch import EmergencyStop
        from ..core.permissions import Effect

        spec = self.kernel.registry.action("calendar", "events")
        if spec is None:
            return None
        decision = self.kernel.permissions.evaluate(tool="calendar", action="events", tier=spec.tier,
                                                    resource_kind=spec.resource_kind, resource=None)
        if decision.effect is not Effect.ALLOW:
            return None
        try:
            r = self.kernel.gateway.invoke("calendar", "events", {"from": start.isoformat(), "to": end.isoformat()},
                                           summary="check the appointment the task names")
        except EmergencyStop:
            return None
        except Exception:
            return None
        return r.get("events", []) if isinstance(r, dict) else None

    def look_first(self, request: str):
        """Look before acting: a task that refers to something already in the calendar or reminders ("my dentist
        appointment tomorrow") is planned with that looked up, read-only, by the same lookup step chat uses. Real
        failure (hard set, 0.19.2): a reminder "one hour before my dentist appointment tomorrow" was planned blind;
        the appointment was the day after. Never raises: no facts just means planning as before."""
        if not LOOK_FIRST.search(request or ""):
            return None
        from .lookup import LookupService  # imported here: lookup imports the planner
        try:
            found = LookupService(self.kernel, [str(r) for r in self.kernel.policy.roots]).run(
                request, only={("calendar", "events"), ("reminders", "list")})
        except Exception as exc:
            self.kernel.audit.record("orchestrator.look_first_failed", actor="system", error=type(exc).__name__)
            return None
        if found.checked:
            self.kernel.audit.record("orchestrator.looked_first", actor="system", checked=found.checked)
        return found.context

    def submit(self, request: str, plan: Plan, *, actor: str = "user", runner: str = "cli",
               replan_of: str | None = None, after: str | None = None) -> str:
        """``runner`` names the process that drives the task, so two processes never run the same one.
        The mission's definition of success (one criterion per step) is decided now, from the plan itself."""
        from .criteria import criteria_for
        if plan.kind != "plan":
            raise ValueError(f"cannot submit a {plan.kind} result")
        context = {"verifier": "mission_verified", "planner": plan.model, "runner": runner, "criteria": criteria_for(plan.steps)}
        if replan_of:
            context["replan_of"] = replan_of
        if after:
            context["after"] = after   # waits until that mission has completed (the runner checks)
        return self.kernel.tasks.create(request, goal=plan.goal or request, steps=plan.steps, actor=actor, context=context)

    @staticmethod
    def failure_story(task: dict[str, Any], steps: list[dict[str, Any]]) -> str:
        """What a failed mission did, for its one replan: step descriptions, states and errors (no file contents)."""
        lines = [f"- step {s['idx'] + 1} ({s['tool']}.{s['action']}): {s['description'][:160]} — {s['state']}"
                 + (f"; error: {str(s['error'])[:200]}" if s["error"] else "") for s in steps]
        why = (task.get("error") or "")[:200]
        return "\n".join(lines) + (f"\nThe mission ended with: {why}" if why else "")

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
        if answer is None:
            # No writing step (the plan put the text straight into the file): say what was saved, rather than
            # finishing with nothing to read. Real case: tooluse-decisions run 4 wrote the right file, empty answer.
            answer = saved_text(steps)
        return {
            "task_id": task_id, "state": task["state"], "goal": task["goal"], "error": task["error"],
            "next_action": task["next_action"],
            "steps": [{"n": s["idx"], "state": s["state"], "description": s["description"],
                       "error": s["error"]} for s in steps],
            "evidence": (task["result"] or {}).get("evidence"),
            "final_text": answer,
        }


def saved_text(steps: list[dict[str, Any]], limit: int = 4000) -> str | None:
    """"Saved <file>:" and what the last finished fs.write saved (its arguments, references filled in)."""
    for s in reversed(steps):
        if (s["tool"], s["action"]) == ("fs", "write") and s["state"] == StepState.DONE:
            try:
                args = resolve_step_args(s, steps)
            except Exception:
                return None
            content, path = args.get("content"), args.get("path")
            if isinstance(content, str) and content.strip() and isinstance(path, str):
                return f"Saved {Path(path).name}:\n\n{content.strip()[:limit]}"
            return None
    return None


__all__ = ["Orchestrator", "Plan", "writes_verified"]
