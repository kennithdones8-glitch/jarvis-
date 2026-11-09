"""Wires the kernel components together around one data directory."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .approvals import Approvals
from .audit import AuditLog
from .db import Database
from .killswitch import KillSwitch
from .permissions import PermissionEngine, Policy
from .tasks import TaskEngine, TaskStore, Verifier
from .tools import ToolGateway, ToolRegistry


def default_home() -> Path:
    if env := os.environ.get("JARVIS_HOME"):
        return Path(env).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "JARVIS"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "jarvis"


class Kernel:
    def __init__(
        self,
        home: str | Path | None = None,
        *,
        policy_path: str | Path | None = None,
        config_path: str | Path | None = None,
        secrets=None,
        registry: ToolRegistry | None = None,
        verifiers: dict[str, Verifier] | None = None,
        **engine_options,
    ):
        self.home = Path(home) if home else default_home()
        self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.policy_path = Path(policy_path) if policy_path else self.home / "policy.toml"
        self.config_path = Path(config_path) if config_path else self.home / "jarvis.toml"

        from ..models import build_model_service, load_model_config  # models depend on core, not vice versa

        self.model_config = load_model_config(self.config_path)
        from .fileperms import make_private

        made_private = make_private(self.home)  # before the database opens, so nothing is readable meanwhile
        db_path = self.home / "jarvis.db"
        if not db_path.exists():  # a new database starts private (SQLite gives its -wal/-shm files the same mode)
            os.close(os.open(db_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
        self.db = Database(db_path)
        made_private |= make_private(self.home)  # files SQLite has just created
        self.audit = AuditLog(self.db)
        if made_private:
            self.audit.record("privacy.files_made_private", changed=made_private)
        self.killswitch = KillSwitch(self.db, self.audit)

        # JARVIS's own state and its policy are never writable by its tools.
        protected = [self.home, self.policy_path, self.config_path]
        if self.policy_path.exists():
            self.policy = Policy.load(self.policy_path, protected=protected)
        else:
            self.policy = Policy.empty(protected=protected)
        self.permissions = PermissionEngine(self.policy)
        self.approvals = Approvals(self.db, self.audit)
        if registry is None:
            from ..tools import default_registry

            registry = default_registry(self.home, searxng_url=self.model_config.searxng_url,
                                        permissions=self.permissions)
        self.registry = registry
        self.gateway = ToolGateway(self.registry, self.permissions, self.approvals, self.audit, self.killswitch)
        self.tasks = TaskStore(self.db, self.audit)
        self.engine = TaskEngine(self.tasks, self.gateway, self.killswitch, self.audit, verifiers=verifiers,
                                 **engine_options)

        self.models = build_model_service(self.model_config, self.db, self.audit, self.approvals, self.killswitch,
                                          secrets=secrets, workdir=str(self.home / "claude-workdir"))

        from ..memory import MemoryStore, settings_from

        self.memory = MemoryStore(self.db, self.audit, settings_from(self.model_config.memory), self.models)
        try:   # tier 7 routing nudges (empty unless the owner turned tier 7 on)
            from ..learn.autopilot import apply_to_router
            apply_to_router(self)
        except Exception:  # noqa: BLE001 - never stop JARVIS from starting over an optional nudge
            pass

    def forget(self, query: str, *, by: str, dry_run: bool = True) -> dict:
        """Everything JARVIS keeps that mentions ``query``: memories, conversation records and finished
        task history. Preview with dry_run; delete otherwise. Running tasks are listed, not touched."""
        from .tasks import TERMINAL, TaskState

        out = self.memory.forget(query, by=by, dry_run=dry_run)
        tasks = self.tasks.find(query)
        out["tasks"] = [{**t, "deletable": TaskState(t["state"]) in TERMINAL} for t in tasks]
        # ratings whose comment mentions it (e.g. a rating stored before answers had record ids); the text is only
        # returned as a count, never shown back
        q = (query or "").strip().lower()
        rated = [r["id"] for r in self.db.query("SELECT id, reason FROM feedback WHERE reason IS NOT NULL")
                 if q and q in r["reason"].lower()]
        out["ratings"] = len(rated)
        # saved plans (Mission Control) whose request mentions it
        plans = [r["id"] for r in self.db.query("SELECT id, request FROM plan_jobs") if q and q in r["request"].lower()]
        out["plans"] = len(plans)
        if not dry_run:
            for t in out["tasks"]:
                if t["deletable"]:
                    self.tasks.delete(t["id"], by=by)
            with self.db.tx() as c:
                for t in out["tasks"]:
                    if t["deletable"]:
                        c.execute("DELETE FROM feedback WHERE target = 'task' AND ref = ?", (t["id"],))
                c.executemany("DELETE FROM feedback WHERE id = ?", [(i,) for i in rated])
                c.executemany("DELETE FROM plan_jobs WHERE id = ?", [(i,) for i in plans])
            if rated:
                self.audit.record("memory.ratings_forgotten", actor=by, count=len(rated))
            self.db.checkpoint()  # with secure_delete, no copy of the deleted text is left in the files
        return out

    def start(self) -> list[str]:
        """Record startup and recover tasks interrupted by a previous crash or shutdown."""
        self.audit.record("kernel.started", pid=os.getpid(), policy_loaded=self.policy_path.exists(),
                          roots=[str(r) for r in self.policy.roots])
        return self.engine.recover()

    def close(self) -> None:
        self.gateway.shutdown()
        self.db.close()
