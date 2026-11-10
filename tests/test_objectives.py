"""Objectives: an outcome pursued through ordinary missions. Only you change them; progress counts real mission
states; autopilot plans (prepare) or also runs (pursue, Mac only) the next mission through the same planner and
approvals, and stops after two failures in a row, under the emergency stop and the initiative pause."""

import json
import re
from datetime import date, timedelta

import pytest
from test_dashboard import call

from jarvis import objectives
from jarvis.core import Kernel
from jarvis.core.db import SCHEMA_VERSION
from jarvis.core.tasks import StepSpec


@pytest.fixture
def k(tmp_path):
    kernel = Kernel(tmp_path / "home")
    yield kernel
    kernel.close()


def _mission(k, goal, state="completed", *, verified=True):
    tid = k.tasks.create(goal, goal=goal, steps=[StepSpec("Note", "fs", "list", {"path": "."})], actor="user:cli",
                         context={})
    with k.db.tx() as c:
        c.execute("UPDATE tasks SET state = ? WHERE id = ?", (state, tid))
    if state == "completed":
        k.audit.record("task.verified", task_id=tid, verifier="mission_verified", ok=verified,
                       evidence={"unconfirmed": 0 if verified else 1})
    return tid


def test_schema_v11_and_rules(k):
    assert SCHEMA_VERSION >= 11 and k.db.schema_version == SCHEMA_VERSION
    with pytest.raises(PermissionError):
        objectives.create(k, "Learn Spanish", by="jarvis")
    for bad in ({"priority": 9}, {"deadline": "soon"}):
        with pytest.raises(objectives.ObjectiveError):
            objectives.create(k, "Learn Spanish", by="user:dashboard", **bad)
    o = objectives.create(k, "Learn Spanish", criteria=["hold a 10-minute conversation"], priority=4, by="user:dashboard")
    assert objectives.valid_id(o["id"]) and o["state"] == "active" and o["autopilot"] == "suggest"
    with pytest.raises(objectives.ObjectiveError):
        objectives.set_state(k, o["id"], "active", by="user:dashboard")          # already active
    assert objectives.set_state(k, o["id"], "paused", by="user:dashboard")["state"] == "paused"
    with pytest.raises(objectives.ObjectiveError):
        objectives.set_state(k, o["id"], "achieved", by="user:dashboard")        # paused → resume first
    with pytest.raises(PermissionError):
        objectives.set_autopilot(k, o["id"], "pursue", by="jarvis:objective")    # never JARVIS itself
    events = [e["event"] for e in k.audit.entries(limit=10)]
    assert "objective.created" in events and "objective.state" in events
    assert "Spanish" not in json.dumps([e["payload"] for e in k.audit.entries(limit=10)])   # ids only in the log


def test_progress_counts_real_mission_states(k):
    o = objectives.create(k, "Move the home office", by="user:dashboard")
    for goal, state, ok in (("Book movers", "completed", True), ("Network checklist", "completed", False),
                            ("Block the week", "running", True)):
        objectives.link_mission(k, o["id"], _mission(k, goal, state, verified=ok), source="test")
    p = objectives.get(k, o["id"])["progress"]
    assert p == {"missions": 3, "done": 2, "confirmed": 1, "failed": 0, "in_flight": 1}


def test_next_request_asks_for_one_mission_knowing_the_history(k):
    o = objectives.create(k, "Move the home office", criteria=["desk set up"], deadline="2026-12-15", by="user:dashboard")
    objectives.link_mission(k, o["id"], _mission(k, "Book movers"), source="test")
    objectives.link_mission(k, o["id"], _mission(k, "Find a router", "failed"), source="test")
    r = objectives.next_request(objectives.get(k, o["id"]))
    assert "Objective: Move the home office" in r and "Done means: desk set up" in r and "Deadline: 2026-12-15" in r
    assert "Already done: Book movers" in r and "Tried and failed: Find a router" in r
    assert r.endswith("Plan only the next single mission towards this objective.")


def test_autopilot_due_rules(k):
    a = objectives.create(k, "Goal A", by="user:dashboard")
    b = objectives.create(k, "Goal B", by="user:dashboard")
    c = objectives.create(k, "Goal C", by="user:dashboard")
    objectives.set_autopilot(k, b["id"], "prepare", by="user:dashboard")
    objectives.set_autopilot(k, c["id"], "pursue", by="user:dashboard")
    due = {o["id"]: run for o, run in objectives.due_for_autopilot(k, pending=set())}
    assert due == {b["id"]: False, c["id"]: True}                               # suggest never plans
    assert c["id"] not in {o["id"] for o, _ in objectives.due_for_autopilot(k, pending={c["id"]})}
    objectives.link_mission(k, c["id"], _mission(k, "in flight", "running"), source="test")
    assert c["id"] not in {o["id"] for o, _ in objectives.due_for_autopilot(k, pending=set())}
    k.killswitch.engage(by="user:cli", reason="t")
    assert objectives.due_for_autopilot(k, pending=set()) == []
    assert a


def test_two_failures_in_a_row_pause_it_and_the_feed_says_so(k):
    o = objectives.create(k, "Fix the printer", by="user:dashboard")
    objectives.set_autopilot(k, o["id"], "pursue", by="user:dashboard")
    for goal in ("try one", "try two"):
        objectives.link_mission(k, o["id"], _mission(k, goal, "failed"), source="test")
    assert objectives.due_for_autopilot(k, pending=set()) == []
    assert objectives.get(k, o["id"])["state"] == "paused"
    assert any(e["event"] == "objective.paused_after_failures" for e in k.audit.entries(limit=10))
    assert [i["key"] for i in objectives.feed_items(k)] == [f"objective-stuck:{o['id']}"]


def test_feed_items_weighted_by_priority(k):
    low = objectives.create(k, "Low one", priority=1, by="user:dashboard")
    high = objectives.create(k, "High one", priority=5, by="user:dashboard")
    due = objectives.create(k, "Due soon", deadline=(date.today() + timedelta(days=2)).isoformat(), by="user:dashboard")
    done = objectives.create(k, "All done", by="user:dashboard")
    objectives.link_mission(k, done["id"], _mission(k, "the only step"), source="test")
    items = {i["key"].split(":")[0] + ":" + i["key"].split(":")[1][-4:]: i for i in objectives.feed_items(k)}
    s = {i["key"]: i["score"] for i in objectives.feed_items(k)}
    assert s[f"objective-next:{high['id']}"] > s[f"objective-next:{low['id']}"]
    assert f"objective-deadline:{due['id']}" in s and f"objective-done:{done['id']}" in s
    assert items


def test_initiative_feed_includes_objectives(k):
    from jarvis import initiative
    o = objectives.create(k, "Write the book", by="user:dashboard")
    assert f"objective-next:{o['id']}" in {i["key"] for i in initiative.candidates(k)}


def test_forget_and_delete(k):
    o = objectives.create(k, "Plan the surprise party", criteria=["venue booked"], by="user:dashboard")
    tid = _mission(k, "Call venues")
    objectives.link_mission(k, o["id"], tid, source="test")
    assert k.forget("surprise party", by="user:cli")["objectives"] == 1          # preview
    k.forget("surprise party", by="user:cli", dry_run=False)
    assert k.db.one("SELECT COUNT(*) FROM objectives")[0] == 0
    assert k.db.one("SELECT COUNT(*) FROM links WHERE dst = ?", (o["id"],))[0] == 0
    assert k.tasks.get(tid)   # missions stay ordinary task history


def test_autopilot_route_is_mac_only():
    from jarvis.remote import LOCAL_ONLY
    assert any(re.fullmatch(p, "/api/objectives/obj-0123456789/autopilot") for p in LOCAL_ONLY)
    assert not any(re.fullmatch(p, "/api/objectives/obj-0123456789/state") for p in LOCAL_ONLY)


def test_dashboard_routes_and_plan_link(dash):
    d, script, root = dash
    status, _, body = call(d, "/api/objectives", {"outcome": "Tidy my notes folder", "priority": 4})
    assert status == 200
    oid = json.loads(body)["id"]
    assert call(d, "/api/objectives", {"outcome": "x"})[0] == 400
    assert [o["id"] for o in json.loads(call(d, "/api/objectives")[2])["objectives"]] == [oid]
    assert json.loads(call(d, "/api/state")[2])["objectives"][0]["id"] == oid
    script["plan"] = {"goal": "List the notes folder", "steps": [
        {"description": "List the folder", "tool": "fs", "action": "list", "args": {"path": str(root)}}]}
    job = json.loads(call(d, f"/api/objectives/{oid}/plan", {})[2])["job_id"]
    import time
    for _ in range(100):
        if d.jobs[job]["state"] != "planning":
            break
        time.sleep(0.05)
    assert d.jobs[job]["state"] == "ready" and d.jobs[job]["objective"] == oid
    tid = json.loads(call(d, f"/api/plan/{job}/run", {})[2])["task_id"]
    assert [m["id"] for m in objectives.missions(d.kernel, oid)] == [tid]
    assert call(d, f"/api/objectives/{oid}/state", {"state": "paused"})[0] == 200
    assert call(d, f"/api/objectives/{oid}/plan", {})[0] == 409                 # resume first
    assert call(d, "/api/objectives/obj-ffffffffff/state", {"state": "paused"})[0] == 404
    assert call(d, f"/api/objectives/{oid}/delete", {})[0] == 200


def test_pursue_runs_the_plan_through_the_same_engine(dash):
    d, script, root = dash
    oid = json.loads(call(d, "/api/objectives", {"outcome": "Keep the notes tidy"})[2])["id"]
    script["plan"] = {"goal": "List the notes folder", "steps": [
        {"description": "List the folder", "tool": "fs", "action": "list", "args": {"path": str(root)}}]}
    assert call(d, f"/api/objectives/{oid}/autopilot", {"level": "pursue"})[0] == 200
    # the dashboard's own maintenance loop may get there first on a slow machine: count attempts, not who made them
    d.objectives_tick()
    assert d.objectives_tick() == 0                                                # one at a time, rate-limited
    planned = [e for e in d.kernel.audit.entries(limit=100) if e["event"] == "objective.autoplanned"]
    assert len(planned) == 1
    import time
    for _ in range(100):
        if objectives.missions(d.kernel, oid):
            break
        time.sleep(0.05)
    ms = objectives.missions(d.kernel, oid)
    assert len(ms) == 1
    created = [e for e in d.kernel.audit.entries(task_id=ms[0]["id"], limit=50) if e["event"] == "task.created"]
    assert created and created[0]["actor"] == "jarvis:objective"     # recorded as JARVIS's, not yours


def test_a_mission_can_follow_another_of_the_same_objective(k):
    o = objectives.create(k, "Move the home office", by="user:dashboard")
    first = _mission(k, "Book movers", "running")
    objectives.link_mission(k, o["id"], first, source="test")
    o = objectives.get(k, o["id"])
    assert objectives.follow_on(o, None) == first                      # the latest mission still in progress
    assert objectives.follow_on(o, first) == first
    done = _mission(k, "Old one")
    objectives.link_mission(k, o["id"], done, source="test")
    with pytest.raises(objectives.ObjectiveError):
        objectives.follow_on(objectives.get(k, o["id"]), done)         # can't wait for a finished one
    second = _mission(k, "Block the week", "queued")
    objectives.link_mission(k, o["id"], second, source="test", after=first)
    m = {x["id"]: x for x in objectives.get(k, o["id"])["missions"]}
    assert m[second]["after"] == first and m[second]["waiting"] is True
    objectives.delete(k, o["id"], by="user:dashboard")
    assert k.db.one("SELECT COUNT(*) FROM links WHERE rel = ?", (objectives.AFTER,))[0] == 0


def test_the_runner_waits_for_the_mission_before_and_never_builds_on_a_failure(dash):
    d, *_ = dash
    k = d.kernel
    dep = _mission(k, "Foundation", "running")
    follower = k.tasks.create("Next", goal="Next", steps=[StepSpec("Note", "fs", "list", {"path": "."})], actor="user:cli",
                              context={"after": dep, "runner": "dashboard"})
    task = k.tasks.get(follower)
    assert d._dependency_met(task) is False                             # still running: wait
    with k.db.tx() as c:
        c.execute("UPDATE tasks SET state = 'completed' WHERE id = ?", (dep,))
    assert d._dependency_met(task) is True
    with k.db.tx() as c:
        c.execute("UPDATE tasks SET state = 'failed' WHERE id = ?", (dep,))
    assert d._dependency_met(task) is False
    assert k.tasks.get(follower)["state"] == "paused"                   # paused with the reason, never run
    assert "waits for a mission that failed" in (k.tasks.get(follower)["error"] or "")
    assert d._dependency_met({"context": {}}) is True                   # ordinary missions are unaffected


def test_plan_while_one_is_in_flight_queues_a_follower(dash):
    d, script, root = dash
    oid = json.loads(call(d, "/api/objectives", {"outcome": "Tidy my notes folder"})[2])["id"]
    first = _mission(d.kernel, "First tidy", "running")
    objectives.link_mission(d.kernel, oid, first, source="test")
    script["plan"] = {"goal": "List the notes folder", "steps": [
        {"description": "List the folder", "tool": "fs", "action": "list", "args": {"path": str(root)}}]}
    r = json.loads(call(d, f"/api/objectives/{oid}/plan", {})[2])
    assert r["after"] == first
    import time
    for _ in range(100):
        if d.jobs[r["job_id"]]["state"] != "planning":
            break
        time.sleep(0.05)
    tid = json.loads(call(d, f"/api/plan/{r['job_id']}/run", {})[2])["task_id"]
    assert d.kernel.tasks.get(tid)["context"]["after"] == first
    m = {x["id"]: x for x in objectives.missions(d.kernel, oid)}
    assert m[tid]["after"] == first
    assert call(d, f"/api/objectives/{oid}/plan", {"after": "t-not-mine"})[0] == 400


def test_the_morning_briefing_shows_objective_progress(k):
    from jarvis.proactive import build_briefing
    o = objectives.create(k, "Move the home office", deadline=(date.today() + timedelta(days=4)).isoformat(),
                          by="user:dashboard")
    objectives.link_mission(k, o["id"], _mission(k, "Book movers"), source="test")
    objectives.link_mission(k, o["id"], _mission(k, "Block the week", "running"), source="test")
    sec = next(s for s in build_briefing(k)["sections"] if s["title"] == "Objectives")
    assert sec["items"] == ["Move the home office: 1/2 missions done, 1 in progress, due in 4 days"]
