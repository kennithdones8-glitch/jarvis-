"""The evolving AI core: JARVIS's look advances only with capabilities verified on this installation.

Each milestone is a check against live state (models answering, a verified mission, a paired phone…). The tier is
the number of milestones verified right now, so it can also go down if something stops working. The first time a
milestone is verified is recorded (meta table + audit log), which is the record of why a visual upgrade unlocked.
Nothing is awarded for activity, time spent, or anything that wasn't checked.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

META_KEY = "evolution.first_verified"
TIERS = (  # (minimum verified milestones, tier number, name)
    (0, 1, "Core"),
    (4, 2, "Development"),
    (7, 3, "Advanced"),
    (10, 4, "Mature"),
)


@dataclass(frozen=True)
class Milestone:
    id: str
    title: str
    evidence: str  # what is checked, in plain words
    check: Callable[[dict[str, Any]], bool]


def _health(facts: dict[str, Any], name: str) -> bool:
    items = (facts.get("health") or {}).get("items") or []
    return any(i["name"] == name and i["ok"] for i in items)


MILESTONES: tuple[Milestone, ...] = (
    Milestone("core_online", "Core online", "database answers and the audit chain verifies",
              lambda f: bool(f["audit_ok"]) and bool(f["db_ok"])),
    Milestone("local_mind", "Local intelligence", "a model on this Mac is answering",
              lambda f: any(p["available"] for p in f["providers"] if p["location"] == "local")),
    Milestone("cloud_mind", "Claude connected", "Claude is signed in and available",
              lambda f: any(p["available"] for p in f["providers"] if p["location"] == "cloud")),
    Milestone("memory", "Memory", "at least one memory you confirmed",
              lambda f: f["confirmed_memories"] > 0),
    Milestone("first_mission", "First verified mission", "a task completed and passed verification",
              lambda f: f["completed_tasks"] > 0),
    Milestone("mac_apps", "Mac apps", "Calendar, Reminders and Notes tools are installed (macOS)",
              lambda f: bool(f["capabilities"].get("mac_apps"))),
    Milestone("voice", "Voice", "the speech recogniser on this Mac is ready",
              lambda f: bool(f["voice_ready"])),
    Milestone("iphone", "iPhone link", "a phone is paired over your tailnet",
              lambda f: f["paired_phones"] > 0),
    Milestone("touch_id", "Touch ID", "a Touch ID key protects the dashboard",
              lambda f: bool(f["touch_id"])),
    Milestone("backups", "Backups verified", "a recent encrypted backup passed its test restore",
              lambda f: _health(f, "Backups")),
    Milestone("benchmark", "Benchmarked", "at least one benchmark run is on record",
              lambda f: bool(f["bench_runs"])),
    Milestone("healthy", "All systems healthy", "every health check passes",
              lambda f: bool((f.get("health") or {}).get("ok"))),
)


def tier_for(count: int) -> tuple[int, str]:
    best = TIERS[0]
    for t in TIERS:
        if count >= t[0]:
            best = t
    return best[1], best[2]


def facts_from(kernel: Any, *, health: dict[str, Any] | None, providers: list[dict[str, Any]],
               capabilities: dict[str, Any], voice_ready: bool, paired_phones: int, touch_id: bool) -> dict[str, Any]:
    db = kernel.db
    try:
        db.one("SELECT 1")
        db_ok = True
    except Exception:
        db_ok = False
    confirmed = db.one("SELECT COUNT(*) FROM memories WHERE origin = 'explicit' OR verified_at IS NOT NULL")[0]
    completed = db.one("SELECT COUNT(*) FROM tasks WHERE state = 'completed'")[0]
    bench_dir = Path(kernel.home) / "bench-results"
    bench_runs = bench_dir.is_dir() and any(p.is_dir() for p in bench_dir.iterdir())
    audit_ok = next((i["ok"] for i in (health or {}).get("items", []) if i["name"] == "Audit log"), None)
    if audit_ok is None:
        audit_ok = kernel.audit.verify().ok
    return {"db_ok": db_ok, "audit_ok": audit_ok, "providers": providers, "confirmed_memories": confirmed,
            "completed_tasks": completed, "capabilities": capabilities, "voice_ready": voice_ready,
            "paired_phones": paired_phones, "touch_id": touch_id, "bench_runs": bench_runs, "health": health}


def evaluate(kernel: Any, facts: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Check every milestone, record first verifications, and return the tier with its evidence."""
    now = now or datetime.now(timezone.utc)
    first = _load(kernel)
    previous_tier, _ = tier_for(sum(1 for m in MILESTONES if m.id in first and first[m.id].get("current")))
    items = []
    changed = False
    for m in MILESTONES:
        try:
            ok = bool(m.check(facts))
        except Exception:
            ok = False
        rec = first.get(m.id)
        if ok and rec is None:
            rec = first[m.id] = {"first": now.isoformat(timespec="seconds"), "current": True}
            kernel.audit.record("evolution.milestone", milestone=m.id)
            changed = True
        elif rec is not None and rec.get("current") != ok:
            rec["current"] = ok
            changed = True
        items.append({"id": m.id, "title": m.title, "evidence": m.evidence, "verified": ok,
                      "first_verified": rec["first"] if rec else None})
    count = sum(1 for i in items if i["verified"])
    tier, name = tier_for(count)
    if tier != previous_tier and first:
        kernel.audit.record("evolution.tier", frm=previous_tier, to=tier, verified=count)
    if changed:
        with kernel.db.tx() as c:
            c.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (META_KEY, json.dumps(first)))
    nxt = next((t for t in TIERS if t[0] > count), None)
    return {"tier": tier, "name": name, "verified": count, "total": len(MILESTONES),
            "next": {"tier": nxt[1], "name": nxt[2], "needs": nxt[0] - count} if nxt else None,
            "milestones": items}


def _load(kernel: Any) -> dict[str, dict[str, Any]]:
    row = kernel.db.one("SELECT value FROM meta WHERE key = ?", (META_KEY,))
    try:
        data = json.loads(row[0]) if row else {}
    except ValueError:
        data = {}
    return data if isinstance(data, dict) else {}
