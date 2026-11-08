// JARVIS avatar: the Projection Director and its eight modules. Projections are built inside the existing scene and
// drawn by the existing renderer and render loop (no second renderer, no second loop). Each module receives the real
// data the dashboard fetched (/api/projection/<module>) and draws only that; empty data is drawn as an empty frame
// with a note. Up to two projections show at once (newest first; a pinned one stays); closing disposes every
// geometry, material and texture it created. Hand tracking does not exist and is not claimed: you rotate a projection
// by dragging and inspect a node by pointing at it.
import * as THREE from "/static/vendor/three.module.min.js";

const GOLD = new THREE.Color("#ffd98f"), WHITE = new THREE.Color("#fff6e4"), SILVER = new THREE.Color("#c9ccd3");
const AMBER = new THREE.Color("#ffb347"), RED = new THREE.Color("#ff5a52"), GREEN = new THREE.Color("#8fe3ad"), DIM = new THREE.Color("#7a6a50");
const STATE_COLOR = { completed: GREEN, done: GREEN, verified: GREEN, approved: GREEN, running: WHITE, started: WHITE, verifying: WHITE,
  planning: GOLD, queued: SILVER, pending: SILVER, awaiting_approval: AMBER, blocked: AMBER, paused: AMBER, failed: RED, rejected: RED,
  expired: DIM, cancelled: DIM, skipped: DIM, recovering: AMBER };
export const TITLES = { workflow: "Workflow map", architecture: "Software architecture", neural: "Knowledge network", globe: "Globe",
  data: "Data", timeline: "Timeline", security: "Security shield", simulation: "Simulation", research: "Research sources" };
// Each side of the figure holds up to two projections (one alone gets the big slot); an expanded projection takes
// the projection area on its own and the others step aside until it collapses. Minimised ones stay in the list.
const SLOTS = [new THREE.Vector3(2.45, 4.25, 0.1), new THREE.Vector3(2.45, 1.75, 0.1)];
const SINGLE = { at: new THREE.Vector3(2.4, 3.1, 0.3), scale: 0.98 }, PAIR_SCALE = 0.7;   // one projection gets the big slot
const EXPANDED = { at: new THREE.Vector3(2.7, 3.0, 0.9), scale: 1.5 };
const MAX_OPEN = 4;

function textSprite(text, { size = 0.16, color = "#ffd98f", weight = 600, max = 30 } = {}, own) {
  const t = String(text).slice(0, max);
  const c = document.createElement("canvas"), g = c.getContext("2d");
  g.font = `${weight} 44px Rajdhani, system-ui, sans-serif`;
  c.width = Math.max(64, Math.ceil(g.measureText(t).width) + 24); c.height = 64;
  g.font = `${weight} 44px Rajdhani, system-ui, sans-serif`; g.fillStyle = color; g.textBaseline = "middle"; g.fillText(t, 12, 34);
  const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace;
  const m = new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false });
  own.push(tex, m);
  const s = new THREE.Sprite(m); s.scale.set((size * c.width) / 64, size, 1);
  return s;
}

// one builder per module: (data, kit) -> THREE.Group, inside a box about 1.9 units wide
const BUILD = {
  workflow(d, k) {
    const g = new THREE.Group(), missions = d.nodes.filter((n) => n.kind === "mission").slice(0, 6);
    if (!missions.length) return k.empty(g, "No missions yet");
    missions.forEach((m, mi) => {
      const y = 0.7 - mi * 0.32;
      k.node(g, m, new THREE.Vector3(-0.85, y, 0), 0.06, STATE_COLOR[m.state] || GOLD, "box");
      const steps = d.edges.filter((e) => e.from === m.id && e.rel === "step").map((e) => d.nodes.find((n) => n.id === e.to)).filter(Boolean);
      let prev = new THREE.Vector3(-0.85, y, 0);
      steps.slice(0, 9).forEach((s, si) => {
        const p = new THREE.Vector3(-0.6 + si * 0.17, y, 0);
        k.line(g, prev, p, STATE_COLOR[s.state] || SILVER, 0.5);
        k.node(g, s, p, 0.035, STATE_COLOR[s.state] || SILVER);
        prev = p;
      });
      d.edges.filter((e) => e.from === m.id && e.rel === "checkpoint").map((e) => d.nodes.find((n) => n.id === e.to)).filter(Boolean)
        .slice(0, 2).forEach((a, ai) => {
          const p = new THREE.Vector3(-0.85 + 0.12 * (ai + 1), y + 0.12, 0.05);
          k.node(g, { ...a, label: `approval ${a.label} · ${a.state}` }, p, 0.04, STATE_COLOR[a.state] || AMBER, "octa");
        });
    });
    return g;
  },
  architecture(d, k) {
    const g = new THREE.Group();
    const groups = [...new Set(d.nodes.map((n) => n.group))];
    const pos = new Map();
    groups.forEach((grp, gi) => {
      const members = d.nodes.filter((n) => n.group === grp);
      const a = (gi / groups.length) * Math.PI * 2 + Math.PI / 2, cx = Math.cos(a) * 0.6, cy = Math.sin(a) * 0.6;   // facing you
      members.forEach((n, i) => {
        const b = (i / Math.max(1, members.length)) * Math.PI * 2, r = 0.08 + Math.min(0.22, members.length * 0.012);
        const p = new THREE.Vector3(cx + Math.cos(b) * r, cy + Math.sin(b) * r, ((i % 5) - 2) * 0.05);
        pos.set(n.id, p);
        const col = n.kind === "frontend" ? WHITE : n.kind === "api" ? SILVER : n.kind === "table" ? AMBER : GOLD;
        k.node(g, { ...n, label: `${n.id}${n.lines ? ` · ${n.lines} lines` : ""}` }, p, n.lines ? 0.018 + Math.min(0.045, n.lines / 30000) : 0.016, col,
               n.kind === "table" ? "box" : n.kind === "api" ? "octa" : "sphere");
      });
      const lab = textSprite(grp, { size: 0.09, color: "#c9ccd3" }, k.own); lab.position.set(cx * 1.35, cy * 1.35, 0.05); g.add(lab);
    });
    k.lines(g, d.edges.slice(0, 400).map((e) => [pos.get(e.from), pos.get(e.to)]).filter(([a, b]) => a && b), GOLD, 0.16);
    return g;
  },
  neural(d, k) {
    const g = new THREE.Group(), n = d.nodes.length;
    if (!n) return k.empty(g, "Nothing learned or remembered yet");
    const pos = new Map();
    d.nodes.forEach((node, i) => {   // a sphere of knowledge (Fibonacci layout); lessons and subjects nearer the centre
      const y = 1 - (i / Math.max(1, n - 1)) * 2, r = Math.sqrt(1 - y * y), th = i * 2.399963;
      const rad = node.kind === "subject" ? 0.35 : node.kind === "lesson" ? 0.55 : 0.8;
      const p = new THREE.Vector3(Math.cos(th) * r * rad, y * rad, Math.sin(th) * r * rad);
      pos.set(node.id, p);
      const col = node.status === "hypothesis" ? AMBER : node.status === "outdated" ? DIM : node.status === "user" || node.status === "confirmed" ? GREEN
        : node.kind === "subject" ? WHITE : node.polarity < 0 ? RED : GOLD;
      k.node(g, { ...node, label: `${node.kind}: ${node.label}${node.status ? ` (${node.status})` : ""}` }, p, node.kind === "lesson" ? 0.05 : 0.03, col);
    });
    k.lines(g, d.edges.filter((e) => e.rel !== "contradicts").map((e) => [pos.get(e.from), pos.get(e.to)]).filter(([a, b]) => a && b), GOLD, 0.3);
    k.lines(g, d.edges.filter((e) => e.rel === "contradicts").map((e) => [pos.get(e.from), pos.get(e.to)]).filter(([a, b]) => a && b), RED, 0.8);
    return g;
  },
  globe(d, k) {
    const g = new THREE.Group(), R = 0.78;
    const grid = [];
    for (let lat = -75; lat <= 75; lat += 15) for (let lon = 0; lon < 360; lon += 6) grid.push([k.ll(lat, lon, R), k.ll(lat, lon + 6, R)]);
    for (let lon = 0; lon < 360; lon += 15) for (let lat = -84; lat < 84; lat += 6) grid.push([k.ll(lat, lon, R), k.ll(lat + 6, lon, R)]);
    k.lines(g, grid, GOLD, 0.16);
    const core = new THREE.Mesh(new THREE.SphereGeometry(R * 0.985, 32, 20), new THREE.MeshBasicMaterial({ color: 0x120c05, transparent: true, opacity: 0.55 }));
    k.own.push(core.geometry, core.material); g.add(core);
    if (!d.points.length) { k.note(g, "No places in your research yet", -1.0); return g; }
    const max = Math.max(...d.points.map((p) => p.mentions));
    d.points.forEach((pt, i) => {
      const base = k.ll(pt.lat, pt.lon, R), tip = k.ll(pt.lat, pt.lon, R + 0.06 + 0.22 * (pt.mentions / max));
      k.line(g, base, tip, i === 0 ? WHITE : GOLD, 0.9);
      k.node(g, { label: `${pt.name} · mentioned ${pt.mentions}×` }, tip, 0.03, i === 0 ? WHITE : GOLD);
    });
    for (let i = 1; i < Math.min(d.points.length, 6); i++) {   // arcs from the most-mentioned place to the next ones
      const a = k.ll(d.points[0].lat, d.points[0].lon, R), b = k.ll(d.points[i].lat, d.points[i].lon, R);
      const mid = a.clone().add(b).multiplyScalar(0.5).normalize().multiplyScalar(R * 1.35);
      k.lines(g, new THREE.QuadraticBezierCurve3(a, mid, b).getPoints(24).map((p, j, arr) => (j ? [arr[j - 1], p] : null)).filter(Boolean), WHITE, 0.45);
    }
    return g;
  },
  data(d, k) {
    const g = new THREE.Group();
    const bars = (rows, x0, label, value, color) => rows.forEach((r, i) => {
      const hgt = Math.max(0.02, value(r) * 0.9);
      const m = new THREE.Mesh(new THREE.BoxGeometry(0.09, hgt, 0.09), new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.85 }));
      k.own.push(m.geometry, m.material);
      m.position.set(x0 + i * 0.13, -0.55 + hgt / 2, 0); m.userData.label = label(r); k.pickable.push(m); g.add(m);
    });
    if (!d.models.length && !d.days.some((x) => x.total)) return k.empty(g, "No measured answers or missions yet");
    bars(d.models.slice(0, 5), -0.9, (r) => `${r.label}: ${Math.round((r.check_rate || 0) * 100)}% of ${r.n} answers passed`, (r) => r.check_rate || 0, GOLD);
    const most = Math.max(1, ...d.days.map((x) => x.total));
    bars(d.days, -0.15, (r) => `${r.day}: ${r.verified} of ${r.total} verified`, (r) => r.total / most, SILVER);
    bars(d.days, -0.15, (r) => `${r.day}: ${r.verified} verified`, (r) => r.verified / most, GREEN);
    k.line(g, new THREE.Vector3(-0.95, -0.55, 0), new THREE.Vector3(1.0, -0.55, 0), GOLD, 0.6);
    const a = textSprite("answer checks by model", { size: 0.06, color: "#c9ccd3" }, k.own); a.position.set(-0.65, -0.68, 0); g.add(a);
    const b = textSprite("verified per day (14 d)", { size: 0.06, color: "#c9ccd3" }, k.own); b.position.set(0.45, -0.68, 0); g.add(b);
    return g;
  },
  timeline(d, k) {
    const g = new THREE.Group(), ev = d.events.slice(-24);
    k.line(g, new THREE.Vector3(-0.95, 0, 0), new THREE.Vector3(0.95, 0, 0), GOLD, 0.6);
    if (!ev.length && !d.upcoming.length) return k.empty(g, "No dated events yet");
    const t0 = ev.length ? Date.parse(ev[0].at) : Date.now(), t1 = Date.now(), span = Math.max(1, t1 - t0);
    ev.forEach((e, i) => {
      const x = -0.95 + 1.5 * ((Date.parse(e.at) - t0) / span), y = (i % 2 ? 1 : -1) * (0.12 + (i % 3) * 0.07);
      const col = e.kind === "milestone" ? GREEN : e.kind === "failed" ? RED : e.kind === "completed" ? GOLD : e.kind === "project" ? WHITE : SILVER;
      k.line(g, new THREE.Vector3(x, 0, 0), new THREE.Vector3(x, y, 0), col, 0.4);
      k.node(g, { label: `${new Date(e.at).toLocaleDateString()} · ${e.kind}: ${e.label}` }, new THREE.Vector3(x, y, 0), 0.03, col, e.kind === "milestone" ? "octa" : "sphere");
    });
    const now = textSprite("now", { size: 0.06, color: "#fff6e4" }, k.own); now.position.set(0.55, -0.42, 0); g.add(now);
    d.upcoming.slice(0, 5).forEach((u, i) => {   // after "now": no dates, so they are spaced evenly and drawn dashed
      const p = new THREE.Vector3(0.65 + i * 0.07, 0.25 + i * 0.09, 0);
      k.node(g, { label: `${u.label}${u.needs ? ` · needs ${u.needs} more milestones` : ""} · ${u.note}` }, p, 0.03, DIM, "octa");
    });
    return g;
  },
  security(d, k) {
    const g = new THREE.Group();
    const ring = (r, segs, color, op, label) => {
      for (let i = 0; i < Math.max(1, segs); i++) {
        const a = (i / Math.max(1, segs)) * Math.PI * 2;
        const m = new THREE.Mesh(new THREE.TorusGeometry(r, 0.012, 6, 24, (Math.PI * 2) / Math.max(1, segs) - 0.05), new THREE.MeshBasicMaterial({ color, transparent: true, opacity: op }));
        k.own.push(m.geometry, m.material); m.rotation.z = a; m.userData.label = label; k.pickable.push(m); g.add(m);
      }
    };
    const stopped = !!d.stop;
    ring(0.32, d.rings.on_its_own, GREEN, 0.8, `JARVIS does ${d.rings.on_its_own} kinds of things on its own`);
    ring(0.55, d.rings.asks_first, GOLD, 0.8, `${d.rings.asks_first} kinds of action always ask you first`);
    ring(0.78, d.rings.never, stopped ? RED : WHITE, 0.9, `${d.rings.never} things JARVIS never does`);
    if (stopped) {
      const dome = new THREE.Mesh(new THREE.SphereGeometry(0.85, 24, 12, 0, Math.PI * 2, 0, Math.PI / 2), new THREE.MeshBasicMaterial({ color: RED, wireframe: true, transparent: true, opacity: 0.35 }));
      k.own.push(dome.geometry, dome.material); dome.rotation.x = Math.PI / 2; dome.userData.label = "Emergency stop is ON: everything is halted"; k.pickable.push(dome); g.add(dome);
    }
    d.pending.forEach((p, i) => {   // pending approvals wait OUTSIDE the shield: not authorized
      const a = (i / Math.max(1, d.pending.length)) * Math.PI * 2;
      k.node(g, { label: `Waiting for you (not authorized): ${p.tool}.${p.action}` }, new THREE.Vector3(Math.cos(a) * 0.98, Math.sin(a) * 0.98, 0.05), 0.045, AMBER, "octa");
    });
    k.node(g, { label: `${d.denied_7d} blocked attempts in 7 days · audit log ${d.audit_ok === false ? "DAMAGED" : "intact"} · Touch ID ${d.touch_id ? "on" : "off"}` },
           new THREE.Vector3(0, 0, 0), 0.07, d.audit_ok === false ? RED : GOLD, "octa");
    return g;
  },
  // the last research answer in this conversation: the question at the centre, its sources around it (green: the
  // research tools really saw the page; amber: cited but not seen). Built in the browser from that answer only.
  research(d, k) {
    const g = new THREE.Group(), src = (d.sources || []).slice(0, 12);
    if (!d.question) return k.empty(g, "No research in this conversation yet");
    k.node(g, { label: `Question: ${d.question}` }, new THREE.Vector3(0, 0, 0), 0.08, GOLD, "octa");
    if (!src.length) { k.note(g, "No sources in that answer", -0.55); return g; }
    src.forEach((x, i) => {
      const a = (i / src.length) * Math.PI * 2 + Math.PI / 2, r = 0.62 + (i % 2) * 0.18;
      const p = new THREE.Vector3(Math.cos(a) * r, Math.sin(a) * r * 0.82, 0);
      k.line(g, new THREE.Vector3(0, 0, 0), p, x.verified ? GREEN : AMBER, x.verified ? 0.55 : 0.3);
      k.node(g, { label: `${x.host} · ${x.verified ? "seen by the research tools" : "cited, not seen by the research tools"}` }, p, 0.045, x.verified ? GREEN : AMBER);
    });
    k.note(g, `${d.searches} searches · ${d.pages} pages read · ${src.filter((x) => x.verified).length}/${src.length} verified`, -0.98);
    return g;
  },
  simulation(d, k) {
    const g = new THREE.Group(), xs = d.experiments.slice(0, 9);
    const floor = []; for (let i = -3; i <= 3; i++) floor.push([new THREE.Vector3(i * 0.28, -0.5, -0.8), new THREE.Vector3(i * 0.28, -0.5, 0.8)], [new THREE.Vector3(-0.84, -0.5, i * 0.26), new THREE.Vector3(0.84, -0.5, i * 0.26)]);
    k.lines(g, floor, SILVER, 0.18);
    if (!xs.length) return k.empty(g, "No experiments yet (Evolution → Simulation lab)");
    xs.forEach((x, i) => {
      const col = x.state === "done" ? GREEN : x.state === "failed" ? RED : x.state === "running" ? WHITE : SILVER;
      const p = new THREE.Vector3(((i % 3) - 1) * 0.5, -0.32 + Math.floor(i / 3) * 0.32, 0);
      k.node(g, { label: `${x.kind} · ${x.state}: ${x.recommendation || x.objective}` }, p, 0.07, col, "box");
    });
    return g;
  },
};

export function createDirector({ scene, kick }) {
  const active = [];   // { module, group, own, pickable, pinned, spin }
  let mix = 0, wx = 0.9, wr = 3, expanded = null;
  function kit(own, pickable) {
    const k = {
      own, pickable,
      ll: (lat, lon, r) => { const a = (lat * Math.PI) / 180, b = (lon * Math.PI) / 180; return new THREE.Vector3(r * Math.cos(a) * Math.cos(b), r * Math.sin(a), -r * Math.cos(a) * Math.sin(b)); },
      node(g, data, p, r, color, shape = "sphere") {
        const geo = shape === "box" ? new THREE.BoxGeometry(r * 1.6, r * 1.6, r * 1.6) : shape === "octa" ? new THREE.OctahedronGeometry(r * 1.3) : new THREE.SphereGeometry(r, 12, 8);
        const m = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.95 }));
        own.push(geo, m.material); m.position.copy(p); m.userData.label = data.label; pickable.push(m); g.add(m); return m;
      },
      line(g, a, b, color, op = 0.5) { k.lines(g, [[a, b]], color, op); },
      lines(g, pairs, color, op) {
        if (!pairs.length) return;
        const arr = new Float32Array(pairs.length * 6);
        pairs.forEach(([a, b], i) => { arr.set([a.x, a.y, a.z, b.x, b.y, b.z], i * 6); });
        const geo = new THREE.BufferGeometry(); geo.setAttribute("position", new THREE.BufferAttribute(arr, 3));
        const mat = new THREE.LineBasicMaterial({ color, transparent: true, opacity: op, blending: THREE.AdditiveBlending, depthWrite: false });
        own.push(geo, mat); g.add(new THREE.LineSegments(geo, mat));
      },
      note(g, text, y = 0) { const s = textSprite(text, { size: 0.13, color: "#fff6e4", weight: 500, max: 48 }, own); s.position.set(0, y, 0); g.add(s); },
      empty(g, text) { k.note(g, text, 0); return g; },
    };
    return k;
  }
  function frame(group, title, own) {   // a holographic frame with the title above
    const pts = [[-1, -0.95], [1, -0.95], [1, 0.95], [-1, 0.95]].map(([x, y]) => new THREE.Vector3(x, y, -0.4));
    const corners = [];
    pts.forEach((p, i) => { const q = pts[(i + 1) % 4]; corners.push([p, p.clone().lerp(q, 0.12)], [q.clone().lerp(p, 0.12), q]); });
    const arr = new Float32Array(corners.length * 6); corners.forEach(([a, b], i) => arr.set([a.x, a.y, a.z, b.x, b.y, b.z], i * 6));
    const geo = new THREE.BufferGeometry(); geo.setAttribute("position", new THREE.BufferAttribute(arr, 3));
    const mat = new THREE.LineBasicMaterial({ color: GOLD, transparent: true, opacity: 0.8 }); own.push(geo, mat);
    group.add(new THREE.LineSegments(geo, mat));
    const t = textSprite(title.toUpperCase(), { size: 0.15 }, own); t.position.set(0, 1.12, 0); group.add(t);
  }
  function dispose(p) {
    scene.remove(p.root);
    for (const o of p.own) if (o && o.dispose) o.dispose();
  }
  // a projection glides to its new place (positions are eased in update; the first placement is immediate)
  function place(p, at, scale) {
    p.root.visible = true; p.root.userData.s = scale;
    if (!p.root.userData.to) p.root.position.copy(at);
    p.root.userData.to = at.clone();
  }
  const shown = () => active.filter((p) => !p.minimized && (!expanded || p.module === expanded));
  function layout() {
    if (expanded && !active.some((p) => p.module === expanded && !p.minimized)) expanded = null;
    for (const p of active) p.root.visible = false;
    if (expanded) {
      const p = active.find((x) => x.module === expanded);
      place(p, EXPANDED.at, EXPANDED.scale);
    } else {
      for (const side of [1, -1]) {   // a side holds two: any more move to the other side (never hidden silently)
        const here = active.filter((p) => !p.minimized && p.side === side);
        for (const extra of here.slice(2)) extra.side = -side;
      }
      for (const side of [1, -1]) {
        const here = active.filter((p) => !p.minimized && p.side === side).slice(0, 2);
        here.forEach((p, i) => {
          const at = (here.length === 1 ? SINGLE.at : SLOTS[i]).clone(); at.x *= side;
          place(p, at, here.length === 1 ? SINGLE.scale : PAIR_SCALE);
        });
      }
    }
    for (const p of active) if (p.root.visible && !p.root.userData.born) p.root.scale.setScalar(p.root.userData.s);
  }
  // where the camera should widen to: toward the side that holds projections, further for an expanded one
  function wideGoal() {
    const vis = shown();
    if (!vis.length) return { mix: 0, x: wx, r: wr };
    if (expanded) return { mix: 1, x: 1.3, r: 5 };
    const sides = new Set(vis.map((p) => p.side));
    return { mix: 1, x: sides.size === 2 ? 0 : 0.9 * [...sides][0], r: sides.size === 2 ? 5.5 : 3 };
  }
  return {
    show(module, data) {
      if (!BUILD[module]) return false;
      const existing = active.findIndex((p) => p.module === module);
      const own = [], pickable = [], root = new THREE.Group(), body = BUILD[module](data, kit(own, pickable));
      root.add(body); frame(root, TITLES[module], own);
      scene.add(root);
      const entry = { module, root, body, own, pickable, pinned: false, minimized: false, side: 1,
                      spin: module === "globe" || module === "neural" || module === "architecture" };
      if (existing >= 0) {   // new data for an open projection: replaced in place (same slot, same rotation, no re-entrance)
        const old = active[existing];
        entry.pinned = old.pinned; entry.minimized = old.minimized; entry.side = old.side; body.rotation.copy(old.body.rotation); root.userData.born = 0;
        dispose(old); active[existing] = entry;
        layout(); kick();
        return true;
      }
      root.scale.setScalar(0.3); root.userData.born = performance.now();
      active.unshift(entry);
      while (active.length > MAX_OPEN) {   // the oldest unpinned one makes room
        const i = active.map((p) => p.pinned).lastIndexOf(false);
        const [gone] = active.splice(i >= 0 ? i : active.length - 1, 1); dispose(gone);
      }
      layout(); kick();
      return true;
    },
    close(module) {
      const i = active.findIndex((p) => p.module === module);
      if (i >= 0) { if (expanded === module) expanded = null; dispose(active[i]); active.splice(i, 1); layout(); kick(); }
    },
    closeAll() { while (active.length) dispose(active.pop()); expanded = null; kick(); },
    pin(module, on = true) { const p = active.find((x) => x.module === module); if (p) p.pinned = on; },
    // panel controls: look only, they never change the data or what JARVIS does
    expand(module) { const p = active.find((x) => x.module === module); if (!p) return false; p.minimized = false; expanded = module; layout(); kick(); return true; },
    collapse() { expanded = null; layout(); kick(); },
    minimize(module, on = true) {
      const p = active.find((x) => x.module === module); if (!p) return false;
      p.minimized = !!on; if (on && expanded === module) expanded = null; layout(); kick(); return true;
    },
    side(module, which) {   // which: "left" | "right"; a side holds two, so the oldest on that side moves over
      const p = active.find((x) => x.module === module); if (!p) return false;
      p.side = which === "left" ? -1 : 1; p.minimized = false;
      const there = active.filter((x) => x !== p && !x.minimized && x.side === p.side);
      if (there.length >= 2) there[there.length - 1].side = -p.side;
      layout(); kick(); return true;
    },
    move(module, delta) {   // reorder: the slot order follows the list order
      const i = active.findIndex((x) => x.module === module), j = i + delta;
      if (i < 0 || j < 0 || j >= active.length) return false;
      [active[i], active[j]] = [active[j], active[i]]; layout(); kick(); return true;
    },
    where(module) {   // the projection's world position and size, for inspecting it with the camera
      const p = active.find((x) => x.module === module && x.root.visible);
      return p ? { at: p.root.position.toArray(), scale: p.root.userData.s || 1 } : null;
    },
    list() { return active.map((p) => ({ module: p.module, title: TITLES[p.module], pinned: p.pinned, minimized: p.minimized,
                                         expanded: expanded === p.module, side: p.side < 0 ? "left" : "right" })); },
    get expanded() { return expanded; },
    get active() { return active.length > 0; },
    get wide() { return mix; }, get wideX() { return wx; }, get wideR() { return wr; },
    // per frame: how far the camera rig should widen (mix, read by the rig) while projections are open; projections appear, rotate slowly when moving
    update(dt, moving) {
      const w = wideGoal(), goal = w.mix, e = moving ? 1 - Math.exp(-dt * 3) : 1;
      mix += (goal - mix) * e; wx += (w.x - wx) * e; wr += (w.r - wr) * e;
      if (Math.abs(goal - mix) < 0.002) mix = goal;
      const shifting = Math.abs(w.x - wx) > 0.002 || Math.abs(w.r - wr) > 0.002;
      let gliding = false;
      for (const p of active) {
        const age = p.root.userData.born ? (performance.now() - p.root.userData.born) / 600 : 1;
        const to = p.root.userData.to;
        if (to) { p.root.position.lerp(to, e); if (p.root.position.distanceTo(to) > 0.003) gliding = true; else p.root.position.copy(to); }
        const want = (p.root.userData.s || PAIR_SCALE) * (moving ? Math.min(1, 0.3 + age) : 1), cur = p.root.scale.x;
        p.root.scale.setScalar(age >= 1 ? cur + (want - cur) * e : want);
        if (Math.abs(p.root.scale.x - want) > 0.003) gliding = true;
        if (moving && p.spin) p.body.rotation[p.module === "architecture" ? "z" : "y"] += dt * (p.module === "architecture" ? 0.04 : 0.15);
      }
      return Math.abs(goal - mix) > 0.002 || shifting || gliding || shown().some((p) => p.spin);
    },
    rotate(dx, dy) { const p = shown()[0]; if (p) { p.body.rotation.y += dx * 0.01; p.body.rotation.x = Math.max(-1, Math.min(1, p.body.rotation.x + dy * 0.01)); kick(); } },
    pick(ray) {
      const all = shown().flatMap((p) => p.pickable);   // hidden projections can't be picked
      const hit = ray.intersectObjects(all, false)[0];
      return hit ? hit.object.userData.label : null;
    },
    hidden: () => active.map((p) => p.root),
    looking: () => (active.length ? 1 : 0),
  };
}
