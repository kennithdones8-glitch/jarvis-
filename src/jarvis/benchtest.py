""""Test this version": one button for the benchmark, nothing to babysit.

You ask for a test (tonight, or now). The maintenance loop starts it when the Mac is idle (and, for "tonight", in your
quiet hours), as a separate process on a throwaway benchmark folder (bench-home inside JARVIS's data folder, holding
only a copy of your model settings), with local models only, so your real data, your Claude plan and your money are
untouched. When it finishes, the result is compared with the latest run of the same tasks on a different commit, and
the verdict (with the reasons) is shown in Systems and the Benchmarks page and written to the audit log.

It runs only because you asked for that one test, never on its own, and never during a mission or the emergency stop.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from . import service

REQUEST = "benchtest.request"
LAST = "benchtest.last"
SETS = ("hard", "all", "core")


def _meta(kernel, key: str) -> dict[str, Any] | None:
    row = kernel.db.one("SELECT value FROM meta WHERE key = ?", (key,))
    try:
        return json.loads(row["value"]) if row else None
    except ValueError:
        return None


def _put(kernel, key: str, value: dict[str, Any] | None) -> None:
    with kernel.db.tx() as c:
        if value is None:
            c.execute("DELETE FROM meta WHERE key = ?", (key,))
        else:
            c.execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                      (key, json.dumps(value)))


def bench_home(kernel) -> Path:
    return Path(kernel.home) / "bench-home"


def request(kernel, *, by: str, when: str = "tonight", set_: str = "hard", repeat: int = 5) -> dict[str, Any]:
    if not by.startswith("user"):
        raise PermissionError("only you can start a benchmark")
    if when not in ("tonight", "now") or set_ not in SETS or not 3 <= int(repeat) <= 10:
        raise ValueError("when is tonight or now; set is hard, all or core; repeat is 3–10")
    current = _meta(kernel, REQUEST)
    if current and current.get("pid"):
        raise ValueError("a test is already running")
    r = {"when": when, "set": set_, "repeat": int(repeat), "asked": time.time(), "by": by}
    _put(kernel, REQUEST, r)
    kernel.audit.record("benchtest.requested", actor=by, when=when, set=set_, repeat=int(repeat))
    return r


def cancel(kernel, *, by: str) -> None:
    r = _meta(kernel, REQUEST)
    if r and r.get("pid"):
        try:
            os.killpg(int(r["pid"]), 15)
        except (ProcessLookupError, PermissionError, ValueError):
            pass
    _put(kernel, REQUEST, None)
    kernel.audit.record("benchtest.cancelled", actor=by)


def status(kernel) -> dict[str, Any]:
    r = _meta(kernel, REQUEST)
    return {"request": {k: r.get(k) for k in ("when", "set", "repeat", "asked", "started")} if r else None,
            "running": bool(r and r.get("pid")), "last": _meta(kernel, LAST)}


def idle(load: float | None = None, cores: int | None = None) -> bool:
    """The Mac isn't busy with other work: 1-minute load below a quarter of its cores (at least 1)."""
    load = os.getloadavg()[0] if load is None else load
    cores = cores or os.cpu_count() or 1
    return load < max(1.0, cores / 4)


def _alive(pid: Any) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (TypeError, ValueError, ProcessLookupError):
        return False
    except PermissionError:
        return True


def tick(kernel, *, quiet: bool, load: float | None = None, spawn=None) -> str | None:
    """Called by the maintenance loop. Starts a waiting test when it may, or finishes one that has ended."""
    r = _meta(kernel, REQUEST)
    if not r:
        return None
    if r.get("pid"):
        if _alive(r["pid"]):
            return "running"
        finish(kernel, r)
        return "finished"
    if kernel.killswitch.engaged() or kernel.db.one("SELECT COUNT(*) FROM tasks WHERE state = 'running'")[0]:
        return "waiting"
    if (r["when"] == "tonight" and not quiet) or not idle(load):
        return "waiting"
    home = bench_home(kernel)
    home.mkdir(exist_ok=True, mode=0o700)
    if kernel.config_path.exists():   # your model settings, nothing else (no memories, policy or history)
        shutil.copyfile(kernel.config_path, home / "jarvis.toml")
    args = [shutil.which("uv") or str(Path.home() / ".local" / "bin" / "uv"), "run", "--project", str(service.REPO),
            "--quiet", "jarvis", "--home", str(home), "bench", "run", "--set", r["set"], "--repeat", str(r["repeat"]),
            "--run-code", "--models", "local"]
    logs = Path(kernel.home) / "logs"
    logs.mkdir(exist_ok=True)
    if spawn is None:
        with open(logs / "benchtest.log", "ab") as log:
            pid = subprocess.Popen(args, cwd=service.REPO, stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                                   start_new_session=True, close_fds=True).pid
    else:
        pid = spawn(args)
    r.update(pid=pid, started=time.time())
    _put(kernel, REQUEST, r)
    kernel.audit.record("benchtest.started", set=r["set"], repeat=r["repeat"])
    return "started"


def _task_ids(data: dict[str, Any]) -> frozenset[str]:
    return frozenset(x["id"] for x in data.get("results", []))


def finish(kernel, r: dict[str, Any]) -> dict[str, Any]:
    """Compare the new run with the latest earlier run of the same tasks on a different commit."""
    from .bench.compare import compare, load

    out = bench_home(kernel) / "bench-results"
    runs = sorted((d for d in out.glob("*") if (d / "results.json").is_file()), key=lambda d: (d / "results.json").stat().st_mtime,
                  reverse=True) if out.is_dir() else []
    new = next((d for d in runs if (d / "results.json").stat().st_mtime >= r.get("started", 0)), None)
    result: dict[str, Any] = {"finished": time.time(), "set": r["set"]}
    if new is None:
        result.update(verdict="NO RESULT", reasons=["the benchmark ended without results (see logs/benchtest.log)"])
    else:
        after = load(new)
        commit = after["meta"].get("git_commit")
        before = next((d for d in runs if d != new and _task_ids(load(d)) == _task_ids(after)
                       and load(d)["meta"].get("git_commit") != commit), None)
        scored = [x for x in after["results"] if x.get("status") in ("pass", "fail")]
        result.update(run=new.name, commit=commit, passed=sum(x["status"] == "pass" for x in scored), scored=len(scored))
        if before is None:
            result.update(verdict="FIRST RUN", reasons=["nothing earlier to compare with: this run is the baseline for the next"])
        else:
            c = compare(load(before), after)
            result.update(verdict=c.verdict, before=before.name, net=c.net, fixed=c.fixed, new_failures=c.new_failures,
                          reasons=c.reasons + c.inconclusive)
    _put(kernel, LAST, result)
    _put(kernel, REQUEST, None)
    kernel.audit.record("benchtest.finished", verdict=result["verdict"], net=result.get("net"))
    return result


if __name__ == "__main__":  # pragma: no cover - manual use: show the state
    from .core import Kernel
    k = Kernel(sys.argv[1] if len(sys.argv) > 1 else None)
    print(json.dumps(status(k), indent=1))
    k.close()
