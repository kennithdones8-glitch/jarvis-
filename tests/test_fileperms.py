"""Data folder privacy: other accounts on the Mac can't read your conversations, memories or audit log."""

import os
import stat

from jarvis.core import Kernel
from jarvis.core.fileperms import is_private, make_private
from jarvis.doctor import OK, WARN, Doctor


def mode(p):
    return stat.S_IMODE(p.stat().st_mode)


def events(k):
    return [e["payload"] for e in k.audit.entries(limit=50) if e["event"] == "privacy.files_made_private"]


def test_a_new_data_folder_starts_private(tmp_path):
    k = Kernel(tmp_path / "home")
    assert mode(k.home) == 0o700 and mode(k.home / "jarvis.db") == 0o600
    assert events(k) == []  # nothing to fix, nothing recorded


def test_an_open_data_folder_is_made_private_on_start_and_recorded(tmp_path):
    # the owner's Mac (0.18.0): drwxr-xr-x folder, -rw-r--r-- jarvis.db
    home = tmp_path / "home"
    Kernel(home)  # a first start, as before this change
    os.chmod(home, 0o755)
    os.chmod(home / "jarvis.db", 0o644)
    k = Kernel(home)
    assert mode(home) == 0o700 and mode(home / "jarvis.db") == 0o600 and is_private(home)
    for name in ("jarvis.db-wal", "jarvis.db-shm"):
        if (home / name).exists():
            assert not mode(home / name) & 0o077
    [ev] = events(k)
    assert ev["changed"]["data folder"] == "755→700" and ev["changed"]["jarvis.db"] == "644→600"
    assert events(Kernel(home)) == [ev]  # already private: the next start changes and records nothing


def test_it_only_ever_removes_access_for_others(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    os.chmod(home, 0o751)
    (home / "jarvis.db").write_bytes(b"")
    os.chmod(home / "jarvis.db", 0o440)  # read-only for you stays read-only
    make_private(home)
    assert mode(home) == 0o700 and mode(home / "jarvis.db") == 0o400


def test_a_symlink_is_not_followed(tmp_path):
    elsewhere = tmp_path / "elsewhere.db"
    elsewhere.write_bytes(b"")
    os.chmod(elsewhere, 0o644)
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    (home / "jarvis.db").symlink_to(elsewhere)
    assert make_private(home) == {}
    assert mode(elsewhere) == 0o644


def test_doctor_warns_while_others_can_read_it(make_kernel):
    k = make_kernel()
    by = lambda: {c.name: c for c in Doctor(k, port=1, voice_test=False).run()}["Data folder privacy"]  # noqa: E731
    assert by().status == OK
    os.chmod(k.home, 0o755)
    check = by()
    assert check.status == WARN and "other accounts" in check.detail and "restart" in check.fix.lower()
