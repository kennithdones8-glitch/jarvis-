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

# "show me …": which projection a request for a visual view means (checked before everything else)
_SHOW = re.compile(r"^(?:(?:hey |ok )?jarvis[,:]?\s+)?(?:please\s+)?(?:show|display|visuali[sz]e|project|open)\s+(?:me\s+)?(?:the\s+|my\s+|your\s+)?(.+)$", re.I)
SHOW = (("architecture", r"architecture|code ?base|your code|source|software|structure"),
        ("workflow", r"what you(?:'re| are) doing|doing|tasks?|missions?|workflow|progress of"),
        ("neural", r"(?:what )?you(?:'ve| have)? learn|learn|knowledge|lessons?|brain|memory graph|neural"),
        ("globe", r"globe|map|world|places|where"),
        ("data", r"data|stats|statistics|performance|charts?|numbers|analytics"),
        ("timeline", r"timeline|history|milestones|roadmap|projects?"),
        ("security", r"security|permissions?|shield|approvals?|what you can do"),
        ("simulation", r"experiments?|simulations?|lab"))


# Direct Mac commands (Music, system): recognised by rules and run through the permission engine, no model involved
_LEAD2 = r"^(?:(?:hey |ok )?jarvis[,:]?\s+)?(?:please\s+|can you\s+|could you\s+)?"
COMMANDS = (
    (re.compile(_LEAD2 + r"(?:pause|stop)(?: the| my)? (?:music|song|track)\W*$|^pause\W*$", re.I), ("music", "control", {"action": "pause"})),
    (re.compile(_LEAD2 + r"(?:resume|play)(?: the| some| my)? music\W*$|^(?:resume|play)\W*$", re.I), ("music", "control", {"action": "play"})),
    (re.compile(_LEAD2 + r"(?:skip|next)(?: (?:this )?(?:song|track))?\W*$|^skip this(?: song| track)?\W*$", re.I), ("music", "control", {"action": "next"})),
    (re.compile(_LEAD2 + r"(?:previous|go back(?: a)?)(?: song| track)?\W*$", re.I), ("music", "control", {"action": "previous"})),
    (re.compile(_LEAD2 + r"(?:what(?:'s| is) playing|what song is (?:this|playing))\W*$", re.I), ("music", "now", {})),
    (re.compile(_LEAD2 + r"(?:how(?:'s| is) my (?:battery|mac)|(?:battery|disk space|wi-?fi|system) status|how much (?:battery|disk space)(?: (?:do i have|is left))?)\W*$", re.I),
     ("system", "status", {})),
    (re.compile(_LEAD2 + r"(?:turn on|enable|start) (?:do not disturb|dnd|focus)\W*$|^dnd on\W*$", re.I), ("system", "focus", {"state": "on"})),
    (re.compile(_LEAD2 + r"(?:turn off|disable|stop) (?:do not disturb|dnd|focus)\W*$|^dnd off\W*$", re.I), ("system", "focus", {"state": "off"})),
)
_PLAYLIST = re.compile(_LEAD2 + r"play (?:my |the )?(?:playlist )?[\"“]?(.{1,80}?)[\"”]?(?: playlist)?\W*$", re.I)
_VOLUME = re.compile(_LEAD2 + r"(?:set |turn )?(?:the )?(music )?volume (?:to |at )?(\d{1,3})\s*%?\W*$", re.I)


def mac_command(text: str) -> dict | None:
    t = " ".join(text.split())
    for pattern, (tool, action, args) in COMMANDS:
        if pattern.match(t):
            return {"tool": tool, "action": action, "args": dict(args)}
    if m := _VOLUME.match(t):
        level = min(100, int(m.group(2)))
        return {"tool": "music" if m.group(1) else "system", "action": "volume", "args": {"level": level}}
    if (m := _PLAYLIST.match(t)) and "playlist" in t.lower():
        return {"tool": "music", "action": "playlist", "args": {"name": m.group(1).strip()}}
    return None


def show_target(text: str) -> str | None:
    m = _SHOW.match(" ".join(text.split()))
    if not m:
        return None
    rest = m.group(1).lower()
    return next((name for name, pat in SHOW if re.search(pat, rest)), None)


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
    if cmd := mac_command(text):
        return {"mode": "command", **cmd, "by": "rules", "reason": "a direct Mac command"}
    if module := show_target(text):
        return {"mode": "show", "module": module, "by": "rules", "reason": "asks to see a projection"}
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
