"""Best-effort secret redaction applied before anything is written to the audit log.

Redaction is a safety net, not a guarantee: secrets should never reach tool arguments
in the first place (they live in the OS keychain and are resolved inside connectors).
"""

from __future__ import annotations

import re
from typing import Any

REDACTED = "[REDACTED]"

_SECRET_KEY = re.compile(
    r"(^|[_\-.])(pass(word)?|passwd|secret|token|api[_\-]?key|auth(orization)?|cookie|"
    r"credentials?|private[_\-]?key|session[_\-]?id)($|[_\-.])",
    re.IGNORECASE,
)

_SECRET_VALUES = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{10,}"),
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"xox[abprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
    re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-~+/]{16,}=*"),
]


def is_secret_key(key: str) -> bool:
    return bool(_SECRET_KEY.search(key))


def redact_text(text: str) -> str:
    for pattern in _SECRET_VALUES:
        text = pattern.sub(REDACTED, text)
    return text


def redact(value: Any) -> Any:
    """Return a copy of ``value`` with secret-looking keys and values replaced."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if isinstance(k, str) and is_secret_key(k) and v not in (None, ""):
                out[k] = REDACTED
            else:
                out[k] = redact(v)
        return out
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return redact_text(value)
    return value
