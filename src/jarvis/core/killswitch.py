"""Global emergency stop.

State lives in the database (not in memory), so a stop engaged from the CLI, the dashboard
or the phone is seen by every process on its next check. Releasing requires an explicit
confirmation from a user actor. A stop cannot undo external actions that already completed.
"""

from __future__ import annotations

import json
from typing import Any

from .audit import AuditLog
from .db import Database
from .util import now_iso

KEY = "emergency_stop"


class EmergencyStop(RuntimeError):
    pass


class KillSwitch:
    def __init__(self, db: Database, audit: AuditLog):
        self.db = db
        self.audit = audit

    def state(self) -> dict[str, Any] | None:
        row = self.db.one("SELECT value FROM meta WHERE key = ?", (KEY,))
        return json.loads(row["value"]) if row else None

    def engaged(self) -> bool:
        return self.state() is not None

    def check(self) -> None:
        state = self.state()
        if state is not None:
            raise EmergencyStop(f"emergency stop engaged by {state['by']}: {state['reason']}")

    def engage(self, *, by: str, reason: str) -> None:
        with self.db.tx() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                (KEY, json.dumps({"by": by, "reason": reason, "ts": now_iso()})),
            )
            self.audit.record("emergency_stop.engaged", actor=by, reason=reason)

    def release(self, *, by: str, confirm: bool) -> None:
        if confirm is not True:
            raise ValueError("releasing the emergency stop requires explicit confirmation")
        if not by.startswith("user"):
            raise PermissionError("only a user may release the emergency stop")
        with self.db.tx() as conn:
            conn.execute("DELETE FROM meta WHERE key = ?", (KEY,))
            self.audit.record("emergency_stop.released", actor=by)
