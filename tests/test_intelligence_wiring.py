"""Evolution 3.0, phase 3 — connecting the intelligence systems.

(a) The intelligence tournament informs routing (tier 7 only): bounded, logged, undoable, withdrawn when the evidence
    no longer supports it, and only among models routing already allows.
(b) Lasting knowledge links: which memories were given to an answer, the evidence behind project ideas, a replan and
    the mission it retried. References only (ids), never text; forgetting either side removes the link.
(c) One ranked Initiative feed: suggests, never acts; paused with the initiative pause; dismissals respected;
    at most one generic notification a day, never in quiet hours.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from jarvis import initiative
from jarvis.core.tasks import StepSpec
from jarvis.learn import Autonomy, analysis, autopilot


def outcomes(k, model, verified, failed):
    now = datetime.now(timezone.utc).isoformat()
    with k.db.tx() as c:
        for i in range(verified + failed):
            c.execute("INSERT INTO outcomes (id, kind, ref, model, verdict, evidence, seconds, errors, recovered, created_at) "
                      "VALUES (?, 'reply', ?, ?, ?, '{}', 1.0, 0, 0, ?)",
                      (f"o-{model}-{i}", f"{model}-{i}", model, "verified" if i < verified else "failed", now))


def tier7(k, on=True):
    for n in (6, 7):
        Autonomy(k).set_tier(n, on, by="user:cli", from_dashboard=False)


# ---- (a) the tournament informs routing ---------------------------------------------------------------------------
def test_the_tournament_moves_routing_only_at_tier_7_and_within_limits(make_kernel):
    k = make_kernel()
    outcomes(k, "ollama/good:7b", 9, 1)
    outcomes(k, "ollama/weak:3b", 4, 6)
    assert analysis.tournament(k)["recommendation"] is not None                      # 90% vs 40%: a clear gap
    assert autopilot.act_on_tournament(k) == [] and k.models.router.adjust == {}    # tier 7 off: nothing happens
    tier7(k)
    added = autopilot.act_on_tournament(k)
    assert {(a["model"], a["bonus"]) for a in added} == {("good:7b", 2.0), ("weak:3b", -3.0)}
    assert all(a["evidence"]["source"] == "intelligence tournament" and a["evidence"]["answers_checked"] == 10 for a in added)
    assert k.models.router.adjust == {"good:7b": 2.0, "weak:3b": -3.0}               # the router clamps ±3 anyway
    assert autopilot.act_on_tournament(k) == []                                     # applied once, not again
    assert any(e["event"] == "autopilot.adjust" for e in k.audit.entries(limit=20))


def test_an_undone_adjustment_stays_undone_and_a_closed_gap_is_withdrawn(make_kernel):
    k = make_kernel()
    tier7(k)
    outcomes(k, "ollama/good:7b", 9, 1)
    outcomes(k, "ollama/weak:3b", 4, 6)
    autopilot.act_on_tournament(k)
    autopilot.undo(k, "tournament:best:ollama/good:7b", by="user:dashboard")
    autopilot.act_on_tournament(k)
    assert "good:7b" not in k.models.router.adjust                                 # you undid it: never re-applied
    with k.db.tx() as c:                                                           # the weak model catches up
        c.execute("UPDATE outcomes SET verdict = 'verified' WHERE model = 'ollama/weak:3b'")
    changed = autopilot.act_on_tournament(k)
    assert [a["lesson"] for a in changed] == ["tournament:worst:ollama/weak:3b"] and changed[0]["active"] is False
    assert k.models.router.adjust == {}
    assert any("withdrew the adjustment for weak:3b" in line for line in autopilot.digest(k))


def test_a_lesson_and_the_tournament_add_up_for_one_model(make_kernel):
    k = make_kernel()
    tier7(k)
    autopilot._put(k.db, autopilot.KEY, json.dumps([
        {"lesson": "reply-quality:x", "model": "good:7b", "bonus": 2.0, "active": True},
        {"lesson": "tournament:best:ollama/good:7b", "model": "good:7b", "bonus": 2.0, "active": True}]))
    assert autopilot.router_bonus(k) == {"good:7b": 4.0}                            # summed; the router caps it at +3


# ---- (b) lasting knowledge links ----------------------------------------------------------------------------------
def test_links_hold_ids_only_and_vanish_with_either_side(make_kernel):
    k = make_kernel()
    mid = k.memory.remember("My sister lives in Lisbon")
    rid = k.memory.learn_from("s", "Where could I stay in Portugal?", "Your sister is in Lisbon.", background=False)
    assert k.memory.link_informed([mid, mid], rid) == 1
    row = k.db.one("SELECT * FROM links WHERE src = ?", (f"memory:{mid}",))
    assert row["dst"] == f"record:{rid}" and row["rel"] == "context for"             # what happened, no stronger claim
    assert "Lisbon" not in json.dumps(dict(row))                                     # references only, never text
    g = analysis.knowledge_graph(k)
    conv = next(n for n in g["nodes"] if n["id"] == f"record:{rid}")
    assert conv["kind"] == "conversation" and conv["label"].startswith("a conversation on ") and "Portugal" not in conv["label"]
    assert {"from": f"memory:{mid}", "to": f"record:{rid}", "rel": "context for"} in g["edges"]
    k.memory.delete(mid, by="user:test")
    assert k.db.one("SELECT COUNT(*) FROM links")[0] == 0
    mid2 = k.memory.remember("I prefer window seats")
    k.memory.link_informed([mid2], rid)
    k.memory.delete_record(rid, by="user:test")
    assert k.db.one("SELECT COUNT(*) FROM links")[0] == 0


def test_forget_removes_links_through_the_normal_path(make_kernel):
    k = make_kernel()
    mid = k.memory.remember("Biscuit is my dog")
    rid = k.memory.learn_from("s", "What should Biscuit eat?", "Dog food.", background=False)
    k.memory.link_informed([mid], rid)
    k.forget("Biscuit", by="user:test", dry_run=False)
    assert k.db.one("SELECT COUNT(*) FROM links WHERE src LIKE 'memory:%' OR dst LIKE 'record:%'")[0] == 0


def test_the_graph_connects_project_evidence_and_replans_without_copies(make_kernel):
    k = make_kernel()
    mid = k.memory.remember("I want to learn watercolour")
    now = datetime.now(timezone.utc).isoformat()
    body = {"why": "x", "evidence": [{"type": "memory", "id": mid}], "steps": [{"text": "a", "done": False}]}
    with k.db.tx() as c:
        c.execute("INSERT INTO project_ideas (id, kind, title, body, state, created_at, updated_at) VALUES ('p1', 'growth', 'Paint weekly', ?, 'open', ?, ?)",
                  (json.dumps(body), now, now))
    first = k.tasks.create("x", steps=[StepSpec("a", "fs", "read", {"path": "/x"})], context={"runner": "cli"})
    second = k.tasks.create("x", steps=[StepSpec("a", "fs", "read", {"path": "/x"})], context={"runner": "cli", "replan_of": first})
    g = analysis.knowledge_graph(k)
    assert {"from": f"memory:{mid}", "to": "project:p1", "rel": "evidence for"} in g["edges"]
    assert {"from": f"task:{second}", "to": f"task:{first}", "rel": "second attempt of"} in g["edges"]
    assert k.db.one("SELECT COUNT(*) FROM links")[0] == 0                          # derived from the ideas themselves


def test_chat_records_which_memories_each_answer_was_given():
    from pathlib import Path
    app = (Path(__file__).resolve().parents[1] / "src" / "jarvis" / "server" / "app.py").read_text()
    assert 'memory.link_informed([m["id"] for m in recalled if m.get("id")], record)' in app


# ---- (c) the Initiative feed --------------------------------------------------------------------------------------
def _failed_mission(k, goal="Summarise my notes"):
    tid = k.tasks.create("r", goal=goal, steps=[StepSpec("Read", "fs", "read", {"path": "/nope"})], context={"runner": "cli"})
    k.engine.run(tid)
    return tid


def _proposal(k, key, size):
    now = datetime.now(timezone.utc).isoformat()
    with k.db.tx() as c:
        c.execute("INSERT INTO proposals (id, key, kind, title, body, state, created_at, updated_at) VALUES (?, ?, 'rule', ?, ?, 'open', ?, ?)",
                  (f"pr-{key}", key, f"Fix {key}", json.dumps({"problem": "it keeps failing", "size": size, "evidence": []}), now, now))


def test_the_feed_ranks_what_matters_and_explains_why(make_kernel):
    k = make_kernel()
    tid = _failed_mission(k)
    _proposal(k, "slow-model", 2)
    health = {"items": [{"name": "Backups", "ok": False, "detail": "no backup for 9 days"}, {"name": "Database", "ok": True}]}
    items = initiative.feed(k, health=health)["items"]
    assert [i["source"] for i in items] == ["health", "mission", "proposal"]
    assert items[1]["key"] == f"mission-failed:{tid}" and "plan it once more" in items[1]["why"]
    for it in items:
        assert it["score"] == round((2 * it["urgency"] + it["value"]) * (0.5 + 0.5 * it["confidence"]), 2)
        assert set(it) == {"key", "source", "title", "why", "value", "urgency", "confidence", "score", "size", "href"}   # no actions


def test_a_replanned_mission_and_old_failures_leave_the_feed(make_kernel):
    k = make_kernel()
    tid = _failed_mission(k)
    k.tasks.create("r", steps=[StepSpec("Read", "fs", "read", {"path": "/x"})], context={"runner": "cli", "replan_of": tid})
    assert not [i for i in initiative.feed(k)["items"] if i["source"] == "mission"]
    _failed_mission(k)
    later = datetime.now(timezone.utc) + timedelta(days=8)
    assert not [i for i in initiative.feed(k, now=later)["items"] if i["source"] == "mission"]


def test_the_initiative_pause_and_the_emergency_stop_empty_the_feed(make_kernel):
    k = make_kernel()
    _failed_mission(k)
    Autonomy(k).set_pause("initiative", True, by="user:test")
    f = initiative.feed(k)
    assert f["paused"] and f["items"] == [] and "paused" in f["why"]
    Autonomy(k).set_pause("initiative", False, by="user:test")
    k.killswitch.engage(reason="t", by="user:test")
    assert initiative.feed(k)["why"] == "the emergency stop is on"


def test_dismissing_hides_until_the_evidence_doubles(make_kernel):
    k = make_kernel()
    _proposal(k, "slow-model", 3)
    initiative.dismiss(k, "proposal:slow-model", by="user:dashboard", size=3)
    assert not initiative.feed(k)["items"]
    with k.db.tx() as c:
        c.execute("UPDATE proposals SET body = ? WHERE key = 'slow-model'", (json.dumps({"problem": "x", "size": 6}),))
    assert [i["key"] for i in initiative.feed(k)["items"]] == ["proposal:slow-model"]   # twice the evidence: back
    with pytest.raises(PermissionError):
        initiative.dismiss(k, "proposal:slow-model", by="jarvis:autopilot")
    later = datetime.now(timezone.utc) + timedelta(days=31)
    initiative.dismiss(k, "proposal:other", by="user:dashboard")
    assert initiative.feed(k, now=later)["items"]                                   # dismissals expire after 30 days


def test_one_generic_notification_a_day_never_in_quiet_hours(make_kernel):
    from jarvis.proactive import Schedule
    from jarvis.remote.push import Notifier

    class Recorder:   # stands in for the push service: records what would be sent
        def __init__(self):
            self.sent = []

        def send(self, title, body, **kw):
            self.sent.append((title, body, kw))
    k = make_kernel()
    _failed_mission(k)
    assert initiative.should_notify(k) is True and initiative.should_notify(k) is False   # once a day
    with k.db.tx() as c:
        c.execute("DELETE FROM meta WHERE key = ?", (initiative.NOTIFIED,))
    push = Recorder()
    quiet = Notifier(k, push, min_interval_s=0, schedule=Schedule(quiet_hours="00:00-23:59"))
    assert "initiative" not in quiet.poll()                                          # quiet hours: held back
    loud = Notifier(k, push, min_interval_s=0, schedule=Schedule(quiet_hours=""))
    sent = loud.poll()
    assert "initiative" in sent and "initiative" not in loud.poll()
    assert ("JARVIS", "JARVIS has a suggestion") in [(t, b) for t, b, _ in push.sent]   # generic: never the item itself


def test_the_feed_endpoints(dash):
    from test_dashboard import call
    d, *_ = dash
    status, _, body = call(d, "/api/initiative")
    assert status == 200 and "items" in json.loads(body)
    assert call(d, "/api/initiative/dismiss", {"key": "proposal:x"})[0] == 200
    assert "proposal:x" in json.loads(d.kernel.db.one("SELECT value FROM meta WHERE key = ?", (initiative.DISMISSED,))["value"])


def test_a_hidden_problem_comes_back_after_a_day_and_hidden_items_are_counted(make_kernel):
    k = make_kernel()
    health = {"items": [{"name": "Backups", "ok": False, "detail": "no backup"}]}
    initiative.dismiss(k, "health:Backups", by="user:dashboard")
    f = initiative.feed(k, health=health)
    assert f["items"] == [] and f["hidden"] == 1                                     # said, not silently gone
    tomorrow = datetime.now(timezone.utc) + timedelta(days=1, minutes=1)
    assert [i["key"] for i in initiative.feed(k, health=health, now=tomorrow)["items"]] == ["health:Backups"]
