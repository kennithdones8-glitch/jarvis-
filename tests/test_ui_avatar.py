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
                      "verifying", "approval", "executing", "completed", "error",
                      "speaking", "warning", "recovery", "halted", "unknown", "learning", "experimenting", "analyzing", "disagreeing"]
    for part in ("helmet", "visor", "face"):
        assert f'["{part}", 1,' in AV, part
    assert "registerPart" in AV and "function registerPart(name, markup)" in AV


AVATAR_HARNESS = r"""
const ui = { convo: [], stage: null };
const window = {};   // no avatar-events.js here: refusals are tested in test_avatar25.py
const core = { dataset: {} };
const $ = () => core;
%s
%s
%s
const out = {};
const ok = { health: { ok: true, items: [{ name: "Database", ok: true }] }, audit_chain: { ok: true } };
const run = (name, s, setup = () => {}, d = ok) => { setup(); out[name] = avatarState(s, d); core.dataset = {}; ui.stage = null; ui.convo = [];
  ui.typingAt = 0; ui.reconnectedAt = 0; ui.chatBusy = false; };
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
run("microphone", { core: "online" }, () => { core.dataset.listening = "1"; });
run("typing", { core: "online" }, () => { ui.typingAt = Date.now(); });
run("typed a while ago", { core: "online" }, () => { ui.typingAt = Date.now() - 10000; });
run("typing while a reply streams", { core: "online" }, () => { ui.typingAt = Date.now(); ui.chatBusy = true; });
run("speaking", { core: "online" }, () => { core.dataset.speaking = "1"; });
run("finished", { core: "online" }, () => { core.dataset.flash = "done"; });
run("failed", { core: "online" }, () => { core.dataset.flash = "failed"; });
run("reconnected", { core: "online" }, () => { ui.reconnectedAt = Date.now(); });
run("health problem", { core: "online", warn: true }, () => {}, { health: { ok: false, items: [{ name: "Backups", ok: false }] }, audit_chain: { ok: true } });
run("database failing", { core: "online", warn: true }, () => {}, { health: { ok: false, items: [{ name: "Database", ok: false }] }, audit_chain: { ok: true } });
run("audit chain broken", { core: "online" }, () => {}, { health: { ok: true, items: [] }, audit_chain: { ok: false } });
run("no data", { core: "online" }, () => {}, null);
run("decision beats speaking", { core: "attention" }, () => { core.dataset.speaking = "1"; });
run("mission beats typing", { core: "executing", kicker: "Executing" }, () => { ui.typingAt = Date.now(); });
run("typing beats a standing warning", { core: "online", warn: true }, () => { ui.typingAt = Date.now(); }, { health: { ok: false, items: [{ name: "Backups", ok: false }] }, audit_chain: { ok: true } });
run("a critical problem beats typing", { core: "online", warn: true }, () => { ui.typingAt = Date.now(); }, { health: { ok: false, items: [{ name: "Database", ok: false }] }, audit_chain: { ok: true } });
console.log(JSON.stringify(out));
"""


def test_every_avatar_state_comes_from_a_real_signal(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    (tmp_path / "a.js").write_text(AVATAR_HARNESS % (fn(JS, "avatarState"), fn(JS, "criticalProblem"), fn(JS, "refusedJustNow")))
    got = json.loads(subprocess.run([node, str(tmp_path / "a.js")], capture_output=True, text=True, check=True).stdout)
    assert got == {
        "idle": "idle", "connecting": "unknown", "decision": "approval", "blocked": "approval", "stopped": "halted",
        "offline": "error", "no models": "warning", "executing": "executing", "task verifying": "verifying",
        "recovering": "recovery", "planning": "planning", "queued": "idle", "researching": "researching",
        "understanding": "understanding", "context": "understanding", "lookup": "researching",
        "waiting for words": "reasoning", "words arriving": "writing", "code arriving": "coding",
        "answer check": "verifying", "code test": "coding", "microphone": "listening", "typing": "listening",
        "typed a while ago": "idle", "typing while a reply streams": "idle", "speaking": "speaking",
        "finished": "completed", "failed": "error", "reconnected": "recovery",
        "health problem": "warning", "database failing": "error", "audit chain broken": "error", "no data": "idle",
        "decision beats speaking": "approval", "mission beats typing": "executing",
        "typing beats a standing warning": "listening", "a critical problem beats typing": "error",
    }
    # red ("error") only from real critical events: a failed task, a lost connection, a failing database/audit log
    assert {k for k, v in got.items() if v == "error"} == {"offline", "failed", "database failing", "audit chain broken",
                                                           "a critical problem beats typing"}


def test_evolution_comes_from_the_server_only():
    head = fn(JS, "renderHead")
    assert "JarvisAvatar.setTier(displayStage(d.evolution))" in head
    assert JS.count("setTier(") == 1  # nothing else in the page can award a stage
    # a device may only show a LOWER stage than the server's
    assert "return cap ? Math.min(cap, evo.tier) : evo.tier;" in fn(JS, "displayStage")


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
    assert 'fx: [["full", "Normal"], ["reduced", "Low performance"], ["off", "Reduced motion"]]' in JS


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


# ---- 3D core (Three.js) -----------------------------------------------------------------------------------------
import hashlib  # noqa: E402

# the 3D renderer is split into modules; checks read them as one source
AV3 = "\n".join((STATIC / f).read_text() for f in ("avatar3d-shaders.js", "avatar3d-geometry.js", "avatar3d-reactor.js",
                                                    "avatar3d-neural.js", "avatar3d-particles.js", "avatar3d-environment.js",
                                                    "avatar3d-projections.js", "avatar3d.js"))
THREE_SHA256 = "3e690ac7d180b0aadf0891bea39eec643e29e2d3e75c99b18689518665f69ba6"  # three@0.160.0 build/three.module.min.js


def test_three_is_the_exact_pinned_build_and_served_from_this_mac(dash):
    path = STATIC / "vendor" / "three.module.min.js"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == THREE_SHA256
    assert "MIT License" in (STATIC / "vendor" / "three.LICENSE.txt").read_text()
    d, _, _ = dash
    status, headers, body = call(d, "/static/vendor/three.module.min.js")
    assert status == 200 and headers["Content-Type"].startswith("text/javascript") and hashlib.sha256(body).hexdigest() == THREE_SHA256
    assert call(d, "/static/vendor/three.LICENSE.txt")[0] == 404  # only the one file is served
    for f in ("avatar3d.js", "avatar3d-shaders.js", "avatar3d-geometry.js", "avatar3d-reactor.js", "avatar3d-neural.js", "avatar3d-particles.js", "avatar3d-environment.js", "avatar3d-projections.js", "avatar3d-worker.js", "avatar-state.js", "avatar3d-camera.js", "avatar-presets.js", "avatar-events.js", "avatar-sound.js", "avatar3d-transform.js"):
        assert call(d, f"/static/{f}")[0] == 200
    csp = call(d, "/")[1]["Content-Security-Policy"]
    assert "script-src 'self'" in csp and "connect-src 'self'" in csp and "unsafe" not in csp  # unchanged


def test_3d_core_is_decoration_only_and_local():
    assert 'import * as THREE from "/static/vendor/three.module.min.js";' in AV3
    for forbidden in ("fetch(", "XMLHttpRequest", "localStorage", "innerHTML", "eval(", "http://", "https://", "Loader("):
        assert forbidden not in AV3, forbidden
    assert set(re.findall(r"^\s+(\w+):\s+\{ tint:", AV3, re.M)) == set(json.loads(re.search(r"const STATES = (\[.*?\]);", AV, re.S).group(1)))


def test_3d_core_falls_back_to_2d_and_respects_the_modes():
    assert 'import("/static/avatar3d.js")' in AV and "if (!three) { av.status = \"2d\"; return; }" in AV  # failure leaves the 2D core
    assert 'av.wrap.classList.remove("has-3d")' in AV  # a lost GPU context goes back to 2D
    assert "av.three.setMode(av.lastMode)" in AV and "av.three.setState(state)" in AV and "av.three.setTier(tier)" in AV
    # Normal: capped frame rate; other modes draw only when something changes; nothing while hidden or off screen
    assert "1000 / 30" in AV3 and "1000 / 24" in AV3 and 'const moving = mode === "full";' in AV3
    assert "if (!visible || document.hidden || lost) return;" in AV3 and "IntersectionObserver" in AV3
    assert "Math.min(1.5, window.devicePixelRatio || 1)" in AV3
    css = (STATIC / "avatar.css").read_text()
    assert ".core-wrap.has-3d .avatar, .core-wrap.has-3d .avatar-fx, .core-wrap.has-3d .avatar-lines { display: none; }" in css


def test_background_motion_stops_when_asked():
    css = (STATIC / "app.css").read_text()
    assert ':root[data-fx="reduced"] .env *, :root[data-fx="off"] .env * { animation: none !important; }' in css
    assert "@media (prefers-reduced-motion: reduce) { .env * { animation: none !important; } .env-dust { display: none; } }" in css
    env = css.split("Theme v3")[1]
    for kf in re.findall(r"@keyframes env-[\w-]+ \{(.*?)\} \}", env, re.S):
        assert set(re.findall(r"([a-z-]+):", kf)) <= {"transform", "opacity"}


# ---- Avatar 2.0 ----------------------------------------------------------------------------------------------------
APPCSS = (STATIC / "app.css").read_text()
HTML = (STATIC / "index.html").read_text()


def test_the_head_is_a_faceless_helmet_with_sensors_driven_by_real_signals():
    # owner's brief (Avatar 3D): an adaptive faceless helmet, not a human face
    assert "function helmet(d, x, ax, y, z) {" in AV3 and "function face(" not in AV3
    for layer in ("centre keel (above the visor only)", "visor recess", "upper visor rim", "lower visor rim"):
        assert f"// {layer}" in AV3, layer
    for human in ("nose", "lip", "mouth", "cheekbone", "jaw line", "eye socket"):
        assert human not in AV3.split("function helmet(")[1].split("export function sdHuman")[0].lower(), human
    assert "for (int i = -4; i <= 4; i++) {" in AV3                                          # the sensor array in the visor
    assert "(0.65 + 0.35 * ph * clamp(uThink, 0.0, 1.0))" in AV3 and "FACE.uThink.value = cur.neural;" in AV3   # thinking: real level
    assert "fres *= 1.0 - 0.7 * faceZone;" in AV3 and "(1.0 - faceZone);   // no panel grid across the face" in AV3
    assert "mesh.renderOrder = -1;" in AV3                                                 # plates never darken the light in front of them
    assert "meshFigure(phone ? 0.018 : 0.013, [-0.34, 4.3, -0.44]" in AV3                  # the head is meshed finer
    assert "FACE.uEyeOpen.value = shut * narrow;" in AV3                                    # shutter (blinks, narrowing) from the state
    assert 'FACE.uEyeScan.value += ((state === "researching" || state === "verifying" ? 1 : 0)' in AV3   # internal scanner
    assert "FACE.uSpeech.value = Math.min(1, Math.max(speech, voice * 0.8));" in AV3                               # light pulse from real word boundaries only


def test_every_state_has_a_3d_look_with_the_engine_parameters():
    looks = dict(re.findall(r"^\s+(\w+):\s+(\{ tint:.*\}),$", AV3, re.M))
    assert set(looks) == set(json.loads(re.search(r"const STATES = (\[.*?\]);", AV, re.S).group(1)))
    for name, body in looks.items():
        for key in ("eyes", "reactor", "neural", "data", "sweep", "discharge", "beat", "head", "flicker"):
            assert f"{key}:" in body, (name, key)
    assert '"#ff4b4b"' in looks["error"] and looks["error"].count("#ff4b4b") == 1
    assert not any("#ff4b4b" in b for n, b in looks.items() if n != "error")  # red is for genuine critical alerts only
    assert "1 - Math.exp(-dt * 2.2)" in AV3  # states blend over ~0.6–1 s, never switch abruptly


def test_speech_pulses_come_only_from_real_word_boundaries():
    assert 'u.onboundary = (e) => { if (e.name === "word" && window.JarvisAvatar) JarvisAvatar.pulse(1); };' in JS
    assert JS.count("JarvisAvatar.pulse(") == 1


def test_typing_counts_as_listening_only_while_you_type():
    assert '$("#cmd").addEventListener("input", () => { ui.typingAt = Date.now(); renderHead(ui.data); });' in JS
    assert "Date.now() - ui.typingAt < 2500 && !ui.chatBusy" in fn(JS, "avatarState")


def test_projection_focus_keeps_the_emergency_stop_and_closes_with_escape():
    assert 'id="projpanel"' in HTML and 'id="projexit"' in HTML and 'id="projback"' in HTML and 'id="avtask"' in HTML
    assert "body.projection .top { position: relative; z-index: 70; }" in (STATIC / "avatar.css").read_text()
    esc = JS.split('document.addEventListener("keydown", (e) => { if (e.key === "Escape")')[1].split("\n")[0]
    assert "if (!stopInspect()) closeProjection();" in esc   # Esc leaves inspection first, then the focus view
    assert '$("#projback").addEventListener("click", closeProjection);' in JS
    assert "style=" not in HTML


def test_every_interactive_avatar_element_does_something_real():
    assert "JarvisAvatar.onFocus = openProjection;" in JS
    assert 'JarvisAvatar.onSystem = (id) => { closeProjection(); ui.ccOpen = new Set([id]); ui.ccKey = ""; location.hash = "#/command"; };' in JS
    assert 'wrap.setAttribute("role", "button");' in AV and 'wrap.setAttribute("tabindex", "0");' in AV  # keyboard reachable
    assert "JarvisAvatar.setSystems(list.map(" in fn(JS, "renderSysbar")  # satellites carry the real system status
    work = fn(JS, "liveWork")
    assert "api(" not in work and "fetch(" not in work and "d.tasks.find" in work  # holograms show real work only


def test_projection_intensity_and_displayed_stage_are_per_device_settings():
    assert 'projection: [["subtle", "Subtle"], ["standard", "Standard"], ["vivid", "Vivid"]]' in JS
    assert "root.dataset.projection = d.projection;" in JS
    assert 'const INTENSITY = { subtle: 0.75, standard: 1, vivid: 1.3 };' in AV
    assert 'localStorage.setItem(EVO_CAP_KEY, String(v))' in JS and "[1, 2, 3, 4, 5].filter((n) => n <= evo.tier)" in JS


def test_idle_liveliness_is_limited_to_rest_and_never_fakes_activity():
    # glances happen only in the resting personality (avatar-events.js), and stop the moment real work starts
    assert 'if (pers ? pers.glances : target.head === "aware") {' in AV3 and "} else glance = null;" in AV3
    events = (STATIC / "avatar-events.js").read_text()
    assert re.findall(r"(\w+): +\{ head: \"\w+\", gesture: \"\w+\", glances: true", events) == ["idle"]
    assert "glanceAt = t + 6 + Math.random() * 5" in AV3          # every ~6–11 s, held ~1.6–2.6 s
    assert 'const shut = headMode() === "still" ? 1 :' in AV3      # halted/unknown/error: no blinking
    # every state has a reactor pattern, from a fixed set
    pats = set(re.findall(r'rpat: "(\w+)"', AV3))
    assert pats <= {"calm", "spin", "scan", "beat", "surge", "stutter", "still"}
    assert len(re.findall(r'rpat: "\w+"', AV3)) == len(json.loads(re.search(r"const STATES = (\[.*?\]);", AV, re.S).group(1)))


def test_bloom_and_surface_detail_are_local_and_fail_safe():
    # post-processing is our own small pipeline (no extra library) and the projection still draws without it
    assert "} catch (e) { return null; }   // no post-processing: draw directly" in AV3
    assert "if (post) post.begin(); else renderer.clear();" in AV3 and "if (post) post.end(t, intensity);" in AV3
    imports = set(re.findall(r'from "([^"]+)";', AV3))   # only Three.js (served locally) and our own modules
    assert imports <= {"/static/vendor/three.module.min.js", "/static/avatar3d-shaders.js", "/static/avatar3d-geometry.js",
                       "/static/avatar3d-reactor.js", "/static/avatar3d-neural.js", "/static/avatar3d-particles.js",
                       "/static/avatar3d-environment.js", "/static/avatar3d-projections.js", "/static/avatar3d-camera.js", "/static/avatar3d-transform.js"}
    assert "import(" not in AV3
    # surfaces turned away are dimmer (depth), and armour gets panel seams; glowing parts stay smooth
    assert "a *= gl_FrontFacing ? 1.0 : 0.38;" in AV3
    assert "uPanel: { value: o.panel ?? ((o.core ?? 0.035) < 0.2 && !o.flow && !o.self ? 0.85 : 0) }" in AV3
    # composite output stays valid for a transparent canvas (colour never exceeds alpha)
    assert "gl_FragColor = vec4(min(col, vec3(a)), a);" in AV3


def test_assembly_runs_once_per_session_is_skippable_and_never_with_reduced_motion():
    assert 'boot = fxLevel() === "full" && !sessionStorage.getItem("jarvis-booted");' in AV   # Normal mode only
    assert 'sessionStorage.setItem("jarvis-booted", "1")' in AV
    assert 'document.addEventListener("keydown", skip, true); document.addEventListener("pointerdown", skip, true);' in AV
    assert 'let boot = opts.boot && mode === "full" ?' in AV3 and "skipBoot()" in AV3
    css = (STATIC / "avatar.css").read_text()
    assert "body.booting .hud .panel, body.booting .hud > .center > * { animation: none; }" in css   # reduced motion
    assert "body.booting .top" not in css and "#estop" not in css   # the top bar and Emergency stop never wait


def test_data_aura_shows_only_real_values():
    aura = fn(JS, "auraValues")
    assert "t.cpu && t.cpu.available ? Math.min(1, t.cpu.load_per_core / 1.5) : null" in aura
    assert "t.memory && t.memory.available ? t.memory.used_pct / 100 : null" in aura
    assert "d.approvals.length" in aura and "ACTIVE.includes(x.state)" in aura
    assert 'const show = typeof v === "number" && isFinite(v);' in AV3 and "a.ring.visible = show;" in AV3   # unavailable → hidden
    assert "if (changed) kick();" in AV3   # unchanged values cause no redraw (Low performance stays idle)


def test_thought_constellation_counts_real_stages_and_surge_needs_a_real_completion():
    assert "JarvisAvatar.setThought(new Set(live.activity.map((a) => a.stage)).size, true);" in JS
    assert "JarvisAvatar.setThought(0, false);" in JS
    assert 'if (effect(state) === "surge") { burst(); surge(); }' in AV        # completed comes only from a finished task
    events = (STATIC / "avatar-events.js").read_text()
    assert [ln.split(":")[0].strip() for ln in events.splitlines() if 'effect: "surge"' in ln] == ["completed"]
    surge = AV.split("  function surge() {")[1].split("\n  }\n")[0]
    assert 'if (fxLevel() !== "full" || !av.wrap) return;' in surge   # never in Low performance / Reduced motion
    assert "@media (prefers-reduced-motion: reduce) { .surge { display: none; }" in (STATIC / "avatar.css").read_text()


def test_figure_is_gold_light_with_sparkles_kept_out_of_the_reflection():
    assert "const metals = [];" in AV3 and "MeshStandardMaterial" not in AV3   # no bulky lit-metal robot plates (owner's feedback)
    assert 'uAccent: { value: new THREE.Color("#fff1cf") }' in AV3            # gold-white highlight (brief: gold, gold-white, amber)
    assert "3dffb8" not in AV3 and "33e6ad" not in AV3                       # no teal left in the projection
    assert "vec3 uTint = mix(uTint0, uAccent, vAccent);" in AV3
    assert "shed.visible = moving;" in AV3                                    # sparkles only while motion is allowed
    hidden = AV3.split("const hidden = [")[1].split("]")[0]
    assert "shed" in hidden and "thought" in hidden                           # hidden during the floor-reflection pass


def test_figure_has_glowing_suit_contours_that_grow_with_the_stage():
    assert "float anat(vec3 p)" in AV3 and "float c = anat(vObj) * uContour * (gl_FrontFacing ? 1.0 : 0.15);" in AV3
    assert "contour: 1, detail: 0.75, head: true" in AV3                      # only the figure carries the seams
    assert "figureMat.uniforms.uContour.value = ([0.75, 0.9, 1.05, 1.2, 1.3][tier - 1] || 0.9) * circ;" in AV3
    assert "smoothstep(0.12, 0.02, p.z));           // crest over the head (not the face)" in AV3


def test_gestures_come_only_from_real_states_and_bend_the_arms_in_the_shader():
    poses = AV3.split("const POSE_OF = ")[1].split(";")[0]
    assert poses == '{ speaking: "present", coding: "work", executing: "work", approval: "raise", completed: "open" }'
    assert "const pose = POSES[gestureOf()] || POSES.rest" in AV3                    # anything else: arms at rest
    assert 'const gestureOf = () => (pers ? pers.gesture : POSE_OF[state] || "rest");' in AV3   # personality first (avatar-events.js)
    assert "uniform mat3 uHead, uArmR, uArmL, uForeR, uForeL;" in AV3
    assert "vObj = position; vObjN = normal;" in AV3                               # seams and panels stay on the moving arm
    figure_code = AV3.replace((STATIC / "avatar3d-projections.js").read_text(), "")   # everything but the projections
    assert "armPose(k);" in AV3 and "wireframe: true" not in figure_code           # no unposed overlay left behind


def test_data_wall_shows_real_signals_only():
    fn_wall = fn(JS, "renderWall")
    assert "auraValues(d)" in fn_wall and 'w.dataset.model = ui.chatBusy ? "on" : "off";' in fn_wall
    assert '(v === null || v === undefined ? "na"' in fn_wall                     # unavailable stays at rest, never invented
    for g in ("rb-cpu", "rb-mem", "rb-model", "rb-work"):
        assert f'<g class="{g}">' in HTML
    assert 'style="' not in HTML.split('class="env-ribbons"')[1].split("</svg>")[0]


def test_focus_view_screen_wall_is_decoration_that_respects_motion_settings():
    assert HTML.count('<div class="vw-tile"></div>') == 7 and '<div class="vwall" aria-hidden="true">' in HTML
    css = (STATIC / "avatar.css").read_text()
    assert ':root[data-fx="reduced"] .vw-tile::after, :root[data-fx="off"] .vw-tile::after { animation: none; display: none; }' in css
    assert "@media (prefers-reduced-motion: reduce) { .vw-tile::after { animation: none; display: none; } }" in css


def test_character_detail_grows_with_the_stage_and_keeps_the_helmet_clean():
    assert "figureMat.uniforms.uDetail.value = ([0.75, 0.85, 1.0, 1.15, 1.25][tier - 1] || 0.75) * circ;" in AV3   # rich now, maximum at stage 4
    assert "uDetail > 0.95 ? circuit(" in AV3                                              # finer circuits only from stage 3
    assert "float body = 1.0 - smoothstep(4.4, 4.5, p.y);   // the head stays smooth" in AV3
    assert 'innerMat = holo({ opacity: 0.35, rim: 0.8, flow: true, core: 0.55, head: true });' in AV3   # bends with the arms
    assert "innerMat.uniforms.uOpacity.value = 0.12 + cur.neural * 0.5" in AV3             # brighter only while really thinking
    assert "shed.visible = moving; wisps.visible = moving;" in AV3                         # no particles in Low performance / Reduced motion
    assert "if (!phone) {   // a soft outline glow" in AV3                                 # the aura shell is skipped on phones


def test_alloy_armour_hugs_the_body_and_reacts_only_to_real_work_and_alerts():
    assert 'part("armour", 1,' in AV3 and "const PLATES = [" in AV3
    names = re.findall(r'name: "(\w+)"', AV3.split("const PLATES = [")[1].split("];")[0])
    assert set(names) == {"chest", "abdomen", "shoulder", "pauldron", "upperarm", "forearm", "hip", "thigh", "knee", "shin",
                          "helmet", "hand"}                                                 # the brief's armour list, layered
    assert 'const src = pl.src === "hands" ? handGeo : figureGeo;' in AV3                   # cut from the figure's own surface
    assert "(0.0072 - Math.abs(z - kz)) * 60); } },   // one plate per finger segment" in AV3
    assert "if (h > uReveal || vEdge < 0.0) discard;   // a smooth plate border" in AV3
    assert "const PLATE_VERT = VERT" in AV3                                                 # bends with the arms and head
    assert "metals.push({ mesh, order: pl.order, dir: d, name: pl.name," in AV3                         # assembles during startup, hidden in the reflection
    vent = AV3.split("plateUni.uOpen.value +=")[1].split(";")[0]
    assert "heavy && moving" in vent                                                        # plates part only while really working, Normal mode
    assert 'const heavy = ["coding", "executing", "reasoning"].includes(state);' in AV3
    assert 'if (s === "error" || s === "warning") shieldFlare = 2.5;' in AV3                # the shield flares only on a real alert
    assert "if (!phone) part(\"shield\", 1," in AV3


def test_eye_behaviours_are_visible_and_only_follow_real_signals():
    assert "FACE.uEyeLook.value = glance && state !== \"researching\"" in AV3                 # the eyes follow the glance
    assert 'FACE.uEyeHot.value += ((state === "error" ? 0 : 1)' in AV3                     # deep red eyes only on an error
    assert "float face = smoothstep(4.36, 4.46, vObj.y) * smoothstep(0.02, 0.14, vObj.z);   // the shield never covers the face" in AV3
    looks = dict(re.findall(r"^\s+(\w+):\s+(\{ tint:.*\}),$", AV3, re.M))
    eyes = {k: float(re.search(r"eyes: ([\d.]+)", v).group(1)) for k, v in looks.items()}
    assert eyes["idle"] < eyes["listening"] < eyes["speaking"]                           # dim idle, brighter listening and speaking
    assert "get eyes() { return av.three ? av.three.eyes : null; }" in AV                 # read-only readout for checks



def test_hands_have_articulated_fingers_that_only_flex_slightly():
    assert "export function sdHand(x, y, z) {" in AV3 and "export function meshHands(" in AV3
    assert "// joint knuckles" in AV3 and "// wrist pistons" in AV3 and "// thumb" in AV3
    assert "attribute float aFing; attribute float aSeg; attribute vec3 aKnuck;" in AV3      # each vertex knows its finger
    assert 'handUni.uFlex.value = moving ? 0.05 : 0;' in AV3                                 # flexing only in Normal mode
    curl = AV3.split("const CURL = ")[1].split(";")[0]
    assert "work: 0.42" in curl and "open: 0.0" in curl                                     # poses come from real states only
    assert "// a relaxed hand turns about 55 degrees at the wrist" in AV3


def test_joints_and_wireframe_are_baked_into_rest_coordinates():
    assert 'part("joints", 1,' in AV3 and "// baked into rest coordinates (the joints bend them)" in AV3
    assert 'part("wire", 2,' in AV3 and "wire: true" in AV3                                  # stage 2: fine holographic wireframe
    assert "vec3 p0 = pos, n0 = nrm;" in AV3                                                 # joints carry local changes (venting, fingers)


def test_reactor_layers_follow_the_real_reactor_level_and_confirm_only_real_completions():
    for layer in ('part("reactorcore2", 1,', 'part("reactorgyro", 2,', 'part("reactorpaths", 1,', 'part("reactorsupports", 1,', 'part("reactorswirl", 1,'):
        assert layer in AV3, layer
    assert "uLvl: REACTOR" in AV3                                                    # the plasma core and swirl follow the real level
    assert 'if (s === "completed") { flash = 1; firePulse(1.4); reactorX.confirm(); }' in AV3   # golden pulse: a real completion only
    assert AV3.count("reactorX.confirm()") == 1
    assert "never a blown-out disc" in AV3


def test_neural_network_reflects_real_thinking_and_execution_and_bends_with_the_body():
    assert 'part("neural", 1, build(false));' in AV3 and 'part("neural3", 3, build(true));' in AV3   # branches from stage 3
    assert 'neuralX.update(cur.neural, ["executing", "coding", "verifying"].includes(state), REACTOR.value);' in AV3
    assert AV3.count("flow: true, core: 0.6, head: true }") >= 2                    # drawn with the figure's vertex shader (bends)


def test_materialise_and_dematerialise_follow_real_events_only():
    # startup (once per session) builds the body from particles; the real emergency stop takes it down; release rebuilds
    assert 'if (s === "halted" && mode === "full") {   // the real emergency stop' in AV3
    assert 'if (prev === "halted" && mode === "full") { demat = null;' in AV3
    assert 'if (m !== "full") demat = null;' in AV3                                       # no sequences in Low performance / Reduced motion
    assert "rebuild.update(edge, mode === \"full\" ? seq : 0);" in AV3                     # particles only while a sequence runs
    assert "const rebuild = buildReconstruction({ U, rng }, figureGeo, body, phone ? 800 : 2400);" in AV3
    assert 'if (opts.onLifecycle) opts.onLifecycle("dematerializing");' in AV3
    assert "onLifecycle: (phase) => { if (SM) show(SM.setLifecycle(phase)); }" in AV
    order = AV3.split("// order: body forms, circuitry lights, sensors wake, the reactor ignites, the orbitals synchronise")[1][:300]
    assert "EYE.value *= ease((boot.t - 2.0) / 0.5);" in order and "orbits.scale.setScalar(0.4 + 0.6 * ease((boot.t - 3.4) / 0.9));" in order


def test_environment_orbitals_and_panels_show_real_data_only():
    for p in ('part("platform2", 1,', 'orbital("orbit_low", 1,', 'orbital("orbit_diag", 2,', 'orbital("orbit_upper", 3,',
              'orbital("orbit_sig", 5,', 'part("chamber", 3,', 'part("ground", 1,', 'part("panels", 1,'):
        assert p in AV3, p
    assert "o.obj.rotation.y += dt * o.speed * (0.4 + lv.ring) * lv.orbitK;" in AV3        # speed follows the real activity level
    items = fn(JS, "panelItems")
    assert '["intelligence", "missions", "health"]' in items and "title: by[id].label, value: by[id].value, status: by[id].status" in items
    assert "JarvisAvatar.setOptions({ panels: true });" in fn(JS, "openProjection")       # panels in the focus view only
    assert "JarvisAvatar.endPreview();" in fn(JS, "closeProjection")


def test_projection_controls_are_per_device_and_every_one_has_an_effect():
    defaults = JS.split("const DISPLAY_DEFAULT = ")[1].split(";")[0]
    for key in ("quality", "particles", "animation", "reactor", "orbit", "env", "orbitals"):
        assert key in defaults, key
    for k in ("K.particles[OPT.particles]", "K.animation[OPT.animation]", "K.reactor[OPT.reactor]", "K.orbit[OPT.orbit]",
              "envX.setVisible(OPT.env, OPT.orbitals); orbits.visible = OPT.orbitals;"):
        assert k in AV3, k
    assert 'if (!lean()) renderer.render(scene, camera);   // the floor reflection: skipped on Performance and Low Power' in AV3
    assert 'o.visible = tier >= 2 && quality === "high";' in AV3
    assert "if (avg > 55 && i > 0)" in AV3                                                  # Auto steps down when frames are slow
    assert 'content: "PREVIEW — not live"' in (STATIC / "avatar.css").read_text()            # a preview is always marked


def test_projection_director_reuses_the_renderer_limits_and_disposes():
    pj = (STATIC / "avatar3d-projections.js").read_text()
    assert "WebGLRenderer" not in pj and "requestAnimationFrame" not in pj                 # same renderer, same loop
    assert "while (active.length > MAX_OPEN)" in pj and "const MAX_OPEN = 4;" in pj        # at most two per side
    assert "for (const o of p.own) if (o && o.dispose) o.dispose();" in pj               # geometry, materials, textures freed
    assert "replaced in place" in pj                                                     # a refresh never reorders or evicts
    assert set(re.findall(r"^  (\w+)\(d, k\) \{", pj, re.M)) == {"workflow", "architecture", "neural", "globe", "data",
                                                                   "timeline", "security", "simulation", "research"}
    assert "Waiting for you (not authorized)" in pj                                       # pending approvals stay outside the shield
    assert "...director.hidden()" in AV3                                                  # projections never appear in the reflection
    js = (STATIC / "app.js").read_text()
    assert "api(`/api/projection/${m}`)" in js and "describeProjection(r.module, data)" in js   # real data; described without a model


def test_learning_experimenting_and_analyzing_come_from_real_signals():
    fn_state = fn(JS, "avatarState")
    assert "L && L.experiments_running" in fn_state and "L.lessons_new_at !== ui.seenLessonAt" in fn_state
    assert "ui.analyzingUntil = Date.now() + 1500" in JS                                     # only while fetching projection data
    sm = (STATIC / "avatar-state.js").read_text()
    assert "MAX_MS = { success: 4000, learning: 4000, disagreeing: 3000 }" in sm             # a lesson is shown briefly, never held


def test_meshes_are_built_off_the_main_thread_with_a_fallback():
    worker = (STATIC / "avatar3d-worker.js").read_text()
    assert 'import { meshFigure, meshHands } from "/static/avatar3d-geometry.js";' in worker
    assert "fetch(" not in worker and "localStorage" not in worker and "document." not in worker   # computes only
    assert 'new Worker("/static/avatar3d-worker.js", { type: "module" })' in AV and "resolve(null)" in AV   # no worker: built inline
    assert "const handGeo = pre ? unpack(pre.hands) : meshHands(" in AV3
