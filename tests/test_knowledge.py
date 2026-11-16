"""Knowledge intelligence (Stage 4): one retrieval over what JARVIS already keeps, with the reason for every item,
its provenance, how sure it is, and private items that never leave the Mac. No copies, no model."""

import json
from datetime import datetime, timedelta, timezone

import pytest
from test_dashboard import call
from test_objectives import _mission

from jarvis import knowledge, objectives


@pytest.fixture
def k(make_kernel):
    return make_kernel()


def _ids(items):
    return {i["id"].split(":")[0] for i in items}


def test_related_project_knowledge_comes_back_together_with_reasons(k):
    k.memory.remember("The garden project needs the fence fixed before planting", by="user:dashboard")
    k.memory.remember("I like tea", by="user:dashboard")
    o = objectives.create(k, "Finish the garden project by June", by="user:dashboard")
    tid = _mission(k, "Order fence panels", "failed")
    objectives.link_mission(k, o["id"], tid, source="test")
    items = knowledge.context(k, "How is the garden project going?")
    assert {"memory", "objective", "task"} <= _ids(items)
    assert not any("tea" in i["text"] for i in items)
    by = {i["id"].split(":")[0]: i for i in items}
    assert by["memory"]["why"] == ["matched: garden, project"] and by["memory"]["status"] == "stated"
    assert by["memory"]["source"] == "you told JARVIS" and by["memory"]["since"]
    assert by["task"]["why"] == ["mission of an objective that matched"] and "failed" in by["task"]["text"]
    assert all({"id", "kind", "text", "status", "confidence", "source", "why", "private", "score"} <= set(i) for i in items)
    assert knowledge.context(k, "garden", exclude={by["memory"]["id"]})[0]["id"] != by["memory"]["id"]


def test_inferred_stays_inferred_and_old_unconfirmed_is_outdated(k):
    a = k.memory.remember("My dentist is Dr Patel", origin="observed", confidence=0.5, by="jarvis")
    it = knowledge.context(k, "who is my dentist")[0]
    assert it["status"] == "inferred" and it["source"] == "noticed in a conversation"
    assert "unconfirmed — may be wrong" in knowledge.context_text([it])
    later = datetime.now(timezone.utc) + timedelta(days=400)
    assert knowledge.context(k, "who is my dentist", now=later)[0]["status"] == "outdated"
    k.memory.confirm(a, by="user:dashboard")
    assert knowledge.context(k, "who is my dentist", now=later)[0]["status"] in ("stated", "confirmed")   # only you promote it


def test_asking_about_jarvis_itself_reads_its_own_docs(k, tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "ARCHITECTURE.md").write_text("# A\n\n## Permission engine\n\nEvery tool call is checked first.\n\n## Planner\n\nThe planner is slow on small models.\n")
    items = knowledge.context(k, "How could we improve JARVIS's planner?", repo=tmp_path)
    doc = next(i for i in items if i["kind"] == "doc")
    assert doc["text"].startswith("Planner:") and "about JARVIS itself" in doc["why"] and doc["source"].endswith("docs/ARCHITECTURE.md")
    assert not any(i["kind"] == "doc" for i in knowledge.context(k, "How is the planner?", repo=tmp_path))   # not about JARVIS


def test_related_shows_connections_and_conflicts(k):
    a = k.memory.remember("My dentist is Dr Patel", by="user:dashboard")
    b = k.memory.remember("My dentist is Dr Shah", by="user:dashboard")
    r = knowledge.related(k, f"memory:{a}")
    assert r["item"]["id"] == f"memory:{a}"
    other = next(x for x in r["related"] if x["id"] == f"memory:{b}")
    assert other["why"] == ["conflicts with this about my dentist"]
    with pytest.raises(KeyError):
        knowledge.related(k, "memory:nope")


def test_nothing_while_the_emergency_stop_is_on(k):
    k.memory.remember("The garden needs water", by="user:dashboard")
    k.killswitch.engage(reason="test", by="user:test")
    assert knowledge.context(k, "garden") == []


def test_chat_says_what_it_used_and_why(dash):
    d, _, _ = dash
    d.kernel.memory.remember("The garden project needs the fence fixed", by="user:dashboard")
    o = objectives.create(d.kernel, "Finish the garden project by June", by="user:dashboard")
    r = json.loads(call(d, "/api/chat", {"message": "How is the garden project going?", "history": []})[2])
    kinds = {u["kind"] for u in r["used"]}
    assert {"memory", "objective"} <= kinds and all(u["why"] for u in r["used"])
    assert any(u["id"] == f"objective:{o['id']}" for u in r["used"]) and r["private_held_back"] == 0
    quick = json.loads(call(d, "/api/chat", {"message": "How is the garden project going?", "history": [], "mode": "quick"})[2])
    assert {u["kind"] for u in quick["used"]} == {"memory"}          # Quick stays quick: memories only
