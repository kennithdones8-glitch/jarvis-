"""Kerbside Grand Prix (the Race tab on the Games page): a full race finishes with honest lap counts, the cars wait for
the lights, driving backwards over the line never scores a lap, the levels change how fast JARVIS drives, and the page
loads the game from this Mac only (no inline code, CSP intact)."""

import json
import shutil
import subprocess

import pytest
from test_dashboard import call

from jarvis.server.app import STATIC

NODE = shutil.which("node")
RACER = str(STATIC / "racer.js")


def js(code: str):
    if not NODE:
        pytest.skip("node not installed")
    out = subprocess.run([NODE, "-e", f"const R = require({json.dumps(RACER)});\n{code}"], capture_output=True, text=True,
                         timeout=120, check=True)
    return json.loads(out.stdout)


RUN = """
const run = (level, seed) => {
  const r = R.newRace({ level, seed }); let t = 0;
  while (r.cars.some((c) => !c.done) && t < 400) { R.step(r, 1 / 120, null); t += 1 / 120; }
  return r;
};
"""


def test_a_full_race_finishes_with_three_honest_laps_for_every_car():
    r = js(RUN + """
const r = run("medium", 3);
console.log(JSON.stringify({ state: r.state, cars: r.cars.map((c) => ({ code: c.code, laps: c.laps, done: c.done,
  times: c.lapTimes, finish: c.finish })), order: R.standings(r).map((c) => c.code) }));""")
    assert r["state"] == "done"
    for c in r["cars"]:
        assert c["done"] and c["laps"] == 3 and len(c["times"]) == 3, c
        assert all(15 < t < 60 for t in c["times"]), c                   # a lap of this circuit takes ~25 s
        assert abs(sum(c["times"]) - c["finish"]) < 1e-6
    finishes = {c["code"]: c["finish"] for c in r["cars"]}
    assert r["order"] == sorted(finishes, key=finishes.get)                 # classification is by finishing time


def test_cars_wait_on_the_grid_for_the_lights():
    # Regression: holding the brake on the grid used to mean reverse, and the field backed off the track.
    r = js("""
const r = R.newRace({}); const start = r.cars.map((c) => [c.x, c.y]);
for (let i = 0; i < 120 * 4; i++) R.step(r, 1 / 120, { steer: 1, thr: true, brk: false });   // you mash the throttle
console.log(JSON.stringify({ state: r.state, moved: Math.max(...r.cars.map((c, i) => Math.hypot(c.x - start[i][0], c.y - start[i][1]))),
  on: r.cars.every((c) => c.on) }));""")
    assert r["state"] == "lights" and r["moved"] < 1 and r["on"]


def test_driving_backwards_over_the_line_never_counts_a_lap():
    r = js("""
const r = R.newRace({}); const me = r.cars[0];
while (r.state === "lights") R.step(r, 1 / 120, { steer: 0, thr: false, brk: false });
let i = me.idx;
for (let k = 0; k < R.N + 40; k++) {                 // a whole lap the wrong way round, then a little more
  i = (i - 1 + R.N) % R.N; me.x = R.TRACK[i][0]; me.y = R.TRACK[i][1]; me.vx = me.vy = 0;
  R.step(r, 1 / 120, { steer: 0, thr: false, brk: false });
}
console.log(JSON.stringify({ laps: me.laps, prog: me.prog, events: r.events.filter((e) => e.type !== "go").length }));""")
    assert r["laps"] == 0 and r["events"] == 0 and r["prog"] < 0


def test_harder_levels_make_jarvis_faster():
    r = js(RUN + """
const t = (lv) => run(lv, 5).cars.find((c) => c.code === "JRV").finish;
console.log(JSON.stringify({ easy: t("easy"), medium: t("medium"), hard: t("hard") }));""")
    assert r["hard"] < r["medium"] < r["easy"]


def test_the_page_serves_the_race_and_keeps_the_csp(dash):
    d, *_ = dash
    status, headers, body = call(d, "/static/racer.js")
    assert status == 200 and b"JarvisRacer" in body
    status, headers, body = call(d, "/")
    html = body.decode()
    assert '<script src="/static/racer.js" defer></script>' in html and "<script>" not in html
    assert "script-src 'self'" in headers.get("Content-Security-Policy", "")
    code = (STATIC / "racer.js").read_text()
    for banned in ("fetch(", "XMLHttpRequest", "WebSocket", "innerHTML", "setAttribute(\"style\"", "eval("):
        assert banned not in code, banned
    app = (STATIC / "app.js").read_text()
    assert '["race", "◆ Race"]' in app and "renderRace()" in app
