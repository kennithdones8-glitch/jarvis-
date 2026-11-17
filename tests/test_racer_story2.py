"""Kerbside Grand Prix story, phase 4: character stories open when the story reaches them and run in order, a choice
can change the mission that follows (the repo-yard heist), turning points cost and change real things, Victor Harlan
reaches into the finale depending on what you did, the ending follows it, and every line that depends on a choice
can actually be reached."""

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
           " order: ['YOU', 'a', 'b', 'c'], beat: ['a', 'b', 'c'], rivals: {}, team: { you: 18, them: 11, won: true }, delivery: { delivered: true, cargo: 1, left: 5, stops: 4, reached: 4 }, ...o });\n"
           "let n = 0; const play = (s, m, o = {}) => C.applyResult(s, { kind: 'arc', event: C.resolve(s, m), raceId: 'a' + (++n) }, sum(o));\n")
    out = subprocess.run([NODE, "-e", pre + code], capture_output=True, text=True, timeout=120, check=True)
    return json.loads(out.stdout)


def test_character_stories_open_with_the_story_and_run_in_order():
    r = js("""
const s = C.fresh(); const early = C.arcs(s).filter((a) => a.open).map((a) => a.id);
s.story.chapter = 2; const nia = () => C.arcs(s).find((a) => a.id === "nia");
const n1 = nia().next.id; const out1 = play(s, nia().next, { mode: "timetrial", of: 1, total: 25, order: ["YOU"], beat: [] }); const n2 = nia().next.id;
const crew = C.fresh(); crew.story.chapter = 4; const before = C.arcs(crew).find((a) => a.id === "otto").open; C.hire(crew, "otto"); const after = C.arcs(crew).find((a) => a.id === "otto").open;
const team = C.config(crew, C.arcs(crew).find((a) => a.id === "otto").next, "arc").field.find((d) => d.team === "you").id;
console.log(JSON.stringify({ early, n1, n2, won: out1.passed, lines: out1.lines.length, before, after, team, arcs: Object.keys(D.ARCS).length, missions: Object.values(D.ARCS).reduce((a, x) => a + x.missions.length, 0) }));""")
    assert r["early"] == [] and r["n1"] == "a-nia-1" and r["n2"] == "a-nia-2" and r["won"] and r["lines"] >= 1
    assert r["before"] is False and r["after"] is True and r["team"] == "otto"
    assert r["arcs"] >= 10 and r["missions"] >= 15


def test_a_choice_changes_the_mission_that_follows_and_rewards_pay_once():
    r = js("""
const s = C.fresh(); s.story.chapter = 3; s.story.done["a-nia-1"] = true;
const m2 = C.mission("a-nia-2"); const plain = C.resolve(s, m2).mode;
C.choose(s, "a-nia-2", 0); const heist = C.resolve(s, m2), cfg = C.config(s, m2, "arc");
const t = C.fresh(); t.story.chapter = 3; C.choose(t, "a-nia-2", 1); const auction = C.config(t, m2, "arc");
const lines = (x) => C.lines(x, m2.intro).map((l) => l.who);
// the last Nia mission pays an engine level and loyalty, once
const u = C.fresh(); u.story.chapter = 3; u.story.done["a-nia-1"] = u.story.done["a-nia-2"] = true; u.crew.members.nia.loyalty = 3; const eng0 = u.garage.owned.pacer.upgrades.engine, loy0 = u.crew.members.nia.loyalty;
const m3 = C.mission("a-nia-3"); play(u, m3); const eng1 = u.garage.owned.pacer.upgrades.engine; play(u, m3); const eng2 = u.garage.owned.pacer.upgrades.engine;
console.log(JSON.stringify({ plain, heist: [heist.mode, heist.title, heist.goal.type], cfg: [cfg.mode, cfg.field.length], auction: [auction.mode, auction.field.map((d) => d.id)],
  who: [lines(s), lines(t)], eng: [eng0, eng1, eng2], loy: u.crew.members.nia.loyalty - loy0, flag: u.story.flags.nia_engine }));""")
    assert r["plain"] == "circuit" and r["heist"] == ["delivery", "Midnight at the Repo Yard", "delivery"] and r["cfg"] == ["delivery", 0]
    assert r["auction"][0] == "circuit" and "rook" in r["auction"][1]
    assert "harlan" not in r["who"][0] and "harlan" in r["who"][1]
    assert r["eng"] == [0, 1, 1] and r["loy"] >= 3 and r["flag"] is True


def test_turning_points_cost_real_things():
    r = js("""
const poor = C.fresh(); poor.money = 1000; const cant = C.choose(poor, "a-benny-2", 0);
const rich = C.fresh(); rich.money = 5000; const inf0 = C.influence(rich, "oldtown"); const can = C.choose(rich, "a-benny-2", 0);
const sora = C.fresh(); C.choose(sora, "a-sora-2", 0);
const sign = C.fresh(); const m0 = sign.money, nia0 = sign.crew.members.nia.loyalty; const sg = C.choose(sign, "a-harlan-1", 0);
console.log(JSON.stringify({ cant: [cant.ok, cant.error, poor.money, poor.story.choices["a-benny-2"] === undefined, !poor.story.flags.benny_saved],
  can: [can.ok, rich.money, C.influence(rich, "oldtown") - inf0, rich.story.flags.benny_saved, !!can.consequence], summit: [C.carAvailable(sora, "summit").ok, C.carAvailable(C.fresh(), "summit").ok],
  sign: [sign.money - m0, sign.crew.members.nia.loyalty - nia0, sg.consequence.includes("Nia")] }));""")
    assert r["cant"][0] is False and "₭2,500" in r["cant"][1] and r["cant"][2] == 1000 and r["cant"][3] and r["cant"][4]   # nothing changed
    assert r["can"] == [True, 2500, 10, True, True]
    assert r["summit"] == [True, False]
    assert r["sign"][0] == 10000 and r["sign"][1] == -3 and r["sign"][2]


def test_harlan_reaches_into_the_finale_and_the_ending():
    r = js("""
const fin = C.mission("c5-finale"), ids = (s) => C.config(s, fin, "story").field.map((d) => d.id + ":" + d.personality);
const refused = C.fresh(); refused.story.flags.harlan_refused = true;
const exposed = C.fresh(); Object.assign(exposed.story.flags, { harlan_refused: true, harlan_exposed: true });
const signedDex = C.fresh(); signedDex.story.flags.dex_signed = true;
const q = C.mission("c5-qualifier"), under = C.fresh(); under.story.flags.route_underground = true;
const end = (flags, fn) => { const s = C.fresh(); Object.assign(s.story.flags, flags); if (fn) fn(s); return C.endingFor(s); };
const allyOf = (s, id) => { s.rivals[id] = { wins: 4, losses: 0, races: 4, respect: 8, passedThem: 0, passedYou: 0, contacts: 0, youHit: 0, theyHit: 0, close: 0, streak: 1, last: "win" }; };
console.log(JSON.stringify({ refused: ids(refused), exposed: ids(exposed), dex: ids(signedDex).find((x) => x.startsWith("dex")),
  qual: [C.resolve(under, q).track, C.resolve(under, q).field.includes("rook"), C.resolve(C.fresh(), q).track],
  endings: { signed: end({ harlan_signed: true }), people: end({ harlan_refused: true, route_underground: true, mara_home: true, benny_saved: true }),
    legend: end({ harlan_exposed: true }, (s) => { allyOf(s, "dex"); allyOf(s, "mara"); s.crew.members.nia.loyalty = 9; }), plain: end({}) } }));""")
    assert any(x.startswith("rook:aggressive") for x in r["refused"]) and not any(x.startswith("rook") for x in r["exposed"])
    assert r["dex"] == "dex:aggressive"
    assert r["qual"] == ["harbour", True, "oldtown"]
    assert r["endings"] == {"signed": "corporate", "people": "people", "legend": "legend", "plain": "champion"}


def test_every_conditional_line_can_be_reached_and_every_speaker_has_a_face():
    r = js("""
const all = [...D.CHAPTERS.flatMap((c) => c.missions), ...Object.values(D.ARCS).flatMap((a) => a.missions)];
const settable = new Set(["crew_otto", "crew_pip"]);
for (const m of all) { for (const o of (m.choice ? m.choice.options : [])) for (const f of Object.keys(o.flags || {})) settable.add(f); for (const f of Object.keys((m.rewards || {}).flags || {})) settable.add(f); }
for (const g of Object.keys(D.GRUDGE)) { settable.add(`grudge_${g}_won`); settable.add(`grudge_${g}_lost`); }
const lines = all.flatMap((m) => [...(m.intro || []), ...(m.win || []), ...(m.lose || []), ...(m.choice ? m.choice.options.flatMap((o) => o.lines || []) : [])]);
const bad = lines.filter((l) => l[2] && !settable.has(l[2].replace("!", ""))).map((l) => l[2]);
const faceless = [...new Set(lines.map((l) => l[0]))].filter((w) => !(D.CAST[w] && D.CAST[w].face));
const turns = D.TURNING_POINTS.filter(([f]) => !settable.has(f)).map(([f]) => f);
const unused = [...settable].filter((f) => !lines.some((l) => l[2] && l[2].replace("!", "") === f) && !D.TURNING_POINTS.some(([t]) => t === f) && !["sponsor_halden", "sponsor_bluewater", "otto_last", "pip_back", "lio_clear", "priya_corvo"].includes(f));
console.log(JSON.stringify({ bad, faceless, turns, consequences: all.flatMap((m) => m.arc || !m.choice ? [] : []).length, unused }));""")
    assert r["bad"] == [] and r["faceless"] == [] and r["turns"] == []
