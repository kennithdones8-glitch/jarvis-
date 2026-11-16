"""Knowledge intelligence (Evolution 4.0, Stage 4): one way to ask "what does JARVIS know that bears on this?"

JARVIS already keeps its knowledge in separate, well-guarded places: memories (what you told it or it noticed),
records (the conversations they came from), missions (tasks) and how they ended, objectives, lessons learned from
outcomes, improvement proposals and your decisions on them, your indexed files, and its own documentation. This
module copies none of it. It reads those tables and returns **items**, each with:

- ``id`` (``memory:…``, ``task:…``, ``objective:…``, ``lesson:…``, ``proposal:…``, ``doc:…``) and ``kind``;
- ``text``, ``since`` (when it was recorded) and ``source`` (where it came from: provenance);
- ``status``: *stated* by you, *confirmed*, *inferred* (not confirmed: may be wrong), *outdated*, or *record*
  (something that happened); and ``confidence`` (0–1);
- ``why``: the plain reasons it was retrieved ("matched: lease, pets", "mission of that objective", …);
- ``private``: true when it may never leave this Mac.

``context(question)`` is used by chat, planning and the lab; ``related(id)`` by the Knowledge page. Retrieval is word
matching (the existing full-text indexes), widened one step along the ``links`` table and by shared objective, then
ranked by match strength, confirmation and recency. No model is called and nothing leaves the Mac here; a caller that
hands items to a model marks them as memory, so the privacy gate applies exactly as before.

Inferred knowledge is never promoted here: an unconfirmed memory stays "inferred" until you confirm it.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .files_index import STOP

REPO = Path(__file__).resolve().parents[2]
ABOUT_WORDS = re.compile(r"\b(jarvis|yourself|your (own )?(code|architecture|design|memory|sandbox|permissions?|roadmap|"
                         r"weakness(es)?|limits?|limitations?)|how (do|are) you (work|built)|improve you)\b", re.I)
OUTDATED_DAYS = 365          # an unconfirmed memory this old is shown as outdated (it was never confirmed)
DOC_FILES = ("docs/ARCHITECTURE.md", "docs/ROADMAP.md", "docs/SECURITY.md", "CHANGELOG.md")
DOC_SECTION = 900
_docs_cache: dict[str, tuple[float, list[dict[str, str]]]] = {}


def words_of(question: str) -> list[str]:
    return list(dict.fromkeys(w for w in re.findall(r"\w+", (question or "").lower()) if len(w) >= 3 and w not in STOP))[:10]


def _age_days(iso: str | None, now: datetime) -> float:
    try:
        t = datetime.fromisoformat(iso)
        return max(0.0, (now - (t if t.tzinfo else t.replace(tzinfo=timezone.utc))).total_seconds() / 86400)
    except (TypeError, ValueError):
        return 9999.0


def _hits(text: str, words: list[str]) -> list[str]:
    low = (text or "").lower()
    return [w for w in words if re.search(rf"\b{re.escape(w)}", low)]


def memory_item(m: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    stated = m["origin"] == "explicit"
    review = m.get("review_after")
    if review and review <= now.date().isoformat():
        status = "outdated"
    elif stated:
        status = "stated"
    elif m.get("verified_at"):
        status = "confirmed"
    else:
        status = "outdated" if _age_days(m["created_at"], now) > OUTDATED_DAYS else "inferred"
    return {"id": f"memory:{m['id']}", "kind": "memory", "text": m["text"], "since": m["created_at"],
            "updated": m.get("updated_at"), "status": status, "confidence": round(float(m["confidence"]), 2),
            "source": "you told JARVIS" if stated else "noticed in a conversation" + (" (you confirmed it)" if m.get("verified_at") else ""),
            "record": m.get("source_record"), "private": (m.get("privacy") or "normal") == "private",
            "important": bool(m.get("important")), "why": []}


# ---- JARVIS's own documentation: a built-in source, read from the checkout it runs from ---------------------------
def doc_sections(repo: Path = REPO) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for rel in DOC_FILES:
        p = repo / rel
        try:
            mtime = p.stat().st_mtime
        except OSError:
            continue
        cached = _docs_cache.get(str(p))
        if not cached or cached[0] != mtime:
            parts = re.split(r"(?m)^(#{2,3} .+)$", p.read_text(errors="replace"))
            secs = [{"id": f"doc:{rel}#{i // 2}", "title": parts[i].lstrip("# ").strip(), "file": rel,
                     "text": parts[i + 1].strip()[:DOC_SECTION]} for i in range(1, len(parts) - 1, 2) if parts[i + 1].strip()]
            _docs_cache[str(p)] = (mtime, secs)
            cached = _docs_cache[str(p)]
        out += cached[1]
    return out


def _doc_items(words: list[str], limit: int, repo: Path = REPO) -> list[dict[str, Any]]:
    scored = []
    for s in doc_sections(repo):
        title_hits, body_hits = _hits(s["title"], words), _hits(s["text"], words)
        hit = list(dict.fromkeys(title_hits + body_hits))
        if hit:
            scored.append((3 * len(title_hits) + len(body_hits), s, hit))
    scored.sort(key=lambda x: -x[0])
    return [{"id": s["id"], "kind": "doc", "text": f"{s['title']}: {s['text']}", "since": None, "status": "record",
             "confidence": 1.0, "source": f"JARVIS's own {s['file']}", "private": False,
             "why": [f"matched: {', '.join(hit)}", "about JARVIS itself"], "_score": 1.0 + score}
            for score, s, hit in scored[:limit]]


# ---- retrieval -------------------------------------------------------------------------------------------------------
def context(kernel, question: str, *, limit: int = 8, exclude: set[str] | None = None, about_jarvis: bool | None = None,
            now: datetime | None = None, repo: Path = REPO) -> list[dict[str, Any]]:
    """What JARVIS knows that bears on ``question``, best first, each with the reasons it was picked. ``exclude``:
    item ids the caller already has. Never raises: a source that can't be read is left out."""
    now = now or datetime.now(timezone.utc)
    words = words_of(question)
    if not words or kernel.killswitch.engaged():
        return []
    db, found = kernel.db, {}

    def add(item: dict[str, Any], score: float, why: str) -> None:
        cur = found.get(item["id"])
        if cur is None:
            found[item["id"]] = cur = {**item, "_score": 0.0}
        cur["_score"] += score
        if why not in cur["why"]:
            cur["why"].append(why)

    def recency(iso: str | None) -> float:
        return 1.0 / (1.0 + _age_days(iso, now) / 30.0)       # 1.0 today, 0.5 a month ago, ~0.08 a year ago

    try:   # memories (full text)
        if kernel.memory.settings.enabled:
            for m in kernel.memory.search(question, limit=limit * 2):
                if kernel.memory.excluded(m["text"]):
                    continue
                it = memory_item(m, now)
                hit = _hits(m["text"], words) or words[:1]
                add(it, 2.0 * len(hit) + (1.0 if it["status"] in ("stated", "confirmed") else 0.0)
                    - (1.5 if it["status"] == "outdated" else 0.0) + recency(m["created_at"]), f"matched: {', '.join(hit)}")
    except Exception:  # noqa: BLE001
        pass
    objectives = []
    try:   # objectives and their missions
        for o in db.query("SELECT id, outcome, state, created_at, updated_at FROM objectives"):
            hit = _hits(o["outcome"], words)
            if hit:
                objectives.append(o["id"])
                add({"id": f"objective:{o['id']}", "kind": "objective", "text": o["outcome"], "since": o["created_at"],
                     "status": "stated", "confidence": 1.0, "source": f"an objective you set ({o['state']})",
                     "private": False, "why": []}, 2.0 * len(hit) + recency(o["updated_at"]), f"matched: {', '.join(hit)}")
        for oid in objectives:
            for t in db.query("SELECT t.id, t.goal, t.state, t.error, t.updated_at, t.created_at FROM links l JOIN tasks t "
                              "ON t.id = l.src WHERE l.dst = ? AND l.rel = 'mission of' ORDER BY t.updated_at DESC LIMIT 4", (oid,)):
                add(_task_item(t), 1.0 + recency(t["updated_at"]), "mission of an objective that matched")
    except Exception:  # noqa: BLE001
        pass
    try:   # missions by what they were for: what was tried, and how it ended
        like = " OR ".join("goal LIKE ?" for _ in words)
        for t in db.query(f"SELECT id, goal, state, error, updated_at, created_at FROM tasks WHERE {like} "
                          "ORDER BY updated_at DESC LIMIT 12", [f"%{w}%" for w in words]):
            hit = _hits(t["goal"], words)
            if hit:
                add(_task_item(t), 1.5 * len(hit) + recency(t["updated_at"]), f"matched: {', '.join(hit)}")
    except Exception:  # noqa: BLE001
        pass
    try:   # lessons (what worked and what didn't) and your decisions on proposals
        for les in db.query("SELECT id, subject, statement, kind, confidence, last_seen, first_seen FROM lessons WHERE state = 'active'"):
            hit = _hits(f"{les['subject']} {les['statement']}", words)
            if hit:
                add({"id": f"lesson:{les['id']}", "kind": "lesson", "text": les["statement"], "since": les["first_seen"],
                     "status": {"confirmed": "confirmed", "user": "stated", "outdated": "outdated"}.get(les["kind"], "inferred"),
                     "confidence": round(float(les["confidence"]), 2), "source": "learned from outcomes in the audit log",
                     "private": False, "why": []}, 1.5 * len(hit) + recency(les["last_seen"]), f"matched: {', '.join(hit)}")
        for p in db.query("SELECT id, title, body, state, created_at, decided_at FROM proposals"):
            problem = str((json.loads(p["body"]) or {}).get("problem") or "")
            hit = _hits(f"{p['title']} {problem}", words)
            if hit:
                decided = {"approved": "you approved it", "rejected": "you rejected it", "done": "done"}.get(p["state"], "not decided yet")
                add({"id": f"proposal:{p['id']}", "kind": "decision", "text": f"{p['title']} — {decided}", "since": p["created_at"],
                     "status": "stated" if p["state"] in ("approved", "rejected") else "record", "confidence": 1.0,
                     "source": "an improvement proposal and your decision", "private": False, "why": []},
                    1.5 * len(hit) + recency(p["decided_at"] or p["created_at"]), f"matched: {', '.join(hit)}")
    except Exception:  # noqa: BLE001
        pass
    try:   # one step along the links: what a matched memory informed, and memories from the same conversation
        mem_ids = [i.split(":", 1)[1] for i in found if i.startswith("memory:")]
        recs = {found[f"memory:{i}"].get("record") for i in mem_ids} - {None}
        for rid in list(recs)[:6]:
            for m in db.query("SELECT * FROM memories WHERE source_record = ? LIMIT 4", (rid,)):
                if f"memory:{m['id']}" not in found and not kernel.memory.excluded(m["text"]):
                    add(memory_item(dict(m), now), 0.8, "from the same conversation as a memory that matched")
    except Exception:  # noqa: BLE001
        pass
    wants_docs = bool(ABOUT_WORDS.search(question or "")) if about_jarvis is None else about_jarvis
    if wants_docs:
        try:
            doc_words = [w for w in words if w != "jarvis"] or words
            for it in _doc_items(doc_words, 3, repo):
                found[it["id"]] = it
        except Exception:  # noqa: BLE001
            pass
    out = sorted((i for i in found.values() if i["id"] not in (exclude or set())), key=lambda i: -i["_score"])[:limit]
    for i in out:
        i["score"] = round(i.pop("_score"), 2)
    return out


def _task_item(t) -> dict[str, Any]:
    ended = {"completed": "completed", "failed": "failed", "cancelled": "stopped"}.get(t["state"], "in progress")
    return {"id": f"task:{t['id']}", "kind": "mission", "text": f"{t['goal']} — {ended}" + (f" ({str(t['error'])[:120]})" if t["error"] and t["state"] == "failed" else ""),
            "since": t["created_at"], "status": "record", "confidence": 1.0, "source": "a mission JARVIS ran (task history)",
            "private": False, "why": []}


def context_text(items: list[dict[str, Any]]) -> str:
    """Items as lines for a model: what it is, how sure, and since when. Unconfirmed and outdated items say so."""
    note = {"stated": "you said so", "confirmed": "confirmed", "inferred": "unconfirmed — may be wrong",
            "outdated": "may be out of date — say so if you use it", "record": "from JARVIS's records"}
    return "\n".join(f"- [{i['kind']}] {i['text']} ({note[i['status']]}" + (f"; {i['since'][:10]}" if i.get("since") else "") + ")"
                     for i in items)


# ---- one item and what connects to it (the Knowledge page) --------------------------------------------------------
def related(kernel, item_id: str, *, limit: int = 12) -> dict[str, Any]:
    """An item and its connections, each with the reason for the connection. Raises KeyError for an unknown id."""
    db = kernel.db
    kind, _, key = item_id.partition(":")
    now = datetime.now(timezone.utc)
    out: list[dict[str, Any]] = []

    def link(item: dict[str, Any], why: str) -> None:
        if item["id"] != item_id and all(o["id"] != item["id"] for o in out):
            out.append({**item, "why": [why]})

    if kind == "memory":
        row = db.one("SELECT * FROM memories WHERE id = ?", (key,))
        if not row:
            raise KeyError(item_id)
        me = memory_item(dict(row), now)
        if row["source_record"]:
            rec = db.one("SELECT id, session, created_at FROM records WHERE id = ?", (row["source_record"],))
            if rec:
                me["conversation"] = {"record": rec["id"], "at": rec["created_at"]}
            for m in db.query("SELECT * FROM memories WHERE source_record = ? AND id != ?", (row["source_record"], key)):
                link(memory_item(dict(m), now), "from the same conversation")
        for r in db.query("SELECT dst FROM links WHERE src = ? AND rel = 'context for' ORDER BY created_at DESC LIMIT 5", (f"memory:{key}",)):
            rec = db.one("SELECT id, created_at FROM records WHERE id = ?", (r["dst"].split(":", 1)[-1],))
            if rec:
                link({"id": f"record:{rec['id']}", "kind": "answer", "text": "An answer JARVIS gave used this memory",
                      "since": rec["created_at"], "status": "record", "confidence": 1.0, "source": "conversation history",
                      "private": False}, "this memory was given to that answer as context")
        from .memory.conflicts import find as find_conflicts
        for c in find_conflicts(kernel.memory.list(limit=500)):
            other = c["b"] if c["a"]["id"] == key else c["a"] if c["b"]["id"] == key else None
            if other:
                orow = db.one("SELECT * FROM memories WHERE id = ?", (other["id"],))
                if orow:
                    link(memory_item(dict(orow), now), f"conflicts with this about {c['subject']}")
        for it in context(kernel, row["text"], limit=limit, exclude={item_id}):
            link(it, "; ".join(it["why"]))
    elif kind == "objective":
        o = db.one("SELECT id, outcome, state, created_at, updated_at FROM objectives WHERE id = ?", (key,))
        if not o:
            raise KeyError(item_id)
        me = {"id": item_id, "kind": "objective", "text": o["outcome"], "since": o["created_at"], "status": "stated",
              "confidence": 1.0, "source": f"an objective you set ({o['state']})", "private": False, "why": []}
        for t in db.query("SELECT t.id, t.goal, t.state, t.error, t.updated_at, t.created_at FROM links l JOIN tasks t ON "
                          "t.id = l.src WHERE l.dst = ? AND l.rel = 'mission of' ORDER BY t.created_at", (key,)):
            link(_task_item(t), "a mission of this objective")
        for it in context(kernel, o["outcome"], limit=limit, exclude={item_id}):
            link(it, "; ".join(it["why"]))
    elif kind == "task":
        t = db.one("SELECT id, goal, state, error, updated_at, created_at FROM tasks WHERE id = ?", (key,))
        if not t:
            raise KeyError(item_id)
        me = _task_item(t)
        for o in db.query("SELECT o.id, o.outcome, o.state, o.created_at FROM links l JOIN objectives o ON o.id = l.dst "
                          "WHERE l.src = ? AND l.rel = 'mission of'", (key,)):
            link({"id": f"objective:{o['id']}", "kind": "objective", "text": o["outcome"], "since": o["created_at"],
                  "status": "stated", "confidence": 1.0, "source": f"an objective you set ({o['state']})", "private": False},
                 "the objective this mission serves")
        for it in context(kernel, t["goal"], limit=limit, exclude={item_id}):
            link(it, "; ".join(it["why"]))
    else:
        raise KeyError(item_id)
    return {"item": me, "related": out[:limit]}


# ---- knowledge intelligence: what needs your attention in what JARVIS knows ---------------------------------------
def _wordset(text: str) -> frozenset[str]:
    return frozenset(w for w in re.findall(r"\w+", text.lower()) if len(w) >= 3 and w not in STOP)


def insights(kernel, *, now: datetime | None = None) -> dict[str, list[dict[str, Any]]]:
    """Plain-rule checks over memories, objectives and task history (no model). Each finding names the items, says
    why, and what you could do. Nothing is changed here: settling a conflict, confirming or deleting is yours.

    - ``conflicts``: memories that give different answers to the same question.
    - ``duplicates``: memories that say the same thing (the same meaningful words).
    - ``outdated``: a review date that has passed; an unconfirmed memory more than a year old; the older side of a
      conflict (superseded unless you say otherwise).
    - ``unconfirmed``: things JARVIS noticed and you haven't confirmed (they are never treated as fact).
    - ``missing``: objectives with no "done means", none in flight and none done, or a deadline that has passed.
    - ``patterns``: the same kind of mission asked for three times or more (a candidate for an objective)."""
    now = now or datetime.now(timezone.utc)
    db = kernel.db
    mems = [dict(r) for r in db.query("SELECT * FROM memories ORDER BY created_at DESC LIMIT 2000")]
    out: dict[str, list[dict[str, Any]]] = {k: [] for k in ("conflicts", "duplicates", "outdated", "unconfirmed", "missing", "patterns")}
    from .memory.conflicts import find as find_conflicts
    superseded = set()
    for c in find_conflicts(mems):
        superseded.add(c["b"]["id"])
        out["conflicts"].append({"title": f"Two memories disagree about {c['subject']}", "items": [memory_item(c["a"], now), memory_item(c["b"], now)],
                                 "why": "same subject, different answers", "do": "Keep the right one (Memory page)."})
    groups: dict[frozenset[str], list[dict[str, Any]]] = {}
    for m in mems:
        ws = _wordset(m["text"])
        if len(ws) >= 2:
            groups.setdefault(ws, []).append(m)
    for same in groups.values():
        if len(same) > 1:
            out["duplicates"].append({"title": f"{len(same)} memories say the same thing", "items": [memory_item(m, now) for m in same],
                                      "why": "the same meaningful words", "do": "Delete the extra ones."})
    today = now.date().isoformat()
    for m in mems:
        it = memory_item(m, now)
        if m.get("review_after") and m["review_after"] <= today:
            out["outdated"].append({"title": "Due for a check", "items": [it], "why": f"you asked to review it after {m['review_after']}",
                                    "do": "Confirm it is still true, edit it, or delete it."})
        elif m["id"] in superseded:
            out["outdated"].append({"title": "Probably replaced by a newer memory", "items": [it], "why": "a newer memory gives a different answer",
                                    "do": "Settle the conflict."})
        elif it["status"] == "outdated":
            out["outdated"].append({"title": "Never confirmed, and over a year old", "items": [it], "why": "noticed in a conversation, not confirmed since",
                                    "do": "Confirm or delete it."})
        elif it["status"] == "inferred":
            out["unconfirmed"].append({"title": "Not confirmed", "items": [it], "why": "JARVIS noticed it; you haven't confirmed it",
                                       "do": "Confirm it if it's right."})
    for o in db.query("SELECT id, outcome, criteria, deadline, state, created_at FROM objectives WHERE state = 'active'"):
        item = {"id": f"objective:{o['id']}", "kind": "objective", "text": o["outcome"], "since": o["created_at"], "status": "stated",
                "confidence": 1.0, "source": "an objective you set (active)", "private": False, "why": []}
        n = db.one("SELECT COUNT(*) FROM links WHERE dst = ? AND rel = 'mission of'", (o["id"],))[0]
        if not json.loads(o["criteria"] or "[]"):
            out["missing"].append({"title": "No “done means” yet", "items": [item], "why": "JARVIS can't tell when this objective is achieved",
                                   "do": "Add what done means (Objectives)."})
        if n == 0:
            out["missing"].append({"title": "No mission has been started", "items": [item], "why": "nothing has been planned for it",
                                   "do": "Plan the next step (Objectives)."})
        if o["deadline"] and o["deadline"] < today:
            out["missing"].append({"title": "Deadline has passed", "items": [item], "why": f"it was due {o['deadline']} and is still active",
                                   "do": "Mark it achieved, move the date, or drop it."})
    goals: dict[frozenset[str], list[Any]] = {}
    for t in db.query("SELECT id, goal, state, error, created_at, updated_at FROM tasks ORDER BY created_at DESC LIMIT 500"):
        ws = _wordset(t["goal"])
        if len(ws) >= 2:
            goals.setdefault(ws, []).append(t)
    for same in goals.values():
        if len(same) >= 3:
            out["patterns"].append({"title": f"Asked for {len(same)} times: “{same[0]['goal'][:80]}”", "items": [_task_item(t) for t in same[:3]],
                                    "why": "the same request keeps coming back", "do": "Consider making it an objective, so JARVIS keeps it moving."})
    for v in out.values():
        del v[40:]
    return out


__all__ = ["insights", "context", "context_text", "doc_sections", "memory_item", "related", "words_of"]
