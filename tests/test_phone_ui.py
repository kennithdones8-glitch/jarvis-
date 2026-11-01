"""Phone layout: sections with a tab bar, the briefing first, and a pairing guide."""

import re

from test_dashboard import call


def test_tab_bar_and_sections(dash):
    d, _, _ = dash
    html = call(d, "/")[2].decode()
    assert '<body data-tab="chat">' in html
    tabs = re.findall(r'data-tab="(\w+)"', html.split('id="tabbar"')[1].split("</nav>")[0])
    assert tabs == ["chat", "missions", "decisions", "memory", "status"]
    assert 'id="logbtn2"' in html.split('id="moremenu"')[1].split("</details>")[0]  # the log, also on phones
    assert 'id="badge-decisions"' in html and 'id="estop"' in html  # the emergency stop stays outside every menu
    css = call(d, "/static/app.css")[2].decode()
    phone = css.split("phone: app-style sections")[1]
    for section in ("missions-panel", "decision-panel", "memory-panel", "systems-panel"):
        assert section in phone
    assert "textarea { font-size: 16px; }" in phone  # smaller and iPhone zooms in when you tap the box
    assert "prefers-reduced-motion: reduce" in css.split("cinematic touches")[1]
    js = call(d, "/static/app.js")[2].decode()
    assert "showBriefing(true)" in js and "function setSection" in js


def test_phone_setup_guide(dash):
    d, _, _ = dash
    status, headers, body = call(d, "/phone-setup")
    page = body.decode()
    assert status == 200 and "uv run jarvis remote enable" in page and "Add to Home Screen" in page
    assert "<script" not in page and "style=" not in page
    assert call(d, "/phone-setup", cookie=False)[0] in (401, 403)
    for cmd in re.findall(r"<code>uv run jarvis ([a-z ]+?)(?: ID)?</code>", page):  # every command it names exists
        from jarvis.cli import main
        import pytest
        with pytest.raises(SystemExit) as e:
            main([*cmd.split(), "--help"])
        assert e.value.code == 0, cmd
    assert "/phone-setup" in call(d, "/static/app.js")[2].decode()
