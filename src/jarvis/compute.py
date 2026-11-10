"""Work it out with code: for maths, dates and logic puzzles answered on this Mac, the local model writes a short
program, JARVIS runs it in the sandbox, and the answer is written from what the program printed.

Why (hard set, smarter-v2): the 14B reasons in words and slips on the arithmetic and bookkeeping a program gets
right every time: "168 km at 72 km/h = 2.33 h" (it is 2 h 20 min), the 10th meeting every 3rd day, a five-person
seating puzzle where it broke a rule it had just stated.

Off unless the owner turns it on (`[coding] compute = true` in jarvis.toml). Every run, in order:
1. Only for a question that needs working out (``needs_reasoning``) and isn't a request for code, in Balanced or
   Deep mode, when the answer stays on this Mac. Quick never; an answer going to Claude never.
2. The program is checked before it runs: standard maths/date/logic modules only (no os, sys, subprocess, socket,
   files...), no open/exec/eval/compile/__import__/input/getattr, no double-underscore names. Anything else and
   nothing runs.
3. It runs in the same sandbox as the coding self-test: macOS sandbox-exec, no network, no writes outside a temp
   folder, no reading the owner's home folder, no starting other programs, empty environment, isolated Python,
   10 s. Without that sandbox (not macOS) nothing is run.
4. Its output (at most 2,000 characters) goes to the answering model, marked local-only, as something to check,
   not something to trust: the program was written by a model too. The reply says it was worked out this way.
"""

from __future__ import annotations

import ast
import subprocess
import tempfile
from dataclasses import dataclass

from .codecheck import CODE, TIMEOUT_S, SandboxUnavailable, _argv, wants_code

MAX_OUTPUT = 2000
ALLOWED_MODULES = frozenset({"math", "fractions", "decimal", "datetime", "calendar", "itertools", "functools",
                             "statistics", "collections", "re", "string", "operator", "cmath", "numbers"})
FORBIDDEN_CALLS = frozenset({"open", "exec", "eval", "compile", "__import__", "input", "getattr", "setattr",
                             "delattr", "globals", "locals", "vars", "breakpoint", "help", "memoryview"})

PROGRAM_PROMPT = """\
You help JARVIS work out an exact answer. Write a short Python 3 program that computes the answer to the owner's \
question and prints it with print(). Reply with one ```python code block only.

Rules: standard library only, and only these modules: math, fractions, decimal, datetime, calendar, itertools, \
functools, statistics, collections, re. No input(), no files, no network. For a puzzle, try every possibility and \
print the one(s) that meet every condition. For times and dates, use datetime. Print a short, clear result."""

NOTE = "🧮 Worked out by running a short program on this Mac (sandboxed); the answer was checked against its output."


@dataclass
class Computed:
    output: str | None = None
    error: str | None = None
    code: str = ""

    @property
    def ok(self) -> bool:
        return self.output is not None and self.error is None


def wants_compute(question: str) -> bool:
    """A question to work out (numbers, dates, a puzzle), not a request to write code."""
    from .models.router import needs_reasoning

    return bool(question) and needs_reasoning(question) and not wants_code(question)


def program_of(text: str) -> str | None:
    blocks = CODE.findall(text or "")
    return blocks[-1].strip() if blocks else None


def vet(code: str) -> str | None:
    """Why this program must not run, or None. Checked on the syntax tree, before anything runs."""
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return f"it isn't valid Python ({exc.msg})"
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            bad = [a.name for a in node.names if a.name.split(".")[0] not in ALLOWED_MODULES]
            if bad:
                return f"it imports {', '.join(bad)}"
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] not in ALLOWED_MODULES or node.level:
                return f"it imports from {node.module or '.'}"
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_CALLS:
            return f"it calls {node.func.id}()"
        elif isinstance(node, ast.Name) and node.id.startswith("__"):
            return f"it uses {node.id}"
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            return f"it uses .{node.attr}"
    return None


def run_program(code: str) -> Computed:
    """Vet, then run in the sandbox. Never raises; an error just means the answer is written the usual way."""
    if problem := vet(code):
        return Computed(error=f"not run: {problem}", code=code)
    with tempfile.TemporaryDirectory() as tmp:
        try:
            argv = _argv(tmp) + ["-c", code]
        except SandboxUnavailable as exc:
            return Computed(error=str(exc), code=code)
        try:
            r = subprocess.run(argv, cwd=tmp, env={"PATH": "/usr/bin:/bin", "HOME": tmp}, capture_output=True,
                               text=True, timeout=TIMEOUT_S, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return Computed(error=f"timed out after {TIMEOUT_S} s", code=code)
    out = (r.stdout or "").strip()
    if r.returncode != 0:
        return Computed(error=((r.stderr or "").strip().splitlines() or ["failed"])[-1][:200], code=code)
    if not out:
        return Computed(error="it printed nothing", code=code)
    return Computed(output=out[:MAX_OUTPUT], code=code)


def result_message_text(c: Computed) -> str:
    return ("JARVIS ran a short program (written by a model, run sandboxed on this Mac) to work this out. It printed:\n"
            f"<program_output>\n{c.output}\n</program_output>\n"
            "Check it makes sense against the question. If it does, base your answer on it and give the final "
            "answer in exactly the form the question asks for. If it doesn't, work it out yourself and say so.")

