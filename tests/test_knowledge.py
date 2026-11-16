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


# ---- knowledge intelligence: conflicts, duplicates, outdated, gaps, patterns ---------------------------------------
def test_insights_find_what_needs_attention_and_change_nothing(k):
    from jarvis.memory.conflicts import stance
    assert stance("I like coffee") == ("coffee", True) and stance("I don't like coffee") == ("coffee", False)
    assert stance("I hate coffee") == ("coffee", False) and stance("The coffee is hot") is None
    k.memory.remember("I like coffee", by="user:dashboard")
    k.memory.remember("I don't like coffee", by="user:dashboard")
    k.memory.remember("The boiler was serviced in March", by="user:dashboard")
    k.memory.remember("In March the boiler was serviced", by="user:dashboard")
    old = k.memory.remember("My gym is on Park Road", origin="observed", confidence=0.5, by="jarvis")
    due = k.memory.remember("My passport expires in 2027", by="user:dashboard")
    with k.db.tx() as c:
        c.execute("UPDATE memories SET review_after = '2020-01-01' WHERE id = ?", (due,))
    o = objectives.create(k, "Sort the garage", by="user:dashboard", deadline="2020-01-01")
    for _ in range(3):
        _mission(k, "Summarise my meeting notes")
    before = k.db.one("SELECT COUNT(*) FROM memories")[0]
    ins = knowledge.insights(k)
    assert [c["title"] for c in ins["conflicts"]] == ["Two memories disagree about whether you like coffee"]
    assert len(ins["duplicates"]) == 1 and len(ins["duplicates"][0]["items"]) == 2
    titles = {x["title"] for x in ins["outdated"]}
    assert {"Due for a check", "Probably replaced by a newer memory"} <= titles
    assert [x["items"][0]["id"] for x in ins["unconfirmed"]] == [f"memory:{old}"]
    assert {m["title"] for m in ins["missing"] if m["items"][0]["id"] == f"objective:{o['id']}"} == {
        "No “done means” yet", "No mission has been started", "Deadline has passed"}
    assert ins["patterns"][0]["title"].startswith("Asked for 3 times")
    assert k.db.one("SELECT COUNT(*) FROM memories")[0] == before          # findings only: nothing settled for you
    later = datetime.now(timezone.utc) + timedelta(days=400)
    assert any(x["title"].startswith("Never confirmed") for x in knowledge.insights(k, now=later)["outdated"])


# ---- privacy: private memories, verified forgetting, export --------------------------------------------------------
def test_private_memories_are_left_out_by_default_and_only_you_set_them(k):
    a = k.memory.remember("My bank PIN hint is the year we met", by="user:dashboard")
    with pytest.raises(PermissionError):
        k.memory.set_privacy(a, True, by="jarvis")
    k.memory.set_privacy(a, True, by="user:dashboard")
    assert k.memory.recall("bank PIN hint") == []                                  # the safe default for every caller
    assert [m["id"] for m in k.memory.recall("bank PIN hint", include_private=True)] == [a]
    it = knowledge.context(k, "bank PIN hint")[0]
    assert it["private"] is True
    assert any(e["event"] == "memory.privacy" for e in k.audit.entries(limit=20))


def test_a_private_memory_never_reaches_a_cloud_answer(dash, monkeypatch):
    d, _, _ = dash
    a = d.kernel.memory.remember("My bank PIN hint is the year we met", by="user:dashboard")
    assert call(d, f"/api/memory/{a}/privacy", {"private": True})[0] == 200
    seen = []
    old = d.kernel.models.complete

    def spy(need, request, **kw):
        seen.append(request)
        return old(need, request, **kw)
    d.kernel.models.complete = spy
    r = json.loads(call(d, "/api/chat", {"message": "What is my bank PIN hint?", "history": []})[2])
    mine = [m for req in seen for m in req.messages if "year we met" in m.content]
    assert mine and all(m.local_only for m in mine) and r["private_held_back"] == 0     # stayed here: used, locally only
    seen.clear()
    monkeypatch.setattr(d.kernel.models, "chat_stays_local", lambda *a, **kw: False)    # an answer that would leave
    r = json.loads(call(d, "/api/chat", {"message": "What is my bank PIN hint?", "history": []})[2])
    assert not [m for req in seen for m in req.messages if "year we met" in m.content]
    assert r["private_held_back"] == 1 and not any("year we met" in u["text"] for u in r["used"])


def test_privacy_change_needs_face_id_or_touch_id_and_review_dates_are_checked(dash):
    import re
    d, _, _ = dash
    from jarvis.remote.passkeys import STEP_UP
    assert any(re.fullmatch(p, "/api/memory/mem-1/privacy") for p in STEP_UP)
    js = call(d, "/static/app.js")[2].decode()
    assert "(delete|edit|privacy)$/" in js
    a = d.kernel.memory.remember("My passport expires in 2027", by="user:dashboard")
    assert call(d, f"/api/memory/{a}/review", {"date": "2027-01-01"})[0] == 200
    assert call(d, f"/api/memory/{a}/review", {"date": "2027-13-45"})[0] == 400
    assert call(d, f"/api/memory/{a}/review", {"date": "soon"})[0] == 400
    assert call(d, f"/api/memory/{a}/privacy", {"private": "yes"})[0] == 400
    assert d.kernel.memory.get(a)["review_after"] == "2027-01-01"


def test_forget_is_verified_across_every_store_including_the_project_board(dash):
    d, _, root = dash
    k = d.kernel
    from jarvis import files_index
    k.memory.remember("The Lisbon trip is in August", by="user:dashboard")
    objectives.create(k, "Plan the Lisbon trip", by="user:dashboard")
    _mission(k, "Book Lisbon flights")
    p = k.board.open("Lisbon trip", "Planning", by="user:dashboard")
    k.board.save(p["id"], "Packing list", "Sun cream, passport", by="user:dashboard")
    other = k.board.open("Garden", "", by="user:dashboard")
    k.board.save(other["id"], "Ideas", "A bench like the one in Lisbon", by="user:dashboard")
    k.board.save(other["id"], "Plants", "Lavender", by="user:dashboard")
    (root / "lisbon.md").write_text("Lisbon hotel booking reference ABC123")
    call(d, "/api/settings/files", {"on": True})
    d.files_tick()
    preview = json.loads(call(d, "/api/memory/forget", {"query": "Lisbon"})[2])
    assert preview["board"] == 3 and preview["indexed_files"] == 1 and "verified" not in preview   # project + its item + one mention
    out = json.loads(call(d, "/api/memory/forget", {"query": "Lisbon", "confirm": True})[2])
    v = out["verified"]
    assert v["clean"] is True and all(v[x] == 0 for x in ("memories", "records", "tasks", "board", "objectives", "indexed_files"))
    assert [i["title"] for pr in k.board.overview() for i in pr["items"]] == ["Plants"]          # unrelated work is kept
    assert files_index.search(k, "Lisbon") == [] and knowledge.context(k, "Lisbon trip") == []
    assert any(e["event"] == "memory.forget_verified" and e["payload"]["clean"] for e in k.audit.entries(limit=60))


def test_export_is_readable_and_complete(k):
    k.memory.remember("I like tea", by="user:dashboard")
    objectives.create(k, "Drink more water", by="user:dashboard")
    ex = k.memory.export()
    assert {"memories", "records", "objectives", "lessons", "links", "exported_at"} <= set(ex)
    assert ex["memories"][0]["privacy"] == "normal" and ex["objectives"][0]["outcome"] == "Drink more water"


# ---- the Knowledge view's routes ------------------------------------------------------------------------------------
def test_knowledge_routes_and_a_phone_never_sees_private_items(dash):
    d, _, _ = dash
    k = d.kernel
    a = k.memory.remember("The garden project needs the fence fixed", by="user:dashboard")
    b = k.memory.remember("My garden safe code hint is tulips", by="user:dashboard")
    k.memory.set_privacy(b, True, by="user:dashboard")
    r = json.loads(call(d, "/api/knowledge?q=garden")[2])
    assert {f"memory:{a}", f"memory:{b}"} <= {i["id"] for i in r["items"]} and r["private_hidden"] == 0
    item = json.loads(call(d, f"/api/knowledge/item?id=memory:{a}")[2])
    assert item["item"]["id"] == f"memory:{a}" and call(d, "/api/knowledge/item?id=memory:nope")[0] == 404
    assert "conflicts" in json.loads(call(d, "/api/knowledge/insights")[2])["insights"]
    assert call(d, "/api/knowledge?q=garden", cookie=False)[0] == 401
    # the same handlers, asked as a paired phone
    import io

    class H:
        def __init__(self):
            self.out, self.status = io.BytesIO(), None
            self.wfile, self.headers = self.out, {}

        def send_response(self, s):
            self.status = s

        def send_header(self, *a):
            pass

        def end_headers(self):
            pass
    from urllib.parse import urlsplit
    h = H()
    d._get(h, urlsplit("/api/knowledge?q=garden"), device={"id": "dev-1", "name": "iPhone"})
    phone = json.loads(h.out.getvalue())
    assert [i["id"] for i in phone["items"] if i["kind"] == "memory"] == [f"memory:{a}"] and phone["private_hidden"] == 1
    h = H()
    d._get(h, urlsplit("/api/memory?q=garden"), device={"id": "dev-1", "name": "iPhone"})
    mem = json.loads(h.out.getvalue())
    assert [m["id"] for m in mem["memories"]] == [a] and mem["private_hidden"] == 1


def test_the_knowledge_view_draws_only_what_the_api_returned(dash):
    d, _, _ = dash
    status, headers, body = call(d, "/static/knowledge.js")
    js = body.decode()
    assert status == 200 and headers["Content-Type"].startswith("text/javascript")
    assert "innerHTML" not in js and "fetch(" not in js and "Math.random" not in js       # page helpers only, nothing invented
    html = call(d, "/")[2].decode()
    assert 'id="memknow"' in html and 'id="meminsights"' in html and '/static/knowledge.js' in html
