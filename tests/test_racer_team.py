"""Kerbside Grand Prix team and career management (racer-career.js, racer-data.js): sponsor contracts pay once when
their target is reached inside their race limit (and expire otherwise), the team championship runs in seasons of
career race days against the home crews, the team's name and colours are yours, and New Game+ keeps what you've
earned while the story starts again, harder and better paid."""

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


def test_contracts_pay_once_inside_their_race_limit_and_expire_otherwise():
    r = js("""
const s = C.fresh();
const offers0 = C.contractOffers(s).map((k) => k.id), early = C.signContract(s, "k-wins");
s.rep = 60;
const signed = ["k-podiums", "k-clean", "k-wins"].map((id) => C.signContract(s, id).ok), fourth = C.signContract(s, "k-drift"), twice = C.signContract(s, "k-wins");
const m0 = s.money;
race(s, { contacts: 2 }); race(s, {}, "quick"); race(s, {}, "free");                      // practice doesn't count
const mid = s.contracts.map((c) => [c.id, c.progress, c.left]);
const out2 = race(s, {}); const out3 = race(s, { place: 2, order: ["pip", "YOU", "otto", "dex"], beat: ["otto", "dex"] });
const paid = s.money - m0 - out2.money - out3.money - D.CONTRACTS["k-podiums"].pay - D.CONTRACTS["k-clean"].pay - (race(s, {}).money || 0);
const left = s.contracts.map((c) => c.id);
// expiry: a drift contract with no drifting
const e = C.fresh(); e.rep = 60; C.signContract(e, "k-drift"); const notes = []; for (let i = 0; i < 4; i++) notes.push(...race(e, {}).notes);
const drop = (() => { const d = C.fresh(); d.rep = 20; C.signContract(d, "k-podiums"); C.dropContract(d, "k-podiums"); return [d.rep, d.contracts.length]; })();
const back = C.importSave(C.exportSave((() => { const x = C.fresh(); x.rep = 99; C.signContract(x, "k-drag"); x.contracts[0].progress = 1; return x; })())).save.contracts;
console.log(JSON.stringify({ offers0, early: early.ok, signed, fourth: fourth.ok, twice: twice.ok, mid, left, paid, ach: Object.keys(s.achievements).includes("contract"), notes, drop, back }));""")
    assert "k-wins" not in r["offers0"] and "k-podiums" in r["offers0"] and r["early"] is False   # 30 rep needed
    assert r["signed"] == [True, True, True] and r["fourth"] is False and r["twice"] is False
    assert r["mid"] == [["k-podiums", 1, 5], ["k-clean", 0, 4], ["k-wins", 1, 5]]                # quick and free didn't count
    assert r["left"] == [] and r["ach"]                                                               # all three paid out
    assert any("Contract expired" in n and "Sideways Season" in n for n in r["notes"])
    assert r["drop"] == [15, 0]
    assert r["back"] == [{"id": "k-drag", "progress": 1, "left": 5}]


def test_the_team_championship_runs_in_seasons_of_career_race_days():
    r = js("""
const s = C.fresh(); let season = null, earned = 0;
for (let i = 0; i < 4; i++) race(s, {}, "quick");                                           // practice: no season days
const m0 = s.money;
const days0 = s.team.days;
for (let i = 0; i < 10; i++) { const o = race(s, {}); earned += o.money; if (o.season) season = o.season; }
const loser = C.fresh(); let lost = null; for (let i = 0; i < 10; i++) { const o = race(loser, { place: 4, order: ["pip", "otto", "dex", "YOU"], beat: [] }); if (o.season) lost = o.season; }
console.log(JSON.stringify({ days0, season, prize: s.money - m0 - earned, after: [s.team.season, s.team.days, s.team.points, s.team.titles], ach: Object.keys(s.achievements).includes("team_champ"),
  lost: lost && [lost.place, lost.prize, lost.table[0].you], news: s.world.news.some((x) => x.text.includes("team championship")) }));""")
    assert r["days0"] == 0
    s = r["season"]
    assert s["season"] == 1 and s["place"] == 1 and s["table"][0]["you"] and s["table"][0]["points"] == 100 and len(s["table"]) == 6
    assert r["prize"] == 8000 and r["after"] == [2, 0, 0, 1] and r["ach"] and r["news"]
    assert r["lost"][0] > 3 and r["lost"][1] == 0 and r["lost"][2] is False   # finishing fourth every race doesn't win a title


def test_team_identity_and_livery():
    r = js("""
const s = C.fresh();
const bad = [C.setTeam(s, { name: "   " }).ok, C.setTeam(s, { color: "red" }).ok];
const ok = C.setTeam(s, { name: "Nightshift Racing Collective Extra", color: "#38e8ff", color2: "#ff3fa4" }).ok; C.teamLivery(s);
const back = C.importSave(C.exportSave(s)).save;
console.log(JSON.stringify({ bad, ok, team: [back.team.name, back.team.color, back.team.color2], car: [back.garage.owned.pacer.paint, back.garage.owned.pacer.paint2] }));""")
    assert r["bad"] == [False, False] and r["ok"]
    assert r["team"][0] == "Nightshift Racing Collec" and r["team"][1:] == ["#38e8ff", "#ff3fa4"]   # names stop at 24 characters
    assert r["car"] == ["#38e8ff", "#ff3fa4"]


def test_new_game_plus_keeps_what_you_earned_and_starts_the_story_again():
    r = js("""
const s = C.fresh(); const early = C.newGamePlus(s).ok;
s.money = 50000; s.xp = 90000; s.rep = 800; s.garage.owned.kestrel = C.carState("kestrel"); s.garage.owned.kestrel.upgrades.engine = 3; s.garage.current = "kestrel";
s.achievements.first_win = 1; s.records.pursuit.escapes = 4; s.best.kerbside = 18.4; s.endings.legend = 1; s.story.ended = true; s.story.chapter = 6;
s.districts.push("harbour", "ridge"); s.rivals.dex = { wins: 9 }; s.world.influence.park = 90; C.hire(s, "pip"); s.team.name = "Nightshift";
const r1 = C.newGamePlus(s), g = r1.save;
const ev = { id: "e", title: "T", tier: 3, track: "kerbside", mode: "circuit", field: ["dex"], goal: { type: "place", max: 3 } };
const skill0 = C.config(s, ev, "side").field[0].skill, skill1 = C.config(g, ev, "side").field[0].skill;
const pay = (save) => C.applyResult(save, { kind: "side", event: ev, raceId: "p" + Math.random() }, sum({ order: ["YOU", "dex"], beat: ["dex"], of: 2 })).money;
const a = C.fresh(), b = C.fresh(); b.ng = 1;
console.log(JSON.stringify({ early, ok: r1.ok, ng: g.ng, kept: [g.money, g.xp, g.garage.current, g.garage.owned.kestrel.upgrades.engine, g.achievements.first_win, g.records.pursuit.escapes, g.best.kerbside, g.endings.legend, C.hired(g, "pip"), g.team.name],
  reset: [g.story.chapter, g.story.ended, g.districts, Object.keys(g.rivals).length, g.world.influence.park === undefined, g.rep], ach: r1.achievements, skill: [skill0, skill1], pay: [pay(a), pay(b)] }));""")
    assert r["early"] is False and r["ok"] and r["ng"] == 1
    assert r["kept"] == [50000, 90000, "kestrel", 3, 1, 4, 18.4, 1, True, "Nightshift"]
    assert r["reset"] == [1, False, ["park"], 0, True, 200]
    assert r["ach"] == ["new_game_plus"]
    assert r["skill"][1] == pytest.approx(r["skill"][0] + 0.01)
    assert r["pay"][1] == pytest.approx(r["pay"][0] * 1.25, abs=10)
