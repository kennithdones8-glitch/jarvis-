"""File tool, scoped by the permission engine to approved roots.

Handlers receive the canonical path the permission engine approved (``ctx.resource``), never
the raw argument. Mutations are reversible: overwrites keep the previous version and deletes
move files to JARVIS's trash, both inside the protected data directory.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from ..core.permissions import ResourceKind, Tier
from ..core.tools import RECONCILE_DONE, RECONCILE_NOT_DONE, ActionSpec, CallContext, ToolError, ToolSpec
from ..core.util import new_id

PATH = ResourceKind.PATH
MAX_READ_BYTES = 1_000_000
MAX_WRITE_BYTES = 5_000_000
MAX_LIST = 500
MAX_SEARCH_FILES = 2_000
MAX_SEARCH_HITS = 100


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _no_symlink(path: Path) -> None:
    # The engine resolved symlinks at check time; refuse if one appeared since (TOCTOU).
    if path.is_symlink():
        raise ToolError("path became a symlink after the permission check")


class FileTool:
    def __init__(self, data_dir: str | Path, *, dest_guard=None):
        self.versions = Path(data_dir) / "file-versions"
        self.trash = Path(data_dir) / "trash"
        # Moves touch a second path. ``dest_guard(path) -> (allowed, reason)`` applies the permission
        # engine's root/protected rules to the destination; without one, moves are refused.
        self.dest_guard = dest_guard

    def spec(self) -> ToolSpec:
        return ToolSpec("fs", "Read, list, search and write files inside approved folders", {
            "read": ActionSpec(Tier.READ, "path", PATH, timeout_s=15),
            "list": ActionSpec(Tier.READ, "path", PATH, timeout_s=15),
            "search": ActionSpec(Tier.READ, "path", PATH, timeout_s=60),
            "mkdir": ActionSpec(Tier.ROUTINE, "path", PATH, timeout_s=10),
            "write": ActionSpec(Tier.ROUTINE, "path", PATH, idempotent=True, timeout_s=30, reconcile=self._reconcile_write),
            "delete": ActionSpec(Tier.HIGH_RISK, "path", PATH, idempotent=False, timeout_s=30,
                                 reconcile=self._reconcile_delete),
            "move": ActionSpec(Tier.REVIEW, "path", PATH, idempotent=False, timeout_s=30,
                               reconcile=self._reconcile_move),
        }, self.handle)

    def handle(self, action: str, args: dict[str, Any], ctx: CallContext) -> Any:
        path = Path(ctx.resource)
        return getattr(self, f"_{action}")(path, args, ctx)

    # ---- read-only ---------------------------------------------------------------------
    def _read(self, path: Path, args: dict[str, Any], ctx: CallContext) -> dict[str, Any]:
        if not path.is_file():
            raise ToolError(f"not a file: {path}")
        size = path.stat().st_size
        with path.open("rb") as fh:
            data = fh.read(MAX_READ_BYTES)
        if b"\x00" in data[:8192]:
            raise ToolError("binary files are not supported yet")
        return {"path": str(path), "bytes": size, "truncated": size > MAX_READ_BYTES, "sha256": _sha(data),
                "content": data.decode("utf-8", errors="replace")}

    def _list(self, path: Path, args: dict[str, Any], ctx: CallContext) -> dict[str, Any]:
        if not path.is_dir():
            raise ToolError(f"not a folder: {path}")
        entries = []
        for i, entry in enumerate(sorted(path.iterdir(), key=lambda p: p.name)):
            if i >= MAX_LIST:
                break
            entries.append({"name": entry.name, "dir": entry.is_dir(),
                            "bytes": entry.stat().st_size if entry.is_file() else None})
        return {"path": str(path), "entries": entries, "truncated": len(entries) >= MAX_LIST}

    def _search(self, path: Path, args: dict[str, Any], ctx: CallContext) -> dict[str, Any]:
        query = str(args.get("query", "")).strip().lower()
        if not query:
            raise ToolError("query is required")
        hits, scanned = [], 0
        for dirpath, dirnames, filenames in os.walk(path, followlinks=False):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            for name in sorted(filenames):
                if scanned >= MAX_SEARCH_FILES or len(hits) >= MAX_SEARCH_HITS:
                    return {"query": query, "hits": hits, "scanned": scanned, "truncated": True}
                file = Path(dirpath) / name
                if file.is_symlink() or name.startswith("."):
                    continue
                scanned += 1
                if query in name.lower():
                    hits.append({"path": str(file), "match": "name"})
                    continue
                try:
                    with file.open("rb") as fh:
                        chunk = fh.read(200_000)
                except OSError:
                    continue
                if b"\x00" in chunk[:4096]:
                    continue
                text = chunk.decode("utf-8", errors="ignore")
                pos = text.lower().find(query)
                if pos >= 0:
                    hits.append({"path": str(file), "match": "content",
                                 "snippet": text[max(0, pos - 80): pos + 120].replace("\n", " ")})
        return {"query": query, "hits": hits, "scanned": scanned, "truncated": False}

    # ---- mutations ---------------------------------------------------------------------
    def _mkdir(self, path: Path, args: dict[str, Any], ctx: CallContext) -> dict[str, Any]:
        path.mkdir(parents=True, exist_ok=True)
        return {"path": str(path), "created": True}

    def _write(self, path: Path, args: dict[str, Any], ctx: CallContext) -> dict[str, Any]:
        content = args.get("content")
        if not isinstance(content, str):
            raise ToolError("content must be text")
        data = content.encode("utf-8")
        if len(data) > MAX_WRITE_BYTES:
            raise ToolError("content too large")
        _no_symlink(path)
        previous = None
        if path.exists():
            if not path.is_file():
                raise ToolError("target exists and is not a file")
            old = path.read_bytes()
            if old == data:
                return {"path": str(path), "bytes": len(data), "sha256": _sha(data), "unchanged": True}
            previous = self._keep_version(path, old)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".jarvis-", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)  # atomic: readers never see a half-written file
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return {"path": str(path), "bytes": len(data), "sha256": _sha(data), "previous_version": previous}

    def _move(self, path: Path, args: dict[str, Any], ctx: CallContext) -> dict[str, Any]:
        """Move or rename a file or folder. Never overwrites. The destination must pass the same
        root/protected checks as a write."""
        to = args.get("to")
        if not isinstance(to, str) or not to.strip():
            raise ToolError("'to' (destination path) is required")
        if self.dest_guard is None:
            raise ToolError("moves are not enabled")
        dest = Path(os.path.realpath(os.path.expanduser(to)))
        if dest.is_dir() and not args.get("exact"):
            dest = dest / path.name  # moving into an existing folder
        allowed, reason = self.dest_guard(str(dest))
        if not allowed:
            raise ToolError(f"destination not allowed: {reason}")
        _no_symlink(path)
        if not path.exists():
            raise ToolError(f"nothing to move at {path}")
        if dest.exists():
            raise ToolError(f"{dest} already exists; JARVIS never overwrites when moving")
        if path == dest or dest.is_relative_to(path):
            raise ToolError("can't move a folder into itself")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), dest)
        return {"from": str(path), "to": str(dest)}

    @staticmethod
    def _reconcile_move(args: dict[str, Any], op_id: str) -> str:
        src = Path(os.path.realpath(os.path.expanduser(str(args.get("path", "")))))
        dest = Path(os.path.realpath(os.path.expanduser(str(args.get("to", "")))))
        if dest.is_dir() and not dest.joinpath(src.name).exists() and src.exists():
            return RECONCILE_NOT_DONE
        target = dest / src.name if dest.is_dir() and dest.joinpath(src.name).exists() else dest
        if target.exists() and not src.exists():
            return RECONCILE_DONE
        if src.exists() and not target.exists():
            return RECONCILE_NOT_DONE
        return "unknown"

    def _delete(self, path: Path, args: dict[str, Any], ctx: CallContext) -> dict[str, Any]:
        _no_symlink(path)
        if not path.exists():
            raise ToolError(f"nothing to delete at {path}")
        self.trash.mkdir(parents=True, exist_ok=True)
        dest = self.trash / f"{ctx.op_id or new_id('del')}__{path.name}"
        shutil.move(str(path), dest)
        return {"path": str(path), "moved_to_trash": str(dest)}

    def _keep_version(self, path: Path, data: bytes) -> str:
        self.versions.mkdir(parents=True, exist_ok=True)
        dest = self.versions / f"{new_id('ver')}__{path.name}"
        dest.write_bytes(data)
        return str(dest)

    # ---- reconciliation after a crash --------------------------------------------------
    @staticmethod
    def _reconcile_write(args: dict[str, Any], op_id: str) -> str:
        path = Path(os.path.realpath(os.path.expanduser(str(args.get("path", "")))))
        content = args.get("content")
        if path.is_file() and isinstance(content, str) and path.read_bytes() == content.encode("utf-8"):
            return RECONCILE_DONE
        return RECONCILE_NOT_DONE

    def _reconcile_delete(self, args: dict[str, Any], op_id: str) -> str:
        if self.trash.exists() and any(p.name.startswith(f"{op_id}__") for p in self.trash.iterdir()):
            return RECONCILE_DONE
        return "unknown"
