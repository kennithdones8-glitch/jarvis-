"""F: work it out with code. The program is vetted before it runs, runs only in the macOS sandbox, only when the
owner turned it on, only for answers that stay on this Mac, and never in Quick mode."""

import json
import subprocess

import pytest

from model_servers import start_ollama
from test_chat_intelligence import CFG, fake_claude  # noqa: F401  (fixture)

from jarvis import codecheck, compute
from jarvis.compute import run_program, vet, wants_compute
from jarvis.server import Dashboard
from jarvis.tools import default_registry

JOURNEY = ("A train leaves at 9:40. It travels 168 km at 72 km/h, waits 15 minutes, then travels 90 km at 60 km/h. "
           "What time does it arrive?")
PROGRAM = ("```python\nfrom datetime import datetime, timedelta\nt = datetime(2026, 1, 1, 9, 40)\n"
           "t += timedelta(hours=168/72) + timedelta(minutes=15) + timedelta(hours=90/60)\nprint(t.strftime('%H:%M'))\n```")


@pytest.mark.parametrize("code, why", [
    ("import os\nprint(os.listdir('/'))", "imports os"),
    ("from subprocess import run\nrun(['ls'])", "imports from subprocess"),
    ("import socket", "imports socket"),
    ("print(open('/etc/passwd').read())", "calls open()"),
    ("__import__('os').system('ls')", "calls __import__()"),
    ("print(().__class__.__bases__)", "uses .__"),
    ("eval('1+1')", "calls eval()"),
    ("exec('x=1')", "calls exec()"),
    ("getattr(print, 'x')", "calls getattr()"),
    ("from . import x", "imports from"),
    ("print(", "isn't valid Python"),
])
def test_unsafe_programs_are_never_run(code, why, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: pytest.fail("a rejected program must never start"))
    assert why in vet(code)
    r = run_program(code)
    assert not r.ok and r.error.startswith("not run:")


def test_ordinary_maths_programs_pass_the_check():
    assert vet(PROGRAM.split("```python\n")[1].rstrip("`\n")) is None
    assert vet("import itertools, math\nfrom fractions import Fraction\nprint(math.gcd(4, 6), Fraction(1, 3))") is None


def test_nothing_runs_without_the_sandbox(monkeypatch):
    monkeypatch.setattr(codecheck, "ALLOW_UNSANDBOXED", False)
    monkeypatch.setattr(codecheck.sys, "platform", "linux")
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: pytest.fail("nothing may run without the sandbox"))
    r = run_program("print(1)")
    assert not r.ok and "only run inside the macOS sandbox" in r.error


def test_a_program_runs_and_its_output_is_captured(monkeypatch):
    monkeypatch.setattr(codecheck, "ALLOW_UNSANDBOXED", True)  # Linux test only: the Mac uses sandbox-exec
    r = run_program(compute.program_of(PROGRAM))
    assert r.ok and r.output == "13:45"
    assert run_program("print('x' * 5000)").output == "x" * compute.MAX_OUTPUT
    assert run_program("pass").error == "it printed nothing"
    assert not run_program("raise ValueError('nope')").ok


def test_an_endless_program_is_stopped(monkeypatch):
    monkeypatch.setattr(codecheck, "ALLOW_UNSANDBOXED", True)
    monkeypatch.setattr(compute, "TIMEOUT_S", 1)
    r = run_program("while True:\n    pass")
    assert not r.ok and "timed out" in r.error


def test_which_questions_are_worked_out():
    assert wants_compute(JOURNEY)
    assert wants_compute("Ana, Ben and Cara each get one slot: 9:00, 10:00 or 11:00. Ana is earlier than Ben. "
                         "Cara is not first. Who has each slot?")
    assert not wants_compute("Write a Python function that adds two numbers")  # that's a request for code
    assert not wants_compute("Tell me a joke")


@pytest.fixture
def mind(make_kernel, tmp_path, monkeypatch):
    """A dashboard with one local model scripted to write the program, and Claude configurable."""
    monkeypatch.setattr(codecheck, "ALLOW_UNSANDBOXED", True)
    made = []

    def _make(*, compute_on=True, mode="local_first", claude=False):
        srv = start_ollama(installed=["llama:3b"])
        seen = []

        def reply(body):
            seen.append(json.dumps(body["messages"]))
            system = body["messages"][0]["content"]
            if "lookup step of JARVIS" in system:
                return json.dumps({"lookups": [], "change": False, "difficulty": "hard"})
            if "work out an exact answer" in system:
                return PROGRAM
            return "It arrives at 13:45.\n13:45"
        srv.reply = reply
        cfg = CFG.format(mode=mode, url=srv.url, claude="true" if claude else "false")
        (tmp_path / "jarvis.toml").write_text(cfg + ("[coding]\ncompute = true\n" if compute_on else ""))
        k = make_kernel(registry=default_registry(tmp_path / "home"), config_path=tmp_path / "jarvis.toml")
        d = Dashboard(k, port=0, token="t")
        made.append((d, srv))
        return k, d, seen
    yield _make
    for d, srv in made:
        d.shutdown()
        srv.stop()


def test_off_by_default(mind):
    k, d, seen = mind(compute_on=False)
    r = d.chat(JOURNEY, [])
    assert not any("work out an exact answer" in s for s in seen) and "🧮" not in (r.get("note") or "")
    assert not [e for e in k.audit.entries(limit=50) if e["event"] == "chat.computed"]


def test_when_on_the_answer_is_written_from_the_programs_output(mind):
    k, d, seen = mind()
    r = d.chat(JOURNEY, [])
    answer_prompt = seen[-1]
    assert "<program_output>\\n13:45\\n</program_output>" in answer_prompt
    assert "🧮 Worked out by running a short program" in r["note"]
    [e] = [e for e in k.audit.entries(limit=50) if e["event"] == "chat.computed"]
    assert e["payload"]["ok"] is True and e["payload"]["output_chars"] == 5 and "13:45" not in json.dumps(e)  # no content in the audit


def test_never_in_quick_mode(mind):
    k, d, seen = mind()
    d.chat(JOURNEY, [], mode="quick")
    assert not any("work out an exact answer" in s for s in seen)


def test_never_runs_when_the_answer_goes_to_claude(mind, fake_claude):  # noqa: F811 (fixture)
    """Deep mode with Claude on: the answer may go to Claude, so nothing is run and no program output exists to
    be sent anywhere."""
    k, d, seen = mind(mode="hybrid", claude=True)
    for cat in ("conversation",):
        k.models.router.gate.grants.grant(category=cat, provider="claude", by="user:test")
    d.chat(JOURNEY, [], mode="deep")
    assert not any("work out an exact answer" in s for s in seen)
    assert "program_output" not in json.dumps(fake_claude())
