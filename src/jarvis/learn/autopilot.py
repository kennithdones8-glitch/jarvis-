"""Tier 7 — verified operation: the few things JARVIS does on its own, always, within fixed limits (owner's choice).

1. **Nightly self-checks**: once a day after 03:00 (local time) the routing replay, the recovery drills and the
   benchmark comparison run in the simulation lab (sandboxed; nothing of yours is touched; no model is called).
2. **Acting on its own lessons**: a well-supported lesson about a model's answers nudges how routing *ranks* the
   models that are already allowed for a request. The router still applies every privacy, budget, capability and
   availability rule first, and in local-first mode a cloud model can never overtake a local one. Each adjustment is
   small (±3 on a score where quality counts 10 per point), logged, shown in the Evolution center and undoable; an
   undone adjustment is never re-applied for the same lesson.
3. **Acting on the intelligence tournament** (phase 3): when the tournament's evidence clearly separates two models
   (each with 5+ checked answers, 20+ points apart on the answer check), the better one gets a small bonus and the
   weaker a small penalty, under the same limits, with the numbers kept as evidence. It's re-evaluated as evidence
   arrives: if the gap closes, the adjustment is withdrawn. Benchmark runs are shown alongside but don't drive it
   (a run mixes several models, so its results can't be credited to one).
4. Everything it did lands in the morning briefing as one digest.

It never changes code, configuration files, permissions or money, and stops with tier 7 off, experiments paused, or
the emergency stop on.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from ..core.util import now_iso
from . import Autonomy

KEY = "learn.adjustments"
LAST_NIGHT = "learn.selfcheck_date"
NIGHT_HOUR = 3
BONUS = {-1: -3.0, 1: 2.0}


def _meta(db, key: str, default: str) -> str:
    row = db.one("SELECT value FROM meta WHERE key = ?", (key,))
    return row["value"] if row else default


def _put(db, key: str, value: str) -> None:
    with db.tx() as c:
        c.execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


def adjustments(kernel) -> list[dict[str, Any]]:
    return json.loads(_meta(kernel.db, KEY, "[]"))


def router_bonus(kernel) -> dict[str, float]:
    """The active adjustments as the router reads them: model name (without provider) → score bonus."""
    if not Autonomy(kernel).can("operate"):
        return {}
    out: dict[str, float] = {}
    for a in adjustments(kernel):   # a lesson and the tournament may both speak about one model: they add up (the router caps ±3)
        if a["active"]:
            out[a["model"]] = out.get(a["model"], 0.0) + a["bonus"]
    return out


def apply_to_router(kernel) -> None:
    kernel.models.router.adjust = router_bonus(kernel)


def act_on_lessons(kernel) -> list[dict[str, Any]]:
    """Turn strong, uncontested lessons about answer quality into routing nudges (new ones only)."""
    if not Autonomy(kernel).can("operate"):
        return []
    have = adjustments(kernel)
    known = {a["lesson"] for a in have}
    rows = kernel.db.query("SELECT key, subject, polarity, statement, confidence FROM lessons WHERE state = 'active' "
                           "AND kind IN ('inferred', 'confirmed') AND confidence >= 0.6 AND polarity != 0 "
                           "AND (key LIKE 'reply-quality:%' OR key LIKE 'owner-rating:%')")
    added = []
    for r in rows:
        if r["key"] in known:
            continue
        model = r["subject"].split("/", 1)[-1]
        adj = {"lesson": r["key"], "model": model, "bonus": BONUS[r["polarity"]], "active": True, "why": r["statement"],
               "at": now_iso()}
        have.append(adj)
        added.append(adj)
        kernel.audit.record("autopilot.adjust", model=model, bonus=adj["bonus"], lesson=r["key"])
    if added:
        _put(kernel.db, KEY, json.dumps(have))
        apply_to_router(kernel)
    return added


def act_on_tournament(kernel) -> list[dict[str, Any]]:
    """Tier 7: turn the tournament's own recommendation into a bounded routing adjustment (and withdraw it when the
    evidence no longer supports it). Only reorders models routing already allows; undone ones are never re-applied."""
    if not Autonomy(kernel).can("operate"):
        return []
    from .analysis import tournament
    rec = tournament(kernel).get("recommendation")
    have = adjustments(kernel)
    changed: list[dict[str, Any]] = []
    wanted = {}
    if rec:
        (best, nb), (worst, nw) = list(rec["evidence"].items())[0], list(rec["evidence"].items())[1]
        wanted = {f"tournament:best:{best}": (best, BONUS[1], nb), f"tournament:worst:{worst}": (worst, BONUS[-1], nw)}
    for a in have:   # the evidence no longer shows this gap: withdraw (not an owner undo, so it may return later)
        if a["lesson"].startswith("tournament:") and a["active"] and a["lesson"] not in wanted:
            a["active"], a["withdrawn_at"] = False, now_iso()
            changed.append(a)
            kernel.audit.record("autopilot.withdraw", model=a["model"], lesson=a["lesson"])
    known = {a["lesson"]: a for a in have}
    for key, (model, bonus, n) in wanted.items():
        old = known.get(key)
        if old and (old["active"] or old.get("undone_by")):
            continue   # already applied, or you undid it: never re-applied
        adj = {"lesson": key, "model": model.split("/", 1)[-1], "bonus": bonus, "active": True, "why": rec["text"],
               "evidence": {"answers_checked": n, "source": "intelligence tournament"}, "at": now_iso()}
        if old:
            have.remove(old)
        have.append(adj)
        changed.append(adj)
        kernel.audit.record("autopilot.adjust", model=adj["model"], bonus=bonus, lesson=key)
    if changed:
        _put(kernel.db, KEY, json.dumps(have))
        apply_to_router(kernel)
    return changed


def undo(kernel, lesson: str, *, by: str) -> None:
    have = adjustments(kernel)
    for a in have:
        if a["lesson"] == lesson and a["active"]:
            a["active"], a["undone_by"], a["undone_at"] = False, by, now_iso()
    _put(kernel.db, KEY, json.dumps(have))
    apply_to_router(kernel)
    kernel.audit.record("autopilot.undo", actor=by, lesson=lesson)


def nightly(kernel, *, now: datetime | None = None) -> list[str]:
    """Run the self-checks once a day after 03:00 local time. Returns the experiment ids it started (in order)."""
    now = now or datetime.now().astimezone()
    if now.hour < NIGHT_HOUR or _meta(kernel.db, LAST_NIGHT, "") == now.date().isoformat():
        return []
    if not Autonomy(kernel).can("operate"):
        return []
    from .analysis import Lab, LabError
    _put(kernel.db, LAST_NIGHT, now.date().isoformat())
    started = []
    for kind in ("replay", "drill", "bench_compare"):
        try:
            started.append(Lab(kernel).start(kind, by="jarvis:autopilot", background=False))
        except LabError as exc:
            kernel.audit.record("autopilot.skipped", kind=kind, reason=str(exc)[:200])
    kernel.audit.record("autopilot.selfcheck", experiments=started)
    return started


def digest(kernel, *, hours: int = 24) -> list[str]:
    """What JARVIS did on its own in the last day, for the morning briefing."""
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    out = []
    for e in kernel.db.query("SELECT event, payload FROM audit WHERE ts >= ? AND event LIKE 'autopilot.%' ORDER BY seq", (since,)):
        p = json.loads(e["payload"])
        if e["event"] == "autopilot.adjust":
            out.append(f"Routing: {'favouring' if p['bonus'] > 0 else 'ranking down'} {p['model']} (from what it learned). Undo in the Evolution center.")
        elif e["event"] == "autopilot.selfcheck":
            for x in kernel.db.query(f"SELECT kind, state, recommendation FROM experiments WHERE id IN ({','.join('?' * len(p['experiments']))})",
                                     tuple(p["experiments"])) if p["experiments"] else []:
                out.append(f"Self-check {x['kind']}: {x['state']} — {x['recommendation']}")
        elif e["event"] == "autopilot.undo":
            out.append("You undid a routing adjustment.")
        elif e["event"] == "autopilot.withdraw":
            out.append(f"Routing: withdrew the adjustment for {p['model']} (the evidence no longer supports it).")
    return out
