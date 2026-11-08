"""Coding self-test: tests from the request, run in the sandbox, one fix, keep the better answer."""

import json
import sys

import pytest
from model_servers import start_ollama
from test_dashboard import CFG, call

from jarvis import codecheck
from jarvis.codecheck import SandboxUnavailable, code_of, parse_cases, run_cases, wants_code
from jarvis.server import Dashboard

DURATION = ('Write a Python function `seconds(text)` that turns durations like "1h 30m", "45s", "2h5m10s" or "90m" '
            "into a number of seconds (an int). Units are h, m and s; spaces between parts are optional. Reply with the "
            "function in one Python code block.")
BUGGY = "```python\ndef seconds(text):\n    return int(text[:-1]) * {'h': 3600, 'm': 60, 's': 1}[text[-1]]\n```"
FIXED = ("```python\nimport re\ndef seconds(text):\n    u = {'h': 3600, 'm': 60, 's': 1}\n"
         "    return sum(int(n) * u[k] for n, k in re.findall(r'(\\d+)\\s*([hms])', text))\n```")
CASES = {"cases": [{"call": "seconds('1h 30m')", "expected": "5400"}, {"call": "seconds('45s')", "expected": "45"},
                   {"call": "seconds('2h5m10s')", "expected": "7510"}]}


@pytest.fixture
def unsandboxed(monkeypatch):
    """Linux has no sandbox-exec; these tests run the harness directly (never allowed in normal use)."""
    if sys.platform != "darwin":
        monkeypatch.setattr(codecheck, "ALLOW_UNSANDBOXED", True)


def test_spotting_code_requests_and_code():
    assert wants_code(DURATION) and wants_code("Fix this function:\n```python\ndef f(): pass\n```")
    assert not wants_code("What's on my calendar tomorrow?")
    assert code_of(BUGGY) == (BUGGY.split("\n", 1)[1].rsplit("```", 1)[0], "seconds")
    assert code_of("No code here") is None and code_of("```\nprint(1)\n```") is None


def test_cases_must_call_the_function():
    raw = {"cases": [{"call": "seconds('1h')", "expected": "3600"}, {"call": "__import__('os').system('x')",
                                                                    "expected": "0"},
                     {"call": "seconds('2m')", "expected": 120}, "junk"]}
    assert parse_cases(raw, "seconds") == [{"call": "seconds('1h')", "expected": "3600"},
                                           {"call": "seconds('2m')", "expected": "120"}]


def test_running_cases(unsandboxed):
    code = code_of(BUGGY)[0]
    run = run_cases(code, CASES["cases"])
    assert run.cases == 3 and run.passed == 1 and not run.all_passed
    assert any("seconds('1h 30m') should be 5400" in f for f in run.failures)
    good = run_cases(code_of(FIXED)[0], CASES["cases"])
    assert good.all_passed
    assert run_cases("def seconds(:\n", CASES["cases"]).error.startswith("SyntaxError")
    assert "timed out" in run_cases("def seconds(t):\n    while True: pass", CASES["cases"][:1]).error
    broken = run_cases(code_of(FIXED)[0], [{"call": "seconds('1h')", "expected": "nonsense("}])
    assert broken.cases == 0  # a test with a broken expectation doesn't count against the code


def test_nothing_runs_without_a_sandbox(monkeypatch):
    monkeypatch.setattr(codecheck.sys, "platform", "linux")  # as on any system without sandbox-exec
    monkeypatch.setattr(codecheck, "ALLOW_UNSANDBOXED", False)
    with pytest.raises(SandboxUnavailable):
        run_cases("def f(): return 1", [{"call": "f()", "expected": "1"}])


# ---- in the chat ------------------------------------------------------------------------------------------------
@pytest.fixture
def coding_env(make_kernel, tmp_path, unsandboxed):
    server = start_ollama(installed=["planner:7b"])
    state = {"answers": [], "cases": CASES, "prompts": []}

    def reply(body):
        system = body["messages"][0]["content"]
        if "lookup step of JARVIS" in system:
            return json.dumps({"lookups": [], "change": False})
        if "You write test cases" in system or "Copy the concrete examples" in system:
            state["prompts"].append(json.dumps(body["messages"]))
            return json.dumps(state["cases"])
        return state["answers"].pop(0) if state["answers"] else "OK"
    server.reply = reply

    def make(self_test=True, examples=False):
        extra = ("self_test = true\n" if self_test else "") + ("examples = true\n" if examples else "")
        (tmp_path / "jarvis.toml").write_text(CFG.format(url=server.url) + (f"\n[coding]\n{extra}" if extra else ""))
        k = make_kernel(config_path=tmp_path / "jarvis.toml")
        d = Dashboard(k, port=0, token="test-token", poll_s=0.05)
        d.start()
        made.append(d)
        return d
    made = []
    yield make, state, server
    for d in made:
        d.shutdown()
    server.stop()


def chat(d, message):
    return json.loads(call(d, "/api/chat", {"message": message, "history": []})[2])


def test_a_failing_answer_is_fixed_once_and_the_fix_is_kept(coding_env):
    make, state, _ = coding_env
    d = make()
    state["answers"] = [BUGGY, FIXED]
    r = chat(d, DURATION)
    assert r["text"] == FIXED and r["code_test"] == {"ran": True, "source": "model", "cases": 3, "passed": 3, "fixed": True, "error": None}
    assert "Tested on 3 case(s)" in r["note"] and "after one fix" in r["note"]
    assert "def seconds" not in state["prompts"][0]  # the test writer never sees the answer's code
    ev = [e["payload"] for e in d.kernel.audit.entries() if e["event"] == "chat.code_test"][-1]
    assert ev["first_passed"] == 1 and ev["passed"] == 3 and "seconds(" not in json.dumps(ev)


def test_a_worse_fix_is_thrown_away(coding_env):
    make, state, _ = coding_env
    d = make()
    worse = "```python\ndef seconds(text):\n    return 0\n```"
    state["answers"] = [BUGGY, worse]
    r = chat(d, DURATION)
    assert r["text"] == BUGGY and r["code_test"]["passed"] == 1 and r["code_test"]["fixed"] is False


def test_a_passing_answer_costs_only_the_test_call(coding_env):
    make, state, server = coding_env
    d = make()
    state["answers"] = [FIXED]
    before = len(server.received)
    r = chat(d, DURATION)
    assert r["text"] == FIXED and r["code_test"]["passed"] == 3 and r["code_test"]["fixed"] is False
    assert len(server.received) - before == 2  # the answer and the test cases; no fix call


def test_off_by_default(coding_env):
    make, state, server = coding_env
    d = make(self_test=False)
    state["answers"] = [BUGGY]
    r = chat(d, DURATION)
    assert r["text"] == BUGGY and r["code_test"] is None and state["prompts"] == []


def test_ordinary_chat_is_never_tested(coding_env):
    make, state, _ = coding_env
    d = make()
    state["answers"] = ["Rainbows come from light bending in raindrops."]
    r = chat(d, "Explain how rainbows form")
    assert r["code_test"] is None and state["prompts"] == []


def test_bench_can_switch_it_on(tmp_path):
    from jarvis.bench.runner import bench_config
    real = tmp_path / "jarvis.toml"
    real.write_text("[coding]\nself_test = false\n")
    assert "self_test = true" in bench_config(real, "local", coding_self_test=True)
    assert "self_test = true" not in bench_config(real, "local")


def test_config_is_checked(tmp_path):
    from jarvis.models.config import ConfigError, parse_model_config
    assert parse_model_config({"coding": {"self_test": True}}).coding == {"self_test": True}
    with pytest.raises(ConfigError):
        parse_model_config({"coding": {"self_test": "yes"}})
    with pytest.raises(ConfigError):
        parse_model_config({"coding": {"run_anything": True}})


def test_the_function_the_question_names_is_the_one_tested():
    answer = "```python\ndef _unit(u):\n    return {'h': 3600}[u]\n\ndef seconds(text):\n    return 0\n```"
    assert code_of(answer, DURATION)[1] == "seconds"
    assert code_of(answer)[1] == "_unit"  # no question: the first definition


def test_the_fix_is_always_local(coding_env, monkeypatch):
    make, state, _ = coding_env
    d = make()
    state["answers"] = [BUGGY, FIXED]
    real, seen = d.kernel.models.complete, []

    def spy(need, *a, **kw):
        seen.append((kw.get("purpose"), need.local_only))
        return real(need, *a, **kw)
    monkeypatch.setattr(d.kernel.models, "complete", spy)
    chat(d, DURATION)
    assert ("dashboard chat (coding self-test fix)", True) in seen


# ---- K: the examples written in the request ---------------------------------------------------------------------
VERSIONS = ('Write a Python function `compare_versions(a, b)` that compares version strings and returns 1, -1 or 0. '
            'Treat missing parts as 0, so compare_versions("1.0", "1") returns 0, and compare_versions("1.10", "1.9") '
            "returns 1. Reply with the function in one Python code block.")
V_BUGGY = "```python\ndef compare_versions(a, b):\n    return (a > b) - (a < b)\n```"
V_FIXED = ("```python\ndef compare_versions(a, b):\n    x = [int(p) for p in a.split('.')]\n"
           "    y = [int(p) for p in b.split('.')]\n    n = max(len(x), len(y))\n"
           "    x += [0] * (n - len(x))\n    y += [0] * (n - len(y))\n    return (x > y) - (x < y)\n```")
V_CASES = {"cases": [{"call": 'compare_versions("1.0", "1")', "expected": "0"},
                     {"call": 'compare_versions("1.10", "1.9")', "expected": "1"},
                     {"call": 'compare_versions("2.0", "3.0")', "expected": "-1"}]}  # made up: not in the request


def test_only_cases_written_in_the_request_are_kept():
    from jarvis.codecheck import from_request
    raw = V_CASES["cases"] + [
        {"call": "compare_versions(a, b)", "expected": "0"},                 # not literal
        {"call": 'other("1.0", "1")', "expected": "0"},                      # wrong function
        {"call": 'compare_versions("1.0", "1")', "expected": "1 - 1"},       # worked out, not copied
        {"call": 'compare_versions("1.10", "1.9")', "expected": "7"},        # value not in the request
        {"call": "compare_versions(", "expected": "0"}]                      # broken
    assert from_request(raw, "compare_versions", VERSIONS) == V_CASES["cases"][:2]
    rle = 'Write `compress(s)` so "aaabcc" becomes "a3bc2"; an empty string "" stays empty.'
    assert from_request([{"call": "compress('aaabcc')", "expected": "'a3bc2'"},
                         {"call": "compress('')", "expected": "''"},
                         {"call": "compress('zz')", "expected": "'z2'"}], "compress", rle) == [
        {"call": "compress('aaabcc')", "expected": "'a3bc2'"}, {"call": "compress('')", "expected": "''"}]
    assert from_request([{"call": "f(10)", "expected": "1"}], "f", "f(110) is 1") == []  # 10 is only part of 110


def test_examples_from_the_request_drive_one_fix(coding_env):
    make, state, _ = coding_env
    d = make(self_test=False, examples=True)
    state["cases"], state["answers"] = V_CASES, [V_BUGGY, V_FIXED]
    r = chat(d, VERSIONS)
    assert r["text"] == V_FIXED
    assert r["code_test"] == {"ran": True, "source": "request", "cases": 2, "passed": 2, "fixed": True, "error": None}
    assert "Tested on 2 example(s) from your request" in r["note"] and "after one fix" in r["note"]
    assert "def compare_versions" not in state["prompts"][0]  # the copier never sees the answer's code


def test_examples_win_over_the_self_test_when_both_are_on(coding_env):
    make, state, _ = coding_env
    d = make(self_test=True, examples=True)
    state["cases"], state["answers"] = V_CASES, [V_FIXED]
    r = chat(d, VERSIONS)
    assert r["code_test"]["source"] == "request" and r["code_test"]["cases"] == 2


def test_no_examples_in_the_request_means_no_test(coding_env):
    make, state, server = coding_env
    d = make(self_test=False, examples=True)
    state["cases"], state["answers"] = CASES, [BUGGY]  # the copier "invents" cases; none are written in DURATION
    before = len(server.received)
    r = chat(d, DURATION.replace('"1h 30m", "45s", "2h5m10s" or "90m"', "hours, minutes and seconds"))
    assert r["text"] == BUGGY and r["code_test"] == {"ran": False, "reason": "no examples in the request"}
    assert len(server.received) - before == 2  # the answer and the copy call; no fix


def test_examples_are_off_by_default(coding_env):
    make, state, _ = coding_env
    d = make(self_test=False)
    state["cases"], state["answers"] = V_CASES, [V_BUGGY]
    r = chat(d, VERSIONS)
    assert r["text"] == V_BUGGY and r["code_test"] is None and state["prompts"] == []


def test_examples_never_run_without_a_sandbox(coding_env, monkeypatch):
    make, state, _ = coding_env
    monkeypatch.setattr(codecheck.sys, "platform", "linux")
    monkeypatch.setattr(codecheck, "ALLOW_UNSANDBOXED", False)
    d = make(self_test=False, examples=True)
    state["cases"], state["answers"] = V_CASES, [V_BUGGY]
    r = chat(d, VERSIONS)
    assert r["text"] == V_BUGGY and r["code_test"]["ran"] is False


def test_examples_config_and_bench_switch(tmp_path):
    from jarvis.bench.runner import bench_config
    from jarvis.models.config import ConfigError, parse_model_config
    assert parse_model_config({"coding": {"examples": True}}).coding == {"examples": True}
    with pytest.raises(ConfigError):
        parse_model_config({"coding": {"examples": "on"}})
    real = tmp_path / "jarvis.toml"
    real.write_text("")
    assert "examples = true" in bench_config(real, "local", examples=True)
    assert "examples = true" not in bench_config(real, "local")
