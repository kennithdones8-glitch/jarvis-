"use strict";
// Kerbside Grand Prix: the race view. Everything the player sees and touches: the world picture, 2.5D scenery,
// cars, lighting, weather, particles, camera, HUD, touch pads and the mount()/unmount()/restart() API on
// JarvisRacer. The simulation it draws lives in racer.js and is unchanged by anything here.
(function (root) {
  const R = root.JarvisRacer;
  if (!R) return;
  const { TW, SP, TRACKS, ROSTER, track, nearest, newRace, step, standings, ghostPose, summary, fmt, clamp, wrapA, rng } = R;
  // ================================================================ The page
  // The race view. A static world picture per race (road, kerbs, ground detail, shadows), then every frame: animated
  // water, skid marks, particles, nitro trails, cars (cached sprites + live wheels and lights), tall scenery in 2.5D
  // (tops lean away from the eye), cloud shadows, colour grade, darkness with lights cut out, a glow pass for neon and
  // lamps, fog, rain, speed effects, cinematic bars. The camera chases your car (rotating) or stays north-up.
  if (root.document && R) {
    const doc = root.document;
    const el = (tag, cls, ...kids) => {
      const e = doc.createElement(tag);
      if (cls) e.className = cls;
      for (const k of kids) if (k !== null && k !== undefined && k !== false) e.append(k instanceof root.Node ? k : String(k));
      return e;
    };
    const KEYS = { ArrowUp: "up", KeyW: "up", ArrowDown: "down", KeyS: "down", ArrowLeft: "left", KeyA: "left",
      ArrowRight: "right", KeyD: "right", Space: "nitro", ShiftLeft: "nitro", ShiftRight: "nitro", KeyE: "shift", KeyQ: "shift" };
    const reduceMotion = () => !!(root.matchMedia && root.matchMedia("(prefers-reduced-motion: reduce)").matches);
    const coarse = () => !!(root.matchMedia && root.matchMedia("(pointer: coarse)").matches);
    const ease = (k) => k * k * (3 - 2 * k);
    let G = null;   // the one mounted game

    // ---------------------------------------------------------------- World art
    // Each location has its own palette (vivid arcade colours by day, neon accents by night).
    const DECOR = {
      park: { ground: "#3f8a3f", stripe: "#3a8139", canopy: ["#1d5a2b", "#2d7a36", "#4f9c45"], alt: ["#7a5a1c", "#a7742a", "#d4a245"], neon: ["#ffb347", "#7cf3ff"] },
      water: { ground: "#3a8640", stripe: "#357d3b", canopy: ["#1d5a2b", "#2d7a36", "#4f9c45"], sea: "#1a6a96", wave: "#3a8dbd", neon: ["#3ef2ff", "#ff4fa3"] },
      rock: { ground: "#6c7b3d", stripe: "#65733a", canopy: ["#1e4a2e", "#2d6237", "#3f7a45"], alt: ["#8a3a1c", "#c2571f", "#e9892c"], rock: ["#6f6a60", "#8f897c", "#b0a99a"], neon: ["#ffcf5a", "#ff6a3d"] },
      city: { ground: "#5d6063", stripe: "#585b5e", canopy: ["#1d5a2b", "#2d7a36", "#4f9c45"], canal: "#1f5f78", neon: ["#ff3fa4", "#38e8ff", "#ffd23a", "#9b6bff"] },
    };
    const SUN = { day: [0.55, 0.75], dawn: [-1.3, 0.6], dusk: [1.5, 0.45], night: [0.12, 0.15] };
    const BRANDS = [["KERBSIDE", "#e9c44a", "#141210"], ["HALDEN TYRES", "#1d9a6c", "#ffffff"], ["BLUEWATER", "#1f6fd6", "#ffffff"], ["OKAFOR MOTORS", "#ef7d22", "#151210"], ["PKRL", "#d23c3c", "#ffffff"], ["CORVO COFFEE", "#2b2320", "#f1d9b0"]];

    function makeProps(t) {
      const rand = rng(t.key.length * 131 + 17), props = [], D = DECOR[t.decor], far = (x, y, m) => nearest(t, x, y, -1)[1] > TW / 2 + m;
      const add = (p) => props.push(p), tooClose = (x, y, r) => props.some((p) => p.k === "box" && Math.abs(p.x - x) < (p.w || 0) / 2 + r && Math.abs(p.y - y) < (p.d || 0) / 2 + r);
      if (t.decor === "city") {
        for (let gx = t.OX + 60; gx < t.OX + t.WW - 60; gx += 150) for (let gy = t.OY + 60; gy < t.OY + t.WH - 60; gy += 150) {
          const w = 90 + rand() * 40, d = 90 + rand() * 40, x = gx + rand() * 20, y = gy + rand() * 20;
          if (!far(x, y, 75 + Math.max(w, d) / 2 * 1.2)) continue;
          if (t.canal && Math.abs(canalY(t, x) - y) < 70) continue;
          const col = ["#9c5f48", "#a98466", "#7d6a5a", "#b8957a", "#6e5b4f", "#c09a78", "#8e6f9a", "#5f7f8f"][Math.floor(rand() * 8)];
          add({ k: "box", x, y, w, d, h: 50 + rand() * 130, a: 0, col, roof: ["#4b4440", "#5a4e45", "#3f3b39", "#6a5a4c"][Math.floor(rand() * 4)], windows: true,
            neon: rand() < 0.45 ? D.neon[Math.floor(rand() * D.neon.length)] : null });
        }
      }
      const treeN = { park: 210, water: 140, rock: 150, city: 40 }[t.decor];
      for (let i = 0; i < treeN * 3 && props.filter((p) => p.k === "tree").length < treeN; i++) {
        const x = t.OX + rand() * t.WW, y = t.OY + rand() * t.WH, dd = nearest(t, x, y, -1)[1];
        if (t.decor === "water" ? (dd < TW / 2 + 80 || dd > TW / 2 + 130) : dd < TW / 2 + 110) continue;
        if (tooClose(x, y, 30)) continue;
        if (t.canal && Math.abs(canalY(t, x) - y) < 60) continue;
        if (t.pond && Math.hypot(x - t.pond[0], y - t.pond[1]) < t.pond[2] + 30) continue;
        const pine = t.decor === "rock" && rand() < 0.6, autumn = D.alt && rand() < (t.decor === "rock" ? 0.35 : 0.12);
        const r = pine ? 11 + rand() * 9 : 13 + rand() * 17;
        add({ k: pine ? "pine" : "tree", x, y, r, h: (pine ? 55 : 30) + rand() * 30, c: autumn ? D.alt : D.canopy });
      }
      if (t.decor === "rock") for (let i = 0; i < 160; i++) {
        const x = t.OX + rand() * t.WW, y = t.OY + rand() * t.WH;
        if (far(x, y, 105)) add({ k: "rock", x, y, r: 14 + rand() * 26, h: 8 + rand() * 18, c: D.rock });
      }
      // grandstand beside the start line, set back past the gravel
      { const [nx, ny] = t.nrm(8), p = t.P[8]; add({ k: "box", x: p[0] - nx * (TW / 2 + 120), y: p[1] - ny * (TW / 2 + 120), w: 260, d: 60, h: 34, a: t.ANG[8], col: "#3a3f4a", roof: "#c44a3b", stand: true }); }
      // the podium, set back from the start straight: three plinths, winner in the middle
      { const i = 16 % t.N, [nx, ny] = t.nrm(i), p = t.P[i], ca = Math.cos(t.ANG[i]), sa = Math.sin(t.ANG[i]), off = t.decor === "water" ? TW / 2 + 100 : TW / 2 + 150, cx = p[0] + nx * off, cy = p[1] + ny * off;   // the harbour verge is narrow
        t.podium = { x: cx, y: cy, a: t.ANG[i] + Math.PI / 2, steps: [[0, 30], [-1, 20], [1, 12]].map(([o, h]) => ({ x: cx + ca * o * 56, y: cy + sa * o * 56, h })) };
        t.podium.steps.forEach((st, k) => add({ k: "box", x: st.x, y: st.y, w: 54, d: 46, h: st.h, a: t.ANG[i], col: ["#d9b45f", "#b8bcc4", "#c4824a"][k], roof: ["#f6e6c2", "#e6e8ec", "#e0a46a"][k], plinth: k + 1 })); }
      // start gantry over the line: the start lights live here too
      add({ k: "box", x: t.P[0][0], y: t.P[0][1], w: 18, d: TW + 60, h: 64, a: t.ANG[0], col: "#24262b", roof: "#2f3238", gantry: true });
      // billboards facing the track on the straights
      for (let i = 30, n = 0; i < t.N; i += 47) {
        if (Math.abs(wrapA(t.ANG[(i + 10) % t.N] - t.ANG[i])) > 0.25) continue;
        const [nx, ny] = t.nrm(i), s = n % 2 ? 1 : -1, p = t.P[i], off = t.decor === "water" ? TW / 2 + 70 : TW / 2 + 80;
        const x = p[0] + nx * s * off, y = p[1] + ny * s * off;
        if (tooClose(x, y, 50)) continue;
        add({ k: "box", x, y, w: 120, d: 8, h: 48, a: t.ANG[i], col: "#2a2c31", roof: "#3a3d44", board: BRANDS[(n + t.key.length) % BRANDS.length], face: -s }); n++;
      }
      // chevron boards on the outside of the tightest bends
      for (let i = 0; i < t.N; i += 9) {
        const turn = wrapA(t.ANG[(i + 8) % t.N] - t.ANG[i]);
        if (Math.abs(turn) < 0.6) continue;
        const [nx, ny] = t.nrm(i + 4), s = turn > 0 ? -1 : 1, p = t.P[(i + 4) % t.N], x = p[0] + nx * s * (TW / 2 + 40), y = p[1] + ny * s * (TW / 2 + 40);
        if (!tooClose(x, y, 30)) add({ k: "box", x, y, w: 46, d: 6, h: 20, a: t.ANG[(i + 4) % t.N], col: "#1d1d1f", roof: "#ffd23a", chevron: turn > 0 ? 1 : -1 });
      }
      if (t.decor === "water") {
        for (let i = 20; i < t.N; i += 95) {   // dock cranes on the verge
          const [nx, ny] = t.nrm(i), p = t.P[i], s = (i / 95) % 2 ? 1 : -1;
          add({ k: "box", x: p[0] + nx * s * (TW / 2 + 105), y: p[1] + ny * s * (TW / 2 + 105), w: 26, d: 26, h: 230, a: t.ANG[i], col: "#d18a2c", roof: "#f0a73e" });
        }
        for (let i = 0; i < 26; i++) {   // boats bobbing in the harbour
          const x = t.OX + rand() * t.WW, y = t.OY + rand() * t.WH;
          if (nearest(t, x, y, -1)[1] > TW / 2 + 190) add({ k: "boat", x, y, r: 16 + rand() * 18, a: rand() * 7, h: 6, col: ["#f2f2f2", "#d23c3c", "#ffd23a", "#2f7de1"][i % 4], ph: rand() * 6 });
        }
      }
      if (t.canal) for (const i of t.canal.cross) {   // bridges over the track where the canal crosses it: cars pass under
        add({ k: "box", x: t.P[i][0], y: t.P[i][1], w: 46, d: TW + 70, h: 22, a: t.ANG[i], col: "#8a7f72", roof: "#a79c8d", bridge: true });
      }
      if (t.decor === "rock") {   // a rock tunnel over the straightest stretch away from the start
        let best = 0, bestT = 9;
        for (let i = 60; i < t.N - 60; i += 3) { let turn = 0; for (let k = 0; k < 30; k += 3) turn = Math.max(turn, Math.abs(wrapA(t.ANG[(i + k) % t.N] - t.ANG[i]))); if (turn < bestT) { bestT = turn; best = i; } }
        t.tunnel = [best, best + 30];
        for (let i = best; i <= best + 30; i += 3) add({ k: "box", x: t.P[i % t.N][0], y: t.P[i % t.N][1], w: SP * 3 + 2, d: TW + 90, h: 38, a: t.ANG[i % t.N], col: "#6d665b", roof: i === best || i >= best + 29 ? "#5a544b" : "#7b7468", tunnel: true, ti: i });
      }
      if (t.decor === "city") for (let i = 40; i < t.N; i += 70) {   // festoon lights strung across the street
        const [nx, ny] = t.nrm(i), p = t.P[i];
        add({ k: "string", x: p[0], y: p[1], ax: p[0] + nx * (TW / 2 + 40), ay: p[1] + ny * (TW / 2 + 40), bx: p[0] - nx * (TW / 2 + 40), by: p[1] - ny * (TW / 2 + 40), h: 70, r: TW, cols: D.neon });
      }
      return props;
    }
    // Spectators: packed along the grandstand and behind the tyre walls at the hairpins; they bob, more as cars pass.
    function makeCrowd(t) {
      const rand = rng(t.key.length * 71 + 3), pts = [], add = (x, y) => pts.push(x, y, Math.floor(rand() * 7), rand() * 6);
      const [nx, ny] = t.nrm(8), p = t.P[8], cx0 = p[0] - nx * (TW / 2 + 120), cy0 = p[1] - ny * (TW / 2 + 120), ca = Math.cos(t.ANG[8]), sa = Math.sin(t.ANG[8]);
      for (let i = 0; i < 160; i++) { const u = (rand() - 0.5) * 250, v = 24 + rand() * 18; add(cx0 + u * ca + nx * v, cy0 + u * sa + ny * v); }   // in front of the stand
      for (let i = 0; i < t.N; i += 6) {
        const turn = wrapA(t.ANG[(i + 8) % t.N] - t.ANG[i]);
        if (Math.abs(turn) < 0.7 || rand() < 0.5) continue;
        const [mx, my] = t.nrm(i), s = turn > 0 ? -1 : 1;
        for (let k = 0; k < 26; k++) { const q = t.P[(i + Math.floor((rand() - 0.5) * 8) + t.N) % t.N], o = TW / 2 + 78 + rand() * 26; add(q[0] + mx * s * o, q[1] + my * s * o); }
      }
      return new Float32Array(pts);
    }
    const SHIRTS = ["#e9c44a", "#d23c3c", "#2f7de1", "#f2f2f2", "#1d9a6c", "#ef7d22", "#b36bff"];
    function drawCrowd(ctx, cx, cy, radius, time, dim) {
      const C = G.world.crowd, cars = G.race.cars, step = G.q.level > 0 ? 4 : 8;
      for (let i = 0; i < C.length; i += step) {
        const x = C[i], y = C[i + 1];
        if (Math.abs(x - cx) > radius || Math.abs(y - cy) > radius) continue;
        let near = 0; for (const c of cars) if (Math.abs(c.x - x) < 260 && Math.abs(c.y - y) < 260) { near = 1; break; }
        const b = Math.sin(time * (near ? 11 : 3) + C[i + 3]) * (near ? 2.2 : 0.7);
        ctx.fillStyle = shade(SHIRTS[C[i + 2]], dim); ctx.fillRect(x - 2.6, y - 2.6 + b, 5.2, 5.2);
        ctx.fillStyle = shade("#e0b48a", dim); ctx.fillRect(x - 1.6, y - 1.6 + b - 3, 3.2, 3.2);
      }
    }
    // Ambient traffic on Old Town's side streets (never on the race track), and birds over the park and the ridge.
    function makeTraffic(t) {
      const out = [];
      if (t.decor === "city") {
        const rand = rng(41);
        for (let k = 0; k < 40 && out.length < 9; k++) {
          const vert = rand() < 0.5, line = vert ? t.OX + 135 + Math.floor(rand() * (t.WW / 150)) * 150 : t.OY + 135 + Math.floor(rand() * (t.WH / 150)) * 150;
          const a0 = (vert ? t.OY : t.OX) + 100, a1 = (vert ? t.OY + t.WH : t.OX + t.WW) - 100;
          // keep only the stretch of this street that stays clear of the track
          let s0 = null, best = null;
          for (let u = a0; u <= a1; u += 40) {
            const x = vert ? line : u, y = vert ? u : line, ok = nearest(t, x, y, -1)[1] > TW / 2 + 110 && (!t.canal || Math.abs(canalY(t, x) - y) > 60);
            if (ok && s0 === null) s0 = u;
            if ((!ok || u + 40 > a1) && s0 !== null) { if (!best || u - s0 > best[1] - best[0]) best = [s0, u - 40]; s0 = null; }
          }
          if (best && best[1] - best[0] > 400) out.push({ vert, line, a0: best[0], a1: best[1], p: rand(), v: 0.04 + rand() * 0.05, dir: rand() < 0.5 ? 1 : -1, shape: ["sedan", "hatch", "kei", "wagon"][k % 4], color: ["#c9c3b5", "#3b5a7a", "#7a3b3b", "#2b2d31", "#d9b45f", "#4f7d5a"][k % 6] });
        }
      }
      return out;
    }
    function drawAmbient(ctx, dt, cx, cy, radius, lightsOn, time) {
      for (const v of G.world.traffic) {
        v.p += v.v * dt * v.dir; if (v.p > 1) { v.p = 1; v.dir = -1; } if (v.p < 0) { v.p = 0; v.dir = 1; }
        const u = v.a0 + (v.a1 - v.a0) * v.p, off = v.dir > 0 ? 14 : -14, x = v.vert ? v.line + off : u, y = v.vert ? u : v.line - off;
        if (Math.abs(x - cx) > radius || Math.abs(y - cy) > radius) continue;
        const a = v.vert ? (v.dir > 0 ? Math.PI / 2 : -Math.PI / 2) : (v.dir > 0 ? 0 : Math.PI);
        ctx.save(); ctx.translate(x, y); ctx.scale(0.8, 0.8); ctx.translate(-x, -y);
        drawCar(ctx, { x, y, a, color: v.color, shape: v.shape, num: "", look: { paint: v.color, number: " " } }, { lights: lightsOn });
        ctx.restore();
      }
      const t = G.world.t;
      if ((t.decor === "park" || t.decor === "rock") && G.q.level > 0) {   // a few birds wheeling overhead
        ctx.fillStyle = "rgba(20,20,24,0.7)";
        for (let i = 0; i < 7; i++) {
          const k = time * 0.06 + i * 0.9, bx = cx + Math.cos(k) * radius * 0.7 + Math.sin(i) * 40, by = cy + Math.sin(k * 1.3) * radius * 0.5 + i * 12, f = Math.sin(time * 9 + i) * 3;
          ctx.beginPath(); ctx.moveTo(bx - 5, by - f); ctx.lineTo(bx, by); ctx.lineTo(bx + 5, by - f); ctx.lineWidth = 1.5; ctx.strokeStyle = "rgba(20,20,24,0.75)"; ctx.stroke();
        }
      }
    }
    function puddlesOf(t) {   // puddles drawn live (so rain can arrive or clear during a race)
      if (t.puddles) return t.puddles;
      const rand = rng(t.key.length * 53 + 9), out = [];
      for (let i = 0; i < 110; i++) { const k = Math.floor(rand() * t.N), [nx, ny] = t.nrm(k), o = (rand() - 0.5) * TW * 0.8, p = t.P[k]; out.push([p[0] + nx * o, p[1] + ny * o, 12 + rand() * 26, 6 + rand() * 10, t.ANG[k]]); }
      return (t.puddles = out);
    }
    function canalY(t, x) { return t.OY + t.WH * 0.47 + Math.sin((x - t.OX) / 420) * 90; }
    function setupCanal(t) {
      if (t.decor !== "city" || t.canal) return;
      const cross = [];
      for (let i = 0; i < t.N; i++) {
        const a = t.P[i][1] - canalY(t, t.P[i][0]), b = t.P[(i + 1) % t.N][1] - canalY(t, t.P[(i + 1) % t.N][0]);
        if (a * b <= 0 && !cross.some((j) => Math.abs(j - i) < 20)) cross.push(i);
      }
      t.canal = { cross };
    }
    function setupPond(t) {   // the park's pond, in the biggest open space found
      if (t.decor !== "park" || t.pond !== undefined) return;
      let best = null;
      for (let gx = t.OX + 200; gx < t.OX + t.WW - 200; gx += 80) for (let gy = t.OY + 200; gy < t.OY + t.WH - 200; gy += 80) {
        const d = nearest(t, gx, gy, -1)[1] - TW / 2 - 60;
        if (d > 120 && (!best || d > best[2])) best = [gx, gy, d];
      }
      t.pond = best ? [best[0], best[1], Math.min(240, best[2] * 0.8)] : null;
    }
    function lampsOf(t) {
      if (t.lamps) return t.lamps;
      const out = [];
      for (let i = 3; i < t.N; i += 32) { const [nx, ny] = t.nrm(i), s = (i / 32) % 2 ? 1 : -1, p = t.P[i]; out.push([p[0] + nx * s * (TW / 2 + 22), p[1] + ny * s * (TW / 2 + 22)]); }
      return (t.lamps = out);
    }
    function noiseTile(seed, base, spread) {   // a small repeating asphalt texture
      const cv = doc.createElement("canvas"); cv.width = cv.height = 96;
      const g = cv.getContext("2d"), rand = rng(seed);
      g.fillStyle = base; g.fillRect(0, 0, 96, 96);
      for (let i = 0; i < 900; i++) { const v = (rand() - 0.5) * spread; g.fillStyle = v > 0 ? `rgba(255,255,255,${v})` : `rgba(0,0,0,${-v})`; g.fillRect(rand() * 96, rand() * 96, 1 + rand() * 1.6, 1 + rand() * 1.6); }
      return cv;
    }

    function paintWorld(t, tod, wet) {
      setupCanal(t); setupPond(t);
      const D = DECOR[t.decor] || DECOR.park, cv = doc.createElement("canvas"); cv.width = t.WW; cv.height = t.WH;
      const g = cv.getContext("2d"), P = t.P, rand = rng(t.key.length * 97 + 7), sun = SUN[tod] || SUN.day;
      g.translate(-t.OX, -t.OY);
      const path = () => { g.beginPath(); P.forEach(([x, y], i) => (i ? g.lineTo(x, y) : g.moveTo(x, y))); g.closePath(); };
      const offsetPath = (o) => { g.beginPath(); P.forEach((p, i) => { const [nx, ny] = t.nrm(i), x = p[0] + nx * o, y = p[1] + ny * o; i ? g.lineTo(x, y) : g.moveTo(x, y); }); g.closePath(); };
      g.lineJoin = "round"; g.lineCap = "round";
      if (D.sea) {
        g.fillStyle = D.sea; g.fillRect(t.OX, t.OY, t.WW, t.WH);
        path(); g.strokeStyle = "#2c86b5"; g.lineWidth = TW + 420; g.stroke();          // shallows
        path(); g.strokeStyle = "#e3d6a6"; g.lineWidth = TW + 330; g.stroke();          // sand
        path(); g.strokeStyle = D.ground; g.lineWidth = TW + 290; g.stroke();
        for (let i = 15; i < t.N; i += 120) {   // wooden piers out into the water
          const [nx, ny] = t.nrm(i), s = (i / 120) % 2 ? 1 : -1, p = t.P[i];
          g.save(); g.translate(p[0] + nx * s * (TW / 2 + 140), p[1] + ny * s * (TW / 2 + 140)); g.rotate(t.ANG[i]);
          g.fillStyle = "#7a5a3a"; g.fillRect(-14, s > 0 ? 0 : -150, 28, 150); g.fillStyle = "rgba(0,0,0,0.25)";
          for (let k = 0; k < 150; k += 10) g.fillRect(-14, (s > 0 ? 0 : -150) + k, 28, 1.5);
          g.restore();
        }
      } else {
        g.fillStyle = D.ground; g.fillRect(t.OX, t.OY, t.WW, t.WH);
        if (t.decor === "city") {   // paving slabs and a darker plaza grid
          g.strokeStyle = "rgba(0,0,0,0.13)"; g.lineWidth = 2;
          for (let x = t.OX; x < t.OX + t.WW; x += 60) { g.beginPath(); g.moveTo(x, t.OY); g.lineTo(x, t.OY + t.WH); g.stroke(); }
          for (let y = t.OY; y < t.OY + t.WH; y += 60) { g.beginPath(); g.moveTo(t.OX, y); g.lineTo(t.OX + t.WW, y); g.stroke(); }
        } else {
          g.fillStyle = D.stripe;   // mown stripes, then soft patches of light and shade
          for (let s = -t.WH; s < t.WW + t.WH; s += 120) { g.beginPath(); g.moveTo(t.OX + s, t.OY); g.lineTo(t.OX + s + 60, t.OY); g.lineTo(t.OX + s + 60 - t.WH, t.OY + t.WH); g.lineTo(t.OX + s - t.WH, t.OY + t.WH); g.fill(); }
          for (let i = 0; i < 320; i++) { const r = 30 + rand() * 90; g.fillStyle = rand() > 0.5 ? "rgba(255,255,190,0.045)" : "rgba(0,30,0,0.06)"; g.beginPath(); g.arc(t.OX + rand() * t.WW, t.OY + rand() * t.WH, r, 0, 7); g.fill(); }
          if (t.decor === "rock") for (let i = 0; i < 70; i++) { g.fillStyle = "rgba(90,80,60,0.18)"; g.beginPath(); g.ellipse(t.OX + rand() * t.WW, t.OY + rand() * t.WH, 40 + rand() * 120, 20 + rand() * 50, rand() * 3, 0, 7); g.fill(); }
        }
      }
      if (t.pond) {   // pond with reeds and a sandy rim
        const [px, py, pr] = t.pond;
        g.fillStyle = "#c9b98a"; g.beginPath(); g.ellipse(px, py, pr + 14, pr * 0.7 + 14, 0.3, 0, 7); g.fill();
        g.fillStyle = "#1f6f8f"; g.beginPath(); g.ellipse(px, py, pr, pr * 0.7, 0.3, 0, 7); g.fill();
        g.fillStyle = "#2c88a8"; g.beginPath(); g.ellipse(px - pr * 0.2, py - pr * 0.15, pr * 0.6, pr * 0.38, 0.3, 0, 7); g.fill();
      }
      if (t.decor === "park") for (let i = 0; i < 40; i++) {   // flower beds
        const x = t.OX + rand() * t.WW, y = t.OY + rand() * t.WH;
        if (nearest(t, x, y, -1)[1] < TW / 2 + 120) continue;
        const col = ["#ff5a8a", "#ffd23a", "#ffffff", "#b36bff"][i % 4];
        for (let k = 0; k < 18; k++) { g.fillStyle = col; g.beginPath(); g.arc(x + (rand() - 0.5) * 50, y + (rand() - 0.5) * 30, 2.2, 0, 7); g.fill(); }
      }
      if (t.canal) {   // canal water with stone banks
        g.beginPath(); for (let x = t.OX; x <= t.OX + t.WW; x += 20) (x === t.OX ? g.moveTo : g.lineTo).call(g, x, canalY(t, x));
        g.strokeStyle = "#7b746a"; g.lineWidth = 120; g.stroke(); g.strokeStyle = D.canal; g.lineWidth = 96; g.stroke();
      }
      path(); g.strokeStyle = t.decor === "city" ? "#8d8b86" : "#d1bf8f"; g.lineWidth = TW + 90; g.stroke();     // run-off: gravel, or a pavement in town
      if (t.decor !== "city") { for (let i = 0; i < t.N; i++) { const [nx, ny] = t.nrm(i), p = t.P[i]; for (let k = 0; k < 2; k++) { const o = (rand() > 0.5 ? 1 : -1) * (TW / 2 + 15 + rand() * 30); g.fillStyle = "rgba(90,70,40,0.25)"; g.fillRect(p[0] + nx * o, p[1] + ny * o, 2, 2); } } }
      // catch fence line at the back of the run-off
      for (const s of [-1, 1]) { offsetPath(s * (TW / 2 + 46)); g.strokeStyle = "rgba(30,32,36,0.55)"; g.lineWidth = 2; g.setLineDash([2, 6]); g.stroke(); g.setLineDash([]); }
      // kerbs with a bevel: white base, red blocks, light inner edge, dark outer edge
      path(); g.strokeStyle = "#f4f1ea"; g.lineWidth = TW + 22; g.stroke();
      path(); g.strokeStyle = "#d8322a"; g.setLineDash([22, 22]); g.stroke(); g.setLineDash([]);
      for (const s of [-1, 1]) { offsetPath(s * (TW / 2 + 10.5)); g.strokeStyle = "rgba(0,0,0,0.35)"; g.lineWidth = 1.5; g.stroke(); }
      // tarmac: a textured pattern, a rubbered racing line, edge lines
      const tile = noiseTile(t.key.length * 13, wet ? "#373c44" : "#43484f", 0.16);
      path(); g.strokeStyle = g.createPattern(tile, "repeat"); g.lineWidth = TW; g.stroke();
      path(); g.strokeStyle = "rgba(0,0,0,0.16)"; g.lineWidth = 52; g.stroke();
      path(); g.strokeStyle = "rgba(0,0,0,0.10)"; g.lineWidth = 22; g.stroke();
      path(); g.strokeStyle = "rgba(255,255,255,0.12)"; g.lineWidth = 3; g.setLineDash([30, 40]); g.stroke(); g.setLineDash([]);
      for (const s of [-1, 1]) { offsetPath(s * (TW / 2 - 6)); g.strokeStyle = "rgba(255,255,255,0.7)"; g.lineWidth = 2.5; g.stroke(); }
      // cracks and patches
      for (let i = 0; i < 70; i++) { const k = Math.floor(rand() * t.N), [nx, ny] = t.nrm(k), o = (rand() - 0.5) * TW * 0.8, p = t.P[k];
        g.fillStyle = "rgba(20,22,26,0.22)"; g.beginPath(); g.ellipse(p[0] + nx * o, p[1] + ny * o, 8 + rand() * 18, 4 + rand() * 8, t.ANG[k] + rand(), 0, 7); g.fill(); }
      if (wet) {   // puddles and a cold sheen
        path(); g.strokeStyle = "rgba(120,150,190,0.10)"; g.lineWidth = TW; g.stroke();
        for (let i = 0; i < 110; i++) { const k = Math.floor(rand() * t.N), [nx, ny] = t.nrm(k), o = (rand() - 0.5) * TW * 0.8, p = t.P[k];
          g.fillStyle = "rgba(160,185,220,0.2)"; g.beginPath(); g.ellipse(p[0] + nx * o, p[1] + ny * o, 12 + rand() * 26, 6 + rand() * 10, t.ANG[k], 0, 7); g.fill(); }
      }
      // tyre walls on the outside of the tightest bends
      for (let i = 0; i < t.N; i += 6) {
        const turn = wrapA(t.ANG[(i + 8) % t.N] - t.ANG[i]);
        if (Math.abs(turn) < 0.55) continue;
        const [nx, ny] = t.nrm(i), s = turn > 0 ? -1 : 1;
        for (let k = -1; k <= 1; k++) { const q = t.P[(i + k + t.N) % t.N];
          for (let r = 0; r < 2; r++) { const x = q[0] + nx * s * (TW / 2 + 52 + r * 13), y = q[1] + ny * s * (TW / 2 + 52 + r * 13);
            g.fillStyle = "#18191b"; g.beginPath(); g.arc(x, y, 7, 0, 7); g.fill(); g.fillStyle = (i / 6 + k + r) % 2 ? "#d3372b" : "#eeeeee"; g.beginPath(); g.arc(x, y, 3, 0, 7); g.fill(); } }
      }
      // braking boards and painted arrows before the tight bends
      for (let i = 0; i < t.N; i += 9) {
        const turn = wrapA(t.ANG[(i + 20) % t.N] - t.ANG[(i + 8) % t.N]);
        if (Math.abs(turn) < 0.6) continue;
        const p = t.P[i]; g.save(); g.translate(p[0], p[1]); g.rotate(t.ANG[i] + Math.PI / 2 * 0);
        g.fillStyle = "rgba(255,255,255,0.22)"; g.beginPath(); g.moveTo(10, 0); g.lineTo(-6, -8); g.lineTo(-6, 8); g.closePath(); g.fill(); g.restore();
      }
      g.save(); g.translate(P[0][0], P[0][1]); g.rotate(t.ANG[0]);
      for (let r = 0; r < 2; r++) for (let c = 0; c < Math.ceil(TW / 10); c++) { g.fillStyle = (r + c) % 2 ? "#111" : "#fafafa"; g.fillRect(-10 + r * 10, -TW / 2 + c * 10, 10, 10); }
      g.restore();
      for (const s of t.slots(6)) {
        g.save(); g.translate(s.x, s.y); g.rotate(s.a); g.strokeStyle = "rgba(255,255,255,0.8)"; g.lineWidth = 3;
        g.beginPath(); g.moveTo(28, -16); g.lineTo(28, 16); g.moveTo(28, -16); g.lineTo(10, -16); g.moveTo(28, 16); g.lineTo(10, 16); g.stroke(); g.restore();
      }
      for (const [x, y] of lampsOf(t)) { g.fillStyle = "#2b2d31"; g.beginPath(); g.arc(x, y, 4, 0, 7); g.fill(); }
      // ground shadows of every tall object, cast by the sun for this time of day (long at dusk and dawn)
      g.fillStyle = tod === "night" ? "rgba(0,0,0,0.16)" : "rgba(10,20,40,0.26)";
      for (const p of t.props) {
        if (p.k === "string" || p.k === "boat") continue;
        const sx = sun[0] * p.h * 0.5, sy = sun[1] * p.h * 0.5;
        if (p.k === "box") {
          const pts = boxBase(p), hull = pts.concat(pts.map(([x, y]) => [x + sx, y + sy]));
          hull.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
          g.beginPath(); convex(hull).forEach(([x, y], i) => (i ? g.lineTo(x, y) : g.moveTo(x, y))); g.closePath(); g.fill();
        } else { g.beginPath(); g.ellipse(p.x + sx * 0.6, p.y + sy * 0.6, p.r * 1.05, p.r * 0.9, 0, 0, 7); g.fill(); }
      }
      return cv;
    }
    function boxBase(p) {
      const c = Math.cos(p.a), s = Math.sin(p.a), hw = p.w / 2, hd = p.d / 2;
      return [[-hw, -hd], [hw, -hd], [hw, hd], [-hw, hd]].map(([u, v]) => [p.x + u * c - v * s, p.y + u * s + v * c]);
    }
    function convex(pts) {   // monotone chain hull of sorted points
      const cross = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
      const lo = [], hi = [];
      for (const p of pts) { while (lo.length >= 2 && cross(lo[lo.length - 2], lo[lo.length - 1], p) <= 0) lo.pop(); lo.push(p); }
      for (let i = pts.length - 1; i >= 0; i--) { const p = pts[i]; while (hi.length >= 2 && cross(hi[hi.length - 2], hi[hi.length - 1], p) <= 0) hi.pop(); hi.push(p); }
      return lo.slice(0, -1).concat(hi.slice(0, -1));
    }
    const shadeCache = {};
    const shade = (hex, f) => {
      const k = hex + f.toFixed(2); if (shadeCache[k]) return shadeCache[k];
      const n = parseInt(hex.slice(1), 16), r = n >> 16, g2 = (n >> 8) & 255, b = n & 255, m = (v) => Math.max(0, Math.min(255, Math.round(v * f)));
      return (shadeCache[k] = `rgb(${m(r)},${m(g2)},${m(b)})`);
    };

    // Draw tall scenery in 2.5D. Emissive bits (lit windows, neon, signs, bulbs) are collected for the glow pass.
    function drawProps(ctx, cx, cy, radius, tod, time, glow) {
      const props = G.world.props, k = 0.0011, list = [], night = tod === "night", dusk = tod === "dusk";
      for (const p of props) { const m = (p.w || p.r * 2 || 40) + p.h + (p.r || 0); if (Math.abs(p.x - cx) < radius + m && Math.abs(p.y - cy) < radius + m) list.push(p); }
      list.sort((a, b) => ((b.x - cx) ** 2 + (b.y - cy) ** 2) - ((a.x - cx) ** 2 + (a.y - cy) ** 2));
      const dim = night ? 0.5 : dusk ? 0.82 : tod === "dawn" ? 0.9 : 1, q = G.q.level;
      const me = G.race.cars[0], inT = G.world.t.tunnel && me && ((me.idx - G.world.t.tunnel[0] + G.world.t.N) % G.world.t.N) <= 32;
      G.inTunnel = !!inT && G.mode === "race";
      for (const p of list) {
        const lean = p.h * k;
        if (p.tunnel) ctx.globalAlpha = G.inTunnel ? 0.3 : 0.97;
        if (p.k === "box") {
          const B = boxBase(p), T = B.map(([x, y]) => [x + (x - cx) * lean, y + (y - cy) * lean]);
          for (let i = 0; i < 4; i++) {
            const a = B[i], b = B[(i + 1) % 4], mx = (a[0] + b[0]) / 2, my = (a[1] + b[1]) / 2;
            const nx = b[1] - a[1], ny = -(b[0] - a[0]), ox = mx - p.x, oy = my - p.y, flip = nx * ox + ny * oy < 0 ? -1 : 1;
            if ((nx * flip) * (cx - mx) + (ny * flip) * (cy - my) <= 0) continue;   // face turned away from the viewer
            const lit = 0.58 + 0.3 * Math.abs(nx * flip * 0.6 + ny * flip * 0.8) / Math.hypot(nx, ny);
            const ta = T[i], tb = T[(i + 1) % 4];
            ctx.fillStyle = shade(p.col, lit * dim);
            ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.lineTo(tb[0], tb[1]); ctx.lineTo(ta[0], ta[1]); ctx.closePath(); ctx.fill();
            if (p.windows && p.h > 60 && q > 0) {   // windows, lit at night (and glowing in the glow pass)
              ctx.fillStyle = night ? "rgba(255,214,140,0.7)" : dusk ? "rgba(255,200,120,0.35)" : "rgba(40,60,85,0.45)";
              const fs = q > 1 ? 0.22 : 0.34;   // fewer window rows below High quality
              for (let f = 0.25; f < 0.95; f += fs) for (let s = 0.2; s < 0.9; s += 0.3) {
                const qx = a[0] + (b[0] - a[0]) * s, qy = a[1] + (b[1] - a[1]) * s, wx = qx + (qx - cx) * lean * f, wy = qy + (qy - cy) * lean * f;
                ctx.fillRect(wx - 3, wy - 3, 6, 5);
                if (night && glow && q > 1 && ((s * 10 + f * 7 + p.x) | 0) % 3 === 0) glow.push([wx, wy, 9, "rgba(255,200,120,0.5)"]);
              }
            }
          }
          ctx.fillStyle = shade(p.roof, dim);
          ctx.beginPath(); T.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y))); ctx.closePath(); ctx.fill();
          if (p.board) {   // billboard face: an affine map from a unit box onto the leaning face
            const a = B[p.face > 0 ? 3 : 0], b = B[p.face > 0 ? 2 : 1], ta = T[p.face > 0 ? 3 : 0];
            ctx.save(); ctx.transform(b[0] - a[0], b[1] - a[1], ta[0] - a[0], ta[1] - a[1], a[0], a[1]);
            ctx.fillStyle = shade(p.board[1], dim > 0.6 ? 1 : 0.85); ctx.fillRect(0.02, 0.08, 0.96, 0.84);
            ctx.restore();
            const mx = (a[0] + b[0] + ta[0] * 2) / 4 + (b[0] - a[0]) * 0.0, my = (a[1] + b[1] + ta[1] * 2) / 4;
            ctx.save(); ctx.translate((a[0] + b[0]) / 2 + (ta[0] - a[0]) * 0.5, (a[1] + b[1]) / 2 + (ta[1] - a[1]) * 0.5); ctx.rotate(Math.atan2(b[1] - a[1], b[0] - a[0]));
            ctx.fillStyle = p.board[2]; ctx.font = '700 15px "Rajdhani", system-ui, sans-serif'; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(p.board[0], 0, 0); ctx.restore();
            if ((night || dusk) && glow) glow.push([mx, my, 70, p.board[1] + "88"]);
          }
          if (p.chevron) {
            const a = T[0], b = T[1];
            ctx.fillStyle = "#1d1d1f";
            for (let s = 0.15; s < 0.9; s += 0.24) { const x = a[0] + (b[0] - a[0]) * s, y = a[1] + (b[1] - a[1]) * s; ctx.beginPath(); ctx.arc(x, y, 2.4, 0, 7); ctx.fill(); }
            if ((night || G.race.fogness > 0.3) && glow) glow.push([(a[0] + b[0]) / 2, (a[1] + b[1]) / 2, 22, "rgba(255,210,58,0.55)"]);
          }
          if (p.neon && q > 0) {   // a neon strip along the roof edge
            ctx.strokeStyle = night ? p.neon : shade(p.neon, 0.7); ctx.lineWidth = 2.5; ctx.beginPath(); ctx.moveTo(T[0][0], T[0][1]); ctx.lineTo(T[1][0], T[1][1]); ctx.stroke();
            if ((night || dusk) && glow) glow.push([(T[0][0] + T[1][0]) / 2, (T[0][1] + T[1][1]) / 2, 60, p.neon + "99"]);
          }
          if (p.plinth) { const mx = T.reduce((a, q) => a + q[0], 0) / 4, my = T.reduce((a, q) => a + q[1], 0) / 4; ctx.save(); ctx.translate(mx, my); ctx.rotate(p.a); ctx.fillStyle = "rgba(20,16,10,0.85)"; ctx.font = '700 22px "Rajdhani", system-ui, sans-serif'; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(String(p.plinth), 0, 0); ctx.restore(); }
          if (p.stand) { ctx.fillStyle = "rgba(255,255,255,0.3)"; const q0 = T[0], r = T[3]; for (let s = 0.1; s <= 0.9; s += 0.08) { const x = q0[0] + (r[0] - q0[0]) * s, y = q0[1] + (r[1] - q0[1]) * s; ctx.fillStyle = ["#e9c44a", "#ffffff", "#d23c3c", "#2f7de1"][(s * 50 | 0) % 4]; ctx.fillRect(x - 2, y - 2, 4, 4); } }
          ctx.globalAlpha = 1;
          if (p.bridge) { ctx.strokeStyle = shade("#5f574e", dim); ctx.lineWidth = 4; ctx.beginPath(); ctx.moveTo(T[0][0], T[0][1]); ctx.lineTo(T[1][0], T[1][1]); ctx.moveTo(T[2][0], T[2][1]); ctx.lineTo(T[3][0], T[3][1]); ctx.stroke(); }
          if (p.tunnel && glow && q > 0 && (p.ti / 3) % 2 === 0) {   // sodium lights along the tunnel walls
            for (const e of [[T[0], T[1]], [T[3], T[2]]]) { const x = (e[0][0] + e[1][0]) / 2, y = (e[0][1] + e[1][1]) / 2; glow.push([x, y, 30, "rgba(255,170,70,0.75)"]); }
          }
          if (p.gantry) {   // five start lights on the gantry, in step with the countdown
            const r = G.race, lit = r.state === "lights" ? Math.min(5, Math.floor(r.lightsT / 0.7)) : 0, a = T[1], b = T[2];
            for (let i = 0; i < 5; i++) { const s = 0.3 + i * 0.1, x = a[0] + (b[0] - a[0]) * s, y = a[1] + (b[1] - a[1]) * s;
              ctx.fillStyle = i < lit ? "#ff2a2a" : r.state === "race" && r.t < 2 ? "#3cff6a" : "#3a2020"; ctx.beginPath(); ctx.arc(x, y, 3.2, 0, 7); ctx.fill();
              if (glow && (i < lit || (r.state === "race" && r.t < 2))) glow.push([x, y, 26, i < lit ? "rgba(255,40,40,0.9)" : "rgba(60,255,106,0.8)"]); }
          }
        } else if (p.k === "string") {   // festoon lights: a sagging line of bulbs above the cars
          const top = (x, y, f) => [x + (x - cx) * lean * f, y + (y - cy) * lean * f];
          ctx.strokeStyle = "rgba(20,20,20,0.7)"; ctx.lineWidth = 1; ctx.beginPath();
          const pts = [];
          for (let s = 0; s <= 1.001; s += 0.1) { const x = p.ax + (p.bx - p.ax) * s, y = p.ay + (p.by - p.ay) * s, sag = 1 - 0.35 * Math.sin(Math.PI * s); pts.push(top(x, y, sag)); }
          pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y))); ctx.stroke();
          pts.forEach(([x, y], i) => { const col = p.cols[i % p.cols.length]; ctx.fillStyle = night || dusk ? col : shade(col, 0.75); ctx.beginPath(); ctx.arc(x, y, 2.4, 0, 7); ctx.fill(); if ((night || dusk) && glow) glow.push([x, y, 16, col + "aa"]); });
        } else if (p.k === "boat") {
          const bob = Math.sin(time * 1.4 + p.ph) * 0.06;
          ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.a + bob);
          ctx.fillStyle = "rgba(0,0,0,0.2)"; ctx.beginPath(); ctx.ellipse(4, 5, p.r, p.r * 0.38, 0, 0, 7); ctx.fill();
          ctx.fillStyle = shade(p.col, dim); ctx.beginPath(); ctx.moveTo(p.r, 0); ctx.quadraticCurveTo(p.r * 0.2, -p.r * 0.42, -p.r, -p.r * 0.32); ctx.lineTo(-p.r, p.r * 0.32); ctx.quadraticCurveTo(p.r * 0.2, p.r * 0.42, p.r, 0); ctx.fill();
          ctx.fillStyle = shade("#e8e2d0", dim); ctx.fillRect(-p.r * 0.45, -p.r * 0.18, p.r * 0.6, p.r * 0.36);
          ctx.restore();
          if (night && glow) glow.push([p.x, p.y, 12, "rgba(255,230,170,0.6)"]);
        } else {
          const tx = p.x + (p.x - cx) * lean, ty = p.y + (p.y - cy) * lean, mx = p.x + (p.x - cx) * lean * 0.55, my = p.y + (p.y - cy) * lean * 0.55;
          if (p.k === "rock") {
            ctx.fillStyle = shade(p.c[0], dim); ctx.beginPath(); ctx.ellipse(mx, my, p.r, p.r * 0.85, 0, 0, 7); ctx.fill();
            ctx.fillStyle = shade(p.c[1], dim); ctx.beginPath(); ctx.ellipse(tx, ty, p.r * 0.8, p.r * 0.68, 0, 0, 7); ctx.fill();
            ctx.fillStyle = shade(p.c[2], dim); ctx.beginPath(); ctx.ellipse(tx - p.r * 0.25, ty - p.r * 0.25, p.r * 0.35, p.r * 0.28, 0, 0, 7); ctx.fill();
          } else if (p.k === "pine") {   // stacked tiers of a conifer
            for (let s = 0; s < 3; s++) {
              const f = 0.35 + s * 0.32, x = p.x + (p.x - cx) * lean * f, y = p.y + (p.y - cy) * lean * f, r = p.r * (1.15 - s * 0.3);
              ctx.fillStyle = shade(p.c[s], dim); ctx.beginPath();
              for (let j = 0; j < 7; j++) { const a = j / 7 * 6.283 + s, rr2 = j % 2 ? r * 0.7 : r; ctx.lineTo(x + Math.cos(a) * rr2, y + Math.sin(a) * rr2); }
              ctx.closePath(); ctx.fill();
            }
          } else {
            const sway = G.race.wetness > 0.5 ? Math.sin(time * 2 + p.x) * 1.5 : Math.sin(time * 0.8 + p.x) * 0.6;
            ctx.fillStyle = shade(p.c[0], dim); ctx.beginPath(); ctx.arc(mx, my, p.r, 0, 7); ctx.fill();
            ctx.fillStyle = shade(p.c[1], dim); ctx.beginPath(); ctx.arc(tx + sway, ty, p.r * 0.78, 0, 7); ctx.fill();
            if (q > 1) { ctx.fillStyle = shade(p.c[2], dim); ctx.beginPath(); ctx.arc(tx - p.r * 0.22 + sway, ty - p.r * 0.25, p.r * 0.38, 0, 7); ctx.fill(); }
          }
        }
      }
    }

    // Soft glows are pre-rendered once per colour and stamped with drawImage (far cheaper than a gradient per light).
    const glowCache = new Map();
    function glowSprite(col) {
      let cv = glowCache.get(col);
      if (cv) return cv;
      cv = doc.createElement("canvas"); cv.width = cv.height = 64;
      const g = cv.getContext("2d"), gr = g.createRadialGradient(32, 32, 0, 32, 32, 32);
      gr.addColorStop(0, col); gr.addColorStop(0.4, col.length === 9 ? col.slice(0, 7) + "55" : col.replace(/[\d.]+\)$/, "0.35)")); gr.addColorStop(1, "rgba(0,0,0,0)");
      g.fillStyle = gr; g.fillRect(0, 0, 64, 64);
      glowCache.set(col, cv); return cv;
    }
    // Which world cells are water (asked once per 90-unit cell, then remembered).
    function isWater(t, D, x, y) {
      const key = ((x / 90) | 0) * 100003 + ((y / 90) | 0), m = t.water || (t.water = new Map());
      let v = m.get(key);
      if (v === undefined) {
        v = D.sea ? nearest(t, x, y, -1)[1] > TW / 2 + 160 : t.pond ? Math.hypot((x - t.pond[0]) / t.pond[2], (y - t.pond[1]) / (t.pond[2] * 0.7)) < 0.9 : !!t.canal && Math.abs(canalY(t, x) - y) < 40;
        m.set(key, v);
      }
      return v;
    }

    // ---------------------------------------------------------------- Cars: cached sprites + live parts
    const SHAPES = {
      open(ctx, w) { ctx.beginPath(); ctx.moveTo(-22, -9 - w); ctx.lineTo(14, -8); ctx.quadraticCurveTo(24, -5, 24, 0); ctx.quadraticCurveTo(24, 5, 14, 8); ctx.lineTo(-22, 9 + w); ctx.closePath(); },
      gt(ctx, w) { rr(ctx, -23, -11 - w, 47, 22 + 2 * w, 7); },
      rally(ctx, w) { rr(ctx, -20, -11 - w, 41, 22 + 2 * w, 4); },
      muscle(ctx, w) { rr(ctx, -25, -12 - w, 51, 24 + 2 * w, 5); },
      proto(ctx, w) { ctx.beginPath(); ctx.moveTo(-24, -11 - w); ctx.lineTo(8, -10 - w); ctx.lineTo(26, -3); ctx.lineTo(26, 3); ctx.lineTo(8, 10 + w); ctx.lineTo(-24, 11 + w); ctx.closePath(); },
      hatch(ctx, w) { rr(ctx, -19, -11 - w, 38, 22 + 2 * w, 6); },
      kei(ctx, w) { rr(ctx, -16, -10 - w, 32, 20 + 2 * w, 4); },
      sedan(ctx, w) { rr(ctx, -24, -11 - w, 48, 22 + 2 * w, 5); },
      wagon(ctx, w) { rr(ctx, -25, -11 - w, 50, 22 + 2 * w, 4); },
      roadster(ctx, w) { rr(ctx, -21, -10 - w, 43, 20 + 2 * w, 8); },
      coupe(ctx, w) { ctx.beginPath(); ctx.moveTo(-23, -10 - w); ctx.lineTo(10, -11 - w); ctx.quadraticCurveTo(25, -9, 25, 0); ctx.quadraticCurveTo(25, 9, 10, 11 + w); ctx.lineTo(-23, 10 + w); ctx.quadraticCurveTo(-25, 0, -23, -10 - w); ctx.closePath(); },
      super(ctx, w) { ctx.beginPath(); ctx.moveTo(-24, -12 - w); ctx.lineTo(2, -12.5 - w); ctx.lineTo(20, -8); ctx.lineTo(27, -3); ctx.lineTo(27, 3); ctx.lineTo(20, 8); ctx.lineTo(2, 12.5 + w); ctx.lineTo(-24, 12 + w); ctx.lineTo(-26, 0); ctx.closePath(); },
    };
    const CABIN = { open: [-6, 0, 7, 5, "e"], gt: [-4, 0, 11, 8, "r"], rally: [-4, 0, 12, 9, "r"], muscle: [-6, 0, 10, 8, "r"], proto: [0, 0, 10, 6, "e"],
      hatch: [-2, 0, 11, 9, "r"], kei: [0, 0, 10, 8.5, "r"], sedan: [-3, 0, 13, 9, "r"], wagon: [-6, 0, 16, 9, "r"], roadster: [-5, 0, 7, 7, "o"], coupe: [-5, 0, 10, 8, "r"], super: [-2, 0, 9, 7, "r"] };
    const ENDS = { open: [-23, 23], gt: [-23, 24], rally: [-20, 21], muscle: [-25, 26], proto: [-24, 26], hatch: [-19, 19], kei: [-16, 16], sedan: [-24, 24], wagon: [-25, 25], roadster: [-21, 22], coupe: [-23, 25], super: [-25, 27] };
    function rr(ctx, x, y, w, h, r) { ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r); ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath(); }
    const SS = 3, SW = 64, SH = 44, sprites = new Map();
    // The body, glass, livery, number and wings, drawn once per look at 3× and reused.
    function sprite(shape, L, color, num) {
      const key = [shape, L.paint || color, L.paint2, L.decal, L.body, L.spoiler, L.number || num, L.finish, L.tint, L.exhaust, L.numpos, L.livery].join("|");
      let cv = sprites.get(key);
      if (cv) return cv;
      if (sprites.size > 80) sprites.clear();
      cv = doc.createElement("canvas"); cv.width = SW * SS; cv.height = SH * SS;
      const g = cv.getContext("2d"), paint = L.paint || color, wide = L.body === "wide" ? 2 : 0;
      g.setTransform(SS, 0, 0, SS, SW / 2 * SS, SH / 2 * SS);
      SHAPES[shape](g, wide); g.fillStyle = paint; g.fill();
      if (shape === "open") { g.fillStyle = paint; g.fillRect(-24, -12, 6, 24); g.fillRect(18, -11, 4, 22); }
      // shading: a highlight down the spine, darker flanks, a hint of sky on top
      g.save(); SHAPES[shape](g, wide); g.clip();
      // paint finish: gloss (a bright spine), metallic (sparkle and a sharper highlight), matte (flat), pearl (a colour shift)
      const fin = L.finish || "gloss", hi = fin === "matte" ? 0.08 : fin === "metallic" ? 0.42 : 0.32;
      const lg = g.createLinearGradient(0, -13, 0, 13);
      lg.addColorStop(0, `rgba(0,0,0,${fin === "matte" ? 0.22 : 0.32})`); lg.addColorStop(0.28, "rgba(255,255,255,0.05)"); lg.addColorStop(0.45, `rgba(255,255,255,${hi})`);
      lg.addColorStop(0.6, "rgba(255,255,255,0.06)"); lg.addColorStop(1, `rgba(0,0,0,${fin === "matte" ? 0.28 : 0.38})`);
      g.fillStyle = lg; g.fillRect(-30, -16, 60, 32);
      if (fin === "metallic") { const rr2 = rng(7); g.fillStyle = "rgba(255,255,255,0.22)"; for (let i = 0; i < 70; i++) g.fillRect(-26 + rr2() * 52, -13 + rr2() * 26, 0.5, 0.5); }
      if (fin === "pearl") { const pg = g.createLinearGradient(-26, -13, 26, 13); pg.addColorStop(0, "rgba(120,200,255,0.16)"); pg.addColorStop(0.5, "rgba(255,255,255,0)"); pg.addColorStop(1, "rgba(255,120,220,0.16)"); g.fillStyle = pg; g.fillRect(-30, -16, 60, 32); }
      const fg = g.createLinearGradient(-26, 0, 26, 0); fg.addColorStop(0, "rgba(0,0,0,0.18)"); fg.addColorStop(0.5, "rgba(0,0,0,0)"); fg.addColorStop(1, "rgba(255,255,255,0.10)");
      g.fillStyle = fg; g.fillRect(-30, -16, 60, 32);
      // livery
      const dec = L.decal;
      const p2 = L.paint2 && L.paint2 !== "#14100a" ? L.paint2 : null;   // the second livery colour, if chosen
      if (dec === "stripe") { g.fillStyle = p2 || "rgba(255,255,255,0.88)"; g.fillRect(-26, -3.5, 52, 2.2); g.fillRect(-26, 1.3, 52, 2.2); }
      else if (dec === "hoops") { g.fillStyle = p2 || "rgba(255,255,255,0.85)"; g.fillRect(-6, -14, 4, 28); g.fillRect(4, -14, 2, 28); }
      else if (dec === "sash") { g.fillStyle = p2 || "#14161a"; g.beginPath(); g.moveTo(-26, -14); g.lineTo(-14, -14); g.lineTo(14, 14); g.lineTo(2, 14); g.closePath(); g.fill(); }
      else if (dec === "flame") { g.fillStyle = "#ff7a1a"; g.beginPath(); g.moveTo(26, -8); g.lineTo(4, -4); g.lineTo(12, -1); g.lineTo(0, 0); g.lineTo(12, 1); g.lineTo(4, 4); g.lineTo(26, 8); g.closePath(); g.fill(); g.fillStyle = "#ffd23a"; g.beginPath(); g.moveTo(26, -4); g.lineTo(10, 0); g.lineTo(26, 4); g.fill(); }
      else if (dec === "checker") { for (let i = 0; i < 5; i++) for (let j = 0; j < 3; j++) if ((i + j) % 2) { g.fillStyle = "rgba(20,20,20,0.75)"; g.fillRect(6 + i * 3.5, -5 + j * 3.5, 3.5, 3.5); } }
      else if (dec === "bolt") { g.fillStyle = "#ffe14a"; g.beginPath(); g.moveTo(-18, -6); g.lineTo(0, -1); g.lineTo(-4, 1); g.lineTo(16, 6); g.lineTo(-2, 2.5); g.lineTo(2, 0); g.closePath(); g.fill(); }
      // panel lines
      g.strokeStyle = "rgba(0,0,0,0.25)"; g.lineWidth = 0.5;
      g.beginPath(); g.moveTo(10, -12); g.lineTo(10, 12); g.moveTo(-12, -12); g.lineTo(-12, 12); g.stroke();
      g.restore();
      // cabin glass with a reflection streak
      const cb = CABIN[shape];
      const glass = (root.KerbsideData && root.KerbsideData.LOOKS.tint[L.tint] || {}).color || "#0b1220";
      if (cb[4] === "e") { g.fillStyle = glass; g.beginPath(); g.ellipse(cb[0], cb[1], cb[2], cb[3], 0, 0, 7); g.fill(); }
      else if (cb[4] === "o") {   // open two-seater: interior, two seats, a windscreen
        g.fillStyle = "#1a1512"; rr(g, cb[0] - cb[2], -cb[3], cb[2] * 2, cb[3] * 2, 3); g.fill();
        g.fillStyle = "#3a2a22"; g.beginPath(); g.ellipse(cb[0] - 1, -3.4, 3.4, 2.6, 0, 0, 7); g.ellipse(cb[0] - 1, 3.4, 3.4, 2.6, 0, 0, 7); g.fill();
        g.strokeStyle = "rgba(180,220,255,0.7)"; g.lineWidth = 1.2; g.beginPath(); g.moveTo(cb[0] + cb[2], -cb[3]); g.quadraticCurveTo(cb[0] + cb[2] + 2, 0, cb[0] + cb[2], cb[3]); g.stroke();
      }
      else {
        g.fillStyle = glass; rr(g, cb[0] - cb[2], -cb[3], cb[2] * 2, cb[3] * 2, 3); g.fill();
        g.fillStyle = paint; rr(g, cb[0] - cb[2] + 4, -cb[3] + 1.6, cb[2] * 2 - 8, cb[3] * 2 - 3.2, 2); g.fill();
        g.fillStyle = "rgba(255,255,255,0.18)"; rr(g, cb[0] - cb[2] + 4, -cb[3] + 1.6, cb[2] * 2 - 8, cb[3] - 1.6, 2); g.fill();
      }
      g.strokeStyle = "rgba(180,220,255,0.5)"; g.lineWidth = 0.8; g.beginPath(); g.moveTo(cb[0] + cb[2] - 2, -cb[3] + 1.5); g.lineTo(cb[0] + cb[2] - 4, cb[3] - 1.5); g.stroke();
      // shape details: intakes on supercars, a bonnet scoop on muscle cars, a roof vent on rally cars, police livery
      if (shape === "super") { g.fillStyle = "rgba(0,0,0,0.6)"; g.beginPath(); g.moveTo(-8, -12.5); g.lineTo(-2, -9); g.lineTo(-12, -9); g.closePath(); g.moveTo(-8, 12.5); g.lineTo(-2, 9); g.lineTo(-12, 9); g.closePath(); g.fill(); }
      if (shape === "muscle") { g.fillStyle = "rgba(0,0,0,0.45)"; rr(g, 10, -3, 8, 6, 1.5); g.fill(); }
      if (shape === "rally" || shape === "hatch") { g.fillStyle = "rgba(0,0,0,0.35)"; g.fillRect(-6, -2.5, 4, 5); }
      if (L.livery === "police") { g.fillStyle = "#f4f4f4"; g.fillRect(-12, -12, 22, 24); g.fillStyle = "#14161a"; g.fillRect(-11, -1.2, 20, 2.4); }
      // spoiler
      if (L.spoiler === "duck" && shape !== "open") { g.fillStyle = shade(/^#[0-9a-f]{6}$/i.test(paint) ? paint : "#888888", 0.75); g.beginPath(); g.moveTo(ENDS[shape][0] + 1, -10); g.quadraticCurveTo(ENDS[shape][0] - 3, 0, ENDS[shape][0] + 1, 10); g.lineTo(ENDS[shape][0] + 4, 10); g.lineTo(ENDS[shape][0] + 4, -10); g.fill(); }
      // exhaust tips at the rear
      const ex = { single: [6], dual: [-6, 6], quad: [-7, -4, 4, 7] }[L.exhaust || "single"] || [6];
      g.fillStyle = "#2a2a2c"; for (const y of ex) { g.beginPath(); g.arc(ENDS[shape][0] - 0.5, y, 1.4, 0, 7); g.fill(); g.fillStyle = "#8a8d92"; g.beginPath(); g.arc(ENDS[shape][0] - 0.5, y, 0.8, 0, 7); g.fill(); g.fillStyle = "#2a2a2c"; }
      if (L.spoiler === "high" || (shape !== "open" && L.spoiler === "low")) {
        const x = L.spoiler === "high" ? -28 : -24.5, w2 = L.spoiler === "high" ? 5 : 3;
        g.fillStyle = shade(/^#[0-9a-f]{6}$/i.test(paint) ? paint : "#888888", 0.55); g.fillRect(x, -12 - wide, w2, 24 + 2 * wide);
        g.fillStyle = "rgba(255,255,255,0.25)"; g.fillRect(x, -12 - wide, w2, 1);
      }
      // number roundel: on the bonnet (or a single-seater's side pod), on the roof, or none
      if (L.numpos !== "none") { g.save(); g.translate(shape === "open" ? -13 : L.numpos === "roof" && cb[4] === "r" ? cb[0] : 13, 0); g.rotate(Math.PI / 2);
      g.fillStyle = "rgba(255,255,255,0.9)"; g.beginPath(); g.arc(0, 0, 5, 0, 7); g.fill();
      g.fillStyle = "#14120f"; g.font = '700 7.5px "Rajdhani", system-ui, sans-serif'; g.textAlign = "center"; g.textBaseline = "middle"; g.fillText(String(L.number || num), 0, 0.4); g.restore(); }
      // outline for definition at a distance
      SHAPES[shape](g, wide); g.strokeStyle = "rgba(10,10,12,0.75)"; g.lineWidth = 0.9; g.stroke();
      sprites.set(key, cv);
      return cv;
    }

    function drawCar(ctx, c, o = {}) {
      const L = c.look || {}, shape = SHAPES[c.shape] ? c.shape : "open", wide = L.body === "wide" ? 2 : 0, paint = L.paint || c.color;
      const wcol = (root.KerbsideData && root.KerbsideData.LOOKS.wheels[L.wheels] || {}).color || "#5a5e64";
      const sp = sprite(shape, L, c.color, c.num), [rear, nose] = ENDS[shape];
      ctx.save(); ctx.translate(c.x, c.y); ctx.rotate(c.a);
      if (o.ghost) ctx.globalAlpha = 0.4;
      if (c.out) ctx.globalAlpha = 0.35;
      // soft shadow, offset by the sun
      if (!o.ghost) { ctx.fillStyle = "rgba(0,0,0,0.33)"; ctx.beginPath(); ctx.ellipse(3, 5, 27, 14, 0, 0, 7); ctx.fill(); ctx.fillStyle = "rgba(0,0,0,0.25)"; ctx.beginPath(); ctx.ellipse(2, 3, 23, 11, 0, 0, 7); ctx.fill(); }
      // wheels with moving tread; the fronts turn with the steering
      const ty = shape === "open" ? 13 : 11.5, wy = ty + wide, ph = ((c.wheelPh || 0) % 6 + 6) % 6;
      for (const [x, y, front] of [[-15, -wy, 0], [-15, wy, 0], [11, -wy, 1], [11, wy, 1]]) {
        ctx.save(); ctx.translate(x, y); if (front) ctx.rotate(clamp(c.steerIn || 0, -1, 1) * 0.42);
        ctx.fillStyle = "#101113"; rr(ctx, -5.5, -3, 11, 6, 1.6); ctx.fill();
        ctx.fillStyle = "rgba(255,255,255,0.10)"; for (let k = -6 + ph; k < 6; k += 3) ctx.fillRect(k, -3, 0.9, 6);
        ctx.fillStyle = wcol; ctx.fillRect(-2.2, -1.3, 4.4, 2.6); ctx.restore();
      }
      const sway = clamp((c.latAcc || 0) * 0.05, -2, 2), pitch = c.brakeOn ? 1.2 : c.boost ? -1 : 0;
      ctx.translate(pitch, sway);
      ctx.drawImage(sp, -SW / 2, -SH / 2, SW, SH);
      if (c.wet) { ctx.fillStyle = "rgba(200,225,255,0.10)"; SHAPES[shape](ctx, wide); ctx.fill(); }
      // damage: scuffs, then a bent nose
      if (c.dmg > 0.12) { ctx.fillStyle = "rgba(25,22,20,0.55)"; ctx.fillRect(nose - 9, -7, 5, 3); if (c.dmg > 0.3) ctx.fillRect(rear + 4, 6, 7, 3); if (c.dmg > 0.5) { ctx.fillRect(-8, -9, 6, 2); ctx.strokeStyle = "rgba(20,20,20,0.75)"; ctx.lineWidth = 1.2; ctx.beginPath(); ctx.moveTo(nose - 5, -9); ctx.lineTo(nose - 1, -3); ctx.lineTo(nose - 4, 2); ctx.stroke(); } }
      // lights
      ctx.fillStyle = c.brakeOn ? "#ff2a2a" : "rgba(150,20,20,0.9)"; ctx.fillRect(rear - 1, -8, 2.5, 4); ctx.fillRect(rear - 1, 4, 2.5, 4);
      if (o.lights) { ctx.fillStyle = (root.KerbsideData && root.KerbsideData.LOOKS.lights[L.lights] || {}).color || "#fff6d6"; ctx.fillRect(nose - 2.5, -8.5, 2.8, 3.8); ctx.fillRect(nose - 2.5, 4.7, 2.8, 3.8); }
      // indicators: an AI driver signals the side it's moving to when it sets up a pass
      if (c.side && G && (G.race.simT * 3 | 0) % 2 === 0) { const y = c.side > 0 ? 9.5 : -12; ctx.fillStyle = "#ffb020"; ctx.fillRect(nose - 4, y, 3, 2.5); ctx.fillRect(rear + 1, y, 3, 2.5); }
      if (c.police) {   // light bar: red and blue, alternating
        const ph = ((G ? G.race.simT : 0) * 8 | 0) % 2;
        ctx.fillStyle = "#1a1a1a"; ctx.fillRect(-3, -7, 4, 14);
        ctx.fillStyle = ph ? "#ff2a3a" : "#5a1010"; ctx.fillRect(-3, -7, 4, 6.5); ctx.fillStyle = ph ? "#103060" : "#2a6aff"; ctx.fillRect(-3, 0.5, 4, 6.5);
      }
      if (c.pop > 0) {   // a backfire on lifting off at high revs
        ctx.fillStyle = `rgba(255,170,60,${Math.min(1, c.pop * 4)})`; ctx.beginPath(); ctx.arc(rear - 4, 3, 3 + c.pop * 8, 0, 7); ctx.fill();
      }
      if (c.boost) {   // nitro flame at the exhausts
        const f = 14 + Math.random() * 12;
        ctx.fillStyle = "rgba(255,120,40,0.85)"; ctx.beginPath(); ctx.moveTo(rear, -4); ctx.lineTo(rear - f, 0); ctx.lineTo(rear, 4); ctx.fill();
        ctx.fillStyle = "rgba(255,240,200,0.95)"; ctx.beginPath(); ctx.moveTo(rear, -2); ctx.lineTo(rear - f * 0.55, 0); ctx.lineTo(rear, 2); ctx.fill();
      }
      ctx.restore();
    }

    // ---------------------------------------------------------------- Particles (fixed pool)
    const PMAX = 640;
    const part = { x: new Float32Array(PMAX), y: new Float32Array(PMAX), vx: new Float32Array(PMAX), vy: new Float32Array(PMAX),
      life: new Float32Array(PMAX), max: new Float32Array(PMAX), size: new Float32Array(PMAX), kind: new Uint8Array(PMAX), col: new Array(PMAX), n: 0 };
    const K = { smoke: 1, dust: 2, spark: 3, spray: 4, confetti: 5, flame: 6, splash: 7 };
    function emit(kind, x, y, vx, vy, life, size, col) {
      if (!G || part.n >= G.q.particles) return;
      const i = part.n++; part.x[i] = x; part.y[i] = y; part.vx[i] = vx; part.vy[i] = vy; part.life[i] = life; part.max[i] = life; part.size[i] = size; part.kind[i] = kind; part.col[i] = col || null;
    }
    function updateParticles(dt) {
      for (let i = 0; i < part.n; i++) {
        part.life[i] -= dt;
        if (part.life[i] <= 0) { const j = --part.n; part.x[i] = part.x[j]; part.y[i] = part.y[j]; part.vx[i] = part.vx[j]; part.vy[i] = part.vy[j]; part.life[i] = part.life[j]; part.max[i] = part.max[j]; part.size[i] = part.size[j]; part.kind[i] = part.kind[j]; part.col[i] = part.col[j]; i--; continue; }
        const k = part.kind[i], drag = k === K.spark ? 0.9 : k === K.confetti ? 0.985 : k === K.smoke ? 0.965 : 0.95;
        part.vx[i] *= drag; part.vy[i] *= drag; part.x[i] += part.vx[i] * dt; part.y[i] += part.vy[i] * dt;
      }
    }
    function drawParticles(ctx, above, night) {
      for (let i = 0; i < part.n; i++) {
        const k = part.kind[i], f = part.life[i] / part.max[i];
        if ((k === K.spark || k === K.confetti || k === K.flame) !== above) continue;
        if (k === K.smoke) { const s = part.size[i] * (1 + (1 - f) * 2.6); ctx.fillStyle = night ? `rgba(150,160,180,${0.22 * f})` : `rgba(235,235,235,${0.3 * f})`; ctx.beginPath(); ctx.arc(part.x[i], part.y[i], s, 0, 7); ctx.fill(); }
        else if (k === K.dust) { ctx.fillStyle = `rgba(196,165,112,${0.32 * f})`; ctx.beginPath(); ctx.arc(part.x[i], part.y[i], part.size[i] * (2.2 - f), 0, 7); ctx.fill(); }
        else if (k === K.spray) { ctx.fillStyle = `rgba(205,220,240,${0.24 * f})`; ctx.beginPath(); ctx.arc(part.x[i], part.y[i], part.size[i] * (1.8 - f), 0, 7); ctx.fill(); }
        else if (k === K.splash) { ctx.strokeStyle = `rgba(210,225,245,${0.5 * f})`; ctx.lineWidth = 1; ctx.beginPath(); ctx.arc(part.x[i], part.y[i], part.size[i] * (1.4 - f), 0, 7); ctx.stroke(); }
        else if (k === K.spark) { ctx.strokeStyle = `rgba(255,${180 + 60 * f | 0},90,${f})`; ctx.lineWidth = 1.8; ctx.beginPath(); ctx.moveTo(part.x[i], part.y[i]); ctx.lineTo(part.x[i] - part.vx[i] * 0.035, part.y[i] - part.vy[i] * 0.035); ctx.stroke(); }
        else if (k === K.flame) { ctx.fillStyle = `rgba(255,${130 + 100 * f | 0},60,${0.75 * f})`; ctx.beginPath(); ctx.arc(part.x[i], part.y[i], part.size[i] * f, 0, 7); ctx.fill(); }
        else if (k === K.confetti) { ctx.fillStyle = part.col[i]; ctx.globalAlpha = Math.min(1, f * 2); ctx.fillRect(part.x[i], part.y[i], part.size[i], part.size[i] * 0.6); ctx.globalAlpha = 1; }
      }
    }
    // Nitro trails: a ribbon of recent exhaust positions, drawn additively (white-hot core, amber, then magenta).
    function drawTrails(ctx) {
      ctx.globalCompositeOperation = "lighter";
      for (const c of G.race.cars) {
        const tr = c.trail; if (!tr || tr.length < 2) continue;
        for (let i = 1; i < tr.length; i++) {
          const f = i / tr.length, a = tr[i - 1], b = tr[i];
          ctx.strokeStyle = `rgba(255,${Math.round(90 + 120 * f)},${Math.round(160 - 110 * f)},${0.55 * f * a[2]})`; ctx.lineWidth = 2 + 7 * f;
          ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke();
        }
        const h = tr[tr.length - 1]; if (h[2] > 0.5) { ctx.strokeStyle = "rgba(255,250,230,0.6)"; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(tr[Math.max(0, tr.length - 5)][0], tr[Math.max(0, tr.length - 5)][1]); ctx.lineTo(h[0], h[1]); ctx.stroke(); }
      }
      ctx.globalCompositeOperation = "source-over";
    }

    // ---------------------------------------------------------------- Quality
    const QUALITY = {
      low: { level: 0, particles: 110, rain: 50, dpr: 1, light: false, reflect: false, props: true, trails: false, clouds: false, glow: false },
      medium: { level: 1, particles: 300, rain: 130, dpr: 1.5, light: true, reflect: false, props: true, trails: true, clouds: true, glow: true },
      high: { level: 2, particles: 640, rain: 240, dpr: 2, light: true, reflect: true, props: true, trails: true, clouds: true, glow: true },
    };
    function pickQuality(s) {
      if (s.quality && QUALITY[s.quality]) return s.quality;
      return coarse() ? "medium" : "high";
    }

    // ---------------------------------------------------------------- Stage
    function build() {
      const cv = el("canvas", "race-cv"), mini = el("canvas", "race-mini");
      mini.width = 150; mini.height = 118;
      const rows = el("div", "race-rows"), towerName = el("span", ""), towerLap = el("span", "", "Lap 1/3");
      const tower = el("div", "race-tower race-hud", el("div", "race-tower-h", towerName, towerLap), rows);
      const posBig = el("b", "", "P1"), posOf = el("span", "", "/4"), lapNum = el("div", "race-lapnum"), lapBar = el("div", "race-lapbar", el("i"));
      const lapTime = el("div", "race-t", fmt(0)), bestLap = el("div", "race-t best"), ghostGap = el("div", "race-ghostgap");
      const pos = el("div", "race-pos", posBig, posOf);
      const lapLbl = el("div", "race-lbl", "Lap time"), bestLbl = el("div", "race-lbl", "Best lap");
      const lapbox = el("div", "race-lapbox race-hud", pos, lapNum, lapBar, lapLbl, lapTime, bestLbl, bestLap, ghostGap, mini);
      const gauge = el("canvas", "race-gauge"); gauge.width = 300; gauge.height = 300;
      const speedo = el("div", "race-speed race-hud", gauge);
      const modeText = el("div", "race-modetext"), meters = el("div", "race-meters"), modebox = el("div", "race-modebox race-hud", modeText, meters); modebox.hidden = true;
      const lights = el("div", "race-lights race-hud", ...[0, 1, 2, 3, 4].map(() => el("i")));
      lights.hidden = true;
      const banner = el("div", "race-banner"); banner.hidden = true;
      const card = el("div", "race-card"), overlay = el("div", "race-overlay", card);
      const pauseBtn = el("button", "race-pausebtn", "II"); pauseBtn.type = "button"; pauseBtn.setAttribute("aria-label", "Pause"); pauseBtn.hidden = true;
      const pad = (k, label, cls) => {
        const b = el("button", "race-pad" + (cls ? " " + cls : ""), label); b.type = "button"; b.dataset.k = k;
        b.setAttribute("aria-label", { left: "Steer left", right: "Steer right", down: "Brake", up: "Accelerate", nitro: "Nitro", shift: "Shift up" }[k]); return b;
      };
      const shiftPad = pad("shift", "SHIFT", "shift"); shiftPad.hidden = true;
      const pads = el("div", "race-pads", el("div", "race-padgrp", pad("left", "◀"), pad("right", "▶"), shiftPad),
        el("div", "race-padgrp", el("div", "race-padcol", pad("nitro", "NOS", "nos"), pad("down", "BRAKE")), pad("up", "GAS", "gas")));
      pads.hidden = true;
      const hud = [tower, lapbox, speedo, modebox, pauseBtn];
      const stage = el("div", "race-stage", cv, ...hud, lights, banner, pads, overlay);
      stage.tabIndex = 0;
      stage.setAttribute("aria-label", "Kerbside Grand Prix. Arrow keys or W A S D drive, Space for nitro, E shifts up in a drag race, P pauses.");
      return { stage, cv, ctx: cv.getContext("2d"), mini, mctx: mini.getContext("2d"), gauge, gctx: gauge.getContext("2d"), rows, towerName, towerLap, pos, posBig, posOf,
        lapNum, lapBar: lapBar.firstChild, lapLbl, bestLbl, lapTime, bestLap, ghostGap, modebox, modeText, meters, shiftPad, tower, lights, banner, card, overlay, pads, pauseBtn, hud };
    }

    function setHud(show) {
      for (const h of G.ui.hud) h.hidden = !show; G.ui.pads.hidden = !show || !G.touch;
      G.ui.modebox.hidden = !show || !G.race || ["circuit", "sprint", "rival"].includes(G.race.mode);
      G.ui.shiftPad.hidden = !G.race || G.race.mode !== "drag";
      G.ui.tower.hidden = !show || !G.race || standings(G.race).length < 2;
      G.meterKey = "";
      G.ui.stage.classList.toggle("racing", !!show);
    }
    function loadWorld(trackKey, tod, weather) {
      const t = track(trackKey); setupCanal(t); setupPond(t);
      if (!t.props) t.props = makeProps(t);
      const key = t.key + tod + weather;
      if (!G.world || G.world.key !== key) {
        G.world = { key, t, props: t.props, cv: paintWorld(t, tod, weather === "rain"), crowd: t.crowd || (t.crowd = makeCrowd(t)), traffic: makeTraffic(t) };
        G.world.ctx = G.world.cv.getContext("2d");
      }
      part.n = 0;
    }
    // A race config: newRace opts plus { title, ghostOn, best (seconds, for the HUD), target: {label, value} }.
    function start(cfg, hooks = {}) {
      G.cfg = cfg; G.hooks = hooks;
      G.race = newRace({ ...cfg, seed: cfg.seed || (Date.now() & 0xffff) + 1 });
      loadWorld(G.race.track, G.race.tod, G.race.weather);
      G.mode = "race"; G.paused = false; G.ui.overlay.hidden = true; G.ui.lights.hidden = false; G.rowKey = ""; G.rowT = 0;
      G.finishT = -1; G.timeScale = 1; G.shake = 0; G.bannerT = 0; G.keys = {}; G.flash = 0; G.punch = 0; G.wasBoost = false;
      G.rec = { start: null, next: 0, frames: [], meta: {}, marks: [] }; G.rp = null; G.ph = null; replayBar(false); photoBar(false); G.ui.cv.style.filter = "";
      snapCamera();
      setHud(true);
      G.ui.stage.focus({ preventScroll: true });
      status(`${G.race.trk.name}${cfg.title ? " · " + cfg.title : ""}: wait for the lights.`);
      if (G.audio) { G.audio.raceStart(); if (G.audio.voice) G.audio.voice(G.race.cars[0].shape); if (G.audio.music) G.audio.music(G.race.mode === "pursuit" ? "pursuit" : "race", 1); }
    }
    function snapCamera() { const me = G.race.cars[0]; G.cam.x = me.x; G.cam.y = me.y; G.cam.vx = G.cam.vy = 0; G.cam.rot = G.chase ? -me.a - Math.PI / 2 : 0; G.cam.z = 0; }
    function status(t) { if (G.onStatus) G.onStatus(t); }
    // The animated background behind menus: the AI field racing round a chosen track, filmed by a drifting chase cam.
    function backdrop(trackKey = "kerbside", tod = "dusk", weather = "dry", field) {
      if (G.rp) { G.rp = null; replayBar(false); } if (G.ph) { G.ph = null; photoBar(false); G.ui.cv.style.filter = ""; }
      G.mode = "menu"; G.paused = false; G.finishT = -1; G.timeScale = 1;
      G.race = newRace({ track: trackKey, time: tod, weather, laps: 99, field: (field || ROSTER.slice(1)).slice(0, 5), seed: 11 });
      G.race.state = "race"; G.race.lightsT = 9;
      loadWorld(G.race.track, G.race.tod, G.race.weather);
      G.attract = { car: 0, t: 0 };
      snapCamera();
      setHud(false); G.ui.lights.hidden = true; G.ui.banner.hidden = true;
      if (G.audio) G.audio.idle();
    }
    function podium() {
      const r = G.race, t = r.trk; if (!t.podium) return;
      const top = standings(r).filter((c) => !c.out).slice(0, 3);
      G.podium = top.map((c, k) => ({ c, st: t.podium.steps[k] }));
      for (const { c, st } of G.podium) { c.x = st.x; c.y = st.y; c.a = t.podium.a; c.vx = c.vy = c.fwd = 0; c.boost = false; c.brakeOn = false; c.steerIn = 0; c.trail = []; }
      G.mode = "podium"; G.timeScale = 1; G.finishT = -1; setHud(false); G.ui.banner.hidden = true;
      G.cam.x = t.podium.x; G.cam.y = t.podium.y; G.cam.vx = G.cam.vy = 0; G.cam.z = 0; G.podT = 0;
    }
    function setPaused(p) {
      if (!G || G.mode !== "race" || !G.race || !(G.race.state === "race" || G.race.state === "lights")) return;
      if (p === G.paused) return;
      G.paused = p; G.keys = {};
      if (G.audio) G.audio.pause(p);
      if (p) { if (G.hooks.pause) G.hooks.pause(); else fallbackCard("pause"); }
      else { G.ui.overlay.hidden = true; G.ui.stage.focus({ preventScroll: true }); }
    }
    function banner(text, ms, warn) {
      const b = G.ui.banner; b.textContent = text; b.classList.toggle("warn", !!warn); b.hidden = false;
      b.classList.remove("pop"); void b.offsetWidth; b.classList.add("pop");
      G.bannerT = ms ? ms / 1000 : 0; G.bannerOn = true;
    }
    function overlay(node, wide) {
      const { card, overlay: ov } = G.ui;
      if (!node) { ov.hidden = true; card.replaceChildren(); return; }
      card.className = "race-card" + (wide ? " wide" : "");
      card.replaceChildren(node); ov.hidden = false; card.scrollTop = 0;
      void card.offsetWidth; card.classList.add("enter");   // the screen transition (CSS; off with reduced motion)
      const f = card.querySelector("[data-autofocus]") || card.querySelector("button, select, input");
      if (f && !G.touch) f.focus({ preventScroll: true });
    }

    function handleEvents() {
      const r = G.race;
      for (const e of r.events.splice(0)) {
        if (G.mode !== "race") continue;
        if (G.hooks.event) G.hooks.event(e);
        if (e.type === "go") { G.ui.lights.hidden = true; banner("Go!", 900); status(r.laps > 99 ? "Lights out, go!" : `Lap 1 of ${r.laps}: lights out, go!`); if (G.audio) G.audio.go(); }
        else if (e.type === "lap") {
          const best = G.cfg.best;
          banner((e.lap === r.laps - 1 ? "Final lap" : "Lap " + (e.lap + 1)) + " · " + fmt(e.time) + (!best || e.time < best ? " fastest" : ""), 1400);
          status(`Lap ${e.lap + 1} of ${r.laps}, P${standings(r).indexOf(r.cars[0]) + 1}.`);
          if (G.audio) { G.audio.lap(); if (e.lap === r.laps - 1 && G.audio.music) G.audio.music(null, 2); }   // the final lap: the music lifts
        } else if (e.type === "finish") { mark("Finish"); finish(); }
        else if (e.type === "eliminated") {
          const c = r.cars.find((x) => x.code === e.code);
          banner(e.you ? "Eliminated" : `${c ? c.name : e.code} is out`, 1600, e.you);
          if (e.you) finish();
        } else if (e.type === "drift-bank" && e.pts > 150) banner(`+${e.pts.toLocaleString()}${e.mult > 1 ? " ×" + e.mult : ""}`, 900);
        else if (e.type === "drift-lost") banner("Combo lost", 700, true);
        else if (e.type === "reset" && e.you) banner("Back on track", 900);
        else if (e.type === "overtake" && e.you && r.t - (G.otT || -9) > 1.2) {
          G.otT = r.t; const other = r.cars.find((c) => c.id === (e.gain ? e.on : e.by));
          mark(e.gain ? `You pass ${other ? other.code : ""}` : `${other ? other.code : "Rival"} passes you`);
          if (e.gain) { banner(`Overtake · ${other ? other.code : ""}`, 800); if (!G.reduce) G.punch = Math.max(G.punch, 0.045); G.edge = 1; if (G.audio && G.audio.whoosh) G.audio.whoosh(); }
          else banner(`${other ? other.code : "Rival"} passes`, 700, true);
        } else if (e.type === "close-finish" && (e.a === "YOU" || e.b === "YOU")) { mark("Photo finish"); banner(`Photo finish · ${e.gap.toFixed(3)}s`, 1600); if (!G.reduce) G.timeScale = 0.2; }
        else if (e.type === "pursuit-end" || e.type === "delivery-failed" || e.type === "touge") { mark({ "pursuit-end": e.result === "escaped" ? "Escaped" : "Busted", "delivery-failed": "Out of time", touge: "Pulled clear" }[e.type]); finish(); }
        else if (e.type === "heat") { if (G.audio && G.audio.radio) { G.audio.radio(); if (e.heat >= 3) G.audio.music("pursuit", 2); } banner(`Heat ${e.heat}`, 1300, true); status(`Heat level ${e.heat}: ${e.heat >= 3 ? "units will ram you and set roadblocks" : "more units are joining"}.`); }
        else if (e.type === "unit-down") { mark("Unit disabled"); banner(`Unit disabled · ${e.left} left`, 1100); if (!G.reduce) G.punch = Math.max(G.punch, 0.05); }
        else if (e.type === "unit-join") { status("Another unit has joined the pursuit."); if (G.audio && G.audio.radio) G.audio.radio(); }
        else if (e.type === "roadblock") { mark("Roadblock"); if (G.audio && G.audio.radio) G.audio.radio(); banner(`Roadblock ahead · gap on the ${e.side > 0 ? "left" : "right"}`, 1800, true); status(`Roadblock ahead. The gap is on the ${e.side > 0 ? "left" : "right"}.`); }
        else if (e.type === "launch") banner({ perfect: "Perfect launch", good: "Good launch", wheelspin: "Wheelspin", bogged: "Bogged down" }[e.q], 900, e.q === "wheelspin" || e.q === "bogged");
        else if (e.type === "shift") { banner(`${e.gear} · ${{ perfect: "Perfect shift", good: "Good shift", early: "Early", late: "Late" }[e.q]}`, 600, e.q === "early" || e.q === "late"); if (G.audio && G.audio.shift) G.audio.shift(); }
        else if (e.type === "pit") { banner(e.done ? "Fresh tyres · go!" : "Pit stop", e.done ? 900 : 2600); status(e.done ? "Pit stop done: fresh tyres and repairs." : "In the pits."); }
        else if (e.type === "checkpoint") { banner(`Stop ${e.n}/${e.of} · +time`, 900); status(`Checkpoint ${e.n} of ${e.of}. ${e.left.toFixed(0)} seconds left.`); if (G.audio && G.audio.lap) G.audio.lap(); }
        else if (e.type === "weather") { banner(e.to === "rain" ? "Rain is coming" : e.to === "fog" ? "Fog rolling in" : "Track drying", 1500); status(e.to === "rain" ? "Rain is arriving: grip will fall." : e.to === "fog" ? "Fog is rolling in." : "The track is drying out."); }
      }
      for (const [x, y, a] of r.skids.splice(0)) {
        const bx = x - Math.cos(a) * 14 - r.trk.OX, by = y - Math.sin(a) * 14 - r.trk.OY, sx = -Math.sin(a) * 9, sy = Math.cos(a) * 9;
        G.world.ctx.fillStyle = "rgba(18,18,20,0.11)"; G.world.ctx.fillRect(bx + sx - 2, by + sy - 2, 4, 4); G.world.ctx.fillRect(bx - sx - 2, by - sy - 2, 4, 4);
      }
      for (const im of r.impacts.splice(0)) {
        if (G.mode !== "race") continue;
        for (let i = 0; i < Math.min(18, 5 + im.v / 25); i++) { const a = Math.random() * 7, s = 120 + Math.random() * 300; emit(K.spark, im.x, im.y, Math.cos(a) * s, Math.sin(a) * s, 0.25 + Math.random() * 0.3, 1); }
        for (let i = 0; i < 4; i++) emit(K.smoke, im.x, im.y, (Math.random() - 0.5) * 60, (Math.random() - 0.5) * 60, 0.6, 6);
        if (im.you) { if (im.v > 120 && (!G.lastMark || G.race.simT - G.lastMark > 2)) { G.lastMark = G.race.simT; mark("Contact"); } if (G.settings.shake !== false && !G.reduce) G.shake = Math.min(1, G.shake + im.v / 240); if (G.audio) G.audio.impact(im.v); }
      }
    }
    function finish() {
      if (G.finishT >= 0) return;
      const r = G.race, s = summary(r);
      G.finishT = 0; G.timeScale = G.reduce ? 1 : 0.35;
      const word = s.pursuit ? (s.pursuit.result === "escaped" ? "Escaped" : "Busted") : s.delivery ? (s.delivery.delivered ? "Delivered" : "Out of time")
        : s.eliminated ? "Eliminated" : s.place === 1 ? "Victory" : "Chequered flag";
      banner(word, 1400, s.pursuit ? s.pursuit.result !== "escaped" : false);
      if (s.place === 1 && !s.eliminated) { const me = r.cars[0]; for (let i = 0; i < 110; i++) { const a = Math.random() * 7, v = 80 + Math.random() * 280; emit(K.confetti, me.x, me.y, Math.cos(a) * v, Math.sin(a) * v, 1.4 + Math.random(), 5, ["#e9c44a", "#d23c3c", "#2f7de1", "#ffffff", "#1d9a6c", "#ff3fa4"][i % 6]); } }
      if (G.audio) G.audio.finish(s.place === 1 && !s.eliminated);
      if (s.pursuit) status(s.pursuit.result === "escaped" ? `Escaped at heat ${s.pursuit.heat} with a ${s.pursuit.bounty.toLocaleString()} bounty.` : `Busted at heat ${s.pursuit.heat}.`);
      else status(s.eliminated ? `Eliminated on ${r.trk.name}.` : `Finished P${s.place} of ${s.of} on ${r.trk.name} in ${fmt(s.total)}.`);
      setTimeout(() => {
        if (!G || G.race !== r) return;
        G.ui.banner.hidden = true; G.timeScale = 1; setHud(false);
        if (G.hooks.end) G.hooks.end(s, r); else fallbackCard("result", s);
      }, 1700);
    }

    // ---------------------------------------------------------------- Camera
    // A spring follows a point ahead of the car; in chase mode the view also turns so the car points up the screen
    // and sits low, looking down the road. Speed widens the view, nitro punches it out, impacts shake it. The start
    // is an orbiting shot that settles behind your car as the lights go out; the finish slows time and orbits again.
    function camera(dt, W, H, focus) {
      G.camBase = Math.max(0.42, Math.min(1.3, Math.min(W, H) / 620));
      if (G.mode === "photo" && G.ph) { const P = G.ph; return { cx: P.x, cy: P.y, z: P.z * G.camBase, rot: P.rot, eyeX: W / 2, eyeY: H / 2 }; }
      const race = G.race, chase = G.chase || G.mode === "replay", me = focus, sp = Math.hypot(me.vx, me.vy), top = me.acc / me.spec.drag;
      let z = Math.max(0.42, Math.min(1.3, Math.min(W, H) / 620)) * (1 - 0.2 * Math.min(1, sp / Math.max(500, top)));
      if (me.boost && !G.wasBoost && !G.reduce) G.punch = 0.08; G.wasBoost = me.boost;
      G.punch = Math.max(0, G.punch - dt * 0.15); z *= 1 - G.punch;
      const ahead = chase ? 0.5 : 0.32;
      let tx = me.x + me.vx * ahead, ty = me.y + me.vy * ahead;
      const heading = sp > 80 ? Math.atan2(me.vy, me.vx) * 0.35 + me.a * 0.65 : me.a;
      let rot = chase ? -heading - Math.PI / 2 : 0, bars = 0;
      if (G.mode === "menu") { z *= 0.82; bars = 1; rot += Math.sin(race.simT * 0.15) * 0.5; }
      else if (G.mode === "podium") { const P0 = race.trk.podium; tx = P0.x; ty = P0.y; z *= 1.35; bars = 1; rot = -P0.a - Math.PI / 2 + Math.PI + Math.sin(G.podT * 0.25) * 0.5; }
      else if (G.mode === "replay" && G.rp) {
        const P = G.rp, t = race.trk;
        if (P.cam === "heli") { z *= 0.5; rot = 0; }
        else if (P.cam === "orbit") { z *= 1.3; rot = P.t * 0.35; tx = me.x; ty = me.y; }
        else if (P.cam === "tv") {   // a fixed trackside camera that pans to follow, cutting to the next one when the car gets away
          if (!P.tvAt || Math.hypot(me.x - P.tvAt.x, me.y - P.tvAt.y) > 650) {
            const [i] = nearest(t, me.x, me.y, -1), k = (i + 28) % t.N, [nx, ny] = t.nrm(k), side = k % 2 ? 1 : -1;
            P.tvAt = { x: t.P[k][0] + nx * side * 230, y: t.P[k][1] + ny * side * 230, a: t.ANG[k] };
            G.cam.x = P.tvAt.x; G.cam.y = P.tvAt.y; G.cam.vx = G.cam.vy = 0; G.cam.rot = -P.tvAt.a - Math.PI / 2;
          }
          tx = P.tvAt.x + (me.x - P.tvAt.x) * 0.8; ty = P.tvAt.y + (me.y - P.tvAt.y) * 0.8; z *= 1.2; rot = -P.tvAt.a - Math.PI / 2;
        }
        bars = 1;
      } else if (race.state === "lights" && !G.reduce) {
        const k = ease(Math.min(1, race.lightsT / 3.6)), gx = race.cars.reduce((s, c) => s + c.x, 0) / race.cars.length, gy = race.cars.reduce((s, c) => s + c.y, 0) / race.cars.length;
        tx = gx + (tx - gx) * k; ty = gy + (ty - gy) * k; z *= 0.6 + 0.4 * k; rot += (1 - k) * 2.2; bars = 1 - k;
      } else if (G.finishT >= 0 && !G.reduce) { const k = Math.min(1, G.finishT / 1.6); z *= 1 + 0.15 * k; rot += k * 0.6; bars = k; }
      // spring (critically damped) on position; eased turn on rotation
      const kS = G.mode === "menu" ? 6 : 34, dS = 2 * Math.sqrt(kS);
      G.cam.vx += ((tx - G.cam.x) * kS - G.cam.vx * dS) * dt; G.cam.vy += ((ty - G.cam.y) * kS - G.cam.vy * dS) * dt;
      G.cam.x += G.cam.vx * dt; G.cam.y += G.cam.vy * dt;
      if (Math.hypot(tx - G.cam.x, ty - G.cam.y) > 900) { G.cam.x = tx; G.cam.y = ty; G.cam.vx = G.cam.vy = 0; }
      G.cam.rot += wrapA(rot - G.cam.rot) * Math.min(1, dt * (G.mode === "menu" ? 1.2 : 4.5));
      G.cam.z = G.cam.z ? G.cam.z + (z - G.cam.z) * Math.min(1, dt * 3) : z;
      G.bars += (bars - G.bars) * Math.min(1, dt * 3);
      let cx = G.cam.x, cy = G.cam.y;
      if (G.shake > 0) { cx += (Math.random() - 0.5) * 16 * G.shake; cy += (Math.random() - 0.5) * 16 * G.shake; G.shake = Math.max(0, G.shake - dt * 2.5); }
      const eyeX = W / 2, eyeY = chase && (G.mode === "race" || (G.mode === "replay" && G.rp && G.rp.cam === "chase")) ? H * 0.62 : H / 2;
      return { cx, cy, z: G.cam.z, rot: G.cam.rot, eyeX, eyeY };
    }

    // ---------------------------------------------------------------- Render
    function render(dt) {
      const { ui } = G, race = G.race, t = race.trk, me = race.cars[0], D = DECOR[t.decor] || DECOR.park, q = G.q;
      const W = ui.stage.clientWidth, H = ui.stage.clientHeight, dpr = Math.min(q.dpr, root.devicePixelRatio || 1);
      if (!W || !H) return;
      if (ui.cv.width !== Math.round(W * dpr) || ui.cv.height !== Math.round(H * dpr)) { ui.cv.width = Math.round(W * dpr); ui.cv.height = Math.round(H * dpr); }
      const ctx = ui.ctx, focus = G.mode === "menu" ? race.cars[G.attract.car % race.cars.length] : G.mode === "podium" && G.podium ? G.podium[0].c : G.mode === "replay" && G.rp ? focusCar() : me;
      const cam = camera(dt, W, H, focus), { cx, cy, z, rot, eyeX, eyeY } = cam, cr = Math.cos(rot), sr = Math.sin(rot);
      const toScreen = (x, y) => { const dx = x - cx, dy = y - cy; return [eyeX + (dx * cr - dy * sr) * z, eyeY + (dx * sr + dy * cr) * z]; };
      const world = () => ctx.setTransform(dpr * z * cr, dpr * z * sr, -dpr * z * sr, dpr * z * cr, dpr * (eyeX - z * (cr * cx - sr * cy)), dpr * (eyeY - z * (sr * cx + cr * cy)));
      const tod = race.tod, night = tod === "night", dusk = tod === "dusk", lightsOn = night || dusk || tod === "dawn" || race.fogness > 0.3 || race.wetness > 0.6;
      const radius = Math.hypot(W, H) / z * 0.62, time = race.simT;
      world();
      ctx.fillStyle = D.sea || D.ground; ctx.fillRect(cx - radius * 1.6, cy - radius * 1.6, radius * 3.2, radius * 3.2);
      ctx.drawImage(G.world.cv, t.OX, t.OY);
      // living water: glints drifting on the sea, the pond and the canal
      if (q.level > 0 && (D.sea || t.pond || t.canal)) {
        ctx.strokeStyle = night ? "rgba(140,180,255,0.18)" : "rgba(255,255,255,0.22)"; ctx.lineWidth = 2; ctx.beginPath();
        const step = 90, off = (time * 14) % step;
        for (let x = Math.floor((cx - radius) / step) * step; x < cx + radius; x += step) for (let y = Math.floor((cy - radius) / step) * step; y < cy + radius; y += step) {
          const h = Math.sin(x * 12.9898 + y * 78.233) * 43758.5453, fr = h - Math.floor(h), px = x + off + fr * 60, py = y + fr * 70;
          if (!isWater(t, D, px, py)) continue;
          const w = 10 + fr * 16 + Math.sin(time * 2 + fr * 6) * 4; ctx.moveTo(px, py); ctx.quadraticCurveTo(px + w / 2, py - 3, px + w, py);
        }
        ctx.stroke();
      }
      if (race.wetness > 0.02 && (race.change || race.weather !== "rain")) {   // live puddles when the rain wasn't baked into the world picture
        ctx.fillStyle = `rgba(160,185,220,${(0.2 * race.wetness).toFixed(3)})`;
        for (const [x, y, rx, ry, a] of puddlesOf(t)) if (Math.abs(x - cx) < radius && Math.abs(y - cy) < radius) { ctx.beginPath(); ctx.ellipse(x, y, rx, ry, a, 0, 7); ctx.fill(); }
      }
      drawParticles(ctx, false, night);
      drawCrowd(ctx, cx, cy, radius, time, night ? 0.55 : dusk ? 0.85 : 1);
      drawAmbient(ctx, dt, cx, cy, radius, lightsOn, time);
      // reflections on a wet road and underglow at night
      for (const c of race.cars) {
        if (c.out || c.hidden) continue;
        if (race.wet && q.reflect) { ctx.save(); ctx.globalAlpha = 0.2; ctx.fillStyle = (c.look && c.look.paint) || c.color; ctx.translate(c.x + 5, c.y + 9); ctx.rotate(c.a); ctx.beginPath(); ctx.ellipse(0, 0, 26, 9, 0, 0, 7); ctx.fill(); ctx.restore(); }
        if ((night || dusk) && q.glow) { ctx.globalCompositeOperation = "lighter"; ctx.drawImage(glowSprite(((c.look && c.look.paint) || c.color) + "66"), c.x - 46, c.y - 46, 92, 92); ctx.globalCompositeOperation = "source-over"; }
      }
      if (q.trails) drawTrails(ctx);
      if (G.mode === "race" || G.mode === "replay") drawModeMarks(ctx, race, time);
      const gp = G.mode === "race" && G.cfg.ghostOn !== false ? ghostPose(race) : null;
      if (gp) drawCar(ctx, { x: gp[0], y: gp[1], a: gp[2], color: me.color, look: me.look, shape: me.shape }, { ghost: true });
      const onPodium = G.mode === "podium" && G.podium ? new Set(G.podium.map((q) => q.c)) : null;
      const noCars = G.mode === "photo" && G.ph && G.ph.hideCars;
      for (const c of race.cars) { if (c.hidden || noCars) continue; c.wet = race.wetness > 0.5; if (!onPodium || !onPodium.has(c)) drawCar(ctx, c, { lights: lightsOn }); }
      const glow = q.glow && (night || dusk || tod === "dawn" || race.fogness > 0.3) ? [] : null;
      if (glow) for (const [x, y] of lampsOf(t)) if (Math.abs(x - cx) < radius && Math.abs(y - cy) < radius) glow.push([x, y, 22, "rgba(255,210,140,0.85)"]);
      if (q.props) drawProps(ctx, cx, cy, radius, tod, time, glow);
      if (onPodium) for (const { c, st } of G.podium) {   // lifted onto the plinth top (the same 2.5D lean as the scenery)
        const k = st.h * 0.0011, x = st.x + (st.x - cx) * k, y = st.y + (st.y - cy) * k;
        drawCar(ctx, { ...c, x, y }, { lights: lightsOn });
      }
      drawParticles(ctx, true, night);
      // cloud shadows drifting over everything (by day)
      if (q.clouds && !night && race.fogness < 0.5) {
        ctx.fillStyle = "rgba(10,20,40,0.10)";
        for (let i = 0; i < 6; i++) {
          const x = t.OX + ((i * 977 + time * 22) % (t.WW + 1200)) - 600, y = t.OY + ((i * 613) % t.WH), r = 260 + (i % 3) * 120;
          if (Math.abs(x - cx) > radius + r || Math.abs(y - cy) > radius + r) continue;
          ctx.beginPath(); ctx.ellipse(x, y, r, r * 0.6, i, 0, 7); ctx.ellipse(x + r * 0.5, y + r * 0.2, r * 0.7, r * 0.45, i, 0, 7); ctx.fill();
        }
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      // colour grade by time of day: a vivid day, a sunset sky at dusk, a cool dawn, moonlit night
      if (tod === "day" && q.level > 1) { ctx.globalCompositeOperation = "soft-light"; ctx.fillStyle = "rgba(255,236,190,0.35)"; ctx.fillRect(0, 0, W, H); ctx.globalCompositeOperation = "source-over"; }
      if (dusk) { const g = ctx.createLinearGradient(0, 0, W * 0.4, H); g.addColorStop(0, "rgba(255,140,50,0.26)"); g.addColorStop(0.55, "rgba(230,70,90,0.14)"); g.addColorStop(1, "rgba(90,40,140,0.22)"); ctx.fillStyle = g; ctx.fillRect(0, 0, W, H); }
      if (tod === "dawn") { const g = ctx.createLinearGradient(W, 0, 0, H); g.addColorStop(0, "rgba(255,190,170,0.22)"); g.addColorStop(1, "rgba(120,150,220,0.16)"); ctx.fillStyle = g; ctx.fillRect(0, 0, W, H); }
      const dark = { night: 0.7, dusk: 0.24, dawn: 0.16, day: 0 }[tod] + race.fogness * 0.05 + (!night ? race.wetness * 0.08 : 0);
      if (dark > 0) {
        if (q.light) {
          const ls = 0.5, lc = G.lightCv || (G.lightCv = doc.createElement("canvas")), lw = Math.ceil(W * ls), lh = Math.ceil(H * ls);
          if (lc.width !== lw || lc.height !== lh) { lc.width = lw; lc.height = lh; }
          const l = lc.getContext("2d");
          l.globalCompositeOperation = "source-over"; l.clearRect(0, 0, lw, lh);
          l.fillStyle = night ? `rgba(4,8,26,${dark})` : dusk ? `rgba(40,14,50,${dark})` : `rgba(20,20,45,${dark})`; l.fillRect(0, 0, lw, lh);
          l.globalCompositeOperation = "destination-out";
          const hs = glowSprite("rgba(0,0,0,1)");
          const hole = (x, y, r, a) => { l.globalAlpha = a; l.drawImage(hs, x - r, y - r, r * 2, r * 2); l.globalAlpha = 1; };
          for (const [x, y] of lampsOf(t)) { const [sx, sy] = toScreen(x, y); if (sx > -200 && sx < W + 200 && sy > -200 && sy < H + 200) hole(sx * ls, sy * ls, 150 * z * ls, 0.85); }
          if (glow) for (const [x, y, r] of glow) if (r > 40) { const [sx, sy] = toScreen(x, y); hole(sx * ls, sy * ls, r * 1.4 * z * ls, 0.45); }
          for (const c of race.cars) {
            if (c.out) continue;
            const [sx, sy] = toScreen(c.x + Math.cos(c.a) * 20, c.y + Math.sin(c.a) * 20), len = 250 * z * ls;
            l.save(); l.translate(sx * ls, sy * ls); l.rotate(c.a + rot);
            const g = l.createLinearGradient(0, 0, len, 0); g.addColorStop(0, "rgba(0,0,0,0.95)"); g.addColorStop(1, "rgba(0,0,0,0)");
            l.fillStyle = g; l.beginPath(); l.moveTo(0, -6 * z * ls); l.lineTo(len, -len * 0.45); l.lineTo(len, len * 0.45); l.lineTo(0, 6 * z * ls); l.closePath(); l.fill(); l.restore();
            hole(sx * ls, sy * ls, 42 * z * ls, 0.6);
          }
          l.globalCompositeOperation = "source-over";
          ctx.drawImage(lc, 0, 0, W, H);
        } else { ctx.fillStyle = night ? `rgba(4,8,26,${dark * 0.75})` : `rgba(30,14,40,${dark * 0.7})`; ctx.fillRect(0, 0, W, H); }
      }
      // glow pass: neon, signs, windows, bulbs, lamp heads; on a wet road they also streak into reflections
      if (glow && glow.length) {
        world(); ctx.globalCompositeOperation = "lighter";
        for (const [x, y, r, col] of glow) {
          ctx.drawImage(glowSprite(col), x - r, y - r, r * 2, r * 2);
          if (race.wet && q.reflect && r >= 20) { ctx.save(); ctx.translate(x, y); ctx.rotate(-rot); ctx.globalAlpha = 0.35; ctx.fillStyle = col; ctx.fillRect(-r * 0.12, r * 0.3, r * 0.24, r * 2.2); ctx.restore(); }
        }
        ctx.globalCompositeOperation = "source-over"; ctx.globalAlpha = 1; ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      }
      if (dusk && q.level > 0) {   // low sun and lens flare at the edge of the frame
        const sx = W * 0.92, sy = H * 0.06; ctx.globalCompositeOperation = "lighter";
        let g = ctx.createRadialGradient(sx, sy, 0, sx, sy, Math.max(W, H) * 0.45); g.addColorStop(0, "rgba(255,190,110,0.45)"); g.addColorStop(1, "rgba(255,120,60,0)"); ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
        for (const [f, r, a] of [[0.3, 26, 0.12], [0.55, 14, 0.14], [0.8, 40, 0.07]]) { const fx = sx + (W / 2 - sx) * f * 2, fy = sy + (H / 2 - sy) * f * 2; g = ctx.createRadialGradient(fx, fy, 0, fx, fy, r); g.addColorStop(0, `rgba(255,220,170,${a})`); g.addColorStop(1, "rgba(255,220,170,0)"); ctx.fillStyle = g; ctx.fillRect(fx - r, fy - r, r * 2, r * 2); }
        ctx.globalCompositeOperation = "source-over";
      }
      if (race.fogness > 0.01) {
        const [px, py] = toScreen(focus.x, focus.y), r0 = Math.min(W, H) * (0.16 + 0.3 * (1 - race.fogness)), r1 = Math.max(W, H) * 0.72, fa = (0.92 * race.fogness).toFixed(3);
        const g = ctx.createRadialGradient(px, py, r0, px, py, r1); g.addColorStop(0, "rgba(205,210,215,0)"); g.addColorStop(1, night ? `rgba(60,66,74,${fa})` : `rgba(212,216,222,${fa})`);
        ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
      }
      if (race.wetness > 0.02 && !G.inTunnel) {   // no rain inside the tunnel
        const drops = G.rain || (G.rain = []), want = Math.round(q.rain * race.wetness);
        while (drops.length < want) drops.push([Math.random() * W, Math.random() * H, 0.6 + Math.random() * 0.6]);
        drops.length = want;
        ctx.strokeStyle = night ? "rgba(170,190,225,0.38)" : "rgba(215,228,248,0.48)"; ctx.lineWidth = 1; ctx.beginPath();
        for (const d of drops) { d[1] += 900 * d[2] * dt; d[0] -= 160 * d[2] * dt; if (d[1] > H) { d[1] -= H + 20; d[0] = Math.random() * (W + 80); } if (d[0] < -20) d[0] += W + 40; ctx.moveTo(d[0], d[1]); ctx.lineTo(d[0] + 4 * d[2], d[1] - 16 * d[2]); }
        ctx.stroke();
        if (night && race.wetness > 0.6 && !G.reduce && Math.random() < dt * 0.06) G.flash = 1;   // distant lightning now and then
        if (G.flash > 0) { ctx.fillStyle = `rgba(220,230,255,${0.32 * G.flash})`; ctx.fillRect(0, 0, W, H); G.flash = Math.max(0, G.flash - dt * 3); }
      }
      // speed: streaks rushing past the car at full pace and on nitro, plus a warm edge glow
      const spd = Math.hypot(focus.vx, focus.vy), frac = spd / Math.max(500, focus.acc / focus.spec.drag);
      if (G.mode === "race" && q.level > 0 && !G.reduce && (frac > 0.82 || focus.boost)) {
        // short streaks near the edges of the frame, pointing away from the car
        const n = focus.boost ? 16 : 8, a0 = focus.boost ? 0.2 : 0.12 * (frac - 0.82) / 0.18, R0 = Math.hypot(W, H) * 0.32;
        ctx.strokeStyle = `rgba(255,248,230,${a0})`; ctx.lineWidth = 1; ctx.beginPath();
        for (let i = 0; i < n; i++) { const a = Math.random() * 6.283, r = R0 * (1 + Math.random() * 0.5), l = 24 + Math.random() * 50; ctx.moveTo(eyeX + Math.cos(a) * r, eyeY + Math.sin(a) * r); ctx.lineTo(eyeX + Math.cos(a) * (r + l), eyeY + Math.sin(a) * (r + l)); }
        ctx.stroke();
      }
      if (G.mode === "race" && focus.boost && q.level > 0 && !G.reduce) { const g = ctx.createRadialGradient(W / 2, H / 2, Math.min(W, H) * 0.35, W / 2, H / 2, Math.max(W, H) * 0.7); g.addColorStop(0, "rgba(255,180,60,0)"); g.addColorStop(1, "rgba(255,130,40,0.2)"); ctx.fillStyle = g; ctx.fillRect(0, 0, W, H); }
      if (G.edge > 0) { G.edge = Math.max(0, G.edge - dt * 2.2); ctx.strokeStyle = `rgba(246,214,140,${(0.55 * G.edge).toFixed(3)})`; ctx.lineWidth = 10; ctx.strokeRect(5, 5, W - 10, H - 10); }
      // vignette and cinematic bars
      if (!G.vig || G.vig.w !== W || G.vig.h !== H) {   // the vignette is drawn once per stage size
        const v = doc.createElement("canvas"); v.width = Math.ceil(W / 2); v.height = Math.ceil(H / 2); const vg = v.getContext("2d"), g = vg.createRadialGradient(v.width / 2, v.height / 2, Math.min(v.width, v.height) * 0.45, v.width / 2, v.height / 2, Math.hypot(v.width, v.height) * 0.62);
        g.addColorStop(0, "rgba(0,0,0,0)"); g.addColorStop(1, "rgba(0,0,0,0.38)"); vg.fillStyle = g; vg.fillRect(0, 0, v.width, v.height); G.vig = { w: W, h: H, cv: v };
      }
      if (G.mode === "photo" && G.ph) { ctx.globalAlpha = Math.min(1, G.ph.vignette * 2.6); ctx.drawImage(G.vig.cv, 0, 0, W, H); ctx.globalAlpha = 1; }   // photo: your vignette, no bars
      else ctx.drawImage(G.vig.cv, 0, 0, W, H);
      if (G.bars > 0.01 && G.mode !== "photo") { const b = H * 0.085 * G.bars; ctx.fillStyle = "#000"; ctx.fillRect(0, 0, W, b); ctx.fillRect(0, H - b, W, b); }
      if (G.mode === "race") hud(race, me, rot);
    }

    // The speedometer: a 240° arc with ticks, a filling bar (gold, then red near the top), the speed, a gear, and
    // the nitro tank as an outer ring that flares while boosting.
    function gauge(me) {
      const g = G.ui.gctx, S = 300, c = S / 2, sp = Math.max(0, me.fwd) * 0.34, top = me.acc / me.spec.drag * 0.34 * 1.3, f = Math.min(1, sp / top);
      const a0 = Math.PI * 0.75, a1 = Math.PI * 2.25, ang = (k) => a0 + (a1 - a0) * k;
      g.clearRect(0, 0, S, S);
      g.fillStyle = "rgba(6,5,4,0.82)"; g.beginPath(); g.arc(c, c, 132, 0, 7); g.fill();
      g.lineCap = "butt";
      g.strokeStyle = "rgba(255,255,255,0.1)"; g.lineWidth = 16; g.beginPath(); g.arc(c, c, 104, a0, a1); g.stroke();
      const grd = g.createLinearGradient(30, 270, 270, 30); grd.addColorStop(0, "#d9b45f"); grd.addColorStop(0.7, "#f6e6c2"); grd.addColorStop(1, "#ff4b55");
      g.strokeStyle = grd; g.beginPath(); g.arc(c, c, 104, a0, ang(f)); g.stroke();
      g.strokeStyle = "rgba(255,255,255,0.55)"; g.lineWidth = 2;
      for (let i = 0; i <= 12; i++) { const a = ang(i / 12), r1 = i % 3 ? 116 : 112; g.beginPath(); g.moveTo(c + Math.cos(a) * r1, c + Math.sin(a) * r1); g.lineTo(c + Math.cos(a) * 124, c + Math.sin(a) * 124); g.stroke(); }
      // nitro ring
      g.strokeStyle = "rgba(255,255,255,0.08)"; g.lineWidth = 6; g.beginPath(); g.arc(c, c, 82, a0, a1); g.stroke();
      g.strokeStyle = me.boost ? "#ffd27a" : "#f2a33a"; if (me.boost) { g.shadowColor = "#ff9a2a"; g.shadowBlur = 16; }
      g.beginPath(); g.arc(c, c, 82, a0, ang(me.nitro)); g.stroke(); g.shadowBlur = 0;
      // needle tip
      const a = ang(f); g.fillStyle = "#fff"; g.beginPath(); g.arc(c + Math.cos(a) * 104, c + Math.sin(a) * 104, 5, 0, 7); g.fill();
      g.fillStyle = "#fbf6ec"; g.textAlign = "center"; g.textBaseline = "middle";
      g.font = '700 70px "Rajdhani", system-ui, sans-serif'; g.fillText(String(Math.round(sp)), c, c - 4);
      g.font = '600 20px "Rajdhani", system-ui, sans-serif'; g.fillStyle = "#b9aa91"; g.fillText("KM/H", c, c + 40);
      const gear = sp < 3 ? "N" : String(Math.min(6, 1 + Math.floor(f * 6)));
      g.font = '700 26px "Rajdhani", system-ui, sans-serif'; g.fillStyle = "#d9b45f"; g.fillText(gear, c, c + 82);
      g.font = '600 15px "Rajdhani", system-ui, sans-serif'; g.fillStyle = me.boost ? "#ffd27a" : "#b9aa91"; g.fillText("NOS", c + 60, c + 96);
    }

    const text = (e, v) => { if (e.textContent !== v) e.textContent = v; };   // only touch the DOM when it changes
    const MODE_NAME = { pursuit: "Pursuit", drag: "Drag", delivery: "Delivery" };
    // The mode panel: a line of text and up to two meters (built once per mode, then only resized).
    function meters(list) {
      const ui = G.ui, key = list.map((m) => m.cls).join();
      if (G.meterKey !== key) { G.meterKey = key; ui.meters.replaceChildren(...list.map((m) => el("div", "race-meter " + m.cls, el("span", "", m.label), el("i", "", el("b"))))); }
      list.forEach((m, k) => {
        const row = ui.meters.children[k];
        row.lastChild.firstChild.style.width = Math.round(clamp(m.v, 0, 1) * 100) + "%"; row.classList.toggle("hot", !!m.hot);
        if (m.text !== undefined) text(row.firstChild, m.text);
      });
    }
    function modeHud(race, me) {
      const ui = G.ui, R2 = root.JarvisRacer;
      if (race.mode === "pursuit") {
        const P = race.pursuit, dots = "●".repeat(P.heat) + "○".repeat(5 - P.heat);
        text(ui.modeText, `Heat ${dots}  ·  Bounty ${Math.round(P.bounty).toLocaleString()}${P.cover ? "  ·  in cover" : P.seen ? "" : "  ·  out of sight"}`);
        meters([{ cls: "bust", label: "Busted", v: P.bust, hot: P.bust > 0.5 }, { cls: "cool", label: "Seen", text: P.seen ? "Seen" : "Escaping", v: P.cool }]);
        if (G.audio && G.audio.siren) G.audio.siren(P.state === "chase" ? clamp(1 - P.near / 900, 0, 1) : 0);
      } else if (race.mode === "drag") {
        const ok = me.rpm >= 0.86 && me.rpm <= 0.97;
        text(ui.modeText, race.state === "lights" ? "Hold the throttle to rev: launch in the green" : `Gear ${me.gear + 1}  ·  ${Math.round(Math.max(0, me.fwd) * 0.36)} km/h${ok && me.gear < 5 ? "  ·  SHIFT" : ""}`);
        meters([{ cls: "rpm", label: "Revs", v: me.rpm, hot: race.state === "lights" ? me.rpm > 0.55 && me.rpm < 0.8 : ok }, { cls: "dist", label: "Distance", v: race.drag ? (me.prog - me.startProg) / race.drag.len : 0 }]);
      } else if (race.mode === "endurance") {
        text(ui.modeText, `Tyres ${Math.round((1 - (me.wear || 0)) * 100)}%  ·  pits ${me.pits || 0}${me.pitT > 0 ? "  ·  in the pits" : "  ·  pit: stop in the box before the line"}`);
        meters([{ cls: "tyre", label: "Tyres", v: 1 - (me.wear || 0), hot: (me.wear || 0) > 0.6 }]);
      } else if (race.mode === "delivery" && race.deliv) {
        const D2 = race.deliv;
        text(ui.modeText, `Stop ${Math.min(D2.next + 1, D2.stops)}/${D2.stops}  ·  ${D2.left.toFixed(1)} s  ·  cargo ${Math.round(D2.cargo * 100)}%`);
        meters([{ cls: "cool", label: "Time", v: D2.left / (D2.add * 1.6), hot: D2.left < 5 }, { cls: "tyre", label: "Cargo", v: D2.cargo, hot: D2.cargo < 0.6 }]);
      } else if (race.mode === "touge") {
        const op = race.cars[1], d = op ? me.prog - op.prog : 0;
        text(ui.modeText, `${d >= 0 ? "Leading" : "Chasing"} by ${Math.abs(Math.round(d * SP * 0.1))} m  ·  ${Math.round(R2.TOUGE_GAP * SP * 0.1)} m clear wins`);
        meters([{ cls: "cool", label: "Gap", v: Math.abs(d) / R2.TOUGE_GAP, hot: d < 0 }]);
      } else if (race.mode === "team") {
        const pts = [10, 8, 6, 5, 4, 3], tally = { you: 0, them: 0 };
        standings(race).forEach((c, i) => { tally[!c.ai || c.team === "you" ? "you" : "them"] += pts[i] || 0; });
        text(ui.modeText, `Team ${tally.you} – ${tally.them}`);
        meters([]);
      } else meters([]);
    }
    function hud(race, me, rot) {
      const { ui } = G, t = race.trk;
      gauge(me);
      const m = ui.mctx, mw = ui.mini.width, mh = ui.mini.height, s = Math.min((mw - 12) / (t.maxX - t.minX), (mh - 12) / (t.maxY - t.minY));
      const mx = (x) => 6 + (x - t.minX) * s + ((mw - 12) - (t.maxX - t.minX) * s) / 2, my = (y) => 6 + (y - t.minY) * s + ((mh - 12) - (t.maxY - t.minY) * s) / 2;
      m.clearRect(0, 0, mw, mh);
      m.beginPath(); t.P.forEach(([x, y], i) => (i ? m.lineTo(mx(x), my(y)) : m.moveTo(mx(x), my(y)))); m.closePath();
      m.lineJoin = "round"; m.strokeStyle = "rgba(0,0,0,0.7)"; m.lineWidth = 7; m.stroke(); m.strokeStyle = "rgba(255,255,255,0.75)"; m.lineWidth = 3; m.stroke();
      m.fillStyle = "#fff"; m.fillRect(mx(t.P[0][0]) - 4, my(t.P[0][1]) - 1.5, 8, 3);
      for (const c of [...race.cars].reverse()) {
        if (c.out) continue;
        m.fillStyle = c.police ? ((race.simT * 6 | 0) % 2 ? "#ff2a3a" : "#2a6aff") : (c.look && c.look.paint) || c.color;
        if (c === me) { m.save(); m.translate(mx(c.x), my(c.y)); m.rotate(c.a); m.beginPath(); m.moveTo(7, 0); m.lineTo(-5, -4.5); m.lineTo(-3, 0); m.lineTo(-5, 4.5); m.closePath(); m.fill(); m.strokeStyle = "#000"; m.lineWidth = 1; m.stroke(); m.restore(); }
        else { m.beginPath(); m.arc(mx(c.x), my(c.y), 3.4, 0, 7); m.fill(); }
      }
      const order = standings(race), place = order.indexOf(me) + 1, lapShown = Math.min(race.laps, me.laps + 1);
      text(ui.towerName, t.name.split(" ").slice(0, -1).join(" ") || t.name);
      ui.pos.hidden = order.length < 2;
      text(ui.posBig, `P${place}`); text(ui.posOf, `/${order.length}`);
      const lapLbl = race.laps > 99 ? MODE_NAME[race.mode] || "" : `Lap ${lapShown}/${race.laps}`;
      text(ui.lapNum, lapLbl); text(ui.towerLap, lapLbl);
      const lapless = race.laps > 99; text(ui.lapLbl, lapless ? "Time" : "Lap time"); ui.bestLbl.hidden = ui.bestLap.hidden = lapless; ui.lapBar.parentNode.hidden = lapless;
      ui.lapBar.style.width = Math.round(clamp((me.prog - me.laps * t.N) / t.N, 0, 1) * 100) + "%";
      text(ui.lapTime, fmt(lapless ? race.t : race.state === "race" ? race.t - me.lapStart : me.done ? me.lapTimes[me.lapTimes.length - 1] : 0));
      const sess = me.lapTimes.length ? Math.min(...me.lapTimes) : 0, saved = G.cfg.best || 0;
      text(ui.bestLap, fmt(saved && sess ? Math.min(saved, sess) : saved || sess));
      const gp = G.cfg.ghostOn !== false && race.ghost && me.laps >= 1 && race.state === "race";
      text(ui.ghostGap, gp ? `Ghost ${fmt(race.ghost.time)}` : "");
      const lit = race.state === "lights" ? Math.min(5, Math.floor(race.lightsT / 0.7)) : 0;
      if (lit !== G.lit) { G.lit = lit; ui.lights.querySelectorAll("i").forEach((e, i) => e.classList.toggle("on", i < lit)); if (lit > 0 && G.audio) G.audio.beep(lit); }
      modeHud(race, me);
      if (race.mode === "drift") { const D2 = race.drift; text(ui.modeText, `Drift ${D2.score.toLocaleString()}${D2.cur > 0 ? `  +${Math.round(D2.cur).toLocaleString()} ×${D2.mult}` : ""}${G.cfg.target ? `  ·  target ${G.cfg.target.value.toLocaleString()}` : ""}`); }
      else if (race.mode === "elimination") text(ui.modeText, `${race.cars.length - race.outCount} left · last car out each lap`);
      else if (race.mode === "timetrial") text(ui.modeText, G.cfg.target ? `${G.cfg.target.label} ${fmt(G.cfg.target.value)} · now ${fmt(race.t)}` : `Time ${fmt(race.t)}`);
      const lead = order[0], key = order.map((c) => c.code + (c.out ? "x" : "")).join();
      G.rowT -= 1;
      if (key !== G.rowKey || G.rowT <= 0) {   // rebuild the tower when the order changes, else ~4×/s for gaps
        if (key !== G.rowKey && G.rowKey && G.prevPlace && place !== G.prevPlace) { ui.pos.classList.remove("bump"); void ui.pos.offsetWidth; ui.pos.classList.add("bump"); }
        G.prevPlace = place; G.rowKey = key; G.rowT = 15;
        ui.rows.replaceChildren(...order.map((c, i) => {
          let gap = i === 0 ? "Leader" : "";
          if (c.out) gap = "OUT";
          else if (i > 0) {
            if (c.done && lead.done) gap = "+" + (c.finish - lead.finish).toFixed(1) + "s";
            else { const dl = (lead.prog - c.prog) / t.N; gap = dl >= 1 ? "+" + Math.floor(dl) + " lap" : "+" + Math.round((lead.prog - c.prog) * SP * 0.1) + " m"; }
          }
          const chip = el("span", "race-chip"); chip.style.background = (c.look && c.look.paint) || c.color;
          return el("div", "race-row" + (c === me ? " me" : "") + (c.out ? " out" : ""), el("span", "pos", i + 1), chip, el("span", "code", c.code), el("span", "gap", gap));
        }));
      }
      if (race.wrongT > 0.8) banner("Wrong way", 0, true);
      else if (ui.banner.classList.contains("warn") && G.bannerT <= 0 && G.bannerOn) { ui.banner.hidden = true; ui.banner.classList.remove("warn"); G.bannerOn = false; }
      void rot;
    }

    // Track markings for the newer modes: the pit box, the next delivery stop, the drag start and finish lines, and
    // the red and blue wash of police lights on the road.
    function gate(ctx, t, i, col, label) {
      const k = ((i % t.N) + t.N) % t.N, [nx, ny] = t.nrm(k), p = t.P[k], h = TW / 2 + 6;
      ctx.save(); ctx.translate(p[0], p[1]); ctx.rotate(Math.atan2(ny, nx) - Math.PI / 2);
      ctx.fillStyle = col; ctx.fillRect(-5, -h, 10, h * 2);
      ctx.fillStyle = "#111"; ctx.fillRect(-8, -h - 8, 16, 10); ctx.fillRect(-8, h - 2, 16, 10);
      if (label) { ctx.fillStyle = "#fff"; ctx.font = "bold 22px system-ui, sans-serif"; ctx.textAlign = "center"; ctx.fillText(label, 0, -h - 14); }
      ctx.restore();
    }
    function drawModeMarks(ctx, race, time) {
      const t = race.trk;
      if (race.mode === "endurance") {   // the pit box: the last ten points before the line, hatched yellow
        ctx.save(); ctx.globalAlpha = 0.45; ctx.strokeStyle = "#ffd23a"; ctx.lineWidth = 5;
        for (let i = t.N - 10; i < t.N; i++) { const [nx, ny] = t.nrm(i), p = t.P[i], q2 = t.P[(i + 1) % t.N]; ctx.beginPath(); ctx.moveTo(p[0] + nx * TW / 2, p[1] + ny * TW / 2); ctx.lineTo(q2[0] - nx * TW / 2, q2[1] - ny * TW / 2); ctx.stroke(); }
        ctx.restore(); gate(ctx, t, t.N - 11, "rgba(255,210,58,0.9)", "PIT");
      } else if (race.mode === "delivery" && race.deliv) {
        const D2 = race.deliv, next = D2.cps[D2.next];
        if (next !== undefined) gate(ctx, t, next, `rgba(56,232,255,${(0.6 + 0.4 * Math.sin(time * 6)).toFixed(2)})`, D2.next + 1 >= D2.stops ? "DROP" : "STOP " + (D2.next + 1));
      } else if (race.mode === "drag" && race.drag) {
        const D2 = race.drag, k = (D2.start + D2.len) % t.N, [nx, ny] = t.nrm(k), p = t.P[k];
        ctx.save(); ctx.translate(p[0], p[1]); ctx.rotate(Math.atan2(ny, nx) - Math.PI / 2);
        for (let y = -TW / 2, n = 0; y < TW / 2; y += 10, n++) for (let x = 0; x < 2; x++) { ctx.fillStyle = (n + x) & 1 ? "#fff" : "#111"; ctx.fillRect(-10 + x * 10, y, 10, 10); }
        ctx.restore();
        gate(ctx, t, D2.start, "rgba(255,255,255,0.75)");
      } else if (race.mode === "pursuit") {
        ctx.globalCompositeOperation = "lighter";
        const ph = (time * 8 | 0) % 2;
        for (const c of race.cars) if (c.police && !c.out) ctx.drawImage(glowSprite(ph ? "#ff2a3a55" : "#2a6aff55"), c.x - 70, c.y - 70, 140, 140);
        ctx.globalCompositeOperation = "source-over";
      }
    }

    function effects(dt) {
      const r = G.race;
      for (const c of r.cars) {
        c.wheelPh = (c.wheelPh || 0) + (c.fwd || 0) * dt * 0.25;
        if (c.out || c.hidden) continue;
        const back = [c.x - Math.cos(c.a) * 18, c.y - Math.sin(c.a) * 18], sp = Math.max(0, c.fwd);
        if (c.on && c.slip > 100 && Math.random() < 0.8) emit(K.smoke, back[0] + (Math.random() - 0.5) * 16, back[1] + (Math.random() - 0.5) * 16, -c.vx * 0.08 + (Math.random() - 0.5) * 30, -c.vy * 0.08 + (Math.random() - 0.5) * 30, 0.9, 6);
        if (!c.on && sp > 120 && Math.random() < 0.7) emit(K.dust, back[0], back[1], -c.vx * 0.15 + (Math.random() - 0.5) * 50, -c.vy * 0.15 + (Math.random() - 0.5) * 50, 0.9, 8);
        if (r.wetness > 0.4 && c.on && sp > 220 && Math.random() < 0.6 * r.wetness) emit(K.spray, back[0] + (Math.random() - 0.5) * 18, back[1] + (Math.random() - 0.5) * 18, -c.vx * 0.22, -c.vy * 0.22, 0.5, 5);
        if (c.boost && Math.random() < 0.8) emit(K.flame, back[0] - Math.cos(c.a) * 10, back[1] - Math.sin(c.a) * 10, -c.vx * 0.3, -c.vy * 0.3, 0.25, 6);
        if (sp < 60 && Math.random() < 0.06) emit(K.smoke, back[0], back[1], -Math.cos(c.a) * 20, -Math.sin(c.a) * 20, 0.8, 3);   // idle exhaust
        c.pop = Math.max(0, (c.pop || 0) - dt);
        if (c.prevThr && !c.thr && sp > 330 && Math.random() < 0.5) { c.pop = 0.18; for (let i = 0; i < 3; i++) emit(K.flame, back[0], back[1], -c.vx * 0.2 + (Math.random() - 0.5) * 60, -c.vy * 0.2 + (Math.random() - 0.5) * 60, 0.18, 4); if (!c.ai && G.audio && G.audio.pop) G.audio.pop(); }
        c.prevThr = c.thr;
        if (G.q.trails) {   // the nitro ribbon fades out after the boost ends
          const tr = c.trail || (c.trail = []);
          if (c.boost) tr.push([back[0], back[1], 1]);
          for (const p of tr) p[2] -= dt * 1.6;
          while (tr.length && (tr[0][2] <= 0 || tr.length > 26)) tr.shift();
        }
      }
      if (r.wetness > 0.3 && G.q.level > 0 && !G.inTunnel) for (let i = 0; i < 3; i++) { const c = r.cars[Math.floor(Math.random() * r.cars.length)]; emit(K.splash, c.x + (Math.random() - 0.5) * 500, c.y + (Math.random() - 0.5) * 500, 0, 0, 0.45, 5); }
      updateParticles(dt);
    }

    // ---------------------------------------------------------------- Loop
    function frame(now) {
      if (!G) return;
      if (!G.ui.stage.isConnected) { unmount(); return; }
      G.raf = root.requestAnimationFrame(frame);
      const view = doc.body.dataset.view, visible = !doc.hidden && (!view || view === "games");
      const rdt = clamp((now - G.last) / 1000, 0, 0.05); G.last = now;   // a frame stamp can precede mount: never negative
      if (!visible) { setPaused(true); return; }
      // adaptive quality: if frames are slow for a while, step down (Auto only)
      G.ft = G.ft * 0.95 + rdt * 1000 * 0.05;
      if (G.autoQ && G.ft > 24 && (G.slowT = (G.slowT || 0) + rdt) > 2 && G.qName !== "low") { G.qName = G.qName === "high" ? "medium" : "low"; G.q = QUALITY[G.qName]; G.slowT = 0; G.ft = 16; }
      else if (G.ft <= 24) G.slowT = 0;
      const dt = rdt * G.timeScale;
      if (G.mode === "race" && !G.paused && G.ui.overlay.hidden) {
        G.acc += dt;
        const k = G.keys, you = { steer: (k.right ? 1 : 0) - (k.left ? 1 : 0), thr: !!k.up, brk: !!k.down, nitro: !!k.nitro, shift: !!k.shift };
        let n = 0;
        while (G.acc >= 1 / 120 && n++ < 12) { step(G.race, 1 / 120, you); G.acc -= 1 / 120; }
        record(G.race);
        if (G.finishT >= 0) { G.finishT += rdt; if (G.finishT > 1.6) G.timeScale = 1; }
        effects(dt);
        handleEvents();
      } else if (G.mode === "podium") {
        G.podT += rdt;
        if (Math.random() < 0.6 && G.podium) { const st = G.podium[0].st; const a = Math.random() * 7, v = 60 + Math.random() * 200; emit(K.confetti, st.x + (Math.random() - 0.5) * 160, st.y + (Math.random() - 0.5) * 100, Math.cos(a) * v, Math.sin(a) * v, 1.6, 5, SHIRTS[Math.floor(Math.random() * 7)]); }
        updateParticles(rdt);
      } else if (G.mode === "menu") {   // the background race keeps going behind the menus
        G.acc += rdt; let n = 0;
        while (G.acc >= 1 / 60 && n++ < 6) { step(G.race, 1 / 60, null); G.acc -= 1 / 60; }
        G.race.events.length = 0; G.race.impacts.length = 0;
        G.attract.t += rdt; if (G.attract.t > 9) { G.attract.t = 0; G.attract.car++; }
        effects(rdt); handleEvents();
      } else if (G.mode === "replay" && G.rp) replayTick(rdt);
      else G.acc = 0;
      if (G.bannerT > 0) { G.bannerT -= rdt; if (G.bannerT <= 0 && !G.ui.banner.classList.contains("warn")) G.ui.banner.hidden = true; }
      if (G.audio) {
        const me = G.race.cars[0], t = G.race.trk, live = G.mode === "race" && !G.paused;
        const crowd = live ? clamp(1 - Math.hypot(me.x - t.P[0][0], me.y - t.P[0][1]) / 900, 0, 1) : 0;   // the grandstands are by the line
        G.audio.update(live ? { speed: Math.max(0, me.fwd), top: me.acc / me.spec.drag, slip: me.on ? me.slip : 0, boost: me.boost, on: me.on, thr: !!me.thr, turbo: me.spec.turbo || 0,
          gear: G.race.mode === "drag" ? me.gear : undefined, rpm: me.rpm, wet: G.race.wetness, tunnel: G.inTunnel, crowd } : null);
      }
      render(rdt);
    }

    function onKey(e) {
      if (!G) return;
      if ((G.mode === "photo" || G.mode === "replay") && e.type === "keydown") {
        const tg = e.target; if (tg && /^(INPUT|TEXTAREA|SELECT)$/.test(tg.tagName) && e.code !== "Escape") return;
        if (G.mode === "photo") { if (photoKey(e)) e.preventDefault(); return; }
        const P = G.rp, k = e.code;
        if (k === "Space") { P.playing = !P.playing; if (P.playing && P.t >= P.end) P.t = 0; }
        else if (k === "ArrowLeft" || k === "ArrowRight") P.t = clamp(P.t + (k === "ArrowLeft" ? -5 : 5), 0, P.end);
        else if (k === "KeyC") cycleCam(); else if (k === "KeyV") { P.focus++; P.tvAt = null; }
        else if (k === "KeyP") photo(() => replayBar(true)); else if (k === "Escape") endReplay(); else return;
        e.preventDefault(); return;
      }
      if (!KEYS[e.code] && e.code !== "KeyP" && e.code !== "Escape") return;
      const t = e.target, typing = t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName));
      const racing = G.mode === "race" && G.race && (G.race.state === "race" || G.race.state === "lights") && G.ui.overlay.hidden;
      if (typing) return;
      if (e.type === "keydown" && (e.code === "KeyP" || e.code === "Escape")) { if (racing) { setPaused(true); e.preventDefault(); } else if (G.paused && e.code === "KeyP") setPaused(false); return; }
      if (!KEYS[e.code]) return;
      if (e.type === "keyup") { G.keys[KEYS[e.code]] = false; return; }
      if (!racing) return;
      G.keys[KEYS[e.code]] = true; e.preventDefault();   // arrows and Space drive the car instead of scrolling the page
    }

    // ---------------------------------------------------------------- Replay and photo mode
    // Every car is recorded 20 times a second from the start (in memory only, up to ten minutes), with marks for
    // the moments worth seeing again. The replay puts copies of the cars back where they were (interpolated between
    // frames) and films them with a choice of cameras; the race itself is never re-simulated. Photo mode freezes the
    // picture and hands you the camera.
    const REC_DT = 0.05, REC_MAX = 12000;
    const FILTERS = { none: ["None", "none"], warm: ["Warm", "sepia(0.25) saturate(1.25) hue-rotate(-8deg)"], cool: ["Cool", "saturate(1.1) hue-rotate(12deg) brightness(1.05)"],
      noir: ["Noir", "grayscale(1) contrast(1.25)"], vintage: ["Vintage", "sepia(0.6) contrast(0.95) brightness(1.05)"], vivid: ["Vivid", "saturate(1.6) contrast(1.1)"] };
    const CAMS = { chase: "Chase", tv: "Trackside", heli: "Helicopter", orbit: "Orbit" };
    function record(r) {
      const R0 = G.rec; if (!R0 || r.state === "lights") return;
      if (R0.start === null) { R0.start = r.simT; R0.next = r.simT; }
      while (R0.next <= r.simT && R0.frames.length < REC_MAX) {
        const f = {};
        for (const c of r.cars) {
          if (!R0.meta[c.id]) R0.meta[c.id] = { id: c.id, code: c.code, name: c.name, color: c.color, look: c.look, shape: c.shape, police: c.police, parked: c.parked, num: c.num, spec: c.spec, acc: c.acc, ai: c.ai };
          f[c.id] = [Math.round(c.x), Math.round(c.y), Math.round(c.a * 1000) / 1000, Math.round(c.fwd), (c.boost ? 1 : 0) | (c.brakeOn ? 2 : 0) | (c.on ? 4 : 0) | (c.out ? 8 : 0), Math.round(c.slip), Math.round((c.steerIn || 0) * 100) / 100, Math.round((c.dmg || 0) * 100) / 100];
        }
        R0.frames.push(f); R0.next += REC_DT;
      }
    }
    function mark(label) { const R0 = G.rec; if (R0 && R0.start !== null && R0.marks.length < 60) R0.marks.push({ t: Math.max(0, G.race.simT - R0.start - 2), label }); }
    function applyFrame(t) {
      const R0 = G.rec, f = t / REC_DT, i = Math.max(0, Math.min(R0.frames.length - 2, Math.floor(f))), k = Math.min(1, f - i), A = R0.frames[i], B = R0.frames[i + 1] || A;
      for (const c of G.rp.race.cars) {
        const a = A[c.id], b = B[c.id] || a;
        if (!a) { c.hidden = true; continue; }
        c.hidden = false; c.x = a[0] + (b[0] - a[0]) * k; c.y = a[1] + (b[1] - a[1]) * k; c.a = a[2] + wrapA(b[2] - a[2]) * k;
        c.fwd = a[3] + (b[3] - a[3]) * k; c.vx = Math.cos(c.a) * c.fwd; c.vy = Math.sin(c.a) * c.fwd;
        c.boost = !!(a[4] & 1); c.brakeOn = !!(a[4] & 2); c.on = !!(a[4] & 4); c.out = !!(a[4] & 8); c.slip = a[5]; c.steerIn = a[6]; c.dmg = a[7]; c.thr = c.fwd > 0;
      }
      G.rp.race.simT = R0.start + t;
    }
    const focusCar = () => { const cars = G.rp.race.cars.filter((c) => !c.hidden && !c.parked); return cars[G.rp.focus % Math.max(1, cars.length)] || G.rp.race.cars[0]; };
    function replay(onExit) {
      const R0 = G.rec; if (!R0 || R0.frames.length < 20) return false;
      const base = G.rp ? G.rp.orig : G.race;
      const cars = Object.values(R0.meta).map((m) => ({ ...m, x: 0, y: 0, a: 0, vx: 0, vy: 0, fwd: 0, slip: 0, on: true, idx: 0, prog: 0, laps: 0, trail: [], hidden: true, dmg: 0 }));
      const race = Object.assign({}, base, { cars, state: "replay", events: [], skids: [], impacts: [], ghost: null });
      G.rp = { orig: base, race, t: 0, end: (R0.frames.length - 1) * REC_DT, speed: 1, playing: true, cam: "chase", focus: 0, onExit, tvAt: null };
      G.race = race; G.mode = "replay"; G.paused = false; G.timeScale = 1; G.finishT = -1;
      setHud(false); G.ui.overlay.hidden = true; G.ui.banner.hidden = true; G.ui.lights.hidden = true;
      if (G.audio) G.audio.update(null);
      applyFrame(0); snapCamera(); replayBar(true);
      status(`Replay: ${fmt(G.rp.end)} recorded. Space plays and pauses, arrows skip, C changes camera, V changes car.`);
      return true;
    }
    function endReplay() {
      if (!G.rp) return;
      const done = G.rp.onExit; G.race = G.rp.orig; G.rp = null; G.mode = "race"; replayBar(false);
      if (done) done();
    }
    function replayBar(show) {
      const ui = G.ui;
      if (!show) { if (ui.replayBar) ui.replayBar.hidden = true; return; }
      const b = (label, fn, aria) => { const x = el("button", "race-rbtn", label); x.type = "button"; if (aria) x.setAttribute("aria-label", aria); x.addEventListener("click", fn); return x; };
      const play = b("❚❚", () => { G.rp.playing = !G.rp.playing; if (G.rp.playing && G.rp.t >= G.rp.end) G.rp.t = 0; }, "Play or pause");
      const speed = b("1×", () => { const S = [0.25, 0.5, 1, 2, 4]; G.rp.speed = S[(S.indexOf(G.rp.speed) + 1) % S.length]; }, "Playback speed");
      const scrub = el("input", "race-scrub"); scrub.type = "range"; scrub.min = 0; scrub.max = G.rp.end.toFixed(2); scrub.step = REC_DT; scrub.value = 0; scrub.setAttribute("aria-label", "Replay position");
      scrub.addEventListener("input", () => { G.rp.t = Number(scrub.value); G.rp.scrubbing = true; });
      scrub.addEventListener("change", () => { G.rp.scrubbing = false; });
      const cam = b("Camera: Chase", () => cycleCam(), "Change camera"), car = b("Car", () => { G.rp.focus++; G.rp.tvAt = null; }, "Follow another car");
      const marks = el("select", "race-select race-marks"); marks.setAttribute("aria-label", "Highlights");
      marks.append(el("option", "", `Highlights (${G.rec.marks.length})`));
      for (const m of G.rec.marks) { const o = el("option", "", `${fmt(m.t)} · ${m.label}`); o.value = m.t; marks.append(o); }
      marks.addEventListener("change", () => { if (marks.value !== "") { G.rp.t = Number(marks.value); G.rp.playing = true; } marks.selectedIndex = 0; });
      const photoBtn = b("Photo", () => photo(() => replayBar(true)), "Photo mode"), exit = b("Exit replay", () => endReplay(), "Exit replay");
      const time = el("span", "race-rtime", "0:00.000");
      const bar = el("div", "race-replaybar", el("div", "race-rrow", play, speed, time, scrub), el("div", "race-rrow", cam, car, marks, photoBtn, exit));
      if (ui.replayBar) ui.replayBar.replaceWith(bar); else ui.stage.append(bar);
      ui.replayBar = bar; Object.assign(ui, { rPlay: play, rSpeed: speed, rScrub: scrub, rCam: cam, rCar: car, rTime: time });
      bar.hidden = false;
    }
    function cycleCam() { const k = Object.keys(CAMS); G.rp.cam = k[(k.indexOf(G.rp.cam) + 1) % k.length]; G.rp.tvAt = null; }
    function replayTick(rdt) {
      const P = G.rp, ui = G.ui;
      if (P.playing && !P.scrubbing) { P.t = Math.min(P.end, P.t + rdt * P.speed); if (P.t >= P.end) P.playing = false; }
      applyFrame(P.t);
      if (P.playing) effects(rdt * P.speed); else updateParticles(0);
      const set = (e, v) => { if (e.textContent !== v) e.textContent = v; };
      set(ui.rPlay, P.playing ? "❚❚" : "▶"); set(ui.rSpeed, P.speed + "×"); set(ui.rCam, "Camera: " + CAMS[P.cam]); set(ui.rTime, `${fmt(P.t)} / ${fmt(P.end)}`);
      set(ui.rCar, focusCar().code || "Car");
      if (!P.scrubbing) ui.rScrub.value = P.t.toFixed(2);
    }
    // Photo mode: the picture freezes and the camera is yours. Drag or use the arrow keys to move, the wheel, + and -
    // or the slider to zoom, Q and E or the slider to turn; pick a filter and a vignette, then save a PNG.
    function photo(onExit) {
      if (!G || !G.race) return false;
      if (G.mode === "replay" && G.ui.replayBar) G.ui.replayBar.hidden = true;
      G.ph = { prev: G.mode, onExit, x: G.cam.x, y: G.cam.y, z: G.cam.z || 1, rot: G.cam.rot, filter: "none", vignette: 0.35, hideCars: false };
      G.mode = "photo"; setHud(false); G.ui.overlay.hidden = true; G.ui.banner.hidden = true; G.ui.lights.hidden = true;
      if (G.audio) G.audio.update(null);
      photoBar(true); status("Photo mode: drag to move, wheel or + and - to zoom, Q and E to turn, Esc to leave.");
      return true;
    }
    function endPhoto() {
      if (!G.ph) return;
      const P = G.ph; G.ph = null; G.mode = P.prev; G.ui.cv.style.filter = ""; photoBar(false);
      if (P.onExit) P.onExit();
    }
    function photoBar(show) {
      const ui = G.ui;
      if (!show) { if (ui.photoBar) ui.photoBar.hidden = true; return; }
      const P = G.ph, slider = (label, min, max, stepv, value, fn) => { const s = el("input", "race-scrub"); s.type = "range"; s.min = min; s.max = max; s.step = stepv; s.value = value; s.setAttribute("aria-label", label); s.addEventListener("input", () => fn(Number(s.value))); return el("label", "race-rlbl", el("span", "", label), s); };
      const filt = el("select", "race-select"); filt.setAttribute("aria-label", "Filter");
      for (const [k, [name]] of Object.entries(FILTERS)) { const o = el("option", "", name); o.value = k; filt.append(o); }
      filt.addEventListener("change", () => { P.filter = filt.value; ui.cv.style.filter = FILTERS[P.filter][1] === "none" ? "" : FILTERS[P.filter][1]; });
      const b = (label, fn) => { const x = el("button", "race-rbtn", label); x.type = "button"; x.addEventListener("click", fn); return x; };
      const hide = b("Hide cars", () => { P.hideCars = !P.hideCars; hide.textContent = P.hideCars ? "Show cars" : "Hide cars"; });
      const zoom = slider("Zoom", 0.3, 3, 0.01, P.z, (v) => { P.z = v; }), turn = slider("Turn", -3.14, 3.14, 0.01, wrapA(P.rot), (v) => { P.rot = v; });
      const bar = el("div", "race-replaybar race-photobar", el("div", "race-rrow", zoom, turn, slider("Vignette", 0, 1, 0.05, P.vignette, (v) => { P.vignette = v; })),
        el("div", "race-rrow", filt, hide, b("Save image", () => savePhoto()), b("Done", () => endPhoto())));
      if (ui.photoBar) ui.photoBar.replaceWith(bar); else ui.stage.append(bar);
      ui.photoBar = bar; ui.pZoom = zoom.lastChild; bar.hidden = false;
    }
    function savePhoto() {
      const src = G.ui.cv, out = doc.createElement("canvas"), f = FILTERS[G.ph.filter][1];
      out.width = src.width; out.height = src.height;
      const g = out.getContext("2d");
      if (f !== "none" && "filter" in g) g.filter = f;
      g.drawImage(src, 0, 0); g.filter = "none";
      if (f !== "none" && !("filter" in g)) {   // older Safari: approximate the filter by hand
        const img = g.getImageData(0, 0, out.width, out.height), d = img.data, k = G.ph.filter;
        for (let i = 0; i < d.length; i += 4) {
          const r = d[i], gg = d[i + 1], bb = d[i + 2], y = 0.3 * r + 0.59 * gg + 0.11 * bb;
          if (k === "noir") { const v = Math.max(0, Math.min(255, (y - 128) * 1.25 + 128)); d[i] = d[i + 1] = d[i + 2] = v; }
          else if (k === "vintage" || k === "warm") { const m = k === "vintage" ? 0.6 : 0.25; d[i] = r * (1 - m) + Math.min(255, y * 1.07 + 30) * m; d[i + 1] = gg * (1 - m) + y * 0.95 * m; d[i + 2] = bb * (1 - m) + y * 0.75 * m; }
          else if (k === "cool") { d[i] = r * 0.92; d[i + 2] = Math.min(255, bb * 1.1); }
          else if (k === "vivid") { d[i] = Math.max(0, Math.min(255, y + (r - y) * 1.6)); d[i + 1] = Math.max(0, Math.min(255, y + (gg - y) * 1.6)); d[i + 2] = Math.max(0, Math.min(255, y + (bb - y) * 1.6)); }
        }
        g.putImageData(img, 0, 0);
      }
      const name = `kerbside-${G.race.track}-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-")}.png`;
      out.toBlob((blob) => {
        if (!blob) { status("Couldn't save the picture in this browser."); return; }
        const a = el("a", ""); a.href = root.URL.createObjectURL(blob); a.download = name; a.hidden = true; doc.body.append(a); a.click();
        setTimeout(() => { root.URL.revokeObjectURL(a.href); a.remove(); }, 4000);
        status(`Saved ${name} to your downloads.`);
      }, "image/png");
    }
    function photoPointer(e) {
      const P = G && G.mode === "photo" && G.ph; if (!P) return;
      if (e.type === "wheel") { P.z = clamp(P.z * (e.deltaY > 0 ? 0.92 : 1.08), 0.3, 3); if (G.ui.pZoom) G.ui.pZoom.value = P.z; e.preventDefault(); return; }
      if (e.type === "pointerdown") { P.drag = [e.clientX, e.clientY]; G.ui.cv.setPointerCapture && G.ui.cv.setPointerCapture(e.pointerId); return; }
      if (e.type === "pointerup" || e.type === "pointercancel") { P.drag = null; return; }
      if (e.type === "pointermove" && P.drag) {
        const dx = e.clientX - P.drag[0], dy = e.clientY - P.drag[1], cr = Math.cos(P.rot), sr = Math.sin(P.rot), z = P.z * G.camBase;
        P.x -= (dx * cr + dy * sr) / z; P.y -= (-dx * sr + dy * cr) / z; P.drag = [e.clientX, e.clientY];
      }
    }
    function photoKey(e) {   // returns true when it handled the key
      const P = G.ph, cr = Math.cos(P.rot), sr = Math.sin(P.rot), s = 40 / (P.z * G.camBase);
      const mv = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1], KeyA: [-1, 0], KeyD: [1, 0], KeyW: [0, -1], KeyS: [0, 1] }[e.code];
      if (mv) { P.x += (mv[0] * cr + mv[1] * sr) * s; P.y += (-mv[0] * sr + mv[1] * cr) * s; return true; }
      if (e.code === "Equal" || e.code === "NumpadAdd") { P.z = clamp(P.z * 1.1, 0.3, 3); return true; }
      if (e.code === "Minus" || e.code === "NumpadSubtract") { P.z = clamp(P.z / 1.1, 0.3, 3); return true; }
      if (e.code === "KeyQ") { P.rot -= 0.05; return true; }
      if (e.code === "KeyE") { P.rot += 0.05; return true; }
      if (e.code === "Escape") { endPhoto(); return true; }
      return false;
    }

    // ---------------------------------------------------------------- Fallback start card (without racer-ui.js)
    const FB = "jarvis-racer-v2";
    let fbCache = null;   // read once, not every frame
    const fb = {
      get() { if (fbCache) return fbCache; const b = { track: "kerbside", level: "medium", ghostOn: true, best: {}, race: {}, wins: 0, ghosts: {} };
        try { fbCache = Object.assign(b, JSON.parse(root.localStorage.getItem(FB) || "{}")); } catch { fbCache = b; } return fbCache; },
      set(v) { fbCache = v; try { root.localStorage.setItem(FB, JSON.stringify(v)); } catch { /* private window */ } },
    };
    function fallbackCard(kind, s) {
      const saved = fb.get(), btn = (label, fn) => { const b = el("button", "race-go", label); b.type = "button"; b.addEventListener("click", fn); return b; };
      const box = el("div", "race-menu");
      if (kind === "pause") { box.append(el("h3", "race-h", "Paused"), btn("Resume", () => setPaused(false)), btn("Quit", () => { backdrop(saved.track); fallbackCard("start"); })); }
      else if (kind === "result") {
        const k = saved.track + ":" + saved.level;
        if (s.best && (!saved.best[k] || s.best < saved.best[k])) saved.best[k] = s.best;
        if (s.place === 1) saved.wins = (saved.wins || 0) + 1;
        fb.set(saved);
        box.append(el("h3", "race-h", s.place === 1 ? "Victory · P1" : `P${s.place} of ${s.of}`), el("p", "race-note", `Race ${fmt(s.total)} · best lap ${fmt(s.best)}`), btn("Race again", () => quick()), btn("Menu", () => { backdrop(saved.track); fallbackCard("start"); }));
      } else {
        const sel = el("select", "race-select"); sel.id = "race-track";
        for (const [v, tt] of Object.entries(TRACKS)) { const o = el("option", "", tt.name); o.value = v; o.selected = v === saved.track; sel.append(o); }
        sel.addEventListener("change", () => { saved.track = sel.value; fb.set(saved); backdrop(saved.track); });
        box.append(el("h3", "race-h", "Kerbside Grand Prix"), el("label", "race-field", el("span", "race-lbl", "Track"), sel), btn("Start race", () => quick()));
      }
      overlay(box);
    }
    function quick() {
      const saved = fb.get(), k = saved.track + ":" + saved.level;
      start({ track: saved.track, level: saved.level, ghost: saved.ghostOn ? saved.ghosts[saved.track] : null, best: saved.best[k] }, {
        event: (e) => { if (e.ghost) { const g = saved.ghosts[saved.track]; if (!g || e.ghost.time < g.time) { saved.ghosts[saved.track] = { time: e.ghost.time, pts: e.ghost.pts }; fb.set(saved); } } },
      });
    }

    function unmount() {
      if (!G) return;
      root.cancelAnimationFrame(G.raf);
      root.removeEventListener("keydown", onKey); root.removeEventListener("keyup", onKey);
      if (G.audio) G.audio.stop();
      if (G.ui_api && G.ui_api.detach) G.ui_api.detach();
      G = null;
    }

    // Returns the game's element to place on the page; keeps playing the same race when the page re-renders.
    function mount(opts = {}) {
      if (G && G.ui.stage.isConnected) return G.ui.stage;
      unmount();
      const ui = build();
      G = { ui, keys: {}, cam: { x: 0, y: 0, vx: 0, vy: 0, rot: 0, z: 0 }, last: root.performance.now(), acc: 0, paused: false, hooks: {}, cfg: {}, onStatus: opts.onStatus,
        settings: {}, reduce: reduceMotion(), touch: coarse(), ft: 16, mode: "menu", timeScale: 1, finishT: -1, bars: 1, punch: 0, flash: 0 };
      applySettings({});
      ui.pads.querySelectorAll(".race-pad").forEach((b) => {
        const k = b.dataset.k, held = new Set();
        const set = () => { if (G) { G.keys[k] = held.size > 0; b.classList.toggle("active", held.size > 0); } };
        b.addEventListener("pointerdown", (e) => { e.preventDefault(); held.add(e.pointerId); try { b.setPointerCapture(e.pointerId); } catch { /* fine */ } set(); });
        const up = (e) => { held.delete(e.pointerId); set(); };
        for (const ev of ["pointerup", "pointercancel", "lostpointercapture"]) b.addEventListener(ev, up);
        b.addEventListener("contextmenu", (e) => e.preventDefault());
      });
      ui.pauseBtn.addEventListener("click", () => setPaused(true));
      for (const ev of ["pointerdown", "pointermove", "pointerup", "pointercancel"]) ui.cv.addEventListener(ev, photoPointer);
      ui.cv.addEventListener("wheel", photoPointer, { passive: false });
      ui.stage.addEventListener("touchstart", () => { if (!G.touch) { G.touch = true; if (G.mode === "race") setHud(true); } }, { passive: true });
      root.addEventListener("keydown", onKey); root.addEventListener("keyup", onKey);
      backdrop("kerbside", "dusk");
      const UI = root.KerbsideUI;
      if (UI && UI.attach) G.ui_api = UI.attach(view);
      else fallbackCard("start");
      G.raf = root.requestAnimationFrame(frame);
      return ui.stage;
    }
    function applySettings(s) {
      if (!G) return;
      G.settings = { ...G.settings, ...s };
      G.reduce = G.settings.reducedMotion === true || (G.settings.reducedMotion !== false && reduceMotion());
      G.chase = G.settings.camera !== "classic" && !G.reduce;   // the turning camera is off with reduced motion
      G.autoQ = !G.settings.quality || G.settings.quality === "auto";
      G.qName = pickQuality(G.settings); G.q = QUALITY[G.qName];
      G.ui.stage.classList.toggle("reduce", G.reduce);
    }
    // What racer-ui.js drives.
    const view = {
      get stage() { return G && G.ui.stage; }, get race() { return G && G.race; }, get quality() { return G && G.qName; },
      start: (cfg, hooks) => start(cfg, hooks), backdrop, overlay, applySettings, podium: () => G && podium(), pause: () => setPaused(true), resume: () => setPaused(false),
      restart: () => { if (G && G.cfg && G.cfg.track) start(G.cfg, G.hooks); }, setAudio: (a) => { if (G) G.audio = a; }, drawCar, status,
      quit: () => { if (!G) return; G.paused = false; G.race.state = "retired"; setHud(false); if (G.audio) G.audio.pause(false); },
      // replay of the race just run (false if there's nothing recorded); onExit runs when the viewer closes
      replay: (onExit) => !!G && replay(onExit), get canReplay() { return !!(G && G.rec && G.rec.frames.length >= 20); },
      // photo mode from the pause menu (or the replay); onExit runs when you leave it
      photo: (onExit) => !!G && photo(onExit),
    };
    Object.assign(R, { mount, unmount, restart: () => view.restart(), view, drawCar });
  }

})(typeof self !== "undefined" ? self : globalThis);
