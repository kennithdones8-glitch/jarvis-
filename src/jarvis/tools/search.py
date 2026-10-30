"""Web search through a self-hosted SearXNG instance (free, no account, no tracking profile).

SearXNG runs on this Mac (Docker) and forwards the *query text* to public search engines,
so a search is a Tier 1 action: it leaves the machine. Results are marked untrusted.

Run it with:  docker run -d -p 127.0.0.1:8888:8080 --name searxng searxng/searxng
then enable the JSON format in its settings.yml (search.formats: [html, json]).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode, urlsplit

from ..core.permissions import Tier
from ..core.tools import ActionSpec, CallContext, ToolError, ToolSpec
from ..models.http import request_json
from ..models.providers import is_loopback_url
from ..models.types import ProviderError

MAX_QUERY_CHARS = 300
MAX_RESULTS = 10


class SearchTool:
    def __init__(self, base_url: str, *, timeout: float = 15.0):
        if not is_loopback_url(base_url):
            raise ValueError("SearXNG must run locally (loopback URL)")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def spec(self) -> ToolSpec:
        return ToolSpec("search", "Search the public web via local SearXNG", {
            "query": ActionSpec(Tier.ROUTINE, "query", None, idempotent=True, timeout_s=self.timeout + 5),
        }, self.handle)

    def handle(self, action: str, args: dict[str, Any], ctx: CallContext) -> Any:
        if action != "query":
            raise ToolError(f"unknown action {action}")
        return self.search(args.get("query"), limit=args.get("limit", 5))

    def search(self, query: Any, *, limit: Any = 5) -> dict[str, Any]:
        if not isinstance(query, str) or not query.strip():
            raise ToolError("query must be non-empty text")
        if len(query) > MAX_QUERY_CHARS:
            raise ToolError(f"query longer than {MAX_QUERY_CHARS} characters")
        if not isinstance(limit, int) or not 1 <= limit <= MAX_RESULTS:
            raise ToolError(f"limit must be 1–{MAX_RESULTS}")
        url = f"{self.base_url}/search?{urlencode({'q': query.strip(), 'format': 'json', 'safesearch': 1})}"
        try:
            data = request_json("GET", url, timeout=self.timeout)
        except ProviderError as exc:
            raise ToolError(f"search backend failed: {exc}", retryable=exc.retryable) from None
        results = []
        for item in data.get("results", []):
            link = item.get("url")
            if not isinstance(link, str) or urlsplit(link).scheme not in ("http", "https"):
                continue
            results.append({"title": str(item.get("title", ""))[:300], "url": link,
                            "snippet": str(item.get("content", ""))[:500], "engine": item.get("engine")})
            if len(results) >= limit:
                break
        return {"query": query.strip(), "results": results, "untrusted": True}
