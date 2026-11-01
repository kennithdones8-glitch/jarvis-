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
