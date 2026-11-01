"""Project ideas: found locally from your own words, grounded in evidence, polished by Claude only with consent."""

import json

import pytest
from test_claude_code import brain, fake_claude  # noqa: F401  (fixtures)
from test_dashboard import call

from jarvis.core.tools import ApprovalRequired
from jarvis.projects import ProjectIdeas

IDEAS = {"ideas": [
    {"kind": "growth", "title": "Build a sourdough log app", "why": "You mentioned baking a lot.", "evidence": ["<sourdough>", "M1"],
     "time": "2 hours a week", "steps": ["Sketch the screens", "Log three bakes", "Pick a stack"]},
    {"kind": "jarvis", "title": "Morning Garmin summary", "why": "You ask about runs.", "evidence": ["<Garmin>"],
     "time": "a weekend", "steps": ["Export a run", "Write a parser"]},
    {"kind": "growth", "title": "Made-up idea", "why": "x", "evidence": ["R99"], "time": "x", "steps": ["a", "b"]},  # no real evidence
    {"kind": "growth", "title": "No plan", "why": "x", "evidence": ["R1"], "time": "x", "steps": ["only one"]},    # too few steps
    {"kind": "world-domination", "title": "Bad kind", "why": "x", "evidence": ["R1"], "time": "x", "steps": ["a", "b"]},
]}


def _seed(k):
    mem = k.memory
    r1 = mem.add_record("s", "user", "I bake sourdough every weekend and want to track my starter")
    r2 = mem.add_record("s", "user", "How far did I run this week on my Garmin?")
    mem.add_record("s", "assistant", "assistant text is never a source")
    m1 = mem.remember("Wants to learn app development", origin="explicit", by="user:test")
    return r1, r2, m1


def _local(srv, reply):
    """A stand-in local model. "<word>" in evidence becomes the label of the item containing that word."""
    seen = []

    def answer(body):
        seen.append(body)
        if "suggest projects" not in body["messages"][0]["content"]:
            return "Local says hello."
        lines = body["messages"][-1]["content"].splitlines()
        label = lambda w: next((ln[1:ln.index("]")] for ln in lines if w in ln), "R404")  # noqa: E731
        text = json.dumps(reply)
        for w in ("sourdough", "Garmin"):
            text = text.replace(f"<{w}>", label(w))
        return text
    srv.reply = answer
    return seen


def test_ideas_come_from_the_local_model_and_must_cite_real_evidence(brain, fake_claude):  # noqa: F811
    k, srv = brain("best")  # Claude is available and preferred, yet generation stays local
    _seed(k)
    seen = _local(srv, IDEAS)
    p = ProjectIdeas(k)
    assert p.generate() == {"added": 2}
    assert fake_claude() == []
    prompt = seen[-1]["messages"][-1]["content"]
    assert "sourdough" in prompt and "assistant text is never a source" not in prompt  # only your own messages
    ideas = {x["title"]: x for x in p.list()}
    assert set(ideas) == {"Build a sourdough log app", "Morning Garmin summary"}
    sour = ideas["Build a sourdough log app"]
    assert sour["kind_label"] == "Growth & side project" and [s["text"] for s in sour["steps"]][0] == "Sketch the screens"
    assert {q["text"] for q in sour["evidence"]} == {"I bake sourdough every weekend and want to track my starter",
                                                     "Wants to learn app development"}
    audit = [e for e in k.audit.entries(limit=200) if e["event"] == "projects.generated"][-1]["payload"]
    assert audit["added"] == 2 and "sourdough" not in json.dumps(audit)  # counts only
    assert p.status()["due"] is False
    assert p.generate() == {"added": 0}  # the same ideas aren't suggested twice


def test_needs_something_to_go_on_and_survives_a_bad_reply(brain, fake_claude):  # noqa: F811
    k, srv = brain("local_first")
    p = ProjectIdeas(k)
    assert p.generate()["added"] == 0 and "Not enough" in p.status()["error"] and srv.received == []
    _seed(k)
    srv.reply = lambda body: "not json at all"
    assert p.generate()["added"] == 0 and p.list() == [] and p.status()["error"]


def test_forgetting_the_evidence_removes_the_idea(brain, fake_claude):  # noqa: F811
    k, srv = brain("local_first")
    r1, r2, m1 = _seed(k)
    _local(srv, IDEAS)
    p = ProjectIdeas(k)
    p.generate()
    k.memory.delete_record(r2, by="user:test")
    assert "Morning Garmin summary" not in {x["title"] for x in p.list()}
    k.memory.delete_record(r1, by="user:test")
    left = {x["title"]: x for x in p.list()}["Build a sourdough log app"]
    assert [q["text"] for q in left["evidence"]] == ["Wants to learn app development"]  # quotes are read live


def test_states_and_steps(brain, fake_claude):  # noqa: F811
    k, srv = brain("local_first")
    _seed(k)
    _local(srv, IDEAS)
    p = ProjectIdeas(k)
    p.generate()
    by_title = {x["title"]: x for x in p.list()}
    a, b = by_title["Build a sourdough log app"], by_title["Morning Garmin summary"]
    p.decide(a["id"], "active", by="user:test")
    p.tick(a["id"], 1, True, by="user:test")
    p.decide(b["id"], "dismissed", by="user:test")
    [only] = p.list()
    assert only["state"] == "active" and [s["done"] for s in only["steps"]] == [False, True, False]
    with pytest.raises(ValueError):
        p.tick(a["id"], 9, True, by="user:test")
    with pytest.raises(ValueError):
        p.decide(a["id"], "deleted", by="user:test")
    with pytest.raises(KeyError):
        p.decide("idea_nope", "active", by="user:test")


def test_polish_sends_only_the_idea_list_and_only_after_you_approve(brain, fake_claude, monkeypatch):  # noqa: F811
    k, srv = brain("best")
    _seed(k)
    _local(srv, IDEAS)
    p = ProjectIdeas(k)
    p.generate()
    with pytest.raises(ApprovalRequired) as ei:
        p.polish()
    assert fake_claude() == []  # nothing sent before you decide
    k.approvals.decide(ei.value.approval_id, approve=True, by="user:test")
    monkeypatch.setenv("FAKE_REPLY", json.dumps({"ideas": [
        {"title": "Sourdough tracker", "time": "3 weekends", "steps": ["One", "Two", "Three"]},
        {"title": "Run recap", "time": "", "steps": ["only one"]}]}))
    assert p.polish()["polished"] == 2
    [sent] = fake_claude()
    for private in ("bake sourdough every weekend", "Garmin?", "Wants to learn app development", "You mentioned"):
        assert private not in sent["stdin"]  # never your quotes, memories or the "why"
    assert "Build a sourdough log app" in sent["stdin"]
    ideas = {x["title"]: x for x in p.list()}
    assert set(ideas) == {"Sourdough tracker", "Run recap"} and all(x["source"] == "polished" for x in ideas.values())
    assert ideas["Sourdough tracker"]["time"] == "3 weekends"
    assert [s["text"] for s in ideas["Sourdough tracker"]["steps"]] == ["One", "Two", "Three"]
    assert len(ideas["Run recap"]["steps"]) in (2, 3)  # a one-step "plan" doesn't replace the real one


def test_dashboard_endpoints(dash):
    d, _, _ = dash
    status, _, body = call(d, "/api/projects")
    data = json.loads(body)
    assert status == 200 and data["ideas"] == [] and data["enough"] is False
    assert call(d, "/api/projects", cookie=False)[0] in (401, 403)
    assert call(d, "/api/projects/generate", {}, headers={"X-Requested-By": "nope"})[0] == 403  # CSRF check
    assert call(d, "/api/projects/idea_nope/accept", {})[0] == 404
    assert call(d, "/api/projects/idea_nope/steps/0", {"done": "yes"})[0] == 400
    p = d.projects
    _seed(d.kernel)
    with d.kernel.db.tx() as c:
        c.execute("INSERT INTO project_ideas (id, kind, title, body, state, source, created_at, updated_at) VALUES "
                  "('idea_t', 'growth', 'T', ?, 'open', 'local', 'x', 'x')",
                  (json.dumps({"why": "", "time": "", "steps": [{"text": "a", "done": False}, {"text": "b", "done": False}],
                               "evidence": [{"type": "record", "id": p.sources()[0][0]["id"]}]}),))
    status, _, body = call(d, "/api/projects/idea_t/accept", {})
    assert status == 200 and json.loads(body)["state"] == "active"
    assert call(d, "/api/projects/idea_t/steps/0", {"done": True})[0] == 200
    assert call(d, "/api/projects/idea_t/steps/7", {"done": True})[0] == 400
    assert json.loads(call(d, "/api/projects")[2])["ideas"][0]["steps"][0]["done"] is True


def test_page_is_reachable_and_safe():
    from pathlib import Path
    static = Path(__file__).resolve().parents[1] / "src" / "jarvis" / "server" / "static"
    js, html = (static / "app.js").read_text(), (static / "index.html").read_text()
    assert '"projects"' in js.split("const VIEWS = ")[1].split("\n")[0]
    assert 'href="#/projects" data-view="projects"' in html and 'href="#/projects"' in html.split('role="menu"')[1]
    block = js.split("// ---------------------------------------------------------------- projects for you")[1].split("// ------")[0]
    assert "innerHTML" not in block and "/api/projects/polish" in block and "/api/plan" in block
