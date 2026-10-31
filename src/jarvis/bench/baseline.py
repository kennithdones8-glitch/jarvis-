"""The standalone baseline: the same tasks, done by you in the Claude app, scored by the same text checks.

B0 ("as you'd really use it"): just the prompt; you add whatever you normally would.
B1 ("same information"): the prompt plus every file, fact and calendar entry JARVIS starts with.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from . import Task
from .scoring import score

ANSWER_MARK = "PASTE CLAUDE'S ANSWER BELOW THIS LINE"


def context_text(task: Task, now: datetime | None = None) -> str:
    now = now or datetime.now().astimezone()
    s, parts = task.setup, []
    if s.get("memories"):
        parts.append("Things I told you before:\n" + "\n".join(f"- {m}" for m in s["memories"]))
    if s.get("forget"):
        parts.append("Afterwards I asked you to forget anything about: " + ", ".join(s["forget"]))
    mac = s.get("mac", {})
    if mac.get("events"):
        parts.append("My calendar:\n" + "\n".join(
            f"- {(now + timedelta(days=e.get('day', 0))):%A %d %B}, {e['start']}–{e['end']}: {e['title']}" for e in mac["events"]))
    if mac.get("reminders"):
        parts.append("My reminders:\n" + "\n".join(
            f"- {r['title']}" + (f" (due {(now + timedelta(days=r['due_day'])):%A %d %B} {r.get('due_time', '09:00')})"
                                 if "due_day" in r else "") for r in mac["reminders"]))
    for f in s.get("files", []):
        parts.append(f"File {f['path']}:\n{f['content'].strip()}")
    if task.baseline_context:
        parts.append(task.baseline_context)
    return "\n\n".join(parts)


def template(tasks: list[Task], *, b1: bool) -> str:
    kind = "B1 · same information" if b1 else "B0 · as you'd really use it"
    lines = [f"# JARVIS benchmark baseline ({kind})", "",
             "For each task: open a NEW chat in the Claude app (same model as JARVIS uses for hard work, e.g. Sonnet), "
             "paste the prompt" + (" and the context" if b1 else "") + ", and paste Claude's final answer under the line. "
             "Write how long it took and what you had to do (uploads, copy/pastes, follow-up messages).", ""]
    for t in tasks:
        lines += [f"## {t.id}", f"*{t.title}* · {t.category}", "", "### Prompt", t.prompt, ""]
        ctx = context_text(t)
        if b1 and ctx:
            lines += ["### Context to paste with it", ctx, ""]
        lines += ["time: ", "effort: ", "", ANSWER_MARK, "", ""]
    return "\n".join(lines)


def parse(text: str) -> dict[str, dict[str, str]]:
    out = {}
    for block in re.split(r"(?m)^## ", text)[1:]:
        tid = block.splitlines()[0].strip()
        answer = block.split(ANSWER_MARK, 1)[1].strip() if ANSWER_MARK in block else ""
        meta = {k: (re.search(rf"(?m)^{k}:[ \t]*(.*)$", block) or [None, ""])[1].strip() for k in ("time", "effort")}
        out[tid] = {"answer": answer, **meta}
    return out


def score_file(path: Path, tasks: list[Task]) -> dict:
    answers = parse(path.read_text())
    results = []
    for t in tasks:
        a = answers.get(t.id)
        if not a or not a["answer"]:
            results.append({"id": t.id, "category": t.category, "status": "missing", "passed": False, "checks": []})
            continue
        outcome = {"answer": a["answer"], "files": None, "mac_calls": None, "approvals": None, "tool_calls": None,
                   "plan_kind": None, "sources": None, "violations": None, "error": None}
        graded = score(outcome, t.checks)
        results.append({"id": t.id, "category": t.category, "time": a["time"], "effort": a["effort"], **graded})
    out = path.with_suffix(".results.json")
    out.write_text(json.dumps({"file": str(path), "scored": datetime.now().astimezone().isoformat(),
                               "results": results}, indent=2))
    return {"path": out, "results": results}
