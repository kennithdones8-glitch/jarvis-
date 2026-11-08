"""Avatar 2.5: the camera rig and inspection, projection presets, and the diagnostics readout.

The rig (static/avatar3d-camera.js) and presets (static/avatar-presets.js) are plain JavaScript run for real in
Node (skipped when Node isn't installed; it is not a project dependency). Behaviour was also checked in a headless
browser: every view and inspection target, wheel and drag, Esc order, presets end to end, and a phone viewport.
"""

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
AV3 = (STATIC / "avatar3d.js").read_text()
CAM = (STATIC / "avatar3d-camera.js").read_text()
PRESETS = (STATIC / "avatar-presets.js").read_text()
CSS = (STATIC / "avatar.css").read_text()
NODE = shutil.which("node")


def node(code: str):
    if not NODE:
        pytest.skip("node not installed")
    res = subprocess.run([NODE, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=30, check=True)
    return json.loads(res.stdout)


def rig(script: str):
    return node(f"""
import {{ createRig, VIEWS, TARGETS }} from {json.dumps(str(STATIC / "avatar3d-camera.js"))};
const cam = {{ position: {{ set(x, y, z) {{ this.v = [x, y, z]; }} }}, lookAt(x, y, z) {{ this.at = [x, y, z]; }} }};
const r = createRig(cam, {{}}); const out = {{}};
const settle = () => {{ for (let i = 0; i < 400; i++) r.update(0.2); }};
{script}
console.log(JSON.stringify(out));
""")


def presets(script: str):
    return node(f"""
import {{ createRequire }} from "module";
const P = createRequire(import.meta.url)({json.dumps(str(STATIC / "avatar-presets.js"))});
const out = {{}};
{script}
console.log(JSON.stringify(out));
""")


# ---- camera rig -------------------------------------------------------------------------------------------------
def test_resting_view_matches_the_original_camera():
    out = rig("out.pos = cam.position.v; out.at = cam.at; out.state = r.state;")
    assert [round(x, 2) for x in out["pos"]] == [0, 2.85, 11.5] and out["at"] == [0, 2.68, 0]
    assert out["state"]["inspecting"] is False and out["state"]["view"] == "front"


def test_orbit_zoom_and_pan_only_while_inspecting_and_stay_in_bounds():
    out = rig("""
r.rotate(300, 0); r.zoom(0.2); r.pan(400, 0); settle(); out.idle = r.state;
r.setInspecting(true); r.rotate(300, -9999); r.zoom(0.001); settle(); out.close = r.state;
r.zoom(1e6); r.pan(1e6, 1e6); settle(); out.far = r.state;
r.setInspecting(false); settle(); out.back = r.state;
""")
    assert out["idle"]["az"] == 0 and out["idle"]["r"] == 11.5 and out["idle"]["target"] == [0, 2.68, 0]   # ignored
    assert out["close"]["az"] != 0 and out["close"]["r"] == 2.4 and out["close"]["el"] == -0.2           # clamped
    assert out["far"]["r"] == 22 and out["far"]["target"][0] in (-4, 5) and out["far"]["target"][1] == 6
    assert out["back"]["view"] == "front" and out["back"]["r"] == 11.5 and out["back"]["target"] == [0, 2.68, 0]   # exit: back to rest


def test_every_view_and_inspection_target_is_reachable():
    out = rig("""
out.views = Object.keys(VIEWS); out.targets = Object.keys(TARGETS);
out.blocked = r.inspectTarget("helmet");   // not inspecting: no
r.setInspecting(true); out.reached = {};
for (const t of out.targets) { r.inspectTarget(t); settle(); out.reached[t] = [r.state.focus, r.state.target]; }
out.bad = [r.view("nope"), r.inspectTarget("nope")];
""")
    assert set(out["views"]) == {"front", "three", "side", "back", "top", "close"}
    assert len(out["targets"]) >= 11 and {"helmet", "reactor", "hand_r", "hand_l", "back", "neural", "platform", "projections"} <= set(out["targets"])
    assert out["blocked"] is False and out["bad"] == [False, False]
    for t, (focus, target) in out["reached"].items():
        assert focus == t and len(target) == 3, t


def test_turning_takes_the_short_way_and_low_motion_jumps():
    out = rig("""
r.setInspecting(true); r.view("back"); r.update(1); out.back = r.state.az;
r.view("three"); r.update(1); out.three = r.state.az;
r.view("side"); r.update(0.5); out.half = r.state.az;
""")
    assert abs(out["back"] - 3.1416) < 0.01 and abs(out["three"] - 0.62) < 0.01   # k = 1 (Low performance / Reduced motion): straight there
    assert 0.62 < out["half"] < 1.5708


def test_projections_widen_the_resting_view_but_not_inspection():
    out = rig("""
r.update(1, 1); out.wide = cam.position.v.slice();
r.setInspecting(true); r.update(1, 1); out.inspect = cam.position.v.slice();
""")
    assert [round(x, 1) for x in out["wide"]] == [0.9, 2.9, 14.5]   # the same wide view the Director used before
    assert round(out["inspect"][2], 1) == 11.5


# ---- presets ----------------------------------------------------------------------------------------------------
def test_built_in_presets_cover_the_brief_and_only_use_display_settings():
    out = presets("out.ids = Object.keys(P.BUILTIN); out.keys = P.KEYS; out.s = Object.values(P.BUILTIN).map((b) => Object.keys(b.s));")
    assert out["ids"] == ["standard", "cinematic", "focus", "diagnostic", "immersive", "performance"]
    for keys in out["s"]:
        assert set(keys) == set(out["keys"])
    display = re.search(r"const DISPLAY_DEFAULT = \{(.*?)\};", JS, re.S).group(1)
    for k in out["keys"]:
        assert f"{k}:" in display, k   # every preset key is an existing per-device display setting


def test_presets_create_rename_update_duplicate_delete_and_protect_built_ins():
    out = presets("""
let st = P.empty(); const d = { ...P.BUILTIN.cinematic.s, particles: "low" };
out.cur0 = P.current(st, d);
let r = P.create(st, "  My\\u0007  look  ", d); st = r.state; const id = r.id; out.created = P.find(st, id);
out.cur1 = P.current(st, d);
out.dupName = P.create(st, "my look", d).state.custom.map((c) => c.name);
r = P.rename(st, id, "Night"); st = r.state; out.renamed = P.find(st, id).label;
r = P.update(st, id, { ...d, particles: "high", evil: "x" }); st = r.state; out.updated = P.find(st, id).s;
r = P.duplicate(st, "cinematic"); st = r.state; out.dup = P.find(st, r.id).label; out.dupId = r.id;
out.protect = [P.rename(st, "standard", "x").ok, P.update(st, "focus", d).ok, P.remove(st, "cinematic").ok];
r = P.remove(st, id); st = r.state; out.after = P.list(st).map((p) => p.label); out.active = st.active;
out.removeActive = P.remove(st, out.dupId).state.active;
out.empty = P.create(st, "   ", d).ok;
""")
    assert out["cur0"] == {"id": "standard", "label": "Standard", "builtin": True, "modified": True}
    assert out["created"]["label"] == "My look" and out["created"]["builtin"] is False   # control characters and spaces cleaned
    assert out["cur1"]["modified"] is False
    assert out["dupName"] == ["My look", "my look (2)"]
    assert out["renamed"] == "Night" and out["updated"]["particles"] == "high" and "evil" not in out["updated"]
    assert out["dup"] == "Cinematic copy" and out["protect"] == [False, False, False]
    assert out["after"][-1] == "Cinematic copy" and "Night" not in out["after"] and out["active"] == out["dupId"]   # the copy is what is showing
    assert out["empty"] is False and out["removeActive"] == "standard"   # deleting the showing preset falls back to Standard


def test_stored_presets_are_validated_on_load():
    out = presets("""
const valid = { quality: ["auto", "high"], particles: ["low"] };
const raw = { active: "c1", custom: [{ id: "c1", name: "ok", s: { quality: "ultra", particles: "low" } },
  { id: "<script>", name: "bad id", s: {} }, { id: "c2", name: "", s: {} }, { id: "c1", name: "dupe", s: {} }] };
out.st = P.normalise(raw, valid); out.junk = P.normalise("nope"); out.lost = P.normalise({ active: "c9", custom: [] });
out.cap = P.normalise({ custom: Array.from({ length: 40 }, (_, i) => ({ id: "c" + i, name: "n" + i, s: {} })) }).custom.length;
""")
    assert out["st"] == {"active": "c1", "custom": [{"id": "c1", "name": "ok", "s": {"particles": "low"}}]}
    assert out["junk"]["active"] == "standard" and out["lost"]["active"] == "standard" and out["cap"] == 20


# ---- wiring, privacy and safety ---------------------------------------------------------------------------------
def test_new_files_are_served_and_loaded(dash):
    d, _, _ = dash
    html = call(d, "/")[2].decode()
    assert html.index("/static/avatar-presets.js") < html.index("/static/app.js")
    for path in ("/static/avatar3d-camera.js", "/static/avatar-presets.js"):
        status, headers, _ = call(d, path)
        assert status == 200 and headers.get("Content-Type", "").startswith("text/javascript"), path
    assert 'import { createRig, VIEWS, TARGETS } from "/static/avatar3d-camera.js";' in AV3
    assert "import " not in CAM   # plain maths: nothing else loaded


def test_gestures_are_captured_only_while_inspecting():
    wheel = AV.split('wrap.addEventListener("wheel"')[1].split("}, { passive: false });")[0]
    assert "if (!inspecting()) return;" in wheel and wheel.index("if (!inspecting()) return;") < wheel.index("e.preventDefault()")
    assert 'if (inspecting()) return;             // inspecting: clicks only steer the camera' in AV
    assert ".core-wrap.inspecting { touch-action: none;" in CSS and "touch-action: none" not in CSS.split(".core-wrap.inspecting")[0]
    assert 'if (!stopInspect()) closeProjection();' in JS   # Esc: inspection first, then the focus view
    assert "stopInspect();\n  document.body.classList.remove(\"projection\");" in JS
    for forbidden in ("fetch(", "localStorage.setItem", "innerHTML"):   # the renderer side still only shows
        assert forbidden not in AV and forbidden not in CAM and forbidden not in PRESETS, forbidden


def test_presets_and_diagnostics_change_the_look_only_and_show_measured_numbers():
    assert 'const PRESET_KEY = "jarvis-presets";' in JS and "JarvisPresets.normalise(raw, displayValid())" in JS
    body = re.search(r"function presetChange\(.*?\n\}\n", JS, re.S).group(0) + re.search(r"function applyPreset\(.*?\n\}\n", JS, re.S).group(0)
    assert "api(" not in body and "call(" not in body and "act(" not in body   # nothing reaches the server
    diag = re.search(r"function renderDiag\(.*?\n\}\n", JS, re.S).group(0)
    assert "JarvisAvatar.stats" in diag and "frameMs" in diag and "Math.random" not in diag
    assert "frameAvg = frameAvg ? frameAvg * 0.9 + (now - last) * 0.1 : now - last;" in AV3   # measured between real frames
    assert "frameMs: raf && mode === \"full\" ? frameAvg : 0" in AV3   # no frame time claimed while idle
    assert "temperature" not in diag.lower()


# ---- phase 2: the central event-to-visual map and personalities --------------------------------------------------
EVENTS = (STATIC / "avatar-events.js").read_text()


def events(script: str):
    return node(f"""
import {{ createRequire }} from "module";
const require = createRequire(import.meta.url);
const E = require({json.dumps(str(STATIC / "avatar-events.js"))}), SM = require({json.dumps(str(STATIC / "avatar-state.js"))});
const out = {{}};
{script}
console.log(JSON.stringify(out));
""")


def test_every_state_has_one_mapping_and_every_personality_is_drawn():
    out = events("out.map = E.MAP; out.pers = E.PERSONALITY; out.states = SM.STATES; out.proj = E.PROJECTIONS;")
    renderer_states = json.loads(re.search(r"const STATES = (\[.*?\]);", AV, re.S).group(1).replace("\n", " "))
    assert set(out["map"]) == set(out["states"]) == set(renderer_states)            # one table, the same states everywhere
    for state, v in out["map"].items():
        assert v["personality"] in out["pers"], state
        assert v["projection"] is None or v["projection"] in out["proj"], state
    for name, p in out["pers"].items():
        assert f'h === "{p["head"]}"' in AV3 or p["head"] == "aware", name            # the renderer draws each head motion
        assert f"    {p['gesture']}:" in AV3, name                                     # and each gesture
    built = set(re.findall(r"^  (\w+)\(d, k\) \{", (STATIC / "avatar3d-projections.js").read_text(), re.M))
    assert set(out["proj"]) <= built                                                  # automatic projections exist


def test_personalities_never_claim_feelings_and_red_stays_for_errors():
    out = events("out.pers = E.PERSONALITY;")
    for name, p in out["pers"].items():
        for word in ("happy", "sad", "angry", "upset", "annoyed", "frustrated", "feels", "excited"):
            assert word not in p["means"].lower(), (name, word)
    looks = re.search(r"const LOOKS = \{(.*?)\n\};", AV3, re.S).group(1)
    disagree = re.search(r'disagreeing: +\{ tint: "(#\w+)"', looks).group(1)
    assert disagree != "#ff4b4b" and re.findall(r'(\w+): +\{ tint: "#ff4b4b"', looks) == ["error"]   # amber, not red


def test_disagreeing_comes_only_from_a_new_refusal_in_the_audit_log():
    fn_ = re.search(r"function refusedJustNow\(.*?\n\}\n", JS, re.S).group(0)
    out = events(f"""
const ui = {{}}; const window = {{ JarvisEvents: E }}, JarvisEvents = E; let clock = 1000; const Date = {{ now: () => clock }};
{fn_}
const d = (rows) => ({{ audit: rows }});
out.first = refusedJustNow(d([{{ seq: 9, event: "permission.denied" }}]));          // already in the log: not replayed
out.other = refusedJustNow(d([{{ seq: 10, event: "task.completed" }}, {{ seq: 9, event: "permission.denied" }}]));
out.fresh = refusedJustNow(d([{{ seq: 12, event: "egress.denied" }}, {{ seq: 11, event: "approval.rejected" }}]));
clock += 2000; out.held = refusedJustNow(d([{{ seq: 12, event: "egress.denied" }}]));
clock += 1500; out.ended = refusedJustNow(d([{{ seq: 12, event: "egress.denied" }}]));
out.rejected = E.fromAudit([{{ seq: 20, event: "approval.rejected" }}], 0);          // your own "no" is not a refusal
const m = SM.createMachine({{ now: () => clock }});
m.input("executing"); clock += 100; out.beats = m.input("disagreeing").state;
clock += 100; out.stop = m.input("halted").state;
const m2 = SM.createMachine({{ now: () => clock }}); m2.input("disagreeing"); clock += 3100; out.oneShot = m2.tick().state;
""")
    assert out["first"] is False and out["other"] is False and out["fresh"] is True
    assert out["held"] is True and out["ended"] is False and out["rejected"] is None
    assert out["beats"] == "disagreeing" and out["stop"] == "halted" and out["oneShot"] == "idle"
    assert 'if (refusedJustNow(d) && s.core !== "stopped" && s.core !== "offline") return "disagreeing";' in JS
    assert set(re.findall(r'"([\w.]+)": "disagreeing"', EVENTS)) == {"permission.denied", "egress.denied"}


def test_dashboard_reads_projection_effect_and_motion_from_the_map():
    assert "const m = JarvisEvents.projectionFor(state);" in JS and "AUTO_PROJECTION" not in JS
    assert "av.three.setPersonality(personality(state));" in AV and 'if (effect(state) === "surge")' in AV
    html = (STATIC / "index.html").read_text()
    assert html.index("/static/avatar-events.js") < html.index("/static/avatar.js")
    assert "document" not in EVENTS and "fetch(" not in EVENTS and "localStorage" not in EVENTS   # data only


# ---- phase 3: schematic panel controls, the projection area, research sources -----------------------------------
DIRECTOR = (STATIC / "avatar3d-projections.js").read_text()

DIRECTOR_HARNESS = """
import { register } from "node:module";
register("data:text/javascript," + encodeURIComponent(`export async function resolve(s, c, next) {
  if (s.startsWith("/static/")) return next(STATIC_URL + s.slice(8), c);
  return next(s, c); }`));
const ctx2d = { measureText: (t) => ({ width: t.length * 20 }), fillText() {}, set font(v) {}, set fillStyle(v) {}, set textBaseline(v) {} };
globalThis.document = { createElement: () => ({ getContext: () => ctx2d, width: 0, height: 0 }) };
globalThis.performance = globalThis.performance || { now: () => Date.now() };
const THREE = await import("/static/vendor/three.module.min.js");
const { createDirector } = await import("/static/avatar3d-projections.js");
const scene = new THREE.Scene(); let kicks = 0;
const D = createDirector({ scene, kick: () => kicks++ });
const settle = () => { for (let i = 0; i < 300; i++) D.update(0.05, true); };
const vis = () => D.list().filter((p) => scene.children.find((r) => r.visible && r.children[0] && p)).length;
const shownMods = () => scene.children.filter((r) => r.visible).length;
const empty = { nodes: [], edges: [] };
const out = {};
%s
console.log(JSON.stringify(out));
"""


def director(script: str):
    return node(DIRECTOR_HARNESS.replace("STATIC_URL", json.dumps((STATIC.as_uri() + "/"))) % script)


def test_panel_controls_expand_minimise_move_and_never_hide_silently():
    out = director("""
for (const m of ["workflow", "security", "timeline"]) D.show(m, m === "security" ? { stop: false, pending: [], denied_7d: 0, rings: { on_its_own: 2, asks_first: 3, never: 4 }, audit_ok: true, touch_id: false } : m === "timeline" ? { events: [], upcoming: [] } : empty);
settle(); out.three = D.list().map((p) => p.side); out.shown = shownMods();
D.expand("security"); settle(); out.expanded = [D.expanded, shownMods(), D.wideX.toFixed(2)];
D.collapse(); D.minimize("workflow", true); settle(); out.min = [shownMods(), D.list().find((p) => p.module === "workflow").minimized];
D.minimize("workflow", false); D.side("security", "left"); settle(); out.sides = Object.fromEntries(D.list().map((p) => [p.module, p.side]));
out.where = D.where("security").at[0] < 0;
D.move("timeline", -1); out.order = D.list().map((p) => p.module);
out.bad = [D.expand("nope"), D.side("nope", "left"), D.move("workflow", 99)];
const before = scene.children.length; D.close("security"); out.closed = [before - scene.children.length, D.list().length];
D.closeAll(); settle(); out.end = [scene.children.length, D.wide];
""")
    assert out["three"].count("right") == 2 and out["three"].count("left") == 1 and out["shown"] == 3   # the third moved over, not hidden
    assert out["expanded"][0] == "security" and out["expanded"][1] == 1                              # alone in the projection area
    assert out["min"] == [2, True]
    assert out["sides"]["security"] == "left" and out["where"] is True
    assert out["bad"] == [False, False, False]
    assert out["closed"] == [1, 2] and out["end"] == [0, 0]                                         # disposed, camera back


def test_research_projection_shows_the_question_and_marks_unseen_sources():
    out = director("""
const data = { question: "Which apps sync offline?", searches: 3, pages: 5,
  sources: [{ host: "example.org", verified: true }, { host: "blog.example.net", verified: false }] };
D.show("research", data); settle();
const labels = []; scene.traverse((o) => { if (o.userData && o.userData.label) labels.push(o.userData.label); });
out.labels = labels;
D.show("research", { question: null, sources: [] });
const l2 = []; scene.traverse((o) => { if (o.userData && o.userData.label) l2.push(o.userData.label); }); out.empty = l2;
""")
    assert "Question: Which apps sync offline?" in out["labels"]
    assert "example.org · seen by the research tools" in out["labels"]
    assert "blog.example.net · cited, not seen by the research tools" in out["labels"]
    assert out["empty"] == []
    rp = re.search(r"function researchProjection\(.*?\n\}\n", JS, re.S).group(0)
    assert "api(" not in rp and "fetch(" not in rp                    # built from this conversation only
    assert "new URL(u).hostname" in rp and ".slice(0, 80)" in rp       # sites only, the question shortened


def test_panel_controls_change_the_look_only():
    bar = re.search(r"function renderProjBar\(.*?\n\}\n", JS, re.S).group(0)
    for forbidden in ("api(", "call(", "act(", "approve", "/api/"):
        assert forbidden not in bar, forbidden                       # no control approves, runs or changes anything
    ctl = AV.split("function projectionControl(")[1].split("\n  }\n")[0]
    assert "fetch" not in ctl and "approv" not in ctl
    assert "const all = shown().flatMap((p) => p.pickable);" in DIRECTOR   # hidden projections can't be picked
    assert "for (const extra of here.slice(2)) extra.side = -side;" in DIRECTOR


@pytest.mark.parametrize("text,module", [("show me the sources", "research"), ("show me what you found", "research"),
                                         ("show me your source code", "architecture"), ("show me the architecture", "architecture")])
def test_asking_to_see_sources_opens_the_research_projection(text, module):
    from jarvis.intent import classify
    r = classify(text)
    assert r["mode"] == "show" and r["module"] == module


# ---- phase 4: recovery, re-initialisation, adaptive quality and Low Power -----------------------------------------
# Checked in a headless browser with WEBGL_lose_context: lost → 2D core → restored (same renderer, projections kept);
# lost and never restored → disposed and rebuilt after 8 s; Rebuild 3D view; a stand-in battery switching Low Power.
def test_a_lost_context_falls_back_then_restores_or_rebuilds_with_limits():
    assert 'canvas.addEventListener("webglcontextlost", onLost);' in AV3 and 'canvas.addEventListener("webglcontextrestored", onRestored);' in AV3
    assert "e.preventDefault(); lost = true;" in AV3                                   # lets the browser restore it
    assert "if (!raf && visible && !document.hidden && !lost)" in AV3                 # nothing is drawn while lost
    rec = AV.split("  // ---- recovery:")[1].split("  window.addEventListener(\"online\", retry3d);")[0]
    assert "const RESTORE_WAIT = 8000, RETRY_WAIT = [1500, 6000, 20000];" in rec
    assert 'av.wrap.classList.remove("has-3d")' in rec and 'av.status = "failed"; return false;' in rec   # 2D at once; gives up after three
    assert "if (manual) av.attempts = 0;" in rec and "av.reopen = open;" in rec        # Rebuild starts over; open projections come back
    assert "JarvisAvatar.onRebuilt = (modules) => { for (const m of modules) openProjectionModule(m, { quiet: true }); };" in JS
    assert "JarvisAvatar.retry3d();" in JS                                             # retried when JARVIS is reachable again


def test_rebuilding_disposes_everything_the_renderer_made():
    disp = AV3.split("// everything this renderer made")[1].split("\n    },\n")[0]
    for part in ("ro.disconnect()", "io.disconnect()", 'removeEventListener("visibilitychange", onVis)', 'removeEventListener("webglcontextlost", onLost)',
                 'removeEventListener("webglcontextrestored", onRestored)', "director.closeAll()", "free(o.geometry)", "free(m)",
                 "v.value.isTexture", "post.dispose()", "renderer.dispose()", "canvas.remove()"):
        assert part in disp, part
    assert "for (const x of Object.values(t)) x.dispose();" in AV3                    # bloom render targets too


def test_auto_quality_has_hysteresis_and_reports_measured_reasons():
    aq = AV3.split("  function autoQuality(interval) {")[1].split("\n  }\n")[0]
    assert "if (now - autoQ.changedAt < 8000) return;" in aq                          # hold any change for 8 s
    assert "now - autoQ.downAt > 20000" in aq and "++autoQ.good >= 2" in aq            # stepping back up waits
    assert 'setAutoQuality(order[i - 1], "frames too slow", avg)' in aq
    assert "avgMs: avg ? +avg.toFixed(1) : null" in AV3                               # the log holds the measured average
    for src in (AV3, JS, AV):
        assert "temperature" not in src.lower() and "thermal" not in src.lower()       # never claimed


def test_low_power_is_a_profile_and_auto_uses_it_only_on_a_low_battery():
    assert '["low", "Performance"], ["lowpower", "Low Power"]' in JS and '["high", "Quality"]' in JS
    assert "lowpower: 0.85" in AV3 and 'quality === "lowpower" ? (phone ? 1000 / 15 : 1000 / 20)' in AV3
    bat = re.search(r"function watchBattery\(.*?\n\}\n", JS, re.S).group(0)
    assert "lowBattery: !b.charging && b.level <= 0.2" in bat and "if (!navigator.getBattery" in bat
    assert 'setAutoQuality("lowpower", "battery low and not charging")' in AV3
    assert 'if (OPT.quality !== "auto" || quality === "lowpower") return;' in AV3      # frame timing never overrides it


# ---- phase 5: voice-reactive reactor (real microphone level) and optional procedural sound ------------------------
SOUND = (STATIC / "avatar-sound.js").read_text()
FAKE_AUDIO = """
const made = { osc: 0, closed: 0 };
class P { constructor() { this.value = 0; } setValueAtTime() {} linearRampToValueAtTime() {} exponentialRampToValueAtTime() {}
          setTargetAtTime(v) { this.value = v; } cancelScheduledValues() {} }
class N { constructor() { this.gain = new P(); this.frequency = new P(); } connect() {} start() {} stop() {} }
globalThis.AudioContext = class { constructor() { this.state = "running"; this.currentTime = 0; this.destination = {}; }
  createGain() { return new N(); } createOscillator() { made.osc++; return new N(); } createBiquadFilter() { return new N(); }
  resume() { return Promise.resolve(); } close() { made.closed++; return Promise.resolve(); } };
"""


def sound(script: str):
    return node(f"""
import {{ createRequire }} from "module";
{FAKE_AUDIO}
const S = createRequire(import.meta.url)({json.dumps(str(STATIC / "avatar-sound.js"))});
const out = {{}};
{script}
console.log(JSON.stringify(out));
""")


def test_sound_is_off_by_default_ducks_for_speech_and_limits_repeats():
    out = sound("""
out.default = [S.enabled, S.cue("confirm"), made.osc];        // off: nothing created, nothing plays
S.setEnabled(true); out.on = [S.enabled, S.running];
out.first = S.cue("confirm"); out.again = S.cue("confirm");     // the same cue twice in a row: once
out.unknown = S.cue("explosion");
S.duck(true); out.ducked = S.cue("deny"); S.duck(false); out.after = S.cue("deny");
out.attention = [S.cue("attention"), S.cue("attention")];
S.setEnabled(false); out.off = [S.enabled, S.running, made.closed, S.cue("learn")];
""")
    assert out["default"] == [False, False, 0]
    assert out["on"] == [True, True] and out["first"] is True and out["again"] is False and out["unknown"] is False
    assert out["ducked"] is False and out["after"] is True                  # no tones while JARVIS speaks or you record
    assert out["attention"] == [True, False]
    assert out["off"] == [False, False, 1, False]                         # off releases the audio device
    events_sounds = set(re.findall(r'sound: "(\w+)"', EVENTS))
    assert events_sounds <= set(re.findall(r"^    (\w+): +\[\[", SOUND, re.M))   # every cue in the map exists
    for forbidden in ("fetch(", "new Audio(", ".mp3", ".wav", ".ogg", "getUserMedia", "localStorage"):
        assert forbidden not in SOUND, forbidden                          # generated here; never listens or stores


def test_sound_setting_is_per_device_off_by_default_and_not_in_presets():
    assert 'sound: [["off", "Off"], ["on", "On"]] };' in JS and 'diag: "off", sound: "off" };' in JS
    assert '"sound"' not in PRESETS                                       # applying a preset never turns sound on
    assert 'if (EV && window.JarvisSound && !smOut.preview && av.cueReady) window.JarvisSound.cue(EV.soundOf(state));' in AV
    assert "u.onstart = () => { core.dataset.speaking = \"1\"; duckSound(); };" in JS


def test_microphone_level_is_measured_locally_and_stops_with_the_recording():
    mic = re.search(r"function startMicLevel\(.*?\n\}\n", JS, re.S).group(0)
    assert "createMediaStreamSource(stream).connect(an)" in mic and "destination" not in mic   # never played back
    assert "Math.sqrt(sum / buf.length)" in mic and "fetch(" not in mic and "api(" not in mic  # RMS, kept on the page
    stop = re.search(r"function stopMicLevel\(.*?\n\}\n", JS, re.S).group(0)
    assert "voice.level.ctx.close()" in stop and "JarvisAvatar.voiceLevel(0)" in stop
    assert "async function finishRecording(type) {\n  clearInterval(voice.timer);\n  stopMicLevel();" in JS
    assert 'const x = mode === "off" ? 0 :' in AV3                         # Reduced motion: no voice motion
    assert "voice * 0.9" in AV3 and "voice * 0.8" in AV3                  # reactor and sensors follow it
