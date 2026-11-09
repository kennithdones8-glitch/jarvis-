"""Keep JARVIS's data folder private to you (owner-approved, 0.18.2).

The folder holds your conversations, memories, audit log and settings. If it was made with your Mac's default
permissions (``drwxr-xr-x``), other accounts on the Mac could read it. On every start JARVIS makes the folder
``drwx------`` (only you) and its database files ``-rw-------``. It only ever *removes* access for others, only on a
folder you own, never follows into other places, and records what it changed (modes only, never contents).
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

DB_FILES = ("jarvis.db", "jarvis.db-wal", "jarvis.db-shm")


def _tighten(path: Path, private: int) -> str | None:
    """Remove group/other access from ``path`` if it's ours. Returns "old→new" when it changed something."""
    try:
        st = path.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(st.st_mode) or st.st_uid != os.getuid() or not st.st_mode & 0o077:
        return None
    old = stat.S_IMODE(st.st_mode)
    new = old & private
    os.chmod(path, new)
    return f"{old:o}→{new:o}"


def make_private(home: Path) -> dict[str, str]:
    """Make the data folder and its database files readable by you only. Returns what changed (name → modes)."""
    changed = {}
    if (c := _tighten(home, 0o700)) is not None:
        changed["data folder"] = c
    for name in DB_FILES:
        if (c := _tighten(home / name, 0o600)) is not None:
            changed[name] = c
    return changed


def is_private(home: Path) -> bool:
    return not stat.S_IMODE(home.stat().st_mode) & 0o077
