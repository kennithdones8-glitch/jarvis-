"""Memory screen: who said it and when, filters that only change the view, honest forgetting."""

from test_dashboard import call


def _js(d):
    return call(d, "/static/app.js")[2].decode()


def test_origin_is_spelled_out_and_inferred_memories_are_not_hidden(dash):
    d, _, _ = dash
    js = _js(d)
    assert '"Stated by you"' in js and '"Confirmed by you"' in js and '"Inferred by JARVIS"' in js
    assert "already used in answers" in js  # inferred memories are used before you confirm them; say so
    assert "confidence" not in js.split("async function loadMemory")[1].split("async function memAct")[0]  # no made-up scores


def test_filters_only_change_what_is_shown(dash):
    d, _, _ = dash
    js = _js(d)
    filt = js.split("function renderMemFilters(counts) {")[1].split("\n}\n")[0]
    assert "api(" not in filt and "call(" not in filt and "memAct(" not in filt
    html = call(d, "/")[2].decode()
    assert 'id="memfilters"' in html and "Claude only sees them if you allow it" in html


def test_memory_requests_are_unchanged(dash):
    d, _, _ = dash
    js = _js(d)
    for path in ("`/api/memory/${m.id}/confirm`", "`/api/memory/${m.id}/edit`", "`/api/memory/${m.id}/important`",
                 "`/api/memory/${m.id}/delete`"):
        assert js.count(path) == 1, path
    forget = js.split("async function forgetMatching()")[1].split("\n}\n")[0]
    assert 'api("/api/memory/forget", { query: ui.memQ })' in forget  # preview first: deletes nothing
    assert 'memAct("/api/memory/forget", { query: ui.memQ, confirm: true })' in forget  # only after you agree
    assert "deletions are applied again" in forget


def test_forget_without_confirm_really_is_only_a_preview(dash):
    d, _, _ = dash
    d.kernel.memory.remember("My gym locker code is 4512", origin="explicit", by="user:test")
    status, _, _ = call(d, "/api/memory/forget", {"query": "locker"})
    assert status == 200 and d.kernel.memory.counts()["memories"] == 1
