"""Production tools. Each declares its actions, tiers and resources; the gateway enforces them."""

from __future__ import annotations

from pathlib import Path

from ..core.tools import ToolRegistry
from .fs import FileTool
from .search import SearchTool
from .web import WebTool


def default_registry(data_dir: str | Path, *, searxng_url: str | None = None) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(FileTool(data_dir).spec())
    registry.register(WebTool().spec())
    if searxng_url:
        registry.register(SearchTool(searxng_url).spec())
    return registry


__all__ = ["FileTool", "SearchTool", "WebTool", "default_registry"]
