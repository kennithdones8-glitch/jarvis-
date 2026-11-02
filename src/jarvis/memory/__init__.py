"""Long-term memory, stored only in JARVIS's local database.

Two layers, kept separate as the spec requires:
- **Records**: original conversation turns, a long-term searchable archive.
- **Memories**: short derived statements ("Prefers email over calls") with provenance:
  origin (explicit = you said "remember…"/confirmed it; observed = noticed by the local model and
  not yet confirmed), confidence, source record, created / last-verified dates.

Deletion is managed: deleting a memory removes it and its index entry and records a tombstone
(a hash of the normalised text) so extraction can't silently re-learn it. Deleting a record also
deletes memories derived from it. The audit log stores ids and sizes, never memory text.
Known limits: task inputs/outputs live in task history, not here, and are not affected by memory
deletion; backups (when added) keep old copies until they expire.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import Any, Iterable

from ..core.audit import AuditLog
from ..core.db import Database
from ..core.util import new_id, now_iso, sha256_hex
from ..models import ChatRequest, Message, ModelService, Need, NoModelAvailable, parse_json_output
from ..models.types import Category, InvalidModelOutput, ProviderError

KINDS = ("preference", "fact", "decision", "project", "person", "other")
ORIGINS = ("explicit", "observed")
MAX_TEXT = 500

REMEMBER = re.compile(r"^\s*(?:jarvis[,:]?\s+)?(?:please\s+)?remember(?:\s+that)?[,:]?\s+(?P<fact>.+)$",
                      re.IGNORECASE | re.DOTALL)

EXTRACT_PROMPT = """You maintain the owner's personal memory. From the owner's message, extract durable facts the \
OWNER states about themselves: preferences, plans, decisions, people they mention, projects, important dates.
Ignore questions, requests, small talk and anything about the assistant. Do not guess or infer beyond what is said.
Write each as a short third-person statement, e.g. "Prefers email over calls".
Reply with JSON: {"memories": [{"text": "...", "kind": "preference|fact|decision|project|person"}]}
Reply {"memories": []} if there is nothing worth remembering."""


def normalise(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text.lower()).split())


def record_tombstone(content: str) -> str:
    return sha256_hex("record:" + normalise(content))


def reapply_tombstones(db: Database, hashes: Iterable[str]) -> dict[str, int]:
    """After restoring an older backup: remove memories and records you deleted since, so deleted data
    doesn't silently come back. Returns how many were removed."""
    hashes = set(hashes)
    removed = {"memories": 0, "records": 0}
    with db.tx() as c:
        for h in hashes:
            c.execute("INSERT OR IGNORE INTO tombstones (hash, created_at) VALUES (?, ?)", (h, now_iso()))
        for row in c.execute("SELECT id, text FROM memories").fetchall():
            if sha256_hex(normalise(row["text"])) in hashes:
                c.execute("DELETE FROM memories WHERE id = ?", (row["id"],))
                c.execute("DELETE FROM memories_fts WHERE id = ?", (row["id"],))
                removed["memories"] += 1
        for row in c.execute("SELECT id, content FROM records").fetchall():
            if record_tombstone(row["content"]) in hashes:
                c.execute("DELETE FROM records WHERE id = ?", (row["id"],))
                c.execute("DELETE FROM records_fts WHERE id = ?", (row["id"],))
                removed["records"] += 1
    return removed


def fts_query(text: str) -> str | None:
    words = [w for w in re.findall(r"\w+", text.lower()) if len(w) >= 3][:12]
    return " OR ".join(f'"{w}"' for w in dict.fromkeys(words)) or None


PROFILE_LIMIT = 8
PROFILE = re.compile(
    r"^\s*(please\s+)?(call me|my name is|(i'?m|i am) (a|an|vegetarian|vegan|pescatarian|allergic|intolerant|from|"
    r"based|married|single|divorced|left-handed|right-handed|retired|\d+)|i prefer|i like|i love|i hate|i don'?t|i do not|i never|i always|"
    r"i live|i work|i'?m allergic|my (wife|husband|partner|girlfriend|boyfriend|sister|brother|mother|mum|mom|father|"
    r"dad|son|daughter|kids?|children|dog|cat|birthday|favourite|favorite|job|dentist|doctor))\b", re.I)


@dataclass(frozen=True)
class MemorySettings:
    enabled: bool = True
    extract: bool = True
    exclude_topics: tuple[str, ...] = ()
    recall_limit: int = 5


class MemoryStore:
    def __init__(self, db: Database, audit: AuditLog, settings: MemorySettings | None = None,
                 models: ModelService | None = None):
        self.db = db
        self.audit = audit
        self.settings = settings or MemorySettings()
        self.models = models
        self._excluded = [re.compile(rf"\b{re.escape(t.lower())}\b") for t in self.settings.exclude_topics]

    # ---- policy ------------------------------------------------------------------------
    def excluded(self, text: str) -> bool:
        lowered = text.lower()
        return any(p.search(lowered) for p in self._excluded)

    def _tombstoned(self, text: str) -> bool:
        return self.db.one("SELECT 1 FROM tombstones WHERE hash = ?", (sha256_hex(normalise(text)),)) is not None

    # ---- records -----------------------------------------------------------------------
    def add_record(self, session: str, role: str, content: str, *, kind: str = "chat") -> str | None:
        if not self.settings.enabled or not content.strip() or self.excluded(content):
            return None
        rid = new_id("rec")
        with self.db.tx() as c:
            c.execute("INSERT INTO records (id, session, kind, role, content, created_at) VALUES (?,?,?,?,?,?)",
                      (rid, session, kind, role, content, now_iso()))
            c.execute("INSERT INTO records_fts (id, content) VALUES (?, ?)", (rid, content))
        return rid

    def search_records(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        q = fts_query(query)
        if not q:
            return []
        rows = self.db.query(
            "SELECT r.*, snippet(records_fts, 1, '[', ']', '…', 12) AS snippet FROM records_fts f "
            "JOIN records r ON r.id = f.id WHERE records_fts MATCH ? ORDER BY bm25(records_fts) LIMIT ?", (q, limit))
        return [dict(r) for r in rows]

    def delete_record(self, record_id: str, *, by: str) -> int:
        """Delete an original record and every memory derived from it. Returns memories removed."""
        derived = [r["id"] for r in self.db.query("SELECT id FROM memories WHERE source_record = ?", (record_id,))]
        for mid in derived:
            self.delete(mid, by=by)
        row = self.db.one("SELECT content FROM records WHERE id = ?", (record_id,))
        with self.db.tx() as c:
            if row:  # lets a restore from an older backup drop this record again
                c.execute("INSERT OR IGNORE INTO tombstones (hash, created_at) VALUES (?, ?)",
                          (record_tombstone(row["content"]), now_iso()))
            c.execute("DELETE FROM records WHERE id = ?", (record_id,))
            c.execute("DELETE FROM records_fts WHERE id = ?", (record_id,))
            self.audit.record("memory.record_deleted", actor=by, record_id=record_id, derived_deleted=len(derived))
        return len(derived)

    # ---- memories ----------------------------------------------------------------------
    def remember(self, text: str, *, kind: str = "fact", origin: str = "explicit", confidence: float | None = None,
                 source_record: str | None = None, by: str = "user") -> str | None:
        text = " ".join(text.split()).strip(" .")[:MAX_TEXT]
        if not self.settings.enabled or not text or self.excluded(text):
            return None
        if kind not in KINDS:
            kind = "other"
        if origin not in ORIGINS:
            raise ValueError("origin must be explicit or observed")
        digest = sha256_hex(normalise(text))
        if origin == "observed" and self._tombstoned(text):
            return None  # you deleted this before; don't re-learn it
        for row in self.db.query("SELECT id, text, origin FROM memories"):
            if normalise(row["text"]) == normalise(text):
                if origin == "explicit" and row["origin"] != "explicit":
                    self.confirm(row["id"], by=by)
                return row["id"]
        mid = new_id("mem")
        now = now_iso()
        with self.db.tx() as c:
            if origin == "explicit":  # saying it again yourself overrides an earlier deletion
                c.execute("DELETE FROM tombstones WHERE hash = ?", (digest,))
            c.execute("INSERT INTO memories (id, text, kind, origin, confidence, source_record, created_at, verified_at)"
                      " VALUES (?,?,?,?,?,?,?,?)",
                      (mid, text, kind, origin, confidence if confidence is not None else (1.0 if origin == "explicit" else 0.6),
                       source_record, now, now if origin == "explicit" else None))
            c.execute("INSERT INTO memories_fts (id, text) VALUES (?, ?)", (mid, text))
            self.audit.record("memory.added", actor=by, memory_id=mid, kind=kind, origin=origin, chars=len(text))
        return mid

    def get(self, memory_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM memories WHERE id = ?", (memory_id,))
        if row is None:
            raise KeyError(memory_id)
        return dict(row)

    def list(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.query(
            "SELECT * FROM memories ORDER BY important DESC, created_at DESC LIMIT ?", (limit,))]

    def search(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        q = fts_query(query)
        if not q:
            return []
        rows = self.db.query(
            "SELECT m.*, bm25(memories_fts) AS rank FROM memories_fts f JOIN memories m ON m.id = f.id "
            "WHERE memories_fts MATCH ? ORDER BY m.important DESC, rank LIMIT ?", (q, limit))
        return [dict(r) for r in rows]

    def confirm(self, memory_id: str, *, by: str) -> None:
        with self.db.tx() as c:
            if c.execute("UPDATE memories SET origin = 'explicit', confidence = 1.0, verified_at = ? WHERE id = ?",
                         (now_iso(), memory_id)).rowcount != 1:
                raise KeyError(memory_id)
            self.audit.record("memory.confirmed", actor=by, memory_id=memory_id)

    def edit(self, memory_id: str, text: str, *, by: str) -> None:
        """Correct a memory. The wrong version is tombstoned so it isn't re-learned."""
        old = self.get(memory_id)
        text = " ".join(text.split()).strip(" .")[:MAX_TEXT]
        if not text:
            raise ValueError("memory text cannot be empty")
        with self.db.tx() as c:
            c.execute("INSERT OR IGNORE INTO tombstones (hash, created_at) VALUES (?, ?)",
                      (sha256_hex(normalise(old["text"])), now_iso()))
            c.execute("UPDATE memories SET text = ?, origin = 'explicit', confidence = 1.0, verified_at = ? WHERE id = ?",
                      (text, now_iso(), memory_id))
            c.execute("DELETE FROM memories_fts WHERE id = ?", (memory_id,))
            c.execute("INSERT INTO memories_fts (id, text) VALUES (?, ?)", (memory_id, text))
            self.audit.record("memory.edited", actor=by, memory_id=memory_id, chars=len(text))

    def set_important(self, memory_id: str, important: bool, *, by: str) -> None:
        with self.db.tx() as c:
            if c.execute("UPDATE memories SET important = ? WHERE id = ?", (int(important), memory_id)).rowcount != 1:
                raise KeyError(memory_id)
            self.audit.record("memory.important", actor=by, memory_id=memory_id, important=important)

    def delete(self, memory_id: str, *, by: str) -> None:
        old = self.get(memory_id)
        with self.db.tx() as c:
            c.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            c.execute("DELETE FROM memories_fts WHERE id = ?", (memory_id,))
            c.execute("INSERT OR IGNORE INTO tombstones (hash, created_at) VALUES (?, ?)",
                      (sha256_hex(normalise(old["text"])), now_iso()))
            self.audit.record("memory.deleted", actor=by, memory_id=memory_id)

    def forget(self, query: str, *, by: str, dry_run: bool = True) -> dict[str, Any]:
        """Everything matching ``query``: preview with dry_run, delete otherwise."""
        mems = self.search(query, limit=500)
        recs = self.search_records(query, limit=500)
        if not dry_run:
            for m in mems:
                try:
                    self.delete(m["id"], by=by)
                except KeyError:
                    pass
            for r in recs:
                self.delete_record(r["id"], by=by)
            self.audit.record("memory.forget", actor=by, memories=len(mems), records=len(recs))
        return {"memories": [{"id": m["id"], "text": m["text"]} for m in mems],
                "records": [{"id": r["id"], "snippet": r["snippet"], "created_at": r["created_at"]} for r in recs]}

    def export(self) -> dict[str, Any]:
        return {"exported_at": now_iso(), "memories": self.list(limit=100_000),
                "records": [dict(r) for r in self.db.query("SELECT * FROM records ORDER BY created_at")]}

    def counts(self) -> dict[str, int]:
        return {"memories": self.db.one("SELECT COUNT(*) FROM memories")[0],
                "unconfirmed": self.db.one("SELECT COUNT(*) FROM memories WHERE origin = 'observed'")[0],
                "records": self.db.one("SELECT COUNT(*) FROM records")[0]}

    # ---- recall for prompts ------------------------------------------------------------
    def recall(self, query: str) -> list[dict[str, Any]]:
        """Your profile (who you are, what you prefer) plus memories matching the words of ``query``.
        The profile is included even when the words don't overlap: "greet me" should know you're Ken."""
        if not self.settings.enabled:
            return []
        out = {m["id"]: m for m in self.profile()}
        for m in self.search(query, limit=self.settings.recall_limit):
            out.setdefault(m["id"], m)
        return list(out.values())

    def profile(self, limit: int = PROFILE_LIMIT) -> list[dict[str, Any]]:
        """Confirmed facts about you: memories marked important, or that read like a profile fact ("call me…",
        "I'm vegetarian", "I prefer…", "my sister…"). Unconfirmed guesses never count. Small and capped."""
        rows = self.db.query("SELECT * FROM memories WHERE origin = 'explicit' ORDER BY important DESC, created_at DESC "
                             "LIMIT 200")
        # Exclusions are checked when a memory is saved; checked again here because the profile goes into every
        # prompt, and a topic excluded later must stop being sent.
        picked = [dict(r) for r in rows if (r["important"] or PROFILE.match(r["text"])) and not self.excluded(r["text"])]
        return picked[:limit]

    @staticmethod
    def context_message(memories: list[dict[str, Any]]) -> Message | None:
        if not memories:
            return None
        lines = []
        for m in memories:
            status = "confirmed" if m["origin"] == "explicit" else "unconfirmed — noticed earlier, may be wrong"
            lines.append(f"- {m['text']} ({status}; noted {m['created_at'][:10]})")
        return Message("system", "What you remember about the owner (use only if relevant; it may be out of date):\n"
                       + "\n".join(lines), Category.MEMORY)

    # ---- learning from a chat turn -----------------------------------------------------
    def explicit_request(self, message: str) -> str | None:
        m = REMEMBER.match(message)
        return m.group("fact").strip() if m else None

    def learn_from(self, session: str, user_text: str, reply: str, *, background: bool = True) -> None:
        """Archive the exchange, store any explicit "remember…" fact, and (optionally) let the LOCAL model
        notice facts you stated. Extraction never uses a cloud model."""
        rid = self.add_record(session, "user", user_text)
        self.add_record(session, "assistant", reply)
        if rid is None:
            return
        fact = self.explicit_request(user_text)
        if fact:
            self.remember(fact, origin="explicit", source_record=rid)
            return
        if self.settings.extract and self.models is not None:
            if background:
                threading.Thread(target=self._extract_quietly, args=(user_text, rid), daemon=True).start()
            else:
                self._extract(user_text, rid)

    def _extract_quietly(self, text: str, record_id: str) -> None:
        # Best-effort background learning: it must never crash the app (e.g. JARVIS shutting down mid-way).
        try:
            self._extract(text, record_id)
        except Exception:
            pass

    def _extract(self, text: str, record_id: str) -> list[str]:
        if len(text.split()) < 4:
            return []
        try:
            r = self.models.complete(Need("extract", prefer="speed", local_only=True), ChatRequest((
                Message("system", EXTRACT_PROMPT, Category.SYSTEM_PROMPT),
                Message("user", text[:3000], Category.CONVERSATION)), max_tokens=300, temperature=0.0, json_mode=True),
                purpose="memory extraction")
            items = parse_json_output(r.text, ("memories",))["memories"]
        except (NoModelAvailable, ProviderError, InvalidModelOutput, KeyError, TypeError):
            return []
        added = []
        for item in items[:3] if isinstance(items, list) else []:
            if isinstance(item, dict) and isinstance(item.get("text"), str) and 3 <= len(item["text"]) <= 300:
                mid = self.remember(item["text"], kind=item.get("kind", "fact"), origin="observed",
                                    source_record=record_id, by="system")
                if mid:
                    added.append(mid)
        return added


def settings_from(data: dict[str, Any]) -> MemorySettings:
    return MemorySettings(enabled=bool(data.get("enabled", True)), extract=bool(data.get("extract", True)),
                          exclude_topics=tuple(str(t) for t in data.get("exclude_topics", [])),
                          recall_limit=int(data.get("recall_limit", 5)))


def iter_lines(memories: Iterable[dict[str, Any]]) -> Iterable[str]:
    for m in memories:
        flag = "✓" if m["origin"] == "explicit" else "?"
        yield f"{m['id']}  {flag} [{m['kind']}] {m['text']}  ({m['created_at'][:10]})"


__all__ = ["MemorySettings", "MemoryStore", "settings_from"]
