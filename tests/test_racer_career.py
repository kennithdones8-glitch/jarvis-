"""Kerbside Grand Prix career and saves (static/racer-career.js): the v3 save validates and repairs, Quick Race records
(v2) migrate without loss, a damaged save falls back to its backup and is kept rather than erased, export/import
round-trips and detects tampering, rewards are paid once per race, the economy charges and caps correctly, upgrades
change the car's physics, story choices have consequences, chapters unlock districts, championships score points,
events are discovered by reputation, and the whole campaign can be finished in simulation."""

import json
import shutil
import subprocess

import pytest

from jarvis.server.app import STATIC

NODE = shutil.which("node")


def js(code: str, timeout=240):
    if not NODE:
        pytest.skip("node not installed")
    pre = (f"const R = require({json.dumps(str(STATIC / 'racer.js'))}), C = require({json.dumps(str(STATIC / 'racer-career.js'))}),"
           f" D = require({json.dumps(str(STATIC / 'racer-data.js'))});\n"
           "const mem = () => { const m = {}; return { m, getItem: (k) => (k in m ? m[k] : null), setItem: (k, v) => { m[k] = String(v); }, removeItem: (k) => { delete m[k]; } }; };\n"
           "const summary = (o) => ({ mode: 'circuit', track: 'kerbside', laps: 3, place: 1, of: 4, finished: true, eliminated: false, total: 70, best: 22, lapTimes: [24, 23, 22], drift: 0, contacts: 0, order: ['YOU', 'dex', 'pip', 'otto'], beat: ['dex', 'pip', 'otto'], tod: 'day', weather: 'dry', ...o });\n")
    out = subprocess.run([NODE, "-e", pre + code], capture_output=True, text=True, timeout=timeout, check=True)
    return json.loads(out.stdout)


def test_a_damaged_save_is_repaired_field_by_field_and_reported():
    r = js("""
const bad = { ...C.fresh(), money: "lots", xp: -50, profile: { name: "", number: 400 }, garage: { current: "nope", owned: { pacer: { paint: "red", upgrades: { engine: 9 } }, fake: {} } },
  story: { chapter: 99, done: { "c1-shakedown": true, x: "yes" } }, settings: { quality: "ultra", volume: 3 } };
const { save, problems } = C.validate(bad);
console.log(JSON.stringify({ save, problems }));""")
    s = r["save"]
    assert s["money"] == 1500 and s["xp"] == 0 and "money" in r["problems"]
    assert s["profile"] == {"name": "Rookie", "number": 99}
    assert s["garage"]["current"] == "pacer" and list(s["garage"]["owned"]) == ["pacer"]
    assert s["garage"]["owned"]["pacer"]["paint"].startswith("#") and s["garage"]["owned"]["pacer"]["upgrades"]["engine"] == 3
    assert s["story"]["chapter"] == 6 and s["story"]["done"] == {"c1-shakedown": True}
    assert s["settings"]["quality"] == "auto" and s["settings"]["volume"] == 1


def test_quick_race_records_migrate_into_the_new_career():
    r = js("""
const st = mem();
const v2 = { track: "harbour", level: "hard", ghostOn: false, best: { "kerbside:medium": 22.5, "kerbside:hard": 21.9, "ridge:easy": 30 },
  race: { "kerbside:hard": 70.1 }, wins: 4, ghosts: { kerbside: { time: 21.9, pts: [1, 2, 0.5, 3, 4, 0.6] } } };
st.setItem(C.LEGACY, JSON.stringify(v2));
const r = C.load(st);
console.log(JSON.stringify({ migrated: r.migrated, notes: r.notes, best: r.save.best, bestRace: r.save.bestRace, wins: r.save.stats.wins, ghost: r.save.ghosts.kerbside, quick: r.save.quick, ghostOn: r.save.settings.ghost, legacyKept: st.getItem(C.LEGACY) !== null }));""")
    assert r["migrated"] and r["notes"]
    assert r["best"] == {"kerbside": 21.9, "ridge": 30} and r["bestRace"] == {"kerbside:circuit": 70.1}
    assert r["wins"] == 4 and r["ghost"]["time"] == 21.9 and r["quick"] == {"track": "harbour", "level": "hard"} and r["ghostOn"] is False
    assert r["legacyKept"]                     # the old records are never deleted


def test_an_unreadable_save_falls_back_to_the_backup_and_is_kept():
    r = js("""
const st = mem(), s = C.fresh(); s.money = 4242;
C.persist(st, s); s.money = 5000; C.persist(st, s);      // backup now holds 4242, main 5000
st.setItem(C.KEY, "{not json");
const a = C.load(st);
st.setItem(C.BAK, "also broken");
const b = C.load(st);
console.log(JSON.stringify({ a: a.save.money, aNotes: a.notes, kept: st.getItem(C.CORRUPT), b: b.save.money, bNotes: b.notes, bFresh: !!b.fresh }));""")
    assert r["a"] == 4242 and any("backup" in n for n in r["aNotes"])
    assert r["kept"] == "{not json"            # the damaged copy is kept, not erased
    assert r["b"] == 1500 and r["bFresh"] and any("kept as a copy" in n for n in r["bNotes"])


def test_export_import_round_trips_and_refuses_tampering():
    r = js("""
const s = C.fresh(); s.money = 9876; s.profile.name = "Kit"; s.story.done["c1-shakedown"] = true;
const txt = C.exportSave(s), back = C.importSave(txt);
const o = JSON.parse(txt); o.data = o.data.replace("9876", "99999");
console.log(JSON.stringify({ ok: back.ok, money: back.save.money, name: back.save.profile.name, done: back.save.story.done,
  tampered: C.importSave(JSON.stringify(o)), junk: C.importSave("hello"), v2: C.importSave(JSON.stringify({ best: { "ridge:medium": 25 }, wins: 2 })).save.best }));""")
    assert r["ok"] and r["money"] == 9876 and r["name"] == "Kit" and r["done"] == {"c1-shakedown": True}
    assert not r["tampered"]["ok"] and "checksum" in r["tampered"]["error"]
    assert not r["junk"]["ok"] and r["v2"] == {"ridge": 25}


def test_saves_write_a_backup_first_and_survive_a_full_disk():
    r = js("""
const st = mem(), s = C.fresh(); C.persist(st, s); s.money = 2000; const ok = C.persist(st, s);
const full = mem(); let n = 0; const real = full.setItem;
full.setItem = (k, v) => { if (k === C.KEY && v.length > 3000) throw new Error("QuotaExceededError"); real(k, v); };
const big = C.fresh(); big.ghosts = { kerbside: { time: 20, pts: Array(3000).fill(1) } };
const r2 = C.persist(full, big);
console.log(JSON.stringify({ ok, bakMoney: JSON.parse(st.getItem(C.BAK)).money, mainMoney: JSON.parse(st.getItem(C.KEY)).money, r2, ghostsLeft: Object.keys(big.ghosts) }));""")
    assert r["ok"]["ok"] and r["bakMoney"] == 1500 and r["mainMoney"] == 2000
    assert r["r2"] == {"ok": True, "trimmed": True} and r["ghostsLeft"] == []


def test_a_race_pays_once_however_often_its_result_arrives():
    r = js("""
const s = C.fresh(), ev = { id: "x", title: "Test", tier: 2, goal: { type: "place", max: 3 } };
const a = C.applyResult(s, { kind: "side", event: ev, raceId: "r1" }, summary({}));
const m1 = s.money;
const b = C.applyResult(s, { kind: "side", event: ev, raceId: "r1" }, summary({}));
console.log(JSON.stringify({ paid: a.money, again: b, m1, m2: s.money, races: s.stats.races, wins: s.stats.wins, ach: a.achievements }));""")
    assert r["paid"] > 0 and r["again"] == {"already": True} and r["m1"] == r["m2"]
    assert r["races"] == 1 and r["wins"] == 1 and "first_win" in r["ach"] and "clean_win" in r["ach"]


def test_the_economy_charges_and_caps_correctly():
    r = js("""
const s = C.fresh();
const locked = C.buyCar(s, "kestrel");
s.garage.unlocked.push("kestrel");
const poor = C.buyCar(s, "kestrel");
s.money = 7000; const ok = C.buyCar(s, "kestrel"); const left = s.money;
const costs = [0, 1, 2].map((lv) => C.upgradeCost("kestrel", "engine", lv)); s.money = 1e6;
const ups = [0, 1, 2, 3].map(() => C.buyUpgrade(s, "kestrel", "engine").ok);
const deco = [C.setLook(s, "kestrel", "decal", "flame").cost, C.setLook(s, "kestrel", "decal", "none").cost, C.setLook(s, "kestrel", "decal", "flame").cost];
const notForSale = C.buyCar(s, "countess");
console.log(JSON.stringify({ locked, poor, ok: ok.ok, ach: ok.achievements, left, costs, ups, deco, notForSale, paintFree: C.setLook(s, "kestrel", "paint", "#123456").cost, badNumber: C.setLook(s, "kestrel", "number", 120).ok }));""")
    assert not r["locked"]["ok"] and "Not unlocked" in r["locked"]["error"]
    assert not r["poor"]["ok"] and "more" in r["poor"]["error"]
    assert r["ok"] and r["ach"] == ["new_car"] and r["left"] == 7000 - 6800
    assert r["costs"] == [650, 1450, 2760]                  # base cost × class B multiplier (1.45), rounded to 10
    assert r["ups"] == [True, True, True, False]            # three levels, then capped
    assert r["deco"][0] > 0 and r["deco"][1] == 0 and r["deco"][2] == 0   # a look is bought once per car
    assert not r["notForSale"]["ok"] and r["paintFree"] == 0 and r["badNumber"] is False


def test_upgrades_really_change_the_car():
    r = js("""
const st = C.carState("pacer"), base = C.carStats("pacer", st);
st.upgrades = { engine: 3, tires: 3, brakes: 3, suspension: 3, nitro: 3 };
const up = C.carStats("pacer", st), spon = C.carStats("pacer", st, "bluewater");
const lap = (spec) => { const r = R.newRace({ track: "ridge", mode: "timetrial", laps: 2, player: { spec } }); let t = 0; while (!r.cars[0].done && t < 200) { R.step(r, 1 / 120, null); t += 1 / 120; } return r.cars[0].finish; };
console.log(JSON.stringify({ base, up, spon, slow: lap(base), fast: lap(up) }));""")
    b, u = r["base"], r["up"]
    assert u["acc"] == pytest.approx(b["acc"] * 1.12) and u["grip"] == pytest.approx(b["grip"] * 1.24)
    assert u["brake"] == pytest.approx(b["brake"] * 1.27) and u["steer"] == pytest.approx(b["steer"] * 1.12)
    assert u["nitro"]["fill"] == pytest.approx(b["nitro"]["fill"] * 1.36) and r["spon"]["nitro"]["fill"] > u["nitro"]["fill"]
    assert r["fast"] < r["slow"] * 0.95                     # a fully built car is clearly quicker round the ridge


def test_story_choices_have_consequences():
    r = js("""
const s = C.fresh(), m = C.mission("c1-callout"), fin = C.mission("c5-finale"), elim = C.mission("c2-elim");
const before = C.config(s, m, "story").field.find((d) => d.id === "dex").skill;
const lines0 = C.lines(s, elim.intro).map((l) => l.text);
C.choose(s, "c1-callout", 1);                                   // tell Dex to watch his mirrors
const after = C.config(s, m, "story").field.find((d) => d.id === "dex").skill;
const lines1 = C.lines(s, elim.intro).map((l) => l.text);
const again = C.choose(s, "c1-callout", 0);
const crew = C.fresh(); C.choose(crew, "c4-crew", 1);
const otto = C.fresh(); C.choose(otto, "c4-crew", 0);
const spon = C.fresh(); C.choose(spon, "c3-sponsor", 0);
console.log(JSON.stringify({ before, after, flags: s.story.flags, respect: s.rivals.dex, lines0, lines1, again,
  finale: C.config(crew, fin, "story").field.map((d) => d.id), tires: otto.garage.owned.pacer.upgrades.tires, sponsor: spon.sponsor,
  needs: C.needsChoice(C.fresh(), C.mission("c3-sponsor")), needsAfter: C.needsChoice(spon, C.mission("c3-sponsor")) }));""")
    assert r["after"] > r["before"] and r["flags"] == {"dex_feud": True} and r["respect"]["respect"] == -2
    assert not any("watch" in t.lower() or "miss me" in t for t in r["lines0"]) and any("miss me" in t for t in r["lines1"])
    assert not r["again"]["ok"]                                     # a choice is final
    assert "pip" in r["finale"] and "benny" not in r["finale"]      # Pip races the finale for you
    assert r["tires"] == 1 and r["sponsor"] == "halden"
    assert r["needs"] is True and r["needsAfter"] is False


def test_winning_missions_moves_the_story_and_unlocks_the_world():
    r = js("""
const s = C.fresh(), win = (id, o) => C.applyResult(s, { kind: "story", event: C.mission(id), raceId: id + Math.random() }, summary(o));
const a = win("c1-shakedown", { mode: "timetrial", place: 1, of: 1, total: 44, order: ["YOU"], beat: [] });
const lose = C.applyResult(s, { kind: "story", event: C.mission("c1-clubnight"), raceId: "l" }, summary({ place: 4, finished: true }));
const b = win("c1-clubnight", { place: 3 });
const locked = C.nextMission(s).id;
const c = win("c1-callout", { mode: "rival", place: 1, of: 2, order: ["YOU", "dex"], beat: ["dex"] });
console.log(JSON.stringify({ a: a.passed, lose: lose.passed, loseLines: lose.lines.length, b: b.passed, locked, chapter: s.story.chapter, newChapter: c.chapter,
  districts: s.districts, unlocked: c.unlocked, choice: !!c.choice, ach: c.achievements, next: C.nextMission(s).id, sides: C.sideEvents(s).map((e) => e.id + ":" + e.open) }));""")
    assert r["a"] and not r["lose"] and r["loseLines"] > 0 and r["b"]
    assert r["locked"] == "c1-callout" and r["chapter"] == 2 and r["newChapter"]["title"] == "Building a Reputation"
    assert r["districts"] == ["park", "harbour"] and {"type": "car", "id": "mistral", "name": "Mistral Hatch"} in r["unlocked"]
    assert r["choice"] and "beat_dex" in r["ach"] and r["next"] == "c2-sprint"
    assert "s-harb-tt:true" in r["sides"] and "s-harb-elim:false" in r["sides"]   # discovered by reputation


def test_championships_score_points_and_pay_the_winner():
    r = js("""
const s = C.fresh(); s.story.chapter = 3;
const start = C.startChamp(s, "cup"), locked = C.startChamp(C.fresh(), "cup");
const outs = [];
for (let i = 0; i < 4; i++) {
  const ev = C.champEvent(s);
  outs.push(C.applyResult(s, { kind: "champ", event: ev, raceId: "c" + i }, summary({ track: ev.track, order: ["YOU", "mara", "dex", "otto", "pip", "benny"], of: 6 })).champ);
}
console.log(JSON.stringify({ start, locked, outs, champ: s.champ, wins: s.champWins, ach: Object.keys(s.achievements) }));""")
    assert r["start"]["ok"] and not r["locked"]["ok"]
    assert r["outs"][0]["done"] is False and r["outs"][0]["table"][0] == {"id": "YOU", "name": "Rookie", "points": 10}
    last = r["outs"][3]
    assert last["done"] and last["place"] == 1 and last["prize"] > 0 and last["table"][0]["points"] == 40
    assert r["champ"] is None and r["wins"] == {"cup": 1} and "champion" in r["ach"]


@pytest.mark.parametrize("pick,level", [(0, "easy"), (1, "medium")])
def test_the_whole_campaign_can_be_finished(pick, level):
    # A simulated player (the AI driving your car; in drift events a corner-committing driver who lifts when the slide
    # gets too big, in the owned car that slides best) plays the story in order, takes choice `pick` everywhere,
    # grinds a classic side event (circuit, sprint, elimination, time trial or drift; it doesn't pit or deliver)
    # after a loss, and spends like a sensible player (it test-laps cars and only buys one at least 2% quicker than the one it
    # drives, or any quicker car once it has lost the same mission three times).
    r = js(f"""
const save = C.fresh(); save.settings.difficulty = {json.dumps(level)}; let n = 0; const tries = {{}};
const race = (kind, ev) => {{
  // like a player would: take the car that slides best to a drift event, then back to your main car
  const main = save.garage.current;
  if (ev.mode === "drift") save.garage.current = Object.keys(save.garage.owned).sort((a, b) => (D.CARS[b].slide || 0) - (D.CARS[a].slide || 0) || score(b) - score(a))[0];
  const cfg = C.config(save, ev, kind), r = R.newRace({{ ...cfg, seed: ++n }}); let t = 0;
  while (r.state !== "done" && t < 400) {{
    if (r.mode === "drift") {{ const a = R.aiInput(r, r.cars[0]); R.step(r, 1 / 120, {{ steer: Math.abs(a.steer) > 0.2 ? Math.sign(a.steer) : a.steer, thr: r.cars[0].slip < 160, brk: false, nitro: false }}); }}
    else R.step(r, 1 / 120, null);
    t += 1 / 120;
  }}
  const out = C.applyResult(save, {{ kind, event: ev, raceId: "r" + n }}, R.summary(r)); save.garage.current = main; return out;
}};
// like a player using the garage's test lap: a car's worth is how fast it actually laps (the AI driving it, stock)
const lapOf = {{}};
const score = (id) => lapOf[id] || (lapOf[id] = (() => {{ const r = R.newRace({{ track: "kerbside", mode: "circuit", laps: 1, seed: 1, field: [{{ id: "t", code: "T", name: "T", color: "#fff", spec: C.carStats(id, C.carState(id)), skill: 1 }}], playerSlot: 1 }});
  const me = r.cars[0]; me.out = true; me.x = r.trk.OX + 25; me.y = r.trk.OY + 25; let t = 0; while (!r.cars[1].done && t < 200) {{ R.step(r, 1 / 120, {{ steer: 0, thr: false, brk: false }}); t += 1 / 120; }}
  return 1000 / (r.cars[1].done ? r.cars[1].finish : 200); }})());
const spend = () => {{
  const buy = Object.entries(D.CARS).filter(([id, c]) => !save.garage.owned[id] && C.carAvailable(save, id).ok && c.price !== null && c.price <= save.money).sort((a, b) => score(b[0]) - score(a[0]))[0];
  if (buy && score(buy[0]) > score(save.garage.current) * (stuck >= 3 ? 1.0 : 1.02)) return C.buyCar(save, buy[0]).ok;
  return ["engine", "tires", "suspension", "brakes", "nitro"].some((p) => C.buyUpgrade(save, save.garage.current, p).ok);
}};
let blocked = null, stuck = 0;
while (!save.story.ended) {{
  const m = C.nextMission(save); if (!m) break;
  if ((tries[m.id] = (tries[m.id] || 0) + 1) > 15) {{ blocked = m.id; break; }}
  stuck = tries[m.id];
  if (C.needsChoice(save, m)) C.choose(save, m.id, {pick} % m.choice.options.length);
  const out = race("story", m);
  if (out.choice) C.choose(save, m.id, {pick} % out.choice.options.length);
  if (!out.passed) {{ const side = C.sideEvents(save).filter((e) => e.open && C.carAllowed(save, e).ok && ["circuit", "sprint", "elimination", "timetrial", "drift"].includes(e.mode)).sort((a, b) => b.tier - a.tier)[0]; if (side) race("side", {{ ...side, goal: side.goal || {{ type: "place", max: 3 }} }}); }}
  while (spend());
}}
console.log(JSON.stringify({{ ended: save.story.ended, blocked, races: n, done: Object.keys(save.story.done).length, owned: Object.keys(save.garage.owned), districts: save.districts, ach: save.achievements.story ? true : false }}));""", timeout=400)
    assert r["blocked"] is None and r["ended"], r
    assert r["done"] == sum(len(c) for c in [range(3), range(3), range(4), range(4), range(4)])   # all 18 missions
    assert "countess" in r["owned"] and sorted(r["districts"]) == ["harbour", "oldtown", "park", "ridge"] and r["ach"]
    assert r["races"] < 120                                          # finishing takes effort, not endless grinding


def test_the_camera_setting_is_validated():
    r = js("""
const ok = C.validate({ ...C.fresh(), settings: { camera: "classic" } }).save.settings.camera;
const bad = C.validate({ ...C.fresh(), settings: { camera: "drone" } }).save.settings.camera;
console.log(JSON.stringify({ ok, bad, fresh: C.fresh().settings.camera }));""")
    assert r == {"ok": "classic", "bad": "chase", "fresh": "chase"}


V3_FIXTURE = {   # a real v3 career as written before save v4 (abridged): it must upgrade without losing anything
    "version": 3, "created": 1, "saved": 2, "profile": {"name": "Kit", "number": 44}, "money": 5432, "xp": 2100, "rep": 140,
    "stats": {"races": 30, "wins": 12, "podiums": 20, "losses": 18, "dnfs": 1, "contacts": 40},
    "history": [{"at": 1, "kind": "story", "title": "Club Night", "track": "kerbside", "mode": "circuit", "place": 2, "of": 4}],
    "best": {"kerbside": 18.4}, "bestRace": {"kerbside:circuit": 60.2}, "medals": {"kerbside": "gold"},
    "ghosts": {"kerbside": {"time": 18.4, "pts": [1, 2, 0.5, 3, 4, 0.6]}},
    "garage": {"current": "kestrel", "owned": {"pacer": {"paint": "#d23c3c", "upgrades": {"engine": 2}}, "kestrel": {"paint": "#2f7de1", "number": 9, "decal": "flame",
               "upgrades": {"engine": 1, "tires": 3}, "bought": {"decal": ["none", "flame"]}}}, "unlocked": ["pacer", "mistral", "kestrel"]},
    "story": {"chapter": 3, "done": {"c1-shakedown": True, "c1-clubnight": True, "c1-callout": True}, "flags": {"dex_feud": True}, "choices": {"c1-callout": 1}, "ended": False},
    "rivals": {"dex": {"wins": 3, "losses": 2, "respect": -2}}, "achievements": {"first_win": 5}, "districts": ["park", "harbour", "oldtown"],
    "sponsor": "halden", "claimed": ["r1", "r2"], "champWins": {"cup": 1},
    "settings": {"quality": "medium", "camera": "classic", "difficulty": "hard"},
}


def test_a_v3_career_upgrades_to_v4_without_losing_anything():
    r = js(f"""
const st = mem(); st.setItem(C.KEY, JSON.stringify({json.dumps(V3_FIXTURE)}));
const a = C.load(st); C.persist(st, a.save); const b = C.load(st);
console.log(JSON.stringify({{ notes: a.notes, v: b.save.version, s: b.save, notes2: b.notes }}));""")
    s = r["s"]
    assert r["v"] == 4 and any("upgraded" in n for n in r["notes"]) and not r["notes2"]
    assert (s["profile"], s["money"], s["xp"], s["rep"]) == ({"name": "Kit", "number": 44}, 5432, 2100, 140)
    assert s["stats"]["wins"] == 12 and s["best"] == {"kerbside": 18.4} and s["medals"] == {"kerbside": "gold"} and s["ghosts"]["kerbside"]["time"] == 18.4
    k = s["garage"]["owned"]["kestrel"]
    assert s["garage"]["current"] == "kestrel" and k["decal"] == "flame" and k["upgrades"]["tires"] == 3 and k["tune"]["preset"] == "balanced"
    assert s["story"]["flags"] == {"dex_feud": True} and s["story"]["chapter"] == 3 and s["sponsor"] == "halden"
    assert s["rivals"]["dex"]["wins"] == 3 and s["rivals"]["dex"]["respect"] == -2 and s["rivals"]["dex"]["passedThem"] == 0
    assert s["claimed"] == ["r1", "r2"] and s["settings"]["camera"] == "classic" and s["settings"]["damage"] == "cosmetic"
    assert s["world"]["day"] == 1 and list(s["crew"]["members"]) == ["nia"] and s["records"]["pursuit"]["escapes"] == 0   # Nia was always your mechanic
