"""Updates are safe: an existing database is backed up (encrypted, verified) before this code upgrades it, a Mac
refuses to upgrade without that backup, and a command that ends up doing nothing never opens (or upgrades) the data."""

import sqlite3
import sys

import pytest

from jarvis import backup
from jarvis.core import Kernel
from jarvis.core.db import MIGRATIONS, SCHEMA_VERSION, schema_of
from jarvis.core.kernel import UPGRADE_BACKUPS, UpgradeBlocked


def _old_database(home, version=SCHEMA_VERSION - 1):
    home.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(home / "jarvis.db")
    for v in range(1, version + 1):
        conn.executescript(f"BEGIN;\n{MIGRATIONS[v - 1]}\nPRAGMA user_version = {v};\nCOMMIT;")
    conn.close()
    return home / "jarvis.db"


def test_upgrade_is_backed_up_first(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_BACKUP_PASSPHRASE", "test-phrase-1234")
    db = _old_database(tmp_path / "home")
    k = Kernel(tmp_path / "home")
    try:
        assert k.db.schema_version == SCHEMA_VERSION
        made = sorted((tmp_path / "home" / "backups" / UPGRADE_BACKUPS).glob("*.jbak"))
        assert len(made) == 1
        entry = next(e for e in k.audit.entries(limit=20) if e["event"] == "database.upgraded")
        assert entry["payload"] == {"from_version": SCHEMA_VERSION - 1, "to_version": SCHEMA_VERSION,
                                    "backup": made[0].name}
    finally:
        k.close()
    assert backup.verify_backup(made[0], "test-phrase-1234")  # decrypts and checks out
    assert schema_of(db) == SCHEMA_VERSION


def test_the_backup_holds_the_old_version(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_BACKUP_PASSPHRASE", "test-phrase-1234")
    _old_database(tmp_path / "home")
    Kernel(tmp_path / "home").close()
    made = next((tmp_path / "home" / "backups" / UPGRADE_BACKUPS).glob("*.jbak"))
    into = tmp_path / "opened"
    into.mkdir()
    backup._open(made, "test-phrase-1234", into)
    assert schema_of(into / "jarvis.db") == SCHEMA_VERSION - 1


def test_a_new_or_current_database_makes_no_upgrade_backup(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_BACKUP_PASSPHRASE", "test-phrase-1234")
    Kernel(tmp_path / "home").close()   # new
    Kernel(tmp_path / "home").close()   # already current
    assert not (tmp_path / "home" / "backups" / UPGRADE_BACKUPS).exists()


def test_a_mac_refuses_to_upgrade_without_a_backup(tmp_path, monkeypatch):
    db = _old_database(tmp_path / "home")
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.delenv("JARVIS_UPGRADE_WITHOUT_BACKUP", raising=False)

    def broken(*a, **k):
        raise backup.BackupError("Keychain locked")
    monkeypatch.setattr(backup, "create_backup", broken)
    with pytest.raises(UpgradeBlocked, match="Nothing was changed"):
        Kernel(tmp_path / "home")
    assert schema_of(db) == SCHEMA_VERSION - 1   # untouched
    monkeypatch.setenv("JARVIS_UPGRADE_WITHOUT_BACKUP", "1")   # the owner's explicit way out
    k = Kernel(tmp_path / "home")
    try:
        entry = next(e for e in k.audit.entries(limit=20) if e["event"] == "database.upgraded")
        assert entry["payload"]["backup"] is None and "Keychain locked" in entry["payload"]["backup_problem"]
    finally:
        k.close()


def test_dashboard_already_running_never_opens_the_data(tmp_path, monkeypatch, capsys):
    from jarvis import cli, service

    monkeypatch.setattr(service, "responding", lambda port=8765: True)

    def must_not_open(*a, **k):
        raise AssertionError("the data was opened")
    monkeypatch.setattr(cli, "Kernel", must_not_open)
    assert cli.main(["--home", str(tmp_path / "home"), "dashboard", "--no-open"]) == 0
    assert "already running" in capsys.readouterr().out


def test_startup_message_for_a_blocked_upgrade():
    from jarvis.cli import _startup_problem
    msg = _startup_problem(UpgradeBlocked("JARVIS needs to upgrade … Nothing was changed."), None)
    assert msg.startswith("error: JARVIS needs to upgrade") and "Traceback" not in msg
