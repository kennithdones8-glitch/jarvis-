"""Kerbside Grand Prix engine (static/racer.js) beyond the original rules: AI personalities drive differently and
keep their identity, faster cars overtake instead of ramming, stuck or lost cars recover, every race mode follows its
rules (sprint, elimination, time trial, drift, rival), rain costs grip, contact causes damage, a six-car grid fits
behind the line, and the menus and new files load from this Mac only (CSP intact, no inline code or styles)."""

import json
import re
import shutil
import subprocess

import pytest
from test_dashboard import call

from jarvis.server.app import STATIC

NODE = shutil.which("node")
NEW_FILES = ["racer-data.js", "racer-career.js", "racer-audio.js", "racer-modes.js", "racer-render.js", "racer-ui.js"]


def js(code: str):
    if not NODE:
        pytest.skip("node not installed")
    pre = (f"const R = require({json.dumps(str(STATIC / 'racer.js'))}), C = require({json.dumps(str(STATIC / 'racer-career.js'))});\n"
           "const drive = (r, max = 300, you = null) => { let t = 0; while (r.state !== 'done' && t < max) { R.step(r, 1 / 120, typeof you === 'function' ? you(r) : you); t += 1 / 120; } return t; };\n"
           "const solo = (d, o = {}) => R.newRace({ track: 'kerbside', mode: 'circuit', laps: 2, field: [d], ...o });\n")
    out = subprocess.run([NODE, "-e", pre + code], capture_output=True, text=True, timeout=240, check=True)
    return json.loads(out.stdout)


def test_personalities_drive_differently():
    r = js("""
const t = {};
for (const p of Object.keys(R.PERSONA)) {
  const r = R.newRace({ track: "ridge", mode: "circuit", laps: 2, level: "hard", field: [{ code: "AI", name: p, personality: p, skill: 1 }], playerSlot: 1 });
  r.cars[0].x = r.cars[0].y = -9999;               // park you out of the way
  r.cars[0].out = true;
  let tt = 0; while (!r.cars[1].done && tt < 200) { R.step(r, 1 / 120, { steer: 0, thr: false, brk: false }); tt += 1 / 120; }
  t[p] = r.cars[1].finish;
}
console.log(JSON.stringify(t));""")
    assert r["technical"] < r["balanced"] < r["beginner"]
    assert r["aggressive"] < r["defensive"] and r["beginner"] == max(r.values())


def test_a_faster_car_overtakes_a_slower_one():
    r = js("""
const r = R.newRace({ track: "harbour", mode: "circuit", laps: 2, field: [{ code: "SLO", personality: "balanced", skill: 0.85 }, { code: "FST", personality: "opportunistic", skill: 1.0 }], playerSlot: 2 });
r.cars[0].out = true; r.cars[0].x = r.cars[0].y = -9999;
drive(r, 80, { steer: 0, thr: false, brk: false });
const [slow, fast] = [r.cars[1], r.cars[2]];
console.log(JSON.stringify({ fastAhead: fast.prog > slow.prog, contacts: fast.contacts, gap: fast.prog - slow.prog }));""")
    assert r["fastAhead"] and r["gap"] > 10


def test_lost_cars_recover_to_the_road():
    r = js("""
const r = R.newRace({ track: "kerbside", mode: "circuit", laps: 3, field: [{ code: "AI", personality: "balanced", skill: 1 }], playerSlot: 1 });
drive(r, 5, { steer: 0, thr: false, brk: false });
const ai = r.cars[1];
ai.a += Math.PI; ai.vx = ai.vy = 0;                   // spun round, stopped
const p0 = ai.prog;
for (let i = 0; i < 120 * 6; i++) R.step(r, 1 / 120, { steer: 0, thr: false, brk: false });
const turned = ai.prog > p0 + 20;
const me = r.cars[0]; me.x = r.trk.OX + 30; me.y = r.trk.OY + 30; me.vx = me.vy = 0;   // you, flung to the edge of the world
const ev0 = r.events.length;
for (let i = 0; i < 120 * 4; i++) R.step(r, 1 / 120, { steer: 0, thr: true, brk: false });
console.log(JSON.stringify({ turned, reset: r.events.slice(ev0).some((e) => e.type === "reset" && e.you), onRoad: R.nearest(r.trk, me.x, me.y, -1)[1] < R.TW }));""")
    assert r["turned"] and r["reset"] and r["onRoad"]


def test_modes_follow_their_rules():
    r = js("""
const sprint = R.newRace({ track: "harbour", mode: "sprint", field: [{ code: "A", skill: 0.9 }] }); drive(sprint);
const tt = R.newRace({ track: "harbour", mode: "timetrial", field: [{ code: "A" }] });
const field = ["a", "b", "c"].map((c, i) => ({ code: c.toUpperCase(), skill: 0.9 + i * 0.03 }));
const elim = R.newRace({ track: "harbour", mode: "elimination", laps: 3, field, playerSlot: 0, player: { spec: { ...R.BASE_SPEC, acc: 520 } } });   // quick, from pole
const outs = []; drive(elim, 300); for (const e of elim.events) if (e.type === "eliminated") outs.push(e.code);
const s = R.summary(elim);
const slow = R.newRace({ track: "harbour", mode: "elimination", laps: 3, field, playerSlot: 3, player: { spec: { ...R.BASE_SPEC, acc: 300 } } });   // slow, from the back
drive(slow, 300); const ss = R.summary(slow);
console.log(JSON.stringify({ sprintLaps: sprint.laps, sprintDone: sprint.cars[0].done, sprintTimes: sprint.cars[0].lapTimes.length, ttCars: tt.cars.length,
  outs, elimOut: elim.cars.filter((c) => c.out).length, summary: { place: s.place, eliminated: s.eliminated, finished: s.finished }, order: s.order,
  slow: { eliminated: ss.eliminated, place: ss.place, state: slow.state, outs: slow.cars.filter((c) => c.out).map((c) => c.code) } }));""")
    assert r["sprintLaps"] == 1 and r["sprintDone"] and r["sprintTimes"] == 1
    assert r["ttCars"] == 1                                     # a time trial has no opponents
    assert len(r["outs"]) == 2 and r["elimOut"] == 2            # one car out after laps 1 and 2 of 3
    s = r["summary"]
    assert not s["eliminated"] and s["finished"] and s["place"] <= 2 and "YOU" not in r["outs"]
    assert r["order"][-1] == r["outs"][0]                       # the first car out ranks last
    assert r["slow"] == {"eliminated": True, "place": 4, "state": "done", "outs": ["YOU"]}   # out after lap 1: your race ends there


def test_drift_points_bank_and_are_lost_on_the_grass():
    r = js("""
// a corner-committing driver scores; the score only grows when a chain banks
const r = R.newRace({ track: "kerbside", mode: "drift", laps: 2, weather: "rain" });
const banks = [], lost = [];
drive(r, 200, (rr) => { const a = R.aiInput(rr, rr.cars[0]); return { steer: Math.abs(a.steer) > 0.2 ? Math.sign(a.steer) : a.steer, thr: true, brk: false, nitro: false }; });
for (const e of r.events) { if (e.type === "drift-bank") banks.push(e.pts); if (e.type === "drift-lost") lost.push(e.pts); }
console.log(JSON.stringify({ score: r.drift.score, banks: banks.reduce((a, b) => a + b, 0), n: banks.length, maxMult: Math.max(...r.events.filter((e) => e.type === "drift-bank").map((e) => e.mult)), done: r.cars[0].done }));""")
    assert r["done"] and r["score"] > 0 and r["score"] == r["banks"] and r["n"] > 3 and r["maxMult"] >= 2


def test_rain_costs_grip_and_contact_causes_damage():
    r = js("""
const lap = (w) => { const r = R.newRace({ track: "oldtown", mode: "timetrial", laps: 2, weather: w }); drive(r); return r.cars[0].finish; };
const r = R.newRace({ track: "kerbside", field: [{ code: "A" }] }); r.state = "race";
const [a, b] = r.cars; b.x = a.x + 30; b.y = a.y; a.vx = 400; a.vy = 0; b.vx = 0; b.vy = 0;
R.step(r, 1 / 120, { steer: 0, thr: false, brk: false });
console.log(JSON.stringify({ dry: lap("dry"), wet: lap("rain"), dmg: a.dmg, contacts: a.contacts, impacts: r.impacts.length }));""")
    assert r["wet"] > r["dry"] * 1.04
    assert r["dmg"] > 0 and r["contacts"] == 1 and r["impacts"] == 1


def test_six_cars_line_up_behind_the_start_line():
    r = js("""
const out = {};
for (const k of Object.keys(R.TRACKS)) {
  const r = R.newRace({ track: k, field: [1, 2, 3, 4, 5].map((i) => ({ code: "A" + i })) });
  const pts = r.cars.map((c) => [c.x, c.y]);
  let minGap = 1e9; for (let i = 0; i < 6; i++) for (let j = i + 1; j < 6; j++) minGap = Math.min(minGap, Math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1]));
  out[k] = { behind: r.cars.every((c) => c.prog < 0), onRoad: r.cars.every((c) => R.nearest(r.trk, c.x, c.y, -1)[1] < R.TW / 2), minGap, you: r.cars[0].code };
}
console.log(JSON.stringify(out));""")
    for k, v in r.items():
        assert v["behind"] and v["onRoad"] and v["minGap"] > 34 and v["you"] == "YOU", (k, v)


def test_the_page_loads_every_game_file_and_keeps_the_csp(dash):
    d, *_ = dash
    for name in NEW_FILES + ["racer.js", "racer.css"]:
        status, headers, body = call(d, f"/static/{name}")
        assert status == 200, name
    status, headers, body = call(d, "/")
    html = body.decode()
    order = [html.index(f'<script src="/static/{n}" defer></script>') for n in ["racer-data.js", "racer-career.js", "racer-audio.js", "racer.js", "racer-modes.js", "racer-render.js", "racer-ui.js"]]
    assert order == sorted(order)                                 # data before career before engine before menus
    assert "<script>" not in html and "script-src 'self'" in headers.get("Content-Security-Policy", "")
    for name in NEW_FILES + ["racer.js"]:
        code = (STATIC / name).read_text()
        for banned in ("fetch(", "XMLHttpRequest", "WebSocket", "innerHTML", 'setAttribute("style"', "eval(", "new Function"):
            assert banned not in code, (name, banned)


def test_no_text_in_the_game_is_under_12px():
    css = (STATIC / "racer.css").read_text()
    sizes = [float(m) for m in re.findall(r"font(?:-size)?:[^;]*?\b(\d+(?:\.\d+)?)px", css)]
    assert sizes and min(sizes) >= 12


def test_sound_is_optional():
    r = js(f"""
const A = require({json.dumps(str(STATIC / 'racer-audio.js'))});
const a = A.create({{}});          // Node has no Web Audio: every call must be a harmless no-op
a.unlock(); a.update({{ speed: 300, top: 600, slip: 0, boost: false, on: true }}); a.beep(3); a.finish(true); a.stop();
console.log(JSON.stringify({{ ok: true }}));""")
    assert r["ok"]


def test_races_log_overtakes_contacts_and_who_caused_them():
    r = js("""
const r = R.newRace({ track: "kerbside", field: [1, 2, 3, 4, 5].map((i) => ({ code: "A" + i, skill: 0.88 + i * 0.025, personality: ["aggressive", "defensive", "opportunistic", "balanced", "technical"][i - 1] })) });
const evs = []; let t = 0;
while (r.state !== "done" && t < 200) { R.step(r, 1 / 120, null); t += 1 / 120; evs.push(...r.events.filter((e) => e.type === "overtake")); r.events.length = 0; }
const s = R.summary(r), ids = r.cars.map((c) => c.id);
console.log(JSON.stringify({ n: r.log.overtakes.length, evs: evs.length, ok: r.log.overtakes.every((o) => ids.includes(o.by) && ids.includes(o.on) && o.by !== o.on),
  contactsOk: r.log.contacts.every((c) => [c.a, c.b].includes(c.by)), rivals: Object.keys(s.rivals), mine: Object.values(s.rivals).reduce((a, o) => a + o.passedThem + o.passedYou, 0),
  mineLog: r.log.overtakes.filter((o) => o.by === "YOU" || o.on === "YOU").length }));""")
    assert r["n"] > 5 and r["evs"] == r["n"] and r["ok"] and r["contactsOk"]
    assert r["rivals"] == ["A1", "A2", "A3", "A4", "A5"] and r["mine"] == r["mineLog"]


def test_the_simulation_file_has_no_page_code():
    for name in ("racer.js", "racer-modes.js"):
        code = (STATIC / name).read_text()
        assert "document" not in code and "requestAnimationFrame" not in code and "localStorage" not in code, name
    code = (STATIC / "racer.js").read_text()
    assert "document" not in code and "requestAnimationFrame" not in code and "localStorage" not in code
    render = (STATIC / "racer-render.js").read_text()
    assert "mount" in render and "unmount" in render and "restart" in render
