"""Evolution 3.0, phase 1: closing the autonomy security gaps found in the audit.

1. Change trials (tier 6) run a branch's tests isolated: a bare environment and a throwaway HOME everywhere, and on
   macOS the system sandbox (no network except this Mac, no writes outside the trial, no reads of JARVIS's data or
   your keys). The macOS sandbox itself can only be exercised on a Mac; here its rules and wiring are checked.
2. A paired iPhone can never start a change trial (tests/test_remote.py).
3. Forgetting removes your ratings and their comments too.
4. Every tool action goes through the permission gateway: no code calls a tool's handler directly (one documented,
   read-only exception: `jarvis mac check`).
"""

import ast
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from jarvis.learn import add_feedback, trial

SRC = Path(__file__).resolve().parents[1] / "src" / "jarvis"
needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
                        "HOME": str(repo), "PATH": "/usr/bin:/bin:/usr/local/bin"})


# ---- 1. trial isolation -------------------------------------------------------------------------------------------
@needs_git
def test_a_trial_runs_with_no_secrets_and_a_throwaway_home(tmp_path, monkeypatch):
    """The candidate's tests check their own environment: they only pass if nothing private reached them."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-never-arrive")
    monkeypatch.setenv("SSH_AUTH_SOCK", "/tmp/agent.sock")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_should-never-arrive")
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "real-data"))
    r = tmp_path / "repo"
    (r / "src").mkdir(parents=True)
    (r / "tests").mkdir()
    (r / "src" / "probe.py").write_text("X = 1\n")
    (r / "tests" / "test_probe.py").write_text(
        "import os\nfrom pathlib import Path\n\n"
        f"REAL_HOME = {str(Path.home())!r}\nREAL_DATA = {str(tmp_path / 'real-data')!r}\n\n"
        "def test_no_secrets():\n"
        "    for k in ('ANTHROPIC_API_KEY', 'SSH_AUTH_SOCK', 'GITHUB_TOKEN'):\n"
        "        assert k not in os.environ, k\n\n"
        "def test_throwaway_home_and_data():\n"
        "    assert os.environ['HOME'] != REAL_HOME and os.environ['JARVIS_HOME'] != REAL_DATA\n"
        "    assert Path(os.environ['HOME']).is_dir() and Path(os.environ['TMPDIR']).is_dir()\n"
        "    assert os.environ.get('PYTHONDONTWRITEBYTECODE') == '1'\n")
    git(r, "init", "-q", "-b", "main")
    git(r, "add", ".")
    git(r, "commit", "-qm", "base")
    result = trial.run("main", "main", work=tmp_path / "work", repo=r, data=tmp_path / "real-data")
    assert result["ran"] and result["candidate"]["tests"] == {"passed": 2, "failed": 0, "error": 0, "skipped": 0}
    assert result["isolation"] == ("macOS sandbox" if sys.platform == "darwin" else "environment only")
    assert not any((tmp_path / "work").iterdir())                                  # the throwaway folders are gone


def test_trial_env_passes_only_the_basics(tmp_path, monkeypatch):
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "x")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "x")
    env = trial.trial_env(tmp_path / "tree", tmp_path / "home", tmp_path / "tmp")
    assert set(env) <= set(trial.PASS_ENV) | {"HOME", "TMPDIR", "PYTHONPATH", "PYTHONDONTWRITEBYTECODE", "JARVIS_HOME"}
    assert env["HOME"] == str(tmp_path / "home") and env["JARVIS_HOME"].startswith(str(tmp_path / "home"))


def test_the_macos_sandbox_rules_deny_network_writes_and_private_reads(tmp_path):
    root, data, home = tmp_path / "data" / "trials" / "trial-1", tmp_path / "data", tmp_path / "home"
    p = trial.sandbox_profile(root, data, home, extra_reads=[tmp_path / "repo" / ".git"])
    lines = p.splitlines()
    assert lines[:3] == ["(version 1)", "(allow default)", "(deny network*)"]
    assert '(allow network-outbound (remote ip "localhost:*"))' in p              # only this Mac (the tests' stand-ins)
    assert '(allow network-bind network-inbound (local ip "localhost:*"))' in p
    assert "(allow network* " not in p                                            # no broad network allow at all
    assert "(deny file-write*)" in p and f'(allow file-write* (subpath "{os.path.realpath(root)}")' in p
    # reads: every user folder and external drive denied, then only the trial, Python and the repo's history back
    deny_all = next(x for x in lines if x.startswith("(deny file-read-data"))
    assert '(subpath "/Users")' in deny_all and '(subpath "/Volumes")' in deny_all and os.path.realpath(home) in deny_all
    allowed = next(x for x in lines if x.startswith("(allow file-read-data"))
    assert os.path.realpath(tmp_path / "repo" / ".git") in allowed and os.path.realpath(sys.prefix) in allowed
    assert lines.index(deny_all) < lines.index(allowed)                          # later rules win
    denied = next(x for x in lines if x.startswith("(deny file-read*"))
    for private in (".ssh", ".aws", "Library/Keychains"):
        assert os.path.realpath(home / private) in denied, private
    assert f'(subpath "{os.path.realpath(data)}")' in denied                     # JARVIS's data folder, even if allowed above
    assert lines[-1] == f'(allow file-read* (subpath "{os.path.realpath(root)}"))'   # the trial itself (inside data): last rule wins
    assert '(global-name "com.apple.SecurityServer")' in p and '(global-name "com.apple.coreservices.appleevents")' in p
    assert "(deny appleevent-send)" in p and '(literal "/usr/bin/osascript")' in p and '(literal "/usr/bin/open")' in p
    assert "docker" in p and f'(path-regex #"^{trial._rx(Path(os.path.realpath(home)))}/")' in p   # no sockets into home
    assert trial._q('/a "b"\\c') == '"/a \\"b\\"\\\\c"'                              # paths can't break out of the rules


def test_contained_run_stops_the_whole_group_on_the_time_limit(tmp_path):
    import time as _t
    marker = tmp_path / "grandchild-alive"
    inner = f"import time; time.sleep(6); open({str(marker)!r}, 'w').write('x')"
    script = f"import subprocess, sys, time\nsubprocess.Popen([sys.executable, '-c', {inner!r}])\ntime.sleep(60)\n"
    t0 = _t.monotonic()
    code, _out, err = trial.contained_run([sys.executable, "-c", script], cwd=tmp_path, env={"PATH": "/usr/bin:/bin"},
                                          timeout=2, watch=tmp_path)
    assert code == -9 and "over the" in err and _t.monotonic() - t0 < 20
    _t.sleep(7)
    assert not marker.exists()                                                  # the grandchild was stopped too


def test_contained_run_limits_file_size_and_the_trial_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(trial, "MAX_FILE", 1024 * 1024)
    big = tmp_path / "big.bin"
    code, _o, err = trial.contained_run([sys.executable, "-c", f"open({str(big)!r}, 'wb').write(b'x' * (4 * 1024 * 1024))"],
                                        cwd=tmp_path, env={"PATH": "/usr/bin:/bin"}, timeout=30, watch=tmp_path)
    assert code != 0 and big.stat().st_size <= 1024 * 1024                      # the file-size limit held
    filler = ("import time\n"
              f"open({str(tmp_path / 'fill.bin')!r}, 'wb').write(b'x' * 900_000)\n"
              "time.sleep(30)\n")
    code, _o, err = trial.contained_run([sys.executable, "-c", filler], cwd=tmp_path, env={"PATH": "/usr/bin:/bin"},
                                        timeout=60, watch=tmp_path, max_disk=512 * 1024)
    assert code == -9 and "trial folder passed" in err


def test_on_a_mac_the_suite_runs_inside_the_sandbox_or_not_at_all(tmp_path, monkeypatch):
    monkeypatch.setattr(trial.sys, "platform", "darwin")
    monkeypatch.setattr(trial.Path, "exists", lambda self: False if str(self) == "/usr/bin/sandbox-exec" else os.path.exists(self))
    with pytest.raises(trial.TrialError, match="sandbox"):
        trial.isolation()                                                       # never falls back to running unsandboxed
    monkeypatch.setattr(trial, "isolation", lambda: "macOS sandbox")
    argv = trial._isolated(["python", "-m", "pytest"], tmp_path, tmp_path)
    assert argv[:2] == ["/usr/bin/sandbox-exec", "-p"] and argv[3:] == ["python", "-m", "pytest"]
    assert "(deny network*)" in argv[2]


def test_the_lab_passes_the_data_folder_to_trials():
    src = (SRC / "learn" / "analysis.py").read_text()
    assert 'trial.run(args[0], args[1], work=Path(self.kernel.home) / "trials", data=Path(self.kernel.home))' in src


# ---- 3. forgetting removes ratings and their comments ---------------------------------------------------------------
def test_forget_removes_ratings_and_their_comments(make_kernel):
    k = make_kernel()
    rid = k.memory.learn_from("s", "What did the vet say about Biscuit's diet?", "Less kibble, more walks.", background=False)
    add_feedback(k, target="reply", ref=rid, rating=1, reason="Biscuit is my dog, this was spot on")
    add_feedback(k, target="reply", ref="s:1700000000", rating=-1, reason="wrong about Biscuit")   # an older-style ref
    add_feedback(k, target="reply", ref="other", rating=1, reason="good answer about tides")
    preview = k.forget("Biscuit", by="user:test", dry_run=True)
    assert preview["ratings"] == 2 and k.db.one("SELECT COUNT(*) FROM feedback")[0] == 3   # a preview deletes nothing
    k.forget("Biscuit", by="user:test", dry_run=False)
    left = [r["reason"] for r in k.db.query("SELECT reason FROM feedback")]
    assert left == ["good answer about tides"]
    raw = b"".join(p.read_bytes() for p in Path(k.home).glob("jarvis.db*"))
    assert b"Biscuit is my dog" not in raw and b"wrong about Biscuit" not in raw   # gone from the files too
    ev = [e for e in k.audit.entries(limit=30) if e["event"] == "memory.ratings_forgotten"]
    assert ev and ev[-1]["payload"]["count"] == 1 and "Biscuit" not in str(ev[-1]["payload"])


def test_deleting_one_exchange_removes_its_rating(make_kernel):
    k = make_kernel()
    rid = k.memory.learn_from("s", "Is the bakery open on Sundays?", "Yes, 9 to 1.", background=False)
    add_feedback(k, target="reply", ref=rid, rating=-1, reason="it was closed")
    k.memory.delete_record(rid, by="user:test")
    assert k.db.one("SELECT COUNT(*) FROM feedback")[0] == 0


# ---- 4. every tool action goes through the permission gateway --------------------------------------------------------
GATEWAY = SRC / "core" / "tools.py"
TOOLS = SRC / "tools"
# The one place outside the gateway that calls tool handlers: `jarvis mac check`, read-only, run by you at Terminal so
# macOS can ask its one-time permission question (see test_mac_check_calls_only_read_actions).
ALLOWED = {("cli.py", "_mac_check")}


def _tool_handler_names() -> set[str]:
    """Every tool handler method defined in the tools package (handle_calendar, handle_fs, …)."""
    names = set()
    for path in TOOLS.rglob("*.py"):
        for n in ast.walk(ast.parse(path.read_text())):
            if isinstance(n, ast.FunctionDef) and n.name.startswith("handle_"):
                names.add(n.name)
    return names


def _direct_handler_calls() -> list[tuple[str, str, int]]:
    handlers = _tool_handler_names()
    assert {"handle_calendar", "handle_music", "handle_system"} <= handlers   # the scan really sees the tools
    found = []
    for path in SRC.rglob("*.py"):
        if path == GATEWAY or TOOLS in path.parents:
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        funcs = [(n.name, n.lineno, n.end_lineno) for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        for node in ast.walk(tree):
            hit = False
            if isinstance(node, ast.Attribute) and (node.attr == "handler" or node.attr in handlers):
                hit = True
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "getattr" and len(node.args) >= 2:
                name = node.args[1]
                text = ast.unparse(name) if not isinstance(name, ast.Constant) else str(name.value)
                hit = hit or "handle_" in text
            if hit:
                owner = min((f for f in funcs if f[1] <= node.lineno <= f[2]), key=lambda f: f[2] - f[1], default=("<module>", 0, 0))
                found.append((str(path.relative_to(SRC)), owner[0], node.lineno))
    return found


def test_no_code_reaches_a_tool_without_the_permission_gateway():
    calls = _direct_handler_calls()
    unexpected = [c for c in calls if (c[0], c[1]) not in ALLOWED]
    assert unexpected == [], f"tool handlers called outside the gateway: {unexpected}"
    assert {(c[0], c[1]) for c in calls} == ALLOWED                       # the exception is still the only one
    gw = GATEWAY.read_text()
    assert "self._pool.submit(spec.handler, action, args, ctx)" in gw     # the gateway is where handlers run


def test_mac_check_calls_only_read_actions(make_kernel):
    from jarvis.core.permissions import Tier
    from jarvis.tools import default_registry
    src = (SRC / "cli.py").read_text()
    body = src.split("def _mac_check(")[1].split("\ndef ")[0]
    pairs = [(t, a) for t, a in ast.literal_eval("[" + ",".join(
        f'("{t}", "{a}")' for t, a in __import__("re").findall(r'\("\w+", "(\w+)", "(\w+)",', body)) + "]")]
    assert pairs == [("calendar", "events"), ("reminders", "list"), ("notes", "search")]
    reg = default_registry(Path(make_kernel().home) / "x", mac_runner=lambda *a: {})
    for t, a in pairs:
        assert reg.action(t, a).tier is Tier.READ, (t, a)


def test_every_server_path_that_runs_a_tool_uses_the_gateway():
    """The server, the briefing and chat lookups reach tools only through gateway.invoke (approvals, the emergency stop,
    the audit log); none of them imports a tool class."""
    for name in ("server/app.py", "proactive.py", "orchestrator/lookup.py", "core/tasks.py"):
        src = (SRC / name).read_text()
        assert "gateway.invoke(" in src, name
        for cls in ("MacTool", "FsTool", "DocumentTool", "WebTool"):
            assert f"{cls}(" not in src, (name, cls)
