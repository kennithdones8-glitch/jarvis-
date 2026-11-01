"""Dashboard shell: sections, navigation on every page, Emergency Stop everywhere, drafts kept."""

import re

from test_dashboard import call

VIEWS = ["home", "missions", "decisions", "memory", "systems", "intelligence"]


def test_sidebar_sections_and_status(dash):
    d, _, _ = dash
    html = call(d, "/")[2].decode()
    nav = html.split('id="sidenav"')[1].split("</nav>")[0]
    assert re.findall(r'href="#/(\w+)" data-view="\w+"', nav) == VIEWS
    assert all(f'href="#/{v}"' in nav for v in VIEWS) and 'id="badge-decisions"' in nav and 'id="navcollapse"' in nav
    assert 'id="statuspill"' in html and 'role="status"' in html.split('id="statuspill"')[1][:120]
    assert 'id="estop"' in html.split("<header")[1].split("</header>")[0]  # in the top bar, never inside a menu
    assert "style=" not in html  # CSP: no inline styles


def test_status_pill_comes_from_the_same_live_situation_as_the_headline(dash):
    d, _, _ = dash
    js = call(d, "/static/app.js")[2].decode()
    head = js.split("function renderHead(d)")[1].split("\n}\n")[0]
    assert "const s = situation(d);" in head and 'pill.dataset.state = s.core;' in head


def test_sections_only_change_what_is_shown(dash):
    d, _, _ = dash
    js = call(d, "/static/app.js")[2].decode()
    body = js.split("function setView(view)")[1].split("\n}\n")[0]
    assert "api(" not in body and "call(" not in body and "act(" not in body  # no requests: nothing paused or changed
    assert 'const VIEWS = ["home", "missions", "decisions", "memory", "systems", "intelligence"];' in js


def test_drafts_survive_and_are_cleared_when_sent(dash):
    d, _, _ = dash
    js = call(d, "/static/app.js")[2].decode()
    assert "sessionStorage.setItem(DRAFT_KEY" in js and 'addEventListener("input", saveDraft)' in js
    submit = js.split("async function submitCommand")[1].split("\nasync function ")[0]
    assert submit.count("clearDraft()") == 2  # both ways the box is emptied after sending


def test_every_page_has_navigation_and_a_working_emergency_stop(dash):
    d, _, _ = dash
    for page, script in (("/bench", "bench"), ("/trust", "trust"), ("/proposals", "proposals")):
        html = call(d, page)[2].decode()
        assert 'id="sidenav"' in html and 'aria-current="page"' in html and 'id="estop"' in html, page
        assert "style=" not in html
        js = call(d, f"/static/{script}.js")[2].decode()
        assert 'fetch("/api/stop", { method: "POST"' in js and '"X-Requested-By": "jarvis"' in js, script
    # and it really stops, with the same request (no Face ID or Touch ID needed to stop)
    status, _, _ = call(d, "/api/stop", {"reason": "stopped from the dashboard"})
    assert status == 200 and d.kernel.killswitch.engaged() is True
