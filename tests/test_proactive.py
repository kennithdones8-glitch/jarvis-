"""Proactive JARVIS: morning briefing, quiet hours, reminders and health alerts."""

import json
from datetime import datetime, timedelta

import pytest

from test_dashboard import call, dash  # noqa: F401  (fixture)

from jarvis.core import StepSpec
from jarvis.models.config import ConfigError, parse_model_config
from jarvis.proactive import (Schedule, briefing_text, build_briefing, last_briefing_date, mark_briefing_sent)
from jarvis.remote.push import Notifier

DAY = datetime(2026, 11, 2).astimezone()


def at(hh, mm=0, day=DAY):
    return day.replace(hour=hh, minute=mm)


class FakePush:
    def __init__(self):
        self.sent = []

    def send(self, title, body, *, tag, url="/"):
        self.sent.append((tag, body, url))


def needs_approval(k, root, name="draft.txt"):
    tid = k.tasks.create("write a draft", steps=[StepSpec("save", "fs", "write", {"path": f"{root}/{name}", "content": "x"})])
    k.engine.run(tid)
    assert k.approvals.pending(task_id=tid)
    return tid


# ---- schedule -------------------------------------------------------------------------------
def test_quiet_hours_across_midnight_and_off():
    s = Schedule(quiet_hours="22:00-07:00")
    assert s.quiet(at(23)) and s.quiet(at(3)) and s.quiet(at(6, 59))
    assert not s.quiet(at(7)) and not s.quiet(at(12)) and not s.quiet(at(21, 59))
    assert Schedule(quiet_hours="13:00-14:00").quiet(at(13, 30))
    assert not Schedule(quiet_hours="").quiet(at(3))


def test_briefing_due_once_in_its_window():
    s = Schedule(briefing_time="08:00")
    assert not s.briefing_due(at(7, 59), None)
    assert s.briefing_due(at(8), None) and s.briefing_due(at(11, 30), None)
    assert not s.briefing_due(at(12, 30), None)                       # too late to call it a morning briefing
    assert not s.briefing_due(at(9), DAY.date().isoformat())          # already announced today
    assert s.briefing_due(at(9, day=DAY + timedelta(days=1)), DAY.date().isoformat())
    assert not Schedule(enabled=False).briefing_due(at(8), None)


def test_config_validation():
    assert parse_model_config({}).proactive["briefing_time"] == "08:00"
    assert parse_model_config({"proactive": {"quiet_hours": ""}}).proactive["quiet_hours"] == ""
    for bad in ({"briefing_time": "8am"}, {"quiet_hours": "22-07"}, {"approval_reminder_min": 1}, {"nope": 1}):
        with pytest.raises(ConfigError):
            parse_model_config({"proactive": bad})


# ---- briefing content -----------------------------------------------------------------------
def test_briefing_from_live_state(make_kernel, root):
    k = make_kernel()
    assert build_briefing(k)["headline"] == "Nothing needs you."
    assert "All quiet" in briefing_text(build_briefing(k))
    (root / "in.txt").write_text("x")
    done = k.tasks.create("summarise the notes", steps=[StepSpec("r", "fs", "read", {"path": f"{root}/in.txt"})])
    k.engine.run(done)
    needs_approval(k, root)
    k.engine.emergency_stop(by="t", reason="t")
    b = build_briefing(k, health={"items": [{"name": "Backups", "ok": False, "detail": "no backups yet"}]})
    titles = {s["title"]: s["items"] for s in b["sections"]}
    assert b["headline"] == "1 thing needs you."
    assert len(titles["Needs you"]) == 1 and "summarise the notes" in titles["Finished"]
    assert any("emergency stop" in i for i in titles["Systems"]) and "Backups: no backups yet" in titles["Systems"]
    # nothing is stored: deleting the task removes it from the next briefing
    k.tasks.delete(done, by="t")
    assert "Finished" not in {s["title"] for s in build_briefing(k)["sections"]}


def test_briefing_window_starts_at_previous_briefing(make_kernel):
    k = make_kernel()
    mark_briefing_sent(k, at(8))
    assert last_briefing_date(k) == DAY.date().isoformat()
    mark_briefing_sent(k, at(8, day=DAY + timedelta(days=1)))
    since = datetime.fromisoformat(build_briefing(k)["since"])
    assert abs(since.timestamp() - at(8).timestamp()) < 1


# ---- notifications --------------------------------------------------------------------------
def test_quiet_hours_hold_notifications(make_kernel, root):
    k = make_kernel()
    push = FakePush()
    now = datetime.now().astimezone()
    window = f"{(now - timedelta(hours=1)):%H:%M}-{(now + timedelta(hours=1)):%H:%M}"  # quiet right now
    n = Notifier(k, push, min_interval_s=0, schedule=Schedule(quiet_hours=window))
    needs_approval(k, root)
    assert n.poll(now=now) == [] and push.sent == []
    assert n.health_changed(False, now=now) is False
    n.schedule = Schedule(quiet_hours="")
    assert n.poll(now=now + timedelta(minutes=5)) == []  # no burst of held-back news afterwards


def test_waiting_decision_reminded_once(make_kernel, root):
    k = make_kernel()
    push = FakePush()
    n = Notifier(k, push, min_interval_s=0, schedule=Schedule(quiet_hours="", approval_reminder_min=60))
    needs_approval(k, root)
    now = datetime.now().astimezone()
    assert n.poll(now=now) == ["approval"]
    assert n.poll(now=now + timedelta(minutes=30)) == []
    assert n.poll(now=now + timedelta(minutes=61)) == ["reminder"]
    assert n.poll(now=now + timedelta(minutes=200)) == []
    assert [t for t, *_ in push.sent] == ["approval", "approval"]
    assert push.sent[1][1] == "A decision is still waiting for you"


def test_health_alert_generic_and_rate_limited(make_kernel):
    k = make_kernel()
    push = FakePush()
    n = Notifier(k, push, min_interval_s=3600, schedule=Schedule(quiet_hours=""))
    assert n.health_changed(True) is False
    assert n.health_changed(False) is True and n.health_changed(False) is False
    assert push.sent == [("health", "Something on your Mac needs attention", "/")]


# ---- dashboard & CLI ------------------------------------------------------------------------
def test_dashboard_announces_briefing_once(dash):
    d, *_ = dash
    push = FakePush()
    d.notifier = Notifier(d.kernel, push, schedule=Schedule(quiet_hours=""))
    assert d.maybe_briefing(now=at(7)) is False
    assert d.maybe_briefing(now=at(8, 5)) is True and d.maybe_briefing(now=at(9)) is False
    assert push.sent == [("briefing", "Your morning briefing is ready", "/#briefing")]
    status, _, body = call(d, "/api/briefing")
    assert status == 200 and json.loads(body)["headline"].startswith("Nothing needs")
    assert any(e["event"] == "briefing.ready" for e in d.kernel.audit.entries())


def test_briefing_needs_sign_in(dash):
    d, *_ = dash
    assert call(d, "/api/briefing", cookie=False)[0] == 401


def test_cli_briefing(tmp_path, capsys):
    from jarvis.cli import main as cli_main
    assert cli_main(["--home", str(tmp_path / "home"), "briefing"]) == 0
    assert "Nothing needs you." in capsys.readouterr().out


def test_notification_links_stay_inside_jarvis(make_kernel, tmp_path):
    from jarvis.remote.push import PushError, PushService
    k = make_kernel()
    push = PushService(k.db, k.audit, tmp_path / "vapid.pem", opener=None)
    for bad in ("https://evil.example/", "//evil.example/x", "javascript:alert(1)"):
        with pytest.raises(PushError):
            push.send("JARVIS", "x", url=bad)
    assert push.send("JARVIS", "x", url="/#briefing") == 0  # no phones subscribed: nothing sent
