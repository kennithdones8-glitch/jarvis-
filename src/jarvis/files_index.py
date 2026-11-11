"""File search: what's inside your approved folders, searchable in an instant ("where's the lease PDF?").

Off until you turn it on (Systems). Then the maintenance loop reads, a few dozen files at a time, only files inside
the folders you've approved for JARVIS (each read is checked with the permission engine first, as a Tier-0 read):
text, Markdown, CSV, JSON, HTML, PDF and Word files up to 20 MB, the first 20,000 characters of each. Hidden files
and folders are skipped. Nothing leaves the Mac and no model is involved.

Turning it off deletes the whole index. `forget` removes the entries of files that mention what you forget and keeps
those files out of the index. The index lives in JARVIS's database, so its encrypted backups contain it too.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .core.util import now_iso

ON = "files.index.on"
EXCLUDED = "files.index.excluded"
EXTS = {".txt", ".md", ".markdown", ".csv", ".json", ".html", ".htm", ".rtf", ".pdf", ".docx", ".log", ".yaml", ".yml", ".toml"}
MAX_BYTES = 20 * 1024 * 1024
MAX_CHARS = 20_000
PER_TICK = 40


def _meta(kernel, key: str, default: str = "") -> str:
    row = kernel.db.one("SELECT value FROM meta WHERE key = ?", (key,))
    return row["value"] if row else default


def _put(kernel, key: str, value: str) -> None:
    with kernel.db.tx() as c:
        c.execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


def enabled(kernel) -> bool:
    return _meta(kernel, ON) == "1"


def set_enabled(kernel, on: bool, *, by: str) -> dict[str, Any]:
    if not by.startswith("user"):
        raise PermissionError("only you can turn file search on or off")
    _put(kernel, ON, "1" if on else "0")
    if not on:
        with kernel.db.tx() as c:
            c.execute("DELETE FROM file_index")
            c.execute("DELETE FROM file_index_meta")
        kernel.db.checkpoint()
    kernel.audit.record("files.index", actor=by, on=on)
    return status(kernel)


def status(kernel) -> dict[str, Any]:
    n = kernel.db.one("SELECT COUNT(*) FROM file_index_meta")[0]
    return {"on": enabled(kernel), "files": n, "folders": [str(r) for r in kernel.policy.roots]}


def _allowed(kernel, path: Path) -> bool:
    from .core.permissions import Effect, ResourceKind, Tier
    d = kernel.permissions.evaluate(tool="fs", action="read", tier=Tier.READ, resource_kind=ResourceKind.PATH, resource=str(path))
    return d.effect is Effect.ALLOW


def _text(path: Path) -> str:
    from .tools import documents as docs
    ext = path.suffix.lower()
    if ext == ".pdf":
        r = docs.read_pdf(path)
    elif ext == ".docx":
        r = docs.read_docx(path)
    else:
        r = docs.read_text(path)
    return str(r.get("content") or "")[:MAX_CHARS]


def _candidates(kernel):
    for root in kernel.policy.roots:
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for f in files:
                if not f.startswith(".") and Path(f).suffix.lower() in EXTS:
                    yield Path(dirpath) / f


def refresh(kernel, *, per_tick: int = PER_TICK) -> dict[str, int]:
    """Index what's new or changed (at most ``per_tick`` files), and drop what's gone or no longer allowed."""
    if not enabled(kernel) or kernel.killswitch.engaged():
        return {"indexed": 0, "removed": 0}
    excluded = set(json.loads(_meta(kernel, EXCLUDED, "[]")))
    known = {r["path"]: (r["mtime"], r["size"]) for r in kernel.db.query("SELECT path, mtime, size FROM file_index_meta")}
    seen, indexed = set(), 0
    for p in _candidates(kernel):
        sp = str(p)
        seen.add(sp)
        if sp in excluded or indexed >= per_tick:
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        if st.st_size > MAX_BYTES or known.get(sp) == (st.st_mtime, st.st_size) or not _allowed(kernel, p):
            continue
        try:
            body = _text(p)
        except Exception:  # noqa: BLE001 - an unreadable file is indexed by name only
            body = ""
        with kernel.db.tx() as c:
            c.execute("DELETE FROM file_index WHERE path = ?", (sp,))
            c.execute("INSERT INTO file_index (path, name, body) VALUES (?, ?, ?)", (sp, p.name, body))
            c.execute("INSERT INTO file_index_meta (path, mtime, size, indexed_at) VALUES (?,?,?,?) ON CONFLICT(path) DO "
                      "UPDATE SET mtime = excluded.mtime, size = excluded.size, indexed_at = excluded.indexed_at",
                      (sp, st.st_mtime, st.st_size, now_iso()))
        indexed += 1
    gone = [p for p in known if p not in seen or p in excluded]
    if gone:
        with kernel.db.tx() as c:
            c.executemany("DELETE FROM file_index WHERE path = ?", [(p,) for p in gone])
            c.executemany("DELETE FROM file_index_meta WHERE path = ?", [(p,) for p in gone])
    return {"indexed": indexed, "removed": len(gone)}


def search(kernel, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
    from .memory import fts_query
    q = fts_query(query)
    if not q or not enabled(kernel):
        return []
    rows = kernel.db.query("SELECT path, name, snippet(file_index, 2, '[', ']', '…', 12) AS snip FROM file_index "
                           "WHERE file_index MATCH ? ORDER BY rank LIMIT ?", (q, limit))
    home = str(Path.home())
    return [{"path": r["path"].replace(home, "~", 1), "name": r["name"], "snippet": r["snip"]} for r in rows]


def forget(kernel, query: str, *, dry_run: bool = True) -> int:
    from .memory import fts_query
    q = fts_query(query)
    if not q:
        return 0
    hits = [r["path"] for r in kernel.db.query("SELECT path FROM file_index WHERE file_index MATCH ?", (q,))]
    if hits and not dry_run:
        excluded = sorted(set(json.loads(_meta(kernel, EXCLUDED, "[]"))) | set(hits))
        _put(kernel, EXCLUDED, json.dumps(excluded))
        with kernel.db.tx() as c:
            c.executemany("DELETE FROM file_index WHERE path = ?", [(p,) for p in hits])
            c.executemany("DELETE FROM file_index_meta WHERE path = ?", [(p,) for p in hits])
    return len(hits)
