"""Kerbside Grand Prix class balance: with the AI driving each stock car around all four tracks, every S-class car
is quicker than every A-class car, every A quicker than every B, and every B quicker than every C. Paying for a
higher class always buys pace."""

import json
import shutil
import subprocess

import pytest

from jarvis.server.app import STATIC

NODE = shutil.which("node")


def test_each_class_is_quicker_than_the_class_below():
    if not NODE:
        pytest.skip("node not installed")
    code = (f"const R = require({json.dumps(str(STATIC / 'racer.js'))}), C = require({json.dumps(str(STATIC / 'racer-career.js'))}),"
            f" D = require({json.dumps(str(STATIC / 'racer-data.js'))});\n" + """
const lap = (id, track) => { const r = R.newRace({ track, mode: "circuit", laps: 2, seed: 3, field: [{ id: "ai", code: "AI", name: "AI", color: "#fff", spec: C.carStats(id, C.carState(id)), skill: 1 }], playerSlot: 1 });
  const me = r.cars[0]; me.out = true; me.x = r.trk.OX + 25; me.y = r.trk.OY + 25; let t = 0; const ai = r.cars[1];
  while (!ai.done && t < 300) { R.step(r, 1 / 120, { steer: 0, thr: false, brk: false }); t += 1 / 120; } return ai.done ? ai.finish / 2 : 150; };
const out = {};
for (const [id, c] of Object.entries(D.CARS)) { if (c.police) continue; const avg = ["kerbside", "harbour", "oldtown", "ridge"].reduce((a, k) => a + lap(id, k), 0) / 4; (out[c.cls] = out[c.cls] || []).push([id, avg]); }
console.log(JSON.stringify(out));""")
    out = subprocess.run([NODE, "-e", code], capture_output=True, text=True, timeout=600, check=True)
    r = json.loads(out.stdout)
    order = ["S", "A", "B", "C"]
    for hi, lo in zip(order, order[1:]):
        slowest_hi = max(r[hi], key=lambda x: x[1])
        fastest_lo = min(r[lo], key=lambda x: x[1])
        assert slowest_hi[1] < fastest_lo[1], f"{slowest_hi[0]} ({hi}) is no quicker than {fastest_lo[0]} ({lo})"
