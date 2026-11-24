"""Date arithmetic done by code, not by the model (owner-approved, 24 Nov 2026).

Small local models count days badly: asked for "the 10th meeting, every 3rd day from Monday 2 March 2026" they slip a
day partway through, and asked for "the day before I travel" they reach for today's date instead of the flight date
they were told about. Like the calendar facts (``lookup.FACTS_HEAD``), JARVIS works these out exactly and hands the
model the results to answer from:

- **Repeats**: "every N days/weeks" from a start date, and which occurrence the question asks about (the 10th, ...).
- **Offsets**: "the day before", "3 days after", "a week before" — applied to every explicit date in the message and
  in what JARVIS remembers, each labelled with the sentence it came from, so the model picks the right one.
- **Weekdays** of the dates involved.

Nothing here guesses meaning: it only computes from dates and numbers that are written down. When nothing applies it
returns nothing and the prompt is unchanged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

MONTHS = {m: i for i, m in enumerate(("january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"), 1)}
MONTHS.update({m[:3]: i for m, i in list(MONTHS.items())})
MONTHS["sept"] = 9
_MON = "|".join(sorted(MONTHS, key=len, reverse=True))
_DAYNAME = r"(?:(?:mon|tues|wednes|thurs|fri|satur|sun)day,?\s+)?"
DATE_DM = re.compile(rf"\b{_DAYNAME}(?:the\s+)?(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MON})\b\.?(?:,?\s+(\d{{4}}))?", re.I)
DATE_MD = re.compile(rf"\b{_DAYNAME}({_MON})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(\d{{4}}))?", re.I)
DATE_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")

WORDNUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
           "ten": 10, "a": 1, "an": 1, "other": 2, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6,
           "seventh": 7}
_NUM = r"(\d{1,3}|" + "|".join(sorted(WORDNUM, key=len, reverse=True)) + r")"
EVERY = re.compile(rf"\bevery\s+(?:{_NUM}(?:st|nd|rd|th)?\s+)?(day|week)s?\b", re.I)
NTH = re.compile(r"\b(\d{1,3})(?:st|nd|rd|th)\s+(?:meeting|session|time|occurrence|class|visit|one|game|match|dose|"
                 r"payment|lesson|appointment|delivery|event|run|walk|practice)\b"
                 r"|\b(?:meeting|session|occurrence|class|visit|lesson|payment|dose)\s+(?:number\s+|no\.?\s*|#)?(\d{1,3})\b",
                 re.I)
OFFSET = re.compile(rf"\b(?:the\s+)?{_NUM}?\s*(day|week)s?\s+(before|after|later|earlier|prior)\b", re.I)
# The question itself must be about a date or a day; a memory that says "the day before" isn't enough on its own.
DATEISH = re.compile(r"\b(dates?|when|days?|weeks?|weekdays?|deadline|until|before|after|later|earlier)\b", re.I)
WEEKDAY_Q = re.compile(r"\b(weekday|day of the week|what day|which day)\b", re.I)
MAX_OCCURRENCES = 60


@dataclass(frozen=True)
class Found:
    day: date
    text: str          # as written
    source: str        # the sentence it came from
    year_given: bool


def _num(s: str | None, default: int = 1) -> int:
    if not s:
        return default
    s = s.lower()
    return int(s) if s.isdigit() else WORDNUM.get(s, default)


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text or "") if s.strip()]


RECENT_DAYS = 60   # a date without a year up to this many days ago is this year's ("from Nov 1st"); older: next year's


def _make(y: int | None, m: int, d: int, today: date) -> tuple[date, bool] | None:
    try:
        if y:
            return date(y, m, d), True
        this = date(today.year, m, d)
        if this > today + timedelta(days=366 - RECENT_DAYS):
            this = date(today.year - 1, m, d)     # e.g. "20 December" asked in early January
        return (this if this >= today - timedelta(days=RECENT_DAYS) else date(today.year + 1, m, d)), False
    except ValueError:
        return None


_QUOTED = re.compile(r'"[^"\n]{0,80}"|“[^”\n]{0,80}”|\blike\s+[A-Z][a-z]+day\s+\d{1,2}\s+[A-Z][a-z]+\b')


def unquoted(text: str) -> str:
    """The message without its examples: 'End with a line like "Tuesday 5 May"' names a format, not a date."""
    return _QUOTED.sub(" ", text or "")



def dates_in(text: str, today: date) -> list[Found]:
    """Every written-out date in ``text`` (e.g. "Monday 2 March 2026", "14 August", "Aug 14th", "2026-08-14")."""
    out: list[Found] = []
    seen: set[tuple[int, int]] = set()
    for sentence in _sentences(text):
        here: list[tuple[int, Found]] = []
        for rx, order in ((DATE_DM, "dm"), (DATE_MD, "md"), (DATE_ISO, "iso")):
            for m in rx.finditer(sentence):
                if any(a < m.end() and m.start() < b for a, b in seen):
                    continue
                if order == "iso":
                    made = _make(int(m.group(1)), int(m.group(2)), int(m.group(3)), today)
                elif order == "dm":
                    made = _make(int(m.group(3)) if m.group(3) else None, MONTHS[m.group(2).lower().rstrip(".")],
                                 int(m.group(1)), today)
                else:
                    made = _make(int(m.group(3)) if m.group(3) else None, MONTHS[m.group(1).lower().rstrip(".")],
                                 int(m.group(2)), today)
                if made:
                    seen.add((m.start(), m.end()))
                    here.append((m.start(), Found(made[0], m.group(0).strip(), sentence, made[1])))
        out += [f for _, f in sorted(here, key=lambda x: x[0])]   # in the order they're written
        seen.clear()
    return out


def show(d: date, year: bool = True) -> str:
    return f"{d:%A} {d.day} {d:%B}" + (f" {d.year}" if year else "")


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def repeats(message: str, today: date) -> list[str]:
    every = EVERY.search(message)
    if not every:
        return []
    step = _num(every.group(1)) * (7 if every.group(2).lower() == "week" else 1)
    starts = dates_in(message, today)
    if not starts or step < 1:
        return []
    start = starts[0]
    nth = sorted({int(a or b) for a, b in NTH.findall(message)}, reverse=True)   # "the 10th", not "(that is the 1st)"
    lines = []
    if nth and 1 <= nth[0] <= 1000:
        n = nth[0]
        target = start.day + timedelta(days=step * (n - 1))
        lines.append(f"Every {step} day{'s' if step != 1 else ''} starting {show(start.day)} (the 1st): the {_ordinal(n)} "
                     f"is {show(target)} ({n - 1} × {step} = {step * (n - 1)} days after the 1st).")
        count = min(n, MAX_OCCURRENCES)
    else:
        count = 10
    listed = [f"{_ordinal(i + 1)} {show(start.day + timedelta(days=step * i))}" for i in range(count)]
    lines.append("In order: " + "; ".join(listed) + ("" if count == (nth[0] if nth else 0) or not nth else " …"))
    return lines


def offsets(message: str, remembered: list[str], today: date) -> list[str]:
    asked = [(m.group(1), m.group(2).lower(), m.group(3).lower())
             for t in (message, *remembered) for m in OFFSET.finditer(t)]
    if not asked:
        return []
    kinds: list[tuple[int, str]] = []
    for num, unit, way in asked:
        days = _num(num) * (7 if unit == "week" else 1)
        sign = -1 if way in ("before", "earlier", "prior") else 1
        n = _num(num)
        label = (f"the {unit} {'before' if sign < 0 else 'after'}" if n == 1
                 else f"{n} {unit}s {'before' if sign < 0 else 'after'}")
        if (sign * days, label) not in kinds:
            kinds.append((sign * days, label))
    lines = []
    for f in [*dates_in(message, today), *(d for t in remembered for d in dates_in(t, today))]:
        parts = [f"{label}: {show(f.day + timedelta(days=delta))}" for delta, label in kinds]
        guess = "" if f.year_given else " (no year given: the next one)"
        lines.append(f"“{f.source[:120]}” → {show(f.day)}{guess}; " + "; ".join(parts) + ".")
    return lines[:12]


def weekdays(message: str, today: date) -> list[str]:
    if not WEEKDAY_Q.search(message):
        return []
    return [f"{f.text} is a {f.day:%A} ({show(f.day)})." for f in dates_in(message, today)][:6]


HEAD = ("Dates worked out by JARVIS's code (exact; answer from these lines instead of counting days yourself, and "
        "pick the line that matches what the owner is asking about):")


def facts(message: str, remembered: list[str] | None = None, today: date | None = None) -> str | None:
    today = today or datetime.now().astimezone().date()
    message = unquoted(message)
    if not DATEISH.search(message) and not EVERY.search(message):
        return None
    lines = [*repeats(message, today), *offsets(message, remembered or [], today), *weekdays(message, today)]
    lines = list(dict.fromkeys(lines))
    return (HEAD + "\n" + "\n".join(f"- {x}" for x in lines)) if lines else None


__all__ = ["HEAD", "dates_in", "facts", "offsets", "repeats", "weekdays"]
