"use strict";
// Kerbside Grand Prix: career, progression and saves. Pure functions over a plain save object, so Node can test
// every rule: the save schema (v3) with validation, migration from the Quick Race records (v2), safe writes with a
// backup, export/import with a checksum, the economy (prizes, cars, upgrades, looks), the story engine (chapters,
// missions, choices and their consequences), side events and discovery, rival challenges, championships and
// achievements. Rewards are paid once per race id, so a double click or a reload can't pay twice.
(function (root) {
  const D = (typeof module !== "undefined" && module.exports) ? require("./racer-data.js") : root.KerbsideData;
  const VERSION = 4, KEY = "kerbside-save-v3", BAK = KEY + "-bak", CORRUPT = KEY + "-corrupt", LEGACY = "jarvis-racer-v2";
  const isObj = (v) => v !== null && typeof v === "object" && !Array.isArray(v);
  const num = (v, d, lo = -Infinity, hi = Infinity) => (typeof v === "number" && isFinite(v) ? Math.max(lo, Math.min(hi, v)) : d);
  const str = (v, d, max = 40) => (typeof v === "string" ? v.slice(0, max) : d);
  const bool = (v, d) => (typeof v === "boolean" ? v : d);
  const PARTS = Object.keys(D.UPGRADES);

  // ---------------------------------------------------------------- Save schema
  const LK = D.LOOK_KEYS;
  const FREE = Object.fromEntries(LK.map((k) => [k, Object.entries(D.LOOKS[k]).filter(([, o]) => !o.price).map(([v]) => v)]));
  function carState(id) {
    const c = { paint: D.LOOKS.paint[0], paint2: "#14100a", number: 7, upgrades: Object.fromEntries(PARTS.map((p) => [p, 0])),
      bought: Object.fromEntries(LK.map((k) => [k, FREE[k].slice()])), tune: { preset: "balanced", gearing: 0, aero: 0, diff: 0, tyre: "sport" }, dmg: 0 };
    for (const k of LK) c[k] = FREE[k][0];
    c.spoiler = id === "pacer" ? "none" : "low"; c.bought.spoiler = [...new Set([...c.bought.spoiler, "low"])];
    return c;
  }
  const RIVAL_KEYS = ["wins", "losses", "races", "close", "passedThem", "passedYou", "contacts", "youHit", "theyHit", "streak"];
  const freshRival = () => ({ ...Object.fromEntries(RIVAL_KEYS.map((k) => [k, 0])), respect: 0, last: null });
  function fresh(now = Date.now()) {
    return { version: VERSION, created: now, saved: now, profile: { name: "Rookie", number: 7 },
      money: 1500, xp: 0, rep: 0, stats: { races: 0, wins: 0, podiums: 0, losses: 0, dnfs: 0, contacts: 0 },
      history: [], best: {}, bestRace: {}, medals: {}, ghosts: {},
      garage: { current: "pacer", owned: { pacer: carState("pacer") }, unlocked: ["pacer"] },
      story: { chapter: 1, done: {}, flags: {}, choices: {}, ended: false },
      rivals: {}, achievements: {}, districts: ["park"], discovered: {}, sideDone: {}, champ: null, champWins: {},
      sponsor: null, claimed: [], interrupted: null, quick: { track: "kerbside", level: "medium" },
      crew: { members: { nia: { hired: true, loyalty: 6, level: 1, xp: 0, mission: true } } }, world: { day: 1, influence: {}, rumors: {}, news: [] },
      team: { name: "Okafor Motors", color: "#e9c44a", color2: "#14100a", rep: 0, points: 0, rivals: {}, season: 1, days: 0, titles: 0 },
      contracts: [], records: { drag: { best: 0, wins: 0 }, pursuit: { best: 0, escapes: 0, busts: 0, heat: 0, fines: 0 }, touge: { wins: 0 }, endurance: { wins: 0 }, tournament: { wins: 0 }, delivery: { done: 0 } },
      tourney: null, wager: null,
      ng: 0, endings: {},
      settings: { quality: "auto", camera: "chase", shake: true, sound: true, music: true, volume: 0.7, reducedMotion: null, ghost: true, difficulty: "medium", damage: "cosmetic" } };
  }
  // Validate anything loaded (from storage or an import). Unknown keys are dropped, bad values replaced by defaults,
  // and every replacement is reported, so a damaged save is repaired visibly instead of silently.
  function validate(raw) {
    const s = fresh(num(raw && raw.created, Date.now())), problems = [];
    if (!isObj(raw)) return { save: s, problems: ["not an object"] };
    const fix = (path, ok) => { if (!ok) problems.push(path); };
    fix("version", raw.version === VERSION || raw.version === 3);   // v3 upgrades to v4 here: new fields get defaults
    if (isObj(raw.profile)) { s.profile.name = str(raw.profile.name, s.profile.name, 18).trim() || "Rookie"; s.profile.number = num(raw.profile.number, 7, 1, 99) | 0; } else fix("profile", false);
    for (const k of ["money", "xp", "rep"]) { s[k] = Math.floor(num(raw[k], s[k], 0, 1e9)); fix(k, typeof raw[k] === "number"); }
    if (isObj(raw.stats)) for (const k of Object.keys(s.stats)) s.stats[k] = Math.floor(num(raw.stats[k], 0, 0, 1e7));
    if (Array.isArray(raw.history)) s.history = raw.history.filter(isObj).slice(-60);
    for (const k of ["best", "bestRace"]) if (isObj(raw[k])) for (const [kk, v] of Object.entries(raw[k])) if (typeof v === "number" && v > 0 && v < 3600) s[k][kk] = v;
    if (isObj(raw.medals)) for (const [kk, v] of Object.entries(raw.medals)) if (["gold", "silver", "bronze"].includes(v)) s.medals[kk] = v;
    if (isObj(raw.ghosts)) for (const [kk, g] of Object.entries(raw.ghosts)) if (isObj(g) && typeof g.time === "number" && Array.isArray(g.pts) && g.pts.length % 3 === 0 && g.pts.every((n) => typeof n === "number")) s.ghosts[kk] = { time: g.time, pts: g.pts };
    if (isObj(raw.garage)) {
      const owned = isObj(raw.garage.owned) ? raw.garage.owned : {};
      for (const [id, st] of Object.entries(owned)) {
        if (!D.CARS[id] || !isObj(st)) continue;
        const c = carState(id);
        c.paint = /^#[0-9a-f]{6}$/i.test(st.paint) ? st.paint : c.paint;
        c.paint2 = /^#[0-9a-f]{6}$/i.test(st.paint2 || "") ? st.paint2 : c.paint2;
        for (const k of LK) c[k] = D.LOOKS[k][st[k]] ? st[k] : c[k];
        c.number = num(st.number, 7, 1, 99) | 0;
        if (isObj(st.upgrades)) for (const p of PARTS) c.upgrades[p] = num(st.upgrades[p], 0, 0, 3) | 0;
        if (isObj(st.bought)) for (const k of Object.keys(c.bought)) if (Array.isArray(st.bought[k])) c.bought[k] = [...new Set([...c.bought[k], ...st.bought[k].filter((v) => D.LOOKS[k][v])])];
        if (isObj(st.tune)) {
          const T = st.tune; c.tune.preset = D.PRESETS && D.PRESETS[T.preset] ? T.preset : (T.preset === "custom" ? "custom" : "balanced");
          c.tune.gearing = num(T.gearing, 0, -1, 1); c.tune.aero = num(T.aero, 0, 0, 1); c.tune.diff = num(T.diff, 0, 0, 1);
          c.tune.tyre = D.TYRES && D.TYRES[T.tyre] ? T.tyre : "sport";
        }
        c.dmg = num(st.dmg, 0, 0, 1);
        s.garage.owned[id] = c;
      }
      if (!s.garage.owned.pacer) s.garage.owned.pacer = carState("pacer");
      if (Array.isArray(raw.garage.unlocked)) s.garage.unlocked = [...new Set(["pacer", ...raw.garage.unlocked.filter((id) => D.CARS[id])])];
      s.garage.current = s.garage.owned[raw.garage.current] ? raw.garage.current : "pacer";
    } else fix("garage", false);
    if (isObj(raw.story)) {
      s.story.chapter = num(raw.story.chapter, 1, 1, D.CHAPTERS.length + 1) | 0;
      for (const k of ["done", "flags"]) if (isObj(raw.story[k])) for (const [kk, v] of Object.entries(raw.story[k])) if (v === true) s.story[k][kk] = true;
      if (isObj(raw.story.choices)) for (const [kk, v] of Object.entries(raw.story.choices)) if (Number.isInteger(v)) s.story.choices[kk] = v;
      s.story.ended = bool(raw.story.ended, false);
    } else fix("story", false);
    if (isObj(raw.rivals)) for (const [id, r] of Object.entries(raw.rivals)) if (D.DRIVERS[id] && isObj(r)) {
      const o = freshRival(); for (const k of RIVAL_KEYS) o[k] = num(r[k], 0, k === "streak" ? -99 : 0, 1e6) | 0;
      o.respect = num(r.respect, 0, -10, 10) | 0; o.last = ["win", "loss"].includes(r.last) ? r.last : null; s.rivals[id] = o;
    }
    if (isObj(raw.crew) && isObj(raw.crew.members)) for (const [id, m] of Object.entries(raw.crew.members)) if (D.CREW && D.CREW[id] && isObj(m))
      s.crew.members[id] = { hired: bool(m.hired, false), loyalty: num(m.loyalty, 5, 0, 10) | 0, level: num(m.level, 1, 1, 5) | 0, xp: num(m.xp, 0, 0, 1e6) | 0, mission: bool(m.mission, false) };
    if (!s.crew.members.nia) s.crew.members.nia = { hired: true, loyalty: 6, level: 1, xp: 0, mission: true };   // older saves: Nia was always your mechanic
    if (isObj(raw.world)) {
      s.world.day = num(raw.world.day, 1, 1, 1e6) | 0;
      if (isObj(raw.world.influence)) for (const [d, v] of Object.entries(raw.world.influence)) if (D.DISTRICTS[d]) s.world.influence[d] = num(v, 0, 0, 100);
      if (isObj(raw.world.rumors)) for (const [k, v] of Object.entries(raw.world.rumors)) if (["heard", "done"].includes(v)) s.world.rumors[k] = v;
      if (Array.isArray(raw.world.news)) s.world.news = raw.world.news.filter((n) => isObj(n) && typeof n.text === "string").slice(-12).map((n) => ({ day: num(n.day, 1) | 0, text: n.text.slice(0, 160) }));
    }
    if (isObj(raw.team)) {
      s.team.name = str(raw.team.name, s.team.name, 24).trim() || "Okafor Motors";
      for (const k of ["color", "color2"]) if (/^#[0-9a-f]{6}$/i.test(raw.team[k] || "")) s.team[k] = raw.team[k];
      s.team.rep = num(raw.team.rep, 0, 0, 1e7) | 0; s.team.points = num(raw.team.points, 0, 0, 1e7) | 0;
      if (isObj(raw.team.rivals)) for (const k of Object.keys(D.CREWS)) if (typeof raw.team.rivals[k] === "number") s.team.rivals[k] = num(raw.team.rivals[k], 0, 0, 1e6) | 0;
      s.team.season = num(raw.team.season, 1, 1, 1e6) | 0; s.team.days = num(raw.team.days, 0, 0, 1e3) | 0;
      s.team.titles = num(raw.team.titles, 0, 0, 1e4) | 0;
    }
    if (Array.isArray(raw.contracts)) s.contracts = raw.contracts.filter((c) => isObj(c) && D.CONTRACTS && D.CONTRACTS[c.id]).slice(0, 3)
      .map((c) => ({ id: c.id, progress: num(c.progress, 0, 0, 1000) | 0, left: num(c.left, 0, 0, 1000) | 0 }));
    if (isObj(raw.records)) for (const [k, v] of Object.entries(s.records)) if (isObj(raw.records[k])) for (const kk of Object.keys(v)) v[kk] = num(raw.records[k][kk], 0, 0, 1e9);
    s.ng = num(raw.ng, 0, 0, 99) | 0;
    if (isObj(raw.endings)) for (const [k, v] of Object.entries(raw.endings)) if (typeof v === "number") s.endings[k] = v;
    if (isObj(raw.achievements)) for (const [id, t] of Object.entries(raw.achievements)) if (D.ACHIEVEMENTS[id] && typeof t === "number") s.achievements[id] = t;
    if (Array.isArray(raw.districts)) s.districts = [...new Set(["park", ...raw.districts.filter((d) => D.DISTRICTS[d])])];
    for (const k of ["discovered", "sideDone"]) if (isObj(raw[k])) for (const [kk, v] of Object.entries(raw[k])) if (typeof v === "number" || v === true) s[k][kk] = v;
    if (isObj(raw.champ) && D.CHAMPIONSHIPS.some((c) => c.id === raw.champ.id) && isObj(raw.champ.points)) {
      const def = D.CHAMPIONSHIPS.find((c) => c.id === raw.champ.id);
      s.champ = { id: raw.champ.id, round: num(raw.champ.round, 0, 0, def.rounds.length - 1) | 0, points: {}, results: Array.isArray(raw.champ.results) ? raw.champ.results.slice(0, 8) : [] };
      for (const [kk, v] of Object.entries(raw.champ.points)) if (typeof v === "number") s.champ.points[kk] = v;
    }
    if (isObj(raw.champWins)) for (const [kk, v] of Object.entries(raw.champWins)) if (typeof v === "number") s.champWins[kk] = v;
    s.sponsor = D.SPONSORS[raw.sponsor] ? raw.sponsor : null;
    if (Array.isArray(raw.claimed)) s.claimed = raw.claimed.filter((x) => typeof x === "string").slice(-200);
    if (isObj(raw.tourney) && D.TOURNAMENTS.some((t) => t.id === raw.tourney.id)) {
      const def = D.TOURNAMENTS.find((t) => t.id === raw.tourney.id);
      s.tourney = { id: def.id, stage: num(raw.tourney.stage, 0, 0, def.stages.length - 1) | 0 };
    }
    if (isObj(raw.wager)) s.wager = { amount: num(raw.wager.amount, 0, 0, 1e6) | 0, event: str(raw.wager.event, "", 40) };
    if (isObj(raw.interrupted)) s.interrupted = { title: str(raw.interrupted.title, "a race", 60), at: num(raw.interrupted.at, 0) };
    if (isObj(raw.quick)) { s.quick.track = str(raw.quick.track, "kerbside"); s.quick.level = ["easy", "medium", "hard"].includes(raw.quick.level) ? raw.quick.level : "medium"; }
    if (isObj(raw.settings)) {
      const st = raw.settings, S = s.settings;
      S.quality = ["auto", "low", "medium", "high"].includes(st.quality) ? st.quality : "auto";
      S.camera = st.camera === "classic" ? "classic" : "chase";
      for (const k of ["shake", "sound", "music", "ghost"]) S[k] = bool(st[k], S[k]);
      S.volume = num(st.volume, 0.7, 0, 1); S.reducedMotion = typeof st.reducedMotion === "boolean" ? st.reducedMotion : null;
      S.difficulty = ["easy", "medium", "hard"].includes(st.difficulty) ? st.difficulty : "medium";
      S.damage = st.damage === "persistent" ? "persistent" : "cosmetic";
    }
    return { save: s, problems };
  }
  // The Quick Race records (v2, key jarvis-racer-v2) become a v3 career: best laps, ghosts, wins and prefs carry over.
  function migrateV2(v2) {
    const s = fresh();
    if (!isObj(v2)) return s;
    if (isObj(v2.best)) for (const [k, v] of Object.entries(v2.best)) { if (typeof v !== "number") continue; const [trk] = k.split(":"); s.best[trk] = Math.min(s.best[trk] || Infinity, v); }
    if (isObj(v2.race)) for (const [k, v] of Object.entries(v2.race)) { if (typeof v !== "number") continue; const [trk] = k.split(":"); const kk = trk + ":circuit"; s.bestRace[kk] = Math.min(s.bestRace[kk] || Infinity, v); }
    if (isObj(v2.ghosts)) s.ghosts = v2.ghosts;
    s.stats.wins = num(v2.wins, 0, 0) | 0; s.stats.races = s.stats.wins;
    if (typeof v2.track === "string") s.quick.track = v2.track;
    if (["easy", "medium", "hard"].includes(v2.level)) s.quick.level = v2.level;
    if (typeof v2.ghostOn === "boolean") s.settings.ghost = v2.ghostOn;
    return validate(s).save;
  }

  // ---------------------------------------------------------------- Storage (a localStorage-like object)
  // load(): main → backup → legacy v2 → fresh. A save that can't be read is kept under a "-corrupt" key, never deleted.
  function load(storage) {
    const notes = [], read = (k) => { try { return storage.getItem(k); } catch { return null; } };
    const parse = (txt) => { try { return JSON.parse(txt); } catch { return undefined; } };
    const main = read(KEY), bak = read(BAK);
    for (const [txt, label] of [[main, "main"], [bak, "backup"]]) {
      if (txt == null) continue;
      const obj = parse(txt);
      if (obj !== undefined && isObj(obj) && (obj.version === VERSION || obj.version === 3)) {
        if (obj.version === 3 && label === "main") notes.push("Your career was upgraded to the new save format. Nothing was lost.");
        const { save, problems } = validate(obj);
        if (label === "backup") notes.push("Your save couldn't be read, so the backup copy was loaded.");
        if (problems.length) notes.push(`Repaired parts of your save: ${problems.slice(0, 4).join(", ")}.`);
        if (label === "backup" && main != null) { try { storage.setItem(CORRUPT, main); } catch { /* keep going */ } }
        if (save.interrupted) {
          notes.push(`Your last race (${save.interrupted.title}) was interrupted. No result was recorded${save.wager ? `, and your ₭${save.wager.amount.toLocaleString()} stake was forfeited` : "; nothing was lost"}.`);
          save.interrupted = null; save.wager = null;
        }
        return { save, notes };
      }
    }
    if (main != null || bak != null) {
      try { storage.setItem(CORRUPT, main != null ? main : bak); } catch { /* keep going */ }
      notes.push("Your save couldn't be read. It has been kept as a copy and a new career started.");
    }
    const legacy = read(LEGACY), v2 = legacy != null ? parse(legacy) : undefined;
    if (isObj(v2)) { notes.push("Your Quick Race best laps, ghosts and wins were carried into your new career."); return { save: migrateV2(v2), notes, migrated: true }; }
    return { save: fresh(), notes, fresh: true };
  }
  // persist(): copy the current save to the backup first, then write and read back. Ghosts are dropped (oldest
  // track first) only if the browser's storage is full, and the caller is told.
  function persist(storage, save) {
    save.saved = Date.now();
    let txt = JSON.stringify(save);
    try {
      const cur = storage.getItem(KEY);
      if (cur != null) storage.setItem(BAK, cur);
      try { storage.setItem(KEY, txt); }
      catch (e) {
        const g = Object.keys(save.ghosts);
        while (g.length) { delete save.ghosts[g.shift()]; txt = JSON.stringify(save); try { storage.setItem(KEY, txt); return { ok: true, trimmed: true }; } catch { /* keep trimming */ } }
        throw e;
      }
      return { ok: storage.getItem(KEY) === txt };
    } catch (e) { return { ok: false, error: String(e && e.message || e) }; }
  }
  function fnv(s) { let h = 0x811c9dc5; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193) >>> 0; } return h.toString(16).padStart(8, "0"); }
  function exportSave(save) { const data = JSON.stringify(save); return JSON.stringify({ format: "kerbside-save", version: VERSION, exported: new Date().toISOString(), checksum: fnv(data), data }); }
  function importSave(text) {
    let o; try { o = JSON.parse(String(text).trim()); } catch { return { ok: false, error: "That isn't a Kerbside save (not valid JSON)." }; }
    if (isObj(o) && o.format === "kerbside-save" && typeof o.data === "string") {
      if (fnv(o.data) !== o.checksum) return { ok: false, error: "The save has been changed or cut short (checksum mismatch)." };
      let d; try { d = JSON.parse(o.data); } catch { return { ok: false, error: "The save data is damaged." }; }
      const { save, problems } = validate(d); return { ok: true, save, problems };
    }
    if (isObj(o) && (isObj(o.best) || isObj(o.ghosts)) && !o.version) return { ok: true, save: migrateV2(o), problems: [], migrated: true };
    return { ok: false, error: "That isn't a Kerbside save." };
  }

  // ---------------------------------------------------------------- Cars and economy
  const level = (xp) => Math.min(50, Math.floor(Math.sqrt(xp / 120)) + 1);
  const xpFor = (lv) => (lv - 1) ** 2 * 120;
  // Everything that makes a car drive the way it does: base stats, traits, upgrades and the tune. The physics reads
  // acc, drag, grip, brake, steer, nitro, mass, turbo (power that builds with lag), aero (grip at speed), slide
  // (looser rear for drifting), tyre {dry, wet} and offroad.
  function carStats(id, st, sponsor) {
    const c = D.CARS[id] || D.CARS.pacer, u = (st && st.upgrades) || {}, L = (p) => u[p] | 0, T = (st && st.tune) || {};
    const nf = 1 + 0.12 * L("nitro") + (sponsor && D.SPONSORS[sponsor] && D.SPONSORS[sponsor].nitroFill || 0);
    const g = Math.max(-1, Math.min(1, T.gearing || 0)), aero = Math.min(1, (T.aero || 0) + 0.25 * L("aero")), ty = D.TYRES[T.tyre] || D.TYRES.sport;
    const wet = 1 + (c.wet || 0);
    return { acc: c.acc * (1 + 0.04 * L("engine")) * (1 + 0.02 * L("ecu")) * (1 + 0.015 * L("weight")) * (1 - 0.06 * g),
      drag: c.drag * (1 - 0.09 * g) * (1 + 0.04 * aero), grip: c.grip * (1 + 0.05 * L("tires") + 0.03 * L("suspension")),
      brake: c.brake * (1 + 0.09 * L("brakes")) * (1 + 0.03 * L("weight")), steer: c.steer * (1 + 0.04 * L("suspension")),
      nitro: { push: c.nitro.push * (1 + 0.06 * L("nitro")), burn: c.nitro.burn, fill: c.nitro.fill * nf, cap: c.nitro.cap },
      mass: (c.mass || 1) * (1 - 0.05 * L("weight")), turbo: (c.turbo || 0) + 0.05 * L("turbo"), aero, slide: Math.min(1, (c.slide || 0) + 0.8 * (T.diff || 0)),
      tyre: { dry: ty.dry, wet: ty.wet * wet }, offroad: c.offroad || 0 };
  }
  // 0..1 bars for the garage (fixed scales so cars compare honestly).
  function bars(spec) {
    const gr = spec.grip * ((spec.tyre && spec.tyre.dry) || 1) * (1 + 0.05 * (spec.aero || 0)) * (1 - 0.1 * (spec.slide || 0));
    const top = spec.acc * (1 + 0.6 * (spec.turbo || 0)) / spec.drag;
    return { acceleration: Math.max(0, Math.min(1, (spec.acc * (1 + 0.6 * (spec.turbo || 0)) - 360) / 220)), topSpeed: Math.max(0, Math.min(1, (top - 560) / 320)),
      grip: Math.max(0, Math.min(1, (gr - 5) / 4)), braking: Math.max(0, Math.min(1, (spec.brake - 800) / 420)), nitro: Math.max(0, Math.min(1, (spec.nitro.push * spec.nitro.fill * 50 - 800) / 800)) };
  }
  // Whether a car can be bought now, and if not, what it takes.
  function carAvailable(save, id) {
    const c = D.CARS[id];
    if (!c || c.police) return { ok: false, why: "Not available." };
    if (save.garage.owned[id]) return { ok: true, owned: true };
    if (c.price === null) return { ok: false, why: "Won in the story's final race." };
    if (save.garage.unlocked.includes(id)) return { ok: true };
    const U = c.unlock;
    if (!U) return { ok: false, why: "Unlocks as the story goes on." };
    if (U.chapter && (save.story.chapter >= U.chapter || save.story.ended)) return { ok: true };
    if (U.rep && save.rep >= U.rep) return { ok: true };
    if (U.ended && save.story.ended) return { ok: true };
    if (U.rival && (save.rivals[U.rival] || {}).wins >= U.wins) return { ok: true };
    return { ok: false, why: U.chapter ? `Opens in chapter ${U.chapter}.` : U.rep ? `Needs ${U.rep} reputation (you have ${save.rep}).` : U.ended ? "Opens after the story ends." :
      U.rival ? `Beat ${D.DRIVERS[U.rival].name} ${U.wins} times (${(save.rivals[U.rival] || {}).wins || 0} so far).` : "Locked." };
  }
  // Tuning is free: a preset, or custom sliders (gearing −1…1, aero 0…1, diff 0…1) and a tyre compound.
  function setTune(save, id, patch) {
    const st = save.garage.owned[id];
    if (!st) return { ok: false, error: "You don't own that car." };
    if (patch.preset && D.PRESETS[patch.preset]) { const P = D.PRESETS[patch.preset]; st.tune = { preset: patch.preset, gearing: P.gearing, aero: P.aero, diff: P.diff, tyre: P.tyre }; return { ok: true }; }
    const t = { ...st.tune, preset: "custom" };
    if ("gearing" in patch) t.gearing = Math.max(-1, Math.min(1, +patch.gearing || 0));
    if ("aero" in patch) t.aero = Math.max(0, Math.min(1, +patch.aero || 0));
    if ("diff" in patch) t.diff = Math.max(0, Math.min(1, +patch.diff || 0));
    if ("tyre" in patch && D.TYRES[patch.tyre]) t.tyre = patch.tyre;
    st.tune = t; return { ok: true };
  }
  const repairCost = (id, st) => round10((st.dmg || 0) * 900 * D.CLASS_COST[D.CARS[id].cls]);
  function repair(save, id) {
    const st = save.garage.owned[id]; if (!st || !st.dmg) return { ok: false, error: "Nothing to repair." };
    const cost = repairCost(id, st) * (save.crew && save.crew.members.nia && save.crew.members.nia.hired ? 0.7 : 1);
    if (save.money < cost) return { ok: false, error: `You need ${(cost - save.money).toLocaleString()} more.` };
    save.money -= Math.round(cost); st.dmg = 0; return { ok: true, cost: Math.round(cost) };
  }
  const round10 = (v) => Math.round(v / 10) * 10;
  const upgradeCost = (id, part, lv) => (lv >= 3 ? null : round10(D.UPGRADES[part].cost[lv] * D.CLASS_COST[(D.CARS[id] || D.CARS.pacer).cls]));
  function buyCar(save, id) {
    const c = D.CARS[id];
    if (!c) return { ok: false, error: "No such car." };
    if (save.garage.owned[id]) return { ok: false, error: "You already own it." };
    if (c.price === null) return { ok: false, error: "Not for sale." };
    const av = carAvailable(save, id);
    if (!av.ok) return { ok: false, error: av.why === "Unlocks as the story goes on." ? "Not unlocked yet: keep going in the story." : av.why };
    if (save.money < c.price) return { ok: false, error: `You need ${(c.price - save.money).toLocaleString()} more.` };
    save.money -= c.price; save.garage.owned[id] = carState(id); save.garage.current = id;
    return { ok: true, achievements: grant(save, "new_car") };
  }
  function buyUpgrade(save, id, part) {
    const st = save.garage.owned[id];
    if (!st || !D.UPGRADES[part]) return { ok: false, error: "Not available." };
    const lv = st.upgrades[part], cost = upgradeCost(id, part, lv);
    if (cost === null) return { ok: false, error: "Already at the top level." };
    if (save.money < cost) return { ok: false, error: `You need ${(cost - save.money).toLocaleString()} more.` };
    save.money -= cost; st.upgrades[part] = lv + 1;
    return { ok: true, level: lv + 1, achievements: lv + 1 === 3 ? grant(save, "maxed") : [] };
  }
  // Looks: paint and number are free; decals, wheels, body kits and spoilers are bought once per car.
  function setLook(save, id, key, value) {
    const st = save.garage.owned[id];
    if (!st) return { ok: false, error: "You don't own that car." };
    if (key === "paint") { if (!/^#[0-9a-f]{6}$/i.test(value)) return { ok: false, error: "Bad colour." }; st.paint = value; return { ok: true, cost: 0 }; }
    if (key === "paint2") { if (!/^#[0-9a-f]{6}$/i.test(value)) return { ok: false, error: "Bad colour." }; st.paint2 = value; return { ok: true, cost: 0 }; }
    if (key === "number") { const n = Math.round(Number(value)); if (!(n >= 1 && n <= 99)) return { ok: false, error: "Pick a number from 1 to 99." }; st.number = n; return { ok: true, cost: 0 }; }
    const opt = D.LOOKS[key] && D.LOOKS[key][value];
    if (!opt) return { ok: false, error: "Not available." };
    let cost = 0;
    if (!st.bought[key].includes(value)) {
      cost = round10(opt.price * D.CLASS_COST[D.CARS[id].cls]);
      if (save.money < cost) return { ok: false, error: `You need ${(cost - save.money).toLocaleString()} more.` };
      save.money -= cost; st.bought[key].push(value);
    }
    st[key] = value;
    return { ok: true, cost };
  }

  // ---------------------------------------------------------------- Events → race configs
  const BASE = [0, 600, 1000, 1600, 2400, 3500], PLACE = [1, 0.62, 0.42, 0.28, 0.18, 0.1];
  // A class-restricted event puts every AI driver in a car of that class (each driver always gets the same one).
  function classCar(id, cls) {
    const pool = Object.entries(D.CARS).filter(([, c]) => c.cls === cls && !c.police && c.price !== null).map(([k]) => k);
    let h = 0; for (const ch of id) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
    return pool[h % pool.length];
  }
  let NG = 0;   // New Game+ cycle of the save being raced: each one makes the field 1% quicker
  function driver(id, tier, over = {}, cls = null) {
    const d = D.DRIVERS[id], car = cls && D.CARS[d.car].cls !== cls ? classCar(id, cls) : d.car, lvl = Math.min(3, d.lvl);
    const st = { upgrades: Object.fromEntries(D.AI_PARTS.map((p) => [p, lvl])) };
    return { id, code: d.code, name: d.name, color: d.color, num: d.num, personality: d.personality, skill: Math.min(1.02 + 0.01 * NG, d.skill + (tier - 3) * 0.008 + 0.01 * NG),
      spec: carStats(car, st), shape: D.CARS[car].shape, look: { paint: d.color, decal: { aggressive: "flame", technical: "stripe", opportunistic: "bolt", defensive: "checker" }[d.personality] || "none", spoiler: "low", number: d.num }, ...over };
  }
  function playerRacer(save) {
    const id = save.garage.current, st = save.garage.owned[id];
    return { code: "YOU", name: save.profile.name, color: st.paint, num: st.number, spec: carStats(id, st, save.sponsor), shape: D.CARS[id].shape,
      look: lookOf(st), dmg: save.settings.damage === "persistent" ? st.dmg || 0 : 0 };
  }
  function lookOf(st) {
    const L = { paint: st.paint, paint2: st.paint2, number: st.number }; for (const k of LK) L[k] = st[k]; return L;
  }
  // Who races beside you in a team event: a crew member who drives (Dex, then Pip, then Otto), else Pip as a hired gun.
  function teammate(save) {
    const id = ["dex", "pip", "otto"].find((x) => hired(save, x)) || "pip";
    return { id, hired: hired(save, id) };
  }
  function fieldFor(save, ev) {
    const f = save.story.flags, cls = ev.cls || ev.aiCls || null;   // aiCls: Free play puts only the opponents in one class
    const list = baseField(save, ev, f).map((d) => (cls && D.CARS[D.DRIVERS[d.id].car].cls !== cls ? { ...driver(d.id, ev.tier, {}, cls), personality: d.personality, skill: d.skill, name: d.name } : d));
    if (!ev.team) return list;
    const m = teammate(save), mate = driver(m.id, ev.tier, { personality: "ally", team: "you", name: D.DRIVERS[m.id].name + (m.hired ? " (your crew)" : " (hired gun)") }, cls);
    return [mate, ...list.filter((d) => d.id !== m.id).map((d) => ({ ...d, team: "them" }))];
  }
  // Story consequences that change who you race and how they drive.
  function baseField(save, ev, f) {
    return (ev.field || []).map((id) => {
      if (ev.id === "c5-finale" && id === "benny" && f.crew_pip) return driver("pip", ev.tier, { personality: "defensive", skill: 0.95, name: "Pip Hollis (your team)", ally: true });
      if (id === "dex" && f.dex_feud) return driver("dex", ev.tier, { skill: Math.min(1.02, D.DRIVERS.dex.skill + (ev.tier - 3) * 0.008 + 0.02) });
      // the rival's stage changes how they drive against you: a feud races harder, an ally gives you room
      const stage = rivalStage(save, id);
      if (stage === "feud") return driver(id, ev.tier, { personality: "aggressive" });   // harder racing, not a faster car
      if (stage === "ally" && ev.mode !== "rival") return driver(id, ev.tier, { personality: "ally" });
      return driver(id, ev.tier);
    });
  }
  function config(save, ev, kind) {
    NG = Math.min(5, save.ng || 0);
    const S = save.settings, mode = ev.mode || "circuit", tr = ev.track;
    const par = D.PAR[tr] * (ev.laps || 3);
    const target = mode === "timetrial" ? (ev.goal && ev.goal.type === "time" ? { label: "Target", value: ev.goal.max } : { label: "Gold", value: par })
      : mode === "drift" ? { label: "Target", value: (ev.goal && ev.goal.min) || 5000 } : null;
    const laps = ev.laps || (mode === "sprint" || mode === "touge" || mode === "drag" ? 1 : mode === "endurance" ? 8 : 3);
    return { kind, eventId: ev.id, title: ev.title, track: mode === "drag" ? "harbour" : tr, mode, laps, level: ev.level || S.difficulty,
      heat: ev.heat || 1, stops: ev.stops || 4, pace: ev.pace || 300, rules: ev.rules || null, policeSpec: mode === "pursuit" ? policeSpec(ev.heat || 1) : null, weather: ev.weather || "dry", time: ev.time || "day", weatherChange: ev.weatherChange || null,
      field: fieldFor(save, ev), player: playerRacer(save), ghost: S.ghost && ["circuit", "sprint", "timetrial", "elimination", "rival"].includes(mode) ? save.ghosts[tr] || null : null,
      ghostOn: S.ghost, best: save.best[tr] || 0, target, tier: ev.tier || 1 };
  }
  // The police drive the Interceptor; from heat 3 it's upgraded (engine and tyres, then turbo).
  function policeSpec(heat) {
    const lv = Math.max(0, Math.min(3, heat - 2));
    return carStats("interceptor", { upgrades: { engine: lv, tires: lv, turbo: Math.max(0, lv - 1) }, tune: {} });
  }
  // Class-restricted events need a car of that class.
  function carAllowed(save, ev) {
    if (!ev || !ev.cls) return { ok: true };
    const c = D.CARS[save.garage.current];
    return c.cls === ev.cls ? { ok: true } : { ok: false, why: `Class ${ev.cls} cars only. Your ${c.name} is class ${c.cls}.`,
      owned: Object.keys(save.garage.owned).filter((id) => D.CARS[id].cls === ev.cls) };
  }

  // ---------------------------------------------------------------- Story
  const allMissions = () => D.CHAPTERS.flatMap((c) => c.missions.map((m) => ({ ...m, chapter: c.id })));
  const mission = (id) => allMissions().find((m) => m.id === id);
  function missions(save) {
    return D.CHAPTERS.map((c) => ({ ...c, state: c.id < save.story.chapter || save.story.ended ? "done" : c.id === save.story.chapter ? "current" : "locked",
      missions: c.missions.map((m, i) => ({ ...m, chapter: c.id, state: save.story.done[m.id] ? "done" : c.id === save.story.chapter && c.missions.slice(0, i).every((x) => save.story.done[x.id]) ? "available" : "locked" })) }));
  }
  function nextMission(save) { for (const c of missions(save)) for (const m of c.missions) if (m.state === "available") return m; return null; }
  function lines(save, list) {
    const f = save.story.flags;
    return (list || []).filter(([, , cond]) => !cond || (cond[0] === "!" ? !f[cond.slice(1)] : f[cond]))
      .map(([who, text]) => ({ who, name: (D.CAST[who] || { name: who }).name.replace("{name}", save.profile.name), text: text.replace(/\{name\}/g, save.profile.name), cast: D.CAST[who] || {} }));
  }
  function needsChoice(save, m) { return !!(m.choice && m.choice.when === "before" && save.story.choices[m.id] === undefined); }
  function choose(save, missionId, i) {
    const m = mission(missionId), opt = m && m.choice && m.choice.options[i];
    if (!opt) return { ok: false, error: "No such choice." };
    if (save.story.choices[missionId] !== undefined) return { ok: false, error: "Already chosen." };
    save.story.choices[missionId] = i;
    Object.assign(save.story.flags, opt.flags || {});
    if (opt.sponsor) save.sponsor = opt.sponsor;
    if (opt.respect) for (const [id, v] of Object.entries(opt.respect)) { const r = rival(save, id); r.respect = Math.max(-10, Math.min(10, r.respect + v)); }
    if (opt.grant && opt.grant.upgrade) { const st = save.garage.owned[save.garage.current]; st.upgrades[opt.grant.upgrade] = Math.min(3, st.upgrades[opt.grant.upgrade] + 1); }
    if (opt.money) save.money += opt.money;
    if (opt.loyalty) for (const [id, v] of Object.entries(opt.loyalty)) loyal(save, id, v);
    if (opt.flags && opt.flags.crew_otto) hire(save, "otto");
    if (opt.flags && opt.flags.crew_pip) hire(save, "pip");
    if (opt.crew) {
      const need = opt.needRespect || {}, ok = Object.entries(need).every(([id, v]) => rival(save, id).respect >= v);
      if (!ok) { save.story.flags.dex_refused = true; return { ok: true, lines: lines(save, opt.refused || []), refused: true }; }
      hire(save, opt.crew);
    }
    return { ok: true, lines: lines(save, opt.lines) };
  }
  // ---------------------------------------------------------------- Crew
  const hired = (save, id) => !!(save.crew.members[id] && save.crew.members[id].hired);
  function hire(save, id) {
    if (!D.CREW[id]) return false;
    const m = save.crew.members[id] || (save.crew.members[id] = { hired: false, loyalty: 5, level: 1, xp: 0, mission: false });
    if (m.hired) return false;
    m.hired = true; m.mission = true;
    if (Object.values(save.crew.members).filter((x) => x.hired).length >= 5) grant(save, "full_crew");
    return true;
  }
  function loyal(save, id, v) {
    const m = save.crew.members[id]; if (!m || !m.hired) return;
    m.loyalty = Math.max(0, Math.min(10, m.loyalty + v));
    if (id === "nia" && m.loyalty >= 9 && !save.story.flags.nia_gift) {   // Nia's thank-you: a free engine level
      save.story.flags.nia_gift = true; const st = save.garage.owned[save.garage.current]; st.upgrades.engine = Math.min(3, st.upgrades.engine + 1);
    }
  }
  const crewLoyalty = (save) => { const h = Object.values(save.crew.members).filter((m) => m.hired); return h.length ? h.reduce((a, m) => a + m.loyalty, 0) / h.length : 5; };
  // ---------------------------------------------------------------- Rival memory
  // A rival's stage comes from respect (earned by clean racing, close fights and wins; lost by contact) and record.
  function rivalStage(save, id) {
    const r = save.rivals[id]; if (!r) return "stranger";
    if (r.respect <= -3) return "feud";
    if (r.respect >= 6 && r.wins >= 3) return "ally";
    if (r.respect >= 3) return "respect";
    return "rival";
  }
  // What a rival says after a race with you, picked from what actually happened between the two of you.
  function rivalReaction(save, id, log, beat) {
    const T = D.RIVAL_LINES[id]; if (!T || !log) return null;
    const stage = rivalStage(save, id), k = log.youHit >= 2 ? "dirty" : log.close ? (beat ? "closeWin" : "closeLoss") : log.theyHit >= 2 ? "bullied"
      : log.passedThem >= 3 ? "passedMany" : stage === "ally" ? "ally" : beat ? "cleanWin" : "loss";
    const text = T[k].replace("{youHit}", log.youHit).replace("{passedThem}", log.passedThem).replace("{gap}", log.gap === null ? "0.1" : Math.abs(log.gap).toFixed(2));
    return { who: id, name: D.DRIVERS[id].name, text, cast: D.CAST[id] || {}, kind: k };
  }
  const rival = (save, id) => save.rivals[id] || (save.rivals[id] = freshRival());
  function goalMet(goal, s) {
    if (!goal) return s.finished && s.place <= 3;
    if (goal.type === "place") return s.finished && s.place <= goal.max;
    if (goal.type === "survive") return !s.eliminated && s.place <= goal.max;
    if (goal.type === "time") return s.finished && s.total > 0 && s.total <= goal.max;
    if (goal.type === "drift") return s.finished && s.drift >= goal.min;
    if (goal.type === "delivery") return !!(s.delivery && s.delivery.delivered && s.delivery.cargo >= (goal.cargo || 0));
    if (goal.type === "escape") return !!(s.pursuit && s.pursuit.result === "escaped");
    if (goal.type === "team") return !!(s.finished && s.team && s.team.won);
    return false;
  }
  function goalText(goal) {
    if (!goal) return "Finish on the podium";
    return { place: goal.max === 1 ? "Win" : `Finish in the top ${goal.max}`, survive: `Don't get eliminated; finish top ${goal.max}`,
      time: `Finish under ${Math.floor(goal.max / 60)}:${String(Math.round(goal.max % 60)).padStart(2, "0")}`, drift: `Score ${goal.min && goal.min.toLocaleString()} drift points`,
      delivery: `Deliver every stop with at least ${Math.round((goal.cargo || 0) * 100)}% of the cargo intact`, escape: "Lose the police", team: "Your team scores more points" }[goal.type];
  }

  // ---------------------------------------------------------------- Events, discovery, rivals, championships
  // ---------------------------------------------------------------- Living world
  const TRACK_DISTRICT = { kerbside: "park", harbour: "harbour", oldtown: "oldtown", ridge: "ridge" };
  const influence = (save, d) => save.world.influence[d] === undefined ? 20 : save.world.influence[d];
  const runs = (save, d) => influence(save, d) >= 75;
  const weekday = (save) => D.WEEKDAYS[(save.world.day - 1) % 7];
  // The weekly special: one open side event per in-game day, paying 50% more.
  function featured(save) {
    const open = D.SIDE.filter((e) => save.districts.includes(e.district) && save.rep >= Math.round(e.rep * (hired(save, "lio") ? 0.7 : 1)) && !e.crew).sort((a, b) => a.id < b.id ? -1 : 1);
    return open.length ? open[(save.world.day * 3) % open.length] : null;
  }
  const rumourSeen = (save, r) => save.rep >= Math.round(r.rep * (hired(save, "lio") ? 0.6 : 1));
  function secretEvents(save) { return D.RUMORS.filter((r) => save.world.rumors[r.id]).map((r) => ({ ...r.event, rumour: r.id, done: save.world.rumors[r.id] === "done", reward: r.reward })); }
  function turfEvents(save) { return Object.entries(D.TURF_EVENTS).filter(([d]) => runs(save, d)).map(([, e]) => e); }
  const news = (save, text) => { save.world.news.push({ day: save.world.day, text }); save.world.news = save.world.news.slice(-12); };
  // Two rivals race each other off-screen, for real: the same simulation as your races, decided on the road.
  function rivalSim(save) {
    const R = (typeof module !== "undefined" && module.exports) ? require("./racer.js") : root.JarvisRacer;
    const ids = Object.keys(D.RIVAL_LINES).filter((id) => save.rivals[id] && save.rivals[id].races > 0);
    if (!R || ids.length < 2) return null;
    const ia = save.world.day % ids.length, a = ids[ia], b = ids[(ia + 1 + (save.world.day % (ids.length - 1))) % ids.length];   // always two different rivals
    const track = ["kerbside", "harbour", "oldtown", "ridge"][save.world.day % 4];
    const r = R.newRace({ track, mode: "circuit", laps: 2, field: [driver(a, 4), driver(b, 4)], seed: save.world.day, playerSlot: 2 });
    const me = r.cars[0]; me.out = true; me.x = r.trk.OX + 25; me.y = r.trk.OY + 25;
    let t = 0; while (!(r.cars[1].done && r.cars[2].done) && t < 150) { R.step(r, 1 / 60, { steer: 0, thr: false, brk: false }); t += 1 / 60; }
    const [w, l] = r.cars[1].done && (!r.cars[2].done || r.cars[1].finish <= r.cars[2].finish) ? [r.cars[1], r.cars[2]] : [r.cars[2], r.cars[1]];
    const gap = l.done ? (l.finish - w.finish).toFixed(1) + "s" : "a lap";
    news(save, `${D.DRIVERS[w.id].name} beat ${D.DRIVERS[l.id].name} on ${R.TRACKS[track].name} by ${gap}.`);
    const home = Object.entries(D.TURF).find(([, T]) => T.rival === w.id);
    if (home) save.world.influence[home[0]] = Math.max(0, influence(save, home[0]) - 1);   // a winning home crew pushes back
    return { winner: w.id, loser: l.id, track };
  }
  function worldTick(save, s, ev, kind, passed, out) {
    save.world.day++;
    const d = ev.district || TRACK_DISTRICT[s.track];
    if (d && D.TURF[d] && kind !== "quick" && kind !== "free") {
      const before = influence(save, d), delta = passed && s.place === 1 ? 8 : s.finished && s.place <= 3 ? 3 : -2, after = Math.max(0, Math.min(100, before + delta));
      save.world.influence[d] = after; out.influence = { district: d, before, after };
      if (before < 75 && after >= 75) { out.notes.push(`You run ${D.DISTRICTS[d].name} now. ${D.TURF[d].crew} wants a turf war.`); news(save, `${save.team.name} takes over ${D.DISTRICTS[d].name}.`); out.achievements.push(...grant(save, "turf")); }
    }
    out.rumours = [];
    for (const r of D.RUMORS) if (!save.world.rumors[r.id] && rumourSeen(save, r)) { save.world.rumors[r.id] = "heard"; out.rumours.push(r); }
    if (ev.rumour && passed && save.world.rumors[ev.rumour] !== "done") {
      const r = D.RUMORS.find((x) => x.id === ev.rumour); save.world.rumors[ev.rumour] = "done";
      if (r.reward.money) save.money += r.reward.money;
      if (r.reward.car && !save.garage.unlocked.includes(r.reward.car)) save.garage.unlocked.push(r.reward.car);
      out.notes.push(`Secret event won: ${r.reward.text}`);
      if (D.RUMORS.filter((x) => save.world.rumors[x.id] === "done").length >= 2) out.achievements.push(...grant(save, "rumours"));
    }
    out.news = rivalSim(save);
    if (kind !== "quick" && kind !== "free") crewDay(save, out);
  }
  // Which ending your story earns: the first in data order whose conditions you meet.
  function endingFor(save) {
    const f = save.story.flags, ids = Object.keys(save.rivals).filter((id) => D.RIVAL_LINES[id]);
    const allies = ids.filter((id) => rivalStage(save, id) === "ally").length, feuds = ids.filter((id) => rivalStage(save, id) === "feud").length;
    const champs = Object.values(save.champWins).reduce((a, b) => a + b, 0), loyalty = crewLoyalty(save);
    if (loyalty >= 7 && allies >= 2 && champs >= 1) return "legend";
    if (f.route_underground && f.benny_kind) return "people";
    if (f.route_league && hired(save, "priya")) return "corporate";
    if (feuds >= 2 || loyalty <= 3) return "lone";
    return "champion";
  }
  function sideEvents(save) {
    const scout = hired(save, "lio") ? 0.7 : 1;
    return D.SIDE.filter((e) => save.districts.includes(e.district) && !(e.crew && hired(save, e.crew))).map((e) => {
      const open = save.rep >= Math.round(e.rep * scout);
      if (open && !save.discovered[e.id]) save.discovered[e.id] = Date.now();
      return { ...e, open, done: !!save.sideDone[e.id], fresh: open && !save.sideDone[e.id] };
    });
  }
  function rivalEvents(save) {
    return D.RIVAL_CHALLENGES.filter((r) => save.story.done[r.after]).map((r) => ({ ...r, title: `Rematch: ${D.DRIVERS[r.rival].name}`, mode: "rival", laps: 3, field: [r.rival],
      time: ["night", "dusk", "day"][r.tier % 3], goal: { type: "place", max: 1 } }));
  }
  const champOpen = (save, def) => (def.after >= 6 ? save.story.ended : save.story.chapter > def.after || save.story.ended);
  function champEvent(save) {
    const c = save.champ, def = c && D.CHAMPIONSHIPS.find((x) => x.id === c.id);
    if (!def) return null;
    const r = def.rounds[c.round];
    return { id: `${def.id}-r${c.round + 1}`, title: `${def.name} · Round ${c.round + 1} of ${def.rounds.length}`, track: r.track, mode: "circuit", laps: 3, field: def.field, tier: def.tier, time: r.time, weather: r.weather || "dry", weatherChange: r.weatherChange || null, goal: { type: "place", max: 3 } };
  }
  function startChamp(save, id) {
    const def = D.CHAMPIONSHIPS.find((c) => c.id === id);
    if (!def || !champOpen(save, def)) return { ok: false, error: "Not open yet." };
    save.champ = { id, round: 0, points: {}, results: [] };
    return { ok: true };
  }
  function champTable(save) {
    const c = save.champ; if (!c) return [];
    const def = D.CHAMPIONSHIPS.find((x) => x.id === c.id), ids = ["YOU", ...def.field];
    return ids.map((id) => ({ id, name: id === "YOU" ? save.profile.name : D.DRIVERS[id].name, points: c.points[id] || 0 })).sort((a, b) => b.points - a.points);
  }

  // ---------------------------------------------------------------- Results → rewards (once per race id)
  function grant(save, id) { if (!D.ACHIEVEMENTS[id] || save.achievements[id]) return []; save.achievements[id] = Date.now(); return [id]; }
  function medal(track, laps, total) {
    if (!(total > 0)) return null;
    const par = D.PAR[track] * laps;
    return total <= par ? "gold" : total <= par * 1.05 ? "silver" : total <= par * 1.12 ? "bronze" : null;
  }
  // ctx: { kind: "story"|"side"|"rival"|"champ"|"quick"|"free", event, raceId }
  function applyResult(save, ctx, s) {
    if (!ctx.raceId || save.claimed.includes(ctx.raceId)) return { already: true };
    save.claimed.push(ctx.raceId); save.claimed = save.claimed.slice(-200); save.interrupted = null;
    const ev = ctx.event || {}, tier = ev.tier || 1, kind = ctx.kind, out = { money: 0, xp: 0, rep: 0, unlocked: [], achievements: [], lines: [], notes: [] };
    if (s.mode === "pursuit") return applyPursuit(save, ctx, s, out);
    const legal = carAllowed(save, ev).ok;   // a class-restricted event in the wrong class can't be won
    const passed = legal && (kind === "quick" || kind === "free" ? s.finished && s.place === 1 : goalMet(ev.goal, s));
    if (!legal) out.notes.push(carAllowed(save, ev).why);
    out.passed = passed;
    // money and experience
    let money = 0;
    if (s.mode === "timetrial") { out.medal = medal(s.track, s.laps, s.total); money = BASE[tier] * ({ gold: 1, silver: 0.6, bronze: 0.35 }[out.medal] || (s.finished ? 0.1 : 0)); }
    else if (s.mode === "drift") { const tgt = (ev.goal && ev.goal.min) || 5000; money = BASE[tier] * Math.min(1.2, s.drift / tgt) * (s.finished ? 1 : 0); }
    else if (s.mode === "delivery") money = s.delivery && s.delivery.delivered ? BASE[tier] * (0.3 + 0.7 * s.delivery.cargo) : 0;   // paid by what arrives
    else if (s.mode === "team") money = s.finished ? BASE[tier] * (s.team && s.team.won ? 0.9 : 0.25) : 0;
    else money = s.finished || s.eliminated ? BASE[tier] * (PLACE[s.place - 1] || 0.08) * (s.eliminated ? 0.4 : 1) : 0;
    if (kind === "quick" || kind === "free") money *= 0.35;   // practice pays a little
    if (kind === "story" && passed && !save.story.done[ev.id]) money *= 1.5;
    if (kind === "story" && save.story.done[ev.id]) money *= 0.5;   // replaying a finished mission
    if (kind === "side" && passed && !save.sideDone[ev.id]) { money *= 1.5; out.notes.push("First completion bonus."); }
    if (save.sponsor) { const sp = D.SPONSORS[save.sponsor]; if (save.sponsor === "bluewater" || s.place <= 3) money *= 1 + sp.bonus; }
    if (hired(save, "priya")) money *= 1.1;
    if (save.ng && kind !== "quick" && kind !== "free") money *= 1 + 0.25 * Math.min(4, save.ng);   // New Game+ pays more
    const fe = featured(save); if (kind === "side" && fe && fe.id === ev.id) { money *= 1.5; out.notes.push(`${weekday(save)} special: +50%.`); }
    const dist = ev.district || TRACK_DISTRICT[s.track]; if (dist && runs(save, dist) && kind !== "quick" && kind !== "free") money *= 1.1;
    out.money = Math.round(money / 10) * 10;
    out.xp = Math.round((40 + tier * 60) * (passed ? 1.6 : 0.6) * (s.finished ? 1 : 0.5) * (hired(save, "otto") ? 1.1 : 1));
    out.rep = passed ? tier * 8 + (s.place === 1 ? 4 : 0) : s.finished ? 2 : 0;
    const lv0 = level(save.xp);
    save.money += out.money; save.xp += out.xp; save.rep += out.rep;
    out.levelUp = level(save.xp) > lv0 ? level(save.xp) : 0;
    // stats and records
    const st = save.stats; st.races++; st.contacts += s.contacts || 0;
    if (save.settings.damage === "persistent" && save.garage.owned[save.garage.current] && kind !== "quick" && kind !== "free") {   // damage carries into the next race until repaired
      const car = save.garage.owned[save.garage.current]; car.dmg = Math.min(1, Math.max(car.dmg || 0, s.damage || 0)); if (car.dmg > 0.05) out.notes.push(`Your car took damage (${Math.round(car.dmg * 100)}%). Repair it in the garage.`);
    }
    if (s.finished && s.place === 1 && s.of > 1) st.wins++; else if (s.of > 1) st.losses++;
    if (s.finished && s.place <= 3 && s.of > 1) st.podiums++;
    if (!s.finished) st.dnfs++;
    if (s.best && (!save.best[s.track] || s.best < save.best[s.track])) { save.best[s.track] = s.best; out.newBest = true; }
    const rk = s.track + ":" + s.mode;
    if (s.finished && s.total && s.mode !== "drift" && (!save.bestRace[rk] || s.total < save.bestRace[rk])) save.bestRace[rk] = s.total;
    if (out.medal) { const mk = s.track; const rank = { gold: 3, silver: 2, bronze: 1 }; if (!save.medals[mk] || rank[out.medal] > rank[save.medals[mk]]) save.medals[mk] = out.medal; }
    save.history.push({ at: Date.now(), kind, title: ev.title || "Race", track: s.track, mode: s.mode, place: s.place, of: s.of, total: s.total, drift: s.drift, passed, money: out.money });
    save.history = save.history.slice(-60);
    // rivals: everyone you raced, you beat or they beat you
    out.reactions = [];
    for (const id of (s.order || [])) {
      if (!D.DRIVERS[id] || id === "YOU") continue;
      const r = rival(save, id), L = (s.rivals || {})[id], beat = s.beat.includes(id) && !s.eliminated, before = rivalStage(save, id);
      r.races++;
      if (beat) { r.wins++; r.streak = Math.max(1, r.streak + 1); r.last = "win"; } else { r.losses++; r.streak = Math.min(-1, r.streak - 1); r.last = "loss"; }
      let dr = beat ? 1 : 0;
      if (L) {
        r.passedThem += L.passedThem; r.passedYou += L.passedYou; r.contacts += L.contacts; r.youHit += L.youHit; r.theyHit += L.theyHit;
        if (L.close) { r.close++; dr += 1; }
        if (L.youHit >= 2) dr -= 2;   // dirty racing costs respect
      }
      r.respect = Math.max(-10, Math.min(10, r.respect + dr));
      const after = rivalStage(save, id);
      if (after !== before) out.notes.push(`${D.DRIVERS[id].name}: ${{ feud: "this is a feud now", ally: "an ally now", respect: "respects you", rival: "a rival again" }[after]}.`);
      if (after === "ally") out.achievements.push(...grant(save, "first_ally"));
      if (D.RIVAL_LINES[id] && out.reactions.length < 2) { const x = rivalReaction(save, id, L, beat); if (x) out.reactions.push(x); }
      if (s.mode === "rival" && s.place === 1 && s.finished) out.achievements.push(...grant(save, "beat_" + id));
    }
    // story progression
    if (kind === "story" && passed) {
      const first = !save.story.done[ev.id];
      save.story.done[ev.id] = true;
      out.lines = lines(save, ev.win);
      if (first && ev.rewards) {
        if (ev.rewards.district && !save.districts.includes(ev.rewards.district)) { save.districts.push(ev.rewards.district); out.unlocked.push({ type: "district", id: ev.rewards.district, name: D.DISTRICTS[ev.rewards.district].name }); }
        if (ev.rewards.car) {
          const c = D.CARS[ev.rewards.car];
          if (!save.garage.unlocked.includes(ev.rewards.car)) save.garage.unlocked.push(ev.rewards.car);
          if (c.price === null && !save.garage.owned[ev.rewards.car]) { save.garage.owned[ev.rewards.car] = carState(ev.rewards.car); out.unlocked.push({ type: "car", id: ev.rewards.car, name: c.name, gift: true }); }
          else out.unlocked.push({ type: "car", id: ev.rewards.car, name: c.name });
        }
      }
      const ch = D.CHAPTERS.find((c) => c.id === save.story.chapter);
      if (ch && ch.missions.every((m) => save.story.done[m.id])) {
        save.story.chapter++;
        const nx = D.CHAPTERS.find((c) => c.id === save.story.chapter);
        if (nx) { if (!save.districts.includes(nx.district)) save.districts.push(nx.district); out.chapter = { id: nx.id, title: nx.title, blurb: nx.blurb }; }
        else {
          save.story.ended = true; out.ending = endingFor(save); save.endings[out.ending] = Date.now(); out.achievements.push(...grant(save, "story"));
          if (Object.keys(save.endings).length >= 3) out.achievements.push(...grant(save, "every_ending"));
        }
      }
      if (ev.choice && ev.choice.when === "after" && save.story.choices[ev.id] === undefined) out.choice = ev.choice;
    } else if (kind === "story") out.lines = lines(save, ev.lose);
    if (kind === "side" && passed) save.sideDone[ev.id] = (save.sideDone[ev.id] || 0) + 1;
    if (kind === "side" && passed && ev.crew && hire(save, ev.crew)) out.unlocked.push({ type: "crew", id: ev.crew, name: D.CREW[ev.crew].name });
    if (passed) for (const [id, m] of Object.entries(save.crew.members)) if (m.hired && id !== "dex") { m.xp += out.xp; m.level = Math.min(5, 1 + Math.floor(m.xp / 4000)); }
    if (kind === "champ" && save.champ) out.champ = champRound(save, s);
    if (kind === "tourney" && save.tourney) out.tourney = tourneyRound(save, passed);
    // mode records
    const R2 = save.records, won = s.finished && s.place === 1;
    if (s.mode === "drag" && s.drag) {
      if (s.drag.et > 0 && (!R2.drag.best || s.drag.et < R2.drag.best)) { R2.drag.best = s.drag.et; out.notes.push(`New best drag time: ${s.drag.et.toFixed(3)} s.`); }
      if (won) R2.drag.wins++;
      if (s.drag.perfect >= 5) out.achievements.push(...grant(save, "perfect_drag"));
    }
    if (s.mode === "touge" && won) R2.touge.wins++;
    if (s.mode === "endurance" && won) { R2.endurance.wins++; out.achievements.push(...grant(save, "iron")); }
    if (s.mode === "delivery" && s.delivery && s.delivery.delivered) { R2.delivery.done++; if (s.delivery.cargo >= 0.999) out.achievements.push(...grant(save, "fragile")); }
    // a wager on a rival race: the stake was taken at the start; a win pays it back twice
    if (save.wager && save.wager.event === ev.id) {
      const amt = save.wager.amount; save.wager = null;
      if (passed) { save.money += amt * 2; out.wager = { won: true, amount: amt }; if (amt >= 2500) out.achievements.push(...grant(save, "high_roller")); }
      else out.wager = { won: false, amount: amt };
    }
    if (kind !== "quick" && kind !== "free") { contractTick(save, s, out); teamPoints(save, s, out); }
    worldTick(save, s, ev, kind, passed, out);
    // achievements
    if (s.finished && s.place === 1 && s.of > 1) {
      out.achievements.push(...grant(save, "first_win"));
      if (!s.contacts) out.achievements.push(...grant(save, "clean_win"));
      if (s.tod === "night" && s.weather === "rain") out.achievements.push(...grant(save, "rain_night"));
    }
    if (st.podiums >= 10) out.achievements.push(...grant(save, "podium10"));
    if (s.drift >= 8000) out.achievements.push(...grant(save, "drifter"));
    if (Object.keys(D.DISTRICTS).every((d) => save.districts.includes(d))) out.achievements.push(...grant(save, "all_districts"));
    if (Object.keys(D.PAR).every((t) => save.medals[t] === "gold")) out.achievements.push(...grant(save, "gold_all"));
    return out;
  }
  // ---------------------------------------------------------------- Team, sponsors, New Game+
  function setTeam(save, patch) {
    if (patch.name !== undefined) { const v = String(patch.name).trim().slice(0, 24); if (!v) return { ok: false, error: "Your team needs a name." }; save.team.name = v; }
    for (const k of ["color", "color2"]) if (patch[k] !== undefined) { if (!/^#[0-9a-f]{6}$/i.test(patch[k])) return { ok: false, error: "Bad colour." }; save.team[k] = patch[k]; }
    return { ok: true };
  }
  function teamLivery(save) {   // your car in the team's colours (free)
    const st = save.garage.owned[save.garage.current]; st.paint = save.team.color; st.paint2 = save.team.color2; return { ok: true };
  }
  // Contracts
  const contractOffers = (save) => Object.entries(D.CONTRACTS).filter(([id, k]) => k.minRep <= save.rep && !save.contracts.some((c) => c.id === id)).map(([id, k]) => ({ id, ...k }));
  function signContract(save, id) {
    const k = D.CONTRACTS[id];
    if (!k) return { ok: false, error: "No such contract." };
    if (save.contracts.some((c) => c.id === id)) return { ok: false, error: "Already signed." };
    if (save.contracts.length >= 3) return { ok: false, error: "Three contracts at a time." };
    if (k.minRep > save.rep) return { ok: false, error: `${k.sponsor} wants ${k.minRep} reputation first.` };
    save.contracts.push({ id, progress: 0, left: k.races }); return { ok: true };
  }
  function dropContract(save, id) {
    const i = save.contracts.findIndex((c) => c.id === id); if (i < 0) return { ok: false, error: "Not signed." };
    save.contracts.splice(i, 1); save.rep = Math.max(0, save.rep - 5); return { ok: true };
  }
  function contractGain(goal, s) {
    const vs = s.of > 1 && !s.pursuit && !s.delivery, won = s.finished && s.place === 1 && vs;
    return { podiums: s.finished && s.place <= 3 && vs ? 1 : 0, clean: s.finished && vs && !s.contacts ? 1 : 0, wins: won ? 1 : 0, drift: s.mode === "drift" && s.finished ? s.drift : 0,
      drag: s.mode === "drag" && won ? 1 : 0, escapes: s.pursuit && s.pursuit.result === "escaped" ? 1 : 0, endurance: s.mode === "endurance" && s.finished && s.place <= 3 ? 1 : 0 }[goal.type] || 0;
  }
  function contractTick(save, s, out) {
    out.contracts = [];
    for (const c of save.contracts.slice()) {
      const k = D.CONTRACTS[c.id];
      c.progress += contractGain(k.goal, s); c.left--;
      if (c.progress >= k.goal.n) {
        save.money += k.pay; save.rep += k.rep; save.team.rep += k.rep; save.contracts.splice(save.contracts.indexOf(c), 1);
        out.contracts.push({ id: c.id, done: true }); out.notes.push(`Contract complete: ${k.sponsor} pays ${"₭" + k.pay.toLocaleString()} for “${k.title}”.`);
        out.achievements.push(...grant(save, "contract"));
      } else if (c.left <= 0) {
        save.contracts.splice(save.contracts.indexOf(c), 1);
        out.contracts.push({ id: c.id, expired: true }); out.notes.push(`Contract expired: “${k.title}” for ${k.sponsor} (${c.progress.toLocaleString()} of ${k.goal.n.toLocaleString()}).`);
      }
    }
  }
  // Team championship: your points come from your finishes (and your teammate's in team races); the crews score
  // in the world's own races each day.
  function teamPoints(save, s, out) {
    if (s.pursuit || s.delivery || !(s.of > 1)) return;
    const pts = s.team ? s.team.you : s.finished || s.eliminated ? D.POINTS[s.place - 1] || 0 : 0;
    save.team.points += pts; out.teamPts = pts;
  }
  function crewDay(save, out) {   // one career race day of the team championship
    const T = save.team, day = save.world.day;
    T.days++;
    for (const [crew, lead] of Object.entries(D.CREWS)) {
      // each crew's day: its lead driver's pace plus the luck of the day (deterministic per day and crew)
      let h = day * 2654435761 >>> 0; for (const ch of crew) h = (h ^ ch.charCodeAt(0)) * 16777619 >>> 0;
      T.rivals[crew] = (T.rivals[crew] || 0) + Math.round((D.DRIVERS[lead].skill - 0.85) * 40 + (h % 1000) / 1000 * 4);
    }
    if (out.news && out.news.winner) { const crew = Object.keys(D.CREWS).find((c) => D.CREWS[c] === out.news.winner); if (crew) T.rivals[crew] += 3; }
    if (T.days < D.TEAM_SEASON) return;
    const table = teamTable(save), place = table.findIndex((r) => r.you) + 1, prize = D.SEASON_PRIZE[place - 1] || 0;
    save.money += prize; T.rep += [30, 15, 8][place - 1] || 0;
    if (place === 1) { T.titles++; out.achievements.push(...grant(save, "team_champ")); }
    news(save, `Season ${T.season} team championship: ${table[0].name} take the title.`);
    out.season = { season: T.season, place, prize, table };
    T.season++; T.days = 0; T.points = 0; T.rivals = {};
  }
  function teamTable(save) {
    const T = save.team;
    return [{ name: T.name, points: T.points, you: true }, ...Object.keys(D.CREWS).map((c) => ({ name: c, points: T.rivals[c] || 0, you: false }))].sort((a, b) => b.points - a.points || (a.you ? -1 : 1));
  }
  // New Game+: the story, the map and the rivals start again; you keep your cars, money, level, crew, team,
  // records, medals, best laps, ghosts and achievements. The field is 1% quicker and prizes 25% bigger per cycle.
  function newGamePlus(save) {
    if (!save.story.ended) return { ok: false, error: "Finish the story first." };
    const n = fresh(), keep = ["profile", "money", "xp", "stats", "history", "best", "bestRace", "medals", "ghosts", "garage", "achievements", "champWins", "crew", "team", "records", "endings", "settings", "quick", "claimed"];
    for (const k of keep) n[k] = JSON.parse(JSON.stringify(save[k]));
    n.ng = (save.ng || 0) + 1; n.rep = Math.round(save.rep / 4);   // people remember you, a little
    n.team.points = 0; n.team.rivals = {}; n.team.days = 0;
    for (const st of Object.values(n.garage.owned)) st.dmg = 0;
    const ach = grant(n, "new_game_plus");
    return { ok: true, save: n, achievements: ach };
  }

  // ---------------------------------------------------------------- Police pursuit (its own mode, apart from the Grand Prix)
  // Escape and the bounty pays (30% of it as prize money); get busted and you pay the fine (never more than half of
  // what you have).
  const pursuitHeats = (save) => Math.min(5, 1 + (save.records.pursuit.heat || 0));   // escape at a heat to unlock the next
  function pursuitEvent(save, o = {}) {
    const heat = Math.max(1, Math.min(pursuitHeats(save), o.heat | 0 || 1));
    return { id: "pursuit", title: `Police pursuit · heat ${heat}`, track: R_TRACK(o.track), mode: "pursuit", heat, tier: Math.min(5, heat), time: o.time || "night", weather: o.weather || "dry", field: [], goal: { type: "escape" } };
  }
  const R_TRACK = (t) => (D.PAR[t] !== undefined ? t : "kerbside");
  function applyPursuit(save, ctx, s, out) {
    const P = s.pursuit || { result: "chase", heat: 1, bounty: 0, fine: 0 }, rec = save.records.pursuit;
    out.pursuit = P; out.passed = P.result === "escaped";
    if (P.result === "escaped") {
      out.money = Math.round(P.bounty * 0.3 / 10) * 10; out.rep = 3 * P.heat + 2; out.xp = Math.round((60 + 50 * P.heat) * (hired(save, "otto") ? 1.1 : 1));
      rec.escapes++; if (P.bounty > rec.best) { rec.best = P.bounty; out.notes.push(`Biggest bounty yet: ${P.bounty.toLocaleString()}.`); }
      if (P.heat > rec.heat) { rec.heat = P.heat; if (P.heat < 5) out.notes.push(`Heat ${P.heat + 1} pursuits are open now.`); }
      out.achievements.push(...grant(save, "first_escape"));
      if (P.heat >= 5) out.achievements.push(...grant(save, "escape_artist"));
    } else if (P.result === "busted") {
      out.fine = Math.min(Math.floor(save.money / 2 / 10) * 10, P.fine || 0); save.money -= out.fine; rec.busts++; rec.fines += out.fine; out.xp = 30;   // never more than half your money
      out.notes.push(out.fine ? `Fined ${"₭" + out.fine.toLocaleString()}.` : "Fined, but you had nothing to pay with. Let off with a warning.");
    }
    const lv0 = level(save.xp);
    save.money += out.money; save.xp += out.xp; save.rep += out.rep;
    out.levelUp = level(save.xp) > lv0 ? level(save.xp) : 0;
    save.stats.races++;
    if (save.settings.damage === "persistent" && save.garage.owned[save.garage.current]) {
      const car = save.garage.owned[save.garage.current]; car.dmg = Math.min(1, Math.max(car.dmg || 0, s.damage || 0));
      if (car.dmg > 0.05) out.notes.push(`Your car took damage (${Math.round(car.dmg * 100)}%). Repair it in the garage.`);
    }
    contractTick(save, s, out);
    save.history.push({ at: Date.now(), kind: "pursuit", title: (ctx.event && ctx.event.title) || "Police pursuit", track: s.track, mode: "pursuit", place: s.place, of: s.of, total: s.total, drift: 0, passed: out.passed, money: out.money - (out.fine || 0) });
    save.history = save.history.slice(-60);
    return out;
  }

  // ---------------------------------------------------------------- Tournaments
  const tourneyOpen = (save, def) => save.story.chapter > def.after || save.story.ended;
  function startTourney(save, id) {
    const def = D.TOURNAMENTS.find((t) => t.id === id);
    if (!def || !tourneyOpen(save, def)) return { ok: false, error: "Not open yet." };
    if (save.tourney) return { ok: false, error: "Finish or leave the tournament you're in first." };
    save.tourney = { id, stage: 0 }; return { ok: true };
  }
  function tourneyEvent(save) {
    const t = save.tourney, def = t && D.TOURNAMENTS.find((x) => x.id === t.id); if (!def) return null;
    const st = def.stages[t.stage];
    return { ...st, id: `${def.id}-s${t.stage + 1}`, title: `${def.name} · ${st.title}`, tier: def.tier, district: TRACK_DISTRICT[st.track], laps: st.laps || 1 };
  }
  function tourneyRound(save, passed) {
    const t = save.tourney, def = D.TOURNAMENTS.find((x) => x.id === t.id), stage = def.stages[t.stage];
    if (!passed) { save.tourney = null; return { done: true, out: true, name: def.name, stage: stage.title }; }
    if (t.stage + 1 >= def.stages.length) {
      save.tourney = null; save.money += def.prize; save.records.tournament.wins++;
      return { done: true, won: true, name: def.name, prize: def.prize, achievements: grant(save, "knockout") };
    }
    t.stage++;
    return { done: false, name: def.name, next: def.stages[t.stage].title };
  }

  // ---------------------------------------------------------------- Wagers (rival races)
  const wagerOptions = (save) => [0, 500, 1000, 2500, 5000].filter((v) => v <= save.money);
  function placeWager(save, ev, amount) {
    save.wager = null;
    if (!amount) return { ok: true };
    if (!ev || !String(ev.id).startsWith("r-")) return { ok: false, error: "Wagers are for rival races." };
    if (amount > save.money || !wagerOptions(save).includes(amount)) return { ok: false, error: "You can't cover that stake." };
    save.money -= amount; save.wager = { amount, event: ev.id };
    return { ok: true };
  }

  function champRound(save, s) {
    const c = save.champ, def = D.CHAMPIONSHIPS.find((x) => x.id === c.id);
    s.order.forEach((id, i) => { c.points[id] = (c.points[id] || 0) + (s.eliminated && id === "YOU" ? 0 : D.POINTS[i] || 0); });
    c.results.push({ track: def.rounds[c.round].track, place: s.place });
    const table = champTable(save);
    if (c.round + 1 >= def.rounds.length) {
      const place = table.findIndex((r) => r.id === "YOU") + 1, prize = Math.round(BASE[def.tier] * [3, 1.6, 1, 0.5, 0.3, 0.2][place - 1] / 10) * 10;
      save.money += prize; save.champ = null;
      const ach = place === 1 ? grant(save, "champion") : [];
      if (place === 1) save.champWins[def.id] = (save.champWins[def.id] || 0) + 1;
      return { done: true, place, prize, table, name: def.name, achievements: ach };
    }
    c.round++;
    return { done: false, round: c.round, table, name: def.name };
  }

  const api = { influence, runs, weekday, featured, secretEvents, turfEvents, rivalSim, worldTick, hire, hired, loyal, crewLoyalty, rivalStage, rivalReaction, endingFor, carAvailable, setTune, repair, repairCost, lookOf, VERSION, KEY, BAK, CORRUPT, LEGACY, fresh, carState, validate, migrateV2, load, persist, exportSave, importSave,
    level, xpFor, carStats, bars, upgradeCost, buyCar, buyUpgrade, setLook, driver, playerRacer, config, missions, nextMission, mission,
    lines, needsChoice, choose, goalMet, goalText, sideEvents, pursuitHeats, pursuitEvent, policeSpec, carAllowed, teammate, classCar,
    tourneyOpen, startTourney, tourneyEvent, wagerOptions, placeWager, setTeam, teamLivery, contractOffers, signContract, dropContract, contractTick, teamTable, newGamePlus, rivalEvents, champOpen, champEvent, startChamp, champTable, applyResult, medal, grant };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.KerbsideCareer = api;
})(typeof self !== "undefined" ? self : globalThis);
