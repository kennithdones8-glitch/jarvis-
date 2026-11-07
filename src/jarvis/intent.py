"""Which kind of message is this: a question (ask), something to look up on the web (research), or a task (do)?

The owner chose: instant rules first; only when the rules are unsure, one short call to a model on this Mac
(never the cloud). The answer is only a suggestion: research and tasks are confirmed with one tap in the
dashboard before anything happens, and a task still only becomes a plan that waits for approval.
"""

from __future__ import annotations

import re
from typing import Callable

MODES = ("ask", "research", "do")

_LEAD = r"^(?:(?:hey |ok |okay )?jarvis[,:]?\s+)?(?:please\s+)?(?:can you\s+|could you\s+|would you\s+|i need you to\s+|i want you to\s+)?"
_DO = re.compile(_LEAD + r"(?:remind me|set (?:a |an )?(?:reminder|timer|alarm)|add (?:a |an |this )?(?:reminder|event|note|task|to-?do|meeting)|"
                 r"schedule|create (?:a |an )?(?:note|reminder|event|file|folder|document|list)|make (?:a |an )?(?:note|reminder|folder|file|list)|"
                 r"send |email |text |message |move |rename |delete |organi[sz]e |clean up |back ?up |book |cancel |"
                 r"summari[sz]e (?:the |my |all )?(?:pdfs?|files?|documents?|folder|downloads)|save (?:this|it|that|a)|put (?:this|it) in|"
                 r"write (?:a |an )?(?:file|note|reminder))", re.I)
_DO_ANYWHERE = re.compile(r"\bremind me\b|\b(?:save|put|add|write)\b[^.?!]{0,40}\b(?:to|in|into) my (?:notes|reminders|calendar|files|"
                          r"downloads|documents)\b|\bin my (?:downloads|documents) folder\b", re.I)
_RESEARCH = re.compile(r"\b(?:latest|newest|breaking|current(?:ly)?|right now|today'?s|this week'?s|news|headlines|"
                       r"stock price|share price|exchange rate|weather|forecast|who won|score of|release date|"
                       r"search (?:the web|online|for)|look (?:it |this )?up|find (?:me )?(?:sources|articles|reviews)|"
                       r"with sources|cite sources|research)\b|\b20(?:2[5-9]|3\d)\b", re.I)
_ASK = re.compile(r"^(?:hi|hello|hey|thanks|thank you|good (?:morning|evening|afternoon))\b|^(?:what|why|how|who|when|where|which|is|are|"
                  r"do|does|did|can|could|should|would|explain|tell me|define|what's|whats)\b", re.I)

PROMPT = ("Classify the user's message for a personal assistant. Answer with exactly one word:\n"
          "ASK - a question or conversation it can answer from knowledge;\n"
          "RESEARCH - it needs current information from the web;\n"
          "DO - the user wants an action done on their computer, calendar, reminders, notes, files or messages.\n"
          "Message: {text}\nAnswer:")


def by_rules(text: str) -> tuple[str | None, str]:
    """(mode, reason) when the rules are sure; (None, reason) when a model should decide."""
    t = " ".join(text.split())
    if not t:
        return "ask", "empty"
    if _DO.search(t) or _DO_ANYWHERE.search(t):
        return "do", "asks for an action"
    if _RESEARCH.search(t):
        return "research", "needs current or sourced information"
    if _ASK.search(t) or t.endswith("?"):
        return "ask", "a question"
    return None, "unclear"


def classify(text: str, complete: Callable[[str], str] | None = None) -> dict[str, str]:
    """``complete(prompt) -> text`` is a local-only model call (the caller guarantees it never leaves the Mac).
    Any failure falls back to "ask", which takes no action and sends nothing to the web."""
    text = text[:2000]
    mode, reason = by_rules(text)
    if mode:
        return {"mode": mode, "by": "rules", "reason": reason}
    if complete is not None:
        try:
            answer = complete(PROMPT.format(text=text)).strip().split()
            word = answer[0].strip(".:,").lower() if answer else ""
            if word in MODES:
                return {"mode": word, "by": "local model", "reason": "decided on this Mac"}
        except Exception:  # noqa: BLE001 - no model, a timeout: just answer it as a question
            pass
    return {"mode": "ask", "by": "default", "reason": "answered as a question"}
