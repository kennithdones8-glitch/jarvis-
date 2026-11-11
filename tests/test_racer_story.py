"""Kerbside Grand Prix story systems (racer-career.js, racer-data.js): rivals remember what happened on track and
say so, their stage (feud, rival, respect, ally) changes how they race you, the crew joins through missions and
choices and its perks pay out, the new choices have consequences, and the ending follows what you did."""

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
           "const sum = (o) => ({ mode: 'circuit', track: 'kerbside', laps: 3, place: 1, of: 2, finished: true, eliminated: false, total: 70, best: 22, lapTimes: [24, 23, 22], drift: 0, contacts: 0,"
           " order: ['YOU', 'dex'], beat: ['dex'], rivals: { dex: { passedThem: 0, passedYou: 0, contacts: 0, youHit: 0, theyHit: 0, gap: 3, close: false } }, ...o });\n"
           "let n = 0; const race = (s, o, kind = 'side') => C.applyResult(s, { kind, event: { id: 'e', title: 'T', tier: 2, goal: { type: 'place', max: 1 } }, raceId: 'r' + (++n) }, sum(o));\n")
    out = subprocess.run([NODE, "-e", pre + code], capture_output=True, text=True, timeout=120, check=True)
    return json.loads(out.stdout)


def test_rivals_remember_the_race_and_say_what_happened():
    r = js("""
const s = C.fresh();
const dirty = race(s, { rivals: { dex: { passedThem: 1, passedYou: 0, contacts: 3, youHit: 3, theyHit: 0, gap: 2, close: false } } });
const close = race(s, { beat: [], order: ['dex', 'YOU'], place: 2, rivals: { dex: { passedThem: 2, passedYou: 3, contacts: 0, youHit: 0, theyHit: 0, gap: -0.04, close: true } } });
const many = race(s, { rivals: { dex: { passedThem: 4, passedYou: 1, contacts: 0, youHit: 0, theyHit: 0, gap: 5, close: false } } });
console.log(JSON.stringify({ mem: s.rivals.dex, dirty: dirty.reactions.find((x) => x.kind === "dirty"), grudge: dirty.reactions[0], close: close.reactions[0], many: many.reactions[0] }));""")
    m = r["mem"]
    assert (m["races"], m["wins"], m["losses"], m["passedThem"], m["passedYou"], m["youHit"], m["close"]) == (3, 2, 1, 7, 4, 3, 1)
    assert r["dirty"]["kind"] == "dirty" and "3 times" in r["dirty"]["text"]          # quotes the real count
    assert r["grudge"]["kind"] == "grudge" and "3 times we've traded paint, and 3 of them were you" in r["grudge"]["text"]   # and calls you out
    assert r["close"]["kind"] == "closeLoss" and r["many"]["kind"] == "passedMany" and "4 times" in r["many"]["text"]


def test_respect_moves_the_stage_and_the_stage_changes_the_driving():
    r = js("""
const s = C.fresh(), ev = C.mission("c3-league");
const field0 = C.config(s, ev, "story").field.find((d) => d.id === "dex").personality;
for (let i = 0; i < 3; i++) race(s, { rivals: { dex: { passedThem: 0, passedYou: 0, contacts: 2, youHit: 2, theyHit: 0, gap: 1, close: false } } });
const feud = [C.rivalStage(s, "dex"), C.config(s, ev, "story").field.find((d) => d.id === "dex").personality];
const t = C.fresh(); const notes = [];
for (let i = 0; i < 6; i++) notes.push(...race(t, { rivals: { dex: { passedThem: 1, passedYou: 0, contacts: 0, youHit: 0, theyHit: 0, gap: 0.2, close: true } } }).notes);
const ally = [C.rivalStage(t, "dex"), C.config(t, ev, "story").field.find((d) => d.id === "dex").personality, C.config(t, C.mission("c5-dex"), "story").field[0].personality];
console.log(JSON.stringify({ field0, feud, ally, notes, ach: Object.keys(t.achievements) }));""")
    assert r["field0"] == "aggressive"                                    # Dex's own personality to begin with
    assert r["feud"] == ["feud", "aggressive"]
    assert r["ally"][0] == "ally" and r["ally"][1] == "ally" and r["ally"][2] == "aggressive"   # an ally gives you room, but not in a 1-on-1
    assert any("ally now" in n for n in r["notes"]) and "first_ally" in r["ach"]


def test_the_crew_joins_and_their_perks_pay():
    r = js("""
const base = C.fresh(), b = race(base, {});
const s = C.fresh(); C.hire(s, "otto"); C.hire(s, "priya"); C.hire(s, "lio");
const p = race(s, {});
s.rep = 25; const lioSees = C.sideEvents(s).find((e) => e.id === "s-harb-tt"); s.districts.push("harbour");
const scout = C.sideEvents(s).find((e) => e.id === "s-harb-tt").open, noScout = (() => { const x = C.fresh(); x.rep = 25; x.districts.push("harbour"); return C.sideEvents(x).find((e) => e.id === "s-harb-tt").open; })();
const m = C.fresh(); m.districts.push("harbour"); m.rep = 40;
const ev = C.sideEvents(m).find((e) => e.id === "s-crew-lio");
const rec = C.applyResult(m, { kind: "side", event: ev, raceId: "lio1" }, sum({ mode: "timetrial", place: 1, of: 1, total: 28, order: ["YOU"], beat: [], rivals: {} }));
console.log(JSON.stringify({ xp: [b.xp, p.xp], money: [b.money, p.money], scout, noScout, nia: base.crew.members.nia.hired, rec: rec.unlocked, lio: C.hired(m, "lio"), gone: C.sideEvents(m).some((e) => e.id === "s-crew-lio") }));""")
    assert r["nia"] is True and r["xp"][1] > r["xp"][0] and r["money"][1] > r["money"][0]   # Otto: +10% XP, Priya: +10% prizes
    assert r["scout"] is True and r["noScout"] is False                                      # Lio finds events before you could
    assert {"type": "crew", "id": "lio", "name": "Lio Marchetti"} in r["rec"] and r["lio"] and r["gone"] is False


def test_the_new_choices_have_consequences():
    r = js("""
const a = C.fresh(), m0 = a.money; C.hire(a, "lio"); const take = C.choose(a, "c3-bet", 0);
const b = C.fresh(); C.hire(b, "lio"); C.choose(b, "c3-bet", 1);
const und = C.fresh(); C.choose(und, "c4-invitational", 1);
const friend = C.fresh(); friend.rivals.dex = { ...C.fresh().rivals, wins: 3, losses: 0, respect: 2 }; const join = C.choose(friend, "c5-dex", 0);
const foe = C.fresh(); C.choose(foe, "c1-callout", 1); foe.rivals.dex.respect = -4; const refuse = C.choose(foe, "c5-dex", 0);
console.log(JSON.stringify({ took: a.money - m0, kept: b.money - C.fresh().money, loyA: [a.crew.members.nia.loyalty, a.crew.members.lio.loyalty], loyB: [b.crew.members.nia.loyalty, b.crew.members.lio.loyalty],
  bennyA: a.rivals.benny.respect, bennyB: b.rivals.benny.respect, route: und.story.flags, joined: C.hired(friend, "dex"), refused: [refuse.refused, C.hired(foe, "dex"), refuse.lines[0].text] }));""")
    assert r["took"] == 1500 and r["kept"] == 500
    assert r["loyA"] == [5, 4] and r["loyB"] == [7, 6] and r["bennyA"] == -1 and r["bennyB"] == 3
    assert r["route"] == {"route_underground": True}
    assert r["joined"] is True and r["refused"][0] is True and r["refused"][1] is False and "rather walk" in r["refused"][2]


def test_the_ending_follows_what_you_did():
    r = js("""
const make = (fn) => { const s = C.fresh(); fn(s); return C.endingFor(s); };
const allyOf = (s, id) => { s.rivals[id] = { ...(s.rivals[id] || {}), wins: 4, losses: 0, races: 4, respect: 8, passedThem: 0, passedYou: 0, contacts: 0, youHit: 0, theyHit: 0, close: 0, streak: 1, last: "win" }; };
const feudOf = (s, id) => { s.rivals[id] = { wins: 0, losses: 3, races: 3, respect: -5, passedThem: 0, passedYou: 0, contacts: 0, youHit: 0, theyHit: 0, close: 0, streak: -1, last: "loss" }; };
console.log(JSON.stringify({
  legend: make((s) => { allyOf(s, "dex"); allyOf(s, "mara"); s.champWins.cup = 1; s.crew.members.nia.loyalty = 9; }),
  people: make((s) => { s.story.flags.route_underground = true; s.story.flags.benny_kind = true; }),
  corporate: make((s) => { s.story.flags.route_league = true; C.hire(s, "priya"); }),
  lone: make((s) => { feudOf(s, "dex"); feudOf(s, "sora"); }),
  champion: make(() => {}) }));""")
    assert r == {"legend": "legend", "people": "people", "corporate": "corporate", "lone": "lone", "champion": "champion"}


@pytest.mark.parametrize("pick", [0, 1])
def test_every_choice_keeps_the_story_coherent(pick):
    # lines are filtered by flags: whatever you choose, no line contradicts a choice you made
    r = js(f"""
const s = C.fresh(), bad = [];
for (const ch of D.CHAPTERS) for (const m of ch.missions) if (m.choice) C.choose(s, m.id, {pick} % m.choice.options.length);
const f = s.story.flags;
for (const ch of D.CHAPTERS) for (const m of ch.missions) for (const list of [m.intro, m.win, m.lose]) for (const line of (list || [])) {{
  const cond = line[2]; if (!cond) continue; const shown = C.lines(s, [line]).length === 1, want = cond[0] === "!" ? !f[cond.slice(1)] : !!f[cond];
  if (shown !== want) bad.push(m.id + ":" + cond);
}}
console.log(JSON.stringify({{ bad, flags: Object.keys(f) }}));""")
    assert r["bad"] == [] and len(r["flags"]) >= 5
