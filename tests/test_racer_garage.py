"""Kerbside Grand Prix garage (racer-data.js cars and tuning, racer-career.js carStats, racer.js physics): the roster
is genuinely varied, upgrades and tuning presets make measurable differences, turbo lag and weight are real, unlock
rules and repairs work, and the expanded looks survive a save."""

import json
import shutil
import subprocess

import pytest

from jarvis.server.app import STATIC

NODE = shutil.which("node")


def js(code: str, timeout=240):
    if not NODE:
        pytest.skip("node not installed")
    pre = (f"const R = require({json.dumps(str(STATIC / 'racer.js'))}), C = require({json.dumps(str(STATIC / 'racer-career.js'))}),"
           f" D = require({json.dumps(str(STATIC / 'racer-data.js'))});\n"
           "const lap = (spec, track, laps = 2, drive = null) => { const r = R.newRace({ track, mode: 'timetrial', laps, player: { spec } }); let t = 0;"
           " while (!r.cars[0].done && t < 200) { R.step(r, 1 / 120, drive ? drive(r) : null); t += 1 / 120; } return { t: r.cars[0].finish, laps: r.cars[0].lapTimes, drift: 0 }; };\n"
           "const tuned = (id, tune, up = {}) => C.carStats(id, { upgrades: up, tune });\n")
    out = subprocess.run([NODE, "-e", pre + code], capture_output=True, text=True, timeout=timeout, check=True)
    return json.loads(out.stdout)


def test_the_roster_is_big_varied_and_every_car_is_different():
    r = js("""
const cars = Object.entries(D.CARS), sig = new Set(), shapes = new Set(), cats = new Set(), byCls = {};
for (const [id, c] of cars) { sig.add([c.acc, c.drag, c.grip, c.brake, c.steer, c.mass, c.slide || 0, c.turbo || 0, c.wet || 0, c.offroad || 0].join()); shapes.add(c.shape); cats.add(c.cat); }
for (const [id, c] of cars) if (!c.police && c.price !== null) (byCls[c.cls] = byCls[c.cls] || []).push(lap(C.carStats(id, C.carState(id)), "ridge").laps[1]);
const avg = Object.fromEntries(Object.entries(byCls).map(([k, v]) => [k, v.reduce((a, b) => a + b, 0) / v.length]));
console.log(JSON.stringify({ n: cars.length, buy: cars.filter(([, c]) => !c.police && c.price !== null).length, unique: sig.size, shapes: shapes.size, cats: cats.size, avg }));""")
    assert r["n"] >= 28 and r["buy"] >= 26 and r["unique"] == r["n"]      # no two cars share a stat sheet
    assert r["shapes"] >= 12 and r["cats"] >= 10
    a = r["avg"]
    assert a["C"] > a["B"] > a["A"] > a["S"]                              # classes really are tiers of pace


def test_tuning_presets_make_measurable_differences():
    r = js("""
// top speed on an endless straight: the car is held on one point of the road (no corner ever cuts the run short)
const P = D.PRESETS, top = (spec) => { const r = R.newRace({ track: "harbour", mode: "timetrial", laps: 1, player: { spec } }); r.state = "race"; let best = 0; const me = r.cars[0];
  for (let i = 0; i < 120 * 40; i++) { me.a = r.trk.ANG[me.idx]; me.x = r.trk.P[me.idx][0]; me.y = r.trk.P[me.idx][1]; R.step(r, 1 / 120, { steer: 0, thr: true, brk: false, nitro: false }); best = Math.max(best, me.fwd); } return best; };
// the same flick at the same speed: how big a slide it makes, and how long the slide lasts above the drift threshold
const slide = (spec) => { const r = R.newRace({ track: "harbour", mode: "drift", laps: 1, player: { spec } }); r.state = "race"; const me = r.cars[0];
  me.a = r.trk.ANG[me.idx]; me.vx = Math.cos(me.a) * 420; me.vy = Math.sin(me.a) * 420; let peak = 0, held = 0;
  for (let i = 0; i < 120 * 1.2; i++) { R.step(r, 1 / 120, { steer: i < 50 ? 1 : 0, thr: true, brk: false, nitro: false }); peak = Math.max(peak, me.slip); if (me.slip > 70) held += 1 / 120; }
  return { peak, held }; };
const kes = (k) => tuned("kestrel", P[k]);
console.log(JSON.stringify({ topDrag: top(kes("drag")), topSprint: top(kes("sprint")), ridgeGrip: lap(kes("grip"), "ridge").laps[1], ridgeDrift: lap(kes("drift"), "ridge").laps[1],
  slideDrift: slide(kes("drift")), slideGrip: slide(kes("grip")),
  wetRain: lap(tuned("kestrel", P.wet), "oldtown").t, wetSoft: (() => { const r = R.newRace({ track: "oldtown", mode: "timetrial", laps: 2, weather: "rain", player: { spec: kes("grip") } }); let t = 0; while (!r.cars[0].done && t < 200) { R.step(r, 1 / 120, null); t += 1 / 120; } return r.cars[0].finish; })(),
  wetRainInRain: (() => { const r = R.newRace({ track: "oldtown", mode: "timetrial", laps: 2, weather: "rain", player: { spec: kes("wet") } }); let t = 0; while (!r.cars[0].done && t < 200) { R.step(r, 1 / 120, null); t += 1 / 120; } return r.cars[0].finish; })() }));""")
    assert r["topDrag"] > r["topSprint"] * 1.03                           # tall gearing: higher top speed
    assert r["ridgeGrip"] < r["ridgeDrift"]                               # grip tune is quicker round the switchbacks
    sd, sg = r["slideDrift"], r["slideGrip"]
    assert sd["peak"] > sg["peak"] * 1.15 and sd["held"] > sg["held"] * 1.3   # ...but the drift tune slides bigger and longer
    assert r["wetRainInRain"] < r["wetSoft"]                              # rain tyres beat soft tyres in the wet


def test_upgrades_turbo_lag_and_weight_are_real():
    r = js("""
const base = C.carStats("kestrel", C.carState("kestrel")), turbo = C.carStats("kestrel", { upgrades: { turbo: 3 }, tune: {} });
const speedAt = (spec, s) => { const r = R.newRace({ track: "harbour", mode: "timetrial", laps: 1, player: { spec } }); r.state = "race"; for (let i = 0; i < 120 * s; i++) R.step(r, 1 / 120, { steer: R.aiInput(r, r.cars[0]).steer, thr: true, brk: false, nitro: false }); return r.cars[0].fwd; };
// weight: a heavy car and a light car meet head-on at the same speed; the light one is thrown back harder
const r = R.newRace({ track: "kerbside", field: [{ code: "L", spec: { ...R.BASE_SPEC, mass: 0.75 } }], player: { spec: { ...R.BASE_SPEC, mass: 1.5 } } });
r.state = "race"; const [h, l] = r.cars; l.x = h.x + 30; l.y = h.y; h.vx = 200; h.vy = 0; l.vx = -200; l.vy = 0;
R.step(r, 1 / 120, { steer: 0, thr: false, brk: false });
const all = C.carStats("pacer", { upgrades: { engine: 3, turbo: 3, ecu: 3, tires: 3, brakes: 3, suspension: 3, weight: 3, aero: 3, nitro: 3 }, tune: {} });
console.log(JSON.stringify({ early: [speedAt(base, 0.25), speedAt(turbo, 0.25)], late: [speedAt(base, 2), speedAt(turbo, 2)], heavyV: h.vx, lightV: l.vx,
  mass: [C.carStats("pacer", C.carState("pacer")).mass, all.mass], lapStock: lap(C.carStats("pacer", C.carState("pacer")), "ridge").laps[1], lapAll: lap(all, "ridge").laps[1] }));""")
    early, late = r["early"], r["late"]
    assert early[1] / early[0] < late[1] / late[0]                        # the turbo's advantage grows once it spools
    assert late[1] > late[0]
    assert abs(r["lightV"]) > abs(r["heavyV"]) and r["lightV"] > 0         # the light car bounces back harder
    assert r["mass"][1] < r["mass"][0] and r["lapAll"] < r["lapStock"] * 0.92


def test_unlock_rules_repairs_and_persistent_damage():
    r = js("""
const s = C.fresh(); s.money = 1e6;
const a = [C.carAvailable(s, "vela").ok, C.buyCar(s, "vela").ok]; s.story.chapter = 2;
const b = [C.carAvailable(s, "vela").ok, C.buyCar(s, "vela").ok, C.carAvailable(s, "ironclad").why];
s.rivals.dex = { ...s.rivals.dex, wins: 3 }; const c = C.carAvailable(s, "ironclad").ok;
const police = C.buyCar(s, "interceptor").ok;
s.settings.damage = "persistent";
const out = C.applyResult(s, { kind: "side", event: { id: "x", tier: 1, goal: { type: "place", max: 3 } }, raceId: "d1" }, { mode: "circuit", track: "kerbside", laps: 3, place: 2, of: 4, finished: true, eliminated: false, total: 70, best: 22, lapTimes: [24, 23, 22], drift: 0, contacts: 3, damage: 0.4, order: ["pip", "YOU"], beat: [], rivals: {} });
const dmg = s.garage.owned.vela.dmg, cost = C.repairCost("vela", s.garage.owned.vela), m0 = s.money, rep = C.repair(s, "vela");
console.log(JSON.stringify({ a, b, c, police, dmg, cost, paid: m0 - s.money, rep, after: s.garage.owned.vela.dmg, racer: C.playerRacer(s).dmg }));""")
    assert r["a"] == [False, False] and r["b"][:2] == [True, True] and "Beat Dex Varga 3 times" in r["b"][2]
    assert r["c"] is True and r["police"] is False
    assert r["dmg"] == pytest.approx(0.4) and r["cost"] > 0 and r["rep"]["ok"] and r["after"] == 0 and r["racer"] == 0
    assert r["paid"] == round(r["cost"] * 0.7)                             # Nia, your mechanic, takes 30% off repairs


def test_expanded_looks_and_tune_survive_a_save():
    r = js("""
const s = C.fresh(); s.money = 1e5;
for (const [k, v] of [["finish", "pearl"], ["tint", "dark"], ["lights", "ice"], ["exhaust", "quad"], ["numpos", "roof"], ["decal", "sash"], ["spoiler", "duck"], ["paint2", "#ff4fa3"]]) C.setLook(s, "pacer", k, v);
C.setTune(s, "pacer", { preset: "drift" }); C.setTune(s, "pacer", { gearing: 0.5 });
const back = C.importSave(C.exportSave(s)).save.garage.owned.pacer;
console.log(JSON.stringify({ back, look: C.lookOf(back) }));""")
    b = r["back"]
    assert (b["finish"], b["tint"], b["lights"], b["exhaust"], b["numpos"], b["decal"], b["spoiler"], b["paint2"]) == ("pearl", "dark", "ice", "quad", "roof", "sash", "duck", "#ff4fa3")
    assert b["tune"] == {"preset": "custom", "gearing": 0.5, "aero": 0, "diff": 1, "tyre": "hard"}
    assert r["look"]["finish"] == "pearl" and r["look"]["paint2"] == "#ff4fa3"
