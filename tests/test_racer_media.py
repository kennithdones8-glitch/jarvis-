"""Kerbside Grand Prix sound, replay and photo mode. The sound module runs here against a stand-in Web Audio context
(Node has none): every call works, every car body has an engine voice, the turbo blows off when you lift, the music
adds drums once you race, and sirens follow the pursuit. The replay viewer and photo mode draw on a real canvas, so
they're checked in a browser by hand; these tests pin their wiring."""

import json
import re
import shutil
import subprocess

import pytest

from jarvis.server.app import STATIC

NODE = shutil.which("node")

FAKE_AUDIO = r"""
const log = { osc: 0, src: 0, targets: [], freq: [] };
const param = (name) => ({ value: 0, setValueAtTime(v) { this.value = v; }, setTargetAtTime(v) { this.value = v; log.targets.push([name, v]); }, exponentialRampToValueAtTime() {}, linearRampToValueAtTime() {} });
const node = (kind) => ({ kind, connect() {}, disconnect() {}, start() {}, stop() {}, gain: param(kind + ".gain"), frequency: param(kind + ".frequency"), Q: param("Q"), type: "", curve: null, buffer: null, loop: false });
class AC {
  constructor() { this.currentTime = 0; this.state = "running"; this.sampleRate = 8000; this.destination = node("dest"); globalThis.lastAC = this; }
  createGain() { return node("gain"); } createBiquadFilter() { return node("filter"); } createWaveShaper() { return node("shaper"); }
  createOscillator() { log.osc++; return node("osc"); } createBufferSource() { log.src++; return node("src"); }
  createBuffer(c, n) { const d = new Float32Array(n); return { getChannelData: () => d }; } resume() {} close() {}
}
globalThis.AudioContext = AC; globalThis.setInterval = () => 1; globalThis.clearInterval = () => {};
"""


def js(code: str):
    if not NODE:
        pytest.skip("node not installed")
    pre = FAKE_AUDIO + f"const A = require({json.dumps(str(STATIC / 'racer-audio.js'))}), D = require({json.dumps(str(STATIC / 'racer-data.js'))});\n"
    out = subprocess.run([NODE, "-e", pre + code], capture_output=True, text=True, timeout=60, check=True)
    return json.loads(out.stdout)


def test_every_car_has_an_engine_voice_and_every_call_works():
    r = js("""
const a = A.create({ sound: true, music: true, volume: 0.5 }); a.unlock();
const shapes = [...new Set(Object.values(D.CARS).map((c) => c.shape))], missing = shapes.filter((s) => !A.VOICES[s]);
for (const s of shapes) { a.voice(s); a.update({ speed: 300, top: 650, slip: 120, boost: true, on: true, thr: true, turbo: 0.3, wet: 1, crowd: 1 }); }
for (const f of ["raceStart", "go", "lap", "pop", "whoosh", "shift", "radio", "click", "idle"]) a[f]();
a.impact(300); a.finish(true); a.finish(false); a.beep(3); a.siren(0.8); a.music("pursuit", 2); a.pause(true); a.pause(false); a.update(null); a.settings({ sound: false }); a.stop();
const none = (() => { delete globalThis.AudioContext; const b = A.create(); b.unlock(); b.update({ speed: 1 }); b.siren(1); b.radio(); return "ok"; })();
console.log(JSON.stringify({ shapes: shapes.length, missing, none }));""")
    assert r["missing"] == [] and r["shapes"] >= 12 and r["none"] == "ok"


def test_engine_pitch_follows_the_voice_and_the_turbo_blows_off():
    r = js("""
const a = A.create(); a.unlock();
const pitch = (shape) => { a.voice(shape); log.targets.length = 0; a.update({ speed: 200, top: 650, slip: 0, on: true, thr: true }); return log.targets.find(([n]) => n === "osc.frequency")[1]; };
const kei = pitch("kei"), muscle = pitch("muscle");
// lift off with the turbo spooled: one blow-off burst (a noise source); without a turbo, none
a.voice("rally"); for (let i = 0; i < 60; i++) a.update({ speed: 400, top: 650, slip: 0, on: true, thr: true, turbo: 0.4 });
let s0 = log.src; a.update({ speed: 400, top: 650, slip: 0, on: true, thr: false, turbo: 0.4 }); const blowoff = log.src - s0;
const b = A.create(); b.unlock(); b.voice("rally"); for (let i = 0; i < 60; i++) b.update({ speed: 400, top: 650, slip: 0, on: true, thr: true, turbo: 0 });
s0 = log.src; b.update({ speed: 400, top: 650, slip: 0, on: true, thr: false, turbo: 0 }); const none = log.src - s0;
// rain hiss off in the tunnel
log.targets.length = 0; a.update({ speed: 100, top: 650, slip: 0, on: true, thr: true, wet: 1, tunnel: true });
console.log(JSON.stringify({ kei, muscle, blowoff, none }));""")
    assert r["kei"] > r["muscle"] * 1.5          # a buzzy kei car sits far above a V8
    assert r["blowoff"] == 1 and r["none"] == 0


def test_music_adds_drums_when_racing_and_the_siren_follows_the_pursuit():
    r = js("""
let tick = null; globalThis.setInterval = (fn) => { tick = fn; return 1; };
const a = A.create(); a.unlock(); const ac = globalThis.lastAC;
const bar = () => { const s0 = log.src; for (let i = 0; i < 80; i++) { ac.currentTime += 0.03; tick(); } return log.src - s0; };   // ~2.4 s of music
const menu = bar(); a.raceStart(); const race = bar(); a.music(null, 2); const finalLap = bar();
log.targets.length = 0; a.siren(0); const quiet = log.targets.filter(([n]) => n === "gain.gain").map(([, v]) => v);
log.targets.length = 0; a.siren(1); const loud = log.targets.filter(([n]) => n === "gain.gain").map(([, v]) => v);
console.log(JSON.stringify({ menu, race, finalLap, quiet, loud }));""")
    assert r["menu"] == 0                         # menus: bass and arpeggio only (no noise drums)
    assert r["race"] >= 8                         # racing: hi-hats on the off-beats (about 9 in 2.4 s at 112 bpm)
    assert r["finalLap"] > r["race"]              # the final lap adds a snare
    assert r["quiet"] == [0] and r["loud"][0] > 0


def test_replay_and_photo_mode_are_wired_up():
    render = (STATIC / "racer-render.js").read_text()
    ui = (STATIC / "racer-ui.js").read_text()
    # the recorder, the viewer, its cameras, highlights and the photo tools
    for needle in ("function record(", "function replay(", "function applyFrame(", "function photo(", "function savePhoto(", "toBlob(", "image/png",
                   'tv: "Trackside"', 'heli: "Helicopter"', 'orbit: "Orbit"', "noir:", "vintage:", "Hide cars", "Save image", "Highlights"):
        assert needle in render, needle
    assert re.search(r"replay: \(onExit\) =>", render) and "get canReplay()" in render and re.search(r"photo: \(onExit\) =>", render)
    assert "Watch replay" in ui and "Photo mode" in ui
    # recorded in memory only: no storage, no network
    block = render[render.index("// ---------------------------------------------------------------- Replay and photo mode"):render.index("// ---------------------------------------------------------------- Fallback start card")]
    for banned in ("localStorage", "fetch(", "XMLHttpRequest"):
        assert banned not in block
