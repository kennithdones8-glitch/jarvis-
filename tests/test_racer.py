"""Kerbside Grand Prix (the Race tab on the Games page): a full race finishes with honest lap counts on every track,
no track crosses itself, the cars wait for the lights, driving backwards over the line never scores a lap, nitro is
faster and runs out, the ghost replays your best flying lap, the levels change how fast JARVIS drives, and the page
loads the game from this Mac only (no inline code, CSP intact)."""

import json
import re
import shutil
import subprocess

import pytest
from test_dashboard import call

from jarvis.server.app import STATIC

NODE = shutil.which("node")
RACER = str(STATIC / "racer.js")
TRACKS = ["kerbside", "harbour", "ridge"]


def js(code: str):
    if not NODE:
        pytest.skip("node not installed")
    out = subprocess.run([NODE, "-e", f"const R = require({json.dumps(RACER)});\n{code}"], capture_output=True, text=True,
                         timeout=180, check=True)
    return json.loads(out.stdout)


RUN = """
const run = (opts) => {
  const r = R.newRace(opts); let t = 0;
  while (r.cars.some((c) => !c.done) && t < 400) { R.step(r, 1 / 120, null); t += 1 / 120; }
  return r;
};
"""


@pytest.mark.parametrize("track", TRACKS)
def test_a_full_race_finishes_with_three_honest_laps_for_every_car(track):
    r = js(RUN + f"""
const r = run({{ track: {json.dumps(track)}, level: "medium", seed: 3 }});
console.log(JSON.stringify({{ state: r.state, track: r.track, cars: r.cars.map((c) => ({{ code: c.code, laps: c.laps, done: c.done,
  times: c.lapTimes, finish: c.finish }})), order: R.standings(r).map((c) => c.code) }}));""")
    assert r["state"] == "done" and r["track"] == track
    for c in r["cars"]:
        assert c["done"] and c["laps"] == 3 and len(c["times"]) == 3, c
        assert all(12 < t < 60 for t in c["times"]), c
        assert abs(sum(c["times"]) - c["finish"]) < 1e-6
    finishes = {c["code"]: c["finish"] for c in r["cars"]}
    assert r["order"] == sorted(finishes, key=finishes.get)                 # classification is by finishing time


def test_no_track_runs_into_itself():
    # Separate parts of a track keep their tarmac and gravel apart (TW + 90 wide), so a corner can't be cut across.
    r = js("""
const out = {};
for (const k of Object.keys(R.TRACKS)) {
  const t = R.track(k); let min = 1e9;
  for (let i = 0; i < t.N; i++) for (let j = i + 1; j < t.N; j++) {
    if (Math.min(j - i, t.N - j + i) * R.SP < R.TW * 2.2) continue;
    min = Math.min(min, Math.hypot(t.P[i][0] - t.P[j][0], t.P[i][1] - t.P[j][1]));
  }
  out[k] = min;
}
console.log(JSON.stringify(out));""")
    assert sorted(r) == sorted(TRACKS)
    for k, d in r.items():
        assert d > 150 + 90, (k, d)


def test_cars_wait_on_the_grid_for_the_lights():
    # Regression: holding the brake on the grid used to mean reverse, and the field backed off the track.
    r = js("""
const r = R.newRace({}); const start = r.cars.map((c) => [c.x, c.y]);
for (let i = 0; i < 120 * 4; i++) R.step(r, 1 / 120, { steer: 1, thr: true, brk: false, nitro: true });   // you mash everything
console.log(JSON.stringify({ state: r.state, moved: Math.max(...r.cars.map((c, i) => Math.hypot(c.x - start[i][0], c.y - start[i][1]))),
  on: r.cars.every((c) => c.on), nitro: r.cars[0].nitro }));""")
    assert r["state"] == "lights" and r["moved"] < 1 and r["on"] and r["nitro"] == pytest.approx(0.3)


def test_driving_backwards_over_the_line_never_counts_a_lap():
    r = js("""
const r = R.newRace({}), me = r.cars[0], t = r.trk;
while (r.state === "lights") R.step(r, 1 / 120, { steer: 0, thr: false, brk: false });
let i = me.idx;
for (let k = 0; k < t.N + 40; k++) {                 // a whole lap the wrong way round, then a little more
  i = (i - 1 + t.N) % t.N; me.x = t.P[i][0]; me.y = t.P[i][1]; me.vx = me.vy = 0;
  R.step(r, 1 / 120, { steer: 0, thr: false, brk: false });
}
console.log(JSON.stringify({ laps: me.laps, prog: me.prog, events: r.events.filter((e) => e.type !== "go").length }));""")
    assert r["laps"] == 0 and r["events"] == 0 and r["prog"] < 0


def test_nitro_is_faster_runs_out_and_refills():
    r = js("""
// The harbour's long opening straight: the same car, with and without nitro held (the AI steers, you hold the pedal).
const top = (nitro) => {
  const r = R.newRace({ track: "harbour" }), me = r.cars[0];
  r.state = "race"; r.cars.splice(1);                 // just you, no traffic
  me.nitro = 1; let best = 0, emptyAt = null;
  for (let i = 0; i < 120 * 4; i++) {
    R.step(r, 1 / 120, { steer: R.aiInput(r, me).steer, thr: true, brk: false, nitro });
    best = Math.max(best, me.fwd); if (emptyAt === null && me.nitro === 0) emptyAt = i / 120;
  }
  const afterEmpty = me.nitro;
  for (let i = 0; i < 120 * 5; i++) R.step(r, 1 / 120, { ...R.aiInput(r, me), nitro: false });
  return { best, emptyAt, afterEmpty, refilled: me.nitro };
};
console.log(JSON.stringify({ with: top(true), without: top(false) }));""")
    assert r["with"]["best"] > r["without"]["best"] * 1.1
    assert r["with"]["emptyAt"] is not None and 2 < r["with"]["emptyAt"] < 3.2     # a full tank lasts ~2.5 s
    assert r["with"]["refilled"] > r["with"]["afterEmpty"]                       # driving on the tarmac refills it
    assert r["without"]["emptyAt"] is None


def test_easy_ai_never_uses_nitro_and_harder_levels_make_jarvis_faster():
    r = js(RUN + """
const used = { easy: false, hard: false };
for (const lv of ["easy", "hard"]) {
  const r = R.newRace({ track: "harbour", level: lv, seed: 5 }); let t = 0;
  while (r.cars.some((c) => !c.done) && t < 400) { R.step(r, 1 / 120, null); t += 1 / 120; if (r.cars.some((c) => c.ai && c.boost)) used[lv] = true; }
}
const t = (lv) => run({ track: "kerbside", level: lv, seed: 5 }).cars.find((c) => c.code === "JRV").finish;
console.log(JSON.stringify({ used, easy: t("easy"), medium: t("medium"), hard: t("hard") }));""")
    assert r["used"] == {"easy": False, "hard": True}
    assert r["hard"] < r["medium"] < r["easy"]


def test_the_ghost_is_your_best_flying_lap_and_replays_it():
    r = js(RUN + """
const r = run({ track: "ridge", seed: 9 });
const laps = r.events.filter((e) => e.type === "lap" || e.type === "finish");
const ghosts = laps.filter((e) => e.ghost).map((e) => ({ lap: e.lap, time: e.time, n: e.ghost.pts.length / 3 }));
// Replay: start a new race with that ghost; on lap 2 it should sit near where you drove at the same lap time.
const g = r.ghost, r2 = R.newRace({ track: "ridge", seed: 9, ghost: g }); let seen = 0, far = 0, onLap1 = 0;
while (!r2.cars[0].done && r2.t < 400) {
  R.step(r2, 1 / 120, null);
  const p = R.ghostPose(r2);
  if (r2.cars[0].laps === 0 && p) onLap1++;
  if (p && r2.cars[0].laps >= 1) { seen++; const t = r2.trk, d = R.nearest(t, p[0], p[1], -1)[1]; if (d > R.TW / 2 + 20) far++; }
}
console.log(JSON.stringify({ ghosts, best: g.time, minFlying: Math.min(...ghosts.map((x) => x.time)), seen, far, onLap1 }));""")
    assert [g["lap"] for g in r["ghosts"]] == [2, 3]                  # lap 1 (from the grid) never becomes a ghost
    assert r["best"] == r["minFlying"]
    for g in r["ghosts"]:
        assert abs(g["n"] * 0.05 - g["time"]) < 0.2                   # one sample every 50 ms for the whole lap
    assert r["seen"] > 120 * 10 and r["far"] == 0 and r["onLap1"] == 0   # it drives the track, from lap 2 on


def test_the_page_serves_the_race_and_keeps_the_csp(dash):
    d, *_ = dash
    status, headers, body = call(d, "/static/racer.js")
    assert status == 200 and b"JarvisRacer" in body
    status, headers, body = call(d, "/static/racer.css")
    assert status == 200 and headers["Content-Type"].startswith("text/css") and b".race-stage" in body
    status, headers, body = call(d, "/")
    html = body.decode()
    assert '<script src="/static/racer.js" defer></script>' in html and "<script>" not in html
    assert '<link rel="stylesheet" href="/static/racer.css">' in html
    assert "script-src 'self'" in headers.get("Content-Security-Policy", "")
    code = (STATIC / "racer.js").read_text()
    for banned in ("fetch(", "XMLHttpRequest", "WebSocket", "innerHTML", "setAttribute(\"style\"", "eval("):
        assert banned not in code, banned
    app = (STATIC / "app.js").read_text()
    assert '["race", "◆ Race"]' in app and "renderRace()" in app


def test_race_text_is_never_under_12px():
    css = (STATIC / "racer.css").read_text()
    sizes = [float(m) for m in re.findall(r"font(?:-size)?:[^;]*?\b(\d+(?:\.\d+)?)px", css)]
    assert sizes and min(sizes) >= 12, sorted(sizes)[:5]
