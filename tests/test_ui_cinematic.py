"""Cinematic mode: presentation only; Emergency stop and anything that needs you stay visible."""

from test_dashboard import call


def _js(d):
    return call(d, "/static/app.js")[2].decode()


def test_switching_sends_nothing_and_changes_nothing(dash):
    d, _, _ = dash
    js = _js(d)
    for name in ("setCinematic(on)", "renderCineStrip(d)"):
        body = js.split(f"function {name} {{")[1].split("\n}\n")[0]
        assert "api(" not in body and "call(" not in body and "act(" not in body, name


def test_emergency_stop_and_exit_stay_in_the_top_bar(dash):
    d, _, _ = dash
    html = call(d, "/")[2].decode()
    header = html.split("<header")[1].split("</header>")[0]
    assert 'id="estop"' in header and 'id="cineexit"' in header and 'id="cinebtn"' in header
    css = call(d, "/static/app.css")[2].decode()
    cine = css.split("Stage 7: cinematic mode")[1]
    assert "#estop" not in cine and "header" not in cine.split("{")[0]  # nothing in cinematic mode hides the top bar


def test_the_strip_shows_everything_that_needs_you(dash):
    d, _, _ = dash
    strip = _js(d).split("function renderCineStrip(d) {")[1].split("\n}\n")[0]
    for source in ("d.approvals.length", 't.state === "blocked"', 't.state === "failed"', "d.health.items.filter((i) => !i.ok)"):
        assert source in strip, source
