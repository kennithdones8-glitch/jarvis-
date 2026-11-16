"""A second copy of the backups, off this Mac: the folder is checked and chosen only by you (Mac only, Touch ID), each
copy is checked byte for byte, an unplugged drive is caught up later, and "Test restore" opens the newest copy
without replacing anything."""

import json
import re

import pytest
from test_dashboard import call

from jarvis import backup as bk

PHRASE = "correct horse battery staple test phrase"


@pytest.fixture
def ddash(dash, monkeypatch):
    monkeypatch.setenv("JARVIS_BACKUP_PASSPHRASE", PHRASE)
    return dash


def test_folder_is_checked(tmp_path):
    home, prim = tmp_path / "home", tmp_path / "home" / "backups"
    prim.mkdir(parents=True)
    for bad in ("", "relative/dir", str(tmp_path / "missing"), str(home), str(prim), str(home / "backups" / "x"),
                str(tmp_path / "a" / ".." / "b")):
        if bad == str(home / "backups" / "x"):
            (home / "backups" / "x").mkdir()
        with pytest.raises(bk.BackupError):
            bk.check_copy_folder(bad, home, prim)
    drive = tmp_path / "Drive"
    drive.mkdir()
    made = bk.check_copy_folder(str(drive / bk.COPY_FOLDER), home, prim)   # the suggested folder is created
    assert made.is_dir()


def test_places_list_drives_and_icloud(tmp_path):
    vols = tmp_path / "Volumes"
    (vols / "Backup Drive").mkdir(parents=True)
    (vols / ".hidden").mkdir()
    icloud = tmp_path / "Library/Mobile Documents/com~apple~CloudDocs"
    icloud.mkdir(parents=True)
    places = bk.copy_places(vols, home=tmp_path)
    assert [p["label"] for p in places] == ["Drive “Backup Drive”", "iCloud Drive"]
    assert all(p["path"].endswith(bk.COPY_FOLDER) for p in places)


def test_copy_is_verified_and_pruned(tmp_path):
    src_dir, dest = tmp_path / "src", tmp_path / "dest"
    src_dir.mkdir(), dest.mkdir()
    for i in range(4):
        f = src_dir / f"jarvis-2026111{i}-000000.jbak"
        f.write_bytes(b"JBAK1" + bytes([i]) * 1000)
        bk.copy_out(f, dest, keep=2)
    assert [p.name for p in bk.list_backups(dest)] == ["jarvis-20261113-000000.jbak", "jarvis-20261112-000000.jbak"]
    assert not list(dest.glob(".*partial"))


def test_routes_are_mac_only_and_choosing_needs_touch_id():
    from jarvis.remote import LOCAL_ONLY
    from jarvis.remote.mac import MAC_STEP_UP
    for p in ("/api/backup/test", "/api/backup/now", "/api/settings/backup-copy"):
        assert any(re.fullmatch(x, p) for x in LOCAL_ONLY), p
    assert any(re.fullmatch(x, "/api/settings/backup-copy") for x in MAC_STEP_UP)


def test_second_copy_end_to_end(ddash, tmp_path):
    d, *_ = ddash
    drive = tmp_path / "Drive"
    drive.mkdir()
    assert json.loads(call(d, "/api/state")[2])["backup_copy"]["set"] is False
    assert call(d, "/api/settings/backup-copy", {"folder": str(d.kernel.home)})[0] == 400
    status, _, body = call(d, "/api/settings/backup-copy", {"folder": str(drive)})
    assert status == 200 and json.loads(body)["set"] is True
    r = json.loads(call(d, "/api/backup/now", {})[2])
    assert r["ok"] and r["copied"] and (drive / r["file"]).exists()
    t = json.loads(call(d, "/api/backup/test", {})[2])
    assert t["ok"] and t["where"] == "second copy" and isinstance(t["audit_entries"], int) and "tasks" in t["counts"]
    # a damaged copy is reported, not hidden
    (drive / t["file"]).write_bytes(b"JBAK1" + b"\0" * 64)
    t = json.loads(call(d, "/api/backup/test", {})[2])
    assert t["ok"] is False and t["error"]
    events = [e["event"] for e in d.kernel.audit.entries(limit=100)]
    assert "backup.copied" in events and "backup.tested" in events and "backup.copy_folder" in events
    health = {i["name"]: i for i in json.loads(call(d, "/api/health/check", {})[2])["items"]}
    assert health["Second copy"]["ok"]
    assert call(d, "/api/settings/backup-copy", {"folder": ""})[0] == 200
    assert json.loads(call(d, "/api/state")[2])["backup_copy"]["set"] is False


def test_an_unplugged_drive_is_caught_up(ddash, tmp_path):
    d, *_ = ddash
    drive = tmp_path / "Drive"
    drive.mkdir()
    call(d, "/api/settings/backup-copy", {"folder": str(drive)})
    drive.rename(tmp_path / "away")                                  # unplugged
    f = json.loads(call(d, "/api/backup/now", {})[2])["file"]
    assert d.backup_copy_status()["connected"] is False
    (tmp_path / "away").rename(drive)                                # back
    d.sync_offsite()                                                 # (the dashboard's own loop may get there first)
    assert (drive / f).exists()                                      # every backup made while it was away
    assert d.sync_offsite() is None                                  # nothing left to copy
