"""Commands that don't use your data never open it, so they can never upgrade it.

Real case (16 Nov 2026): `jarvis gate` run in a branch's folder opened the real data folder and upgraded its database
from v12 to v13, which the installed JARVIS (v12) then refused to open."""

import sqlite3
from types import SimpleNamespace

import pytest

from jarvis.cli import main
from jarvis.core.db import SCHEMA_VERSION, schema_of


def _older_db(home, version=SCHEMA_VERSION - 1):
    home.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(home / "jarvis.db")
    conn.execute(f"PRAGMA user_version = {version}")
    conn.commit()
    conn.close()
    return home / "jarvis.db"


@pytest.fixture
def fake_gate(monkeypatch):
    from jarvis import gate
    monkeypatch.setattr(gate, "run", lambda: SimpleNamespace(passed=True))
    monkeypatch.setattr(gate, "report", lambda r: "gate: PASS")


def test_gate_leaves_an_older_data_folder_as_it_is(tmp_path, fake_gate, capsys):
    db = _older_db(tmp_path / "home")
    assert main(["--home", str(tmp_path / "home"), "gate"]) == 0
    assert schema_of(db) == SCHEMA_VERSION - 1 and "PASS" in capsys.readouterr().out


def test_gate_doesnt_even_create_a_data_folder(tmp_path, fake_gate):
    assert main(["--home", str(tmp_path / "nothing-here"), "gate"]) == 0
    assert not (tmp_path / "nothing-here").exists()


def test_bench_reports_and_comparisons_dont_open_data(tmp_path, capsys):
    db = _older_db(tmp_path / "home")
    assert main(["--home", str(tmp_path / "home"), "bench", "list"]) == 0
    assert "planning-free" in capsys.readouterr().out
    assert main(["--home", str(tmp_path / "home"), "bench", "compare"]) == 1   # no runs: usage, but nothing opened
    assert main(["--home", str(tmp_path / "home"), "bench", "rescore"]) == 1
    assert schema_of(db) == SCHEMA_VERSION - 1


def _fake_drills(monkeypatch, passed=True):
    from jarvis import drill
    monkeypatch.setattr(drill, "run", lambda only=None: [SimpleNamespace(passed=passed)])
    monkeypatch.setattr(drill, "report", lambda results: "drills: done")


def test_drill_on_an_older_data_folder_runs_but_records_nothing(tmp_path, monkeypatch, capsys):
    _fake_drills(monkeypatch)
    db = _older_db(tmp_path / "home")
    assert main(["--home", str(tmp_path / "home"), "drill"]) == 0
    assert schema_of(db) == SCHEMA_VERSION - 1
    assert "Your data was left as it is" in capsys.readouterr().err


def test_drill_still_counts_toward_the_milestone_when_versions_match(tmp_path, monkeypatch, make_kernel):
    from jarvis.core import Kernel
    _fake_drills(monkeypatch)
    home = tmp_path / "current"
    Kernel(home).close()   # data at this code's version
    assert main(["--home", str(home), "drill"]) == 0
    k = Kernel(home)
    try:
        assert any(e["event"] == "evolution.check" for e in k.audit.entries())
    finally:
        k.close()


def test_too_new_points_to_the_backup_made_before_the_upgrade(tmp_path, capsys):
    from jarvis.core.kernel import UPGRADE_BACKUPS
    home = tmp_path / "home"
    _older_db(home, SCHEMA_VERSION + 1)
    saved = home / "backups" / UPGRADE_BACKUPS
    saved.mkdir(parents=True)
    (saved / "jarvis-20261116-101500.jbak").write_bytes(b"x")
    assert main(["--home", str(home), "status"]) == 1
    err = capsys.readouterr().err
    assert "newer than this code" in err and "jarvis-20261116-101500.jbak" in err and "ask before restoring" in err
