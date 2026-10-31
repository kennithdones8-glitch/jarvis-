"""Outcome Engine v1: profile memories, one goal-reader call that also rates difficulty, no downgrades, and the
grounding check on calendar/reminder answers."""

import json
from datetime import datetime, timedelta

import pytest

from model_servers import start_ollama
from test_dashboard import CFG, call
from test_mac import FakeMac

from jarvis.models.router import hard_signals
from jarvis.orchestrator.grounding import times_in, unsupported_times
from jarvis.server import Dashboard
from jarvis.tools import default_registry


# ---- profile memories ---------------------------------------------------------------------------------------
def test_profile_memories_are_recalled_without_matching_words(make_kernel):
    k = make_kernel()
    for text in ("Please call me Ken.", "I'm vegetarian.", "My sister Maya lives in Leeds.", "The wifi password is in the drawer."):
        k.memory.remember(text, origin="explicit", by="user:test")
    k.memory.remember("Seems to like jazz", origin="observed", by="user:test")  # a guess, not a fact you stated
    texts = " | ".join(m["text"] for m in k.memory.recall("suggest a dinner for tonight"))
    assert "Ken" in texts and "vegetarian" in texts and "Maya" in texts
    assert "wifi" not in texts and "jazz" not in texts  # not profile facts; unconfirmed guesses never count


def test_important_memories_join_the_profile_and_it_stays_small(make_kernel):
    k = make_kernel()
    mid = k.memory.remember("The boiler code is 7731.", origin="explicit", by="user:test")
    assert all("boiler" not in m["text"] for m in k.memory.profile())
    k.memory.set_important(mid, True, by="user:test")
    assert any("boiler" in m["text"] for m in k.memory.profile())
    for i in range(20):
        k.memory.remember(f"I like song number {i}.", origin="explicit", by="user:test")
    assert len(k.memory.profile()) == 8


def test_forgotten_profile_facts_stay_forgotten(make_kernel):
    k = make_kernel()
    k.memory.remember("I'm allergic to penicillin.", origin="explicit", by="user:test")
    k.forget("penicillin", by="user:test", dry_run=False)
    assert k.memory.profile() == []


def test_profile_reaches_the_answering_model_as_private_memory(make_kernel):
    from jarvis.models.types import Category
    k = make_kernel()
    k.memory.remember("Call me Ken.", origin="explicit", by="user:test")
    msg = k.memory.context_message(k.memory.recall("hello"))
    assert msg.category is Category.MEMORY  # the privacy gate asks before Claude sees it


# ---- no downgrades ------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text,hard", [
    ("```python\nx = 1\n```\nwhy does this fail?", True), ("Can you debug this for me", True),
    ("Should I pay off my mortgage early or invest?", True), ("What? Why? How?", True), ("x" * 1300, True),
    ("hi there", False), ("What's the capital of France?", False), ("Summarise this note please", False),
])
def test_hard_signals(text, hard):
    assert hard_signals(text) is hard


# ---- grounding ----------------------------------------------------------------------------------------------
def test_times_are_read_in_any_common_format():
    assert times_in("at 3pm, 9:30 a.m. and 14:05, not 25:00 or 13pm") == {"15:00", "09:30", "14:05"}
    assert times_in("Room 101 on floor 3") == set()


def test_unsupported_times_ignore_the_question_and_the_data():
    data = "- Mon 03 Nov 09:00–09:30 Standup [Work]"
    assert unsupported_times("Standup is at 9:00 and you're free 2pm-3:30pm", data, "free between 2pm and 3:30pm?") == []
    assert unsupported_times("Standup is at 10am", data, "first thing?") == ["10:00"]


# ---- in chat, end to end ----------------------------------------------------------------------------------------
@pytest.fixture
def chat_env(make_kernel, tmp_path):
    server = start_ollama(installed=["planner:7b"])
    state = {"answers": [], "router": 0, "triage": 0, "difficulty": "medium", "lookups": []}

    def reply(body):
        system = body["messages"][0]["content"]
        if "lookup step of JARVIS" in system:
            state["router"] += 1
            return json.dumps({"lookups": state["lookups"], "change": False, "difficulty": state["difficulty"]})
        if "Classify how demanding" in system:
            state["triage"] += 1
            return "SIMPLE"
        return state["answers"].pop(0) if state["answers"] else "OK"
    server.reply = reply
    fake = FakeMac()
    now = datetime.now().astimezone()
    start = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    fake.events.append({"title": "Standup", "start": start.isoformat(), "end": (start + timedelta(minutes=30)).isoformat(),
                        "all_day": False, "location": "", "calendar": "Work", "recurrence": None})
    day = start.replace(hour=0)
    state["week"] = {"from": day.isoformat(), "to": (day + timedelta(days=1)).isoformat()}
    (tmp_path / "jarvis.toml").write_text(CFG.format(url=server.url))
    k = make_kernel(registry=default_registry(tmp_path / "home", mac_runner=fake), config_path=tmp_path / "jarvis.toml")
    d = Dashboard(k, port=0, token="test-token", poll_s=0.05)
    d.start()
    yield d, state, server
    d.shutdown()
    server.stop()


def chat(d, message):
    return json.loads(call(d, "/api/chat", {"message": message, "history": []})[2])


def test_a_made_up_time_is_retried_then_flagged(chat_env):
    d, state, _ = chat_env
    state["lookups"] = [{"tool": "calendar", "action": "events", "args": state["week"]}]
    state["answers"] = ["Your first meeting is Standup at 10am.", "Your first meeting is Standup at 10:00."]
    r = chat(d, "What's my first meeting tomorrow?")
    assert r["grounded"] is False and "Unverified" in r["note"] and "10:00" in r["note"]
    ev = [e for e in d.kernel.audit.entries() if e["event"] == "chat.grounding"]
    assert ev[-1]["payload"]["ok"] is False and ev[-1]["payload"]["retried"] is True
    assert "Standup" not in json.dumps(ev[-1]["payload"])  # no content logged


def test_a_retry_that_fixes_it_counts_as_grounded(chat_env):
    d, state, _ = chat_env
    state["lookups"] = [{"tool": "calendar", "action": "events", "args": state["week"]}]
    state["answers"] = ["Standup at 10am.", "Your first meeting is Standup at 9:00."]
    r = chat(d, "What's my first meeting tomorrow?")
    assert r["grounded"] is True and r["text"].endswith("9:00.") and "Unverified" not in (r["note"] or "")


def test_a_cloud_answer_is_flagged_but_never_retried(chat_env, monkeypatch):
    """Retrying a Claude answer would be a new request needing consent again: flag it instead, no stray approval."""
    from dataclasses import replace
    d, state, _ = chat_env
    state["lookups"] = [{"tool": "calendar", "action": "events", "args": state["week"]}]
    state["answers"] = ["Standup at 10am."]
    real = d.kernel.models.complete
    calls = []

    def as_if_claude(*a, **kw):
        calls.append(kw.get("purpose"))
        return replace(real(*a, **kw), provider="claude", model="sonnet")
    monkeypatch.setattr(d.kernel.models, "complete", as_if_claude)
    r = chat(d, "What's my first meeting tomorrow?")
    assert r["grounded"] is False and "Unverified" in r["note"]
    assert calls.count("dashboard chat (grounding retry)") == 0 and d.kernel.approvals.pending() == []


def test_answers_without_calendar_data_are_not_checked(chat_env):
    d, state, _ = chat_env
    state["answers"] = ["Rainbows appear around 4pm in summer."]
    r = chat(d, "Explain how rainbows form")
    assert r["grounded"] is None and r["text"].startswith("Rainbows")


def test_hybrid_rates_difficulty_in_the_same_call_as_lookups(chat_env, tmp_path):
    d, state, _ = chat_env
    d.kernel.models.router.mode = "hybrid"
    state["difficulty"] = "simple"
    chat(d, "hi there")
    assert state["router"] == 1 and state["triage"] == 0  # one local call, not two
    lvl = [e for e in d.kernel.audit.entries() if e["event"] == "model.triage"][-1]["payload"]
    assert lvl["level"] == "simple" and lvl["raw"] == "goal reader"


def test_no_downgrade_even_if_the_goal_reader_says_simple(chat_env):
    d, state, _ = chat_env
    d.kernel.models.router.mode = "hybrid"
    state["difficulty"] = "simple"
    chat(d, "Can you debug this function for me?")
    lvl = [e for e in d.kernel.audit.entries() if e["event"] == "model.triage"][-1]["payload"]
    assert lvl["level"] == "hard"


def test_local_first_mode_keeps_ordinary_chat_free_of_extra_calls(chat_env):
    d, state, _ = chat_env
    chat(d, "Explain how rainbows form")
    assert state["router"] == 0 and state["triage"] == 0
