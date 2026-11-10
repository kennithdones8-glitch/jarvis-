"""Objectives (Evolution 4.0, first milestone): an outcome you want, pursued through missions.

An objective is what you want ("the home office is set up by 15 December"), what done means, a priority (1–5) and an
optional deadline. Missions stay ordinary tasks, planned by the usual planner and run by the usual task engine, with
every step through the permission gateway; an objective only ties them together (`links`, rel "mission of") and asks
for the next one. Nothing about a mission is copied here.

Autopilot, chosen per objective by you:
- suggest (default): the suggestions feed says when the next mission is worth planning;
- prepare: when nothing of it is in flight, JARVIS plans the next mission and leaves the plan in Missions for you to Run;
- pursue (only from the Mac): it also runs that plan. Each step still asks you when the rules say it must, exactly as
  when you press Run, so pursue never does anything you'd otherwise have been asked about.
Autopilot stops by itself after two failed missions in a row (the objective is paused and the feed says why), while
the emergency stop is on, and while the autonomy "initiative" pause is on. Achieved is yours to say.

Progress is counted from the missions' real states: done = completed; confirmed = completed and its checks found
everything (a check that couldn't run is "not confirmed", never counted as confirmed).
"""

from __future__ import annotations

import json
import re
import secrets
from datetime import date
from typing import Any

from .core.util import now_iso

STATES = ("active", "paused", "achieved", "abandoned")
TRANSITIONS = {"active": {"paused", "achieved", "abandoned"}, "paused": {"active", "abandoned"},
               "achieved": {"active"}, "abandoned": {"active"}}
AUTOPILOT = ("suggest", "prepare", "pursue")
REL = "mission of"
MAX_FAILS = 2
OPEN_TASK_STATES = ("queued", "planning", "awaiting_approval", "running", "paused", "blocked", "recovering", "verifying")


class ObjectiveError(ValueError):
    pass


def _user(by: str) -> None:
    if not by.startswith("user"):
        raise PermissionError("only you can change an objective")


def _row(kernel, oid: str) -> dict[str, Any]:
    r = kernel.db.one("SELECT * FROM objectives WHERE id = ?", (oid,))
    if not r:
        raise KeyError(oid)
    return dict(r)


def create(kernel, outcome: str, *, criteria: list[str] | None = None, priority: int = 3, deadline: str | None = None,
           by: str) -> dict[str, Any]:
    _user(by)
    outcome = " ".join(str(outcome or "").split())
    if not 3 <= len(outcome) <= 400:
        raise ObjectiveError("say the outcome you want in a few words (up to 400 characters)")
    crit = [" ".join(str(c).split())[:200] for c in (criteria or []) if str(c).strip()][:8]
    if not isinstance(priority, int) or not 1 <= priority <= 5:
        raise ObjectiveError("priority is 1 (low) to 5 (high)")
    if deadline:
        try:
            date.fromisoformat(deadline)
        except (TypeError, ValueError):
            raise ObjectiveError("the deadline is a date like 2026-12-15") from None
    oid = "obj-" + secrets.token_hex(5)
    now = now_iso()
    with kernel.db.tx() as c:
        c.execute("INSERT INTO objectives (id, outcome, criteria, priority, deadline, created_at, updated_at) "
                  "VALUES (?,?,?,?,?,?,?)", (oid, outcome, json.dumps(crit), priority, deadline or None, now, now))
    kernel.audit.record("objective.created", actor=by, objective=oid, priority=priority, criteria=len(crit),
                        deadline=bool(deadline))
    return get(kernel, oid)


def set_state(kernel, oid: str, state: str, *, by: str) -> dict[str, Any]:
    _user(by)
    o = _row(kernel, oid)
    if state not in TRANSITIONS.get(o["state"], set()):
        raise ObjectiveError(f"an objective that is {o['state']} can't become {state}")
    with kernel.db.tx() as c:
        c.execute("UPDATE objectives SET state = ?, updated_at = ? WHERE id = ?", (state, now_iso(), oid))
    kernel.audit.record("objective.state", actor=by, objective=oid, frm=o["state"], to=state)
    return get(kernel, oid)


def set_autopilot(kernel, oid: str, level: str, *, by: str) -> dict[str, Any]:
    """Only you; "pursue" is only allowed from the Mac (the route is Mac-only)."""
    _user(by)
    if level not in AUTOPILOT:
        raise ObjectiveError("autopilot is suggest, prepare or pursue")
    _row(kernel, oid)
    with kernel.db.tx() as c:
        c.execute("UPDATE objectives SET autopilot = ?, updated_at = ? WHERE id = ?", (level, now_iso(), oid))
    kernel.audit.record("objective.autopilot", actor=by, objective=oid, level=level)
    return get(kernel, oid)


def delete(kernel, oid: str, *, by: str) -> None:
    """The objective and its links go; its missions stay in the task history (delete those like any task)."""
    _user(by)
    _row(kernel, oid)
    with kernel.db.tx() as c:
        c.execute("DELETE FROM links WHERE dst = ? AND rel = ?", (oid, REL))
        c.execute("DELETE FROM objectives WHERE id = ?", (oid,))
    kernel.audit.record("objective.deleted", actor=by, objective=oid)


def link_mission(kernel, oid: str, task_id: str, *, source: str) -> None:
    _row(kernel, oid)
    with kernel.db.tx() as c:
        c.execute("INSERT OR IGNORE INTO links (src, dst, rel, source, created_at) VALUES (?,?,?,?,?)",
                  (task_id, oid, REL, source, now_iso()))
        c.execute("UPDATE objectives SET updated_at = ? WHERE id = ?", (now_iso(), oid))


def _confirmed(kernel, task_id: str) -> bool:
    row = kernel.db.one("SELECT payload FROM audit WHERE task_id = ? AND event = 'task.verified' ORDER BY seq DESC LIMIT 1",
                        (task_id,))
    if not row:
        return False
    p = json.loads(row["payload"])
    ev = p.get("evidence") if isinstance(p.get("evidence"), dict) else {}
    return bool(p.get("ok")) and not ev.get("unconfirmed")


def missions(kernel, oid: str) -> list[dict[str, Any]]:
    rows = kernel.db.query("SELECT t.id, t.goal, t.state, t.error, t.created_at, t.updated_at FROM links l "
                           "JOIN tasks t ON t.id = l.src WHERE l.dst = ? AND l.rel = ? ORDER BY t.created_at", (oid, REL))
    out = []
    for r in rows:
        m = dict(r)
        m["confirmed"] = m["state"] == "completed" and _confirmed(kernel, m["id"])
        out.append(m)
    return out


def get(kernel, oid: str) -> dict[str, Any]:
    o = _row(kernel, oid)
    o["criteria"] = json.loads(o["criteria"] or "[]")
    ms = missions(kernel, oid)
    done = [m for m in ms if m["state"] == "completed"]
    o.update(missions=ms, progress={"missions": len(ms), "done": len(done), "confirmed": sum(m["confirmed"] for m in done),
                                    "failed": sum(m["state"] == "failed" for m in ms),
                                    "in_flight": sum(m["state"] in OPEN_TASK_STATES for m in ms)})
    if o["deadline"]:
        o["days_left"] = (date.fromisoformat(o["deadline"]) - date.today()).days
    return o


def list_all(kernel, *, include_closed: bool = True) -> list[dict[str, Any]]:
    rows = kernel.db.query("SELECT id FROM objectives ORDER BY CASE state WHEN 'active' THEN 0 WHEN 'paused' THEN 1 ELSE 2 END, "
                           "priority DESC, COALESCE(deadline, '9999'), created_at")
    out = [get(kernel, r["id"]) for r in rows]
    return out if include_closed else [o for o in out if o["state"] in ("active", "paused")]


def next_request(o: dict[str, Any]) -> str:
    """What the planner is asked for: only the next mission, knowing what is already done and what failed."""
    parts = [f"Objective: {o['outcome']}"]
    if o["criteria"]:
        parts.append("Done means: " + "; ".join(o["criteria"]))
    if o.get("deadline"):
        parts.append(f"Deadline: {o['deadline']}")
    done = [m["goal"] for m in o["missions"] if m["state"] == "completed"]
    failed = [f"{m['goal']} ({(m.get('error') or 'failed')[:80]})" for m in o["missions"] if m["state"] == "failed"][-2:]
    if done:
        parts.append("Already done: " + "; ".join(done[-6:]))
    if failed:
        parts.append("Tried and failed: " + "; ".join(failed))
    parts.append("Plan only the next single mission towards this objective.")
    return "\n".join(parts)[:1500]


def _fails_in_a_row(o: dict[str, Any]) -> int:
    n = 0
    for m in reversed(o["missions"]):
        if m["state"] != "failed":
            break
        n += 1
    return n


def due_for_autopilot(kernel, *, pending: set[str]) -> list[tuple[dict[str, Any], bool]]:
    """Objectives whose autopilot should plan the next mission now: [(objective, run_it)]. ``pending``: objectives
    with a plan already being made or waiting for you. Pauses an objective after MAX_FAILS failures in a row."""
    from .learn import Autonomy
    if kernel.killswitch.engaged() or not Autonomy(kernel).can("propose"):
        return []
    out = []
    for o in list_all(kernel, include_closed=False):
        if o["state"] != "active" or o["autopilot"] == "suggest" or o["id"] in pending or o["progress"]["in_flight"]:
            continue
        if _fails_in_a_row(o) >= MAX_FAILS:
            with kernel.db.tx() as c:
                c.execute("UPDATE objectives SET state = 'paused', updated_at = ? WHERE id = ?", (now_iso(), o["id"]))
            kernel.audit.record("objective.paused_after_failures", objective=o["id"], failures=MAX_FAILS)
            continue
        out.append((o, o["autopilot"] == "pursue"))
    return out


def forget(kernel, query: str, *, by: str, dry_run: bool = True) -> int:
    """Objectives whose outcome or criteria mention ``query`` (part of `jarvis forget`)."""
    q = (query or "").strip().lower()
    if not q:
        return 0
    hits = [r["id"] for r in kernel.db.query("SELECT id, outcome, criteria FROM objectives")
            if q in r["outcome"].lower() or q in r["criteria"].lower()]
    if not dry_run:
        for oid in hits:
            delete(kernel, oid, by=by)
    return len(hits)


def feed_items(kernel, *, now_date: date | None = None) -> list[dict[str, Any]]:
    """Suggestions for the Initiative feed (suggest only), weighted by your priority."""
    from .initiative import _item
    today = now_date or date.today()
    out = []
    for o in list_all(kernel, include_closed=False):
        weight = 1 + (o["priority"] - 1) * 0.125
        p, href = o["progress"], "#/objectives"
        if o["state"] == "paused" and _fails_in_a_row(o) >= MAX_FAILS:
            it = _item(f"objective-stuck:{o['id']}", "objective", f"“{o['outcome'][:70]}” is stuck",
                       f"Its last {MAX_FAILS} missions failed, so autopilot paused it. Look at what went wrong, then resume.",
                       value=3, urgency=3, confidence=1.0, href=href)
        elif o["state"] != "active":
            continue
        elif p["missions"] and p["done"] == p["missions"] and not p["in_flight"]:
            it = _item(f"objective-done:{o['id']}", "objective", f"Is “{o['outcome'][:70]}” achieved?",
                       f"All {p['missions']} of its missions are done ({p['confirmed']} confirmed). Mark it achieved, or plan another.",
                       value=2, urgency=1, confidence=0.8, href=href)
        elif o.get("deadline") and (date.fromisoformat(o["deadline"]) - today).days <= 3 and not p["in_flight"]:
            days = (date.fromisoformat(o["deadline"]) - today).days
            it = _item(f"objective-deadline:{o['id']}", "objective", f"“{o['outcome'][:70]}” is due "
                       + ("today" if days == 0 else "overdue" if days < 0 else f"in {days} day{'s' if days != 1 else ''}"),
                       "Nothing of it is in progress. Plan the next mission?", value=3, urgency=3, confidence=1.0, href=href)
        elif not p["in_flight"] and o["autopilot"] == "suggest":
            it = _item(f"objective-next:{o['id']}", "objective", f"Next step for “{o['outcome'][:70]}”?",
                       "Nothing of it is in progress. JARVIS can plan the next mission for you to check.",
                       value=2, urgency=1, confidence=0.7, href=href)
        else:
            continue
        it["score"] = round(it["score"] * weight, 2)
        out.append(it)
    return out


_ID = re.compile(r"obj-[0-9a-f]{10}")


def valid_id(oid: str) -> bool:
    return bool(_ID.fullmatch(oid or ""))
