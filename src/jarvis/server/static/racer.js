"use strict";
// Kerbside Grand Prix: the racing engine (the race view is racer-render.js). A top-down racer with a layered 2.5D look: four circuits,
// twelve modes (circuit, sprint, elimination, time trial, drift, rival here; pursuit, drag, touge, endurance, delivery
// and team in racer-modes.js), cars with their own stats and looks, AI drivers
// with personalities, nitro, damage, weather and time of day, and a ghost of your best lap. Written for JARVIS: no
// library, no model, no network. The simulation (newRace/step/summary) is plain data and runs in Node for the tests;
// mount() adds the canvas, HUD and controls. With racer-ui.js loaded, mount() opens the full game (career, garage,
// world map); without it, a simple start card still runs quick races. Best times and ghosts stay in this browser.
(function (root) {
  const TW = 150, SP = 12, LAPS = 3, RAD = 17, ACC = 430, GHOST_DT = 0.05, LATG = 90;

  // ---------------------------------------------------------------- Tracks: closed splines, resampled every SP units
  const TRACKS = {
    kerbside: { name: "Kerbside Circuit", blurb: "Eighteen corners, a fast back straight and a hairpin.", decor: "park",
      ctrl: [[400, 1400], [400, 760], [560, 430], [960, 340], [1240, 580], [1500, 520], [1800, 300], [2300, 330],
        [2620, 680], [2470, 1040], [2020, 1090], [1760, 1340], [2100, 1600], [2520, 1690], [2440, 2050], [1640, 2160],
        [920, 2060], [560, 1820]] },
    harbour: { name: "Harbour Loop", blurb: "Long straights by the water and one tight chicane. Nitro country.", decor: "water",
      ctrl: [[400, 1250], [400, 640], [640, 360], [1500, 320], [2350, 360], [2640, 620], [2640, 1000], [2380, 1270],
        [1980, 1290], [1800, 1110], [1560, 1110], [1380, 1300], [700, 1360]] },
    ridge: { name: "Ridge Hairpins", blurb: "Up and over the ridge: switchbacks, few places to pass.", decor: "rock",
      ctrl: [[400, 1650], [400, 900], [580, 500], [950, 430], [1080, 780], [1280, 1000], [1520, 860], [1520, 470],
        [1820, 300], [2220, 400], [2330, 800], [2080, 1120], [2330, 1450], [2230, 1820], [1720, 1880], [1320, 1620],
        [960, 1880], [600, 1930]] },
    oldtown: { name: "Old Town Streets", blurb: "Stone walls, canal bridges and square corners.", decor: "city",
      ctrl: [[420, 1500], [420, 640], [580, 430], [1150, 410], [1330, 560], [1330, 860], [1500, 1020], [2150, 1020],
        [2330, 1180], [2330, 1620], [2160, 1800], [1600, 1800], [1450, 1640], [1250, 1640], [1100, 1800], [620, 1830],
        [440, 1700]] },
  };
  const cr = (a, b, c, d, t) => { const t2 = t * t, t3 = t2 * t; return 0.5 * (2 * b + (-a + c) * t + (2 * a - 5 * b + 4 * c - d) * t2 + (-a + 3 * b - 3 * c + d) * t3); };
  const wrapA = (a) => { while (a > Math.PI) a -= 2 * Math.PI; while (a < -Math.PI) a += 2 * Math.PI; return a; };
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const built = {};
  function track(key) {
    if (!TRACKS[key]) key = "kerbside";
    if (built[key]) return built[key];
    const C = TRACKS[key].ctrl, raw = [];
    for (let i = 0; i < C.length; i++) {
      const n = C.length, p0 = C[(i - 1 + n) % n], p1 = C[i], p2 = C[(i + 1) % n], p3 = C[(i + 2) % n];
      for (let s = 0; s < 40; s++) { const t = s / 40; raw.push([cr(p0[0], p1[0], p2[0], p3[0], t), cr(p0[1], p1[1], p2[1], p3[1], t)]); }
    }
    const P = [];
    let prev = raw[0], need = SP; P.push(prev);
    for (let i = 1; i <= raw.length; i++) {
      const cur = raw[i % raw.length]; let seg = Math.hypot(cur[0] - prev[0], cur[1] - prev[1]);
      while (seg >= need) { const t = need / seg; prev = [prev[0] + (cur[0] - prev[0]) * t, prev[1] + (cur[1] - prev[1]) * t]; P.push(prev); seg -= need; need = SP; }
      need -= seg; prev = cur;
    }
    const l = P[P.length - 1]; if (Math.hypot(l[0] - P[0][0], l[1] - P[0][1]) < SP / 2) P.pop();
    const N = P.length, ANG = P.map((p, i) => { const q = P[(i + 1) % N]; return Math.atan2(q[1] - p[1], q[0] - p[0]); });
    let minX = 1e9, minY = 1e9, maxX = -1e9, maxY = -1e9;
    for (const [x, y] of P) { minX = Math.min(minX, x); minY = Math.min(minY, y); maxX = Math.max(maxX, x); maxY = Math.max(maxY, y); }
    const M = 520, t = { key, ...TRACKS[key], P, N, ANG, minX, minY, maxX, maxY, OX: minX - M, OY: minY - M,
      WW: Math.ceil(maxX - minX + 2 * M), WH: Math.ceil(maxY - minY + 2 * M), grids: {} };
    t.nrm = (i) => { const a = ANG[((i % N) + N) % N]; return [-Math.sin(a), Math.cos(a)]; };
    // curvature (radians per unit) over ±3 points: how hard each part of the road turns
    t.K = P.map((_, i) => Math.abs(wrapA(ANG[(i + 3) % N] - ANG[(i - 3 + N) % N])) / (6 * SP));
    t.slots = (n) => t.grids[n] || (t.grids[n] = [...Array(n).keys()].map((k) => {
      const i = ((N - 5 - k * 5) % N + N) % N, [nx, ny] = t.nrm(i), side = n === 1 ? 0 : k % 2 ? 1 : -1;
      return { i, x: P[i][0] + nx * side * 34, y: P[i][1] + ny * side * 34, a: ANG[i] };
    }));
    t.grid = t.slots(4);
    return (built[key] = t);
  }

  // Nearest centreline point: a local search around the last one (cars move a few points per step), or all of them.
  function nearest(t, x, y, hint) {
    let best = -1, bd = Infinity;
    const scan = (i) => { const p = t.P[i], d = (p[0] - x) ** 2 + (p[1] - y) ** 2; if (d < bd) { bd = d; best = i; } };
    if (hint < 0) for (let i = 0; i < t.N; i++) scan(i);
    else for (let k = -45; k <= 45; k++) scan(((hint + k) % t.N + t.N) % t.N);
    return [best, Math.sqrt(bd)];
  }
  const latOff = (t, c) => { const [nx, ny] = t.nrm(c.idx), p = t.P[c.idx]; return (c.x - p[0]) * nx + (c.y - p[1]) * ny; };

  // ---------------------------------------------------------------- Cars, levels, personalities
  const ROSTER = [
    { code: "YOU", name: "You", color: "#e9c44a", num: 7, ai: false, skill: 1, lane: 0 },
    { code: "JRV", name: "JARVIS", color: "#d23c3c", num: 1, ai: true, skill: 0.985, lane: -18 },
    { code: "BLU", name: "Bleu", color: "#2f7de1", num: 4, ai: true, skill: 0.965, lane: 14 },
    { code: "WIT", name: "Whitlock", color: "#f2f2f2", num: 22, ai: true, skill: 0.94, lane: 0 },
  ];
  const LEVELS = { easy: 0.9, medium: 0.975, hard: 1.0 };   // multiplies each AI driver's own skill
  const NITRO = { fill: 0.055, burn: 0.4, push: 380, cap: 1.28, start: 0.3 };   // per second; full tank ≈ 2.5 s of boost
  const BASE_SPEC = { acc: ACC, drag: 0.64, grip: 6.5, brake: 950, steer: 2.75, nitro: { push: NITRO.push, burn: NITRO.burn, fill: NITRO.fill, cap: NITRO.cap } };
  const MODES = ["circuit", "sprint", "elimination", "timetrial", "drift", "rival", "pursuit", "drag", "touge", "endurance", "delivery", "team"];
  // Rules for the newer modes live in racer-modes.js, which registers them here: HOOKS[mode] = { init, input, post, summary }.
  const HOOKS = {};
  const TIMES = ["day", "dawn", "dusk", "night"], WEATHERS = ["dry", "rain", "fog"];
  // How each personality drives. corner: cornering speed factor; brake: how far over target speed before braking;
  // pass/block: how strongly it moves to overtake / cover the car behind; nitro: when it fires; wobble: line errors.
  const PERSONA = {
    balanced: { corner: 1, brake: 45, pass: 0.6, block: 0.15, nitro: "straight", wobble: 0, contact: false },
    aggressive: { corner: 1.05, brake: 70, pass: 1, block: 0.3, nitro: "early", wobble: 0, contact: true },
    defensive: { corner: 0.99, brake: 45, pass: 0.35, block: 1, nitro: "straight", wobble: 0, contact: false },
    technical: { corner: 1.07, brake: 35, pass: 0.65, block: 0.2, nitro: "exit", wobble: 0, contact: false },
    opportunistic: { corner: 1, brake: 50, pass: 0.9, block: 0.1, nitro: "draft", wobble: 0, contact: false },
    beginner: { corner: 0.9, brake: 20, pass: 0.25, block: 0, nitro: "rare", wobble: 26, contact: false },
    ally: { corner: 1, brake: 45, pass: 0.3, block: 0, nitro: "straight", wobble: 0, contact: false },   // gives you room
  };

  function rng(seed) { let s = (seed >>> 0) % 2147483647 || 7; return () => (s = (s * 16807) % 2147483647) / 2147483647; }
  const specOf = (d) => {
    const s = d.spec || BASE_SPEC;
    return { acc: s.acc, drag: s.drag, grip: s.grip, brake: s.brake, steer: s.steer, nitro: { ...BASE_SPEC.nitro, ...(s.nitro || {}) },
      mass: s.mass || 1, turbo: s.turbo || 0, aero: s.aero || 0, slide: s.slide || 0, tyre: s.tyre || { dry: 1, wet: 1 }, offroad: s.offroad || 0, band: s.band || 0 };
  };

  // opts: { track, level, seed, ghost: {time, pts}, mode, laps, field: [driver], player: {driver}, weather, time,
  //         playerSlot } — a driver is { id, code, name, color, num, skill, personality, lane, spec, look, shape }.
  // pts is a flat [x, y, a, …] every GHOST_DT seconds. With no field, the classic Quick Race roster is used.
  function newRace(opts = {}) {
    const mode = MODES.includes(opts.mode) ? opts.mode : "circuit", H = HOOKS[mode] || {};
    const trk = track(H.track || opts.track), level = LEVELS[opts.level] ? opts.level : "medium", mult = LEVELS[level], rand = rng(opts.seed || 1);
    const laps = opts.laps > 0 ? Math.min(mode === "endurance" ? 20 : 9, opts.laps | 0) : mode === "sprint" || mode === "touge" ? 1 : mode === "endurance" ? 8 : LAPS;
    const solo = mode === "timetrial" || mode === "drift" || mode === "pursuit" || mode === "delivery";
    const field = solo ? [] : (opts.field || ROSTER.slice(1)).slice(0, H.maxField || 5);
    const n = 1 + field.length, slots = trk.slots(n);
    const ps = Number.isInteger(opts.playerSlot) ? clamp(opts.playerSlot, 0, n - 1) : n === 4 ? 2 : Math.min(n - 1, Math.floor(n / 2));
    const order = [ps, ...[...Array(n).keys()].filter((k) => k !== ps)];
    const drivers = [{ ...ROSTER[0], ...(opts.player || {}), ai: false }, ...field.map((d, k) => ({ lane: [-18, 14, 0, -26, 22][k % 5], ...d, ai: true }))];
    const cars = drivers.map((r, k) => {
      const s = slots[order[k]], spec = specOf(r), skill = r.ai ? (r.skill || 0.95) * mult : 1;
      return { ...r, id: r.id || r.code, persona: PERSONA[r.personality] || PERSONA.balanced, spec, skill, acc: spec.acc * skill,
        x: s.x, y: s.y, a: s.a, vx: 0, vy: 0, fwd: 0, slip: 0, on: true, idx: s.i, prog: s.i - trk.N, laps: 0, lapStart: 0,
        lapTimes: [], done: false, finish: 0, out: false, outAt: 0, wander: rand() * 6, nitro: NITRO.start, boost: false,
        aiBoost: false, laneCur: 0, side: 0, stuckT: 0, recoverT: 0, dmg: Math.max(0, Math.min(1, r.dmg || 0)), contacts: 0, brakeOn: false, steerIn: 0, latAcc: 0, spool: 0 };
    });
    const weather = WEATHERS.includes(opts.weather) ? opts.weather : "dry", tod = TIMES.includes(opts.time) ? opts.time : "day";
    const ru = opts.rules || {}, rules = { nitro: ru.nitro !== false, collisions: ru.collisions !== false, damage: ru.damage !== false };
    if (!rules.nitro) for (const c of cars) c.nitro = 0;
    const change = opts.weatherChange && WEATHERS.includes(opts.weatherChange.to) && opts.weatherChange.at > 0 ? { at: +opts.weatherChange.at, to: opts.weatherChange.to } : null;
    const race = { trk, track: trk.key, level, mode, laps, weather, tod, wet: weather === "rain", wetness: weather === "rain" ? 1 : 0, fogness: weather === "fog" ? 1 : 0, change, aiNitro: level !== "easy", cars, state: "lights",
      lightsT: 0, t: 0, simT: 0, wrongT: 0, events: [], skids: [], impacts: [], elimDone: 0, outCount: 0,
      ghost: opts.ghost && opts.ghost.pts && opts.ghost.pts.length ? opts.ghost : null, rec: [], recT: 0,
      drift: mode === "drift" ? { score: 0, cur: 0, chain: 0, grace: 0, mult: 1, best: 0 } : null,
      log: { overtakes: [], contacts: [], close: [] }, rank: null, pairT: {}, rules, H };
    if (H.init) H.init(race, opts, rand);
    return race;
  }

  function physics(race, c, inp, dt) {
    const sp = c.spec;
    let fx = Math.cos(c.a), fy = Math.sin(c.a);
    const sp0 = c.vx * fx + c.vy * fy;
    const sf = Math.min(1, Math.abs(sp0) / 150) * (1 - 0.42 * Math.min(1, Math.abs(sp0) / 700));
    c.a += inp.steer * sp.steer * (1 + 0.1 * (sp.slide || 0)) * sf * Math.sign(sp0 || 1) * dt;
    fx = Math.cos(c.a); fy = Math.sin(c.a);
    let fwd = c.vx * fx + c.vy * fy, lat = -c.vx * fy + c.vy * fx;
    const top = c.acc / sp.drag, n = sp.nitro;
    c.boost = !!inp.nitro && c.nitro > 0 && !!inp.thr && fwd > 0;
    if (c.boost) { c.nitro = Math.max(0, c.nitro - n.burn * dt); if (fwd < top * n.cap) fwd += n.push * dt; }
    else if (race.state === "race" && c.on && fwd > 200 && race.rules.nitro) c.nitro = Math.min(1, c.nitro + n.fill * dt);
    // a turbo builds boost over about half a second of throttle and loses it when you lift
    c.spool = Math.max(0, Math.min(1, c.spool + (inp.thr ? 2 : -3) * dt));
    // power band: a torquey engine (band < 0) pulls harder low down, a revvy one (band > 0) harder near the top;
    // the effect fades out approaching top speed, so top speed itself doesn't change
    const fr = Math.min(1, Math.max(0, fwd) / top), bandF = 1 + (sp.band || 0) * 0.3 * (fr - 0.5) * (fr < 0.85 ? 1 : Math.max(0, (1 - fr) / 0.15));
    if (inp.thr) fwd += c.acc * bandF * (c.accF === undefined ? 1 : c.accF) * (1 + sp.turbo * c.spool) * dt * (c.on ? 1 : 0.55 + 0.3 * sp.offroad);
    if (inp.brk) fwd -= (fwd > 15 ? sp.brake : 260) * dt;              // brake, then reverse
    fwd -= fwd * (c.on ? (c.boost ? sp.drag / 2 : sp.drag) * (1 + 0.04 * c.dmg) : 2.3 * (1 - 0.5 * sp.offroad)) * dt;   // drag; damage costs ≤4%
    if (!inp.thr && !inp.brk) fwd -= Math.sign(fwd) * Math.min(Math.abs(fwd), 70 * dt);
    fwd = Math.max(fwd, -160);
    // Tyre grip pulls the sideways speed back to zero, but only up to a cornering-force limit (grip × 90 units/s²):
    // too fast into a bend and the car slides wide. Rain takes a quarter of the grip.
    // Tyre compound (dry/wet grip), downforce (more grip as speed builds) and a loose diff (slides more) adjust it.
    const tyreF = sp.tyre.dry * (1 - race.wetness) + sp.tyre.wet * race.wetness, aeroF = 1 + 0.1 * sp.aero * Math.min(1, Math.abs(fwd) / 650);
    // a loose diff lets slides last longer (slower to straighten up) without throwing the car off the road
    const gripE = sp.grip * tyreF * aeroF * (1 - 0.3 * (c.wear || 0));   // worn tyres (endurance) lose up to 30%
    const lat0 = lat, wetF = 1 - 0.26 * race.wetness, damp = lat * (1 - Math.exp(-(c.on ? gripE * (1 - 0.3 * sp.slide) : 3) * wetF * dt));
    const lim = (c.on ? gripE * LATG * (1 - 0.06 * sp.slide) : 180) * wetF * dt;
    lat -= Math.abs(damp) > lim ? Math.sign(damp) * lim : damp;
    c.vx = fx * fwd - fy * lat; c.vy = fy * fwd + fx * lat;
    const t = race.trk;
    c.x = Math.max(t.OX + 20, Math.min(t.OX + t.WW - 20, c.x + c.vx * dt));
    c.y = Math.max(t.OY + 20, Math.min(t.OY + t.WH - 20, c.y + c.vy * dt));
    c.fwd = fwd; c.slip = Math.abs(lat); c.brakeOn = !!inp.brk && fwd > 15; c.steerIn = inp.steer || 0; c.thr = !!inp.thr;
    c.latAcc = c.latAcc * 0.9 + (lat0 - lat) * 0.1;
  }

  // An AI driver aims at a point ahead on its own line, brakes for the sharpest bend in the next ~500 units, moves
  // over to pass the car ahead or cover the one behind (by personality), uses nitro by personality (never on Easy),
  // and reverses out when it's stuck or facing the wrong way. It sees only what a driver could: positions and speeds.
  function aiInput(race, c) {
    const t = race.trk, P = c.persona || PERSONA.balanced, sp = Math.max(0, c.fwd || 0), N = t.N;
    let ahead = null, gapA = 1e9, behind = null, gapB = 1e9;
    for (const o of race.cars) {
      if (o === c || o.out) continue;
      const d = o.prog - c.prog;
      if (d > 0 && d < 14 && d < gapA) { ahead = o; gapA = d; }
      if (d < 0 && d > -10 && -d < gapB) { behind = o; gapB = -d; }
    }
    let lane = (c.lane || 0) + Math.sin(race.simT * 0.35 + (c.wander || 0)) * 16 + (P.wobble ? Math.sin(race.simT * 1.3 + (c.wander || 0) * 2) * P.wobble : 0);
    let lift = false;
    const room = TW / 2 - 24;
    if (ahead && P.pass > 0 && (ahead.fwd || 0) < sp + 60) {
      const oL = latOff(t, ahead);
      if (!c.side) c.side = oL > latOff(t, c) ? -1 : 1;
      lane = lane * (1 - P.pass) + clamp(oL + c.side * 46, -room, room) * P.pass;
      if (!P.contact && gapA < 4 && Math.abs(latOff(t, c) - oL) < 26 && sp > (ahead.fwd || 0)) lift = true;   // don't ram
    } else {
      c.side = 0;
      if (behind && P.block > 0 && gapB < 8) lane = lane * (1 - P.block * 0.7) + latOff(t, behind) * P.block * 0.7;
    }
    c.laneCur = (c.laneCur || 0) + (clamp(lane, -room, room) - (c.laneCur || 0)) * 0.03;
    const ti = (c.idx + Math.round(7 + sp / 45)) % N, [nx, ny] = t.nrm(ti);
    const diff = wrapA(Math.atan2(t.P[ti][1] + ny * c.laneCur - c.y, t.P[ti][0] + nx * c.laneCur - c.x) - c.a);
    // stuck or pointing the wrong way: back out, turning the nose toward the road
    if (race.state === "race") { c.stuckT = Math.abs(c.fwd || 0) < 35 || (Math.abs(diff) > 2.2 && sp < 120) ? (c.stuckT || 0) + 1 / 120 : 0; }
    if (c.stuckT > 1.2) { c.recoverT = 0.9; c.stuckT = 0; }
    if (c.recoverT > 0) { c.recoverT -= 1 / 120; return { steer: -clamp(diff * 3, -1, 1), thr: false, brk: true, nitro: false }; }
    // Corner speed: the lower of what the steering can follow (authority falls with speed) and what the tyres can hold
    // (cornering-force limit, less in the wet), with a margin; then the speed it can still brake down from in time.
    const S = c.spec, ty = S.tyre ? S.tyre.dry * (1 - race.wetness) + S.tyre.wet * race.wetness : 1;
    const wetF = 1 - 0.26 * race.wetness, top = c.acc * (1 + (S.turbo || 0)) / S.drag, auth = S.steer * 0.9 * P.corner, B = S.brake * 0.5 * (1 - 0.2 * race.wetness);
    const aLat = S.grip * ty * (1 + 0.05 * (S.aero || 0)) * (1 - 0.06 * (S.slide || 0)) * LATG * wetF * 0.85 * P.corner;
    let target = top * 0.99;
    for (let k = 2; k <= 72; k += 3) {
      const kap = t.K[(c.idx + k) % N] + 1e-6, vmax = Math.min(auth / (kap + 0.42 * auth / 700), Math.sqrt(aLat / kap)), allow = Math.sqrt(vmax * vmax + 2 * B * k * SP);
      if (allow < target) target = allow;
    }
    target = Math.max(200, target);
    let straight = 0;
    for (let k = 4; k <= 64; k += 6) straight = Math.max(straight, Math.abs(wrapA(t.ANG[(c.idx + k) % N] - t.ANG[c.idx])));
    const want = { straight: straight < 0.18 && c.nitro > 0.45 && sp > 300, early: straight < 0.3 && c.nitro > 0.3 && sp > 260,
      exit: straight < 0.22 && c.nitro > 0.35 && sp > 250 && sp < target - 20, draft: (ahead && gapA < 9 && straight < 0.35 && c.nitro > 0.2) || (straight < 0.15 && c.nitro > 0.7),
      rare: straight < 0.12 && c.nitro > 0.9 }[P.nitro];
    if (c.aiBoost) c.aiBoost = straight < 0.3 && c.nitro > 0.02;
    else c.aiBoost = race.aiNitro && !!want;
    return { steer: clamp(diff * 3, -1, 1), thr: (sp < target || c.aiBoost) && !lift, brk: !c.aiBoost && sp > target + P.brake, nitro: c.aiBoost };
  }

  function collide(race) {
    const cars = race.cars;
    for (let i = 0; i < cars.length; i++) for (let j = i + 1; j < cars.length; j++) {
      const a = cars[i], b = cars[j];
      if (a.out || b.out) continue;
      const dx = b.x - a.x, dy = b.y - a.y, d = Math.hypot(dx, dy);
      if (d > 0 && d < 2 * RAD) {
        const nx = dx / d, ny = dy / d, o = (2 * RAD - d) / 2, ma = a.spec.mass || 1, mb = b.spec.mass || 1, fa = 2 * mb / (ma + mb), fb = 2 * ma / (ma + mb);
        a.x -= nx * o * fa; a.y -= ny * o * fa; b.x += nx * o * fb; b.y += ny * o * fb;   // the heavier car moves less
        const rv = (b.vx - a.vx) * nx + (b.vy - a.vy) * ny;
        if (rv < 0) {
          const jx = -0.65 * rv * nx, jy = -0.65 * rv * ny; a.vx -= jx * fa; a.vy -= jy * fa; b.vx += jx * fb; b.vy += jy * fb;
          const v = -rv;
          if (v > 30) {
            a.dmg = Math.min(1, a.dmg + v / 2600); b.dmg = Math.min(1, b.dmg + v / 2600); a.contacts++; b.contacts++;
            if (race.impacts.length < 40) race.impacts.push({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2, v, you: !a.ai || !b.ai });
            // who hit whom: the car moving faster toward the other one
            const by = (a.vx * nx + a.vy * ny) >= -(b.vx * nx + b.vy * ny) ? a : b;
            if (race.log && race.log.contacts.length < 300) race.log.contacts.push({ t: race.t, a: a.id, b: b.id, by: by.id, v: Math.round(v) });
          }
        }
      }
    }
  }

  // Classification: finishers by time, then running cars by progress, then eliminated cars (last out ranks lowest).
  function standings(race) {
    return race.cars.filter((c) => !c.police && !c.parked).sort((a, b) => {
      if (a.out || b.out) return a.out && b.out ? b.outAt - a.outAt : a.out ? 1 : -1;
      return (a.done && b.done) ? a.finish - b.finish : a.done ? -1 : b.done ? 1 : b.prog - a.prog;
    });
  }

  // Where the ghost is now: it replays your best flying lap from the moment you start each lap after the first.
  function ghostPose(race) {
    const me = race.cars[0], g = race.ghost;
    if (!g || me.laps < 1 || me.done || race.state !== "race") return null;
    const f = (race.t - me.lapStart) / GHOST_DT, i = Math.floor(f), n = g.pts.length / 3;
    if (i >= n - 1) return null;
    const k = f - i, p = g.pts;
    return [p[i * 3] + (p[i * 3 + 3] - p[i * 3]) * k, p[i * 3 + 1] + (p[i * 3 + 4] - p[i * 3 + 1]) * k, p[i * 3 + 2] + wrapA(p[i * 3 + 5] - p[i * 3 + 2]) * k];
  }

  // Drift scoring: a slide (on the tarmac, fast, sideways) earns points; keep sliding and the multiplier climbs (×5
  // max). A pause under 0.7 s keeps the chain; the chain banks when it ends. Grass or contact loses the unbanked chain.
  function driftStep(race, c, dt, hit) {
    const D = race.drift;
    if (!c.on || hit) { if (D.cur > 0) race.events.push({ type: "drift-lost", pts: Math.round(D.cur * D.mult) }); D.cur = 0; D.chain = 0; D.mult = 1; D.grace = 0; return; }
    if (c.fwd > 200 && c.slip > 70) {
      D.cur += (c.slip - 60) * (c.fwd / 300) * 4 * dt; D.chain += dt; D.grace = 0.7;
      D.mult = Math.min(5, 1 + Math.floor(D.chain / 1.5));
    } else if (D.cur > 0) {
      D.grace -= dt;
      if (D.grace <= 0) bankDrift(race);
    }
  }
  function bankDrift(race) {
    const D = race.drift; if (!D || D.cur <= 0) return;
    const pts = Math.round(D.cur * D.mult); D.score += pts; D.best = Math.max(D.best, pts);
    race.events.push({ type: "drift-bank", pts, mult: D.mult }); D.cur = 0; D.chain = 0; D.mult = 1;
  }

  function eliminate(race) {
    const running = standings(race).filter((c) => !c.out && !c.done);
    if (running.length < 2) return;
    const last = running[running.length - 1];
    last.out = true; last.outAt = race.t; race.outCount++;
    race.events.push({ type: "eliminated", code: last.code, you: !last.ai });
    if (!last.ai) { race.state = "done"; last.finish = race.t; }
    else if (running.length === 2 && !running[0].ai) {   // you're the last one standing
      const me = running[0]; me.done = true; me.finish = race.t; race.state = "done";
      race.events.push({ type: "finish", lap: me.laps, time: race.t - me.lapStart, ghost: null });
    }
  }

  // One fixed step. `you` is the player's input {steer -1..1, thr, brk, nitro}; pass null to let the AI drive your car.
  // Laps count from continuous progress along the centreline, so driving backwards over the line never scores one.
  function step(race, dt, you) {
    const t = race.trk;
    race.simT += dt;
    if (race.state === "lights") {
      race.lightsT += dt;
      if (race.lightsT > 4.1) { race.state = "race"; race.events.push({ type: "go" }); }
    }
    const moving = race.state !== "lights";
    if (moving && race.cars.some((c) => !c.done && !c.out)) race.t += dt;   // runs until every car is home
    // weather that changes during the race: rain arrives (or clears, or fog rolls in) over about 20 seconds
    if (race.change && race.t >= race.change.at) {
      const to = race.change.to, k = dt / 20;
      race.wetness = Math.max(0, Math.min(1, race.wetness + (to === "rain" ? k : -k)));
      race.fogness = Math.max(0, Math.min(1, race.fogness + (to === "fog" ? k : -k)));
      race.wet = race.wetness > 0.5;
      const settled = (to === "rain" ? race.wetness === 1 : race.wetness === 0) && (to === "fog" ? race.fogness === 1 : race.fogness === 0);
      if (!race.changeSaid) { race.changeSaid = true; race.events.push({ type: "weather", to }); }
      if (settled) { race.weather = to; race.change = null; }
    }
    for (const c of race.cars) {
      let inp = { steer: 0, thr: false, brk: false, nitro: false };
      if (c.out) inp = { steer: 0, thr: false, brk: c.fwd > 0, nitro: false };
      else if (moving) {
        if (c.done && !c.ai) inp = { steer: aiInput(race, { ...c, skill: 0.6, lane: 0, persona: PERSONA.balanced }).steer, thr: c.fwd < 200, brk: false, nitro: false };  // cool-down lap
        else if (c.ai || !you) inp = aiInput(race, c);
        else inp = you;
      }
      if (race.H.input) inp = race.H.input(race, c, inp, you) || inp;
      if (c.parked) { c.vx = c.vy = c.fwd = 0; continue; }
      physics(race, c, inp, dt);
    }
    const before = race.cars[0].contacts, dmg0 = race.rules.damage ? null : race.cars.map((c) => c.dmg);
    if (race.rules.collisions) collide(race);
    if (dmg0) race.cars.forEach((c, k) => { c.dmg = dmg0[k]; });
    const me = race.cars[0];
    if (race.state === "race" && !me.done && !me.out) {           // record this lap for the ghost
      race.recT += dt;
      while (race.recT >= GHOST_DT) { race.recT -= GHOST_DT; race.rec.push(Math.round(me.x), Math.round(me.y), Math.round(me.a * 100) / 100); }
    }
    let leadLaps = 0;
    for (const c of race.cars) {
      let [ni, dist] = nearest(t, c.x, c.y, c.idx);
      if (dist > TW * 1.5) [ni, dist] = nearest(t, c.x, c.y, -1);   // far off the road: find where it really is
      c.on = dist < TW / 2 + 11;
      // beyond the gravel for 3 s (or pinned at the edge of the world): put the car back on the road, stopped
      c.offT = moving && !c.out && dist > TW / 2 + 90 ? (c.offT || 0) + dt : 0;
      if (c.offT > 3) {
        const [nx, ny] = t.nrm(ni); c.x = t.P[ni][0] + nx * (c.lane || 0) * 0.5; c.y = t.P[ni][1] + ny * (c.lane || 0) * 0.5;
        c.a = t.ANG[ni]; c.vx = c.vy = c.fwd = 0; c.offT = 0; c.recoverT = 0; c.stuckT = 0; dist = 0; c.on = true;
        race.events.push({ type: "reset", code: c.code, you: !c.ai });
      }
      let d = ni - c.idx; if (d > t.N / 2) d -= t.N; if (d < -t.N / 2) d += t.N;
      c.prog += d; c.idx = ni;
      const lapsNow = Math.max(0, Math.floor(c.prog / t.N));
      if (moving && !c.done && !c.out && lapsNow > c.laps) {
        c.laps = lapsNow; c.lapTimes.push(race.t - c.lapStart); c.lapStart = race.t;
        if (c.laps >= race.laps) {
          c.done = true; c.finish = race.t;
          const prev = race.cars.filter((o) => o !== c && o.done && !o.out).sort((x, y) => y.finish - x.finish)[0];
          if (prev && c.finish - prev.finish < 0.3) { race.log.close.push({ a: prev.id, b: c.id, gap: c.finish - prev.finish }); race.events.push({ type: "close-finish", a: prev.id, b: c.id, gap: c.finish - prev.finish }); }
        }
        if (!c.ai) {
          const time = c.lapTimes[c.lapTimes.length - 1], flying = c.laps >= 2;   // lap 1 starts from the grid
          const ghost = flying ? { time, pts: race.rec } : null;
          if (ghost && (!race.ghost || time < race.ghost.time)) race.ghost = ghost;   // race your new best from now on
          if (c.done && race.drift) bankDrift(race);
          race.events.push({ type: c.done ? "finish" : "lap", lap: c.laps, time, ghost });
          race.rec = []; race.recT = 0;
          if (c.done) race.state = "done";
        }
      }
      if (!c.out) leadLaps = Math.max(leadLaps, c.laps);
      if (!c.ai) {
        const along = c.vx * Math.cos(t.ANG[c.idx]) + c.vy * Math.sin(t.ANG[c.idx]);
        race.wrongT = race.state === "race" && along < -40 ? race.wrongT + dt : 0;
      }
      if (c.on && c.slip > 110 && race.skids.length < 400) race.skids.push([c.x, c.y, c.a]);
    }
    if (race.mode === "elimination" && race.state === "race" && leadLaps > race.elimDone && leadLaps < race.laps) {
      race.elimDone = leadLaps; eliminate(race);
    }
    if (race.drift && race.state === "race") driftStep(race, me, dt, me.contacts > before);
    if (race.state === "race" && race.t > 2) trackOvertakes(race);
    if (race.H.post) race.H.post(race, dt);
  }

  // Overtakes: a pair of running cars swapping order. A swap back within 1.5 s doesn't count (side by side).
  function trackOvertakes(race) {
    const run = race.cars.filter((c) => !c.out && !c.done && !c.police && !c.parked).sort((a, b) => b.prog - a.prog);
    const rank = {}; run.forEach((c, i) => { rank[c.id] = i; });
    const prev = race.rank; race.rank = rank;
    if (!prev) return;
    for (const x of run) for (const y of run) {
      if (x === y || prev[x.id] === undefined || prev[y.id] === undefined) continue;
      if (prev[x.id] > prev[y.id] && rank[x.id] < rank[y.id]) {
        const key = x.id < y.id ? x.id + "|" + y.id : y.id + "|" + x.id;
        if (race.t - (race.pairT[key] || -9) < 1.5) { race.pairT[key] = race.t; continue; }
        race.pairT[key] = race.t;
        if (race.log.overtakes.length < 400) race.log.overtakes.push({ t: race.t, by: x.id, on: y.id, lap: x.laps });
        race.events.push({ type: "overtake", by: x.id, on: y.id, you: !x.ai || !y.ai, gain: !x.ai });
      }
    }
  }

  // What the career needs to know about a finished (or abandoned) race.
  function summary(race) {
    const me = race.cars[0], order = standings(race), place = order.indexOf(me) + 1;
    const out = { mode: race.mode, track: race.track, laps: race.laps, level: race.level, weather: race.weather, tod: race.tod,
      place, of: race.cars.length, finished: me.done, eliminated: me.out, total: me.done ? me.finish : 0,
      best: me.lapTimes.length ? Math.min(...me.lapTimes) : 0, lapTimes: me.lapTimes.slice(), drift: race.drift ? race.drift.score : 0,
      contacts: me.contacts, damage: me.dmg, order: order.map((c) => c.id), beat: order.slice(place).map((c) => c.id), rivals: rivalLog(race) };
    if (race.H.summary) race.H.summary(race, out);
    return out;
  }
  // What happened between you and each other car this race: passes both ways, contacts (and who caused them),
  // the gap at the flag, and whether it was a photo finish.
  function rivalLog(race) {
    const me = race.cars[0], out = {};
    for (const c of race.cars.slice(1)) {
      if (c.police || c.parked) continue;
      const L = race.log, o = { passedThem: 0, passedYou: 0, contacts: 0, youHit: 0, theyHit: 0, gap: null, close: false };
      for (const e of L.overtakes) { if (e.by === me.id && e.on === c.id) o.passedThem++; if (e.by === c.id && e.on === me.id) o.passedYou++; }
      for (const e of L.contacts) if ((e.a === me.id && e.b === c.id) || (e.a === c.id && e.b === me.id)) { o.contacts++; if (e.by === me.id) o.youHit++; else o.theyHit++; }
      if (me.done && c.done) o.gap = +(c.finish - me.finish).toFixed(3);
      o.close = L.close.some((e) => (e.a === me.id && e.b === c.id) || (e.a === c.id && e.b === me.id)) || (o.gap !== null && Math.abs(o.gap) < 0.5);
      out[c.id] = o;
    }
    return out;
  }

  const fmt = (s) => {
    if (!isFinite(s) || s <= 0) return "–:––.–––";
    const m = Math.floor(s / 60), r = s - m * 60;
    return m + ":" + (r < 10 ? "0" : "") + r.toFixed(3);
  };

  const api = { TRACKS, LAPS, TW, SP, RAD, LEVELS, ROSTER, NITRO, GHOST_DT, PERSONA, MODES, TIMES, WEATHERS, BASE_SPEC, HOOKS,
    track, nearest, newRace, step, standings, aiInput, ghostPose, summary, fmt, latOff, clamp, wrapA, rng, specOf };

  if (typeof module !== "undefined" && module.exports) { module.exports = api; require("./racer-modes.js"); }
  else root.JarvisRacer = api;
})(typeof self !== "undefined" ? self : globalThis);
