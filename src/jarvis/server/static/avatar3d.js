// JARVIS holographic core — 3D renderer (Three.js r160, served from this Mac; see vendor/three.LICENSE.txt).
// Loaded by avatar.js only when WebGL works; otherwise the 2D core stays. Like the 2D core it only *shows* the
// state it is given: it never fetches, decides or acts, and the chat never waits for it.
//
// The figure is built from simple shapes in code (no downloaded model): every part is named and can be replaced
// on its own (helmet, faceplate, visor, ears, crest…). Parts above the verified evolution tier are hidden.
//
// Performance: Normal draws at most 30 frames a second (24 on phones) while on screen and visible; Low
// performance and Reduced motion draw only when something changes. Pixel ratio is capped at 1.5.
import * as THREE from "/static/vendor/three.module.min.js";

const GOLD = new THREE.Color("#d9b45f"), CHAMPAGNE = new THREE.Color("#f3e3bd"), WHITE = new THREE.Color("#fff8ec");
// Per state: tint, rim, scan speed, energy flow, ring speed, beam, chest light, flicker. Values chosen for legibility
// at a glance; every state is driven by a real signal (see avatarState() in app.js).
const LOOKS = {
  idle:          { tint: "#f3e3bd", eyes: 0.8, rim: 1.0, scan: 1.0, flow: 0.35, ring: 0.12, beam: 0.65, light: 1.0, flicker: 0 },
  listening:     { tint: "#d6f3ff", eyes: 1.25, rim: 1.3, scan: 1.4, flow: 0.6,  ring: 0.45, beam: 0.9,  light: 1.2, flicker: 0, pulse: 2.6 },
  understanding: { tint: "#fff3d6", eyes: 1.0, rim: 1.2, scan: 3.0, flow: 0.7,  ring: 0.35, beam: 0.85, light: 1.15, flicker: 0 },
  planning:      { tint: "#f6e2b0", eyes: 1.0, rim: 1.2, scan: 1.6, flow: 0.9,  ring: 0.9,  beam: 0.9,  light: 1.2, flicker: 0 },
  researching:   { tint: "#e6dcff", eyes: 1.05, rim: 1.25, scan: 2.6, flow: 0.8, ring: 0.8,  beam: 0.95, light: 1.2, flicker: 0 },
  reasoning:     { tint: "#fff0cc", eyes: 1.1, rim: 1.3, scan: 1.2, flow: -1.2, ring: 0.5,  beam: 0.9,  light: 1.35, flicker: 0, pulse: 1.4 },
  writing:       { tint: "#fff6e2", eyes: 1.6, rim: 1.35, scan: 1.4, flow: 1.6, ring: 0.55, beam: 1.0,  light: 1.4, flicker: 0 },
  coding:        { tint: "#ffd98a", eyes: 1.4, rim: 1.35, scan: 1.8, flow: 2.6, ring: 0.7,  beam: 1.0,  light: 1.4, flicker: 0 },
  verifying:     { tint: "#f3f0e6", eyes: 1.1, rim: 1.2, scan: 4.0, flow: 0.9,  ring: 0.5,  beam: 0.95, light: 1.25, flicker: 0 },
  approval:      { tint: "#f2a33a", eyes: 1.1, rim: 1.3, scan: 1.0, flow: 0.4,  ring: 0.2,  beam: 0.85, light: 1.3, flicker: 0, pulse: 1.8 },
  executing:     { tint: "#f8dda0", eyes: 1.2, rim: 1.3, scan: 1.8, flow: 1.7, ring: 1.2,  beam: 1.0,  light: 1.4, flicker: 0 },
  completed:     { tint: "#ffffff", eyes: 2.0, rim: 1.8, scan: 1.0, flow: 1.0, ring: 0.6,  beam: 1.2,  light: 2.2, flicker: 0 },
  error:         { tint: "#ff6b62", eyes: 0.45, rim: 1.1, scan: 0.6, flow: 0.0, ring: 0.0,  beam: 0.45, light: 0.6, flicker: 0.8 },
};

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

// Holographic glass: bright rim (Fresnel), fine scan lines, a slow light band rising through the figure, optional
// energy pulses along a path (uv.x), a materialisation edge, a fade into the projector beam, and a floor reflection.
const FRAG = `
uniform vec3 uTint; uniform float uTime, uOpacity, uRim, uScan, uFlow, uFlowOn, uFlicker, uReveal, uFadeLow, uReflect, uCore;
varying vec3 vNormal; varying vec3 vView; varying vec3 vWorld; varying vec2 vUv;
float hash(float n) { return fract(sin(n) * 43758.5453); }
void main() {
  float h = uReflect > 0.5 ? -vWorld.y : vWorld.y;
  if (h > uReveal) discard;
  float fres = pow(1.0 - abs(dot(normalize(vNormal), normalize(vView))), 2.0);
  float scan = mix(0.78, 1.0, 0.5 + 0.5 * sin(h * 70.0 - uTime * uScan * 5.0));
  float band = exp(-pow((fract(h * 0.16 - uTime * 0.05 * uScan) - 0.5) * 12.0, 2.0));
  vec3 deep = uTint * vec3(0.95, 0.72, 0.38);
  vec3 col = mix(deep * 0.45, mix(uTint, vec3(1.0, 0.97, 0.9), 0.22), pow(fres, 0.8)) + uTint * band * 0.3;
  float a = (uCore + fres * uRim * 0.7) * scan * uOpacity + band * 0.05;
  if (uFlowOn > 0.5) {
    float d = fract(vUv.x * 3.0 - uTime * uFlow * 0.35);
    float pulse = smoothstep(0.0, 0.05, d) * smoothstep(0.22, 0.05, d);
    col += vec3(1.0, 0.96, 0.88) * pulse * 1.4; a = max(a, 0.28 * uOpacity) + pulse * 0.7;
  }
  float edge = smoothstep(uReveal - 0.18, uReveal, h);
  col += vec3(1.0, 0.95, 0.85) * edge * 1.6; a += edge * 0.8;
  a *= smoothstep(uFadeLow, uFadeLow + 0.9, h);
  if (uReflect > 0.5) a *= 0.2 * smoothstep(-2.2, 0.0, vWorld.y);
  a *= 1.0 - uFlicker * step(0.55, hash(floor(uTime * 22.0))) * 0.65;
  gl_FragColor = vec4(col, clamp(a, 0.0, 1.0));
}`;

const BEAM_FRAG = `
uniform vec3 uTint; uniform float uTime, uBeam;
varying vec2 vUv; varying vec3 vNormal; varying vec3 vView;
float hash(float n) { return fract(sin(n) * 43758.5453); }
void main() {
  float up = vUv.y;
  float streak = 0.65 + 0.35 * sin(vUv.x * 62.83 * 3.0 + uTime * 0.7) * sin(vUv.x * 62.83 * 7.0 - uTime * 0.4);
  float side = pow(abs(dot(normalize(vNormal), normalize(vView))), 1.5);
  float a = (1.0 - up) * (1.0 - up) * 0.22 * streak * side * uBeam;
  gl_FragColor = vec4(uTint * 1.1, a);
}`;
const BEAM_VERT = `
varying vec2 vUv; varying vec3 vNormal; varying vec3 vView;
void main() { vUv = uv; vNormal = normalize(normalMatrix * normal); vec4 mv = modelViewMatrix * vec4(position, 1.0);
  vView = -mv.xyz; gl_Position = projectionMatrix * mv; }`;

const DUST_VERT = `
uniform float uTime, uSpeed, uSize; attribute float aSeed;
varying float vA;
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
const DUST_FRAG = `
uniform vec3 uTint; varying float vA;
void main() { float d = length(gl_PointCoord - 0.5); if (d > 0.5) discard;
  gl_FragColor = vec4(uTint, vA * smoothstep(0.5, 0.0, d)); }`;

// ---- geometry helpers ---------------------------------------------------------------------------------------
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
// A point on the front of the torso (for circuits and plates).
function onChest(x, y, lift = 0.025) {
  const r = torsoRadius(y), k = Math.min(0.98, Math.abs(x) / r);
  return new THREE.Vector3(x, y, Math.sqrt(1 - k * k) * r * TORSO_Z + lift);
}

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

  const mats = [];           // every hologram material (time and look are updated together)
  const parts = {};          // name -> { group, tier, reveal }
  // The figure is drawn at 90% around the chest (y = 2.0), so the reactor overlay (#core) stays aligned.
  const SCALE = 0.9, BASE_Y = 2.0 * (1 - SCALE);
  const figure = new THREE.Group(), mirror = new THREE.Group();
  figure.scale.setScalar(SCALE); figure.position.y = BASE_Y;
  mirror.scale.set(SCALE, -SCALE, SCALE); mirror.position.y = BASE_Y;
  scene.add(figure, mirror);

  function holo(o = {}) {
    const m = new THREE.ShaderMaterial({
      vertexShader: VERT, fragmentShader: FRAG, transparent: true, depthWrite: false, side: THREE.DoubleSide,
      blending: THREE.AdditiveBlending,
      uniforms: { uTint: { value: CHAMPAGNE.clone() }, uTime: { value: 0 }, uOpacity: { value: o.opacity ?? 0.9 },
        uRim: { value: o.rim ?? 1 }, uScan: { value: 1 }, uFlow: { value: 0.4 }, uFlowOn: { value: o.flow ? 1 : 0 },
        uFlicker: { value: 0 }, uReveal: { value: -2 }, uFadeLow: { value: o.fadeLow ?? -10 }, uReflect: { value: 0 },
        uCore: { value: o.core ?? 0.035 } },
    });
    m.userData.base = { opacity: o.opacity ?? 0.9, rim: o.rim ?? 1 };
    mats.push(m);
    return m;
  }
  const lineMats = [];
  function lines(geo, opacity = 0.32, angle = 28) {
    const m = new THREE.LineBasicMaterial({ color: CHAMPAGNE, transparent: true, opacity, blending: THREE.AdditiveBlending, depthWrite: false });
    m.userData.lineBase = opacity;
    lineMats.push(m);
    return new THREE.LineSegments(new THREE.EdgesGeometry(geo, angle), m);
  }

  // part(name, tier, build): build(add) adds meshes; reflect=true also adds a mirrored copy for the floor.
  function part(name, tier, build, reflect = true) {
    const group = new THREE.Group(), refl = new THREE.Group();
    const add = (mesh, withReflection = reflect) => {
      group.add(mesh);
      if (withReflection && mesh.isMesh && mesh.material.uniforms) {
        const copy = new THREE.Mesh(mesh.geometry, mesh.material.clone());
        copy.material.uniforms.uReflect.value = 1;
        copy.material.userData.base = mesh.material.userData.base;
        mats.push(copy.material);
        copy.position.copy(mesh.position); copy.rotation.copy(mesh.rotation); copy.scale.copy(mesh.scale);
        refl.add(copy);
      }
      return mesh;
    };
    build(add);
    figure.add(group); mirror.add(refl);
    const own = [];
    group.traverse((o) => o.material && o.material.uniforms && own.push(o.material));
    refl.traverse((o) => o.material && o.material.uniforms && own.push(o.material));
    parts[name] = { group, refl, tier, reveal: -2, mats: own };
    return parts[name];
  }

  // ---- the figure ------------------------------------------------------------------------------------------
  part("pad", 1, (add) => {
    const disc = add(new THREE.Mesh(new THREE.CylinderGeometry(1.25, 1.35, 0.06, 64, 1, false), holo({ opacity: 0.8, rim: 1.2, core: 0.12 })), false);
    disc.position.y = 0.03;
    for (const [r, o] of [[1.45, 0.7], [1.05, 0.5], [1.7, 0.35]]) {
      const ring = add(new THREE.Mesh(new THREE.TorusGeometry(r, 0.012, 6, 128), holo({ opacity: o, rim: 1.4, flow: true, core: 0.4 })), false);
      ring.rotation.x = Math.PI / 2; ring.position.y = 0.065; ring.userData.spin = r === 1.7 ? -1 : 1;
    }
  }, false);

  part("torso", 1, (add) => {
    const geo = new THREE.LatheGeometry(TORSO, 56);
    const m = add(new THREE.Mesh(geo, holo({ opacity: 0.85, fadeLow: 0.5 })));
    m.scale.z = TORSO_Z;
    const wire = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ color: CHAMPAGNE, wireframe: true, transparent: true, opacity: 0.018,
      blending: THREE.AdditiveBlending, depthWrite: false }));
    wire.scale.z = TORSO_Z; add(wire, false);
    for (const s of [-1, 1]) {  // upper arms, so the silhouette reads as a figure rather than a block
      const armGeo = new THREE.LatheGeometry([V2(0.001, 0.0), V2(0.2, 0.05), V2(0.24, 0.5), V2(0.29, 1.0), V2(0.34, 1.3), V2(0.33, 1.5),
                                               V2(0.24, 1.66), V2(0.001, 1.7)], 28);
      const arm = add(new THREE.Mesh(armGeo, holo({ opacity: 0.75, fadeLow: 0.55 })));
      arm.position.set(1.6 * s, 0.95, -0.05); arm.rotation.z = 0.12 * s; arm.scale.z = 0.85;
      const aw = new THREE.Mesh(arm.geometry, new THREE.MeshBasicMaterial({ color: CHAMPAGNE, wireframe: true, transparent: true,
        opacity: 0.015, blending: THREE.AdditiveBlending, depthWrite: false }));
      aw.position.copy(arm.position); aw.rotation.copy(arm.rotation); aw.scale.copy(arm.scale); add(aw, false);
    }
    const neck = add(new THREE.Mesh(new THREE.CylinderGeometry(0.27, 0.34, 0.42, 24, 1, true), holo({ opacity: 0.85 })));
    neck.position.y = 2.98;

  });

  // ---- helmet: sentinel faceplate with knight elements (original design; every piece is its own part) ----------
  // Faceted (flat-shaded) geometry reads as forged armour plates rather than a smooth egg.
  const facet = (g) => { const f = g.index ? g.toNonIndexed() : g; f.computeVertexNormals(); return f; };
  const plate = (shape, depth = 0.04, bevel = 0.012) => facet(new THREE.ExtrudeGeometry(shape, { depth, bevelEnabled: true,
    bevelThickness: bevel, bevelSize: bevel, bevelSegments: 1 }));
  const shapeOf = (pts) => { const sh = new THREE.Shape(); sh.moveTo(pts[0][0], pts[0][1]); for (const [x, y] of pts.slice(1)) sh.lineTo(x, y); sh.closePath(); return sh; };
  const edged = (add, geo, mesh, o = 0.34) => { const l = add(lines(geo, o, 24), false); l.position.copy(mesh.position); l.rotation.copy(mesh.rotation); l.scale.copy(mesh.scale); return l; };

  part("helmet", 1, (add) => {
    const prof = [V2(0.001, 3.22), V2(0.42, 3.26), V2(0.6, 3.42), V2(0.7, 3.7), V2(0.72, 3.98), V2(0.69, 4.28), V2(0.58, 4.56), V2(0.38, 4.78), V2(0.001, 4.88)];
    const geo = facet(new THREE.LatheGeometry(prof, 14));
    const shell = add(new THREE.Mesh(geo, holo({ opacity: 0.8, rim: 1.2 })));
    shell.scale.set(0.92, 1, 0.98);
    edged(add, geo, shell, 0.16);
    // knight crest: a blade ridge from the brow over the crown to the back
    const crestGeo = new THREE.TorusGeometry(0.8, 0.045, 4, 56, 2.7).rotateZ(0.25);
    const crest = add(new THREE.Mesh(crestGeo, holo({ opacity: 1, rim: 1.7, core: 0.25 })));
    crest.rotation.y = Math.PI / 2; crest.position.y = 3.98; crest.scale.set(1, 1, 0.45);
    // side guards (knight cheek guards) with a small sensor disc
    for (const s of [-1, 1]) {
      const g = plate(shapeOf([[-0.22, 0.12], [0.1, 0.16], [0.16, -0.08], [0.02, -0.34], [-0.2, -0.26]]), 0.035);
      const m = add(new THREE.Mesh(g, holo({ opacity: 1, rim: 1.5, core: 0.08 })));
      m.position.set(0.64 * s, 3.66, -0.08); m.rotation.set(0, (Math.PI / 2 + 0.35) * s, 0.15 * s);
      edged(add, g, m);
      const disc = add(new THREE.Mesh(new THREE.CylinderGeometry(0.07, 0.07, 0.05, 20), holo({ opacity: 1, rim: 1.8, core: 0.5 })), false);
      disc.rotation.z = Math.PI / 2; disc.position.set(0.69 * s, 3.9, -0.12);
    }
  });

  part("face", 1, (add) => {
    // angled V-brow: shades the eyes and gives the calm, powerful expression
    const browGeo = plate(shapeOf([[-0.52, 0.1], [0, 0.0], [0.52, 0.1], [0.5, 0.16], [0, 0.07], [-0.5, 0.16]]), 0.06);
    const brow = add(new THREE.Mesh(browGeo, holo({ opacity: 1, rim: 1.8, core: 0.14 })));
    brow.position.set(0, 4.0, 0.6); brow.rotation.x = -0.2;
    edged(add, browGeo, brow, 0.45);
    // knight visor bar / nose ridge down the centre
    const keelGeo = plate(shapeOf([[-0.05, 0.0], [0.05, 0.0], [0.045, -0.3], [0, -0.38], [-0.045, -0.3]]), 0.05);
    const keel = add(new THREE.Mesh(keelGeo, holo({ opacity: 1, rim: 1.6, core: 0.1 })));
    keel.position.set(0, 3.84, 0.7); keel.rotation.x = -0.12;
    edged(add, keelGeo, keel, 0.4);
    // cheek plates wrap around the face; layered jaw plates and breathing vents below
    for (const s of [-1, 1]) {
      const cg = plate(shapeOf([[0.07, 0.0], [0.4, 0.06], [0.38, -0.16], [0.18, -0.42], [0.06, -0.38]]), 0.04);
      const c = add(new THREE.Mesh(cg, holo({ opacity: 1, rim: 1.5, core: 0.07 })));
      c.position.set(0, 3.8, 0.56); c.scale.x = s; c.rotation.set(-0.08, 0.55 * s, 0);
      edged(add, cg, c);
      for (let i = 0; i < 3; i++) {
        const v = add(new THREE.Mesh(new THREE.BoxGeometry(0.13, 0.016, 0.02), holo({ opacity: 1, rim: 1.2, core: 0.55 })), false);
        v.position.set(0.2 * s, 3.56 - i * 0.05, 0.64); v.rotation.y = 0.5 * s;
      }
    }
    const jawGeo = plate(shapeOf([[-0.2, 0], [0.2, 0], [0.13, -0.17], [-0.13, -0.17]]), 0.05);
    const jaw = add(new THREE.Mesh(jawGeo, holo({ opacity: 1, rim: 1.5, core: 0.1 })));
    jaw.position.set(0, 3.42, 0.6); jaw.rotation.x = 0.25;
    edged(add, jawGeo, jaw, 0.4);
  });

  // two glowing eye slits, angled slightly upward toward the outside; brighter while JARVIS speaks or writes
  const eyeMats = [], eyeGlows = [];
  part("eyes", 1, (add) => {
    for (const s of [-1, 1]) {
      const g = new THREE.ExtrudeGeometry(shapeOf([[0.06, -0.008], [0.34, 0.045], [0.33, 0.0], [0.07, -0.05]]), { depth: 0.02, bevelEnabled: false });
      const m = holo({ opacity: 2.2, rim: 3.0, core: 2.0 });
      eyeMats.push(m);
      const e = add(new THREE.Mesh(g, m), false);
      e.position.set(0, 3.925, 0.71); e.scale.x = s; e.rotation.y = 0.3 * s;
      const glow = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTexture(), color: WHITE, transparent: true, opacity: 0.5,
        blending: THREE.AdditiveBlending, depthWrite: false }));
      glow.position.set(0.21 * s, 3.935, 0.86); glow.scale.set(0.75, 0.3, 1);
      eyeGlows.push(glow); add(glow, false);
    }
  }, false);

  // ---- body armour: all of it from the start; evolution adds light and energy only ---------------------------
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
    const keel = add(new THREE.Mesh(new THREE.BoxGeometry(0.045, 0.42, 0.04), holo({ opacity: 1, rim: 1.6, core: 0.3, fadeLow: 0.5 })));
    keel.position.copy(onChest(0, 1.12, 0.1));
    for (const s of [-1, 1]) {   // pectoral plates
      const g = plate(shapeOf([[0, 0], [0.6, 0.06], [0.68, -0.22], [0.56, -0.5], [0.1, -0.56], [0.02, -0.3]]), 0.045, 0.015);
      const m = add(new THREE.Mesh(g, holo({ opacity: 0.95, rim: 1.5, core: 0.08, fadeLow: 0.5 })));
      m.position.copy(onChest(0.3 * s, 2.55, 0.1)); m.scale.set(0.82 * s, 0.82, 1); m.rotation.set(-0.12, 0.32 * s, 0.1 * s);
      edged(add, g, m, 0.36);
    }
    for (let r = 0; r < 3; r++) for (const s of [-1, 1]) {   // abdominal plates
      const g = facet(new THREE.BoxGeometry(0.3, 0.16, 0.05));
      const m = add(new THREE.Mesh(g, holo({ opacity: 0.9, rim: 1.4, core: 0.08, fadeLow: 0.5 })));
      m.position.copy(onChest(0.18 * s, 1.45 - r * 0.21, 0.06)); m.rotation.y = 0.12 * s;
      edged(add, g, m, 0.3);
    }
  });
  part("pauldrons", 1, (add) => {
    for (const s of [-1, 1]) for (let i = 0; i < 3; i++) {   // knight-style layered shoulder lames
      const r = 0.66 - i * 0.08;
      const g = facet(new THREE.SphereGeometry(r, 14, 6, 0, Math.PI * 2, 0, Math.PI / 2));
      const m = add(new THREE.Mesh(g, holo({ opacity: 1 - i * 0.1, rim: 1.6, core: 0.07 })));
      m.position.set((1.3 + i * 0.07) * s, 2.56 - i * 0.16, 0); m.scale.set(1, 0.5, 0.85); m.rotation.z = -0.52 * s;
      edged(add, g, m, 0.3 - i * 0.05);
    }
  });
  part("bracers", 1, (add) => {
    for (const s of [-1, 1]) {
      const g = facet(new THREE.CylinderGeometry(0.33, 0.3, 0.66, 12, 1, true, -1.6, 3.2));
      const m = add(new THREE.Mesh(g, holo({ opacity: 0.95, rim: 1.5, core: 0.07, fadeLow: 0.55 })));
      m.position.set(1.6 * s, 1.85, -0.03); m.rotation.z = 0.12 * s;
      edged(add, g, m, 0.28);
      const couter = add(new THREE.Mesh(facet(new THREE.SphereGeometry(0.2, 10, 6)), holo({ opacity: 0.9, rim: 1.5, fadeLow: 0.55 })));
      couter.position.set(1.66 * s, 1.08, 0.12); couter.scale.set(1, 0.8, 0.6);
    }
  });

  // ---- evolution: light and energy only ---------------------------------------------------------------------
  part("circuits", 2, (add) => {
    const paths = [
      [[0, 2.0], [0.2, 2.25], [0.55, 2.38], [0.95, 2.4]], [[0, 2.0], [-0.2, 2.25], [-0.55, 2.38], [-0.95, 2.4]],
      [[0.25, 1.9], [0.6, 1.8], [0.95, 1.55], [1.15, 1.3]], [[-0.25, 1.9], [-0.6, 1.8], [-0.95, 1.55], [-1.15, 1.3]],
      [[0.12, 1.72], [0.3, 1.35], [0.62, 1.1]], [[-0.12, 1.72], [-0.3, 1.35], [-0.62, 1.1]],
    ];
    for (const pts of paths) {
      const curve = new THREE.CatmullRomCurve3(pts.map(([x, y]) => onChest(x, y, 0.03)));
      add(new THREE.Mesh(new THREE.TubeGeometry(curve, 40, 0.012, 5, false), holo({ opacity: 0.9, rim: 1, flow: true, core: 0.3, fadeLow: 0.5 })), false);
    }
  });
  part("crestglow", 3, (add) => {   // energy running along the crest
    const g = new THREE.TorusGeometry(0.815, 0.012, 4, 80, 2.7).rotateZ(0.25);
    const m = add(new THREE.Mesh(g, holo({ opacity: 1, rim: 1.8, flow: true, core: 0.6 })), false);
    m.rotation.y = Math.PI / 2; m.position.y = 3.98;
  }, false);
  part("halo", 4, (add) => {
    for (const [r, o] of [[1.22, 0.9], [1.36, 0.45]]) {
      const ring = add(new THREE.Mesh(new THREE.TorusGeometry(r, 0.01, 6, 160), holo({ opacity: o, rim: 1.5, flow: true, core: 0.5 })), false);
      ring.position.set(0, 3.95, -0.45); ring.userData.spin = r > 1.3 ? -0.5 : 0.5;
    }
  }, false);
  part("crown", 4, (add) => {   // a crown of light above the crest
    for (const s of [-1, 1]) {
      const g = new THREE.TorusGeometry(0.42, 0.008, 4, 40, 1.2).rotateZ(Math.PI / 2 - 0.6);
      const m = add(new THREE.Mesh(g, holo({ opacity: 1, rim: 1.8, flow: true, core: 0.7 })), false);
      m.position.set(0.18 * s, 4.75, -0.1); m.rotation.set(0.2, 0, -0.35 * s);
    }
  }, false);

  // orbit rings around the figure (always present)
  const orbits = new THREE.Group();
  for (const [r, y, tilt, o] of [[2.05, 2.0, 0.18, 0.75], [1.78, 2.0, -0.1, 0.5], [1.12, 3.95, 0.12, 0.6]]) {
    const ring = new THREE.Mesh(new THREE.TorusGeometry(r, 0.008, 6, 160), holo({ opacity: o, rim: 1.5, flow: true, core: 0.55 }));
    ring.rotation.x = Math.PI / 2 - tilt; ring.position.y = y; ring.userData.spin = tilt > 0 ? 1 : -1;
    orbits.add(ring);
  }
  figure.add(orbits);

  // projector beam and rising dust
  const beamMat = new THREE.ShaderMaterial({ vertexShader: BEAM_VERT, fragmentShader: BEAM_FRAG, transparent: true, depthWrite: false,
    side: THREE.DoubleSide, blending: THREE.AdditiveBlending, uniforms: { uTint: { value: CHAMPAGNE.clone() }, uTime: { value: 0 }, uBeam: { value: 0.7 } } });
  const beam = new THREE.Mesh(new THREE.CylinderGeometry(0.72, 1.28, 4.6, 64, 1, true), beamMat);
  beam.position.y = 2.33; beam.scale.setScalar(SCALE); beam.position.y = BASE_Y + 2.33 * SCALE;
  scene.add(beam);
  const N = phone ? 70 : 160, seeds = new Float32Array(N), pos = new Float32Array(N * 3);
  for (let i = 0; i < N; i++) seeds[i] = Math.random();
  const dustGeo = new THREE.BufferGeometry();
  dustGeo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  dustGeo.setAttribute("aSeed", new THREE.BufferAttribute(seeds, 1));
  const dustMat = new THREE.ShaderMaterial({ vertexShader: DUST_VERT, fragmentShader: DUST_FRAG, transparent: true, depthWrite: false,
    blending: THREE.AdditiveBlending, uniforms: { uTime: { value: 0 }, uSpeed: { value: 1 }, uSize: { value: 3.2 }, uTint: { value: WHITE.clone() } } });
  const dust = new THREE.Points(dustGeo, dustMat);
  dust.frustumCulled = false; dust.scale.setScalar(SCALE); dust.position.y = BASE_Y;
  scene.add(dust);

  // ---- state ---------------------------------------------------------------------------------------------------
  const cur = { ...LOOKS.idle, tint: new THREE.Color(LOOKS.idle.tint) };
  let target = LOOKS.idle, state = "idle", tier = 1, mode = opts.mode || "full";
  const targetTint = new THREE.Color(LOOKS.idle.tint);
  let t = 0, last = 0, raf = 0, visible = true, flash = 0, settling = 2.5;

  function setState(s) {
    if (!LOOKS[s] || s === state) return;
    state = s; target = LOOKS[s]; targetTint.set(target.tint);
    if (s === "completed") flash = 1;
    settling = 2.5; kick();
  }
  function setTier(n) {
    n = Math.max(1, Math.min(4, Number(n) || 1));
    if (n === tier) return;
    const up = tier !== 0 && n > tier;  // the first tier comes with the initial materialisation
    tier = n; applyTier(up);
  }
  function applyTier(animate) {
    for (const p of Object.values(parts)) {
      const show = tier >= p.tier;
      if (show && !p.group.visible && animate) p.reveal = -1.5;
      p.group.visible = p.refl.visible = show;
    }
    settling = 3; kick();
  }
  function setMode(m) {
    mode = m;
    if (mode !== "full") for (const p of Object.values(parts)) p.reveal = 10;  // no materialisation without motion
    settling = 1; kick();
  }

  // materialise from the projector upward on first appearance
  for (const p of Object.values(parts)) { p.reveal = mode === "full" ? -1.2 : 10; p.group.visible = p.refl.visible = tier >= p.tier; }

  function frame(now) {
    raf = 0;
    if (!visible || document.hidden) return;
    const cap = phone ? 1000 / 24 : 1000 / 30;
    if (mode === "full" && now - last < cap) { raf = requestAnimationFrame(frame); return; }
    const dt = Math.min(0.1, last ? (now - last) / 1000 : 0.033);
    last = now;
    const moving = mode === "full";
    if (moving) t += dt;
    const k = mode === "full" ? 1 - Math.exp(-dt * 4) : 1;
    for (const key of ["rim", "scan", "flow", "ring", "beam", "light", "flicker", "eyes"]) cur[key] += ((target[key] ?? 0) - cur[key]) * k;
    cur.tint.lerp(targetTint, k);
    flash = Math.max(0, flash - dt * 0.9);
    const pulse = target.pulse && moving ? 0.82 + 0.18 * Math.sin(t * target.pulse * Math.PI) : 1;
    const flicker = moving ? cur.flicker : 0;
    let revealing = false;
    for (const p of Object.values(parts)) {
      if (p.reveal < 10) { p.reveal += dt * 3.2; revealing = true; if (p.reveal >= 6) p.reveal = 10; }
      for (const m of p.mats) m.uniforms.uReveal.value = p.reveal;
    }
    for (const m of mats) {
      const u = m.uniforms;
      u.uTime.value = t; u.uTint.value.copy(cur.tint); u.uScan.value = cur.scan; u.uFlow.value = cur.flow; u.uFlicker.value = flicker;
      u.uRim.value = m.userData.base.rim * cur.rim * pulse * (1 + flash * 0.8);
      u.uOpacity.value = m.userData.base.opacity * (1 + flash * 0.5);
    }
    const seams = [0.7, 1.0, 1.2, 1.35][tier - 1] || 1;  // seams glow brighter as verified milestones accumulate
    for (const m of lineMats) { m.color.copy(cur.tint); m.opacity = m.userData.lineBase * pulse * seams; }
    const eyeLevel = cur.eyes * (1 + flash) * (1 - flicker * 0.5);
    for (const m of eyeMats) { m.uniforms.uOpacity.value = m.userData.base.opacity * eyeLevel; m.uniforms.uTint.value.copy(cur.tint).lerp(WHITE, 0.7); }
    for (const g of eyeGlows) { g.material.opacity = Math.min(1, 0.85 * eyeLevel); g.material.color.copy(cur.tint).lerp(WHITE, 0.75); }
    beamMat.uniforms.uTime.value = t; beamMat.uniforms.uBeam.value = cur.beam * (1 + flash); beamMat.uniforms.uTint.value.copy(cur.tint);
    dustMat.uniforms.uTime.value = t; dustMat.uniforms.uSpeed.value = 1 + flash * 4 + cur.flow * 0.3;
    dust.visible = moving;
    if (moving) {
      figure.rotation.y = Math.sin(t * 0.18) * 0.07;  // calm: a slow, small turn mirror.rotation.y = figure.rotation.y;
      figure.position.y = BASE_Y + Math.sin(t * 0.9) * 0.025;
      orbits.children.forEach((r) => { r.rotation.z += dt * cur.ring * r.userData.spin; });
      for (const p of [parts.pad, parts.halo]) p.group.children.forEach((r) => { if (r.userData.spin) r.rotation.z += dt * 0.2 * r.userData.spin; });
      const s = state === "listening" ? 0.96 + 0.04 * Math.sin(t * 5) : 1;
      orbits.scale.set(s, 1, s);
    }
    renderer.render(scene, camera);
    settling -= dt;
    if (moving || revealing || settling > 0 && mode === "full") raf = requestAnimationFrame(frame);
  }
  function kick() { if (!raf && visible && !document.hidden) raf = requestAnimationFrame(frame); }

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
    setState, setTier, setMode, onLost: null,
    get animating() { return raf !== 0; }, get lost() { return lost; },
    dispose() { cancelAnimationFrame(raf); ro.disconnect(); io.disconnect(); document.removeEventListener("visibilitychange", onVis);
      renderer.dispose(); canvas.remove(); },
  };
  return api;
}
