"""Recovery drills: they pass on a healthy JARVIS, and each one FAILS when the protection it checks is broken,
so a passing drill means something. Crash drills use real child processes killed mid-action."""

import pytest

from jarvis import drill
from jarvis.core.approvals import APPROVED, Approvals
from jarvis.core.audit import AuditLog, VerifyResult
from jarvis.core.killswitch import KillSwitch


def by_name(results):
    return {r.name: r for r in results}


def test_all_drills_pass_on_a_healthy_jarvis():
    results = drill.run()
    assert len(results) == len(drill.DRILLS) == 10
    assert [r.name for r in results if not r.passed] == [], drill.report(results)


def test_drills_leave_nothing_behind(tmp_path, monkeypatch):
    monkeypatch.setattr(drill.tempfile, "tempdir", str(tmp_path))
    drill.run(["checkpoint", "audit"])
    assert list(tmp_path.iterdir()) == []


def test_audit_drill_fails_if_tampering_goes_unnoticed(monkeypatch):
    monkeypatch.setattr(AuditLog, "verify", lambda self: VerifyResult(True, 1))
    assert by_name(drill.run(["audit"]))["Tampered audit log"].passed is False


def test_race_drill_fails_if_one_approval_could_be_spent_twice(monkeypatch):
    def leaky_claim(self, *, task_id, tool, action, resource, digest):  # finds it but never marks it used
        row = self.db.one("SELECT id FROM approvals WHERE state = ? AND task_id IS ? AND tool = ? AND action = ? "
                          "AND resource IS ? AND args_hash = ?", (APPROVED, task_id, tool, action, resource, digest))
        return row["id"] if row else None
    monkeypatch.setattr(Approvals, "claim", leaky_claim)
    r = by_name(drill.run(["racing"]))["Two callers racing for one approval"]
    assert r.passed is False and "spent" in r.detail


def test_stop_drill_fails_if_the_stop_is_ignored(monkeypatch):
    monkeypatch.setattr(KillSwitch, "check", lambda self: None)
    assert by_name(drill.run(["emergency"]))["Emergency stop from another process"].passed is False


def test_restore_drill_never_uses_the_keychain(monkeypatch):
    from jarvis import backup

    def no(*a, **k):
        raise AssertionError("the drill touched the Keychain")
    monkeypatch.setattr(backup, "_keychain_get", no)
    monkeypatch.setattr(backup, "_keychain_set", no)
    monkeypatch.delenv("JARVIS_BACKUP_PASSPHRASE", raising=False)
    assert by_name(drill.run(["restore"]))["Lost database, restore from backup"].passed is True


def test_cli(tmp_path, capsys):
    from jarvis.cli import main as cli_main
    assert cli_main(["--home", str(tmp_path / "home"), "drill", "checkpoint"]) == 0
    assert "1/1 passed" in capsys.readouterr().out
    assert cli_main(["--home", str(tmp_path / "home"), "drill", "no-such-drill"]) == 1  # nothing ran: not a pass


@pytest.mark.parametrize("name", [n for n, _ in drill.DRILLS])
def test_each_drill_has_a_plain_name(name):
    assert name[0].isupper() and len(name) <= 40
