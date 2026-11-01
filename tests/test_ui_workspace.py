"""Workspace: context beside the conversation, built only from the latest reply and live state."""

from test_dashboard import call


def _ctx(d):
    js = call(d, "/static/app.js")[2].decode()
    return js.split("function renderContext(d) {")[1].split("\n}\n")[0]


def test_context_only_reads_what_already_exists(dash):
    d, _, _ = dash
    ctx = _ctx(d)
    assert "api(" not in ctx and "call(" not in ctx and "act(" not in ctx
    for source in ("last.sources", "last.checked", "last.meta", "d.tasks.find", "MODES[ui.mode][1]"):
        assert source in ctx, source
    assert "x.verified" in ctx and "not seen by the research tools" in ctx  # unverified sources are labelled, not hidden


def test_no_panels_for_things_jarvis_cannot_do(dash):
    d, _, _ = dash
    ctx = _ctx(d).lower()
    for unsupported in ("diff", "repository", "file browser", "terminal", "%"):
        assert unsupported not in ctx, unsupported


def test_workspace_is_reachable_on_mac_and_phone(dash):
    d, _, _ = dash
    html = call(d, "/")[2].decode()
    assert 'href="#/workspace" data-view="workspace"' in html  # sidebar
    assert 'href="#/workspace" title=' in html.split('id="moremenu"')[1].split("</details>")[0]  # More menu (phones)
    assert 'id="estop"' in html.split("<header")[1].split("</header>")[0]
