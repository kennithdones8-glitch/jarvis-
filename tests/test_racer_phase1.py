"""Kerbside Grand Prix quality overhaul, phase 1: the story slice (the staged callout, grudge matches that quote
what happened, Benny's bet with consequences that last) runs on real game state and survives a save; and the new
graphics draw every car body, every track, every time of day, weather and quality level in a real browser without
errors (skipped when Playwright isn't installed)."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from jarvis.server.app import STATIC

NODE = shutil.which("node")
ROOT = Path(__file__).resolve().parents[1]


def js(code: str, timeout=120):
    if not NODE:
        pytest.skip("node not installed")
    pre = (f"const C = require({json.dumps(str(STATIC / 'racer-career.js'))}), D = require({json.dumps(str(STATIC / 'racer-data.js'))});\n"
           "const sum = (o) => ({ mode: 'rival', track: 'kerbside', laps: 3, place: 1, of: 2, finished: true, eliminated: false, total: 70, best: 22, lapTimes: [24, 23, 22], drift: 0, contacts: 0, damage: 0,"
           " order: ['YOU', 'dex'], beat: ['dex'], rivals: { dex: { passedThem: 0, passedYou: 0, contacts: 0, youHit: 0, theyHit: 0, gap: 1, close: false } }, ...o });\n"
           "let n = 0; const race = (s, o, kind = 'side', ev = { id: 'e', title: 'T', tier: 2, goal: { type: 'place', max: 3 } }) => C.applyResult(s, { kind, event: ev, raceId: 'r' + (++n) }, sum(o));\n")
    out = subprocess.run([NODE, "-e", pre + code], capture_output=True, text=True, timeout=timeout, check=True)
    return json.loads(out.stdout)


def test_the_callout_is_a_staged_scene_with_a_motive():
    r = js("""
const m = C.mission("c1-callout"), s = C.fresh(), cfg = C.config(s, m, "story");
const speakers = [...new Set(m.intro.map((l) => l[0]))];
console.log(JSON.stringify({ scene: m.scene, focusInField: cfg.field.some((d) => d.id === m.scene.focus), lines: m.intro.length, speakers,
  faces: Object.keys(D.CAST).filter((k) => !D.CAST[k].face), allStory: [...new Set(D.CHAPTERS.flatMap((c) => c.missions.flatMap((x) => [...x.intro, ...x.win, ...x.lose].map((l) => l[0]))))].filter((k) => !(D.CAST[k] && D.CAST[k].face)) }));""")
    assert r["scene"]["focus"] == "dex" and r["focusInField"] and r["lines"] >= 6 and {"nia", "dex", "jarvis"} <= set(r["speakers"])
    assert r["faces"] == [] and r["allStory"] == []       # every speaker has a drawn portrait


def test_a_grudge_match_quotes_the_history_and_its_result_lasts():
    r = js("""
const s = C.fresh(); s.story.done["c1-callout"] = true;
const hit = { dex: { passedThem: 0, passedYou: 0, contacts: 2, youHit: 2, theyHit: 0, gap: 1, close: false } };
const a = race(s, { rivals: hit }); const before = C.rivalEvents(s).filter((e) => e.grudge).length;
const b = race(s, { rivals: { dex: { ...hit.dex, contacts: 1, youHit: 0, theyHit: 1 } } });
const g = C.rivalEvents(s).find((e) => e.grudge === "dex");
const respect0 = s.rivals.dex.respect, out = race(s, {}, "rival", g);
const after = C.rivalEvents(s).filter((e) => e.grudge).length;
const later = C.lines(s, C.mission("c4-fog").intro).map((l) => l.text);
const lost = C.fresh(); lost.story.flags.grudge_dex_offered = true; const g2 = C.rivalEvents(lost).find((e) => e.grudge === "dex");
race(lost, { place: 2, order: ["dex", "YOU"], beat: [] }, "rival", g2);
const back = C.importSave(C.exportSave(s)).save.story.flags;
console.log(JSON.stringify({ before, offer: b.reactions[0], g: g && { id: g.id, track: g.track, mode: g.mode }, won: [s.story.flags.grudge_dex_won, s.rivals.dex.respect - respect0, out.lines[0].text], after, later,
  lostFlags: [lost.story.flags.grudge_dex_lost, C.lines(lost, C.mission("c4-fog").intro).some((l) => l.text.includes("owe you for the harbour"))], back: back.grudge_dex_won }));""")
    assert r["before"] == 0                                                     # two contacts: not yet
    assert r["offer"]["kind"] == "grudge" and "3 times we've traded paint, and 2 of them were you" in r["offer"]["text"]
    assert r["g"] == {"id": "g-dex", "track": "harbour", "mode": "rival"}
    assert r["won"][0] is True and r["won"][1] >= 3 and "stop trying" in r["won"][2] and r["after"] == 0
    assert any("check my mirrors" in t for t in r["later"])                     # Dex's later line changes
    assert r["lostFlags"] == [True, True] and r["back"] is True                 # and it's saved


def test_benny_s_bet_has_consequences_that_last():
    r = js("""
const paid = C.fresh(); paid.districts.push("oldtown"); paid.rep = 200; const inf0 = C.influence(paid, "oldtown");
const p = C.choose(paid, "c3-bet", 0);
const kind = C.fresh(); kind.districts.push("oldtown"); kind.rep = 200; const k = C.choose(kind, "c3-bet", 1);
const benny = (s, id) => C.config(s, C.mission(id), "story").field.find((d) => d.id === "benny").personality;
const charity = (s) => C.sideEvents(s).some((e) => e.id === "s-old-charity");
const ev = D.SIDE.find((e) => e.id === "s-old-charity"); const resp0 = (kind.rivals.benny || {}).respect || 0;
C.applyResult(kind, { kind: "side", event: ev, raceId: "c1" }, { mode: "sprint", track: "oldtown", laps: 1, place: 1, of: 4, finished: true, eliminated: false, total: 30, best: 30, lapTimes: [30], drift: 0, contacts: 0, damage: 0, order: ["YOU", "benny", "pip", "mara"], beat: ["benny", "pip", "mara"], rivals: {} });
const lines = (s) => C.lines(s, C.mission("c5-qualifier").intro).map((l) => l.text);
const back = C.importSave(C.exportSave(paid)).save;
console.log(JSON.stringify({ infl: [inf0, C.influence(paid, "oldtown")], cons: [p.consequence, k.consequence], benny: [benny(paid, "c4-fog"), benny(kind, "c4-fog"), benny(paid, "c3-bet")],
  charity: [charity(paid), charity(kind)], resp: kind.rivals.benny.respect - resp0, lines: [lines(paid), lines(kind)], back: [back.story.flags.benny_paid, C.influence(back, "oldtown")] }));""")
    assert r["infl"][1] == r["infl"][0] - 10
    assert "Old Town turns against you" in r["cons"][0] and "charity sprint" in r["cons"][1]
    assert r["benny"][0] == "aggressive" and r["benny"][1] != "aggressive" and r["benny"][2] != "aggressive"   # not in a 1-on-1
    assert r["charity"] == [False, True] and r["resp"] >= 2
    assert any("Hard feelings" in t for t in r["lines"][0]) and not any("Hard feelings" in t for t in r["lines"][1])
    assert r["back"][0] is True and r["back"][1] == r["infl"][1]


def test_every_car_body_has_art_and_lights():
    src = (STATIC / "racer-render.js").read_text()
    r = js("console.log(JSON.stringify([...new Set(Object.values(D.CARS).map((c) => c.shape))]))")
    body = src[src.index("const BODY = {"):src.index("// a smooth closed outline")]
    for shape in r:
        assert f"\n      {shape}: {{ o: [" in body, shape
    assert body.count("wheels: {") == len(r) and body.count("glass: {") == len(r)   # one body per style in use


BROWSER = r"""
const { chromium, devices } = require(process.env.PW || 'playwright');
const page = process.argv[2];
(async () => {
  const b = await chromium.launch(); const errs = [], out = {};
  const p = await (await b.newContext({ viewport: { width: 1000, height: 640 } })).newPage();
  p.on('pageerror', (e) => errs.push(e.message)); p.on('console', (m) => m.type() === 'error' && errs.push(m.text()));
  await p.goto('file://' + page); await p.waitForTimeout(500);
  out.cars = await p.evaluate(() => {   // every body, every look option, damaged, lit, braking, boosting
    const D = window.KerbsideData, cv = document.createElement('canvas'); cv.width = 400; cv.height = 400; const g = cv.getContext('2d'); let n = 0;
    for (const shape of [...new Set(Object.values(D.CARS).map((c) => c.shape))]) for (const sp of ['none', 'low', 'high', 'duck']) for (const fin of ['gloss', 'metallic', 'matte', 'pearl']) {
      window.JarvisRacer.drawCar(g, { x: 200, y: 200, a: 0.3, shape, color: '#d23c3c', num: 7, id: 'x' + n, look: { paint: '#d23c3c', spoiler: sp, finish: fin, decal: 'stripe', body: n % 2 ? 'wide' : 'none', exhaust: 'quad' }, steerIn: 0.5, dmg: (n % 5) / 4, brakeOn: true, boost: true }, { lights: true }); n++;
    }
    return n;
  });
  out.shapes = await p.evaluate(() => new Set(Object.values(window.KerbsideData.CARS).map((c) => c.shape)).size);
  const scenes = [];
  for (const track of ['kerbside', 'harbour', 'ridge', 'oldtown']) for (const [time, weather] of [['day', 'dry'], ['night', 'rain'], ['dusk', 'fog'], ['dawn', 'dry']]) scenes.push([track, time, weather]);
  out.frames = 0;
  for (const [i, [track, time, weather]] of scenes.entries()) {
    out.frames += await p.evaluate(async ([track, time, weather, q]) => {
      const V = window.JarvisRacer.view; V.applySettings({ quality: q }); V.overlay(null);
      V.start({ track, time, weather, mode: 'circuit', laps: 3, field: [{ id: 'a', code: 'AAA', name: 'A', color: '#2f7de1', shape: 'super' }, { id: 'b', code: 'BBB', name: 'B', color: '#1d9a6c', shape: 'rally' }] }, {});
      return await new Promise((res) => { let n = 0; const f = () => { if (++n < 20) requestAnimationFrame(f); else res(n); }; requestAnimationFrame(f); });
    }, [track, time, weather, ['low', 'medium', 'high', 'auto'][i % 4]]);
  }
  const ph = await (await b.newContext({ ...devices['iPhone 13'] })).newPage();
  ph.on('pageerror', (e) => errs.push('phone: ' + e.message));
  await ph.goto('file://' + page); await ph.waitForTimeout(500);
  out.phoneOverflow = await ph.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  await ph.getByRole('button', { name: 'Garage', exact: true }).click(); await ph.waitForTimeout(400);
  out.studio = await ph.evaluate(() => { const c = document.querySelector('.race-preview'); return c ? [c.width, c.height, c.getBoundingClientRect().width <= window.innerWidth] : null; });
  console.log(JSON.stringify({ ...out, errs })); await b.close();
})();
"""


def test_the_graphics_draw_everything_in_a_real_browser(tmp_path):
    if not NODE:
        pytest.skip("node not installed")
    probe = subprocess.run([NODE, "-e", "require.resolve('playwright')"], capture_output=True, text=True)
    if probe.returncode:
        pytest.skip("Playwright isn't installed (browser checks are optional)")
    # the standalone page with the current game files
    site = tmp_path / "site"
    site.mkdir()
    shutil.copy(ROOT / "games/kerbside/index.html", site / "index.html")
    for f in STATIC.glob("racer*"):
        shutil.copy(f, site / f.name)
    shutil.copytree(STATIC / "fonts", site / "fonts")
    script = tmp_path / "check.js"
    script.write_text(BROWSER)
    out = subprocess.run([NODE, str(script), str(site / "index.html")], capture_output=True, text=True, timeout=300, cwd=tmp_path)
    assert out.returncode == 0, out.stderr[-2000:]
    r = json.loads(out.stdout.strip().splitlines()[-1])
    assert r["errs"] == [], r["errs"]
    assert r["cars"] == r["shapes"] * 16 and r["frames"] == 16 * 20
    assert r["phoneOverflow"] is False and r["studio"][:2] == [720, 400] and r["studio"][2]
