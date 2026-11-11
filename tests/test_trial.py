"""Tier 6 change trials: a candidate is tested in throwaway worktrees and compared; nothing is merged or changed."""

import shutil
import subprocess

import pytest

from jarvis.learn import Autonomy, analysis, trial

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
                        "HOME": str(repo), "PATH": "/usr/bin:/bin:/usr/local/bin"})


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    (r / "src").mkdir(parents=True)
    (r / "tests").mkdir()
    (r / "src" / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    (r / "tests" / "test_calc.py").write_text("from calc import add\n\n\ndef test_add():\n    assert add(2, 2) == 4\n\n\ndef test_zero():\n    assert add(0, 0) == 0\n")
    git(r, "init", "-q", "-b", "main")
    git(r, "add", ".")
    git(r, "commit", "-qm", "base")
    git(r, "checkout", "-qb", "broken")
    (r / "src" / "calc.py").write_text("def add(a, b):\n    return a - b\n")   # breaks test_add, test_zero still passes
    git(r, "commit", "-qam", "break add")
    git(r, "checkout", "-q", "main")
    return r


def test_a_regression_is_caught_and_nothing_is_merged(repo, tmp_path):
    before = subprocess.run(["git", "rev-parse", "main"], cwd=repo, capture_output=True, text=True).stdout
    r = trial.run("broken", "main", work=tmp_path / "work", repo=repo)
    assert r["ran"] and not r["ok"]
    assert r["newly_failing"] == ["tests/test_calc.py::test_add"]
    assert r["baseline"]["tests"]["passed"] == 2 and r["candidate"]["tests"]["passed"] == 1
    assert "Don't merge yet" in trial.recommendation(r)
    assert subprocess.run(["git", "rev-parse", "main"], cwd=repo, capture_output=True, text=True).stdout == before   # untouched
    assert len(subprocess.run(["git", "worktree", "list"], cwd=repo, capture_output=True, text=True).stdout.strip().splitlines()) == 1
    assert not any((tmp_path / "work").iterdir())                                            # throwaway copies removed


def test_a_fix_is_reported_as_no_regression(repo, tmp_path):
    r = trial.run("main", "broken", work=tmp_path / "work", repo=repo)
    assert r["ok"] and r["newly_passing"] == ["tests/test_calc.py::test_add"]


def test_refs_are_validated():
    for bad in ("--upload-pack=x", "a b", "../../etc", "", "x;rm"):
        with pytest.raises(trial.TrialError):
            trial.resolve(bad)


def test_trials_need_tier_6_from_the_terminal(make_kernel):
    k = make_kernel()
    with pytest.raises(analysis.LabError, match="tier 6"):
        analysis.Lab(k).start("trial", by="t", background=False, ref="HEAD")
    with pytest.raises(Exception):
        Autonomy(k).set_tier(6, True, by="dashboard")                                       # never from a browser
    Autonomy(k).set_tier(6, True, by="cli", from_dashboard=False)
    assert Autonomy(k).can("execute")
    Autonomy(k).set_pause("experiments", True, by="t")
    assert not Autonomy(k).can("execute")                                                   # pausing experiments stops trials
