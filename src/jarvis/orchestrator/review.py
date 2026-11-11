"""A second opinion: a different local model checks the work before JARVIS calls it done.

Two places, both local-only (the check never goes to the cloud, never needs your consent and costs nothing):
- Deep-mode chat answers: the reviewer reads your question and the answer. If it names a concrete error, the
  answering model gets one chance to fix it (when that answer was made on this Mac), and the reply says what the
  second opinion found either way.
- Mission plans that change something: before you press Run, the reviewer reads the request and the steps and says
  whether they do what was asked, and what worries it. It only informs you; it never approves, edits or blocks a plan.

The reviewer must be a different model from the one that wrote the work (the same model tends to agree with itself).
If none is installed, the work is shown as "not reviewed", never as checked.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ..models import ChatRequest, Message, Need
from ..models.types import Category
from .lookup import lenient_json

ANSWER_PROMPT = """You are checking another assistant's answer for JARVIS. Read the QUESTION and the ANSWER.
Decide whether the answer is correct and answers what was asked. Only say "disagree" for a concrete error you can
name (a wrong number, date, fact or step, or the question not answered). Style is not an error.
Reply with JSON only: {"verdict": "agree" | "disagree" | "unsure", "problems": ["short, specific problem", ...]}"""

PLAN_PROMPT = """You are checking a plan JARVIS made before its owner runs it. Read the REQUEST and the STEPS.
Say whether the steps do what was asked, and name anything risky or wrong: a step that changes more than asked,
the wrong file, folder, date or person, a missing step, or steps in the wrong order. Do not invent problems.
Reply with JSON only: {"verdict": "agree" | "disagree" | "unsure", "problems": ["short, specific problem", ...]}"""


@dataclass
class Opinion:
    verdict: str = "unavailable"          # agree | disagree | unsure | unavailable
    problems: list[str] = field(default_factory=list)
    model: str | None = None
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"verdict": self.verdict, "problems": self.problems[:5], "model": self.model, **({"error": self.error} if self.error else {})}


def _ask(models, system: str, content: str, *, author: str | None, purpose: str) -> Opinion:
    try:
        r = models.complete(Need("chat", prefer="quality", local_only=True, avoid=author or ""),
                            ChatRequest((Message("system", system, Category.SYSTEM_PROMPT),
                                         Message("user", content[:12000], Category.CONVERSATION, local_only=True)),
                                        max_tokens=400, temperature=0.0), purpose=purpose)
    except Exception as exc:  # noqa: BLE001 - no second model, emergency stop...: say it wasn't reviewed
        return Opinion(error=type(exc).__name__)
    try:
        data = lenient_json(r.text)
    except Exception:  # noqa: BLE001 - not JSON: unreadable, so "unsure", never a verdict
        data = None
    if not isinstance(data, dict) or data.get("verdict") not in ("agree", "disagree", "unsure"):
        return Opinion(verdict="unsure", model=f"{r.provider}/{r.model}", error="the reviewer's reply wasn't readable")
    problems = [" ".join(str(p).split())[:200] for p in (data.get("problems") or []) if str(p).strip()][:5]
    verdict = data["verdict"] if (data["verdict"] != "disagree" or problems) else "unsure"   # disagree must say why
    return Opinion(verdict=verdict, problems=problems, model=f"{r.provider}/{r.model}")


def answer_opinion(models, question: str, answer: str, *, author: str | None) -> Opinion:
    return _ask(models, ANSWER_PROMPT, f"QUESTION:\n{question}\n\nANSWER:\n{answer}", author=author,
                purpose="second opinion (answer)")


def plan_opinion(models, request: str, steps: list[dict[str, Any]], *, author: str | None) -> Opinion:
    lines = [f"{i + 1}. {s.get('description', '')} [{s.get('call', '')}] {json.dumps(s.get('args', {}))[:300]}"
             for i, s in enumerate(steps)]
    return _ask(models, PLAN_PROMPT, f"REQUEST:\n{request}\n\nSTEPS:\n" + "\n".join(lines), author=author,
                purpose="second opinion (plan)")


def note_for(op: Opinion, *, fixed: bool = False) -> str:
    if op.verdict == "unavailable":
        return "Second opinion: not reviewed (no other local model is available)."
    who = (op.model or "").split("/")[-1]
    if op.verdict == "agree":
        return f"Second opinion ({who}): agrees."
    if op.verdict == "unsure":
        return f"Second opinion ({who}): unsure."
    head = "pointed out a problem; the answer was revised once" if fixed else "disagrees"
    return f"Second opinion ({who}) {head}: " + "; ".join(op.problems[:3])
