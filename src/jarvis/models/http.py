"""Minimal JSON-over-HTTP client (stdlib only) with error classification and size limits."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from .types import ProviderError, ProviderUnavailable

MAX_RESPONSE_BYTES = 8 * 1024 * 1024


def request_json(method: str, url: str, payload: Any = None, *, headers: dict[str, str] | None = None,
                 timeout: float = 60.0) -> Any:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        # Do not echo the response body: it can contain request content.
        retryable = exc.code == 429 or exc.code >= 500
        raise ProviderError(f"HTTP {exc.code} from provider", retryable=retryable) from None
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise ProviderUnavailable(f"provider unreachable: {reason}") from None
    if len(body) > MAX_RESPONSE_BYTES:
        raise ProviderError("provider response too large")
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        raise ProviderError("provider returned invalid JSON") from None
