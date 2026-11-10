"""Evolution 3.0, phase 2 — Mission Control (Outcome Engine v2).

- Every mission has a definition of success decided from its plan (not by a model): one criterion per step.
- "Completed" means checked: files by content, Calendar events, reminders and notes read back from the app. A check
  that fails fails the mission; one that couldn't run leaves it "completed, not confirmed", never "verified".
- Planning jobs survive a restart: a plan waiting for you comes back; planning that was cut off starts again.
- A failed mission can be planned once more, told what happened; the new plan is reviewed like any other.
"""

import json

from test_dashboard import call, state, wait_for
from test_mac import FakeMac

from jarvis.core import TaskState
from jarvis.core.tasks import StepSpec
from jarvis.learn import Pipeline
from jarvis.orchestrator import Orchestrator
from jarvis.orchestrator.criteria import criteria_for
from jarvis.orchestrator.planner import Plan
from jarvis.tools import default_registry

ALLOW_MAC = """
[[rules]]
id = "test-mac-changes"
effect = "allow"
tools = ["calendar", "reminders", "notes", "mail"]
actions = ["add", "create", "draft"]
"""


def mac_kernel(make_kernel, tmp_path, fake):
    from conftest import DEFAULT_POLICY
    return make_kernel(policy=DEFAULT_POLICY + ALLOW_MAC, registry=default_registry(tmp_path / "home", mac_runner=fake))


def submit(k, *steps):
    orch = Orchestrator(k)
    tid = orch.submit("test mission", Plan("plan", goal="test", steps=[StepSpec(*s) for s in steps]))
    return tid, k.engine.run(tid)


EVENT = ("Add the dentist", "calendar", "add", {"title": "Dentist", "start": "2026-12-01T10:00:00+00:00",
                                                "end": "2026-12-01T11:00:00+00:00"})


# ---- the definition of success ----------------------------------------------------------------------------------
def test_criteria_are_decided_from_the_plan_not_by_a_model():
    steps = [StepSpec("Save", "fs", "write", {"path": "~/n/a.md", "content": "x"}), StepSpec(*EVENT),
             StepSpec("Remind", "reminders", "add", {"title": "{{steps.0.text}}"}), StepSpec("Draft", "mail", "draft", {"to": ["a@b.c"]}),
             StepSpec("Summarise", "llm", "compose", {"instruction": "x"}), StepSpec("Pause", "music", "control", {"action": "pause"})]
    c = criteria_for(steps)
    assert [x["check"] for x in c] == ["file", "read_back", "read_back", "reported", "finished", "reported"]
    assert c[0]["text"] == "the file ~/n/a.md exists with exactly what was written"
    assert c[1]["text"] == "the event “Dentist” is in Calendar"
    assert c[2]["text"] == "the reminder is in Reminders"            # a title filled in later isn't shown as {{…}}
    assert "can't be read back" in c[3]["text"]                      # said plainly, never claimed as verified


def test_a_submitted_mission_carries_its_criteria(make_kernel, tmp_path):
    k = mac_kernel(make_kernel, tmp_path, FakeMac())
    tid = Orchestrator(k).submit("x", Plan("plan", goal="x", steps=[StepSpec(*EVENT)]))
    ctx = k.tasks.get(tid)["context"]
    assert ctx["verifier"] == "mission_verified" and ctx["criteria"][0]["check"] == "read_back"


# ---- checking it -----------------------------------------------------------------------------------------------
def test_an_event_is_read_back_before_the_mission_counts_as_done(make_kernel, tmp_path):
    fake = FakeMac()
    k = mac_kernel(make_kernel, tmp_path, fake)
    tid, st = submit(k, EVENT)
    assert st is TaskState.COMPLETED
    assert [c[0] for c in fake.calls] == ["calendar.add", "calendar.find"]          # added, then looked for
    ev = k.tasks.get(tid)["result"]["evidence"]
    assert ev["checks"] == [{"step": 0, "check": "read_back", "text": "the event “Dentist” is in Calendar", "status": "verified"}]
    assert ev["unconfirmed"] == 0


def test_a_tool_that_returned_but_left_nothing_fails_the_mission(make_kernel, tmp_path):
    class Forgetful(FakeMac):   # Calendar says it added the event, but it isn't there
        def __call__(self, name, args, timeout):
            r = super().__call__(name, args, timeout)
            if name == "calendar.add":
                self.events.clear()
            return r
    k = mac_kernel(make_kernel, tmp_path, Forgetful())
    tid, st = submit(k, EVENT)
    assert st is TaskState.FAILED                                                   # never "completed" on the tool's word
    assert k.tasks.get(tid)["result"]["evidence"]["checks"][0]["status"] == "failed"


def test_a_check_that_cannot_run_is_unconfirmed_never_verified(make_kernel, tmp_path):
    fake = FakeMac()   # the stand-in has no reminders.find: the read-back can't run
    k = mac_kernel(make_kernel, tmp_path, fake)
    tid, st = submit(k, ("Remind", "reminders", "add", {"title": "Call mum", "due": "2026-12-01T18:00:00+00:00"}),
                     ("Draft", "mail", "draft", {"to": ["sam@example.com"], "subject": "Hi", "body": "Hello"}))
    assert st is TaskState.COMPLETED
    ev = k.tasks.get(tid)["result"]["evidence"]
    assert [c["status"] for c in ev["checks"]] == ["unconfirmed", "reported"] and ev["unconfirmed"] == 1
    Pipeline(k).ingest()
    out = k.db.one("SELECT verdict FROM outcomes WHERE kind = 'task' AND ref = ?", (tid,))
    assert out["verdict"] == "unverified"                                            # learning never counts it as verified


def test_older_missions_still_verify(make_kernel, tmp_path):
    from jarvis.orchestrator.criteria import criteria_for_rows
    k = mac_kernel(make_kernel, tmp_path, FakeMac())
    tid = k.tasks.create("old", steps=[StepSpec(*EVENT)], context={"verifier": "writes_verified", "runner": "cli"})
    Orchestrator(k)
    assert k.engine.run(tid) is TaskState.COMPLETED                                 # their verifier is unchanged
    assert criteria_for_rows(k.tasks.steps(tid))[0]["check"] == "read_back"


# ---- plans survive a restart -------------------------------------------------------------------------------------
def _restart(d):
    from jarvis.server import Dashboard
    d.shutdown()
    d2 = Dashboard(d.kernel, port=0, token="test-token", poll_s=0.05)
    d2.start()
    return d2


def _plan(root):
    return {"goal": "Save a note", "question": None, "cannot": None, "steps": [
        {"description": "Save", "tool": "fs", "action": "write", "args": {"path": f"{root}/kept.md", "content": "kept"}, "depends_on": []}]}


def test_a_plan_waiting_for_you_survives_a_restart(dash):
    d, script, root = dash
    script["plan"] = _plan(root)
    job = json.loads(call(d, "/api/plan", {"request": "save a note called kept"})[2])["job_id"]
    wait_for(lambda: next((x for x in state(d)["jobs"] if x["id"] == job and x["state"] == "ready"), None))
    d2 = _restart(d)
    try:
        j = next(x for x in state(d2)["jobs"] if x["id"] == job)
        assert j["kind"] == "plan" and j["restored"] and j["criteria"][0]["check"] == "file"
        tid = json.loads(call(d2, f"/api/plan/{job}/run", {})[2])["task_id"]
        appr = wait_for(lambda: state(d2)["approvals"])[0]
        call(d2, f"/api/approvals/{appr['id']}", {"approve": True})
        t = wait_for(lambda: next((t for t in state(d2)["tasks"] if t["id"] == tid and t["state"] == "completed"), None), timeout=20)
        assert (root / "kept.md").read_text() == "kept" and t["evidence"]["checks"][0]["status"] == "verified"
    finally:
        d2.shutdown()


def test_planning_that_was_cut_off_starts_again_after_a_restart(dash):
    d, script, root = dash
    script["plan"] = _plan(root)
    k = d.kernel
    d.shutdown()
    with k.db.tx() as c:   # what a crash mid-planning leaves behind
        c.execute("INSERT INTO plan_jobs (id, request, state, data, created_at, updated_at) VALUES ('j1', 'save a note', 'planning', ?, datetime('now'), datetime('now'))",
                  (json.dumps({"id": "j1", "request": "save a note", "state": "planning", "started": 0}),))
        c.execute("INSERT INTO plan_jobs (id, request, state, data, created_at, updated_at) VALUES ('old', 'ancient', 'ready', '{}', '2020-01-01', '2020-01-01')")
    d2 = _restart(d)
    try:
        j = wait_for(lambda: next((x for x in state(d2)["jobs"] if x["id"] == "j1" and x["state"] == "ready"), None))
        assert j["kind"] == "plan" and j["restored"]
        assert not any(x["id"] == "old" for x in state(d2)["jobs"])                     # stale jobs are dropped
        assert k.db.one("SELECT COUNT(*) FROM plan_jobs WHERE id = 'old'")[0] == 0
    finally:
        d2.shutdown()


# ---- one replan for a failed mission ------------------------------------------------------------------------------
def test_a_failed_mission_can_be_planned_again_once_and_is_reviewed_first(dash):
    d, script, root = dash
    script["plan"] = {"goal": "Summarise", "question": None, "cannot": None, "steps": [
        {"description": "Read the notes", "tool": "fs", "action": "read", "args": {"path": f"{root}/missing.txt"}, "depends_on": []}]}
    (root / "missing.txt").write_text("here at planning time")
    job = json.loads(call(d, "/api/plan", {"request": "summarise my notes"})[2])["job_id"]
    j = wait_for(lambda: next((x for x in state(d)["jobs"] if x["id"] == job and x["state"] == "ready"), None))
    assert j["kind"] == "plan", j
    (root / "missing.txt").unlink()                      # gone by the time it runs: the step fails
    tid = json.loads(call(d, f"/api/plan/{job}/run", {})[2])["task_id"]
    t = wait_for(lambda: next((t for t in state(d)["tasks"] if t["id"] == tid and t["state"] == "failed"), None), timeout=20)
    assert t["replannable"] is True

    (root / "missing.txt").write_text("found it")
    script["plan"] = {"goal": "Summarise", "question": None, "cannot": None, "steps": [
        {"description": "Read the notes again", "tool": "fs", "action": "read", "args": {"path": f"{root}/missing.txt"}, "depends_on": []}]}
    status, _, body = call(d, f"/api/tasks/{tid}/replan", {})
    job2 = json.loads(body)["job_id"]
    j2 = wait_for(lambda: next((x for x in state(d)["jobs"] if x["id"] == job2 and x["state"] == "ready"), None))
    assert status == 200 and j2["replan_of"] == tid and "earlier" not in j2
    assert not state(d)["approvals"] and next(t for t in state(d)["tasks"] if t["id"] == tid)["state"] == "failed"   # nothing ran by itself
    assert call(d, f"/api/tasks/{tid}/replan", {})[0] == 409                            # once
    assert next(t for t in state(d)["tasks"] if t["id"] == tid)["replannable"] is False
    tid2 = json.loads(call(d, f"/api/plan/{job2}/run", {})[2])["task_id"]
    t2 = wait_for(lambda: next((t for t in state(d)["tasks"] if t["id"] == tid2 and t["state"] in ("completed", "failed")), None), timeout=20)
    assert t2["state"] == "completed" and t2["replan_of"] == tid
    assert call(d, f"/api/tasks/{tid2}/replan", {})[0] == 409                           # a second attempt can't be replanned
    assert call(d, "/api/tasks/nope/replan", {})[0] == 404
    assert any(e["event"] == "mission.replan" for e in d.kernel.audit.entries(limit=50))


def test_the_new_plan_is_told_what_happened_without_file_contents(make_kernel, tmp_path):
    k = mac_kernel(make_kernel, tmp_path, FakeMac())
    tid = k.tasks.create("x", steps=[StepSpec("Read secrets.txt", "fs", "read", {"path": "/nope"})], context={"runner": "cli"})
    k.engine.run(tid)
    story = Orchestrator.failure_story(k.tasks.get(tid), k.tasks.steps(tid))
    assert "Read secrets.txt" in story and "failed" in story and "The mission ended with" in story


def test_forget_removes_saved_plans(dash):
    d, script, root = dash
    script["plan"] = _plan(root)
    job = json.loads(call(d, "/api/plan", {"request": "write to Biscuit's vet"})[2])["job_id"]
    wait_for(lambda: next((x for x in state(d)["jobs"] if x["id"] == job and x["state"] == "ready"), None))
    preview = json.loads(call(d, "/api/memory/forget", {"query": "Biscuit"})[2])
    assert preview["plans"] == 1 and d.kernel.db.one("SELECT COUNT(*) FROM plan_jobs")[0] == 1
    call(d, "/api/memory/forget", {"query": "Biscuit", "confirm": True})
    assert d.kernel.db.one("SELECT COUNT(*) FROM plan_jobs")[0] == 0
    assert not any(x["id"] == job for x in state(d)["jobs"])


def test_the_replan_hands_the_planner_what_happened(make_kernel, tmp_path):
    k = mac_kernel(make_kernel, tmp_path, FakeMac())
    orch = Orchestrator(k)
    seen = {}
    orch.planner.plan = lambda request, local_only=False, facts=None: seen.update(facts=facts) or Plan("cannot", message="x")
    orch.plan("save my notes", earlier="- step 1 (fs.read): Read notes — failed; error: no such file")
    assert "A first attempt at this request failed" in seen["facts"].content and "no such file" in seen["facts"].content
    orch.plan("save my notes")
    assert seen["facts"] is None                                                   # a first plan gets no such note
