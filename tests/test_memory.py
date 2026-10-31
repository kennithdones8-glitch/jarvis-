import json

import pytest

from model_servers import start_ollama

from jarvis.memory import MemorySettings, MemoryStore, normalise
from jarvis.models.types import Category
from jarvis.server import Dashboard
from jarvis.tools import default_registry

CFG = """[memory]
exclude_topics = ["medical"]
[providers.ollama]
kind = "ollama"
enabled = true
host = "{url}"
[[providers.ollama.models]]
id = "llama:3b"
capabilities = ["chat", "extract", "json", "classify", "summarize"]
context_tokens = 16384
quality = 2
speed = 4
"""


@pytest.fixture
def mk(make_kernel, tmp_path):
    srv = start_ollama(installed=["llama:3b"])
    script = {"extract": {"memories": []}, "chat_requests": []}

    def reply(body):
        system = body["messages"][0]["content"]
        if "personal memory" in system:
            return json.dumps(script["extract"])
        script["chat_requests"].append(body["messages"])
        return "Noted."
    srv.reply = reply
    (tmp_path / "jarvis.toml").write_text(CFG.format(url=srv.url))
    k = make_kernel(registry=default_registry(tmp_path / "home"), config_path=tmp_path / "jarvis.toml")
    yield k, script
    srv.stop()


def test_explicit_remember_search_and_provenance(mk):
    k, _ = mk
    m = k.memory
    mid = m.remember("I prefer email over phone calls", by="user:test")
    got = m.get(mid)
    assert got["origin"] == "explicit" and got["confidence"] == 1.0 and got["verified_at"]
    assert [x["id"] for x in m.search("how should I contact by email?")] == [mid]
    assert m.remember("i prefer EMAIL over phone calls!", by="user:test") == mid      # no duplicates


def test_remember_that_in_chat_is_explicit_and_recalled_later(mk):
    k, script = mk
    d = Dashboard(k, port=0, token="t")
    try:
        r = d.chat("Remember that my sister's birthday is on 14 March", [], session="s1")
        assert r["text"] == "Noted."
        [mem] = k.memory.list()
        assert mem["text"] == "my sister's birthday is on 14 March" and mem["origin"] == "explicit"
        assert mem["source_record"]                                       # linked to the original record
        r2 = d.chat("When is my sister's birthday?", [], session="s1")
        assert r2["memories_used"] == 1
        sent = script["chat_requests"][-1]
        memory_msg = next(m for m in sent if m["role"] == "system" and "What you remember" in m["content"])
        assert "14 March" in memory_msg["content"] and "confirmed" in memory_msg["content"]
        assert len(k.memory.search_records("birthday")) >= 2               # originals archived
    finally:
        d.shutdown()


def test_observed_facts_are_unconfirmed_until_confirmed(mk):
    k, script = mk
    script["extract"] = {"memories": [{"text": "Is training for a half marathon in May", "kind": "project"}]}
    k.memory.learn_from("s", "I'm training for a half marathon in May and need a plan", "Sure.", background=False)
    [mem] = k.memory.list()
    assert mem["origin"] == "observed" and mem["confidence"] < 1 and mem["verified_at"] is None
    k.memory.confirm(mem["id"], by="user:test")
    assert k.memory.get(mem["id"])["origin"] == "explicit"


def test_deleted_memory_is_not_relearned_but_can_be_said_again(mk):
    k, script = mk
    script["extract"] = {"memories": [{"text": "Owns a red bicycle", "kind": "fact"}]}
    k.memory.learn_from("s", "I ride my red bicycle to work every single day", "Nice.", background=False)
    [mem] = k.memory.list()
    k.memory.delete(mem["id"], by="user:test")
    k.memory.learn_from("s", "My red bicycle has a flat tyre again today sadly", "Oh no.", background=False)
    assert k.memory.list() == []                                          # tombstone blocks re-learning
    k.memory.remember("Owns a red bicycle", by="user:test")               # but you can tell it again yourself
    assert len(k.memory.list()) == 1


def test_edit_tombstones_wrong_version(mk):
    k, script = mk
    mid = k.memory.remember("Lives in Leeds", by="user:test")
    k.memory.edit(mid, "Lives in York", by="user:test")
    script["extract"] = {"memories": [{"text": "Lives in Leeds", "kind": "fact"}]}
    k.memory.learn_from("s", "Back when I lived in Leeds the trains were awful", "Ha.", background=False)
    assert [m["text"] for m in k.memory.list()] == ["Lives in York"]


def test_deleting_a_record_deletes_derived_memories(mk):
    k, script = mk
    script["extract"] = {"memories": [{"text": "Allergic to peanuts", "kind": "fact"}]}
    k.memory.learn_from("s", "Just so you know I am allergic to peanuts", "Got it.", background=False)
    rec = k.memory.search_records("peanuts")[0]
    assert k.memory.delete_record(rec["id"], by="user:test") == 1
    assert k.memory.list() == [] and k.memory.search("peanuts") == []


def test_forget_previews_then_deletes_everything_matching(mk):
    k, _ = mk
    k.memory.remember("Planning a trip to Japan in April", by="user:test")
    k.memory.add_record("s", "user", "Find me hotels in Japan near Kyoto")
    preview = k.memory.forget("Japan", by="user:test")
    assert len(preview["memories"]) == 1 and len(preview["records"]) == 1 and k.memory.counts()["memories"] == 1
    k.memory.forget("Japan", by="user:test", dry_run=False)
    assert k.memory.counts() == {"memories": 0, "unconfirmed": 0, "records": 0}
    assert k.memory.search("Japan") == [] and k.memory.search_records("Kyoto") == []


def test_excluded_topics_never_stored(mk):
    k, _ = mk
    assert k.memory.remember("My medical results came back fine", by="user:test") is None
    assert k.memory.add_record("s", "user", "about my medical appointment") is None
    assert k.memory.counts()["records"] == 0


def test_audit_holds_no_memory_text(mk):
    k, _ = mk
    secretish = "Keeps the spare key under the blue flowerpot"
    mid = k.memory.remember(secretish, by="user:test")
    k.memory.delete(mid, by="user:test")
    assert "flowerpot" not in str(k.audit.entries(limit=500))
    assert k.audit.verify().ok


def test_memory_context_is_private_category():
    msg = MemoryStore.context_message([{"text": "Likes tea", "origin": "observed", "created_at": "2026-10-31T00:00"}])
    assert msg.category is Category.MEMORY and "unconfirmed" in msg.content
    assert MemoryStore.context_message([]) is None


def test_disabled_memory_stores_nothing(mk):
    k, _ = mk
    m = MemoryStore(k.db, k.audit, MemorySettings(enabled=False))
    assert m.remember("x y z", by="user:test") is None and m.add_record("s", "user", "hi there") is None
    assert m.recall("anything") == []


def test_normalise():
    assert normalise("  Prefers EMAIL, over calls! ") == "prefers email over calls"
