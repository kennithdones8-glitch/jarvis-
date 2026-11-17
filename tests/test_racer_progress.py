"""Kerbside Grand Prix progression (phase 5): the team climbs levels with real perks, every car has a performance
rating that moves with upgrades and events say what they ask for, the prize money explains itself (with bonuses for
racing clean and overtaking), achievements pay out (money or exclusive looks you can't buy), and Priya's extra
contract slot is real."""

import json
import shutil
import subprocess

import pytest

from jarvis.server.app import STATIC

NODE = shutil.which("node")


def js(code: str):
    if not NODE:
        pytest.skip("node not installed")
    pre = (f"const C = require({json.dumps(str(STATIC / 'racer-career.js'))}), D = require({json.dumps(str(STATIC / 'racer-data.js'))});\n"
           "const sum = (o) => ({ mode: 'circuit', track: 'kerbside', laps: 3, place: 1, of: 4, finished: true, eliminated: false, total: 70, best: 22, lapTimes: [24, 23, 22], drift: 0, contacts: 0, damage: 0,"
           " order: ['YOU', 'pip', 'otto', 'dex'], beat: ['pip', 'otto', 'dex'], rivals: {}, ...o });\n"
           "let n = 0; const race = (s, o, kind = 'side', ev = { id: 'e', title: 'T', tier: 2, goal: { type: 'place', max: 3 } }) => C.applyResult(s, { kind, event: ev, raceId: 'r' + (++n) }, sum(o));\n")
    out = subprocess.run([NODE, "-e", pre + code], capture_output=True, text=True, timeout=120, check=True)
    return json.loads(out.stdout)


def test_the_team_climbs_levels_with_real_perks():
    r = js("""
const at = (rep) => { const s = C.fresh(); s.team.rep = rep; return s; };
const repair = (s) => { s.garage.owned.pacer.dmg = 0.5; const m0 = s.money = 10000; C.repair(s, "pacer"); return m0 - s.money; };
const upg = (s) => C.upgradeCost("pacer", "engine", 0, s);
const prize = (s) => race(s, { contacts: 1 }, "side", { id: "x" + Math.random(), tier: 2, goal: { type: "place", max: 3 } }).money;
const lv = [0, 40, 100, 200, 350].map((r) => C.teamLevel(at(r)).i);
const p = C.fresh(); C.hire(p, "priya");
const grow = C.fresh(); grow.team.rep = 38; const out = race(grow, {});
console.log(JSON.stringify({ lv, repair: [repair(at(0)), repair(at(40))], upg: [upg(at(0)), upg(at(200))], prize: [prize(at(0)), prize(at(100))],
  slots: [C.contractSlots(at(0)), C.contractSlots(at(350)), C.contractSlots(p)], grow: [grow.team.rep, out.teamRep, out.notes.some((x) => x.includes("Licensed workshop"))],
  podium: race(C.fresh(), { place: 3, order: ["pip", "otto", "YOU", "dex"], beat: ["dex"] }).teamRep, loss: race(C.fresh(), { place: 4, order: ["pip", "otto", "dex", "YOU"], beat: [] }).teamRep || 0 }));""")
    assert r["lv"] == [0, 1, 2, 3, 4]
    assert r["repair"][1] == pytest.approx(r["repair"][0] * 0.85, abs=2)
    assert r["upg"][1] == pytest.approx(r["upg"][0] * 0.9, abs=10)
    assert r["prize"][1] == pytest.approx(r["prize"][0] * 1.05, abs=10)
    assert r["slots"] == [3, 4, 4]                                  # Priya's extra slot is real now
    assert r["grow"] == [40, 2, True] and r["podium"] == 1 and r["loss"] == 0


def test_ratings_move_with_upgrades_and_events_say_what_they_ask_for():
    r = js("""
const rate = (id, lv) => { const st = C.carState(id); for (const p of Object.keys(st.upgrades)) st.upgrades[p] = lv; return C.rating(C.carStats(id, st)); };
const med = (cls) => { const v = Object.entries(D.CARS).filter(([, c]) => c.cls === cls && !c.police).map(([id]) => rate(id, 0)).sort((a, b) => a - b); return v[v.length >> 1]; };
const s = C.fresh();
console.log(JSON.stringify({ up: [rate("pacer", 0), rate("pacer", 1), rate("pacer", 3)], cls: ["C", "B", "A", "S"].map(med),
  rec: [C.recommended(s, C.mission("c1-clubnight")), C.recommended(s, C.mission("c5-finale")), C.recommended(s, C.mission("c1-shakedown"))] }));""")
    u = r["up"]
    assert u[0] < u[1] < u[2] and u[2] - u[0] > 250
    c = r["cls"]
    assert c[0] < c[1] < c[2] < c[3]                                # classes are tiers of rating
    assert r["rec"][0] < r["rec"][1] and r["rec"][2] > 0            # the finale asks far more than club night


def test_prize_money_explains_itself_and_rewards_racing_well():
    r = js("""
const clean = race(C.fresh(), { rivals: { dex: { passedThem: 2 }, pip: { passedThem: 1 } } });
const dirty = race(C.fresh(), { contacts: 3 });
const sumOf = (o) => o.breakdown.reduce((a, b) => a + b.amount, 0);
console.log(JSON.stringify({ clean: [clean.money, sumOf(clean), clean.breakdown.map((b) => b.label)], dirty: [dirty.money, dirty.breakdown.map((b) => b.label)] }));""")
    c, d = r["clean"], r["dirty"]
    assert abs(c[0] - c[1]) <= 30                                   # the lines add up (to rounding)
    assert any("Clean race" in x for x in c[2]) and any("3 overtakes" in x for x in c[2])
    assert not any("Clean race" in x for x in d[1]) and c[0] > d[0]


def test_achievements_pay_out_and_exclusive_looks_must_be_earned():
    r = js("""
const s = C.fresh(); s.money = 10000; const m0 = s.money;
const first = race(s, {}); const paid = s.money - m0 - first.money;
const again = (() => { const m1 = s.money; const o = race(s, {}); return s.money - m1 - o.money; })();
const before = [C.setLook(s, "pacer", "wheels", "chrome").ok, C.setLook(s, "pacer", "finish", "chrome").ok, C.setLook(s, "pacer", "decal", "laurel").ok];
C.grant(s, "collector"); s.achievements.champion = 1;
const after = [C.setLook(s, "pacer", "wheels", "chrome").ok, C.setLook(s, "pacer", "finish", "chrome").ok, C.setLook(s, "pacer", "decal", "laurel").ok];
const freebies = C.carState("pacer").bought;
console.log(JSON.stringify({ paid, again, before, after, notFree: [freebies.wheels.includes("chrome"), freebies.finish.includes("chrome"), freebies.decal.includes("laurel")],
  cost: s.money, back: C.importSave(C.exportSave(s)).save.garage.owned.pacer.wheels }));""")
    assert r["paid"] == 500 and r["again"] == 0                   # first win pays ₭500, once
    assert r["before"] == [False, False, False] and r["after"] == [True, True, False]   # laurel still needs the story win
    assert r["notFree"] == [False, False, False] and r["back"] == "chrome"
