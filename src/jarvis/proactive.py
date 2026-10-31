"""Proactive JARVIS: the morning briefing, quiet hours and nudges.

- The briefing is built from live state each time it's opened and is never stored, so `forget` and task
  deletion still remove everything. Only the date it was last announced is kept.
- Notifications stay generic ("Your morning briefing is ready"); the content appears after you sign in.
- Quiet hours hold back notifications; what happened overnight is in the next briefing instead.
- Nothing here acts: it reads state and tells you. No model is called and nothing leaves the Mac.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

DEFAULTS = {"enabled": True, "briefing_time": "08:00", "quiet_hours": "22:00-07:00", "approval_reminder_min": 60}
BRIEFING_WINDOW_H = 4  # a "morning" briefing isn't announced more than 4 hours late (e.g. the Mac was asleep)
META_LAST = "briefing.last_date"
META_LAST_AT = "briefing.last_at"
META_SINCE = "briefing.window_start"


def parse_hhmm(text: str) -> tuple[int, int]:
    try:
        hh, mm = (int(x) for x in str(text).split(":"))
    except ValueError:
        raise ValueError(f"expected a time like 08:00, got {text!r}") from None
    if not (0 <= hh < 24 and 0 <= mm < 60):
        raise ValueError(f"expected a time like 08:00, got {text!r}")
    return hh, mm


def validate(cfg: dict[str, Any]) -> dict[str, Any]:
    out = {**DEFAULTS, **cfg}
    parse_hhmm(out["briefing_time"])
    if out["quiet_hours"]:
        start, _, end = str(out["quiet_hours"]).partition("-")
        parse_hhmm(start), parse_hhmm(end)
    if not 5 <= int(out["approval_reminder_min"]) <= 24 * 60:
        raise ValueError("approval_reminder_min must be between 5 and 1440")
    return out


@dataclass
class Schedule:
    enabled: bool = True
    briefing_time: str = "08:00"
    quiet_hours: str = "22:00-07:00"
    approval_reminder_min: int = 60

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> "Schedule":
        v = validate(cfg)
        return cls(bool(v["enabled"]), v["briefing_time"], v["quiet_hours"], int(v["approval_reminder_min"]))

    def quiet(self, now: datetime) -> bool:
        if not self.quiet_hours:
            return False
        start, _, end = self.quiet_hours.partition("-")
        s, e, t = parse_hhmm(start), parse_hhmm(end), (now.hour, now.minute)
        return s <= t < e if s <= e else (t >= s or t < e)

    def briefing_due(self, now: datetime, last_date: str | None) -> bool:
        if not self.enabled or last_date == now.date().isoformat():
            return False
        hh, mm = parse_hhmm(self.briefing_time)
        at = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        return at <= now < at + timedelta(hours=BRIEFING_WINDOW_H)


def _meta(db, key: str) -> str | None:
    row = db.one("SELECT value FROM meta WHERE key = ?", (key,))
    return row[0] if row else None


def _set_meta(db, key: str, value: str) -> None:
    with db.tx() as c:
        c.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))


def last_briefing_date(kernel) -> str | None:
    return _meta(kernel.db, META_LAST)


def mark_briefing_sent(kernel, now: datetime) -> None:
    """Announce today's briefing: it covers everything since the previous one (or the last 24 hours)."""
    prev = _meta(kernel.db, META_LAST_AT)
    ts = now.timestamp()
    _set_meta(kernel.db, META_SINCE, prev if prev and ts - float(prev) < 3 * 86400 else str(ts - 86400))
    _set_meta(kernel.db, META_LAST_AT, str(ts))
    _set_meta(kernel.db, META_LAST, now.date().isoformat())


def build_briefing(kernel, *, health: dict[str, Any] | None = None, now: float | None = None) -> dict[str, Any]:
    """What you'd want to know first thing: what needs you, what happened, what's wrong. Live data only."""
    now = now or time.time()
    since_raw = _meta(kernel.db, META_SINCE)
    since = float(since_raw) if since_raw and now - float(since_raw) < 3 * 86400 else now - 86400
    since_iso = datetime.fromtimestamp(since).astimezone().isoformat()

    def changed_since(t: dict) -> bool:
        try:
            return datetime.fromisoformat(t["updated_at"]).timestamp() >= since
        except (KeyError, ValueError):
            return False

    tasks = kernel.tasks.list(limit=200)
    approvals = kernel.approvals.pending()
    sections: list[dict[str, Any]] = []

    home = str(Path.home())
    needs = [f"Approve: {a['summary'].replace(home, '~')}"
             + (f" → {Path(a['resource']).name}" if a.get("resource") and "/" in a["resource"] else "") for a in approvals] + [f"Blocked: {t['goal']}" for t in tasks if t["state"] == "blocked"]
    if needs:
        sections.append({"title": "Needs you", "items": needs[:10], "alert": True})
    done = [t["goal"] for t in tasks if t["state"] == "completed" and changed_since(t)]
    if done:
        sections.append({"title": "Finished", "items": done[:10]})
    failed = [t["goal"] for t in tasks if t["state"] == "failed" and changed_since(t)]
    if failed:
        sections.append({"title": "Failed", "items": failed[:10], "alert": True})
    running = [t["goal"] for t in tasks if t["state"] in ("queued", "running", "verifying", "recovering")]
    if running:
        sections.append({"title": "In progress", "items": running[:10]})
    systems = []
    stop = kernel.killswitch.state()
    if stop:
        systems.append("The emergency stop is on — new actions are blocked until you release it.")
    for item in (health or {}).get("items", []):
        if not item["ok"]:
            systems.append(f"{item['name']}: {item['detail']}")
    if systems:
        sections.append({"title": "Systems", "items": systems, "alert": True})
    unconfirmed = kernel.memory.counts().get("unconfirmed", 0)
    if unconfirmed:
        sections.append({"title": "Memory", "items": [
            f"{unconfirmed} thing{'s' if unconfirmed != 1 else ''} JARVIS noticed {'are' if unconfirmed != 1 else 'is'} "
            "waiting for you to confirm or delete (Memory panel)."]})
    try:
        usage = [u for u in kernel.models.router.gate.usage_summary() if u["calls"]]
    except Exception:
        usage = []
    if usage:
        sections.append({"title": "Claude usage (last 5 hours)", "items": [
            f"{u['provider']}: {u['calls']} calls" + (" — at the limit" if u["limited_until"] else "") for u in usage]})

    n = len(needs)
    headline = (f"{n} thing{'s' if n != 1 else ''} need{'s' if n == 1 else ''} you." if n
                else "Nothing needs you." if not systems else "Nothing needs a decision, but check Systems.")
    return {"headline": headline, "since": since_iso, "generated_at": now, "sections": sections}


def briefing_text(b: dict[str, Any]) -> str:
    lines = [b["headline"]]
    for s in b["sections"]:
        lines.append(f"\n{s['title']}:")
        lines += [f"  - {i}" for i in s["items"]]
    if len(lines) == 1:
        lines.append("All quiet: nothing finished, failed or broke since the last briefing.")
    return "\n".join(lines)
