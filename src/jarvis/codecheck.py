"""Coding self-test: before a chat answer with Python code is shown, run it on test cases in a sandbox.

Off unless the owner turns it on (`[coding] self_test = true` in jarvis.toml). Flow, for a local answer only:
1. The local model writes 3–6 test cases from the owner's request alone (it never sees the answer's code, so the
   tests can't simply copy its mistakes).
2. The answer's code runs on them in a child process: macOS sandbox with no network, no writing outside a temp
   folder, no reading files in the owner's home folder (only the Python installation), no starting other programs (only Python's own launcher), 10 s,
   empty environment, isolated Python.
3. If any case fails, the model gets the failures once and may fix the code (or say a case contradicts the request).
   The new answer is kept only if its code passes at least as many cases as before.

Without a sandbox (not macOS) nothing is run. Tests are written by the same small model, so a pass is evidence,
not proof; the reply says how many cases were run and passed.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MAX_CASES = 6
TIMEOUT_S = 10
CODE = re.compile(r"```(?:python|py)?[ \t]*\n(.*?)```", re.S)
DEF = re.compile(r"^def\s+([A-Za-z_]\w*)\s*\(", re.M)
WANTS_CODE = re.compile(r"\b(write|fix|implement|correct|debug|make|create)\b.{0,80}\b(function|code|python|def|script|"
                        r"method)\b|\bdef\s+\w+\(|```", re.I | re.S)
ALLOW_UNSANDBOXED = False  # tests on Linux only; never set in normal use

TEST_PROMPT = """\
You write test cases for a Python function, from the owner's request alone (you have not seen any solution). \
Reply with JSON only.

The function is named `{name}`. Write 3 to {max} cases covering the normal behaviour and every edge case the \
request mentions (e.g. empty input). Use only behaviour the request states; don't guess anything else.
Each case is a Python expression calling the function, and the expected result as a Python literal.

JSON format: {{"cases": [{{"call": "{name}(...)", "expected": "..."}}]}}"""

PROFILE = """(version 1)(allow default)(deny network*)
(deny file-write*)(allow file-write* (subpath "{tmp}") (literal "/dev/null"))
(deny file-read-data (subpath "{home}"))(allow file-read-data (subpath "{tmp}"){python_reads})
(deny process-exec*)(allow process-exec*{python_execs})"""

HARNESS = r'''
import json, sys
_out = []
try:
    exec(compile(_CODE, "<answer>", "exec"), globals())
except BaseException as _e:
    print(json.dumps({"load_error": f"{type(_e).__name__}: {_e}"[:300]}))
    sys.exit(0)
for _c in _CASES:
    try:
        _want = eval(_c["expected"], {})
    except BaseException as _e:
        _out.append({"call": _c["call"], "bad_case": f"{type(_e).__name__}: {_e}"[:120]})
        continue
    try:
        _got = eval(_c["call"], globals())
        _ok = _got == _want
        _out.append({"call": _c["call"], "ok": bool(_ok), "want": repr(_want)[:120], "got": repr(_got)[:120]})
    except BaseException as _e:
        _out.append({"call": _c["call"], "ok": False, "want": repr(_want)[:120], "got": f"{type(_e).__name__}: {_e}"[:160]})
print(json.dumps({"results": _out}))
'''


class SandboxUnavailable(RuntimeError):
    pass


@dataclass
class TestRun:
    cases: int = 0
    passed: int = 0
    failures: list[str] = field(default_factory=list)
    error: str | None = None  # the code didn't load, timed out, or the sandbox stopped it

    @property
    def all_passed(self) -> bool:
        return self.error is None and self.cases > 0 and self.passed == self.cases

    def describe(self) -> str:
        if self.error:
            return f"the code failed to run: {self.error}"
        return "\n".join(self.failures)


def wants_code(question: str) -> bool:
    return bool(WANTS_CODE.search(question or ""))


def code_of(answer: str, question: str = "") -> tuple[str, str] | None:
    """(code, function name) from the answer's last Python block that defines a function. The function tested is
    the one the question names (`seconds(text)`), so a helper defined first isn't mistaken for it."""
    for block in reversed(CODE.findall(answer or "")):
        names = DEF.findall(block)
        if names:
            asked = [n for n in names if re.search(rf"\b{re.escape(n)}\s*\(", question or "")]
            return block, (asked or names)[0]
    return None


def parse_cases(data: Any, name: str) -> list[dict[str, str]]:
    raw = data.get("cases") if isinstance(data, dict) else data
    out = []
    for c in raw if isinstance(raw, list) else []:
        if (isinstance(c, dict) and isinstance(c.get("call"), str) and isinstance(c.get("expected"), str | int | float
                                                                                 | bool | list | type(None))
                and c["call"].strip().startswith(f"{name}(") and len(c["call"]) <= 400):
            out.append({"call": c["call"].strip(), "expected": c["expected"] if isinstance(c["expected"], str)
                        else repr(c["expected"])})
    return out[:MAX_CASES]


def _argv(tmp: str) -> list[str]:
    python = os.path.realpath(sys.executable)
    if sys.platform == "darwin" and Path("/usr/bin/sandbox-exec").exists():
        reads = {os.path.realpath(p) for p in (sys.base_prefix, sys.prefix, os.path.dirname(python))}
        # Framework builds (Homebrew, python.org) start a second binary inside the installation (Python.app), so
        # programs may be started from the Python installation only; shells and everything else stay blocked.
        install = {os.path.realpath(sys.base_prefix), os.path.dirname(python)}
        profile = PROFILE.format(tmp=os.path.realpath(tmp), home=os.path.realpath(Path.home()),
                                 python_reads="".join(f' (subpath "{r}")' for r in sorted(reads)),
                                 python_execs="".join(f' (subpath "{r}")' for r in sorted(install)))
        return ["/usr/bin/sandbox-exec", "-p", profile, python, "-I", "-S", "-B"]
    if ALLOW_UNSANDBOXED:
        return [python, "-I", "-S", "-B"]
    raise SandboxUnavailable("code is only run inside the macOS sandbox")


def run_cases(code: str, cases: list[dict[str, str]]) -> TestRun:
    script = f"_CODE = {code!r}\n_CASES = {json.dumps(cases)}\n{HARNESS}"
    with tempfile.TemporaryDirectory() as tmp:
        argv = _argv(tmp) + ["-c", script]
        try:
            r = subprocess.run(argv, cwd=tmp, env={"PATH": "/usr/bin:/bin", "HOME": tmp}, capture_output=True,
                               text=True, timeout=TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return TestRun(cases=len(cases), error=f"timed out after {TIMEOUT_S} s (an endless loop?)")
    last = (r.stdout.strip().splitlines() or [""])[-1]
    try:
        data = json.loads(last)
    except json.JSONDecodeError:
        return TestRun(cases=len(cases), error=(r.stderr.strip() or "no output")[-300:])
    if "load_error" in data:
        return TestRun(cases=len(cases), error=data["load_error"])
    results = [x for x in data["results"] if "bad_case" not in x]  # a test with a broken expectation doesn't count
    run = TestRun(cases=len(results), passed=sum(1 for x in results if x["ok"]))
    run.failures = [f"{x['call']} should be {x['want']}, got {x['got']}" for x in results if not x["ok"]]
    return run
