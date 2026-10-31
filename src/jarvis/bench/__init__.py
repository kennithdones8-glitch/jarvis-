"""The JARVIS benchmark: fixed tasks, fixed inputs, checks written before any run.

Each task (``bench/tasks/<id>.toml``) states its prompt, the made-up data it starts from (files, memories, calendar,
reminders), which approvals a careful owner would give, and the checks that decide pass/fail. The same tasks are
given to the standalone Claude app as a baseline (``jarvis bench baseline``), scored by the same text checks.

Runs never touch your real data: each task gets its own temporary JARVIS data folder, approved folder, permission
policy (no standing permissions) and a stand-in for the Mac apps seeded from the task.
"""

from __future__ import annotations

import hashlib
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

TASKS_DIR = Path(__file__).resolve().parents[3] / "bench" / "tasks"
CATEGORIES = ("reasoning", "coding", "research", "memory", "planning", "tool_use", "recovery")
SETS = ("core", "extended")  # core: the fixed 12 compared with the Claude-app baseline; extended: more coverage
MODES = ("chat", "do", "research")


class TaskError(ValueError):
    pass


@dataclass
class Task:
    id: str
    category: str
    title: str
    mode: str
    prompt: str
    checks: list[dict[str, Any]]
    time_limit_s: int = 600
    setup: dict[str, Any] = field(default_factory=dict)
    approve: list[str] = field(default_factory=list)
    baseline_context: str = ""
    set: str = "core"
    sha256: str = ""
    path: Path | None = None

    @property
    def needs_claude(self) -> bool:
        return self.mode == "research"


def load_task(path: Path) -> Task:
    raw = path.read_bytes()
    try:
        data = tomllib.loads(raw.decode())
    except tomllib.TOMLDecodeError as exc:
        raise TaskError(f"{path.name}: {exc}") from None
    for key in ("id", "category", "title", "mode", "prompt", "checks"):
        if key not in data:
            raise TaskError(f"{path.name}: missing '{key}'")
    if data["category"] not in CATEGORIES:
        raise TaskError(f"{path.name}: category must be one of {CATEGORIES}")
    if data["mode"] not in MODES:
        raise TaskError(f"{path.name}: mode must be one of {MODES}")
    if data.get("set", "core") not in SETS:
        raise TaskError(f"{path.name}: set must be one of {SETS}")
    if data["id"] != path.stem:
        raise TaskError(f"{path.name}: id must match the file name")
    from .scoring import CHECKS
    for c in data["checks"]:
        if c.get("type") not in CHECKS:
            raise TaskError(f"{path.name}: unknown check type {c.get('type')!r}")
    return Task(id=data["id"], category=data["category"], title=data["title"], mode=data["mode"],
                prompt=data["prompt"].strip(), checks=data["checks"], time_limit_s=int(data.get("time_limit_s", 600)),
                setup=data.get("setup", {}), approve=list(data.get("approve", {}).get("match", [])),
                baseline_context=data.get("baseline", {}).get("context", "").strip(),
                set=data.get("set", "core"), sha256=hashlib.sha256(raw).hexdigest(), path=path)


def load_tasks(ids: list[str] | None = None, directory: Path = TASKS_DIR, *, which: str | None = "core") -> list[Task]:
    """``which``: "core" (default: the fixed 12), "extended", or None for all. Naming tasks by id ignores it."""
    tasks = [load_task(p) for p in sorted(directory.glob("*.toml"))]
    if which is not None and not ids:
        tasks = [t for t in tasks if t.set == which]
    if ids:
        unknown = set(ids) - {t.id for t in tasks}
        if unknown:
            raise TaskError(f"unknown task(s): {', '.join(sorted(unknown))}")
        tasks = [t for t in tasks if t.id in ids]
    return tasks
