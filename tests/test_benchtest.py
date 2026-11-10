"""'Test this version': asked for by you, started only when allowed (idle; tonight = quiet hours; no mission, no stop),
run on a throwaway folder with local models, and judged against the last run of the same tasks on another commit."""

import json
import shutil
from pathlib import Path

import pytest
from test_dashboard import call

from jarvis import benchtest
from jarvis.core import Kernel


@pytest.fixture
def k(tmp_path):
    kernel = Kernel(tmp_path / "home")
    (kernel.config_path).write_text("# model settings\n")
    yield kernel
    kernel.close()


def test_only_you_can_ask_and_inputs_are_checked(k):
    with pytest.raises(PermissionError):
        benchtest.request(k, by="jarvis")
    with pytest.raises(ValueError):
        benchtest.request(k, by="user:dashboard", when="whenever")
    with pytest.raises(ValueError):
        benchtest.request(k, by="user:dashboard", repeat=50)


def test_waits_for_quiet_hours_an_idle_mac_and_no_mission(k):
    started = []
    spawn = lambda args: started.append(args) or 4242   # noqa: E731
    benchtest.request(k, by="user:dashboard", when="tonight")
    assert benchtest.tick(k, quiet=False, load=0.1, spawn=spawn) == "waiting"     # daytime
    assert benchtest.tick(k, quiet=True, load=50.0, spawn=spawn) == "waiting"     # busy Mac
    k.killswitch.engage(by="user:cli", reason="t")
    assert benchtest.tick(k, quiet=True, load=0.1, spawn=spawn) == "waiting"      # emergency stop
    k.killswitch.release(by="user:cli", confirm=True)
    assert benchtest.tick(k, quiet=True, load=0.1, spawn=spawn) == "started"
    args = started[0]
    assert args[args.index("--home") + 1] == str(benchtest.bench_home(k))         # never your real data folder
    assert args[args.index("--models") + 1] == "local" and "--run-code" in args
    assert (benchtest.bench_home(k) / "jarvis.toml").read_text() == "# model settings\n"
    assert not (benchtest.bench_home(k) / "policy.toml").exists()
    assert benchtest.status(k)["running"]


def _run(out: Path, name: str, commit: str, passes: dict[str, int], mtime: float):
    d = out / name
    d.mkdir(parents=True)
    results = [{"id": t, "run": i + 1, "status": "pass" if i < n else "fail", "category": "x"}
               for t, n in passes.items() for i in range(5)]
    (d / "results.json").write_text(json.dumps({"meta": {"run_id": name, "git_commit": commit, "repeat": 5}, "results": results}))
    import os
    os.utime(d / "results.json", (mtime, mtime))


def test_finish_compares_with_the_last_run_on_another_commit(k):
    out = benchtest.bench_home(k) / "bench-results"
    _run(out, "20261101-000000-local", "aaa", {"t1": 1, "t2": 1, "t3": 5}, 1000)
    _run(out, "20261102-000000-local", "bbb", {"t1": 5, "t2": 5, "t3": 5}, 3000)
    r = benchtest.finish(k, {"set": "hard", "started": 2000})
    assert r["run"] == "20261102-000000-local" and r["before"] == "20261101-000000-local"
    assert r["verdict"] == "MERGE" and r["net"] == 2 and r["passed"] == 15
    assert benchtest.status(k)["last"]["verdict"] == "MERGE" and benchtest.status(k)["request"] is None
    assert any(e["event"] == "benchtest.finished" for e in k.audit.entries(limit=10))


def test_first_run_and_no_result_are_said_plainly(k):
    assert benchtest.finish(k, {"set": "hard", "started": 0})["verdict"] == "NO RESULT"
    out = benchtest.bench_home(k) / "bench-results"
    _run(out, "20261103-000000-local", "ccc", {"t1": 5}, 5000)
    assert benchtest.finish(k, {"set": "hard", "started": 4000})["verdict"] == "FIRST RUN"


def test_idle_rule():
    assert benchtest.idle(load=2.0, cores=12) and not benchtest.idle(load=4.0, cores=12)
    assert benchtest.idle(load=0.5, cores=2) and not benchtest.idle(load=1.2, cores=2)


def test_routes_are_mac_only(dash, monkeypatch):
    import re

    monkeypatch.setattr(benchtest, "idle", lambda load=None, cores=None: False)   # never start a real benchmark here
    from jarvis.remote import LOCAL_ONLY
    for path in ("/api/benchtest", "/api/benchtest/cancel"):
        assert any(re.fullmatch(p, path) for p in LOCAL_ONLY), path
    d, *_ = dash
    status, _, body = call(d, "/api/benchtest", {"when": "tonight"})
    assert status == 200 and json.loads(body)["request"]["when"] == "tonight"
    assert json.loads(call(d, "/api/state")[2])["benchtest"]["request"]
    assert json.loads(call(d, "/api/benchtest/cancel", {})[2])["request"] is None
    shutil.rmtree(benchtest.bench_home(d.kernel), ignore_errors=True)
