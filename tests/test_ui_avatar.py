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
                      "speaking", "warning", "recovery", "halted", "unknown"]
    for part in ("helmet", "visor", "face"):
        assert f'["{part}", 1,' in AV, part
    assert "registerPart" in AV and "function registerPart(name, markup)" in AV


AVATAR_HARNESS = r"""
const ui = { convo: [], stage: null };
const core = { dataset: {} };
const $ = () => core;
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
    (tmp_path / "a.js").write_text(AVATAR_HARNESS % (fn(JS, "avatarState"), fn(JS, "criticalProblem")))
    got = json.loads(subprocess.run([node, str(tmp_path / "a.js")], capture_output=True, text=True, check=True).stdout)
    assert got == {
        "idle": "idle", "connecting": "unknown", "decision": "approval", "blocked": "approval", "stopped": "halted",
        "offline": "error", "no models": "warning", "executing": "executing", "task verifying": "verifying",
        "recovering": "recovery", "planning": "planning", "queued": "planning", "researching": "researching",
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

AV3 = (STATIC / "avatar3d.js").read_text()
THREE_SHA256 = "3e690ac7d180b0aadf0891bea39eec643e29e2d3e75c99b18689518665f69ba6"  # three@0.160.0 build/three.module.min.js


def test_three_is_the_exact_pinned_build_and_served_from_this_mac(dash):
    path = STATIC / "vendor" / "three.module.min.js"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == THREE_SHA256
    assert "MIT License" in (STATIC / "vendor" / "three.LICENSE.txt").read_text()
    d, _, _ = dash
    status, headers, body = call(d, "/static/vendor/three.module.min.js")
    assert status == 200 and headers["Content-Type"].startswith("text/javascript") and hashlib.sha256(body).hexdigest() == THREE_SHA256
    assert call(d, "/static/vendor/three.LICENSE.txt")[0] == 404  # only the one file is served
    assert call(d, "/static/avatar3d.js")[0] == 200
    csp = call(d, "/")[1]["Content-Security-Policy"]
    assert "script-src 'self'" in csp and "connect-src 'self'" in csp and "unsafe" not in csp  # unchanged


def test_3d_core_is_decoration_only_and_local():
    assert 'import * as THREE from "/static/vendor/three.module.min.js";' in AV3
    for forbidden in ("fetch(", "XMLHttpRequest", "localStorage", "innerHTML", "eval(", "http://", "https://", "Loader("):
        assert forbidden not in AV3, forbidden
    assert set(re.findall(r"^\s+(\w+):\s+\{ tint:", AV3, re.M)) == set(json.loads(re.search(r"const STATES = (\[.*?\]);", AV, re.S).group(1)))


def test_3d_core_falls_back_to_2d_and_respects_the_modes():
    assert 'import("/static/avatar3d.js")' in AV and "if (!three) return;" in AV  # failure leaves the 2D core
    assert 'av.wrap.classList.remove("has-3d")' in AV  # a lost GPU context goes back to 2D
    assert "av.three.setMode(av.lastMode)" in AV and "av.three.setState(state)" in AV and "av.three.setTier(tier)" in AV
    # Normal: capped frame rate; other modes draw only when something changes; nothing while hidden or off screen
    assert "1000 / 30" in AV3 and "1000 / 24" in AV3 and 'const moving = mode === "full";' in AV3
    assert "if (!visible || document.hidden) return;" in AV3 and "IntersectionObserver" in AV3
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


def test_the_helm_is_faceless():
    for human in ("mouth", "jaw", "grille", "lips", "nose"):
        assert human not in AV3.lower().replace("no mouth", ""), human
    assert 'part("figure", 1,' in AV3 and "export function sdHuman(" in AV3 and "export function meshFigure(" in AV3
    for gone in ("sensors", "faceplate", "mechanics"):   # the toy-robot parts are gone
        assert f'part("{gone}"' not in AV3


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
    assert "closeProjection();" in JS.split('e.key === "Escape"')[1].split("\n")[0]
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
    assert 'localStorage.setItem(EVO_CAP_KEY, String(v))' in JS and "[1, 2, 3, 4].filter((n) => n <= evo.tier)" in JS


def test_idle_liveliness_is_limited_to_rest_and_never_fakes_activity():
    # glances happen only in the resting "aware" look, and stop the moment real work starts
    assert 'if (target.head === "aware") {' in AV3 and "} else glance = null;" in AV3
    assert "glanceAt = t + 6 + Math.random() * 5" in AV3          # every ~6–11 s, held ~1.6–2.6 s
    assert 'const shut = target.head === "still" ? 1 :' in AV3     # halted/unknown/error: no blinking
    # every state has a reactor pattern, from a fixed set
    pats = set(re.findall(r'rpat: "(\w+)"', AV3))
    assert pats <= {"calm", "spin", "scan", "beat", "surge", "stutter", "still"}
    assert len(re.findall(r'rpat: "\w+"', AV3)) == len(json.loads(re.search(r"const STATES = (\[.*?\]);", AV, re.S).group(1)))


def test_bloom_and_surface_detail_are_local_and_fail_safe():
    # post-processing is our own small pipeline (no extra library) and the projection still draws without it
    assert "} catch (e) { return null; }   // no post-processing: draw directly" in AV3
    assert "if (post) post.begin(); else renderer.clear();" in AV3 and "if (post) post.end(t, intensity);" in AV3
    assert AV3.count('from "/static/vendor/three.module.min.js"') == 1 and "import(" not in AV3
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
    assert 'if (state === "completed") { burst(); surge(); }' in AV            # completed comes only from a finished task
    surge = AV.split("  function surge() {")[1].split("\n  }\n")[0]
    assert 'if (fxLevel() !== "full" || !av.wrap) return;' in surge   # never in Low performance / Reduced motion
    assert "@media (prefers-reduced-motion: reduce) { .surge { display: none; }" in (STATIC / "avatar.css").read_text()


def test_figure_is_a_light_body_with_teal_hands_and_sparkles_kept_out_of_the_reflection():
    assert "const metals = [];" in AV3 and "MeshStandardMaterial" not in AV3   # no bulky lit-metal robot plates (owner's feedback)
    assert 'uAccent: { value: new THREE.Color("#3dffb8") }' in AV3            # teal-green accent, marked per vertex (hands)
    assert "vec3 uTint = mix(uTint0, uAccent, vAccent);" in AV3
    assert "shed.visible = moving;" in AV3                                    # sparkles only while motion is allowed
    hidden = AV3.split("const hidden = [")[1].split("]")[0]
    assert "shed" in hidden and "thought" in hidden                           # hidden during the floor-reflection pass


def test_figure_has_glowing_suit_contours_that_grow_with_the_stage():
    assert "float anat(vec3 p)" in AV3 and "float c = anat(vObj) * uContour;" in AV3
    assert "contour: 1, detail: 0.75, head: true" in AV3                      # only the figure carries the seams
    assert "figureMat.uniforms.uContour.value = [0.75, 0.9, 1.05, 1.2][tier - 1]" in AV3
    for word in ("mouth", "jaw", "nose", "eye"):                              # contours stay off the face
        assert word not in AV3.split("float anat(vec3 p)")[1].split("return min(c, 1.0);")[0]


def test_gestures_come_only_from_real_states_and_bend_the_arms_in_the_shader():
    poses = AV3.split("const POSE_OF = ")[1].split(";")[0]
    assert poses == '{ speaking: "present", coding: "work", executing: "work", approval: "raise", completed: "open" }'
    assert "const pose = POSES[POSE_OF[state] || \"rest\"]" in AV3                 # anything else: arms at rest
    assert "uniform mat3 uHead, uArmR, uArmL, uForeR, uForeL;" in AV3
    assert "vObj = position; vObjN = normal;" in AV3                               # seams and panels stay on the moving arm
    assert "armPose(k);" in AV3 and "wireframe: true" not in AV3                   # no unposed overlay left behind


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


def test_character_detail_grows_with_the_stage_and_keeps_the_face_smooth():
    assert "figureMat.uniforms.uDetail.value = [0.75, 0.85, 1.0, 1.15][tier - 1]" in AV3   # rich now, maximum at stage 4
    assert "uDetail > 0.95 ? circuit(" in AV3                                              # finer circuits only from stage 3
    assert "float body = 1.0 - smoothstep(4.4, 4.5, p.y);   // the head stays smooth" in AV3
    for gone in ("eye", "mouth", "visor"):                                                 # owner's choice: fully smooth face
        assert gone not in AV3.split("// ---- the figure:")[1].split("export function meshFigure")[0].lower()
    assert 'innerMat = holo({ opacity: 0.35, rim: 0.8, flow: true, core: 0.55, head: true });' in AV3   # bends with the arms
    assert "innerMat.uniforms.uOpacity.value = 0.12 + cur.neural * 0.5" in AV3             # brighter only while really thinking
    assert "shed.visible = moving; wisps.visible = moving;" in AV3                         # no particles in Low performance / Reduced motion
    assert "if (!phone) {   // a soft outline glow" in AV3                                 # the aura shell is skipped on phones


def test_alloy_armour_hugs_the_body_and_reacts_only_to_real_work_and_alerts():
    assert 'part("armour", 1,' in AV3 and "const PLATES = [" in AV3
    names = re.findall(r'name: "(\w+)"', AV3.split("const PLATES = [")[1].split("];")[0])
    assert set(names) == {"chest", "abdomen", "shoulder", "forearm", "shin", "helmet"}       # key plates, not a full suit
    assert "const P = figureGeo.attributes.position.array" in AV3                           # cut from the figure's own surface
    assert "if (h > uReveal || vEdge < 0.0) discard;   // a smooth plate border" in AV3
    assert "const PLATE_VERT = VERT" in AV3                                                 # bends with the arms and head
    assert "metals.push({ mesh, order: pl.order, dir: d });" in AV3                         # assembles during startup, hidden in the reflection
    vent = AV3.split("plateUni.uOpen.value +=")[1].split(";")[0]
    assert "heavy && moving" in vent                                                        # plates part only while really working, Normal mode
    assert 'const heavy = ["coding", "executing", "reasoning"].includes(state);' in AV3
    assert 'if (s === "error" || s === "warning") shieldFlare = 2.5;' in AV3                # the shield flares only on a real alert
    assert "if (!phone) part(\"shield\", 1," in AV3
