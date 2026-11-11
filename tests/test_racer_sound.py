"""Kerbside Grand Prix audio and polish (phase 7): a race announcer built on the browser's own speech (free, no
assets) that you can switch off, that never talks over a more important line and goes quiet when paused or muted;
crowd reactions; a distinct sound for each kind of menu action; and the announcer heard in a real browser race."""

import json
import shutil
import subprocess

import pytest

from jarvis.server.app import STATIC

NODE = shutil.which("node")
ROOT = STATIC.parents[3]

FAKE = r"""
const log = { said: [], cancels: 0, tones: [] };
const param = () => ({ value: 0, setValueAtTime(v) { this.value = v; }, setTargetAtTime() {}, exponentialRampToValueAtTime() {}, linearRampToValueAtTime() {} });
const node = (k) => ({ kind: k, connect() {}, start() {}, stop() {}, gain: param(), frequency: { ...param(), setValueAtTime(v) { log.tones.push(k + ":" + Math.round(v)); } }, Q: param(), type: "", curve: null, buffer: null });
globalThis.AudioContext = class { constructor() { this.currentTime = 0; this.state = "running"; this.sampleRate = 8000; this.destination = node("d"); }
  createGain() { return node("gain"); } createBiquadFilter() { return node("filter"); } createWaveShaper() { return node("shaper"); } createOscillator() { return node("osc"); }
  createBufferSource() { return node("src"); } createBuffer(c, n) { const d = new Float32Array(n); return { getChannelData: () => d }; } resume() {} close() {} };
globalThis.setInterval = () => 1; globalThis.clearInterval = () => {};
globalThis.speechSynthesis = { speak(u) { log.said.push(u.text); }, cancel() { log.cancels++; }, getVoices() { return [{ lang: "en-US", name: "us" }, { lang: "en-GB", name: "gb" }]; } };
globalThis.SpeechSynthesisUtterance = class { constructor(t) { this.text = t; } };
let now = 1e6; Date.now = () => now;
"""


def js(code: str, fake=True):
    if not NODE:
        pytest.skip("node not installed")
    pre = (FAKE if fake else "") + (f"const A = require({json.dumps(str(STATIC / 'racer-audio.js'))}), C = require({json.dumps(str(STATIC / 'racer-career.js'))});\n")
    out = subprocess.run([NODE, "-e", pre + code], capture_output=True, text=True, timeout=120, check=True)
    return json.loads(out.stdout)


def test_the_announcer_knows_when_to_talk():
    r = js("""
const a = A.create(); a.unlock();
const said = (t, p) => { a.say(t, p); return log.said.at(-1); };
const first = said("Lights out!", 2), talkedOver = (a.say("Rain.", 1), log.said.length);   // less important: waits
const urgent = said("Photo finish!", 3);                                                // more important: interrupts
now += 10000; const later = said("Rain.", 1);
a.settings({ announcer: false }); now += 10000; const off = (a.say("Hello", 3), log.said.length);
a.settings({ announcer: true, sound: false }); now += 10000; const muted = (a.say("Hello", 3), log.said.length);
a.settings({ sound: true }); a.pause(true); now += 10000; const paused = (a.say("Hello", 3), log.said.length); a.pause(false);
now += 10000; const back = said("Back!", 1);
console.log(JSON.stringify({ first, talkedOver, urgent, later, off, muted, paused, back, cancels: log.cancels, can: a.canSpeak }));""")
    assert r["first"] == "Lights out!" and r["talkedOver"] == 1 and r["urgent"] == "Photo finish!" and r["later"] == "Rain."
    assert r["off"] == r["muted"] == r["paused"] == 3 and r["back"] == "Back!"
    assert r["cancels"] >= 3 and r["can"] is True                      # interrupting, switching off and pausing all stop speech


def test_no_speech_means_no_announcer_control():
    r = js("""
delete globalThis.speechSynthesis;
const a = A.create(); a.unlock(); const none = A.create.length >= 0 && a.canSpeak;
console.log(JSON.stringify({ none, safe: a.say("x", 3) === false }));""")
    assert r["none"] is False and r["safe"]
    r = js("""const a = A.create(); console.log(JSON.stringify({ noAudio: a.canSpeak === true }));""", fake=False)
    assert r["noAudio"] is False                                         # no Web Audio at all: the setting stays hidden


def test_crowd_and_menu_sounds_are_each_their_own():
    r = js("""
const a = A.create(); a.unlock();
const hear = (f) => { log.tones.length = 0; f(); return log.tones.join(","); };
const ui = ["confirm", "back", "buy", "error", "unlock", "achievement"].map((k) => hear(() => a.ui(k)));
const crowd = ["cheer", "gasp", "ooh"].map((k) => hear(() => a.crowd(k)));
console.log(JSON.stringify({ ui: [new Set(ui).size, ui.every((x) => x.length)], crowd: [new Set(crowd).size, crowd.every((x) => x.length)] }));""")
    assert r["ui"] == [6, True] and r["crowd"] == [3, True]


def test_the_announcer_setting_saves_and_old_saves_keep_it_on():
    r = js("""
const s = C.fresh(); const def = s.settings.announcer; s.settings.announcer = false;
const back = C.importSave(C.exportSave(s)).save.settings.announcer;
const old = JSON.parse(JSON.stringify(C.fresh())); delete old.settings.announcer;
console.log(JSON.stringify({ def, back, old: C.validate(old).save.settings.announcer, junk: C.validate({ ...old, settings: { ...old.settings, announcer: "loud" } }).save.settings.announcer }));""")
    assert r == {"def": True, "back": False, "old": True, "junk": True}


BROWSER = r"""
const { chromium } = require(process.env.PW || 'playwright');
(async () => {
  const b = await chromium.launch(); const errs = [];
  const p = await (await b.newContext({ viewport: { width: 1000, height: 640 } })).newPage(); p.on('pageerror', (e) => errs.push(e.message));
  await p.addInitScript(() => { window.__said = []; Object.defineProperty(window, 'speechSynthesis', { configurable: true, value: { speak(u) { window.__said.push(u.text); }, cancel() {}, getVoices() { return []; } } });
    window.SpeechSynthesisUtterance = class { constructor(t) { this.text = t; } }; });
  await p.goto('file://' + process.argv[2]); await p.waitForTimeout(500);
  await p.evaluate(() => { const V = window.JarvisRacer.view; V.overlay(null); const a = window.KerbsideAudio.create({ sound: true, announcer: true }); a.unlock();
    V.start({ track: 'kerbside', time: 'day', weather: 'dry', mode: 'circuit', laps: 2, field: [{ id: 'a', code: 'AAA', name: 'Ada', color: '#2f7de1', shape: 'super' }, { id: 'b', code: 'BBB', name: 'Bo', color: '#1d9a6c', shape: 'rally' }] }, {});
    V.setAudio(a); });
  await p.waitForFunction(() => window.__said.some((x) => /win|podium|flag/i.test(x)), null, { timeout: 240000 }).catch(() => errs.push('no finish line'));
  console.log(JSON.stringify({ said: await p.evaluate(() => window.__said), errs })); await b.close();
})();
"""


def test_the_announcer_calls_a_real_race_in_the_browser(tmp_path):
    if not NODE:
        pytest.skip("node not installed")
    if subprocess.run([NODE, "-e", "require.resolve('playwright')"], capture_output=True).returncode:
        pytest.skip("Playwright isn't installed (browser checks are optional)")
    site = tmp_path / "site"
    site.mkdir()
    shutil.copy(ROOT / "games/kerbside/index.html", site / "index.html")
    for f in STATIC.glob("racer*"):
        shutil.copy(f, site / f.name)
    shutil.copytree(STATIC / "fonts", site / "fonts")
    # test copy only: the computer drives your car so the race finishes on its own
    rj = (site / "racer.js").read_text()
    assert rj.count("        else inp = you;") == 1
    (site / "racer.js").write_text(rj.replace("        else inp = you;", "        else inp = { ...aiInput(race, c), nitro: c.aiBoost };"))
    script = tmp_path / "check.js"
    script.write_text(BROWSER)
    out = subprocess.run([NODE, str(script), str(site / "index.html")], capture_output=True, text=True, timeout=330, cwd=tmp_path)
    assert out.returncode == 0, out.stderr[-2000:]
    r = json.loads(out.stdout.strip().splitlines()[-1])
    assert r["errs"] == [], r
    s = r["said"]
    assert s[0] == "Lights out, and away they go!" and any(x.startswith("Final lap") for x in s), s
    assert any(x in ("And it's a win!", "P2. A podium finish.", "P3. A podium finish.") for x in s), s
