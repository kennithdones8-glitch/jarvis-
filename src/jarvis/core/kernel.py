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
        self.db = Database(self.home / "jarvis.db")
        self.audit = AuditLog(self.db)
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

    def forget(self, query: str, *, by: str, dry_run: bool = True) -> dict:
        """Everything JARVIS keeps that mentions ``query``: memories, conversation records and finished
        task history. Preview with dry_run; delete otherwise. Running tasks are listed, not touched."""
        from .tasks import TERMINAL, TaskState

        out = self.memory.forget(query, by=by, dry_run=dry_run)
        tasks = self.tasks.find(query)
        out["tasks"] = [{**t, "deletable": TaskState(t["state"]) in TERMINAL} for t in tasks]
        if not dry_run:
            for t in out["tasks"]:
                if t["deletable"]:
                    self.tasks.delete(t["id"], by=by)
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
