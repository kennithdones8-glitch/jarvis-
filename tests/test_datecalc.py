"""Date arithmetic is done by code and handed to the model. Built from two real failures on the owner's Mac (hard set,
20 Nov 2026): "the 10th meeting, every 3rd day from Monday 2 March 2026" (the 7B slipped a day: 2/5) and "the day
before I travel" with the flight date in memory (it used today's date instead: 0/5)."""

from datetime import date

from test_outcome import chat, chat_env  # noqa: F401  (fixture)

from jarvis.orchestrator.datecalc import HEAD, dates_in, facts

TODAY = date(2026, 11, 24)
CLUB = ('A club meets every 3rd day, starting on Monday 2 March 2026 (that is the 1st meeting). On which weekday and '
        'date is the 10th meeting? End with a line like "Tuesday 5 May".')
CAT = "Which date do I need to take the cat to my mum's? End with the date on its own line."
MEMORIES = ["My flight to Lisbon is on 14 August.", "Whenever I travel, the cat goes to my mum's the day before I leave.",
            "My dentist appointment is on 20 August."]


def test_the_nth_of_a_repeat_is_counted_by_code():
    text = facts(CLUB, [], TODAY)
    assert text.startswith(HEAD)
    assert "the 10th is Sunday 29 March 2026 (9 × 3 = 27 days after the 1st)" in text
    assert "9th Thursday 26 March 2026; 10th Sunday 29 March 2026" in text
    assert "5 May" not in text          # the example in quotes is a format, not a date


def test_the_day_before_is_worked_out_for_every_remembered_date_with_its_sentence():
    text = facts(CAT, MEMORIES, TODAY)
    assert "“My flight to Lisbon is on 14 August.” → Saturday 14 August 2027" in text
    assert "the day before: Friday 13 August 2027" in text
    assert "the day before: Thursday 19 August 2027" in text   # the dentist too: the model picks by the sentence


def test_offsets_in_weeks_and_numbers_and_weekdays():
    text = facts("My exam is on 20 December 2026. What day of the week is 2 weeks before it?", [], TODAY)
    assert "2 weeks before: Sunday 6 December 2026" in text and "20 December 2026 is a Sunday" in text
    assert "3 days after: Monday 28 December 2026" in facts("And 3 days after 25 December 2026?", [], TODAY)


def test_a_date_without_a_year_is_the_nearest_sensible_one():
    assert dates_in("from Nov 1st", TODAY)[0].day == date(2026, 11, 1)       # a few weeks ago: this year
    assert dates_in("on 14 August", TODAY)[0].day == date(2027, 8, 14)       # months ago: the next one
    assert dates_in("on 20 December", date(2027, 1, 5))[0].day == date(2026, 12, 20)   # just gone, across new year
    assert dates_in("on 2026-08-14 and Aug 3rd, 2027", TODAY)[1].day == date(2027, 8, 3)


def test_nothing_to_work_out_leaves_the_prompt_alone():
    assert facts("Tell me a joke about Tuesdays", [], TODAY) is None
    assert facts("What should I cook tonight?", MEMORIES, TODAY) is None   # dates in memory, but nothing asked of them
    assert facts("every day I walk the dog", [], TODAY) is None            # a habit with no date to count from


def test_the_chat_hands_the_worked_out_dates_to_the_model(chat_env):  # noqa: F811
    d, state, server = chat_env
    for text in MEMORIES:
        d.kernel.memory.remember(text, origin="explicit", by="user:dashboard")
    state["answers"] = ["You need to take the cat on Friday 13 August.\n13 August"] * 3
    chat(d, CAT)
    sent = next(b["body"]["messages"] for b in reversed(server.received)
                if any(HEAD in m["content"] for m in b["body"]["messages"]))
    facts_msg = next(m["content"] for m in sent if HEAD in m["content"])
    assert "13 August" in facts_msg.split("My flight to Lisbon")[1].split("\n")[0]   # whatever year it is now
    assert "My flight to Lisbon" in facts_msg
