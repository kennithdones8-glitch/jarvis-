"""Claude Code provider, routing to Claude, and consent flows.

A stand-in `claude` executable records exactly what JARVIS passes (argv, stdin, environment, cwd),
so these tests prove the safety flags and that nothing is sent before approval. The live check
against the real CLI is `jarvis use-claude on` on the Mac.
"""

import json
import os
import stat
import sys
import time

import pytest

from model_servers import start_ollama

from jarvis.cli import main as cli_main
from jarvis.core.tools import ApprovalRequired
from jarvis.models import ChatRequest, Message, Need
from jarvis.models.config import load_model_config
from jarvis.models.providers import ClaudeCodeProvider
from jarvis.models.types import Category, ModelInfo, ProviderError, ProviderUnavailable
from jarvis.server import Dashboard
from jarvis.tools import default_registry

FAKE = r'''#!{python}
import json, os, sys, time
args = sys.argv[1:]
stdin = sys.stdin.read()
log = os.environ["FAKE_CLAUDE_LOG"]
with open(log, "a") as fh:
    fh.write(json.dumps({{"args": args, "stdin": stdin, "cwd": os.getcwd(),
                         "env_keys": sorted(k for k in os.environ if k.startswith("ANTHROPIC"))}}) + "\n")
mode = os.environ.get("FAKE_CLAUDE_MODE", "ok")
if mode == "sleep":
    time.sleep(5)
if mode == "garbage":
    print("segfault-ish noise"); sys.exit(1)
if mode == "limit":
    print(json.dumps({{"type": "result", "is_error": True, "result": "Claude AI usage limit reached|1700000000"}})); sys.exit(1)
system = args[args.index("--system-prompt") + 1]
reply = os.environ.get("FAKE_PLAN", "{{}}") if "planning component" in system else "Claude says hello."
print(json.dumps({{"type": "result", "subtype": "success", "is_error": False, "result": reply,
                  "usage": {{"input_tokens": 42, "output_tokens": 7}}, "total_cost_usd": 0.01}}))
'''

INFO = ModelInfo("sonnet", frozenset({"chat", "plan", "code", "summarize", "json"}), 200000, 5, 3)


@pytest.fixture
def fake_claude(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    exe = bindir / "claude"
    exe.write_text(FAKE.format(python=sys.executable))
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "claude.log"
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log))

    def calls():
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    return calls


def req(*msgs, json_mode=False):
    return ChatRequest(tuple(msgs), json_mode=json_mode)


# ---- provider ------------------------------------------------------------------------------
def test_safety_flags_env_and_stdin(fake_claude, tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-never-be-used")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://elsewhere.example")
    p = ClaudeCodeProvider("claude", {"sonnet": INFO}, workdir=tmp_path / "wd")
    r = p.chat("sonnet", req(Message("system", "SYS", Category.SYSTEM_PROMPT), Message("user", "private question")))
    assert r.text == "Claude says hello." and (r.usage.input_tokens, r.usage.output_tokens) == (42, 7)
    [call] = fake_claude()
    a = call["args"]
    assert a[:3] == ["-p", "--output-format", "json"] and a[a.index("--model") + 1] == "sonnet"
    assert a[a.index("--tools") + 1] == ""                      # every built-in tool disabled
    for flag in ("--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence"):
        assert flag in a
    assert "--bare" not in a                                    # --bare would ignore the Pro login
    assert a[a.index("--system-prompt") + 1] == "SYS"
    assert "private question" not in " ".join(a)                # private text only via stdin
    assert call["stdin"] == "private question"
    assert call["env_keys"] == []                               # no API key → can't bill an API account
    assert call["cwd"] == str(tmp_path / "wd")


def test_multi_turn_and_json_mode(fake_claude, tmp_path):
    p = ClaudeCodeProvider("claude", {"sonnet": INFO}, workdir=tmp_path)
    p.chat("sonnet", req(Message("user", "first"), Message("assistant", "reply"), Message("user", "second"),
                         json_mode=True))
    call = fake_claude()[0]
    assert "[Owner]: first" in call["stdin"] and "[You]: reply" in call["stdin"] and call["stdin"].endswith("last message.")
    assert "JSON object only" in call["args"][call["args"].index("--system-prompt") + 1]


@pytest.mark.parametrize("mode,exc,match", [
    ("limit", ProviderUnavailable, "usage limit"),
    ("garbage", ProviderError, "exit 1"),
])
def test_errors_classified(fake_claude, tmp_path, monkeypatch, mode, exc, match):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", mode)
    with pytest.raises(exc, match=match):
        ClaudeCodeProvider("claude", {"sonnet": INFO}, workdir=tmp_path).chat("sonnet", req(Message("user", "x")))


def test_timeout_and_missing_binary(fake_claude, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "sleep")
    with pytest.raises(ProviderError, match="did not answer"):
        ClaudeCodeProvider("claude", {"sonnet": INFO}, workdir=tmp_path, timeout=0.5).chat("sonnet", req(Message("user", "x")))
    missing = ClaudeCodeProvider("claude", {"sonnet": INFO}, workdir=tmp_path, command="no-such-claude-binary")
    with pytest.raises(ProviderUnavailable, match="not installed"):
        missing.available_models()


# ---- routing + consent through the real kernel --------------------------------------------
CFG = """[routing]
mode = "{mode}"
[providers.ollama]
kind = "ollama"
enabled = true
host = "{url}"
[[providers.ollama.models]]
id = "llama:3b"
capabilities = ["chat", "plan", "summarize", "json"]
context_tokens = 16384
quality = 3
speed = 4
[providers.claude]
kind = "claude_code"
enabled = true
[[providers.claude.models]]
id = "sonnet"
capabilities = ["chat", "plan", "code", "summarize", "json"]
context_tokens = 200000
quality = 5
speed = 3
"""


@pytest.fixture
def brain(make_kernel, tmp_path, fake_claude):
    servers = []

    def _make(mode="best"):
        srv = start_ollama(installed=["llama:3b"])
        srv.reply = lambda body: (json.dumps({"goal": "local plan", "steps": [{"description": "List", "tool": "fs",
                                  "action": "list", "args": {"path": "/"}, "depends_on": []}]})
                                  if "planning component" in body["messages"][0]["content"] else "Local says hello.")
        servers.append(srv)
        (tmp_path / "jarvis.toml").write_text(CFG.format(mode=mode, url=srv.url))
        return make_kernel(registry=default_registry(tmp_path / "home"), config_path=tmp_path / "jarvis.toml"), srv
    yield _make
    for s in servers:
        s.stop()


PRIVATE = req(Message("system", "SYS", Category.SYSTEM_PROMPT), Message("user", "my private question"))


def test_best_mode_asks_before_sending_then_sends_identical_request(brain, fake_claude):
    k, local = brain("best")
    with pytest.raises(ApprovalRequired) as ei:
        k.models.complete(Need("chat", prefer="auto"), PRIVATE, purpose="chat")
    assert fake_claude() == [] and local.received == []      # nothing sent anywhere before you decide
    appr = k.approvals.get(ei.value.approval_id)
    assert appr["tool"] == "egress" and appr["action"] == "claude" and "Claude Pro" in appr["summary"]
    k.approvals.decide(ei.value.approval_id, approve=True, by="user:test")
    r = k.models.complete(Need("chat", prefer="auto"), PRIVATE, purpose="chat")
    assert (r.provider, r.text) == ("claude", "Claude says hello.") and len(fake_claude()) == 1
    assert r.cost_usd == 0.0                                   # subscription: nothing billed


def test_local_first_mode_and_local_only_never_touch_claude(brain, fake_claude):
    k, _ = brain("local_first")
    assert k.models.complete(Need("chat", prefer="auto"), PRIVATE, purpose="chat").provider == "ollama"
    k2, _ = brain("best")
    assert k2.models.complete(Need("chat", prefer="auto", local_only=True), PRIVATE, purpose="chat").provider == "ollama"
    assert fake_claude() == []


def test_public_content_needs_no_approval(brain, fake_claude):
    k, _ = brain("best")
    r = k.models.complete(Need("chat", prefer="auto"), req(Message("user", "status", Category.SYSTEM_PROMPT)), purpose="t")
    assert r.provider == "claude"


def test_usage_limit_falls_back_to_local_and_is_recorded(brain, fake_claude, monkeypatch):
    k, _ = brain("best")
    k.models.router.gate.grants.grant(category="conversation", provider="claude", by="user:test")
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "limit")
    r = k.models.complete(Need("chat", prefer="auto"), PRIVATE, purpose="chat")
    assert r.provider == "ollama"
    failed = [e for e in k.audit.entries(limit=200) if e["event"] == "model.attempt_failed"]
    assert failed and "usage limit" in failed[-1]["payload"]["error"]


def test_dashboard_chat_consent_flow(brain, fake_claude):
    k, _ = brain("best")
    d = Dashboard(k, port=0, token="t")
    try:
        first = d.chat("hello there", [])
        assert first["needs_approval"] and "Claude" in first["summary"] and fake_claude() == []
        k.approvals.decide(first["approval_id"], approve=True, by="user:test")
        again = d.chat("hello there", [])
        assert again["text"] == "Claude says hello." and again["model"] == "claude/sonnet"
        local = d.chat("keep this local", [], local_only=True)
        assert local["text"] == "Local says hello." and len(fake_claude()) == 1
    finally:
        d.shutdown()


def test_dashboard_planning_waits_for_decision_then_plans_locally_on_reject(brain, fake_claude):
    k, _ = brain("best")
    d = Dashboard(k, port=0, token="t")
    try:
        job_id = d.start_plan("list my root folder")
        end = time.time() + 10
        while d.jobs[job_id]["state"] != "waiting_approval" and time.time() < end:
            time.sleep(0.05)
        assert d.jobs[job_id]["state"] == "waiting_approval" and fake_claude() == []
        k.approvals.decide(d.jobs[job_id]["approval_id"], approve=False, by="user:test")
        while d.jobs[job_id]["state"] != "ready" and time.time() < end:
            time.sleep(0.05)
        job = d.jobs[job_id]
        assert job["kind"] == "plan" and job["model"] == "ollama/llama:3b" and "locally" in job["note"]
        assert fake_claude() == []
    finally:
        d.shutdown()


def test_use_claude_command_edits_config_and_probes(fake_claude, tmp_path):
    home = tmp_path / "jhome"
    assert cli_main(["--home", str(home), "init"]) == 0
    assert cli_main(["--home", str(home), "use-claude", "on"]) == 0
    cfg = load_model_config(home / "jarvis.toml")
    assert cfg.routing_mode == "best" and any(p.name == "claude" and p.enabled for p in cfg.providers)
    probe = fake_claude()[-1]
    assert probe["stdin"] == "Status check."                 # the probe sends no private data
    assert (home / "jarvis.toml.bak").exists()
    assert cli_main(["--home", str(home), "use-claude", "off"]) == 0
    cfg = load_model_config(home / "jarvis.toml")
    assert cfg.routing_mode == "local_first" and not any(p.name == "claude" and p.enabled for p in cfg.providers)
