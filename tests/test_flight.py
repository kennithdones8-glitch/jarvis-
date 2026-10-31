"""Flight Recorder: one task's whole story, in order, from what JARVIS already records. Read-only."""

import json

import pytest

from test_dashboard import call

from jarvis import flight
from jarvis.core import StepSpec, TaskState

SECRET = "PRIVATE-CONTENT-7319"


def approved_task(k, root, approve=True):
    (root / "input.txt").write_text("notes")
    tid = k.tasks.create("copy my notes", steps=[
        StepSpec("Read the notes", "fs", "read", {"path": f"{root}/input.txt"}),
        StepSpec("Save a copy outside Notes", "fs", "write", {"path": f"{root}/copy.md", "content": SECRET}, depends_on=[0]),
    ], actor="user:test")
    assert k.engine.run(tid) is TaskState.AWAITING_APPROVAL
    [pending] = k.approvals.pending(task_id=tid)
    k.approvals.decide(pending["id"], approve=approve, by="user:test")
    k.engine.run(tid)
    return tid


def test_the_whole_story_in_order(make_kernel, root):
    k = make_kernel()
    tid = approved_task(k, root)
    t = flight.timeline(k, tid)
    events = [e["event"] for e in t["events"]]
    assert events[0] == "task.created"
    order = [events.index(e) for e in ("approval.requested", "approval.approved", "approval.consumed")]
    assert order == sorted(order)  # asked, then approved, then used
    assert events.index("approval.consumed") < max(i for i, e in enumerate(events) if e == "tool.start")
    assert [e["seq"] for e in t["events"]] == sorted(e["seq"] for e in t["events"])
    approved = next(e for e in t["events"] if e["event"] == "approval.approved")
    assert approved["actor"] == "user:test" and approved["phase"] == "approval"
    s = t["summary"]
    assert (s["approvals_requested"], s["approved"], s["rejected"], s["steps_done"], s["steps"]) == (1, 1, 0, 2, 2)
    assert s["tools_run"] == 2 and t["task"]["state"] == "completed" and t["integrity"]["audit_chain_ok"]
    assert t["approvals"][0]["decided_by"] == "user:test"
    assert [e["text"] for e in t["events"] if e["event"] == "tool.result"] == ["Finished fs.read", "Finished fs.write"]


def test_holds_no_private_text(make_kernel, root):
    k = make_kernel()
    tid = approved_task(k, root)
    assert SECRET in (root / "copy.md").read_text()
    assert SECRET not in json.dumps(flight.timeline(k, tid))  # the audit log keeps fingerprints, not your text


def test_a_rejection_is_shown_as_a_problem(make_kernel, root):
    k = make_kernel()
    tid = approved_task(k, root, approve=False)
    t = flight.timeline(k, tid)
    assert t["summary"]["rejected"] == 1 and t["summary"]["problems"] >= 1
    assert any(e["problem"] and e["event"] == "task.state" for e in t["events"])
    assert "! " in flight.as_text(t)


def test_timeline_reports_a_damaged_audit_log(make_kernel, root):
    k = make_kernel()
    tid = approved_task(k, root)
    with k.db.tx() as c:
        c.execute("DROP TRIGGER audit_append_only_update")
        c.execute("UPDATE audit SET payload = '{\"n\":99}' WHERE seq = 2")
    t = flight.timeline(k, tid)
    assert t["integrity"]["audit_chain_ok"] is False
    assert "may be incomplete" in flight.as_text(t)


def test_unknown_task(make_kernel):
    with pytest.raises(KeyError):
        flight.timeline(make_kernel(), "task_nope")


def test_dashboard_and_cli(dash, capsys):
    from jarvis.cli import main as cli_main
    d, _, root = dash
    tid = d.kernel.tasks.create("look", steps=[StepSpec("List", "fs", "list", {"path": str(root)})],
                                context={"runner": "cli"})
    d.kernel.engine.run(tid)
    status, _, body = call(d, f"/api/tasks/{tid}/timeline")
    assert status == 200 and json.loads(body)["task"]["id"] == tid
    assert call(d, f"/api/tasks/{tid}/timeline", cookie=False)[0] == 401
    assert cli_main(["--home", str(d.kernel.home), "trace", tid]) == 0
    out = capsys.readouterr().out
    assert "Goal: look" in out and "Audit log: intact" in out
