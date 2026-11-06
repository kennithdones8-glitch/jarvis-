"""Phase 2 dashboard: the holographic core, its truthful states and evolution, adaptive layout, the eight command
systems, and the comfort/performance switches. Behaviour was also checked in a headless browser (desktop, laptop,
iPhone size, reduced motion)."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from test_dashboard import call

STATIC = Path(__file__).resolve().parents[1] / "src" / "jarvis" / "server" / "static"
JS = (STATIC / "app.js").read_text()
AV = (STATIC / "avatar.js").read_text()
AVCSS = (STATIC / "avatar.css").read_text()


def fn(js, name):
    return re.search(rf"function {name}\(.*?\n\}}\n", js, re.S).group(0)


def test_avatar_files_are_served_and_loaded_after_the_page(dash):
    d, _, _ = dash
    html = call(d, "/")[2].decode()
    assert '<script src="/static/avatar.js" defer></script>' in html and 'href="/static/avatar.css"' in html
    assert html.index("avatar.js") < html.index("app.js")
    for path, ctype in (("/static/avatar.js", "text/javascript"), ("/static/avatar.css", "text/css")):
        status, headers, _ = call(d, path)
        assert status == 200 and headers.get("Content-Type", "").startswith(ctype), path
    assert "requestIdleCallback" in JS and "JarvisAvatar.mount(" in JS  # mounted once the page is usable


def test_avatar_is_decoration_only():
    for forbidden in ("fetch(", "XMLHttpRequest", "api(", "localStorage.setItem", "innerHTML", "eval("):
        assert forbidden not in AV, forbidden
    assert 'parseFromString(' in AV and '"image/svg+xml"' in AV  # parts are static SVG, parsed as SVG


def test_all_thirteen_states_and_replaceable_parts():
    states = json.loads(re.search(r"const STATES = (\[.*?\]);", AV, re.S).group(1).replace("\n", " "))
    assert states == ["idle", "listening", "understanding", "planning", "researching", "reasoning", "writing", "coding",
                      "verifying", "approval", "executing", "completed", "error"]
    for part in ("helmet", "visor", "face"):
        assert f'["{part}", 1,' in AV, part
    assert "registerPart" in AV and "function registerPart(name, markup)" in AV


AVATAR_HARNESS = r"""
const ui = { convo: [], stage: null };
const core = { dataset: {} };
const $ = () => core;
%s
const out = {};
const run = (name, s, setup = () => {}) => { setup(); out[name] = avatarState(s); core.dataset = {}; ui.stage = null; ui.convo = []; };
run("idle", { core: "online" });
run("connecting", { core: "connecting" });
run("decision", { core: "attention" });
run("blocked", { core: "blocked" });
run("stopped", { core: "stopped" });
run("offline", { core: "offline" });
run("no models", { core: "degraded" });
run("executing", { core: "executing", kicker: "Executing" });
run("task verifying", { core: "executing", kicker: "Verifying" });
run("recovering", { core: "recovering" });
run("planning", { core: "planning" });
run("queued", { core: "queued" });
run("researching", { core: "researching" });
run("understanding", { core: "thinking" }, () => { ui.stage = { stage: "understanding" }; });
run("context", { core: "thinking" }, () => { ui.stage = { stage: "context" }; });
run("lookup", { core: "thinking" }, () => { ui.stage = { stage: "lookup" }; });
run("waiting for words", { core: "thinking" }, () => { ui.stage = { stage: "generating" }; ui.convo = [{ live: true, text: "" }]; });
run("words arriving", { core: "thinking" }, () => { ui.stage = { stage: "generating" }; ui.convo = [{ live: true, text: "Tides" }]; });
run("code arriving", { core: "thinking" }, () => { ui.stage = { stage: "generating" }; ui.convo = [{ live: true, text: "```python" }]; });
run("answer check", { core: "thinking" }, () => { ui.stage = { stage: "checking" }; });
run("code test", { core: "thinking" }, () => { ui.stage = { stage: "checking", code_test: true }; });
run("listening", { core: "online" }, () => { core.dataset.listening = "1"; });
run("speaking", { core: "online" }, () => { core.dataset.speaking = "1"; });
run("finished", { core: "online" }, () => { core.dataset.flash = "done"; });
run("failed", { core: "online" }, () => { core.dataset.flash = "failed"; });
run("decision beats speaking", { core: "attention" }, () => { core.dataset.speaking = "1"; });
console.log(JSON.stringify(out));
"""


def test_every_avatar_state_comes_from_a_real_signal(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    (tmp_path / "a.js").write_text(AVATAR_HARNESS % fn(JS, "avatarState"))
    got = json.loads(subprocess.run([node, str(tmp_path / "a.js")], capture_output=True, text=True, check=True).stdout)
    assert got == {
        "idle": "idle", "connecting": "idle", "decision": "approval", "blocked": "approval", "stopped": "error",
        "offline": "error", "no models": "error", "executing": "executing", "task verifying": "verifying",
        "recovering": "verifying", "planning": "planning", "queued": "planning", "researching": "researching",
        "understanding": "understanding", "context": "understanding", "lookup": "researching",
        "waiting for words": "reasoning", "words arriving": "writing", "code arriving": "coding",
        "answer check": "verifying", "code test": "coding", "listening": "listening", "speaking": "writing",
        "finished": "completed", "failed": "error", "decision beats speaking": "approval",
    }


def test_evolution_comes_from_the_server_only():
    head = fn(JS, "renderHead")
    assert "JarvisAvatar.setTier(d.evolution.tier)" in head
    assert JS.count("setTier(") == 1  # nothing else in the page can award a tier


def test_comfort_and_performance_switches():
    reduced = AVCSS.split("@media (prefers-reduced-motion: reduce) {")[1].split("\n}\n")[0]
    assert ".avatar, .avatar * { animation: none !important; }" in reduced and ".avatar-fx { display: none; }" in reduced
    assert ':root[data-fx="off"] .avatar, :root[data-fx="off"] .avatar * { animation: none !important; }' in AVCSS
    assert ".page-hidden .avatar, .page-hidden .avatar * { animation-play-state: paused !important; }" in AVCSS
    # the canvas loop runs only on screen, page visible, Effects Full, no reduced motion; capped at ~30 fps
    assert 'av.visible && !document.hidden && fxLevel() === "full"' in AV and "t - av.last < 33" in AV
    assert 'reduced ? "off" : fx' in AV and "IntersectionObserver" in AV
    # only cheap properties animate
    for kf in re.findall(r"@keyframes [\w-]+ \{(.*?)\}\n", AVCSS, re.S):
        props = set(re.findall(r"([a-z-]+):", kf))
        assert props <= {"transform", "opacity", "stroke-dashoffset"}, props
    assert 'fx: [["full", "Full"], ["reduced", "Reduced"], ["off", "Off (lowest power)"]]' in JS


def test_adaptive_layout_follows_real_activity():
    act = fn(JS, "activityOf")
    for activity in ('"voice"', '"research"', '"mission"', '"conversation"', '"idle"'):
        assert activity in act, activity
    for activity in ("conversation", "research", "mission", "voice"):
        assert f'body[data-activity="{activity}"]' in AVCSS or f'[data-activity="{activity}"]' in AVCSS, activity


def test_eight_command_systems_from_live_state(dash):
    d, _, _ = dash
    html = call(d, "/")[2].decode()
    assert 'href="#/command" data-view="command"' in html and 'id="sysbar"' in html and 'id="command"' in html
    assert 'href="#/command"' in html.split('role="menu"')[1].split("</div>")[0]  # phones: More menu
    systems = fn(JS, "systems")
    ids = re.findall(r'\{ id: "(\w+)", short:', systems)
    assert ids == ["health", "intelligence", "missions", "security", "communications", "research", "personal", "diagnostics"]
    assert "api(" not in systems and "call(" not in systems and "fetch(" not in systems  # reads the snapshot only
    assert "unavailable" in systems and "not connected (no integration exists)" in systems  # honest gaps
    assert "innerHTML" not in fn(JS, "renderCommand") and "innerHTML" not in fn(JS, "renderSysbar")


def test_phone_layout_rules():
    css = (STATIC / "app.css").read_text()
    phone = "".join(b.split("\n}\n")[0] for b in css.split("@media (max-width: 760px) {")[1:])
    assert ".sidenav > a.nav-command { display: none; }" in phone  # the tab bar keeps five
    assert ".cmd .intel-cycle:not([hidden]) { display: inline-flex;" in phone and "grid-row: 1;" in phone  # in the tabs row
    assert ".cmd .intel-modes, .cmd .intel-modes:not([hidden]) { display: none; }" in phone  # no extra row
    assert ".sys-chip { grid-template-columns: auto 1fr; padding: 6px; }" in phone
    assert "min-height: 44px" in css.split(".sys-chip {")[1].split("}")[0]
