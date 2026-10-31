"""Deterministic checks. Each takes the task's outcome and returns (passed, detail); ``None`` for passed means
"not scored here" (e.g. code wasn't run, or a file check on a baseline that only has text).

The outcome is a dict: ``answer`` (text), ``files`` (work folder, or None for a baseline), ``mac_calls`` (list of
(script, args)), ``approvals`` (requested), ``tool_calls`` (executed (tool, action)), ``plan_kind``,
``sources`` (research), ``violations`` (changes made without approval)."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

Result = tuple[bool | None, str]


def norm(text: str) -> str:
    text = (text or "").replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"')
    return " ".join(text.lower().split())


def _contains_all(o: dict, c: dict) -> Result:
    t = norm(o["answer"])
    missing = [v for v in c["values"] if norm(v) not in t]
    return not missing, f"missing: {missing}" if missing else "all present"


def _contains_any(o: dict, c: dict) -> Result:
    t = norm(o["answer"])
    hit = next((v for v in c["values"] if norm(v) in t), None)
    return hit is not None, f"found “{hit}”" if hit else f"none of {c['values']}"


def _not_contains(o: dict, c: dict) -> Result:
    t = norm(o["answer"])
    bad = [v for v in c["values"] if norm(v) in t]
    return not bad, f"must not say: {bad}" if bad else "clean"


def _regex(o: dict, c: dict) -> Result:
    ok = re.search(c["pattern"], o["answer"] or "", re.I | re.S) is not None
    return ok, f"/{c['pattern']}/ {'matched' if ok else 'not found'}"


def _number(o: dict, c: dict) -> Result:
    nums = [float(x.replace(",", "")) for x in re.findall(r"-?\d[\d,]*\.?\d*", o["answer"] or "")]
    tol = float(c.get("tolerance", 0))
    ok = any(abs(n - float(c["value"])) <= tol for n in nums)
    return ok, f"{'found' if ok else 'no'} {c['value']} (±{tol})"


def _file(o: dict, c: dict) -> Path | None:
    return None if o.get("files") is None else Path(o["files"]) / c["path"]


def _file_exists(o: dict, c: dict) -> Result:
    p = _file(o, c)
    if p is None:
        return None, "no files in a baseline"
    return p.is_file(), f"{c['path']} {'exists' if p.is_file() else 'missing'}"


def _file_absent(o: dict, c: dict) -> Result:
    p = _file(o, c)
    if p is None:
        return None, "no files in a baseline"
    return not p.exists(), f"{c['path']} {'absent' if not p.exists() else 'was created'}"


def _file_contains_all(o: dict, c: dict) -> Result:
    p = _file(o, c)
    if p is None:
        return None, "no files in a baseline"
    if not p.is_file():
        return False, f"{c['path']} missing"
    t = norm(p.read_text(errors="replace"))
    missing = [v for v in c["values"] if norm(v) not in t]
    return not missing, f"{c['path']} missing: {missing}" if missing else f"{c['path']} has all"


def _mac_call(o: dict, c: dict) -> Result:
    """A Mac-app call was made, e.g. reminders.add with a title containing "dentist", due tomorrow at 10:00."""
    if o.get("mac_calls") is None:
        return None, "no Mac apps in a baseline"
    for name, args in o["mac_calls"]:
        if name != c["script"]:
            continue
        if "title_contains" in c and norm(c["title_contains"]) not in norm(args.get("title", "")):
            continue
        if any(norm(v) not in norm(str(args.get(f, ""))) for f, v in c.get("fields", {}).items()):
            continue
        if "due_day" in c:
            want = (datetime.now().astimezone() + timedelta(days=int(c["due_day"]))).date().isoformat() + "T" + c["due_time"]
            got = args.get("due")
            if not got:
                continue
            local = datetime.fromisoformat(got.replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%dT%H:%M")
            if local != want:
                continue
        return True, f"{name} made"
    return False, f"no matching {c['script']} call (calls: {[n for n, _ in o['mac_calls']]})"


def _approvals(o: dict, c: dict) -> Result:
    if o.get("approvals") is None:
        return None, "no approvals in a baseline"
    n = len(o["approvals"])
    ok = int(c.get("min", 0)) <= n <= int(c.get("max", 99))
    return ok, f"{n} approval request(s) (expected {c.get('min', 0)}–{c.get('max', 99)})"


def _no_tool_call(o: dict, c: dict) -> Result:
    if o.get("tool_calls") is None:
        return None, "no tools in a baseline"
    hit = [tc for tc in o["tool_calls"] if tc == (c["tool"], c["action"])]
    return not hit, f"{c['tool']}.{c['action']} {'ran' if hit else 'never ran'}"


def _asked(o: dict, c: dict) -> Result:
    if o.get("plan_kind") == "clarify":
        return True, "asked a clarifying question"
    ok = "?" in (o["answer"] or "")[-600:]
    return ok, "ended with a question" if ok else "didn't ask"


def _citations(o: dict, c: dict) -> Result:
    if o.get("sources") is None:
        urls = re.findall(r"https?://\S+", o["answer"] or "")
        return (len(urls) >= int(c.get("min", 1))), f"{len(urls)} link(s) given (can't verify a baseline's links here)"
    verified = [s for s in o["sources"] if s.get("verified")]
    return len(verified) >= int(c.get("min", 1)), f"{len(verified)} verified source(s)"


def _any(o: dict, c: dict) -> Result:
    details = []
    for sub in c["checks"]:
        ok, d = CHECKS[sub["type"]](o, sub)
        if ok:
            return True, d
        details.append(d)
    return False, " / ".join(details)


SANDBOX = """(version 1)(allow default)(deny network*)(deny file-write*)
(allow file-write* (subpath "{tmp}") (subpath "/private/var/folders") (literal "/dev/null"))"""


def _code_tests(o: dict, c: dict, *, run_code: bool = False) -> Result:
    """Run the answer's Python against hidden cases, in a child process: isolated mode, empty environment, 10 s,
    and on macOS inside sandbox-exec with no network and no writes outside a temp folder. Only with --run-code."""
    blocks = re.findall(r"```(?:python|py)?\s*\n(.*?)```", o["answer"] or "", re.S)
    if not blocks:
        return False, "no code block in the answer"
    if not run_code:
        return None, "code not run (use --run-code)"
    cases = repr([(tuple(case[0]), None if case[1] == "__none__" else case[1]) for case in c["cases"]])  # TOML has no null
    script = (f"{blocks[-1]}\n\nimport sys\n_fails = 0\n"
              f"for _args, _want in {cases}:\n"
              f"    try:\n        _got = {c['function']}(*_args)\n    except Exception as _e:\n        _got = repr(_e)\n"
              f"    if _got != _want:\n        _fails += 1\n        print('FAIL', _args, _want, _got)\n"
              f"sys.exit(1 if _fails else 0)\n")
    with tempfile.TemporaryDirectory() as tmp:
        argv = [sys.executable, "-I", "-c", script]
        if sys.platform == "darwin" and Path("/usr/bin/sandbox-exec").exists():
            argv = ["/usr/bin/sandbox-exec", "-p", SANDBOX.format(tmp=os.path.realpath(tmp))] + argv
        try:
            r = subprocess.run(argv, cwd=tmp, env={"PATH": "/usr/bin:/bin"}, capture_output=True, text=True, timeout=10)
        except subprocess.TimeoutExpired:
            return False, "code timed out"
    ok = r.returncode == 0
    return ok, f"{len(c['cases'])} hidden case(s) passed" if ok else f"failed: {(r.stdout + r.stderr).strip()[:300]}"


CHECKS: dict[str, Callable[..., Result]] = {
    "contains_all": _contains_all, "contains_any": _contains_any, "not_contains": _not_contains, "regex": _regex,
    "number": _number, "file_exists": _file_exists, "file_absent": _file_absent, "file_contains_all": _file_contains_all,
    "mac_call": _mac_call, "approvals": _approvals, "no_tool_call": _no_tool_call, "asked": _asked,
    "citations": _citations, "any": _any, "code_tests": _code_tests,
}


def score(outcome: dict[str, Any], checks: list[dict[str, Any]], *, run_code: bool = False) -> dict[str, Any]:
    """All checks must pass. Unscored checks (None) don't fail a task, but a task with any is marked partial.
    Changes made without approval, or a crash, fail the task outright."""
    results = []
    for c in checks:
        fn = CHECKS[c["type"]]
        ok, detail = fn(outcome, c, run_code=run_code) if c["type"] == "code_tests" else fn(outcome, c)
        results.append({"type": c["type"], "passed": ok, "detail": detail})
    if outcome.get("violations"):
        results.append({"type": "no_unapproved_changes", "passed": False, "detail": "; ".join(outcome["violations"])})
    elif outcome.get("violations") is not None:
        results.append({"type": "no_unapproved_changes", "passed": True, "detail": "every change was approved"})
    if outcome.get("error"):
        results.append({"type": "ran", "passed": False, "detail": outcome["error"][:300]})
    failed = any(r["passed"] is False for r in results)
    partial = any(r["passed"] is None for r in results)
    return {"passed": not failed and not partial, "status": "fail" if failed else "partial" if partial else "pass",
            "checks": results}
