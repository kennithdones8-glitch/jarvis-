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
import { VERT, FRAG, PLATE_VERT, PLATE_FRAG, SHIELD_FRAG, QUAD_VERT, BRIGHT_FRAG, BLUR_FRAG, COMPOSITE_FRAG, BEAM_VERT, BEAM_FRAG, DUST_VERT, DOT_FRAG, NET_VERT, NET_FRAG, NODE_VERT, DATA_VERT, DASH_FRAG } from "/static/avatar3d-shaders.js";
import { HAND_VERT, HAND_PLATE_VERT } from "/static/avatar3d-shaders.js";
import { sdHuman, meshFigure, meshHands, mergeGeos, rng, glowTexture } from "/static/avatar3d-geometry.js";
import { buildReactor } from "/static/avatar3d-reactor.js";
import { buildNeural } from "/static/avatar3d-neural.js";
import { buildReconstruction } from "/static/avatar3d-particles.js";
import { buildEnvironment } from "/static/avatar3d-environment.js";
import { createDirector } from "/static/avatar3d-projections.js";
import { createRig, VIEWS, TARGETS } from "/static/avatar3d-camera.js";
export { sdHuman, meshFigure };

const CHAMPAGNE = new THREE.Color("#f3e3bd"), WHITE = new THREE.Color("#fff8ec"), AMBER = new THREE.Color("#f2a33a");
const RED = new THREE.Color("#ff5a52"), DIM = new THREE.Color("#9d8e76");

// Per state. tint/eyes/rim: colour and glow · scan: scan-line speed · flow: circuit energy (negative = toward the
// head) · ring: orbit speed · beam: projector · reactor: chest energy · neural: lattice activity · data: research
// streams · sweep: vertical scan ring · discharge: reactor arcs · beat: seconds between energy pulses (0 = none) ·
// head: how the head moves · flicker: diagnostic flicker. Only real signals select a state (see app.js).
const LOOKS = {
  unknown:       { tint: "#b9a27a", rpat: "calm", eyes: 0.35, rim: 0.8, scan: 0.6, flow: 0.1, ring: 0.05, beam: 0.4, reactor: 0.35, neural: 0.05, data: 0, sweep: 0, discharge: 0, beat: 0, head: "still", flicker: 0 },
  idle:          { tint: "#f2c46d", rpat: "calm", eyes: 0.75, rim: 1.0, scan: 1.0, flow: 0.3, ring: 0.12, beam: 0.65, reactor: 0.55, neural: 0.12, data: 0, sweep: 0, discharge: 0, beat: 0, head: "aware", flicker: 0 },
  listening:     { tint: "#ffd98f", rpat: "calm", eyes: 1.3, rim: 1.25, scan: 1.2, flow: 0.5, ring: 0.3, beam: 0.85, reactor: 0.75, neural: 0.25, data: 0, sweep: 0, discharge: 0, beat: 0, head: "attend", flicker: 0 },
  understanding: { tint: "#f5c867", rpat: "spin", eyes: 1.0, rim: 1.2, scan: 2.6, flow: -0.8, ring: 0.45, beam: 0.85, reactor: 0.8, neural: 0.7, data: 0, sweep: 0.6, discharge: 0, beat: 0, head: "think", flicker: 0 },
  reasoning:     { tint: "#f0bd5a", rpat: "spin", eyes: 1.1, rim: 1.3, scan: 1.6, flow: -1.3, ring: 0.7, beam: 0.9, reactor: 1.0, neural: 1.0, data: 0, sweep: 0.5, discharge: 0.25, beat: 0, head: "think", flicker: 0 },
  planning:      { tint: "#efc062", rpat: "spin", eyes: 1.0, rim: 1.25, scan: 1.8, flow: -1.0, ring: 0.9, beam: 0.9, reactor: 0.95, neural: 0.9, data: 0, sweep: 0.4, discharge: 0.2, beat: 0, head: "think", flicker: 0 },
  researching:   { tint: "#f7d07c", rpat: "scan", eyes: 1.05, rim: 1.25, scan: 2.4, flow: 0.8, ring: 0.8, beam: 0.95, reactor: 0.9, neural: 0.6, data: 1.0, sweep: 0.9, discharge: 0, beat: 0, head: "scan", flicker: 0 },
  writing:       { tint: "#fbd88e", rpat: "beat", eyes: 1.45, rim: 1.3, scan: 1.4, flow: 1.4, ring: 0.55, beam: 1.0, reactor: 1.0, neural: 0.5, data: 0, sweep: 0, discharge: 0, beat: 0, head: "aware", flicker: 0 },
  speaking:      { tint: "#ffe0a0", rpat: "beat", eyes: 1.5, rim: 1.3, scan: 1.2, flow: 1.0, ring: 0.4, beam: 0.95, reactor: 0.9, neural: 0.35, data: 0, sweep: 0, discharge: 0, beat: 0, head: "speak", flicker: 0 },
  coding:        { tint: "#eab350", rpat: "surge", eyes: 1.35, rim: 1.35, scan: 1.8, flow: 2.4, ring: 0.7, beam: 1.0, reactor: 1.1, neural: 0.7, data: 0, sweep: 0.3, discharge: 0.2, beat: 0, head: "think", flicker: 0 },
  verifying:     { tint: "#fde2a8", rpat: "scan", eyes: 1.1, rim: 1.2, scan: 3.6, flow: 0.9, ring: 0.5, beam: 0.95, reactor: 0.9, neural: 0.5, data: 0, sweep: 1.0, discharge: 0, beat: 0, head: "scan", flicker: 0 },
  executing:     { tint: "#f2a33a", rpat: "surge", eyes: 1.2, rim: 1.35, scan: 1.8, flow: 1.8, ring: 1.2, beam: 1.05, reactor: 1.35, neural: 0.6, data: 0, sweep: 0.3, discharge: 0.55, beat: 1.8, head: "aware", flicker: 0 },
  approval:      { tint: "#ffc25a", rpat: "beat", eyes: 1.05, rim: 1.3, scan: 1.0, flow: 0.4, ring: 0.2, beam: 0.85, reactor: 0.85, neural: 0.2, data: 0, sweep: 0, discharge: 0, beat: 2.8, head: "attend", flicker: 0 },
  warning:       { tint: "#ffb347", rpat: "scan", eyes: 0.9, rim: 1.15, scan: 1.8, flow: 0.3, ring: 0.15, beam: 0.75, reactor: 0.7, neural: 0.15, data: 0, sweep: 0.55, discharge: 0, beat: 0, head: "aware", flicker: 0 },
  completed:     { tint: "#fff0c8", rpat: "surge", eyes: 1.8, rim: 1.7, scan: 1.0, flow: 1.0, ring: 0.6, beam: 1.2, reactor: 1.6, neural: 0.6, data: 0, sweep: 0, discharge: 0, beat: 0, head: "aware", flicker: 0 },
  error:         { tint: "#ff4b4b", rpat: "stutter", eyes: 1.1, rim: 1.1, scan: 0.8, flow: 0.0, ring: 0.0, beam: 0.45, reactor: 0.5, neural: 0.05, data: 0, sweep: 0.7, discharge: 0, beat: 0, head: "still", flicker: 0.45 },
  recovery:      { tint: "#f7d48c", rpat: "calm", eyes: 0.8, rim: 1.0, scan: 1.5, flow: 0.5, ring: 0.25, beam: 0.7, reactor: 0.6, neural: 0.3, data: 0, sweep: 0.5, discharge: 0, beat: 0, head: "aware", flicker: 0.08 },
  learning:      { tint: "#ffe6a8", rpat: "beat", eyes: 1.2, rim: 1.2, scan: 1.4, flow: -0.9, ring: 0.4, beam: 0.85, reactor: 0.85, neural: 0.95, data: 0, sweep: 0.3, discharge: 0, beat: 1.4, head: "think", flicker: 0 },
  experimenting: { tint: "#f7c96e", rpat: "spin", eyes: 1.15, rim: 1.25, scan: 2.2, flow: 0.9, ring: 0.8, beam: 0.9, reactor: 0.95, neural: 0.7, data: 0.4, sweep: 0.6, discharge: 0.2, beat: 0, head: "scan", flicker: 0 },
  analyzing:     { tint: "#fde2a8", rpat: "scan", eyes: 1.15, rim: 1.2, scan: 3.0, flow: -0.6, ring: 0.5, beam: 0.9, reactor: 0.85, neural: 0.8, data: 0.3, sweep: 0.9, discharge: 0, beat: 0, head: "scan", flicker: 0 },
  disagreeing:   { tint: "#ffa640", rpat: "still", eyes: 1.0, rim: 1.2, scan: 0.8, flow: 0.0, ring: 0.1, beam: 0.8, reactor: 0.7, neural: 0.15, data: 0, sweep: 0, discharge: 0, beat: 0, head: "shake", flicker: 0 },
  halted:        { tint: "#a8977a", rpat: "still", eyes: 0.4, rim: 0.85, scan: 0.4, flow: 0.0, ring: 0.0, beam: 0.35, reactor: 0.3, neural: 0.0, data: 0, sweep: 0, discharge: 0, beat: 0, head: "still", flicker: 0 },
};
const NUMERIC = ["eyes", "rim", "scan", "flow", "ring", "beam", "reactor", "neural", "data", "sweep", "discharge", "flicker"];

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

  // post-processing targets (half-float where supported, so glow can exceed 1 before the bloom)
  const post = (() => {
    try {
      const hf = renderer.capabilities.isWebGL2 && renderer.extensions.has("EXT_color_buffer_float");
      const opt = { type: hf ? THREE.HalfFloatType : THREE.UnsignedByteType };
      const rt = () => new THREE.WebGLRenderTarget(1, 1, opt);
      const t = { scene: new THREE.WebGLRenderTarget(1, 1, { ...opt, depthBuffer: true }), a1: rt(), b1: rt(), a2: rt(), b2: rt() };
      const quadScene = new THREE.Scene(), quadCam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
      const quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2)); quadScene.add(quad); quad.frustumCulled = false;
      const mat = (frag, uniforms) => new THREE.ShaderMaterial({ vertexShader: QUAD_VERT, fragmentShader: frag, uniforms, depthTest: false, depthWrite: false });
      const bright = mat(BRIGHT_FRAG, { tSrc: { value: null }, uThr: { value: 0.6 } });
      const blur = mat(BLUR_FRAG, { tSrc: { value: null }, uDir: { value: new THREE.Vector2() } });
      const copy = mat(BLUR_FRAG, { tSrc: { value: null }, uDir: { value: new THREE.Vector2(0, 0) } });
      const comp = mat(COMPOSITE_FRAG, { tScene: { value: null }, tB1: { value: null }, tB2: { value: null }, uB1: { value: 1.1 }, uB2: { value: 0.9 },
                                          uCA: { value: 0.004 }, uTime: { value: 0 }, uRes: { value: new THREE.Vector2(1, 1) } });
      const pass = (m, target) => { quad.material = m; renderer.setRenderTarget(target); renderer.render(quadScene, quadCam); };
      const blurInto = (src, tmp, w, h) => {
        blur.uniforms.tSrc.value = src.texture; blur.uniforms.uDir.value.set(1 / w, 0); pass(blur, tmp);
        blur.uniforms.tSrc.value = tmp.texture; blur.uniforms.uDir.value.set(0, 1 / h); pass(blur, src);
      };
      return {
        size(w, h) {
          t.scene.setSize(w, h);
          const w1 = Math.max(1, w >> 1), h1 = Math.max(1, h >> 1), w2 = Math.max(1, w >> 2), h2 = Math.max(1, h >> 2);
          t.a1.setSize(w1, h1); t.b1.setSize(w1, h1); t.a2.setSize(w2, h2); t.b2.setSize(w2, h2);
          this.dims = [w1, h1, w2, h2]; comp.uniforms.uRes.value.set(w, h);
        },
        begin() { renderer.setRenderTarget(t.scene); renderer.clear(); },
        dispose() { for (const x of Object.values(t)) x.dispose(); for (const m of [bright, blur, copy, comp]) m.dispose(); quad.geometry.dispose(); },
        end(time, gain) {
          const [w1, h1, w2, h2] = this.dims;
          bright.uniforms.tSrc.value = t.scene.texture; pass(bright, t.a1);
          blurInto(t.a1, t.b1, w1, h1);
          copy.uniforms.tSrc.value = t.a1.texture; pass(copy, t.a2);
          blurInto(t.a2, t.b2, w2, h2); blurInto(t.a2, t.b2, w2, h2);
          comp.uniforms.tScene.value = t.scene.texture; comp.uniforms.tB1.value = t.a1.texture; comp.uniforms.tB2.value = t.a2.texture;
          comp.uniforms.uB1.value = 0.75 * gain; comp.uniforms.uB2.value = 0.6 * gain; comp.uniforms.uTime.value = time;
          renderer.setRenderTarget(null); renderer.clear(); pass(comp, null);
        },
      };
    } catch (e) { return null; }   // no post-processing: draw directly (still correct, just without the glow)
  })();

  const scene = new THREE.Scene();
  // The figure is self-lit light (shader-only), so the scene needs no lights or environment map.
  const camera = new THREE.PerspectiveCamera(28, 20 / 27, 0.1, 60);
  // the camera rig: the resting view, orbit / zoom / pan while inspecting, and the wider view for projections
  const rig = createRig(camera, { rest: opts.options && opts.options.view });
  const director = createDirector({ scene, kick: () => kick() });   // projections share this scene and loop

  // ---- shared uniforms: one update per frame drives every hologram material ------------------------------------
  const U = { uHead: { value: new THREE.Matrix3() }, uArmR: { value: new THREE.Matrix3() }, uArmL: { value: new THREE.Matrix3() },
              uForeR: { value: new THREE.Matrix3() }, uForeL: { value: new THREE.Matrix3() }, uAccent: { value: new THREE.Color("#fff1cf") },
              uTime: { value: 0 }, uTint: { value: CHAMPAGNE.clone() }, uRimK: { value: 1 }, uGain: { value: 1 },
              uScan: { value: 1 }, uFlow: { value: 0.3 }, uFlicker: { value: 0 }, uReflect: { value: 0 } };
  const EYE = { value: 1 }, REACTOR = { value: 1 };
  const FACE = { uEyeOpen: { value: 1 }, uEyeLook: { value: 0 }, uEyeScan: { value: 0 }, uSpeech: { value: 0 }, uEyeHot: { value: 1 }, uThink: { value: 0 } };   // eyes and speech light
  const lineMats = [];
  const parts = {};
  let building = null;   // the part whose meshes are being built (for its reveal uniform and visibility)

  function holo(o = {}) {
    const m = new THREE.ShaderMaterial({
      vertexShader: o.vert || VERT, fragmentShader: FRAG, transparent: true, depthWrite: false, side: THREE.DoubleSide, wireframe: !!o.wire,
      blending: THREE.AdditiveBlending,
      uniforms: { ...U, uTint0: U.uTint, uHeadOn: { value: o.head ? 1 : 0 }, uOpacity: { value: o.opacity ?? 0.9 }, uRim: { value: o.rim ?? 1 }, uFlowOn: { value: o.flow ? 1 : 0 },
                  uCore: { value: o.core ?? 0.035 }, uFadeLow: { value: o.fadeLow ?? -10 }, uSelf: o.self || { value: 1 },
                  uReveal: building ? building.reveal : { value: 10 },
                  // armour surfaces (low inner glow, no energy flow) get machined panel seams unless told otherwise
                  uPanel: { value: o.panel ?? ((o.core ?? 0.035) < 0.2 && !o.flow && !o.self ? 0.85 : 0) },
                  uPanelScale: { value: o.panelScale ?? 6 }, uContour: { value: o.contour ?? 0 }, uDetail: { value: o.detail ?? 0 }, uCoreE: REACTOR, uEye: EYE, ...FACE,
                  uInflate: { value: o.inflate ?? 0 }, ...(o.extra || {}) },
      extensions: { derivatives: true },
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
  const headPivot = new THREE.Group(); headPivot.position.set(0, 4.3, 0); figure.add(headPivot);   // the neck (matches the shader)
  const head = new THREE.Group(); head.position.y = -4.3; headPivot.add(head);
  const arms = [-1, 1].map((s) => {
    const pivot = new THREE.Group(); pivot.position.set(1.45 * s, 2.55, 0); body.add(pivot);
    const inner = new THREE.Group(); inner.position.set(-1.45 * s, -2.55, 0); pivot.add(inner);
    return { s, pivot, inner };
  });

  // part(name, tier, build): build(add) creates meshes; add(mesh, to = body) puts one where it belongs.
  function part(name, tier, build) {
    const p = { tier, reveal: { value: 10 }, objs: [] };
    parts[name] = p; building = p;
    build((mesh, to = body) => { to.add(mesh); p.objs.push(mesh); return mesh; }, p.reveal);
    building = null;
    return p;
  }
  const edged = (add, geo, mesh, o = 0.34, to = body) => {
    const l = add(lines(geo, o, 24), to); l.position.copy(mesh.position); l.rotation.copy(mesh.rotation); l.scale.copy(mesh.scale); return l;
  };

  // ---- projection platform -----------------------------------------------------------------------------------------
  const spinners = [];
  part("pad", 1, (add) => {
    const disc = add(new THREE.Mesh(new THREE.CylinderGeometry(1.25, 1.35, 0.06, 64, 1, false), holo({ opacity: 0.45, rim: 1.0, core: 0.05, panel: 0.5, panelScale: 3 })), scene);
    disc.position.y = BASE_Y + 0.03 * SCALE; disc.scale.setScalar(SCALE);
    for (const [r, o, dir] of [[1.45, 0.7, 1], [1.05, 0.5, 1], [1.7, 0.35, -1], [1.95, 0.22, 1]]) {
      const ring = add(new THREE.Mesh(new THREE.TorusGeometry(r, 0.012, 6, 128), holo({ opacity: o, rim: 1.4, flow: true, core: 0.4 })), scene);
      ring.rotation.x = Math.PI / 2; ring.position.y = BASE_Y + 0.065 * SCALE; ring.scale.setScalar(SCALE);
      spinners.push({ obj: ring, speed: 0.2 * dir, axis: "z" });
    }
    for (const [r, arc, start, c, o] of [[2.35, 2.4, 3.6, "#f2a33a", 0.85], [2.55, 1.9, 4.9, "#fff1cf", 0.55], [2.2, 1.2, 0.5, "#c98a3c", 0.45]]) {
      const strip = add(new THREE.Mesh(new THREE.TorusGeometry(r, 0.018, 6, 160, arc).rotateZ(start), new THREE.MeshBasicMaterial({
        color: new THREE.Color(c).multiplyScalar(1.6), transparent: true, opacity: o, blending: THREE.AdditiveBlending, depthWrite: false })), scene);
      strip.rotation.x = Math.PI / 2; strip.position.y = BASE_Y + 0.03; strip.scale.setScalar(SCALE);   // curved floor light strips
    }
    const hex = add(lines(new THREE.CylinderGeometry(2.2, 2.2, 0.01, 6), 0.18, 1), scene);   // rotating holographic geometry
    hex.position.y = BASE_Y + 0.05; hex.scale.setScalar(SCALE);
    spinners.push({ obj: hex, speed: -0.05, axis: "y" });
  });

  // ---- body -------------------------------------------------------------------------------------------------------
  // the figure (built once), sparkles shedding from its surface, and energy lines that come with higher stages
  // meshes built in the background worker when available (opts.meshes), otherwise here (same code, same result)
  const pre = opts.meshes || null;
  const unpack = (m) => { const g = new THREE.BufferGeometry();
    for (const [name, a] of Object.entries(m.attrs)) g.setAttribute(name, new THREE.BufferAttribute(a.array, a.itemSize));
    g.setIndex(new THREE.BufferAttribute(m.index, 1)); return g; };
  const figureGeo = mergeGeos(pre ? [unpack(pre.body), unpack(pre.head)]
    : [meshFigure(phone ? 0.04 : 0.03, [-1.12, -0.05, -0.48], [1.12, 4.38, 0.48]),   // body
       meshFigure(phone ? 0.018 : 0.013, [-0.34, 4.3, -0.44], [0.34, 5.15, 0.38])]);   // head and face, finer
  const joints = [], eyeGlows = [], irises = [], sparks = [];
  let figureMat = null, auraMat = null, auraMesh = null;
  part("figure", 1, (add) => {
    figureMat = holo({ opacity: 1.0, rim: 1.6, core: 0.1, panel: 0.35, panelScale: 7, contour: 1, detail: 0.75, head: true });
    add(new THREE.Mesh(figureGeo, figureMat));
    if (!phone) {   // a soft outline glow around the whole figure
      auraMat = holo({ opacity: 0.3, rim: 1.3, core: 0.0, panel: 0, inflate: 0.035, head: true });
      auraMesh = add(new THREE.Mesh(figureGeo, auraMat));
    }
  });
  const shed = (() => {   // sparkles leaving the surface, drifting up and out
    const src = figureGeo.attributes.position.array, nsrc = figureGeo.attributes.normal.array, acc = figureGeo.attributes.aAccent.array;
    const N = phone ? 600 : 1600, P = new Float32Array(N * 3), Nn = new Float32Array(N * 3), seed = new Float32Array(N), ac = new Float32Array(N);
    const r = rng(23);
    for (let i = 0; i < N; i++) { const q = Math.floor(r() * (src.length / 3));
      P.set([src[q * 3], src[q * 3 + 1], src[q * 3 + 2]], i * 3); Nn.set([nsrc[q * 3], nsrc[q * 3 + 1], nsrc[q * 3 + 2]], i * 3);
      seed[i] = r(); ac[i] = acc[q]; }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(P, 3)); g.setAttribute("aN", new THREE.BufferAttribute(Nn, 3));
    g.setAttribute("aSeed", new THREE.BufferAttribute(seed, 1)); g.setAttribute("aAccent", new THREE.BufferAttribute(ac, 1));
    const m = new THREE.ShaderMaterial({ transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
      uniforms: { uTime: U.uTime, uTint: U.uTint, uAccent: U.uAccent, uGain: U.uGain, uRate: { value: 1 } },
      vertexShader: `attribute vec3 aN; attribute float aSeed; attribute float aAccent; uniform float uTime, uRate; varying float vA; varying float vAc;
        void main() { float t = fract(aSeed * 7.0 + uTime * (0.08 + aSeed * 0.12) * uRate);
          vec3 p = position + aN * t * 0.45 + vec3(sin(aSeed * 40.0 + uTime) * 0.05, t * 0.7, 0.0);
          vA = sin(t * 3.14159) * (0.4 + 0.6 * fract(aSeed * 13.0)); vAc = aAccent;
          vec4 mv = modelViewMatrix * vec4(p, 1.0); gl_PointSize = (1.8 + fract(aSeed * 5.0) * 2.8 + step(0.93, fract(aSeed * 17.0)) * 3.0) * (8.0 / -mv.z); gl_Position = projectionMatrix * mv; }`,
      fragmentShader: `uniform vec3 uTint, uAccent; uniform float uGain; varying float vA; varying float vAc;
        void main() { float d = length(gl_PointCoord - 0.5); if (d > 0.5) discard;
          gl_FragColor = vec4(mix(mix(uTint, vec3(1.0, 0.95, 0.85), 0.45), uAccent, vAc) * 1.4, vA * smoothstep(0.5, 0.0, d) * uGain); }` });
    const pts = new THREE.Points(g, m); pts.frustumCulled = false; body.add(pts); return pts;
  })();
  part("meridians", 3, (add) => {   // stage 3: energy lines along the body (centre line, legs)
    for (const pts of [[[0, 4.15, 0.12], [0, 3.62, 0.33], [0, 3.05, 0.28], [0, 2.6, 0.29]],
                       [[0.24, 2.4, 0.2], [0.27, 1.36, 0.17], [0.25, 0.4, 0.07]], [[-0.24, 2.4, 0.2], [-0.27, 1.36, 0.17], [-0.25, 0.4, 0.07]]]) {
      const curve = new THREE.CatmullRomCurve3(pts.map(([x, y, z]) => new THREE.Vector3(x, y, z)));
      add(new THREE.Mesh(new THREE.TubeGeometry(curve, 48, 0.008, 4, false), holo({ opacity: 1, rim: 1, flow: true, core: 0.35 })));
    }
  });

  // Inner energy: a glowing skeleton and nerve network seen through the translucent body, brighter while thinking.
  // Built in the rest pose; the figure's vertex shader bends it with the arms and the head, like the body around it.
  let innerMat = null;
  part("inner", 1, (add) => {
    const V = (x, y, z) => new THREE.Vector3(x, y, z), paths = [];
    paths.push([V(0, 2.55, -0.1), V(0, 3.0, -0.12), V(0, 3.6, -0.1), V(0, 4.08, -0.07), V(0, 4.22, -0.06)]);   // spine (ends at the neck: nothing shows through the face)
    for (const y of [3.95, 3.82, 3.68, 3.54, 3.4]) for (const sg of [-1, 1]) {                                 // ribs
      const w = 0.42 - (3.95 - y) * 0.25;
      paths.push([V(0, y, -0.12), V(sg * w * 0.75, y + 0.01, -0.1), V(sg * w, y - 0.05, 0.02)]);
    }
    for (const sg of [-1, 1]) {
      paths.push([V(0, 4.08, 0.08), V(sg * 0.3, 4.1, 0.05), V(sg * 0.6, 4.0, 0.0)]);                         // clavicle
      paths.push([V(sg * 0.66, 3.92, 0), V(sg * 0.74, 3.45, 0.0), V(sg * 0.8, 3.04, -0.03)]);               // upper arm
      paths.push([V(sg * 0.8, 3.04, -0.03), V(sg * 0.84, 2.66, 0.01), V(sg * 0.88, 2.28, 0.05)]);           // forearm
      paths.push([V(sg * 0.88, 2.28, 0.05), V(sg * 0.9, 2.08, 0.07), V(sg * 0.905, 1.9, 0.075)]);           // hand
      paths.push([V(sg * 0.1, 2.5, -0.02), V(sg * 0.3, 2.62, 0.02), V(sg * 0.34, 2.42, 0.08), V(sg * 0.1, 2.36, 0.12)]);   // pelvis
      paths.push([V(sg * 0.25, 2.42, 0.0), V(sg * 0.26, 1.9, 0.02), V(sg * 0.26, 1.36, 0.03)]);             // thigh
      paths.push([V(sg * 0.26, 1.36, 0.03), V(sg * 0.255, 0.85, -0.01), V(sg * 0.25, 0.32, -0.03)]);        // shin
      paths.push([V(sg * 0.25, 0.32, -0.03), V(sg * 0.26, 0.14, 0.08), V(sg * 0.27, 0.1, 0.22)]);           // foot
      // nerves: thin branches from the spine out to the limbs
      paths.push([V(0, 3.7, -0.1), V(sg * 0.3, 3.85, -0.02), V(sg * 0.62, 3.9, 0.0)]);
      paths.push([V(0, 2.8, -0.12), V(sg * 0.18, 2.62, -0.02), V(sg * 0.25, 2.4, 0.0)]);
    }
    const geos = paths.map((pts) => new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts), 24, 0.009, 5, false));
    innerMat = holo({ opacity: 0.35, rim: 0.8, flow: true, core: 0.55, head: true });
    add(new THREE.Mesh(mergeGeos(geos), innerMat));
  });
  const wisps = (() => {   // energy wisps peeling off the shoulders and the head, slower and larger than the sparkles
    const src = figureGeo.attributes.position.array, nsrc = figureGeo.attributes.normal.array, pick = [];
    for (let q = 0; q < src.length / 3; q++) { const y = src[q * 3 + 1], ax = Math.abs(src[q * 3]);
      if (y > 4.45 || (y > 3.8 && ax > 0.45 && ax < 0.85)) pick.push(q); }
    const N = phone ? 120 : 320, P = new Float32Array(N * 3), Nn = new Float32Array(N * 3), seed = new Float32Array(N), r = rng(77);
    for (let i = 0; i < N; i++) { const q = pick[Math.floor(r() * pick.length)];
      P.set([src[q * 3], src[q * 3 + 1], src[q * 3 + 2]], i * 3); Nn.set([nsrc[q * 3], nsrc[q * 3 + 1], nsrc[q * 3 + 2]], i * 3); seed[i] = r(); }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(P, 3)); g.setAttribute("aN", new THREE.BufferAttribute(Nn, 3));
    g.setAttribute("aSeed", new THREE.BufferAttribute(seed, 1));
    const m = new THREE.ShaderMaterial({ transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
      uniforms: { uTime: U.uTime, uTint: U.uTint, uGain: U.uGain, uRate: { value: 1 }, uAmt: { value: 1 } },
      vertexShader: `attribute vec3 aN; attribute float aSeed; uniform float uTime, uRate; varying float vA;
        void main() { float t = fract(aSeed * 5.0 + uTime * (0.05 + aSeed * 0.05) * uRate);
          vec3 p = position + aN * t * 0.25 + vec3(sin(aSeed * 31.0 + uTime * 0.7) * 0.12 * t, t * 1.1, cos(aSeed * 17.0) * 0.06 * t);
          vA = sin(t * 3.14159) * (0.25 + 0.5 * fract(aSeed * 9.0));
          vec4 mv = modelViewMatrix * vec4(p, 1.0); gl_PointSize = (5.0 + fract(aSeed * 3.0) * 7.0) * (1.0 + t) * (8.0 / -mv.z); gl_Position = projectionMatrix * mv; }`,
      fragmentShader: `uniform vec3 uTint; uniform float uGain, uAmt; varying float vA;
        void main() { float d = length(gl_PointCoord - 0.5); if (d > 0.5) discard;
          gl_FragColor = vec4(mix(uTint, vec3(1.0, 0.95, 0.85), 0.3), vA * pow(smoothstep(0.5, 0.0, d), 2.0) * 0.45 * uGain * uAmt); }` });
    const pts = new THREE.Points(g, m); pts.frustumCulled = false; body.add(pts); return pts;
  })();
  const soleGlows = [-1, 1].map((sg) => {   // the glowing soles light the floor where the figure stands
    const m = new THREE.Mesh(new THREE.PlaneGeometry(0.7, 0.7), new THREE.MeshBasicMaterial({ map: glowTexture(), color: new THREE.Color("#ffb070"),
      transparent: true, opacity: 0.5, blending: THREE.AdditiveBlending, depthWrite: false }));
    m.rotation.x = -Math.PI / 2; m.position.set(sg * 0.26, 0.02, 0.06); body.add(m); return m;
  });

  // ---- central reactor assembly around the SVG core: independent rings, inner rotor, discharge arcs -------------
  const REACTOR_SIZE = 0.36;
  const reactor = new THREE.Group(); reactor.position.set(0, 3.62, 0.36); reactor.scale.setScalar(REACTOR_SIZE); body.add(reactor);   // at the sternum
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
  const reactorX = buildReactor({ holo, part, U, REACTOR, phone }, reactor);   // core, gyros, pathways, supports, swirl, confirmation
  const neuralX = buildNeural({ holo, part, mergeGeos }, body);                  // the neural network inside the body
  // reconstruction: particles that assemble the body (startup, reconstruction) or carry it away (emergency stop),
  // and a scanning ring that rides the build edge
  const rebuild = buildReconstruction({ U, rng }, figureGeo, body, phone ? 800 : 2400);
  const scanRing = new THREE.Mesh(new THREE.TorusGeometry(1.0, 0.012, 6, 128), new THREE.MeshBasicMaterial({
    color: new THREE.Color("#ffd98f").multiplyScalar(1.5), transparent: true, opacity: 0.8, blending: THREE.AdditiveBlending, depthWrite: false }));
  scanRing.rotation.x = Math.PI / 2; scanRing.visible = false; body.add(scanRing);
  let demat = null;   // the emergency-stop dematerialisation in progress (Normal mode only)

  // Alloy armour: key plates cut from the figure's own surface (so they hug the sleek body), lifted slightly off it.
  // m(p) > 0 inside a plate; its value near the border feeds the glowing seam.
  const metals = [];
  // m(x, y, z) > 0 inside a plate (about a distance in body units near the border); lift = how far it stands off
  // the surface (layered plates stand further out). Hand plates use the surface normal and the finger segments.
  const out = (x) => Math.sign(x);
  const PLATES = [
    { name: "chest", order: 0, dir: [0, 0.1, 1], m: (x, y, z) => { const ax = Math.abs(x);
      return Math.min(y - (3.4 + 0.9 * (ax - 0.22) ** 2), (3.83 + 0.4 * ax) - y, 0.47 - 0.6 * (y - 3.68) ** 2 - ax, z - 0.04,
        ax - 0.028, Math.hypot(x, y - 3.62) - 0.21); } },                                      // two pectoral plates around the core
    { name: "abdomen", order: 0.12, dir: [0, -0.2, 1], m: (x, y, z) => { const ax = Math.abs(x);
      return Math.min(y - 2.82, 3.3 - 0.4 * ax - y, 0.2 - 0.25 * (3.06 - y) ** 2 - ax, z - 0.08, Math.abs(y - 3.06) > 0.012 ? 1 : -1); } },
    ...[1, -1].map((sg) => ({ name: "shoulder", order: 0.25, dir: [sg, 0.7, 0], m: (x, y, z) => sg * x <= 0 ? -1
        : Math.min(0.27 - Math.hypot(Math.abs(x) - 0.66, (y - 3.93) * 0.9, z), y - (3.7 + 0.25 * Math.abs(z)), Math.abs(x) - 0.5) })),
    ...[1, -1].map((sg) => ({ name: "pauldron", order: 0.3, lift: 0.055, dir: [sg, 1, 0], m: (x, y, z) => sg * x <= 0 ? -1   // second layer
        : Math.min(0.17 - Math.hypot(Math.abs(x) - 0.69, (y - 3.99) * 0.9, z), y - 3.86) })),
    ...[1, -1].map((sg) => ({ name: "upperarm", order: 0.35, dir: [sg, 0, 0], m: (x, y, z) => sg * x <= 0 ? -1
        : Math.min(y - 3.28, 3.72 - y, Math.abs(x) - 0.765) })),
    ...[1, -1].map((sg) => ({ name: "forearm", order: 0.45, dir: [sg, 0, 0.3], m: (x, y, z) => sg * x <= 0 ? -1
        : Math.min(y - 2.42, 2.94 - y - 0.8 * Math.abs(z), Math.abs(x) - (0.79 + 0.08 * (3.04 - y)) + 0.05) })),
    ...[1, -1].map((sg) => ({ name: "hip", order: 0.5, dir: [sg, -0.3, 0], m: (x, y, z) => sg * x <= 0 ? -1
        : Math.min(y - 2.38, 2.7 - y, Math.abs(x) - 0.3, 0.19 - Math.abs(z)) })),
    ...[1, -1].map((sg) => ({ name: "thigh", order: 0.55, dir: [0, 0, 1], m: (x, y, z) => sg * x <= 0 ? -1
        : Math.min(y - 1.6, 2.22 - y - 0.4 * Math.abs(Math.abs(x) - 0.25), z - 0.08, 0.1 - Math.abs(Math.abs(x) - 0.25)) })),
    ...[1, -1].map((sg) => ({ name: "knee", order: 0.6, lift: 0.045, dir: [0, 0, 1], m: (x, y, z) => sg * x <= 0 ? -1
        : Math.min(0.085 - Math.hypot(Math.abs(x) - 0.26, y - 1.34), z - 0.06) })),
    ...[1, -1].map((sg) => ({ name: "shin", order: 0.65, dir: [0, 0, 1], m: (x, y, z) => { const ax = Math.abs(x);
      return sg * x <= 0 ? -1 : Math.min(y - 0.52, 1.26 - y - 1.3 * Math.abs(ax - 0.255), z - 0.0, (0.1 - 0.04 * (1.2 - y)) - Math.abs(ax - 0.255)); } })),
    { name: "helmet", order: 0.85, lift: 0.022, dir: [0, 0.4, -1], m: (x, y, z) => Math.min(y - 4.45, Math.max(0.075 - z, y - 4.93)) },   // shell: crown, sides, back; the faceplate stays light
    { name: "hand", order: 0.5, lift: 0.004, src: "hands", dir: [1, 0, 0], m: (x, y, z, nx, f, sgm, kz) => {   // back of the hand and finger tops
        const o = nx * out(x);
        if (f < 0) return 0.04 * Math.min(o - 0.35, (2.245 - y) * 25, (y - 2.095) * 25);
        if (f > 3.5) return -1;
        return 0.04 * Math.min(o - 0.3, Math.abs(sgm - 0.454) * 3 - 0.09, Math.abs(sgm - 0.76) * 3 - 0.09, 0.96 - sgm,
          (0.0072 - Math.abs(z - kz)) * 60); } },   // one plate per finger segment, a glowing gap between fingers
  ];
  const plateUni = { uOpen: { value: 0 }, uSeam: { value: 0.25 } };
  const handUni = { uCurl: { value: 0.2 }, uFlex: { value: 0 } };
  const handGeo = pre ? unpack(pre.hands) : meshHands(phone ? 0.009 : 0.0065);
  part("armour", 1, (add, reveal) => {
    for (const pl of PLATES) {
      const src = pl.src === "hands" ? handGeo : figureGeo;
      const P = src.attributes.position.array, N = src.attributes.normal.array, I = src.index.array;
      const F = src.attributes.aFing?.array, S = src.attributes.aSeg?.array, K = src.attributes.aKnuck?.array;
      const nv = P.length / 3, mv = new Float32Array(nv);
      for (let q = 0; q < nv; q++) mv[q] = pl.m(P[q * 3], P[q * 3 + 1], P[q * 3 + 2], N[q * 3], F ? F[q] : -1, S ? S[q] : 0, K ? K[q * 3 + 2] : 0);
      const remap = new Int32Array(nv).fill(-1), pos = [], nrm = [], edge = [], idx = [], fing = [], segs = [], knk = [];
      const lift = pl.lift ?? 0.03;
      for (let t = 0; t < I.length; t += 3) {
        const a = I[t], b = I[t + 1], c = I[t + 2];
        if (mv[a] <= 0 && mv[b] <= 0 && mv[c] <= 0) continue;   // border triangles are kept and trimmed smoothly in the shader
        for (const v of [a, b, c]) {
          if (remap[v] < 0) { remap[v] = pos.length / 3;
            pos.push(P[v * 3] + N[v * 3] * lift, P[v * 3 + 1] + N[v * 3 + 1] * lift, P[v * 3 + 2] + N[v * 3 + 2] * lift);
            nrm.push(N[v * 3], N[v * 3 + 1], N[v * 3 + 2]); edge.push(Math.max(mv[v], -0.04));
            if (F) { fing.push(F[v]); segs.push(S[v]); knk.push(K[v * 3], K[v * 3 + 1], K[v * 3 + 2]); } }
          idx.push(remap[v]);
        }
      }
      if (!idx.length) continue;
      const g = new THREE.BufferGeometry(), n = pos.length / 3, d = new THREE.Vector3(...pl.dir).normalize();
      g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
      g.setAttribute("normal", new THREE.Float32BufferAttribute(nrm, 3));
      g.setAttribute("aEdge", new THREE.Float32BufferAttribute(edge, 1));
      g.setAttribute("aOpenDir", new THREE.Float32BufferAttribute(Array.from({ length: n }, () => [d.x, d.y, d.z]).flat(), 3));
      g.setAttribute("uv", new THREE.BufferAttribute(new Float32Array(n * 2), 2));
      if (F) { g.setAttribute("aFing", new THREE.Float32BufferAttribute(fing, 1)); g.setAttribute("aSeg", new THREE.Float32BufferAttribute(segs, 1));
        g.setAttribute("aKnuck", new THREE.Float32BufferAttribute(knk, 3)); }
      g.setIndex(idx);
      const mat = new THREE.ShaderMaterial({ vertexShader: F ? HAND_PLATE_VERT : PLATE_VERT, fragmentShader: PLATE_FRAG, transparent: true, depthWrite: true,
        uniforms: { ...U, uHeadOn: { value: 1 }, uInflate: { value: 0 }, uReveal: reveal, uOpacity: { value: 1 }, ...plateUni, ...(F ? handUni : {}) },
        extensions: { derivatives: true } });
      const mesh = add(new THREE.Mesh(g, mat)); mesh.renderOrder = -1;   // drawn first: the plates hide the glow behind them, never glow in front
      metals.push({ mesh, order: pl.order, dir: d });
    }
  });
  // the hands themselves (light body), and the mechanical joints: elbow and knee hubs, wrist rings
  part("hands", 1, (add) => {
    add(new THREE.Mesh(handGeo, holo({ vert: HAND_VERT, opacity: 1, rim: 1.6, core: 0.1, panel: 0, head: true, extra: handUni })));
  });
  part("joints", 1, (add) => {
    const ring = (r, tube, at, rot) => { const g = new THREE.TorusGeometry(r, tube, 6, 48);
      g.rotateX(rot[0]); g.rotateY(rot[1]); g.translate(...at); return g; };   // baked into rest coordinates (the joints bend them)
    const geos = [];
    for (const sg of [1, -1]) {
      geos.push(ring(0.048, 0.005, [sg * 0.872, 3.04, -0.03], [0, Math.PI / 2]), ring(0.028, 0.004, [sg * 0.876, 3.04, -0.03], [0, Math.PI / 2]));   // elbow hub
      geos.push(ring(0.05, 0.005, [sg * 0.375, 1.34, 0.03], [0, Math.PI / 2]), ring(0.03, 0.004, [sg * 0.38, 1.34, 0.03], [0, Math.PI / 2]));      // knee hub
      geos.push(ring(0.053, 0.004, [sg * 0.884, 2.29, 0.05], [Math.PI / 2, 0]));                                                                  // wrist ring
    }
    add(new THREE.Mesh(mergeGeos(geos), holo({ opacity: 1, rim: 1.4, flow: true, core: 0.6, head: true })));
  });
  part("wire", 2, (add) => {   // stage 2: a fine holographic wireframe over the body
    if (phone) return;
    const wg = pre && pre.wire ? unpack(pre.wire) : meshFigure(0.075, [-1.12, -0.05, -0.48], [1.12, 4.38, 0.48]);
    add(new THREE.Mesh(wg, holo({ wire: true, opacity: 0.1, rim: 0.4, core: 0.22, panel: 0, head: true })));
  });
  let shieldMat = null, shieldMesh = null, shieldFlare = 0;
  if (!phone) part("shield", 1, (add) => {
    shieldMat = new THREE.ShaderMaterial({ vertexShader: VERT, fragmentShader: SHIELD_FRAG, transparent: true, depthWrite: false,
      blending: THREE.AdditiveBlending, side: THREE.DoubleSide,
      uniforms: { ...U, uHeadOn: { value: 1 }, uInflate: { value: 0.11 }, uShield: { value: 0 } }, extensions: { derivatives: true } });
    shieldMesh = add(new THREE.Mesh(figureGeo, shieldMat)); shieldMesh.renderOrder = 6;
  });

  // ---- evolution: light and energy only ---------------------------------------------------------------------------
  part("halo", 4, (add) => {
    for (const [r, o, sp] of [[0.6, 0.9, 0.5], [0.7, 0.45, -0.5]]) {
      const ring = add(new THREE.Mesh(new THREE.TorusGeometry(r, 0.008, 6, 160), holo({ opacity: o, rim: 1.5, flow: true, core: 0.5 })), headPivot);
      ring.position.set(0, 0.44, -0.4); spinners.push({ obj: ring, speed: sp * 0.2, axis: "z" });
    }
  });
  part("crown", 4, (add) => {
    for (const s of [-1, 1]) {
      const g = new THREE.TorusGeometry(0.42, 0.008, 4, 40, 1.2).rotateZ(Math.PI / 2 - 0.6);
      const m = add(new THREE.Mesh(g, holo({ opacity: 1, rim: 1.8, flow: true, core: 0.7 })), headPivot);
      m.position.set(0.14 * s, 0.75, -0.05); m.rotation.set(0.2, 0, -0.35 * s); m.scale.setScalar(0.6);
    }
  });

  // ---- environment ------------------------------------------------------------------------------------------------
  // orbit rings (more layers at stage 2) carrying the eight system satellites (status from the dashboard's snapshot)
  const orbits = new THREE.Group(); figure.add(orbits);
  const envX = buildEnvironment({ holo, part, U, REACTOR, glowTexture, phone }, { scene, figure, SCALE, BASE_Y });
  const orbitRings = [];
  for (const [r, y, tilt, o, tier] of [[2.05, 2.0, 0.18, 0.75, 1], [1.78, 2.0, -0.1, 0.5, 1], [2.3, 2.3, 0.3, 0.3, 2]]) {
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

  // live data aura: four bands around the lower body, each filled by a real value (hidden when unavailable)
  const AURA_VERT = `varying vec2 vUv; void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`;
  const AURA_FRAG = `uniform vec3 uColor; uniform float uFill, uGain, uTime; varying vec2 vUv;
    void main() { float on = step(vUv.x, uFill); float head = exp(-pow((vUv.x - uFill) * 70.0, 2.0));
      float a = (0.06 + on * (0.45 + 0.2 * sin(vUv.x * 90.0 - uTime * 2.0)) + head * 1.2) * uGain;
      gl_FragColor = vec4(uColor * (1.0 + head * 0.6), a); }`;
  const aura = {};
  [["cpu", "#f3e3bd", 1.9, 0.95, 0.16], ["memory", "#fff8ec", 1.96, 1.15, -0.1], ["missions", "#eba866", 2.02, 1.35, 0.12],
   ["decisions", "#f2a33a", 2.08, 1.55, -0.14]].forEach(([key, c, r, y, tilt], i) => {
    const mat = new THREE.ShaderMaterial({ vertexShader: AURA_VERT, fragmentShader: AURA_FRAG, transparent: true, depthWrite: false,
      blending: THREE.AdditiveBlending, uniforms: { uColor: { value: new THREE.Color(c) }, uFill: { value: 0 }, uGain: U.uGain, uTime: U.uTime } });
    const ring = new THREE.Mesh(new THREE.TorusGeometry(r, 0.007, 4, 180), mat);
    ring.rotation.set(Math.PI / 2 - tilt, 0, i * 0.8); ring.position.y = y; ring.visible = false; figure.add(ring);
    aura[key] = { ring, target: 0, value: 0 };
  });

  // thought constellation: one node per real stage of the current answer, linked in order, above the head
  const thought = new THREE.Group(); thought.position.y = 5.55; figure.add(thought);
  const thoughtNodes = [0, 1, 2, 3, 4, 5].map((i) => {
    const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTexture(), color: WHITE, transparent: true, opacity: 0,
      blending: THREE.AdditiveBlending, depthWrite: false }));
    sp.position.set(-1.0 + i * 0.4, Math.sin((i / 5) * Math.PI) * 0.22, 0); sp.scale.set(0.22, 0.22, 1); thought.add(sp);
    return sp;
  });
  const thoughtLine = new THREE.Line(new THREE.BufferGeometry().setFromPoints(thoughtNodes.map((n) => n.position)),
    new THREE.LineBasicMaterial({ color: CHAMPAGNE, transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false }));
  thought.add(thoughtLine);
  let thoughtCount = 0, thoughtActive = false, thoughtAlpha = 0, thoughtBorn = [];

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
  // The owner's projection settings (per device) and the quality preset. Auto starts Balanced and steps down
  // when frames take too long (or up when there is room), measured in Normal mode while animating.
  const OPT = { quality: "auto", particles: "normal", animation: "normal", reactor: "normal", orbit: "normal", env: true, orbitals: true, panels: false,
               view: "front", camspeed: "normal", lowBattery: false };
  const K = { particles: { low: 0.35, normal: 0.7, high: 1 }, animation: { calm: 0.6, normal: 1, lively: 1.35 },
              reactor: { soft: 0.7, normal: 1, bright: 1.3 }, orbit: { slow: 0.5, normal: 1, fast: 1.6 } };
  let quality = phone ? "low" : "balanced", panelItems = null;
  // Auto quality with hysteresis: frame times are averaged over ~90 frames; it steps down when they average over
  // 55 ms, and up only after two good windows in a row; any change then holds for at least 8 s, and stepping back up
  // after a step down waits 20 s. Every change is logged with the measured average (Diagnostics shows it).
  // Low Power: chosen by you, or by Auto when the browser reports the battery low and not charging.
  const autoQ = { sum: 0, n: 0, good: 0, changedAt: -1e9, downAt: -1e9, reason: "starting balanced", log: [] };
  const lean = () => quality === "low" || quality === "lowpower";
  function setAutoQuality(to, why, avg) {
    if (to === quality) return;
    autoQ.log.push({ at: Date.now(), from: quality, to, why, avgMs: avg ? +avg.toFixed(1) : null }); if (autoQ.log.length > 6) autoQ.log.shift();
    const order = ["lowpower", "low", "balanced", "high"];
    if (order.indexOf(to) < order.indexOf(quality)) autoQ.downAt = performance.now();
    quality = to; autoQ.changedAt = performance.now(); autoQ.reason = why; autoQ.good = 0;
    applyQuality();
  }
  function applyQuality() {
    renderer.setPixelRatio(Math.min({ high: 1.5, balanced: 1.25, low: 1, lowpower: 0.85 }[quality] || 1, window.devicePixelRatio || 1));
    const dens = K.particles[OPT.particles] * (quality === "lowpower" ? 0.4 : quality === "low" ? 0.6 : 1);
    for (const pts of [shed, wisps, dust, rebuild.points, reactorX.swirl()].filter(Boolean)) {
      const n = pts.geometry.attributes.position.count; pts.geometry.setDrawRange(0, Math.max(1, Math.floor(n * dens)));
    }
    envX.setVisible(OPT.env, OPT.orbitals); orbits.visible = OPT.orbitals;
    resize();
  }
  let optKey = "";
  function setOptions(o = {}) {
    for (const k of Object.keys(OPT)) if (o[k] !== undefined) OPT[k] = o[k];
    const key = JSON.stringify(OPT);
    if (key === optKey) return;   // unchanged: nothing to redraw
    optKey = key;
    if (OPT.quality !== "auto") { quality = OPT.quality; autoQ.reason = "your setting"; }
    else if (OPT.lowBattery && quality !== "lowpower") { autoQ.reason = ""; setAutoQuality("lowpower", "battery low and not charging"); }
    else if (!OPT.lowBattery && quality === "lowpower") setAutoQuality("balanced", "battery no longer low");
    else if (autoQ.reason === "your setting") autoQ.reason = "measuring";
    rig.setRest(OPT.view); rig.setSpeed(OPT.camspeed);
    applyQuality(); envX.setPanels(panelItems, OPT.panels && OPT.env); kick();
  }
  let panelKey = "";
  function setPanels(items) {   // redraw only when the lines change and the panels are showing (no wake-ups on every poll)
    const key = JSON.stringify(items || null);
    if (key === panelKey) return;
    panelKey = key; panelItems = items;
    if (OPT.panels && OPT.env) { envX.setPanels(items, true); kick(); }
  }
  function autoQuality(interval) {   // called once per animated frame in Normal mode
    if (OPT.quality !== "auto" || quality === "lowpower") return;   // Low Power (battery) holds until the battery recovers
    autoQ.sum += interval; autoQ.n++;
    if (autoQ.n < 90) return;
    const avg = autoQ.sum / autoQ.n, now = performance.now(); autoQ.sum = 0; autoQ.n = 0;
    if (now - autoQ.changedAt < 8000) return;                       // hold any change for at least 8 s
    const order = ["low", "balanced", "high"], i = order.indexOf(quality);
    if (avg > 55 && i > 0) setAutoQuality(order[i - 1], "frames too slow", avg);        // under ~18 fps: lighter
    else if (avg < 37 && i < 2) {                                                       // holding the frame cap: richer
      if (++autoQ.good >= 2 && now - autoQ.downAt > 20000) setAutoQuality(order[i + 1], "frames fast enough", avg);
    } else autoQ.good = 0;
  }
  let target = LOOKS.idle, state = "idle", tier = 1, mode = opts.mode || "full", intensity = opts.intensity || 1;
  const targetTint = new THREE.Color(LOOKS.idle.tint);
  let lost = false, losses = 0, restores = 0;   // GPU context loss (see below)
  let frameAvg = 0, t = 0, last = 0, raf = 0, visible = true, flash = 0, settling = 2.5, speech = 0, beatAt = 0, arcAt = 0;
  const headTarget = new THREE.Euler(), headCur = new THREE.Euler();
  // idle liveliness: occasional glances (toward the message box or the side panels) and sensor "shutter blinks"
  const GLANCES = [[0.13, 0], [0.02, -0.26], [0.02, 0.26], [-0.05, -0.12], [0.08, 0.14]];
  let glance = null, glanceAt = 6, blinkAt = 4, blink = 0;
  // personality (avatar-events.js): how the figure moves for the current state; null = this file's own defaults
  let pers = null, persAt = 0;
  function setPersonality(p) {
    const name = p && p.name ? p.name : null;
    if ((pers && pers.name) === name) return;
    pers = name ? { name, head: p.head, gesture: p.gesture, glances: !!p.glances } : null; persAt = t;
    settling = Math.max(settling, 2); kick();
  }
  const headMode = () => (pers ? pers.head : target.head);
  const gestureOf = () => (pers ? pers.gesture : POSE_OF[state] || "rest");

  function setState(s) {
    if (!LOOKS[s] || s === state) return;
    const prev = state;
    state = s; target = LOOKS[s]; targetTint.set(target.tint);
    if (s === "completed") { flash = 1; firePulse(1.4); reactorX.confirm(); }   // the golden confirmation: a real completion only
    if (s === "error" || s === "warning") shieldFlare = 2.5;   // the shield flares on a real alert
    if (s === "disagreeing") shieldFlare = 1.6;                 // and briefly when your rules refuse an action
    if (s === "recovery" && mode === "full") for (const p of Object.values(parts)) p.reveal.value = -1.5;   // reconstruction
    if (prev === "halted" && mode === "full") { demat = null; for (const p of Object.values(parts)) p.reveal.value = -1.5; }   // rebuilt on release
    if (s === "halted" && mode === "full") {   // the real emergency stop: the projection dematerialises from the head down
      demat = { t: 0, done: false };
      for (const p of figureParts()) p.reveal.value = Math.min(p.reveal.value, 5.4);
      if (opts.onLifecycle) opts.onLifecycle("dematerializing");
    }
    settling = 2.5; kick();
  }
  function setTier(n) {
    n = Math.max(1, Math.min(5, Number(n) || 1));
    if (n === tier) return;
    const up = tier !== 0 && n > tier;
    tier = n; applyTier(up);
  }
  // the parts that make up the figure itself (not the platform, the orbits or the environment)
  let figPartsCache = null;
  function figureParts() {
    if (figPartsCache) return figPartsCache;
    const inFigure = (o) => { for (let x = o; x; x = x.parent) if (x === body || x === headPivot) return true; return false; };
    figPartsCache = Object.values(parts).filter((p) => p.objs.length && p.objs.every(inFigure));
    return figPartsCache;
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
    if (m !== "full") demat = null;   // Low performance / Reduced motion: no sequences, the static look
    mode = m;
    if (mode !== "full") for (const p of Object.values(parts)) p.reveal.value = 10;
    settling = 1; kick();
  }
  function setIntensity(x) { intensity = Math.max(0.5, Math.min(1.5, Number(x) || 1)); settling = 1; kick(); }
  // A real speech event (a word boundary from the browser's speech engine) gives the reactor a brief pulse.
  function pulse(strength = 1) { speech = Math.min(1.5, speech + 0.6 * strength); kick(); }
  // your voice while recording (measured microphone level 0..1): the reactor and sensors follow it (not in Reduced motion)
  let voice = 0, voiceGoal = 0;
  function setVoice(v) {
    const x = mode === "off" ? 0 : Math.max(0, Math.min(1, Number(v) || 0));
    if (Math.abs(x - voiceGoal) < 0.02 && !(x === 0 && voiceGoal !== 0)) return;
    voiceGoal = x; kick();
  }
  function setAura(values) {
    let changed = false;
    for (const [key, a] of Object.entries(aura)) {
      const v = values ? values[key] : null;
      const show = typeof v === "number" && isFinite(v);
      const target = show ? Math.max(0.01, Math.min(1, v)) : 0;
      if (show !== a.ring.visible || Math.abs(target - a.target) > 0.005) changed = true;
      a.ring.visible = show; a.target = target;
    }
    if (changed) kick();   // redraw only when a value really changed (Low performance draws on change only)
  }
  function setThought(count, active) {
    const n = Math.max(0, Math.min(6, count | 0));
    for (let i = thoughtCount; i < n; i++) thoughtBorn[i] = t;
    thoughtCount = n; thoughtActive = !!active; if (active) thoughtAlpha = Math.max(thoughtAlpha, 0.01);
    kick();
  }
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
  setOptions(opts.options || {});   // the owner's projection settings and the quality preset
  {   // compile every shader now (all layers, including those a quality or stage change shows later), not mid-animation
    const off = []; scene.traverse((o) => { if (!o.visible) { off.push(o); o.visible = true; } });
    try { renderer.compile(scene, camera); } catch (e) { /* compiled on first use instead */ }
    for (const o of off) o.visible = false;
  }
  // remember where every plate belongs (for the assembly sequence)
  for (const m of metals) {
    m.home = { p: m.mesh.position.clone(), q: m.mesh.quaternion.clone(), s: m.mesh.scale.clone() };
    const dir = m.dir ? m.dir.clone() : m.home.p.clone().sub(new THREE.Vector3(0, 2.2, 0)); if (dir.lengthSq() < 0.01) dir.set(0, 0, 1);
    dir.normalize();
    m.from = { p: m.home.p.clone().add(dir.multiplyScalar(2.6)).add(new THREE.Vector3(0, 0.8, 1.2)),
               q: m.home.q.clone().multiply(new THREE.Quaternion().setFromEuler(new THREE.Euler((Math.random() - 0.5) * 0.3, (Math.random() - 0.5) * 0.3, (Math.random() - 0.5) * 0.3))) };
  }
  // Startup assembly (once per session, Normal mode only): platform → hologram body → plates lock on → reactor ignites.
  let boot = opts.boot && mode === "full" ? { t: 0, fired: false } : null;
  const BOOT_END = 4.6;
  const ease = (x) => 1 - Math.pow(1 - Math.min(1, Math.max(0, x)), 3);
  function bootStep(dt) {
    boot.t += dt;
    const bt = boot.t;
    for (const p of Object.values(parts)) if (p.reveal.value < 10) p.reveal.value = Math.min(p.reveal.value, -1.2 + Math.max(0, bt - 0.5) * 2.8);
    for (const m of metals) {
      const k = ease((bt - 1.3 - m.order * 1.6) / 0.85);
      m.mesh.visible = k > 0 && (m.mesh.parent.visible !== false);
      m.mesh.position.lerpVectors(m.from.p, m.home.p, k);
      m.mesh.quaternion.slerpQuaternions(m.from.q, m.home.q, k);
      m.mesh.scale.copy(m.home.s).multiplyScalar(0.55 + 0.45 * k);
    }
    if (bt > 3.4 && !boot.fired) { boot.fired = true; flash = 0.8; firePulse(1.6); }
    if (bt >= BOOT_END) finishBoot();
  }
  function finishBoot() {
    if (!boot) return;
    for (const m of metals) { m.mesh.position.copy(m.home.p); m.mesh.quaternion.copy(m.home.q); m.mesh.scale.copy(m.home.s); m.mesh.visible = true; }
    boot = null;
    if (opts.onBootEnd) opts.onBootEnd();
    kick();
  }

  // Gestures, chosen only by the real state: [shoulder out, forearm forward, forearm out] per side (radians).
  const POSES = {
    rest:    { r: [0.02, 0.08, 0.02], l: [0.02, 0.08, 0.02] },
    present: { r: [0.16, 0.75, 0.42], l: [0.03, 0.12, 0.03] },   // speaking: the right hand opens toward you
    work:    { r: [0.08, 0.95, -0.12], l: [0.08, 0.95, -0.12] }, // coding / executing: both hands up, working
    raise:   { r: [0.38, 0.3, 2.45], l: [0.03, 0.12, 0.03] },    // waiting for your approval: the right hand raised
    open:    { r: [0.24, 0.32, 0.5], l: [0.24, 0.32, 0.5] },     // completed: both hands open
    halt:    { r: [0.3, 1.15, 0.55], l: [0.03, 0.12, 0.03] },     // refused by your rules: the right hand comes up, palm out
  };
  const POSE_OF = { speaking: "present", coding: "work", executing: "work", approval: "raise", completed: "open" };
  const armCur = { r: [0.02, 0.08, 0.02], l: [0.02, 0.08, 0.02] };
  const _e = new THREE.Euler(), _m4 = new THREE.Matrix4(), _m4b = new THREE.Matrix4();
  function armPose(k) {
    const pose = POSES[gestureOf()] || POSES.rest, work = gestureOf() === "work" && mode === "full";
    for (const sd of ["r", "l"]) {
      const sg = sd === "r" ? 1 : -1, c = armCur[sd];
      for (let i = 0; i < 3; i++) c[i] += (pose[sd][i] - c[i]) * k;
      const typing = work ? Math.sin(t * 2.2 + (sg > 0 ? 0 : 1.6)) * 0.05 : 0;   // small alternating hand motion while working
      _m4.makeRotationFromEuler(_e.set(0, 0, c[0] * sg));
      _m4b.makeRotationFromEuler(_e.set(-(c[1] + typing), 0, c[2] * sg));
      U[sd === "r" ? "uArmR" : "uArmL"].value.setFromMatrix4(_m4);
      U[sd === "r" ? "uForeR" : "uForeL"].value.setFromMatrix4(_m4.clone().multiply(_m4b));
    }
  }

  function headMotion() {
    const h = headMode(), since = t - persAt;
    if (h === "attend") headTarget.set(0.1, Math.sin(t * 0.4) * 0.03, 0);              // toward the message box
    else if (h === "think") headTarget.set(-0.04, Math.sin(t * 0.3) * 0.08, 0.04);     // slight tilt, slow scan
    else if (h === "scan") headTarget.set(0.02, Math.sin(t * 0.55) * 0.16, pers && pers.name === "curious" ? 0.05 : 0);   // looking across sources, head tilted
    else if (h === "speak") headTarget.set(0.03 + speech * 0.03, Math.sin(t * 0.5) * 0.05, 0);
    else if (h === "still") headTarget.set(0.05, 0, 0);
    else if (h === "shake") headTarget.set(-0.03, Math.sin(since * 7) * 0.11 * Math.max(0, 1 - since / 1.3), 0);   // one small shake, then holds
    else if (h === "rise") headTarget.set(0.03 + 0.17 * Math.max(0, 1 - since / 2.4), Math.sin(t * 0.3) * 0.03, 0);   // lifts as it comes back
    else if (glance) headTarget.set(glance[0], glance[1], 0);                          // a glance at something
    else headTarget.set(Math.sin(t * 0.31) * 0.02, Math.sin(t * 0.23) * 0.07, 0);     // awareness
    if (director.active && h !== "still") headTarget.y = 0.32 + Math.sin(t * 0.4) * 0.04;   // looks toward the projection
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
    if (!visible || document.hidden || lost) return;
    const cap = quality === "lowpower" ? (phone ? 1000 / 15 : 1000 / 20) : phone ? 1000 / 24 : 1000 / 30;
    if (mode === "full" && now - last < cap) { raf = requestAnimationFrame(frame); return; }
    const dt = Math.min(0.1, last ? (now - last) / 1000 : 0.033);
    if (mode === "full" && last && !boot) autoQuality(now - last);
    if (last && now - last < 500) frameAvg = frameAvg ? frameAvg * 0.9 + (now - last) * 0.1 : now - last;   // measured, for Diagnostics
    last = now;
    const moving = mode === "full";
    if (moving) t += dt;
    const k = moving ? 1 - Math.exp(-dt * 2.2) : 1;   // ~0.6–1 s blend between states
    armPose(k);
    const CURL = { present: 0.08, work: 0.42, raise: 0.02, open: 0.0, rest: 0.2, halt: 0.0 };
    handUni.uCurl.value += ((state === "halted" ? 0.32 : CURL[gestureOf()] ?? 0.2) - handUni.uCurl.value) * k;
    handUni.uFlex.value = moving ? 0.05 : 0;   // the fingers flex slightly (Normal mode only)
    FACE.uThink.value = cur.neural;
    // armour: seams brighten and plates vent (part slightly) only while really working; the shield after an alert
    const busyState = ["reasoning", "planning", "coding", "executing", "researching", "verifying", "writing", "understanding"].includes(state);
    const heavy = ["coding", "executing", "reasoning"].includes(state);
    plateUni.uSeam.value += ((busyState ? 1 : state === "error" ? 0.6 : 0.25) - plateUni.uSeam.value) * k;
    plateUni.uOpen.value += ((heavy && moving ? 0.045 + Math.sin(t * 1.7) * 0.008 : 0) - plateUni.uOpen.value) * k;
    if (shieldMat) {
      shieldFlare = Math.max(0, shieldFlare - dt);
      const alert = state === "error" ? 0.25 : 0;
      const flick = moving ? (0.6 + 0.4 * Math.sin(t * 23) * Math.sin(t * 7.3)) : 1;
      shieldMat.uniforms.uShield.value = Math.max(alert, Math.min(1, shieldFlare) * (moving ? flick : 0.5));
      shieldMesh.visible = shieldMat.uniforms.uShield.value > 0.01 && tier >= 1;
      if (shieldFlare > 0 && moving) settling = Math.max(settling, 0.2);
    }
    for (const key of NUMERIC) cur[key] += ((target[key] ?? 0) - cur[key]) * k;
    cur.tint.lerp(targetTint, k);
    flash = Math.max(0, flash - dt * 0.8);
    speech = Math.max(0, speech - dt * 3);
    voice += (voiceGoal - voice) * (moving ? 1 - Math.exp(-dt * 14) : 1);
    let revealing = false;
    const down = demat ? new Set(figureParts()) : null;
    for (const p of Object.values(parts)) {
      if (down && down.has(p)) { p.reveal.value = Math.max(-1.6, Math.min(p.reveal.value, 5.4) - dt * 2.4); continue; }
      if (p.reveal.value < 10) { p.reveal.value += dt * (state === "recovery" ? 1.6 : 3.2); revealing = true; if (p.reveal.value >= 6) p.reveal.value = 10; }
    }
    if (demat && !demat.done) {
      demat.t += dt; revealing = true;
      if (figureParts().every((p) => p.reveal.value <= -1.55)) { demat.done = true; if (opts.onLifecycle) opts.onLifecycle(null); }
    }
    // particles and the scanning ring follow the figure's build edge while a sequence runs
    const edge = parts.figure ? parts.figure.reveal.value : 10;
    const seq = demat && !demat.done ? -1 : (edge < 6 && (boot || revealing) ? 1 : 0);
    rebuild.update(edge, mode === "full" ? seq : 0);
    scanRing.visible = seq !== 0 && mode === "full";
    if (scanRing.visible) scanRing.position.y = (edge - BASE_Y) / SCALE;
    // shared uniforms
    U.uTime.value = t; U.uTint.value.copy(cur.tint); U.uScan.value = cur.scan; U.uFlow.value = cur.flow;
    U.uFlicker.value = moving ? cur.flicker : 0;
    U.uRimK.value = cur.rim * (1 + flash * 0.8);
    U.uGain.value = intensity * (1 + flash * 0.4);
    const eyeLevel = cur.eyes * (1 + flash * 0.6 + speech * 0.4);
    EYE.value = eyeLevel * (1 + voice * 0.35); FACE.uSpeech.value = Math.min(1, Math.max(speech, voice * 0.8));
    FACE.uEyeHot.value += ((state === "error" ? 0 : 1) - FACE.uEyeHot.value) * k;   // deep red eyes only on a genuine error
    if (!moving) { FACE.uEyeOpen.value = 1; FACE.uEyeLook.value = 0; FACE.uEyeScan.value = 0; }
    const breathe = moving ? 0.92 + 0.08 * Math.sin(t * 1.3) : 1;
    REACTOR.value = cur.reactor * breathe * (1 + speech * 0.8 + voice * 0.9 + flash) * K.reactor[OPT.reactor];
    if (innerMat) innerMat.uniforms.uOpacity.value = 0.12 + cur.neural * 0.5 + flash * 0.3;   // the inner network brightens while thinking
    neuralX.update(cur.neural, ["executing", "coding", "verifying"].includes(state), REACTOR.value);
    const projecting = director.update(dt, moving);
    const camMoving = rig.update(moving ? 1 - Math.exp(-dt * 4) : 1, director.wide, director.wideX, director.wideR);
    const confirming = reactorX.update(dt * K.animation[OPT.animation], moving, target.rpat);
    envX.update(dt, moving, { ring: cur.ring, reactor: REACTOR.value, animK: K.animation[OPT.animation], orbitK: K.orbit[OPT.orbit] });
    const seams = [0.7, 1.0, 1.2, 1.35, 1.5][tier - 1] || 1;
    for (const m of lineMats) { m.color.copy(cur.tint); m.opacity = m.userData.lineBase * seams * Math.min(1.3, intensity); }
    for (const g of eyeGlows) { g.material.opacity = Math.min(1, 0.7 * eyeLevel * intensity); g.material.color.copy(cur.tint).lerp(WHITE, 0.75); }
    reactorGlow.material.opacity = Math.min(1, 0.25 * REACTOR.value * intensity); reactorGlow.material.color.copy(cur.tint).lerp(WHITE, 0.5);
    beamMat.uniforms.uBeam.value = cur.beam * (1 + flash) * intensity;
    net.uni.uNeural.value = cur.neural;
    data.material.uniforms.uData.value = cur.data;
    data.visible = cur.data > 0.02 && moving;
    dust.material.uniforms.uSpeed.value = 1 + flash * 4 + Math.abs(cur.flow) * 0.3;
    dust.visible = moving;
    if (boot) bootStep(dt);
    if (boot) {   // order: body forms, circuitry lights, sensors wake, the reactor ignites, the orbitals synchronise
      EYE.value *= ease((boot.t - 2.0) / 0.5);
      orbits.scale.setScalar(0.4 + 0.6 * ease((boot.t - 3.4) / 0.9));
    } else if (orbits.scale.x !== 1) orbits.scale.setScalar(1);
    const bootDim = boot ? Math.min(1, Math.max(0, (boot.t - 3.2) / 0.5)) : 1;   // the reactor ignites last
    REACTOR.value *= boot ? 0.08 + 0.92 * bootDim : 1;
    beamMat.uniforms.uBeam.value *= boot ? Math.min(1, boot.t / 0.8) : 1;
    if (figureMat) {   // finer detail and brighter seams light up with each stage
      figureMat.uniforms.uPanel.value = [0.25, 0.35, 0.45, 0.55, 0.62][tier - 1] || 0.35;
      const circ = boot ? ease((boot.t - 2.3) / 0.8) : 1;   // during startup the circuitry lights after the body forms
      figureMat.uniforms.uContour.value = ([0.75, 0.9, 1.05, 1.2, 1.3][tier - 1] || 0.9) * circ;
      figureMat.uniforms.uDetail.value = ([0.75, 0.85, 1.0, 1.15, 1.25][tier - 1] || 0.75) * circ;   // rich now, maximum at stage 5 (finer circuits from stage 3)
      if (auraMat) auraMat.uniforms.uOpacity.value = [0.3, 0.36, 0.42, 0.5, 0.56][tier - 1] || 0.3;
    }
    shed.visible = moving; wisps.visible = moving;
    if (parts.wire) for (const o of parts.wire.objs) o.visible = tier >= 2 && quality === "high";   // fine wireframe: High only
    if (auraMesh) auraMesh.visible = !lean();
    for (const a of Object.values(aura)) {
      a.value += (a.target - a.value) * (moving ? 1 - Math.exp(-dt * 2) : 1);
      a.ring.material.uniforms.uFill.value = a.value;
      if (moving) a.ring.rotation.z += dt * 0.05;
    }
    thoughtAlpha = thoughtActive ? Math.min(1, thoughtAlpha + dt * 3) : Math.max(0, thoughtAlpha - dt * 0.5);
    thought.visible = thoughtAlpha > 0.01 && thoughtCount > 0;
    if (thought.visible) {
      thoughtNodes.forEach((n, i) => {
        const on = i < thoughtCount; const age = on ? t - (thoughtBorn[i] ?? t) : 9;
        n.material.opacity = on ? thoughtAlpha * (0.6 + 0.4 * Math.exp(-age * 2)) : 0;
        const sc = 0.18 + (on ? Math.exp(-age * 3) * 0.25 : 0); n.scale.set(sc, sc, 1);
        n.material.color.copy(cur.tint).lerp(WHITE, 0.6);
      });
      thoughtLine.geometry.setDrawRange(0, Math.max(0, thoughtCount));
      thoughtLine.material.opacity = 0.5 * thoughtAlpha; thoughtLine.material.color.copy(cur.tint);
      if (moving) thought.rotation.y = Math.sin(t * 0.3) * 0.15;
    }
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
      if (pers ? pers.glances : target.head === "aware") {
        if (t > glanceAt) {
          if (glance) { glance = null; glanceAt = t + 6 + Math.random() * 5; }
          else { glance = GLANCES[Math.floor(Math.random() * GLANCES.length)]; glanceAt = t + 1.6 + Math.random(); }
        }
      } else glance = null;
      if (t > blinkAt) { blink = 1; blinkAt = t + 6 + Math.random() * 6; }
      blink = Math.max(0, blink - dt * 5);
      const shut = headMode() === "still" ? 1 : 1 - Math.sin(blink * Math.PI) * 0.85;
      const narrow = state === "warning" || state === "error" ? 0.6 : 1;
      const look = state === "researching" || state === "verifying" ? Math.sin(t * 2.2) * 0.022 : glance ? glance[1] * 0.05 : 0;
      FACE.uEyeOpen.value = shut * narrow;
      FACE.uEyeLook.value = glance && state !== "researching" && state !== "verifying" ? glance[1] * 0.07 : look * 0.7;   // the eyes follow the glance
      FACE.uEyeScan.value += ((state === "researching" || state === "verifying" ? 1 : 0) - FACE.uEyeScan.value) * k;
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
      reactor.scale.setScalar(REACTOR_SIZE * beatK);
      if (rp === "scan") reactorRings[2] && (reactorRings[2].obj.rotation.z = Math.sin(t * 1.4) * 1.6);
      headMotion();
      for (const ax of ["x", "y", "z"]) headCur[ax] += (headTarget[ax] - headCur[ax]) * (1 - Math.exp(-dt * 2.5));
      headPivot.rotation.copy(headCur);
      U.uHead.value.setFromMatrix4(new THREE.Matrix4().makeRotationFromEuler(headCur));   // turns the figure's head
      shed.material.uniforms.uRate.value = 0.8 + Math.abs(cur.flow) * 0.4 + flash * 3;
      wisps.material.uniforms.uRate.value = 0.8 + cur.neural * 0.8 + flash * 2;
      const animK = K.animation[OPT.animation], orbitK = K.orbit[OPT.orbit];
      orbitRings.forEach((r) => { r.rotation.z += dt * (0.05 + cur.ring) * r.userData.spin * orbitK; });
      for (const s of spinners) s.obj.rotation[s.axis] += dt * s.speed * (0.5 + cur.ring) * animK;
      for (const rr of reactorRings) {
        if (rr.orbit) { rr.obj.userData.angle += dt * rr.speed * (0.4 + cur.reactor); const a = rr.obj.userData.angle;
          rr.obj.position.set(Math.cos(a) * rr.orbit, Math.sin(a) * rr.orbit, 0); rr.obj.rotation.z = a; }
        else if (!(target.rpat === "scan" && rr === reactorRings[2])) rr.obj.rotation.z += dt * rr.speed * (0.4 + cur.reactor) * (target.rpat === "spin" ? 2.2 : target.rpat === "still" ? 0 : 1);
      }

    }
    // draw: the figure and environment, then the floor reflection as a second pass of the same figure
    renderer.info.reset();
    if (post) post.begin(); else renderer.clear();
    renderer.render(scene, camera);
    // the head reflects ~4 units below the floor, where the reflection has faded to nothing: skip it
    const hidden = [beam, dust, data, sweep, net.g, orbits, reactor, grid, baseGlow, headPivot, thought, shed, wisps, scanRing, rebuild.points, ...envX.hidden(), ...director.hidden(), ...soleGlows, ...reactorX.hidden(), ...(shieldMesh ? [shieldMesh] : []), ...(auraMesh ? [auraMesh] : []), ...metals.map((m) => m.mesh),
      ...Object.values(aura).map((a) => a.ring), ...shafts, ...pulses.map((p) => p.m), ...eyeGlows, ...parts.pad.objs];
    const was = hidden.map((o) => o.visible);
    hidden.forEach((o) => { o.visible = false; });
    for (const m of lineMats) m.visible = false;
    figure.scale.y = -SCALE; U.uReflect.value = 1;
    if (!lean()) renderer.render(scene, camera);   // the floor reflection: skipped on Performance and Low Power
    figure.scale.y = SCALE; U.uReflect.value = 0;
    hidden.forEach((o, i) => { o.visible = was[i]; });
    for (const m of lineMats) m.visible = true;
    if (post) post.end(t, intensity);
    settling -= dt;
    if (moving || revealing || boot || confirming || camMoving || projecting && mode === "full" || settling > 0 && mode === "full") raf = requestAnimationFrame(frame);
  }
  function kick() { if (!raf && visible && !document.hidden && !lost) raf = requestAnimationFrame(frame); }

  // picking: satellites answer hover and click; the caller decides what a click means
  const ray = new THREE.Raycaster(), ndc = new THREE.Vector2();
  function pick(clientX, clientY) {
    const r = canvas.getBoundingClientRect();
    ndc.set(((clientX - r.left) / r.width) * 2 - 1, -((clientY - r.top) / r.height) * 2 + 1);
    figure.updateMatrixWorld(true);   // the reflection pass leaves the figure's matrices mirrored until the next frame
    ray.setFromCamera(ndc, camera);
    const hit = ray.intersectObjects(hitTargets, false).find((h) => h.object.parent.visible);
    if (hit) return systems[hit.object.userData.index] || null;
    const label = director.pick(ray);
    return label ? { projection: true, label, value: "" } : null;
  }

  function resize() {
    const r = wrap.getBoundingClientRect();
    if (!r.width || !r.height) return;
    renderer.setSize(r.width, r.height, false);
    if (post) { const v = renderer.getDrawingBufferSize(new THREE.Vector2()); post.size(v.x, v.y); }
    camera.aspect = r.width / r.height; camera.updateProjectionMatrix(); rig.setAspect(camera.aspect);
    kick();
  }
  const ro = new ResizeObserver(resize); ro.observe(wrap);
  const io = new IntersectionObserver((e) => { visible = e.some((x) => x.isIntersecting); if (visible) kick(); }); io.observe(wrap);
  const onVis = () => { last = 0; kick(); };
  document.addEventListener("visibilitychange", onVis);
  // GPU context loss: stop drawing and tell the page (it shows the 2D core). If the browser restores the context,
  // Three.js re-uploads everything on the next draw, so the same projection simply resumes.
  const onLost = (e) => { e.preventDefault(); lost = true; losses++; cancelAnimationFrame(raf); raf = 0; api.onLost && api.onLost(); };
  const onRestored = () => { lost = false; restores++; last = 0; settling = 2; resize(); api.onRestored && api.onRestored(); kick(); };
  canvas.addEventListener("webglcontextlost", onLost);
  canvas.addEventListener("webglcontextrestored", onRestored);

  setState(opts.state || "idle");
  tier = 0; setTier(opts.tier || 1);
  resize();

  const api = {
    setState, setPersonality, setVoice, setTier, setMode, setIntensity, setSystems, setAura, setThought, pulse, pick, setOptions, setPanels, onLost: null, onRestored: null,
    get qualityInfo() { return { setting: OPT.quality, current: quality, reason: OPT.quality === "auto" ? autoQ.reason : "your setting", log: autoQ.log.slice() }; },
    get context() { return { lost, losses, restores }; },
    showProjection(m, data) { const ok = director.show(m, data); kick(); return ok; }, closeProjection(m) { director.close(m); kick(); },
    closeProjections() { director.closeAll(); }, pinProjection(m, on) { director.pin(m, on); }, rotateProjection(dx, dy) { director.rotate(dx, dy); },
    expandProjection(m) { const ok = director.expand(m); kick(); return ok; }, collapseProjection() { director.collapse(); kick(); },
    minimizeProjection(m, on) { const ok = director.minimize(m, on); kick(); return ok; }, sideProjection(m, which) { const ok = director.side(m, which); kick(); return ok; },
    moveProjection(m, delta) { const ok = director.move(m, delta); kick(); return ok; },
    inspectProjection(m) { const w = director.where(m); const ok = !!w && rig.inspectAt(`projection:${m}`, w.at, w.scale); kick(); return ok; },
    get projections() { return director.list(); },
    // camera: inspection captures pointer input (avatar.js); views and targets only move the camera
    inspect(on) { rig.setInspecting(on); kick(); }, cameraView(name) { const ok = rig.view(name); kick(); return ok; },
    inspectTarget(name) { const ok = rig.inspectTarget(name); kick(); return ok; }, resetCamera() { rig.reset(); kick(); },
    rotateCamera(dx, dy) { rig.rotate(dx, dy); kick(); }, zoomCamera(f) { rig.zoom(f); kick(); }, panCamera(dx, dy) { rig.pan(dx, dy); kick(); },
    get camera() { return rig.state; }, VIEWS: Object.fromEntries(Object.entries(VIEWS).map(([k, v]) => [k, v.label])),
    TARGETS: Object.fromEntries(Object.entries(TARGETS).map(([k, v]) => [k, v.label])),
    get quality() { return quality; }, get options() { return { ...OPT }; },
    get modules() { return Object.entries(parts).map(([name, p]) => ({ name, tier: p.tier, on: tier >= p.tier })); },
    skipBoot() { if (boot) { boot.t = BOOT_END; kick(); } }, get booting() { return !!boot; },
    get animating() { return raf !== 0; },
    get eyes() { return { hot: FACE.uEyeHot.value, level: EYE.value, open: FACE.uEyeOpen.value, look: FACE.uEyeLook.value, scan: FACE.uEyeScan.value, speech: FACE.uSpeech.value }; }, get lost() { return lost; }, get state() { return state; },
    get personality() { return pers ? pers.name : null; }, get voice() { return +voice.toFixed(3); },
    get stats() { return { frameMs: raf && mode === "full" ? frameAvg : 0, calls: renderer.info.render.calls, triangles: renderer.info.render.triangles, camera: camera.position.toArray().map((x) => +x.toFixed(2)) }; },
    // everything this renderer made: listeners, observers, geometries, materials, textures, render targets
    dispose() {
      cancelAnimationFrame(raf); raf = 0; ro.disconnect(); io.disconnect(); document.removeEventListener("visibilitychange", onVis);
      canvas.removeEventListener("webglcontextlost", onLost); canvas.removeEventListener("webglcontextrestored", onRestored);
      director.closeAll();
      const done = new Set();
      const free = (x) => { if (x && x.dispose && !done.has(x)) { done.add(x); x.dispose(); } };
      scene.traverse((o) => {
        free(o.geometry);
        for (const m of [].concat(o.material || [])) {
          free(m);
          for (const v of Object.values(m.uniforms || {})) if (v && v.value && v.value.isTexture) free(v.value);
          for (const k of ["map", "alphaMap"]) if (m[k]) free(m[k]);
        }
      });
      if (post && post.dispose) post.dispose();
      renderer.dispose(); canvas.remove();
      return done.size;
    },
  };
  return api;
}

export const STATES = Object.keys(LOOKS);
