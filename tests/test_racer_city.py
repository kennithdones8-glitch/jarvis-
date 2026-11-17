"""Kerbside Grand Prix living world (phase 6): your turning points change the city (events open and close, the news
wire reports them), tonight-only events come and go every three race days (the same ones on reload), rivals race
each other for real and the street rankings keep score, a close loss between rivals becomes a showdown you can
gatecrash, crew members argue and you settle it once, and the city has a name for you."""

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
           "const sum = (o) => ({ mode: 'circuit', track: 'kerbside', laps: 3, place: 1, of: 3, finished: true, eliminated: false, total: 70, best: 22, lapTimes: [24, 23, 22], drift: 0, contacts: 0, damage: 0,"
           " order: ['YOU', 'pip', 'otto'], beat: ['pip', 'otto'], rivals: {}, ...o });\n"
           "let n = 0; const race = (s, ev, o = {}) => C.applyResult(s, { kind: 'side', event: ev, raceId: 'w' + (++n) }, sum(o));\n"
           "const ids = (s) => C.sideEvents(s).map((e) => e.id);\n")
    out = subprocess.run([NODE, "-e", pre + code], capture_output=True, text=True, timeout=180, check=True)
    return json.loads(out.stdout)


def test_turning_points_reshape_the_city():
    r = js("""
const pick = (flag) => { const s = C.fresh(); s.districts = Object.keys(D.DISTRICTS); s.rep = 999; s.story.flags[flag] = true; return ids(s); };
const base = (() => { const s = C.fresh(); s.districts = Object.keys(D.DISTRICTS); s.rep = 999; return ids(s); })();
const news = (() => { const s = C.fresh(); s.money = 1e5; const m = C.mission("a-benny-2");
  const i = m.choice.options.findIndex((o) => o.flags && o.flags.benny_saved); C.choose(s, m.id, i); return s.world.news.map((x) => x.text); })();
console.log(JSON.stringify({ base, saved: pick("benny_saved"), lost: pick("benny_lost"), home: pick("mara_home"), alone: pick("mara_alone"), signed: pick("harlan_signed"), exposed: pick("harlan_exposed"), news }));""")
    assert "s-old-revival" in r["saved"] and "s-old-revival" not in r["base"] and "s-old-revival" not in r["lost"]
    assert "s-old-flats" in r["lost"] and "s-old-night" not in r["lost"] and "s-old-night" in r["base"]   # the Brickyard's night race goes with it
    assert "s-harb-tidewater" in r["home"] and "s-harb-marina" in r["alone"] and "s-harb-marina" not in r["home"]
    assert "s-park-harlancup" in r["signed"] and "s-park-crews" in r["exposed"] and "s-park-crews" not in r["signed"]
    assert any("Brickyard stays open" in x for x in r["news"])


def test_tonight_only_events_come_and_go():
    r = js("""
const s = C.fresh(); s.districts = Object.keys(D.DISTRICTS); s.rivals.dex = { wins: 1, losses: 0, races: 1, respect: 0 };
const at = (d) => { s.world.day = d; return C.tonight(s).map((e) => e.id); };
const w = [at(1), at(2), at(3), at(4), at(7)];
const reload = (() => { s.world.day = 5; const a = C.tonight(s).map((e) => e.id); const b = C.tonight(C.validate(JSON.parse(JSON.stringify(s))).save).map((e) => e.id); return [a, b]; })();
s.world.day = 4; const ev = C.tonight(s).find((e) => e.mode !== "pursuit" && e.mode !== "delivery") || C.tonight(s)[0];
s.world.day = 4; const t = C.tonight(s).find((e) => e.mode === "circuit" || e.mode === "sprint" || e.mode === "rival" || e.mode === "drag");
const out = race(s, t, { mode: t.mode });
const after = C.tonight(s).find((e) => e.id === t.id);
let wins = 0; for (let d = 10; d < 40 && !s.achievements.tonight; d += 3) { s.world.day = d; const e = C.tonight(s).find((x) => ["circuit", "sprint", "rival", "drag"].includes(x.mode)); if (e) race(s, e, { mode: e.mode }); }
const kinds = new Set(); for (let d = 1; d < 120; d += 3) { s.world.day = d; for (const e of C.tonight(s)) kinds.add(e.kind); }
s.world.day = 200; race(s, { id: "x", tier: 1, goal: { type: "place", max: 3 } }); const pruned = Object.keys(s.sideDone).filter((k) => /^t\\d/.test(k)).length;
console.log(JSON.stringify({ w, reload, label: out.breakdown.map((b) => b.label), after: after && after.done, ach: !!s.achievements.tonight, kinds: [...kinds], pruned }));""")
    w = r["w"]
    assert w[0] == w[1] == w[2] and w[3] != w[0] and w[4] != w[3] and len(w[0]) == 2   # three race days, then a new set
    assert r["reload"][0] == r["reload"][1]                                              # same events after a reload
    assert any("Tonight only" in x for x in r["label"]) and r["after"] is True
    assert r["ach"] and len(r["kinds"]) >= 5 and r["pruned"] == 0


def test_rivals_race_each_other_and_the_rankings_keep_score():
    r = js("""
const s = C.fresh(); for (const id of ["dex", "mara", "benny"]) s.rivals[id] = { wins: 0, losses: 0, races: 1, respect: 0, passedThem: 0, passedYou: 0, contacts: 0, youHit: 0, theyHit: 0, close: 0, streak: 0 };
s.rivals.dex.wins = 4; s.rivals.dex.losses = 1;
let sims = 0, showdown = null; for (let d = 1; d <= 12; d++) { s.world.day = d; if (C.rivalSim(s)) sims++; if (!showdown && s.world.showdown) showdown = { ...s.world.showdown }; }
const total = Object.values(s.world.ranks).reduce((a, x) => a + x.w, 0), lost = Object.values(s.world.ranks).reduce((a, x) => a + x.l, 0);
const table = C.rankings(s), back = C.validate(JSON.parse(JSON.stringify(s))).save.world, ranks0 = JSON.parse(JSON.stringify(s.world.ranks));
// the showdown: on the map while it lasts, pays double, and earns Gatecrasher
s.world.showdown = { a: "dex", b: "mara", win: Math.floor((s.world.day - 1) / 3) };
const sd = C.tonight(s).find((e) => e.showdown); const out = race(s, sd, { order: ["YOU", "dex", "mara"], beat: ["dex", "mara"] });
const gone = C.tonight(s).some((e) => e.showdown);
// a showdown you never turn up to: the city moves on
const m = C.fresh(); m.world.showdown = { a: "dex", b: "mara", win: 0 }; m.world.day = 10; race(m, { id: "y", tier: 1, goal: { type: "place", max: 3 } });
console.log(JSON.stringify({ sims, total, lost, showdown, you: table.find((x) => x.you), sorted: table.every((x, i) => i === 0 || table[i - 1].pts >= x.pts), back: back.ranks,
  ranks: ranks0, sd: [sd.field, out.breakdown.some((b) => b.label.includes("Showdown")), out.achievements.includes("showdown")], gone, missed: [m.world.showdown, m.world.news.some((x) => x.text.includes("without you"))] }));""")
    assert r["sims"] == 12 and r["total"] == 12 and r["lost"] == 12      # every off-screen race has a winner and a loser
    assert r["you"]["w"] == 4 and r["you"]["l"] == 1 and r["sorted"] and r["back"] == r["ranks"]
    assert r["showdown"] is not None and r["showdown"]["a"] != r["showdown"]["b"]
    assert r["sd"] == [["dex", "mara"], True, True] and r["gone"] is False
    assert r["missed"] == [None, True]


def test_crew_matters_are_settled_once_and_matter():
    r = js("""
const s = C.fresh(); const none = C.matters(s).map((m) => m.id);
C.hire(s, "dex"); const open = C.matters(s).map((m) => m.id);
const nia0 = s.crew.members.nia.loyalty, dex0 = s.crew.members.dex.loyalty, m0 = s.money;
const r1 = C.settle(s, "nia-dex", 0), twice = C.settle(s, "nia-dex", 1);
const h = C.fresh(); h.story.flags.harlan_signed = true; h.money = 100; const broke = C.settle(h, "nia-harlan", 0); const still = C.matters(h).map((m) => m.id);
const back = C.validate(JSON.parse(JSON.stringify(s))).save;
console.log(JSON.stringify({ none, open, r1: r1.ok, twice: twice.ok, nia: s.crew.members.nia.loyalty - nia0, dex: s.crew.members.dex.loyalty - dex0, money: s.money - m0,
  after: C.matters(s).map((m) => m.id), broke: broke.ok, still, back: [back.world.matters, C.matters(back).map((m) => m.id)], faces: D.MATTERS.every((M) => M.who.every((w) => D.CAST[w] && D.CAST[w].face)) }));""")
    assert r["none"] == [] and r["open"] == ["nia-dex"]
    assert r["r1"] and r["twice"] is False and r["nia"] == 2 and r["dex"] == -1 and r["money"] == 600
    assert r["after"] == [] and r["broke"] is False and "nia-harlan" in r["still"]   # can't afford it: nothing changes
    assert r["back"] == [{"nia-dex": 0}, []] and r["faces"]


def test_the_city_has_a_name_for_you_and_old_saves_load():
    r = js("""
const t = (rep) => { const s = C.fresh(); s.rep = rep; return C.repTitle(s); };
const old = C.fresh(); delete old.world.ranks; delete old.world.matters; delete old.world.tonightWins; delete old.world.showdown; old.world.news = [{ day: 3, text: "Old news." }];
const v = C.validate(JSON.parse(JSON.stringify(old))).save.world;
const bad = C.validate(JSON.parse(JSON.stringify({ ...C.fresh(), world: { day: 4, ranks: { nobody: { w: 1 }, dex: { w: "x", l: 2 } }, matters: { "nia-dex": 9, fake: 0 }, showdown: { a: "dex", b: "dex" } } }))).save.world;
console.log(JSON.stringify({ titles: [t(0), t(60), t(700), t(5000)], v: [v.news.length, v.ranks, v.matters, v.tonightWins, v.showdown], bad: [bad.ranks, bad.matters, bad.showdown] }));""")
    assert r["titles"] == ["Unknown", "Local name", "Port Kerbside star", "City legend"]
    assert r["v"] == [1, {}, {}, 0, None]
    assert r["bad"] == [{"dex": {"w": 0, "l": 2}}, {}, None]
