"""Small shared helpers: ids, timestamps, canonical JSON."""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from datetime import datetime, timezone
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def new_id(prefix: str) -> str:
    """Time-sortable, collision-resistant id, e.g. ``task_0192ab34cd5e1f2a3b4c5d``."""
    return f"{prefix}_{time.time_ns() // 1_000_000:012x}{secrets.token_hex(5)}"


def canonical_json(value: Any) -> str:
    """Deterministic JSON used for hashing and storage."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
