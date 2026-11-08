"""Continuous intelligence: JARVIS learns from what really happened, with evidence, and only within the autonomy
the owner allows.

The single source of events is the existing hash-chained audit log. The pipeline reads only new entries (a cursor
in ``meta``), turns them into **outcomes** (tasks and chat replies, each judged by verification evidence, never by
"it returned without an error"), and recomputes **lessons** from outcomes, owner feedback and audit counts with
fixed rules: no model, nothing leaves the Mac, nothing in a lesson is the owner's private text (lessons name models,
tools and counts). A lesson keeps its evidence, a confidence that grows with the number of observations, when it was
first and last seen, and becomes "outdated" when the evidence stops arriving. Two lessons about the same subject with
opposite polarity are both downgraded to "hypothesis" (a contradiction is shown, never resolved silently).

Learning changes no behaviour by itself: lessons inform proposals, the tournament and the dashboard. Every change to
JARVIS remains propose-only.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any

from ..core.util import new_id, now_iso

CURSOR = "learn.audit_seq"
BATCH = 5000
WINDOW_DAYS = 30
OUTDATED_DAYS = 30

# ---- autonomy ------------------------------------------------------------------------------------------------------
TIERS = {
    1: ("Observe", "Read permitted activity from the audit log and keep outcomes."),
    2: ("Learn", "Extract lessons with evidence from those outcomes."),
    3: ("Analyze", "Find weaknesses, compare models (tournament) and spot opportunities."),
    4: ("Experiment", "Run approved kinds of experiments in throwaway sandboxes or on recorded data."),
    5: ("Propose", "Turn findings into improvement proposals for you to approve or reject."),
    6: ("Approved execution", "Try a change you name (a branch or commit) in a throwaway copy of JARVIS: run every test and the "
                              "linter there and compare with your current code. Never merges, pushes or changes the running code."),
    7: ("Verified operation", "Routine operations within explicit limits. Not built: nothing runs on its own."),
}
DEFAULT_TIERS = {1: True, 2: True, 3: True, 4: True, 5: True, 6: False, 7: False}
PAUSES = ("learning", "experiments", "initiative")
DASHBOARD_MAX_TIER = 5   # tiers 6 and 7 can't be switched on from a browser (only from the Mac's terminal)


class AutonomyError(ValueError):
    pass


class Autonomy:
    def __init__(self, kernel):
        self.kernel = kernel
        self.db = kernel.db

    def _get(self, key: str, default: str) -> str:
        row = self.db.one("SELECT value FROM autonomy WHERE key = ?", (key,))
        return row["value"] if row else default

    def state(self) -> dict[str, Any]:
        tiers = {n: self._get(f"tier.{n}", "1" if on else "0") == "1" for n, on in DEFAULT_TIERS.items()}
        pauses = {p: self._get(f"pause.{p}", "0") == "1" for p in PAUSES}
        stopped = self.kernel.killswitch.engaged()
        return {"tiers": [{"tier": n, "name": TIERS[n][0], "about": TIERS[n][1], "on": tiers[n]} for n in TIERS],
                "paused": pauses, "stopped": stopped,
                "allowed": {"observe": self.allowed(1, None, tiers, pauses, stopped),
                            "learn": self.allowed(2, "learning", tiers, pauses, stopped),
                            "analyze": self.allowed(3, "learning", tiers, pauses, stopped),
                            "experiment": self.allowed(4, "experiments", tiers, pauses, stopped),
                            "propose": self.allowed(5, "initiative", tiers, pauses, stopped),
                            "execute": self.allowed(6, "experiments", tiers, pauses, stopped)}}

    @staticmethod
    def allowed(tier: int, pause: str | None, tiers: dict, pauses: dict, stopped: bool) -> bool:
        """A tier works only if it and every tier below it are on, its pause is off and the emergency stop is off."""
        return not stopped and all(tiers[n] for n in range(1, tier + 1)) and not (pause and pauses.get(pause))

    def can(self, what: str) -> bool:
        return bool(self.state()["allowed"].get(what))

    def set_tier(self, tier: int, on: bool, *, by: str, from_dashboard: bool = True) -> None:
        if tier not in TIERS:
            raise AutonomyError("unknown tier")
        if on and from_dashboard and tier > DASHBOARD_MAX_TIER:
            raise AutonomyError(f"tier {tier} can only be switched on from the Mac's terminal")
        self._put(f"tier.{tier}", "1" if on else "0", by)
        self.kernel.audit.record("autonomy.tier", actor=by, tier=tier, on=on)

    def set_pause(self, what: str, paused: bool, *, by: str) -> None:
        if what not in PAUSES:
            raise AutonomyError("unknown pause")
        self._put(f"pause.{what}", "1" if paused else "0", by)
        self.kernel.audit.record("autonomy.pause", actor=by, what=what, paused=paused)

    def _put(self, key: str, value: str, by: str) -> None:
        with self.db.tx() as c:
            c.execute("INSERT INTO autonomy (key, value, updated_at, updated_by) VALUES (?,?,?,?) "
                      "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at, "
                      "updated_by = excluded.updated_by", (key, value, now_iso(), by))


# ---- feedback ------------------------------------------------------------------------------------------------------
def add_feedback(kernel, *, target: str, ref: str, rating: int, model: str | None = None, mode: str | None = None,
                 reason: str | None = None, by: str = "owner") -> str:
    if target not in ("reply", "task") or rating not in (-1, 1) or not ref:
        raise ValueError("feedback needs a target (reply or task), a reference and a rating of -1 or 1")
    fid = new_id("fb")
    reason = (reason or "").strip()[:200] or None
    with kernel.db.tx() as c:
        c.execute("DELETE FROM feedback WHERE target = ? AND ref = ?", (target, ref))   # one rating per answer
        c.execute("INSERT INTO feedback (id, target, ref, model, mode, rating, reason, created_at) VALUES (?,?,?,?,?,?,?,?)",
                  (fid, target, ref[:120], (model or "")[:80] or None, (mode or "")[:20] or None, rating, reason, now_iso()))
    kernel.audit.record("learn.feedback", actor=by, target=target, rating=rating, model=model, has_reason=bool(reason))
    return fid


# ---- the pipeline --------------------------------------------------------------------------------------------------
def _meta(db, key: str) -> str | None:
    row = db.one("SELECT value FROM meta WHERE key = ?", (key,))
    return row["value"] if row else None


def _set_meta(c, key: str, value: str) -> None:
    c.execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _seconds(a: str, b: str) -> float | None:
    try:
        return round((_parse(b) - _parse(a)).total_seconds(), 1)
    except (TypeError, ValueError):
        return None


class Pipeline:
    """OBSERVE (audit → outcomes) and LEARN (outcomes → lessons). Runs in the dashboard's maintenance loop."""

    def __init__(self, kernel):
        self.kernel = kernel
        self.db = kernel.db
        self.autonomy = Autonomy(kernel)

    # OBSERVE
    def ingest(self) -> int:
        start = int(_meta(self.db, CURSOR) or 0)
        rows = self.db.query("SELECT seq, ts, event, task_id, payload FROM audit WHERE seq > ? ORDER BY seq LIMIT ?", (start, BATCH))
        if not rows:
            return 0
        last_chat_model: str | None = None
        last_chat_seconds: float | None = None
        new = []
        for r in rows:
            p = json.loads(r["payload"])
            ev = r["event"]
            if ev == "model.local_call" and str(p.get("purpose", "")).startswith("dashboard chat"):
                last_chat_model, last_chat_seconds = f"local/{p.get('model')}", p.get("latency_s")
            elif ev == "egress.received" and not r["task_id"]:
                last_chat_model, last_chat_seconds = f"{p.get('provider')}/{p.get('model')}", p.get("latency_s")
            elif ev == "chat.answer_check":
                still = int(p.get("still") or 0)
                verdict = "verified" if still == 0 else "failed"
                new.append(("reply", f"seq{r['seq']}", last_chat_model, verdict,
                            {"problems_found": p.get("problems"), "retried": p.get("retried"), "still_wrong": still},
                            last_chat_seconds, int(p.get("problems") or 0), 1 if p.get("retried") and still == 0 else 0, r["ts"]))
                last_chat_model = last_chat_seconds = None
            elif ev == "task.verified" and r["task_id"]:
                task = self.db.one("SELECT created_at FROM tasks WHERE id = ?", (r["task_id"],))
                errors = self.db.one("SELECT COUNT(*) FROM audit WHERE task_id = ? AND event = 'tool.error'", (r["task_id"],))[0]
                recovered = self.db.one("SELECT COUNT(*) FROM audit WHERE task_id = ? AND event = 'task.state' "
                                        "AND payload LIKE '%\"recovering\"%'", (r["task_id"],))[0]
                model = self.db.one("SELECT payload FROM audit WHERE task_id = ? AND event IN ('model.local_call', 'egress.received') "
                                    "ORDER BY seq DESC LIMIT 1", (r["task_id"],))
                mname = None
                if model:
                    mp = json.loads(model["payload"])
                    mname = f"{mp['provider']}/{mp['model']}" if "provider" in mp else f"local/{mp.get('model')}"
                new.append(("task", r["task_id"], mname, "verified" if p.get("ok") else "failed",
                            {"verifier": p.get("verifier"), "evidence": p.get("evidence")},
                            _seconds(task["created_at"], r["ts"]) if task else None, errors, 1 if recovered else 0, r["ts"]))
        with self.db.tx() as c:
            for kind, ref, model, verdict, ev, secs, errs, rec, ts in new:
                c.execute("INSERT INTO outcomes (id, kind, ref, model, verdict, evidence, seconds, errors, recovered, created_at) "
                          "VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(kind, ref) DO UPDATE SET verdict = excluded.verdict, "
                          "evidence = excluded.evidence", (new_id("out"), kind, ref, model, verdict, json.dumps(ev, default=str)[:2000],
                                                           secs, errs, rec, ts))
            _set_meta(c, CURSOR, str(rows[-1]["seq"]))
        return len(new)

    # LEARN
    def findings(self) -> list[dict[str, Any]]:
        """Each finding: key, subject, polarity (+1 good / -1 bad), statement, evidence, observations."""
        since = (datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)).isoformat()
        out: list[dict[str, Any]] = []
        # replies per model: how often the answer check still found problems
        by_model: dict[str, list] = defaultdict(list)
        for r in self.db.query("SELECT model, verdict, seconds FROM outcomes WHERE kind = 'reply' AND created_at >= ? AND model IS NOT NULL", (since,)):
            by_model[r["model"]].append(r)
        for model, rows in by_model.items():
            n, bad = len(rows), sum(1 for r in rows if r["verdict"] == "failed")
            secs = [r["seconds"] for r in rows if r["seconds"] is not None]
            if n >= 5 and bad / n >= 0.3:
                out.append({"key": f"reply-quality:{model}", "subject": model, "polarity": -1, "n": n,
                            "statement": f"Answers from {model} often still fail the answer check ({bad} of {n}).",
                            "evidence": {"replies": n, "failed": bad}})
            elif n >= 5 and bad / n <= 0.1:
                out.append({"key": f"reply-quality:{model}", "subject": model, "polarity": 1, "n": n,
                            "statement": f"{model} answers reliably ({n - bad} of {n} passed the check"
                                         + (f", median {median(secs):.1f} s)." if secs else ")."),
                            "evidence": {"replies": n, "failed": bad, "median_s": round(median(secs), 2) if secs else None}})
        # owner feedback per model
        fb: dict[str, Counter] = defaultdict(Counter)
        for r in self.db.query("SELECT model, rating FROM feedback WHERE created_at >= ? AND model IS NOT NULL", (since,)):
            fb[r["model"]][r["rating"]] += 1
        for model, c in fb.items():
            n = c[1] + c[-1]
            if n >= 3 and c[-1] / n >= 0.5:
                out.append({"key": f"owner-rating:{model}", "subject": model, "polarity": -1, "n": n,
                            "statement": f"You rated {c[-1]} of {n} answers from {model} as not helpful.",
                            "evidence": {"helpful": c[1], "not_helpful": c[-1]}})
            elif n >= 3 and c[1] / n >= 0.8:
                out.append({"key": f"owner-rating:{model}", "subject": model, "polarity": 1, "n": n,
                            "statement": f"You found {c[1]} of {n} answers from {model} helpful.",
                            "evidence": {"helpful": c[1], "not_helpful": c[-1]}})
        # tasks: verification
        tasks = self.db.query("SELECT ref, verdict, recovered FROM outcomes WHERE kind = 'task' AND created_at >= ?", (since,))
        if len(tasks) >= 3:
            ok = sum(1 for t in tasks if t["verdict"] == "verified")
            pol = 1 if ok / len(tasks) >= 0.8 else -1 if ok / len(tasks) < 0.5 else 0
            if pol:
                out.append({"key": "missions:verification", "subject": "missions", "polarity": pol, "n": len(tasks),
                            "statement": f"{ok} of {len(tasks)} missions passed verification in the last {WINDOW_DAYS} days.",
                            "evidence": {"missions": len(tasks), "verified": ok, "task_ids": [t["ref"] for t in tasks][-10:]}})
        # tools that keep failing
        ops: dict[str, str] = {}
        errs: Counter = Counter()
        for r in self.db.query("SELECT event, payload FROM audit WHERE ts >= ? AND event IN ('tool.start', 'tool.error')", (since,)):
            p = json.loads(r["payload"])
            if r["event"] == "tool.start":
                ops[p.get("op_id")] = f"{p.get('tool')}.{p.get('action')}"
            else:
                errs[ops.get(p.get("op_id"), "unknown tool")] += 1
        for call, n in errs.items():
            if n >= 3:
                out.append({"key": f"tool-errors:{call}", "subject": call, "polarity": -1, "n": n,
                            "statement": f"The {call} tool failed {n} times in the last {WINDOW_DAYS} days.",
                            "evidence": {"errors": n}})
        # approvals the owner always rejects
        asked: dict[str, str] = {}
        decided: dict[str, Counter] = defaultdict(Counter)
        for r in self.db.query("SELECT event, payload FROM audit WHERE ts >= ? AND event IN ('approval.requested', 'approval.approved', 'approval.rejected')", (since,)):
            p = json.loads(r["payload"])
            if r["event"] == "approval.requested":
                asked[p.get("approval_id")] = f"{p.get('tool')}.{p.get('action')}"
            else:
                decided[asked.get(p.get("approval_id"), "unknown action")][r["event"].split(".")[1]] += 1
        for call, c in decided.items():
            if c["rejected"] >= 3 and c["approved"] == 0:
                out.append({"key": f"approvals:{call}", "subject": call, "polarity": -1, "n": c["rejected"],
                            "statement": f"You rejected all {c['rejected']} requests to run {call}.",
                            "evidence": {"rejected": c["rejected"], "approved": 0}})
            elif c["approved"] >= 5 and c["rejected"] == 0:
                out.append({"key": f"approvals:{call}", "subject": call, "polarity": 1, "n": c["approved"],
                            "statement": f"You approved all {c['approved']} requests to run {call} (a standing permission could save you the taps).",
                            "evidence": {"rejected": 0, "approved": c["approved"]}})
        # requests with no model available
        nr = self.db.one("SELECT COUNT(*) FROM audit WHERE ts >= ? AND event = 'model.no_route'", (since,))[0]
        if nr >= 3:
            out.append({"key": "routing:no-route", "subject": "routing", "polarity": -1, "n": nr,
                        "statement": f"{nr} requests found no suitable model in the last {WINDOW_DAYS} days.",
                        "evidence": {"no_route": nr}})
        return out

    def learn(self) -> dict[str, int]:
        now = now_iso()
        found = self.findings()
        # contradictions: opposite polarities about the same subject → both are only hypotheses
        pols: dict[str, set] = defaultdict(set)
        for f in found:
            pols[f["subject"]].add(f["polarity"])
        added = updated = 0
        with self.db.tx() as c:
            for f in found:
                contested = len(pols[f["subject"]]) > 1
                conf = round(min(0.95, 0.4 + 0.08 * f["n"]), 2)
                kind = "hypothesis" if contested else "inferred"
                row = c.execute("SELECT id, kind, state, seen FROM lessons WHERE key = ?", (f["key"],)).fetchone()
                ev = json.dumps({**f["evidence"], "contested": contested})
                if row is None:
                    c.execute("INSERT INTO lessons (id, key, subject, polarity, statement, kind, evidence, confidence, first_seen, last_seen) "
                              "VALUES (?,?,?,?,?,?,?,?,?,?)", (new_id("les"), f["key"], f["subject"], f["polarity"], f["statement"],
                                                               kind, ev, conf, now, now))
                    added += 1
                else:
                    keep = row["kind"] if row["kind"] in ("confirmed", "user") and not contested else kind
                    c.execute("UPDATE lessons SET statement = ?, polarity = ?, kind = ?, evidence = ?, confidence = ?, "
                              "seen = seen + 1, last_seen = ? WHERE id = ?",
                              (f["statement"], f["polarity"], keep, ev, conf, now, row["id"]))
                    updated += 1
                # knowledge links: the lesson is about its subject
                c.execute("INSERT OR IGNORE INTO links (src, dst, rel, source, created_at) VALUES (?,?,?,?,?)",
                          (f"lesson:{f['key']}", f"subject:{f['subject']}", "about", "pipeline", now))
            # evidence that stopped arriving: the lesson is outdated (kept, so you can see what used to be true)
            cutoff = (datetime.now(timezone.utc) - timedelta(days=OUTDATED_DAYS)).isoformat()
            outdated = c.execute("UPDATE lessons SET kind = 'outdated' WHERE last_seen < ? AND kind != 'outdated'", (cutoff,)).rowcount
        return {"added": added, "updated": updated, "outdated": outdated}

    def run(self) -> dict[str, Any]:
        """One cycle. Does nothing (and says why) when the autonomy settings or the emergency stop don't allow it."""
        a = self.autonomy.state()["allowed"]
        if not a["observe"]:
            return {"ran": False, "why": "observing is off or the emergency stop is on"}
        outcomes = self.ingest()
        result: dict[str, Any] = {"ran": True, "outcomes": outcomes}
        if a["learn"]:
            result.update(self.learn())
        if outcomes or result.get("added"):
            self.kernel.audit.record("learn.cycle", outcomes=outcomes, lessons_added=result.get("added", 0),
                                     lessons_updated=result.get("updated", 0))
        return result


# ---- reading -------------------------------------------------------------------------------------------------------
def lessons(kernel, *, include_rejected: bool = False) -> list[dict[str, Any]]:
    rows = kernel.db.query("SELECT * FROM lessons" + ("" if include_rejected else " WHERE state = 'active'")
                           + " ORDER BY last_seen DESC LIMIT 200")
    return [{**dict(r), "evidence": json.loads(r["evidence"])} for r in rows]


def decide_lesson(kernel, lesson_id: str, decision: str, *, by: str) -> None:
    """The owner confirms a lesson, rejects it (it stays hidden even if the evidence returns), or deletes it."""
    with kernel.db.tx() as c:
        row = c.execute("SELECT key FROM lessons WHERE id = ?", (lesson_id,)).fetchone()
        if row is None:
            raise KeyError("no such lesson")
        if decision == "confirm":
            c.execute("UPDATE lessons SET kind = 'confirmed', state = 'active' WHERE id = ?", (lesson_id,))
        elif decision == "reject":
            c.execute("UPDATE lessons SET state = 'rejected' WHERE id = ?", (lesson_id,))
        elif decision == "delete":
            c.execute("DELETE FROM links WHERE src = ?", (f"lesson:{row['key']}",))
            c.execute("DELETE FROM lessons WHERE id = ?", (lesson_id,))
        else:
            raise ValueError("decision must be confirm, reject or delete")
    kernel.audit.record("learn.lesson", actor=by, decision=decision, lesson=lesson_id)


def summary(kernel) -> dict[str, Any]:
    """Only numbers that can be calculated exactly from the records."""
    db = kernel.db
    since = (datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)).isoformat()
    def count(sql: str, *args) -> int:
        return db.one(sql, args)[0]
    tasks = count("SELECT COUNT(*) FROM outcomes WHERE kind = 'task' AND created_at >= ?", since)
    tasks_ok = count("SELECT COUNT(*) FROM outcomes WHERE kind = 'task' AND verdict = 'verified' AND created_at >= ?", since)
    replies = count("SELECT COUNT(*) FROM outcomes WHERE kind = 'reply' AND created_at >= ?", since)
    replies_ok = count("SELECT COUNT(*) FROM outcomes WHERE kind = 'reply' AND verdict = 'verified' AND created_at >= ?", since)
    recovered = count("SELECT COUNT(*) FROM outcomes WHERE recovered = 1 AND created_at >= ?", since)
    fb_up = count("SELECT COUNT(*) FROM feedback WHERE rating = 1 AND created_at >= ?", since)
    fb_down = count("SELECT COUNT(*) FROM feedback WHERE rating = -1 AND created_at >= ?", since)
    last = db.one("SELECT ts FROM audit WHERE event = 'learn.cycle' ORDER BY seq DESC LIMIT 1")
    newest = db.one("SELECT last_seen FROM lessons WHERE state = 'active' ORDER BY first_seen DESC LIMIT 1")
    return {"window_days": WINDOW_DAYS,
            "missions": {"total": tasks, "verified": tasks_ok}, "replies": {"total": replies, "verified": replies_ok},
            "recovered": recovered, "feedback": {"helpful": fb_up, "not_helpful": fb_down},
            "lessons": count("SELECT COUNT(*) FROM lessons WHERE state = 'active'"),
            "lessons_new_at": newest["last_seen"] if newest else None,
            "experiments_running": count("SELECT COUNT(*) FROM experiments WHERE state = 'running'"),
            "last_cycle": last["ts"] if last else None}
