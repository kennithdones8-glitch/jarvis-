"""Tier 7: nightly self-checks and lesson-based routing nudges — bounded, logged, undoable, and off unless allowed."""

from datetime import datetime

from test_learn import replies
from test_models import model_kernel, servers  # noqa: F401 - fixtures

from jarvis.learn import Autonomy, Pipeline, autopilot
from jarvis.models import ChatRequest, Message, Need
from jarvis.models.types import Category


def tier7(k):
    Autonomy(k).set_tier(6, True, by="cli", from_dashboard=False)
    Autonomy(k).set_tier(7, True, by="cli", from_dashboard=False)


def test_nothing_happens_without_tier_7(make_kernel):
    k = make_kernel()
    replies(k, "haiku", 8, still=1)
    Pipeline(k).run()
    assert autopilot.act_on_lessons(k) == [] and autopilot.router_bonus(k) == {}
    assert autopilot.nightly(k, now=datetime(2026, 1, 1, 4).astimezone()) == []


def test_strong_lessons_nudge_routing_and_can_be_undone_for_good(make_kernel):
    k = make_kernel()
    tier7(k)
    replies(k, "haiku", 8, still=1)
    Pipeline(k).run()
    [adj] = autopilot.act_on_lessons(k)
    assert adj["model"] == "haiku" and adj["bonus"] == -3.0
    autopilot.apply_to_router(k)
    assert k.models.router.adjust == {"haiku": -3.0}
    autopilot.undo(k, adj["lesson"], by="t")
    assert k.models.router.adjust == {} and autopilot.act_on_lessons(k) == []      # never re-applied for that lesson
    assert "You undid a routing adjustment." in autopilot.digest(k)
    k.killswitch.engage(by="t", reason="x")
    assert autopilot.router_bonus(k) == {}                                          # the stop clears every nudge


def test_nudges_reorder_allowed_models_only_and_never_beat_local_first(model_kernel):  # noqa: F811 - pytest fixture
    """A local model (quality 2) and a cloud model (quality 4). Nudges change the ranking among allowed models only."""
    k, *_ = model_kernel()
    r = k.models.router
    request = ChatRequest((Message("user", "hi", Category.CONVERSATION),))
    order = lambda: [c.model for c in r.route(Need("chat", prefer="quality"), request).candidates]   # noqa: E731
    r.mode = "best"
    assert order() == ["big-70b", "small:3b"]
    r.adjust = {"big-70b": -99.0, "small:3b": 99.0}          # clamped to ±3: quality still dominates (10 per point)
    assert order() == ["big-70b", "small:3b"]
    r.mode = "local_first"                                   # the local-first bonus (100) is never overtaken
    r.adjust = {"big-70b": 3.0, "small:3b": -3.0}
    assert order()[0] == "small:3b"
    r.adjust = {"not-configured": 3.0}
    assert sorted(order()) == ["big-70b", "small:3b"]       # a nudge never makes a model appear that isn't allowed


def test_nightly_self_checks_run_once_a_day_after_3am(make_kernel):
    k = make_kernel()
    tier7(k)
    assert autopilot.nightly(k, now=datetime(2026, 1, 1, 2).astimezone()) == []      # before 03:00
    ids = autopilot.nightly(k, now=datetime(2026, 1, 1, 4).astimezone())
    assert len(ids) == 3
    states = {r["kind"]: r["state"] for r in k.db.query("SELECT kind, state FROM experiments")}
    assert set(states) == {"replay", "drill", "bench_compare"} and "running" not in states.values()
    assert autopilot.nightly(k, now=datetime(2026, 1, 1, 23).astimezone()) == []     # once a day
    assert any(line.startswith("Self-check drill") for line in autopilot.digest(k, hours=24 * 365 * 10))
