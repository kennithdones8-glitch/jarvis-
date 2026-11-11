"""Kerbside Grand Prix living world (racer-career.js): the calendar moves with each race, the weekly special pays
more, winning in a district grows your share until you run it (and unlocks a turf war), rumours are heard by
reputation (sooner with a scout) and reveal secret events whose rewards pay once, and rivals race each other
off-screen in the real simulation."""

import json
import shutil
import subprocess

import pytest

from jarvis.server.app import STATIC

NODE = shutil.which("node")


def js(code: str):
    if not NODE:
        pytest.skip("node not installed")
    pre = (f"const C = require({json.dumps(str(STATIC / 'racer-career.js'))}), D = require({json.dumps(str(STATIC / 'racer-data.js'))}), R = require({json.dumps(str(STATIC / 'racer.js'))});\n"
           "const sum = (o) => ({ mode: 'circuit', track: 'harbour', laps: 3, place: 1, of: 4, finished: true, eliminated: false, total: 50, best: 15, lapTimes: [17, 16, 15], drift: 0, contacts: 0, order: ['YOU'], beat: [], rivals: {}, ...o });\n"
           "let n = 0; const race = (s, ev, o = {}, kind = 'side') => C.applyResult(s, { kind, event: { title: 'T', tier: 2, goal: { type: 'place', max: 1 }, ...ev }, raceId: 'w' + (++n) }, sum(o));\n")
    out = subprocess.run([NODE, "-e", pre + code], capture_output=True, text=True, timeout=180, check=True)
    return json.loads(out.stdout)


def test_the_calendar_moves_and_the_weekly_special_pays_more():
    r = js("""
const s = C.fresh(); s.districts.push("harbour"); s.rep = 300;
const d0 = s.world.day, f = C.featured(s), w0 = C.weekday(s);
const t = JSON.parse(JSON.stringify(s));
const special = race(s, { ...f, id: f.id }), plain = race(t, { ...f, id: "not-special", district: f.district });
console.log(JSON.stringify({ d0, d1: s.world.day, w0, w1: C.weekday(s), special: special.money, plain: plain.money, f2: C.featured(s).id !== f.id || true }));""")
    assert r["d1"] == r["d0"] + 1 and r["w0"] != r["w1"]
    assert r["special"] >= round(r["plain"] * 1.45, -1)                   # +50% (rounded to tens)


def test_winning_in_a_district_takes_it_over_and_opens_a_turf_war():
    r = js("""
const s = C.fresh(); s.districts.push("harbour"); const seen = [];
for (let i = 0; i < 8; i++) { const o = race(s, { id: "h" + i, district: "harbour" }); seen.push(Math.round(o.influence.after)); }
const lost = race(s, { id: "l", district: "harbour" }, { place: 4, finished: true });
console.log(JSON.stringify({ seen, runs: C.runs(s, "harbour"), turf: C.turfEvents(s).map((e) => e.id), lost: lost.influence, ach: Object.keys(s.achievements), wire: s.world.news.map((n) => n.text) }));""")
    assert r["seen"][0] == 28 and r["seen"][-1] >= 75 and r["runs"] is True
    assert r["turf"] == ["turf-harbour"] and "turf" in r["ach"]
    assert r["lost"]["after"] < r["lost"]["before"]                        # a bad result costs ground
    assert any("takes over Harbourside" in t for t in r["wire"])


def test_rumours_are_earned_a_scout_hears_them_first_and_secret_rewards_pay_once():
    r = js("""
const a = C.fresh(); a.rep = 20; race(a, { id: "x1", district: "park" });
const b = C.fresh(); b.rep = 20; C.hire(b, "lio"); const heard = race(b, { id: "x2", district: "park" }).rumours.map((x) => x.id);
const sec = C.secretEvents(b).find((e) => e.id === "x-docks"), m0 = b.money;
const won = race(b, sec, { mode: "sprint" }), m1 = b.money, again = race(b, sec, { mode: "sprint" });
const g = C.fresh(); g.rep = 200; race(g, { id: "y", district: "park" }); const ghost = C.secretEvents(g).find((e) => e.id === "x-ghost");
race(g, ghost, { mode: "timetrial", place: 1, of: 1, total: 37 }); 
console.log(JSON.stringify({ aHeard: Object.keys(a.world.rumors), heard, gain: m1 - m0 - won.money, again: b.money - m1 - again.money, state: b.world.rumors["ru-docks"], phantom: C.carAvailable(g, "phantom").ok }));""")
    assert r["aHeard"] == [] and "ru-docks" in r["heard"]                  # 40 rep after the race: too early alone, enough with Lio
    assert r["gain"] == 3000 and r["again"] == 0 and r["state"] == "done"
    assert r["phantom"] is True                                            # the ghost lap unlocks the Phantom early


def test_rivals_race_each_other_for_real():
    r = js("""
const s = C.fresh(); for (const id of ["dex", "mara", "benny"]) s.rivals[id] = { ...s.rivals[id], races: 1, wins: 0, losses: 0, respect: 0 };
const res = [];
for (let d = 1; d <= 4; d++) { s.world.day = d; const x = C.rivalSim(s); if (x) res.push(x); }
// replay the first one independently: same seed, same field, same track -> same winner
const s2 = C.fresh(); for (const id of ["dex", "mara", "benny"]) s2.rivals[id] = { ...s2.rivals[id], races: 1 }; s2.world.day = 1; const again = C.rivalSim(s2);
console.log(JSON.stringify({ res, again, wire: s.world.news.map((x) => x.text) }));""")
    assert len(r["res"]) >= 2 and all(x["winner"] != x["loser"] for x in r["res"])
    assert r["again"] == r["res"][0]                                       # decided by the simulation, reproducibly
    results = [t for t in r["wire"] if "demands a rematch" not in t]          # a close loss can also start a showdown (phase 6)
    assert len(results) == len(r["res"]) and all(" beat " in t and " on " in t for t in results)
