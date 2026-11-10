"""Memories that disagree: two things JARVIS remembers that give different answers to the same question ("My dentist
is Dr Patel" / "My dentist is Dr Shah"). Found with plain rules on the memory text (no model, nothing sent), shown in
Memory and the suggestions feed for you to settle: keep one, and the other is deleted (as a deletion you make).

Recognised shapes: "my/our X is/are Y", "X is my Y", "I live in / work at / work for / was born in / am from Y",
"I am N years old". Two memories disagree when the subject matches and the answers differ.
"""

from __future__ import annotations

import re
from typing import Any

_MY = re.compile(r"^(?:my|our)\s+(?P<key>[a-z][\w' -]{0,40}?)\s+(?:is|are|was|=)\s+(?P<val>.+)$")
_IS_MY = re.compile(r"^(?P<val>[\w' .-]{1,40}?)\s+is\s+my\s+(?P<key>[a-z][\w' -]{0,30})$")
_I = re.compile(r"^i\s+(?P<key>live in|work at|work for|was born in|am from|go to)\s+(?P<val>.+)$")
_AGE = re.compile(r"^i(?:'m| am)\s+(?P<val>\d{1,3})(?:\s+years? old)?$")
_IS_MY_UNIQUE = {"wife", "husband", "partner", "boss", "dentist", "doctor", "landlord", "manager", "mum", "mom", "dad",
                 "father", "mother", "girlfriend", "boyfriend", "fiancé", "fiance", "fiancée", "fiancee"}


def _norm(text: str) -> str:
    t = " ".join(str(text).lower().replace("’", "'").split())
    return re.sub(r"[.!]+$", "", t).strip()


def claim(text: str) -> tuple[str, str] | None:
    """(subject, answer) if the memory states one fact in a recognised shape, else None."""
    t = _norm(text)
    if m := _AGE.match(t):
        return "my age", m["val"]
    if m := _I.match(t):
        return f"i {m['key']}", m["val"]
    if m := _MY.match(t):
        return f"my {m['key'].strip()}", m["val"].strip()
    if (m := _IS_MY.match(t)) and m["key"].strip() in _IS_MY_UNIQUE:
        return f"my {m['key'].strip()}", m["val"].strip()
    return None


def find(memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pairs that disagree, newest first: [{"subject", "a": memory, "b": memory}] (a is the newer one)."""
    by_key: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for mem in memories:
        c = claim(mem.get("text", ""))
        if c:
            by_key.setdefault(c[0], []).append((c[1], mem))
    out = []
    for key, items in by_key.items():
        items.sort(key=lambda x: x[1].get("created_at") or "", reverse=True)
        newest_val, newest = items[0]
        for val, other in items[1:]:
            if val != newest_val:
                out.append({"subject": key, "a": newest, "b": other})
                break
    out.sort(key=lambda p: p["a"].get("created_at") or "", reverse=True)
    return out
