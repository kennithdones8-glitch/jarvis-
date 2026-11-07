"""Polish: keyboard shortcuts only move around; display settings stay on this device; the welcome is current."""

from test_dashboard import call


def _js(d):
    return call(d, "/static/app.js")[2].decode()


def _fn(js, name):
    return js.split(f"function {name}(")[1].split("\n}\n")[0]


def test_shortcuts_never_act(dash):
    d, _, _ = dash
    keys = _fn(_js(d), "onShortcut")
    for forbidden in ("api(", "call(", "act(", "/api/", "estop", "approve", "submit"):
        assert forbidden not in keys, forbidden
    assert "/^(INPUT|TEXTAREA|SELECT)$/" in keys and "e.metaKey || e.ctrlKey || e.altKey" in keys  # never while typing


def test_display_settings_are_local_to_the_device(dash):
    d, _, _ = dash
    js = _js(d)
    settings = _fn(js, "showDisplaySettings") + _fn(js, "loadDisplay") + _fn(js, "applyDisplay")
    assert "localStorage" in settings and "api(" not in settings and "call(" not in settings
    css = call(d, "/static/app.css")[2].decode()
    assert 'html[data-text="larger"] body { zoom: 1.25; }' in css and 'html[data-density="compact"] .panel' in css
    html = call(d, "/")[2].decode()
    assert 'id="displaybtn"' in html and 'id="keysbtn"' in html


def test_welcome_describes_the_current_dashboard(dash):
    d, _, _ = dash
    welcome = _fn(_js(d), "welcomeCard")
    assert "Command box" not in welcome  # the old layout
    for text in ("what matters now", "nothing changes until you approve it", "Emergency stop", "Workspace"):
        assert text in welcome, text


def test_activity_never_shows_raw_data_for_idea_events(dash):
    d, _, _ = dash
    from jarvis.proposals import Proposals
    Proposals(d.kernel).refresh()
    state = __import__("json").loads(call(d, "/api/state")[2])
    raw = [e for e in state["audit"] if e["event"] == "proposals.refreshed"]
    assert raw and raw[0]["detail"].lstrip().startswith("{")  # the server's fallback the page rewords
    js = _js(d)
    assert '"proposals.refreshed": () => "Checked its own record for improvement ideas"' in js
    assert "entries = entries.map(wordEvent);" in js and '"memory.important": (p) =>' in js


def test_ui3_meters_show_only_real_ratios_and_effects_respect_motion_settings():
    from pathlib import Path
    static = Path(__file__).resolve().parents[1] / "src" / "jarvis" / "server" / "static"
    js, css = (static / "app.js").read_text(), (static / "app.css").read_text()
    assert "if (ratio === null || ratio === undefined || !Number.isFinite(ratio)) return null;" in js     # unknown: no meter
    assert 'total ? online / total : null' in js and "m.budget.monthly_limit_usd ? (m.budget.spent_this_month_usd || 0) / m.budget.monthly_limit_usd : null" in js
    assert '.meter[data-fill="10"] { --f: 100%; }' in css and 'style="' not in js                           # no inline styles (CSP)
    assert ':root[data-fx="reduced"] .hud .panel > .ph::before, :root[data-fx="off"] .hud .panel > .ph::before { animation: none; display: none; }' in css
    assert "@media (prefers-reduced-motion: reduce) { .hud .panel > .ph::before { animation: none; display: none; } }" in css
    assert ".cc-sys[open] { grid-column: 1 / -1;" in css
