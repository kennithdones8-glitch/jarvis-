"""The Trust Contract: what JARVIS does on its own, what it always asks about, and what it never does.

Generated every time from the live permission engine, policy, privacy settings, grants and budget, never written
by hand, so it can't drift from what JARVIS actually enforces. Each action's line comes from asking the permission
engine about it (inside each approved folder, for file actions). Built-in rules that settings can't change are
listed with the release-gate item whose tests prove them.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .core.permissions import Effect, ResourceKind, Tier
from .models.types import Category

PHRASES: dict[tuple[str, str], str] = {
    ("fs", "read"): "read files", ("fs", "list"): "list folders", ("fs", "search"): "search inside files",
    ("fs", "mkdir"): "create folders", ("fs", "write"): "write or change files", ("fs", "move"): "move or rename files",
    ("fs", "delete"): "delete files", ("doc", "read"): "read PDF and Word documents", ("doc", "info"): "look at document details",
    ("web", "fetch"): "read public web pages", ("search", "query"): "search the web (the query only, via your SearXNG)",
    ("calendar", "events"): "look at your Calendar", ("calendar", "add"): "add Calendar events",
    ("reminders", "list"): "look at your Reminders", ("reminders", "add"): "add reminders",
    ("reminders", "complete"): "tick off reminders", ("notes", "search"): "search your Notes",
    ("notes", "read"): "read a note", ("notes", "create"): "create notes", ("mail", "draft"): "save email drafts (never sends)",
    ("apps", "open"): "open apps", ("llm", "compose"): "write text with a local model from data it was given",
    ("research", "web"): "research the web with Claude",
}
CATEGORY_NAMES = {"conversation": "what you say in chat", "file_content": "your files and app data (calendar, reminders, notes)",
                  "memory": "what JARVIS remembers about you", "project": "project files", "web_content": "web page text",
                  "screenshot": "screenshots"}
SAMPLE = "jarvis-trust-contract-example"  # a name inside a folder, only used to ask the permission engine

# Fixed behaviour that no setting can change, each with the release-gate item that proves it.
BUILT_IN_NEVER = [
    ("Touch files outside your approved folders, or write to its own data or settings", "Permission bypass"),
    ("Do a high-stakes action (tier 3–4) without asking you, whatever a rule says", "Permission bypass"),
    ("Reuse an approval for anything other than the exact action you approved", "Duplicate-action prevention"),
    ("Follow instructions found inside files, web pages, emails or app data", "Prompt injection"),
    ("Send email: it only saves drafts for you to send", "Permission bypass"),
    ("Keep working while the emergency stop is on", "Emergency stop (protected)"),
    ("Spend more than your monthly budget", "Budget guard (protected)"),
    ("Hide a failure, or report unverified work as done", "Honest reporting"),
    ("Write what you said into its logs (they hold counts and ids, not content)", "Privacy and data disclosure"),
    ("Change its own code: improvements are proposals you approve", "Policy (propose-only)"),
]
POLICY = "Policy (propose-only)"  # the owner's rule, not a test


@dataclass
class Line:
    text: str
    source: str  # where it comes from: a policy rule, a setting, a grant, or a release-gate item


@dataclass
class Contract:
    generated: str
    on_its_own: list[Line] = field(default_factory=list)
    asks_first: list[Line] = field(default_factory=list)
    never: list[Line] = field(default_factory=list)
    privacy: list[Line] = field(default_factory=list)
    phone: list[Line] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _home(p: Path | str) -> str:
    s, home = str(p), str(Path.home())
    return "~" + s[len(home):] if s == home or s.startswith(home + "/") else s


def _phrase(key: tuple[str, str]) -> str:
    return PHRASES.get(key, f"{key[0]}.{key[1]}")


def _places(kernel) -> list[Path]:
    """Every approved folder, plus each folder a path rule names inside one, so a narrower allow/deny shows."""
    out = list(kernel.policy.roots)
    for rule in kernel.policy.rules:
        for res in rule.resources:
            if res.endswith("/**") and res.startswith("/"):
                p = Path(res[:-3])
                if p not in out:
                    out.append(p)
    return out


def contract(kernel) -> Contract:
    perms, policy, reg = kernel.permissions, kernel.policy, kernel.registry
    c = Contract(generated=datetime.now().astimezone().isoformat(timespec="seconds"))
    on_own: dict[str, list[str]] = {}
    asks: dict[str, list[str]] = {}
    never: dict[str, list[str]] = {}
    for tool in sorted(reg.names()):
        spec = reg.get(tool)
        for action, a in spec.actions.items():
            key = (tool, action)
            if a.resource_kind is ResourceKind.PATH:
                seen: dict[Effect, list[Path]] = {}
                for place in _places(kernel):
                    d = perms.evaluate(tool=tool, action=action, tier=a.tier, resource_kind=a.resource_kind,
                                       resource=str(place / SAMPLE))
                    if any(place == p or p in place.parents for p in seen.get(d.effect, [])):
                        continue  # already covered by a folder around it with the same answer
                    seen.setdefault(d.effect, []).append(place)
                    where = f"in {_home(place)}"
                    {Effect.ALLOW: on_own, Effect.CONFIRM: asks, Effect.DENY: never}[d.effect] \
                        .setdefault(_phrase(key), []).append(where if d.effect is not Effect.DENY or not d.rule_id
                                                             else f"{where} (rule “{d.rule_id}”)")
            else:
                resource = "https://example.com/" if a.resource_kind is ResourceKind.URL else None
                d = perms.evaluate(tool=tool, action=action, tier=a.tier, resource_kind=a.resource_kind, resource=resource)
                bucket = {Effect.ALLOW: on_own, Effect.CONFIRM: asks, Effect.DENY: never}[d.effect]
                note = f"rule “{d.rule_id}”" if d.rule_id else ("tier 3–4: always" if a.tier >= Tier.EXTERNAL else "")
                bucket.setdefault(_phrase(key), []).append(note)
    for bucket, target, src in ((on_own, c.on_its_own, "permission engine"), (asks, c.asks_first, "permission engine"),
                                (never, c.never, "permission engine")):
        for phrase, wheres in bucket.items():
            places = [w for w in wheres if w]
            target.append(Line(phrase[0].upper() + phrase[1:] + (": " + "; ".join(dict.fromkeys(places)) if places else ""), src))
    if not policy.roots:
        c.never.append(Line("Read or change any of your files (no folders approved yet)", "policy"))
    c.never += [Line(text, "your policy: every change to JARVIS is proposed and approved by you" if item == POLICY
                     else f"release gate: {item}") for text, item in BUILT_IN_NEVER]

    # Privacy: what may leave this Mac, per kind of data.
    cfg = kernel.model_config
    cloud = [p.name for p in cfg.providers if p.enabled and p.kind != "ollama"]
    local_only = set(cfg.local_only_categories)
    grants = [g for g in kernel.models.router.gate.grants.list() if not g.get("revoked_at")]
    if not cloud:
        c.privacy.append(Line("Nothing is sent to an online AI: no cloud provider is switched on", "settings"))
    for cat in ("conversation", "file_content", "memory", "project", "web_content", "screenshot"):
        name = CATEGORY_NAMES[cat]
        if cat in local_only or Category(cat).value in local_only:
            c.privacy.append(Line(f"Never leaves this Mac: {name}", "settings: [privacy] local_only_categories"))
            continue
        if not cloud:
            continue
        standing = [g for g in grants if g["category"] == cat]
        if standing:
            for g in standing:
                until = f" until {g['expires_at'][:10]}" if g.get("expires_at") else ""
                c.privacy.append(Line(f"May be sent to {g['provider']} without asking{until}: {name}",
                                      f"grant {g['id']} (you created it; revocable)"))
        else:
            c.privacy.append(Line(f"Asks you each time before sending to {', '.join(cloud)}: {name}", "privacy gate"))
    limit = cfg.monthly_limit_usd
    c.privacy.append(Line("Spends nothing: the monthly budget is $0" if limit == 0 else
                          f"Spends at most ${limit:.2f} a month, then stops", "settings: [budget]"))

    remote = cfg.remote or {}
    if remote.get("enabled"):
        c.phone += [Line("Only your paired iPhone can connect, through your Tailscale network (never the open internet)",
                         "settings: [remote]"),
                    Line("Every approval from the phone needs Face ID; pairing new devices only at the Mac",
                         "release gate: Permission bypass")]
    else:
        c.phone.append(Line("Phone access is off: the dashboard only answers on this Mac", "settings: [remote]"))
    c.phone.append(Line("Your voice is never treated as proof that it's you", "built in"))
    return c


def as_text(c: Contract) -> str:
    out = [f"JARVIS Trust Contract · generated {c.generated} from your current settings", ""]
    for title, lines in (("Does on its own", c.on_its_own), ("Always asks you first", c.asks_first),
                         ("Never does", c.never), ("Your data and money", c.privacy), ("Your phone", c.phone)):
        out.append(title.upper())
        out += [f"  • {ln.text}" for ln in lines] or ["  (nothing)"]
        out.append("")
    return "\n".join(out).rstrip()
