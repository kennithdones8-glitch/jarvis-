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
// The face, sculpted subtly like a statue of light (owner's choice): brow, eye sockets, cheekbones, nose, lips, chin.
function face(d, x, ax, y, z) {
  d = smax(d, -sdEll(ax, y, z, 0.075, 4.738, 0.3, 0.056, 0.028, 0.045), 0.03);                // eye sockets
  d = smin(d, sdLimb(ax, y, z, 0.018, 4.782, 0.27, 0.125, 4.785, 0.232, 0.013, 0.011), 0.035); // brow ridge
  d = smin(d, sdLimb(x, y, z, 0, 4.748, 0.278, 0, 4.632, 0.3, 0.009, 0.015), 0.03);            // nose bridge (slim)
  d = smin(d, sdEll(x, y, z, 0, 4.626, 0.29, 0.02, 0.02, 0.014), 0.05);                        // nose tip (soft, blends into the lip)
  d = smin(d, sdEll(x, y, z, 0, 4.585, 0.272, 0.022, 0.03, 0.012), 0.04);                       // philtrum: fills under the nose
  d = smin(d, sdEll(ax, y, z, 0.118, 4.682, 0.205, 0.06, 0.026, 0.045), 0.045);                // cheekbones (high)
  d = smax(d, -sdEll(ax, y, z, 0.105, 4.6, 0.262, 0.042, 0.04, 0.025), 0.05);                  // soft hollows under them
  // the mouth is a fine line drawn in the shader (sculpted lips this small break up at this mesh resolution)
  d = smin(d, sdEll(x, y, z, 0, 4.455, 0.2, 0.045, 0.034, 0.04), 0.06);                        // chin
  d = smin(d, sdLimb(ax, y, z, 0.14, 4.6, 0.04, 0.05, 4.457, 0.183, 0.024, 0.02), 0.07);       // jaw line
  return d;
}
export function sdHuman(x, y, z) {
  const ax = Math.abs(x);   // symmetric
  let d = sdEll(x, y, z, 0, 4.75, 0.0, 0.235, 0.32, 0.28);                                   // cranium
  d = smin(d, sdEll(x, y, z, 0, 4.8, -0.07, 0.22, 0.27, 0.26), 0.1);                         // swept-back crown
  d = smin(d, sdEll(x, y, z, 0, 4.54, 0.07, 0.16, 0.18, 0.19), 0.12);                        // lower head
  if (y > 4.38 && z > 0.0) d = face(d, x, ax, y, z);                                          // sculpted face (meshed finer)
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
  d = smin(d, sdEll(ax, y, z, 0.9, 2.08, 0.07, 0.07, 0.13, 0.045), 0.05);                    // hands (palm)
  d = smin(d, sdLimb(ax, y, z, 0.9, 2.0, 0.07, 0.91, 1.86, 0.08, 0.045, 0.03), 0.04);        // fingers, closed
  d = smin(d, sdLimb(ax, y, z, 0.24, 2.42, 0, 0.26, 1.36, 0.03, 0.2, 0.125), 0.1);           // thighs
  d = smin(d, sdEll(ax, y, z, 0.25, 1.9, 0.08, 0.15, 0.4, 0.13), 0.08);                      // quadriceps
  d = smin(d, sdEll(ax, y, z, 0.26, 1.34, 0.08, 0.1, 0.1, 0.08), 0.06);                      // knees
  d = smin(d, sdLimb(ax, y, z, 0.26, 1.33, 0.03, 0.25, 0.32, -0.03, 0.115, 0.07), 0.07);     // lower legs
  d = smin(d, sdEll(ax, y, z, 0.26, 1.0, -0.07, 0.1, 0.25, 0.1), 0.06);                      // calves
  d = smin(d, sdLimb(ax, y, z, 0.25, 0.2, -0.06, 0.27, 0.1, 0.24, 0.07, 0.05), 0.05);        // feet
  return d;
}
// Surface nets: one vertex per cell that the surface crosses, quads across every crossed grid edge. Smooth
// normals come from the field's gradient; aAccent marks the hands (teal-green accents, as in the owner's reference).
export function meshFigure(h = 0.03, lo = [-1.12, -0.05, -0.48], hi = [1.12, 5.15, 0.48]) {
  const [x0, y0, z0] = lo, [x1, y1, z1] = hi;
  const nx = Math.ceil((x1 - x0) / h) + 1, ny = Math.ceil((y1 - y0) / h) + 1, nz = Math.ceil((z1 - z0) / h) + 1;
  const v = new Float32Array(nx * ny * nz);
  for (let k = 0; k < nz; k++) for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++)
    v[i + nx * (j + ny * k)] = sdHuman(x0 + i * h, y0 + j * h, z0 + k * h);
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
    let gx = sdHuman(px + e, py, pz) - sdHuman(px - e, py, pz), gy = sdHuman(px, py + e, pz) - sdHuman(px, py - e, pz),
        gz = sdHuman(px, py, pz + e) - sdHuman(px, py, pz - e);
    const l = Math.hypot(gx, gy, gz) || 1; nrm[q] = gx / l; nrm[q + 1] = gy / l; nrm[q + 2] = gz / l;
    const hand = Math.hypot(Math.abs(px) - 0.88, py - 2.12, pz - 0.06);
    acc[q / 3] = Math.max(0, Math.min(1, (0.5 - hand) / 0.18));
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
