// JARVIS Avatar 2.0 — Living Intelligence Projection (3D renderer; Three.js r160 served from this Mac, see
// vendor/three.LICENSE.txt). Loaded by avatar.js only when WebGL works; otherwise the 2D core stays.
//
// It only *shows* the state it is given (setState / setTier / setSystems / pulse): it never fetches, decides or
// acts, and the chat never waits for it. Every visual state comes from a real signal (avatarState() in app.js).
//
// Structure: one figure (body + head on a neck pivot + arms on shoulder pivots), built from named parts in code
// (no downloaded model), each replaceable on its own. Parts above the verified evolution stage are hidden; with
// "full armour from the start" (owner's choice) higher stages add only light and energy. The environment (neural
// lattice, data streams, scan sweep, energy pulses, system satellites) sits behind and around the figure.
//
// Performance: Normal draws at most 30 frames a second (24 on phones) while on screen and visible; Low performance
// and Reduced motion draw only when something changes. Pixel ratio is capped at 1.5. Shared uniforms mean one
// update per frame drives every material.
import * as THREE from "/static/vendor/three.module.min.js";

const CHAMPAGNE = new THREE.Color("#f3e3bd"), WHITE = new THREE.Color("#fff8ec"), AMBER = new THREE.Color("#f2a33a");
const RED = new THREE.Color("#ff5a52"), DIM = new THREE.Color("#9d8e76");

// Per state. tint/eyes/rim: colour and glow · scan: scan-line speed · flow: circuit energy (negative = toward the
// head) · ring: orbit speed · beam: projector · reactor: chest energy · neural: lattice activity · data: research
// streams · sweep: vertical scan ring · discharge: reactor arcs · beat: seconds between energy pulses (0 = none) ·
// head: how the head moves · flicker: diagnostic flicker. Only real signals select a state (see app.js).
const LOOKS = {
  unknown:       { tint: "#cbbd9f", rpat: "calm", eyes: 0.35, rim: 0.8, scan: 0.6, flow: 0.1, ring: 0.05, beam: 0.4, reactor: 0.35, neural: 0.05, data: 0, sweep: 0, discharge: 0, beat: 0, head: "still", flicker: 0 },
  idle:          { tint: "#f3e3bd", rpat: "calm", eyes: 0.75, rim: 1.0, scan: 1.0, flow: 0.3, ring: 0.12, beam: 0.65, reactor: 0.55, neural: 0.12, data: 0, sweep: 0, discharge: 0, beat: 0, head: "aware", flicker: 0 },
  listening:     { tint: "#fff6e6", rpat: "calm", eyes: 1.3, rim: 1.25, scan: 1.2, flow: 0.5, ring: 0.3, beam: 0.85, reactor: 0.75, neural: 0.25, data: 0, sweep: 0, discharge: 0, beat: 0, head: "attend", flicker: 0 },
  understanding: { tint: "#fff3d6", rpat: "spin", eyes: 1.0, rim: 1.2, scan: 2.6, flow: -0.8, ring: 0.45, beam: 0.85, reactor: 0.8, neural: 0.7, data: 0, sweep: 0.6, discharge: 0, beat: 0, head: "think", flicker: 0 },
  reasoning:     { tint: "#fff0cc", rpat: "spin", eyes: 1.1, rim: 1.3, scan: 1.6, flow: -1.3, ring: 0.7, beam: 0.9, reactor: 1.0, neural: 1.0, data: 0, sweep: 0.5, discharge: 0.25, beat: 0, head: "think", flicker: 0 },
  planning:      { tint: "#f6e2b0", rpat: "spin", eyes: 1.0, rim: 1.25, scan: 1.8, flow: -1.0, ring: 0.9, beam: 0.9, reactor: 0.95, neural: 0.9, data: 0, sweep: 0.4, discharge: 0.2, beat: 0, head: "think", flicker: 0 },
  researching:   { tint: "#f4ecd8", rpat: "scan", eyes: 1.05, rim: 1.25, scan: 2.4, flow: 0.8, ring: 0.8, beam: 0.95, reactor: 0.9, neural: 0.6, data: 1.0, sweep: 0.9, discharge: 0, beat: 0, head: "scan", flicker: 0 },
  writing:       { tint: "#fff6e2", rpat: "beat", eyes: 1.45, rim: 1.3, scan: 1.4, flow: 1.4, ring: 0.55, beam: 1.0, reactor: 1.0, neural: 0.5, data: 0, sweep: 0, discharge: 0, beat: 0, head: "aware", flicker: 0 },
  speaking:      { tint: "#fff6e2", rpat: "beat", eyes: 1.5, rim: 1.3, scan: 1.2, flow: 1.0, ring: 0.4, beam: 0.95, reactor: 0.9, neural: 0.35, data: 0, sweep: 0, discharge: 0, beat: 0, head: "speak", flicker: 0 },
  coding:        { tint: "#ffd98a", rpat: "surge", eyes: 1.35, rim: 1.35, scan: 1.8, flow: 2.4, ring: 0.7, beam: 1.0, reactor: 1.1, neural: 0.7, data: 0, sweep: 0.3, discharge: 0.2, beat: 0, head: "think", flicker: 0 },
  verifying:     { tint: "#f3f0e6", rpat: "scan", eyes: 1.1, rim: 1.2, scan: 3.6, flow: 0.9, ring: 0.5, beam: 0.95, reactor: 0.9, neural: 0.5, data: 0, sweep: 1.0, discharge: 0, beat: 0, head: "scan", flicker: 0 },
  executing:     { tint: "#f8dda0", rpat: "surge", eyes: 1.2, rim: 1.35, scan: 1.8, flow: 1.8, ring: 1.2, beam: 1.05, reactor: 1.35, neural: 0.6, data: 0, sweep: 0.3, discharge: 0.55, beat: 1.8, head: "aware", flicker: 0 },
  approval:      { tint: "#f2a33a", rpat: "beat", eyes: 1.05, rim: 1.3, scan: 1.0, flow: 0.4, ring: 0.2, beam: 0.85, reactor: 0.85, neural: 0.2, data: 0, sweep: 0, discharge: 0, beat: 2.8, head: "attend", flicker: 0 },
  warning:       { tint: "#f5d49a", rpat: "scan", eyes: 0.9, rim: 1.15, scan: 1.8, flow: 0.3, ring: 0.15, beam: 0.75, reactor: 0.7, neural: 0.15, data: 0, sweep: 0.55, discharge: 0, beat: 0, head: "aware", flicker: 0 },
  completed:     { tint: "#ffe7ad", rpat: "surge", eyes: 1.8, rim: 1.7, scan: 1.0, flow: 1.0, ring: 0.6, beam: 1.2, reactor: 1.6, neural: 0.6, data: 0, sweep: 0, discharge: 0, beat: 0, head: "aware", flicker: 0 },
  error:         { tint: "#ff5a52", rpat: "stutter", eyes: 0.55, rim: 1.1, scan: 0.8, flow: 0.0, ring: 0.0, beam: 0.45, reactor: 0.5, neural: 0.05, data: 0, sweep: 0.7, discharge: 0, beat: 0, head: "still", flicker: 0.45 },
  recovery:      { tint: "#f6e6c2", rpat: "calm", eyes: 0.8, rim: 1.0, scan: 1.5, flow: 0.5, ring: 0.25, beam: 0.7, reactor: 0.6, neural: 0.3, data: 0, sweep: 0.5, discharge: 0, beat: 0, head: "aware", flicker: 0.08 },
  halted:        { tint: "#b9a78a", rpat: "still", eyes: 0.4, rim: 0.85, scan: 0.4, flow: 0.0, ring: 0.0, beam: 0.35, reactor: 0.3, neural: 0.0, data: 0, sweep: 0, discharge: 0, beat: 0, head: "still", flicker: 0 },
};
const NUMERIC = ["eyes", "rim", "scan", "flow", "ring", "beam", "reactor", "neural", "data", "sweep", "discharge", "flicker"];

// ---- shaders ---------------------------------------------------------------------------------------------------
const VERT = `
varying vec3 vNormal; varying vec3 vView; varying vec3 vWorld; varying vec2 vUv;
void main() {
  vec4 world = modelMatrix * vec4(position, 1.0);
  vWorld = world.xyz; vUv = uv;
  vNormal = normalize(normalMatrix * normal);
  vec4 mv = viewMatrix * world;
  vView = -mv.xyz;
  gl_Position = projectionMatrix * mv;
}`;

// Holographic glass: bright rim (Fresnel), fine scan lines, a rising light band, optional energy pulses along a
// path (uv.x), a materialisation edge, a fade into the projector beam, a floor reflection, and a faint projection
// distortion. Shared uniforms (time, tint, gains) are the same objects in every material.
const FRAG = `
uniform vec3 uTint; uniform float uTime, uOpacity, uRim, uRimK, uGain, uSelf, uScan, uFlow, uFlowOn, uFlicker, uReveal, uFadeLow, uReflect, uCore;
varying vec3 vNormal; varying vec3 vView; varying vec3 vWorld; varying vec2 vUv;
float hash(float n) { return fract(sin(n) * 43758.5453); }
void main() {
  float h = uReflect > 0.5 ? -vWorld.y : vWorld.y;
  if (h > uReveal) discard;
  float fres = pow(1.0 - abs(dot(normalize(vNormal), normalize(vView))), 2.0);
  float scan = mix(0.78, 1.0, 0.5 + 0.5 * sin(h * 70.0 - uTime * uScan * 5.0));
  float band = exp(-pow((fract(h * 0.16 - uTime * 0.05 * uScan) - 0.5) * 12.0, 2.0));
  float distort = 0.94 + 0.06 * sin(h * 9.0 + uTime * 2.3) * step(0.985, hash(floor(uTime * 3.0) + floor(h * 6.0)));
  vec3 deep = uTint * vec3(0.95, 0.72, 0.38);
  vec3 col = mix(deep * 0.45, mix(uTint, vec3(1.0, 0.97, 0.9), 0.22), pow(fres, 0.8)) + uTint * band * 0.3;
  float a = (uCore + fres * uRim * uRimK * 0.7) * scan * uOpacity + band * 0.05;
  if (uFlowOn > 0.5) {
    float d = fract(vUv.x * 3.0 - uTime * uFlow * 0.35);
    float pulse = smoothstep(0.0, 0.05, d) * smoothstep(0.22, 0.05, d);
    col += vec3(1.0, 0.96, 0.88) * pulse * 1.4; a = max(a, 0.28 * uOpacity) + pulse * 0.7;
  }
  float edge = smoothstep(uReveal - 0.18, uReveal, h);
  col += vec3(1.0, 0.95, 0.85) * edge * 1.6; a += edge * 0.8;
  a *= smoothstep(uFadeLow, uFadeLow + 0.9, h) * uGain * uSelf * distort;
  if (uReflect > 0.5) a *= 0.2 * smoothstep(-2.2, 0.0, vWorld.y);
  a *= 1.0 - uFlicker * step(0.55, hash(floor(uTime * 18.0))) * 0.65;
  gl_FragColor = vec4(col, clamp(a, 0.0, 1.0));
}`;

const BEAM_VERT = `
varying vec2 vUv; varying vec3 vNormal; varying vec3 vView;
void main() { vUv = uv; vNormal = normalize(normalMatrix * normal); vec4 mv = modelViewMatrix * vec4(position, 1.0);
  vView = -mv.xyz; gl_Position = projectionMatrix * mv; }`;
const BEAM_FRAG = `
uniform vec3 uTint; uniform float uTime, uBeam;
varying vec2 vUv; varying vec3 vNormal; varying vec3 vView;
void main() {
  float up = vUv.y;
  float streak = 0.65 + 0.35 * sin(vUv.x * 62.83 * 3.0 + uTime * 0.7) * sin(vUv.x * 62.83 * 7.0 - uTime * 0.4);
  float side = pow(abs(dot(normalize(vNormal), normalize(vView))), 1.5);
  gl_FragColor = vec4(uTint * 1.1, (1.0 - up) * (1.0 - up) * 0.22 * streak * side * uBeam);
}`;

// rising dust in the beam
const DUST_VERT = `
uniform float uTime, uSpeed, uSize; attribute float aSeed; varying float vA;
void main() {
  vec3 p = position;
  float t = fract(aSeed + uTime * uSpeed * (0.04 + aSeed * 0.05));
  p.y = mix(0.1, 5.2, t);
  float r = mix(1.15, 0.6, t) * (0.25 + 0.75 * fract(aSeed * 7.13));
  float ang = aSeed * 40.0 + uTime * 0.15;
  p.x = cos(ang) * r; p.z = sin(ang) * r * 0.6;
  vA = sin(t * 3.14159) * (0.4 + 0.6 * fract(aSeed * 3.7));
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  gl_PointSize = uSize * (0.6 + fract(aSeed * 11.0)) * (8.0 / -mv.z);
  gl_Position = projectionMatrix * mv;
}`;
const DOT_FRAG = `
uniform vec3 uTint; varying float vA;
void main() { float d = length(gl_PointCoord - 0.5); if (d > 0.5) discard; gl_FragColor = vec4(uTint, vA * smoothstep(0.5, 0.0, d)); }`;

// neural lattice: links light up with pulses travelling along them; links above the current stage stay dark
const NET_VERT = `
attribute float aT; attribute float aPhase; attribute float aStage; varying float vT; varying float vPhase; varying float vOn;
uniform float uStage;
void main() { vT = aT; vPhase = aPhase; vOn = step(aStage, uStage + 0.5);
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`;
const NET_FRAG = `
uniform vec3 uTint; uniform float uTime, uNeural, uGain; varying float vT; varying float vPhase; varying float vOn;
void main() {
  float p = exp(-pow((fract(vT - uTime * (0.25 + uNeural * 0.5) + vPhase) - 0.5) * 16.0, 2.0));
  float a = (0.04 + 0.05 * uNeural + p * 0.75 * uNeural) * vOn * uGain;
  gl_FragColor = vec4(mix(uTint, vec3(1.0, 0.97, 0.9), p), a);
}`;
const NODE_VERT = `
attribute float aStage; attribute float aSeed; uniform float uStage, uTime, uNeural, uSize; varying float vA;
void main() { vA = step(aStage, uStage + 0.5) * (0.3 + 0.7 * uNeural) * (0.6 + 0.4 * sin(uTime * 2.0 + aSeed * 30.0));
  vec4 mv = modelViewMatrix * vec4(position, 1.0); gl_PointSize = uSize * (8.0 / -mv.z); gl_Position = projectionMatrix * mv; }`;

// research data streams: short dashes falling in columns around the projection
const DATA_VERT = `
attribute float aSeed; attribute float aCol; uniform float uTime, uData, uSize; varying float vA;
void main() {
  float ang = -2.5 + aCol * 0.55 + (aCol > 4.5 ? 0.9 : 0.0);
  float r = 1.78 + fract(aSeed * 13.0) * 0.18;
  float t = fract(aSeed + uTime * (0.08 + fract(aSeed * 5.0) * 0.06));
  vec3 p = vec3(sin(ang) * r, mix(5.3, 0.3, t), cos(ang) * r * 0.55 - 0.3);
  vA = uData * sin(t * 3.14159) * (0.4 + 0.6 * fract(aSeed * 7.0));
  vec4 mv = modelViewMatrix * vec4(p, 1.0); gl_PointSize = uSize * (8.0 / -mv.z); gl_Position = projectionMatrix * mv;
}`;
const DASH_FRAG = `
uniform vec3 uTint; varying float vA;
void main() { vec2 c = gl_PointCoord - 0.5; if (abs(c.y) > 0.1 || abs(c.x) > 0.45) discard; gl_FragColor = vec4(uTint, vA); }`;

// ---- geometry helpers ------------------------------------------------------------------------------------------
const V2 = (x, y) => new THREE.Vector2(x, y);
const TORSO = [V2(1.2, 0.45), V2(1.3, 1.1), V2(1.42, 1.75), V2(1.5, 2.2), V2(1.48, 2.45), V2(1.36, 2.62), V2(1.05, 2.78),
               V2(0.62, 2.88), V2(0.34, 2.93)];
const TORSO_Z = 0.5;
function torsoRadius(y) {
  for (let i = 1; i < TORSO.length; i++) {
    if (y <= TORSO[i].y) { const a = TORSO[i - 1], b = TORSO[i]; return a.x + (b.x - a.x) * ((y - a.y) / (b.y - a.y)); }
  }
  return TORSO[TORSO.length - 1].x;
}
function onChest(x, y, lift = 0.025) {   // a point on the front of the torso (for circuits and plates)
  const r = torsoRadius(y), k = Math.min(0.98, Math.abs(x) / r);
  return new THREE.Vector3(x, y, Math.sqrt(1 - k * k) * r * TORSO_Z + lift);
}
function rng(seed) { let s = seed >>> 0; return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296); }

let glowTex = null;
function glowTexture() {
  if (glowTex) return glowTex;
  const c = document.createElement("canvas"); c.width = c.height = 64;
  const g = c.getContext("2d"), r = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  r.addColorStop(0, "rgba(255,250,236,1)"); r.addColorStop(0.35, "rgba(255,236,190,.45)"); r.addColorStop(1, "rgba(255,220,160,0)");
  g.fillStyle = r; g.fillRect(0, 0, 64, 64);
  glowTex = new THREE.CanvasTexture(c);
  return glowTex;
}

export function create(wrap, opts = {}) {
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ alpha: true, antialias: false, powerPreference: "low-power" });
  } catch (e) { return null; }
  if (!renderer.getContext()) return null;
  renderer.setClearColor(0x000000, 0);
  renderer.autoClear = false;
  renderer.info.autoReset = false;   // count both passes of a frame (see stats)
  const phone = matchMedia("(max-width: 760px)").matches;
  renderer.setPixelRatio(Math.min(1.5, window.devicePixelRatio || 1));
  const canvas = renderer.domElement;
  canvas.className = "avatar3d";
  canvas.setAttribute("aria-hidden", "true");
  wrap.prepend(canvas);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(28, 20 / 27, 0.1, 60);
  camera.position.set(0, 2.85, 11.5);
  camera.lookAt(0, 2.68, 0);

  // ---- shared uniforms: one update per frame drives every hologram material ------------------------------------
  const U = { uTime: { value: 0 }, uTint: { value: CHAMPAGNE.clone() }, uRimK: { value: 1 }, uGain: { value: 1 },
              uScan: { value: 1 }, uFlow: { value: 0.3 }, uFlicker: { value: 0 }, uReflect: { value: 0 } };
  const EYE = { value: 1 }, REACTOR = { value: 1 };
  const lineMats = [];
  const parts = {};
  let building = null;   // the part whose meshes are being built (for its reveal uniform and visibility)

  function holo(o = {}) {
    const m = new THREE.ShaderMaterial({
      vertexShader: VERT, fragmentShader: FRAG, transparent: true, depthWrite: false, side: THREE.DoubleSide,
      blending: THREE.AdditiveBlending,
      uniforms: { ...U, uOpacity: { value: o.opacity ?? 0.9 }, uRim: { value: o.rim ?? 1 }, uFlowOn: { value: o.flow ? 1 : 0 },
                  uCore: { value: o.core ?? 0.035 }, uFadeLow: { value: o.fadeLow ?? -10 }, uSelf: o.self || { value: 1 },
                  uReveal: building ? building.reveal : { value: 10 } },
    });
    return m;
  }
  function lines(geo, opacity = 0.32, angle = 24) {
    const m = new THREE.LineBasicMaterial({ color: CHAMPAGNE, transparent: true, opacity, blending: THREE.AdditiveBlending, depthWrite: false });
    m.userData.lineBase = opacity;
    lineMats.push(m);
    return new THREE.LineSegments(new THREE.EdgesGeometry(geo, angle), m);
  }
  const facet = (g) => { const f = g.index ? g.toNonIndexed() : g; f.computeVertexNormals(); return f; };
  const plate = (shape, depth = 0.04, bevel = 0.012) => facet(new THREE.ExtrudeGeometry(shape, { depth, bevelEnabled: true,
    bevelThickness: bevel, bevelSize: bevel, bevelSegments: 1 }));
  const shapeOf = (pts) => { const sh = new THREE.Shape(); sh.moveTo(pts[0][0], pts[0][1]); for (const [x, y] of pts.slice(1)) sh.lineTo(x, y); sh.closePath(); return sh; };

  // ---- hierarchy: body (breathes), head on a neck pivot, arms on shoulder pivots --------------------------------
  // The figure is drawn at 90% around the chest (y = 2.0) so the SVG reactor (#core) stays aligned with it.
  const SCALE = 0.9, BASE_Y = 2.0 * (1 - SCALE);
  const figure = new THREE.Group(); figure.scale.setScalar(SCALE); figure.position.y = BASE_Y;
  scene.add(figure);
  const body = new THREE.Group(); figure.add(body);
  const headPivot = new THREE.Group(); headPivot.position.set(0, 3.0, 0); figure.add(headPivot);
  const head = new THREE.Group(); head.position.y = -3.0; headPivot.add(head);
  const arms = [-1, 1].map((s) => {
    const pivot = new THREE.Group(); pivot.position.set(1.45 * s, 2.55, 0); body.add(pivot);
    const inner = new THREE.Group(); inner.position.set(-1.45 * s, -2.55, 0); pivot.add(inner);
    return { s, pivot, inner };
  });

  // part(name, tier, build): build(add) creates meshes; add(mesh, to = body) puts one where it belongs.
  function part(name, tier, build) {
    const p = { tier, reveal: { value: 10 }, objs: [] };
    parts[name] = p; building = p;
    build((mesh, to = body) => { to.add(mesh); p.objs.push(mesh); return mesh; });
    building = null;
    return p;
  }
  const edged = (add, geo, mesh, o = 0.34, to = body) => {
    const l = add(lines(geo, o, 24), to); l.position.copy(mesh.position); l.rotation.copy(mesh.rotation); l.scale.copy(mesh.scale); return l;
  };

  // ---- projection platform -----------------------------------------------------------------------------------------
  const spinners = [];
  part("pad", 1, (add) => {
    const disc = add(new THREE.Mesh(new THREE.CylinderGeometry(1.25, 1.35, 0.06, 64, 1, false), holo({ opacity: 0.8, rim: 1.2, core: 0.12 })), scene);
    disc.position.y = BASE_Y + 0.03 * SCALE; disc.scale.setScalar(SCALE);
    for (const [r, o, dir] of [[1.45, 0.7, 1], [1.05, 0.5, 1], [1.7, 0.35, -1], [1.95, 0.22, 1]]) {
      const ring = add(new THREE.Mesh(new THREE.TorusGeometry(r, 0.012, 6, 128), holo({ opacity: o, rim: 1.4, flow: true, core: 0.4 })), scene);
      ring.rotation.x = Math.PI / 2; ring.position.y = BASE_Y + 0.065 * SCALE; ring.scale.setScalar(SCALE);
      spinners.push({ obj: ring, speed: 0.2 * dir, axis: "z" });
    }
    const hex = add(lines(new THREE.CylinderGeometry(2.2, 2.2, 0.01, 6), 0.18, 1), scene);   // rotating holographic geometry
    hex.position.y = BASE_Y + 0.05; hex.scale.setScalar(SCALE);
    spinners.push({ obj: hex, speed: -0.05, axis: "y" });
  });

  // ---- body -------------------------------------------------------------------------------------------------------
  part("torso", 1, (add) => {
    const geo = new THREE.LatheGeometry(TORSO, 56);
    const m = add(new THREE.Mesh(geo, holo({ opacity: 0.85, fadeLow: 0.5 })));
    m.scale.z = TORSO_Z;
    const wire = add(new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ color: CHAMPAGNE, wireframe: true, transparent: true, opacity: 0.018,
      blending: THREE.AdditiveBlending, depthWrite: false })));
    wire.scale.z = TORSO_Z;
    const neck = add(new THREE.Mesh(new THREE.CylinderGeometry(0.27, 0.34, 0.42, 24, 1, true), holo({ opacity: 0.85 })));
    neck.position.y = 2.98;
    for (let i = 0; i < 3; i++) {   // neck servo rings
      const ring = add(new THREE.Mesh(new THREE.TorusGeometry(0.31 - i * 0.015, 0.012, 4, 32), holo({ opacity: 1, rim: 1.4, core: 0.4 })));
      ring.rotation.x = Math.PI / 2; ring.position.y = 2.84 + i * 0.09; ring.scale.z = 0.8;
    }
  });
  part("gorget", 1, (add) => {
    for (const [prof, o] of [[[V2(0.33, 3.05), V2(0.42, 2.96), V2(0.6, 2.86), V2(0.82, 2.76)], 1], [[V2(0.3, 3.16), V2(0.36, 3.08), V2(0.47, 3.0)], 0.9]]) {
      const g = facet(new THREE.LatheGeometry(prof, 16));
      const m = add(new THREE.Mesh(g, holo({ opacity: o, rim: 1.6, core: 0.1 })));
      m.scale.z = 0.62; edged(add, g, m, 0.3);
    }
  });
  part("cuirass", 1, (add) => {
    const shell = facet(new THREE.SphereGeometry(1, 16, 10, Math.PI / 2 - 1.25, 2.5, 0.28 * Math.PI, 0.36 * Math.PI));
    const c = add(new THREE.Mesh(shell, holo({ opacity: 0.85, rim: 1.4, core: 0.05, fadeLow: 0.5 })));
    c.position.set(0, 2.08, 0); c.scale.set(1.32, 0.95, 0.88);
    edged(add, shell, c, 0.22);
    for (const s of [-1, 1]) {   // pectoral plates, with a gap for the reactor
      const g = plate(shapeOf([[0.05, 0], [0.6, 0.06], [0.68, -0.22], [0.56, -0.5], [0.16, -0.56], [0.1, -0.3]]), 0.045, 0.015);
      const m = add(new THREE.Mesh(g, holo({ opacity: 0.95, rim: 1.5, core: 0.08, fadeLow: 0.5 })));
      m.position.copy(onChest(0.3 * s, 2.58, 0.1)); m.scale.set(0.82 * s, 0.82, 1); m.rotation.set(-0.12, 0.32 * s, 0.1 * s);
      edged(add, g, m, 0.36);
    }
    for (let r = 0; r < 3; r++) for (const s of [-1, 1]) {   // abdominal plates
      const g = facet(new THREE.BoxGeometry(0.3, 0.16, 0.05));
      const m = add(new THREE.Mesh(g, holo({ opacity: 0.9, rim: 1.4, core: 0.08, fadeLow: 0.5 })));
      m.position.copy(onChest(0.18 * s, 1.45 - r * 0.21, 0.06)); m.rotation.y = 0.12 * s;
      edged(add, g, m, 0.3);
    }
    for (const s of [-1, 1]) for (let i = 0; i < 4; i++) {   // small illuminated components along the ribs
      const led = add(new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.018, 0.02), holo({ opacity: 1, rim: 1, core: 0.9, self: REACTOR })));
      led.position.copy(onChest(0.78 * s, 2.15 - i * 0.12, 0.05)); led.rotation.y = 0.5 * s;
    }
  });
  const joints = [];
  part("mechanics_body", 1, (add) => {
    for (const s of [-1, 1]) {
      for (let i = 0; i < 3; i++) {   // side vents
        const v = add(new THREE.Mesh(new THREE.BoxGeometry(0.14, 0.02, 0.02), holo({ opacity: 1, rim: 1.2, core: 0.5, self: REACTOR })));
        v.position.copy(onChest(1.02 * s, 1.95 - i * 0.08, 0.02)); v.rotation.y = 0.8 * s;
      }
      const cable = new THREE.CatmullRomCurve3([new THREE.Vector3(0.18 * s, 3.08, 0.12), new THREE.Vector3(0.3 * s, 2.92, 0.22),
                                                new THREE.Vector3(0.48 * s, 2.82, 0.2)]);
      add(new THREE.Mesh(new THREE.TubeGeometry(cable, 16, 0.014, 5, false), holo({ opacity: 1, rim: 1.4, flow: true, core: 0.3 })));
    }
  });
  part("pauldrons", 1, (add) => {
    for (const s of [-1, 1]) for (let i = 0; i < 3; i++) {   // layered shoulder lames
      const r = 0.66 - i * 0.08;
      const g = facet(new THREE.SphereGeometry(r, 14, 6, 0, Math.PI * 2, 0, Math.PI / 2));
      const m = add(new THREE.Mesh(g, holo({ opacity: 1 - i * 0.1, rim: 1.6, core: 0.07 })));
      m.position.set((1.3 + i * 0.07) * s, 2.56 - i * 0.16, 0); m.scale.set(1, 0.5, 0.85); m.rotation.z = -0.52 * s;
      edged(add, g, m, 0.3 - i * 0.05);
    }
  });
  part("arms", 1, (add) => {
    for (const { s, inner } of arms) {
      const armGeo = new THREE.LatheGeometry([V2(0.001, 0.0), V2(0.2, 0.05), V2(0.24, 0.5), V2(0.29, 1.0), V2(0.34, 1.3), V2(0.33, 1.5),
                                               V2(0.24, 1.66), V2(0.001, 1.7)], 28);
      const arm = add(new THREE.Mesh(armGeo, holo({ opacity: 0.75, fadeLow: 0.55 })), inner);
      arm.position.set(1.6 * s, 0.95, -0.05); arm.rotation.z = 0.12 * s; arm.scale.z = 0.85;
      const g = facet(new THREE.CylinderGeometry(0.33, 0.3, 0.66, 12, 1, true, -1.6, 3.2));
      const br = add(new THREE.Mesh(g, holo({ opacity: 0.95, rim: 1.5, core: 0.07, fadeLow: 0.55 })), inner);
      br.position.set(1.6 * s, 1.85, -0.03); br.rotation.z = 0.12 * s;
      edged(add, g, br, 0.28, inner);
      const couter = add(new THREE.Mesh(facet(new THREE.SphereGeometry(0.2, 10, 6)), holo({ opacity: 0.9, rim: 1.5, fadeLow: 0.55 })), inner);
      couter.position.set(1.66 * s, 1.08, 0.12); couter.scale.set(1, 0.8, 0.6);
      // internal energy pathway down the arm, and a shoulder actuator
      const path = new THREE.CatmullRomCurve3([[1.42, 2.5], [1.58, 2.1], [1.68, 1.6], [1.7, 1.15]].map(([x, y]) => new THREE.Vector3(x * s, y, 0.3)));
      add(new THREE.Mesh(new THREE.TubeGeometry(path, 30, 0.01, 4, false), holo({ opacity: 0.9, rim: 1, flow: true, core: 0.3, fadeLow: 0.6 })), inner);
      const piston = add(new THREE.Mesh(new THREE.CylinderGeometry(0.035, 0.035, 0.34, 8), holo({ opacity: 1, rim: 1.5, core: 0.25 })), inner);
      piston.position.set(1.18 * s, 2.42, 0.25); piston.rotation.z = 0.7 * s; joints.push({ obj: piston, kind: "piston" });
      for (const [y, r, x] of [[2.45, 0.24, 1.47], [1.2, 0.2, 1.66]]) {   // shoulder and elbow joint rings
        const j = add(new THREE.Mesh(new THREE.TorusGeometry(r, 0.014, 4, 40), holo({ opacity: 1, rim: 1.6, core: 0.35 })), inner);
        j.position.set(x * s, y, 0.18); j.rotation.y = Math.PI / 2 + 0.3 * s; joints.push({ obj: j, kind: "ring" });
      }
    }
  });

  // ---- head: faceless helm with optical sensors (original design: sentinel shell, knight crest) -----------------
  part("helmet", 1, (add) => {
    const prof = [V2(0.001, 3.22), V2(0.42, 3.26), V2(0.6, 3.42), V2(0.7, 3.7), V2(0.72, 3.98), V2(0.69, 4.28), V2(0.58, 4.56), V2(0.38, 4.78), V2(0.001, 4.88)];
    const geo = facet(new THREE.LatheGeometry(prof, 14));
    const shell = add(new THREE.Mesh(geo, holo({ opacity: 0.8, rim: 1.2 })), head);
    shell.scale.set(0.92, 1, 0.98);
    edged(add, geo, shell, 0.16, head);
    const crestGeo = new THREE.TorusGeometry(0.86, 0.055, 4, 64, 2.75).rotateZ(0.22);   // knight crest blade, taller
    const crest = add(new THREE.Mesh(crestGeo, holo({ opacity: 1, rim: 1.8, core: 0.25 })), head);
    crest.rotation.y = Math.PI / 2; crest.position.y = 3.96; crest.scale.set(1, 1, 0.4);
    const fore = plate(shapeOf([[-0.3, 0], [0.3, 0], [0.22, 0.26], [0, 0.34], [-0.22, 0.26]]), 0.04);   // forehead plate
    const fp = add(new THREE.Mesh(fore, holo({ opacity: 1, rim: 1.6, core: 0.08 })), head);
    fp.position.set(0, 4.12, 0.58); fp.rotation.x = -0.45;
    edged(add, fore, fp, 0.38, head);
    for (const sd of [-1, 1]) {   // temple plates
      const tg = plate(shapeOf([[0, 0.18], [0.24, 0.12], [0.22, -0.16], [0, -0.1]]), 0.035);
      const tp = add(new THREE.Mesh(tg, holo({ opacity: 1, rim: 1.6, core: 0.08 })), head);
      tp.position.set(0.5 * sd, 4.05, 0.42); tp.scale.x = sd; tp.rotation.set(0, 0.95 * sd, 0.1 * sd);
      edged(add, tg, tp, 0.36, head);
    }
    for (const s of [-1, 1]) {   // swept side guards with sensor discs
      const g = plate(shapeOf([[-0.22, 0.12], [0.1, 0.16], [0.16, -0.08], [0.02, -0.34], [-0.2, -0.26]]), 0.035);
      const m = add(new THREE.Mesh(g, holo({ opacity: 1, rim: 1.5, core: 0.08 })), head);
      m.position.set(0.64 * s, 3.66, -0.08); m.rotation.set(0, (Math.PI / 2 + 0.35) * s, 0.15 * s);
      edged(add, g, m, 0.34, head);
      const disc = add(new THREE.Mesh(new THREE.CylinderGeometry(0.07, 0.07, 0.05, 20), holo({ opacity: 1, rim: 1.8, core: 0.5, self: EYE })), head);
      disc.rotation.z = Math.PI / 2; disc.position.set(0.69 * s, 3.9, -0.12);
    }
  });
  part("faceplate", 1, (add) => {
    // layered, faceless: a smooth visor shell over a darker inner plate, a V-brow, and plated cheeks and chin
    const visor = new THREE.SphereGeometry(0.735, 40, 16, Math.PI / 2 - 0.9, 1.8, 1.32, 0.5);
    add(new THREE.Mesh(visor, holo({ opacity: 0.9, rim: 1.6, core: 0.06 })), head).position.set(0, 3.9, 0.02);
    const browGeo = plate(shapeOf([[-0.52, 0.1], [0, 0.0], [0.52, 0.1], [0.5, 0.16], [0, 0.07], [-0.5, 0.16]]), 0.06);
    const brow = add(new THREE.Mesh(browGeo, holo({ opacity: 1, rim: 1.8, core: 0.14 })), head);
    brow.position.set(0, 4.03, 0.6); brow.rotation.x = -0.2;
    edged(add, browGeo, brow, 0.45, head);
    for (const s of [-1, 1]) {
      const cg = plate(shapeOf([[0.05, 0.0], [0.42, 0.04], [0.4, -0.2], [0.2, -0.46], [0.04, -0.44]]), 0.04);
      const c = add(new THREE.Mesh(cg, holo({ opacity: 1, rim: 1.5, core: 0.07 })), head);
      c.position.set(0, 3.78, 0.56); c.scale.x = s; c.rotation.set(-0.08, 0.55 * s, 0);
      edged(add, cg, c, 0.34, head);
    }
    const chinGeo = plate(shapeOf([[-0.22, 0.02], [0.22, 0.02], [0.16, -0.16], [0, -0.22], [-0.16, -0.16]]), 0.05);   // solid chin plate, no mouth
    const chin = add(new THREE.Mesh(chinGeo, holo({ opacity: 1, rim: 1.5, core: 0.1 })), head);
    chin.position.set(0, 3.38, 0.6); chin.rotation.x = 0.28;
    edged(add, chinGeo, chin, 0.4, head);
  });
  // optical sensors: lens rings with a glowing iris (no human eyes, no mouth); brighter when attending or speaking
  const eyeGlows = [], irises = [], sparks = [];
  part("sensors", 1, (add) => {
    for (const s of [-1, 1]) {
      const at = new THREE.Vector3(0.24 * s, 3.92, 0.73);
      const hex = add(lines(new THREE.CylinderGeometry(0.12, 0.12, 0.01, 6).rotateX(Math.PI / 2), 0.55, 1), head);   // sensor housing
      hex.position.copy(at); hex.rotation.y = 0.32 * s; hex.scale.y = 0.62;
      const spark = add(new THREE.Mesh(new THREE.SphereGeometry(0.012, 6, 4), holo({ opacity: 2, core: 2, self: EYE })), head);
      spark.userData = { at, s }; sparks.push(spark);
      const ring = add(new THREE.Mesh(new THREE.TorusGeometry(0.085, 0.012, 6, 28), holo({ opacity: 1.4, rim: 2, core: 0.8, self: EYE })), head);
      ring.position.copy(at); ring.rotation.y = 0.32 * s; ring.scale.y = 0.55;
      const iris = add(new THREE.Mesh(new THREE.CircleGeometry(0.05, 20), holo({ opacity: 2.2, rim: 0.5, core: 2.2, self: EYE })), head);
      iris.position.copy(at).add(new THREE.Vector3(0, 0, 0.005)); iris.rotation.y = 0.32 * s; iris.scale.y = 0.55;
      iris.userData.at = iris.position.clone(); irises.push(iris);
      const glow = add(new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTexture(), color: WHITE, transparent: true, opacity: 0.5,
        blending: THREE.AdditiveBlending, depthWrite: false })), head);
      glow.position.copy(at).add(new THREE.Vector3(0, 0, 0.12)); glow.scale.set(0.45, 0.26, 1);
      eyeGlows.push(glow);
    }
  });
  // internal mechanics visible through the glass: slowly turning gear rings inside the helm
  part("mechanics", 1, (add) => {
    for (const [r, y, z, sp] of [[0.26, 4.25, 0.05, 0.3], [0.18, 4.25, 0.05, -0.5], [0.2, 3.6, 0.1, 0.4]]) {
      const g = add(new THREE.Mesh(new THREE.TorusGeometry(r, 0.01, 4, 6 + Math.round(r * 40)), holo({ opacity: 0.6, rim: 1.2, core: 0.25 })), head);
      g.position.set(0, y, z);
      spinners.push({ obj: g, speed: sp, axis: "z" });
    }
  });
  // a scan line sweeping across the visor
  const visorScan = new THREE.Mesh(new THREE.PlaneGeometry(1.1, 0.012), holo({ opacity: 1.2, rim: 0, core: 1.0 }));
  visorScan.position.set(0, 3.9, 0.78); head.add(visorScan); parts.faceplate.objs.push(visorScan);

  // ---- central reactor assembly around the SVG core: independent rings, inner rotor, discharge arcs -------------
  const reactorAt = onChest(0, 2.0, 0.17);
  const reactor = new THREE.Group(); reactor.position.copy(reactorAt); body.add(reactor);
  const reactorRings = [];
  part("reactor", 1, (add) => {
    // three rings turning independently; the middle one carries moving segment pulses (one draw call)
    for (const [r, arc, tube, sp, flow] of [[0.6, Math.PI * 1.7, 0.016, 0.6, false], [0.7, Math.PI * 2, 0.022, -0.35, true], [0.8, Math.PI * 1.2, 0.02, 0.25, false]]) {
      const ring = add(new THREE.Mesh(new THREE.TorusGeometry(r, tube, 4, 96, arc), holo({ opacity: 1, rim: 1.5, flow, core: flow ? 0.2 : 0.55, self: REACTOR })), reactor);
      reactorRings.push({ obj: ring, speed: sp });
    }
    for (let i = 0; i < 3; i++) {   // inner rotor blades just outside the SVG core
      const blade = add(new THREE.Mesh(new THREE.BoxGeometry(0.2, 0.025, 0.01), holo({ opacity: 1, rim: 1, core: 0.7, self: REACTOR })), reactor);
      blade.userData.angle = (i / 3) * Math.PI * 2;
      reactorRings.push({ obj: blade, speed: -1.1, orbit: 0.5 });
    }
  });
  const spokes = new THREE.Group(); reactor.add(spokes);
  part("reactorcore", 1, (add) => {
    const hex = add(lines(new THREE.CylinderGeometry(0.52, 0.52, 0.01, 6).rotateX(Math.PI / 2), 0.5, 1), spokes);
    hex.rotation.z = Math.PI / 6;
    for (let i = 0; i < 6; i++) {
      const sp = add(new THREE.Mesh(new THREE.BoxGeometry(0.008, 0.16, 0.008), holo({ opacity: 1, core: 0.8, self: REACTOR })), spokes);
      const a = (i / 6) * Math.PI * 2; sp.position.set(Math.cos(a) * 0.43, Math.sin(a) * 0.43, 0); sp.rotation.z = a - Math.PI / 2;
    }
  });
  part("reactor2", 3, (add) => {   // stage 3: an outer counter-rotating ring with segments
    const ring = add(new THREE.Mesh(new THREE.TorusGeometry(0.9, 0.006, 4, 120), holo({ opacity: 1, rim: 1.5, flow: true, core: 0.6, self: REACTOR })), reactor);
    reactorRings.push({ obj: ring, speed: -0.15 });
  });
  const arcs = [];
  for (let i = 0; i < 3; i++) {
    const geo = new THREE.BufferGeometry().setAttribute("position", new THREE.BufferAttribute(new Float32Array(8 * 3), 3));
    const mat = new THREE.LineBasicMaterial({ color: WHITE, transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false });
    const l = new THREE.Line(geo, mat); reactor.add(l); arcs.push(l);
  }
  const reactorGlow = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTexture(), color: WHITE, transparent: true, opacity: 0.4,
    blending: THREE.AdditiveBlending, depthWrite: false }));
  reactorGlow.scale.set(1.6, 1.6, 1); reactor.add(reactorGlow);

  // ---- evolution: light and energy only ---------------------------------------------------------------------------
  part("circuits", 2, (add) => {
    const paths = [
      [[0, 2.0], [0.2, 2.25], [0.55, 2.38], [0.95, 2.4]], [[0, 2.0], [-0.2, 2.25], [-0.55, 2.38], [-0.95, 2.4]],
      [[0.25, 1.9], [0.6, 1.8], [0.95, 1.55], [1.15, 1.3]], [[-0.25, 1.9], [-0.6, 1.8], [-0.95, 1.55], [-1.15, 1.3]],
      [[0.12, 1.72], [0.3, 1.35], [0.62, 1.1]], [[-0.12, 1.72], [-0.3, 1.35], [-0.62, 1.1]],
    ];
    for (const pts of paths) {
      const curve = new THREE.CatmullRomCurve3(pts.map(([x, y]) => onChest(x, y, 0.03)));
      add(new THREE.Mesh(new THREE.TubeGeometry(curve, 40, 0.012, 5, false), holo({ opacity: 0.9, rim: 1, flow: true, core: 0.3, fadeLow: 0.5 })));
    }
  });
  part("crestglow", 3, (add) => {
    const g = new THREE.TorusGeometry(0.815, 0.012, 4, 80, 2.7).rotateZ(0.25);
    const m = add(new THREE.Mesh(g, holo({ opacity: 1, rim: 1.8, flow: true, core: 0.6 })), head);
    m.rotation.y = Math.PI / 2; m.position.y = 3.98;
  });
  part("halo", 4, (add) => {
    for (const [r, o, sp] of [[1.22, 0.9, 0.5], [1.36, 0.45, -0.5]]) {
      const ring = add(new THREE.Mesh(new THREE.TorusGeometry(r, 0.01, 6, 160), holo({ opacity: o, rim: 1.5, flow: true, core: 0.5 })), head);
      ring.position.set(0, 3.95, -0.45); spinners.push({ obj: ring, speed: sp * 0.2, axis: "z" });
    }
  });
  part("crown", 4, (add) => {
    for (const s of [-1, 1]) {
      const g = new THREE.TorusGeometry(0.42, 0.008, 4, 40, 1.2).rotateZ(Math.PI / 2 - 0.6);
      const m = add(new THREE.Mesh(g, holo({ opacity: 1, rim: 1.8, flow: true, core: 0.7 })), head);
      m.position.set(0.18 * s, 4.75, -0.1); m.rotation.set(0.2, 0, -0.35 * s);
    }
  });

  // ---- environment ------------------------------------------------------------------------------------------------
  // orbit rings (more layers at stage 2) carrying the eight system satellites (status from the dashboard's snapshot)
  const orbits = new THREE.Group(); figure.add(orbits);
  const orbitRings = [];
  for (const [r, y, tilt, o, tier] of [[2.05, 2.0, 0.18, 0.75, 1], [1.78, 2.0, -0.1, 0.5, 1], [1.12, 3.95, 0.12, 0.6, 1], [2.3, 2.3, 0.3, 0.3, 2]]) {
    building = parts["orbit" + orbitRings.length] = { tier, reveal: { value: 10 }, objs: [] };
    const ring = new THREE.Mesh(new THREE.TorusGeometry(r, 0.008, 6, 160), holo({ opacity: o, rim: 1.5, flow: true, core: 0.55 }));
    building.objs.push(ring); building = null;
    ring.rotation.x = Math.PI / 2 - tilt; ring.position.y = y; ring.userData.spin = tilt > 0 ? 1 : -1;
    orbits.add(ring); orbitRings.push(ring);
  }
  const satellites = [], hitTargets = [];
  const satMat = (c) => new THREE.MeshBasicMaterial({ color: c, transparent: true, opacity: 0.9, blending: THREE.AdditiveBlending, depthWrite: false });
  for (let i = 0; i < 8; i++) {
    const a = (i / 8) * Math.PI * 2 + 0.2;
    const sat = new THREE.Mesh(new THREE.OctahedronGeometry(0.075), satMat(CHAMPAGNE));
    sat.position.set(Math.cos(a) * 2.05, Math.sin(a) * 2.05, 0);
    const hit = new THREE.Mesh(new THREE.SphereGeometry(0.22, 8, 6), new THREE.MeshBasicMaterial({ visible: false }));
    hit.userData.index = i; sat.add(hit);
    orbitRings[0].add(sat); satellites.push(sat); hitTargets.push(hit);
  }
  let systems = [];

  // neural lattice behind the figure: more nodes and links light up at higher verified stages
  const net = (() => {
    const r = rng(7), nodes = [], stages = [];
    for (let i = 0; i < 70; i++) {
      const th = -1.25 + r() * 2.5, ph = -0.55 + r() * 1.4;
      nodes.push(new THREE.Vector3(Math.sin(th) * 2.05 * Math.cos(ph), 2.9 + Math.sin(ph) * 2.0, -1.4 - Math.cos(th) * 1.2));
      stages.push(i < 28 ? 1 : i < 50 ? 3 : 4);
    }
    const pos = [], aT = [], aPhase = [], aStage = [];
    for (let i = 0; i < nodes.length; i++) for (let j = i + 1; j < nodes.length; j++) {
      if (nodes[i].distanceTo(nodes[j]) > 0.95) continue;
      pos.push(...nodes[i].toArray(), ...nodes[j].toArray()); aT.push(0, 1);
      const ph = r(); aPhase.push(ph, ph); const st = Math.max(stages[i], stages[j]); aStage.push(st, st);
    }
    const lg = new THREE.BufferGeometry();
    lg.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
    lg.setAttribute("aT", new THREE.Float32BufferAttribute(aT, 1));
    lg.setAttribute("aPhase", new THREE.Float32BufferAttribute(aPhase, 1));
    lg.setAttribute("aStage", new THREE.Float32BufferAttribute(aStage, 1));
    const uni = { uTint: U.uTint, uTime: U.uTime, uGain: U.uGain, uNeural: { value: 0.1 }, uStage: { value: 1 }, uSize: { value: 4 } };
    const linesObj = new THREE.LineSegments(lg, new THREE.ShaderMaterial({ vertexShader: NET_VERT, fragmentShader: NET_FRAG, uniforms: uni,
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }));
    const ng = new THREE.BufferGeometry();
    ng.setAttribute("position", new THREE.Float32BufferAttribute(nodes.flatMap((n) => n.toArray()), 3));
    ng.setAttribute("aStage", new THREE.Float32BufferAttribute(stages, 1));
    ng.setAttribute("aSeed", new THREE.Float32BufferAttribute(nodes.map(() => r()), 1));
    const pts = new THREE.Points(ng, new THREE.ShaderMaterial({ vertexShader: NODE_VERT, fragmentShader: `uniform vec3 uTint; varying float vA;
      void main() { float d = length(gl_PointCoord - 0.5); if (d > 0.5) discard; gl_FragColor = vec4(uTint, vA * smoothstep(0.5, 0.0, d)); }`,
      uniforms: uni, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }));
    const g = new THREE.Group(); g.add(linesObj, pts); figure.add(g);
    return { g, uni };
  })();

  // light shafts behind the figure, a polar floor grid and a soft glow at the base (static geometry, cheap)
  const shafts = [];
  for (const [x, w, o] of [[-1.35, 0.5, 0.55], [0, 0.8, 0.4], [1.35, 0.5, 0.55]]) {
    const m = new THREE.Mesh(new THREE.PlaneGeometry(w, 5.6), new THREE.ShaderMaterial({ vertexShader: BEAM_VERT, transparent: true,
      depthWrite: false, blending: THREE.AdditiveBlending, uniforms: { uTint: U.uTint, uTime: U.uTime, uBeam: { value: o }, uPhase: { value: x } },
      fragmentShader: `uniform vec3 uTint; uniform float uTime, uBeam, uPhase; varying vec2 vUv;
        void main() { float edge = smoothstep(0.0, 0.5, vUv.x) * smoothstep(1.0, 0.5, vUv.x);
          float a = edge * smoothstep(0.0, 0.35, vUv.y) * (1.0 - vUv.y) * 0.07 * uBeam * (0.75 + 0.25 * sin(uTime * 0.35 + uPhase * 2.0));
          gl_FragColor = vec4(uTint, a); }` }));
    m.position.set(x * SCALE, BASE_Y + 2.8 * SCALE, -2.6); m.scale.setScalar(SCALE); scene.add(m); shafts.push(m);
  }
  const grid = new THREE.LineSegments((() => {
    const pts = [];
    for (let r = 1.6; r <= 3.4; r += 0.45) for (let i = 0; i < 64; i++) {
      const a = (i / 64) * Math.PI * 2, b = ((i + 1) / 64) * Math.PI * 2;
      pts.push(Math.cos(a) * r, 0, Math.sin(a) * r, Math.cos(b) * r, 0, Math.sin(b) * r);
    }
    for (let i = 0; i < 24; i++) { const a = (i / 24) * Math.PI * 2; pts.push(Math.cos(a) * 1.6, 0, Math.sin(a) * 1.6, Math.cos(a) * 3.4, 0, Math.sin(a) * 3.4); }
    return new THREE.BufferGeometry().setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
  })(), new THREE.LineBasicMaterial({ color: CHAMPAGNE, transparent: true, opacity: 0.09, blending: THREE.AdditiveBlending, depthWrite: false }));
  grid.position.y = BASE_Y + 0.02; grid.scale.setScalar(SCALE); scene.add(grid);
  spinners.push({ obj: grid, speed: 0.02, axis: "y" });
  const baseGlow = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTexture(), color: CHAMPAGNE, transparent: true, opacity: 0.35,
    blending: THREE.AdditiveBlending, depthWrite: false }));
  baseGlow.position.set(0, BASE_Y + 0.15, 0.2); baseGlow.scale.set(5, 1.1, 1); scene.add(baseGlow);

  // projector beam, rising dust, research data streams, vertical scan ring, energy pulses
  const beamMat = new THREE.ShaderMaterial({ vertexShader: BEAM_VERT, fragmentShader: BEAM_FRAG, transparent: true, depthWrite: false,
    side: THREE.DoubleSide, blending: THREE.AdditiveBlending, uniforms: { uTint: U.uTint, uTime: U.uTime, uBeam: { value: 0.7 } } });
  const beam = new THREE.Mesh(new THREE.CylinderGeometry(0.72, 1.28, 4.6, 64, 1, true), beamMat);
  beam.scale.setScalar(SCALE); beam.position.y = BASE_Y + 2.33 * SCALE;
  scene.add(beam);
  const points = (n, vert, frag, uniforms, attrs) => {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(n * 3), 3));
    for (const [k, f] of Object.entries(attrs)) g.setAttribute(k, new THREE.BufferAttribute(Float32Array.from({ length: n }, (_, i) => f(i)), 1));
    const p = new THREE.Points(g, new THREE.ShaderMaterial({ vertexShader: vert, fragmentShader: frag, uniforms, transparent: true,
      depthWrite: false, blending: THREE.AdditiveBlending }));
    p.frustumCulled = false; p.scale.setScalar(SCALE); p.position.y = BASE_Y;
    scene.add(p); return p;
  };
  const r2 = rng(11);
  const dust = points(phone ? 70 : 160, DUST_VERT, DOT_FRAG, { uTime: U.uTime, uSpeed: { value: 1 }, uSize: { value: 3.2 }, uTint: { value: WHITE.clone() } },
    { aSeed: () => r2() });
  const data = points(phone ? 60 : 120, DATA_VERT, DASH_FRAG, { uTime: U.uTime, uData: { value: 0 }, uSize: { value: 7 }, uTint: U.uTint },
    { aSeed: () => r2(), aCol: (i) => i % 10 });
  const sweep = new THREE.Mesh(new THREE.TorusGeometry(1.75, 0.008, 4, 120), new THREE.MeshBasicMaterial({ color: WHITE, transparent: true,
    opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false }));
  sweep.rotation.x = Math.PI / 2; figure.add(sweep);
  const pulses = [0, 1, 2].map(() => {
    const m = new THREE.Mesh(new THREE.TorusGeometry(1, 0.012, 4, 96), new THREE.MeshBasicMaterial({ color: WHITE, transparent: true, opacity: 0,
      blending: THREE.AdditiveBlending, depthWrite: false }));
    m.rotation.x = Math.PI / 2; m.position.y = BASE_Y + 0.07; scene.add(m);
    return { m, life: 0 };
  });
  const firePulse = (strength = 1) => {
    const p = pulses.reduce((a, b) => (a.life <= b.life ? a : b));
    p.life = 1; p.strength = strength;
  };

  // ---- state ------------------------------------------------------------------------------------------------------
  const cur = { ...LOOKS.idle, tint: new THREE.Color(LOOKS.idle.tint) };
  let target = LOOKS.idle, state = "idle", tier = 1, mode = opts.mode || "full", intensity = opts.intensity || 1;
  const targetTint = new THREE.Color(LOOKS.idle.tint);
  let t = 0, last = 0, raf = 0, visible = true, flash = 0, settling = 2.5, speech = 0, beatAt = 0, arcAt = 0;
  const headTarget = new THREE.Euler(), headCur = new THREE.Euler();
  // idle liveliness: occasional glances (toward the message box or the side panels) and sensor "shutter blinks"
  const GLANCES = [[0.13, 0], [0.02, -0.26], [0.02, 0.26], [-0.05, -0.12], [0.08, 0.14]];
  let glance = null, glanceAt = 6, blinkAt = 4, blink = 0;

  function setState(s) {
    if (!LOOKS[s] || s === state) return;
    const prev = state;
    state = s; target = LOOKS[s]; targetTint.set(target.tint);
    if (s === "completed") { flash = 1; firePulse(1.4); }
    if (s === "recovery" && mode === "full") for (const p of Object.values(parts)) p.reveal.value = -1.5;   // reconstruction
    if (prev === "halted" && mode === "full") for (const p of Object.values(parts)) p.reveal.value = -1.5;
    settling = 2.5; kick();
  }
  function setTier(n) {
    n = Math.max(1, Math.min(4, Number(n) || 1));
    if (n === tier) return;
    const up = tier !== 0 && n > tier;
    tier = n; applyTier(up);
  }
  function applyTier(animate) {
    for (const p of Object.values(parts)) {
      const show = tier >= p.tier;
      if (show && !p.objs[0]?.visible && animate) p.reveal.value = -1.5;
      for (const o of p.objs) o.visible = show;
    }
    net.uni.uStage.value = tier;
    settling = 3; kick();
  }
  function setMode(m) {
    mode = m;
    if (mode !== "full") for (const p of Object.values(parts)) p.reveal.value = 10;
    settling = 1; kick();
  }
  function setIntensity(x) { intensity = Math.max(0.5, Math.min(1.5, Number(x) || 1)); settling = 1; kick(); }
  // A real speech event (a word boundary from the browser's speech engine) gives the reactor a brief pulse.
  function pulse(strength = 1) { speech = Math.min(1.5, speech + 0.6 * strength); kick(); }
  function setSystems(list) {
    systems = Array.isArray(list) ? list.slice(0, 8) : [];
    satellites.forEach((sat, i) => {
      const st = systems[i]?.status;
      sat.material.color.copy(st === "bad" ? RED : st === "warn" ? AMBER : st === "off" ? DIM : CHAMPAGNE);
      sat.visible = !!systems[i];
    });
    kick();
  }

  for (const p of Object.values(parts)) { p.reveal.value = mode === "full" ? -1.2 : 10; for (const o of p.objs) o.visible = tier >= p.tier; }

  function headMotion() {
    const h = target.head;
    if (h === "attend") headTarget.set(0.1, Math.sin(t * 0.4) * 0.03, 0);              // toward the message box
    else if (h === "think") headTarget.set(-0.04, Math.sin(t * 0.3) * 0.08, 0.04);     // slight tilt, slow scan
    else if (h === "scan") headTarget.set(0.02, Math.sin(t * 0.55) * 0.16, 0);         // looking across sources
    else if (h === "speak") headTarget.set(0.03 + speech * 0.03, Math.sin(t * 0.5) * 0.05, 0);
    else if (h === "still") headTarget.set(0.05, 0, 0);
    else if (glance) headTarget.set(glance[0], glance[1], 0);                          // a glance at something
    else headTarget.set(Math.sin(t * 0.31) * 0.02, Math.sin(t * 0.23) * 0.07, 0);     // awareness
  }

  function regenerateArcs() {
    for (const l of arcs) {
      const a = Math.random() * Math.PI * 2, b = a + (Math.random() - 0.5) * 1.4;
      const from = new THREE.Vector3(Math.cos(a) * 0.82, Math.sin(a) * 0.82, 0), to = new THREE.Vector3(Math.cos(b) * 0.36, Math.sin(b) * 0.36, 0);
      const arr = l.geometry.attributes.position.array;
      for (let i = 0; i < 8; i++) {
        const p = from.clone().lerp(to, i / 7);
        if (i > 0 && i < 7) p.add(new THREE.Vector3((Math.random() - 0.5) * 0.08, (Math.random() - 0.5) * 0.08, 0));
        arr.set(p.toArray(), i * 3);
      }
      l.geometry.attributes.position.needsUpdate = true;
      l.userData.on = Math.random() < 0.7;
    }
  }

  function frame(now) {
    raf = 0;
    if (!visible || document.hidden) return;
    const cap = phone ? 1000 / 24 : 1000 / 30;
    if (mode === "full" && now - last < cap) { raf = requestAnimationFrame(frame); return; }
    const dt = Math.min(0.1, last ? (now - last) / 1000 : 0.033);
    last = now;
    const moving = mode === "full";
    if (moving) t += dt;
    const k = moving ? 1 - Math.exp(-dt * 2.2) : 1;   // ~0.6–1 s blend between states
    for (const key of NUMERIC) cur[key] += ((target[key] ?? 0) - cur[key]) * k;
    cur.tint.lerp(targetTint, k);
    flash = Math.max(0, flash - dt * 0.8);
    speech = Math.max(0, speech - dt * 3);
    let revealing = false;
    for (const p of Object.values(parts)) {
      if (p.reveal.value < 10) { p.reveal.value += dt * (state === "recovery" ? 1.6 : 3.2); revealing = true; if (p.reveal.value >= 6) p.reveal.value = 10; }
    }
    // shared uniforms
    U.uTime.value = t; U.uTint.value.copy(cur.tint); U.uScan.value = cur.scan; U.uFlow.value = cur.flow;
    U.uFlicker.value = moving ? cur.flicker : 0;
    U.uRimK.value = cur.rim * (1 + flash * 0.8);
    U.uGain.value = intensity * (1 + flash * 0.4);
    const eyeLevel = cur.eyes * (1 + flash * 0.6 + speech * 0.4);
    EYE.value = eyeLevel;
    const breathe = moving ? 0.92 + 0.08 * Math.sin(t * 1.3) : 1;
    REACTOR.value = cur.reactor * breathe * (1 + speech * 0.8 + flash);
    const seams = [0.7, 1.0, 1.2, 1.35][tier - 1] || 1;
    for (const m of lineMats) { m.color.copy(cur.tint); m.opacity = m.userData.lineBase * seams * Math.min(1.3, intensity); }
    for (const g of eyeGlows) { g.material.opacity = Math.min(1, 0.7 * eyeLevel * intensity); g.material.color.copy(cur.tint).lerp(WHITE, 0.75); }
    reactorGlow.material.opacity = Math.min(1, 0.25 * REACTOR.value * intensity); reactorGlow.material.color.copy(cur.tint).lerp(WHITE, 0.5);
    beamMat.uniforms.uBeam.value = cur.beam * (1 + flash) * intensity;
    net.uni.uNeural.value = cur.neural;
    data.material.uniforms.uData.value = cur.data;
    data.visible = cur.data > 0.02 && moving;
    dust.material.uniforms.uSpeed.value = 1 + flash * 4 + Math.abs(cur.flow) * 0.3;
    dust.visible = moving;
    // vertical scan ring
    sweep.visible = moving && cur.sweep > 0.02;
    if (sweep.visible) { const y = (t * 1.1) % 5.2; sweep.position.y = y; sweep.material.opacity = cur.sweep * 0.6 * Math.sin((y / 5.2) * Math.PI); }
    // energy pulses from the platform: on success, and on a steady beat while executing or awaiting a decision
    if (moving && target.beat && t - beatAt > target.beat) { beatAt = t; firePulse(0.8); }
    for (const p of pulses) {
      if (p.life > 0) { p.life = Math.max(0, p.life - dt * 0.8); const g = 1 - p.life; p.m.scale.setScalar(SCALE * (1.3 + g * 1.9));
        p.m.material.opacity = p.life * 0.6 * (p.strength || 1) * intensity; p.m.material.color.copy(cur.tint).lerp(WHITE, 0.4); }
      p.m.visible = p.life > 0 && moving;
    }
    // reactor discharge arcs
    const discharging = moving && cur.discharge > 0.15;
    if (discharging && t - arcAt > 0.12) { arcAt = t; regenerateArcs(); }
    for (const l of arcs) { l.visible = discharging && l.userData.on; l.material.opacity = cur.discharge * 0.8 * intensity; }
    if (moving) {
      // breathing body, head and arm motion, rotating rings
      body.scale.y = 1 + Math.sin(t * 1.1) * 0.008; body.position.y = 2.0 * (1 - body.scale.y);
      if (target.head === "aware") {
        if (t > glanceAt) {
          if (glance) { glance = null; glanceAt = t + 6 + Math.random() * 5; }
          else { glance = GLANCES[Math.floor(Math.random() * GLANCES.length)]; glanceAt = t + 1.6 + Math.random(); }
        }
      } else glance = null;
      if (t > blinkAt) { blink = 1; blinkAt = t + 6 + Math.random() * 6; }
      blink = Math.max(0, blink - dt * 5);
      const shut = target.head === "still" ? 1 : 1 - Math.sin(blink * Math.PI) * 0.85;
      const narrow = state === "warning" || state === "error" ? 0.6 : 1;
      const look = state === "researching" || state === "verifying" ? Math.sin(t * 2.2) * 0.022 : glance ? glance[1] * 0.05 : 0;
      irises.forEach((ir, i) => { ir.scale.y = 0.55 * shut * narrow; ir.position.x = ir.userData.at.x + look;
        const pulse = state === "reasoning" || state === "understanding" ? 0.85 + 0.15 * Math.sin(t * 3 + i) : 1; ir.scale.x = pulse; });
      sparks.forEach((sp, i) => { const a = t * (1.5 + cur.scan * 0.4) + i * Math.PI; const { at, s: sd } = sp.userData;
        sp.position.set(at.x + Math.cos(a) * 0.1, at.y + Math.sin(a) * 0.06, at.z + 0.01); sp.visible = sd !== 0; });
      const busy = state === "executing" || state === "coding" ? 1 : 0.2;
      for (const j of joints) {
        if (j.kind === "ring") j.obj.rotation.z += dt * (0.3 + busy * 2.5);
        else j.obj.scale.y = 1 + Math.sin(t * (1 + busy * 3)) * 0.12 * busy;
      }
      // the reactor's own pattern per state
      const rp = target.rpat;
      const spin = rp === "spin" ? 2.4 : rp === "surge" ? 1.8 : rp === "scan" ? 1.2 : rp === "stutter" ? (Math.sin(t * 9) > 0.6 ? 2 : 0) : rp === "still" ? 0 : 0.6;
      spokes.rotation.z += dt * spin * 0.5 * (rp === "spin" ? -1 : 1);
      const beatK = rp === "beat" ? 1 + Math.max(0, Math.sin(t * 5)) * 0.06 + speech * 0.08 : rp === "surge" ? 1 + Math.sin(t * 8) * 0.03 : 1;
      reactor.scale.setScalar(beatK);
      if (rp === "scan") reactorRings[2] && (reactorRings[2].obj.rotation.z = Math.sin(t * 1.4) * 1.6);
      headMotion();
      for (const ax of ["x", "y", "z"]) headCur[ax] += (headTarget[ax] - headCur[ax]) * (1 - Math.exp(-dt * 2.5));
      headPivot.rotation.copy(headCur);
      const armAmp = state === "executing" || state === "coding" ? 0.025 : 0.01;
      for (const a of arms) a.pivot.rotation.z = a.s * armAmp * Math.sin(t * 0.8 + a.s);
      orbitRings.forEach((r) => { r.rotation.z += dt * (0.05 + cur.ring) * r.userData.spin; });
      for (const s of spinners) s.obj.rotation[s.axis] += dt * s.speed * (0.5 + cur.ring);
      for (const rr of reactorRings) {
        if (rr.orbit) { rr.obj.userData.angle += dt * rr.speed * (0.4 + cur.reactor); const a = rr.obj.userData.angle;
          rr.obj.position.set(Math.cos(a) * rr.orbit, Math.sin(a) * rr.orbit, 0); rr.obj.rotation.z = a; }
        else if (!(target.rpat === "scan" && rr === reactorRings[2])) rr.obj.rotation.z += dt * rr.speed * (0.4 + cur.reactor) * (target.rpat === "spin" ? 2.2 : target.rpat === "still" ? 0 : 1);
      }
      visorScan.position.y = 3.9 + Math.sin(t * (0.6 + cur.scan * 0.3)) * 0.14;
      visorScan.visible = parts.faceplate.objs[0].visible;
    }
    // draw: the figure and environment, then the floor reflection as a second pass of the same figure
    renderer.info.reset();
    renderer.clear();
    renderer.render(scene, camera);
    // the head reflects ~4 units below the floor, where the reflection has faded to nothing: skip it
    const hidden = [beam, dust, data, sweep, net.g, orbits, reactor, grid, baseGlow, headPivot, ...shafts, ...pulses.map((p) => p.m), ...eyeGlows, ...parts.pad.objs];
    const was = hidden.map((o) => o.visible);
    hidden.forEach((o) => { o.visible = false; });
    for (const m of lineMats) m.visible = false;
    figure.scale.y = -SCALE; U.uReflect.value = 1;
    renderer.render(scene, camera);
    figure.scale.y = SCALE; U.uReflect.value = 0;
    hidden.forEach((o, i) => { o.visible = was[i]; });
    for (const m of lineMats) m.visible = true;
    settling -= dt;
    if (moving || revealing || settling > 0 && mode === "full") raf = requestAnimationFrame(frame);
  }
  function kick() { if (!raf && visible && !document.hidden) raf = requestAnimationFrame(frame); }

  // picking: satellites answer hover and click; the caller decides what a click means
  const ray = new THREE.Raycaster(), ndc = new THREE.Vector2();
  function pick(clientX, clientY) {
    const r = canvas.getBoundingClientRect();
    ndc.set(((clientX - r.left) / r.width) * 2 - 1, -((clientY - r.top) / r.height) * 2 + 1);
    figure.updateMatrixWorld(true);   // the reflection pass leaves the figure's matrices mirrored until the next frame
    ray.setFromCamera(ndc, camera);
    const hit = ray.intersectObjects(hitTargets, false).find((h) => h.object.parent.visible);
    return hit ? systems[hit.object.userData.index] || null : null;
  }

  function resize() {
    const r = wrap.getBoundingClientRect();
    if (!r.width || !r.height) return;
    renderer.setSize(r.width, r.height, false);
    camera.aspect = r.width / r.height; camera.updateProjectionMatrix();
    kick();
  }
  const ro = new ResizeObserver(resize); ro.observe(wrap);
  const io = new IntersectionObserver((e) => { visible = e.some((x) => x.isIntersecting); if (visible) kick(); }); io.observe(wrap);
  const onVis = () => { last = 0; kick(); };
  document.addEventListener("visibilitychange", onVis);
  let lost = false;
  canvas.addEventListener("webglcontextlost", (e) => { e.preventDefault(); lost = true; api.onLost && api.onLost(); });

  setState(opts.state || "idle");
  tier = 0; setTier(opts.tier || 1);
  resize();

  const api = {
    setState, setTier, setMode, setIntensity, setSystems, pulse, pick, onLost: null,
    get animating() { return raf !== 0; }, get lost() { return lost; }, get state() { return state; },
    get stats() { return { calls: renderer.info.render.calls, triangles: renderer.info.render.triangles }; },
    dispose() { cancelAnimationFrame(raf); ro.disconnect(); io.disconnect(); document.removeEventListener("visibilitychange", onVis);
      renderer.dispose(); canvas.remove(); },
  };
  return api;
}

export const STATES = Object.keys(LOOKS);
