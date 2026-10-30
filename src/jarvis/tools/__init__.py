"""Production tools. Each declares its actions, tiers and resources; the gateway enforces them."""

from __future__ import annotations

from pathlib import Path

from ..core.tools import ToolRegistry
from .fs import FileTool
from .web import WebTool


def default_registry(data_dir: str | Path) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(FileTool(data_dir).spec())
    registry.register(WebTool().spec())
    return registry


__all__ = ["FileTool", "WebTool", "default_registry"]
