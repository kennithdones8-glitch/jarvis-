"""Mission Control (Outcome Engine v2): what "done" means for a mission, and checking it.

When a plan is submitted, each step gets a success criterion in plain words, decided by what the step does — never
by a model, and never by whether the tool merely returned:

- a file write: the file exists with exactly the content JARVIS wrote (sha-256), and, after web research, it cites a
  source the research actually saw;
- a Calendar event, a reminder or a note: read back from the app afterwards (the same read-only lookup crash recovery
  uses) — it must really be there;
- a Mail draft, Music and system changes: reported by the app itself (Mail drafts can't be read back reliably), and
  said so;
- reads, lookups and composing: finishing is the point.

The verifier records every criterion with its status: verified, failed, unconfirmed (couldn't check, e.g. Calendar
didn't answer) or reported. A failed criterion fails the mission. Unconfirmed ones leave it completed but never
"verified": the dashboard and the learning engine see the difference.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.tasks import StepState, Verification

READ_BACK = {("calendar", "add"): "the event “{title}” is in Calendar", ("reminders", "add"): "the reminder “{title}” is in Reminders",
             ("notes", "create"): "the note “{title}” is in Notes"}
REPORTED = {("mail", "draft"): "a Mail draft was created (reported by Mail; drafts can't be read back)",
            ("music", "control"): "Music reported the change", ("music", "playlist"): "Music reported the playlist playing",
            ("music", "volume"): "Music reported its new volume", ("system", "volume"): "macOS reported the new volume",
            ("system", "focus"): "your Focus Shortcut ran"}


def _short(v: Any, n: int = 60) -> str:
    s = str(v if v is not None else "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def criterion(tool: str, action: str, args: dict[str, Any], description: str = "") -> dict[str, str]:
    """One step's success criterion (what will be checked, and how)."""
    key = (tool, action)
    if key == ("fs", "write"):
        return {"check": "file", "text": f"the file {_short(args.get('path'))} exists with exactly what was written"}
    if key in READ_BACK:
        title = args.get("title")
        named = isinstance(title, str) and "{{" not in title
        return {"check": "read_back", "text": READ_BACK[key].format(title=_short(title)) if named
                else READ_BACK[key].replace("“{title}” ", "")}
    if key in REPORTED:
        return {"check": "reported", "text": REPORTED[key]}
    return {"check": "finished", "text": f"finished: {_short(description or f'{tool}.{action}', 80)}"}


def criteria_for(steps) -> list[dict[str, Any]]:
    """The mission's definition of success: every step finishes, and each step's own criterion holds."""
    out = []
    for i, s in enumerate(steps):
        c = criterion(s.tool, s.action, s.args, s.description)
        out.append({"step": i, **c})
    return out


def make_verifier(registry, files_check):
    """``files_check``: the existing file/citation verifier (``writes_verified``). Returns the mission verifier."""
    from ..core.tools import RECONCILE_DONE, RECONCILE_NOT_DONE

    def mission_verified(task: dict[str, Any], steps: list[dict[str, Any]]) -> Verification:
        base = files_check(task, steps)
        evidence = dict(base.evidence)
        ok = base.ok
        criteria = task["context"].get("criteria") or criteria_for_rows(steps)
        by_idx = {s["idx"]: s for s in steps}
        files = {f["path"]: f for f in evidence.get("files", [])}
        checks = []
        for c in criteria:
            s = by_idx.get(c["step"])
            status = "verified"
            if s is None or s["state"] not in (StepState.DONE, StepState.SKIPPED):
                status = "failed"
            elif s["state"] == StepState.SKIPPED:
                status = "skipped"
            elif c["check"] == "file":
                f = files.get(str(Path((s["result"] or {}).get("path", "")))) if isinstance(s["result"], dict) else None
                status = "verified" if f and f.get("content_matches") and f.get("verified_sources_cited", 1) else "failed"
            elif c["check"] == "read_back":
                act = registry.action(s["tool"], s["action"])
                result = s["result"] if isinstance(s["result"], dict) else {}
                args = {**(s["args"] or {}), **{k: v for k, v in result.items() if v is not None}}
                try:
                    found = act.reconcile(args, s["op_id"]) if act and act.reconcile else "unknown"
                except Exception:  # noqa: BLE001 - the app didn't answer: unconfirmed, never verified
                    found = "unknown"
                status = "verified" if found == RECONCILE_DONE else "failed" if found == RECONCILE_NOT_DONE else "unconfirmed"
            elif c["check"] == "reported":
                status = "reported"
            checks.append({**c, "status": status})
        failed = [c for c in checks if c["status"] == "failed"]
        unconfirmed = [c for c in checks if c["status"] == "unconfirmed"]
        evidence.update(checks=checks, unconfirmed=len(unconfirmed))
        return Verification(ok and not failed, evidence)

    return mission_verified


def criteria_for_rows(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Criteria for a mission stored before criteria existed (from its step rows)."""
    return [{"step": s["idx"], **criterion(s["tool"], s["action"], s["args"] or {}, s["description"])} for s in steps]
