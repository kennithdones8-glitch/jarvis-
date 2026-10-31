"""Planner: turns a request into a validated, fixed plan — or a clarifying question.

The model only proposes. Deterministic code validates every step (allowed actions, argument
shapes, references, dependencies) and the permission engine still checks each call at run time.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from ..core.tasks import StepSpec
from ..core.tools import ToolRegistry
from ..models import ChatRequest, Message, ModelService, Need, parse_json_output
from ..models.types import Category, InvalidModelOutput
from .refs import references

MAX_STEPS = 10

# Actions the planner may use, with the argument shapes it must follow. Deletion and anything
# external are deliberately absent from planning in this version.
ACTION_DOCS: dict[tuple[str, str], str] = {
    ("fs", "read"): 'fs.read {"path": "<file>"} -> {"content": "<text>"}',
    ("fs", "list"): 'fs.list {"path": "<folder>"} -> {"entries": [{"name", "dir"}]}',
    ("fs", "search"): 'fs.search {"path": "<folder>", "query": "<words>"} -> {"hits": [{"path", "snippet"}]}',
    ("fs", "mkdir"): 'fs.mkdir {"path": "<folder>"}',
    ("fs", "write"): 'fs.write {"path": "<file>", "content": "<text>"} -> saves a text file',
    ("web", "fetch"): 'web.fetch {"url": "https://..."} -> {"title", "text"}',
    ("search", "query"): 'search.query {"query": "<words>", "limit": 5} -> {"results": [{"title", "url", "snippet"}]}',
    ("research", "web"): 'research.web {"question": "<what to find out>"} -> {"answer", "sources": [{"url", "verified"}]} '
                         ' (searches the web and reads pages; use for anything current, factual or needing sources)',
    ("llm", "compose"): 'llm.compose {"instruction": "<what to write>", "inputs": ["{{steps.N.field}}", ...]} '
                        '-> {"text"}  (use for summarising, drafting, answering from gathered data)',
}
REQUIRED_ARGS: dict[tuple[str, str], dict[str, type]] = {
    ("fs", "read"): {"path": str}, ("fs", "list"): {"path": str}, ("fs", "mkdir"): {"path": str},
    ("fs", "search"): {"path": str, "query": str}, ("fs", "write"): {"path": str, "content": str},
    ("web", "fetch"): {"url": str}, ("search", "query"): {"query": str},
    ("llm", "compose"): {"instruction": str, "inputs": list},
    ("research", "web"): {"question": str},
}
RETRIES = {"web": 3, "search": 3, "llm": 2, "fs": 2, "research": 2}

PLANNER_PROMPT = """\
You are the planning component of JARVIS, a personal assistant on the owner's Mac. Turn the \
owner's request into a short plan of tool steps. Reply with JSON only.

Available actions (use nothing else):
{catalog}

Rules:
- Files may only be read or written inside: {roots}. Save new documents in {notes}.
- Steps are numbered from 0. To use an earlier step's output write "{{{{steps.N.field}}}}", e.g. \
"{{{{steps.0.content}}}}", and put N in that step's "depends_on".
- Keep plans short (at most {max_steps} steps). Do not add steps the owner did not ask for.
- When a document should cite research, pass the research step's answer AND sources to llm.compose and \
ask it to keep a "Sources" section with the URLs.
- If the request is ambiguous or missing something essential, do not guess: return a short "question".
- If it cannot be done with these actions, return "cannot" with the reason.

JSON format:
{{"goal": "<one sentence>", "question": null, "cannot": null, "steps": [{{"description": "<what and why>", \
"tool": "<tool>", "action": "<action>", "args": {{}}, "depends_on": []}}]}}

Example request: "Summarise {notes}/trip.txt in one paragraph and save it as trip-summary.md"
Example reply:
{{"goal": "Save a one-paragraph summary of trip.txt", "question": null, "cannot": null, "steps": [
 {{"description": "Read the trip notes", "tool": "fs", "action": "read", "args": {{"path": "{notes}/trip.txt"}}, "depends_on": []}},
 {{"description": "Write the summary", "tool": "llm", "action": "compose", "args": {{"instruction": "Summarise in one paragraph", "inputs": ["{{{{steps.0.content}}}}"]}}, "depends_on": [0]}},
 {{"description": "Save the summary", "tool": "fs", "action": "write", "args": {{"path": "{notes}/trip-summary.md", "content": "{{{{steps.1.text}}}}"}}, "depends_on": [1]}}]}}"""


class PlanError(ValueError):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass
class Plan:
    kind: Literal["plan", "clarify", "cannot", "failed"]
    goal: str = ""
    steps: list[StepSpec] = field(default_factory=list)
    message: str = ""          # the question, the reason it cannot be done, or the validation problems
    model: str = ""
    attempts: int = 1


def available_actions(registry: ToolRegistry) -> list[tuple[str, str]]:
    return [key for key in ACTION_DOCS if registry.action(*key) is not None]


def validate(data: Any, registry: ToolRegistry) -> Plan:
    if not isinstance(data, dict):
        raise PlanError(["reply must be a JSON object"])
    if isinstance(data.get("question"), str) and data["question"].strip():
        return Plan("clarify", message=data["question"].strip())
    if isinstance(data.get("cannot"), str) and data["cannot"].strip():
        return Plan("cannot", message=data["cannot"].strip())

    allowed = set(available_actions(registry))
    problems: list[str] = []
    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise PlanError(["'steps' must be a non-empty list (or ask a question)"])
    if len(raw_steps) > MAX_STEPS:
        problems.append(f"too many steps ({len(raw_steps)} > {MAX_STEPS})")

    steps: list[StepSpec] = []
    for i, raw in enumerate(raw_steps[:MAX_STEPS]):
        where = f"step {i}"
        if not isinstance(raw, dict):
            problems.append(f"{where}: must be an object")
            continue
        key = (raw.get("tool"), raw.get("action"))
        args = raw.get("args")
        deps = raw.get("depends_on", [])
        if key not in allowed:
            problems.append(f"{where}: {key[0]}.{key[1]} is not an available action")
            continue
        if not isinstance(args, dict):
            problems.append(f"{where}: args must be an object")
            continue
        for name, typ in REQUIRED_ARGS[key].items():
            if not isinstance(args.get(name), typ):
                problems.append(f"{where}: {key[0]}.{key[1]} needs '{name}' ({typ.__name__})")
        if not isinstance(deps, list) or any(not isinstance(d, int) or not 0 <= d < i for d in deps):
            problems.append(f"{where}: depends_on must list earlier step numbers")
            continue
        refs = references(args)
        if any(r >= i for r in refs):
            problems.append(f"{where}: refers to a later step")
        missing = sorted(refs - set(deps))
        if missing:
            problems.append(f"{where}: uses steps {missing} but does not list them in depends_on")
        description = raw.get("description")
        steps.append(StepSpec(
            description=description.strip()[:200] if isinstance(description, str) and description.strip()
            else f"{key[0]}.{key[1]}",
            tool=key[0], action=key[1], args=args, depends_on=deps, max_attempts=RETRIES.get(key[0], 2),
        ))
    if problems:
        raise PlanError(problems)
    goal = data.get("goal")
    return Plan("plan", goal=goal.strip()[:300] if isinstance(goal, str) and goal.strip() else "", steps=steps)


class Planner:
    def __init__(self, models: ModelService, registry: ToolRegistry, *, roots: list[str], notes_dir: str):
        self.models = models
        self.registry = registry
        self.roots = roots
        self.notes_dir = notes_dir

    def system_prompt(self) -> str:
        catalog = "\n".join(f"- {ACTION_DOCS[k]}" for k in available_actions(self.registry))
        return PLANNER_PROMPT.format(catalog=catalog, roots=", ".join(self.roots) or "(none)",
                                     notes=self.notes_dir, max_steps=MAX_STEPS)

    def plan(self, request: str, *, task_id: str | None = None, local_only: bool = False) -> Plan:
        messages = [Message("system", self.system_prompt(), Category.SYSTEM_PROMPT),
                    Message("user", request, Category.CONVERSATION)]
        problems: list[str] = []
        for attempt in (1, 2):
            r = self.models.complete(Need("plan", min_quality=3, local_only=local_only), ChatRequest(tuple(messages), max_tokens=900,
                                     temperature=0.0, json_mode=True), purpose="plan a task", task_id=task_id)
            try:
                plan = validate(parse_json_output(r.text), self.registry)
                plan.model, plan.attempts = f"{r.provider}/{r.model}", attempt
                return plan
            except (InvalidModelOutput, PlanError) as exc:
                problems = exc.problems if isinstance(exc, PlanError) else [str(exc)]
            messages += [Message("assistant", r.text[:4000], Category.CONVERSATION),
                         Message("user", "That plan is invalid: " + "; ".join(problems)
                                 + ". Reply with corrected JSON only.", Category.CONVERSATION)]
        return Plan("failed", message="; ".join(problems), model=f"{r.provider}/{r.model}", attempts=2)


def describe_args(args: dict[str, Any], limit: int = 140) -> str:
    text = json.dumps(args, ensure_ascii=False).replace(str(Path.home()), "~")
    return text if len(text) <= limit else text[: limit - 1] + "…"
