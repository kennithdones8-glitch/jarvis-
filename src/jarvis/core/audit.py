"""Append-only, hash-chained audit log.

Each entry's hash covers the previous entry's hash, so editing or deleting a past entry
breaks verification. SQLite triggers block UPDATE/DELETE as a second, casual-tamper guard.
Known limit: truncating the newest entries is not detectable from the chain alone; anchoring
the head hash outside the database (backups, the phone) is planned for a later milestone.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .db import Database
from .redact import redact
from .util import canonical_json, now_iso, sha256_hex

GENESIS = "0" * 64
MAX_STRING = 4000


def _truncate(value: Any) -> Any:
    if isinstance(value, str) and len(value) > MAX_STRING:
        return value[:MAX_STRING] + f"…[truncated {len(value) - MAX_STRING} chars]"
    if isinstance(value, dict):
        return {k: _truncate(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_truncate(v) for v in value]
    return value


def _entry_hash(prev_hash: str, ts: str, actor: str, event: str, task_id: str | None, payload: str) -> str:
    body = canonical_json({"ts": ts, "actor": actor, "event": event, "task_id": task_id, "payload": payload})
    return sha256_hex(prev_hash + body)


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    checked: int
    first_bad_seq: int | None = None
    reason: str | None = None


class AuditLog:
    def __init__(self, db: Database):
        self.db = db

    def record(self, event: str, *, actor: str = "system", task_id: str | None = None, **payload: Any) -> str:
        clean = canonical_json(_truncate(redact(payload)))
        with self.db.tx() as conn:
            row = conn.execute("SELECT hash FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
            prev = row["hash"] if row else GENESIS
            ts = now_iso()
            digest = _entry_hash(prev, ts, actor, event, task_id, clean)
            conn.execute(
                "INSERT INTO audit (ts, actor, event, task_id, payload, prev_hash, hash) VALUES (?,?,?,?,?,?,?)",
                (ts, actor, event, task_id, clean, prev, digest),
            )
        return digest

    def entries(self, *, task_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        if task_id:
            rows = self.db.query(
                "SELECT * FROM audit WHERE task_id = ? ORDER BY seq DESC LIMIT ?", (task_id, limit)
            )
        else:
            rows = self.db.query("SELECT * FROM audit ORDER BY seq DESC LIMIT ?", (limit,))
        return [{**dict(r), "payload": json.loads(r["payload"])} for r in reversed(rows)]

    def verify(self) -> VerifyResult:
        prev = GENESIS
        checked = 0
        expected_seq = None
        for row in self.db.query("SELECT * FROM audit ORDER BY seq"):
            if expected_seq is not None and row["seq"] != expected_seq:
                return VerifyResult(False, checked, row["seq"], f"gap in sequence before seq {row['seq']}")
            if row["prev_hash"] != prev:
                return VerifyResult(False, checked, row["seq"], "previous-hash link broken")
            digest = _entry_hash(prev, row["ts"], row["actor"], row["event"], row["task_id"], row["payload"])
            if digest != row["hash"]:
                return VerifyResult(False, checked, row["seq"], "entry content does not match its hash")
            prev = row["hash"]
            expected_seq = row["seq"] + 1
            checked += 1
        return VerifyResult(True, checked)
