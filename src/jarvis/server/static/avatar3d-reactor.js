// JARVIS avatar: the chest reactor's added layers (the signature piece). The existing rings, rotor, hex cage and
// discharge arcs stay in avatar3d.js; this module adds, in depth order:
//   a plasma core sphere, two tilted gyroscope rings, an inner segmented ring, radial energy pathways with pulses
//   travelling outward, mechanical supports locking it into the chest plates, a swirl of energy particles, and the
//   golden confirmation pulse shown only when a task really completes.
// Every level comes from the caller (the real reactor level of the current state); nothing here invents activity.
import * as THREE from "/static/vendor/three.module.min.js";

const CORE_VERT = `varying vec3 vN; varying vec3 vV; varying vec3 vP;
void main() { vP = position; vN = normalize(normalMatrix * normal); vec4 mv = modelViewMatrix * vec4(position, 1.0); vV = -mv.xyz;
  gl_Position = projectionMatrix * mv; }`;
const CORE_FRAG = `uniform vec3 uTint; uniform float uTime, uLvl, uGain; varying vec3 vN; varying vec3 vV; varying vec3 vP;
void main() {
  float f = pow(1.0 - abs(dot(normalize(vN), normalize(vV))), 1.6);
  float plasma = 0.5 + 0.5 * sin(vP.x * 26.0 + uTime * 2.1) * sin(vP.y * 23.0 - uTime * 1.7) * sin(vP.z * 29.0 + uTime * 1.3);
  vec3 col = mix(uTint, vec3(1.0, 0.98, 0.92), 0.55 + 0.45 * (1.0 - f)) * (0.55 + 0.6 * plasma);
  gl_FragColor = vec4(col * (0.3 + 0.45 * min(uLvl, 1.6)), clamp((0.25 + 0.5 * (1.0 - f)) * (0.3 + 0.6 * min(uLvl, 1.5)) * uGain, 0.0, 1.0));   // bright, never a blown-out disc
}`;
const SWIRL_VERT = `attribute float aSeed; uniform float uTime, uLvl; varying float vA;
void main() { float a = aSeed * 40.0 + uTime * (0.6 + aSeed) * (0.4 + uLvl); float r = 0.28 + fract(aSeed * 7.3) * 0.75;
  vec3 p = vec3(cos(a) * r, sin(a) * r, (fract(aSeed * 3.1) - 0.5) * 0.25);
  vA = (0.3 + 0.7 * fract(aSeed * 11.0)) * min(uLvl, 1.4) * smoothstep(1.05, 0.6, r);
  vec4 mv = modelViewMatrix * vec4(p, 1.0); gl_PointSize = (2.0 + fract(aSeed * 5.0) * 3.0) * (8.0 / -mv.z); gl_Position = projectionMatrix * mv; }`;
const SWIRL_FRAG = `uniform vec3 uTint; uniform float uGain; varying float vA;
void main() { float d = length(gl_PointCoord - 0.5); if (d > 0.5) discard; gl_FragColor = vec4(mix(uTint, vec3(1.0), 0.5), vA * smoothstep(0.5, 0.0, d) * uGain); }`;

// ctx: { holo, part, U, REACTOR, phone }; parent: the reactor group (local units, radius ~1).
export function buildReactor(ctx, parent) {
  const { holo, part, U, REACTOR, phone } = ctx;
  const spin = [];   // { obj, axis, speed }
  let core = null, swirl = null, pathMat = null;

  part("reactorcore2", 1, (add) => {   // the plasma core: brightest at the centre, follows the real reactor level
    core = add(new THREE.Mesh(new THREE.SphereGeometry(0.17, 32, 24), new THREE.ShaderMaterial({
      vertexShader: CORE_VERT, fragmentShader: CORE_FRAG, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
      uniforms: { uTint: U.uTint, uTime: U.uTime, uGain: U.uGain, uLvl: REACTOR } })), parent);
    core.position.z = 0.02;
    // the inner segmented ring: twelve small blocks just outside the core
    const segGeo = [];
    for (let i = 0; i < 12; i++) {
      const g = new THREE.BoxGeometry(0.07, 0.022, 0.03), a = (i / 12) * Math.PI * 2;
      g.translate(0.31, 0, 0); g.rotateZ(a); segGeo.push(g);
    }
    const segs = add(new THREE.Mesh(mergeBoxes(segGeo), holo({ opacity: 1, rim: 1.2, core: 0.75, self: REACTOR })), parent);
    segs.position.z = 0.05; spin.push({ obj: segs, axis: "z", speed: 0.9 });
  });
  part("reactorgyro", 2, (add) => {   // stage 2: two tilted gyroscope rings, turning on their own axes (depth)
    for (const [r, tilt, sp] of [[0.4, 0.9, 0.7], [0.46, -0.7, -0.5]]) {
      const pivot = new THREE.Group(); pivot.rotation.x = tilt; parent.add(pivot);
      const ring = add(new THREE.Mesh(new THREE.TorusGeometry(r, 0.008, 6, 96), holo({ opacity: 1, rim: 1.6, flow: true, core: 0.55, self: REACTOR })), pivot);
      spin.push({ obj: pivot, axis: "y", speed: sp });
      ring.userData.gyro = true;
    }
  });
  part("reactorpaths", 1, (add) => {   // radial energy pathways: pulses travel outward from the core
    const geos = [];
    for (let i = 0; i < 8; i++) {
      const a = (i / 8) * Math.PI * 2 + Math.PI / 8;
      const pts = [0.24, 0.55, 0.96].map((rr, j) => new THREE.Vector3(Math.cos(a + j * 0.06) * rr, Math.sin(a + j * 0.06) * rr, 0.04 - j * 0.03));
      geos.push(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts), 24, 0.008, 4, false));
    }
    pathMat = holo({ opacity: 1, rim: 0.8, flow: true, core: 0.3, self: REACTOR });
    add(new THREE.Mesh(mergeBoxes(geos), pathMat), parent);
  });
  part("reactorsupports", 1, (add) => {   // mechanical supports locking the reactor into the chest plates
    const geos = [];
    for (let i = 0; i < 6; i++) {
      const a = (i / 6) * Math.PI * 2;
      const g = new THREE.BoxGeometry(0.2, 0.05, 0.05); g.translate(1.02, 0, -0.05); g.rotateZ(a); geos.push(g);
      const p = new THREE.CylinderGeometry(0.018, 0.018, 0.09, 8); p.rotateX(Math.PI / 2); p.translate(0.9, 0, 0.0); p.rotateZ(a); geos.push(p);
    }
    const m = add(new THREE.Mesh(mergeBoxes(geos), new THREE.MeshBasicMaterial({ color: 0x241a10, transparent: true, opacity: 0.95 })), parent);
    m.renderOrder = -1;   // drawn with the plates: solid, never glowing in front
    add(new THREE.Mesh(mergeBoxes(geos.map((g) => g.clone())), holo({ opacity: 0.9, rim: 2.0, core: 0.0, self: REACTOR })), parent);   // their lit edges
  });
  if (!phone) part("reactorswirl", 1, (add) => {   // a swirl of energy particles around the core
    const N = 90, seed = new Float32Array(N); for (let i = 0; i < N; i++) seed[i] = (i * 0.618034) % 1;
    const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(N * 3), 3));
    g.setAttribute("aSeed", new THREE.BufferAttribute(seed, 1));
    swirl = add(new THREE.Points(g, new THREE.ShaderMaterial({ vertexShader: SWIRL_VERT, fragmentShader: SWIRL_FRAG, transparent: true,
      depthWrite: false, blending: THREE.AdditiveBlending, uniforms: { uTint: U.uTint, uTime: U.uTime, uGain: U.uGain, uLvl: REACTOR } })), parent);
    swirl.frustumCulled = false;
  });
  // the golden confirmation pulse (a real completion only): a ring expanding from the core and fading
  const confirmRing = new THREE.Mesh(new THREE.TorusGeometry(1, 0.02, 6, 96), new THREE.MeshBasicMaterial({
    color: new THREE.Color("#ffd27a").multiplyScalar(1.6), transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false }));
  parent.add(confirmRing); confirmRing.visible = false;
  let confirmT = -1;

  return {
    swirl: () => swirl,
    confirm() { confirmT = 0; confirmRing.visible = true; },
    update(dt, moving, rp) {
      const mult = rp === "spin" ? 2.2 : rp === "surge" ? 1.8 : rp === "scan" ? 1.2 : rp === "still" ? 0 : rp === "stutter" ? 0.4 : 0.7;
      if (moving) for (const s of spin) s.obj.rotation[s.axis] += dt * s.speed * mult;
      if (confirmT >= 0) {
        confirmT += dt;
        const k = Math.min(1, confirmT / 1.2);
        confirmRing.scale.setScalar(0.6 + k * 2.4); confirmRing.material.opacity = (1 - k) * 0.9;
        if (k >= 1) { confirmT = -1; confirmRing.visible = false; }
      }
      return confirmT >= 0;   // still animating
    },
    hidden: () => [confirmRing, ...(swirl ? [swirl] : [])],
  };
}

function mergeBoxes(geos) {   // non-indexed merge for small part sets (position, normal, uv)
  const parts = geos.map((g) => (g.index ? g.toNonIndexed() : g));
  let n = 0; for (const g of parts) n += g.attributes.position.count;
  const pos = new Float32Array(n * 3), nrm = new Float32Array(n * 3), uv = new Float32Array(n * 2);
  let o = 0;
  for (const g of parts) {
    pos.set(g.attributes.position.array, o * 3); nrm.set(g.attributes.normal.array, o * 3);
    if (g.attributes.uv) uv.set(g.attributes.uv.array, o * 2);
    o += g.attributes.position.count;
  }
  const out = new THREE.BufferGeometry();
  out.setAttribute("position", new THREE.BufferAttribute(pos, 3)); out.setAttribute("normal", new THREE.BufferAttribute(nrm, 3));
  out.setAttribute("uv", new THREE.BufferAttribute(uv, 2));
  return out;
}
