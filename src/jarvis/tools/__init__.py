"""Production tools. Each declares its actions, tiers and resources; the gateway enforces them."""

from __future__ import annotations

from pathlib import Path

from ..core.tools import ToolRegistry
from .documents import DocumentTool
from .fs import FileTool
from .search import SearchTool
from .web import WebTool


def default_registry(data_dir: str | Path, *, searxng_url: str | None = None, permissions=None,
                     mac_runner=None) -> ToolRegistry:
    from ..core.permissions import Effect, ResourceKind, Tier

    def dest_guard(path: str) -> tuple[bool, str]:
        d = permissions.evaluate(tool="fs", action="write", tier=Tier.ROUTINE, resource_kind=ResourceKind.PATH,
                                 resource=path)
        return d.effect is not Effect.DENY, d.reason

    registry = ToolRegistry()
    registry.register(FileTool(data_dir, dest_guard=dest_guard if permissions is not None else None).spec())
    registry.register(DocumentTool().spec())
    registry.register(WebTool().spec())
    from . import mac
    if mac.available() or mac_runner is not None:  # Calendar, Reminders, Notes, Mail drafts, opening apps
        for spec in mac.MacTool(**({"runner": mac_runner} if mac_runner else {})).specs():
            registry.register(spec)
    if searxng_url and _reachable(searxng_url):  # don't offer the planner a search engine that isn't running
        registry.register(SearchTool(searxng_url).spec())
    return registry


def _reachable(url: str, timeout: float = 0.3) -> bool:
    import socket
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    try:
        with socket.create_connection((parts.hostname, parts.port or 80), timeout=timeout):
            return True
    except (OSError, ValueError):
        return False


__all__ = ["DocumentTool", "FileTool", "SearchTool", "WebTool", "default_registry"]
