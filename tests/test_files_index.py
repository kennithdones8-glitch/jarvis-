"""File search: off until you turn it on, reads only files inside your approved folders (each checked by the
permission engine), keeps nothing once turned off, and is reachable only on the Mac."""

import json
import os
import re

import pytest
from test_dashboard import call

from jarvis import files_index
from jarvis.core.db import SCHEMA_VERSION


@pytest.fixture
def k(make_kernel):
    return make_kernel()


def _seed(root):
    (root / "lease.md").write_text("Flat lease agreement, rent due on the first of the month.")
    (root / "notes" / "recipe.txt").write_text("Lemon cake: flour, sugar, eggs.")
    (root / ".secret.txt").write_text("hidden lease details")
    (root / ".hidden").mkdir()
    (root / ".hidden" / "x.md").write_text("lease in a hidden folder")
    (root / "photo.jpg").write_bytes(b"\xff\xd8 lease")


def test_schema_has_the_index():
    assert SCHEMA_VERSION >= 12


def test_off_by_default_and_only_you_turn_it_on(k, root):
    _seed(root)
    assert not files_index.enabled(k)
    assert files_index.refresh(k) == {"indexed": 0, "removed": 0}
    assert files_index.search(k, "lease") == []
    with pytest.raises(PermissionError):
        files_index.set_enabled(k, True, by="jarvis")
    assert files_index.set_enabled(k, True, by="user:dashboard")["on"] is True


def test_indexes_only_visible_supported_files_in_approved_folders(k, root, tmp_path):
    _seed(root)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "lease.md").write_text("another lease, outside the approved folder")
    files_index.set_enabled(k, True, by="user:dashboard")
    assert files_index.refresh(k)["indexed"] == 2
    hits = files_index.search(k, "lease")
    assert [h["name"] for h in hits] == ["lease.md"] and str(outside) not in hits[0]["path"]
    assert "[lease]" in hits[0]["snippet"].lower()
    assert files_index.search(k, "lemon")[0]["name"] == "recipe.txt"
    assert files_index.refresh(k)["indexed"] == 0          # unchanged files aren't read again


def test_changes_and_deletions_are_followed(k, root):
    _seed(root)
    files_index.set_enabled(k, True, by="user:dashboard")
    files_index.refresh(k)
    p = root / "notes" / "recipe.txt"
    p.write_text("Orange cake now.")
    os.utime(p, (1, 1))
    assert files_index.refresh(k)["indexed"] == 1
    assert files_index.search(k, "lemon") == [] and files_index.search(k, "orange")
    (root / "lease.md").unlink()
    assert files_index.refresh(k)["removed"] == 1 and files_index.search(k, "lease") == []


def test_denied_files_are_never_read(k, root, monkeypatch):
    _seed(root)
    files_index.set_enabled(k, True, by="user:dashboard")
    monkeypatch.setattr(files_index, "_allowed", lambda kernel, p: p.name != "lease.md")
    files_index.refresh(k)
    assert files_index.search(k, "lease") == [] and files_index.search(k, "lemon")


def test_turning_off_deletes_the_index(k, root):
    _seed(root)
    files_index.set_enabled(k, True, by="user:dashboard")
    files_index.refresh(k)
    files_index.set_enabled(k, False, by="user:dashboard")
    assert k.db.one("SELECT COUNT(*) FROM file_index")[0] == 0
    assert k.db.one("SELECT COUNT(*) FROM file_index_meta")[0] == 0


def test_forget_drops_and_keeps_out_matching_files(k, root):
    _seed(root)
    files_index.set_enabled(k, True, by="user:dashboard")
    files_index.refresh(k)
    assert files_index.forget(k, "lease") == 1                       # preview changes nothing
    assert files_index.search(k, "lease")
    k.forget("lease", by="user:cli", dry_run=False)
    assert files_index.search(k, "lease") == []
    os.utime(root / "lease.md", (2, 2))
    files_index.refresh(k)
    assert files_index.search(k, "lease") == []                      # stays out


def test_routes_are_mac_only_and_switch_needs_touch_id():
    from jarvis.remote import LOCAL_ONLY
    from jarvis.remote.mac import MAC_STEP_UP
    assert any(re.fullmatch(p, "/api/files/search") for p in LOCAL_ONLY)
    assert any(re.fullmatch(p, "/api/settings/files") for p in LOCAL_ONLY)
    assert any(re.fullmatch(p, "/api/settings/files") for p in MAC_STEP_UP)


def test_dashboard_switch_and_search(dash):
    d, _, root = dash
    _seed(root)
    assert json.loads(call(d, "/api/state")[2])["files"]["on"] is False
    assert call(d, "/api/settings/files", {"on": True})[0] == 200
    d.files_tick()
    data = json.loads(call(d, "/api/files/search?q=lease")[2])
    assert data["on"] is True and [r["name"] for r in data["results"]] == ["lease.md"]
    assert call(d, "/api/settings/files", {"on": "yes"})[0] == 400
