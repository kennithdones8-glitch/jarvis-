"""Mac checkup: look-only, fixed commands, clear advice; one broken check never hides the others."""

import subprocess
import time
from pathlib import Path

from jarvis.checkup import INFO, OK, SKIP, WARN, Checkup, report

NOW = time.mktime(time.strptime("2026-11-07 12:00", "%Y-%m-%d %H:%M"))
SPPOWER = "Battery Information:\n  Health Information:\n    Cycle Count: 412\n    Condition: Normal\n"
UPDATES = ("Software Update Tool\n\nSoftware Update found the following new or updated software:\n"
           "* Label: macOS Sonoma 14.7.1-23H222\n\tTitle: macOS Sonoma 14.7.1, Version: 14.7.1\n")


def fake(outputs: dict, calls: list):
    def run(args, timeout):
        calls.append(args)
        for key, out in outputs.items():
            if key in " ".join(args):
                if isinstance(out, Exception):
                    raise out
                return out
        raise subprocess.CalledProcessError(1, args)
    return run


def mac(tmp_path, **extra):
    calls: list = []
    outputs = {"sw_vers": "14.1.1\n", "hw.memsize": str(32 * 1024**3), "vm.swapusage": "total = 2048.00M  used = 512.00M",
               "SPPowerDataType": SPPOWER, "kern.boottime": f"{{ sec = {int(NOW - 20 * 86400)}, usec = 0 }}",
               "tmutil": "/Volumes/Backup/Backups.backupdb/Mac/2026-11-06-101500\n",
               "ps": "%CPU COMM\n 85.0 mds_stores\n 30.2 Safari\n  1.0 Finder\n", "du": "1024\t/x\n"}
    outputs.update(extra)
    return Checkup(run=fake(outputs, calls), home=tmp_path, platform="darwin", now=NOW), calls


def by(findings):
    return {f.name: f for f in findings}


def test_a_full_checkup_on_the_owners_mac(tmp_path):
    (tmp_path / "Downloads").mkdir()
    c, calls = mac(tmp_path)
    r = by(c.all())
    assert r["macOS"].status == WARN and "14.1.1" in r["macOS"].detail and "Software Update" in r["macOS"].advice
    assert r["Battery"].status == OK and "412 cycles" in r["Battery"].detail
    assert r["Last restart"].status == INFO and "20 day" in r["Last restart"].detail
    assert r["Time Machine"].status == OK and r["Memory"].status == OK
    assert "Software updates" not in r  # only with --updates (the one check that uses the network)
    assert "mds_stores 85%" in r["CPU"].detail or r["CPU"].status in (OK, WARN)
    text = report(c.all())
    assert text.startswith("Mac checkup (look only: nothing was changed)")


def test_only_fixed_read_only_commands_are_run(tmp_path):
    (tmp_path / "Downloads").mkdir()
    c, calls = mac(tmp_path)
    c.all(updates=True)
    allowed = {"/usr/bin/sw_vers", "/usr/sbin/softwareupdate", "/usr/bin/du", "/bin/ps", "/usr/sbin/sysctl",
               "/usr/sbin/system_profiler", "/usr/bin/tmutil"}
    assert {a[0] for a in calls} <= allowed
    for a in calls:  # never an install, delete, restart or shell
        assert not set(a) & {"--install", "-i", "--restart", "-r", "rm", "sh", "-c", "delete"} or a[0] == "/bin/ps"
    assert ["/usr/sbin/softwareupdate", "--list"] in calls


def test_waiting_updates_are_listed_and_left_to_you(tmp_path):
    c, _ = mac(tmp_path, softwareupdate=UPDATES)
    f = c.software_updates()
    assert f.status == WARN and "macOS Sonoma 14.7.1" in f.detail and "never installs" in f.advice


def test_a_broken_check_is_reported_and_the_rest_still_run(tmp_path):
    c, _ = mac(tmp_path, SPPowerDataType=subprocess.TimeoutExpired(["system_profiler"], 20))
    r = by(c.all())
    assert r["Battery"].status == SKIP and "couldn't check" in r["Battery"].detail
    assert r["macOS"].status == WARN and r["Time Machine"].status == OK


def test_no_time_machine_and_old_backups_are_flagged(tmp_path):
    c, _ = mac(tmp_path, tmutil=subprocess.CalledProcessError(1, ["tmutil"]))
    assert c.time_machine().status == WARN
    c, _ = mac(tmp_path, tmutil="/Volumes/B/2026-10-01-090000\n")
    assert c.time_machine().status == WARN and "37 day" in c.time_machine().detail


def test_not_a_mac_skips_mac_only_checks(tmp_path):
    c = Checkup(run=lambda a, t: (_ for _ in ()).throw(AssertionError("no commands")), home=tmp_path, platform="linux")
    r = by(c.all(updates=True))
    assert r["macOS"].status == SKIP and r["Battery"].status == SKIP and r["Disk space"].status in (OK, WARN)


def test_cli_records_counts_only(tmp_path, capsys, monkeypatch):
    from jarvis import checkup
    from jarvis.cli import main
    monkeypatch.setattr(checkup.Checkup, "all", lambda self, updates=False: [
        checkup.Finding("CPU", WARN, "load 3.4 · busiest: SecretApp 90%", "quit it")])
    assert main(["--home", str(tmp_path / "home"), "checkup"]) == 0
    assert "SecretApp" in capsys.readouterr().out  # shown to you
    from jarvis.core import Kernel
    k = Kernel(tmp_path / "home")
    [ev] = [e for e in k.audit.entries(limit=50) if e["event"] == "checkup.run"]
    assert ev["payload"] == {"checks": 1, "warnings": 1, "updates": False} and "SecretApp" not in str(ev)
    assert Path(tmp_path / "home").exists()
