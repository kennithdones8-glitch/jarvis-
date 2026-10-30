import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from helpers import build_registry

from jarvis.core import StepSpec, TaskState, Verification
from jarvis.core.tasks import InvalidTransition, StepState


class FakeClock:
    def __init__(self):
        self.t = 1_000.0

    def __call__(self):
        return self.t


def file_verifier(root):
    def verify(task, steps):
        path = Path(root) / "notes" / "brief.md"
        ok = path.exists() and "Sources" in path.read_text()
        return Verification(ok, {"path": str(path), "exists": path.exists()})
    return verify


def test_end_to_end_with_approval_and_evidence(make_kernel, root):
    (root / "input.txt").write_text("raw research notes")
    k = make_kernel(verifiers={"brief": file_verifier(root)})
    tid = k.tasks.create(
        "summarise my notes into a brief",
        steps=[
            StepSpec("read input", "fs", "read", {"path": f"{root}/input.txt"}),
            StepSpec("draft brief outside notes (needs approval)", "fs", "write",
                     {"path": f"{root}/draft.md", "content": "draft"}, depends_on=[0]),
            StepSpec("save brief", "fs", "write",
                     {"path": f"{root}/notes/brief.md", "content": "# Brief\n## Sources\n- input.txt"}, depends_on=[1]),
        ],
        context={"verifier": "brief"},
    )
    assert k.engine.run(tid) is TaskState.AWAITING_APPROVAL
    assert not (root / "draft.md").exists()
    assert k.engine.run(tid) is TaskState.AWAITING_APPROVAL  # still pending; nothing re-runs

    [pending] = k.approvals.pending(task_id=tid)
    k.approvals.decide(pending["id"], approve=True, by="user:test")
    assert k.engine.run(tid) is TaskState.COMPLETED

    task = k.tasks.get(tid)
    assert task["result"]["evidence"]["exists"] is True
    assert [s["state"] for s in k.tasks.steps(tid)] == ["done"] * 3
    assert k.tasks.latest_checkpoint(tid)["data"]["completed_step"] == 2
    events = [e["event"] for e in k.audit.entries(task_id=tid, limit=500)]
    assert "approval.requested" in events and "task.verified" in events
    assert k.audit.verify().ok


def test_rejection_fails_task_honestly(make_kernel, root):
    k = make_kernel()
    tid = k.tasks.create("write outside notes", steps=[
        StepSpec("write", "fs", "write", {"path": f"{root}/x.md", "content": "c"})])
    k.engine.run(tid)
    [p] = k.approvals.pending(task_id=tid)
    k.approvals.decide(p["id"], approve=False, by="user:test")
    assert k.engine.run(tid) is TaskState.FAILED
    assert "rejected" in k.tasks.get(tid)["error"]
    assert not (root / "x.md").exists()


def test_failed_verification_is_not_reported_as_complete(make_kernel, root):
    k = make_kernel(verifiers={"brief": file_verifier(root)})
    tid = k.tasks.create("brief", steps=[
        StepSpec("save without sources", "fs", "write", {"path": f"{root}/notes/brief.md", "content": "no refs"})],
        context={"verifier": "brief"})
    assert k.engine.run(tid) is TaskState.FAILED
    assert k.tasks.get(tid)["error"] == "verification failed"


def test_unknown_verifier_fails(make_kernel, root):
    k = make_kernel()
    tid = k.tasks.create("x", steps=[StepSpec("read", "fs", "read", {"path": f"{root}/notes"})],
                         context={"verifier": "nope"})
    (root / "notes" / "f").write_text("")
    k.tasks.steps(tid)
    assert k.engine.run(tid) is TaskState.FAILED


def test_invalid_transitions_rejected(make_kernel):
    k = make_kernel()
    tid = k.tasks.create("x")
    with pytest.raises(InvalidTransition):
        k.tasks.transition(tid, TaskState.COMPLETED)
    k.engine.cancel(tid)
    with pytest.raises(InvalidTransition):
        k.tasks.transition(tid, TaskState.RUNNING)
    with pytest.raises(InvalidTransition):
        k.engine.cancel(tid)


def test_bad_dependencies_rejected(make_kernel):
    k = make_kernel()
    with pytest.raises(ValueError):
        k.tasks.create("x", steps=[StepSpec("a", "fs", "read", {}, depends_on=[0])])


def test_bounded_retries_with_backoff(make_kernel):
    calls, clock = [], FakeClock()
    k = make_kernel(registry=build_registry(calls, flaky_failures=2), clock=clock, backoff_base=10)
    tid = k.tasks.create("flaky", steps=[StepSpec("flaky", "test", "flaky", max_attempts=3)])
    assert k.engine.run(tid) is TaskState.RUNNING           # attempt 1 failed; waiting 10s
    assert k.engine.run(tid) is TaskState.RUNNING           # too early: nothing runs
    assert len(calls) == 1
    clock.t += 10
    assert k.engine.run(tid) is TaskState.RUNNING           # attempt 2 failed; waiting 20s
    clock.t += 19
    k.engine.run(tid)
    assert len(calls) == 2
    clock.t += 1
    assert k.engine.run(tid) is TaskState.COMPLETED         # attempt 3 succeeds
    assert len({op for _, op in calls}) == 1                 # same operation id across retries


def test_retry_limit_reached(make_kernel):
    calls, clock = [], FakeClock()
    k = make_kernel(registry=build_registry(calls, flaky_failures=99), clock=clock, backoff_base=1)
    tid = k.tasks.create("flaky", steps=[StepSpec("flaky", "test", "flaky", max_attempts=2)])
    k.engine.run(tid)
    clock.t += 5
    assert k.engine.run(tid) is TaskState.FAILED
    assert len(calls) == 2 and "retry limit" in k.audit.entries(task_id=tid)[-1]["payload"]["reason"]


def test_timeout_on_non_idempotent_step_blocks_instead_of_retrying(make_kernel):
    k = make_kernel(registry=build_registry(timeout_s=0.2))
    tid = k.tasks.create("x", steps=[StepSpec("mutating call", "test", "slow_mutation", {"seconds": 1})])
    assert k.engine.run(tid) is TaskState.BLOCKED
    [step] = k.tasks.steps(tid)
    assert step["state"] == StepState.UNCERTAIN and step["attempts"] == 1
    with pytest.raises(InvalidTransition):
        k.engine.resume(tid)
    k.engine.resolve_uncertain(tid, step["id"], happened=True)
    assert k.engine.run(tid) is TaskState.COMPLETED


def test_emergency_stop_pauses_then_requires_explicit_resume(make_kernel, root):
    k = make_kernel()
    tid = k.tasks.create("x", steps=[StepSpec("w", "fs", "write", {"path": f"{root}/notes/a", "content": "1"})])
    k.engine.emergency_stop(by="user:test", reason="test")
    assert k.engine.run(tid) is TaskState.QUEUED and not (root / "notes" / "a").exists()
    k.killswitch.release(by="user:test", confirm=True)
    assert k.engine.run(tid) is TaskState.COMPLETED


def test_pause_resume_cancel(make_kernel, root):
    k = make_kernel()
    tid = k.tasks.create("x", steps=[StepSpec("w", "fs", "write", {"path": f"{root}/notes/a", "content": "1"})])
    k.engine.pause(tid)
    assert k.engine.run(tid) is TaskState.PAUSED
    k.engine.resume(tid)
    k.engine.cancel(tid)
    assert k.tasks.get(tid)["state"] == TaskState.CANCELLED
    assert not (root / "notes" / "a").exists()


def test_corrupt_checkpoint_skipped(make_kernel, root):
    k = make_kernel()
    tid = k.tasks.create("x", steps=[StepSpec("w", "fs", "write", {"path": f"{root}/notes/a", "content": "1"})])
    k.engine.run(tid)
    with k.db.tx() as c:
        c.execute("INSERT INTO checkpoints (task_id, step_id, ts, data) VALUES (?, NULL, 'now', '{corrupt')", (tid,))
    assert k.tasks.latest_checkpoint(tid)["data"]["completed_step"] == 0


CRASH_SCRIPT = textwrap.dedent("""
    import os, sys
    sys.path.insert(0, {tests!r})
    from helpers import build_registry, fs_handler
    import helpers
    from jarvis.core import Kernel, StepSpec

    root = {root!r}
    def crashing(action, args, ctx):
        if action == {crash_action!r} and ("two" in args["path"] or "log" in args["path"]):
            if {crash_after!r}:
                fs_handler(action, args, ctx)   # the side effect lands...
            os._exit(1)                          # ...then the process dies before recording it
        return fs_handler(action, args, ctx)
    helpers.fs_handler = crashing
    reg = build_registry(reconcile_appends={reconcile!r})
    reg._tools["fs"].handler = crashing
    k = Kernel({home!r}, policy_path={policy!r}, registry=reg)
    tid = k.tasks.create("crash test", steps=[
        StepSpec("step one", "fs", "write", {{"path": root + "/notes/one.md", "content": "1"}}),
        StepSpec("step two", "fs", {crash_action!r}, {step_two_args}, depends_on=[0]),
        StepSpec("step three", "fs", "write", {{"path": root + "/notes/three.md", "content": "3"}}, depends_on=[1]),
    ])
    print(tid, flush=True)
    k.engine.run(tid)
""")


def run_crash(make_kernel, tmp_path, root, *, crash_action, crash_after, reconcile):
    make_kernel().close()  # writes policy.toml + initialises the database
    args = ('{"path": root + "/notes/log.md", "line": "entry"}' if crash_action == "append"
            else '{"path": root + "/notes/two.md", "content": "2"}')
    script = CRASH_SCRIPT.format(tests=str(Path(__file__).parent), root=str(root), home=str(tmp_path / "home"),
                                 policy=str(tmp_path / "policy.toml"), crash_action=crash_action,
                                 crash_after=crash_after, reconcile=reconcile, step_two_args=args)
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 1, proc.stderr
    tid = proc.stdout.strip()
    k = make_kernel(registry=build_registry(reconcile_appends=reconcile))
    assert k.tasks.get(tid)["state"] == TaskState.RUNNING  # what the dead process left behind
    assert k.start() == [tid]
    return k, tid


def test_crash_recovery_resumes_idempotent_step(make_kernel, tmp_path, root):
    k, tid = run_crash(make_kernel, tmp_path, root, crash_action="write", crash_after=False, reconcile=False)
    assert k.tasks.get(tid)["state"] == TaskState.QUEUED
    assert k.engine.run(tid) is TaskState.COMPLETED
    assert [p.name for p in sorted((root / "notes").iterdir())] == ["one.md", "three.md", "two.md"]
    steps = k.tasks.steps(tid)
    assert steps[0]["attempts"] == 1  # completed work was not repeated
    assert steps[1]["attempts"] == 2


def test_crash_recovery_never_repeats_uncertain_non_idempotent_step(make_kernel, tmp_path, root):
    k, tid = run_crash(make_kernel, tmp_path, root, crash_action="append", crash_after=True, reconcile=False)
    assert k.tasks.get(tid)["state"] == TaskState.BLOCKED
    assert k.engine.run(tid) is TaskState.BLOCKED
    assert (root / "notes" / "log.md").read_text().count("entry") == 1
    step = k.tasks.steps(tid)[1]
    k.engine.resolve_uncertain(tid, step["id"], happened=True)
    assert k.engine.run(tid) is TaskState.COMPLETED
    assert (root / "notes" / "log.md").read_text().count("entry") == 1


def test_crash_recovery_reconciles_when_tool_can_tell(make_kernel, tmp_path, root):
    k, tid = run_crash(make_kernel, tmp_path, root, crash_action="append", crash_after=True, reconcile=True)
    assert k.tasks.steps(tid)[1]["state"] == StepState.DONE  # reconcile found the op id in the file
    assert k.engine.run(tid) is TaskState.COMPLETED
    assert (root / "notes" / "log.md").read_text().count("entry") == 1


def test_crash_recovery_reruns_append_that_never_landed(make_kernel, tmp_path, root):
    k, tid = run_crash(make_kernel, tmp_path, root, crash_action="append", crash_after=False, reconcile=True)
    assert k.engine.run(tid) is TaskState.COMPLETED
    assert (root / "notes" / "log.md").read_text().count("entry") == 1
