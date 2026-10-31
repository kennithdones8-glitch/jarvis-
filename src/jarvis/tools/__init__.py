"""Production tools. Each declares its actions, tiers and resources; the gateway enforces them."""

from __future__ import annotations

from pathlib import Path

from ..core.tools import ToolRegistry
from .documents import DocumentTool
from .fs import FileTool
from .search import SearchTool
from .web import WebTool


def default_registry(data_dir: str | Path, *, searxng_url: str | None = None, permissions=None) -> ToolRegistry:
    from ..core.permissions import Effect, ResourceKind, Tier

    def dest_guard(path: str) -> tuple[bool, str]:
        d = permissions.evaluate(tool="fs", action="write", tier=Tier.ROUTINE, resource_kind=ResourceKind.PATH,
                                 resource=path)
        return d.effect is not Effect.DENY, d.reason

    registry = ToolRegistry()
    registry.register(FileTool(data_dir, dest_guard=dest_guard if permissions is not None else None).spec())
    registry.register(DocumentTool().spec())
    registry.register(WebTool().spec())
    if searxng_url:
        registry.register(SearchTool(searxng_url).spec())
    return registry


__all__ = ["DocumentTool", "FileTool", "SearchTool", "WebTool", "default_registry"]
