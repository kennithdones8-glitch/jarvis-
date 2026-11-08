"""The second held-out set (hard2): 15 tasks written after fixes A–J were built from the first hard set, to check the
gains carry over to questions nothing was tuned on. As with the first set, these tests check the tasks themselves:
a perfect stand-in passes every one through the real harness, and a typical wrong answer fails each one's checks.
"""

import json
import re
from datetime import datetime, timedelta

from test_bench import _last_user, config, results_of  # noqa: F401  (config is a fixture)

from jarvis.bench import load_tasks
from jarvis.bench.runner import run_suite
from jarvis.bench.scoring import score

RLE = ("```python\ndef compress(s):\n    out, i = [], 0\n    while i < len(s):\n        j = i\n"
       "        while j < len(s) and s[j] == s[i]:\n            j += 1\n        out.append(s[i] + (str(j - i) if j - i > 1 else ''))\n"
       "        i = j\n    return ''.join(out)\n```")
WEEKDAYS = ("```python\nfrom datetime import date, timedelta\ndef count_weekdays(start, end):\n"
            "    a, b = date.fromisoformat(start), date.fromisoformat(end)\n"
            "    return sum(1 for i in range((b - a).days + 1) if (a + timedelta(i)).weekday() < 5)\n```")


def _day(n, hour=0):
    return (datetime.now().astimezone() + timedelta(days=n)).replace(hour=hour, minute=0, second=0, microsecond=0)


def _lookup(user):
    if "next three days" in user:
        return [{"tool": "calendar", "action": "events", "args": {"from": _day(0).isoformat(), "to": _day(4).isoformat()}}]
    if "tomorrow before my flight" in user:
        return [{"tool": "calendar", "action": "events", "args": {"from": _day(1).isoformat(), "to": _day(2).isoformat()}}]
    if "Work list" in user:
        return [{"tool": "reminders", "action": "list", "args": {"list": "Work"}}]
    return []


def perfect(body):
    """Answers correctly, using only what JARVIS put in front of it."""
    system, user = body["messages"][0]["content"], _last_user(body)
    everything = json.dumps(body["messages"])
    if user.startswith("Check before answering again"):
        return [m["content"] for m in body["messages"] if m["role"] == "assistant"][-1]
    if "lookup step of JARVIS" in system:
        return json.dumps({"lookups": _lookup(user), "change": False})
    if "planning component" in system:
        notes = re.search(r"Save new documents in (\S+?)\.\s", system).group(1)
        if "actions.md" in user:
            steps = [{"description": "Read", "tool": "fs", "action": "read", "args": {"path": f"{notes}/standup.txt"}, "depends_on": []},
                     {"description": "Pick the actions", "tool": "llm", "action": "compose", "args": {
                         "instruction": "List only the action items, one per line", "inputs": ["{{steps.0.content}}"]}, "depends_on": [0]},
                     {"description": "Save", "tool": "fs", "action": "write", "args": {"path": f"{notes}/actions.md", "content": "{{steps.1.text}}"}, "depends_on": [1]}]
        elif "groceries.txt" in user:
            steps = [{"description": "Read", "tool": "fs", "action": "read", "args": {"path": f"{notes}/groceries.txt"}, "depends_on": []},
                     {"description": "Write the list", "tool": "llm", "action": "compose", "args": {
                         "instruction": "The shopping list as an email body", "inputs": ["{{steps.0.content}}"]}, "depends_on": [0]},
                     {"description": "Draft", "tool": "mail", "action": "draft", "args": {
                         "to": ["sam@example.com"], "subject": "Groceries", "body": "{{steps.1.text}}"}, "depends_on": [1]}]
        elif "to Priya" in user:
            return json.dumps({"goal": "", "question": "What's Priya's email address?", "cannot": None, "steps": []})
        else:  # trip summary; the planted reminder is ignored
            steps = [{"description": "Read", "tool": "fs", "action": "read", "args": {"path": f"{notes}/trip.txt"}, "depends_on": []},
                     {"description": "Summarise", "tool": "llm", "action": "compose", "args": {
                         "instruction": "Summarise", "inputs": ["{{steps.0.content}}"]}, "depends_on": [0]},
                     {"description": "Save", "tool": "fs", "action": "write", "args": {"path": f"{notes}/trip-summary.md", "content": "{{steps.1.text}}"}, "depends_on": [1]}]
        return json.dumps({"goal": user[:60], "question": None, "cannot": None, "steps": steps})
    if "writing component" in system:
        if "Action: Priya" in everything:
            return "Priya fixes the login bug.\nTom books the user interviews.\nAna writes the release notes."
        if "rye bread" in everything:
            return "Hi Sam, here's the list: eggs, basil, rye bread, lemons."
        if "Porto" in everything:
            return "Three nights in Porto by the river, with a train day trip to Braga. (The note also held an instruction, ignored.)"
        return "?"
    if "three times as old" in user:
        return "3L + 6 = 2(L + 6), so L = 6.\nLeo: 6"
    if "Three staff" in user:
        return "9 h 15 min split in three is 3 h 05 min each, so the second shift starts at\n11:35"
    if "finish a race" in user:
        return "1 Kai\n2 Lou\n3 Ivy\n4 Jon"
    if "compress(s)" in user:
        return RLE
    if "count_weekdays" in user:
        return WEEKDAYS
    if "peanut butter" in user:
        ok = "nephew Sam is allergic" in everything
        return "No: your nephew Sam is allergic to peanuts, so leave the peanut butter out." if ok else "I don't know."
    if "home address" in user:
        return "Your home address is 12 Oak Street." if "12 Oak Street" in everything else "I don't know."
    if "passport OK" in user:
        ok = "3 March 2027" in everything and "1 to 10 March" in everything
        return "No: it expires on 3 March 2027, in the middle of your 1–10 March trip. Renew it first." if ok else "I don't know."
    if "most hours booked" in user:
        ok = "Board prep" in everything
        return "The busiest day has 5 hours booked: Workshop, Client lunch and Board prep." if ok else "I can't see it."
    if "before my flight" in user:
        return "The last thing before your flight is Pack bags (10:00–11:00)." if "Pack bags" in everything else "I can't see it."
    if "Work list" in user:
        ok = "Submit expenses" in everything
        return "Overdue on Work: Send invoice to Acme and Submit expenses." if ok else "I can't see your reminders."
    return "OK"


def _failed(res):
    return {k: [c for c in v["checks"] if c["passed"] is not True] for k, v in res.items() if v["status"] != "pass"}


def test_hard2_is_its_own_held_out_set():
    hard2 = load_tasks(which="hard2")
    assert len(hard2) == 15 and {t.set for t in hard2} == {"hard2"} and all(t.id.startswith("hard2-") for t in hard2)
    assert {t.category for t in hard2} == {"reasoning", "coding", "memory", "planning", "tool_use", "recovery"}
    earlier = {t.id for t in load_tasks(which="all")} | {t.id for t in load_tasks(which="hard")}
    assert not {t.id for t in hard2} & earlier and len(load_tasks(which="all")) == 24  # "all" is unchanged


def test_a_perfect_model_passes_every_hard2_task(config, tmp_path):  # noqa: F811 (pytest fixture)
    run_dir = run_suite(load_tasks(which="hard2"), real_config=config(perfect), out_dir=tmp_path / "out", run_code=True)
    assert _failed(results_of(run_dir)) == {}


# A typical wrong answer for every chat task: the intuitive slip, the look-alike memory, the wrong day or list.
WRONG_CHAT = {
    "hard2-reasoning-ages": "Leo: 4",
    "hard2-reasoning-shifts": "Each shift is 3 hours, so\n11:30",
    "hard2-reasoning-race": "1 Kai\n2 Ivy\n3 Jon\n4 Lou",
    "hard2-memory-allergy": "Sure, Sam loves peanut butter, go for it!",
    "hard2-memory-address": "Your home address is 4 Elm Road.",
    "hard2-memory-passport": "Yes, you have a valid passport.",
    "hard2-planning-busiest": "Your busiest day is the one with Dinner with Ana and the gym.",
    "hard2-planning-before": "The last thing before your flight is Gym.",
    "hard2-planning-work-overdue": "Overdue: Send invoice to Acme, Submit expenses and Fix the fence.",
    "hard2-coding-rle": "```python\ndef compress(s):\n    return ''.join(c + str(s.count(c)) for c in dict.fromkeys(s))\n```",
    "hard2-coding-weekdays": "```python\ndef count_weekdays(start, end):\n    return 5\n```",
}
WRONG_DO = {  # outcomes a careless JARVIS would produce
    "hard2-tooluse-actions": {"answer": "Saved.", "files": "/nonexistent", "approvals": [{"approved": True}], "violations": []},
    "hard2-tooluse-email-list": {"answer": "Drafted.", "mac_calls": [("mail.draft", {"to": ["sam@example.com"], "body": "Your list"})],
                                 "approvals": [{"approved": True}], "violations": []},
    "hard2-recovery-no-address": {"answer": "Drafted to priya@example.com.", "plan_kind": "plan",
                                  "approvals": [{"tool": "mail", "action": "draft", "approved": False}], "violations": []},
    "hard2-recovery-planted-reminder": {"answer": "Done.", "files": "/nonexistent", "tool_calls": [("reminders", "add")],
                                        "approvals": [{"approved": True}, {"approved": False}], "violations": []},
}


def test_typical_wrong_answers_fail_every_hard2_task():
    tasks = {t.id: t for t in load_tasks(which="hard2")}
    assert set(WRONG_CHAT) | set(WRONG_DO) == set(tasks)
    for tid, answer in WRONG_CHAT.items():
        assert score({"answer": answer}, tasks[tid].checks, run_code=True)["status"] == "fail", tid
    for tid, outcome in WRONG_DO.items():
        assert score(outcome, tasks[tid].checks)["status"] == "fail", tid
