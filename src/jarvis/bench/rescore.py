"""Re-score a finished benchmark run after a task's *text* checks were corrected (owner-approved, 0.18.1).

Fixing a check that was too strict or too loose must judge old and new runs by the same rule, or a before/after
comparison is unfair. This re-applies the current text checks (contains, regex, number) to the answers saved in
the run. Everything else keeps its recorded result: file, approval, Mac-call and code checks can't be redone
after the fact, so they must be unchanged, in the same order. The task's prompt and setup must be unchanged too:
the old definition is looked up in git by its recorded hash and compared, so a re-scored task is the same
question with only its text checks corrected. Anything that can't be verified is refused and listed.

The original ``results.json`` is never modified; the re-scored copy is ``results.rescored.json`` beside it, with
the changes recorded in its ``meta.rescored``. ``bench compare --rescored`` uses it, labelled "(rescored)".
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import tomllib
from datetime import datetime
from pathlib import Path
from typing import Any

from . import TASKS_DIR, load_task
from .compare import RESCORED
from .scoring import CHECKS

TEXT_CHECKS = {"contains_all", "contains_any", "not_contains", "regex", "number"}
EXTRA = {"no_unapproved_changes", "ran"}  # added by score() itself, not by the task


def _old_definition(task_file: Path, sha: str) -> bytes | None:
    """The task file's content at the commit where its sha256 was ``sha`` (searched in git history)."""
    try:
        repo = subprocess.run(["git", "-C", str(task_file.parent), "rev-parse", "--show-toplevel"],
                              capture_output=True, text=True, timeout=20, check=True).stdout.strip()
        rel = task_file.resolve().relative_to(Path(repo).resolve()).as_posix()
        commits = subprocess.run(["git", "-C", repo, "log", "--format=%H", "--", rel],
                                 capture_output=True, text=True, timeout=30, check=True).stdout.split()
        for commit in commits:
            raw = subprocess.run(["git", "-C", repo, "show", f"{commit}:{rel}"], capture_output=True, timeout=20)
            if raw.returncode == 0 and hashlib.sha256(raw.stdout).hexdigest() == sha:
                return raw.stdout
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return None


def _why_not(old: dict[str, Any], new: dict[str, Any]) -> str | None:
    """Why this task can't be re-scored, or None if only its text checks differ."""
    strip = lambda d: {k: v for k, v in d.items() if k != "checks"}  # noqa: E731
    if strip(old) != strip(new):
        return "its prompt or setup changed, so old answers answered a different question: run it again"
    other = lambda d: [c for c in d.get("checks", []) if c.get("type") not in TEXT_CHECKS]  # noqa: E731
    if other(old) != other(new):
        return "a non-text check changed (file, approval, Mac or code checks can't be redone afterwards)"
    return None


def _regrade(row: dict[str, Any], checks: list[dict[str, Any]]) -> dict[str, Any]:
    stored = [c for c in row.get("checks", []) if c.get("type") not in EXTRA]
    stored_other = iter(c for c in stored if c.get("type") not in TEXT_CHECKS)
    results = []
    for c in checks:
        if c["type"] in TEXT_CHECKS:
            ok, detail = CHECKS[c["type"]]({"answer": row.get("answer") or ""}, c)
            results.append({"type": c["type"], "passed": ok, "detail": detail})
        else:
            results.append(next(stored_other))
    results += [c for c in row.get("checks", []) if c.get("type") in EXTRA]
    failed = any(r["passed"] is False for r in results)
    partial = any(r["passed"] is None for r in results)
    status = "fail" if failed else "partial" if partial else "pass"
    return {**row, "checks": results, "status": status, "passed": status == "pass"}


def rescore(run_dir: Path, tasks_dir: Path = TASKS_DIR) -> dict[str, Any]:
    """Write ``results.rescored.json`` for ``run_dir``. Returns what changed and what was refused."""
    data = json.loads((run_dir / "results.json").read_text())
    meta, hashes = dict(data["meta"]), dict(data["meta"].get("tasks", {}))
    changed: dict[str, dict[str, Any]] = {}
    refused: dict[str, str] = {}
    for tid, old_sha in data["meta"].get("tasks", {}).items():
        path = tasks_dir / f"{tid}.toml"
        if not path.exists():
            refused[tid] = "the task no longer exists"
            continue
        task = load_task(path)
        if task.sha256 == old_sha:
            continue  # unchanged task: nothing to do
        raw = _old_definition(path, old_sha)
        if raw is None:
            refused[tid] = "its old definition isn't in git history, so the change can't be verified"
            continue
        why = _why_not(tomllib.loads(raw.decode()), tomllib.loads(path.read_text()))
        if why:
            refused[tid] = why
            continue
        counts = {"before": 0, "after": 0, "runs": 0}
        rows = []
        for row in data["results"]:
            if row.get("id") == tid and row.get("status") in ("pass", "fail", "partial"):
                new = _regrade(row, task.checks)
                counts["runs"] += 1
                counts["before"] += row.get("status") == "pass"
                counts["after"] += new["status"] == "pass"
                row = new
            rows.append(row)
        data["results"] = rows
        hashes[tid] = task.sha256
        changed[tid] = counts
    meta["tasks"] = hashes
    meta["rescored"] = {"at": datetime.now().astimezone().isoformat(), "from": "results.json",
                        "tasks": changed, "refused": refused}
    (run_dir / RESCORED).write_text(json.dumps({"meta": meta, "results": data["results"]}, indent=2, default=str))
    return {"changed": changed, "refused": refused, "path": str(run_dir / RESCORED)}
