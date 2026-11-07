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
  unknown:       { tint: "#b89a7c", rpat: "calm", eyes: 0.35, rim: 0.8, scan: 0.6, flow: 0.1, ring: 0.05, beam: 0.4, reactor: 0.35, neural: 0.05, data: 0, sweep: 0, discharge: 0, beat: 0, head: "still", flicker: 0 },
  idle:          { tint: "#ff9a48", rpat: "calm", eyes: 0.75, rim: 1.0, scan: 1.0, flow: 0.3, ring: 0.12, beam: 0.65, reactor: 0.55, neural: 0.12, data: 0, sweep: 0, discharge: 0, beat: 0, head: "aware", flicker: 0 },
  listening:     { tint: "#ffb27a", rpat: "calm", eyes: 1.3, rim: 1.25, scan: 1.2, flow: 0.5, ring: 0.3, beam: 0.85, reactor: 0.75, neural: 0.25, data: 0, sweep: 0, discharge: 0, beat: 0, head: "attend", flicker: 0 },
  understanding: { tint: "#ffa35c", rpat: "spin", eyes: 1.0, rim: 1.2, scan: 2.6, flow: -0.8, ring: 0.45, beam: 0.85, reactor: 0.8, neural: 0.7, data: 0, sweep: 0.6, discharge: 0, beat: 0, head: "think", flicker: 0 },
  reasoning:     { tint: "#ff9d52", rpat: "spin", eyes: 1.1, rim: 1.3, scan: 1.6, flow: -1.3, ring: 0.7, beam: 0.9, reactor: 1.0, neural: 1.0, data: 0, sweep: 0.5, discharge: 0.25, beat: 0, head: "think", flicker: 0 },
  planning:      { tint: "#ff9a48", rpat: "spin", eyes: 1.0, rim: 1.25, scan: 1.8, flow: -1.0, ring: 0.9, beam: 0.9, reactor: 0.95, neural: 0.9, data: 0, sweep: 0.4, discharge: 0.2, beat: 0, head: "think", flicker: 0 },
  researching:   { tint: "#ffaf6a", rpat: "scan", eyes: 1.05, rim: 1.25, scan: 2.4, flow: 0.8, ring: 0.8, beam: 0.95, reactor: 0.9, neural: 0.6, data: 1.0, sweep: 0.9, discharge: 0, beat: 0, head: "scan", flicker: 0 },
  writing:       { tint: "#ffb27a", rpat: "beat", eyes: 1.45, rim: 1.3, scan: 1.4, flow: 1.4, ring: 0.55, beam: 1.0, reactor: 1.0, neural: 0.5, data: 0, sweep: 0, discharge: 0, beat: 0, head: "aware", flicker: 0 },
  speaking:      { tint: "#ffbe86", rpat: "beat", eyes: 1.5, rim: 1.3, scan: 1.2, flow: 1.0, ring: 0.4, beam: 0.95, reactor: 0.9, neural: 0.35, data: 0, sweep: 0, discharge: 0, beat: 0, head: "speak", flicker: 0 },
  coding:        { tint: "#ff8a38", rpat: "surge", eyes: 1.35, rim: 1.35, scan: 1.8, flow: 2.4, ring: 0.7, beam: 1.0, reactor: 1.1, neural: 0.7, data: 0, sweep: 0.3, discharge: 0.2, beat: 0, head: "think", flicker: 0 },
  verifying:     { tint: "#ffc497", rpat: "scan", eyes: 1.1, rim: 1.2, scan: 3.6, flow: 0.9, ring: 0.5, beam: 0.95, reactor: 0.9, neural: 0.5, data: 0, sweep: 1.0, discharge: 0, beat: 0, head: "scan", flicker: 0 },
  executing:     { tint: "#ff8f40", rpat: "surge", eyes: 1.2, rim: 1.35, scan: 1.8, flow: 1.8, ring: 1.2, beam: 1.05, reactor: 1.35, neural: 0.6, data: 0, sweep: 0.3, discharge: 0.55, beat: 1.8, head: "aware", flicker: 0 },
  approval:      { tint: "#ffb347", rpat: "beat", eyes: 1.05, rim: 1.3, scan: 1.0, flow: 0.4, ring: 0.2, beam: 0.85, reactor: 0.85, neural: 0.2, data: 0, sweep: 0, discharge: 0, beat: 2.8, head: "attend", flicker: 0 },
  warning:       { tint: "#ffbf6a", rpat: "scan", eyes: 0.9, rim: 1.15, scan: 1.8, flow: 0.3, ring: 0.15, beam: 0.75, reactor: 0.7, neural: 0.15, data: 0, sweep: 0.55, discharge: 0, beat: 0, head: "aware", flicker: 0 },
  completed:     { tint: "#ffd6a0", rpat: "surge", eyes: 1.8, rim: 1.7, scan: 1.0, flow: 1.0, ring: 0.6, beam: 1.2, reactor: 1.6, neural: 0.6, data: 0, sweep: 0, discharge: 0, beat: 0, head: "aware", flicker: 0 },
  error:         { tint: "#ff4b4b", rpat: "stutter", eyes: 0.55, rim: 1.1, scan: 0.8, flow: 0.0, ring: 0.0, beam: 0.45, reactor: 0.5, neural: 0.05, data: 0, sweep: 0.7, discharge: 0, beat: 0, head: "still", flicker: 0.45 },
  recovery:      { tint: "#ffb27a", rpat: "calm", eyes: 0.8, rim: 1.0, scan: 1.5, flow: 0.5, ring: 0.25, beam: 0.7, reactor: 0.6, neural: 0.3, data: 0, sweep: 0.5, discharge: 0, beat: 0, head: "aware", flicker: 0.08 },
  halted:        { tint: "#a8927a", rpat: "still", eyes: 0.4, rim: 0.85, scan: 0.4, flow: 0.0, ring: 0.0, beam: 0.35, reactor: 0.3, neural: 0.0, data: 0, sweep: 0, discharge: 0, beat: 0, head: "still", flicker: 0 },
};
const NUMERIC = ["eyes", "rim", "scan", "flow", "ring", "beam", "reactor", "neural", "data", "sweep", "discharge", "flicker"];

// ---- shaders ---------------------------------------------------------------------------------------------------
const VERT = `
uniform mat3 uHead, uArmR, uArmL, uForeR, uForeL; uniform float uHeadOn, uInflate; attribute float aAccent;
varying vec3 vNormal; varying vec3 vView; varying vec3 vWorld; varying vec2 vUv; varying vec3 vObj; varying vec3 vObjN; varying float vAccent;
void main() {
  vec3 pos = position, nrm = normal;
  if (uHeadOn > 0.5) {   // the head turns on a soft neck: vertices blend from body to head between y 4.22 and 4.42
    float w = smoothstep(4.22, 4.42, position.y); vec3 c = vec3(0.0, 4.3, 0.0);
    pos = mix(position, uHead * (position - c) + c, w); nrm = normalize(mix(normal, uHead * normal, w));
    // arms bend at the shoulder and the elbow (gestures): weights from the rest position, so seams stay attached
    float side = sign(position.x), ax = abs(position.x);
    float wU = smoothstep(0.52, 0.66, ax) * smoothstep(4.15, 3.95, position.y), wF = wU * smoothstep(3.12, 2.96, position.y);
    if (wU > 0.0) {
      mat3 Ru = side > 0.0 ? uArmR : uArmL, Rf = side > 0.0 ? uForeR : uForeL;
      vec3 S = vec3(0.66 * side, 3.92, 0.0), E = vec3(0.8 * side, 3.04, -0.03), E2 = S + Ru * (E - S);
      pos = mix(pos, S + Ru * (position - S), wU); nrm = mix(nrm, Ru * normal, wU);
      pos = mix(pos, E2 + Rf * (position - E), wF); nrm = normalize(mix(nrm, Rf * normal, wF));
    }
  }
  pos += nrm * uInflate;   // the aura shell: the same body, slightly larger
  vec4 world = modelMatrix * vec4(pos, 1.0);
  vWorld = world.xyz; vUv = uv; vObj = position; vObjN = normal; vAccent = aAccent;   // detail is fixed to the rest shape
  vNormal = normalize(normalMatrix * nrm);
  vec4 mv = viewMatrix * world;
  vView = -mv.xyz;
  gl_Position = projectionMatrix * mv;
}`;

// Holographic armour: a bright Fresnel rim over a dark gold interior; machined panel seams and fine detail lines
// (triplanar, in the part's own space, so they stay put as it moves) with energy running along them; scan lines and
// a rising light band; faces turned away drawn dimmer for depth; a materialisation edge; a fade into the projector
// beam; a floor reflection; a faint projection distortion. Shared uniforms are the same objects in every material.
const FRAG = `
uniform vec3 uTint0, uAccent; uniform float uTime, uOpacity, uRim, uRimK, uGain, uSelf, uScan, uFlow, uFlowOn, uFlicker, uReveal, uFadeLow, uReflect, uCore, uPanel, uPanelScale, uContour, uDetail, uCoreE;
varying vec3 vNormal; varying vec3 vView; varying vec3 vWorld; varying vec2 vUv; varying vec3 vObj; varying vec3 vObjN; varying float vAccent;
float hash(float n) { return fract(sin(n) * 43758.5453); }
float seam(vec2 p, float w) { vec2 g = abs(fract(p - 0.5) - 0.5) / max(fwidth(p), vec2(1e-4)); return 1.0 - min(min(g.x, g.y) / w, 1.0); }
float tri(vec3 p, vec3 wt, float w) { return seam(p.yz, w) * wt.x + seam(p.xz, w) * wt.y + seam(p.xy, w) * wt.z; }
// glowing suit contours on the figure: thin anti-aliased lines along curves fixed to the body (they turn with the head)
float L(float d, float w) { float f = fwidth(d) + 1e-4; return 1.0 - smoothstep(w, w + 1.5 * f, abs(d)); }
float win(float v, float a, float b) { return smoothstep(a - 0.03, a, v) * smoothstep(b + 0.03, b, v); }
float anat(vec3 p) {
  float ax = abs(p.x), fr = smoothstep(0.0, 0.1, p.z), bk = smoothstep(0.0, -0.1, p.z);
  float torso = 1.0 - smoothstep(0.5, 0.58, ax), arm = smoothstep(0.62, 0.7, ax), leg = (1.0 - arm) * (1.0 - smoothstep(2.35, 2.45, p.y));
  float c = L(p.x, 0.006) * fr * win(p.y, 2.8, 3.98);                                     // sternum
  c = max(c, L(p.y - (3.86 + 0.42 * ax), 0.007) * fr * win(ax, 0.05, 0.5));               // collar V
  c = max(c, L(p.y - (3.46 + 0.9 * (ax - 0.24) * (ax - 0.24)), 0.006) * fr * win(ax, 0.04, 0.48));   // chest line
  c = max(c, L(ax - (0.2 + 0.25 * (3.42 - p.y)), 0.005) * fr * win(p.y, 2.85, 3.38) * 0.7);   // flank lines
  c = max(c, L(p.y - 2.74, 0.006) * torso * (1.0 - arm));                                  // waist band
  c = max(c, L(p.y - (2.36 + 0.55 * ax), 0.006) * fr * win(ax, 0.06, 0.4));               // hip lines
  c = max(c, max(L(p.y - 3.04, 0.004), L(p.y - 2.3, 0.006)) * arm);                      // elbows, wrists
  c = max(c, max(L(p.y - 1.36, 0.007), L(p.y - 0.42, 0.007)) * leg);                     // knees, ankles
  c = max(c, L(ax - 0.25, 0.005) * fr * win(p.y, 0.5, 2.25) * leg * (1.0 - win(p.y, 1.3, 1.42)));   // leg seams
  c = max(c, L(p.x, 0.006) * bk * win(p.y, 2.7, 4.15));                                   // spine
  c = max(c, L(p.x, 0.006) * win(p.y, 4.5, 5.1) * smoothstep(0.24, 0.12, p.z));           // crest over the head
  // armour plates over the light body
  c = max(c, L(p.y - (3.97 - 0.5 * (ax - 0.64) * (ax - 0.64) * 4.0), 0.006) * smoothstep(0.5, 0.56, ax) * (1.0 - smoothstep(0.8, 0.86, ax)));   // shoulder plates
  c = max(c, max(L(p.y - 2.56, 0.004), L(p.y - 2.76, 0.004)) * arm * 0.8);                  // forearm bands
  c = max(c, max(L(p.y - 2.34, 0.004), L(p.y - 2.3, 0.006)) * arm);                         // wrist emitter (double band)
  c = max(c, L(length(vec2((ax - 0.25) / 0.13, (p.y - 1.9) / 0.38)) - 1.0, 0.03) * fr * leg * 0.7);   // thigh plates
  c = max(c, L(length(vec2((ax - 0.26) / 0.085, (p.y - 1.34) / 0.085)) - 1.0, 0.06) * fr * leg);   // knee caps
  c = max(c, L(length(vec2((ax - 0.255) / 0.08, (p.y - 0.9) / 0.32)) - 1.0, 0.04) * fr * leg * 0.7);   // shin guards
  // hands: finger grooves and knuckle points (fingers hang below y 1.99, spread along x)
  float hu = (ax - 0.9) / 0.026, hand = win(ax, 0.85, 0.95) * arm;
  c = max(c, L((hu - floor(hu + 0.5)) * 0.026, 0.0035) * hand * win(p.y, 1.84, 1.98) * step(abs(hu), 1.2));
  c = max(c, L(length(vec2((fract(hu) - 0.5) * 0.026, p.y - 2.0)) - 0.004, 0.004) * hand * step(abs(hu), 2.0) * 1.3);
  // helmet: rings around the temple pods and a line along the rear fin
  c = max(c, L(length(vec2(p.y - 4.68, p.z + 0.03)) - 0.085, 0.005) * smoothstep(0.18, 0.21, ax));
  c = max(c, L(p.y - (4.96 - 0.35 * max(-p.z, 0.0)), 0.004) * smoothstep(0.0, -0.05, p.z) * win(ax, 0.02, 0.2) * 0.7);
  return min(c, 1.0);
}
float hash2(vec2 q) { return fract(sin(dot(q, vec2(127.1, 311.7))) * 43758.5453); }
// circuit traces: per cell a straight run, a turn or a via, projected on the face of the body it is on
float circuit(vec2 q, float t, out float pulse) {
  vec2 id = floor(q), f = fract(q); float h = hash2(id), w = 0.035, c;
  float hx = 1.0 - smoothstep(w, w + 1.5 * fwidth(f.y), abs(f.y - 0.5)), vy = 1.0 - smoothstep(w, w + 1.5 * fwidth(f.x), abs(f.x - 0.5));
  if (h < 0.3) c = hx; else if (h < 0.55) c = vy;
  else if (h < 0.8) c = max(hx * step(f.x, 0.5 + w), vy * step(0.5 - w, f.y));
  else c = 0.0;
  c = max(c, (1.0 - smoothstep(0.1, 0.1 + 1.5 * fwidth(f.x), length(f - 0.5))) * step(0.55, h));   // via pads
  if (h > 0.92) c = 0.0;
  pulse = smoothstep(0.85, 1.0, sin((id.x + id.y) * 0.9 + h * 6.28 - t * 2.2));
  return c;
}
void main() {
  vec3 uTint = mix(uTint0, uAccent, vAccent);   // teal-green accents where marked (the hands)
  float h = uReflect > 0.5 ? -vWorld.y : vWorld.y;
  if (h > uReveal) discard;
  float facing = abs(dot(normalize(vNormal), normalize(vView)));
  float fres = pow(1.0 - facing, 2.2);
  float scan = mix(0.8, 1.0, 0.5 + 0.5 * sin(h * 70.0 - uTime * uScan * 5.0));
  float band = exp(-pow((fract(h * 0.16 - uTime * 0.05 * uScan) - 0.5) * 12.0, 2.0));
  float distort = 0.94 + 0.06 * sin(h * 9.0 + uTime * 2.3) * step(0.985, hash(floor(uTime * 3.0) + floor(h * 6.0)));
  vec3 deep = uTint * vec3(0.62, 0.44, 0.18);
  vec3 edgeCol = mix(uTint, vec3(1.0, 0.98, 0.94), 0.55);
  vec3 col = mix(deep * 0.5, edgeCol, pow(fres, 0.7)) + uTint * band * 0.3;
  float a = (uCore + fres * uRim * uRimK * 0.75) * scan * uOpacity + band * 0.05;
  if (uPanel > 0.0) {
    vec3 wt = abs(normalize(vObjN)); wt /= (wt.x + wt.y + wt.z + 1e-4);
    vec3 p = vObj * uPanelScale;
    float major = tri(p, wt, 1.2);
    float fine = tri(p * 3.0, wt, 0.8) * 0.35;
    float run = exp(-pow((fract(vWorld.y * 0.45 - uTime * 0.12 * (0.6 + abs(uFlow))) - 0.5) * 18.0, 2.0));
    float lines = (major + fine) * uPanel;
    col += mix(uTint * 0.9, vec3(1.0, 0.97, 0.9), run) * lines * (0.7 + 1.6 * run);
    a += lines * (0.22 + 0.5 * run) * uOpacity;
  }
  if (uContour > 0.0) {
    float c = anat(vObj) * uContour;
    float run = exp(-pow((fract(vObj.y * 0.3 - uTime * 0.18 * (0.6 + abs(uFlow))) - 0.5) * 10.0, 2.0));   // energy rising along the seams
    col += mix(mix(uTint, vec3(1.0, 0.96, 0.9), 0.35), vec3(1.0, 0.98, 0.94), run) * c * (0.65 + 1.5 * run);
    a += c * (0.28 + 0.5 * run) * uOpacity;
  }
  if (uDetail > 0.0) {
    vec3 p = vObj; vec3 n = abs(normalize(vObjN)); float ax = abs(p.x);
    float body = 1.0 - smoothstep(4.4, 4.5, p.y);   // the head stays smooth
    // circuit traces (a finer second layer from stage 3)
    vec2 q = n.z > max(n.x, n.y) ? p.xy : (n.x > n.y ? p.zy : p.xz);
    float pl, pl2; float cc = circuit(q * 13.0, uTime, pl);
    float cc2 = uDetail > 0.95 ? circuit(q * 26.0 + 7.3, uTime * 1.3, pl2) * 0.5 : 0.0;
    float circ = max(cc, cc2) * body * 1.0 * uDetail;
    col += mix(uTint * 0.7, vec3(1.0, 0.97, 0.9), pl) * circ * (0.18 + 1.1 * pl);
    a += circ * (0.05 + 0.3 * pl) * uOpacity;
    // energy veins spreading from the core over the chest, pulsing outward with the reactor
    vec2 rc = p.xy - vec2(0.0, 3.62); float r = length(rc), ang = atan(rc.y, rc.x);
    float vein = abs(sin(ang * 4.0 + sin(r * 9.0) * 0.55 + sin(r * 23.0) * 0.12));
    float vd = vein * r * 0.25;
    float veins = (1.0 - smoothstep(0.004, 0.004 + 1.5 * fwidth(vd), vd)) * smoothstep(0.3, 0.38, r) * smoothstep(1.05, 0.55, r) * smoothstep(0.05, 0.15, p.z);
    float vp = exp(-pow((fract(r * 1.4 - uTime * 0.7) - 0.5) * 7.0, 2.0));
    float ve = veins * (0.35 + 0.65 * min(uCoreE, 1.5)) * uDetail;
    col += mix(uTint, vec3(1.0, 0.98, 0.94), vp) * ve * (0.6 + 1.8 * vp);
    a += ve * (0.15 + 0.5 * vp) * uOpacity;
    // glowing soles
    float sole = smoothstep(0.16, 0.03, p.y);
    col += mix(uTint, vec3(1.0, 0.96, 0.9), 0.5) * sole * 1.2; a += sole * 0.35 * uOpacity;
  }
  if (uFlowOn > 0.5) {
    float d = fract(vUv.x * 3.0 - uTime * uFlow * 0.35);
    float pulse = smoothstep(0.0, 0.05, d) * smoothstep(0.22, 0.05, d);
    col += vec3(1.0, 0.96, 0.88) * pulse * 1.4; a = max(a, 0.28 * uOpacity) + pulse * 0.7;
  }
  float edge = smoothstep(uReveal - 0.18, uReveal, h);
  col += vec3(1.0, 0.95, 0.85) * edge * 1.6; a += edge * 0.8;
  a *= gl_FrontFacing ? 1.0 : 0.38;   // the far side of a shell is dimmer: depth instead of a flat glow
  a *= smoothstep(uFadeLow, uFadeLow + 0.9, h) * uGain * uSelf * distort;
  if (uReflect > 0.5) a *= 0.2 * smoothstep(-2.2, 0.0, vWorld.y);
  a *= 1.0 - uFlicker * step(0.55, hash(floor(uTime * 18.0))) * 0.65;
  gl_FragColor = vec4(col, clamp(a, 0.0, 1.0));
}`;

// Dark alloy armour plates: the same vertex path as the figure (they bend with the arms and head), each plate
// pushed out along its own direction by uOpen when it vents light. Graphite with a soft sheen and an orange rim
// reflection; the plate borders are glowing seams (aEdge = distance inside the plate), brighter with uSeam.
const PLATE_VERT = VERT
  .replace("uniform float uHeadOn, uInflate;", "uniform float uHeadOn, uInflate, uOpen; attribute float aEdge; attribute vec3 aOpenDir; varying float vEdge;")
  .replace("vec3 pos = position, nrm = normal;", "vec3 pos = position + aOpenDir * uOpen, nrm = normal; vEdge = aEdge;");
const PLATE_FRAG = `
uniform vec3 uTint; uniform float uTime, uGain, uReveal, uReflect, uSeam, uOpacity;
varying vec3 vNormal; varying vec3 vView; varying vec3 vWorld; varying vec3 vObj; varying float vEdge;
void main() {
  float h = uReflect > 0.5 ? -vWorld.y : vWorld.y;
  if (h > uReveal || vEdge < 0.0) discard;   // a smooth plate border
  vec3 n = normalize(vNormal), v = normalize(vView), l = normalize(vec3(-0.45, 0.65, 0.6));
  float diff = max(dot(n, l), 0.0), spec = pow(max(dot(reflect(-l, n), v), 0.0), 36.0);
  float fres = pow(1.0 - abs(dot(n, v)), 3.0);
  vec3 col = vec3(0.055, 0.05, 0.047) * (0.45 + 0.9 * diff) + vec3(1.0, 0.86, 0.7) * spec * 0.4 + uTint * fres * 0.35;
  float edge = 1.0 - smoothstep(0.004, 0.02, vEdge), inner = 1.0 - smoothstep(0.0, 0.0045, abs(vEdge - 0.05));
  float run = exp(-pow((fract(vObj.y * 0.4 - uTime * 0.25) - 0.5) * 8.0, 2.0));
  col += mix(uTint, vec3(1.0, 0.96, 0.9), 0.4) * (edge * (1.6 + 2.6 * uSeam) + inner * 0.5 * (0.4 + uSeam)) * (1.0 + run * uSeam);
  float a = mix(0.9, 1.0, edge) * uOpacity * min(uGain, 1.0);
  if (uReveal < 9.0) col += vec3(1.0, 0.95, 0.85) * smoothstep(uReveal - 0.18, uReveal, h) * 1.4;
  gl_FragColor = vec4(col, a);
}`;
// The alert shield: a hexagon energy field just outside the body, flaring only on a real error or warning.
const SHIELD_FRAG = `
uniform vec3 uTint; uniform float uTime, uGain, uShield;
varying vec3 vNormal; varying vec3 vView; varying vec3 vObj; varying vec3 vObjN;
float hexd(vec2 p) { p = abs(p); return max(dot(p, vec2(0.5, 0.866)), p.x); }
void main() {
  vec3 nn = abs(normalize(vObjN));
  vec2 q = (nn.z > max(nn.x, nn.y) ? vObj.xy : (nn.x > nn.y ? vObj.zy : vObj.xz)) * 7.0;
  const vec2 sz = vec2(1.0, 1.732);
  vec2 a = mod(q, sz) - sz * 0.5, b = mod(q - sz * 0.5, sz) - sz * 0.5, g = dot(a, a) < dot(b, b) ? a : b;
  float e = hexd(g), line = 1.0 - smoothstep(0.42, 0.42 + 1.5 * fwidth(e), e);
  float fres = pow(1.0 - abs(dot(normalize(vNormal), normalize(vView))), 2.0);
  float sweep = exp(-pow((fract(vObj.y * 0.25 - uTime * 0.5) - 0.5) * 6.0, 2.0));
  float aa = ((1.0 - line) * (0.5 + sweep) + fres * 0.4) * uShield * uGain;
  gl_FragColor = vec4(mix(uTint, vec3(1.0, 0.95, 0.9), 0.4), clamp(aa, 0.0, 1.0) * 0.6);
}`;

// ---- post-processing: bloom (bright edges and cores glow), a slight lens fringe and fine grain ------------------
const QUAD_VERT = `varying vec2 vUv; void main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }`;
const BRIGHT_FRAG = `uniform sampler2D tSrc; uniform float uThr; varying vec2 vUv;
void main() { vec4 c = texture2D(tSrc, vUv); float l = max(c.r, max(c.g, c.b));
  gl_FragColor = vec4(c.rgb * smoothstep(uThr, uThr + 0.4, l), 1.0); }`;
const BLUR_FRAG = `uniform sampler2D tSrc; uniform vec2 uDir; varying vec2 vUv;
void main() { vec3 s = texture2D(tSrc, vUv).rgb * 0.227;
  s += (texture2D(tSrc, vUv + uDir * 1.385).rgb + texture2D(tSrc, vUv - uDir * 1.385).rgb) * 0.316;
  s += (texture2D(tSrc, vUv + uDir * 3.231).rgb + texture2D(tSrc, vUv - uDir * 3.231).rgb) * 0.070;
  gl_FragColor = vec4(s, 1.0); }`;
const COMPOSITE_FRAG = `uniform sampler2D tScene, tB1, tB2; uniform float uB1, uB2, uCA, uTime; uniform vec2 uRes; varying vec2 vUv;
float hash(vec2 p) { return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453); }
void main() {
  vec2 off = (vUv - 0.5) * uCA;
  vec4 s = texture2D(tScene, vUv);
  vec3 col = vec3(texture2D(tScene, vUv + off).r, s.g, texture2D(tScene, vUv - off).b);
  col += texture2D(tB1, vUv).rgb * uB1 + texture2D(tB2, vUv).rgb * uB2;
  col = col / (1.0 + max(col - 0.8, 0.0) * 0.9);   // soft roll-off: bright highlights stay golden instead of clipping
  col += (hash(vUv * uRes + uTime) - 0.5) * 0.02 * col;
  float a = clamp(max(s.a, max(col.r, max(col.g, col.b))), 0.0, 1.0);
  gl_FragColor = vec4(min(col, vec3(a)), a);
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
const TORSO = [V2(0.92, 0.45), V2(1.0, 1.0), V2(1.2, 1.55), V2(1.42, 2.05), V2(1.5, 2.35), V2(1.42, 2.58), V2(1.12, 2.76),
               V2(0.64, 2.88), V2(0.34, 2.93)];
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
function mergeGeos(geos) {   // one draw call for many tubes (position, normal, uv, index)
  let nv = 0, ni = 0; for (const g of geos) { nv += g.attributes.position.count; ni += g.index.count; }
  const pos = new Float32Array(nv * 3), nrm = new Float32Array(nv * 3), uv = new Float32Array(nv * 2), idx = new Uint32Array(ni);
  let ov = 0, oi = 0;
  for (const g of geos) {
    pos.set(g.attributes.position.array, ov * 3); nrm.set(g.attributes.normal.array, ov * 3); uv.set(g.attributes.uv.array, ov * 2);
    const ix = g.index.array; for (let i = 0; i < ix.length; i++) idx[oi + i] = ix[i] + ov;
    ov += g.attributes.position.count; oi += ix.length; g.dispose();
  }
  const out = new THREE.BufferGeometry();
  out.setAttribute("position", new THREE.BufferAttribute(pos, 3)); out.setAttribute("normal", new THREE.BufferAttribute(nrm, 3));
  out.setAttribute("uv", new THREE.BufferAttribute(uv, 2)); out.setIndex(new THREE.BufferAttribute(idx, 1));
  return out;
}
function rng(seed) { let s = seed >>> 0; return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296); }

// ---- the figure: a sleek humanoid sculpted as a blended distance field, meshed once with surface nets ------------
// Original, made in code (no downloaded model). Units: feet at y ≈ 0, top of the head at y ≈ 5.07, facing +z.
const smin = (a, b, k) => { const h = Math.max(k - Math.abs(a - b), 0) / k; return Math.min(a, b) - h * h * k * 0.25; };
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
export function sdHuman(x, y, z) {
  const ax = Math.abs(x);   // symmetric
  let d = sdEll(x, y, z, 0, 4.75, 0.0, 0.235, 0.32, 0.28);                                   // cranium
  d = smin(d, sdEll(x, y, z, 0, 4.8, -0.07, 0.22, 0.27, 0.26), 0.1);                         // swept-back crown
  d = smin(d, sdEll(x, y, z, 0, 4.54, 0.07, 0.16, 0.18, 0.19), 0.12);                        // lower head (smooth, faceless)
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
export function meshFigure(h = 0.03) {
  const [x0, y0, z0] = [-1.12, -0.05, -0.48], [x1, y1, z1] = [1.12, 5.15, 0.48];
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
  camera.position.set(0, 2.85, 11.5);
  camera.lookAt(0, 2.68, 0);

  // ---- shared uniforms: one update per frame drives every hologram material ------------------------------------
  const U = { uHead: { value: new THREE.Matrix3() }, uArmR: { value: new THREE.Matrix3() }, uArmL: { value: new THREE.Matrix3() },
              uForeR: { value: new THREE.Matrix3() }, uForeL: { value: new THREE.Matrix3() }, uAccent: { value: new THREE.Color("#3dffb8") },
              uTime: { value: 0 }, uTint: { value: CHAMPAGNE.clone() }, uRimK: { value: 1 }, uGain: { value: 1 },
              uScan: { value: 1 }, uFlow: { value: 0.3 }, uFlicker: { value: 0 }, uReflect: { value: 0 } };
  const EYE = { value: 1 }, REACTOR = { value: 1 };
  const lineMats = [];
  const parts = {};
  let building = null;   // the part whose meshes are being built (for its reveal uniform and visibility)

  function holo(o = {}) {
    const m = new THREE.ShaderMaterial({
      vertexShader: VERT, fragmentShader: FRAG, transparent: true, depthWrite: false, side: THREE.DoubleSide,
      blending: THREE.AdditiveBlending,
      uniforms: { ...U, uTint0: U.uTint, uHeadOn: { value: o.head ? 1 : 0 }, uOpacity: { value: o.opacity ?? 0.9 }, uRim: { value: o.rim ?? 1 }, uFlowOn: { value: o.flow ? 1 : 0 },
                  uCore: { value: o.core ?? 0.035 }, uFadeLow: { value: o.fadeLow ?? -10 }, uSelf: o.self || { value: 1 },
                  uReveal: building ? building.reveal : { value: 10 },
                  // armour surfaces (low inner glow, no energy flow) get machined panel seams unless told otherwise
                  uPanel: { value: o.panel ?? ((o.core ?? 0.035) < 0.2 && !o.flow && !o.self ? 0.85 : 0) },
                  uPanelScale: { value: o.panelScale ?? 6 }, uContour: { value: o.contour ?? 0 }, uDetail: { value: o.detail ?? 0 }, uCoreE: REACTOR,
                  uInflate: { value: o.inflate ?? 0 } },
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
    for (const [r, arc, start, c, o] of [[2.35, 2.4, 3.6, "#ff8a3a", 0.85], [2.55, 1.9, 4.9, "#33e6ad", 0.7], [2.2, 1.2, 0.5, "#33e6ad", 0.45]]) {
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
  const figureGeo = meshFigure(phone ? 0.04 : 0.03);
  const joints = [], eyeGlows = [], irises = [], sparks = [];
  let figureMat = null, auraMat = null;
  part("figure", 1, (add) => {
    figureMat = holo({ opacity: 1.0, rim: 1.6, core: 0.1, panel: 0.35, panelScale: 7, contour: 1, detail: 0.75, head: true });
    add(new THREE.Mesh(figureGeo, figureMat));
    if (!phone) {   // a soft outline glow around the whole figure
      auraMat = holo({ opacity: 0.3, rim: 1.3, core: 0.0, panel: 0, inflate: 0.035, head: true });
      add(new THREE.Mesh(figureGeo, auraMat));
    }
  });
  const shed = (() => {   // sparkles leaving the surface, drifting up and out
    const src = figureGeo.attributes.position.array, nsrc = figureGeo.attributes.normal.array, acc = figureGeo.attributes.aAccent.array;
    const N = phone ? 600 : 1600, P = new Float32Array(N * 3), Nn = new Float32Array(N * 3), seed = new Float32Array(N), ac = new Float32Array(N);
    const r = rng(23);
    for (let i = 0; i < N; i++) { const q = Math.floor(r() * (src.length / 3));
      P.set([src[q * 3], src[q * 3 + 1], src[q * 3 + 2]], i * 3); Nn.set([nsrc[q * 3], nsrc[q * 3 + 1], nsrc[q * 3 + 2]], i * 3);
      seed[i] = r(); ac[i] = Math.max(acc[q], r() < 0.14 ? 1 : 0); }
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
    paths.push([V(0, 2.55, -0.1), V(0, 3.0, -0.12), V(0, 3.6, -0.1), V(0, 4.15, -0.06), V(0, 4.42, -0.02)]);   // spine
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

  // Alloy armour: key plates cut from the figure's own surface (so they hug the sleek body), lifted slightly off it.
  // m(p) > 0 inside a plate; its value near the border feeds the glowing seam.
  const metals = [];
  const PLATES = [
    { name: "chest", order: 0, dir: [0, 0.1, 1], m: (x, y, z) => { const ax = Math.abs(x);
      return Math.min(y - (3.4 + 0.9 * (ax - 0.22) ** 2), (3.83 + 0.4 * ax) - y, 0.47 - 0.6 * (y - 3.68) ** 2 - ax, z - 0.04,
        ax - 0.028, Math.hypot(x, y - 3.62) - 0.21); } },                                      // two pectoral plates around the core
    { name: "abdomen", order: 0.12, dir: [0, -0.2, 1], m: (x, y, z) => { const ax = Math.abs(x);
      return Math.min(y - 2.82, 3.3 - 0.4 * ax - y, 0.2 - 0.25 * (3.06 - y) ** 2 - ax, z - 0.08, Math.abs(y - 3.06) > 0.012 ? 1 : -1); } },
    ...[1, -1].map((sg) => ({ name: "shoulder", order: 0.25, dir: [sg, 0.7, 0], m: (x, y, z) => sg * x <= 0 ? -1
        : Math.min(0.27 - Math.hypot(Math.abs(x) - 0.66, (y - 3.93) * 0.9, z), y - (3.7 + 0.25 * Math.abs(z)), Math.abs(x) - 0.5) })),
    ...[1, -1].map((sg) => ({ name: "forearm", order: 0.45, dir: [sg, 0, 0.3], m: (x, y, z) => sg * x <= 0 ? -1
        : Math.min(y - 2.42, 2.94 - y - 0.8 * Math.abs(z), Math.abs(x) - (0.79 + 0.08 * (3.04 - y)) + 0.05) })),
    ...[1, -1].map((sg) => ({ name: "shin", order: 0.65, dir: [0, 0, 1], m: (x, y, z) => { const ax = Math.abs(x);
      return sg * x <= 0 ? -1 : Math.min(y - 0.52, 1.26 - y - 1.3 * Math.abs(ax - 0.255), z - 0.0, (0.1 - 0.04 * (1.2 - y)) - Math.abs(ax - 0.255)); } })),
    { name: "helmet", order: 0.85, dir: [0, 0.4, -1], m: (x, y, z) => Math.min(y - 4.47, y - (4.8 - 1.2 * (0.1 - z))) },   // crown, sides and back; face open
  ];
  const plateUni = { uOpen: { value: 0 }, uSeam: { value: 0.25 } };
  part("armour", 1, (add, reveal) => {
    const P = figureGeo.attributes.position.array, N = figureGeo.attributes.normal.array, I = figureGeo.index.array;
    for (const pl of PLATES) {
      const nv = P.length / 3, mv = new Float32Array(nv);
      for (let q = 0; q < nv; q++) mv[q] = pl.m(P[q * 3], P[q * 3 + 1], P[q * 3 + 2]);
      const remap = new Int32Array(nv).fill(-1), pos = [], nrm = [], edge = [], idx = [];
      const lift = pl.name === "helmet" ? 0.022 : 0.03;
      for (let t = 0; t < I.length; t += 3) {
        const a = I[t], b = I[t + 1], c = I[t + 2];
        if (mv[a] <= 0 && mv[b] <= 0 && mv[c] <= 0) continue;   // border triangles are kept and trimmed smoothly in the shader
        for (const v of [a, b, c]) {
          if (remap[v] < 0) { remap[v] = pos.length / 3;
            pos.push(P[v * 3] + N[v * 3] * lift, P[v * 3 + 1] + N[v * 3 + 1] * lift, P[v * 3 + 2] + N[v * 3 + 2] * lift);
            nrm.push(N[v * 3], N[v * 3 + 1], N[v * 3 + 2]); edge.push(Math.max(mv[v], -0.04)); }
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
      g.setIndex(idx);
      const mat = new THREE.ShaderMaterial({ vertexShader: PLATE_VERT, fragmentShader: PLATE_FRAG, transparent: true, depthWrite: true,
        uniforms: { ...U, uHeadOn: { value: 1 }, uInflate: { value: 0 }, uReveal: reveal, uOpacity: { value: 1 }, ...plateUni },
        extensions: { derivatives: true } });
      const mesh = add(new THREE.Mesh(g, mat)); mesh.renderOrder = 5;   // drawn over the light body: it shows in the gaps
      metals.push({ mesh, order: pl.order, dir: d });
    }
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
    if (s === "error" || s === "warning") shieldFlare = 2.5;   // the shield flares on a real alert
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
  const BOOT_END = 4.3;
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
  };
  const POSE_OF = { speaking: "present", coding: "work", executing: "work", approval: "raise", completed: "open" };
  const armCur = { r: [0.02, 0.08, 0.02], l: [0.02, 0.08, 0.02] };
  const _e = new THREE.Euler(), _m4 = new THREE.Matrix4(), _m4b = new THREE.Matrix4();
  function armPose(k) {
    const pose = POSES[POSE_OF[state] || "rest"], work = POSE_OF[state] === "work" && mode === "full";
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
    armPose(k);
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
    if (innerMat) innerMat.uniforms.uOpacity.value = 0.12 + cur.neural * 0.5 + flash * 0.3;   // the inner network brightens while thinking
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
    if (boot) bootStep(dt);
    const bootDim = boot ? Math.min(1, Math.max(0, (boot.t - 3.2) / 0.5)) : 1;   // the reactor ignites last
    REACTOR.value *= boot ? 0.08 + 0.92 * bootDim : 1;
    beamMat.uniforms.uBeam.value *= boot ? Math.min(1, boot.t / 0.8) : 1;
    if (figureMat) {   // finer detail and brighter seams light up with each stage
      figureMat.uniforms.uPanel.value = [0.25, 0.35, 0.45, 0.55][tier - 1] || 0.35;
      figureMat.uniforms.uContour.value = [0.75, 0.9, 1.05, 1.2][tier - 1] || 0.9;
      figureMat.uniforms.uDetail.value = [0.75, 0.85, 1.0, 1.15][tier - 1] || 0.75;   // rich now, maximum at stage 4 (finer circuits from stage 3)
      if (auraMat) auraMat.uniforms.uOpacity.value = [0.3, 0.36, 0.42, 0.5][tier - 1] || 0.3;
    }
    shed.visible = moving; wisps.visible = moving;
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
      reactor.scale.setScalar(REACTOR_SIZE * beatK);
      if (rp === "scan") reactorRings[2] && (reactorRings[2].obj.rotation.z = Math.sin(t * 1.4) * 1.6);
      headMotion();
      for (const ax of ["x", "y", "z"]) headCur[ax] += (headTarget[ax] - headCur[ax]) * (1 - Math.exp(-dt * 2.5));
      headPivot.rotation.copy(headCur);
      U.uHead.value.setFromMatrix4(new THREE.Matrix4().makeRotationFromEuler(headCur));   // turns the figure's head
      shed.material.uniforms.uRate.value = 0.8 + Math.abs(cur.flow) * 0.4 + flash * 3;
      wisps.material.uniforms.uRate.value = 0.8 + cur.neural * 0.8 + flash * 2;
      orbitRings.forEach((r) => { r.rotation.z += dt * (0.05 + cur.ring) * r.userData.spin; });
      for (const s of spinners) s.obj.rotation[s.axis] += dt * s.speed * (0.5 + cur.ring);
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
    const hidden = [beam, dust, data, sweep, net.g, orbits, reactor, grid, baseGlow, headPivot, thought, shed, wisps, ...soleGlows, ...(shieldMesh ? [shieldMesh] : []), ...metals.map((m) => m.mesh),
      ...Object.values(aura).map((a) => a.ring), ...shafts, ...pulses.map((p) => p.m), ...eyeGlows, ...parts.pad.objs];
    const was = hidden.map((o) => o.visible);
    hidden.forEach((o) => { o.visible = false; });
    for (const m of lineMats) m.visible = false;
    figure.scale.y = -SCALE; U.uReflect.value = 1;
    renderer.render(scene, camera);
    figure.scale.y = SCALE; U.uReflect.value = 0;
    hidden.forEach((o, i) => { o.visible = was[i]; });
    for (const m of lineMats) m.visible = true;
    if (post) post.end(t, intensity);
    settling -= dt;
    if (moving || revealing || boot || settling > 0 && mode === "full") raf = requestAnimationFrame(frame);
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
    if (post) { const v = renderer.getDrawingBufferSize(new THREE.Vector2()); post.size(v.x, v.y); }
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
    setState, setTier, setMode, setIntensity, setSystems, setAura, setThought, pulse, pick, onLost: null,
    skipBoot() { if (boot) { boot.t = BOOT_END; kick(); } }, get booting() { return !!boot; },
    get animating() { return raf !== 0; }, get lost() { return lost; }, get state() { return state; },
    get stats() { return { calls: renderer.info.render.calls, triangles: renderer.info.render.triangles }; },
    dispose() { cancelAnimationFrame(raf); ro.disconnect(); io.disconnect(); document.removeEventListener("visibilitychange", onVis);
      renderer.dispose(); canvas.remove(); },
  };
  return api;
}

export const STATES = Object.keys(LOOKS);
