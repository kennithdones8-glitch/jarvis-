"""`jarvis drill`: recovery drills. Breaks a THROWAWAY JARVIS on purpose and checks that it recovers safely.

Each drill builds a fresh JARVIS in a temporary folder (its own database, approved folder, policy and small drill
tools), does something that goes wrong in real life (a hard crash mid-action, an emergency stop from another
process, two callers racing for one approval, a damaged checkpoint, a tampered audit log, losing the database and
restoring a backup, a second process trying to take over a running task), and checks the outcome. Your real
JARVIS, its data, the Keychain and your apps are never touched; the folder is deleted afterwards.

Crashes are real: a child process is killed with os._exit (no clean-up, like pulling the plug) at the exact moment
under test, and recovery runs in a separate process, as after a real restart.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .core import ActionSpec, Kernel, ResourceKind, StepSpec, Tier, ToolError, ToolRegistry, ToolSpec
from .core.tools import RECONCILE_DONE, RECONCILE_NOT_DONE, CallContext

PATH = ResourceKind.PATH


# ---- the drill's own small tools (files inside the throwaway folder only) --------------------------------------
def _handler(action: str, args: dict[str, Any], ctx: CallContext) -> Any:
    path = Path(ctx.resource)
    crash = os.environ.get("JARVIS_DRILL_CRASH")
    if action == "write":
        if crash == "write-before" and path.name == "two.txt":  # only the step under test, not the first write
            os._exit(1)
        path.write_text(args["content"])
        return {"bytes": len(args["content"])}
    if action == "note":  # a one-time action: appends a line tagged with its operation id
        if crash == "note-before":
            os._exit(1)
        with path.open("a") as fh:
            fh.write(f"{ctx.op_id}:{args['line']}\n")
        if crash == "note-after":
            os._exit(1)
        return {"appended": True}
    if action == "slow":
        time.sleep(float(args.get("seconds", 1.0)))
        return {"slept": True}
    raise ToolError(f"unknown drill action {action}")


def _note_reconcile(args: dict[str, Any], op_id: str) -> str:
    path = Path(args["path"]).expanduser()
    return RECONCILE_DONE if path.exists() and f"{op_id}:" in path.read_text() else RECONCILE_NOT_DONE


def registry(*, can_check: bool = False) -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(ToolSpec("drill", "drill tools", {
        "write": ActionSpec(Tier.ROUTINE, "path", PATH, idempotent=True),
        "note": ActionSpec(Tier.ROUTINE, "path", PATH, idempotent=False,
                           reconcile=_note_reconcile if can_check else None),
        "slow": ActionSpec(Tier.READ, "path", PATH, timeout_s=30),
    }, _handler))
    return reg


class Sandbox:
    """A throwaway JARVIS: data folder, approved folder and a policy that allows the drill tools there."""

    def __init__(self, base: Path, *, allow_changes: bool = True):
        self.base, self.home, self.work = base, base / "home", base / "work"
        self.work.mkdir(parents=True)
        rule = (f'\n[[rules]]\nid = "drill"\neffect = "allow"\ntools = ["drill"]\nactions = ["write", "note"]\n'
                f'resources = ["{self.work}/**"]\n') if allow_changes else ""
        (base / "policy.toml").write_text(f'[filesystem]\nroots = ["{self.work}"]\n{rule}')
        (base / "jarvis.toml").write_text("")

    def kernel(self, *, can_check: bool = False) -> Kernel:
        return Kernel(self.home, policy_path=self.base / "policy.toml", config_path=self.base / "jarvis.toml",
                      registry=registry(can_check=can_check))


CHILD = textwrap.dedent("""
    import os, sys
    from pathlib import Path
    from jarvis.drill import Sandbox
    from jarvis.core import StepSpec
    sb = Sandbox.__new__(Sandbox)
    sb.base = Path({base!r}); sb.home = sb.base / "home"; sb.work = sb.base / "work"
    k = sb.kernel(can_check={can_check})
    w = str(sb.work)
    tid = k.tasks.create("drill", steps=[
        StepSpec("first", "drill", "write", {{"path": w + "/one.txt", "content": "1"}}),
        StepSpec("second", "drill", {action!r}, {args}, depends_on=[0]),
        StepSpec("third", "drill", "write", {{"path": w + "/three.txt", "content": "3"}}, depends_on=[1]),
    ])
    print(tid, flush=True)
    os.environ["JARVIS_DRILL_CRASH"] = {crash!r}
    k.engine.run(tid)
    print("NO CRASH", flush=True)
""")


def _crash(sb: Sandbox, *, action: str, crash: str, can_check: bool) -> str:
    sb.kernel().close()  # create the database first
    args = ('{"path": w + "/log.txt", "line": "entry"}' if action == "note"
            else '{"path": w + "/two.txt", "content": "2"}')
    script = CHILD.format(base=str(sb.base), can_check=can_check, action=action, args=args, crash=crash)
    # -I: the child imports only the installed JARVIS (not files in the current folder or PYTHON* variables)
    p = subprocess.run([sys.executable, "-I", "-c", script], capture_output=True, text=True, timeout=120)
    if "NO CRASH" in p.stdout or p.returncode != 1:
        raise DrillError(f"the child process didn't crash as planned (exit {p.returncode}): {p.stderr[-300:]}")
    return p.stdout.split()[0]


class DrillError(RuntimeError):
    pass


def _expect(ok: bool, message: str) -> None:
    if not ok:
        raise DrillError(message)


# ---- the drills --------------------------------------------------------------------------------------------------
def drill_crash_one_time_action_unknown(sb: Sandbox) -> str:
    from .core.tasks import TaskState
    tid = _crash(sb, action="note", crash="note-after", can_check=False)
    k = sb.kernel()
    try:
        k.start()
        _expect(k.tasks.get(tid)["state"] == TaskState.BLOCKED, f"expected blocked, got {k.tasks.get(tid)['state']}")
        _expect(k.engine.run(tid) is TaskState.BLOCKED, "it ran again instead of waiting for you")
        lines = (sb.work / "log.txt").read_text().count("entry")
        _expect(lines == 1, f"the one-time action ran {lines} times")
        return "crashed right after a one-time action; JARVIS couldn't tell if it happened, so it stopped and asked (ran once)"
    finally:
        k.close()


def drill_crash_one_time_action_checked(sb: Sandbox) -> str:
    from .core.tasks import TaskState
    tid = _crash(sb, action="note", crash="note-after", can_check=True)
    k = sb.kernel(can_check=True)
    try:
        k.start()
        _expect(k.engine.run(tid) is TaskState.COMPLETED, "the task didn't finish after recovery")
        lines = (sb.work / "log.txt").read_text().count("entry")
        _expect(lines == 1, f"the one-time action ran {lines} times")
        return "crashed right after a one-time action; JARVIS checked, saw it had happened, and finished without repeating it"
    finally:
        k.close()


def drill_crash_before_action(sb: Sandbox) -> str:
    from .core.tasks import TaskState
    tid = _crash(sb, action="note", crash="note-before", can_check=True)
    k = sb.kernel(can_check=True)
    try:
        k.start()
        _expect(k.engine.run(tid) is TaskState.COMPLETED, "the task didn't finish after recovery")
        lines = (sb.work / "log.txt").read_text().count("entry")
        _expect(lines == 1, f"the action ran {lines} times (expected exactly once)")
        return "crashed just before a one-time action; JARVIS checked, saw it hadn't happened, and did it once"
    finally:
        k.close()


def drill_crash_repeatable_step(sb: Sandbox) -> str:
    from .core.tasks import TaskState
    tid = _crash(sb, action="write", crash="write-before", can_check=False)
    k = sb.kernel()
    try:
        k.start()
        _expect(k.engine.run(tid) is TaskState.COMPLETED, "the task didn't finish after recovery")
        steps = k.tasks.steps(tid)
        _expect(steps[0]["attempts"] == 1, "finished work was repeated")
        _expect(all((sb.work / f).exists() for f in ("one.txt", "two.txt", "three.txt")), "a file is missing")
        return "crashed mid-way; JARVIS resumed from the interrupted step without redoing finished work"
    finally:
        k.close()


def drill_emergency_stop_from_another_process(sb: Sandbox) -> str:
    from .core.killswitch import EmergencyStop
    from .core.tasks import TaskState
    a = sb.kernel()
    b = sb.kernel()  # e.g. the Terminal while the background service runs the task
    try:
        w = str(sb.work)
        tid = a.tasks.create("long job", steps=[
            StepSpec("wait", "drill", "slow", {"path": w, "seconds": 1.5}),
            StepSpec("then write", "drill", "write", {"path": f"{w}/after.txt", "content": "x"}, depends_on=[0])])
        out: dict = {}
        t = threading.Thread(target=lambda: out.setdefault("state", a.engine.run(tid)))
        t.start()
        time.sleep(0.5)
        b.engine.emergency_stop(by="user:drill", reason="drill")
        t.join(30)
        _expect(not (sb.work / "after.txt").exists(), "a step ran after the emergency stop")
        _expect(a.tasks.get(tid)["state"] == TaskState.PAUSED, f"expected paused, got {a.tasks.get(tid)['state']}")
        try:
            b.gateway.invoke("drill", "write", {"path": f"{w}/new.txt", "content": "x"})
            raise DrillError("a new action ran while the stop was on")
        except EmergencyStop:
            pass
        b.killswitch.release(by="user:drill", confirm=True)
        b.engine.resume(tid, actor="user:drill")
        _expect(b.engine.run(tid) is TaskState.COMPLETED, "the task didn't finish after release + resume")
        return "stop pressed in another process paused the running task, blocked new actions, and resuming finished it"
    finally:
        a.close()
        b.close()


def drill_approval_race(sb: Sandbox) -> str:
    from .core.tools import ApprovalRequired
    (sb.base / "policy.toml").write_text(f'[filesystem]\nroots = ["{sb.work}"]\n')  # no standing permission here
    k = sb.kernel()
    try:
        args = {"path": f"{sb.work}/log.txt", "line": "once"}
        try:
            k.gateway.invoke("drill", "note", args, task_id=None)
        except ApprovalRequired as exc:
            k.approvals.decide(exc.approval_id, approve=True, by="user:drill")
        results: list[str] = []

        def spend() -> None:
            try:
                k.gateway.invoke("drill", "note", args, task_id=None)
                results.append("ran")
            except ApprovalRequired:
                results.append("asked again")
        threads = [threading.Thread(target=spend) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        lines = (sb.work / "log.txt").read_text().count("once")
        _expect(results.count("ran") == 1 and lines == 1, f"one approval was spent {results.count('ran')} times")
        return "4 simultaneous attempts to use one approval: exactly 1 ran, the others had to ask again"
    finally:
        k.close()


def drill_damaged_checkpoint(sb: Sandbox) -> str:
    k = sb.kernel()
    try:
        w = str(sb.work)
        tid = k.tasks.create("x", steps=[StepSpec("w", "drill", "write", {"path": f"{w}/a.txt", "content": "1"})])
        k.engine.run(tid)
        with k.db.tx() as c:
            c.execute("INSERT INTO checkpoints (task_id, step_id, ts, data) VALUES (?, NULL, 'now', '{corrupt')", (tid,))
        cp = k.tasks.latest_checkpoint(tid)
        _expect(cp is not None and cp["data"].get("completed_step") == 0, "the damaged checkpoint was trusted")
        return "a corrupted checkpoint was skipped and the last good one used"
    finally:
        k.close()


def drill_tampered_audit_log(sb: Sandbox) -> str:
    k = sb.kernel()
    try:
        for i in range(5):
            k.audit.record("drill.event", n=i)
        _expect(k.audit.verify().ok, "the fresh audit log didn't verify")
        with k.db.tx() as c:
            c.execute("DROP TRIGGER audit_append_only_update")
            c.execute("UPDATE audit SET payload = '{\"n\":99}' WHERE seq = 3")
        r = k.audit.verify()
        _expect(not r.ok and r.first_bad_seq == 3, "an edited audit entry wasn't detected")
        return "an audit entry edited behind JARVIS's back (protections removed first) was detected at the exact entry"
    finally:
        k.close()


def drill_lost_database_restored(sb: Sandbox) -> str:
    from .backup import create_backup, restore_backup, verify_backup
    phrase = "drill-" + os.urandom(8).hex()  # a throwaway passphrase: the Keychain is never used
    k = sb.kernel()
    k.memory.remember("My drill fact is apricot.", origin="explicit", by="user:drill")
    k.close()
    b = create_backup(sb.home, sb.base / "policy.toml", sb.base / "jarvis.toml", dest_dir=sb.base / "backups",
                      passphrase=phrase)
    verify_backup(b.path, phrase)
    k = sb.kernel()
    k.memory.remember("Added after the backup.", origin="explicit", by="user:drill")
    k.close()
    for f in sb.home.glob("jarvis.db*"):  # the disk "lost" the database
        f.unlink()
    restore_backup(b.path, sb.home, sb.base / "policy.toml", sb.base / "jarvis.toml", passphrase=phrase)
    k = sb.kernel()
    try:
        texts = " | ".join(m["text"] for m in k.memory.list(limit=50))
        _expect("apricot" in texts, "the backed-up memory didn't come back")
        _expect("after the backup" not in texts, "the restore didn't return to the backup's point in time")
        _expect(k.audit.verify().ok, "the restored audit log doesn't verify")
        _expect(k.db.one("PRAGMA integrity_check")[0] == "ok", "the restored database failed its integrity check")
        return "deleted the database, restored the encrypted backup: memory back, audit log and database intact"
    finally:
        k.close()


def drill_no_hijack(sb: Sandbox) -> str:
    from .core.tasks import TaskBusy, TaskState
    a, b = sb.kernel(), sb.kernel()
    try:
        tid = a.tasks.create("job", steps=[StepSpec("wait", "drill", "slow", {"path": str(sb.work), "seconds": 1.5})])
        out: dict = {}
        t = threading.Thread(target=lambda: out.setdefault("state", a.engine.run(tid)))
        t.start()
        time.sleep(0.5)
        _expect(b.start() == [], "a second process 'recovered' a task that was still running")
        try:
            b.engine.run(tid)
            raise DrillError("a second process ran a task another process was running")
        except TaskBusy:
            pass
        t.join(30)
        _expect(out.get("state") is TaskState.COMPLETED, "the original process didn't finish its task")
        return "a second JARVIS process left a running task alone; the owner finished it"
    finally:
        a.close()
        b.close()


DRILLS: list[tuple[str, Callable[[Sandbox], str]]] = [
    ("Crash after one-time action, can't check", drill_crash_one_time_action_unknown),
    ("Crash after one-time action, can check", drill_crash_one_time_action_checked),
    ("Crash just before a one-time action", drill_crash_before_action),
    ("Crash during a repeatable step", drill_crash_repeatable_step),
    ("Emergency stop from another process", drill_emergency_stop_from_another_process),
    ("Two callers racing for one approval", drill_approval_race),
    ("Damaged checkpoint", drill_damaged_checkpoint),
    ("Tampered audit log", drill_tampered_audit_log),
    ("Lost database, restore from backup", drill_lost_database_restored),
    ("Second process tries to take over", drill_no_hijack),
]


@dataclass
class DrillResult:
    name: str
    passed: bool
    detail: str
    seconds: float


def run(only: list[str] | None = None) -> list[DrillResult]:
    results = []
    for name, fn in DRILLS:
        if only and not any(o.lower() in name.lower() for o in only):
            continue
        base = Path(tempfile.mkdtemp(prefix="jarvis-drill-"))
        started = time.monotonic()
        try:
            detail, ok = fn(Sandbox(base)), True
        except DrillError as exc:
            detail, ok = str(exc), False
        except Exception as exc:  # a drill that crashes is a failed drill, with the reason
            detail, ok = f"{type(exc).__name__}: {exc}", False
        finally:
            shutil.rmtree(base, ignore_errors=True)
        results.append(DrillResult(name, ok, detail, round(time.monotonic() - started, 1)))
    return results


def report(results: list[DrillResult]) -> str:
    passed = sum(r.passed for r in results)
    lines = [f"Recovery drills: {passed}/{len(results)} passed" + ("" if passed == len(results) else "  ← FIX BEFORE TRUSTING RECOVERY"),
             "(each ran on a throwaway JARVIS, deleted afterwards; your real data was not touched)", ""]
    for r in results:
        lines.append(f"{'✓' if r.passed else '✗'} {r.name:<40} {r.detail}  ({r.seconds}s)")
    return "\n".join(lines)


def as_json(results: list[DrillResult]) -> str:
    return json.dumps([r.__dict__ for r in results], indent=2)
