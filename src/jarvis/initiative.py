"""The Initiative feed (Opportunity Radar + Initiative Engine, Evolution 3.0 phase 3): one ranked list of things worth
your attention, gathered from what JARVIS already tracks. It suggests; it never does. Every item links to the place
where you decide (a mission, a proposal, a project, a lesson), and nothing in it runs anything.

Sources (no new detectors, no model calls, nothing leaves the Mac):
- a mission that failed in the last 7 days and can still be planned again (Mission Control);
- something wrong right now (failing health checks the dashboard already runs);
- an active project that hasn't moved for 7 days with steps left;
- lessons that contradict each other (a "hypothesis" waiting for your judgement);
- open improvement proposals (proposals.py) and new project ideas (projects.py).

Ranking: score = (2 × urgency + value) × (0.5 + 0.5 × confidence), each on a fixed scale set by the source, so the
order can be explained. Dismissing an item hides it for 30 days (a failing health check: one day), or until its
evidence has at least doubled; the feed says how many are hidden.
With the autonomy "initiative" pause on (or level 5 off, or the emergency stop) the feed is empty and says why.
Notifications: at most one a day, never in quiet hours, generic ("JARVIS has a suggestion"), never the item itself.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from .core.util import now_iso

DISMISSED = "initiative.dismissed"
NOTIFIED = "initiative.notified_date"
DISMISS_DAYS = 30
DISMISS_DAYS_BY_SOURCE = {"health": 1}   # a real problem only steps aside for a day
STALL_DAYS = 7
NOTIFY_SCORE = 6.0   # only a suggestion this strong is worth a notification


def _meta(db, key: str, default: str) -> str:
    row = db.one("SELECT value FROM meta WHERE key = ?", (key,))
    return row["value"] if row else default


def _put(db, key: str, value: str) -> None:
    with db.tx() as c:
        c.execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


def _item(key: str, source: str, title: str, why: str, *, value: int, urgency: int, confidence: float, size: int = 1,
          href: str = "") -> dict[str, Any]:
    score = round((2 * urgency + value) * (0.5 + 0.5 * max(0.0, min(1.0, confidence))), 2)
    return {"key": key, "source": source, "title": title[:160], "why": why[:300], "value": value, "urgency": urgency,
            "confidence": round(confidence, 2), "score": score, "size": size, "href": href}


def _days_ago(iso: str | None, now: datetime) -> float:
    try:
        return (now - datetime.fromisoformat(iso)).total_seconds() / 86400
    except (TypeError, ValueError):
        return 0.0


def candidates(kernel, *, health: dict[str, Any] | None = None, now: datetime | None = None) -> list[dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    db, out = kernel.db, []
    since = (now - timedelta(days=7)).isoformat()
    for t in db.query("SELECT id, goal, error, context, updated_at FROM tasks WHERE state = 'failed' AND updated_at >= ? "
                      "ORDER BY updated_at DESC LIMIT 5", (since,)):
        ctx = json.loads(t["context"] or "{}")
        if ctx.get("replan_of") or db.one("SELECT 1 FROM plan_jobs WHERE replan_of = ?", (t["id"],)) \
                or db.one("SELECT 1 FROM tasks WHERE json_extract(context, '$.replan_of') = ?", (t["id"],)):
            continue
        out.append(_item(f"mission-failed:{t['id']}", "mission", f"Try “{t['goal'][:80]}” again?",
                         f"It failed: {(t['error'] or 'a step failed')[:160]}. JARVIS can plan it once more, knowing what happened.",
                         value=2, urgency=3, confidence=1.0, href=f"#/missions/{t['id']}"))
    for item in (health or {}).get("items", []):
        if not item.get("ok"):
            out.append(_item(f"health:{item.get('name')}", "health", f"{item.get('name')} needs attention",
                             str(item.get("detail") or item.get("fix") or "A health check is failing.")[:200],
                             value=3, urgency=3, confidence=1.0, href="#/command"))
    for p in db.query("SELECT id, title, body, updated_at FROM project_ideas WHERE state = 'active'"):
        steps = json.loads(p["body"]).get("steps", [])
        left = [s for s in steps if not s.get("done")]
        if left and _days_ago(p["updated_at"], now) >= STALL_DAYS:
            out.append(_item(f"project-stalled:{p['id']}", "project", f"Pick up “{p['title'][:80]}”?",
                             f"No progress for {int(_days_ago(p['updated_at'], now))} days; next: {left[0].get('text', '')[:120]}",
                             value=2, urgency=2, confidence=0.8, href="#/projects"))
    contested = db.query("SELECT id, subject, statement FROM lessons WHERE state = 'active' AND kind = 'hypothesis' "
                         "ORDER BY last_seen DESC LIMIT 5")
    for les in contested:
        out.append(_item(f"lesson-contested:{les['subject']}", "lesson", f"Evidence disagrees about {les['subject'][:60]}",
                         f"{les['statement'][:200]} Confirm or reject it in the Evolution center.",
                         value=2, urgency=1, confidence=0.6, href="#/evolution"))
    for p in db.query("SELECT id, key, title, body FROM proposals WHERE state = 'open' ORDER BY updated_at DESC LIMIT 10"):
        body = json.loads(p["body"])
        size = int(body.get("size") or len(body.get("evidence") or []) or 1)
        out.append(_item(f"proposal:{p['key']}", "proposal", p["title"], str(body.get("problem") or "")[:200],
                         value=min(3, 1 + size // 5), urgency=1, confidence=min(1.0, 0.4 + 0.1 * size), size=size, href="#/intelligence"))
    for p in db.query("SELECT id, title, body FROM project_ideas WHERE state = 'open' ORDER BY created_at DESC LIMIT 3"):
        out.append(_item(f"project-idea:{p['id']}", "project", p["title"], str(json.loads(p["body"]).get("why") or "")[:200],
                         value=2, urgency=1, confidence=0.5, href="#/projects"))
    return out


def feed(kernel, *, health: dict[str, Any] | None = None, now: datetime | None = None, limit: int = 8) -> dict[str, Any]:
    from .learn import Autonomy
    if not Autonomy(kernel).can("propose"):
        why = "the emergency stop is on" if kernel.killswitch.engaged() else "initiative is paused (or autonomy level 5 is off)"
        return {"paused": True, "why": why, "items": []}
    now = now or datetime.now(timezone.utc)
    dismissed = json.loads(_meta(kernel.db, DISMISSED, "{}"))
    items, seen, hidden = [], set(), 0
    for it in sorted(candidates(kernel, health=health, now=now), key=lambda x: -x["score"]):
        if it["key"] in seen:
            continue
        seen.add(it["key"])
        d = dismissed.get(it["key"])
        days = DISMISS_DAYS_BY_SOURCE.get(it["source"], DISMISS_DAYS)
        if d and _days_ago(d["at"], now) < days and it["size"] < 2 * max(1, d.get("size", 1)):
            hidden += 1
            continue
        items.append(it)
    return {"paused": False, "items": items[:limit], "hidden": hidden}


def dismiss(kernel, key: str, *, by: str, size: int = 1) -> None:
    if not by.startswith("user"):
        raise PermissionError("only you can dismiss a suggestion")
    d = json.loads(_meta(kernel.db, DISMISSED, "{}"))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=DISMISS_DAYS)).isoformat()
    d = {k: v for k, v in d.items() if v["at"] >= cutoff}   # old dismissals expire
    d[key[:200]] = {"at": now_iso(), "size": int(size)}
    _put(kernel.db, DISMISSED, json.dumps(d))
    kernel.audit.record("initiative.dismissed", actor=by, source=key.split(":", 1)[0])


def should_notify(kernel, *, health: dict[str, Any] | None = None, now: datetime | None = None) -> bool:
    """One generic notification a day at most, for a strong suggestion; the caller checks quiet hours."""
    now = now or datetime.now(timezone.utc)
    today = now.astimezone().date().isoformat()
    if _meta(kernel.db, NOTIFIED, "") == today:
        return False
    top = feed(kernel, health=health, now=now)["items"]
    if not top or top[0]["score"] < NOTIFY_SCORE:
        return False
    _put(kernel.db, NOTIFIED, today)
    return True
