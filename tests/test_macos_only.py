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
