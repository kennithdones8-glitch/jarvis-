"""Benchmark history on the dashboard, and failures at a glance in reports."""

import json

from test_bench import _run
from test_dashboard import call

from jarvis.bench.runner import failures_at_a_glance, report, summary_part


def _seed(home, extra_fail=None):
    out = home / "bench-results"
    _run(out, "20261101-013403-local", {"a": "ppf", "b": "fff"}, started="2026-11-01T01:34:03-04:00")
    after = _run(out, "20261101-013114-local", {"a": "ppp", "b": "ppf"}, started="2026-11-01T01:31:14-05:00")
    data = json.loads((after / "results.json").read_text())
    for r in data["results"]:  # give the failure some detail
        r.update(category="planning", title=r["id"], seconds=12.0, passed=r["status"] == "pass")
        if r["status"] == "fail":
            r.update(checks=[{"type": "contains_all", "passed": False, "detail": "missing: ['standup']"}],
                     checked=["Calendar, Mon 02 Nov–Tue 03 Nov"], lookup_notes=[], answer="I don't have access." * 100,
                     approvals=[{"tool": "apps", "action": "open", "summary": "Open Mail", "approved": False}])
    (after / "results.json").write_text(json.dumps(data))
    (out / "not-a-run").mkdir()
    (out / "not-a-run" / "results.json").write_text("{}")
    return out


def test_runs_detail_and_compare(dash):
    d, _, _ = dash
    _seed(d.kernel.home)
    status, _, body = call(d, "/api/bench")
    runs = json.loads(body)["runs"]
    assert status == 200 and [r["run_id"] for r in runs] == ["20261101-013114-local", "20261101-013403-local"]
    assert runs[0]["passed"] == 5 and runs[0]["scored"] == 6 and runs[0]["categories"]["planning"]["scored"] == 6

    status, _, body = call(d, "/api/bench/20261101-013114-local")
    det = json.loads(body)
    b = next(t for t in det["tasks"] if t["id"] == "b")
    assert status == 200 and b["passed"] == 2 and b["failure"]["checked"] == ["Calendar, Mon 02 Nov–Tue 03 Nov"]
    assert b["failure"]["approvals"] == [{"call": "apps.open", "summary": "Open Mail", "approved": False}]
    assert len(b["failure"]["answer"]) == 1200

    status, _, body = call(d, "/api/bench/compare")  # the two latest by real start time, across the clock change
    c = json.loads(body)
    assert c["before"]["run_id"] == "20261101-013403-local" and c["after"]["run_id"] == "20261101-013114-local"
    assert c["fixed"] == ["b"] and c["net"] == 1 and c["merge"] is False


def test_only_run_folders_can_be_opened(dash):
    d, _, _ = dash
    _seed(d.kernel.home)
    for path in ("/api/bench/not-a-run", "/api/bench/..%2F..%2Fjarvis.db", "/api/bench/20991231-000000-local",
                 "/api/bench/compare?before=../x&after=20261101-013114-local"):
        assert call(d, path)[0] == 404, path


def test_page_needs_the_session_and_obeys_the_csp(dash):
    d, _, _ = dash
    assert call(d, "/api/bench", cookie=False)[0] in (401, 403)
    status, headers, body = call(d, "/bench")
    assert status == 200 and b'src="/static/bench.js"' in body and "script-src 'self'" in headers["Content-Security-Policy"]
    assert b"style=" not in body
    for asset in ("/static/bench.js", "/static/bench.css"):
        assert call(d, asset)[0] == 200
    js = call(d, "/static/bench.js")[2].decode()
    assert "innerHTML" not in js and "style:" not in js  # text only via DOM nodes; no inline style attributes
    assert b'href="/bench"' in call(d, "/")[2]


def test_no_runs_yet(dash):
    d, _, _ = dash
    assert json.loads(call(d, "/api/bench")[2]) == {"runs": []}
    assert call(d, "/api/bench/compare")[0] == 404


def test_failures_at_a_glance_in_the_report(tmp_path):
    out = _seed(tmp_path)
    data = json.loads((out / "20261101-013114-local" / "results.json").read_text())
    data["meta"].update(jarvis_version="x", platform="Darwin", models="local", repeat=3)
    text = report(data["meta"], data["results"])
    head = summary_part(text)
    assert "## Failures at a glance" in head and "### b · passed 2 of 3" in head
    assert "- ✗ contains_all: missing: ['standup']" in head and "apps.open “Open Mail” → rejected" in head
    assert "looked up: Calendar, Mon 02 Nov–Tue 03 Nov" in head and "## a (run 1)" not in head
    assert "## a (run 1)" in text
    assert failures_at_a_glance([{"id": "a", "status": "pass"}]) == ["**No failures.**", ""]
