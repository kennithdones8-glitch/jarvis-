"""Improvement proposals: JARVIS studies its own record and suggests what to change. It never changes anything.

Your policy is propose-only: every change to JARVIS is approved by you before it's applied. So a proposal is a
note with evidence, and deciding on one only records your answer:
- approve → it goes on the to-do list; for code, `jarvis proposals brief ID` prints a self-contained brief for a
  Claude Code session, which then works on a branch you review and benchmark before anything is merged;
- reject → it won't be proposed again (until the evidence changes a lot);
- mark done → once it's been dealt with.

The detectors are deterministic: counts from the audit log, approvals and the latest benchmark run. No model is
asked and nothing leaves the Mac. Evidence holds counts, task ids and action names, never what you wrote.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .core.util import new_id, now_iso

WINDOW_DAYS = 30
MAX_AUDIT = 50_000
STATES = ("open", "approved", "rejected", "done")
CATEGORY_IDEAS = {
    "coding": "Run code before answering (the coding self-test branch), or route coding to Claude in hybrid mode.",
    "reasoning": "Check answers against the question's own conditions and formats (the answer-check branch), or "
                 "route puzzles to Claude in hybrid mode.",
    "planning": "Look at what the calendar/reminder lookups returned for the failing tasks on the Benchmarks page; "
                "most planning failures so far came from the lookup step, not the answer.",
    "memory": "Check which memories reached the prompt (profile vs. search) for the failing tasks.",
    "recovery": "Look at the failing runs' plans and approvals: recovery failures usually mean a refusal or a wrong step.",
    "tool_use": "Look at the plan each failing run made and which approval it asked for.",
    "research": "Research needs Claude; check its sources were verified.",
}


@dataclass
class Proposal:
    key: str            # stable identity, so the same finding isn't proposed twice
    kind: str           # "code" | "setting" | "rule" | "investigate"
    title: str
    problem: str
    evidence: list[str]
    suggestion: str
    risk: str
    size: int = 0       # how much evidence; a rejected proposal comes back only if this grows a lot
    data: dict[str, Any] = field(default_factory=dict)


# ---- detectors ---------------------------------------------------------------------------------------------------
def _audit(kernel, days: int) -> list[dict[str, Any]]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = kernel.db.query("SELECT event, ts, payload FROM audit WHERE ts >= ? ORDER BY seq DESC LIMIT ?", (since, MAX_AUDIT))
    return [{"event": r["event"], "ts": r["ts"], "payload": json.loads(r["payload"])} for r in rows]


def _benchmark(kernel) -> list[Proposal]:
    from .bench.compare import latest_runs
    out_dir = kernel.home / "bench-results"
    dirs = latest_runs(out_dir, 1) if out_dir.is_dir() else []
    if not dirs:
        return []
    try:
        data = json.loads((dirs[0] / "results.json").read_text())
    except (OSError, ValueError):
        return []
    run = {"run_id": dirs[0].name, "version": data.get("meta", {}).get("jarvis_version", "?")}
    per: dict[str, list[int]] = {}
    cat: dict[str, str] = {}
    for r in data["results"]:
        if r.get("status") in ("pass", "fail"):
            t = per.setdefault(r["id"], [0, 0])
            t[0] += r["status"] == "pass"
            t[1] += 1
            cat[r["id"]] = r.get("category", "?")
    failing: dict[str, list[str]] = {}
    for tid, (passed, scored) in per.items():
        if passed * 2 <= scored:
            failing.setdefault(cat[tid], []).append(f"{tid} ({passed}/{scored})")
    out = []
    for category, tasks in sorted(failing.items()):
        out.append(Proposal(
            key=f"bench:{category}", kind="investigate",
            title=f"Benchmark: {category.replace('_', ' ')} tasks fail in most runs",
            problem=f"In the latest benchmark run, {len(tasks)} {category.replace('_', ' ')} task(s) failed in at least "
                    "half their runs.",
            evidence=[f"run {run['run_id']} (JARVIS {run['version']})"] + tasks,
            suggestion=CATEGORY_IDEAS.get(category, "Look at the failures on the Benchmarks page."),
            risk="None until a change is made; any change goes on a branch and is benchmarked before merging.",
            size=len(tasks), data={"run": run["run_id"], "tasks": tasks}))
    return out


def _tool_trouble(entries: list[dict]) -> list[Proposal]:
    starts = {e["payload"].get("op_id"): f"{e['payload'].get('tool')}.{e['payload'].get('action')}"
              for e in entries if e["event"] == "tool.start"}
    timeouts = Counter(starts.get(e["payload"].get("op_id"), "?") for e in entries if e["event"] == "tool.timeout")
    errors = Counter(starts.get(e["payload"].get("op_id"), "?") for e in entries if e["event"] == "tool.error")
    calls = Counter(starts.values())
    out = []
    for action, n in timeouts.items():
        if n >= 3:
            out.append(Proposal(
                key=f"timeout:{action}", kind="code", title=f"{action} keeps timing out",
                problem=f"{action} timed out {n} times in the last {WINDOW_DAYS} days (of {calls.get(action, n)} calls).",
                evidence=[f"{n} timeouts", f"{calls.get(action, 0)} calls"],
                suggestion="Measure where the time goes (like the Calendar probe did) and make the slow part bounded.",
                risk="Low: read speed only; changes are tested and benchmarked.", size=n))
    for action, n in errors.items():
        total = calls.get(action, 0)
        if n >= 5 and total and n / total >= 0.3:
            out.append(Proposal(
                key=f"errors:{action}", kind="investigate", title=f"{action} fails often",
                problem=f"{action} failed {n} of {total} times in the last {WINDOW_DAYS} days.",
                evidence=[f"{n} errors of {total} calls"],
                suggestion="Read the errors in `jarvis audit` (or a task's timeline) and fix the common cause.",
                risk="None until a change is made.", size=n))
    return out


def _approvals(kernel, days: int) -> list[Proposal]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = kernel.db.query("SELECT tool, action, resource, tier, state FROM approvals WHERE created_at >= ?", (since,))
    out = []
    approved: Counter = Counter()
    rejected: Counter = Counter()
    for r in rows:
        folder = str(Path(r["resource"]).parent) if r["resource"] and r["resource"].startswith("/") else None
        k = (r["tool"], r["action"], folder, r["tier"])
        if r["state"] in ("approved", "consumed"):
            approved[k] += 1
        elif r["state"] == "rejected":
            rejected[k] += 1
    for (tool, action, folder, tier), n in approved.items():
        if n >= 10 and tier <= 1 and rejected.get((tool, action, folder, tier), 0) == 0:
            where = f" in {folder}" if folder else ""
            rule = (f'[[rules]]\nid = "allow-{tool}-{action}"\neffect = "allow"\ntools = ["{tool}"]\nactions = ["{action}"]'
                    + (f'\nresources = ["{folder}/**"]' if folder else ""))
            out.append(Proposal(
                key=f"allow:{tool}.{action}:{folder}", kind="rule",
                title=f"You always approve {tool}.{action}{where}",
                problem=f"You approved {tool}.{action}{where} {n} times in {days} days and never rejected it.",
                evidence=[f"{n} approvals, 0 rejections"],
                suggestion="If you're happy for JARVIS to do this without asking, add this rule to policy.toml yourself "
                           f"(JARVIS never edits its own policy):\n{rule}",
                risk="It would no longer ask before this action in that place. Only routine actions (tier 0–1) are "
                     "ever suggested; deletes and anything external always ask.", size=n,
                data={"rule": rule}))
    for (tool, action, folder, tier), n in rejected.items():
        if n >= 3:
            out.append(Proposal(
                key=f"rejected:{tool}.{action}:{folder}", kind="investigate",
                title=f"You keep rejecting {tool}.{action}",
                problem=f"You rejected {tool}.{action}{f' in {folder}' if folder else ''} {n} times in {days} days.",
                evidence=[f"{n} rejections"],
                suggestion="JARVIS may be planning this step when it shouldn't (like the unrequested \"open Mail\" step "
                           "found by the benchmark). Look at those tasks' plans.",
                risk="None until a change is made.", size=n))
    return out


def _answers(entries: list[dict]) -> list[Proposal]:
    out = []
    grounding = [e["payload"] for e in entries if e["event"] == "chat.grounding"]
    bad = [p for p in grounding if p.get("ok") is False]
    if len(bad) >= 3:
        out.append(Proposal(
            key="answers:ungrounded", kind="setting", title="Calendar answers mention times that aren't in your calendar",
            problem=f"{len(bad)} of {len(grounding)} checked answers in {WINDOW_DAYS} days still mentioned a time not in the "
                    "looked-up data after a retry.",
            evidence=[f"{len(bad)} unverified of {len(grounding)}"],
            suggestion="A larger local model, or hybrid routing so harder questions can go to Claude (it asks you first).",
            risk="Hybrid sends questions to Claude only with your consent; a larger model needs a download you approve.",
            size=len(bad)))
    fallbacks = [e for e in entries if e["event"] == "model.fallback"]
    if len(fallbacks) >= 5:
        out.append(Proposal(
            key="models:fallbacks", kind="investigate", title="Claude was often unavailable",
            problem=f"Answers fell back to the local model {len(fallbacks)} times in {WINDOW_DAYS} days.",
            evidence=[f"{len(fallbacks)} fallbacks"],
            suggestion="Check `jarvis doctor` for Claude's status and your plan's usage limits.",
            risk="None.", size=len(fallbacks)))
    return out


def detect(kernel, *, days: int = WINDOW_DAYS) -> list[Proposal]:
    entries = _audit(kernel, days)
    return _benchmark(kernel) + _tool_trouble(entries) + _approvals(kernel, days) + _answers(entries)


# ---- storage -----------------------------------------------------------------------------------------------------
class Proposals:
    def __init__(self, kernel):
        self.kernel = kernel
        self.db = kernel.db
        self.audit = kernel.audit

    def refresh(self) -> dict[str, int]:
        """Run the detectors; add new findings, update open ones. A rejected one returns only if its evidence at
        least doubles; a done one returns if the problem is seen again."""
        added = updated = 0
        now = now_iso()
        for p in detect(self.kernel):
            body = json.dumps(asdict(p))
            row = self.db.one("SELECT id, state, body FROM proposals WHERE key = ?", (p.key,))
            with self.db.tx() as c:
                if row is None:
                    c.execute("INSERT INTO proposals (id, key, kind, title, body, state, created_at, updated_at) "
                              "VALUES (?,?,?,?,?,'open',?,?)", (new_id("prop"), p.key, p.kind, p.title, body, now, now))
                    added += 1
                    continue
                old = json.loads(row["body"]).get("size", 0)
                reopen = (row["state"] == "rejected" and p.size >= max(2 * old, old + 1)) or row["state"] == "done"
                if row["state"] == "open" or reopen:
                    c.execute("UPDATE proposals SET title = ?, body = ?, updated_at = ?, state = 'open'"
                              + (", decided_at = NULL, decided_by = NULL" if reopen else "") + " WHERE id = ?",
                              (p.title, body, now, row["id"]))
                    updated += 1
        self.audit.record("proposals.refreshed", added=added, updated=updated)
        return {"added": added, "updated": updated}

    def list(self, state: str | None = None) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM proposals" + (" WHERE state = ?" if state else "")
                             + " ORDER BY CASE state WHEN 'open' THEN 0 WHEN 'approved' THEN 1 ELSE 2 END, updated_at DESC",
                             (state,) if state else ())
        return [{**{k: r[k] for k in r.keys() if k != "body"}, **json.loads(r["body"])} for r in rows]

    def get(self, pid: str) -> dict[str, Any]:
        found = [p for p in self.list() if p["id"] == pid]
        if not found:
            raise KeyError(pid)
        return found[0]

    def decide(self, pid: str, state: str, *, by: str) -> None:
        """Records your answer. Changes nothing else: approving is permission to work on it, not the change itself."""
        if state not in ("approved", "rejected", "done", "open"):
            raise ValueError("state must be approved, rejected, done or open")
        if not by.startswith("user"):
            raise PermissionError("only you can decide on a proposal")
        with self.db.tx() as c:
            if c.execute("UPDATE proposals SET state = ?, decided_at = ?, decided_by = ? WHERE id = ?",
                         (state, now_iso(), by, pid)).rowcount != 1:
                raise KeyError(pid)
            self.audit.record("proposals.decided", actor=by, proposal_id=pid, state=state)

    def brief(self, pid: str) -> str:
        """A self-contained task for a Claude Code session working in the repository. Only for approved proposals."""
        p = self.get(pid)
        if p["state"] != "approved":
            raise PermissionError("approve the proposal first: only approved proposals get a brief")
        lines = [f"# JARVIS improvement: {p['title']}", "",
                 f"Approved by the owner on {p['decided_at'][:10]} (proposal {p['id']}, kind: {p['kind']}).", "",
                 "## Problem", p["problem"], "", "## Evidence", *[f"- {e}" for e in p["evidence"]], "",
                 "## Suggested direction", p["suggestion"], "", "## Risk", p["risk"], "",
                 "## How to work (from the JARVIS engineering constitution)",
                 "- Stage A first: investigate and propose a plan; wait for the owner's approval before changing code.",
                 "- Work on a new branch. Don't touch the permission engine, privacy controls, credential handling, "
                 "approval system, audit integrity, budget guard or emergency stop without explicit approval.",
                 "- Run `uv run jarvis gate`; benchmark before/after with `jarvis bench run` and `jarvis bench compare`.",
                 "- Report honestly: what changed, tests run and their results, limitations, rollback."]
        return "\n".join(lines)
