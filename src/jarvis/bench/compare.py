"""Before/after: two benchmark runs compared under the merge rule the owner set for a change.

The rule (Outcome Engine v1, approved by the owner): merge only if, on the same tasks with the same models,
- at least ``min_net`` more tasks pass (default 2),
- no task that passed before fails after, and
- Claude calls rise by at most ``max_claude_rise`` (default 25 %; from zero, any Claude call is a rise).
Any change made without an approval in the "after" run is a failure regardless.

A task "passes" when more than half of its scored runs passed. Each side can be several runs pooled together
(owner's choice, 0.18.1): one run of 3 repeats lets luck flip a task, so a verdict needs at least ``min_runs``
(default 5) scored runs of every compared task on each side; with fewer it says INCONCLUSIVE instead of
MERGE. Each changed task also gets a two-sided Fisher exact test, so a real change (0/6 → 6/6, p≈0.002) can be
told apart from luck (2/3 → 0/3, p=0.4). Tasks whose definition changed between runs (different hash) are left
out and listed, never compared silently.
"""

from __future__ import annotations

import json
from datetime import datetime
from math import comb
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
    inconclusive: list[str] = field(default_factory=list)  # too few runs for a verdict
    befores: list[dict[str, Any]] = field(default_factory=list)
    afters: list[dict[str, Any]] = field(default_factory=list)

    @property
    def merge(self) -> bool:
        return not self.reasons and not self.inconclusive

    @property
    def verdict(self) -> str:
        """Too few runs makes any verdict but an unapproved change INCONCLUSIVE: a "worse" result can be luck too."""
        if self.merge:
            return "MERGE"
        return "INCONCLUSIVE" if self.inconclusive and not self.violations else "DON'T MERGE"


MIN_RUNS = 5
CLEAR_P = 0.05


def fisher_p(a_pass: int, a_n: int, b_pass: int, b_n: int) -> float:
    """Two-sided Fisher exact test on two pass rates: the chance of a split at least this uneven by luck alone."""
    total_pass, n = a_pass + b_pass, a_n + b_n
    if a_n == 0 or b_n == 0:
        return 1.0
    denom = comb(n, total_pass)

    def prob(k: int) -> float:
        return comb(a_n, k) * comb(b_n, total_pass - k) / denom
    observed = prob(a_pass)
    lo, hi = max(0, total_pass - b_n), min(a_n, total_pass)
    return min(1.0, sum(p for k in range(lo, hi + 1) if (p := prob(k)) <= observed * (1 + 1e-9)))


RESCORED = "results.rescored.json"


def load(run_dir: Path, *, rescored: bool = False) -> dict[str, Any]:
    """A run's results. ``rescored``: use its re-scored copy when one exists (see rescore.py); the label says so."""
    path = run_dir / RESCORED if rescored and (run_dir / RESCORED).exists() else run_dir / "results.json"
    if not path.exists():
        raise FileNotFoundError(f"no results.json in {run_dir}")
    data = json.loads(path.read_text())
    if path.name == RESCORED:
        data["meta"]["run_id"] = f"{data['meta'].get('run_id')} (rescored)"
    return data


def latest_runs(out_dir: Path, n: int = 2) -> list[Path]:
    """The ``n`` most recent runs by their real start time. Folder names are local clock times, which repeat an
    hour when the clocks go back (it happened on the owner's first before/after: the "after" folder sorted first)."""
    def started(p: Path) -> datetime:
        try:
            return datetime.fromisoformat(json.loads(p.read_text())["meta"]["started"]).astimezone()  # naive = local
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


def _pool(datas: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, set[str]]]:
    """Per task: runs added up across several result files, and every task hash seen."""
    out: dict[str, dict[str, Any]] = {}
    hashes: dict[str, set[str]] = {}
    for data in datas:
        for tid, t in _tasks(data).items():
            o = out.setdefault(tid, {"passed": 0, "scored": 0, "claude": 0, "violations": []})
            for k in ("passed", "scored", "claude"):
                o[k] += t[k]
            o["violations"] += t["violations"]
        for tid, h in data["meta"].get("tasks", {}).items():
            hashes.setdefault(tid, set()).add(h)
    return out, hashes


def compare(before: dict[str, Any] | list[dict[str, Any]], after: dict[str, Any] | list[dict[str, Any]], *,
            min_net: int = 2, max_claude_rise: float = 0.25, min_runs: int = MIN_RUNS) -> Comparison:
    befores = before if isinstance(before, list) else [before]
    afters = after if isinstance(after, list) else [after]
    c = Comparison(befores[0]["meta"], afters[0]["meta"], befores=[d["meta"] for d in befores],
                   afters=[d["meta"] for d in afters])
    (b, hb), (a, ha) = _pool(befores), _pool(afters)
    for tid in sorted(set(b) | set(a)):
        if tid not in b or tid not in a:
            c.left_out.append(f"{tid}: only in the {'before' if tid in b else 'after'} run")
            continue
        hashes = hb.get(tid, set()) | ha.get(tid, set())
        if len(hashes) > 1:
            c.left_out.append(f"{tid}: the task changed between the runs")
            continue
        if not b[tid]["scored"] or not a[tid]["scored"]:
            c.left_out.append(f"{tid}: not scored in both runs (skipped)")
            continue
        was, now = passes(b[tid]), passes(a[tid])
        p = fisher_p(b[tid]["passed"], b[tid]["scored"], a[tid]["passed"], a[tid]["scored"])
        c.rows.append({"id": tid, "before": f"{b[tid]['passed']}/{b[tid]['scored']}",
                       "after": f"{a[tid]['passed']}/{a[tid]['scored']}", "was": was, "now": now,
                       "p": round(p, 4), "clear": p < CLEAR_P,
                       "runs": min(b[tid]["scored"], a[tid]["scored"])})
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

    models = {d["meta"].get("models") for d in befores + afters}
    if len(models) > 1:
        c.reasons.append(f"different models ({', '.join(sorted(str(m) for m in models))})")
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
    short = [r["id"] for r in c.rows if r["runs"] < min_runs]
    if short:
        fewest = min(r["runs"] for r in c.rows)
        c.inconclusive.append(f"needs at least {min_runs} runs of every task on each side (fewest here: {fewest}); "
                              f"add runs, e.g. another `bench run --repeat 3`, and pool them")
    if c.reasons and c.inconclusive and not c.violations:
        # with too few runs a "worse" result can be luck too: say so rather than a firm DON'T MERGE
        c.inconclusive.append("the reasons below may also be luck at this number of runs")
    return c


def as_text(c: Comparison) -> str:
    def head(m: dict[str, Any]) -> str:
        return f"{m.get('run_id')} · JARVIS {m.get('jarvis_version')} ({m.get('git_commit')}) · {m.get('models')} · ×{m.get('repeat')}"

    lines = []
    for label, metas in (("Before", c.befores or [c.before]), ("After ", c.afters or [c.after])):
        lines += [f"{label}: {head(metas[0])}"] + [f"        + {head(m)}" for m in metas[1:]]
    lines.append("")
    width = max([len(r["id"]) for r in c.rows] + [4])
    for r in c.rows:
        mark = "  fixed" if r["now"] and not r["was"] else "  NEW FAILURE" if r["was"] and not r["now"] else ""
        if r["before"] != r["after"]:
            mark += f"  ({'clear change' if r['clear'] else 'could be luck'}, p={r['p']:.3g})"
        lines.append(f"  {r['id']:<{width}}  {r['before']:>5} → {r['after']:<5}{mark}")
    pb = sum(r["was"] for r in c.rows)
    pa = sum(r["now"] for r in c.rows)
    lines += ["", f"Tasks passing (more than half their runs): {pb} → {pa} of {len(c.rows)}  (net {c.net:+d})",
              f"Claude calls: {c.claude[0]} → {c.claude[1]}"]
    from .runner import busy, swapped
    slow = [m.get("run_id") for m in (c.befores or [c.before]) + (c.afters or [c.after])
            if any(busy(m.get(k)) for k in ("load_start", "load_peak", "load_end")) or swapped(m)]
    if slow:
        lines.append(f"Note: the Mac was busy or short of memory during {', '.join(map(str, slow))}: compare pass "
                     "rates, not times.")
    if c.left_out:
        lines += ["Left out:"] + [f"  - {x}" for x in c.left_out]
    if c.violations:
        lines += ["Unapproved changes in the after run:"] + [f"  - {v}" for v in c.violations]
    verdict = {"MERGE": "Verdict: MERGE (meets the rule)", "DON'T MERGE": "Verdict: DON'T MERGE",
               "INCONCLUSIVE": "Verdict: INCONCLUSIVE (not enough runs to decide)"}
    lines += ["", verdict[c.verdict]]
    lines += [f"  - {r}" for r in c.inconclusive + c.reasons]
    return "\n".join(lines)
