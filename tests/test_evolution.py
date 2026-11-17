"""The Self-Evolution Laboratory (Stage 5): opportunities ranked from evidence, a design per opportunity, verdicts
that need every repeated run to agree, fair contests, packages only for changes that held, and an append-only history
in which only you can record a decision. Nothing here changes JARVIS."""

import inspect
import json
import re
import sqlite3

import pytest
from test_dashboard import call

from jarvis.learn import Autonomy, evolution, trial
from jarvis.learn.analysis import Lab, LabError


@pytest.fixture
def k(make_kernel):
    return make_kernel()


def _evidence(k, timeouts=4, errors=6):
    """Real evidence for the detectors: a tool that keeps timing out (a "code" opportunity) and one that keeps
    failing (an "investigate" one), written to the audit log the way the tool gateway writes them."""
    for i in range(timeouts):
        k.audit.record("tool.start", op_id=f"t{i}", tool="calendar", action="events")
        k.audit.record("tool.timeout", op_id=f"t{i}")
    for i in range(errors):
        k.audit.record("tool.start", op_id=f"e{i}", tool="fs", action="read")
        k.audit.record("tool.error", op_id=f"e{i}", error="FileNotFoundError")


def run_result(*, fail=(), fixed=(), base_fail=(), secs=10.0, ran=True, lint="clean"):
    return {"ran": ran, "ok": ran and not fail, "newly_failing": list(fail), "newly_passing": list(fixed), "isolation": "macOS sandbox",
            "candidate": {"ref": "cand", "tests": {"passed": 100 - len(fail), "error": 0}, "lint": lint, "seconds": secs, "failing": list(fail)},
            "baseline": {"ref": "HEAD", "tests": {"passed": 100, "error": 0}, "lint": "clean", "seconds": 10.0, "failing": list(base_fail)}}


# ---- verdicts need every run to agree ------------------------------------------------------------------------------
def test_one_good_run_is_not_a_winner():
    assert evolution.evaluate([run_result()] * 3)["verdict"] == "holds"
    flaky = evolution.evaluate([run_result(), run_result(fail=["t::a"]), run_result()])
    assert flaky["verdict"] == "flaky" and flaky["flaky"] == ["t::a"] and flaky["regressions"] == []
    bad = evolution.evaluate([run_result(fail=["t::a"]), run_result(fail=["t::a", "t::b"])])
    assert bad["verdict"] == "fails" and bad["regressions"] == ["t::a"] and bad["flaky"] == ["t::b"]
    assert evolution.evaluate([run_result(), run_result(ran=False)])["verdict"] == "did not run"
    assert evolution.evaluate([])["verdict"] == "did not run"
    assert evolution.evaluate([run_result(lint="E501 line too long")])["verdict"] == "fails"
    base_flaky = evolution.evaluate([run_result(base_fail=["t::z"]), run_result()])
    assert base_flaky["verdict"] == "flaky" and base_flaky["flaky_on_baseline"] == ["t::z"]     # the baseline wobbling counts too
    fixed = evolution.evaluate([run_result(fixed=["t::f", "t::g"]), run_result(fixed=["t::f"])])
    assert fixed["fixed_every_run"] == ["t::f"]                                                # a fix counts only if it held every time


def test_contests_use_the_same_criteria_and_name_no_winner_on_a_tie():
    hold = evolution.evaluate([run_result()] * 2)
    better = evolution.evaluate([run_result(fixed=["t::f"])] * 2)
    broken = evolution.evaluate([run_result(fail=["t::a"])] * 2)
    c = evolution.compare({"a": hold, "b": better, "c": broken})
    assert c["winner"] == "b" and [r["name"] for r in c["ranking"]] == ["b", "a", "c"] and len(c["criteria"]) == 3
    assert evolution.compare({"a": hold, "b": dict(hold)})["winner"] is None                    # level: no winner
    assert evolution.compare({"a": broken, "c": broken})["winner"] is None
    faster = evolution.evaluate([run_result(secs=5.0)] * 2)
    assert evolution.compare({"a": hold, "b": faster})["winner"] == "b"                         # only beyond a 10% margin
    slightly = evolution.evaluate([run_result(secs=9.8)] * 2)
    assert evolution.compare({"a": hold, "b": slightly})["winner"] is None


# ---- opportunities and designs ----------------------------------------------------------------------------------------
def test_opportunities_are_ranked_with_the_numbers_shown_and_recorded_once(k):
    _evidence(k)
    opps = evolution.opportunities(k)
    assert {"timeout:calendar.events", "errors:fs.read"} <= {o["subject"] for o in opps} and all({"benefit", "confidence", "complexity", "risk", "reversible", "priority", "how", "tried_before"} <= set(o) for o in opps)
    assert opps == sorted(opps, key=lambda o: -o["priority"])
    assert evolution.history(k) == []                                         # looking records nothing
    evolution.opportunities(k, refresh=True)
    n = len(evolution.history(k, kind="opportunity"))
    assert n == len(opps)
    evolution.opportunities(k, refresh=True)
    assert len(evolution.history(k, kind="opportunity")) == n                 # not again until the evidence grows
    body = evolution.history(k, kind="opportunity")[0]["body"]
    assert set(body) == {"kind", "size", "benefit", "confidence", "complexity", "risk", "priority"}    # numbers only, none of your words


def test_a_failed_attempt_lowers_priority_but_keeps_the_idea(k):
    _evidence(k)
    first = evolution.opportunities(k)[0]
    evolution.record(k, "experiment", first["subject"], "Trial experiment: fails", {"experiment": "exp-1", "verdict": "fails"}, actor="system:lab")
    again = next(o for o in evolution.opportunities(k) if o["subject"] == first["subject"])
    assert again["priority"] < first["priority"] and again["tried_before"][0]["verdict"] == "fails"


def test_design_has_every_part_and_is_recorded(k):
    _evidence(k)
    subject = "timeout:calendar.events"
    d = evolution.design(k, subject, runs=9)
    assert d["testable_in_lab"] is True and "autonomy level 6" in d["needs"]
    assert evolution.design(k, "errors:fs.read")["testable_in_lab"] is False       # nothing to test: yours to look into
    assert {"problem", "evidence", "proposed", "alternatives", "success", "regression_risks", "test_plan", "budget", "rollback"} <= set(d)
    assert d["budget"]["runs"] == evolution.MAX_RUNS and d["budget"]["cost"].startswith("$0") and len(d["alternatives"]) >= 2
    assert {h["subject"] for h in evolution.history(k, kind="design")} == {subject, "errors:fs.read"}
    with pytest.raises(evolution.EvolutionError):
        evolution.design(k, "no-such-opportunity")


# ---- the history: append-only, and only you decide ----------------------------------------------------------------
def test_history_cannot_be_changed_or_deleted_and_is_searchable(k):
    evolution.record(k, "opportunity", "tool-errors:fs.read", "The fs.read tool keeps failing", {"size": 3}, actor="system")
    for sql in ("UPDATE evolution SET title = 'x'", "DELETE FROM evolution"):
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            with k.db.tx() as c:
                c.execute(sql)
    assert [h["subject"] for h in evolution.history(k, q="fs.read")] == ["tool-errors:fs.read"]
    assert evolution.history(k, q="nothing-like-this") == []


def test_only_you_can_decide_or_mark_and_the_order_is_enforced(k, monkeypatch):
    with pytest.raises(PermissionError):
        evolution.record(k, "decision", "s", "t", {}, actor="system:lab")
    eid = _held_experiment(k, monkeypatch)
    pkg = evolution.package(k, eid)
    assert pkg["status"] == "awaiting your decision" and "git apply" in pkg["apply"] and "git apply -R" in pkg["rollback"]
    assert pkg["jarvis_will_not"].startswith("apply, commit, merge or push")
    for who in ("jarvis", "system:lab", "jarvis:objective"):
        with pytest.raises(PermissionError):
            evolution.decide(k, pkg["seq"], "approved", by=who)
    with pytest.raises(evolution.EvolutionError, match="only when it is approved"):
        evolution.mark(k, pkg["seq"], "applied", by="user:dashboard")
    evolution.decide(k, pkg["seq"], "approved", by="user:dashboard")
    with pytest.raises(evolution.EvolutionError):
        evolution.mark(k, pkg["seq"], "rolled_back", by="user:dashboard")          # can't roll back what wasn't applied
    evolution.mark(k, pkg["seq"], "applied", by="user:dashboard")
    evolution.mark(k, pkg["seq"], "rolled_back", by="user:dashboard")
    assert evolution.packages(k)[0]["status"] == "rolled back"
    assert [h["kind"] for h in evolution.history(k)][:4] == ["rolled_back", "applied", "decision", "package"]


FIX = "--- a/src/calc.py\n+++ b/src/calc.py\n@@ -1,2 +1,2 @@\n def add(a, b):\n-    return a - b\n+    return a + b\n"


def _held_experiment(k, monkeypatch, *, results=None, sensitive=()):
    from jarvis.learn import drafts
    Autonomy(k).set_tier(6, True, by="user:cli", from_dashboard=False)
    files = ["src/calc.py", *sensitive]
    monkeypatch.setattr(drafts, "draft", lambda models, problem: {"problem": problem, "picked": files, "patch": FIX,
                                                                  "model": "ollama/coder", "sha256": "x", "files": files, "sensitive": list(sensitive)})
    monkeypatch.setattr(drafts, "code_review", lambda *a, **kw: {"verdict": "agree", "problems": []})
    seq = iter(results or [run_result(fixed=["tests/test_calc.py::test_add"])] * 3)
    monkeypatch.setattr(trial, "run", lambda *a, **kw: next(seq))
    return Lab(k).start("draft", by="user:dashboard", problem="add() subtracts instead of adding", background=False, runs=3)


def test_a_package_needs_a_change_that_held_in_every_run(k, monkeypatch):
    eid = _held_experiment(k, monkeypatch, results=[run_result(), run_result(fail=["t::a"]), run_result()])
    exp = next(x for x in Lab(k).list() if x["id"] == eid)
    assert exp["state"] == "failed" and exp["results"]["evaluation"]["verdict"] == "flaky" and exp["runs"] == 3
    with pytest.raises(evolution.EvolutionError, match="didn't hold"):
        evolution.package(k, eid)
    assert evolution.history(k, kind="experiment")[0]["body"]["verdict"] == "flaky"      # the failure is on the record
    assert evolution.packages(k) == []
    with pytest.raises(KeyError):
        evolution.package(k, "exp-nope")


def test_package_flags_security_files_and_migrations(k, monkeypatch):
    eid = _held_experiment(k, monkeypatch, sensitive=("src/jarvis/core/permissions.py", "src/jarvis/core/db.py"))
    pkg = evolution.package(k, eid)
    assert pkg["security"]["touches_security_sensitive_files"] == ["src/jarvis/core/permissions.py"]
    assert "read every line" in pkg["security"]["note"] and pkg["migration"].startswith("Yes")
    assert "restore the backup" in pkg["rollback"] and pkg["evidence"]["runs"] == 3
    assert pkg["evidence"]["tests_fixed_in_every_run"] == ["tests/test_calc.py::test_add"]


def test_repeated_trials_and_contests_run_through_the_lab(k, monkeypatch):
    Autonomy(k).set_tier(6, True, by="user:cli", from_dashboard=False)
    monkeypatch.setattr(trial, "available", lambda repo=None: None)
    monkeypatch.setattr(trial, "resolve", lambda ref, repo=None: "a" * 40)
    monkeypatch.setattr(trial, "_git", lambda *a, **kw: "src/calc.py\n")
    calls = []

    def fake(cand, base, **kw):
        calls.append(cand)
        return run_result(fixed=["t::f"]) if cand == "good" else run_result(fail=["t::a"]) if cand == "bad" else run_result()
    monkeypatch.setattr(trial, "run", fake)
    for bad in (0, 6, True, "3"):
        with pytest.raises(LabError, match="runs must be"):
            Lab(k).start("trial", by="user:dashboard", ref="good", runs=bad, background=False)
    eid = Lab(k).start("trial", by="user:dashboard", ref="good", runs=3, background=False, opportunity="tool-errors:fs.read")
    assert calls == ["good"] * 3
    exp = next(x for x in Lab(k).list() if x["id"] == eid)
    assert exp["state"] == "done" and exp["results"]["evaluation"]["verdict"] == "holds" and exp["opportunity"] == "tool-errors:fs.read"
    assert evolution.history(k, subject="tool-errors:fs.read", kind="experiment")[0]["body"]["verdict"] == "holds"
    with pytest.raises(LabError, match="two or three different"):
        Lab(k).start("contest", by="user:dashboard", refs=["good", "good"], runs=2, background=False)
    calls.clear()
    cid = Lab(k).start("contest", by="user:dashboard", refs=["plain", "good", "bad"], runs=2, background=False)
    assert calls == ["plain", "plain", "good", "good", "bad", "bad"]                    # every candidate, the same number of runs
    contest = next(x for x in Lab(k).list() if x["id"] == cid)
    assert contest["results"]["winner_ref"] == "good" and contest["state"] == "done"
    pkg = evolution.package(k, cid)
    assert "git merge good" in pkg["apply"] and pkg["files"] == ["src/calc.py"]


# ---- guardrails -------------------------------------------------------------------------------------------------------
def test_the_laboratory_cannot_touch_its_own_limits():
    """It never writes the autonomy, permission or approval tables, never applies or pushes, and never runs code
    itself (it calls the Lab, which enforces the tiers and the sandbox)."""
    src = inspect.getsource(evolution)
    code = "\n".join(line for line in src.split('"""', 2)[2].splitlines() if not line.strip().startswith("#"))
    assert re.findall(r"(?:INSERT INTO|UPDATE|DELETE FROM)\s+(\w+)", code) == ["evolution"]
    for forbidden in ("subprocess", "os.system", "set_tier", "egress_grants", "approvals.approve", "killswitch.release",
                      '"git", "apply"', '"push"', '"merge"', '"commit"'):
        assert forbidden not in code, forbidden


def test_routes_are_mac_only_decisions_need_touch_id_and_a_phone_cannot_start_code(dash):
    d, *_ = dash
    from jarvis.remote import LOCAL_ONLY
    from jarvis.remote.mac import MAC_STEP_UP
    for p in ("/api/evolution/decide", "/api/evolution/mark", "/api/evolution/package", "/api/evolution/design", "/api/evolution/refresh"):
        assert any(re.fullmatch(x, p) for x in LOCAL_ONLY), p
    assert any(re.fullmatch(x, "/api/evolution/decide") for x in MAC_STEP_UP)
    assert "/^\\/api\\/evolution\\/decide$/" in call(d, "/static/app.js")[2].decode()
    app = inspect.getsource(__import__("jarvis.server.app", fromlist=["x"]))
    assert 'body.get("kind") in ("trial", "draft", "contest")' in app                    # the phone path refuses all three
    r = json.loads(call(d, "/api/evolution")[2])
    assert {"opportunities", "packages", "history", "max_runs"} <= set(r)
    assert call(d, "/api/evolution/package", {"experiment": "exp-nope"})[0] == 404
    assert call(d, "/api/evolution/decide", {"package": 1, "decision": "approved"})[0] == 404
    assert call(d, "/api/evolution/decide", {"package": "1", "decision": "approved"})[0] == 400
    assert call(d, "/api/experiments", {"kind": "contest", "refs": ["a", "b"], "runs": 2})[0] == 409   # tier 6 is off
    assert call(d, "/api/evolution/refresh", {})[0] == 200
