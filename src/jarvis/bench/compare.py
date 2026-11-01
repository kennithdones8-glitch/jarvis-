"""Before/after: two benchmark runs compared under the merge rule the owner set for a change.

The rule (Outcome Engine v1, approved by the owner): merge only if, on the same tasks with the same models,
- at least ``min_net`` more tasks pass (default 2),
- no task that passed before fails after, and
- Claude calls rise by at most ``max_claude_rise`` (default 25 %; from zero, any Claude call is a rise).
Any change made without an approval in the "after" run is a failure regardless.

A task "passes" when more than half of its scored runs passed (2 of 3 with ``--repeat 3``). Tasks whose
definition changed between the runs (different hash) are left out and listed, never compared silently.
"""

from __future__ import annotations

import json
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Comparison:
    before: dict[str, Any]
    after: dict[str, Any]
    rows: list[dict[str, Any]] = field(default_factory=list)
    left_out: list[str] = field(default_factory=list)
    net: int = 0
    new_failures: list[str] = field(default_factory=list)
    fixed: list[str] = field(default_factory=list)
    claude: tuple[int, int] = (0, 0)
    claude_ok: bool = True
    violations: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    @property
    def merge(self) -> bool:
        return not self.reasons


def load(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "results.json"
    if not path.exists():
        raise FileNotFoundError(f"no results.json in {run_dir}")
    return json.loads(path.read_text())


def latest_runs(out_dir: Path, n: int = 2) -> list[Path]:
    """The ``n`` most recent runs by their real start time. Folder names are local clock times, which repeat an
    hour when the clocks go back (it happened on the owner's first before/after: the "after" folder sorted first)."""
    def started(p: Path) -> datetime:
        try:
            return datetime.fromisoformat(json.loads(p.read_text())["meta"]["started"])
        except (OSError, ValueError, KeyError, TypeError):
            return datetime.fromtimestamp(p.stat().st_mtime).astimezone()
    runs = sorted(out_dir.glob("*/results.json"), key=started)
    return [p.parent for p in runs[-n:]]


def _tasks(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for r in data["results"]:
        t = out.setdefault(r["id"], {"passed": 0, "scored": 0, "claude": 0, "violations": []})
        if r.get("status") in ("pass", "fail"):
            t["scored"] += 1
            t["passed"] += r["status"] == "pass"
        t["claude"] += int((r.get("usage") or {}).get("claude_calls", 0))
        t["violations"] += r.get("violations") or []
    return out


def passes(t: dict[str, Any]) -> bool:
    return t["scored"] > 0 and t["passed"] * 2 > t["scored"]


def compare(before: dict[str, Any], after: dict[str, Any], *, min_net: int = 2,
            max_claude_rise: float = 0.25) -> Comparison:
    c = Comparison(before["meta"], after["meta"])
    b, a = _tasks(before), _tasks(after)
    hb, ha = before["meta"].get("tasks", {}), after["meta"].get("tasks", {})
    for tid in sorted(set(b) | set(a)):
        if tid not in b or tid not in a:
            c.left_out.append(f"{tid}: only in the {'before' if tid in b else 'after'} run")
            continue
        if hb.get(tid) != ha.get(tid):
            c.left_out.append(f"{tid}: the task changed between the runs")
            continue
        if not b[tid]["scored"] or not a[tid]["scored"]:
            c.left_out.append(f"{tid}: not scored in both runs (skipped)")
            continue
        was, now = passes(b[tid]), passes(a[tid])
        c.rows.append({"id": tid, "before": f"{b[tid]['passed']}/{b[tid]['scored']}",
                       "after": f"{a[tid]['passed']}/{a[tid]['scored']}", "was": was, "now": now})
        if was and not now:
            c.new_failures.append(tid)
        if now and not was:
            c.fixed.append(tid)
        c.violations += [f"{tid}: {v}" for v in a[tid]["violations"]]
    compared = [r["id"] for r in c.rows]
    c.net = sum(passes(a[t]) for t in compared) - sum(passes(b[t]) for t in compared)
    cb, ca = sum(b[t]["claude"] for t in compared), sum(a[t]["claude"] for t in compared)
    c.claude = (cb, ca)
    c.claude_ok = ca <= cb * (1 + max_claude_rise) if cb else ca == 0

    if before["meta"].get("models") != after["meta"].get("models"):
        c.reasons.append(f"different models ({before['meta'].get('models')} vs {after['meta'].get('models')})")
    if before["meta"].get("repeat") != after["meta"].get("repeat"):
        c.reasons.append("different number of repeats")
    if not compared:
        c.reasons.append("no tasks in common to compare")
    if c.net < min_net:
        c.reasons.append(f"net change is {c.net:+d} task(s); the rule needs at least +{min_net}")
    if c.new_failures:
        c.reasons.append("new failures: " + ", ".join(c.new_failures))
    if not c.claude_ok:
        c.reasons.append(f"Claude calls rose from {cb} to {ca} (limit +{round(max_claude_rise * 100)}%)")
    if c.violations:
        c.reasons.append("changes made without an approval in the after run")
    return c


def as_text(c: Comparison) -> str:
    def head(m: dict[str, Any]) -> str:
        return f"{m.get('run_id')} · JARVIS {m.get('jarvis_version')} ({m.get('git_commit')}) · {m.get('models')} · ×{m.get('repeat')}"

    lines = [f"Before: {head(c.before)}", f"After:  {head(c.after)}", ""]
    width = max([len(r["id"]) for r in c.rows] + [4])
    for r in c.rows:
        mark = "  fixed" if r["now"] and not r["was"] else "  NEW FAILURE" if r["was"] and not r["now"] else ""
        lines.append(f"  {r['id']:<{width}}  {r['before']:>5} → {r['after']:<5}{mark}")
    pb = sum(r["was"] for r in c.rows)
    pa = sum(r["now"] for r in c.rows)
    lines += ["", f"Tasks passing (more than half their runs): {pb} → {pa} of {len(c.rows)}  (net {c.net:+d})",
              f"Claude calls: {c.claude[0]} → {c.claude[1]}"]
    if c.left_out:
        lines += ["Left out:"] + [f"  - {x}" for x in c.left_out]
    if c.violations:
        lines += ["Unapproved changes in the after run:"] + [f"  - {v}" for v in c.violations]
    lines += ["", "Verdict: MERGE (meets the rule)" if c.merge else "Verdict: DON'T MERGE"]
    lines += [f"  - {r}" for r in c.reasons]
    return "\n".join(lines)
