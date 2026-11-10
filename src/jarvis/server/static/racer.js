"use strict";
// Kerbside Grand Prix: a top-down, three-lap race against JARVIS and two other cars. Track, physics and the AI
// drivers are written for JARVIS: no library, no model, no network. The simulation (newRace/step) is plain data and
// runs in Node for the tests; mount() adds the canvas, HUD and controls on the Games page. Best times are kept in
// this browser only (localStorage).
(function (root) {
  // ---------------------------------------------------------------- Track: a closed spline, resampled every SP units
  const CTRL = [[400, 1400], [400, 760], [560, 430], [960, 340], [1240, 580], [1500, 520], [1800, 300], [2300, 330],
    [2620, 680], [2470, 1040], [2020, 1090], [1760, 1340], [2100, 1600], [2520, 1690], [2440, 2050], [1640, 2160],
    [920, 2060], [560, 1820]];
  const TW = 150, SP = 12, LAPS = 3, RAD = 17;
  const cr = (a, b, c, d, t) => { const t2 = t * t, t3 = t2 * t; return 0.5 * (2 * b + (-a + c) * t + (2 * a - 5 * b + 4 * c - d) * t2 + (-a + 3 * b - 3 * c + d) * t3); };
  const raw = [];
  for (let i = 0; i < CTRL.length; i++) {
    const n = CTRL.length, p0 = CTRL[(i - 1 + n) % n], p1 = CTRL[i], p2 = CTRL[(i + 1) % n], p3 = CTRL[(i + 2) % n];
    for (let s = 0; s < 40; s++) { const t = s / 40; raw.push([cr(p0[0], p1[0], p2[0], p3[0], t), cr(p0[1], p1[1], p2[1], p3[1], t)]); }
  }
  const P = [];
  {
    let prev = raw[0], need = SP; P.push(prev);
    for (let i = 1; i <= raw.length; i++) {
      const cur = raw[i % raw.length]; let seg = Math.hypot(cur[0] - prev[0], cur[1] - prev[1]);
      while (seg >= need) { const t = need / seg; prev = [prev[0] + (cur[0] - prev[0]) * t, prev[1] + (cur[1] - prev[1]) * t]; P.push(prev); seg -= need; need = SP; }
      need -= seg; prev = cur;
    }
    const l = P[P.length - 1]; if (Math.hypot(l[0] - P[0][0], l[1] - P[0][1]) < SP / 2) P.pop();
  }
  const N = P.length;
  const ANG = P.map((p, i) => { const q = P[(i + 1) % N]; return Math.atan2(q[1] - p[1], q[0] - p[0]); });
  const wrapA = (a) => { while (a > Math.PI) a -= 2 * Math.PI; while (a < -Math.PI) a += 2 * Math.PI; return a; };
  const nrm = (i) => { const a = ANG[((i % N) + N) % N]; return [-Math.sin(a), Math.cos(a)]; };
  let minX = 1e9, minY = 1e9, maxX = -1e9, maxY = -1e9;
  for (const [x, y] of P) { minX = Math.min(minX, x); minY = Math.min(minY, y); maxX = Math.max(maxX, x); maxY = Math.max(maxY, y); }
  const MARGIN = 320, OX = minX - MARGIN, OY = minY - MARGIN, WW = Math.ceil(maxX - minX + 2 * MARGIN), WH = Math.ceil(maxY - minY + 2 * MARGIN);

  // Nearest centreline point: a local search around the last one (cars move a few points per step), or all of them.
  function nearest(x, y, hint) {
    let best = -1, bd = Infinity;
    const scan = (i) => { const p = P[i], d = (p[0] - x) ** 2 + (p[1] - y) ** 2; if (d < bd) { bd = d; best = i; } };
    if (hint < 0) for (let i = 0; i < N; i++) scan(i);
    else for (let k = -45; k <= 45; k++) scan(((hint + k) % N + N) % N);
    return [best, Math.sqrt(bd)];
  }
  function gridSlots() {
    return [0, 1, 2, 3].map((k) => {
      const i = (N - 5 - k * 5) % N, [nx, ny] = nrm(i), side = k % 2 ? 1 : -1;
      return { i, x: P[i][0] + nx * side * 34, y: P[i][1] + ny * side * 34, a: ANG[i] };
    });
  }

  // ---------------------------------------------------------------- Cars and levels
  const ROSTER = [
    { code: "YOU", name: "You", color: "#e9c44a", num: 7, ai: false, skill: 1, lane: 0 },
    { code: "JRV", name: "JARVIS", color: "#d23c3c", num: 1, ai: true, skill: 0.985, lane: -18 },
    { code: "BLU", name: "Bleu", color: "#2f7de1", num: 4, ai: true, skill: 0.965, lane: 14 },
    { code: "WIT", name: "Whitlock", color: "#f2f2f2", num: 22, ai: true, skill: 0.94, lane: 0 },
  ];
  const LEVELS = { easy: 0.9, medium: 0.975, hard: 1.0 };   // multiplies each AI driver's own skill
  const ACC = 430;

  function rng(seed) { let s = (seed >>> 0) % 2147483647 || 7; return () => (s = (s * 16807) % 2147483647) / 2147483647; }

  function newRace(opts = {}) {
    const level = LEVELS[opts.level] ? opts.level : "medium", mult = LEVELS[level], rand = rng(opts.seed || 1);
    const slots = gridSlots(), order = [2, 0, 1, 3];   // you start third
    const cars = ROSTER.map((r, k) => {
      const s = slots[order[k]], skill = r.ai ? r.skill * mult : 1;
      return { ...r, skill, acc: ACC * skill, x: s.x, y: s.y, a: s.a, vx: 0, vy: 0, fwd: 0, slip: 0, on: true,
        idx: s.i, prog: s.i - N, laps: 0, lapStart: 0, lapTimes: [], done: false, finish: 0, wander: rand() * 6 };
    });
    return { level, cars, state: "lights", lightsT: 0, t: 0, simT: 0, wrongT: 0, events: [], skids: [] };
  }

  function physics(c, inp, dt) {
    let fx = Math.cos(c.a), fy = Math.sin(c.a);
    const sp0 = c.vx * fx + c.vy * fy;
    const sf = Math.min(1, Math.abs(sp0) / 150) * (1 - 0.42 * Math.min(1, Math.abs(sp0) / 700));
    c.a += inp.steer * 2.75 * sf * Math.sign(sp0 || 1) * dt;
    fx = Math.cos(c.a); fy = Math.sin(c.a);
    let fwd = c.vx * fx + c.vy * fy, lat = -c.vx * fy + c.vy * fx;
    if (inp.thr) fwd += c.acc * dt * (c.on ? 1 : 0.55);
    if (inp.brk) fwd -= (fwd > 15 ? 950 : 260) * dt;            // brake, then reverse
    fwd -= fwd * (c.on ? 0.64 : 2.3) * dt;                         // drag; grass and gravel are slow
    if (!inp.thr && !inp.brk) fwd -= Math.sign(fwd) * Math.min(Math.abs(fwd), 70 * dt);
    fwd = Math.max(fwd, -160);
    lat *= Math.exp(-(c.on ? 6.5 : 3) * dt);                       // tyre grip
    c.vx = fx * fwd - fy * lat; c.vy = fy * fwd + fx * lat;
    c.x = Math.max(OX + 20, Math.min(OX + WW - 20, c.x + c.vx * dt));
    c.y = Math.max(OY + 20, Math.min(OY + WH - 20, c.y + c.vy * dt));
    c.fwd = fwd; c.slip = Math.abs(lat);
  }

  // An AI driver aims at a point ahead on its own line and brakes for the sharpest bend in the next ~500 units.
  function aiInput(c, t) {
    const sp = Math.max(0, c.fwd || 0);
    const ti = (c.idx + Math.round(7 + sp / 45)) % N, [nx, ny] = nrm(ti);
    const lane = c.lane + Math.sin(t * 0.35 + c.wander) * 16;
    const diff = wrapA(Math.atan2(P[ti][1] + ny * lane - c.y, P[ti][0] + nx * lane - c.x) - c.a);
    let turn = 0;
    for (let k = 4; k <= 44; k += 4) turn = Math.max(turn, Math.abs(wrapA(ANG[(c.idx + k) % N] - ANG[c.idx])));
    const target = Math.max(235, 665 * c.skill - Math.min(turn, 1.6) * 300);
    return { steer: Math.max(-1, Math.min(1, diff * 3)), thr: sp < target, brk: sp > target + 45 };
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

  // One fixed step. `you` is the player's input {steer -1..1, thr, brk}; pass null to let the AI drive your car too.
  // Laps count from continuous progress along the centreline, so driving backwards over the line never scores one.
  function step(race, dt, you) {
    race.simT += dt;
    if (race.state === "lights") {
      race.lightsT += dt;
      if (race.lightsT > 4.1) { race.state = "race"; race.events.push({ type: "go" }); }
    }
    const moving = race.state !== "lights";
    if (moving && race.cars.some((c) => !c.done)) race.t += dt;   // runs until every car is home
    for (const c of race.cars) {
      let inp = { steer: 0, thr: false, brk: false };
      if (moving) {
        if (c.done && !c.ai) inp = { steer: aiInput({ ...c, skill: 0.6, lane: 0 }, race.simT).steer, thr: c.fwd < 200, brk: false };  // cool-down lap
        else if (c.ai || !you) inp = aiInput(c, race.simT);
        else inp = you;
      }
      physics(c, inp, dt);
    }
    collide(race.cars);
    for (const c of race.cars) {
      const [ni, dist] = nearest(c.x, c.y, c.idx);
      c.on = dist < TW / 2 + 11;
      let d = ni - c.idx; if (d > N / 2) d -= N; if (d < -N / 2) d += N;
      c.prog += d; c.idx = ni;
      const lapsNow = Math.max(0, Math.floor(c.prog / N));
      if (moving && !c.done && lapsNow > c.laps) {
        c.laps = lapsNow; c.lapTimes.push(race.t - c.lapStart); c.lapStart = race.t;
        if (c.laps >= LAPS) { c.done = true; c.finish = race.t; }
        if (!c.ai) race.events.push({ type: c.done ? "finish" : "lap", lap: c.laps, time: c.lapTimes[c.lapTimes.length - 1] });
        if (!c.ai && c.done) race.state = "done";
      }
      if (!c.ai) {
        const along = c.vx * Math.cos(ANG[c.idx]) + c.vy * Math.sin(ANG[c.idx]);
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

  const api = { TRACK: P, N, TW, SP, LAPS, LEVELS, ROSTER, nearest, newRace, step, standings, aiInput, fmt };

  // ---------------------------------------------------------------- The page: canvas, HUD, touch pads
  if (root.document) {
    const STORE = "jarvis-racer";
    const store = {
      get() { try { return Object.assign({ level: "medium", best: {}, race: {}, wins: 0 }, JSON.parse(root.localStorage.getItem(STORE) || "{}")); } catch { return { level: "medium", best: {}, race: {}, wins: 0 }; } },
      set(v) { try { root.localStorage.setItem(STORE, JSON.stringify(v)); } catch { /* private window: this visit only */ } },
    };
    const el = (tag, cls, ...kids) => {
      const e = root.document.createElement(tag);
      if (cls) e.className = cls;
      for (const k of kids) if (k !== null && k !== undefined) e.append(k instanceof root.Node ? k : String(k));
      return e;
    };
    const KEYS = { ArrowUp: "up", KeyW: "up", ArrowDown: "down", KeyS: "down", ArrowLeft: "left", KeyA: "left", ArrowRight: "right", KeyD: "right" };
    let G = null;   // the one mounted game

    const trees = [];
    { const rand = rng(7); for (let i = 0; i < 260; i++) { const x = OX + rand() * WW, y = OY + rand() * WH; if (nearest(x, y, -1)[1] > TW / 2 + 110) trees.push([x, y, 14 + rand() * 18]); } }

    function paintTrack() {
      const cv = root.document.createElement("canvas"); cv.width = WW; cv.height = WH;
      const g = cv.getContext("2d");
      g.translate(-OX, -OY);
      g.fillStyle = "#2f6e38"; g.fillRect(OX, OY, WW, WH);
      g.fillStyle = "#2a6533";
      for (let s = -WH; s < WW + WH; s += 120) { g.beginPath(); g.moveTo(OX + s, OY); g.lineTo(OX + s + 60, OY); g.lineTo(OX + s + 60 - WH, OY + WH); g.lineTo(OX + s - WH, OY + WH); g.fill(); }
      const path = () => { g.beginPath(); P.forEach(([x, y], i) => (i ? g.lineTo(x, y) : g.moveTo(x, y))); g.closePath(); };
      g.lineJoin = "round"; g.lineCap = "round";
      path(); g.strokeStyle = "#cbb98c"; g.lineWidth = TW + 90; g.stroke();     // gravel run-off
      path(); g.strokeStyle = "#f2f0ea"; g.lineWidth = TW + 22; g.stroke();     // kerbs
      path(); g.strokeStyle = "#d3372b"; g.setLineDash([22, 22]); g.stroke(); g.setLineDash([]);
      path(); g.strokeStyle = "#474c55"; g.lineWidth = TW; g.stroke();          // tarmac
      path(); g.strokeStyle = "rgba(255,255,255,0.10)"; g.lineWidth = 3; g.setLineDash([30, 40]); g.stroke(); g.setLineDash([]);
      g.save(); g.translate(P[0][0], P[0][1]); g.rotate(ANG[0]);
      const sq = 10;
      for (let r = 0; r < 2; r++) for (let c = 0; c < Math.ceil(TW / sq); c++) { g.fillStyle = (r + c) % 2 ? "#111" : "#fafafa"; g.fillRect(-sq + r * sq, -TW / 2 + c * sq, sq, sq); }
      g.restore();
      for (const s of gridSlots()) {
        g.save(); g.translate(s.x, s.y); g.rotate(s.a); g.strokeStyle = "rgba(255,255,255,0.75)"; g.lineWidth = 3;
        g.beginPath(); g.moveTo(28, -16); g.lineTo(28, 16); g.moveTo(28, -16); g.lineTo(10, -16); g.moveTo(28, 16); g.lineTo(10, 16); g.stroke(); g.restore();
      }
      for (const [x, y, r] of trees) {
        g.fillStyle = "rgba(0,0,0,0.18)"; g.beginPath(); g.arc(x + 6, y + 8, r, 0, 7); g.fill();
        g.fillStyle = "#1f5228"; g.beginPath(); g.arc(x, y, r, 0, 7); g.fill();
        g.fillStyle = "#2b6a34"; g.beginPath(); g.arc(x - r * 0.25, y - r * 0.3, r * 0.55, 0, 7); g.fill();
      }
      return cv;
    }

    function drawCar(ctx, c) {
      ctx.save(); ctx.translate(c.x, c.y); ctx.rotate(c.a);
      ctx.fillStyle = "rgba(0,0,0,0.28)"; ctx.fillRect(-21, -9, 46, 22);
      ctx.fillStyle = "#121214";
      for (const [x, y] of [[-15, -13], [-15, 8], [10, -13], [10, 8]]) ctx.fillRect(x, y, 10, 5);
      ctx.fillStyle = c.color;
      ctx.beginPath(); ctx.moveTo(-22, -9); ctx.lineTo(14, -8); ctx.quadraticCurveTo(24, -5, 24, 0); ctx.quadraticCurveTo(24, 5, 14, 8); ctx.lineTo(-22, 9); ctx.closePath(); ctx.fill();
      ctx.fillRect(-24, -12, 6, 24); ctx.fillRect(18, -11, 4, 22);   // wings
      ctx.fillStyle = "rgba(10,16,28,0.85)"; ctx.beginPath(); ctx.ellipse(-2, 0, 7, 5, 0, 0, 7); ctx.fill();
      ctx.fillStyle = c.color === "#f2f2f2" ? "#1a1a1a" : "rgba(255,255,255,0.9)";
      ctx.font = '700 10px "Rajdhani", system-ui, sans-serif';
      ctx.translate(-13, 0); ctx.rotate(Math.PI / 2); ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(c.num, 0, 0);
      ctx.restore();
    }

    function build(onStatus) {
      const cv = el("canvas", "race-cv"), mini = el("canvas", "race-mini");
      mini.width = 140; mini.height = 110;
      const rows = el("div", "race-rows"), towerLap = el("span", "", "Lap 1/3");
      const tower = el("div", "race-tower race-hud", el("div", "race-tower-h", el("span", "", "Kerbside"), towerLap), rows);
      const lapNum = el("div", "race-lapnum"), lapTime = el("div", "race-t", fmt(0)), bestLap = el("div", "race-t best");
      const lapbox = el("div", "race-lapbox race-hud", lapNum, el("div", "race-lbl", "Lap time"), lapTime, el("div", "race-lbl", "Best lap"), bestLap, mini);
      const kmh = el("b", "", "0"), speedo = el("div", "race-speed race-hud", kmh, el("span", "", "km/h"));
      const lights = el("div", "race-lights race-hud", ...[0, 1, 2, 3, 4].map(() => el("i")));
      lights.hidden = true;
      const banner = el("div", "race-banner"); banner.hidden = true;
      const card = el("div", "race-card");
      const overlay = el("div", "race-overlay", card);
      const pad = (k, label, cls) => { const b = el("button", "race-pad" + (cls ? " " + cls : ""), label); b.type = "button"; b.dataset.k = k; b.setAttribute("aria-label", { left: "Steer left", right: "Steer right", down: "Brake", up: "Accelerate" }[k]); return b; };
      const pads = el("div", "race-pads", el("div", "race-padgrp", pad("left", "◀"), pad("right", "▶")), el("div", "race-padgrp", pad("down", "BRAKE"), pad("up", "GAS", "gas")));
      pads.hidden = !(root.matchMedia && root.matchMedia("(pointer: coarse)").matches);
      const stage = el("div", "race-stage", cv, tower, lapbox, speedo, lights, banner, pads, overlay);
      stage.tabIndex = 0;
      stage.setAttribute("aria-label", "Race track. Arrow keys or W A S D drive; P pauses.");
      return { stage, cv, ctx: cv.getContext("2d"), mini, mctx: mini.getContext("2d"), rows, towerLap, lapNum, lapTime, bestLap, kmh, lights, banner, card, overlay, pads, onStatus };
    }

    function showCard(kind) {
      const { card, overlay } = G.ui, saved = store.get(), lvl = kind === "start" ? G.level : G.race.level;
      const btn = (label, fn) => { const b = el("button", "btn race-go", label); b.type = "button"; b.addEventListener("click", fn); return b; };
      const stat = (label, v, cls) => el("div", "race-stat", el("div", "race-lbl", label), el("div", "race-v" + (cls ? " " + cls : ""), v));
      card.replaceChildren();
      if (kind === "start") G.ui.lights.hidden = true;
      if (kind === "start") {
        card.append(el("p", "race-eyebrow", `Kerbside Circuit · ${LAPS} laps · JARVIS on ${lvl}`), el("h3", "race-h", "Kerbside Grand Prix"),
          el("p", "d-why", "Wait for the five red lights to go out, then race. Grass and gravel cost you speed."),
          el("div", "race-stats", stat("Best lap", saved.best[lvl] ? fmt(saved.best[lvl]) : "–", "best"),
            stat("Best race", saved.race[lvl] ? fmt(saved.race[lvl]) : "–"), stat("Wins", String(saved.wins || 0))),
          btn("Start race", () => start()));
      } else if (kind === "pause") {
        card.append(el("p", "race-eyebrow", "Paused"), el("h3", "race-h", "Pit wall"), el("p", "d-why", "The race clock is stopped."), btn("Resume", () => setPaused(false)));
      } else {
        const me = G.race.cars[0], order = standings(G.race), place = order.indexOf(me) + 1, best = Math.min(...me.lapTimes);
        const lapChips = el("div", "race-laps", ...me.lapTimes.map((t, i) => el("span", t === best ? "best" : "", `L${i + 1} ${fmt(t)}`)));
        const tbl = el("table", "race-classif"), tb = el("tbody");
        order.forEach((c, i) => {
          const chip = el("span", "race-chip"); chip.style.background = c.color;
          const gap = c.done ? (i === 0 ? fmt(c.finish) : "+" + (c.finish - order[0].finish).toFixed(3) + "s") : "Lap " + Math.min(LAPS, c.laps + 1);
          const tr = el("tr", c === me ? "me" : "", el("td", "", "P" + (i + 1)), el("td", "", chip, `${c.name} #${c.num}`), el("td", "", gap));
          tb.append(tr);
        });
        tbl.append(tb);
        card.append(el("p", "race-eyebrow", `Chequered flag · JARVIS on ${lvl}`), el("h3", "race-h", place === 1 ? "Victory · P1" : `P${place} of ${order.length}`),
          el("div", "race-stats", stat("Race time", fmt(me.finish)), stat("Best lap", fmt(best) + (G.newBest ? " · PB" : ""), "best"), stat("All-time", fmt(store.get().best[lvl]))),
          lapChips, tbl, btn("Race again", () => start()));
      }
      overlay.hidden = false;
      const b = card.querySelector("button"); if (b && kind !== "start") b.focus({ preventScroll: true });
    }

    function start() {
      G.race = newRace({ level: G.level, seed: (Date.now() & 0xffff) + 1 });
      G.track = paintTrack(); G.tctx = G.track.getContext("2d");
      G.newBest = false; G.paused = false; G.ui.overlay.hidden = true; G.ui.lights.hidden = false;
      G.cam.x = G.race.cars[0].x; G.cam.y = G.race.cars[0].y;
      G.ui.stage.focus({ preventScroll: true });
      G.ui.onStatus(`Racing JARVIS on ${G.level}: wait for the lights.`);
    }
    function setPaused(p) {
      if (!G || !G.race || G.race.state === "done") return;
      G.paused = p;
      if (p) showCard("pause"); else { G.ui.overlay.hidden = true; G.ui.stage.focus({ preventScroll: true }); }
    }
    function banner(text, ms, warn) {
      const b = G.ui.banner; b.textContent = text; b.classList.toggle("warn", !!warn); b.hidden = false;
      clearTimeout(G.bannerTimer); if (ms) G.bannerTimer = setTimeout(() => { b.hidden = true; }, ms);
    }
    function finish() {
      const me = G.race.cars[0], lvl = G.race.level, s = store.get(), best = Math.min(...me.lapTimes), place = standings(G.race).indexOf(me) + 1;
      if (!s.best[lvl] || best < s.best[lvl]) { s.best[lvl] = best; G.newBest = true; }
      if (!s.race[lvl] || me.finish < s.race[lvl]) s.race[lvl] = me.finish;
      if (place === 1) s.wins = (s.wins || 0) + 1;
      store.set(s);
      banner("Chequered flag", 1200);
      G.ui.onStatus(place === 1 ? `You beat JARVIS: P1 in ${fmt(me.finish)}.` : `You finished P${place} in ${fmt(me.finish)}.`);
      setTimeout(() => { if (G && G.race && G.race.state === "done") { G.ui.banner.hidden = true; showCard("result"); } }, 900);
    }

    function handleEvents() {
      const r = G.race, best = store.get().best[r.level];
      for (const e of r.events.splice(0)) {
        if (e.type === "go") { G.ui.lights.hidden = true; banner("Go!", 900); G.ui.onStatus(`Lap 1 of ${LAPS}: lights out, go!`); }
        else if (e.type === "lap") {
          banner((e.lap === LAPS - 1 ? "Final lap" : "Lap " + (e.lap + 1)) + " · " + fmt(e.time) + (!best || e.time < best ? " fastest" : ""), 1400);
          G.ui.onStatus(`Lap ${e.lap + 1} of ${LAPS}, P${standings(r).indexOf(r.cars[0]) + 1}.`);
        } else if (e.type === "finish") finish();
      }
      for (const [x, y, a] of r.skids.splice(0)) {
        const bx = x - Math.cos(a) * 14 - OX, by = y - Math.sin(a) * 14 - OY, sx = -Math.sin(a) * 9, sy = Math.cos(a) * 9;
        G.tctx.fillStyle = "rgba(20,20,22,0.10)"; G.tctx.fillRect(bx + sx - 2, by + sy - 2, 4, 4); G.tctx.fillRect(bx - sx - 2, by - sy - 2, 4, 4);
      }
    }

    function render() {
      const { ui, race } = G, me = race.cars[0];
      const W = ui.stage.clientWidth, H = ui.stage.clientHeight, dpr = Math.min(2, root.devicePixelRatio || 1);
      if (ui.cv.width !== Math.round(W * dpr) || ui.cv.height !== Math.round(H * dpr)) { ui.cv.width = Math.round(W * dpr); ui.cv.height = Math.round(H * dpr); }
      const ctx = ui.ctx, sp = Math.hypot(me.vx, me.vy);
      const z = Math.max(0.42, Math.min(1.25, Math.min(W, H) / 640)) * (1 - 0.16 * Math.min(1, sp / 650));
      G.cam.x += (me.x + me.vx * 0.32 - G.cam.x) * 0.12; G.cam.y += (me.y + me.vy * 0.32 - G.cam.y) * 0.12;
      ctx.setTransform(dpr * z, 0, 0, dpr * z, dpr * (W / 2 - G.cam.x * z), dpr * (H / 2 - G.cam.y * z));
      ctx.fillStyle = "#2d6a36"; ctx.fillRect(G.cam.x - W / z, G.cam.y - H / z, 2 * W / z, 2 * H / z);
      ctx.drawImage(G.track, OX, OY);
      for (const c of race.cars) if (c !== me) drawCar(ctx, c);
      drawCar(ctx, me);
      ctx.setTransform(1, 0, 0, 1, 0, 0);

      const m = ui.mctx, mw = ui.mini.width, mh = ui.mini.height, s = Math.min((mw - 10) / (maxX - minX), (mh - 10) / (maxY - minY));
      const mx = (x) => 5 + (x - minX) * s + ((mw - 10) - (maxX - minX) * s) / 2, my = (y) => 5 + (y - minY) * s + ((mh - 10) - (maxY - minY) * s) / 2;
      m.clearRect(0, 0, mw, mh);
      m.beginPath(); P.forEach(([x, y], i) => (i ? m.lineTo(mx(x), my(y)) : m.moveTo(mx(x), my(y)))); m.closePath();
      m.strokeStyle = "rgba(255,255,255,0.55)"; m.lineWidth = 3; m.lineJoin = "round"; m.stroke();
      m.fillStyle = "#fff"; m.fillRect(mx(P[0][0]) - 4, my(P[0][1]) - 1, 8, 2);
      for (const c of [...race.cars].reverse()) { m.fillStyle = c.color; m.beginPath(); m.arc(mx(c.x), my(c.y), c === me ? 4.5 : 3.2, 0, 7); m.fill(); }

      const lapShown = Math.min(LAPS, me.laps + 1), text = (e, v) => { if (e.textContent !== v) e.textContent = v; };
      text(ui.lapNum, `${lapShown}/${LAPS}`); text(ui.towerLap, `Lap ${lapShown}/${LAPS}`);
      text(ui.lapTime, fmt(race.state === "race" ? race.t - me.lapStart : me.done ? me.lapTimes[me.lapTimes.length - 1] : 0));
      const saved = store.get().best[race.level], sess = me.lapTimes.length ? Math.min(...me.lapTimes) : 0;
      text(ui.bestLap, fmt(saved && sess ? Math.min(saved, sess) : saved || sess));
      text(ui.kmh, String(Math.round(Math.max(0, me.fwd) * 0.34)));
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
            else { const dl = (lead.prog - c.prog) / N; gap = dl >= 1 ? "+" + Math.floor(dl) + " lap" : "+" + Math.round((lead.prog - c.prog) * SP * 0.1) + " m"; }
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
      const visible = !root.document.hidden && (!root.document.body.dataset.view || root.document.body.dataset.view === "games");
      const dt = Math.min(0.05, (now - G.last) / 1000); G.last = now;
      if (!visible) { if (G.race.state === "race" || G.race.state === "lights") setPaused(true); return; }
      if (!G.paused && G.ui.overlay.hidden) {
        G.acc += dt;
        const k = G.keys, you = { steer: (k.right ? 1 : 0) - (k.left ? 1 : 0), thr: !!k.up, brk: !!k.down };
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
      if (e.type === "keydown" && e.code === "KeyP" && G.race && G.race.state !== "done") { setPaused(!G.paused); return; }
      if (!KEYS[e.code]) return;
      if (e.type === "keyup") { G.keys[KEYS[e.code]] = false; return; }
      if (!racing) return;
      G.keys[KEYS[e.code]] = true; e.preventDefault();   // arrows drive the car instead of scrolling the page
    }

    function unmount() {
      if (!G) return;
      root.cancelAnimationFrame(G.raf); clearTimeout(G.bannerTimer);
      root.removeEventListener("keydown", onKey); root.removeEventListener("keyup", onKey);
      G = null;
    }

    // Returns the game's element to place on the page; keeps playing the same race when the page re-renders.
    function mount(opts = {}) {
      if (G && G.ui.stage.isConnected) return G.root;
      unmount();
      const ui = build(opts.onStatus || (() => {}));
      G = { ui, keys: {}, cam: { x: 0, y: 0 }, last: root.performance.now(), acc: 0, level: store.get().level, paused: false };
      G.race = newRace({ level: G.level }); G.track = paintTrack(); G.tctx = G.track.getContext("2d");
      G.cam.x = G.race.cars[0].x; G.cam.y = G.race.cars[0].y;
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
      G.state = "start"; showCard("start");
      G.root = ui.stage;
      G.raf = root.requestAnimationFrame(frame);
      return ui.stage;
    }
    function setLevel(level) {
      if (!LEVELS[level]) return;
      const s = store.get(); s.level = level; store.set(s);
      if (G) { G.level = level; if (!G.race || G.race.state !== "race") { G.race = newRace({ level }); showCard("start"); } }
    }
    Object.assign(api, {
      mount, unmount, setLevel, level: () => store.get().level,
      restart: () => { if (G) start(); },
    });
  }

  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.JarvisRacer = api;
})(typeof self !== "undefined" ? self : globalThis);
