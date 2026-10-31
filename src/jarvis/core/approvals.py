"""Approval requests.

An approval is bound to the exact (task, tool, action, resource, arguments) it was asked for,
and is single-use: approving "write file A with content X" does not authorise writing
different content, a different file, or a second write. A rejection for a resource blocks
every tool from touching that resource for the rest of the task.
"""

from __future__ import annotations

from typing import Any

from .audit import AuditLog
from .db import Database
from .permissions import Decision
from .util import canonical_json, new_id, now_iso, sha256_hex

PENDING, APPROVED, REJECTED, CONSUMED, EXPIRED = "pending", "approved", "rejected", "consumed", "expired"


def args_hash(tool: str, action: str, args: dict[str, Any]) -> str:
    return sha256_hex(canonical_json({"tool": tool, "action": action, "args": args}))


class ApprovalStateError(RuntimeError):
    pass


class Approvals:
    def __init__(self, db: Database, audit: AuditLog):
        self.db = db
        self.audit = audit

    def get(self, approval_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM approvals WHERE id = ?", (approval_id,))
        if row is None:
            raise KeyError(approval_id)
        return dict(row)

    def pending(self, *, task_id: str | None = None) -> list[dict[str, Any]]:
        if task_id is None:
            rows = self.db.query("SELECT * FROM approvals WHERE state = ? ORDER BY created_at", (PENDING,))
        else:
            rows = self.db.query(
                "SELECT * FROM approvals WHERE state = ? AND task_id IS ? ORDER BY created_at", (PENDING, task_id)
            )
        return [dict(r) for r in rows]

    def find_usable(self, *, task_id: str | None, tool: str, action: str, resource: str | None, digest: str) -> str | None:
        row = self.db.one(
            "SELECT id FROM approvals WHERE state = ? AND task_id IS ? AND tool = ? AND action = ? "
            "AND resource IS ? AND args_hash = ? ORDER BY created_at LIMIT 1",
            (APPROVED, task_id, tool, action, resource, digest),
        )
        return row["id"] if row else None

    def claim(self, *, task_id: str | None, tool: str, action: str, resource: str | None, digest: str) -> str | None:
        """Find a matching approved request and mark it used in ONE transaction, so two concurrent callers
        can never both spend the same single-use approval. Returns its id, or None."""
        with self.db.tx() as conn:
            row = conn.execute(
                "SELECT id FROM approvals WHERE state = ? AND task_id IS ? AND tool = ? AND action = ? "
                "AND resource IS ? AND args_hash = ? ORDER BY created_at LIMIT 1",
                (APPROVED, task_id, tool, action, resource, digest)).fetchone()
            if row is None:
                return None
            conn.execute("UPDATE approvals SET state = ? WHERE id = ? AND state = ?", (CONSUMED, row["id"], APPROVED))
            self.audit.record("approval.consumed", approval_id=row["id"])
            return row["id"]

    def is_rejected(self, *, task_id: str | None, tool: str, action: str, resource: str | None) -> bool:
        if task_id is None:
            return False
        if resource is not None:
            row = self.db.one(
                "SELECT 1 FROM approvals WHERE state = ? AND task_id = ? AND resource = ?", (REJECTED, task_id, resource)
            )
        else:
            row = self.db.one(
                "SELECT 1 FROM approvals WHERE state = ? AND task_id = ? AND tool = ? AND action = ? AND resource IS NULL",
                (REJECTED, task_id, tool, action),
            )
        return row is not None

    def request(
        self,
        *,
        task_id: str | None,
        step_id: str | None,
        tool: str,
        action: str,
        digest: str,
        decision: Decision,
        summary: str,
    ) -> str:
        with self.db.tx() as conn:
            existing = conn.execute(
                "SELECT id FROM approvals WHERE state = ? AND task_id IS ? AND tool = ? AND action = ? "
                "AND resource IS ? AND args_hash = ?",
                (PENDING, task_id, tool, action, decision.resource, digest),
            ).fetchone()
            if existing:
                return existing["id"]
            aid = new_id("appr")
            conn.execute(
                "INSERT INTO approvals (id, task_id, step_id, tool, action, resource, args_hash, tier, reason, summary,"
                " state, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (aid, task_id, step_id, tool, action, decision.resource, digest, int(decision.tier),
                 decision.reason, summary, PENDING, now_iso()),
            )
            self.audit.record(
                "approval.requested", task_id=task_id, approval_id=aid, tool=tool, action=action,
                resource=decision.resource, tier=int(decision.tier), reason=decision.reason, summary=summary,
            )
        return aid

    def decide(self, approval_id: str, *, approve: bool, by: str) -> None:
        if not by.startswith("user"):
            raise PermissionError("only a user may decide an approval")
        with self.db.tx() as conn:
            row = conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
            if row is None:
                raise KeyError(approval_id)
            if row["state"] != PENDING:
                raise ApprovalStateError(f"approval {approval_id} is {row['state']}, not pending")
            state = APPROVED if approve else REJECTED
            conn.execute(
                "UPDATE approvals SET state = ?, decided_at = ?, decided_by = ? WHERE id = ?",
                (state, now_iso(), by, approval_id),
            )
            self.audit.record(f"approval.{state}", actor=by, task_id=row["task_id"], approval_id=approval_id)

    def consume(self, approval_id: str) -> None:
        with self.db.tx() as conn:
            cur = conn.execute(
                "UPDATE approvals SET state = ? WHERE id = ? AND state = ?", (CONSUMED, approval_id, APPROVED)
            )
            if cur.rowcount != 1:
                raise ApprovalStateError(f"approval {approval_id} is not usable")
            self.audit.record("approval.consumed", approval_id=approval_id)

    def restore(self, approval_id: str) -> None:
        """Undo ``consume`` after a failed call, so the identical request can be retried."""
        with self.db.tx() as conn:
            cur = conn.execute("UPDATE approvals SET state = ? WHERE id = ? AND state = ?",
                               (APPROVED, approval_id, CONSUMED))
            if cur.rowcount == 1:
                self.audit.record("approval.restored", approval_id=approval_id)

    def expire_for_task(self, task_id: str) -> int:
        with self.db.tx() as conn:
            cur = conn.execute(
                "UPDATE approvals SET state = ? WHERE task_id = ? AND state IN (?, ?)",
                (EXPIRED, task_id, PENDING, APPROVED),
            )
            if cur.rowcount:
                self.audit.record("approval.expired", task_id=task_id, count=cur.rowcount)
            return cur.rowcount
