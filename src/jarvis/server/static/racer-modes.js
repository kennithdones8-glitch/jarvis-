"use strict";
// Kerbside Grand Prix: the rules of the newer race modes. racer.js runs the physics, the AI line-following and the
// lap counting; each mode here adds its own rules through four hooks (init, input, post, summary):
//   pursuit   — the police chase you. Heat rises with time and with every unit you ram; more units join, and from
//               heat 3 they ram back and set roadblocks. Stay boxed in near a unit and the busted meter fills; get out
//               of sight (the Ridge tunnel and the Old Town bridges hide you faster) and the escape meter fills; stay
//               well clear while still in sight and it fills slowly.
//   drag      — side by side down the Harbour waterfront straight. Rev for the launch, shift up at the right
//               moment (six gears, a rev limiter), steering is automatic.
//   touge     — a one-on-one where pulling about 1.5 s clear (55 track points) wins on the spot.
//   endurance — tyres wear with distance and with sliding (up to 30% less grip); stop in the pit box before the
//               line for fresh tyres and repairs. The AI pits when its tyres are worn.
//   delivery  — checkpoints against the clock, each one adds time; leaving the road or sliding hard bruises cargo.
//   team      — a circuit race scored for two teams by points.
// Plain data, no page code: the tests run these in Node.
(function (root) {
  const R = typeof module !== "undefined" && module.exports ? require("./racer.js") : root.JarvisRacer;
  const { HOOKS, TW, SP, PERSONA, nearest, clamp, wrapA, latOff, aiInput, specOf, LEVELS } = R;

  const idxGap = (t, a, b) => { let d = a - b; if (d > t.N / 2) d -= t.N; if (d < -t.N / 2) d += t.N; return d; };
  const steerTo = (c, x, y) => clamp(wrapA(Math.atan2(y - c.y, x - c.x) - c.a) * 3, -1, 1);
  const pointAt = (t, i, lat) => { const k = ((i % t.N) + t.N) % t.N, [nx, ny] = t.nrm(k); return [t.P[k][0] + nx * lat, t.P[k][1] + ny * lat]; };
  const carFields = (t, i, lat, v) => {
    const k = ((i % t.N) + t.N) % t.N, [x, y] = pointAt(t, k, lat), a = t.ANG[k];
    return { x, y, a, vx: Math.cos(a) * v, vy: Math.sin(a) * v, fwd: v, slip: 0, on: true, idx: k, laps: 0, lapStart: 0, lapTimes: [],
      done: false, finish: 0, out: false, outAt: 0, wander: 0, nitro: 0.3, boost: false, aiBoost: false, laneCur: lat, side: 0, stuckT: 0,
      recoverT: 0, dmg: 0, contacts: 0, brakeOn: false, steerIn: 0, latAcc: 0, spool: 0 };
  };

  // Places a pursuit can't see you as well: the Ridge's rock tunnel and Old Town's canal bridges. The same stretch
  // of road the renderer roofs over (it uses the same rules).
  function coverOf(t) {
    if (t.cover) return t.cover;
    const zones = [];
    if (t.decor === "rock") {
      let best = 0, bestT = 9;
      for (let i = 60; i < t.N - 60; i += 3) { let turn = 0; for (let k = 0; k < 30; k += 3) turn = Math.max(turn, Math.abs(wrapA(t.ANG[(i + k) % t.N] - t.ANG[i]))); if (turn < bestT) { bestT = turn; best = i; } }
      zones.push([best - 2, 36]);
    }
    if (t.decor === "city") {
      const cy = (x) => t.OY + t.WH * 0.47 + Math.sin((x - t.OX) / 420) * 90, cross = [];
      for (let i = 0; i < t.N; i++) {
        const a = t.P[i][1] - cy(t.P[i][0]), b = t.P[(i + 1) % t.N][1] - cy(t.P[(i + 1) % t.N][0]);
        if (a * b <= 0 && !cross.some((j) => Math.abs(j - i) < 20)) cross.push(i);
      }
      for (const i of cross) zones.push([i - 7, 14]);
    }
    return (t.cover = zones);
  }
  const inCover = (t, i) => coverOf(t).some(([s, n]) => ((i - s) % t.N + t.N) % t.N <= n);

  // ------------------------------------------------------------------ Police pursuit
  const HEAT = [null,
    { units: 2, skill: 0.96, ram: false, rb: false, need: 7 },
    { units: 3, skill: 0.99, ram: false, rb: false, need: 8 },
    { units: 3, skill: 1.02, ram: true, rb: true, need: 9 },
    { units: 4, skill: 1.04, ram: true, rb: true, need: 10 },
    { units: 5, skill: 1.06, ram: true, rb: true, need: 12 }];
  const POLICE_SPEC = { acc: 470, drag: 0.64, grip: 6.8, brake: 1000, steer: 2.7, mass: 1.35, nitro: { push: 380, burn: 0.4, fill: 0.055, cap: 1.28 } };

  function addUnit(race, idx, lat, v, parked) {
    const P = race.pursuit, t = race.trk, me = race.cars[0], k = P.units++, spec = specOf({ spec: P.spec });
    const skill = HEAT[P.heat].skill * LEVELS[race.level];
    const c = { id: "pol" + k, code: "PKPD", name: parked ? "Roadblock" : "Unit " + (k + 1), color: "#f4f4f4", num: 0, ai: true, police: true, parked: !!parked,
      shape: "sedan", art: { add: ["pushbar", "aerial"] }, look: { livery: "police", color: "#f4f4f4" }, persona: PERSONA.aggressive, spec, skill, acc: spec.acc * skill, ...carFields(t, idx, lat, v) };
    if (parked) { c.a += Math.PI / 2 * (lat > 0 ? 1 : -1); c.spec = { ...spec, mass: 4 }; }
    c.prog = me.prog + idxGap(t, c.idx, me.idx); c.laps = Math.max(0, Math.floor(c.prog / t.N));
    race.cars.push(c);
    return c;
  }
  const units = (race) => race.cars.filter((c) => c.police && !c.parked && !c.out);

  HOOKS.pursuit = {
    init(race, opts) {
      race.laps = 999;
      const heat = clamp(opts.heat | 0 || 1, 1, 5);
      race.pursuit = { heat, heatP: 0, maxHeat: heat, bust: 0, cool: 0, bounty: 0, time: 0, state: "chase", units: 0, disabled: 0, rams: 0,
        rb: null, rbT: 0, rbPassed: 0, spawnT: 0, seen: true, cover: false, near: 1e9, logN: 0, spec: opts.policeSpec || POLICE_SPEC };
      const me = race.cars[0];
      for (let k = 0; k < HEAT[heat].units; k++) addUnit(race, me.idx - 14 - k * 10, k % 2 ? 22 : -22, 0);
    },
    input(race, c, inp) {
      if (!c.police || c.parked) return inp;
      const P = race.pursuit, me = race.cars[0], t = race.trk;
      if (race.state === "lights") return inp;
      const base = aiInput(race, c);
      if (P.state !== "chase" || c.out) return { steer: base.steer, thr: false, brk: c.fwd > 0, nitro: false };
      if (c.recoverT > 0 || !P.seen) return base;                           // lost you: search along the road
      const g = idxGap(t, me.idx, c.idx), d = Math.hypot(me.x - c.x, me.y - c.y), H = HEAT[P.heat];
      if (d < 260 && Math.abs(me.fwd) < 170) {                             // you've slowed or stopped: pull up alongside and pin you
        const want = Math.max(0, (d - 40) * 1.6), to = Math.atan2(me.y - c.y, me.x - c.x);
        if (Math.cos(to - c.a) < -0.2 && d > 60) {                         // you're behind it: reverse back to you
          return { steer: -clamp(wrapA(to - c.a - Math.PI) * 3, -1, 1), thr: false, brk: true, nitro: false };
        }
        return { steer: steerTo(c, me.x, me.y), thr: c.fwd < want, brk: c.fwd > want + 40, nitro: false };
      }
      if (g >= 0 && g < 40 && d < 420) {                                    // behind you and close: take your line, then hit you
        c.lane = clamp(latOff(t, me), -TW / 2 + 22, TW / 2 - 22);
        const ram = H.ram && d < 130 && !base.brk;                           // on the straights, not into a bend
        const lead = clamp(d / 700, 0.05, 0.25), steer = d < 130 ? steerTo(c, me.x + me.vx * lead, me.y + me.vy * lead) : base.steer;
        return { steer, thr: base.thr || ram, brk: base.brk && !ram, nitro: P.heat >= 2 && d > 220 && c.nitro > 0.15 && !base.brk };
      }
      c.lane = 0;
      if (g < 0 && g > -30 && P.heat >= 2) {                                // ahead of you: cut across your line and slow you down
        const [bx, by] = pointAt(t, c.idx + 8, clamp(latOff(t, me), -TW / 2 + 22, TW / 2 - 22));
        const hold = c.fwd > Math.max(120, me.fwd - 30);
        return { steer: steerTo(c, bx, by), thr: !hold && base.thr, brk: hold && c.fwd > me.fwd + 40, nitro: false };
      }
      return { ...base, nitro: base.nitro || (P.heat >= 2 && g > 0 && c.nitro > 0.3 && !base.brk) };
    },
    post(race, dt) {
      const P = race.pursuit, me = race.cars[0], t = race.trk;
      if (race.state !== "race" || P.state !== "chase") return;
      P.time += dt; P.bounty += dt * 8 * P.heat;
      // contacts this step: ramming a unit damages it hard (four big hits take it out) and raises the heat
      const L = race.log.contacts;
      for (; P.logN < L.length; P.logN++) {
        const e = L[P.logN], other = e.a === me.id ? e.b : e.b === me.id ? e.a : null, u = other && race.cars.find((c) => c.id === other);
        if (!u || !u.police || e.v < 70) continue;
        u.dmg = Math.min(1, u.dmg + e.v / 900);
        if (e.by === me.id) { P.rams++; P.heatP += 0.12 + e.v / 2000; }
      }
      for (const u of race.cars) if (u.police && !u.out && u.dmg >= 1) {
        u.out = true; u.outAt = race.t; u.vx *= 0.3; u.vy *= 0.3;
        if (!u.parked) { P.disabled++; P.bounty += 400 * P.heat; P.heatP += 0.3; race.events.push({ type: "unit-down", left: units(race).length }); }
      }
      P.heatP += dt / 35;
      if (P.heatP >= 1) {
        if (P.heat < 5) { P.heat++; P.heatP = 0; P.maxHeat = Math.max(P.maxHeat, P.heat); race.events.push({ type: "heat", heat: P.heat }); } else P.heatP = 1;
      }
      // reinforcements join from behind, out of sight, until the heat level's number of units is on you
      P.spawnT += dt;
      if (units(race).length < HEAT[P.heat].units && P.spawnT > 6) { P.spawnT = 0; addUnit(race, me.idx - 70, 0, 300); race.events.push({ type: "unit-join" }); }
      // roadblocks: two parked units across the road ahead, leaving a gap on one side
      if (HEAT[P.heat].rb) P.rbT += dt;
      if (!P.rb && P.rbT > 28) {
        let i = me.idx + 115;
        for (let k = 0; k < 40 && (t.K[((i % t.N) + t.N) % t.N] > 0.004 || inCover(t, ((i % t.N) + t.N) % t.N)); k++) i++;
        const side = (Math.floor(race.t) % 2) ? 1 : -1;
        P.rb = { idx: ((i % t.N) + t.N) % t.N, t: race.t, cars: [addUnit(race, i, side * 50, 0, true), addUnit(race, i, side * 10, 0, true)], side };
        race.events.push({ type: "roadblock", side: -side });
      }
      if (P.rb) {
        const passed = idxGap(t, me.idx, P.rb.idx) > 25;
        if (passed || race.t - P.rb.t > 45) {
          if (passed) { P.rbPassed++; P.bounty += 150 * P.heat; }
          race.cars = race.cars.filter((c) => !P.rb.cars.includes(c)); P.rb = null; P.rbT = 0;
        }
      }
      // sight: fog and night shorten it; in cover only a unit right on you still sees you
      const range = race.fogness > 0.5 ? 400 : race.tod === "night" ? 540 : 650, cover = inCover(t, me.idx);
      let seen = false, near = 1e9, nearAny = 1e9;
      for (const u of race.cars) {
        if (!u.police || u.out) continue;
        const d = Math.hypot(u.x - me.x, u.y - me.y);
        nearAny = Math.min(nearAny, d);
        if (u.parked) continue;
        near = Math.min(near, d);
        if (d < (cover ? 200 : range)) seen = true;
      }
      P.seen = seen; P.cover = cover; P.near = near;
      // busted: pinned next to a unit (or stopped against a roadblock) at low speed
      if (nearAny < 115 && Math.abs(me.fwd) < 150) P.bust += dt / (3 - 0.25 * P.heat);
      else P.bust = Math.max(0, P.bust - dt / 2);
      // out of sight the escape meter fills (twice as fast in cover); still in sight but well clear, it fills slowly
      if (!seen) P.cool += dt / HEAT[P.heat].need * (cover ? 2 : 1);
      else if (near > 420) P.cool += dt / HEAT[P.heat].need * 0.3;
      else P.cool = Math.max(0, P.cool - dt / 3);
      const end = (result) => {
        P.state = result; me.done = true; me.finish = race.t; race.state = "done";
        P.fine = result === "busted" ? Math.round(P.bounty * 0.4 + 250 * P.heat) : 0;
        race.events.push({ type: "pursuit-end", result, bounty: Math.round(P.bounty) });
      };
      if (P.bust >= 1) end("busted");
      else if (P.cool >= 1) end("escaped");
    },
    summary(race, out) {
      const P = race.pursuit;
      out.pursuit = { result: P.state, heat: P.maxHeat, bounty: Math.round(P.bounty), time: +P.time.toFixed(2), disabled: P.disabled, rams: P.rams, roadblocks: P.rbPassed, fine: P.fine || 0 };
      out.place = P.state === "escaped" ? 1 : 2; out.of = 2; out.finished = P.state === "escaped"; out.total = P.time;
      out.order = P.state === "escaped" ? [race.cars[0].id, "police"] : ["police", race.cars[0].id]; out.beat = [];
    },
  };

  // ------------------------------------------------------------------ Drag
  // Six gears. Each gear's pull rises with the revs (and dies on the limiter), and each taller gear pulls less hard at
  // the same road speed until the revs are near the top: so the quickest time comes from shifting near 90% revs.
  const GEARS = [0.3, 0.47, 0.62, 0.76, 0.89, 1], T1 = 0.6;
  const TORQUE = GEARS.map((_, g) => T1 * [1, 1.334, 1.6, 1.835, 2.04, 2.21][g]);
  const DRAG_LEN = 130;
  const curve = (r) => (r < 0.93 ? 0.3 + 0.75 * r : r < 1 ? 0.9975 * (1 - (r - 0.93) * 6) : 0);
  function straightest(t, len) {
    let best = 0, bestT = 9;
    for (let s = 0; s < t.N; s += 2) {
      let turn = 0;
      for (let k = 0; k <= len + 20 && turn < bestT; k += 4) turn = Math.max(turn, Math.abs(wrapA(t.ANG[(s + k) % t.N] - t.ANG[s])));
      if (turn < bestT) { bestT = turn; best = s; }
    }
    return best;
  }
  HOOKS.drag = {
    maxField: 1, track: "harbour",                                     // the waterfront straight is the only one long enough
    init(race, opts, rand) {
      const t = race.trk, s = straightest(t, DRAG_LEN), len = opts.dragLen || DRAG_LEN;
      race.laps = 999;
      race.drag = { start: s, len, goT: 0 };
      race.cars.forEach((c, k) => {
        const lat = k === 0 ? -32 : 32;
        Object.assign(c, carFields(t, s, lat, 0), { lane: lat, gear: 0, rpm: 0, shiftT: 0, launch: 1, perfect: 0, shifts: 0, bonusT: 0, trap: 0, shiftWas: false,
          nitro: race.rules.nitro ? 0.6 : 0, shiftAt: c.ai ? clamp(0.93 - (1 - (c.skill || 0.95)) * 1.4 - rand() * 0.03, 0.78, 0.93) : 0.9, revTo: c.ai ? 0.62 + rand() * 0.12 : 0.65 });
        c.prog = s - t.N; c.startProg = c.prog;
        c.spec = { ...c.spec, nitro: { ...c.spec.nitro, push: c.spec.nitro.push * 0.5 } };   // a shot of nitro, not a rocket
      });
    },
    input(race, c, inp, you) {
      const t = race.trk, [tx, ty] = pointAt(t, c.idx + 10, c.lane), steer = steerTo(c, tx, ty);
      const human = !c.ai && you, thr = human ? !!you.thr : null;
      if (race.state === "lights") {                                     // revving on the line
        const on = human ? thr : c.rpm < c.revTo;
        c.rpm = clamp(c.rpm + (on ? 1.5 : -1.2) / 120, 0, 1);
        return { steer: 0, thr: false, brk: false, nitro: false };
      }
      if (c.done) return { steer, thr: false, brk: true, nitro: false };
      if (c.rpm0 === undefined) {                                        // the launch: the revs you held when the lights went
        c.rpm0 = c.rpm; const r = c.rpm;
        c.launch = r < 0.4 ? 0.72 + r * 0.5 : r <= 0.8 ? 1 - Math.abs(r - 0.66) * 0.5 : 0.92 - (r - 0.8) * 1.2;
        if (!c.ai) race.events.push({ type: "launch", q: c.launch > 0.95 ? "perfect" : c.launch > 0.86 ? "good" : r > 0.8 ? "wheelspin" : "bogged" });
      }
      const top = c.acc / c.spec.drag;
      c.rpm = clamp(c.fwd / (top * GEARS[c.gear]), 0, 1.02);
      const shift = human ? !!you.shift && !c.shiftWas : c.rpm >= c.shiftAt;
      if (human) c.shiftWas = !!you.shift;
      if (shift && c.gear < GEARS.length - 1 && c.shiftT <= 0) {
        const r = c.rpm, q = r >= 0.86 && r <= 0.97 ? "perfect" : r < 0.76 ? "early" : r > 0.97 ? "late" : "good";
        c.gear++; c.shifts++; c.shiftT = 0.18;
        if (q === "perfect") { c.perfect++; c.bonusT = 0.5; }
        if (!c.ai) race.events.push({ type: "shift", gear: c.gear + 1, q });
      }
      c.shiftT -= 1 / 120; c.bonusT -= 1 / 120;
      const launching = race.t < 1.2 ? c.launch : 1;
      c.accF = c.shiftT > 0 ? 0 : TORQUE[c.gear] * curve(c.gear === 0 ? Math.max(c.rpm, 0.55) : c.rpm) * launching * (c.bonusT > 0 ? 1.08 : 1);
      const nitro = human ? !!you.nitro : c.gear >= 2 && c.nitro > 0;
      return { steer, thr: human ? thr : true, brk: false, nitro };
    },
    post(race) {
      const D = race.drag;
      for (const c of race.cars) {
        if (c.done || race.state !== "race" || c.prog - c.startProg < D.len) continue;
        c.done = true; c.finish = race.t; c.trap = Math.max(0, c.fwd);
        if (!c.ai) { race.state = "done"; race.events.push({ type: "finish", lap: 1, time: race.t, ghost: null }); }
      }
    },
    summary(race, out) {
      const me = race.cars[0], op = race.cars[1];
      out.drag = { et: me.done ? +me.finish.toFixed(3) : 0, trap: Math.round(me.trap), launch: +me.launch.toFixed(3), perfect: me.perfect, shifts: me.shifts,
        theirs: op && op.done ? +op.finish.toFixed(3) : 0 };
    },
  };

  // ------------------------------------------------------------------ Touge
  const TOUGE_GAP = 55;
  HOOKS.touge = {
    maxField: 1,
    init(race) { race.touge = { how: "", lead: 0 }; },
    post(race) {
      const me = race.cars[0], op = race.cars[1];
      if (!op || race.state !== "race" || me.done || op.done) return;
      const d = me.prog - op.prog;
      race.touge.lead = Math.max(race.touge.lead, d);
      if (Math.abs(d) < TOUGE_GAP) return;
      const w = d > 0 ? me : op, l = w === me ? op : me;
      w.done = true; w.finish = race.t; l.done = true; l.finish = race.t + 1.5;
      race.touge.how = "gap"; race.state = "done";
      race.events.push({ type: "touge", you: w === me });
      if (w === me) race.events.push({ type: "finish", lap: me.laps, time: race.t - me.lapStart, ghost: null });
    },
    summary(race, out) { out.touge = { how: race.touge.how || "line", lead: Math.round(race.touge.lead) }; },
  };

  // ------------------------------------------------------------------ Endurance
  const inBox = (t, c) => c.idx >= t.N - 10;            // the pit box: the last 10 points before the line
  HOOKS.endurance = {
    init(race, opts) { race.endur = { rate: opts.wearRate || 1 }; for (const c of race.cars) { c.wear = 0; c.pitT = 0; c.pits = 0; c.lastPit = -99; } },
    input(race, c, inp) {
      const t = race.trk;
      if (c.pitT > 0) return { steer: 0, thr: false, brk: true, nitro: false };
      if (c.ai && !c.done && c.wear > 0.5 && race.laps - c.laps >= 2) {   // AI: brake into the box when the tyres are gone
        const to = t.N - 10 - c.idx;
        if (to >= 0 && to < 36 && c.fwd > 90 + to * 12) return { ...inp, thr: false, brk: true, nitro: false };
        if (inBox(t, c) && c.fwd > 60) return { ...inp, thr: false, brk: true, nitro: false };
      }
      return inp;
    },
    post(race, dt) {
      const t = race.trk;
      if (race.state !== "race" && race.state !== "done") return;
      for (const c of race.cars) {
        if (c.out) continue;
        if (c.pitT > 0) {
          c.vx = c.vy = c.fwd = 0; c.pitT -= dt;
          if (c.pitT <= 0) { c.wear = 0; if (race.rules.damage) c.dmg = 0; c.nitro = Math.max(c.nitro, 0.5); if (!c.ai) race.events.push({ type: "pit", done: true }); }
          continue;
        }
        if (c.done) continue;
        c.wear = Math.min(1, c.wear + dt * race.endur.rate * (0.0032 + clamp((c.slip - 40) / 400, 0, 0.012)) * (c.on ? 1 : 1.5));
        if (c.laps >= 1 && inBox(t, c) && Math.abs(c.fwd) < 110 && race.t - c.lastPit > 20 && race.laps - c.laps >= 1) {
          c.pitT = 2.5; c.pits++; c.lastPit = race.t;
          if (!c.ai) race.events.push({ type: "pit", done: false });
        }
      }
    },
    summary(race, out) { const me = race.cars[0]; out.endurance = { pits: me.pits, wear: +me.wear.toFixed(3) }; },
  };

  // ------------------------------------------------------------------ Delivery
  HOOKS.delivery = {
    init(race, opts) {
      const t = race.trk, me = race.cars[0], stops = clamp(opts.stops | 0 || 4, 2, 8), laps = clamp(opts.laps | 0 || 1, 1, 3);
      const seg = t.N * laps / stops, segT = seg * SP / (opts.pace || 300);
      race.laps = 999;
      race.deliv = { cps: [...Array(stops).keys()].map((k) => Math.round(me.prog + seg * (k + 1))), next: 0, left: segT * 1.25, add: segT, cargo: 1, stops, failed: false };
    },
    post(race, dt) {
      const D = race.deliv, me = race.cars[0];
      if (race.state !== "race" || me.done || me.out) return;
      if (!me.on && me.fwd > 150) D.cargo -= dt * 0.12 * (me.fwd / 400);
      if (me.slip > 120) D.cargo -= dt * 0.03;
      D.cargo = Math.max(0, D.cargo);
      D.left -= dt;
      if (me.prog >= D.cps[D.next]) {
        D.next++;
        if (D.next >= D.cps.length) { me.done = true; me.finish = race.t; race.state = "done"; race.events.push({ type: "finish", lap: 1, time: race.t, ghost: null }); return; }
        D.left += D.add; race.events.push({ type: "checkpoint", n: D.next, of: D.cps.length, left: D.left });
      }
      if (D.left <= 0) { D.left = 0; D.failed = true; me.out = true; me.outAt = race.t; race.state = "done"; race.events.push({ type: "delivery-failed" }); }
    },
    summary(race, out) {
      const D = race.deliv;
      out.delivery = { delivered: !D.failed && D.next >= D.cps.length, cargo: +D.cargo.toFixed(3), left: +D.left.toFixed(2), stops: D.stops, reached: D.next };
      out.place = out.delivery.delivered ? 1 : 2; out.of = 2;
    },
  };

  // ------------------------------------------------------------------ Team (2 v 2 and up)
  const POINTS = [10, 8, 6, 5, 4, 3];
  HOOKS.team = {
    summary(race, out) {
      const tally = { you: 0, them: 0 };
      R.standings(race).forEach((c, i) => { const side = !c.ai ? "you" : c.team === "you" ? "you" : "them"; tally[side] += c.out ? 0 : POINTS[i] || 0; });
      out.team = { you: tally.you, them: tally.them, won: tally.you > tally.them };
    },
  };

  Object.assign(R, { coverOf, inCover, HEAT, GEARS, DRAG_LEN, TOUGE_GAP, POLICE_SPEC, idxGap });
  if (typeof module !== "undefined" && module.exports) module.exports = R;
})(typeof self !== "undefined" ? self : globalThis);
