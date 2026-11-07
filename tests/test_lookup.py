"""Smarter chat: JARVIS looks things up (read-only, chosen by the local model) before answering."""

import json
from datetime import date, datetime, timedelta

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


def test_small_model_spellings_are_accepted_and_skips_are_explained(env):
    d, script, seen, fake, _ = env
    script["raw"] = json.dumps([{"tool": "calendar.events", "args": week()}, {"tool": "weather", "action": "now"},
                                {"tool": "calendar", "action": "events"}])  # a bare list, a joined name, junk
    r = chat(d, "Am I free tomorrow afternoon?")
    assert fake.calls[0][0] == "calendar.events" and r["checked"][0].startswith("Calendar, ")
    assert "ignored unknown lookup weather.now" in r["lookup_notes"]
    assert "ignored calendar.events: missing from, to" in r["lookup_notes"]


def test_when_nothing_is_looked_up_the_reason_is_given(env):
    d, script, seen, fake, _ = env
    script["raw"] = "sorry, I can't do JSON"
    r = chat(d, "What's on my calendar this week?")
    assert fake.calls == [] and any(n.startswith("choosing lookups failed") for n in r["lookup_notes"])
    script.pop("raw")
    script["lookups"] = []
    assert "the model chose no lookups" in chat(d, "What's on my calendar next week?")["lookup_notes"]
    assert chat(d, "Explain how rainbows form")["lookup_notes"] == ["no lookup words in the message"]


def test_router_json_wrapped_in_prose_is_still_used(env):
    d, script, seen, fake, _ = env
    script["raw"] = "Sure! Here is the JSON:\n" + json.dumps({"lookups": [{"tool": "reminders", "action": "list", "args": {}}]})
    r = chat(d, "Anything overdue on my reminders?")
    assert fake.calls[0][0] == "reminders.list" and r["checked"] == ["Reminders"]


def test_calendar_lookups_cover_whole_days(env):
    from jarvis.orchestrator.lookup import whole_days
    d, script, seen, fake, _ = env
    tomorrow = (datetime.now().astimezone() + timedelta(days=1)).replace(second=0, microsecond=0)
    narrow = {"from": tomorrow.replace(hour=14, minute=0).isoformat(), "to": tomorrow.replace(hour=15, minute=30).isoformat()}
    script["lookups"] = [{"tool": "calendar", "action": "events", "args": narrow}]
    chat(d, "Am I free tomorrow between 2pm and 3:30pm, and what's my first commitment?")
    sent = fake.calls[0][1]
    at = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))  # noqa: E731  (the script gets UTC times)
    local_midnight = lambda d: datetime(d.year, d.month, d.day).astimezone()  # noqa: E731
    assert at(sent["from"]) == local_midnight(tomorrow)  # the same moment, whatever the Mac's time zone
    assert at(sent["to"]) == local_midnight(tomorrow + timedelta(days=1))
    week_ = whole_days({"from": "2026-11-02T00:00", "to": "2026-11-09T00:00"})  # already whole days: unchanged span
    assert week_["from"][:16] == "2026-11-02T00:00" and week_["to"][:16] == "2026-11-09T00:00"
    assert whole_days({"from": "nonsense", "to": 3}) == {"from": "nonsense", "to": 3}


def test_an_invented_reminders_list_falls_back_to_every_list(env):
    d, script, seen, fake, _ = env
    due = (datetime.now().astimezone() - timedelta(days=2)).isoformat()  # overdue, so it is listed (0.19.1 filters)
    fake.reminders.append({"title": "Pay rent", "due": due, "completed": False, "notes": "", "list": "Reminders"})
    script["lookups"] = [{"tool": "reminders", "action": "list", "args": {"list": "overdue"}}]
    r = chat(d, "What's overdue?")
    assert [c[1].get("list") for c in fake.calls] == ["overdue", None]
    assert r["checked"] == ["Reminders (all lists; nothing open in “overdue”)"]
    assert "Pay rent" in seen["answer_prompts"][-1]


@pytest.fixture
def new_york(monkeypatch):
    import time as _time
    monkeypatch.setenv("TZ", "America/New_York")
    _time.tzset()
    yield
    monkeypatch.undo()
    _time.tzset()


def test_whole_days_and_the_fixture_survive_the_clocks_going_back(new_york):
    """US clocks went back on 1 Nov 2026, the day of the first real benchmark run: "tomorrow 9:00" came out as 8:00."""
    from jarvis.bench.runner import FixtureMac
    from jarvis.orchestrator.lookup import whole_days
    w = whole_days({"from": "2026-11-02T14:00", "to": "2026-11-02T15:30"})
    assert w["from"] == "2026-11-02T00:00:00-05:00" and w["to"] == "2026-11-03T00:00:00-05:00"
    w = whole_days({"from": "2026-10-31T10:00:00-04:00", "to": "2026-11-01T10:00:00-05:00"})
    assert w["from"] == "2026-10-31T00:00:00-04:00" and w["to"] == "2026-11-02T00:00:00-05:00"
    before = datetime.fromisoformat("2026-11-01T01:12:00-04:00")
    fx = FixtureMac({"events": [{"title": "Standup", "day": 1, "start": "09:00", "end": "09:30"}]}, now=before)
    assert fx.events[0]["start"] == "2026-11-02T09:00:00-05:00"


def test_reminders_say_how_far_off_they_are():
    from jarvis.orchestrator.lookup import _when, render
    now = datetime.now().astimezone()
    assert _when((now - timedelta(days=2)).isoformat()) == "OVERDUE by 2 days"
    assert _when((now + timedelta(days=5)).isoformat()) == "in 5 days"
    text = render(("reminders", "list"), {"reminders": [{"title": "Pay rent", "due": (now - timedelta(days=1)).isoformat(),
                                                          "list": "Home"}, {"title": "Milk", "due": None, "list": "Home"}]})
    assert "Pay rent (due " in text and "OVERDUE by 1 day)" in text and "- Milk [Home]" in text


# ---- "tomorrow" is worked out by JARVIS, not the small model (owner's Mac, 0.18.3 benchmark) ----------------------
def test_named_days_come_from_the_clock():
    from datetime import date
    from jarvis.orchestrator.lookup import named_days
    fri = date(2026, 11, 6)  # a Friday
    assert named_days("Am I free tomorrow between 2pm and 3:30pm?", fri) == [date(2026, 11, 7)]
    assert named_days("what's on today and tonight", fri) == [fri]
    assert named_days("the day after tomorrow", fri) == [date(2026, 11, 8)]
    assert named_days("Am I free on Monday?", fri) == [date(2026, 11, 9)]
    assert named_days("Anything on Friday?", fri) == [fri] and named_days("next Friday", fri) == [date(2026, 11, 13)]
    assert named_days("Explain how rainbows form", fri) == []


def test_a_lookup_of_the_wrong_day_is_corrected_to_the_day_asked_about(env):
    """Real failure: asked late on Fri 6 Nov about tomorrow, the small model looked up Friday, found nothing, and
    made up a "Meeting with John". Now JARVIS widens the lookup to tomorrow itself, and says so."""
    d, script, seen, fake, _ = env
    now = datetime.now().astimezone()
    today = {"from": now.replace(hour=20, minute=0).isoformat(), "to": now.replace(hour=23, minute=0).isoformat()}
    script["lookups"] = [{"tool": "calendar", "action": "events", "args": today}]
    r = chat(d, "Am I free tomorrow between 2pm and 3:30pm? And what's my first commitment tomorrow?")
    asked = fake.calls[0][1]
    tomorrow = (now + timedelta(days=1)).date()
    assert datetime.fromisoformat(asked["from"]).date() <= tomorrow < datetime.fromisoformat(asked["to"]).date()
    assert "Dentist" in seen["answer_prompts"][-1]  # tomorrow's event reaches the answering model
    assert any("corrected to cover" in n for n in r["lookup_notes"])  # and the correction is shown, not hidden
    assert r["checked"][0].endswith(f"{(now + timedelta(days=1)):%a %d %b}")


def test_a_right_lookup_is_left_alone(env):
    d, script, seen, fake, _ = env
    script["lookups"] = [{"tool": "calendar", "action": "events", "args": week()}]
    r = chat(d, "Am I free tomorrow afternoon?")
    assert not any("corrected" in n for n in r["lookup_notes"])


# ---- exact facts worked out by JARVIS, not the small model (owner's Mac, 0.19.0 benchmark) -------------------------
def _ev(day, start, end, title, base):
    d = base + timedelta(days=day)
    at = lambda hm: datetime(d.year, d.month, d.day, *map(int, hm.split(":"))).astimezone().isoformat()  # noqa: E731
    return {"title": title, "start": at(start), "end": at(end), "all_day": False, "location": "", "calendar": "Work"}


def _days(base, n):
    lo = datetime(base.year, base.month, base.day).astimezone()
    return {"from": lo.isoformat(), "to": (lo + timedelta(days=n)).isoformat()}


def test_first_event_and_free_time_are_stated_exactly():
    """Real failure: with a 09:00 Standup in the list, the 7B said the first commitment was the 13:00 lunch."""
    from datetime import date
    from jarvis.orchestrator.lookup import FACTS_HEAD, calendar_facts, worked_out
    fri, sat = date(2026, 11, 6), date(2026, 11, 7)
    events = [_ev(1, "09:00", "09:30", "Standup", fri), _ev(1, "13:00", "14:00", "Lunch with Sam", fri),
              _ev(1, "15:30", "16:30", "Dentist", fri), _ev(2, "07:00", "08:00", "Gym", fri)]
    msg = "Am I free tomorrow between 2pm and 3:30pm? And what's my first commitment tomorrow, and when is it?"
    lines = calendar_facts(events, _days(sat, 1), msg, today=fri)
    assert lines[0] == "- First event on Sat 07 Nov: 09:00–09:30 Standup"
    assert "- Sat 07 Nov 14:00–15:30: FREE: yes, you're free then (nothing scheduled)" in lines  # lunch ends at 14:00, dentist at 15:30
    busy = calendar_facts(events, _days(sat, 1), "Am I free tomorrow between 1pm and 2pm?", today=fri)
    assert "- Sat 07 Nov 13:00–14:00: BUSY: no, you're not free then: Lunch with Sam 13:00–14:00" in busy
    text = worked_out(("calendar", "events"), {"events": events}, _days(sat, 1), msg)
    assert text.startswith(FACTS_HEAD) and "yes or no first" in FACTS_HEAD and text.endswith("The full list:")


def test_clashes_are_found_by_jarvis():
    """Real failure: the model listed both meetings but never said they clash."""
    from datetime import date
    from jarvis.orchestrator.lookup import calendar_facts
    base = date(2026, 11, 6)
    events = [_ev(1, "14:00", "15:00", "Client call", base), _ev(1, "14:30", "15:30", "Team review", base),
              _ev(2, "07:00", "08:00", "Gym", base), _ev(2, "12:30", "13:30", "Lunch with Alex", base)]
    lines = calendar_facts(events, _days(base, 3), "Do I have any clashing appointments in the next three days?")
    assert "- CLASH on Sat 07 Nov: Client call 14:00–15:00 overlaps Team review 14:30–15:30" in lines
    back_to_back = [_ev(1, "13:00", "14:00", "A", base), _ev(1, "14:00", "15:00", "B", base)]
    assert "- No clashes: none of these events overlap" in calendar_facts(back_to_back, _days(base, 3), "clashes?")


def test_reminders_outside_the_asked_window_are_counted_not_listed():
    """Real failure: asked for the next 7 days, the model also listed "Book dentist", due in 9 days."""
    from jarvis.orchestrator.lookup import render, reminder_facts
    now = datetime(2026, 11, 6, 21, 0).astimezone()
    at = lambda days, hm="09:00": (datetime(2026, 11, 6, *map(int, hm.split(":"))).astimezone()  # noqa: E731
                                   + timedelta(days=days)).isoformat()
    rem = [{"title": "Renew car insurance", "due": at(3, "10:00"), "list": "Admin"},
           {"title": "Call the plumber", "due": at(5), "list": "Home"},
           {"title": "Book dentist", "due": at(9), "list": "Home"},
           {"title": "Tax return", "due": at(20, "17:00"), "list": "Admin"},
           {"title": "Learn Spanish", "due": None, "list": "Someday"},
           {"title": "Pay rent", "due": at(-2), "list": "Home"}]
    lines, keep = reminder_facts(rem, "Which of my reminders are due in the next 7 days?", now)
    assert lines[0] == "- Overdue (1): Pay rent"
    assert lines[1].endswith("(2): Renew car insurance, Call the plumber")
    assert lines[2].startswith("- Not in that: 3 other open reminder(s)")
    assert [r["title"] for r in keep] == ["Pay rent", "Renew car insurance", "Call the plumber"]
    lines, keep = reminder_facts(rem, "Which of my reminders are overdue?", now)
    assert lines[0] == "- Overdue (1): Pay rent" and [r["title"] for r in keep] == ["Pay rent"]
    assert reminder_facts(rem, "Show me all my reminders", now) == ([], rem)  # no window asked: everything, as before
    shown = render(("reminders", "list"), {"reminders": rem}, "Which of my reminders are due in the next 7 days?")
    assert "Book dentist" not in shown and "Call the plumber" in shown


def test_overdue_and_a_window_together_list_both():
    """Real gap (hard set): "overdue or due today" listed only the overdue ones, so the reminder due today was lost."""
    from jarvis.orchestrator.lookup import reminder_facts, reminder_window
    now = datetime(2026, 11, 6, 12, 0).astimezone()
    at = lambda days, hm="09:00": (datetime(2026, 11, 6, *map(int, hm.split(":"))).astimezone()  # noqa: E731
                                   + timedelta(days=days)).isoformat()
    rem = [{"title": "Pay council tax", "due": at(-2), "list": "Home"},
           {"title": "Call plumber", "due": at(0, "18:00"), "list": "Home"},
           {"title": "Water plants", "due": at(1, "08:00"), "list": "Home"},
           {"title": "Renew passport", "due": at(20), "list": "Admin"}]
    for q, want in (("What's overdue or due today?", ["Pay council tax", "Call plumber"]),
                    ("Anything late or due tomorrow?", ["Pay council tax", "Call plumber", "Water plants"]),
                    ("Which reminders are overdue or due in the next 3 days?", ["Pay council tax", "Call plumber", "Water plants"])):
        assert reminder_window(q)[0] == "within", q
        assert [r["title"] for r in reminder_facts(rem, q, now)[1]] == want, q
    assert reminder_window("Which of my reminders are overdue?") == ("overdue", None)  # overdue alone: unchanged


def test_facts_reach_the_answering_model(env):
    d, script, seen, fake, _ = env
    script["lookups"] = [{"tool": "calendar", "action": "events", "args": week()}]
    chat(d, "Am I free tomorrow between 2pm and 3:30pm? What's my first commitment tomorrow?")
    prompt = seen["answer_prompts"][-1]
    assert "Worked out by JARVIS" in prompt and "not free then: Dentist 14:00" in prompt  # the fixture's 14:00 dentist


def test_parsing_times_and_windows():
    from jarvis.orchestrator.lookup import asked_window, reminder_window
    assert asked_window("Am I free tomorrow between 2pm and 3:30pm?") == ((14, 0), (15, 30))
    assert asked_window("between 2 and 3:30") == ((14, 0), (15, 30))
    assert asked_window("from 11 to 1pm") == ((11, 0), (13, 0))
    assert asked_window("from noon to 2pm") == ((12, 0), (14, 0))
    assert asked_window("14:00-15:30") == ((14, 0), (15, 30))
    for nothing in ("the score was 3-4", "Am I free tomorrow afternoon?", "2026-11-07"):
        assert asked_window(nothing) is None, nothing
    assert reminder_window("Which of my reminders are due in the next 7 days?") == ("within", 7)
    assert reminder_window("Which of my reminders are overdue?") == ("overdue", None)
    assert reminder_window("What's due tomorrow?") == ("within", 1)
    assert reminder_window("Remind me to call Sam") is None


def test_reminders_are_always_looked_up_when_the_message_asks_whats_due():
    """Real failure (hard set): "what do I need to deal with today? only overdue or due today" looked at the
    calendar only. Read-only, and only added when missing."""
    from jarvis.orchestrator.lookup import LOOKUPS, with_required_lookups
    cal = {"tool": "calendar", "action": "events", "args": {"from": "a", "to": "b"}}
    for q in ("Anything I'm late on? What's overdue?", "What's due this week?", "Show my to-dos for today"):
        why = []
        plan = with_required_lookups({"lookups": [cal]}, q, list(LOOKUPS), why)
        assert plan["lookups"][0] == {"tool": "reminders", "action": "list", "args": {}} and cal in plan["lookups"], q
        assert why == ["added a reminders lookup: the message asks what's due"]
    same = {"lookups": [{"tool": "reminders", "action": "list", "args": {}}]}
    assert with_required_lookups(same, "What's overdue?", list(LOOKUPS), []) == same  # never twice
    assert with_required_lookups({"lookups": []}, "The match was cancelled due to rain", list(LOOKUPS), []) == {"lookups": []}
    no_reminders = [a for a in LOOKUPS if a != ("reminders", "list")]
    assert with_required_lookups({}, "What's overdue?", no_reminders, []) == {}  # not available: nothing added


def test_a_free_slot_of_a_given_length_is_worked_out_exactly():
    """Real failure (hard set): asked for a free 90 minutes, the model called 11:00–13:15 free."""
    from jarvis.orchestrator.lookup import asked_minutes, calendar_facts
    day = date(2026, 11, 9)
    at = lambda hm: datetime(2026, 11, 9, *map(int, hm.split(":"))).astimezone().isoformat()  # noqa: E731
    ev = lambda t, a, b: {"title": t, "start": at(a), "end": at(b)}  # noqa: E731
    events = [ev("Gym", "08:00", "09:30"), ev("Call", "10:00", "11:00"), ev("Lunch", "12:00", "13:00"),
              ev("Review", "13:00", "15:30"), ev("School run", "15:45", "16:30")]
    args = {"from": datetime(2026, 11, 9).astimezone().isoformat(), "to": datetime(2026, 11, 10).astimezone().isoformat()}
    lines = calendar_facts(events, args, "Can I fit in two hours on Monday between 9am and 6pm?", today=date(2026, 11, 7))
    [slot] = [x for x in lines if x.startswith("- FREE SLOTS")]
    assert slot == "- FREE SLOTS of at least 120 min, Mon 09 Nov 09:00–18:00: none: no gap that long (longest free: 16:30–18:00, 90 min)"
    lines = calendar_facts(events, args, "Is there a free hour on Monday?", today=date(2026, 11, 7))
    [slot] = [x for x in lines if x.startswith("- FREE SLOTS")]
    assert slot == "- FREE SLOTS of at least 60 min, Mon 09 Nov 08:00–20:00: yes: 11:00–12:00 (60 min free); 16:30–20:00 (210 min free)"
    assert not any("FREE: yes" in x or "BUSY" in x for x in lines)  # the slot answer replaces whole-window free/busy
    assert day.weekday() == 0
    for q, want in (("a 45 min gap", 45), ("half an hour free?", 30), ("1.5 hours available", 90),
                    ("my 30 minute run", None), ("Am I free between 2pm and 3pm?", None)):
        assert asked_minutes(q) == want, q
