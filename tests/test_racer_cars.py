"""Kerbside Grand Prix car identity (phase 2): every drivable car has its own handling (no near-twins), its own power
character, its own engine voice, its own look and factory livery, rivals bring their signature cars, body parts only
fit the cars they suit, and older saves pick up the new parts without losing anything."""

import json
import shutil
import subprocess

import pytest

from jarvis.server.app import STATIC

NODE = shutil.which("node")


def js(code: str, timeout=180):
    if not NODE:
        pytest.skip("node not installed")
    pre = (f"const R = require({json.dumps(str(STATIC / 'racer.js'))}), C = require({json.dumps(str(STATIC / 'racer-career.js'))}),"
           f" D = require({json.dumps(str(STATIC / 'racer-data.js'))}), A = require({json.dumps(str(STATIC / 'racer-audio.js'))});\n"
           "const cars = Object.entries(D.CARS).filter(([, c]) => !c.police);\n")
    out = subprocess.run([NODE, "-e", pre + code], capture_output=True, text=True, timeout=timeout, check=True)
    return json.loads(out.stdout)


def test_every_car_is_its_own_car():
    r = js("""
const k = ["acc", "drag", "grip", "brake", "steer", "mass", "band", "turbo", "slide", "wet", "offroad"], v = cars.map(([id, c]) => [id, k.map((f) => c[f] || 0)]);
const sd = k.map((_, i) => { const a = v.map((x) => x[1][i]), m = a.reduce((s, x) => s + x, 0) / a.length; return Math.sqrt(a.reduce((s, x) => s + (x - m) ** 2, 0) / a.length) || 1; });
let min = 9, pair = null;
for (let i = 0; i < v.length; i++) for (let j = i + 1; j < v.length; j++) { const d = Math.sqrt(k.reduce((s, _, q) => s + ((v[i][1][q] - v[j][1][q]) / sd[q]) ** 2, 0)); if (d < min) { min = d; pair = [v[i][0], v[j][0]]; } }
const voices = new Set(cars.map(([, c]) => JSON.stringify({ ...A.VOICES[c.shape], ...c.voice }))).size;
const looks = new Set(cars.map(([, c]) => c.shape + JSON.stringify(c.art))).size;
const liveries = new Set(cars.map(([, c]) => JSON.stringify(c.factory))).size;
console.log(JSON.stringify({ n: cars.length, min, pair, voices, looks, liveries, missing: cars.filter(([, c]) => !c.handling || c.band === undefined || !c.factory || !c.voice || !(c.voice.cyl || c.voice.electric)).map(([id]) => id) }));""")
    assert r["missing"] == []
    assert r["min"] >= 1.0, r["pair"]                  # no two cars handle alike (in standard deviations across 11 traits)
    assert r["voices"] == r["n"] and r["looks"] == r["n"] and r["liveries"] == r["n"]


def test_the_power_band_changes_how_a_car_pulls_but_not_its_top_speed():
    r = js("""
const run = (band, secs) => { const r = R.newRace({ track: "harbour", mode: "timetrial", laps: 1, player: { spec: { ...R.BASE_SPEC, band } } }); r.state = "race"; const me = r.cars[0], top = R.BASE_SPEC.acc / R.BASE_SPEC.drag;
  me.a = r.trk.ANG[me.idx]; const out = { t50: 0, t80: 0, v: [] }; let t = 0;
  for (let i = 0; i < 120 * secs; i++) { R.step(r, 1 / 120, { steer: 0, thr: true, brk: false, nitro: false }); t += 1 / 120; me.a = r.trk.ANG[me.idx]; me.x = r.trk.P[me.idx][0]; me.y = r.trk.P[me.idx][1];
    if (!out.t50 && me.fwd >= top * 0.5) out.t50 = t; if (!out.t80 && me.fwd >= top * 0.8) out.t80 = t; if (i % 30 === 29) out.v.push(me.fwd); } return out; };
const torque = run(-0.8, 40), revs = run(0.8, 40), flat = run(0, 40);
console.log(JSON.stringify({ early: [torque.v[0], revs.v[0]], mid: [torque.t80 - torque.t50, revs.t80 - revs.t50], top: [torque.v.at(-1), revs.v.at(-1), flat.v.at(-1)] }));""")
    assert r["early"][0] > r["early"][1] * 1.05          # torque launches harder
    assert r["mid"][1] < r["mid"][0]                    # revs pull harder through the middle (50% → 80% of top speed sooner)
    t = r["top"]
    assert abs(t[0] - t[2]) / t[2] < 0.02 and abs(t[1] - t[2]) / t[2] < 0.02   # same top speed


def test_rivals_bring_their_signature_cars_when_it_gets_serious():
    r = js("""
const pick = (id, tier) => C.driver(id, tier).car;
console.log(JSON.stringify({ dex: [pick("dex", 2), pick("dex", 3)], mara: [pick("mara", 2), pick("mara", 4)], benny: [pick("benny", 2), pick("benny", 3)], sora: [pick("sora", 3), pick("sora", 4)],
  kestrels: Object.values(D.DRIVERS).filter((d) => d.car === "kestrel").length, art: !!C.driver("dex", 4).art }));""")
    assert r["dex"] == ["brute", "ironclad"] and r["mara"] == ["mistral", "tidewater"] and r["benny"] == ["ardent", "brickyard"] and r["sora"] == ["halcyon", "summit"]
    assert r["kestrels"] <= 2 and r["art"]


def test_body_parts_fit_only_where_they_suit_and_old_saves_keep_everything():
    r = js("""
const s = C.fresh(); s.money = 1e5; s.garage.owned.spectre = C.carState("spectre"); s.garage.owned.tempest = C.carState("tempest");
const bar = [C.setLook(s, "spectre", "bumper", "pushbar").ok, C.setLook(s, "tempest", "bumper", "pushbar").ok, C.setLook(s, "tempest", "tyres", "offroad").ok, C.setLook(s, "spectre", "tyres", "offroad").ok];
// a save from before the new parts existed: the keys are missing, so they default; paint and decals are kept
const old = JSON.parse(C.exportSave(C.fresh()).replace(/^[^{]*/, "") || "{}");
const legacy = C.fresh(); legacy.garage.owned.pacer.paint = "#123456"; const raw = JSON.parse(JSON.stringify(legacy));
for (const k of ["bumper", "bonnet", "tyres"]) delete raw.garage.owned.pacer[k], delete raw.garage.owned.pacer.bought[k];
const v = C.validate(raw).save.garage.owned.pacer;
const fresh = C.carState("goliath");
console.log(JSON.stringify({ bar, legacy: [v.paint, v.bumper, v.bonnet, v.tyres], factory: [fresh.paint, fresh.decal, fresh.bought.decal.includes("flame")] }));""")
    assert r["bar"] == [False, True, True, False]
    assert r["legacy"] == ["#123456", "stock", "stock", "road"]
    assert r["factory"] == ["#14161a", "flame", True]   # the factory livery comes free


def test_each_car_sounds_like_itself():
    r = js(r"""
const log = { targets: [] };
const param = (n) => ({ value: 0, setValueAtTime(v) { this.value = v; }, setTargetAtTime(v) { this.value = v; log.targets.push([n, v]); }, exponentialRampToValueAtTime() {} });
const node = (k) => ({ kind: k, connect() {}, start() {}, stop() {}, gain: param(k + ".gain"), frequency: param(k + ".frequency"), Q: param("Q"), type: "", curve: null });
globalThis.AudioContext = class { constructor() { this.currentTime = 0; this.state = "running"; this.sampleRate = 8000; this.destination = node("d"); }
  createGain() { return node("gain"); } createBiquadFilter() { return node("filter"); } createWaveShaper() { return node("shaper"); } createOscillator() { return node("osc"); }
  createBufferSource() { return node("src"); } createBuffer(c, n) { const d = new Float32Array(n); return { getChannelData: () => d }; } resume() {} close() {} };
globalThis.setInterval = () => 1;
const a = A.create(); a.unlock();
const hear = (id) => { const c = D.CARS[id]; a.voice(c.shape, c.voice); log.targets.length = 0; a.update({ speed: 120, top: 650, slip: 0, on: true, thr: true }); return log.targets.map(([n, v]) => n + "=" + v.toFixed(2)).join(","); };
const sounds = cars.map(([id]) => hear(id));
console.log(JSON.stringify({ distinct: new Set(sounds).size, n: cars.length }));""")
    assert r["distinct"] == r["n"]                     # no two cars produce the same engine settings


def test_the_new_cars_are_earned_the_way_they_say():
    r = js("""
const avail = (s, id) => C.carAvailable(s, id).ok;
const s = C.fresh(), before = ["kurogane", "tsubame", "thunderbolt", "bulldozer", "volta", "vecchia"].map((id) => avail(s, id));
s.achievements.drifter = 1; s.medals = { kerbside: "gold", ridge: "gold" }; C.hire(s, "otto"); s.records.pursuit.heat = 3;
s.story.flags.grudge_valentina_won = true;
const t = C.fresh(); t.story.chapter = 3; C.startTourney(t, "dragkings");
const sum = (o) => ({ mode: "drag", track: "harbour", laps: 1, place: 1, of: 2, finished: true, eliminated: false, total: 5, best: 5, lapTimes: [5], drift: 0, contacts: 0, damage: 0, order: ["YOU", "x"], beat: ["x"], rivals: {}, ...o });
let n = 0, notes = [];
for (let i = 0; i < 3; i++) { const ev = C.tourneyEvent(t); const out = C.applyResult(t, { kind: "tourney", event: ev, raceId: "t" + (++n) }, sum({})); notes.push(...out.notes); }
const again = C.applyResult(t, { kind: "side", event: { id: "e", tier: 1, goal: { type: "place", max: 3 } }, raceId: "t9" }, sum({ mode: "circuit" })).notes;
const after = ["kurogane", "tsubame", "thunderbolt", "bulldozer", "vecchia"].map((id) => avail(s, id));
const k = C.fresh(); k.money = 1e7; const got = [];
for (const [id, c] of cars) { if (c.price === null || k.garage.owned[id]) continue; k.garage.unlocked.push(id); const r = C.buyCar(k, id); got.push(...r.achievements); }
k.garage.owned.countess = C.carState("countess"); got.push(...C.collectionCheck(k));
console.log(JSON.stringify({ before, after, volta: avail(t, "volta"), notes: notes.filter((x) => x.includes("Volta")).length, again: again.filter((x) => x.includes("Volta")).length,
  ach: [...new Set(got)].filter((a) => ["collector", "every_class", "full_garage"].includes(a)), col: C.collection(k) }));""")
    assert r["before"] == [False] * 6 and r["after"] == [True] * 5
    assert r["volta"] is True and r["notes"] == 1 and r["again"] == 0          # announced once
    assert set(r["ach"]) == {"collector", "every_class", "full_garage"} and r["col"]["owned"] == r["col"]["total"]


def test_the_pickup_and_the_electric_car_are_their_own_kind():
    r = js("""
const truck = D.CARS.bulldozer, ev = D.CARS.volta, heaviest = Math.max(...cars.map(([, c]) => c.mass)), lightest = Math.min(...cars.map(([, c]) => c.mass));
console.log(JSON.stringify({ truck: [truck.shape, truck.mass === heaviest, truck.offroad > 0], ev: [ev.band, !!ev.voice.electric, ev.voice.cyl], light: D.CARS.feather.mass === lightest,
  kinds: new Set(cars.map(([, c]) => c.cat)).size, n: cars.length }));""")
    assert r["truck"] == ["truck", True, True] and r["ev"] == [-1, True, 0] and r["light"]
    assert r["n"] == 38 and r["kinds"] >= 28
