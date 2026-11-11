"""Kerbside Grand Prix driving feel: weight moves (a dab of brake sharpens turn-in, the throttle loads the tail),
rear-drive cars rotate on the throttle while front-drive cars push wide, the handbrake swings the tail round and
scrubs speed, every car has a drivetrain, and slide assist is a saved setting."""

import json
import shutil
import subprocess

import pytest

from jarvis.server.app import STATIC

NODE = shutil.which("node")


def js(code: str):
    if not NODE:
        pytest.skip("node not installed")
    pre = (f"const R = require({json.dumps(str(STATIC / 'racer.js'))}), C = require({json.dumps(str(STATIC / 'racer-career.js'))}),"
           f" D = require({json.dumps(str(STATIC / 'racer-data.js'))});\n"
           # a car at a steady 380 units/s on a straight, then 0.4 s of the given inputs: how far it turned, how much it slid, its speed
           "const turn = (spec, inp, secs = 0.4, dab = 0) => { const r = R.newRace({ track: 'harbour', mode: 'timetrial', laps: 1, player: { spec } }); r.state = 'race';\n"
           "  const c = r.cars[0]; c.a = r.trk.ANG[c.idx]; c.vx = Math.cos(c.a) * 380; c.vy = Math.sin(c.a) * 380; c.load = 0; const a0 = c.a; let slip = 0;\n"
           "  for (let i = 0; i < 120 * secs; i++) { R.step(r, 1 / 120, { steer: 0, thr: false, brk: i < dab * 120, nitro: false, ...inp }); slip = Math.max(slip, c.slip); }\n"
           "  return { yaw: Math.abs(c.a - a0), slip, speed: Math.hypot(c.vx, c.vy) }; };\n"
           "const spec = (drive, extra = {}) => ({ ...R.BASE_SPEC, drive, ...extra });\n")
    out = subprocess.run([NODE, "-e", pre + code], capture_output=True, text=True, timeout=120, check=True)
    return json.loads(out.stdout)


def test_weight_transfer_braking_sharpens_turn_in():
    r = js("""
const coast = turn(spec("A"), { steer: 1 }), brake = turn(spec("A"), { steer: 1 }, 0.4, 0.12), power = turn(spec("A"), { steer: 1, thr: true });   // a 0.12 s dab of brake
console.log(JSON.stringify({ coast: coast.yaw, brake: brake.yaw, power: power.yaw }));""")
    assert r["brake"] > r["coast"] * 1.05            # weight on the nose: more bite
    assert r["brake"] > r["power"]


def test_drivetrains_behave_differently_on_the_throttle():
    r = js("""
const go = (d) => turn(spec(d, { slide: 0.3 }), { steer: 1, thr: true });
const F = go("F"), Rr = go("R"), A = go("A"), Fc = turn(spec("F", { slide: 0.3 }), { steer: 1 });
console.log(JSON.stringify({ F: F.yaw, R: Rr.yaw, A: A.yaw, Fcoast: Fc.yaw, slip: [F.slip, Rr.slip] }));""")
    assert r["R"] > r["A"] > r["F"]                   # rear-drive rotates on power, front-drive pushes wide
    assert r["F"] < r["Fcoast"]                       # power on a front-driver costs turn-in
    assert r["slip"][1] > r["slip"][0]                # and the rear-driver's tail steps out more


def test_the_handbrake_swings_the_tail_and_scrubs_speed():
    r = js("""
const plain = turn(spec("R"), { steer: 1 }), hb = turn(spec("R"), { steer: 1, hb: true }), straight = turn(spec("R"), { hb: true }), slow = (() => {
  const r = R.newRace({ track: 'harbour', mode: 'timetrial', laps: 1 }); r.state = 'race'; const c = r.cars[0]; c.a = r.trk.ANG[c.idx]; const a0 = c.a; c.vx = Math.cos(c.a) * 40; c.vy = Math.sin(c.a) * 40;
  for (let i = 0; i < 48; i++) R.step(r, 1 / 120, { steer: 1, thr: false, brk: false, hb: true }); return Math.abs(c.a - a0); })();
console.log(JSON.stringify({ plain, hb, straight, slow }));""")
    assert r["hb"]["yaw"] > r["plain"]["yaw"] * 1.15 and r["hb"]["slip"] > r["plain"]["slip"] * 1.8
    assert r["hb"]["speed"] < r["plain"]["speed"] and r["straight"]["yaw"] < 0.01   # no steering, no spin
    assert r["slow"] < 0.2                            # does nothing at walking pace


def test_every_car_has_a_drivetrain_and_assist_is_a_setting():
    r = js("""
const cars = Object.values(D.CARS), mix = cars.reduce((a, c) => (a[c.drive] = (a[c.drive] || 0) + 1, a), {});
const s = C.fresh(); const def = s.settings.assist; s.settings.assist = "strong";
const back = C.importSave(C.exportSave(s)).save.settings.assist, old = JSON.parse(JSON.stringify(C.fresh())); delete old.settings.assist;
console.log(JSON.stringify({ all: cars.every((c) => ["F", "R", "A"].includes(c.drive)), mix, stats: C.carStats("vela", C.carState("vela")).drive,
  tempest: D.CARS.tempest.drive, ronin: D.CARS.ronin.drive, def, back, old: C.validate(old).save.settings.assist, junk: C.validate({ ...old, settings: { assist: "max" } }).save.settings.assist }));""")
    assert r["all"] and all(r["mix"].get(k, 0) >= 3 for k in "FRA")
    assert r["stats"] == "F" and r["tempest"] == "A" and r["ronin"] == "R"
    assert [r["def"], r["back"], r["old"], r["junk"]] == ["light", "strong", "light", "light"]


def test_surfaces_grip_and_slow_you_the_way_they_look():
    r = js("""
// the same car, put down at the same speed at the same offset from the centre line, on different ground
const on = (track, off, i0) => { const r = R.newRace({ track, mode: 'timetrial', laps: 1 }); r.state = 'race'; const c = r.cars[0], t = r.trk;
  const i = i0 % t.N, [nx, ny] = t.nrm(i); c.idx = i; c.x = t.P[i][0] + nx * off; c.y = t.P[i][1] + ny * off; c.a = t.ANG[i]; c.vx = Math.cos(c.a) * 300; c.vy = Math.sin(c.a) * 300;
  R.step(r, 1 / 120, { steer: 0, thr: false, brk: false }); const surf = c.surf;
  for (let k = 0; k < 60; k++) { R.step(r, 1 / 120, { steer: 0, thr: false, brk: false }); }
  return { surf, speed: Math.hypot(c.vx, c.vy) }; };
const TW = R.TW, t = R.newRace({ track: 'kerbside', mode: 'timetrial', laps: 1 }).trk;
// a straight piece of track (no kerbs, no gravel): road, then apron, then grass
let s = 0; for (let i = 0; i < t.N; i++) { let ok = true; for (let k = -10; k <= 70; k++) if (Math.abs(R.wrapA(t.ANG[(i + k + 6 + t.N) % t.N] - t.ANG[(i + k - 6 + t.N) % t.N])) > 0.1) ok = false; if (ok) { s = i; break; } }
// a bend, and its outside: gravel
let b = 0, side = 1; for (let i = 0; i < t.N; i++) { const b2 = R.wrapA(t.ANG[(i + 6) % t.N] - t.ANG[(i - 6 + t.N) % t.N]); if (Math.abs(b2) > 0.7) { b = i; side = b2 > 0 ? -1 : 1; break; } }
console.log(JSON.stringify({ road: on('kerbside', 0, s), apron: on('kerbside', TW / 2 + 14, s), grass: on('kerbside', TW / 2 + 40, s), gravel: on('kerbside', side * (TW / 2 + 45), b), kerb: on('kerbside', -side * (TW / 2 + 5), b).surf }));""")
    assert [r[k]["surf"] for k in ("road", "apron", "grass", "gravel")] == ["road", "apron", "grass", "gravel"] and r["kerb"] == "kerb"
    assert r["road"]["speed"] > r["apron"]["speed"] > r["grass"]["speed"] > r["gravel"]["speed"]


def test_barriers_stop_you_driving_through_and_scrape_speed():
    r = js("""
const hit = (track) => { const r = R.newRace({ track, mode: 'timetrial', laps: 1 }); r.state = 'race'; const c = r.cars[0], t = r.trk, i = c.idx, [nx, ny] = t.nrm(i);
  // aimed 35 degrees off the road's direction, straight at the barrier, at speed
  c.a = t.ANG[i] + 0.6; c.vx = Math.cos(c.a) * 420; c.vy = Math.sin(c.a) * 420; let far = 0, v0 = 420;
  for (let k = 0; k < 120 * 2; k++) { R.step(r, 1 / 120, { steer: 0, thr: true, brk: false }); const [n2, d2] = R.nearest(t, c.x, c.y, c.idx); far = Math.max(far, d2); }
  return { far, contacts: c.contacts, impacts: r.impacts.some((x) => x.wall) }; };
console.log(JSON.stringify({ town: hit('oldtown'), park: hit('kerbside'), TW: R.TW }));""")
    assert r["town"]["far"] < r["TW"] / 2 + 47 and r["park"]["far"] < r["TW"] / 2 + 98   # you never pass through
    assert r["town"]["contacts"] >= 1 and r["town"]["impacts"]


def test_the_slipstream_pulls_you_along_behind_another_car():
    r = js("""
const run = (withLead) => { const r = R.newRace({ track: 'harbour', mode: 'circuit', laps: 1, field: withLead ? [{ id: 'a', code: 'A', name: 'A', color: '#fff' }] : [] }); r.state = 'race';
  const me = r.cars[0], t = r.trk, lead = withLead ? r.cars[1] : null;
  // both pinned on a straight, you 70 units behind, both at 400; then 1.5 s flat out (the lead car holds 400)
  let draft = 0;
  for (let k = 0; k < 180; k++) { const i = me.idx, j = (i + 6) % t.N; me.a = t.ANG[i]; me.x = t.P[i][0]; me.y = t.P[i][1];
    if (k === 0) { me.vx = Math.cos(me.a) * 400; me.vy = Math.sin(me.a) * 400; }
    if (lead) { lead.a = t.ANG[i]; lead.x = t.P[i][0] + Math.cos(lead.a) * 70; lead.y = t.P[i][1] + Math.sin(lead.a) * 70; lead.vx = Math.cos(lead.a) * 400; lead.vy = Math.sin(lead.a) * 400; }
    R.step(r, 1 / 120, { steer: 0, thr: true, brk: false }); draft = Math.max(draft, me.draft); }
  return { speed: me.fwd, draft }; };
const alone = run(false), tow = run(true);
console.log(JSON.stringify({ alone, tow }));""")
    assert r["tow"]["draft"] > 0.3 and r["alone"]["draft"] < 0.01
    assert r["tow"]["speed"] > r["alone"]["speed"] + 3
