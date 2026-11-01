"""Settling a step whose outcome is unknown: only you can, with Face ID on the phone; never guessed."""

import json

from test_dashboard import call
from test_remote import paired, remote_dash  # noqa: F401  (fixture)

from jarvis.core import StepSpec


def _uncertain(k):
    tid = k.tasks.create("Send the invoice", goal="Send the invoice", actor="user:test", context={"runner": "cli"},
                         steps=[StepSpec("Draft", "fs", "list", {"path": "/tmp"}), StepSpec("Send", "fs", "list", {"path": "/tmp"})])
    steps = k.tasks.steps(tid)
    with k.db.tx() as c:
        c.execute("UPDATE tasks SET state = 'blocked' WHERE id = ?", (tid,))
        c.execute("UPDATE steps SET state = 'done' WHERE id = ?", (steps[0]["id"],))
        c.execute("UPDATE steps SET state = 'uncertain' WHERE id = ?", (steps[1]["id"],))
    return tid, steps[1]["id"]


def test_state_names_each_step_so_the_page_can_settle_it(dash):
    d, _, _ = dash
    tid, sid = _uncertain(d.kernel)
    task = next(t for t in json.loads(call(d, "/api/state")[2])["tasks"] if t["id"] == tid)
    assert [s["state"] for s in task["steps"]] == ["done", "uncertain"] and task["steps"][1]["id"] == sid


def test_yes_marks_it_done_and_the_mission_continues(dash):
    d, _, _ = dash
    tid, sid = _uncertain(d.kernel)
    status, _, body = call(d, f"/api/tasks/{tid}/steps/{sid}/resolve", {"happened": True})
    assert status == 200 and json.loads(body)["state"] == "queued"
    assert d.kernel.tasks.step(sid)["state"] == "done"
    ev = [e for e in d.kernel.audit.entries() if e["event"] == "step.resolved"][-1]["payload"]
    assert ev["happened"] is True and ev.get("step_id") == sid


def test_no_means_it_will_be_done_again(dash):
    d, _, _ = dash
    tid, sid = _uncertain(d.kernel)
    assert call(d, f"/api/tasks/{tid}/steps/{sid}/resolve", {"happened": False})[0] == 200
    assert d.kernel.tasks.step(sid)["state"] == "pending"


def test_only_a_clear_yes_or_no_and_only_for_uncertain_steps(dash):
    d, _, _ = dash
    tid, sid = _uncertain(d.kernel)
    for bad in ({}, {"happened": "yes"}, {"happened": 1}, {"happened": None}):
        assert call(d, f"/api/tasks/{tid}/steps/{sid}/resolve", bad)[0] == 400, bad
    assert d.kernel.tasks.step(sid)["state"] == "uncertain"  # nothing guessed
    assert call(d, f"/api/tasks/{tid}/steps/{sid}/resolve", {"happened": True})[0] == 200
    assert call(d, f"/api/tasks/{tid}/steps/{sid}/resolve", {"happened": False})[0] >= 400  # already settled
    assert call(d, f"/api/tasks/{tid}/steps/{sid}/resolve", {"happened": True}, headers={"X-Requested-By": "x"})[0] == 403


def test_settling_from_the_phone_needs_face_id(remote_dash):  # noqa: F811
    d, *_ = remote_dash
    phone, _ = paired(d)
    tid, sid = _uncertain(d.kernel)
    path = f"/api/tasks/{tid}/steps/{sid}/resolve"
    assert phone.req(path, {"happened": True})[0] == 403
    assert d.kernel.tasks.step(sid)["state"] == "uncertain"
    assert phone.req(path, phone.face_id(path, {"happened": True}))[0] == 200
    assert d.kernel.tasks.step(sid)["state"] == "done"


def test_page_offers_yes_no_with_honest_warnings(dash):
    d, _, _ = dash
    js = call(d, "/static/app.js")[2].decode()
    settle = js.split("async function settleStep(t, s, happened) {")[1].split("\n}\n")[0]
    assert "JARVIS will do this step again" in settle and "it may happen twice" in settle
    assert "act(`/api/tasks/${t.id}/steps/${s.id}/resolve`, { happened })" in settle
    assert "/^\\/api\\/tasks\\/[\\w-]+\\/steps\\/[\\w-]+\\/resolve$/" in js  # Face ID / Touch ID on the client too
