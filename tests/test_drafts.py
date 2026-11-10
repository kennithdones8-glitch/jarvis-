"""JARVIS drafts a fix: only src/ and tests/ may change, the patch is tested on a throwaway copy (never your code),
reviewed by another model, and handed to you with the command to apply it; JARVIS never applies it."""

import subprocess
from types import SimpleNamespace

import pytest
from test_trial import git, repo  # noqa: F401 - the fixture

from jarvis.learn import drafts, trial

FIX = """--- a/src/calc.py
+++ b/src/calc.py
@@ -1,2 +1,2 @@
 def add(a, b):
-    return a - b
+    return a + b
"""


def test_scope_is_src_and_tests_only_and_sensitive_files_are_flagged():
    assert drafts.check_scope(FIX)["files"] == ["src/calc.py"]
    bad = FIX.replace("src/calc.py", "pyproject.toml")
    with pytest.raises(drafts.DraftError, match="outside src/ and tests/"):
        drafts.check_scope(bad)
    with pytest.raises(drafts.DraftError):
        drafts.check_scope(FIX.replace("src/calc.py", "src/../.github/workflows/gate.yml"))
    with pytest.raises(drafts.DraftError, match="isn't a patch"):
        drafts.check_scope("just some words")
    sens = drafts.check_scope(FIX.replace("src/calc.py", "src/jarvis/core/permissions.py"))
    assert sens["sensitive"] == ["src/jarvis/core/permissions.py"]


def test_a_patch_is_tested_on_a_throwaway_copy_and_never_applied(repo, tmp_path):  # noqa: F811
    git(repo, "checkout", "-q", "broken")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout
    r = trial.run("HEAD", "HEAD", work=tmp_path / "work", repo=repo, patch=FIX)
    assert r["ran"] and r["ok"] and r["newly_passing"] == ["tests/test_calc.py::test_add"]
    assert (repo / "src" / "calc.py").read_text().endswith("return a - b\n")       # your code untouched
    assert subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout == head
    assert not subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True).stdout
    assert not any((tmp_path / "work").iterdir())                                   # the copies are gone
    with pytest.raises(trial.TrialError, match="doesn't apply"):
        trial.run("HEAD", "HEAD", work=tmp_path / "work", repo=repo, patch=FIX.replace("a - b", "a * b"))


def test_draft_picks_listed_files_only_and_extracts_the_diff(repo, monkeypatch):  # noqa: F811
    replies = iter(['{"files": ["src/calc.py", "/etc/passwd"]}', f"Here you go:\n```diff\n{FIX}```"])
    monkeypatch.setattr(drafts, "_complete", lambda *a, **k: SimpleNamespace(text=next(replies), provider="ollama", model="coder"))
    d = drafts.draft(None, "add() subtracts instead of adding", repo=repo)
    assert d["picked"] == ["src/calc.py"] and d["files"] == ["src/calc.py"] and d["patch"].startswith("--- a/src/calc.py")
    monkeypatch.setattr(drafts, "_complete", lambda *a, **k: SimpleNamespace(text='{"files": []}', provider="o", model="m"))
    with pytest.raises(drafts.DraftError, match="which files"):
        drafts.draft(None, "something vague but long enough", repo=repo)


def test_the_recommendation_never_claims_it_was_applied(tmp_path):
    ok = {"ran": True, "ok": True, "newly_failing": [], "newly_passing": ["t"], "candidate": {"tests": {"passed": 3}, "lint": "clean"}}
    text = drafts.recommendation(ok, {"verdict": "agree"}, {"sensitive": []}, tmp_path / "exp-1.patch")
    assert "Tests hold" in text and "agrees" in text and "git apply" in text and "never applies" in text
    bad = {**ok, "newly_failing": ["tests/x.py::y"]}
    assert drafts.recommendation(bad, {"verdict": "unavailable"}, {"sensitive": ["src/jarvis/gate.py"]},
                                 tmp_path / "p").startswith("Don't use it yet")
    assert "couldn't be tested" in drafts.recommendation(None, {}, {}, tmp_path / "p", error="doesn't apply")


def test_the_lab_needs_tier_6_and_you(make_kernel, monkeypatch):
    from jarvis.learn import Autonomy
    from jarvis.learn.analysis import Lab, LabError
    k = make_kernel()
    with pytest.raises(LabError, match="tier 6"):
        Lab(k).start("draft", by="user:dashboard", problem="add() subtracts instead of adding", background=False)
    Autonomy(k).set_tier(6, True, by="user:cli", from_dashboard=False)
    with pytest.raises(LabError, match="only you"):
        Lab(k).start("draft", by="jarvis", problem="add() subtracts instead of adding", background=False)
    calls = {}
    monkeypatch.setattr(drafts, "draft", lambda models, problem: {"problem": problem, "picked": ["src/calc.py"], "patch": FIX,
                                                                  "model": "ollama/coder", "sha256": "x", "files": ["src/calc.py"], "sensitive": []})
    monkeypatch.setattr(drafts, "code_review", lambda *a, **kw: {"verdict": "agree", "problems": []})
    monkeypatch.setattr(trial, "run", lambda *a, **kw: calls.setdefault("trial", kw) and {
        "ran": True, "ok": True, "newly_failing": [], "newly_passing": [], "candidate": {"tests": {"passed": 1}, "lint": "clean"}})
    eid = Lab(k).start("draft", by="user:dashboard", problem="add() subtracts instead of adding", background=False)
    exp = next(x for x in Lab(k).list() if x["id"] == eid)
    assert exp["state"] == "done" and exp["results"]["patch"] == FIX and calls["trial"]["patch"] == FIX
    assert (k.home / "drafts" / f"{eid}.patch").read_text() == FIX
    assert oct((k.home / "drafts" / f"{eid}.patch").stat().st_mode & 0o777) == "0o600"
    assert "git apply" in exp["recommendation"]
