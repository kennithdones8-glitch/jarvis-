"""Update JARVIS from the dashboard: one button, on the Mac, by you. JARVIS never starts an update itself.

"Check for updates" fetches your branch from GitHub and lists the new commits; nothing changes. "Update" then runs a
separate helper (so the dashboard can restart under it) that does, in order:

1. the checks: a git checkout on a branch, no local edits, only new commits (a fast-forward), no mission running,
   the emergency stop off, and the background service in charge of JARVIS;
2. an encrypted, verified backup (backups/before-update);
3. the new commits (fast-forward only) and `uv sync`;
4. the release gate on the new code. If it fails, the old commit comes back and nothing is restarted;
5. a restart of the background service, then up to two minutes for it to answer. If it doesn't, the old code and the
   database as it was just before the restart are put back, and the old version is started again.

Progress is written to update/state.json in JARVIS's data folder, so the dashboard can show it across the restart.
The plain copy of the database taken for step 5 lives in that private folder only for the minutes of the update.
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

from . import backup, service   # imported up front: the helper keeps running while the files on disk change

STATE = "state.json"
SNAPSHOT = "jarvis-before-restart.db"
KEEP = 5
GATE_TIMEOUT = 1200
ANSWER_WAIT = 120


class UpdateError(RuntimeError):
    pass


def _git(repo: Path, *args: str, timeout: int = 120) -> str:
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise UpdateError(f"git {args[0]}: {(r.stderr or r.stdout).strip()[:300]}")
    return r.stdout.strip()


def _cmd(args: list[str], cwd: Path, timeout: int) -> tuple[bool, str]:
    """Run a command; (succeeded, the last lines of its output)."""
    try:
        r = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)[:300]
    tail = "\n".join((r.stdout + r.stderr).strip().splitlines()[-6:])
    return r.returncode == 0, tail[:600]


def _uv() -> str:
    return shutil.which("uv") or str(Path.home() / ".local" / "bin" / "uv")


def folder(home: Path) -> Path:
    d = Path(home) / "update"
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    return d


def check(repo: Path = service.REPO) -> dict[str, Any]:
    """Fetch the current branch and say what an update would bring. Changes nothing but git's view of GitHub."""
    repo = Path(repo)
    if not (repo / ".git").exists():
        return {"can_update": False, "why": "JARVIS isn't running from a git checkout"}
    branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if branch == "HEAD":
        return {"can_update": False, "why": "this checkout isn't on a branch"}
    head = _git(repo, "rev-parse", "HEAD")
    _git(repo, "fetch", "--quiet", "origin", branch, timeout=90)
    remote = _git(repo, "rev-parse", f"origin/{branch}")
    behind = int(_git(repo, "rev-list", "--count", f"HEAD..origin/{branch}"))
    ahead = int(_git(repo, "rev-list", "--count", f"origin/{branch}..HEAD"))
    dirty = bool(_git(repo, "status", "--porcelain", "--untracked-files=no"))
    commits = _git(repo, "log", "--format=%h %s", "-20", f"HEAD..origin/{branch}").splitlines() if behind else []
    why = ("there are local edits in the JARVIS folder" if dirty else
           "this copy has commits GitHub doesn't, so it can't simply move forward" if ahead else
           "already up to date" if not behind else "")
    return {"can_update": not why, "why": why, "branch": branch, "head": head[:12], "to": remote, "behind": behind,
            "ahead": ahead, "dirty": dirty, "commits": commits}


def status(home: Path) -> dict[str, Any] | None:
    p = Path(home) / "update" / STATE
    try:
        s = json.loads(p.read_text())
    except (OSError, ValueError):
        return None
    if s.get("state") == "running" and not _alive(s.get("pid")):
        s.update(state="failed", finished=time.time(),
                 steps=s.get("steps", []) + [{"name": "Updater", "ok": False, "detail": "stopped unexpectedly"}])
        _write(home, s)
    return s


def _alive(pid: Any) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (TypeError, ValueError, ProcessLookupError):
        return False
    except PermissionError:
        return True


def _write(home: Path, s: dict[str, Any]) -> None:
    p = folder(home) / STATE
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, indent=1))
    os.chmod(tmp, 0o600)
    os.replace(tmp, p)


def start(kernel, *, repo: Path = service.REPO, port: int = service.DEFAULT_PORT, by: str) -> dict[str, Any]:
    if not by.startswith("user"):
        raise PermissionError("only you can update JARVIS")
    if sys.platform != "darwin" or not service.is_loaded():
        raise UpdateError("updating from the dashboard needs the background service on the Mac (`jarvis service install`)")
    current = status(kernel.home)
    if current and current.get("state") == "running":
        raise UpdateError("an update is already running")
    if kernel.killswitch.engaged():
        raise UpdateError("the emergency stop is on; release it first")
    if kernel.db.one("SELECT COUNT(*) FROM tasks WHERE state = 'running'")[0]:
        raise UpdateError("a mission is running; update when it has finished")
    c = check(repo)
    if not c["can_update"]:
        raise UpdateError(c["why"])
    s = {"state": "running", "from": _git(Path(repo), "rev-parse", "HEAD"), "to": c["to"], "branch": c["branch"],
         "behind": c["behind"], "started": time.time(), "steps": [], "reported": False}
    _write(kernel.home, s)
    logs = Path(kernel.home) / "logs"
    logs.mkdir(exist_ok=True)
    with open(logs / "update.log", "ab") as log:
        proc = subprocess.Popen([sys.executable, "-m", "jarvis.update", "--home", str(kernel.home), "--repo", str(repo),
                                 "--port", str(port)], cwd=repo, stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                                start_new_session=True, close_fds=True)
    s["pid"] = proc.pid
    _write(kernel.home, s)
    kernel.audit.record("update.started", actor=by, to=c["to"][:12], commits=c["behind"])
    return s


def run(home: Path, repo: Path, port: int) -> dict[str, Any]:
    """The helper: every step from the module notes, recorded as it goes."""
    home, repo = Path(home), Path(repo)
    s = json.loads((folder(home) / STATE).read_text())   # written by start(); not status(), which checks the pid
    s.update(state="running", pid=os.getpid())
    frm, to = s["from"], s["to"]

    def step(name: str, ok: bool, detail: str = "") -> bool:
        s["steps"].append({"name": name, "ok": ok, "detail": detail[:600], "at": time.time()})
        _write(home, s)
        return ok

    def finish(state: str) -> dict[str, Any]:
        s.update(state=state, finished=time.time())
        _write(home, s)
        return s

    def back_to_old_code() -> None:
        _git(repo, "reset", "--hard", frm)
        _cmd([_uv(), "sync", "-q"], repo, 600)

    try:
        r = backup.create_backup(home, home / "policy.toml", home / "jarvis.toml",
                                 dest_dir=home / "backups" / "before-update", keep=KEEP)
        step("Backup", True, r.path.name)
    except Exception as exc:  # noqa: BLE001 - no backup, no update
        step("Backup", False, str(exc))
        return finish("failed")
    try:
        _git(repo, "merge", "--ff-only", to)
        step("Download", _git(repo, "rev-parse", "HEAD") == to, f"now at {to[:12]}")
    except UpdateError as exc:
        step("Download", False, str(exc))
        return finish("failed")
    ok, out = _cmd([_uv(), "sync", "-q"], repo, 600)
    if not step("Install", ok, out):
        back_to_old_code()
        return finish("failed")
    ok, out = _cmd([_uv(), "run", "--project", str(repo), "--quiet", "jarvis", "gate"], repo, GATE_TIMEOUT)
    if not step("Tests", ok, out if not ok else "the release gate passed"):
        back_to_old_code()
        step("Undo", True, f"back on {frm[:12]}; nothing was restarted")
        return finish("failed")
    snap = folder(home) / SNAPSHOT
    backup._snapshot_db(home / "jarvis.db", snap)
    os.chmod(snap, 0o600)
    try:
        service.restart()
    except Exception as exc:  # noqa: BLE001
        step("Restart", False, str(exc))
    deadline = time.monotonic() + ANSWER_WAIT
    time.sleep(3)
    while time.monotonic() < deadline and not service.responding(port):
        time.sleep(2)
    if service.responding(port):
        step("Restart", True, "the new version is answering")
        snap.unlink(missing_ok=True)
        return finish("done")
    step("Restart", False, f"the new version didn't answer within {ANSWER_WAIT // 60} minutes")
    service._launchctl("bootout", f"{service._domain()}/{service.LABEL}", check=False)
    back_to_old_code()
    for extra in ("jarvis.db-wal", "jarvis.db-shm"):
        (home / extra).unlink(missing_ok=True)
    shutil.copyfile(snap, home / "jarvis.db")
    os.chmod(home / "jarvis.db", 0o600)
    snap.unlink(missing_ok=True)
    service._launchctl("bootstrap", service._domain(), str(service.plist_path()), check=False)
    time.sleep(3)
    step("Undo", service.responding(port), f"old version {frm[:12]} and its database are back")
    return finish("rolled_back")


def report(kernel) -> None:
    """Once, after an update has finished: put the outcome in the audit log."""
    s = status(kernel.home)
    if not s or s.get("state") == "running" or s.get("reported"):
        return
    kernel.audit.record("update.finished", outcome=s["state"], to=str(s.get("to", ""))[:12],
                        steps=[f"{x['name']}: {'ok' if x['ok'] else 'failed'}" for x in s.get("steps", [])])
    s["reported"] = True
    _write(kernel.home, s)


if __name__ == "__main__":   # the helper started by start()
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--home", required=True)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--port", type=int, default=service.DEFAULT_PORT)
    a = ap.parse_args()
    run(Path(a.home), Path(a.repo), a.port)
