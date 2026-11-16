"""Your week: counted from the tasks, approvals, objectives and audit log of the last 7 days. Nothing estimated,
nothing changed; an audit chain that doesn't verify is said first."""

import json
from datetime import datetime, timedelta, timezone

import pytest
from test_dashboard import call
from test_objectives import _mission

from jarvis import objectives, weekly


@pytest.fixture
def k(make_kernel):
    return make_kernel()


def test_quiet_week_says_so(k):
    r = weekly.review(k)
    assert r["headline"].startswith("A quiet week") and r["audit_ok"] is True
    assert r["missions"]["started"] == 0 and r["decisions"]["asked"] == 0


def test_counts_come_from_the_records(k):
    a = _mission(k, "Tidy the notes folder")                         # completed, verified
    _mission(k, "Book the dentist", "failed")
    _mission(k, "Plan the trip", "running")
    old = _mission(k, "Last month's thing")
    with k.db.tx() as c:                                              # outside the window: not counted
        c.execute("UPDATE tasks SET created_at = ? WHERE id = ?",
                  ((datetime.now(timezone.utc) - timedelta(days=20)).isoformat(), old))
    k.memory.remember("I like tea", by="user:dashboard")
    k.audit.record("permission.denied", tool="fs", action="write")
    o = objectives.create(k, "Keep the notes tidy", by="user:dashboard")
    objectives.link_mission(k, o["id"], a, source="test")
    r = weekly.review(k)
    m = r["missions"]
    assert (m["started"], m["completed"], m["failed"], m["open"], m["verified"]) == (3, 1, 1, 1, 1)
    assert [t["goal"] for t in m["list"]][0] == "Plan the trip" and "Last month's thing" not in [t["goal"] for t in m["list"]]
    assert r["memory"]["added"] == 1 and r["safety"]["refused_by_rules"] == 1
    assert r["objectives"][0]["outcome"] == "Keep the notes tidy" and r["objectives"][0]["missions_done"] == 1
    assert r["headline"] == "3 missions started, 1 completed, 1 failed; your rules refused 1 action."
    assert "Missions: 3 started" in weekly.as_text(r)


def test_broken_audit_chain_is_said_first(k):
    from jarvis.core.audit import VerifyResult
    k.audit.verify = lambda: VerifyResult(False, 3, 2, "previous-hash link broken")   # the log refuses edits
    r = weekly.review(k)
    assert r["audit_ok"] is False and weekly.as_text(r).splitlines()[1].startswith("WARNING")


def test_your_week_appears_on_sunday_until_seen(k):
    sunday = datetime(2026, 11, 15, 18, 0).astimezone()
    tuesday, thursday = sunday + timedelta(days=2), sunday + timedelta(days=4)
    assert weekly.due(k, now=sunday) and weekly.due(k, now=tuesday) and not weekly.due(k, now=thursday)
    weekly.mark_seen(k, now=sunday)
    assert not weekly.due(k, now=sunday) and not weekly.due(k, now=tuesday)   # the same week, seen
    assert weekly.due(k, now=sunday + timedelta(days=7))


def test_feed_item_and_routes(dash):
    d, _, _ = dash
    from jarvis import initiative
    sunday = datetime(2026, 11, 15, 18, 0).astimezone()
    items = initiative.feed(d.kernel, now=sunday)["items"]
    assert any(i["source"] == "weekly" and i["href"] == "#/weekly" for i in items)
    r = json.loads(call(d, "/api/weekly")[2])
    assert r["days"] == 7 and "headline" in r
    assert call(d, "/api/weekly/seen", {})[0] == 200
