"""What's new: after an update, the home screen lists what arrived (the newest CHANGELOG section's headings) until you
dismiss it. Read from the repository JARVIS runs from; nothing is fetched. Only a fingerprint of what you've seen is kept."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from .service import REPO

SEEN = "whatsnew.seen"


def items(repo: Path = REPO, limit: int = 12) -> list[str]:
    try:
        text = (Path(repo) / "CHANGELOG.md").read_text()
    except OSError:
        return []
    sections = re.split(r"(?m)^## ", text)
    if len(sections) < 2:
        return []
    heads = re.findall(r"(?m)^### (.+)$", sections[1])
    return [h.strip() for h in heads][:limit]


def _fingerprint(heads: list[str]) -> str:
    return hashlib.sha256("\n".join(heads).encode()).hexdigest()[:16]


def state(kernel, repo: Path = REPO) -> dict[str, Any]:
    heads = items(repo)
    row = kernel.db.one("SELECT value FROM meta WHERE key = ?", (SEEN,))
    seen = row["value"] if row else None
    fp = _fingerprint(heads)
    if seen is None and heads:   # a fresh install: nothing is "new" yet
        mark_seen(kernel, repo)
        seen = fp
    return {"items": heads, "unseen": bool(heads) and seen != fp}


def mark_seen(kernel, repo: Path = REPO) -> None:
    fp = _fingerprint(items(repo))
    with kernel.db.tx() as c:
        c.execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (SEEN, fp))
