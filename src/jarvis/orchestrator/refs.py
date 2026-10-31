"""References from one step's arguments to an earlier step's result: ``{{steps.N.field.sub}}``.

A string that is exactly one reference takes the referenced value as-is (any type); a reference
embedded in longer text is replaced by its text form. Path parts may be dict keys or list indexes.
"""

from __future__ import annotations

import json
import re
from typing import Any

REF = re.compile(r"\{\{\s*steps\.(\d+)((?:\.[A-Za-z0-9_]+)*)\s*\}\}")


def references(value: Any) -> set[int]:
    if isinstance(value, str):
        return {int(m.group(1)) for m in REF.finditer(value)}
    if isinstance(value, dict):
        return set().union(*(references(v) for v in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(references(v) for v in value)) if value else set()
    return set()


def _lookup(results: dict[int, Any], idx: int, path: str) -> Any:
    if idx not in results:
        raise KeyError(f"step {idx} has no result yet")
    value = results[idx]
    for part in [p for p in path.split(".") if p]:
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            raise KeyError(f"step {idx} result has no '{path.lstrip('.')}'")
    return value


def _as_text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def resolve(value: Any, results: dict[int, Any]) -> Any:
    if isinstance(value, str):
        whole = REF.fullmatch(value.strip())
        if whole:
            return _lookup(results, int(whole.group(1)), whole.group(2))
        return REF.sub(lambda m: _as_text(_lookup(results, int(m.group(1)), m.group(2))), value)
    if isinstance(value, dict):
        return {k: resolve(v, results) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, results) for v in value]
    return value


def resolve_step_args(step: dict[str, Any], steps: list[dict[str, Any]]) -> dict[str, Any]:
    results = {s["idx"]: s["result"] for s in steps if s["state"] == "done"}
    return resolve(step["args"], results)
