"""Memories that disagree are found with plain rules (no model), shown for you to settle, and settling deletes the
one you don't keep (a deletion you make, behind the same Face ID / Touch ID as deleting a memory)."""

import json
import re

from test_dashboard import call

from jarvis.memory.conflicts import claim, find


def test_claims_are_read_from_common_shapes():
    assert claim("My dentist is Dr Patel.") == ("my dentist", "dr patel")
    assert claim("Dr Shah is my dentist") == ("my dentist", "dr shah")
    assert claim("I live in Leeds") == ("i live in", "leeds")
    assert claim("I'm 34 years old") == ("my age", "34")
    assert claim("I like chess") is None and claim("Sam is my friend") is None   # friends aren't unique


def test_disagreements_pair_newest_with_older_and_agreement_is_not_a_conflict():
    mems = [{"id": "m1", "text": "My dentist is Dr Patel", "created_at": "2026-01-01"},
            {"id": "m2", "text": "Dr Shah is my dentist", "created_at": "2026-03-01"},
            {"id": "m3", "text": "I live in Leeds", "created_at": "2026-01-01"},
            {"id": "m4", "text": "I live in Leeds.", "created_at": "2026-02-01"}]
    pairs = find(mems)
    assert len(pairs) == 1 and pairs[0]["subject"] == "my dentist"
    assert pairs[0]["a"]["id"] == "m2" and pairs[0]["b"]["id"] == "m1"


def test_memory_page_lists_conflicts_and_settling_deletes_the_other(dash):
    d, *_ = dash
    k = d.kernel
    a = k.memory.remember("My dentist is Dr Patel", by="user:dashboard")
    b = k.memory.remember("My dentist is Dr Shah", by="user:dashboard")
    data = json.loads(call(d, "/api/memory")[2])
    assert len(data["conflicts"]) == 1 and {data["conflicts"][0]["a"]["id"], data["conflicts"][0]["b"]["id"]} == {a, b}
    assert call(d, "/api/memory/conflicts/resolve", {"keep": a, "drop": b})[0] == 200
    assert [m["id"] for m in k.memory.list()] == [a]
    assert json.loads(call(d, "/api/memory")[2])["conflicts"] == []
    assert any(e["event"] == "memory.conflict_resolved" for e in k.audit.entries(limit=20))


def test_settling_needs_the_same_step_up_as_deleting():
    from jarvis.remote import STEP_UP
    assert any(re.fullmatch(p, "/api/memory/conflicts/resolve") for p in STEP_UP)


def test_the_feed_asks_about_a_conflict(make_kernel):
    from jarvis import initiative
    k = make_kernel()
    k.memory.remember("I work at Acme", by="user:cli")
    k.memory.remember("I work at Globex", by="user:cli")
    assert any(i["key"].startswith("memory-conflict:") for i in initiative.candidates(k))
