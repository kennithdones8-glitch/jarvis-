"""The hard set: 17 held-out tasks written after core + extended were all passing on the owner's Mac.

These tests don't measure JARVIS; they check the tasks themselves, through the real harness:
- a "perfect" stand-in model that only uses what JARVIS put in front of it must pass every hard task, so no task
  is impossible or has a broken check;
- a "plausible but wrong" stand-in (the obvious-but-wrong answer, the outdated fact, acting without checking) must
  fail every hard task, so the checks really catch the mistakes they were written for.
"""

import json
import re
from datetime import datetime, timedelta

from test_bench import _last_user, config, results_of  # noqa: F401  (config is a fixture)

from jarvis.bench import load_tasks
from jarvis.bench.runner import run_suite
from jarvis.bench.scoring import score

VERSIONS = ("```python\ndef compare_versions(a, b):\n    x = [int(p) for p in a.split('.')]\n    y = [int(p) for p in b.split('.')]\n"
            "    n = max(len(x), len(y))\n    x += [0] * (n - len(x))\n    y += [0] * (n - len(y))\n"
            "    return (x > y) - (x < y)\n```")
MERGE = ("```python\ndef merge(ranges):\n    out = []\n    for s, e in sorted(ranges):\n        if out and s <= out[-1][1]:\n"
         "            out[-1][1] = max(out[-1][1], e)\n        else:\n            out.append([s, e])\n    return out\n```")
BALANCE = ("```python\ndef running_balance(start, transactions):\n    out = []\n    balance = start\n    for t in transactions:\n"
           "        if balance + t >= 0:\n            balance += t\n        out.append(balance)\n    return out\n```")


def _day(n, hour=0):
    return (datetime.now().astimezone() + timedelta(days=n)).replace(hour=hour, minute=0, second=0, microsecond=0)


def _lookup(user):
    if "clashing" in user:
        return [{"tool": "calendar", "action": "events", "args": {"from": _day(0).isoformat(), "to": _day(6).isoformat()}}]
    if "90-minute" in user:
        return [{"tool": "calendar", "action": "events", "args": {"from": _day(1).isoformat(), "to": _day(2).isoformat()}}]
    if "deal with today" in user:
        return [{"tool": "reminders", "action": "list", "args": {}}]
    return []


def perfect(body):
    """Answers correctly, but only from what JARVIS put in front of it (memories, files, calendar, reminders)."""
    system, user = body["messages"][0]["content"], _last_user(body)
    everything = json.dumps(body["messages"])
    if user.startswith("Check before answering again"):
        return [m["content"] for m in body["messages"] if m["role"] == "assistant"][-1]
    if "lookup step of JARVIS" in system:
        return json.dumps({"lookups": _lookup(user), "change": False})
    if "planning component" in system:
        notes = re.search(r"Save new documents in (\S+?)\.\s", system).group(1)
        if "todo.txt" in user:
            due = _day(1, 9).strftime("%Y-%m-%dT%H:%M")
            steps = [{"description": "Read the list", "tool": "fs", "action": "read", "args": {"path": f"{notes}/todo.txt"}, "depends_on": []},
                     {"description": "Pick the urgent item", "tool": "llm", "action": "compose", "args": {
                         "instruction": "Give only the title of the urgent item", "inputs": ["{{steps.0.content}}"]}, "depends_on": [0]},
                     {"description": "Add the reminder", "tool": "reminders", "action": "add",
                      "args": {"title": "{{steps.1.text}}", "due": due}, "depends_on": [1]}]
        elif "totals.md" in user:
            steps = [{"description": f"Read {m}", "tool": "fs", "action": "read", "args": {"path": f"{notes}/expenses-{m}.txt"}, "depends_on": []}
                     for m in ("jan", "feb", "mar")]
            steps += [{"description": "Add up", "tool": "llm", "action": "compose", "args": {
                          "instruction": "Each month's total and the overall total",
                          "inputs": ["{{steps.0.content}}", "{{steps.1.content}}", "{{steps.2.content}}"]}, "depends_on": [0, 1, 2]},
                      {"description": "Save", "tool": "fs", "action": "write", "args": {"path": f"{notes}/totals.md", "content": "{{steps.3.text}}"}, "depends_on": [3]}]
        elif "don't create any new files" in user:
            return json.dumps({"goal": "", "question": "You asked for summary.md but also no new files: should I create it, "
                               "or just show you the summary here?", "cannot": None, "steps": []})
        else:  # the dentist reminder: when the appointment is isn't known, so ask rather than guess
            return json.dumps({"goal": "", "question": "I can't see a dentist appointment tomorrow. Which day and time is it?",
                               "cannot": None, "steps": []})
        return json.dumps({"goal": user[:60], "question": None, "cannot": None, "steps": steps})
    if "writing component" in system:
        if "URGENT" in everything:
            return "Renew car insurance"
        if "Groceries 210.25" in everything and "Phone 45.50" in everything and "Bus pass" in everything:
            return "# Totals\n- January: 165.50\n- February: 100.00\n- March: 210.25\n- All three months: 475.75"
        return "?"
    if "train leaves" in user:
        return "168/72 = 2 h 20 min, so 12:00; wait until 12:15; 90/60 = 1 h 30 min.\n13:45"
    if "notebook and a pen" in user:
        return "If the pen is x, the notebook is x + 1.00, so 2x + 1.00 = 1.30 and x = 0.15.\nPen: £0.15"
    if "Eli's slot" in user:
        return "9:00 Cara\n10:00 Ben\n11:00 Dev\n12:00 Ana\n13:00 Eli"
    if "every 3rd day" in user:
        return "The 10th meeting is 27 days after 2 March.\nSunday 29 March"
    if "compare_versions" in user:
        return VERSIONS
    if "merge(ranges)" in user:
        return MERGE
    if "running_balance" in user:
        return BALANCE
    if "sister's birthday" in user:
        ok = "sister's birthday is on 3 May" in everything and "sister Priya lives in Leeds" in everything
        return "Your sister Priya's birthday is on 3 May, and she lives in Leeds." if ok else "I don't know."
    if "Which gym" in user:
        return "You now go to Anytime Fitness." if "Anytime Fitness" in everything else "I don't know."
    if "cat to my mum" in user:
        ok = "14 August" in everything and "day before" in everything
        return "Your flight is on 14 August, so the cat goes the day before.\n13 August" if ok else "I don't know."
    if "clashing" in user:
        ok = "Dinner with Sam" in everything and "Standup" in everything
        return ("Two clashes: Dentist (10:00–11:00) overlaps Standup (10:30–10:45), and Yoga (18:00–19:00) overlaps "
                "Dinner with Sam (18:30–20:00). Lunch with Jo and Budget call are back to back, not a clash.") if ok else "I can't see it."
    if "90-minute" in user:
        return "You're free from 14:00 to 16:00, so 14:00–15:30 works." if "Client call" in everything else "I can't see it."
    if "deal with today" in user:
        ok = "Pay council tax" in everything and "Call plumber" in everything
        return "Overdue: Pay council tax, Book MOT. Due today: Call plumber." if ok else "I can't see your reminders."
    return "OK"


def plausible_but_wrong(body):
    """The mistakes these tasks were written to catch: the intuitive answer, an off-by-one, the outdated or
    look-alike fact, back-to-back called a clash, acting without checking, and doing both halves of a contradiction."""
    system, user = body["messages"][0]["content"], _last_user(body)
    if "lookup step of JARVIS" in system:
        return json.dumps({"lookups": _lookup(user), "change": False})
    if "planning component" in system:
        notes = re.search(r"Save new documents in (\S+?)\.\s", system).group(1)
        if "todo.txt" in user:  # picks the first item instead of the urgent one
            steps = [{"description": "Add", "tool": "reminders", "action": "add",
                      "args": {"title": "Tidy the garage", "due": _day(1, 9).strftime("%Y-%m-%dT%H:%M")}, "depends_on": []}]
        elif "totals.md" in user:
            steps = [{"description": "Save", "tool": "fs", "action": "write",
                      "args": {"path": f"{notes}/totals.md", "content": "January 165.50, February 100, March 210.25, total 465.75"}, "depends_on": []}]
        elif "don't create any new files" in user:
            steps = [{"description": "Save", "tool": "fs", "action": "write",
                      "args": {"path": f"{notes}/summary.md", "content": "Launch in May."}, "depends_on": []}]
        else:  # assumes the appointment is tomorrow at 10
            steps = [{"description": "Add", "tool": "reminders", "action": "add",
                      "args": {"title": "Bring insurance card", "due": _day(1, 9).strftime("%Y-%m-%dT%H:%M")}, "depends_on": []}]
        return json.dumps({"goal": "x", "question": None, "cannot": None, "steps": steps})
    if "train leaves" in user:
        return "Travel time 2 h 20 min + 1 h 30 min = 3 h 50 min.\n13:30"
    if "notebook and a pen" in user:
        return "Pen: £0.30"
    if "Eli's slot" in user:
        return "9:00 Ben\n10:00 Cara\n11:00 Dev\n12:00 Ana\n13:00 Eli"
    if "every 3rd day" in user:
        return "Saturday 28 March"
    if "compare_versions" in user:  # compares as text: "1.10" < "1.9"
        return "```python\ndef compare_versions(a, b):\n    return (a > b) - (a < b)\n```"
    if "merge(ranges)" in user:  # touching ranges stay apart
        return MERGE.replace("s <= out[-1][1]", "s < out[-1][1]")
    if "running_balance" in user:  # skips the line too
        return BALANCE.replace("        out.append(balance)\n", "            out.append(balance)\n")
    if "sister's birthday" in user:
        return "Priya's birthday is 12 June and she lives in Bristol."
    if "Which gym" in user:
        return "You go to The Gym Group."
    if "cat to my mum" in user:
        return "14 August"
    if "clashing" in user:
        return "Lunch with Jo clashes with Budget call, and Yoga clashes with Dinner with Sam."
    if "90-minute" in user:
        return "You could do 10:30 to 12:00."
    if "deal with today" in user:
        return "Pay council tax, Book MOT, Call plumber and Renew passport."
    return "OK"


def _failed(res):
    return {k: [c for c in v["checks"] if c["passed"] is not True] for k, v in res.items() if v["status"] != "pass"}


def test_hard_set_is_separate_and_complete():
    hard = load_tasks(which="hard")
    assert len(hard) == 17 and {t.set for t in hard} == {"hard"} and all(t.id.startswith("hard-") for t in hard)
    assert {t.category for t in hard} == {"reasoning", "coding", "memory", "planning", "tool_use", "recovery"}
    assert not {t.id for t in hard} & {t.id for t in load_tasks(which="all")}  # "all" still means the earlier 24


# Found by writing these tasks: a perfect model failed these two, because JARVIS never put the facts in front of it.
# Fixed in smarter-v2: "overdue or due today" now lists both, and a small memory store is shown whole to answers that
# stay on this Mac. The right answers still pass their checks:
WERE_GAPS = {
    "hard-planning-today": "Overdue: Pay council tax, Book MOT. Due today: Call plumber.",
    "hard-memory-combine": "Your flight is on 14 August, so the cat goes the day before.\n13 August",
}


def test_a_perfect_model_passes_every_hard_task(config, tmp_path):  # noqa: F811 (pytest fixture)
    run_dir = run_suite(load_tasks(which="hard"), real_config=config(perfect), out_dir=tmp_path / "out", run_code=True)
    assert _failed(results_of(run_dir)) == {}


def test_the_former_gaps_have_sound_checks():
    tasks = {t.id: t for t in load_tasks(which="hard")}
    for tid, answer in WERE_GAPS.items():
        assert score({"answer": answer}, tasks[tid].checks)["status"] == "pass", tid


def test_a_plausible_but_wrong_model_fails_every_hard_task(config, tmp_path):  # noqa: F811 (pytest fixture)
    run_dir = run_suite(load_tasks(which="hard"), real_config=config(plausible_but_wrong), out_dir=tmp_path / "out",
                        run_code=True)
    res = results_of(run_dir)
    passed = sorted(k for k, v in res.items() if v["status"] == "pass")
    # smarter-v2: JARVIS itself now refuses a plan that breaks "don't create any new files" and asks instead, so
    # even this careless model passes that one. Its checks still fail the careless plan: see the test below.
    assert passed == ["hard-recovery-contradiction"]


def test_the_contradiction_checks_fail_a_plan_that_writes_anyway():
    task = next(t for t in load_tasks(which="hard") if t.id == "hard-recovery-contradiction")
    wrote = {"answer": "Saved.", "plan_kind": "plan", "approvals": [{"tool": "fs", "action": "write", "approved": False}],
             "files": "/nonexistent", "violations": []}
    assert score(wrote, task.checks)["status"] == "fail"
