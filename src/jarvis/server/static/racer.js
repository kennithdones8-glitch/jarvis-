"use strict";
// Kerbside Grand Prix: a top-down, three-lap race against JARVIS and two other cars, on three circuits, with nitro
// and a ghost of your best lap. Tracks, physics and the AI drivers are written for JARVIS: no library, no model, no
// network. The simulation (newRace/step) is plain data and runs in Node for the tests; mount() adds the canvas, HUD
// and controls (the Games page, or the standalone page in the zip). Best times and ghosts stay in this browser.
(function (root) {
  const TW = 150, SP = 12, LAPS = 3, RAD = 17, ACC = 430, GHOST_DT = 0.05;

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
  };
  const cr = (a, b, c, d, t) => { const t2 = t * t, t3 = t2 * t; return 0.5 * (2 * b + (-a + c) * t + (2 * a - 5 * b + 4 * c - d) * t2 + (-a + 3 * b - 3 * c + d) * t3); };
  const wrapA = (a) => { while (a > Math.PI) a -= 2 * Math.PI; while (a < -Math.PI) a += 2 * Math.PI; return a; };
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
      WW: Math.ceil(maxX - minX + 2 * M), WH: Math.ceil(maxY - minY + 2 * M) };
    t.nrm = (i) => { const a = ANG[((i % N) + N) % N]; return [-Math.sin(a), Math.cos(a)]; };
    t.grid = [0, 1, 2, 3].map((k) => {
      const i = (N - 5 - k * 5) % N, [nx, ny] = t.nrm(i), side = k % 2 ? 1 : -1;
      return { i, x: P[i][0] + nx * side * 34, y: P[i][1] + ny * side * 34, a: ANG[i] };
    });
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

  // ---------------------------------------------------------------- Cars and levels
  const ROSTER = [
    { code: "YOU", name: "You", color: "#e9c44a", num: 7, ai: false, skill: 1, lane: 0 },
    { code: "JRV", name: "JARVIS", color: "#d23c3c", num: 1, ai: true, skill: 0.985, lane: -18 },
    { code: "BLU", name: "Bleu", color: "#2f7de1", num: 4, ai: true, skill: 0.965, lane: 14 },
    { code: "WIT", name: "Whitlock", color: "#f2f2f2", num: 22, ai: true, skill: 0.94, lane: 0 },
  ];
  const LEVELS = { easy: 0.9, medium: 0.975, hard: 1.0 };   // multiplies each AI driver's own skill
  const NITRO = { fill: 0.055, burn: 0.4, push: 380, cap: 1.28, start: 0.3 };   // per second; full tank ≈ 2.5 s of boost

  function rng(seed) { let s = (seed >>> 0) % 2147483647 || 7; return () => (s = (s * 16807) % 2147483647) / 2147483647; }

  // opts: { track, level, seed, ghost: {time, pts} } — pts is a flat [x, y, a, x, y, a, …] every GHOST_DT seconds.
  function newRace(opts = {}) {
    const trk = track(opts.track), level = LEVELS[opts.level] ? opts.level : "medium", mult = LEVELS[level], rand = rng(opts.seed || 1);
    const order = [2, 0, 1, 3];   // you start third
    const cars = ROSTER.map((r, k) => {
      const s = trk.grid[order[k]], skill = r.ai ? r.skill * mult : 1;
      return { ...r, skill, acc: ACC * skill, x: s.x, y: s.y, a: s.a, vx: 0, vy: 0, fwd: 0, slip: 0, on: true,
        idx: s.i, prog: s.i - trk.N, laps: 0, lapStart: 0, lapTimes: [], done: false, finish: 0, wander: rand() * 6,
        nitro: NITRO.start, boost: false, aiBoost: false };
    });
    return { trk, track: trk.key, level, aiNitro: level !== "easy", cars, state: "lights", lightsT: 0, t: 0, simT: 0,
      wrongT: 0, events: [], skids: [], ghost: opts.ghost && opts.ghost.pts && opts.ghost.pts.length ? opts.ghost : null,
      rec: [], recT: 0 };
  }

  function physics(race, c, inp, dt) {
    let fx = Math.cos(c.a), fy = Math.sin(c.a);
    const sp0 = c.vx * fx + c.vy * fy;
    const sf = Math.min(1, Math.abs(sp0) / 150) * (1 - 0.42 * Math.min(1, Math.abs(sp0) / 700));
    c.a += inp.steer * 2.75 * sf * Math.sign(sp0 || 1) * dt;
    fx = Math.cos(c.a); fy = Math.sin(c.a);
    let fwd = c.vx * fx + c.vy * fy, lat = -c.vx * fy + c.vy * fx;
    const top = c.acc / 0.64;
    c.boost = !!inp.nitro && c.nitro > 0 && !!inp.thr && fwd > 0;
    if (c.boost) { c.nitro = Math.max(0, c.nitro - NITRO.burn * dt); if (fwd < top * NITRO.cap) fwd += NITRO.push * dt; }
    else if (race.state === "race" && c.on && fwd > 200) c.nitro = Math.min(1, c.nitro + NITRO.fill * dt);
    if (inp.thr) fwd += c.acc * dt * (c.on ? 1 : 0.55);
    if (inp.brk) fwd -= (fwd > 15 ? 950 : 260) * dt;              // brake, then reverse
    fwd -= fwd * (c.on ? (c.boost ? 0.32 : 0.64) : 2.3) * dt;        // drag; grass and gravel are slow
    if (!inp.thr && !inp.brk) fwd -= Math.sign(fwd) * Math.min(Math.abs(fwd), 70 * dt);
    fwd = Math.max(fwd, -160);
    lat *= Math.exp(-(c.on ? 6.5 : 3) * dt);                         // tyre grip
    c.vx = fx * fwd - fy * lat; c.vy = fy * fwd + fx * lat;
    const t = race.trk;
    c.x = Math.max(t.OX + 20, Math.min(t.OX + t.WW - 20, c.x + c.vx * dt));
    c.y = Math.max(t.OY + 20, Math.min(t.OY + t.WH - 20, c.y + c.vy * dt));
    c.fwd = fwd; c.slip = Math.abs(lat);
  }

  // An AI driver aims at a point ahead on its own line, brakes for the sharpest bend in the next ~500 units, and
  // (above Easy) uses nitro when the road ahead is straight.
  function aiInput(race, c) {
    const t = race.trk, sp = Math.max(0, c.fwd || 0);
    const ti = (c.idx + Math.round(7 + sp / 45)) % t.N, [nx, ny] = t.nrm(ti);
    const lane = c.lane + Math.sin(race.simT * 0.35 + c.wander) * 16;
    const diff = wrapA(Math.atan2(t.P[ti][1] + ny * lane - c.y, t.P[ti][0] + nx * lane - c.x) - c.a);
    let turn = 0;
    for (let k = 4; k <= 44; k += 4) turn = Math.max(turn, Math.abs(wrapA(t.ANG[(c.idx + k) % t.N] - t.ANG[c.idx])));
    const target = Math.max(235, 665 * c.skill - Math.min(turn, 1.6) * 300);
    let straight = 0;
    for (let k = 4; k <= 64; k += 6) straight = Math.max(straight, Math.abs(wrapA(t.ANG[(c.idx + k) % t.N] - t.ANG[c.idx])));
    if (c.aiBoost) c.aiBoost = straight < 0.3 && c.nitro > 0.02;
    else c.aiBoost = race.aiNitro && straight < 0.18 && c.nitro > 0.45 && sp > 300;
    return { steer: Math.max(-1, Math.min(1, diff * 3)), thr: sp < target || c.aiBoost, brk: !c.aiBoost && sp > target + 45, nitro: c.aiBoost };
  }

  function collide(cars) {
    for (let i = 0; i < cars.length; i++) for (let j = i + 1; j < cars.length; j++) {
      const a = cars[i], b = cars[j], dx = b.x - a.x, dy = b.y - a.y, d = Math.hypot(dx, dy);
      if (d > 0 && d < 2 * RAD) {
        const nx = dx / d, ny = dy / d, o = (2 * RAD - d) / 2;
        a.x -= nx * o; a.y -= ny * o; b.x += nx * o; b.y += ny * o;
        const rv = (b.vx - a.vx) * nx + (b.vy - a.vy) * ny;
        if (rv < 0) { const jx = -0.65 * rv * nx, jy = -0.65 * rv * ny; a.vx -= jx; a.vy -= jy; b.vx += jx; b.vy += jy; }
      }
    }
  }

  function standings(race) {
    return [...race.cars].sort((a, b) => (a.done && b.done) ? a.finish - b.finish : a.done ? -1 : b.done ? 1 : b.prog - a.prog);
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
    if (moving && race.cars.some((c) => !c.done)) race.t += dt;   // runs until every car is home
    for (const c of race.cars) {
      let inp = { steer: 0, thr: false, brk: false, nitro: false };
      if (moving) {
        if (c.done && !c.ai) inp = { steer: aiInput(race, { ...c, skill: 0.6, lane: 0 }).steer, thr: c.fwd < 200, brk: false, nitro: false };  // cool-down lap
        else if (c.ai || !you) inp = aiInput(race, c);
        else inp = you;
      }
      physics(race, c, inp, dt);
    }
    collide(race.cars);
    const me = race.cars[0];
    if (race.state === "race" && !me.done) {           // record this lap for the ghost
      race.recT += dt;
      while (race.recT >= GHOST_DT) { race.recT -= GHOST_DT; race.rec.push(Math.round(me.x), Math.round(me.y), Math.round(me.a * 100) / 100); }
    }
    for (const c of race.cars) {
      const [ni, dist] = nearest(t, c.x, c.y, c.idx);
      c.on = dist < TW / 2 + 11;
      let d = ni - c.idx; if (d > t.N / 2) d -= t.N; if (d < -t.N / 2) d += t.N;
      c.prog += d; c.idx = ni;
      const lapsNow = Math.max(0, Math.floor(c.prog / t.N));
      if (moving && !c.done && lapsNow > c.laps) {
        c.laps = lapsNow; c.lapTimes.push(race.t - c.lapStart); c.lapStart = race.t;
        if (c.laps >= LAPS) { c.done = true; c.finish = race.t; }
        if (!c.ai) {
          const time = c.lapTimes[c.lapTimes.length - 1], flying = c.laps >= 2;   // lap 1 starts from the grid
          const ghost = flying ? { time, pts: race.rec } : null;
          if (ghost && (!race.ghost || time < race.ghost.time)) race.ghost = ghost;   // race your new best from now on
          race.events.push({ type: c.done ? "finish" : "lap", lap: c.laps, time, ghost });
          race.rec = []; race.recT = 0;
          if (c.done) race.state = "done";
        }
      }
      if (!c.ai) {
        const along = c.vx * Math.cos(t.ANG[c.idx]) + c.vy * Math.sin(t.ANG[c.idx]);
        race.wrongT = race.state === "race" && along < -40 ? race.wrongT + dt : 0;
      }
      if (c.on && c.slip > 110 && race.skids.length < 400) race.skids.push([c.x, c.y, c.a]);
    }
  }

  const fmt = (s) => {
    if (!isFinite(s) || s <= 0) return "–:––.–––";
    const m = Math.floor(s / 60), r = s - m * 60;
    return m + ":" + (r < 10 ? "0" : "") + r.toFixed(3);
  };

  const api = { TRACKS, LAPS, TW, SP, LEVELS, ROSTER, NITRO, GHOST_DT, track, nearest, newRace, step, standings, aiInput, ghostPose, fmt };

  // ---------------------------------------------------------------- The page: canvas, HUD, touch pads
  if (root.document) {
    const STORE = "jarvis-racer-v2";
    const blank = () => ({ track: "kerbside", level: "medium", ghostOn: true, best: {}, race: {}, wins: 0, ghosts: {} });
    const store = {
      get() { try { return Object.assign(blank(), JSON.parse(root.localStorage.getItem(STORE) || "{}")); } catch { return blank(); } },
      set(v) { try { root.localStorage.setItem(STORE, JSON.stringify(v)); } catch { /* private window: this visit only */ } },
    };
    const el = (tag, cls, ...kids) => {
      const e = root.document.createElement(tag);
      if (cls) e.className = cls;
      for (const k of kids) if (k !== null && k !== undefined) e.append(k instanceof root.Node ? k : String(k));
      return e;
    };
    const KEYS = { ArrowUp: "up", KeyW: "up", ArrowDown: "down", KeyS: "down", ArrowLeft: "left", KeyA: "left",
      ArrowRight: "right", KeyD: "right", Space: "nitro", ShiftLeft: "nitro", ShiftRight: "nitro" };
    let G = null;   // the one mounted game

    const DECOR = {
      park: { ground: "#2f6e38", stripe: "#2a6533", blob: ["#1f5228", "#2b6a34"] },
      water: { ground: "#2f6e38", stripe: "#2a6533", blob: ["#1f5228", "#2b6a34"], sea: "#1d5f86", wave: "#2a74a0" },
      rock: { ground: "#5b6b3a", stripe: "#56653a", blob: ["#6f6a60", "#8a857a"] },
    };
    function paintTrack(t) {
      const D = DECOR[t.decor] || DECOR.park, cv = root.document.createElement("canvas"); cv.width = t.WW; cv.height = t.WH;
      const g = cv.getContext("2d"), P = t.P, rand = rng(t.key.length * 97 + 7);
      g.translate(-t.OX, -t.OY);
      const path = () => { g.beginPath(); P.forEach(([x, y], i) => (i ? g.lineTo(x, y) : g.moveTo(x, y))); g.closePath(); };
      g.lineJoin = "round"; g.lineCap = "round";
      if (D.sea) {   // the harbour: water everywhere, a sandy edge and a grass verge along the road
        g.fillStyle = D.sea; g.fillRect(t.OX, t.OY, t.WW, t.WH);
        g.strokeStyle = D.wave; g.lineWidth = 3;
        for (let i = 0; i < 120; i++) { const x = t.OX + rand() * t.WW, y = t.OY + rand() * t.WH; g.beginPath(); g.moveTo(x, y); g.quadraticCurveTo(x + 14, y - 8, x + 28, y); g.stroke(); }
        path(); g.strokeStyle = "#d9cc9f"; g.lineWidth = TW + 330; g.stroke();
        path(); g.strokeStyle = D.ground; g.lineWidth = TW + 290; g.stroke();
      } else {
        g.fillStyle = D.ground; g.fillRect(t.OX, t.OY, t.WW, t.WH);
        g.fillStyle = D.stripe;
        for (let s = -t.WH; s < t.WW + t.WH; s += 120) { g.beginPath(); g.moveTo(t.OX + s, t.OY); g.lineTo(t.OX + s + 60, t.OY); g.lineTo(t.OX + s + 60 - t.WH, t.OY + t.WH); g.lineTo(t.OX + s - t.WH, t.OY + t.WH); g.fill(); }
      }
      path(); g.strokeStyle = "#cbb98c"; g.lineWidth = TW + 90; g.stroke();     // gravel run-off
      path(); g.strokeStyle = "#f2f0ea"; g.lineWidth = TW + 22; g.stroke();     // kerbs
      path(); g.strokeStyle = "#d3372b"; g.setLineDash([22, 22]); g.stroke(); g.setLineDash([]);
      path(); g.strokeStyle = "#474c55"; g.lineWidth = TW; g.stroke();          // tarmac
      path(); g.strokeStyle = "rgba(255,255,255,0.10)"; g.lineWidth = 3; g.setLineDash([30, 40]); g.stroke(); g.setLineDash([]);
      g.save(); g.translate(P[0][0], P[0][1]); g.rotate(t.ANG[0]);
      for (let r = 0; r < 2; r++) for (let c = 0; c < Math.ceil(TW / 10); c++) { g.fillStyle = (r + c) % 2 ? "#111" : "#fafafa"; g.fillRect(-10 + r * 10, -TW / 2 + c * 10, 10, 10); }
      g.restore();
      for (const s of t.grid) {
        g.save(); g.translate(s.x, s.y); g.rotate(s.a); g.strokeStyle = "rgba(255,255,255,0.75)"; g.lineWidth = 3;
        g.beginPath(); g.moveTo(28, -16); g.lineTo(28, 16); g.moveTo(28, -16); g.lineTo(10, -16); g.moveTo(28, 16); g.lineTo(10, 16); g.stroke(); g.restore();
      }
      const gap = D.sea ? [TW / 2 + 75, TW / 2 + 125] : [TW / 2 + 110, Infinity];   // on the harbour, trees on the verge only
      for (let i = 0; i < 300; i++) {
        const x = t.OX + rand() * t.WW, y = t.OY + rand() * t.WH, r = 14 + rand() * 18, d = nearest(t, x, y, -1)[1];
        if (d < gap[0] || d > gap[1]) continue;
        g.fillStyle = "rgba(0,0,0,0.18)"; g.beginPath(); g.arc(x + 6, y + 8, r, 0, 7); g.fill();
        g.fillStyle = D.blob[0]; g.beginPath(); g.arc(x, y, r, 0, 7); g.fill();
        g.fillStyle = D.blob[1]; g.beginPath(); g.arc(x - r * 0.25, y - r * 0.3, r * 0.55, 0, 7); g.fill();
      }
      return cv;
    }
    const freshPaint = (t) => paintTrack(t);   // a clean picture each race (skid marks are painted onto it); none kept, to spare phone memory

    function drawCar(ctx, c, ghost) {
      ctx.save(); ctx.translate(c.x, c.y); ctx.rotate(c.a);
      if (ghost) ctx.globalAlpha = 0.38;
      if (c.boost) {   // nitro flame
        ctx.fillStyle = "#ffb43a"; ctx.beginPath(); ctx.moveTo(-24, -5); ctx.lineTo(-40 - Math.random() * 10, 0); ctx.lineTo(-24, 5); ctx.fill();
        ctx.fillStyle = "#fff2c4"; ctx.beginPath(); ctx.moveTo(-24, -2.5); ctx.lineTo(-32, 0); ctx.lineTo(-24, 2.5); ctx.fill();
      }
      if (!ghost) { ctx.fillStyle = "rgba(0,0,0,0.28)"; ctx.fillRect(-21, -9, 46, 22); }
      ctx.fillStyle = "#121214";
      for (const [x, y] of [[-15, -13], [-15, 8], [10, -13], [10, 8]]) ctx.fillRect(x, y, 10, 5);
      ctx.fillStyle = c.color;
      ctx.beginPath(); ctx.moveTo(-22, -9); ctx.lineTo(14, -8); ctx.quadraticCurveTo(24, -5, 24, 0); ctx.quadraticCurveTo(24, 5, 14, 8); ctx.lineTo(-22, 9); ctx.closePath(); ctx.fill();
      ctx.fillRect(-24, -12, 6, 24); ctx.fillRect(18, -11, 4, 22);   // wings
      ctx.fillStyle = "rgba(10,16,28,0.85)"; ctx.beginPath(); ctx.ellipse(-2, 0, 7, 5, 0, 0, 7); ctx.fill();
      if (!ghost) {
        ctx.fillStyle = c.color === "#f2f2f2" ? "#1a1a1a" : "rgba(255,255,255,0.9)";
        ctx.font = '700 10px "Rajdhani", system-ui, sans-serif';
        ctx.translate(-13, 0); ctx.rotate(Math.PI / 2); ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(c.num, 0, 0);
      }
      ctx.restore();
    }

    function build(onStatus) {
      const cv = el("canvas", "race-cv"), mini = el("canvas", "race-mini");
      mini.width = 140; mini.height = 110;
      const rows = el("div", "race-rows"), towerName = el("span", ""), towerLap = el("span", "", "Lap 1/3");
      const tower = el("div", "race-tower race-hud", el("div", "race-tower-h", towerName, towerLap), rows);
      const lapNum = el("div", "race-lapnum"), lapTime = el("div", "race-t", fmt(0)), bestLap = el("div", "race-t best"), ghostGap = el("div", "race-ghostgap");
      const lapbox = el("div", "race-lapbox race-hud", lapNum, el("div", "race-lbl", "Lap time"), lapTime, el("div", "race-lbl", "Best lap"), bestLap, ghostGap, mini);
      const kmh = el("b", "", "0"), nitroFill = el("i"), nitroBar = el("div", "race-nitro", nitroFill);
      const speedo = el("div", "race-speed race-hud", el("div", "", kmh, el("span", "", "km/h")), nitroBar);
      const lights = el("div", "race-lights race-hud", ...[0, 1, 2, 3, 4].map(() => el("i")));
      lights.hidden = true;
      const banner = el("div", "race-banner"); banner.hidden = true;
      const card = el("div", "race-card"), overlay = el("div", "race-overlay", card);
      const pad = (k, label, cls) => {
        const b = el("button", "race-pad" + (cls ? " " + cls : ""), label); b.type = "button"; b.dataset.k = k;
        b.setAttribute("aria-label", { left: "Steer left", right: "Steer right", down: "Brake", up: "Accelerate", nitro: "Nitro" }[k]); return b;
      };
      const pads = el("div", "race-pads", el("div", "race-padgrp", pad("left", "◀"), pad("right", "▶")),
        el("div", "race-padgrp", el("div", "race-padcol", pad("nitro", "NOS", "nos"), pad("down", "BRAKE")), pad("up", "GAS", "gas")));
      pads.hidden = !(root.matchMedia && root.matchMedia("(pointer: coarse)").matches);
      const stage = el("div", "race-stage", cv, tower, lapbox, speedo, lights, banner, pads, overlay);
      stage.tabIndex = 0;
      stage.setAttribute("aria-label", "Race track. Arrow keys or W A S D drive, Space for nitro, P pauses.");
      return { stage, cv, ctx: cv.getContext("2d"), mini, mctx: mini.getContext("2d"), rows, towerName, towerLap, lapNum, lapTime,
        bestLap, ghostGap, kmh, nitroFill, lights, banner, card, overlay, pads, onStatus };
    }

    const bestKey = (trk, lvl) => trk + ":" + lvl;
    function showCard(kind) {
      const { card, overlay } = G.ui, saved = store.get();
      const btn = (label, fn, ghost) => { const b = el("button", "race-go" + (ghost ? " alt" : ""), label); b.type = "button"; b.addEventListener("click", fn); return b; };
      const stat = (label, v, cls) => el("div", "race-stat", el("div", "race-lbl", label), el("div", "race-v" + (cls ? " " + cls : ""), v));
      const pick = (id, label, value, options, onChange) => {
        const s = el("select", "race-select"); s.id = id;
        for (const [v, l] of options) { const o = el("option", "", l); o.value = v; if (v === value) o.selected = true; s.append(o); }
        s.addEventListener("change", () => onChange(s.value));
        return el("label", "race-field", el("span", "race-lbl", label), s);
      };
      const setPref = (k, v) => { const s = store.get(); s[k] = v; store.set(s); resetGrid(); showCard("start"); };
      card.replaceChildren();
      if (kind === "start") {
        G.ui.lights.hidden = true;
        const T = TRACKS[saved.track] || TRACKS.kerbside, k = bestKey(saved.track, saved.level), gh = saved.ghosts[saved.track];
        const ghostBox = el("input"); ghostBox.type = "checkbox"; ghostBox.id = "race-ghost"; ghostBox.checked = !!saved.ghostOn;
        ghostBox.addEventListener("change", () => { const s = store.get(); s.ghostOn = ghostBox.checked; store.set(s); });
        card.append(el("p", "race-eyebrow", `${LAPS} laps · you, JARVIS and two more`), el("h3", "race-h", "Kerbside Grand Prix"),
          el("div", "race-fields",
            pick("race-track", "Track", saved.track, Object.entries(TRACKS).map(([v, t]) => [v, t.name]), (v) => setPref("track", v)),
            pick("race-level", "JARVIS drives", saved.level, Object.keys(LEVELS).map((v) => [v, v[0].toUpperCase() + v.slice(1)]), (v) => setPref("level", v))),
          el("p", "race-note", T.blurb + " Space (or NOS) fires nitro; the meter refills as you drive."),
          el("label", "race-check", ghostBox, gh ? ` Race my ghost (best lap ${fmt(gh.time)})` : " Race my ghost (after your first flying lap here)"),
          el("div", "race-stats", stat("Best lap", saved.best[k] ? fmt(saved.best[k]) : "–", "best"),
            stat("Best race", saved.race[k] ? fmt(saved.race[k]) : "–"), stat("Wins", String(saved.wins || 0))),
          btn("Start race", () => start()));
      } else if (kind === "pause") {
        card.append(el("p", "race-eyebrow", "Paused"), el("h3", "race-h", "Pit wall"), el("p", "race-note", "The race clock is stopped."),
          btn("Resume", () => setPaused(false)), btn("Retire and change track", () => { G.paused = false; resetGrid(); showCard("start"); }, true));
      } else {
        const r = G.race, me = r.cars[0], order = standings(r), place = order.indexOf(me) + 1, best = Math.min(...me.lapTimes);
        const lapChips = el("div", "race-laps", ...me.lapTimes.map((t, i) => el("span", t === best ? "best" : "", `L${i + 1} ${fmt(t)}`)));
        const tbl = el("table", "race-classif"), tb = el("tbody");
        order.forEach((c, i) => {
          const chip = el("span", "race-chip"); chip.style.background = c.color;
          const gap = c.done ? (i === 0 ? fmt(c.finish) : "+" + (c.finish - order[0].finish).toFixed(3) + "s") : "Lap " + Math.min(LAPS, c.laps + 1);
          tb.append(el("tr", c === me ? "me" : "", el("td", "", "P" + (i + 1)), el("td", "", chip, `${c.name} #${c.num}`), el("td", "", gap)));
        });
        tbl.append(tb);
        card.append(el("p", "race-eyebrow", `Chequered flag · ${r.trk.name} · JARVIS on ${r.level}`), el("h3", "race-h", place === 1 ? "Victory · P1" : `P${place} of ${order.length}`),
          el("div", "race-stats", stat("Race time", fmt(me.finish)), stat("Best lap", fmt(best) + (G.newBest ? " · PB" : ""), "best"), stat("All-time", fmt(store.get().best[bestKey(r.track, r.level)]))),
          lapChips, G.newGhost ? el("p", "race-note", "New ghost saved: your best flying lap on this track.") : null, tbl,
          btn("Race again", () => start()), btn("Change track or level", () => { resetGrid(); showCard("start"); }, true));
      }
      overlay.hidden = false;
      const b = card.querySelector("button"); if (b && kind !== "start") b.focus({ preventScroll: true });
    }

    function resetGrid() {   // a fresh grid for the chosen track, shown behind the start card
      const s = store.get();
      G.race = newRace({ track: s.track, level: s.level });
      G.track = freshPaint(G.race.trk); G.tctx = G.track.getContext("2d");
      G.cam.x = G.race.cars[0].x; G.cam.y = G.race.cars[0].y; G.rowKey = ""; G.ui.banner.hidden = true;
    }
    function start() {
      const s = store.get();
      G.race = newRace({ track: s.track, level: s.level, seed: (Date.now() & 0xffff) + 1, ghost: s.ghostOn ? s.ghosts[s.track] : null });
      G.track = freshPaint(G.race.trk); G.tctx = G.track.getContext("2d");
      G.newBest = false; G.newGhost = false; G.paused = false; G.ui.overlay.hidden = true; G.ui.lights.hidden = false; G.rowKey = "";
      G.cam.x = G.race.cars[0].x; G.cam.y = G.race.cars[0].y;
      G.ui.stage.focus({ preventScroll: true });
      G.ui.onStatus(`${G.race.trk.name}, JARVIS on ${G.race.level}: wait for the lights.`);
    }
    function setPaused(p) {
      if (!G || !G.race || !(G.race.state === "race" || G.race.state === "lights")) return;
      if (p && !G.ui.overlay.hidden) return;   // the start card is up: nothing to pause
      G.paused = p;
      if (p) showCard("pause"); else { G.ui.overlay.hidden = true; G.ui.stage.focus({ preventScroll: true }); }
    }
    function banner(text, ms, warn) {
      const b = G.ui.banner; b.textContent = text; b.classList.toggle("warn", !!warn); b.hidden = false;
      clearTimeout(G.bannerTimer); if (ms) G.bannerTimer = setTimeout(() => { b.hidden = true; }, ms);
    }
    function keepGhost(g) {
      if (!g) return;
      const s = store.get(), old = s.ghosts[G.race.track];
      if (!old || g.time < old.time) { s.ghosts[G.race.track] = { time: g.time, pts: g.pts }; store.set(s); G.newGhost = true; }
    }
    function finish() {
      const r = G.race, me = r.cars[0], k = bestKey(r.track, r.level), s = store.get(), best = Math.min(...me.lapTimes), place = standings(r).indexOf(me) + 1;
      if (!s.best[k] || best < s.best[k]) { s.best[k] = best; G.newBest = true; }
      if (!s.race[k] || me.finish < s.race[k]) s.race[k] = me.finish;
      if (place === 1) s.wins = (s.wins || 0) + 1;
      store.set(s);
      banner("Chequered flag", 1200);
      G.ui.onStatus(place === 1 ? `You beat JARVIS on ${r.trk.name}: P1 in ${fmt(me.finish)}.` : `You finished P${place} on ${r.trk.name} in ${fmt(me.finish)}.`);
      setTimeout(() => { if (G && G.race === r && r.state === "done") { G.ui.banner.hidden = true; showCard("result"); } }, 900);
    }

    function handleEvents() {
      const r = G.race, best = store.get().best[bestKey(r.track, r.level)];
      for (const e of r.events.splice(0)) {
        if (e.type === "go") { G.ui.lights.hidden = true; banner("Go!", 900); G.ui.onStatus(`Lap 1 of ${LAPS}: lights out, go!`); }
        else if (e.type === "lap") {
          keepGhost(e.ghost);
          banner((e.lap === LAPS - 1 ? "Final lap" : "Lap " + (e.lap + 1)) + " · " + fmt(e.time) + (!best || e.time < best ? " fastest" : ""), 1400);
          G.ui.onStatus(`Lap ${e.lap + 1} of ${LAPS}, P${standings(r).indexOf(r.cars[0]) + 1}.`);
        } else if (e.type === "finish") { keepGhost(e.ghost); finish(); }
      }
      for (const [x, y, a] of r.skids.splice(0)) {
        const bx = x - Math.cos(a) * 14 - r.trk.OX, by = y - Math.sin(a) * 14 - r.trk.OY, sx = -Math.sin(a) * 9, sy = Math.cos(a) * 9;
        G.tctx.fillStyle = "rgba(20,20,22,0.10)"; G.tctx.fillRect(bx + sx - 2, by + sy - 2, 4, 4); G.tctx.fillRect(bx - sx - 2, by - sy - 2, 4, 4);
      }
    }

    function render() {
      const { ui, race } = G, t = race.trk, me = race.cars[0], D = DECOR[t.decor] || DECOR.park;
      const W = ui.stage.clientWidth, H = ui.stage.clientHeight, dpr = Math.min(2, root.devicePixelRatio || 1);
      if (ui.cv.width !== Math.round(W * dpr) || ui.cv.height !== Math.round(H * dpr)) { ui.cv.width = Math.round(W * dpr); ui.cv.height = Math.round(H * dpr); }
      const ctx = ui.ctx, sp = Math.hypot(me.vx, me.vy);
      const z = Math.max(0.42, Math.min(1.25, Math.min(W, H) / 640)) * (1 - 0.18 * Math.min(1, sp / 700));
      G.cam.x += (me.x + me.vx * 0.32 - G.cam.x) * 0.12; G.cam.y += (me.y + me.vy * 0.32 - G.cam.y) * 0.12;
      const hw = W / 2 / z, hh = H / 2 / z;   // keep the view inside the painted world, so its edge never shows
      const cx = t.WW > 2 * hw ? Math.max(t.OX + hw, Math.min(t.OX + t.WW - hw, G.cam.x)) : t.OX + t.WW / 2;
      const cy = t.WH > 2 * hh ? Math.max(t.OY + hh, Math.min(t.OY + t.WH - hh, G.cam.y)) : t.OY + t.WH / 2;
      ctx.setTransform(dpr * z, 0, 0, dpr * z, dpr * (W / 2 - cx * z), dpr * (H / 2 - cy * z));
      ctx.fillStyle = D.sea || D.ground; ctx.fillRect(cx - W / z, cy - H / z, 2 * W / z, 2 * H / z);
      ctx.drawImage(G.track, t.OX, t.OY);
      const gp = ghostPose(race);
      if (gp) drawCar(ctx, { x: gp[0], y: gp[1], a: gp[2], color: me.color }, true);
      for (const c of race.cars) if (c !== me) drawCar(ctx, c);
      drawCar(ctx, me);
      ctx.setTransform(1, 0, 0, 1, 0, 0);

      const m = ui.mctx, mw = ui.mini.width, mh = ui.mini.height, s = Math.min((mw - 10) / (t.maxX - t.minX), (mh - 10) / (t.maxY - t.minY));
      const mx = (x) => 5 + (x - t.minX) * s + ((mw - 10) - (t.maxX - t.minX) * s) / 2, my = (y) => 5 + (y - t.minY) * s + ((mh - 10) - (t.maxY - t.minY) * s) / 2;
      m.clearRect(0, 0, mw, mh);
      m.beginPath(); t.P.forEach(([x, y], i) => (i ? m.lineTo(mx(x), my(y)) : m.moveTo(mx(x), my(y)))); m.closePath();
      m.strokeStyle = "rgba(255,255,255,0.55)"; m.lineWidth = 3; m.lineJoin = "round"; m.stroke();
      m.fillStyle = "#fff"; m.fillRect(mx(t.P[0][0]) - 4, my(t.P[0][1]) - 1, 8, 2);
      for (const c of [...race.cars].reverse()) { m.fillStyle = c.color; m.beginPath(); m.arc(mx(c.x), my(c.y), c === me ? 4.5 : 3.2, 0, 7); m.fill(); }

      const lapShown = Math.min(LAPS, me.laps + 1), text = (e, v) => { if (e.textContent !== v) e.textContent = v; };
      text(ui.towerName, t.name.split(" ")[0]);
      text(ui.lapNum, `${lapShown}/${LAPS}`); text(ui.towerLap, `Lap ${lapShown}/${LAPS}`);
      text(ui.lapTime, fmt(race.state === "race" ? race.t - me.lapStart : me.done ? me.lapTimes[me.lapTimes.length - 1] : 0));
      const saved = store.get().best[bestKey(race.track, race.level)], sess = me.lapTimes.length ? Math.min(...me.lapTimes) : 0;
      text(ui.bestLap, fmt(saved && sess ? Math.min(saved, sess) : saved || sess));
      text(ui.ghostGap, gp ? `Ghost ${fmt(race.ghost.time)}` : "");
      text(ui.kmh, String(Math.round(Math.max(0, me.fwd) * 0.34)));
      ui.nitroFill.style.width = Math.round(me.nitro * 100) + "%";
      ui.nitroFill.classList.toggle("on", me.boost);
      const lit = race.state === "lights" ? Math.min(5, Math.floor(race.lightsT / 0.7)) : 0;
      ui.lights.querySelectorAll("i").forEach((e, i) => e.classList.toggle("on", i < lit));
      const order = standings(race), lead = order[0];
      const key = order.map((c) => c.code + Math.round(c.prog / 4)).join();
      if (key !== G.rowKey) {
        G.rowKey = key;
        ui.rows.replaceChildren(...order.map((c, i) => {
          let gap = "Leader";
          if (i > 0) {
            if (c.done && lead.done) gap = "+" + (c.finish - lead.finish).toFixed(1) + "s";
            else { const dl = (lead.prog - c.prog) / t.N; gap = dl >= 1 ? "+" + Math.floor(dl) + " lap" : "+" + Math.round((lead.prog - c.prog) * SP * 0.1) + " m"; }
          }
          const chip = el("span", "race-chip"); chip.style.background = c.color;
          return el("div", "race-row" + (c === me ? " me" : ""), el("span", "pos", i + 1), chip, el("span", "code", c.code), el("span", "gap", gap));
        }));
      }
      if (race.wrongT > 0.8) banner("Wrong way", 0, true);
      else if (ui.banner.classList.contains("warn")) { ui.banner.hidden = true; ui.banner.classList.remove("warn"); }
    }

    function frame(now) {
      if (!G) return;
      if (!G.ui.stage.isConnected) { unmount(); return; }
      G.raf = root.requestAnimationFrame(frame);
      const view = root.document.body.dataset.view, visible = !root.document.hidden && (!view || view === "games");
      const dt = Math.min(0.05, (now - G.last) / 1000); G.last = now;
      if (!visible) { setPaused(true); return; }
      if (!G.paused && G.ui.overlay.hidden) {
        G.acc += dt;
        const k = G.keys, you = { steer: (k.right ? 1 : 0) - (k.left ? 1 : 0), thr: !!k.up, brk: !!k.down, nitro: !!k.nitro };
        while (G.acc >= 1 / 120) { step(G.race, 1 / 120, you); G.acc -= 1 / 120; }
      } else G.acc = 0;
      handleEvents();
      render();
    }

    function onKey(e) {
      if (!G || !KEYS[e.code] && e.code !== "KeyP") return;
      const t = e.target, typing = t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName));
      const racing = G.race && (G.race.state === "race" || G.race.state === "lights") && G.ui.overlay.hidden;
      if (typing) return;
      if (e.type === "keydown" && e.code === "KeyP") { if (racing) setPaused(true); else if (G.paused) setPaused(false); return; }
      if (!KEYS[e.code]) return;
      if (e.type === "keyup") { G.keys[KEYS[e.code]] = false; return; }
      if (!racing) return;
      G.keys[KEYS[e.code]] = true; e.preventDefault();   // arrows and Space drive the car instead of scrolling the page
    }

    function unmount() {
      if (!G) return;
      root.cancelAnimationFrame(G.raf); clearTimeout(G.bannerTimer);
      root.removeEventListener("keydown", onKey); root.removeEventListener("keyup", onKey);
      G = null;
    }

    // Returns the game's element to place on the page; keeps playing the same race when the page re-renders.
    function mount(opts = {}) {
      if (G && G.ui.stage.isConnected) return G.ui.stage;
      unmount();
      const ui = build(opts.onStatus || (() => {}));
      G = { ui, keys: {}, cam: { x: 0, y: 0 }, last: root.performance.now(), acc: 0, paused: false };
      resetGrid();
      ui.pads.querySelectorAll(".race-pad").forEach((b) => {
        const k = b.dataset.k, held = new Set();
        const set = () => { if (G) { G.keys[k] = held.size > 0; b.classList.toggle("active", held.size > 0); } };
        b.addEventListener("pointerdown", (e) => { e.preventDefault(); held.add(e.pointerId); try { b.setPointerCapture(e.pointerId); } catch { /* fine */ } set(); });
        const up = (e) => { held.delete(e.pointerId); set(); };
        for (const ev of ["pointerup", "pointercancel", "lostpointercapture"]) b.addEventListener(ev, up);
        b.addEventListener("contextmenu", (e) => e.preventDefault());
      });
      ui.stage.addEventListener("touchstart", () => { ui.pads.hidden = false; }, { passive: true, once: true });
      root.addEventListener("keydown", onKey); root.addEventListener("keyup", onKey);
      showCard("start");
      G.raf = root.requestAnimationFrame(frame);
      return ui.stage;
    }
    Object.assign(api, { mount, unmount, restart: () => { if (G) start(); } });
  }

  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.JarvisRacer = api;
})(typeof self !== "undefined" ? self : globalThis);
