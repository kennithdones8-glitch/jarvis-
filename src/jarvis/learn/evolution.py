"""The Self-Evolution Laboratory (Evolution 4.0, Stage 5): find what's weak, design a fair experiment, judge it on
repeated evidence, and hand you a package to approve. It never changes JARVIS.

The loop, each step recorded in the append-only ``evolution`` history:

1. **Opportunities** come from evidence JARVIS already has (the proposal detectors and the lessons learned from
   outcomes: failed and stuck missions, tools that keep failing, answers that fail their check, your ratings,
   benchmark drops, requests no model could take). Each is ranked by expected benefit, confidence, complexity, risk
   and reversibility, with the numbers shown, not a single opaque score.
2. **A design** for an opportunity: the problem and its evidence, the proposed solution and alternatives, success
   criteria, regression risks, the test plan, a budget, and how to roll back.
3. **Experiments** run in the existing level-6 sandbox (see ``trial.py``), now repeated: a change only "holds" when
   every run agrees. A test that fails in some runs and not others is reported as flaky and never decides the
   verdict. Several candidates can be tried against the same baseline and are judged on the same criteria.
4. **A package** for a change that held: weakness, before and after, evidence, security implications, files, whether
   a database migration is involved, rollback instructions, and its approval status.
5. **Your decision**, and later your note that you applied it or rolled it back. JARVIS never applies, commits,
   merges or pushes anything: applying is something you do, with the command the package gives you.

What this module cannot do, by construction and by test: write to the autonomy, permission or approval tables;
record a decision, an "applied" or a "rolled back" as anyone but you; change or delete a line of the history (the
database refuses); or run an experiment itself (it only calls the Lab, which enforces the autonomy tiers, the
emergency stop and the sandbox).

A failed experiment is evidence about that attempt, not a verdict on the idea: the opportunity stays, with "tried
before" attached, and comes back when the evidence for it grows.
"""

from __future__ import annotations

import json
from typing import Any

from ..core.util import now_iso

OWNER_ONLY = ("decision", "applied", "rolled_back")
COMPLEXITY = {"setting": 1, "rule": 2, "investigate": 3, "code": 4}       # how much work a change of this kind is
RISK = {"setting": 1, "rule": 2, "investigate": 1, "code": 3}
REVERSIBLE = {"setting": "immediately (change the setting back)", "rule": "immediately (remove the rule)",
              "investigate": "nothing is changed by looking", "code": "by reverting the patch (git apply -R)"}
MAX_RUNS = 5


class EvolutionError(ValueError):
    pass


# ---- the history ----------------------------------------------------------------------------------------------------
def record(kernel, kind: str, subject: str, title: str, body: dict[str, Any], *, actor: str) -> int:
    """Add one line. Decisions and "applied"/"rolled back" notes can only come from you."""
    if kind in OWNER_ONLY and not actor.startswith("user"):
        raise PermissionError(f"only you can record '{kind.replace('_', ' ')}' in the evolution history")
    with kernel.db.tx() as c:
        cur = c.execute("INSERT INTO evolution (ts, kind, subject, title, body, actor) VALUES (?,?,?,?,?,?)",
                        (now_iso(), kind, subject[:200], title[:200], json.dumps(body, default=str)[:20000], actor))
        seq = cur.lastrowid
    kernel.audit.record("evolution.recorded", actor=actor, kind=kind, seq=seq)
    return seq


def history(kernel, *, q: str | None = None, subject: str | None = None, kind: str | None = None,
            limit: int = 100) -> list[dict[str, Any]]:
    """Newest first. ``q`` matches the title, subject or body text."""
    where, args = [], []
    if subject:
        where.append("subject = ?")
        args.append(subject)
    if kind:
        where.append("kind = ?")
        args.append(kind)
    if q and q.strip():
        where.append("(title LIKE ? OR subject LIKE ? OR body LIKE ?)")
        args += [f"%{q.strip()}%"] * 3
    rows = kernel.db.query("SELECT * FROM evolution" + (" WHERE " + " AND ".join(where) if where else "")
                           + " ORDER BY seq DESC LIMIT ?", (*args, limit))
    return [{**dict(r), "body": json.loads(r["body"])} for r in rows]


def _last(kernel, subject: str, kind: str) -> dict[str, Any] | None:
    found = history(kernel, subject=subject, kind=kind, limit=1)
    return found[0] if found else None


# ---- 1. opportunities -------------------------------------------------------------------------------------------------
def _rank(kind: str, size: int, tried_failed: int) -> dict[str, Any]:
    benefit = max(1, min(5, 1 + size // 2))                    # more evidence of the problem = more to gain
    confidence = round(min(0.95, 0.3 + 0.1 * size), 2)         # grows with observations, never certain
    complexity, risk = COMPLEXITY.get(kind, 3), RISK.get(kind, 2)
    priority = round(benefit * confidence / (complexity + risk) * (0.8 ** tried_failed), 3)
    return {"benefit": benefit, "confidence": confidence, "complexity": complexity, "risk": risk,
            "reversible": REVERSIBLE.get(kind, "by reverting the change"), "priority": priority,
            "how": "priority = benefit × confidence ÷ (complexity + risk), lowered a fifth for each earlier attempt that failed"}


def opportunities(kernel, *, refresh: bool = False, by: str = "system") -> list[dict[str, Any]]:
    """What could be improved, best first, from evidence JARVIS already holds. ``refresh`` also writes newly found
    ones (or ones whose evidence at least doubled) to the history; that needs the "propose" autonomy and is skipped
    while the emergency stop is on."""
    from .. import proposals
    from . import Autonomy
    out = []
    for p in proposals.detect(kernel):
        subject = p.key
        attempts = history(kernel, subject=subject, kind="experiment", limit=20)
        failed = sum(1 for a in attempts if a["body"].get("verdict") in ("fails", "flaky", "did not run"))
        decision = _last(kernel, subject, "decision")
        out.append({"subject": subject, "kind": p.kind, "title": p.title, "problem": p.problem, "evidence": p.evidence,
                    "suggestion": p.suggestion, "risk_note": p.risk, "size": p.size, **_rank(p.kind, p.size, failed),
                    "tried_before": [{"seq": a["seq"], "ts": a["ts"], "verdict": a["body"].get("verdict")} for a in attempts[:5]],
                    "last_decision": decision["body"].get("decision") if decision else None})
    out.sort(key=lambda o: -o["priority"])
    if refresh and Autonomy(kernel).can("propose"):
        for o in out:
            seen = _last(kernel, o["subject"], "opportunity")
            if seen is None or o["size"] >= max(2 * seen["body"].get("size", 0), seen["body"].get("size", 0) + 1):
                # names, counts and the detector's own wording only: never the owner's text
                record(kernel, "opportunity", o["subject"], o["title"],
                       {k: o[k] for k in ("kind", "size", "benefit", "confidence", "complexity", "risk", "priority")}, actor=by)
    return out


# ---- 2. the experiment design -----------------------------------------------------------------------------------------
ALTERNATIVES = {
    "code": ["Change a setting or routing rule instead of code, if one covers it.", "Add a test that pins the failure first, and fix nothing yet.",
             "Leave it: accept the failure rate and revisit when the evidence grows."],
    "setting": ["Leave the setting and add a rule for the specific case.", "Leave it as it is and watch for another month."],
    "rule": ["Decide case by case as now (no standing rule).", "A narrower rule covering only the exact resource."],
    "investigate": ["Reproduce it with a benchmark task first.", "Wait for more occurrences before spending time on it."],
}


def design(kernel, subject: str, *, runs: int = 3, by: str = "system") -> dict[str, Any]:
    """The plan for testing one opportunity. Rule-built from the opportunity's own evidence (no model), recorded in
    the history. Raises EvolutionError if the opportunity is no longer found."""
    opp = next((o for o in opportunities(kernel) if o["subject"] == subject), None)
    if opp is None:
        raise EvolutionError("that opportunity is no longer supported by the evidence")
    from . import trial
    runs = max(1, min(MAX_RUNS, int(runs)))
    testable = opp["kind"] == "code"
    d = {
        "subject": subject, "problem": opp["problem"], "evidence": opp["evidence"], "proposed": opp["suggestion"],
        "alternatives": ALTERNATIVES.get(opp["kind"], ALTERNATIVES["investigate"]),
        "success": (["No test that passes now fails with the change, in every one of the runs.", "The linter stays clean.",
                     "The failing case named in the evidence passes (add a test for it if there isn't one)."] if testable else
                    ["The problem's count in the evidence stops growing over the next 30 days.", "Nothing that worked before stops working."]),
        "regression_risks": [opp["risk_note"]] + (["Any change to JARVIS's code can break something else: that is what the full suite is for."] if testable else []),
        "test_plan": ([f"Draft the change in the lab (it writes a patch to src/ and tests/ only).",  # noqa: F541
                       f"Run the full suite and linter on your current code and on the change, {runs} time(s) each, in the sandbox.",
                       "A test that fails in some runs but not others is reported as flaky and does not decide the result.",
                       "A second local model reviews the patch."] if testable else
                      ["No code to test. Try the proposed change yourself; the evidence shows whether it helped."]),
        "budget": {"runs": runs, "time_limit_s_per_run": trial.TIMEOUT, "disk_limit_gb": trial.MAX_DISK // 10**9 if hasattr(trial, "MAX_DISK") else None,
                   "network": "none (this Mac's own test servers only)", "cost": "$0: local models and local tests"},
        "rollback": opp["reversible"], "needs": "autonomy level 6 (Mac terminal) to run a change trial" if testable else "nothing: this is yours to try",
        "testable_in_lab": testable,
    }
    record(kernel, "design", subject, f"Design: {opp['title']}",
           {"runs": runs, "testable": testable, "kind": opp["kind"], "size": opp["size"]}, actor=by)
    return d


# ---- 3. judging repeated runs -------------------------------------------------------------------------------------------
def evaluate(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """One verdict from several runs of the same trial (each a ``trial.run`` result). A change **holds** only if
    every run ran and none shows a regression. Tests whose result differs between runs are **flaky**: listed, and
    they never count for or against. One good run is never enough to call it when others disagree."""
    if not runs:
        return {"verdict": "did not run", "runs": 0, "why": "no run finished"}
    ran = [r for r in runs if r.get("ran")]
    if len(ran) < len(runs):
        return {"verdict": "did not run", "runs": len(runs), "why": f"the tests didn't run in {len(runs) - len(ran)} of {len(runs)} runs, so this proves nothing"}
    cand = [r.get("candidate") or {} for r in runs]
    base = [r.get("baseline") or {} for r in runs]
    per = [set(r.get("newly_failing") or []) for r in runs]
    always, ever = set.intersection(*per), set.union(*per)
    flaky = sorted(ever - always)
    base_fail = [set(b.get("failing") or []) for b in base]
    flaky_base = sorted(set.union(*base_fail) - set.intersection(*base_fail))
    fixed = [set(r.get("newly_passing") or []) for r in runs]
    lint_bad = [c.get("lint") for c in cand if c.get("lint") not in (None, "clean")]
    errors = max((c.get("tests") or {}).get("error", 0) for c in cand)
    secs = sorted(c.get("seconds", 0.0) for c in cand)
    base_secs = sorted(b.get("seconds", 0.0) for b in base)
    if always or errors or lint_bad:
        verdict, why = "fails", (f"{len(always)} test(s) fail with the change in every run" if always else
                                 "the suite reported errors" if errors else f"the linter reports: {lint_bad[0]}")
    elif flaky or flaky_base:
        verdict, why = "flaky", (f"{len(flaky) + len(flaky_base)} test(s) gave different results between runs, so a regression can't be "
                                 "ruled in or out: run it again or fix the flaky test first")
    else:
        verdict, why = "holds", f"no regression in any of {len(runs)} run(s)"
    return {"verdict": verdict, "why": why, "runs": len(runs), "regressions": sorted(always), "flaky": flaky,
            "flaky_on_baseline": flaky_base, "fixed_every_run": sorted(set.intersection(*fixed)),
            "passed": [(c.get("tests") or {}).get("passed", 0) for c in cand],
            "median_seconds": secs[len(secs) // 2], "baseline_median_seconds": base_secs[len(base_secs) // 2],
            "isolation": sorted({r.get("isolation", "?") for r in runs})}


def compare(candidates: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Rank evaluated candidates (name → ``evaluate`` result) on the same criteria, in this order: holds; fixes more
    tests in every run; faster. A winner is named only among those that hold, and only if it is strictly ahead."""
    def key(item):
        _name, e = item
        return (e["verdict"] != "holds", -len(e.get("fixed_every_run", [])), e.get("median_seconds", 1e9))
    ranked = sorted(candidates.items(), key=key)
    holding = [(n, e) for n, e in ranked if e["verdict"] == "holds"]
    winner, why = None, "no candidate held in every run"
    if holding:
        if len(holding) == 1 or key(holding[0])[:2] != key(holding[1])[:2]:
            winner, why = holding[0][0], "it holds and fixes the most tests" if len(holding) > 1 else "it is the only candidate that holds"
        else:
            margin = holding[1][1]["median_seconds"] - holding[0][1]["median_seconds"]
            if margin > 0.1 * max(1.0, holding[1][1]["median_seconds"]):
                winner, why = holding[0][0], "the candidates fix the same tests; this one's suite ran more than 10% faster"
            else:
                why = "the leading candidates are level on every criterion: no winner on this evidence"
    return {"ranking": [{"name": n, "verdict": e["verdict"], "fixed": len(e.get("fixed_every_run", [])),
                         "median_seconds": e.get("median_seconds")} for n, e in ranked],
            "winner": winner, "why": why,
            "criteria": ["holds in every run", "tests fixed in every run", "suite time (only beyond a 10% margin)"]}


# ---- 4. the improvement package -----------------------------------------------------------------------------------------
def package(kernel, experiment_id: str, *, by: str = "system") -> dict[str, Any]:
    """Everything you need to decide on a change that held in the lab. Refused for an experiment that didn't hold:
    a package is a claim that the evidence supports the change."""
    from .drafts import SENSITIVE
    row = kernel.db.one("SELECT * FROM experiments WHERE id = ?", (experiment_id,))
    if not row:
        raise KeyError(experiment_id)
    if row["kind"] not in ("trial", "draft", "contest"):
        raise EvolutionError("only a change trial, a drafted fix or a contest can become a package")
    res = json.loads(row["results"] or "{}")
    ev = res.get("evaluation")
    if row["state"] != "done" or not ev or ev.get("verdict") != "holds":
        raise EvolutionError("this experiment didn't hold (" + ((ev or {}).get("why") or row["state"]) + "), so there is nothing to propose from it")
    draft = res.get("draft") or {}
    files = list(draft.get("files") or res.get("files") or [])
    sensitive = [f for f in files if any(f.startswith(s) for s in SENSITIVE)]
    migration = any(f.endswith("core/db.py") for f in files)
    patch_file = res.get("patch_file")
    cand = res.get("winner_ref") or (res.get("runs") or [{}])[0].get("candidate", {}).get("ref")
    subject = row["opportunity"] or f"experiment:{experiment_id}"
    pkg = {
        "experiment": experiment_id, "subject": subject, "kind": row["kind"],
        "weakness": row["objective"], "original_behaviour": f"Your current code ({row['baseline']}).",
        "proposed_behaviour": row["hypothesis"],
        "evidence": {"verdict": ev["verdict"], "why": ev["why"], "runs": ev["runs"], "tests_passed_per_run": ev["passed"],
                     "tests_fixed_in_every_run": ev["fixed_every_run"], "flaky": ev["flaky"] + ev["flaky_on_baseline"],
                     "isolation": ev["isolation"]},
        "benchmark": {"suite_seconds_with_change": ev["median_seconds"], "suite_seconds_now": ev["baseline_median_seconds"],
                      "note": "Suite time only. Answer quality is measured by `jarvis bench`, which this trial didn't run."},
        "comparison": res.get("comparison"),
        "review": res.get("review"),
        "security": {"touches_security_sensitive_files": sensitive,
                     "note": ("It changes files that guard permissions, approvals, the audit log, the sandbox or sign-in: read every line."
                              if sensitive else "It touches no file on the security-sensitive list."),
                     "sandboxed": ev["isolation"] == ["macOS sandbox"]},
        "files": files, "migration": ("Yes: it changes the database schema file. Back up first (JARVIS does before any upgrade)." if migration
                                      else "No database change."),
        "apply": (f'Review the patch, then in the JARVIS folder: git apply "{patch_file}"' if patch_file else
                  f"Review the branch, then merge it yourself: git merge {cand}" if cand else "See the experiment."),
        "rollback": (f'git apply -R "{patch_file}"' if patch_file else "git revert the merge commit") + ", then restart JARVIS."
                    + (" If the database was upgraded, restore the backup made before the upgrade." if migration else ""),
        "status": "awaiting your decision",
        "jarvis_will_not": "apply, commit, merge or push this. Applying is yours to do.",
    }
    pkg["seq"] = record(kernel, "package", subject, f"Package: {row['objective'][:150]}",
                        {k: pkg[k] for k in ("experiment", "kind", "files", "evidence", "security", "migration")}, actor=by)
    return pkg


def packages(kernel) -> list[dict[str, Any]]:
    """Every package with its current status, worked out from the history: awaiting your decision → approved /
    rejected → applied → rolled back."""
    out = []
    for p in history(kernel, kind="package", limit=200):
        later = [h for h in history(kernel, subject=p["subject"], limit=200)
                 if h["seq"] > p["seq"] and h["kind"] in OWNER_ONLY and h["body"].get("package") == p["seq"]]
        status = "awaiting your decision"
        for h in sorted(later, key=lambda h: h["seq"]):
            status = {"decision": h["body"].get("decision", status), "applied": "applied", "rolled_back": "rolled back"}[h["kind"]]
        out.append({**p, "status": status})
    return out


def decide(kernel, package_seq: int, decision: str, *, by: str) -> None:
    """Your answer on a package: approved (you intend to apply it) or rejected. It changes nothing else."""
    if decision not in ("approved", "rejected"):
        raise EvolutionError("decision must be approved or rejected")
    pkg = next((p for p in packages(kernel) if p["seq"] == package_seq), None)
    if pkg is None:
        raise KeyError(package_seq)
    record(kernel, "decision", pkg["subject"], f"{decision.capitalize()}: {pkg['title'][9:]}", {"package": package_seq, "decision": decision}, actor=by)


def mark(kernel, package_seq: int, what: str, *, by: str) -> None:
    """Your note that you applied a package (after approving it) or rolled it back (after applying it). JARVIS does
    neither; this keeps the history true."""
    if what not in ("applied", "rolled_back"):
        raise EvolutionError("mark must be applied or rolled_back")
    pkg = next((p for p in packages(kernel) if p["seq"] == package_seq), None)
    if pkg is None:
        raise KeyError(package_seq)
    need = "approved" if what == "applied" else "applied"
    if pkg["status"] != need:
        raise EvolutionError(f"a package can be marked {what.replace('_', ' ')} only when it is {need} (it is: {pkg['status']})")
    record(kernel, what, pkg["subject"], f"{what.replace('_', ' ').capitalize()}: {pkg['title'][9:]}", {"package": package_seq}, actor=by)


__all__ = ["EvolutionError", "compare", "decide", "design", "evaluate", "history", "mark", "opportunities", "package",
           "packages", "record"]
