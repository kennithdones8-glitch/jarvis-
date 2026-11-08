"""Smarter answers from experience: when you ask something similar to an earlier question, the answer you rated
helpful comes back as a reference, and one you rated unhelpful as something not to repeat.

Local only: the earlier exchange is read from the conversation records on this Mac (so memory settings, exclusions
and `forget` apply, and a forgotten exchange can never come back). It joins the prompt as conversation, exactly like
chat history, so the same privacy rules decide whether a cloud model may see it. At most one of each.
"""

from __future__ import annotations

import re
from typing import Any

from ..models import Message
from ..models.types import Category

SIMILAR = 0.5   # share of meaningful words two questions must have in common


def _words(text: str) -> set[str]:
    stop = {"the", "and", "for", "you", "what", "how", "can", "does", "with", "about", "this", "that", "are", "was", "is"}
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2 and w not in stop}


def past_exchanges(kernel, message: str) -> list[dict[str, Any]]:
    mem = kernel.memory
    if not mem.settings.enabled:
        return []
    want = _words(message)
    if len(want) < 2:
        return []
    found, seen = [], set()
    for r in mem.search_records(message, limit=25):
        if r["role"] != "user" or r["id"] in seen:
            continue
        seen.add(r["id"])
        have = _words(r["content"])
        if not have or len(want & have) / len(want | have) < SIMILAR:
            continue
        fb = kernel.db.one("SELECT rating FROM feedback WHERE target = 'reply' AND ref = ? ORDER BY created_at DESC LIMIT 1", (r["id"],))
        if fb is None:
            continue
        reply = kernel.db.one("SELECT content FROM records WHERE session = ? AND role = 'assistant' AND created_at >= ? "
                              "ORDER BY created_at LIMIT 1", (r["session"], r["created_at"]))
        if reply is None:
            continue
        found.append({"record": r["id"], "rating": fb["rating"], "question": r["content"], "answer": reply["content"]})
    best = next((x for x in found if x["rating"] > 0), None)
    worst = next((x for x in found if x["rating"] < 0), None)
    return [x for x in (best, worst) if x]


def context_message(kernel, message: str) -> tuple[Message | None, int]:
    past = past_exchanges(kernel, message)
    if not past:
        return None, 0
    parts = []
    for x in past:
        if x["rating"] > 0:
            parts.append(f"An earlier answer the user rated HELPFUL for a similar question. Reuse what worked; check it still fits.\n"
                         f"Q: {x['question'][:500]}\nA: {x['answer'][:1500]}")
        else:
            parts.append(f"An earlier answer the user rated NOT HELPFUL for a similar question. Don't repeat its approach.\n"
                         f"Q: {x['question'][:500]}\nA: {x['answer'][:600]}")
    kernel.audit.record("learn.recalled", helpful=sum(1 for x in past if x["rating"] > 0),
                        unhelpful=sum(1 for x in past if x["rating"] < 0))
    return Message("user", "<past_experience>\n" + "\n\n".join(parts) + "\n</past_experience>", Category.CONVERSATION), len(past)
