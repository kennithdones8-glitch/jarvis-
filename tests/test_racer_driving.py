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
