"""The evolving projection: JARVIS's look advances only with capabilities verified on this installation.

Each milestone is a check against live state (models answering, a verified mission, a paired phone…).

- **Evidence-based:** a milestone counts while it verifies, and for ``GRACE_DAYS`` after it last verified (owner's
  choice: an earned stage holds for 7 days, so a brief outage doesn't undo it). After that it stops counting.
- **Persistent:** the first and last verification of each milestone are stored (meta table); every first
  verification, stage change and definitions change is in the audit log.
- **Versionable:** ``DEFINITION_VERSION`` is stored with the record; a change of definitions is audited.
- **Reversible / configurable:** the stage drops when capabilities are lost; a device may also choose to *show* a
  lower stage (the dashboard's Evolution record), which never changes the record.

Nothing is awarded for activity, time spent, or anything that wasn't checked, and a stage is a description of what
was verified, not a claim of intelligence.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

META_KEY = "evolution.first_verified"   # per milestone: first / last verification (name kept for existing data)
VERSION_KEY = "evolution.version"
STAGE_KEY = "evolution.stage"
DEFINITION_VERSION = 4   # 4: five stages (Signature: every milestone verified, including 30 days reliable)
CHECK_KEY = "evolution.check."         # + doctor / mac_check / drill: the last real run's outcome on this install
CHECK_FRESH_DAYS = 30
BENCH_PASS = 0.8                       # share of scored benchmark tasks passing (e.g. 18 of 22)
RELIABLE_DAYS = 30
GRACE_DAYS = 7
LAST_REFRESH = timedelta(hours=1)        # how often "last verified" is rewritten while a milestone keeps verifying
TIERS = (  # (minimum counting milestones, stage number, name)
    (0, 1, "Foundational Projection"),
    (5, 2, "Advanced Projection"),
    (10, 3, "Intelligence Projection"),
    (15, 4, "Evolved Projection"),
    (19, 5, "Signature Projection"),   # every milestone, including 30 days reliable and 100 verified missions
)
STAGE_NAMES = [t[2] for t in TIERS]


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
    Milestone("bench_pass", "Benchmark pass", f"the latest `jarvis bench` run passed at least {int(BENCH_PASS * 100)}% of scored tasks",
              lambda f: (f.get("bench_latest") or 0) >= BENCH_PASS),
    Milestone("missions_5", "5 verified missions", "5 tasks completed and passed verification",
              lambda f: f["completed_tasks"] >= 5),
    Milestone("missions_25", "25 verified missions", "25 tasks completed and passed verification",
              lambda f: f["completed_tasks"] >= 25),
    Milestone("missions_100", "100 verified missions", "100 tasks completed and passed verification",
              lambda f: f["completed_tasks"] >= 100),
    Milestone("doctor_green", "Installation check", f"the last `jarvis doctor` was all green (within {CHECK_FRESH_DAYS} days)",
              lambda f: (f.get("checks") or {}).get("doctor") is True),
    Milestone("mac_check", "Mac apps check", f"the last `jarvis mac check` passed (within {CHECK_FRESH_DAYS} days)",
              lambda f: (f.get("checks") or {}).get("mac_check") is True),
    Milestone("reliable_30d", f"{RELIABLE_DAYS} days reliable", f"installed {RELIABLE_DAYS}+ days with no health failure or failed "
              "recovery drill in that time, and healthy now", lambda f: bool(f.get("reliable"))),
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
    now = datetime.now(timezone.utc)
    return {"db_ok": db_ok, "audit_ok": audit_ok, "providers": providers, "confirmed_memories": confirmed,
            "completed_tasks": completed, "capabilities": capabilities, "voice_ready": voice_ready,
            "paired_phones": paired_phones, "touch_id": touch_id, "bench_runs": bench_runs, "health": health,
            "bench_latest": _bench_latest(bench_dir), "checks": {n: _check_ok(kernel, n, now) for n in ("doctor", "mac_check")},
            "reliable": _reliable(kernel, health, now)}


def _bench_latest(out_dir: Path) -> float | None:
    """Pass rate of the newest benchmark run (scored tasks only), or None without one."""
    from .bench import history

    try:
        runs = history.runs(out_dir)
    except Exception:
        return None
    latest = runs[0] if runs else None
    return latest["passed"] / latest["scored"] if latest and latest["scored"] else None


def record_check(kernel: Any, name: str, ok: bool, *, now: datetime | None = None) -> None:
    """Called by `jarvis doctor`, `jarvis mac check` and `jarvis drill` after a real run on this installation."""
    stamp = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    _set_meta(kernel, CHECK_KEY + name, json.dumps({"ok": bool(ok), "at": stamp}))
    kernel.audit.record("evolution.check", check=name, ok=bool(ok))


def _check(kernel: Any, name: str) -> dict[str, Any] | None:
    try:
        data = json.loads(_meta(kernel, CHECK_KEY + name) or "null")
    except ValueError:
        return None
    return data if isinstance(data, dict) and "at" in data else None


def _check_ok(kernel: Any, name: str, now: datetime) -> bool:
    c = _check(kernel, name)
    return bool(c and c.get("ok") and now - _parse(c["at"]) <= timedelta(days=CHECK_FRESH_DAYS))


def _reliable(kernel: Any, health: dict[str, Any] | None, now: datetime) -> bool:
    if not (health or {}).get("ok"):
        return False
    first = kernel.db.one("SELECT ts FROM audit ORDER BY seq LIMIT 1")
    if not first or now - _parse(first[0]) < timedelta(days=RELIABLE_DAYS):
        return False
    since = (now - timedelta(days=RELIABLE_DAYS)).isoformat(timespec="seconds")
    for (payload,) in kernel.db.query("SELECT payload FROM audit WHERE event = 'health.changed' AND ts >= ?", (since,)):
        try:
            if json.loads(payload).get("ok") is False:
                return False
        except ValueError:
            continue
    drill = _check(kernel, "drill")
    return not (drill and not drill.get("ok") and drill["at"] >= since)


def evaluate(kernel: Any, facts: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Check every milestone, keep the record, and return the stage with its evidence."""
    now = now or datetime.now(timezone.utc)
    stamp = now.isoformat(timespec="seconds")
    grace = timedelta(days=GRACE_DAYS)
    record = _load(kernel)
    changed = False
    old_version = _meta(kernel, VERSION_KEY)
    if old_version != str(DEFINITION_VERSION):
        if old_version is not None or record:
            kernel.audit.record("evolution.definitions", frm=old_version or "1", to=str(DEFINITION_VERSION))
        _set_meta(kernel, VERSION_KEY, str(DEFINITION_VERSION))
    items = []
    for m in MILESTONES:
        try:
            ok = bool(m.check(facts))
        except Exception:
            ok = False
        rec = record.get(m.id)
        if ok and rec is None:
            rec = record[m.id] = {"first": stamp, "last": stamp, "current": True}
            kernel.audit.record("evolution.milestone", milestone=m.id)
            changed = True
        elif rec is not None:
            if ok and (not rec.get("last") or now - _parse(rec["last"]) >= LAST_REFRESH):
                rec["last"] = stamp
                changed = True
            if rec.get("current") != ok:
                rec["current"] = ok
                changed = True
        last = _parse(rec["last"]) if rec and rec.get("last") else None
        held = bool(not ok and last and now - last <= grace)
        items.append({"id": m.id, "title": m.title, "evidence": m.evidence, "verified": ok, "held": held,
                      "counts": ok or held, "first_verified": rec["first"] if rec else None,
                      "last_verified": rec.get("last") if rec else None,
                      "held_until": (last + grace).isoformat(timespec="seconds") if held else None})
    count = sum(1 for i in items if i["counts"])
    tier, name = tier_for(count)
    previous = _meta(kernel, STAGE_KEY)
    if previous is not None and previous != str(tier):
        kernel.audit.record("evolution.tier", frm=int(previous), to=tier, verified=count)
    if previous != str(tier):
        _set_meta(kernel, STAGE_KEY, str(tier))
    if changed:
        _set_meta(kernel, META_KEY, json.dumps(record))
    nxt = next((t for t in TIERS if t[0] > count), None)
    return {"tier": tier, "name": name, "stages": STAGE_NAMES, "version": DEFINITION_VERSION, "grace_days": GRACE_DAYS,
            "verified": count, "verified_now": sum(1 for i in items if i["verified"]), "total": len(MILESTONES),
            "next": {"tier": nxt[1], "name": nxt[2], "needs": nxt[0] - count} if nxt else None,
            "milestones": items}


def _parse(stamp: str) -> datetime:
    d = datetime.fromisoformat(stamp)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _meta(kernel: Any, key: str) -> str | None:
    row = kernel.db.one("SELECT value FROM meta WHERE key = ?", (key,))
    return row[0] if row else None


def _set_meta(kernel: Any, key: str, value: str) -> None:
    with kernel.db.tx() as c:
        c.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))


def _load(kernel: Any) -> dict[str, dict[str, Any]]:
    row = kernel.db.one("SELECT value FROM meta WHERE key = ?", (META_KEY,))
    try:
        data = json.loads(row[0]) if row else {}
    except ValueError:
        data = {}
    return data if isinstance(data, dict) else {}
