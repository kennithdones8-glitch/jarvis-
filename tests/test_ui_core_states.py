"""Reactor states: the page's own situation() run in Node against every scenario (skipped without Node)."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "src" / "jarvis" / "server" / "static"
JS = (STATIC / "app.js").read_text()
CSS = (STATIC / "app.css").read_text()

HARNESS = r"""
const ui = { online: true, chatBusy: false, chatEndpoint: null };
const greeting = () => "Good evening";
%s
%s
%s
const task = (state, extra = {}) => ({ id: "t" + state, goal: "G", state, steps: [{ state: "started", description: "s" }], next_action: null, ...extra });
const models = { providers: [{ configured: ["m"], available: ["m"] }] };
const base = { approvals: [], tasks: [], jobs: [], models, emergency_stop: null };
const out = {};
const run = (name, d, setup = () => {}) => { setup(); out[name] = situation(d).core; ui.chatBusy = false; ui.online = true; };
run("ready", base);
run("decision", { ...base, approvals: [{ summary: "Write x — y" }] });
run("blocked", { ...base, tasks: [task("blocked")] });
run("running", { ...base, tasks: [task("running")] });
run("verifying", { ...base, tasks: [task("verifying")] });
run("recovering", { ...base, tasks: [task("recovering")] });
run("queued", { ...base, tasks: [task("queued")] });
run("paused", { ...base, tasks: [task("paused")] });
run("planning", { ...base, jobs: [{ state: "planning", request: "r", elapsed: 3 }] });
run("no models", { ...base, models: { providers: [{ configured: ["m"], available: [] }] } });
run("stopped", { ...base, emergency_stop: { reason: "r" } });
run("chat", base, () => { ui.chatBusy = true; ui.chatEndpoint = "/api/chat"; });
run("research", base, () => { ui.chatBusy = true; ui.chatEndpoint = "/api/research"; });
run("offline", base, () => { ui.online = false; });
run("first load", null);
run("decision beats running and chat", { ...base, approvals: [{ summary: "x — y" }], tasks: [task("running")] }, () => { ui.chatBusy = true; });
run("running beats chat", { ...base, tasks: [task("running")] }, () => { ui.chatBusy = true; });
run("running beats queued", { ...base, tasks: [task("queued"), task("running")] });
run("stop beats everything", { ...base, emergency_stop: { reason: "r" }, approvals: [{ summary: "x — y" }] });
console.log(JSON.stringify(out));
"""


def _piece(pattern):
    return re.search(pattern, JS, re.S).group(0)


def test_every_scenario_maps_to_its_own_truthful_state(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    src = HARNESS % (_piece(r"const plural = [^\n]+"), _piece(r"const ACTIVE = [^\n]+"),
                     _piece(r"function situation\(d\) \{.*?\n\}\n"))
    (tmp_path / "h.js").write_text(src)
    got = json.loads(subprocess.run([node, str(tmp_path / "h.js")], capture_output=True, text=True, check=True).stdout)
    assert got == {
        "ready": "online", "decision": "attention", "blocked": "blocked", "running": "executing",
        "verifying": "executing", "recovering": "recovering", "queued": "queued", "paused": "online",
        "planning": "planning", "no models": "degraded", "stopped": "stopped", "chat": "thinking",
        "research": "researching", "offline": "offline", "first load": "connecting",
        "decision beats running and chat": "attention", "running beats chat": "executing",
        "stop beats everything": "stopped", "running beats queued": "executing",
    }


def test_every_state_has_a_look_and_motion_stops_when_asked():
    for state in ("connecting", "planning", "researching", "recovering", "blocked", "degraded"):
        assert f'.core[data-state="{state}"]' in CSS or f'.core[data-state="{state}"])' in CSS, state
    for overlay in ("data-listening", "data-speaking", 'data-flash="done"', 'data-flash="failed"'):
        assert f".core[{overlay}]" in CSS, overlay
    reduced = CSS.split("Stage 3: reactor states")[1]
    assert "@media (prefers-reduced-motion: reduce)" in reduced and ".core-wrap::before { transition: none; }" in reduced


def test_listening_speaking_and_flash_follow_real_events():
    assert '$("#core").dataset.listening = "1";' in JS and 'delete $("#core").dataset.listening;' in JS
    assert 'u.onstart = () => { core.dataset.speaking = "1"; };' in JS and "u.onend = u.onerror" in JS
    flash = JS.split("function flashOnFinish(d) {")[1].split("\n}\n")[0]
    assert "if (!before) return;" in flash  # never on first load
    assert "setTimeout(() => { delete core.dataset.flash; }, 4000)" in flash
