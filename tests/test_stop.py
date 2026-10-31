"""v0.12 F3: the emergency stop (pressed in any JARVIS process) kills Claude Code work in progress,
including anything it spawned, and the task pauses cleanly."""

import os
import stat
import sys
import threading
import time
from pathlib import Path

import pytest

from jarvis.core import Kernel, StepSpec, TaskState
from jarvis.core.killswitch import EmergencyStop
from jarvis.models import ChatRequest, Message
from jarvis.models.providers import ClaudeCodeProvider, run_tracked
from jarvis.models.types import Category, ModelInfo

HANG = r'''#!{python}
import os, subprocess, sys, time
sys.stdin.read()
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
open(os.environ["PIDS"], "w").write(f"{{os.getpid()}} {{child.pid}}")
time.sleep(60)
'''


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:  # a zombie (exited, not yet reaped) counts as dead
        return Path(f"/proc/{pid}/stat").read_text().split()[2] != "Z"
    except OSError:
        return True


@pytest.fixture
def hanging_claude(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    exe = bindir / "claude"
    exe.write_text(HANG.format(python=sys.executable))
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    pids = tmp_path / "pids"
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("PIDS", str(pids))
    return pids


def wait_for(path: Path, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end and not path.exists():
        time.sleep(0.05)
    return [int(x) for x in path.read_text().split()]


def test_stop_kills_running_claude_and_its_children(make_kernel, tmp_path, hanging_claude):
    cfg = tmp_path / "jarvis.toml"
    cfg.write_text('[routing]\nmode = "best"\n[providers.claude]\nkind = "claude_code"\nenabled = true\n'
                   '[[providers.claude.models]]\nid = "haiku"\ncapabilities = ["chat", "summarize"]\n'
                   'context_tokens = 200000\nquality = 4\nspeed = 5\n')
    k = make_kernel(registry="default", config_path=cfg)
    from jarvis.orchestrator import Orchestrator
    Orchestrator(k)                                               # registers llm.compose
    k.models.router.gate.grants.grant(category="file_content", provider="claude", by="user:test")
    tid = k.tasks.create("write", steps=[StepSpec("Write", "llm", "compose", {"instruction": "x", "inputs": ["data"]})])
    result = {}
    t = threading.Thread(target=lambda: result.setdefault("state", k.engine.run(tid)))
    t.start()
    claude_pid, child_pid = wait_for(hanging_claude)
    assert alive(claude_pid) and alive(child_pid)
    other = Kernel(k.home, policy_path=k.policy_path, config_path=cfg)  # e.g. `jarvis stop` in a terminal
    pressed = time.monotonic()
    other.engine.emergency_stop(by="user:test", reason="stop now")
    t.join(timeout=15)
    assert not t.is_alive() and time.monotonic() - pressed < 5
    assert result["state"] is TaskState.PAUSED
    step = k.tasks.steps(tid)[0]
    assert step["state"] == "pending"                              # will re-run after you resume; nothing half-done
    time.sleep(0.3)
    assert not alive(claude_pid) and not alive(child_pid)          # the whole process group is gone
    other.close()


def test_run_tracked_deadline_kills_process_group(tmp_path, hanging_claude):
    import subprocess
    with pytest.raises(subprocess.TimeoutExpired):
        run_tracked([str(tmp_path / "bin" / "claude")], input="", timeout=1.0, cwd=tmp_path, env=dict(os.environ))
    claude_pid, child_pid = wait_for(hanging_claude)
    time.sleep(0.3)
    assert not alive(claude_pid) and not alive(child_pid)


def test_direct_provider_call_raises_emergency_stop(make_kernel, tmp_path, hanging_claude):
    k = make_kernel()
    p = ClaudeCodeProvider("claude", {"haiku": ModelInfo("haiku", frozenset({"chat"}), 1000, 4, 5)}, workdir=tmp_path / "wd")
    p.cancel_check = k.killswitch.engaged
    threading.Timer(1.0, lambda: k.killswitch.engage(by="user:test", reason="x")).start()
    from jarvis.models.providers import Cancelled
    with pytest.raises(Cancelled):
        p.chat("haiku", ChatRequest((Message("user", "hi", Category.SYSTEM_PROMPT),)))
