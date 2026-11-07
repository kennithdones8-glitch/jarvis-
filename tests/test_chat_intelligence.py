"""Phase 3a: Claude replies shown as they're written, intelligence modes (Quick / Balanced / Deep), and the real
stages of a chat answer.

A stand-in `claude` executable speaks Claude Code's `stream-json` format (with partial messages) and records
exactly what JARVIS passes, so these tests prove the safety flags survive streaming, nothing streams before
consent, and a stopped or abandoned reply kills the process. Live check against the real CLI: on the Mac.
"""

import json
import os
import stat
import sys
import time
import urllib.request

import pytest

from model_servers import start_ollama

from jarvis.core.tools import ApprovalRequired
from jarvis.models import ChatRequest, Message, Need
from jarvis.models.providers import Cancelled, ClaudeCodeProvider
from jarvis.models.types import Category, ModelInfo, ProviderError, UsageLimited
from jarvis.server import Dashboard
from jarvis.tools import default_registry

FAKE = r'''#!{python}
import json, os, sys, time
args = sys.argv[1:]
stdin = sys.stdin.read()
with open(os.environ["FAKE_CLAUDE_LOG"], "a") as fh:
    fh.write(json.dumps({{"args": args, "stdin": stdin, "pid": os.getpid(),
                         "env_keys": sorted(k for k in os.environ if k.startswith("ANTHROPIC"))}}) + "\n")
mode = os.environ.get("FAKE_CLAUDE_MODE", "ok")
reply = os.environ.get("FAKE_REPLY", "Claude streams this reply word by word.")
delay = float(os.environ.get("FAKE_DELAY", "0"))
if "stream-json" not in args:  # a whole reply takes as long to write as a streamed one
    time.sleep(delay * len(reply.split(" ")))
    print(json.dumps({{"type": "result", "is_error": False, "result": reply, "usage": {{"input_tokens": 9, "output_tokens": 5}}}}))
    sys.exit(0)
def emit(obj):
    print(json.dumps(obj), flush=True)
emit({{"type": "system", "subtype": "init"}})
if mode == "garbage":
    print("noise", flush=True); sys.exit(1)
if mode == "limit":
    emit({{"type": "result", "is_error": True, "result": "Claude AI usage limit reached|1700000000"}}); sys.exit(1)
if mode == "stall":
    time.sleep(30)
words = reply.split(" ")
for i, w in enumerate(words):
    piece = w if i == 0 else " " + w
    emit({{"type": "stream_event", "event": {{"type": "content_block_delta", "index": 0,
          "delta": {{"type": "text_delta", "text": piece}}}}}})
    if mode == "slow":
        time.sleep(5)
    elif delay:
        time.sleep(delay)
emit({{"type": "assistant", "message": {{"content": [{{"type": "text", "text": reply}}]}}}})
emit({{"type": "result", "subtype": "success", "is_error": False, "result": reply,
      "usage": {{"input_tokens": 11, "output_tokens": len(words)}}}})
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


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:  # a zombie that's been reaped by nobody still "exists"; check its state where we can
        with open(f"/proc/{pid}/stat") as fh:
            return fh.read().split()[2] != "Z"
    except OSError:
        return True


def provider(tmp_path, **kw):
    return ClaudeCodeProvider("claude", {"sonnet": INFO}, workdir=tmp_path / "wd", **kw)


REQ = ChatRequest((Message("system", "SYS", Category.SYSTEM_PROMPT), Message("user", "private question")))


# ---- provider ------------------------------------------------------------------------------------------------
def test_claude_streams_pieces_that_add_up_to_the_final_reply(fake_claude, tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-never-be-used")
    pieces = []
    r = provider(tmp_path).chat("sonnet", REQ, on_token=pieces.append)
    assert r.text == "Claude streams this reply word by word." == "".join(p for p in pieces if p)
    assert len([p for p in pieces if p]) == 7 and (r.usage.input_tokens, r.usage.output_tokens) == (11, 7)
    [call] = fake_claude()
    a = call["args"]
    assert a[:6] == ["-p", "--output-format", "stream-json", "--verbose", "--include-partial-messages", "--model"]
    # the same protections as a whole reply
    assert a[a.index("--tools") + 1] == "" and a[a.index("--setting-sources") + 1] == "project"
    for flag in ("--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence"):
        assert flag in a
    assert "private question" not in " ".join(a) and call["stdin"] == "private question"
    assert call["env_keys"] == []


def test_without_a_viewer_claude_still_answers_whole(fake_claude, tmp_path):
    r = provider(tmp_path).chat("sonnet", REQ)
    assert r.text == "Claude streams this reply word by word."
    assert fake_claude()[0]["args"][:3] == ["-p", "--output-format", "json"]


def test_viewer_leaving_kills_claude_and_is_not_a_model_failure(fake_claude, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "slow")  # 5 s between words

    def gone(piece):
        if piece:
            raise BrokenPipeError("page closed")
    started = time.monotonic()
    with pytest.raises(BrokenPipeError):  # not a ProviderError: the router must not try another model
        provider(tmp_path).chat("sonnet", REQ, on_token=gone)
    assert time.monotonic() - started < 4
    time.sleep(0.2)
    assert not alive(fake_claude()[0]["pid"])


def test_closed_page_noticed_before_the_first_word(fake_claude, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "stall")  # says nothing for 30 s
    probes = []

    def probe(piece):
        probes.append(piece)
        if piece == "":
            raise BrokenPipeError("page closed")
    started = time.monotonic()
    with pytest.raises(BrokenPipeError):
        provider(tmp_path).chat("sonnet", REQ, on_token=probe)
    assert probes == [""] and time.monotonic() - started < 4
    time.sleep(0.2)
    assert not alive(fake_claude()[0]["pid"])


def test_emergency_stop_kills_a_streaming_reply(fake_claude, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "slow")
    state = {"stop": False}
    p = provider(tmp_path)
    p.cancel_check = lambda: state["stop"]

    def on_token(piece):
        if piece:
            state["stop"] = True  # pressed while Claude is writing
    with pytest.raises(Cancelled):
        p.chat("sonnet", REQ, on_token=on_token)
    time.sleep(0.2)
    assert not alive(fake_claude()[0]["pid"])


@pytest.mark.parametrize("mode,exc,match", [("limit", UsageLimited, "usage limit"), ("garbage", ProviderError, "exit 1")])
def test_streamed_errors_classified_like_whole_ones(fake_claude, tmp_path, monkeypatch, mode, exc, match):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", mode)
    with pytest.raises(exc, match=match):
        provider(tmp_path).chat("sonnet", REQ, on_token=lambda piece: None)


def test_streaming_respects_the_deadline(fake_claude, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "stall")
    with pytest.raises(ProviderError, match="did not answer"):
        provider(tmp_path, timeout=0.7).chat("sonnet", REQ, on_token=lambda piece: None)
    time.sleep(0.2)
    assert not alive(fake_claude()[0]["pid"])


# ---- through the kernel: consent first, then words ---------------------------------------------------------
CFG = """[routing]
mode = "{mode}"
[providers.ollama]
kind = "ollama"
enabled = true
host = "{url}"
[[providers.ollama.models]]
id = "llama:3b"
capabilities = ["chat", "plan", "summarize", "json", "classify"]
context_tokens = 16384
quality = 3
speed = 4
[providers.claude]
kind = "claude_code"
enabled = {claude}
[[providers.claude.models]]
id = "sonnet"
capabilities = ["chat", "plan", "code", "summarize", "json"]
context_tokens = 200000
quality = 5
speed = 3
[[providers.claude.models]]
id = "haiku"
capabilities = ["chat", "summarize", "json"]
context_tokens = 200000
quality = 4
speed = 5
"""


def local_reply(body):
    system = body["messages"][0]["content"]
    if "lookup step of JARVIS" in system:
        return json.dumps({"lookups": [], "change": False, "difficulty": "hard"})
    if "Classify how demanding" in system:
        return "HARD"
    return "Local says hello."


@pytest.fixture
def brain(make_kernel, tmp_path, fake_claude):
    servers, dashboards = [], []

    def _make(mode="hybrid", claude=True):
        srv = start_ollama(installed=["llama:3b"])
        srv.reply = local_reply
        servers.append(srv)
        (tmp_path / "jarvis.toml").write_text(CFG.format(mode=mode, url=srv.url, claude="true" if claude else "false"))
        k = make_kernel(registry=default_registry(tmp_path / "home"), config_path=tmp_path / "jarvis.toml")
        d = Dashboard(k, port=0, token="test-token", poll_s=0.05)
        d.start()
        dashboards.append(d)
        return k, srv, d
    yield _make
    for d in dashboards:
        d.shutdown()
    for s in servers:
        s.stop()


def stream(d, body):
    req = urllib.request.Request(
        f"http://127.0.0.1:{d.port}/api/chat/stream", data=json.dumps(body).encode(), method="POST",
        headers={"Host": f"localhost:{d.port}", "Content-Type": "application/json", "X-Requested-By": "jarvis",
                 "Cookie": "jarvis_session=test-token"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return [json.loads(x) for x in r.read().decode().splitlines() if x.strip()]


def stages(lines):
    return [x["s"]["stage"] for x in lines if "s" in x]


def test_nothing_streams_before_consent(brain, fake_claude):
    k, _, _ = brain("best")
    pieces = []
    with pytest.raises(ApprovalRequired):
        k.models.complete(Need("chat", prefer="auto"), REQ, purpose="chat", on_token=pieces.append)
    assert fake_claude() == [] and pieces == []


def test_dashboard_streams_claude_with_real_stages(brain, fake_claude):
    k, _, d = brain("best")
    k.models.router.gate.grants.grant(category="conversation", provider="claude", by="user:test")
    lines = stream(d, {"message": "explain tides", "history": [], "mode": "deep"})
    done = lines[-1]["done"]
    words = "".join(x["t"] for x in lines if "t" in x)
    assert words == done["text"] == "Claude streams this reply word by word."
    assert done["model"] == "claude/sonnet" and done["mode"] == "deep" and done["location"] == "cloud"
    assert stages(lines)[:3] == ["understanding", "context", "generating"]
    gen = next(x["s"] for x in lines if x.get("s", {}).get("stage") == "generating")
    assert gen == {"stage": "generating", "model": "claude/sonnet", "location": "cloud", "streams": True}
    first_word = next(i for i, x in enumerate(lines) if "t" in x)
    assert lines.index({"s": gen}) < first_word  # you see who is writing before the words arrive
    assert fake_claude()[0]["args"][2] == "stream-json"


def test_quick_mode_stays_local_and_skips_the_goal_reader(brain, fake_claude):
    k, local, d = brain("hybrid")
    lines = stream(d, {"message": "explain tides", "history": [], "mode": "quick"})
    done = lines[-1]["done"]
    assert done["model"] == "ollama/llama:3b" and done["location"] == "local" and done["mode"] == "quick"
    systems = [b["body"]["messages"][0]["content"] for b in local.received]
    assert len(systems) == 1 and "lookup step" not in systems[0]  # one call: the answer itself
    assert fake_claude() == []


def test_quick_mode_never_upgrades_maths_to_a_slower_model(brain, fake_claude):
    k, local, d = brain("hybrid")
    q = "A recipe for 4 uses 300 g of flour. How many grams do I need for 10 people?"
    stream(d, {"message": q, "history": [], "mode": "quick"})
    assert not [e for e in k.audit.entries(limit=100) if e["event"] == "model.reasoning_local"]  # Quick means fast


def test_balanced_hybrid_still_rates_with_the_goal_reader(brain, fake_claude):
    k, local, d = brain("hybrid")
    k.models.router.gate.grants.grant(category="conversation", provider="claude", by="user:test")
    done = stream(d, {"message": "explain tides", "history": []})[-1]["done"]
    assert done["mode"] == "balanced"
    assert any("lookup step" in b["body"]["messages"][0]["content"] for b in local.received)
    assert done["model"] == "claude/sonnet"  # the goal reader rated it hard


def test_deep_mode_prefers_the_strongest_model_and_asks_first(brain, fake_claude):
    k, local, d = brain("local_first")  # even when your routing is local-first
    first = d.chat("prove there are infinitely many primes", [], mode="deep")
    assert first["needs_approval"] and fake_claude() == []
    k.approvals.decide(first["approval_id"], approve=True, by="user:test")
    again = d.chat("prove there are infinitely many primes", [], mode="deep")
    assert again["model"] == "claude/sonnet"
    assert '"max_tokens"' not in fake_claude()[0]["stdin"]  # (prompt over stdin only; sanity)
    assert not any("lookup step" in b["body"]["messages"][0]["content"] for b in local.received)


def test_deep_without_claude_answers_locally_and_says_so(brain, fake_claude):
    k, _, d = brain("local_first", claude=False)
    r = d.chat("prove there are infinitely many primes", [], mode="deep")
    assert r["model"] == "ollama/llama:3b" and "no stronger model is available" in r["note"]
    assert any(e["event"] == "chat.mode_fallback" for e in k.audit.entries(limit=100))


def test_local_only_is_never_overridden_by_a_mode(brain, fake_claude):
    k, _, d = brain("best")
    for mode in ("quick", "balanced", "deep"):
        r = d.chat("hi", [], mode=mode, local_only=True)
        assert r["location"] == "local", mode
    assert fake_claude() == []


def test_unknown_mode_is_balanced(brain, fake_claude):
    k, _, d = brain("local_first")
    lines = stream(d, {"message": "hi", "history": [], "mode": "turbo-max"})
    assert lines[-1]["done"]["mode"] == "balanced"


def test_a_failed_attempt_is_announced_so_its_words_can_be_dropped(brain, fake_claude, monkeypatch):
    k, _, d = brain("best")
    k.models.router.gate.grants.grant(category="conversation", provider="claude", by="user:test")
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "limit")
    lines = stream(d, {"message": "hi", "history": []})
    gens = [x["s"] for x in lines if x.get("s", {}).get("stage") == "generating"]
    assert gens[0]["location"] == "cloud" and gens[-1]["location"] == "local"
    assert lines[-1]["done"]["text"] == "Local says hello."
