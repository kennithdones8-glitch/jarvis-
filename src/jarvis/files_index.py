"""File search: what's inside your approved folders, searchable in an instant ("where's the lease PDF?").

Off until you turn it on (Systems). Then the maintenance loop reads, a few dozen files at a time, only files inside
the folders you've approved for JARVIS (each read is checked with the permission engine first, as a Tier-0 read):
text, Markdown, CSV, JSON, HTML, PDF and Word files up to 20 MB. A whole document is indexed (up to 200,000
characters, about 300 PDF pages) in chunks of about 1,500 characters cut at paragraph ends, so a clause on page 180
is found. A file whose text is identical to one already indexed is recorded as a duplicate, not indexed twice.
Hidden files and folders are skipped. Nothing leaves the Mac and no model is involved.

What a file says is data, never an instruction: nothing in a document can run a tool (chat can't act at all), and a
file containing text that reads like instructions to an AI ("ignore your previous instructions…") is flagged, shown
as such, and handed to the answering model with that warning.

Turning it off deletes the whole index. `forget` removes the entries of files that mention what you forget and keeps
those files out of the index. The index lives in JARVIS's database, so its encrypted backups contain it too.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from .core.util import now_iso

ON = "files.index.on"
EXCLUDED = "files.index.excluded"
EXTS = {".txt", ".md", ".markdown", ".csv", ".json", ".html", ".htm", ".rtf", ".pdf", ".docx", ".log", ".yaml", ".yml", ".toml"}
MAX_BYTES = 20 * 1024 * 1024
MAX_CHARS = 200_000          # what tools/documents reads at most (about 300 PDF pages)
CHUNK = 1500                 # characters per chunk, cut at a paragraph or sentence end where there is one
PER_TICK = 40
PER_TICK_CHARS = 1_500_000   # a few big documents don't hold the background loop for long
# Text that addresses an AI rather than a reader. A flag, never a filter: the file stays searchable and is shown
# with a warning; nothing a document says is ever followed.
INSTRUCTION_LIKE = re.compile(
    r"\b(ignore|disregard|forget|override)\b.{0,40}\b(previous|prior|above|earlier|all|your|system)\b.{0,30}"
    r"\b(instructions?|prompts?|rules?|guidelines?)\b"
    r"|\byou are now\b|\bnew (system )?instructions?\s*:|\bsystem prompt\b|\bdo not tell the user\b"
    r"|\b(reveal|print|send|exfiltrate)\b.{0,40}\b(password|api key|secret|token|credentials?)\b", re.I | re.S)


def chunks_of(text: str, size: int = CHUNK) -> list[str]:
    """``text`` in pieces of at most ``size`` characters, cut at the last paragraph end, else sentence end, else
    space before the limit. Nothing is dropped or repeated: joining the pieces gives the text back."""
    out, i, n = [], 0, len(text)
    while i < n:
        end = min(i + size, n)
        if end < n:
            window = text[i:end]
            cut = window.rfind("\n\n") + 2                      # just after the last paragraph end, if there is one
            if cut - 2 < size // 3:
                cut = max(window.rfind(". "), window.rfind(".\n"), window.rfind("\n")) + 1
            if cut - 1 < size // 3:
                cut = window.rfind(" ") + 1
            if cut - 1 >= size // 3:
                end = i + cut
        out.append(text[i:end])
        i = end
    return out


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
            c.execute("DELETE FROM file_chunks")
            c.execute("DELETE FROM file_index")
            c.execute("DELETE FROM file_index_meta")
        kernel.db.checkpoint()
    kernel.audit.record("files.index", actor=by, on=on)
    return status(kernel)


def status(kernel) -> dict[str, Any]:
    row = kernel.db.one("SELECT COUNT(*) AS n, COALESCE(SUM(chunks), 0) AS chunks, COALESCE(SUM(duplicate_of IS NOT NULL), 0) AS dup, "
                        "COALESCE(SUM(flagged), 0) AS flagged FROM file_index_meta")
    return {"on": enabled(kernel), "files": row["n"], "chunks": row["chunks"], "duplicates": row["dup"],
            "flagged": row["flagged"], "folders": [str(r) for r in kernel.policy.roots]}


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
    seen, indexed, chars = set(), 0, 0
    for p in _candidates(kernel):
        sp = str(p)
        seen.add(sp)
        if sp in excluded or indexed >= per_tick or chars >= PER_TICK_CHARS:
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
        digest = hashlib.sha256(body.encode("utf-8", "replace")).hexdigest() if body.strip() else None
        twin = kernel.db.one("SELECT path FROM file_index_meta WHERE sha256 = ? AND path != ? AND duplicate_of IS NULL "
                             "ORDER BY path LIMIT 1", (digest, sp)) if digest else None
        pieces = [] if twin else (chunks_of(body) or [""])    # a duplicate is recorded, not indexed again
        with kernel.db.tx() as c:
            c.execute("DELETE FROM file_chunks WHERE path = ?", (sp,))
            c.executemany("INSERT INTO file_chunks (path, chunk, name, body) VALUES (?, ?, ?, ?)",
                          [(sp, i, p.name, piece) for i, piece in enumerate(pieces)])
            c.execute("INSERT INTO file_index_meta (path, mtime, size, indexed_at, sha256, chunks, duplicate_of, flagged) "
                      "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET mtime = excluded.mtime, size = excluded.size, "
                      "indexed_at = excluded.indexed_at, sha256 = excluded.sha256, chunks = excluded.chunks, "
                      "duplicate_of = excluded.duplicate_of, flagged = excluded.flagged",
                      (sp, st.st_mtime, st.st_size, now_iso(), digest, len(pieces), twin["path"] if twin else None,
                       1 if INSTRUCTION_LIKE.search(body) else 0))
            # copies that pointed at this file are re-read next time (it changed, so they may no longer match)
            c.execute("UPDATE file_index_meta SET mtime = -1 WHERE duplicate_of = ? AND path != ?", (sp, sp))
        indexed += 1
        chars += len(body)
    gone = [p for p in known if p not in seen or p in excluded]
    if gone:
        with kernel.db.tx() as c:
            c.executemany("DELETE FROM file_chunks WHERE path = ?", [(p,) for p in gone])
            c.executemany("DELETE FROM file_index_meta WHERE path = ?", [(p,) for p in gone])
            # a copy whose original went away is indexed in its own right next time
            c.executemany("UPDATE file_index_meta SET mtime = -1, duplicate_of = NULL WHERE duplicate_of = ?", [(p,) for p in gone])
    return {"indexed": indexed, "removed": len(gone)}


def _meta_of(kernel, paths: list[str]) -> dict[str, dict[str, Any]]:
    if not paths:
        return {}
    marks = ",".join("?" * len(paths))
    out = {r["path"]: {"flagged": bool(r["flagged"]), "indexed_at": r["indexed_at"], "copies": []}
           for r in kernel.db.query(f"SELECT path, flagged, indexed_at FROM file_index_meta WHERE path IN ({marks})", paths)}
    for r in kernel.db.query(f"SELECT path, duplicate_of FROM file_index_meta WHERE duplicate_of IN ({marks})", paths):
        out.setdefault(r["duplicate_of"], {"flagged": False, "indexed_at": None, "copies": []})["copies"].append(r["path"])
    return out


def search(kernel, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
    """Files matching any word of ``query``, best first, one result per file (its best chunk), with where the match
    is in the document, identical copies elsewhere, and whether the file contains instruction-like text."""
    from .memory import fts_query
    q = fts_query(query)
    if not q or not enabled(kernel):
        return []
    rows = kernel.db.query("SELECT path, name, chunk, snippet(file_chunks, 3, '[', ']', '…', 12) AS snip FROM file_chunks "
                           "WHERE file_chunks MATCH ? ORDER BY rank LIMIT ?", (q, limit * 6))
    best: dict[str, Any] = {}
    for r in rows:
        best.setdefault(r["path"], r)
    picked = list(best.values())[:limit]
    meta = _meta_of(kernel, [r["path"] for r in picked])
    home = str(Path.home())
    tilde = lambda p: p.replace(home, "~", 1)  # noqa: E731
    return [{"path": tilde(r["path"]), "name": r["name"], "snippet": r["snip"], "part": int(r["chunk"]) + 1,
             "copies": [tilde(c) for c in meta.get(r["path"], {}).get("copies", [])],
             "flagged": meta.get(r["path"], {}).get("flagged", False),
             "indexed_at": meta.get(r["path"], {}).get("indexed_at")} for r in picked]


# Words that say nothing about which file you mean ("what does my lease say about pets?" → lease, pets).
STOP = set("""a about after again all also am an and any are as at be been before but by can could did do does
doing for from had has have how i if in into is it its just me my of on or our say says said should so some tell
than that the their them then there these they this to up was we were what when where which who why will with would
you your please find show look check much many more most file files document documents doc docs pdf folder folders""".split())
PASSAGE = 700
MAX_PASSAGES = 3


def terms(question: str) -> list[str]:
    import re
    return list(dict.fromkeys(w for w in re.findall(r"\w+", question.lower()) if len(w) >= 3 and w not in STOP))[:8]


def passages(kernel, question: str, *, limit: int = MAX_PASSAGES) -> list[dict[str, Any]]:
    """For a chat question: the passages of your indexed files that contain *every* meaningful word of it (so "what's
    on tomorrow" doesn't drag in a random document), best match first, each file re-checked by the permission engine
    now (a folder you've since removed stays out). Empty when file search is off. Nothing leaves the Mac here; the
    caller marks the text as private file content, so the privacy gate applies before any cloud model sees it."""
    words = terms(question)
    if not words or not enabled(kernel) or kernel.killswitch.engaged():
        return []
    try:
        # every meaningful word must be somewhere in the file (its name or any chunk) …
        paths: set[str] | None = None
        for w in words:
            got = {r["path"] for r in kernel.db.query("SELECT DISTINCT path FROM file_chunks WHERE file_chunks MATCH ?", (f'"{w}"',))}
            paths = got if paths is None else paths & got
            if not paths:
                return []
        # … and the passage is the chunk that says most about the words that aren't just the file's name
        rows = kernel.db.query("SELECT path, name, chunk, body, rank FROM file_chunks WHERE file_chunks MATCH ? ORDER BY rank",
                               (" OR ".join(f'"{w}"' for w in words),))
    except Exception:  # noqa: BLE001 - a query FTS can't parse is simply no match
        return []
    scored: dict[str, tuple[float, Any]] = {}
    for r in rows:
        if r["path"] not in paths:
            continue
        low, nm = (r["body"] or "").lower(), r["name"].lower()
        score = sum((0.1 if w in nm else 1.0) * low.count(w) for w in words)
        if r["path"] not in scored or score > scored[r["path"]][0]:
            scored[r["path"]] = (score, r)
    ranked = sorted(scored.values(), key=lambda x: -x[0])
    meta = _meta_of(kernel, [r["path"] for _, r in ranked])
    home, out = str(Path.home()), []
    for _score, r in ranked:
        if len(out) >= limit:
            break
        if not _allowed(kernel, Path(r["path"])):
            continue
        out.append({"path": r["path"].replace(home, "~", 1), "name": r["name"], "part": int(r["chunk"]) + 1,
                    "text": _best(r["body"] or "", words, r["name"]),
                    "flagged": meta.get(r["path"], {}).get("flagged", False), "matched": words})
    return out


def _best(body: str, words: list[str], name: str = "") -> str:
    """The ~700-character stretch of ``body`` that mentions the most of ``words`` (plain counting, no model). A word in
    the file's name ("lease" in lease.md) found the file; the passage is chosen mostly by the others ("pets")."""
    if len(body) <= PASSAGE:
        return body.strip()
    low, step, nm = body.lower(), PASSAGE // 2, name.lower()
    weight = {w: 0.1 if w in nm else 1.0 for w in words}
    best, at = -1.0, 0
    for i in range(0, max(1, len(body) - step), step):
        n = sum(weight[w] * low.count(w, i, i + PASSAGE) for w in words)
        if n > best:
            best, at = n, i
    return ("…" if at else "") + body[at:at + PASSAGE].strip() + ("…" if at + PASSAGE < len(body) else "")


def forget(kernel, query: str, *, dry_run: bool = True) -> int:
    from .memory import fts_query
    q = fts_query(query)
    if not q:
        return 0
    hits = [r["path"] for r in kernel.db.query("SELECT DISTINCT path FROM file_chunks WHERE file_chunks MATCH ?", (q,))]
    # identical copies of a forgotten file hold the same text, so they go (and stay out) too
    if hits:
        marks = ",".join("?" * len(hits))
        hits += [r["path"] for r in kernel.db.query(f"SELECT path FROM file_index_meta WHERE duplicate_of IN ({marks})", hits)]
    if hits and not dry_run:
        excluded = sorted(set(json.loads(_meta(kernel, EXCLUDED, "[]"))) | set(hits))
        _put(kernel, EXCLUDED, json.dumps(excluded))
        with kernel.db.tx() as c:
            c.executemany("DELETE FROM file_chunks WHERE path = ?", [(p,) for p in hits])
            c.executemany("DELETE FROM file_index_meta WHERE path = ?", [(p,) for p in hits])
    return len(hits)
