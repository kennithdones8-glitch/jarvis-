"""The project board: JARVIS opens and plans projects on the dashboard instead of leaving files in Notes, and pages it
made (e.g. animations) play only when the owner turned that on, sealed off from the dashboard."""

import json
import re

import pytest

from test_dashboard import call, state, wait_for

from jarvis.board import PLAY_HEADERS, BoardError, shape
from jarvis.core.permissions import Effect, Tier

@pytest.fixture
def kernel(make_kernel):
    return make_kernel()


ANIMATION = "<!doctype html><html><body><canvas id=c></canvas><script>let t=0;setInterval(()=>t++,16)</script></body></html>"


# ---- what gets saved, and how ----------------------------------------------------------------------------------------
def test_kind_is_worked_out_and_a_fenced_page_is_kept_as_bare_html():
    assert shape(ANIMATION, "Animation", None) == ("page", ANIMATION)
    wrapped = f"Here is your animation:\n\n```html\n{ANIMATION}\n```\nEnjoy!"
    assert shape(wrapped, "Bouncing ball", None) == ("page", ANIMATION)   # small models wrap HTML in prose and a fence
    assert shape("```python\nprint(1)\n```", "Script", None)[0] == "code"
    assert shape("def f():\n    return 1", "Helper", None)[0] == "code"
    assert shape("1. Buy wood\n2. Cut it", "Plan", None)[0] == "plan"
    assert shape("Remember the blue paint", "Thoughts", None)[0] == "note"
    assert shape("just words", "x", "note") == ("note", "just words")
    with pytest.raises(BoardError):
        shape("not html at all", "x", "page")
    with pytest.raises(BoardError):
        shape("x", "y", "binary")


def test_save_opens_the_project_replaces_by_title_and_retries_change_nothing(kernel):
    b = kernel.board
    r = b.save("Garden shed", "Plan", "1. Measure\n2. Buy wood", by="jarvis", summary="A shed for tools")
    assert r["changed"] and r["kind"] == "plan" and r["project"] == "Garden shed"
    again = b.save("garden  SHED", "plan", "1. Measure\n2. Buy wood", by="jarvis")  # same name, same text
    assert again["changed"] is False and again["item_id"] == r["item_id"]
    b.save("Garden shed", "Plan", "1. Measure twice\n2. Buy wood", by="jarvis")
    [p] = b.overview()
    assert p["title"] == "Garden shed" and p["summary"] == "A shed for tools" and p["state"] == "planning"
    assert [i["title"] for i in p["items"]] == ["Plan"] and b.item(r["item_id"])["content"].startswith("1. Measure twice")
    # the audit log says what was saved, never the content
    saved = [e for e in kernel.audit.entries() if e["event"] == "board.saved"]
    assert len(saved) == 2 and all("Measure" not in json.dumps(e) for e in saved)


def test_projects_change_state_and_archived_ones_come_back_when_used(kernel):
    b = kernel.board
    p = b.open("Learn guitar", "", by="user:dashboard")
    assert p["opened"] and b.open("learn guitar", by="jarvis")["opened"] is False
    b.set_state(p["id"], "archived", by="user:dashboard")
    assert b.overview() == [] and len(b.overview(include_archived=True)) == 1
    b.save("Learn guitar", "Chords", "G C D", by="jarvis")
    assert b.overview()[0]["state"] == "planning"
    with pytest.raises(BoardError):
        b.set_state(p["id"], "deleted", by="user:dashboard")
    with pytest.raises(KeyError):
        b.set_state("Learn guitar", "done", by="user:dashboard")   # by id only


# ---- the planner saves there, with your approval ----------------------------------------------------------------------
def test_saving_is_a_routine_change_that_asks_first_and_reading_does_not(kernel):
    assert kernel.registry.action("projects", "save").tier is Tier.ROUTINE
    assert kernel.registry.action("projects", "read").tier is Tier.READ
    d = kernel.permissions.evaluate(tool="projects", action="save", tier=Tier.ROUTINE)
    assert d.effect is Effect.CONFIRM


def test_planner_keeps_project_work_on_the_dashboard_and_files_only_when_named(kernel):
    from jarvis.orchestrator import Orchestrator
    prompt = Orchestrator(kernel).planner.system_prompt()
    assert "projects.save" in prompt and "Never put project work in Apple Notes" in prompt
    assert re.search(r"Save new documents in (\S+?)\.\s", prompt)    # a named file still goes to the notes folder
    assert "When the owner names a file" in prompt


def test_without_the_board_the_old_rule_stays(kernel):
    from jarvis.core.tools import ToolRegistry
    from jarvis.orchestrator.planner import Planner
    p = Planner(kernel.models, ToolRegistry(), roots=["/tmp"], notes_dir="/tmp/notes")
    assert p.save_rule() == "Save new documents in /tmp/notes."


def test_a_board_save_is_checked_by_reading_it_back():
    from jarvis.core.tasks import StepState
    from jarvis.orchestrator.criteria import criterion, make_verifier
    from jarvis.core.tasks import Verification

    class FakeBoard:
        items = {}

        def item(self, iid):
            if iid not in self.items:
                raise KeyError(iid)
            return self.items[iid]

    board = FakeBoard()
    c = criterion("projects", "save", {"project": "Shed", "title": "Plan"})
    assert c["check"] == "board" and "Shed" in c["text"]
    verify = make_verifier(None, lambda task, steps: Verification(True, {}), board)
    step = {"idx": 0, "state": StepState.DONE, "tool": "projects", "action": "save", "args": {}, "op_id": None,
            "result": {"item_id": "item_1", "sha256": "abc"}, "description": "Save"}
    task = {"context": {"criteria": [{"step": 0, **c}]}}
    assert verify(task, [step]).ok is False                       # nothing there: failed, never "verified"
    board.items["item_1"] = {"sha256": "abc"}
    assert verify(task, [step]).ok is True
    board.items["item_1"] = {"sha256": "changed since"}
    assert verify(task, [step]).ok is False


def test_the_reply_says_where_it_is_not_a_notes_folder():
    from jarvis.core.tasks import StepState
    from jarvis.orchestrator import saved_text
    step = {"idx": 0, "tool": "projects", "action": "save", "state": StepState.DONE, "args": {"content": "1. Measure"},
            "depends_on": [], "result": {"title": "Plan", "project": "Shed", "kind": "plan"}}
    text = saved_text([step])
    assert "project “Shed” on the dashboard" in text and "1. Measure" in text and "Notes" not in text
    page = saved_text([{**step, "args": {"content": ANIMATION}, "result": {"title": "Ball", "project": "Toys", "kind": "page"}}])
    assert "Play" in page and "<canvas" not in page


def test_chat_tells_the_owner_projects_live_on_the_dashboard():
    from jarvis.persona import PROJECTS_ABILITY, chat_abilities, priming_messages
    text = priming_messages(chat_abilities(True, lookups=True))[0].content
    assert PROJECTS_ABILITY in text and "Never tell the owner to look in Notes" in text


# ---- the dashboard ----------------------------------------------------------------------------------------------------
def test_a_mission_saves_to_the_board_after_approval_and_is_verified(dash):
    d, script, _ = dash
    script["plan"] = {"goal": "Plan the shed", "question": None, "cannot": None, "steps": [
        {"description": "Write the plan", "tool": "llm", "action": "compose", "args": {"instruction": "Plan a shed", "inputs": []}, "depends_on": []},
        {"description": "Keep it on the dashboard", "tool": "projects", "action": "save",
         "args": {"project": "Garden shed", "title": "Plan", "content": "{{steps.0.text}}"}, "depends_on": [0]}]}
    job = json.loads(call(d, "/api/plan", {"request": "start a project: a garden shed"})[2])["job_id"]
    wait_for(lambda: next((x for x in state(d)["jobs"] if x["id"] == job and x["state"] == "ready"), None))
    tid = json.loads(call(d, f"/api/plan/{job}/run", {})[2])["task_id"]
    appr = wait_for(lambda: state(d)["approvals"])[0]
    assert appr["task_id"] == tid and json.loads(call(d, "/api/board")[2])["projects"] == []   # nothing before you approve
    assert call(d, f"/api/approvals/{appr['id']}", {"approve": True})[0] == 200
    t = wait_for(lambda: next((t for t in state(d)["tasks"] if t["id"] == tid and t["state"] == "completed"), None))
    [p] = json.loads(call(d, "/api/board")[2])["projects"]
    assert p["title"] == "Garden shed" and [i["title"] for i in p["items"]] == ["Plan"]
    item = json.loads(call(d, f"/api/board/items/{p['items'][0]['id']}")[2])
    assert item["content"] == "Composed text." and item["task_id"] == tid
    assert [c["status"] for c in t["evidence"]["checks"] if c["check"] == "board"] == ["verified"]


def test_open_archive_and_delete_from_the_dashboard(dash):
    d, *_ = dash
    assert call(d, "/api/board/projects", {"title": ""})[0] == 400
    p = json.loads(call(d, "/api/board/projects", {"title": "Bird box", "summary": "For the garden"})[2])["project"]
    assert p["created_by"] == "user:dashboard"
    item = d.kernel.board.save("Bird box", "Cut list", "4 panels", by="jarvis")
    assert call(d, f"/api/board/projects/{p['id']}/state", {"state": "nope"})[0] == 400
    assert call(d, "/api/board/projects/proj_missing/state", {"state": "done"})[0] == 404
    assert call(d, f"/api/board/items/{item['item_id']}/delete", {})[0] == 200
    assert call(d, f"/api/board/items/{item['item_id']}")[0] == 404
    assert call(d, f"/api/board/projects/{p['id']}/state", {"state": "archived"})[0] == 200
    assert json.loads(call(d, "/api/board")[2])["projects"] == []
    assert len(json.loads(call(d, "/api/board?archived=1")[2])["projects"]) == 1
    assert call(d, "/api/board", cookie=False)[0] == 401


def test_starting_an_idea_opens_it_on_the_board_with_its_plan(dash):
    d, *_ = dash
    from jarvis.core.util import new_id, now_iso
    iid, now = new_id("idea"), now_iso()
    mid = d.kernel.memory.remember("I love watching the birds in the garden", origin="explicit", by="user:dashboard")
    body = json.dumps({"why": "You keep mentioning birds.", "evidence": [{"type": "memory", "id": mid}], "time": "a weekend",
                       "steps": [{"text": "Buy wood", "done": False}, {"text": "Cut panels", "done": False}]})
    with d.kernel.db.tx() as c:
        c.execute("INSERT INTO project_ideas (id, kind, title, body, state, created_at, updated_at)"
                  " VALUES (?, 'growth', 'Build a bird box', ?, 'open', ?, ?)", (iid, body, now, now))
    assert any(x["id"] == iid for x in d.projects.list())
    assert call(d, f"/api/projects/{iid}/accept", {})[0] == 200
    [p] = json.loads(call(d, "/api/board")[2])["projects"]
    assert p["title"] == "Build a bird box" and p["items"][0]["title"] == "Plan"
    assert d.kernel.board.item(p["items"][0]["id"])["content"] == "1. Buy wood\n2. Cut panels"


def test_animations_play_only_when_turned_on_and_only_sealed_off(dash):
    d, *_ = dash
    page = d.kernel.board.save("Toys", "Bouncing ball", ANIMATION, by="jarvis")
    note = d.kernel.board.save("Toys", "Ideas", "a ball that bounces", by="jarvis")
    b = json.loads(call(d, "/api/board")[2])
    assert b["play"] is False and b["can_set_play"] is True
    assert call(d, f"/play/{page['item_id']}")[0] == 403                  # off by default
    assert call(d, "/api/settings/play", {"on": "yes"})[0] == 400
    assert call(d, "/api/settings/play", {"on": True})[0] == 200
    assert call(d, f"/play/{page['item_id']}", cookie=False)[0] == 401     # still needs your sign-in
    assert call(d, f"/play/{note['item_id']}")[0] == 404                  # only pages play
    status, headers, body = call(d, f"/play/{page['item_id']}")
    assert status == 200 and body.decode() == ANIMATION
    csp = headers["Content-Security-Policy"]
    assert csp.startswith("sandbox allow-scripts;") and "allow-same-origin" not in csp   # an empty origin of its own
    assert "connect-src 'none'" in csp and "default-src 'none'" in csp and "form-action 'none'" in csp
    assert "frame-ancestors 'self'" in csp and headers["X-Frame-Options"] == "SAMEORIGIN"
    assert "microphone=()" in headers["Permissions-Policy"] and headers == {**headers, **PLAY_HEADERS}
    # the dashboard itself still can't be framed by anyone
    assert "frame-ancestors 'none'" in call(d, "/api/board")[1]["Content-Security-Policy"]
    assert call(d, "/api/settings/play", {"on": False})[0] == 200
    assert call(d, f"/play/{page['item_id']}")[0] == 403                  # off stops every page at once
    events = [e for e in d.kernel.audit.entries() if e["event"] == "board.play"]
    assert len(events) == 2 and all(e["actor"] == "user:dashboard" for e in events)


def test_the_switch_is_mac_only_with_touch_id(dash):
    from jarvis.board import set_play
    from jarvis.remote import LOCAL_ONLY
    from jarvis.remote.mac import MAC_STEP_UP
    assert any(re.fullmatch(p, "/api/settings/play") for p in LOCAL_ONLY)
    assert any(re.fullmatch(p, "/api/settings/play") for p in MAC_STEP_UP)
    d, *_ = dash
    with pytest.raises(PermissionError):
        set_play(d.kernel, True, by="jarvis")                              # JARVIS can never turn it on itself


def test_the_page_plays_in_a_sandboxed_frame_without_same_origin(dash):
    d, *_ = dash
    js = call(d, "/static/app.js")[2].decode()
    frame = js.split('h("iframe"')[1].split(")")[0]
    assert 'sandbox: "allow-scripts"' in frame and "allow-same-origin" not in frame
    html = call(d, "/")[2].decode()
    assert 'id="board"' in html and ">Projects</span>" in html
