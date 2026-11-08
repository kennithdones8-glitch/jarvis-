"""Continuous intelligence: outcomes need evidence, lessons carry evidence and confidence, contradictions and stale
evidence are flagged, the owner controls autonomy, experiments stay isolated, and nothing here can act."""

import json
from datetime import datetime, timedelta, timezone

import pytest
from test_dashboard import call

from jarvis import learn
from jarvis.learn import Autonomy, AutonomyError, Pipeline, analysis, projections


def replies(k, model, n, *, still=0, local=False, latency=3.0):
    for _ in range(n):
        if local:
            k.audit.record("model.local_call", model=model, purpose="dashboard chat", latency_s=latency)
        else:
            k.audit.record("egress.received", provider="claude", model=model, latency_s=latency)
        k.audit.record("chat.answer_check", problems=still, retried=False, still=still)


def test_outcomes_are_judged_by_evidence_not_by_returning(make_kernel):
    k = make_kernel()
    replies(k, "sonnet", 2)
    replies(k, "sonnet", 1, still=2)
    k.audit.record("task.state", task_id="task_x", frm="running", to="completed")   # completion alone proves nothing
    assert Pipeline(k).run()["outcomes"] == 3
    rows = k.db.query("SELECT kind, verdict FROM outcomes ORDER BY created_at")
    assert [(r["kind"], r["verdict"]) for r in rows] == [("reply", "verified"), ("reply", "verified"), ("reply", "failed")]
    k.audit.record("task.verified", task_id="task_x", verifier="all_steps_done", ok=False, evidence={"incomplete_steps": [2]})
    Pipeline(k).run()
    assert k.db.one("SELECT verdict FROM outcomes WHERE kind = 'task' AND ref = 'task_x'")["verdict"] == "failed"
    assert Pipeline(k).run()["outcomes"] == 0                                                      # each entry read once


def test_lessons_have_evidence_confidence_and_flag_contradictions(make_kernel):
    k = make_kernel()
    replies(k, "haiku", 6, still=1)
    Pipeline(k).run()
    [lesson] = learn.lessons(k)
    assert lesson["polarity"] == -1 and lesson["kind"] == "inferred" and lesson["evidence"]["failed"] == 6
    assert 0.4 < lesson["confidence"] <= 0.95
    for _ in range(4):   # the owner says otherwise: two lessons about the same model point opposite ways
        learn.add_feedback(k, target="reply", ref=f"r{_}", rating=1, model="claude/haiku")
    Pipeline(k).run()
    kinds = {les["key"]: les["kind"] for les in learn.lessons(k)}
    assert kinds == {"reply-quality:claude/haiku": "hypothesis", "owner-rating:claude/haiku": "hypothesis"}
    g = analysis.knowledge_graph(k)
    assert any(e["rel"] == "contradicts" for e in g["edges"])


def test_stale_lessons_become_outdated_and_owner_decisions_stick(make_kernel):
    k = make_kernel()
    replies(k, "haiku", 6, still=1)
    Pipeline(k).run()
    old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    with k.db.tx() as c:
        c.execute("UPDATE lessons SET last_seen = ?", (old,))
        c.execute("UPDATE outcomes SET created_at = ?", (old,))   # the evidence itself is old too
    assert Pipeline(k).learn()["outdated"] == 1
    [lesson] = learn.lessons(k)
    learn.decide_lesson(k, lesson["id"], "delete", by="t")
    assert learn.lessons(k, include_rejected=True) == [] and k.db.one("SELECT COUNT(*) FROM links")[0] == 0


def test_autonomy_tiers_pauses_and_the_emergency_stop(make_kernel):
    k = make_kernel()
    a = Autonomy(k)
    assert a.can("learn") and a.can("propose") and not a.state()["tiers"][5]["on"]   # tier 6 off by default
    with pytest.raises(AutonomyError):
        a.set_tier(6, True, by="dashboard")                                          # never from a browser
    a.set_pause("learning", True, by="t")
    assert not a.can("learn") and a.can("observe")
    replies(k, "haiku", 6, still=1)
    assert Pipeline(k).run().get("added") is None and learn.lessons(k) == []         # observed, not learned
    a.set_pause("learning", False, by="t")
    a.set_tier(2, False, by="t")
    assert not a.can("propose")                                                      # higher tiers need the lower ones
    a.set_tier(2, True, by="t")
    k.killswitch.engage(by="t", reason="test")
    assert Pipeline(k).run()["ran"] is False and not a.can("observe")
    with pytest.raises(analysis.LabError):
        analysis.Lab(k).start("replay", by="t", background=False)


def test_experiments_have_a_full_record_and_run_one_at_a_time(make_kernel):
    k = make_kernel()
    replies(k, "sonnet", 6)
    replies(k, "llama", 6, still=1, local=True)
    eid = analysis.Lab(k).start("replay", by="t", background=False)
    [e] = analysis.Lab(k).list()
    assert e["id"] == eid and e["state"] == "done"
    for field in ("objective", "hypothesis", "baseline", "criteria", "environment", "recommendation"):
        assert e[field], field
    assert "claude/sonnet" in e["recommendation"] and "local/llama" in e["recommendation"]
    with k.db.tx() as c:
        c.execute("UPDATE experiments SET state = 'running'")
    with pytest.raises(analysis.LabError):
        analysis.Lab(k).start("replay", by="t", background=False)
    with pytest.raises(analysis.LabError):
        analysis.Lab(k).start("rm -rf", by="t", background=False)                    # only the listed kinds exist


def test_tournament_never_assumes_the_bigger_model_wins(make_kernel):
    k = make_kernel()
    replies(k, "opus", 6, still=1)                       # the "big" model fails the check
    replies(k, "llama", 6, local=True, latency=1.5)      # the small local one passes
    Pipeline(k).run()
    t = analysis.tournament(k)
    assert t["recommendation"]["text"].startswith("local/llama")


def test_proposals_include_initiative_and_respect_the_propose_pause(make_kernel):
    from jarvis.proposals import Proposals
    k = make_kernel()
    replies(k, "haiku", 8, still=1)
    Pipeline(k).run()
    Autonomy(k).set_pause("initiative", True, by="t")
    assert Proposals(k).refresh()["skipped"] is True and Proposals(k).list() == []
    Autonomy(k).set_pause("initiative", False, by="t")
    Proposals(k).refresh()
    assert any(p["key"].startswith("lesson:reply-quality") for p in Proposals(k).list())


def test_self_inspection_reads_the_real_source():
    a = analysis.architecture()
    ids = {n["id"] for n in a["nodes"]}
    assert "jarvis.learn" in ids and "jarvis.core.db" in ids and "static/avatar3d.js" in ids
    assert "db.lessons" in ids and a["routes"] > 20
    assert {"from": "jarvis.learn.analysis", "to": "jarvis.learn", "rel": "imports"} in a["edges"]


def test_dashboard_endpoints(dash):
    d, *_ = dash
    d._evolution = d.evolution()   # as after the first background check (a field-name bug once hid behind its timing)
    status, _, body = call(d, "/api/learn")
    data = json.loads(body)
    assert status == 200 and set(data) >= {"summary", "autonomy", "lessons", "experiments", "kinds", "discoveries"}
    assert call(d, "/api/feedback", {"ref": "reply-1", "rating": 1, "model": "local/planner:7b"})[0] == 200
    assert call(d, "/api/feedback", {"ref": "reply-1", "rating": 5})[0] == 400
    assert call(d, "/api/autonomy", {"tier": 7, "on": True})[0] == 400                 # not from the dashboard
    assert call(d, "/api/autonomy", {"pause": "experiments", "paused": True})[0] == 200
    assert call(d, "/api/experiments", {"kind": "replay"})[0] == 409                    # paused
    for m in projections.MODULES:
        status, _, body = call(d, f"/api/projection/{m}")
        assert status == 200 and json.loads(body)["basis"], m
    assert call(d, "/api/projection/nope")[0] == 404
    assert call(d, "/api/learn", cookie=False)[0] in (401, 403)                       # same sign-in as everything else
    assert "learn" in json.loads(call(d, "/api/state")[2])


def test_autonomy_is_mac_only():
    from jarvis.remote import LOCAL_ONLY
    assert r"/api/autonomy" in LOCAL_ONLY


def test_projection_security_never_calls_pending_authorized(dash):
    d, *_ = dash
    s = json.loads(call(d, "/api/projection/security")[2])
    assert "Pending means NOT authorized" in s["basis"] and isinstance(s["pending"], list)
