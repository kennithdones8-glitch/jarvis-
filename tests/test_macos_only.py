"""Checks that need macOS itself (run on the owner's Mac and on GitHub's macOS runners; skipped elsewhere).
They don't need any permission prompts: scripts are compiled, not run."""

import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")


def test_mac_app_scripts_compile():
    from jarvis.tools.mac import PRELUDE, SCRIPTS
    with tempfile.TemporaryDirectory() as tmp:
        for name, body in SCRIPTS.items():
            src, out = Path(tmp) / f"{name}.js", Path(tmp) / f"{name}.scpt"
            src.write_text(PRELUDE + body)
            r = subprocess.run(["/usr/bin/osacompile", "-l", "JavaScript", "-o", str(out), str(src)],
                               capture_output=True, text=True, timeout=60)
            assert r.returncode == 0, f"{name}: {r.stderr}"


def test_launch_agent_file_is_valid(tmp_path):
    from jarvis.service import build_plist
    plist = tmp_path / "com.jarvis.dashboard.plist"
    plist.write_bytes(build_plist(home=tmp_path / "home", uv="/usr/local/bin/uv"))
    r = subprocess.run(["/usr/bin/plutil", "-lint", str(plist)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stdout + r.stderr


def test_code_sandbox_blocks_network_and_outside_writes():
    from jarvis.bench.scoring import _code_tests
    outside = Path.home() / "jarvis-sandbox-escape-test.txt"
    attempts = {
        "write": f"```python\ndef f():\n    open({str(outside)!r}, 'w').write('x')\n    return 1\n```",
        "network": "```python\nimport socket\ndef f():\n    socket.create_connection(('1.1.1.1', 80), timeout=3)\n    return 1\n```",
    }
    for what, code in attempts.items():
        ok, detail = _code_tests({"answer": code}, {"function": "f", "cases": [[[], 1]]}, run_code=True)
        assert ok is False, f"the sandbox allowed a {what}: {detail}"
    assert not outside.exists()
    ok, _ = _code_tests({"answer": "```python\ndef f():\n    return 1\n```"}, {"function": "f", "cases": [[[], 1]]},
                        run_code=True)
    assert ok is True  # ordinary code still runs


def test_chat_code_self_test_sandbox():
    """Model-written code in the coding self-test: it runs, but can't read the owner's files, reach the network,
    write outside its temp folder, or start other programs."""
    from jarvis.codecheck import run_cases
    assert run_cases("def add(a, b):\n    return a + b", [{"call": "add(2, 3)", "expected": "5"}]).all_passed
    secret = Path.home() / "jarvis-sandbox-read-test.txt"
    secret.write_text("private")
    outside = Path.home() / "jarvis-sandbox-write-test.txt"
    try:
        attempts = {
            "read a file in the home folder": f"def go():\n    return open({str(secret)!r}).read()",
            "network": "def go():\n    import socket\n    socket.create_connection(('1.1.1.1', 80), timeout=3)\n    return 'private'",
            "write outside": f"def go():\n    open({str(outside)!r}, 'w').write('x')\n    return 'private'",
            "start a program": "def go():\n    import subprocess\n    return subprocess.run(['/bin/echo', 'private'], "
                               "capture_output=True, text=True).stdout.strip()",
        }
        for what, code in attempts.items():
            run = run_cases(code, [{"call": "go()", "expected": "'private'"}])
            assert run.passed == 0, f"the sandbox allowed: {what}"
        assert not outside.exists()
    finally:
        secret.unlink(missing_ok=True)
        outside.unlink(missing_ok=True)


def test_launcher_app_compiles_and_holds_no_secret(tmp_path):
    """`jarvis app install` with Apple's real osacompile: a valid applet, marked as ours, no dashboard link inside."""
    from jarvis import launcher
    from jarvis.service import dashboard_token
    home = tmp_path / "home"
    home.mkdir()
    token = dashboard_token(home)
    app = launcher.install(home, custom_home=True, dest_dir=tmp_path / "Apps")
    assert app.name == "JARVIS.app" and launcher.is_ours(app)
    assert (app / "Contents" / "Info.plist").is_file() and (app / "Contents" / "Resources" / "Scripts" / "main.scpt").is_file()
    src = subprocess.run(["/usr/bin/osadecompile", str(app / "Contents" / "Resources" / "Scripts" / "main.scpt")],
                         capture_output=True, text=True, timeout=60)
    assert src.returncode == 0 and "open" in src.stdout and str(home) in src.stdout
    assert token not in src.stdout and not any(token in p.read_bytes().decode("latin-1") for p in app.rglob("*") if p.is_file())
    assert launcher.uninstall(tmp_path / "Apps") and not app.exists()


def test_trial_sandbox_escape_attempts_all_fail(tmp_path):
    """The level-6 trial sandbox, for real: a program inside it tries to get out every way the 4.0 audit listed."""
    import json
    import os
    import socket
    import threading

    from jarvis.learn import trial

    root = Path(os.path.realpath(tmp_path)) / "trial"
    root.mkdir()
    (root / "inside.txt").write_text("ok")
    canary = Path.home() / "jarvis-trial-canary.txt"
    canary.write_text("private")
    outside = Path.home() / "jarvis-trial-escape-write.txt"
    sock_path = Path.home() / ".jarvis-trial-test.sock"
    sock_path.unlink(missing_ok=True)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(sock_path))
    server.listen(1)
    threading.Thread(target=lambda: server.accept(), daemon=True).start()
    probe = f"""
import json, socket, subprocess
out = {{}}
def attempt(name, fn):
    try:
        fn(); out[name] = "allowed"
    except Exception as e:
        out[name] = "blocked: " + type(e).__name__
attempt("read home file", lambda: open({str(canary)!r}).read())
attempt("read inside", lambda: open({str(root / "inside.txt")!r}).read())
attempt("write outside", lambda: open({str(outside)!r}, "w").write("x"))
attempt("internet", lambda: socket.create_connection(("1.1.1.1", 80), timeout=3))
def local():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); s.listen(1)
    socket.create_connection(s.getsockname(), timeout=3).close()
attempt("localhost", local)
def home_socket():
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.settimeout(3); s.connect({str(sock_path)!r})
attempt("socket in home", home_socket)
def osa():
    r = subprocess.run(["/usr/bin/osascript", "-e", "return 1"], capture_output=True, timeout=10)
    if r.returncode != 0: raise PermissionError(r.stderr.decode()[:80])
attempt("osascript", osa)
def echo():
    r = subprocess.run(["/bin/echo", "hi"], capture_output=True, timeout=10)
    if r.returncode != 0: raise RuntimeError("echo failed")
attempt("ordinary program", echo)
print(json.dumps(out))
"""
    try:
        argv = trial._isolated([sys.executable, "-I", "-c", probe], root, tmp_path / "data")
        code, out, err = trial.contained_run(argv, cwd=root, env={"PATH": "/usr/bin:/bin", "HOME": str(root)},
                                             timeout=60, watch=root)
        result = json.loads(out.strip().splitlines()[-1]) if out.strip() else {"error": err[-500:]}
    finally:
        server.close()
        sock_path.unlink(missing_ok=True)
        canary.unlink(missing_ok=True)
    assert result.get("read inside") == "allowed" and result.get("localhost") == "allowed", result
    assert result.get("ordinary program") == "allowed", result
    for what in ("read home file", "write outside", "internet", "socket in home", "osascript"):
        assert result.get(what, "").startswith("blocked"), (what, result)
    assert not outside.exists()
