"""Smarter chat: JARVIS looks things up (read-only, chosen by the local model) before answering."""

import json
from datetime import datetime, timedelta

import pytest

from model_servers import start_ollama
from test_dashboard import CFG, call
from test_mac import FakeMac

from jarvis.models.types import Category
from jarvis.orchestrator.lookup import LookupService, looks_like_change, might_need_lookup
from jarvis.persona import chat_abilities, priming_messages
from jarvis.server import Dashboard
from jarvis.tools import default_registry


@pytest.fixture
def env(make_kernel, tmp_path, root):
    server = start_ollama(installed=["planner:7b"])
    script = {"lookups": [], "change": False}
    seen = {"router": 0, "answer_prompts": []}

    def reply(body):
        system = body["messages"][0]["content"]
        if "lookup step of JARVIS" in system:
            seen["router"] += 1
            return json.dumps(script) if not isinstance(script.get("raw"), str) else script["raw"]
        seen["answer_prompts"].append(json.dumps(body["messages"]))
        return "Here's what I found."
    server.reply = reply
    fake = FakeMac()
    now = datetime.now().astimezone()
    fake.events.append({"title": "Dentist", "start": (now + timedelta(days=1)).replace(hour=14, minute=0).isoformat(),
                        "end": (now + timedelta(days=1)).replace(hour=15, minute=0).isoformat(), "all_day": False,
                        "location": "High St", "calendar": "Home", "recurrence": None})
    (tmp_path / "jarvis.toml").write_text(CFG.format(url=server.url))
    k = make_kernel(registry=default_registry(tmp_path / "home", mac_runner=fake), config_path=tmp_path / "jarvis.toml")
    d = Dashboard(k, port=0, token="test-token", poll_s=0.05)
    d.start()
    yield d, script, seen, fake, root
    d.shutdown()
    server.stop()


def chat(d, message):
    return json.loads(call(d, "/api/chat", {"message": message, "history": []})[2])


def week():
    now = datetime.now().astimezone()
    return {"from": now.replace(hour=0, minute=0).isoformat(), "to": (now + timedelta(days=7)).isoformat()}


def test_cues():
    assert might_need_lookup("Am I free Thursday afternoon?") and might_need_lookup("what's in my notes about Rome")
    assert might_need_lookup("Do I have any clashing appointments in the next three days?")  # plurals count
    assert might_need_lookup("Anything due soon?") and might_need_lookup("Which PDFs are in Downloads?")
    assert not might_need_lookup("Explain how rainbows form")
    assert looks_like_change("Add the dentist on Thursday at 2") and looks_like_change("please remind me to call Sam")
    assert not looks_like_change("When is the dentist?")


def test_calendar_question_is_answered_from_the_calendar(env):
    d, script, seen, fake, _ = env
    script["lookups"] = [{"tool": "calendar", "action": "events", "args": week()}]
    r = chat(d, "Am I free tomorrow afternoon?")
    assert r["text"] == "Here's what I found." and r["checked"][0].startswith("Calendar, ")
    assert fake.calls[0][0] == "calendar.events"
    assert "Dentist" in seen["answer_prompts"][-1] and "<lookup>" in seen["answer_prompts"][-1]
    assert d.kernel.approvals.pending() == []
    assert r["offer_plan"] is False


def test_ordinary_chat_skips_the_lookup_step(env):
    d, script, seen, fake, _ = env
    chat(d, "Explain how rainbows form")
    assert seen["router"] == 0 and fake.calls == []


def test_lookups_can_never_change_anything(env):
    d, script, seen, fake, root = env
    script["lookups"] = [{"tool": "calendar", "action": "add", "args": {"title": "x", "start": "2026-11-05T10:00", "end": "2026-11-05T11:00"}},
                         {"tool": "fs", "action": "write", "args": {"path": f"{root}/notes/x.md", "content": "x"}},
                         {"tool": "fs", "action": "read", "args": {"path": "/etc/hosts"}},
                         {"tool": "mail", "action": "draft", "args": {"to": ["a@b.co"], "subject": "s", "body": "b"}}]
    r = chat(d, "my calendar tomorrow")
    assert fake.calls == [] and not (root / "notes" / "x.md").exists()
    assert d.kernel.approvals.pending() == []  # nothing left waiting either
    assert r["checked"] == []


def test_outside_approved_folders_is_reported_not_read(env):
    d, script, seen, fake, root = env
    (root / "plan.txt").write_text("Trip to Rome in May")
    script["lookups"] = [{"tool": "fs", "action": "read", "args": {"path": "/etc/hosts"}},
                         {"tool": "fs", "action": "read", "args": {"path": f"{root}/plan.txt"}}]
    r = chat(d, "what does my plan file say")
    prompt = seen["answer_prompts"][-1]
    assert "Trip to Rome" in prompt and "not allowed" in prompt and "localhost" not in prompt
    assert len(r["checked"]) == 1


def test_change_requests_offer_a_plan(env):
    d, script, seen, fake, _ = env
    script["change"] = True
    r = chat(d, "Add the dentist on Thursday at 2pm to my calendar")
    assert r["offer_plan"] is True and fake.calls == []


def test_broken_lookup_reply_still_answers(env):
    d, script, seen, fake, _ = env
    script["raw"] = "I think you should check the calendar"
    r = chat(d, "am I free today")
    assert r["text"] == "Here's what I found." and r["checked"] == []


def test_lookup_results_are_private_and_the_question_stays_local(env):
    d, script, seen, fake, _ = env
    script["lookups"] = [{"tool": "reminders", "action": "list", "args": {}}]
    svc = LookupService(d.kernel, [])
    found = svc.run("what reminders do I have")
    assert found.context.category is Category.FILE_CONTENT  # the privacy gate asks before Claude sees it
    assert found.checked == ["Reminders"]


def test_persona_matches_the_new_abilities():
    text = priming_messages(chat_abilities(True, lookups=True))[0].content
    cannot = text.split("can NOT")[1]
    assert "look up the owner's calendar" in text and "Make a plan" in text
    assert "sending email" in cannot and "calendar, reminders, notes or files directly" in cannot
    assert "remembering" not in cannot
    plain = priming_messages(chat_abilities(True))[0].content
    assert "reminders" in plain.split("can NOT")[1]  # without lookups it still says it can't
