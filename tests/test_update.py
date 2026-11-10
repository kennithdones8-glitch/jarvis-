"""The dashboard's Update button: owner-only, Mac-only, fast-forward only, backed up first, tested before restarting,
and put back by itself (code and database) when the new version fails its tests or doesn't answer."""

import json
import sqlite3
import subprocess
import sys

import pytest
from test_dashboard import call

from jarvis import update
from jarvis.core import Kernel


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repos(tmp_path):
    origin, local = tmp_path / "origin.git", tmp_path / "jarvis"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    subprocess.run(["git", "clone", "-q", str(origin), str(local)], check=True, capture_output=True)
    for k, v in (("user.email", "t@example.invalid"), ("user.name", "t")):
        git(local, "config", k, v)
    (local / "a.txt").write_text("one\n")
    git(local, "add", ".")
    git(local, "commit", "-qm", "first")
    git(local, "push", "-q", "origin", "HEAD:main")
    other = tmp_path / "other"
    subprocess.run(["git", "clone", "-q", str(origin), str(other)], check=True, capture_output=True)
    for k, v in (("user.email", "t@example.invalid"), ("user.name", "t")):
        git(other, "config", k, v)
    (other / "a.txt").write_text("two\n")
    git(other, "commit", "-qam", "second: better answers")
    git(other, "push", "-q", "origin", "HEAD:main")
    return local, other


def test_check_lists_new_commits_and_changes_nothing(repos):
    local, _ = repos
    head = git(local, "rev-parse", "HEAD")
    c = update.check(local)
    assert c["can_update"] and c["behind"] == 1 and c["ahead"] == 0 and c["branch"] == "main"
    assert c["commits"][0].endswith("second: better answers")
    assert git(local, "rev-parse", "HEAD") == head and (local / "a.txt").read_text() == "one\n"


def test_check_refuses_local_edits_and_diverged_history(repos):
    local, _ = repos
    (local / "a.txt").write_text("edited\n")
    c = update.check(local)
    assert not c["can_update"] and "local edits" in c["why"]
    git(local, "checkout", "-q", "a.txt")
    (local / "b.txt").write_text("x\n")
    git(local, "add", "b.txt")
    git(local, "commit", "-qm", "local only")
    c = update.check(local)
    assert not c["can_update"] and "can't simply move forward" in c["why"]


@pytest.fixture
def updater(repos, tmp_path, monkeypatch):
    """A home with a database, the update state as start() writes it, and the outside world faked."""
    local, _ = repos
    monkeypatch.setenv("JARVIS_BACKUP_PASSPHRASE", "test-phrase-1234")
    home = tmp_path / "home"
    Kernel(home).close()
    c = update.check(local)
    update._write(home, {"state": "running", "from": git(local, "rev-parse", "HEAD"), "to": c["to"], "branch": "main",
                         "behind": 1, "started": 0, "steps": [], "reported": False})
    calls = []
    world = {"gate_ok": True, "answers": True}

    def fake_cmd(args, cwd, timeout):
        calls.append(args[1:3])
        return (world["gate_ok"], "1 failed") if "gate" in args else (True, "")
    monkeypatch.setattr(update, "_cmd", fake_cmd)

    def fake_restart():
        calls.append("restart")
        conn = sqlite3.connect(home / "jarvis.db")   # the "new version" writes to the database as it starts
        conn.execute("INSERT INTO meta (key, value) VALUES ('new-version-was-here', '1')")
        conn.commit()
        conn.close()
    monkeypatch.setattr(update.service, "restart", fake_restart)
    monkeypatch.setattr(update.service, "responding", lambda port=8765: world["answers"] and "restart" in calls
                        and calls[-1] != "bootout")
    monkeypatch.setattr(update.service, "_launchctl", lambda *a, **k: calls.append(a[0]))
    monkeypatch.setattr(update.time, "sleep", lambda s: None)
    monkeypatch.setattr(update, "ANSWER_WAIT", 0)
    return home, local, c, calls, world


def _meta(home, key):
    conn = sqlite3.connect(home / "jarvis.db")
    try:
        return conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    finally:
        conn.close()


def test_a_good_update_backs_up_moves_forward_and_restarts(updater):
    home, local, c, calls, _ = updater
    s = update.run(home, local, 8765)
    assert s["state"] == "done", s["steps"]
    assert [x["name"] for x in s["steps"]] == ["Backup", "Download", "Install", "Tests", "Restart"]
    assert git(local, "rev-parse", "HEAD") == c["to"] and (local / "a.txt").read_text() == "two\n"
    assert list((home / "backups" / "before-update").glob("*.jbak"))
    assert not (home / "update" / update.SNAPSHOT).exists()   # the plain copy is gone once it isn't needed


def test_failing_tests_put_the_old_code_back_without_a_restart(updater):
    home, local, c, calls, world = updater
    world["gate_ok"] = False
    before = update.status(home)["from"]
    s = update.run(home, local, 8765)
    assert s["state"] == "failed" and s["steps"][-1]["name"] == "Undo"
    assert git(local, "rev-parse", "HEAD") == before and (local / "a.txt").read_text() == "one\n"
    assert "restart" not in calls


def test_a_new_version_that_doesnt_answer_is_rolled_back_with_its_database(updater):
    home, local, c, calls, world = updater
    world["answers"] = False
    before = update.status(home)["from"]
    s = update.run(home, local, 8765)
    assert s["state"] == "rolled_back"
    assert git(local, "rev-parse", "HEAD") == before
    assert _meta(home, "new-version-was-here") is None        # the database as it was before the restart
    assert "bootout" in calls and "bootstrap" in calls
    assert not (home / "update" / update.SNAPSHOT).exists()


def test_report_records_the_outcome_once(updater):
    home, local, *_ = updater
    update.run(home, local, 8765)
    k = Kernel(home)
    try:
        update.report(k)
        update.report(k)
        done = [e for e in k.audit.entries(limit=20) if e["event"] == "update.finished"]
        assert len(done) == 1 and done[0]["payload"]["outcome"] == "done"
    finally:
        k.close()


def test_start_refuses_without_the_mac_service_or_from_jarvis(tmp_path, monkeypatch):
    k = Kernel(tmp_path / "home")
    try:
        with pytest.raises(PermissionError):
            update.start(k, by="jarvis")
        monkeypatch.setattr(sys, "platform", "linux")
        with pytest.raises(update.UpdateError, match="background service on the Mac"):
            update.start(k, by="user:dashboard")
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.setattr(update.service, "is_loaded", lambda: True)
        k.killswitch.engage(by="user:cli", reason="test")
        with pytest.raises(update.UpdateError, match="emergency stop"):
            update.start(k, by="user:dashboard")
    finally:
        k.close()


def test_a_dead_helper_shows_as_failed(tmp_path):
    home = tmp_path / "home"
    update._write(home, {"state": "running", "pid": 999999999, "steps": []})
    assert update.status(home)["state"] == "failed"


def test_update_and_backup_routes_are_mac_only_and_update_needs_touch_id():
    import re

    from jarvis.remote import LOCAL_ONLY
    from jarvis.remote.mac import MAC_STEP_UP
    for path in ("/api/update", "/api/update/check", "/api/update/start", "/api/backup/now"):
        assert any(re.fullmatch(p, path) for p in LOCAL_ONLY), path
    assert any(re.fullmatch(p, "/api/update/start") for p in MAC_STEP_UP)


def test_dashboard_routes(dash, monkeypatch):
    d, *_ = dash
    monkeypatch.setattr(update, "check", lambda repo=None: {"can_update": False, "why": "already up to date", "behind": 0})
    status, _, body = call(d, "/api/update/check", {})
    assert status == 200 and json.loads(body)["why"] == "already up to date"
    assert call(d, "/api/update/start", {})[0] == 400          # not the Mac service here: refused with a reason
    assert "update" in json.loads(call(d, "/api/state")[2])
    assert call(d, "/api/health/check", {})[0] == 200
