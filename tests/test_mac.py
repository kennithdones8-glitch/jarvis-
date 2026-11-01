"""Mac apps (Calendar, Reminders, Notes, Mail drafts, opening apps) through the real gateway, permission engine
and approvals, with a stand-in for osascript that records what JARVIS asks each app. The JXA scripts themselves
run only on a real Mac (`jarvis mac check`)."""

import json
import subprocess
from datetime import datetime, timedelta, timezone

import pytest

from jarvis.core import StepSpec, TaskState
from jarvis.core.tools import CallContext
from jarvis.server.app import mac_preview
from jarvis.tools import default_registry
from jarvis.tools import mac
from jarvis.tools.mac import MacError, MacTool, expand

CTX = CallContext(task_id=None, step_id=None, op_id=None, resource=None)


class FakeMac:
    """Plays Calendar/Reminders/Notes/Mail: answers each script by name and records the arguments."""

    def __init__(self):
        self.calls, self.events, self.reminders, self.notes = [], [], [], []

    def __call__(self, name, args, timeout):
        self.calls.append((name, args))
        if name == "calendar.events":
            return self.events
        if name == "calendar.add":
            self.events.append({"title": args["title"], "start": args["start"], "end": args["end"], "all_day": False,
                                "location": args["location"], "calendar": args["calendar"] or "Home", "recurrence": None})
            return {**args, "calendar": args["calendar"] or "Home"}
        if name == "calendar.find":
            return {"found": any(e["title"] == args["title"] for e in self.events)}
        if name == "reminders.list":
            return [r for r in self.reminders if not r["completed"] and args.get("list") in (None, r["list"])]
        if name == "reminders.add":
            self.reminders.append({"title": args["title"], "due": args["due"], "completed": False, "notes": "", "list": "Reminders"})
            return {"title": args["title"], "list": "Reminders", "due": args["due"]}
        if name == "reminders.complete":
            hits = [r for r in self.reminders if r["title"] == args["title"] and not r["completed"]]
            if not hits:
                return {"error": "not_found"}
            hits[0]["completed"] = True
            return {"title": args["title"], "list": hits[0]["list"]}
        if name == "notes.search":
            hits = [n for n in self.notes if args["query"] in n["title"] + n["html"]]
            return {"total": len(hits), "results": [{"title": n["title"], "modified": None, "snippet": ""} for n in hits][:args["limit"]]}
        if name == "notes.create":
            self.notes.append(args)
            return {"title": args["title"], "folder": "Notes"}
        if name == "mail.draft":
            return {**args, "saved_as": "draft"}
        if name == "apps.open":
            return {"opened": args["name"]}
        raise AssertionError(name)


@pytest.fixture
def fake():
    return FakeMac()


@pytest.fixture
def k(make_kernel, tmp_path, fake):
    return make_kernel(registry=default_registry(tmp_path / "home", mac_runner=fake))


def run(k, *steps):
    tid = k.tasks.create("mac", steps=[StepSpec(*s) for s in steps], context={"runner": "cli"})
    return tid, k.engine.run(tid)


# ---- permissions: reading runs, changing asks ----------------------------------------------------------
def test_tools_and_tiers(k):
    from jarvis.core.permissions import Tier
    for tool, action, tier in (("calendar", "events", Tier.READ), ("calendar", "add", Tier.ROUTINE),
                               ("reminders", "list", Tier.READ), ("reminders", "add", Tier.ROUTINE),
                               ("reminders", "complete", Tier.ROUTINE), ("notes", "search", Tier.READ),
                               ("notes", "read", Tier.READ), ("notes", "create", Tier.ROUTINE),
                               ("mail", "draft", Tier.ROUTINE), ("apps", "open", Tier.ROUTINE)):
        assert k.registry.action(tool, action).tier is tier, (tool, action)
    assert k.registry.action("mail", "send") is None  # sending doesn't exist
    assert k.registry.action("calendar", "delete") is None


def test_reading_runs_without_asking(k, fake):
    now = datetime.now().astimezone()
    tid, state = run(k, ("Look at the week", "calendar", "events", {"from": now.isoformat(),
                                                                    "to": (now + timedelta(days=7)).isoformat()}))
    assert state is TaskState.COMPLETED and not k.approvals.pending()
    assert fake.calls[0][0] == "calendar.events"


def test_adding_asks_first_and_shows_exactly_what(k, fake):
    tid, state = run(k, ("Add dentist", "calendar", "add", {"title": "Dentist", "start": "2026-11-05T14:00",
                                                           "end": "2026-11-05T15:00", "location": "High St"}))
    assert state is TaskState.AWAITING_APPROVAL and fake.calls == []  # nothing reached Calendar yet
    appr = k.approvals.pending()[0]
    assert (appr["tool"], appr["action"]) == ("calendar", "add")
    k.approvals.decide(appr["id"], approve=True, by="user:test")
    assert k.engine.run(tid) is TaskState.COMPLETED
    assert fake.calls[0][0] == "calendar.add" and fake.calls[0][1]["title"] == "Dentist"


def test_rejected_change_never_reaches_the_app(k, fake):
    tid, _ = run(k, ("Draft", "mail", "draft", {"to": ["sam@example.com"], "subject": "Hi", "body": "Hello"}))
    k.approvals.decide(k.approvals.pending()[0]["id"], approve=False, by="user:test")
    k.engine.run(tid)
    assert fake.calls == []


def test_preview_for_approval_cards():
    p = mac_preview("calendar", "add", {"title": "Dentist", "start": "2026-11-05T14:00", "end": "2026-11-05T15:00"})
    assert "Event: Dentist" in p and "Thu 05 Nov 2026, 14:00" in p
    p = mac_preview("mail", "draft", {"to": ["sam@example.com"], "subject": "Hi", "body": "Hello"})
    assert "never sends" in p and "sam@example.com" in p and "Hello" in p
    assert mac_preview("reminders", "complete", {"title": "Milk"}).startswith("Tick off: Milk")


# ---- argument checks ------------------------------------------------------------------------------------
@pytest.mark.parametrize("tool,action,args,msg", [
    ("calendar", "events", {"from": "2026-11-05", "to": "2026-11-01"}, "forward"),
    ("calendar", "events", {"from": "2026-01-01", "to": "2026-06-01"}, "62 days"),
    ("calendar", "events", {"from": "next tuesday", "to": "2026-11-01"}, "date/time"),
    ("calendar", "add", {"title": "x", "start": "2026-11-05T15:00", "end": "2026-11-05T14:00"}, "end after"),
    ("mail", "draft", {"to": ["not an email"], "subject": "s", "body": "b"}, "email"),
    ("mail", "draft", {"to": ["a@b.co", "x@y.z; rm -rf"], "subject": "s", "body": "b"}, "email"),
    ("apps", "open", {"name": 'Safari"); doShellScript("rm'}, "app name"),
    ("notes", "search", {"query": "a", "limit": 500}, "limit"),
    ("reminders", "add", {"title": ""}, "title"),
])
def test_bad_arguments_refused_before_any_app_is_asked(fake, tool, action, args, msg):
    t = MacTool(runner=fake)
    with pytest.raises(MacError, match=msg):
        getattr(t, f"handle_{tool}")(action, args, CTX)
    assert fake.calls == []


def test_note_body_is_escaped_html(fake):
    MacTool(runner=fake).handle_notes("create", {"title": "Plan", "body": "<script>x</script>\nline 2"}, CTX)
    html = fake.notes[0]["html"]
    assert "<script>" not in html and "&lt;script&gt;" in html and "<div>line 2</div>" in html


def test_dates_without_a_zone_are_local_time(fake):
    MacTool(runner=fake).handle_reminders("add", {"title": "Call bank", "due": "2026-11-05T17:00"}, CTX)
    due = datetime.fromisoformat(fake.calls[0][1]["due"].replace("Z", "+00:00"))
    assert due == datetime(2026, 11, 5, 17, 0).astimezone()


def test_complete_needs_an_exact_open_reminder(fake):
    t = MacTool(runner=fake)
    with pytest.raises(MacError, match="no open reminder"):
        t.handle_reminders("complete", {"title": "Milk"}, CTX)
    t.handle_reminders("add", {"title": "Milk"}, CTX)
    assert t.handle_reminders("complete", {"title": "Milk"}, CTX)["title"] == "Milk"


# ---- repeating events ---------------------------------------------------------------------------------------
def utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


def test_weekly_meeting_appears_every_week_minus_exceptions():
    raw = [{"title": "Standup", "start": "2026-10-05T09:00:00Z", "end": "2026-10-05T09:30:00Z", "all_day": False,
            "location": "", "calendar": "Work", "recurrence": "FREQ=WEEKLY;BYDAY=MO", "excluded": ["2026-11-09T09:00:00Z"]},
           {"title": "Dentist", "start": "2026-11-05T14:00:00Z", "end": "2026-11-05T15:00:00Z", "all_day": False,
            "location": "", "calendar": "Home", "recurrence": None, "excluded": []},
           {"title": "Old", "start": "2026-10-01T10:00:00Z", "end": "2026-10-01T11:00:00Z", "all_day": False,
            "location": "", "calendar": "Home", "recurrence": None, "excluded": []}]
    out = expand(raw, utc(2026, 11, 1), utc(2026, 11, 23))
    standups = [e["start"] for e in out if e["title"] == "Standup"]
    assert standups == ["2026-11-02T09:00:00Z", "2026-11-16T09:00:00Z"]  # the 9th was cancelled
    assert [e["title"] for e in out] == ["Standup", "Dentist", "Standup"]
    assert all(e["title"] != "Old" for e in out)


def test_ended_repeat_and_bad_rules():
    raw = [{"title": "Course", "start": "2026-10-01T18:00:00Z", "end": "2026-10-01T19:00:00Z", "all_day": False,
            "location": "", "calendar": "c", "recurrence": "FREQ=WEEKLY;COUNT=3", "excluded": []},
           {"title": "Weird", "start": "2026-11-02T08:00:00Z", "end": "2026-11-02T09:00:00Z", "all_day": False,
            "location": "", "calendar": "c", "recurrence": "NOT A RULE", "excluded": []}]
    out = expand(raw, utc(2026, 11, 1), utc(2026, 11, 30))
    assert [e["title"] for e in out] == ["Weird"]  # the course ended in October; the odd rule still shows once


def test_meeting_already_in_progress_at_range_start_is_included():
    raw = [{"title": "Offsite", "start": "2026-10-31T09:00:00Z", "end": "2026-11-02T17:00:00Z", "all_day": True,
            "location": "", "calendar": "c", "recurrence": None, "excluded": []}]
    assert len(expand(raw, utc(2026, 11, 1), utc(2026, 11, 3))) == 1


# ---- osascript plumbing ----------------------------------------------------------------------------------------
def test_arguments_go_as_data_never_into_the_script(monkeypatch):
    seen = {}

    def fake_run(argv, **kw):
        seen["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, '{"opened": "Music"}', "")
    monkeypatch.setattr(mac.subprocess, "run", fake_run)
    mac.osascript("apps.open", {"name": 'Mu"sic'}, 5)
    argv = seen["argv"]
    assert argv[:4] == ["osascript", "-l", "JavaScript", "-e"]
    assert 'Mu"sic' not in argv[4] and json.loads(argv[5]) == {"name": 'Mu"sic'}


@pytest.mark.parametrize("stderr,msg", [
    ("execution error: Not authorized to send Apple events to Calendar. (-1743)", "Privacy & Security"),
    ("execution error: Error: Can't get object. (-1728)", "check the name"),
])
def test_errors_explained(monkeypatch, stderr, msg):
    monkeypatch.setattr(mac.subprocess, "run", lambda argv, **kw: subprocess.CompletedProcess(argv, 1, "", stderr))
    with pytest.raises(MacError, match=msg):
        mac.osascript("calendar.events", {}, 5)


def test_timed_out_change_is_marked_uncertain_not_retried(monkeypatch):
    def slow(argv, **kw):
        raise subprocess.TimeoutExpired(argv, 1)
    monkeypatch.setattr(mac.subprocess, "run", slow)
    with pytest.raises(MacError) as change:
        mac.osascript("calendar.add", {}, 1)
    assert change.value.outcome_unknown and not change.value.retryable
    with pytest.raises(MacError) as read:
        mac.osascript("calendar.events", {}, 1)
    assert read.value.retryable and not read.value.outcome_unknown


def test_reconcile_after_a_crash(fake):
    t = MacTool(runner=fake)
    check = t.specs()[0].actions["add"].reconcile
    args = {"title": "Dentist", "start": "2026-11-05T14:00", "end": "2026-11-05T15:00"}
    assert check(args, "op") == "not_done"
    t.handle_calendar("add", args, CTX)
    assert check(args, "op") == "done"


# ---- planner + CLI --------------------------------------------------------------------------------------------
def test_planner_knows_the_date_and_the_mac_actions(k):
    from jarvis.orchestrator import Orchestrator
    prompt = Orchestrator(k).planner.system_prompt()
    assert "calendar.events" in prompt and "mail.draft" in prompt and "never sends" in prompt
    assert datetime.now().astimezone().strftime("%Y") in prompt.split("Now:")[1][:80]


def test_not_registered_off_macos(tmp_path, monkeypatch):
    monkeypatch.setattr(mac, "available", lambda: False)
    assert default_registry(tmp_path).action("calendar", "events") is None


def test_mac_check_cli(fake, capsys):
    from jarvis.cli import _mac_check
    assert _mac_check(runner=fake) == 0
    out = capsys.readouterr().out
    assert "✓ Calendar" in out and "✓ Reminders" in out and "nothing is changed" in out
    assert {c[0] for c in fake.calls} == {"calendar.events", "reminders.list", "notes.search"}  # reads only


def test_calendar_reply_with_timing_dedupes_and_reports_gaps():
    ev = {"title": "Standup", "start": "2026-11-02T09:00:00Z", "end": "2026-11-02T09:30:00Z", "all_day": False,
          "location": "", "calendar": "Work", "recurrence": None, "excluded": []}

    def runner(name, args, timeout):
        return {"events": [ev, dict(ev)], "timing": [
            {"calendar": "Work", "overlapping": 1, "repeating": 1, "seconds": 0.4},
            {"calendar": "Holidays", "seconds": 2.0, "error": "repeating: can't filter"}]}
    r = MacTool(runner=runner).handle_calendar("events", {"from": "2026-11-02T00:00:00Z", "to": "2026-11-03T00:00:00Z"}, CTX)
    assert r["count"] == 1  # the same event from both questions counts once
    assert r["incomplete"] == ["Holidays: repeating: can't filter"]  # a gap is reported, never hidden
    assert r["timing"][0]["calendar"] == "Work"


def test_calendar_script_never_asks_for_the_whole_history():
    """`whose` date/recurrence filters stalled Calendar for over 85 s on the owner's Mac (macOS 14), while bulk
    reads of every event took seconds; the script must bulk-read and filter itself, with a cap."""
    from jarvis.tools.mac import SCRIPTS
    script = SCRIPTS["calendar.events"]
    assert ".whose(" not in script
    assert "evs.startDate()" in script and "evs.recurrence()" in script and "max" in script


FAKE_CALENDAR = """
const D = (s) => new Date(s);
const data = {
  Work: [["Standup", "2026-11-02T09:00:00Z", "2026-11-02T09:15:00Z", ""],
         ["Old meeting", "2025-01-01T09:00:00Z", "2025-01-01T10:00:00Z", ""],
         ["Weekly 1:1", "2026-01-05T14:00:00Z", "2026-01-05T14:30:00Z", "FREQ=WEEKLY"],
         ["Next year", "2027-06-01T09:00:00Z", "2027-06-01T10:00:00Z", "FREQ=DAILY"]],
  Birthdays: [["Sam", "2001-11-03T00:00:00Z", "2001-11-04T00:00:00Z", "FREQ=YEARLY"]],
};
function cal(name) {
  const rows = data[name];
  const evs = rows.map((r) => ({summary: () => r[0], alldayEvent: () => name === "Birthdays", location: () => "",
                                excludedDates: () => []}));
  evs.startDate = () => rows.map((r) => D(r[1]));
  evs.endDate = () => rows.map((r) => D(r[2]));
  evs.recurrence = () => rows.map((r) => r[3]);
  evs.whose = () => { throw new Error("whose must not be used"); };
  return {name: () => name, events: evs};
}
function Application() {
  const cals = () => Object.keys(data).map(cal);
  cals.byName = cal;
  return {calendars: cals};
}
"""


def test_calendar_script_filters_correctly(tmp_path):
    import shutil
    from jarvis.tools.mac import PRELUDE, SCRIPTS
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    js = tmp_path / "cal.js"
    js.write_text(FAKE_CALENDAR + PRELUDE + SCRIPTS["calendar.events"] +
                  "\nconsole.log(run([process.argv[2]]));")

    def call(**a):
        out = subprocess.run([node, str(js), json.dumps(a)], capture_output=True, text=True, check=True).stdout
        return json.loads(out)

    r = call(**{"from": "2026-11-01T00:00:00Z", "to": "2026-11-08T00:00:00Z"})
    titles = sorted(e["title"] for e in r["events"])
    assert titles == ["Sam", "Standup", "Weekly 1:1"]  # not the old one-off, not the future repeating one
    assert {t["calendar"]: (t["overlapping"], t["repeating"]) for t in r["timing"]} == {"Work": (1, 1), "Birthdays": (0, 1)}
    assert not any(t.get("error") for t in r["timing"])
    capped = call(**{"from": "2026-11-01T00:00:00Z", "to": "2026-11-08T00:00:00Z", "max": 1})
    assert len(capped["events"]) == 1 and "stopped at 1" in capped["timing"][0]["error"]
    only = call(**{"from": "2026-11-01T00:00:00Z", "to": "2026-11-08T00:00:00Z", "calendar": "Birthdays"})
    assert [e["title"] for e in only["events"]] == ["Sam"]
