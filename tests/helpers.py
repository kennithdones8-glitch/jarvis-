"""Real (non-mocked) test tools that operate on the filesystem inside a temp workspace."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from jarvis.core import ActionSpec, ResourceKind, Tier, ToolError, ToolRegistry, ToolSpec
from jarvis.core.tools import RECONCILE_DONE, RECONCILE_NOT_DONE, CallContext

PATH = ResourceKind.PATH


def fs_handler(action: str, args: dict[str, Any], ctx: CallContext) -> Any:
    path = Path(ctx.resource)  # canonical path decided by the permission engine
    if action == "read":
        return {"content": path.read_text()}
    if action == "write":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(args["content"])
        return {"bytes": len(args["content"].encode())}
    if action == "append":
        with path.open("a") as fh:
            fh.write(f"{ctx.op_id}:{args['line']}\n")
        return {"appended": True}
    if action == "delete":
        path.unlink()
        return {"deleted": True}
    raise ToolError(f"unknown action {action}")


def append_reconcile(args: dict[str, Any], op_id: str) -> str:
    """Appends are tagged with the op id, so we can tell whether an interrupted append landed."""
    path = Path(args["path"]).expanduser()
    if not path.exists():
        return RECONCILE_NOT_DONE
    return RECONCILE_DONE if f"{op_id}:" in path.read_text() else RECONCILE_NOT_DONE


def build_registry(calls: list | None = None, *, reconcile_appends: bool = False, flaky_failures: int = 0,
                   timeout_s: float = 2.0) -> ToolRegistry:
    calls = calls if calls is not None else []
    reg = ToolRegistry()
    reg.register(ToolSpec("fs", "files in approved roots", {
        "read": ActionSpec(Tier.READ, "path", PATH),
        "write": ActionSpec(Tier.ROUTINE, "path", PATH, idempotent=True),
        "append": ActionSpec(Tier.ROUTINE, "path", PATH, idempotent=False,
                             reconcile=append_reconcile if reconcile_appends else None),
        "delete": ActionSpec(Tier.HIGH_RISK, "path", PATH, idempotent=False),
    }, fs_handler))

    def post(action: str, args: dict[str, Any], ctx: CallContext) -> Any:
        calls.append(("post", args["url"], ctx.op_id))
        return {"status": 200}

    reg.register(ToolSpec("net", "send data out", {
        "post": ActionSpec(Tier.EXTERNAL, "url", ResourceKind.URL, idempotent=False),
    }, post))

    state = {"left": flaky_failures}

    def flaky(action: str, args: dict[str, Any], ctx: CallContext) -> Any:
        calls.append(("flaky", ctx.op_id))
        if state["left"] > 0:
            state["left"] -= 1
            raise ToolError("temporary failure", retryable=True)
        return {"ok": True}

    def slow(action: str, args: dict[str, Any], ctx: CallContext) -> Any:
        time.sleep(args.get("seconds", 5))
        return {"ok": True}

    def big(action: str, args: dict[str, Any], ctx: CallContext) -> Any:
        return {"blob": "x" * 2000}

    def boom(action: str, args: dict[str, Any], ctx: CallContext) -> Any:
        raise ValueError("unexpected bug")

    reg.register(ToolSpec("test", "test-only behaviours", {
        "flaky": ActionSpec(Tier.READ, idempotent=True),
        "slow": ActionSpec(Tier.READ, idempotent=True, timeout_s=timeout_s),
        "slow_mutation": ActionSpec(Tier.READ, idempotent=False, timeout_s=timeout_s),
        "big": ActionSpec(Tier.READ, max_output_bytes=500),
        "boom": ActionSpec(Tier.READ, idempotent=True),
    }, lambda a, args, ctx: {"flaky": flaky, "slow": slow, "slow_mutation": slow, "big": big,
                             "boom": boom}[a](a, args, ctx)))
    return reg
