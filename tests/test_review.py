"""A second opinion: a different local model checks Deep answers and plans that change something. It is never the
same model, never the cloud, can't approve or edit a plan, and "not reviewed" is said plainly when no other model."""

import json
import time
from types import SimpleNamespace

import pytest
from test_dashboard import call

from jarvis.models import ChatRequest, Message, Need, NoModelAvailable
from jarvis.models.types import Category
from jarvis.orchestrator import review


class FakeModels:
    def __init__(self, text):
        self.text, self.needs = text, []

    def complete(self, need, request, *, purpose, **kw):
        self.needs.append(need)
        return SimpleNamespace(text=self.text, provider="ollama", model="checker:14b")


def test_reviewer_is_local_and_never_the_author():
    m = FakeModels('{"verdict": "disagree", "problems": ["168 km at 72 km/h is 2 h 20 min, not 2.33 h"]}')
    op = review.answer_opinion(m, "When does it arrive?", "13:40", author="ollama/writer:7b")
    assert m.needs[0].local_only is True and m.needs[0].avoid == "ollama/writer:7b"
    assert op.verdict == "disagree" and op.problems and op.model == "ollama/checker:14b"
    assert "disagrees" in review.note_for(op) and "revised once" in review.note_for(op, fixed=True)


def test_a_disagreement_must_say_why_and_junk_is_unsure():
    assert review.answer_opinion(FakeModels('{"verdict": "disagree", "problems": []}'), "q", "a", author=None).verdict == "unsure"
    assert review.answer_opinion(FakeModels("I think it's fine"), "q", "a", author=None).verdict == "unsure"


def test_no_other_model_means_not_reviewed():
    class NoModel:
        def complete(self, *a, **k):
            raise NoModelAvailable("none", {})
    op = review.plan_opinion(NoModel(), "Tidy notes", [{"description": "Write", "call": "fs.write", "args": {}}], author="x")
    assert op.verdict == "unavailable" and "not reviewed" in review.note_for(op)


def test_router_leaves_out_the_model_being_checked(dash):
    d, *_ = dash
    req = ChatRequest((Message("user", "hi", Category.CONVERSATION),), max_tokens=10)
    route = d.kernel.models.router.route(Need("chat", local_only=True), req)
    only = f"{route.candidates[0].provider}/{route.candidates[0].model}"
    with pytest.raises(NoModelAvailable) as exc:
        d.kernel.models.router.route(Need("chat", local_only=True, avoid=only), req)
    assert exc.value.reasons[only] == "the model whose work is being checked"


def test_deep_chat_says_when_it_wasnt_reviewed(dash):
    d, *_ = dash   # the test Ollama has one model only, so there is nobody to give a second opinion
    status, _, body = call(d, "/api/chat", {"message": "What is the capital of France?", "mode": "deep"})
    data = json.loads(body)
    assert status == 200 and data["second_opinion"]["verdict"] == "unavailable"
    assert "not reviewed" in (data["note"] or "")
    assert any(e["event"] == "chat.second_opinion" for e in d.kernel.audit.entries(limit=30))
    status, _, body = call(d, "/api/chat", {"message": "What is the capital of France?", "mode": "balanced"})
    assert json.loads(body)["second_opinion"] is None                         # only Deep asks for one


def test_a_plan_that_changes_something_gets_a_second_opinion_read_only_doesnt(dash):
    d, script, root = dash
    for steps, expect in (([{"description": "Write the note", "tool": "fs", "action": "write",
                             "args": {"path": str(root / "n.md"), "content": "x"}}], True),
                          ([{"description": "List the folder", "tool": "fs", "action": "list",
                             "args": {"path": str(root)}}], False)):
        script["plan"] = {"goal": "g", "steps": steps}
        job = d.start_plan("Do the thing")
        for _ in range(100):
            if d.jobs[job]["state"] != "planning":
                break
            time.sleep(0.05)
        assert ("review" in d.jobs[job]) is expect, steps
        if expect:
            assert d.jobs[job]["review"]["verdict"] == "unavailable" and d.jobs[job]["kind"] == "plan"   # informs only
