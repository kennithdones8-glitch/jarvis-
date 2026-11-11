"""Kerbside Grand Prix modes (racer-modes.js on racer.js): the police pursuit has real rules (the police chase, heat
rises, units join and set roadblocks with a gap, rams disable them, you get busted when pinned, and you escape out of
sight, faster in cover), drag rewards a good launch and shifting near the top of the revs, touge ends when one car
pulls clear, endurance tyres wear and pit stops fix them, deliveries run against the clock, team races score
points, and custom rules (no nitro, no collisions, no damage) hold."""

import json
import shutil
import subprocess

import pytest

from jarvis.server.app import STATIC

NODE = shutil.which("node")


def js(code: str, timeout=240):
    if not NODE:
        pytest.skip("node not installed")
    pre = (f"const R = require({json.dumps(str(STATIC / 'racer.js'))});\n"
           "const go = (r) => { while (r.state === 'lights') R.step(r, 1 / 120, { steer: 0, thr: false, brk: false, nitro: false }); };\n"
           "const run = (r, drive, max = 300) => { let t = 0; const ev = []; while (r.state !== 'done' && t < max) { R.step(r, 1 / 120, drive ? drive(r, t) : null); t += 1 / 120; ev.push(...r.events.splice(0)); } return ev; };\n")
    out = subprocess.run([NODE, "-e", pre + code], capture_output=True, text=True, timeout=timeout, check=True)
    return json.loads(out.stdout)


def test_police_chase_you_down_and_bust_you_when_you_stop():
    r = js("""
const r = R.newRace({ track: "kerbside", mode: "pursuit", heat: 1 }); go(r);
const me = r.cars[0], gap0 = Math.min(...r.cars.filter((c) => c.police).map((c) => Math.hypot(c.x - me.x, c.y - me.y)));
let closest = 1e9, bustAt = 0;
const ev = run(r, (rr, t) => { closest = Math.min(closest, rr.pursuit.near); return { steer: 0, thr: false, brk: me.fwd > 20, nitro: false }; }, 60);
const s = R.summary(r);
console.log(JSON.stringify({ gap0, closest, s: s.pursuit, place: s.place, finished: s.finished, ended: ev.some((e) => e.type === "pursuit-end"), units: r.cars.filter((c) => c.police).length, order: s.order }));""")
    assert r["gap0"] > 150 and r["closest"] < 115                       # they start behind you and drive right up to you
    p = r["s"]
    assert p["result"] == "busted" and p["fine"] > 0 and r["ended"] and r["finished"] is False and r["place"] == 2
    assert p["time"] < 30


def test_you_escape_out_of_sight_and_cover_hides_you_faster():
    r = js("""
// out of sight (every unit parked far behind you, engines off): the escape meter fills; in the Ridge tunnel it fills twice as fast
const cool = (track, inCover) => {
  const r = R.newRace({ track, mode: "pursuit", heat: 1 }); go(r); const me = r.cars[0], t = r.trk;
  const i = inCover ? R.coverOf(t)[0][0] + 18 : (R.coverOf(t).length ? R.coverOf(t)[0][0] + 200 : 300);
  const put = (c, k, lat) => { const [nx, ny] = t.nrm(k); c.x = t.P[k][0] + nx * lat; c.y = t.P[k][1] + ny * lat; c.idx = k; c.vx = c.vy = 0; c.a = t.ANG[k]; };
  put(me, i % t.N, 0); me.prog = i - t.N;
  for (let k = 0; k < 120 * 2; k++) { for (const c of r.cars) if (c.police) { c.x = t.OX + 30; c.y = t.OY + 30; c.vx = c.vy = 0; } R.step(r, 1 / 120, { steer: 0, thr: false, brk: false, nitro: false }); }
  return { cool: r.pursuit.cool, seen: r.pursuit.seen, cover: r.pursuit.cover };
};
const far = (() => { const r = R.newRace({ track: "harbour", mode: "pursuit", heat: 1, player: { spec: { ...R.BASE_SPEC, acc: 1100, grip: 9 } } }); go(r); const ev = run(r, null, 200); return { s: R.summary(r).pursuit, ev: ev.filter((e) => e.type === "pursuit-end") }; })();
console.log(JSON.stringify({ open: cool("ridge", false), cover: cool("ridge", true), far, zones: [R.coverOf(R.track("ridge")).length, R.coverOf(R.track("oldtown")).length, R.coverOf(R.track("harbour")).length] }));""")
    assert r["open"]["seen"] is False and r["open"]["cover"] is False and r["cover"]["cover"] is True
    assert r["cover"]["cool"] == pytest.approx(r["open"]["cool"] * 2, rel=0.05) and r["open"]["cool"] > 0.2
    assert r["far"]["s"]["result"] == "escaped" and r["far"]["s"]["bounty"] > 0 and r["far"]["ev"][0]["result"] == "escaped"
    assert r["zones"][0] == 1 and r["zones"][1] >= 2 and r["zones"][2] == 0     # the tunnel; the canal bridges; open water


def test_heat_rises_units_join_and_roadblocks_leave_a_gap():
    r = js("""
const r = R.newRace({ track: "harbour", mode: "pursuit", heat: 3 }); go(r);
const me = r.cars[0]; let rb = null, maxUnits = 0;
// keep you moving (the AI drives your car) but never caught: units that get close are sent back
for (let k = 0; k < 120 * 75 && r.state !== "done"; k++) {
  for (const c of r.cars) if (c.police && !c.parked && Math.hypot(c.x - me.x, c.y - me.y) < 300) { c.vx *= 0.5; c.vy *= 0.5; }
  R.step(r, 1 / 120, null);
  if (r.pursuit.rb && !rb) { const t = r.trk; rb = r.pursuit.rb.cars.map((c) => R.latOff(t, { ...c, idx: r.pursuit.rb.idx })); }
  maxUnits = Math.max(maxUnits, r.cars.filter((c) => c.police && !c.parked && !c.out).length);
}
const P = r.pursuit;
console.log(JSON.stringify({ heat: P.maxHeat, rb, maxUnits, ev: r.events.length }));""")
    assert r["heat"] >= 4 and r["maxUnits"] >= 4                             # heat climbs over time; more units join
    lat = sorted(r["rb"])
    assert len(lat) == 2
    half, rad = 75, 17
    gaps = [lat[0] - rad + half, half - (lat[1] + rad)]                       # open road either side of the block
    assert max(gaps) > 2 * rad + 20 and lat[1] - lat[0] < 2 * rad + 10        # one side is open, the block itself is solid


def test_ramming_disables_a_unit_and_raises_the_heat():
    r = js("""
const r = R.newRace({ track: "harbour", mode: "pursuit", heat: 1 }); go(r);
const me = r.cars[0], u = r.cars.find((c) => c.police), t = r.trk, h0 = r.pursuit.heat + r.pursuit.heatP;
let hits = 0;
for (let n = 0; n < 6 && !u.out; n++) {
  const k = (me.idx + 4) % t.N; u.x = t.P[k][0]; u.y = t.P[k][1]; u.vx = u.vy = 0; u.idx = k;
  me.x = t.P[me.idx][0]; me.y = t.P[me.idx][1]; me.a = t.ANG[me.idx]; me.vx = Math.cos(me.a) * 330; me.vy = Math.sin(me.a) * 330;
  for (let s = 0; s < 30; s++) R.step(r, 1 / 120, { steer: 0, thr: true, brk: false, nitro: false });
  hits++;
}
console.log(JSON.stringify({ out: u.out, hits, rams: r.pursuit.rams, disabled: r.pursuit.disabled, heatUp: r.pursuit.heat + r.pursuit.heatP - h0 }));""")
    assert r["out"] is True and r["disabled"] == 1 and 2 <= r["hits"] <= 6 and r["rams"] >= 2 and r["heatUp"] > 0.5


def test_drag_rewards_the_launch_and_shifting_near_the_top():
    r = js("""
const drag = (revTo, shiftAt) => { const r = R.newRace({ track: "kerbside", mode: "drag", field: [{ code: "OPP", id: "opp", skill: 0.95 }], rules: { nitro: false } });
  const ev = run(r, (rr) => { const me = rr.cars[0]; return { thr: rr.state === "lights" ? me.rpm < revTo : true, shift: rr.state === "race" && me.rpm > shiftAt, nitro: false }; }, 30);
  return { ...R.summary(r).drag, track: r.track, place: R.summary(r).place, launch: ev.find((e) => e.type === "launch").q, shiftsQ: ev.filter((e) => e.type === "shift").map((e) => e.q) }; };
const good = drag(0.66, 0.9), early = drag(0.66, 0.72), limiter = drag(0.66, 0.995), bog = drag(0.1, 0.9), spin = drag(1, 0.9);
console.log(JSON.stringify({ good, early, limiter, bog, spin }));""")
    g = r["good"]
    assert g["track"] == "harbour" and 3 < g["et"] < 9 and g["launch"] == "perfect" and g["shiftsQ"].count("perfect") == 5
    assert g["et"] < r["early"]["et"] and g["et"] < r["limiter"]["et"]       # shifting early or on the limiter costs time
    assert r["early"]["shiftsQ"][0] == "early"
    assert r["bog"]["launch"] == "bogged" and r["spin"]["launch"] == "wheelspin"
    assert g["et"] < r["bog"]["et"] and g["et"] < r["spin"]["et"]


def test_touge_ends_when_a_car_pulls_clear():
    r = js("""
const duel = (sk) => { const r = R.newRace({ track: "ridge", mode: "touge", field: [{ code: "T", id: "t", skill: sk }] }); const ev = run(r, null, 120); return { s: R.summary(r), ev: ev.filter((e) => e.type === "touge") }; };
const walk = duel(0.6), close = duel(1.0);
console.log(JSON.stringify({ walk: [walk.s.touge, walk.s.place, walk.ev], close: [close.s.touge.how, close.s.laps] }));""")
    assert r["walk"][0]["how"] == "gap" and r["walk"][1] == 1 and r["walk"][2][0]["you"] is True
    assert r["close"] == ["line", 1]


def test_endurance_tyres_wear_and_the_pit_box_fixes_them():
    r = js("""
const lapAt = (wear) => { const r = R.newRace({ track: "kerbside", mode: "endurance", laps: 3 }); r.cars[0].wear = wear; let t = 0; const me = r.cars[0];
  while (me.laps < 2 && t < 120) { if (me.laps >= 1) me.wear = wear; R.step(r, 1 / 120, null); t += 1 / 120; } return me.lapTimes[1]; };
const fresh = lapAt(0), worn = lapAt(0.9);
// wear builds up over a stint; then stop in the box before the line
const r = R.newRace({ track: "kerbside", mode: "endurance", laps: 6 }); const me = r.cars[0], t = r.trk;
while (me.laps < 2) R.step(r, 1 / 120, null);
const wear2 = me.wear;
let pitted = false, ev = [];
for (let k = 0; k < 120 * 60 && !pitted; k++) { const box = me.idx >= t.N - 22 && me.idx < t.N - 1; const a = R.aiInput(r, me); R.step(r, 1 / 120, box ? { steer: a.steer, thr: false, brk: true, nitro: false } : a); ev.push(...r.events.splice(0)); pitted = ev.some((e) => e.type === "pit" && e.done); }
const ai = (() => { const x = R.newRace({ track: "kerbside", mode: "endurance", laps: 8 }); run(x, null, 400); return x.cars.slice(1).map((c) => c.pits); })();
console.log(JSON.stringify({ fresh, worn, wear2, pitted, after: me.wear, pits: me.pits, ai }));""")
    assert r["worn"] > r["fresh"] * 1.03                                        # worn tyres: slower laps
    assert 0.1 < r["wear2"] < 0.6
    assert r["pitted"] and r["after"] == 0 and r["pits"] == 1
    assert all(p >= 1 for p in r["ai"])                                         # the AI pits too


def test_deliveries_run_against_the_clock_and_bruise_cargo():
    r = js("""
const ok = (() => { const r = R.newRace({ track: "kerbside", mode: "delivery", stops: 4 }); const ev = run(r, null, 200); return { d: R.summary(r).delivery, cps: ev.filter((e) => e.type === "checkpoint").length }; })();
const slow = (() => { const r = R.newRace({ track: "kerbside", mode: "delivery", stops: 4, player: { spec: { ...R.BASE_SPEC, acc: 150 } } }); const ev = run(r, null, 200); return { d: R.summary(r).delivery, failed: ev.some((e) => e.type === "delivery-failed"), out: R.summary(r).eliminated }; })();
const rough = (() => { const r = R.newRace({ track: "kerbside", mode: "delivery", stops: 4 }); go(r); const me = r.cars[0];
  for (let k = 0; k < 120 * 4; k++) R.step(r, 1 / 120, { steer: k < 40 ? 1 : 0, thr: true, brk: false, nitro: false }); return r.deliv.cargo; })();
console.log(JSON.stringify({ ok, slow, rough }));""")
    assert r["ok"]["d"]["delivered"] and r["ok"]["cps"] == 3 and r["ok"]["d"]["cargo"] > 0.9
    assert r["slow"]["failed"] and r["slow"]["out"] and not r["slow"]["d"]["delivered"]
    assert r["rough"] < 0.95


def test_team_races_score_points_and_custom_rules_hold():
    r = js("""
const tm = R.newRace({ track: "kerbside", mode: "team", field: [{ code: "PIP", id: "pip", team: "you", personality: "ally" }, { code: "A", id: "a" }, { code: "B", id: "b" }] });
run(tm, null, 200); const team = R.summary(tm).team;
const noN = R.newRace({ track: "harbour", rules: { nitro: false } }); run(noN, null, 40); const nitro = Math.max(...noN.cars.map((c) => c.nitro));
const ghost = R.newRace({ track: "kerbside", rules: { collisions: false } }); go(ghost); ghost.cars[1].x = ghost.cars[0].x + 5; ghost.cars[1].y = ghost.cars[0].y;
for (let k = 0; k < 10; k++) R.step(ghost, 1 / 120, null);
const nd = R.newRace({ track: "kerbside", rules: { damage: false } }); go(nd); nd.cars[1].x = nd.cars[0].x + 30; nd.cars[1].y = nd.cars[0].y; nd.cars[0].vx = 300; nd.cars[1].vx = -300; R.step(nd, 1 / 120, null);
console.log(JSON.stringify({ team, nitro, contacts: ghost.cars[0].contacts, dmg: nd.cars.map((c) => c.dmg), ndContacts: nd.cars[0].contacts }));""")
    t = r["team"]
    assert t["you"] + t["them"] == 10 + 8 + 6 + 5 and t["won"] == (t["you"] > t["them"])
    assert r["nitro"] == 0 and r["contacts"] == 0
    assert r["ndContacts"] >= 1 and set(r["dmg"]) == {0}


def cjs(code: str):
    return js(f"const C = require({json.dumps(str(STATIC / 'racer-career.js'))}), D = require({json.dumps(str(STATIC / 'racer-data.js'))});\n"
              "let n = 0; const apply = (s, kind, ev, sum) => C.applyResult(s, { kind, event: ev, raceId: 'm' + (++n) }, sum);\n" + code)


def test_pursuit_pays_a_bounty_or_a_fine_and_unlocks_higher_heat():
    r = cjs("""
const s = C.fresh(); s.money = 1000;
const heats0 = C.pursuitHeats(s), ev = C.pursuitEvent(s, { heat: 4, track: "ridge" });
const esc = apply(s, "pursuit", ev, { mode: "pursuit", track: "ridge", place: 1, of: 2, finished: true, total: 80, damage: 0, pursuit: { result: "escaped", heat: 2, bounty: 2000, time: 80, disabled: 1, rams: 2, roadblocks: 0, fine: 0 } });
const m1 = s.money, heats1 = C.pursuitHeats(s);
const bust = apply(s, "pursuit", C.pursuitEvent(s, { heat: 2 }), { mode: "pursuit", track: "kerbside", place: 2, of: 2, finished: false, total: 40, damage: 0, pursuit: { result: "busted", heat: 3, bounty: 9000, time: 40, disabled: 0, rams: 0, roadblocks: 0, fine: 99999 } });
const broke = C.fresh(); broke.money = 0;
const free = apply(broke, "pursuit", C.pursuitEvent(broke), { mode: "pursuit", track: "kerbside", place: 2, of: 2, finished: false, total: 40, damage: 0, pursuit: { result: "busted", heat: 1, bounty: 100, time: 20, disabled: 0, rams: 0, roadblocks: 0, fine: 290 } });
const police = C.config(s, C.pursuitEvent(s, { heat: 3 }), "pursuit");
console.log(JSON.stringify({ heats0, evHeat: ev.heat, esc: [esc.money, esc.passed, esc.achievements], m1, heats1, bust: [bust.fine, bust.passed], after: s.money, rec: s.records.pursuit, free: [free.fine, broke.money],
  policeAcc: police.policeSpec.acc, stockAcc: C.policeSpec(1).acc, mode: police.mode, heat: police.heat }));""")
    assert r["heats0"] == 1 and r["evHeat"] == 1                         # heat 4 isn't open yet: you get heat 1
    assert r["esc"] == [600, True, ["first_escape"]] and r["m1"] == 1600 and r["heats1"] == 3
    assert r["bust"] == [800, False] and r["after"] == 800                # the fine never takes more than half your money
    assert r["rec"] == {"best": 2000, "escapes": 1, "busts": 1, "heat": 2, "fines": 800}
    assert r["free"] == [0, 0]
    assert r["mode"] == "pursuit" and r["heat"] == 3 and r["policeAcc"] > r["stockAcc"]   # heat 3 units are upgraded


def test_wagers_tournaments_class_rules_and_team_events():
    r = cjs("""
const sum = (o) => ({ mode: "rival", track: "kerbside", laps: 3, place: 1, of: 2, finished: true, eliminated: false, total: 70, best: 22, lapTimes: [24, 23, 22], drift: 0, contacts: 0, damage: 0, order: ["YOU", "dex"], beat: ["dex"], rivals: {}, ...o });
const s = C.fresh(); s.money = 3000; const rv = { id: "r-dex", rival: "dex", tier: 2, mode: "rival", track: "kerbside", field: ["dex"], goal: { type: "place", max: 1 } };
const bad = C.placeWager(s, { id: "s-park-tt" }, 500).ok, tooMuch = C.placeWager(s, rv, 5000).ok;
C.placeWager(s, rv, 2500); const staked = s.money;
const win = apply(s, "rival", rv, sum({})); const afterWin = s.money - win.money;
C.placeWager(s, rv, 1000); const lose = apply(s, "rival", rv, sum({ place: 2, order: ["dex", "YOU"], beat: [] }));
// tournament: drag kings, three stages; lose one and you're out
const t = C.fresh(); t.story.chapter = 3; const st = C.startTourney(t, "dragkings").ok, ev1 = C.tourneyEvent(t);
const r1 = apply(t, "tourney", ev1, sum({ mode: "drag", track: "harbour" })), ev2 = C.tourneyEvent(t);
const r2 = apply(t, "tourney", ev2, sum({ mode: "drag", track: "harbour" })), r3 = apply(t, "tourney", C.tourneyEvent(t), sum({ mode: "drag", track: "harbour" }));
const u = C.fresh(); u.story.chapter = 3; C.startTourney(u, "dragkings"); const out = apply(u, "tourney", C.tourneyEvent(u), sum({ mode: "drag", place: 2, beat: [] }));
const locked = C.startTourney(C.fresh(), "knockout").ok;
// class: a C-class event in a B-class car can't be won; the AI field is put in C-class cars
const k = C.fresh(); const cev = D.SIDE.find((e) => e.id === "s-park-class"); const okC = C.carAllowed(k, cev).ok;
k.garage.owned.kestrel = C.carState("kestrel"); k.garage.current = "kestrel"; const okB = C.carAllowed(k, cev);
const illegal = apply(k, "side", cev, sum({ mode: "circuit" }));
const aiCars = C.config(C.fresh(), cev, "side").field.map((d) => d.shape);
// team: your crew driver (or a hired gun) races with you; the goal is your team's points
const tv = D.TURF_EVENTS.park, tf = C.config(C.fresh(), tv, "side").field, h = C.fresh(); C.hire(h, "dex");
const tf2 = C.config(h, tv, "side").field;
const teamWin = C.goalMet(tv.goal, { finished: true, team: { you: 18, them: 11, won: true } }), teamLose = C.goalMet(tv.goal, { finished: true, team: { you: 11, them: 18, won: false } });
const v = C.validate(JSON.parse(JSON.stringify({ ...t, tourney: { id: "knockout", stage: 9 }, wager: { amount: 500, event: "r-dex" } })));
console.log(JSON.stringify({ bad, tooMuch, staked, wagerWin: win.wager, afterWin, lose: lose.wager, ach: win.achievements,
  st, ev1: [ev1.mode, ev1.field, ev1.title], r1: r1.tourney, ev2: ev2.field, r2: r2.tourney, r3: r3.tourney, wins: t.records.tournament.wins, inT: t.tourney, out: out.tourney, locked,
  okC, okB: [okB.ok, okB.why], illegal: [illegal.passed, illegal.notes], aiCars, tf: tf.map((d) => [d.id, d.team]), tf2: tf2[0].name, teamWin, teamLose, v: [v.save.tourney, v.save.wager] }));""")
    assert r["bad"] is False and r["tooMuch"] is False and r["staked"] == 500
    assert r["wagerWin"] == {"won": True, "amount": 2500} and r["afterWin"] == 5500 and "high_roller" in r["ach"]
    assert r["lose"] == {"won": False, "amount": 1000}
    assert r["st"] and r["ev1"][0] == "drag" and r["ev1"][1] == ["pip"] and r["ev2"] == ["dex"]
    assert r["r1"] == {"done": False, "name": "Drag Kings", "next": "Semi-final"} and r["r3"]["won"] and r["r3"]["prize"] == 6000
    assert r["wins"] == 1 and r["inT"] is None and r["out"]["out"] is True and r["locked"] is False
    assert r["okC"] is True and r["okB"][0] is False and "Class C" in r["okB"][1]
    assert r["illegal"][0] is False and any("Class C" in n for n in r["illegal"][1])
    shapes_c = {c["shape"] for c in js("const D = require(" + json.dumps(str(STATIC / 'racer-data.js')) + "); console.log(JSON.stringify(Object.values(D.CARS).filter((c) => c.cls === 'C')));")}
    assert set(r["aiCars"]) <= shapes_c
    assert r["tf"] == [["pip", "you"], ["dex", "them"], ["otto", "them"]] and "your crew" in r["tf2"]
    assert r["teamWin"] is True and r["teamLose"] is False
    assert r["v"] == [{"id": "knockout", "stage": 2}, {"amount": 500, "event": "r-dex"}]
