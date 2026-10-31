from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from helpers import build_registry  # noqa: E402

from jarvis.core import Kernel  # noqa: E402

DEFAULT_POLICY = """
[filesystem]
roots = ["{root}"]

[[rules]]
id = "notes-write"
effect = "allow"
tools = ["fs"]
actions = ["write", "append"]
resources = ["{root}/notes/**"]

[[rules]]
id = "net-allow"
effect = "allow"
tools = ["net"]
actions = ["post"]
"""


@pytest.fixture(autouse=True)
def _never_touch_the_real_mac(monkeypatch):
    """Tests run on the owner's Mac too, so they must never reach the real machine: no launchctl (it would restart
    the owner's background service) and no Mac apps (their real Calendar, Reminders and Notes). Tests that need
    either pass a stand-in explicitly (e.g. ``default_registry(..., mac_runner=fake)``)."""
    import subprocess

    from jarvis import service
    from jarvis.tools import mac

    def no_launchctl(*args, check=True):
        return subprocess.CompletedProcess(["launchctl", *args], 113, "", "not loaded (tests never use launchctl)")
    monkeypatch.setattr(service, "_launchctl", no_launchctl)
    monkeypatch.setattr(mac, "available", lambda: False)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    r = tmp_path / "work"
    (r / "notes").mkdir(parents=True)
    return r


@pytest.fixture
def make_kernel(tmp_path: Path, root: Path):
    opened: list[Kernel] = []

    def _make(policy: str | None = DEFAULT_POLICY, registry=None, **kwargs) -> Kernel:
        policy_path = tmp_path / "policy.toml"
        if policy is not None:
            policy_path.write_text(policy.replace("{root}", str(root)))
        # registry="default" → the kernel's real production tools (as on the Mac)
        chosen = None if registry == "default" else (registry or build_registry())
        kernel = Kernel(tmp_path / "home", policy_path=policy_path, registry=chosen, **kwargs)
        opened.append(kernel)
        return kernel

    yield _make
    for k in opened:
        k.close()


# ---- a running dashboard with a stand-in Ollama (used by dashboard, Touch ID, doctor, proactive tests) ----
CFG = """[providers.ollama]
kind = "ollama"
enabled = true
host = "{url}"
[[providers.ollama.models]]
id = "planner:7b"
capabilities = ["chat", "plan", "json", "summarize"]
context_tokens = 16384
quality = 3
speed = 2
"""


@pytest.fixture
def dash(make_kernel, tmp_path, root):
    from model_servers import start_ollama

    from jarvis.server import Dashboard
    from jarvis.tools import default_registry

    server = start_ollama(installed=["planner:7b"])
    script = {"plan": None}

    def reply(body):
        if "planning component" in body["messages"][0]["content"]:
            return json.dumps(script["plan"])
        if "writing component" in body["messages"][0]["content"]:
            return "Composed text."
        return "Hello, I am JARVIS."
    server.reply = reply
    (tmp_path / "jarvis.toml").write_text(CFG.format(url=server.url))
    k = make_kernel(registry=default_registry(tmp_path / "home"), config_path=tmp_path / "jarvis.toml")
    d = Dashboard(k, port=0, token="test-token", poll_s=0.05)
    d.start()
    yield d, script, root
    d.shutdown()
    server.stop()
