"""Automatic Ask / Research / Do: rules first, a local model only when unsure, never the cloud."""

from pathlib import Path

import pytest

from jarvis import intent

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("text,mode", [
    ("Remind me to call mum at 6", "do"),
    ("Please add a reminder for the dentist on Friday", "do"),
    ("Summarise the PDFs in my Downloads folder into one note", "do"),
    ("Research note-taking apps and save a brief to my notes", "do"),
    ("Jarvis, create a folder called Taxes", "do"),
    ("What's the latest news on the Mars mission?", "research"),
    ("Find me reviews of the Framework laptop with sources", "research"),
    ("Who won the match yesterday? search the web", "research"),
    ("What's the weather in Leeds tomorrow?", "research"),
    ("How do tides work?", "ask"),
    ("Explain recursion simply", "ask"),
    ("Thanks!", "ask"),
])
def test_rules_decide_the_obvious_cases(text, mode):
    assert intent.classify(text)["mode"] == mode


def test_unclear_messages_go_to_the_local_model_and_fall_back_to_ask():
    assert intent.by_rules("Monthly budget for groceries and transport")[0] is None
    seen = []
    def local(prompt):
        seen.append(prompt)
        return "DO."
    r = intent.classify("Monthly budget for groceries and transport", local)
    assert r == {"mode": "do", "by": "local model", "reason": "decided on this Mac"} and len(seen) == 1
    assert intent.classify("Monthly budget for groceries", lambda p: "banana")["mode"] == "ask"   # nonsense: ask
    def broken(prompt):
        raise RuntimeError("no model")
    assert intent.classify("Monthly budget for groceries", broken)["mode"] == "ask"             # no model: ask, nothing sent


def test_the_dashboard_route_is_local_only_and_research_and_tasks_are_confirmed():
    app = (ROOT / "src/jarvis/server/app.py").read_text()
    route = app.split("def route_message(")[1].split("return intent.classify(message, complete)")[0]
    assert 'Need("chat", prefer="speed", local_only=True, keep_speed=True)' in route             # never leaves the Mac, stays fast
    js = (ROOT / "src/jarvis/server/static/app.js").read_text()
    assert 'if (r.mode === "research" || r.mode === "do") { showRouteConfirm(r); return; }' in js   # one tap first
    assert '"Plan it"' in js and '"Research it"' in js and '"Just answer"' in js
    assert 'role="tablist" aria-label="Mode" hidden' in (ROOT / "src/jarvis/server/static/index.html").read_text()   # buttons removed


@pytest.mark.parametrize("text,module", [
    ("JARVIS, show me my software architecture", "architecture"),
    ("Show me what you're doing", "workflow"),
    ("Show me what you've learned", "neural"),
    ("show me the map", "globe"),
    ("Show me the security shield", "security"),
    ("visualize your experiments", "simulation"),
])
def test_show_me_opens_the_matching_projection(text, module):
    assert intent.classify(text) == {"mode": "show", "module": module, "by": "rules", "reason": "asks to see a projection"}


def test_show_requests_never_become_actions():
    assert intent.classify("Show me how to bake bread")["mode"] != "do"
