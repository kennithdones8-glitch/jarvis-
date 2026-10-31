"""Grounding check for answers about the owner's calendar and reminders.

Every time of day an answer mentions ("3pm", "14:30") must appear in what JARVIS looked up, or in the owner's own
question. A time that appears in neither is something the model made up or misread. Deterministic and cheap: it
can't prove an answer right, but it reliably catches invented times, the most damaging calendar mistake.
"""

from __future__ import annotations

import re

TIME = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)(?![a-z])|\b(\d{1,2}):(\d{2})\b", re.I)
SOURCES = ("Calendar", "Reminders")


def times_in(text: str) -> set[str]:
    out = set()
    for m in TIME.finditer(text or ""):
        if m.group(3):  # 3pm, 9:30 a.m.
            h, mins, ampm = int(m.group(1)), int(m.group(2) or 0), m.group(3).lower().replace(".", "")
            if not 1 <= h <= 12 or mins > 59:
                continue
            h = (h % 12) + (12 if ampm == "pm" else 0)
        else:  # 14:30
            h, mins = int(m.group(4)), int(m.group(5))
            if h > 23 or mins > 59:
                continue
        out.add(f"{h:02d}:{mins:02d}")
    return out


def applies(checked: list[str]) -> bool:
    return any(label.startswith(SOURCES) for label in checked)


def unsupported_times(answer: str, looked_up: str, question: str) -> list[str]:
    return sorted(times_in(answer) - times_in(looked_up) - times_in(question))
