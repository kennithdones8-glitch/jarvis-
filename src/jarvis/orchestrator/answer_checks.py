"""Cheap, deterministic checks on a finished answer, each naming a specific problem the model can fix in one retry.

They target failures seen on the owner's Mac with small local models, each of which would also happen in real use:
- saying "I don't have access to your calendar" right after JARVIS looked the calendar up;
- ignoring an explicit answer format ("end with the number on its own line", "finish with four lines…");
- getting a puzzle with several conditions wrong without checking it;
- refusing a harmless task outright because the data contained a planted instruction.

None of these can make an answer right; they only point out a concrete, checkable problem. The caller retries at
most once, and only with a local model (a Claude retry would be a new request needing consent).
"""

from __future__ import annotations

import re

DENIES_ACCESS = re.compile(
    r"\b(i\s+(do\s+not|don'?t|can\s*not|can'?t|am\s+unable\s+to|'m\s+unable\s+to)\s+(have\s+)?(real[- ]time\s+)?"
    r"(access|see|view|check|look\s+at)\b[^.]{0,40}\b(calendar|schedule|reminders?|notes|files?|data|information)"
    r"|\bas an ai\b[^.]{0,60}\b(access|calendar|schedule|reminders?))", re.I)
REFUSAL = re.compile(
    r"^\W*(i\s+(can\s*not|can'?t|won'?t|will\s+not|am\s+unable\s+to|'m\s+unable\s+to|must\s+decline\s+to)\s+"
    r"(fulfil+|help|comply|assist|do|complete|perform|process|carry\s+out)\b|sorry,?\s+(but\s+)?i\s+can)", re.I)
ON_ITS_OWN_LINE = re.compile(r"\bend (?:with|on) (?:the|a|your) ([\w ]{1,30}?) on (?:its|a) own line\b", re.I)
FINISH_WITH_LINES = re.compile(
    r"\b(?:finish|end) with (\w+) lines?(?: in the form \"([^\"]{1,60})\")?", re.I)
NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
           "ten": 10}
PUZZLE = re.compile(
    r"\b(each (?:get|gets|has|have|take|takes)|who (?:has|gets|is|sits|owns) (?:each|which|what)|neither\b.{1,40}\bnor|"
    r"is (?:earlier|later|older|younger|taller|shorter) than|(?:is|are) not (?:at|in|on|next to)|exactly one of|"
    r"logic puzzle|riddle)", re.I | re.S)


def denies_access(answer: str) -> bool:
    return bool(DENIES_ACCESS.search(answer or ""))


def refuses(answer: str) -> bool:
    return bool(REFUSAL.search((answer or "").strip()[:300]))


def is_puzzle(question: str) -> bool:
    """A question with several conditions to satisfy at once (at least two puzzle-like phrases)."""
    return len(PUZZLE.findall(question or "")) >= 2


def _lines(answer: str) -> list[str]:
    return [ln.strip() for ln in (answer or "").strip().splitlines() if ln.strip()]


def _form_pattern(form: str) -> re.Pattern:
    """ "9:00 Name" → digits match digits, a capitalised placeholder word matches any word, the rest literally."""
    out = []
    for tok in re.split(r"(\d+|[A-Z][a-z]+)", form):
        if not tok:
            continue
        if tok.isdigit():
            out.append(r"\d{1,%d}" % max(2, len(tok)))
        elif tok[0].isupper() and tok[1:].islower():
            out.append(r"[\w'-]+")
        else:
            out.append(re.escape(tok).replace(r"\ ", r"\s+"))
    return re.compile(r"^\W*" + "".join(out) + r"\W*$")


def format_problems(question: str, answer: str) -> list[str]:
    """Explicit format requests in the question that the answer doesn't follow."""
    problems, lines = [], _lines(answer)
    if m := ON_ITS_OWN_LINE.search(question or ""):
        last = lines[-1] if lines else ""
        if not (len(last) <= 30 and re.search(r"\d", last) and len(re.findall(r"[A-Za-z]{3,}", last)) <= 2):
            problems.append(f"the question asks you to end with {m.group(1)} on its own line: make the last line "
                            "just that (for example \"100 g\"), with nothing else on it")
    if m := FINISH_WITH_LINES.search(question or ""):
        n = NUMBERS.get(m.group(1).lower()) or (int(m.group(1)) if m.group(1).isdigit() else None)
        if n:
            tail = lines[-n:]
            pattern = _form_pattern(m.group(2)) if m.group(2) else None
            if len(tail) < n or (pattern and not all(pattern.match(ln) for ln in tail)):
                form = f' in the form "{m.group(2)}"' if m.group(2) else ""
                problems.append(f"the question asks you to finish with {n} lines{form}: end with exactly those "
                                f"{n} lines, one per line, nothing after them")
    return problems


def chat_problems(question: str, answer: str, *, looked_up: bool, puzzle: bool = True) -> list[str]:
    """Everything worth one retry for a chat answer (the grounding check for times is separate)."""
    problems = []
    if looked_up and denies_access(answer):
        problems.append("you say you can't access the owner's data, but JARVIS has just looked it up for you: it is "
                        "in the <lookup> block above. Answer from it")
    problems += format_problems(question, answer)
    if puzzle and is_puzzle(question):  # always worth one check: nothing in the answer shows it's wrong
        problems.append("this is a puzzle with several conditions: check your answer against each condition in the "
                        "question one by one, fix anything that breaks one, then give the final answer")
    return problems


# ---- "list every decision from both meetings": nothing left out (owner's Mac, 0.19.0 benchmark) -----------------
# Real failure: asked to list every decision from two meeting notes, the 7B wrote four items and dropped "the budget
# is approved at 12,000". When the instruction asks to list/combine X and the data has lines labelled "X:"/"Xs:", JARVIS
# checks each labelled sentence is in the text, and names the missing ones for one retry. Nothing else is checked.
WANTS_ALL = re.compile(r"\b(every|all|each|list|lists|listing|combine[ds]?|merge[ds]?|both|full)\b", re.I)
STOP = frozenset("that this with from have will were been they them their then than there these those what when "
                 "which while into onto about also just only some more most very would could should does doing done "
                 "being over under after before again each other such your yours ours".split())


def _words(text: str) -> set[str]:
    return {w.strip(".,;:'\"").replace(",", "") for w in re.findall(r"[a-z0-9][a-z0-9,'.]*", text.lower())
            if len(w.strip(".,;:'\"")) >= 4 and w.strip(".,;:'\"") not in STOP}


def listed_items(instruction: str, inputs: list[str]) -> list[str]:
    """Sentences under a "Decisions:" (etc.) label in the data, when the instruction asks for every decision."""
    if not WANTS_ALL.search(instruction or ""):
        return []
    nouns = {w.lower().rstrip("s") for w in re.findall(r"[A-Za-z]{4,20}", instruction or "")}
    nouns -= {"item", "thing", "line", "word", "file", "note", "meeting", "point", "both", "time", "list", "every",
              "each", "combine", "combined", "merge", "full", "from", "into", "with", "save", "write", "read"}
    items: list[str] = []
    for noun in nouns:
        label = re.compile(rf"(?im)^\s*{re.escape(noun)}s?\b[^:\n]{{0,20}}:\s*(.+)$")
        for text in inputs:
            for m in label.finditer(text or ""):
                items += [x.strip() for x in re.split(r"(?<=[.!?;])\s+", m.group(1)) if len(x.strip()) > 3]
    return items[:40]


def left_out(instruction: str, inputs: list[str], text: str) -> list[str]:
    """Items the instruction asked for "every" of that the written text doesn't mention (by their key words)."""
    have = _words(text)
    missing = []
    for item in listed_items(instruction, inputs):
        key = _words(item)
        if key and len(key & have) * 2 < len(key):  # fewer than half of its key words: treat it as left out
            missing.append(item)
    return missing


# ---- the facts JARVIS worked out are all in the answer (hard set, smarter-v2) -------------------------------------
# Real failure: JARVIS listed "Due in the window you asked about (1): Call plumber" and the answer named only the two
# overdue reminders. The reminders JARVIS listed as overdue or due in the window asked about must each be named.
FACT_LIST = re.compile(r"^- (?:Overdue|Due in the window you asked about[^:]*?) \((\d+)\): (.+)$", re.M)


def facts_left_out(answer: str, lookup_text: str) -> list[str]:
    """Reminders JARVIS listed (overdue, or due in the window asked about) that the answer doesn't name."""
    missing = []
    low = (answer or "").lower()
    for m in FACT_LIST.finditer(lookup_text or ""):
        if m.group(1) == "0":
            continue
        for title in (t.strip() for t in m.group(2).split(", ")):
            every = re.findall(r"[a-z0-9]+", title.lower())
            # the words that name it ("council", "plumber"); short verbs like "pay", "buy" aren't required
            words = [w for w in every if len(w) >= 4] or [w for w in every if len(w) >= 3]
            if title and title.lower() not in low and not (words and all(w in low for w in words)):
                missing.append(title)
    return missing


# ---- "what's my first commitment?": the first event JARVIS worked out is the answer ------------------------------
# Real failure (owner's Mac, smarter-v2, 7B): the facts said "First event on Mon 09 Nov: 09:00–09:30 Standup" and the
# answer called the 13:00 lunch the first commitment (planning-free 9/10 with the 3B, 4/10 with the 7B). Only checked
# when the question asks what comes first and JARVIS listed the first event of 1–3 days; nothing else is judged.
ASKS_FIRST = re.compile(r"\b(first|earliest)\b[^?.!]{0,40}\b(commitment|event|meeting|appointment|thing|plan|"
                        r"booking|call)s?\b|\bwhat time do i (?:start|have to be)\b|\bwhen do i start\b", re.I)
FIRST_EVENT = re.compile(r"^- First event on [^:]+: (\d{2}:\d{2})–\d{2}:\d{2} (.+)$", re.M)


def first_event_left_out(question: str, answer: str, lookup_text: str) -> list[str]:
    """The first events JARVIS worked out that an answer to "what's first?" doesn't name (by title or start time)."""
    if not ASKS_FIRST.search(question or ""):
        return []
    found = FIRST_EVENT.findall(lookup_text or "")
    if not 1 <= len(found) <= 3:
        return []
    low = (answer or "").lower()
    missing = []
    for start, title in found:
        words = [w for w in re.findall(r"[a-z0-9]+", title.lower()) if len(w) >= 3] or [title.lower()]
        named = all(w in low for w in words)
        hour = start.lstrip("0") if not start.startswith("00") else start
        timed = start in low or hour in low
        if not (named and timed):
            missing.append(f"{title.strip()} at {start}")
    return missing
