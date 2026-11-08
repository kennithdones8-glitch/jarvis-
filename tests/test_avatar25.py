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
