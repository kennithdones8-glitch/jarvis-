"""v0.12 F1: one process runs a task at a time. Regression for the discovery repro where a second
process's startup 'recovered' a live task, ran a step twice and failed a healthy task."""

import threading
import time

import pytest

from jarvis.core import ActionSpec, Kernel, StepSpec, TaskState, Tier, ToolRegistry, ToolSpec
from jarvis.core.tasks import TaskBusy


def slow_registry(calls, seconds=1.5):
    def slow(action, args, ctx):
        calls.append(ctx.op_id)
        time.sleep(seconds)
        return {"ok": True}
    r = ToolRegistry()
    r.register(ToolSpec("slow", "", {"op": ActionSpec(Tier.READ, idempotent=True, timeout_s=10)}, slow))
    return r


@pytest.fixture
def two(tmp_path):
    (tmp_path / "policy.toml").write_text('[filesystem]\nroots = []\n')
    calls = []
    made = []

    def make(**kw):
        k = Kernel(tmp_path / "home", policy_path=tmp_path / "policy.toml", registry=slow_registry(calls), **kw)
        made.append(k)
        return k
    yield make, calls
    for k in made:
        k.close()


def test_second_process_does_not_hijack_a_live_task(two):
    make, calls = two
    a, b = make(), make()                                    # e.g. background dashboard + `jarvis do`
    tid = a.tasks.create("long job", steps=[StepSpec("one", "slow", "op"), StepSpec("two", "slow", "op", depends_on=[0])])
    result = {}
    t = threading.Thread(target=lambda: result.setdefault("a", a.engine.run(tid)))
    t.start()
    time.sleep(0.4)
    assert b.start() == []                                   # nothing "recovered" — A is alive and holds the lease
    with pytest.raises(TaskBusy):
        b.engine.run(tid)
    t.join()
    assert result["a"] is TaskState.COMPLETED and len(calls) == 2
    assert a.tasks.lease(tid) == (None, None)                # released when done


def test_crashed_owner_is_taken_over_and_reconciled(two):
    make, calls = two
    a = make()
    tid = a.tasks.create("job", steps=[StepSpec("one", "slow", "op")])
    # simulate a process that started the step and died: a lease held by a pid that doesn't exist
    a.tasks.transition(tid, TaskState.RUNNING)
    [step] = a.tasks.steps(tid)
    a.tasks.start_step(step["id"], "op_dead")
    a.tasks.claim(tid, f"{a.engine.owner.split(':')[0]}:999999:dead", ttl=3600)
    b = make()
    assert b.start() == [tid]                                # dead holder detected immediately
    assert b.engine.run(tid) is TaskState.COMPLETED and len(calls) == 1


def test_expired_lease_from_another_machine_is_taken_over_after_ttl(two):
    make, _ = two
    a = make(lease_ttl=0.3)
    tid = a.tasks.create("job", steps=[StepSpec("one", "slow", "op")])
    a.tasks.claim(tid, "other-host:123:x", ttl=0.3)          # can't check another host's pid → wait for expiry
    with pytest.raises(TaskBusy):
        a.engine.run(tid)
    time.sleep(0.4)
    assert a.engine.run(tid) is TaskState.COMPLETED


def test_heartbeat_keeps_lease_alive_during_long_steps(two):
    make, calls = two
    a = make(lease_ttl=0.3)                                  # step (1.5 s) is much longer than the ttl
    b = make(lease_ttl=0.3)
    tid = a.tasks.create("job", steps=[StepSpec("one", "slow", "op")])
    t = threading.Thread(target=lambda: a.engine.run(tid))
    t.start()
    time.sleep(0.9)                                          # three ttl periods later
    with pytest.raises(TaskBusy):
        b.engine.run(tid)
    t.join()
    assert len(calls) == 1


def test_cancel_from_another_process_is_a_request_not_a_takeover(two):
    make, calls = two
    a, b = make(), make()
    tid = a.tasks.create("job", steps=[StepSpec("one", "slow", "op"), StepSpec("two", "slow", "op", depends_on=[0])])
    result = {}
    t = threading.Thread(target=lambda: result.setdefault("a", a.engine.run(tid)))
    t.start()
    time.sleep(0.4)
    b.engine.cancel(tid, actor="user:test")                  # sets the control flag; A stops after the current step
    t.join()
    assert result["a"] is TaskState.CANCELLED and len(calls) == 1
