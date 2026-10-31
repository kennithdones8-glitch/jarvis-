import plistlib
import time

import pytest

from jarvis import backup as bk
from jarvis.cli import main as cli_main
from jarvis.server import Dashboard
from jarvis.service import build_plist, dashboard_token

PHRASE = "test-passphrase-0001"


@pytest.fixture
def k(make_kernel, monkeypatch):
    monkeypatch.setenv("JARVIS_BACKUP_PASSPHRASE", PHRASE)
    return make_kernel(registry="default")


def backup(k, **kw):
    return bk.create_backup(k.home, k.policy_path, k.policy_path.with_name("missing.toml"), **kw)


def test_backup_is_encrypted_verified_and_restores_with_deletions_kept(k, tmp_path):
    mid_keep = k.memory.remember("Prefers tea over coffee", by="user:test")
    mid_gone = k.memory.remember("Old address is 12 Elm Street", by="user:test")
    rec = k.memory.add_record("s", "user", "secret plans for the surprise party")
    r = backup(k)
    assert r.verified and r.path.suffix == ".jbak" and r.detail["counts"]["memories"] == 2
    raw = r.path.read_bytes()
    assert raw.startswith(b"JBAK1") and b"Elm Street" not in raw and b"SQLite" not in raw   # actually encrypted
    # after the backup: you delete a memory and a conversation record, and add something new
    k.memory.delete(mid_gone, by="user:test")
    k.memory.delete_record(rec, by="user:test")
    k.memory.remember("Started learning guitar", by="user:test")
    k.close()
    res = bk.restore_backup(r.path, k.home, k.policy_path, k.policy_path.with_name("missing.toml"))
    assert res["reapplied_deletions"] == {"memories": 1, "records": 1}       # deleted data did NOT come back
    from jarvis.core import Kernel
    k2 = Kernel(k.home, policy_path=k.policy_path, config_path=k.policy_path.with_name("missing.toml"))
    texts = {m["text"] for m in k2.memory.list()}
    assert texts == {"Prefers tea over coffee"} and mid_keep
    assert k2.memory.search_records("surprise party") == []
    assert any(p.name.startswith("jarvis.db.before-restore-") for p in k.home.iterdir())  # old state kept
    assert k2.audit.verify().ok and k2.audit.entries()[-1]["event"] == "backup.restored"
    k2.close()


def test_wrong_passphrase_and_tampering_detected(k):
    r = backup(k)
    with pytest.raises(bk.BackupError, match="wrong passphrase"):
        bk.verify_backup(r.path, "not-the-passphrase")
    data = bytearray(r.path.read_bytes())
    data[60] ^= 0xFF
    r.path.write_bytes(bytes(data))
    with pytest.raises(bk.BackupError, match="damaged"):
        bk.verify_backup(r.path)
    r.path.write_bytes(b"hello")
    with pytest.raises(bk.BackupError, match="not a JARVIS backup"):
        bk.verify_backup(r.path)


def test_retention_keeps_newest(k, tmp_path):
    folder = tmp_path / "bk"
    for i in range(4):
        (folder).mkdir(exist_ok=True)
        r = backup(k, dest_dir=folder, keep=2)
        time.sleep(1.05)
    assert len(bk.list_backups(folder)) == 2 and bk.list_backups(folder)[0] == r.path


def test_no_passphrase_means_no_silent_backup(k, monkeypatch):
    monkeypatch.delenv("JARVIS_BACKUP_PASSPHRASE")
    d = Dashboard(k, port=0, token="t")
    try:
        assert d.maybe_backup() is None                                   # never creates a passphrase you haven't seen
        health = d.check_health()
        b = next(i for i in health["items"] if i["name"] == "Backups")
        assert not b["ok"] and "jarvis backup now" in b["detail"]
    finally:
        d.shutdown()


def test_daily_auto_backup_and_health(k):
    d = Dashboard(k, port=0, token="t")
    try:
        assert d.maybe_backup()["ok"] is True
        assert d.maybe_backup() is None                                   # not again within 24 h
        h = d.check_health()
        names = {i["name"]: i for i in h["items"]}
        assert names["Database"]["ok"] and names["Audit log"]["ok"] and names["Backups"]["ok"]
        assert any(e["event"] == "backup.created" for e in k.audit.entries())
    finally:
        d.shutdown()


def test_cli_backup_commands(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("JARVIS_BACKUP_PASSPHRASE", PHRASE)
    home = tmp_path / "jh"
    assert cli_main(["--home", str(home), "init"]) == 0
    assert cli_main(["--home", str(home), "remember", "Has a dog called Max"]) == 0
    assert cli_main(["--home", str(home), "backup", "now"]) == 0
    [file] = bk.list_backups(home / "backups")
    assert cli_main(["--home", str(home), "backup", "verify", str(file)]) == 0
    assert cli_main(["--home", str(home), "backup", "restore", str(file)]) == 0     # without --yes: explains only
    assert "Add --yes" in capsys.readouterr().out
    assert cli_main(["--home", str(home), "backup", "restore", str(file), "--yes"]) == 0
    assert "Restored" in capsys.readouterr().out


def test_launch_agent_plist(tmp_path):
    data = plistlib.loads(build_plist(home=tmp_path, uv="/Users/me/.local/bin/uv", port=8765,
                                      path_env="/Users/me/.local/bin:/usr/local/bin:/usr/bin:/bin"))
    assert data["Label"] == "com.jarvis.dashboard" and data["RunAtLoad"] is True
    assert data["KeepAlive"] == {"SuccessfulExit": False}                      # restart on crash only
    assert data["ProgramArguments"][-4:] == ["dashboard", "--no-open", "--port", "8765"]
    assert "--home" not in data["ProgramArguments"]
    assert data["EnvironmentVariables"]["JARVIS_SERVICE"] == "1"
    assert "/Users/me/.local/bin" in data["EnvironmentVariables"]["PATH"]      # so it can find claude and uv
    custom = plistlib.loads(build_plist(home=tmp_path, uv="uv", custom_home=True))
    assert custom["ProgramArguments"][custom["ProgramArguments"].index("--home") + 1] == str(tmp_path)


def test_dashboard_token_stable_until_rotated(tmp_path):
    t1 = dashboard_token(tmp_path)
    assert dashboard_token(tmp_path) == t1 and len(t1) >= 32
    assert (tmp_path / "dashboard.token").stat().st_mode & 0o777 == 0o600
    assert dashboard_token(tmp_path, rotate=True) != t1


def test_service_refuses_off_macos(tmp_path):
    import sys
    from jarvis import service
    if sys.platform != "darwin":
        with pytest.raises(service.ServiceError, match="macOS"):
            service.install(tmp_path)
