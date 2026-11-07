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


def test_ui_meters_show_only_real_ratios_and_the_glass_respects_effects_settings():
    from pathlib import Path
    static = Path(__file__).resolve().parents[1] / "src" / "jarvis" / "server" / "static"
    js, css = (static / "app.js").read_text(), (static / "app.css").read_text()
    assert "if (ratio === null || ratio === undefined || !Number.isFinite(ratio)) return null;" in js     # unknown: no meter
    assert 'total ? online / total : null' in js and "m.budget.monthly_limit_usd ? (m.budget.spent_this_month_usd || 0) / m.budget.monthly_limit_usd : null" in js
    assert '.meter[data-fill="10"] { --f: 100%; }' in css and 'style="' not in js                           # no inline styles (CSP)
    # UI 5 (owner's spec): rounded frosted panels, no blur when effects are low/off, bar docked at the bottom
    assert "border-radius: 18px; clip-path: none;" in css and "backdrop-filter: blur(18px)" in css
    assert ':root[data-fx="reduced"] .panel, :root[data-fx="off"] .panel { backdrop-filter: none;' in css
    assert ".cmdbar { position: sticky; bottom: 14px;" in css and ".hud > .center > .matters { order: -1; }" in css
    assert ".cc-sys[open] { grid-column: 1 / -1;" in css


def test_hud_module_gauges_are_real_and_depth_never_breaks_the_focus_view():
    from pathlib import Path
    static = Path(__file__).resolve().parents[1] / "src" / "jarvis" / "server" / "static"
    js, css = (static / "app.js").read_text(), (static / "app.css").read_text()
    assert ".hud { perspective" not in css                                       # would re-anchor the fixed focus projection
    assert "transform: perspective(1800px) rotateY(calc(-8deg" in css
    assert ':root[data-fx="reduced"] :is(.g-spin, .g-spin-rev), :root[data-fx="off"] :is(.g-spin, .g-spin-rev) { animation: none; }' in css
    assert 'document.documentElement.dataset.fx !== "full" || matchMedia("(prefers-reduced-motion: reduce)").matches' in js   # parallax: Normal only
    times = js.split("function responseTimes(d) {")[1].split("\n}\n")[0]
    assert 'e.event === "egress.received"' in times and 'e.event === "model.local_call"' in times   # real calls from the audit log


def test_hud_activity_missions_and_decisions_show_only_real_values():
    from pathlib import Path
    static = Path(__file__).resolve().parents[1] / "src" / "jarvis" / "server" / "static"
    js, css = (static / "app.js").read_text(), (static / "app.css").read_text()
    pulse = js.split("function activityPulse(entries) {")[1].split("\n}\n")[0]
    assert "Date.parse(e.ts)" in pulse and "bins[11 - Math.floor(age)]++" in pulse          # real events per 5 minutes
    ring = js.split("function stepRing(t) {")[1].split("\n}\n")[0]
    assert 'x.state === "done" || x.state === "skipped"' in ring and "if (!n) return null;" in ring   # real steps, no fake progress
    assert 'a.created_at ? h("span", { class: "d-wait" }, `waiting ${since(a.created_at)}`) : null' in js   # no invented deadline
    assert ':root[data-fx="off"] :is(#recent li.new, .sys-chip .sc-dot::after, .sys-chip::before, .decision .d-ring)' in css
