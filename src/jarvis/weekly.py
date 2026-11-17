"""Weekly review: what happened in the last seven days, counted from what JARVIS already records.

Everything here is read from the database: the tasks table (your missions and how they ended), the approvals table
(the decisions you made), the objectives you set, and the hash-chained audit log (models used, refusals, backups,
errors). Nothing is estimated or written by a model, and nothing is changed. If the audit log's chain doesn't verify,
the review says so first, because then the counts may be incomplete.

It is available on the Weekly review page at any time; on Sundays (or the first day you open JARVIS after one) a
"Your week" item appears in "Worth your attention" until you've looked at it.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

DAYS = 7
SEEN = "weekly.seen"            # the ISO week (e.g. 2026-W46) whose review you last opened
DONE, FAILED, STOPPED = "completed", "failed", "cancelled"
OPEN = ("queued", "planning", "awaiting_approval", "running", "paused", "blocked", "recovering", "verifying")
AUDIT_EVENTS = ("model.local_call", "egress.send", "permission.denied", "egress.denied", "emergency_stop.engaged",
                "memory.added", "backup.created", "backup.failed", "tool.error", "tool.start", "task.verified",
                "objective.autoplanned", "update.finished")


def _since(now: datetime, days: int) -> str:
    return (now - timedelta(days=days)).astimezone(timezone.utc).isoformat(timespec="microseconds")


def review(kernel, *, now: datetime | None = None, days: int = DAYS) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    since = _since(now, days)
    tasks = [dict(r) for r in kernel.db.query(
        "SELECT id, goal, state, error, created_at, updated_at FROM tasks WHERE created_at >= ? ORDER BY created_at",
        (since,))]
    by_state = Counter(t["state"] for t in tasks)
    approvals = Counter(r["state"] for r in kernel.db.query(
        "SELECT state FROM approvals WHERE created_at >= ?", (since,)))
    rows = kernel.db.query(
        f"SELECT event, task_id, payload FROM audit WHERE ts >= ? AND event IN ({','.join('?' * len(AUDIT_EVENTS))})",
        (since, *AUDIT_EVENTS))
    ev = Counter(r["event"] for r in rows)
    ids = {t["id"] for t in tasks}
    last_check = {r["task_id"]: json.loads(r["payload"]).get("ok") is True   # the latest verification of each mission
                  for r in rows if r["event"] == "task.verified" and r["task_id"] in ids}
    verified = Counter(last_check.values())
    objectives = []
    for o in kernel.db.query("SELECT id, outcome, state, updated_at FROM objectives ORDER BY priority DESC"):
        moved = kernel.db.query(
            "SELECT t.state FROM links l JOIN tasks t ON t.id = l.src WHERE l.dst = ? AND l.rel = 'mission of' "
            "AND t.updated_at >= ?", (o["id"], since))
        if o["state"] in ("active", "paused") or o["updated_at"] >= since:
            objectives.append({"id": o["id"], "outcome": o["outcome"], "state": o["state"],
                               "missions_moved": len(moved),
                               "missions_done": sum(m["state"] == DONE for m in moved)})
    chain = kernel.audit.verify()
    out = {
        "from": since, "to": now.astimezone(timezone.utc).isoformat(timespec="seconds"), "days": days,
        "week": iso_week(now),
        "audit_ok": chain.ok,
        "missions": {"started": len(tasks), "completed": by_state[DONE], "failed": by_state[FAILED],
                     "cancelled": by_state[STOPPED], "open": sum(by_state[s] for s in OPEN),
                     "verified": verified[True], "not_verified": verified[False],
                     "list": [{"id": t["id"], "goal": t["goal"], "state": t["state"]} for t in tasks[-12:][::-1]]},
        "decisions": {"asked": sum(approvals.values()), "approved": approvals["approved"] + approvals["consumed"],
                      "rejected": approvals["rejected"], "expired": approvals["expired"],
                      "waiting": approvals["pending"]},
        "objectives": objectives,
        "models": {"on_mac": ev["model.local_call"], "claude": ev["egress.send"]},
        "safety": {"refused_by_rules": ev["permission.denied"], "kept_private": ev["egress.denied"],
                   "emergency_stops": ev["emergency_stop.engaged"]},
        "memory": {"added": ev["memory.added"]},
        "upkeep": {"backups": ev["backup.created"], "backup_failures": ev["backup.failed"],
                   "updates": ev["update.finished"], "tool_runs": ev["tool.start"], "tool_errors": ev["tool.error"]},
    }
    out["headline"] = headline(out)
    return out


def headline(r: dict[str, Any]) -> str:
    m, d = r["missions"], r["decisions"]
    if not (m["started"] or d["asked"] or r["models"]["on_mac"] or r["models"]["claude"]):
        return "A quiet week: no missions, decisions or chats recorded."
    parts = [f"{m['started']} mission{'s' * (m['started'] != 1)} started, {m['completed']} completed"
             + (f", {m['failed']} failed" if m["failed"] else "")]
    if d["asked"]:
        parts.append(f"{d['asked']} decision{'s' * (d['asked'] != 1)} ({d['approved']} approved, {d['rejected']} declined)")
    if r["safety"]["refused_by_rules"]:
        parts.append(f"your rules refused {r['safety']['refused_by_rules']} action{'s' * (r['safety']['refused_by_rules'] != 1)}")
    return "; ".join(parts) + "."


def iso_week(now: datetime) -> str:
    y, w, _ = now.astimezone().isocalendar()
    return f"{y}-W{w:02d}"


def _meta(kernel, key: str) -> str | None:
    row = kernel.db.one("SELECT value FROM meta WHERE key = ?", (key,))
    return row["value"] if row else None


def due(kernel, *, now: datetime | None = None) -> bool:
    """Show "Your week" from Sunday until you open this week's review (Monday and later still count the week before
    if you haven't looked; the week label is the one that just ended)."""
    now = (now or datetime.now(timezone.utc)).astimezone()
    week = iso_week(now if now.isoweekday() == 7 else now - timedelta(days=now.isoweekday()))
    return now.isoweekday() in (7, 1, 2) and _meta(kernel, SEEN) != week


def mark_seen(kernel, *, now: datetime | None = None) -> None:
    now = (now or datetime.now(timezone.utc)).astimezone()
    week = iso_week(now if now.isoweekday() == 7 else now - timedelta(days=now.isoweekday()))
    with kernel.db.tx() as c:
        c.execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                  (SEEN, week))


def as_text(r: dict[str, Any]) -> str:
    m, d, s, u = r["missions"], r["decisions"], r["safety"], r["upkeep"]
    lines = [f"Your week ({r['from'][:10]} to {r['to'][:10]})", r["headline"], ""]
    if not r["audit_ok"]:
        lines.insert(1, "WARNING: the audit log's chain doesn't verify, so these counts may be incomplete.")
    lines += [f"Missions: {m['started']} started · {m['completed']} completed ({m['verified']} verified) · "
              f"{m['failed']} failed · {m['cancelled']} stopped · {m['open']} still open",
              f"Decisions: {d['asked']} asked · {d['approved']} approved · {d['rejected']} declined · "
              f"{d['expired']} expired · {d['waiting']} waiting",
              f"Models: {r['models']['on_mac']} calls on this Mac · {r['models']['claude']} to Claude",
              f"Safety: {s['refused_by_rules']} refused by your rules · {s['kept_private']} kept private · "
              f"{s['emergency_stops']} emergency stops",
              f"Memory: {r['memory']['added']} added · Backups: {u['backups']} made, {u['backup_failures']} failed · "
              f"Tools: {u['tool_runs']} runs, {u['tool_errors']} errors"]
    for o in r["objectives"]:
        lines.append(f"Objective “{o['outcome']}” ({o['state']}): {o['missions_moved']} mission(s) moved, "
                     f"{o['missions_done']} done")
    return "\n".join(lines)


__all__ = ["DAYS", "as_text", "due", "headline", "iso_week", "mark_seen", "review"]
