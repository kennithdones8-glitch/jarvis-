"""Central permission engine.

Pure policy evaluation: (tool, action, tier, resource) -> allow | confirm | deny.
It never executes anything and never consults a model. The tool gateway is the only
caller, and the gateway is the only path to a tool handler.

Evaluation order:
  1. Path resources are canonicalised (``~`` expanded, symlinks resolved). A path outside
     every approved root is denied. Writes to protected paths are denied.
  2. URL resources must be http(s).
  3. Matching rules are collected. Any ``deny`` wins; then ``confirm``; then ``allow``.
  4. Tier 3 (external) and Tier 4 (high-risk) actions are never auto-allowed: an ``allow``
     rule is lowered to ``confirm``. Policy cannot remove this floor.
  5. With no matching rule: Tier 0 reads inside approved roots are allowed; everything
     else requires confirmation.
"""

from __future__ import annotations

import fnmatch
import os
import tomllib
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit


class Tier(IntEnum):
    READ = 0
    ROUTINE = 1
    REVIEW = 2
    EXTERNAL = 3
    HIGH_RISK = 4


class Effect(StrEnum):
    ALLOW = "allow"
    CONFIRM = "confirm"
    DENY = "deny"


class ResourceKind(StrEnum):
    PATH = "path"
    URL = "url"


class PolicyError(ValueError):
    pass


@dataclass(frozen=True)
class Decision:
    effect: Effect
    tier: Tier
    reason: str
    rule_id: str | None = None
    resource: str | None = None


def canonical_path(raw: Any) -> Path:
    if not isinstance(raw, str) or not raw.strip() or "\x00" in raw:
        raise PolicyError("invalid path")
    return Path(os.path.realpath(os.path.expanduser(raw)))


def is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


@dataclass(frozen=True)
class Rule:
    id: str
    effect: Effect
    tools: tuple[str, ...] = ("*",)
    actions: tuple[str, ...] = ("*",)
    resources: tuple[str, ...] = ("*",)

    def matches(self, tool: str, action: str, resource: str | None, kind: ResourceKind | None) -> bool:
        if not any(fnmatch.fnmatchcase(tool, t) for t in self.tools):
            return False
        if not any(fnmatch.fnmatchcase(action, a) for a in self.actions):
            return False
        if "*" in self.resources:
            return True
        if resource is None:
            return False
        return any(_resource_matches(p, resource, kind) for p in self.resources)


def _resource_matches(pattern: str, resource: str, kind: ResourceKind | None) -> bool:
    if kind is ResourceKind.PATH:
        if pattern.endswith("/**"):
            return is_within(Path(resource), Path(pattern[:-3]))
        return fnmatch.fnmatchcase(resource, pattern)
    return fnmatch.fnmatchcase(resource, pattern)


def _normalise_pattern(pattern: str) -> str:
    """Canonicalise the directory part of path-like patterns so they compare with canonical paths."""
    if pattern == "*" or "://" in pattern or not pattern.startswith(("/", "~")):
        return pattern
    if pattern.endswith("/**"):
        return str(canonical_path(pattern[:-3])) + "/**"
    head, tail = os.path.split(pattern)
    if any(ch in head for ch in "*?["):
        return os.path.expanduser(pattern)
    return os.path.join(str(canonical_path(head)), tail)


@dataclass(frozen=True)
class Policy:
    roots: tuple[Path, ...] = ()
    protected: tuple[Path, ...] = ()
    rules: tuple[Rule, ...] = field(default_factory=tuple)

    @classmethod
    def empty(cls, *, protected: Iterable[str | Path] = ()) -> "Policy":
        return cls(protected=tuple(canonical_path(str(p)) for p in protected))

    @classmethod
    def load(cls, path: str | Path, *, protected: Iterable[str | Path] = ()) -> "Policy":
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
        return cls.from_dict(data, protected=protected)

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, protected: Iterable[str | Path] = ()) -> "Policy":
        unknown = set(data) - {"filesystem", "rules"}
        if unknown:
            raise PolicyError(f"unknown policy sections: {sorted(unknown)}")
        fs = data.get("filesystem", {})
        unknown = set(fs) - {"roots", "protected"}
        if unknown:
            raise PolicyError(f"unknown [filesystem] keys: {sorted(unknown)}")
        roots = tuple(canonical_path(r) for r in fs.get("roots", []))
        prot = tuple(canonical_path(str(p)) for p in [*fs.get("protected", []), *protected])

        rules: list[Rule] = []
        seen: set[str] = set()
        for raw in data.get("rules", []):
            unknown = set(raw) - {"id", "effect", "tools", "actions", "resources"}
            if unknown:
                raise PolicyError(f"unknown rule keys: {sorted(unknown)}")
            rid = raw.get("id")
            if not rid or rid in seen:
                raise PolicyError(f"rule id missing or duplicated: {rid!r}")
            seen.add(rid)
            try:
                effect = Effect(raw.get("effect"))
            except ValueError:
                raise PolicyError(f"rule {rid}: effect must be allow, confirm or deny") from None
            rules.append(
                Rule(
                    id=rid,
                    effect=effect,
                    tools=tuple(raw.get("tools", ["*"])),
                    actions=tuple(raw.get("actions", ["*"])),
                    resources=tuple(_normalise_pattern(r) for r in raw.get("resources", ["*"])),
                )
            )
        return cls(roots=roots, protected=prot, rules=tuple(rules))


class PermissionEngine:
    def __init__(self, policy: Policy):
        self.policy = policy

    def evaluate(
        self,
        *,
        tool: str,
        action: str,
        tier: Tier,
        resource_kind: ResourceKind | None = None,
        resource: Any = None,
    ) -> Decision:
        res: str | None = None
        if resource_kind is ResourceKind.PATH:
            try:
                path = canonical_path(resource)
            except PolicyError as exc:
                return Decision(Effect.DENY, tier, str(exc))
            if not any(is_within(path, root) for root in self.policy.roots):
                return Decision(Effect.DENY, tier, "path is outside approved roots", resource=str(path))
            if tier > Tier.READ and any(is_within(path, p) for p in self.policy.protected):
                return Decision(Effect.DENY, tier, "path is protected", resource=str(path))
            res = str(path)
        elif resource_kind is ResourceKind.URL:
            if not isinstance(resource, str) or urlsplit(resource).scheme not in ("http", "https"):
                return Decision(Effect.DENY, tier, "only http(s) URLs are allowed")
            if not urlsplit(resource).hostname:
                return Decision(Effect.DENY, tier, "URL has no host")
            res = resource
        elif resource is not None:
            res = str(resource)

        matching = [r for r in self.policy.rules if r.matches(tool, action, res, resource_kind)]
        for effect in (Effect.DENY, Effect.CONFIRM, Effect.ALLOW):
            hit = next((r for r in matching if r.effect is effect), None)
            if hit is None:
                continue
            if effect is Effect.ALLOW and tier >= Tier.EXTERNAL:
                return Decision(Effect.CONFIRM, tier, f"tier {int(tier)} always requires confirmation", hit.id, res)
            return Decision(effect, tier, f"matched rule {hit.id}", hit.id, res)

        if tier is Tier.READ:
            return Decision(Effect.ALLOW, tier, "read-only within approved scope", resource=res)
        return Decision(Effect.CONFIRM, tier, "no standing policy covers this action", resource=res)
