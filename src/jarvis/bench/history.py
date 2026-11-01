"""Benchmark history for the dashboard: every run's totals, one run's tasks and failures, and a before/after.

Read-only. Only folders directly inside ``bench-results`` whose names look like a run id are ever opened, so a
request can't name any other file. Benchmark answers contain only the made-up data of the tasks.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .compare import compare

RUN_ID = re.compile(r"\d{8}-\d{6}-(local|hybrid)")
MAX_RUNS = 60


class HistoryError(ValueError):
    pass


def _load(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) and "meta" in data and "results" in data else None
    except (OSError, ValueError):
        return None


def _started(meta: dict[str, Any]) -> str:
    try:
        return datetime.fromisoformat(meta["started"]).isoformat()
    except (KeyError, TypeError, ValueError):
        return ""


def _scored(results: list[dict]) -> list[dict]:
    return [r for r in results if r.get("status") in ("pass", "fail")]


def summary(data: dict[str, Any]) -> dict[str, Any]:
    meta, results = data["meta"], data["results"]
    scored = _scored(results)
    cats: dict[str, list[int]] = {}
    for r in scored:
        c = cats.setdefault(r.get("category", "?"), [0, 0])
        c[0] += r["status"] == "pass"
        c[1] += 1
    return {"run_id": meta.get("run_id"), "started": _started(meta), "version": meta.get("jarvis_version"),
            "commit": meta.get("git_commit"), "models": meta.get("models"), "repeat": meta.get("repeat"),
            "coding_self_test": bool(meta.get("coding_self_test")), "tasks": len({r["id"] for r in results}),
            "passed": sum(r["status"] == "pass" for r in scored), "scored": len(scored),
            "skipped": sum(r.get("status") == "skipped" for r in results),
            "claude_calls": sum(int((r.get("usage") or {}).get("claude_calls", 0)) for r in results),
            "categories": {k: {"passed": v[0], "scored": v[1]} for k, v in sorted(cats.items())}}


def runs(out_dir: Path) -> list[dict[str, Any]]:
    """Newest first, by the recorded start time (folder names repeat when the clocks go back)."""
    found = []
    for d in out_dir.glob("*") if out_dir.is_dir() else []:
        if RUN_ID.fullmatch(d.name) and (data := _load(d / "results.json")):
            found.append(summary(data))
    # by the instant, not the text: "01:34-04:00" is earlier than "01:31-05:00"
    found.sort(key=lambda s: datetime.fromisoformat(s["started"]) if s["started"] else datetime.min.replace(tzinfo=timezone.utc),
               reverse=True)
    return found[:MAX_RUNS]


def _open(out_dir: Path, run_id: str) -> dict[str, Any]:
    if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
        raise HistoryError("not a benchmark run id")
    data = _load(out_dir / run_id / "results.json")
    if data is None:
        raise HistoryError("no such run")
    return data


def detail(out_dir: Path, run_id: str) -> dict[str, Any]:
    data = _open(out_dir, run_id)
    tasks: dict[str, dict[str, Any]] = {}
    for r in data["results"]:
        t = tasks.setdefault(r["id"], {"id": r["id"], "title": r.get("title", ""), "category": r.get("category", ""),
                                       "passed": 0, "scored": 0, "skipped": 0, "seconds": [], "failure": None})
        if r.get("status") == "skipped":
            t["skipped"] += 1
            continue
        if r.get("status") not in ("pass", "fail"):
            continue
        t["scored"] += 1
        t["passed"] += r["status"] == "pass"
        t["seconds"].append(r.get("seconds", 0))
        if r["status"] == "fail" and t["failure"] is None:
            t["failure"] = {
                "run": r.get("run", 1),
                "failed": [f"{c['type']}: {str(c['detail'])[:240]}" for c in r.get("checks", [])
                           if c.get("passed") is False],
                "error": (str(r["error"])[:240] if r.get("error") else None),
                "checked": r.get("checked") or [], "lookup_notes": (r.get("lookup_notes") or [])[:6],
                "approvals": [{"call": f"{a['tool']}.{a['action']}", "summary": str(a.get("summary", ""))[:100],
                               "approved": bool(a.get("approved"))} for a in r.get("approvals") or []],
                "plan_kind": r.get("plan_kind"),
                "answer": (r.get("answer") or "")[:1200],
            }
    for t in tasks.values():
        secs = t.pop("seconds")
        t["avg_seconds"] = round(sum(secs) / len(secs), 1) if secs else None
    return {"summary": summary(data), "tasks": sorted(tasks.values(), key=lambda t: (t["category"], t["id"]))}


def before_after(out_dir: Path, before: str | None = None, after: str | None = None) -> dict[str, Any]:
    """Defaults to the two latest runs. The verdict uses the owner's merge rule (see compare.py)."""
    if not before or not after:
        latest = runs(out_dir)[:2]
        if len(latest) < 2:
            raise HistoryError("needs at least two runs")
        after, before = latest[0]["run_id"], latest[1]["run_id"]
    c = compare(_open(out_dir, before), _open(out_dir, after))
    return {"before": summary(_open(out_dir, before)), "after": summary(_open(out_dir, after)), "rows": c.rows,
            "net": c.net, "fixed": c.fixed, "new_failures": c.new_failures, "left_out": c.left_out,
            "claude": list(c.claude), "violations": c.violations, "merge": c.merge, "reasons": c.reasons}
