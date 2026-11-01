"""Command Center Home: built only from live state; nothing that was shown before is lost."""

from test_dashboard import call


def _js(d):
    return call(d, "/static/app.js")[2].decode()


def _fn(js, name):
    return js.split(f"function {name}(")[1].split("\n}\n")[0]


def test_home_sections_exist(dash):
    d, _, _ = dash
    html = call(d, "/")[2].decode()
    for marker in ('id="matters"', 'id="suggest"', 'id="recent"', 'id="recentlog"', 'id="summary"', 'href="#/systems">Details'):
        assert marker in html, marker
    assert "style=" not in html


def test_what_matters_comes_only_from_tasks_and_health(dash):
    d, _, _ = dash
    matters = _fn(_js(d), "renderMatters")
    assert "for (const t of d.tasks)" in matters and "d.health.items.filter((x) => !x.ok)" in matters
    for state in ('"blocked"', '"paused"', '"failed"'):
        assert f"t.state === {state}" in matters
    assert "d.approvals.length ?" in matters and "d.approvals.map" not in matters  # decisions have their own panel
    assert "api(" not in matters and "call(" not in matters  # reading only


def test_the_old_stats_row_numbers_still_shown(dash):
    d, _, _ = dash
    summary = _fn(_js(d), "renderSummary")
    for label in ("Health", "Models online", "Missions active", "Claude", "Spent this month"):
        assert f'ro("{label}"' in summary, label
    assert "fill($(\"#summary\")" in summary  # optional rows are left out, never printed as "null"


def test_suggestions_are_the_capability_aware_help_examples(dash):
    d, _, _ = dash
    sug = _fn(_js(d), "renderSuggestions")
    assert "helpExamples(d)" in sug and ".slice(0, 3)" in sug and "saveDraft()" in sug
    assert "api(" not in sug  # putting a suggestion in the box never sends it


def test_recent_activity_and_full_log_kept(dash):
    d, _, _ = dash
    js = _js(d)
    assert '$("#recent").replaceChildren' in _fn(js, "renderActivity")
    assert '$("#recentlog").addEventListener("click", () => $("#logdlg").showModal())' in js
