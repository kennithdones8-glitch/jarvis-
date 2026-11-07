// JARVIS avatar: geometry built in code (no downloaded models): the figure's distance field and its meshing,
// small mesh helpers, and the soft glow texture.
import * as THREE from "/static/vendor/three.module.min.js";

// ---- geometry helpers ------------------------------------------------------------------------------------------
export function mergeGeos(geos) {   // one draw call for many tubes (position, normal, uv, index)
  let nv = 0, ni = 0; for (const g of geos) { nv += g.attributes.position.count; ni += g.index.count; }
  const pos = new Float32Array(nv * 3), nrm = new Float32Array(nv * 3), uv = new Float32Array(nv * 2), idx = new Uint32Array(ni);
  const acc = geos.every((g) => g.attributes.aAccent) ? new Float32Array(nv) : null;
  let ov = 0, oi = 0;
  for (const g of geos) {
    pos.set(g.attributes.position.array, ov * 3); nrm.set(g.attributes.normal.array, ov * 3); uv.set(g.attributes.uv.array, ov * 2);
    if (acc) acc.set(g.attributes.aAccent.array, ov);
    const ix = g.index.array; for (let i = 0; i < ix.length; i++) idx[oi + i] = ix[i] + ov;
    ov += g.attributes.position.count; oi += ix.length; g.dispose();
  }
  const out = new THREE.BufferGeometry();
  out.setAttribute("position", new THREE.BufferAttribute(pos, 3)); out.setAttribute("normal", new THREE.BufferAttribute(nrm, 3));
  out.setAttribute("uv", new THREE.BufferAttribute(uv, 2)); out.setIndex(new THREE.BufferAttribute(idx, 1));
  if (acc) out.setAttribute("aAccent", new THREE.BufferAttribute(acc, 1));
  return out;
}
export function rng(seed) { let s = seed >>> 0; return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296); }

// ---- the figure: a sleek humanoid sculpted as a blended distance field, meshed once with surface nets ------------
// Original, made in code (no downloaded model). Units: feet at y ≈ 0, top of the head at y ≈ 5.07, facing +z.
const smin = (a, b, k) => { const h = Math.max(k - Math.abs(a - b), 0) / k; return Math.min(a, b) - h * h * k * 0.25; };
const smax = (a, b, k) => -smin(-a, -b, k);
function sdEll(px, py, pz, cx, cy, cz, rx, ry, rz) {
  const x = (px - cx) / rx, y = (py - cy) / ry, z = (pz - cz) / rz;
  const k0 = Math.hypot(x, y, z), k1 = Math.hypot(x / rx, y / ry, z / rz);
  return k1 > 0 ? (k0 * (k0 - 1)) / k1 : -Math.min(rx, ry, rz);
}
function sdLimb(px, py, pz, ax, ay, az, bx, by, bz, ra, rb) {   // a capsule whose radius tapers from a to b
  const bax = bx - ax, bay = by - ay, baz = bz - az, pax = px - ax, pay = py - ay, paz = pz - az;
  const h = Math.max(0, Math.min(1, (pax * bax + pay * bay + paz * baz) / (bax * bax + bay * bay + baz * baz)));
  return Math.hypot(pax - bax * h, pay - bay * h, paz - baz * h) - (ra + (rb - ra) * h);
}
// The helmet (faceless, owner's direction): a smooth faceplate with a fine centre keel, a recessed visor band
// that wraps the front (the sensor array sits in it, drawn in the shader) and raised rims above and below the visor;
// the dark alloy shell (armour) frames it. Each layer is the head's own surface grown or cut by a few millimetres, so it stays sleek.
function helmet(d, x, ax, y, z) {
  const front = z - 0.1;
  d = smin(d, sdLimb(x, y, z, 0, 4.98, 0.22, 0, 4.8, 0.272, 0.012, 0.009), 0.035);             // centre keel (above the visor only)
  d = Math.max(d, -Math.max(Math.abs(y - 4.735) - 0.026, -(d + 0.022), -front));               // visor recess
  d = Math.min(d, Math.max(Math.abs(y - 4.776) - 0.006, d - 0.007, -front));                   // upper visor rim
  d = Math.min(d, Math.max(Math.abs(y - 4.694) - 0.005, d - 0.006, -front));                   // lower visor rim
  return d;
}
export function sdHuman(x, y, z) {
  const ax = Math.abs(x);   // symmetric
  let d = sdEll(x, y, z, 0, 4.75, 0.0, 0.235, 0.32, 0.28);                                   // cranium
  d = smin(d, sdEll(x, y, z, 0, 4.8, -0.07, 0.22, 0.27, 0.26), 0.1);                         // swept-back crown
  d = smin(d, sdEll(x, y, z, 0, 4.54, 0.07, 0.16, 0.18, 0.19), 0.12);                        // lower head
  if (y > 4.38 && y < 5.0) d = helmet(d, x, ax, y, z);                                         // faceless helmet layers (meshed finer)
  d = smin(d, sdLimb(x, y, z, 0, 5.02, 0.1, 0, 4.92, -0.24, 0.035, 0.03), 0.06);             // helmet crest ridge
  d = smin(d, sdLimb(x, y, z, 0, 4.9, -0.2, 0, 4.6, -0.36, 0.03, 0.008), 0.06);              // swept rear fin
  d = smin(d, sdEll(ax, y, z, 0.225, 4.68, -0.03, 0.035, 0.075, 0.075), 0.04);               // temple pods
  d = smin(d, sdLimb(x, y, z, 0, 4.18, -0.02, 0, 4.48, 0.02, 0.11, 0.095), 0.1);             // neck
  d = smin(d, sdLimb(ax, y, z, 0.02, 4.22, -0.06, 0.5, 4.02, -0.05, 0.1, 0.07), 0.14);       // trapezius
  d = smin(d, sdEll(x, y, z, 0, 3.66, -0.01, 0.56, 0.52, 0.3), 0.14);                        // ribcage
  d = smin(d, sdEll(ax, y, z, 0.36, 3.42, -0.05, 0.2, 0.36, 0.2), 0.14);                     // lats (V-taper)
  d = smin(d, sdEll(ax, y, z, 0.21, 3.75, 0.15, 0.24, 0.17, 0.15), 0.08);                    // chest
  d = smin(d, sdLimb(ax, y, z, 0.05, 4.1, -0.02, 0.58, 3.98, -0.02, 0.12, 0.1), 0.12);       // shoulder line
  d = smin(d, sdEll(ax, y, z, 0.64, 3.9, 0.01, 0.17, 0.22, 0.17), 0.16);                     // deltoids
  d = smin(d, sdEll(x, y, z, 0, 3.05, 0.03, 0.36, 0.46, 0.235), 0.16);                       // abdomen (narrow waist)
  d = smin(d, sdEll(x, y, z, 0, 3.12, 0.12, 0.2, 0.36, 0.15), 0.08);                         // abdominal wall
  d = smin(d, sdEll(x, y, z, 0, 2.52, 0, 0.39, 0.3, 0.26), 0.16);                            // hips
  d = smin(d, sdLimb(ax, y, z, 0.68, 3.86, 0, 0.8, 3.05, -0.03, 0.125, 0.1), 0.08);          // upper arms
  d = smin(d, sdEll(ax, y, z, 0.74, 3.44, 0.04, 0.115, 0.24, 0.12), 0.07);                   // biceps
  d = smin(d, sdLimb(ax, y, z, 0.8, 3.03, -0.03, 0.88, 2.26, 0.05, 0.095, 0.068), 0.06);     // forearms
  d = smin(d, sdEll(ax, y, z, 0.82, 2.82, 0.0, 0.1, 0.24, 0.095), 0.06);                     // forearm muscle
  d = smin(d, sdEll(ax, y, z, 0.884, 2.27, 0.05, 0.05, 0.035, 0.045), 0.04);                  // wrist end (the hands are their own mesh)
  d = smin(d, sdLimb(ax, y, z, 0.24, 2.42, 0, 0.26, 1.36, 0.03, 0.2, 0.125), 0.1);           // thighs
  d = smin(d, sdEll(ax, y, z, 0.25, 1.9, 0.08, 0.15, 0.4, 0.13), 0.08);                      // quadriceps
  d = smin(d, sdEll(ax, y, z, 0.26, 1.34, 0.08, 0.1, 0.1, 0.08), 0.06);                      // knees
  d = smin(d, sdLimb(ax, y, z, 0.26, 1.33, 0.03, 0.25, 0.32, -0.03, 0.115, 0.07), 0.07);     // lower legs
  d = smin(d, sdEll(ax, y, z, 0.26, 1.0, -0.07, 0.1, 0.25, 0.1), 0.06);                      // calves
  d = smin(d, sdLimb(ax, y, z, 0.25, 0.2, -0.06, 0.27, 0.1, 0.24, 0.07, 0.05), 0.05);        // feet
  return d;
}
// Surface nets: one vertex per cell that the surface crosses, quads across every crossed grid edge. Smooth
// normals come from the field's gradient; aAccent is a per-vertex highlight (0 on the body).
export function meshFigure(h = 0.03, lo = [-1.12, -0.05, -0.48], hi = [1.12, 5.15, 0.48], field = sdHuman) {
  const [x0, y0, z0] = lo, [x1, y1, z1] = hi;
  const nx = Math.ceil((x1 - x0) / h) + 1, ny = Math.ceil((y1 - y0) / h) + 1, nz = Math.ceil((z1 - z0) / h) + 1;
  const v = new Float32Array(nx * ny * nz);
  for (let k = 0; k < nz; k++) for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++)
    v[i + nx * (j + ny * k)] = field(x0 + i * h, y0 + j * h, z0 + k * h);
  const at = (i, j, k) => v[i + nx * (j + ny * k)];
  const cell = new Int32Array((nx - 1) * (ny - 1) * (nz - 1)).fill(-1);
  const cid = (i, j, k) => i + (nx - 1) * (j + (ny - 1) * k);
  const pos = [], idx = [];
  const E = [[0, 0, 0, 1, 0, 0], [0, 1, 0, 1, 1, 0], [0, 0, 1, 1, 0, 1], [0, 1, 1, 1, 1, 1], [0, 0, 0, 0, 1, 0], [1, 0, 0, 1, 1, 0],
             [0, 0, 1, 0, 1, 1], [1, 0, 1, 1, 1, 1], [0, 0, 0, 0, 0, 1], [1, 0, 0, 1, 0, 1], [0, 1, 0, 0, 1, 1], [1, 1, 0, 1, 1, 1]];
  for (let k = 0; k < nz - 1; k++) for (let j = 0; j < ny - 1; j++) for (let i = 0; i < nx - 1; i++) {
    let sx = 0, sy = 0, sz = 0, n = 0;
    for (const [a, b, c, d, e, f] of E) {
      const va = at(i + a, j + b, k + c), vb = at(i + d, j + e, k + f);
      if ((va < 0) === (vb < 0)) continue;
      const tt = va / (va - vb);
      sx += a + (d - a) * tt; sy += b + (e - b) * tt; sz += c + (f - c) * tt; n++;
    }
    if (!n) continue;
    cell[cid(i, j, k)] = pos.length / 3;
    pos.push(x0 + (i + sx / n) * h, y0 + (j + sy / n) * h, z0 + (k + sz / n) * h);
  }
  const quad = (a, b, c, d, flip) => { if (a < 0 || b < 0 || c < 0 || d < 0) return;
    if (flip) idx.push(a, b, c, a, c, d); else idx.push(a, c, b, a, d, c); };
  for (let k = 1; k < nz - 1; k++) for (let j = 1; j < ny - 1; j++) for (let i = 1; i < nx - 1; i++) {
    const inside = at(i, j, k) < 0;
    if (inside !== (at(i + 1, j, k) < 0)) quad(cell[cid(i, j - 1, k - 1)], cell[cid(i, j, k - 1)], cell[cid(i, j, k)], cell[cid(i, j - 1, k)], inside);
    if (inside !== (at(i, j + 1, k) < 0)) quad(cell[cid(i - 1, j, k - 1)], cell[cid(i - 1, j, k)], cell[cid(i, j, k)], cell[cid(i, j, k - 1)], inside);
    if (inside !== (at(i, j, k + 1) < 0)) quad(cell[cid(i - 1, j - 1, k)], cell[cid(i, j - 1, k)], cell[cid(i, j, k)], cell[cid(i - 1, j, k)], inside);
  }
  const nrm = new Float32Array(pos.length), acc = new Float32Array(pos.length / 3), e = 0.004;
  for (let q = 0; q < pos.length; q += 3) {
    const [px, py, pz] = [pos[q], pos[q + 1], pos[q + 2]];
    let gx = field(px + e, py, pz) - field(px - e, py, pz), gy = field(px, py + e, pz) - field(px, py - e, pz),
        gz = field(px, py, pz + e) - field(px, py, pz - e);
    const l = Math.hypot(gx, gy, gz) || 1; nrm[q] = gx / l; nrm[q + 1] = gy / l; nrm[q + 2] = gz / l;
    acc[q / 3] = 0;
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute("normal", new THREE.BufferAttribute(nrm, 3));
  g.setAttribute("aAccent", new THREE.BufferAttribute(acc, 1));
  g.setAttribute("uv", new THREE.BufferAttribute(new Float32Array((pos.length / 3) * 2), 2));
  g.setIndex(idx);
  return g;
}

let glowTex = null;
export function glowTexture() {
  if (glowTex) return glowTex;
  const c = document.createElement("canvas"); c.width = c.height = 64;
  const g = c.getContext("2d"), r = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  r.addColorStop(0, "rgba(255,250,236,1)"); r.addColorStop(0.35, "rgba(255,236,190,.45)"); r.addColorStop(1, "rgba(255,220,160,0)");
  g.fillStyle = r; g.fillRect(0, 0, 64, 64);
  glowTex = new THREE.CanvasTexture(c);
  return glowTex;
}

// ---- hands: their own fine mesh, articulated fingers (right hand in rest pose; the left is its mirror) ---------
// The palm faces the body (-x), fingers hang down and curl toward the palm; the thumb sits in front (+z).
const KNUCKLE_Y = 2.075, HAND_X = 0.9;
const FINGERS = [[-0.033, 0.82], [-0.011, 0.97], [0.011, 1.0], [0.033, 0.93]].map(([dz, k]) => {
  const joints = [[HAND_X, KNUCKLE_Y, 0.06 + dz]]; let a = 0.12;
  for (const len of [0.046, 0.031, 0.025]) { const [px, py, pz] = joints[joints.length - 1];
    joints.push([px - Math.sin(a) * len * k, py - Math.cos(a) * len * k, pz]); a += 0.2; }
  return joints;
});
FINGERS.push([[0.888, 2.17, 0.112], [0.878, 2.115, 0.13], [0.866, 2.07, 0.128], [0.858, 2.04, 0.12]]);   // thumb
export function sdHand(x, y, z) {
  let d = sdEll(x, y, z, HAND_X, 2.15, 0.06, 0.026, 0.078, 0.052);                              // palm
  d = smin(d, sdEll(x, y, z, HAND_X + 0.004, 2.235, 0.055, 0.03, 0.05, 0.045), 0.02);           // heel of the hand
  FINGERS.forEach((j, f) => {
    const r0 = f === 4 ? 0.0125 : 0.0108;
    for (let i = 0; i < 3; i++) {
      const [a, b] = [j[i], j[i + 1]], ra = r0 * (1 - i * 0.12), rb = r0 * (1 - (i + 1) * 0.12);
      d = smin(d, sdLimb(x, y, z, ...a, ...b, ra, rb), i === 0 ? 0.012 : 0.003);              // segments
      d = smin(d, Math.hypot(x - b[0], y - b[1], z - b[2]) - rb * 1.12, 0.002);              // joint knuckles
    }
  });
  for (const pz of [0.028, 0.092])                                                             // wrist pistons
    d = smin(d, sdLimb(x, y, z, 0.918, 2.33, pz, 0.912, 2.205, pz, 0.0055, 0.0055), 0.003);
  return d;
}
export function meshHands(h = 0.0055) {
  const right = meshFigure(h, [0.8, 1.94, -0.02], [0.99, 2.36, 0.17], sdHand);
  const P = right.attributes.position.array, n = P.length / 3;
  const fing = new Float32Array(n).fill(-1), seg = new Float32Array(n), knuck = new Float32Array(n * 3);
  for (let q = 0; q < n; q++) {
    const [x, y, z] = [P[q * 3], P[q * 3 + 1], P[q * 3 + 2]];
    let best = 0.03, bf = -1, bs = 0;
    FINGERS.forEach((j, f) => {
      const total = [0, 1, 2].reduce((t, i) => t + Math.hypot(j[i + 1][0] - j[i][0], j[i + 1][1] - j[i][1], j[i + 1][2] - j[i][2]), 0);
      let along = 0;
      for (let i = 0; i < 3; i++) {
        const [a, b] = [j[i], j[i + 1]], ab = [b[0] - a[0], b[1] - a[1], b[2] - a[2]], L = Math.hypot(...ab);
        const tt = Math.max(0, Math.min(1, ((x - a[0]) * ab[0] + (y - a[1]) * ab[1] + (z - a[2]) * ab[2]) / (L * L)));
        const dd = Math.hypot(x - a[0] - ab[0] * tt, y - a[1] - ab[1] * tt, z - a[2] - ab[2] * tt);
        if (dd < best && !(i === 0 && tt <= 0)) { best = dd; bf = f; bs = (along + L * tt) / total; }
        along += L;
      }
    });
    fing[q] = bf; seg[q] = bs;
    const k = bf >= 0 ? FINGERS[bf][0] : [HAND_X, KNUCKLE_Y, 0.06];
    knuck.set(k, q * 3);
  }
  // mirror to the left hand
  const mirror = (src, flipX) => { const out = new Float32Array(src.length); for (let i = 0; i < src.length; i += 3) {
    out[i] = flipX ? -src[i] : src[i]; out[i + 1] = src[i + 1]; out[i + 2] = src[i + 2]; } return out; };
  const nr = right.attributes.normal.array, ix = right.index.array;
  const g = new THREE.BufferGeometry(), N2 = n * 2;
  const pos = new Float32Array(N2 * 3), nrm = new Float32Array(N2 * 3);
  pos.set(P, 0); pos.set(mirror(P, true), n * 3); nrm.set(nr, 0); nrm.set(mirror(nr, true), n * 3);
  const idx = new Uint32Array(ix.length * 2);
  idx.set(ix, 0); for (let i = 0; i < ix.length; i += 3) { idx[ix.length + i] = ix[i] + n; idx[ix.length + i + 1] = ix[i + 2] + n; idx[ix.length + i + 2] = ix[i + 1] + n; }
  const k2 = new Float32Array(N2 * 3); k2.set(knuck, 0); k2.set(mirror(knuck, true), n * 3);
  const f2 = new Float32Array(N2); f2.set(fing, 0); f2.set(fing, n);
  const s2 = new Float32Array(N2); s2.set(seg, 0); s2.set(seg, n);
  g.setAttribute("position", new THREE.BufferAttribute(pos, 3)); g.setAttribute("normal", new THREE.BufferAttribute(nrm, 3));
  g.setAttribute("aFing", new THREE.BufferAttribute(f2, 1)); g.setAttribute("aSeg", new THREE.BufferAttribute(s2, 1));
  g.setAttribute("aKnuck", new THREE.BufferAttribute(k2, 3));
  g.setAttribute("aAccent", new THREE.BufferAttribute(new Float32Array(N2).fill(0.35), 1));
  g.setAttribute("uv", new THREE.BufferAttribute(new Float32Array(N2 * 2), 2));
  g.setIndex(new THREE.BufferAttribute(idx, 1));
  return g;
}
