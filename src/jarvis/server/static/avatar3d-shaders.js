// JARVIS avatar: the shaders (GLSL source strings) shared by the 3D renderer's modules. No logic, no state.
// ---- shaders ---------------------------------------------------------------------------------------------------
export const VERT = `
uniform mat3 uHead, uArmR, uArmL, uForeR, uForeL; uniform float uHeadOn, uInflate; attribute float aAccent;
varying vec3 vNormal; varying vec3 vView; varying vec3 vWorld; varying vec2 vUv; varying vec3 vObj; varying vec3 vObjN; varying float vAccent;
/*DECL*/
void main() {
  vec3 pos = position, nrm = normal;
  /*PRE*/
  if (uHeadOn > 0.5) {
    // local changes (plates venting, fingers flexing) are made above; the joints below carry them along
    vec3 p0 = pos, n0 = nrm;
    // the head turns on a soft neck: vertices blend from body to head between y 4.22 and 4.42
    float w = smoothstep(4.22, 4.42, position.y); vec3 c = vec3(0.0, 4.3, 0.0);
    pos = mix(p0, uHead * (p0 - c) + c, w); nrm = normalize(mix(n0, uHead * n0, w));
    // arms bend at the shoulder and the elbow (gestures): weights from the rest position, so seams stay attached
    float side = sign(position.x), ax = abs(position.x);
    float wU = smoothstep(0.52, 0.66, ax) * smoothstep(4.15, 3.95, position.y), wF = wU * smoothstep(3.12, 2.96, position.y);
    if (wU > 0.0) {
      mat3 Ru = side > 0.0 ? uArmR : uArmL, Rf = side > 0.0 ? uForeR : uForeL;
      vec3 S = vec3(0.66 * side, 3.92, 0.0), E = vec3(0.8 * side, 3.04, -0.03), E2 = S + Ru * (E - S);
      pos = mix(pos, S + Ru * (p0 - S), wU); nrm = mix(nrm, Ru * n0, wU);
      pos = mix(pos, E2 + Rf * (p0 - E), wF); nrm = normalize(mix(nrm, Rf * n0, wF));
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
export const FRAG = `
uniform vec3 uTint0, uAccent; uniform float uTime, uOpacity, uRim, uRimK, uGain, uSelf, uScan, uFlow, uFlowOn, uFlicker, uReveal, uFadeLow, uReflect, uCore, uPanel, uPanelScale, uContour, uDetail, uCoreE, uEye, uEyeOpen, uEyeLook, uEyeScan, uSpeech, uEyeHot, uThink;
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
  c = max(c, L(p.x, 0.006) * win(p.y, 4.5, 5.1) * smoothstep(0.12, 0.02, p.z));           // crest over the head (not the face)
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
  vec3 uTint = mix(uTint0, uAccent, vAccent);   // gold-white highlight where marked (the hands)
  float h = uReflect > 0.5 ? -vWorld.y : vWorld.y;
  if (h > uReveal) discard;
  float facing = abs(dot(normalize(vNormal), normalize(vView)));
  float fres = pow(1.0 - facing, 2.2);
  // on the face, outlines around small features read as cartoon rings: soften the rim there and light the form instead
  float faceZone = uDetail > 0.0 ? smoothstep(4.34, 4.44, vObj.y) * smoothstep(4.97, 4.88, vObj.y) * smoothstep(0.08, 0.18, vObj.z) : 0.0;
  fres *= 1.0 - 0.7 * faceZone;
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
    float lines = (major + fine) * uPanel * (1.0 - faceZone);   // no panel grid across the face
    col += mix(uTint * 0.9, vec3(1.0, 0.97, 0.9), run) * lines * (0.7 + 1.6 * run);
    a += lines * (0.22 + 0.5 * run) * uOpacity;
  }
  if (uContour > 0.0) {
    float c = anat(vObj) * uContour * (gl_FrontFacing ? 1.0 : 0.15);   // seams on the far side barely show through
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
    // the helmet's optical system (faceless): a sensor array in the visor band, an internal scanner sweeping behind
    // it, and the whole visor glowing faintly. Levels come from the real state (uEye), the shutter from blinks
    // and narrowing (uEyeOpen), the scanner from researching / verifying (uEyeScan), the pattern from thinking.
    float facem = smoothstep(4.4, 4.45, p.y) * smoothstep(4.95, 4.85, p.y) * smoothstep(0.12, 0.22, p.z);
    float vis = smoothstep(0.03, 0.022, abs(p.y - 4.735)) * smoothstep(0.08, 0.16, p.z);   // the visor band
    float headm = smoothstep(4.36, 4.46, p.y);   // soft key light from upper left on the head: the shell reads as a form
    float key = dot(normalize(vObjN), normalize(vec3(-0.3, 0.35, 0.88))) * 0.5 + 0.5;   // wrap light: soft, no black pockets
    col *= mix(1.0, 0.7 + 0.5 * key, headm * 0.8);
    col += mix(uTint, vec3(1.0, 0.95, 0.88), 0.3) * faceZone * (0.32 + 0.5 * pow(key, 3.0)); a += faceZone * (0.24 + 0.25 * pow(key, 3.0)) * uOpacity;   // even fill: no dark pockets where the shell meets the view head-on
    float lvl = min(uEye, 2.0) * max(uEyeOpen, 0.08);
    float sens = 0.0;
    for (int i = -4; i <= 4; i++) {
      float sx = float(i) * 0.034 + uEyeLook, ph = sin(uTime * 4.0 + float(i) * 1.7);
      float on = (abs(float(i)) <= 2.0 ? 1.0 : 0.55) * (0.65 + 0.35 * ph * clamp(uThink, 0.0, 1.0));   // thinking: the array works
      vec2 q2 = vec2((p.x - sx) / 0.0075, (p.y - 4.735) / 0.0065);
      sens += exp(-dot(q2, q2)) * on;
    }
    sens *= vis * lvl * step(0.02, uEyeOpen);
    float scanx = sin(uTime * 2.4) * 0.14 + uEyeLook;
    float escan = exp(-pow((p.x - scanx) / 0.016, 2.0)) * vis * uEyeScan;   // the internal scanner behind the visor
    vec3 hot = mix(uTint, vec3(1.0, 0.98, 0.95), 0.55 * uEyeHot);
    col += hot * (sens * 2.4 + escan * 2.0) + uTint * vis * lvl * 0.25 + uTint * facem * uSpeech * 0.45;
    a += (sens * 0.75 + escan * 0.55 + vis * lvl * 0.12 + facem * uSpeech * 0.15) * uOpacity;
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
export const PLATE_VERT = VERT
  .replace("/*DECL*/", "uniform float uOpen; attribute float aEdge; attribute vec3 aOpenDir; varying float vEdge;")
  .replace("/*PRE*/", "pos += aOpenDir * uOpen; vEdge = aEdge;");
// Hands: fingers flex around their knuckles (aFing: finger 0-3, thumb 4, -1 palm; aSeg: 0 at the knuckle -> 1 at
// the tip). The fingers curl toward the palm (the inner side, toward the body).
export const HAND_DECL = "uniform float uCurl, uFlex, uTime; attribute float aFing; attribute float aSeg; attribute vec3 aKnuck;";
export const HAND_PRE = `if (aFing >= 0.0) {
    float s = sign(position.x), th = (uCurl + sin(uTime * 0.7 + aFing * 1.3) * uFlex) * aSeg * (aFing > 3.5 ? 0.5 : 1.0);
    float c = cos(-th * s), sn = sin(-th * s); vec2 r = pos.xy - aKnuck.xy;
    pos.xy = aKnuck.xy + vec2(c * r.x - sn * r.y, sn * r.x + c * r.y);
    nrm.xy = vec2(c * nrm.x - sn * nrm.y, sn * nrm.x + c * nrm.y);
  }
  {   // a relaxed hand turns about 55 degrees at the wrist: the back of the hand and the fingers face forward
    float s = sign(position.x), a = -0.95 * s, ca = cos(a), sa = sin(a);
    vec2 w = vec2(0.884 * s, 0.05), r = pos.xz - w;
    pos.xz = w + vec2(ca * r.x + sa * r.y, -sa * r.x + ca * r.y);
    nrm.xz = vec2(ca * nrm.x + sa * nrm.z, -sa * nrm.x + ca * nrm.z);
  }`;
export const HAND_VERT = VERT.replace("/*DECL*/", HAND_DECL).replace("/*PRE*/", HAND_PRE);
// plates on the hands: they flex with the fingers and vent like the others
export const HAND_PLATE_VERT = VERT
  .replace("/*DECL*/", "uniform float uOpen; attribute float aEdge; attribute vec3 aOpenDir; varying float vEdge; " + HAND_DECL)
  .replace("/*PRE*/", HAND_PRE + " pos += aOpenDir * uOpen; vEdge = aEdge;");
export const PLATE_FRAG = `
uniform vec3 uTint; uniform float uTime, uGain, uReveal, uReflect, uSeam, uOpacity;
varying vec3 vNormal; varying vec3 vView; varying vec3 vWorld; varying vec3 vObj; varying vec3 vObjN; varying float vEdge;
void main() {
  float h = uReflect > 0.5 ? -vWorld.y : vWorld.y;
  if (h > uReveal || vEdge < 0.0) discard;   // a smooth plate border
  vec3 n = normalize(vNormal), v = normalize(vView), l = normalize(vec3(-0.45, 0.65, 0.6));
  float diff = max(dot(n, l), 0.0), spec = pow(max(dot(reflect(-l, n), v), 0.0), 36.0);
  float fres = pow(1.0 - abs(dot(n, v)), 3.0);
  vec3 col = vec3(0.055, 0.05, 0.047) * (0.45 + 0.9 * diff) + vec3(1.0, 0.86, 0.7) * spec * 0.4 + uTint * fres * 0.35;
  float edge = 1.0 - smoothstep(0.004, 0.02, vEdge), inner = 1.0 - smoothstep(0.0, 0.0045, abs(vEdge - 0.05));
  float run = exp(-pow((fract(vObj.y * 0.4 - uTime * 0.25) - 0.5) * 8.0, 2.0));
  vec3 an = abs(normalize(vObjN)); vec2 mq = (an.z > max(an.x, an.y) ? vObj.xy : (an.x > an.y ? vObj.zy : vObj.xz)) * 22.0;
  vec2 mg = abs(fract(mq) - 0.5) / max(fwidth(mq), vec2(1e-4));
  float micro = (1.0 - min(min(mg.x, mg.y), 1.0)) * smoothstep(0.06, 0.1, vEdge) * 0.22;           // engraved micro-panels
  float pin = (1.0 - smoothstep(0.08, 0.14, length(fract(mq * 0.5) - 0.5))) * step(0.82, fract(sin(dot(floor(mq * 0.5), vec2(12.9, 78.2))) * 43758.5)) * smoothstep(0.07, 0.12, vEdge);
  col += uTint * (micro * (0.4 + uSeam) + pin * (0.8 + 1.2 * uSeam));
  col += mix(uTint, vec3(1.0, 0.96, 0.9), 0.4) * (edge * (1.6 + 2.6 * uSeam) + inner * 0.5 * (0.4 + uSeam)) * (1.0 + run * uSeam);
  float a = mix(0.9, 1.0, edge) * uOpacity * min(uGain, 1.0);
  if (uReveal < 9.0) col += vec3(1.0, 0.95, 0.85) * smoothstep(uReveal - 0.18, uReveal, h) * 1.4;
  gl_FragColor = vec4(col, a);
}`;
// The alert shield: a hexagon energy field just outside the body, flaring only on a real error or warning.
export const SHIELD_FRAG = `
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
  float face = smoothstep(4.36, 4.46, vObj.y) * smoothstep(0.02, 0.14, vObj.z);   // the shield never covers the face
  float aa = ((1.0 - line) * (0.5 + sweep) + fres * 0.4) * uShield * uGain * (1.0 - face);
  gl_FragColor = vec4(mix(uTint, vec3(1.0, 0.95, 0.9), 0.4), clamp(aa, 0.0, 1.0) * 0.4);
}`;

// ---- post-processing: bloom (bright edges and cores glow), a slight lens fringe and fine grain ------------------
export const QUAD_VERT = `varying vec2 vUv; void main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }`;
export const BRIGHT_FRAG = `uniform sampler2D tSrc; uniform float uThr; varying vec2 vUv;
void main() { vec4 c = texture2D(tSrc, vUv); float l = max(c.r, max(c.g, c.b));
  gl_FragColor = vec4(c.rgb * smoothstep(uThr, uThr + 0.4, l), 1.0); }`;
export const BLUR_FRAG = `uniform sampler2D tSrc; uniform vec2 uDir; varying vec2 vUv;
void main() { vec3 s = texture2D(tSrc, vUv).rgb * 0.227;
  s += (texture2D(tSrc, vUv + uDir * 1.385).rgb + texture2D(tSrc, vUv - uDir * 1.385).rgb) * 0.316;
  s += (texture2D(tSrc, vUv + uDir * 3.231).rgb + texture2D(tSrc, vUv - uDir * 3.231).rgb) * 0.070;
  gl_FragColor = vec4(s, 1.0); }`;
export const COMPOSITE_FRAG = `uniform sampler2D tScene, tB1, tB2; uniform float uB1, uB2, uCA, uTime; uniform vec2 uRes; varying vec2 vUv;
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

export const BEAM_VERT = `
varying vec2 vUv; varying vec3 vNormal; varying vec3 vView;
void main() { vUv = uv; vNormal = normalize(normalMatrix * normal); vec4 mv = modelViewMatrix * vec4(position, 1.0);
  vView = -mv.xyz; gl_Position = projectionMatrix * mv; }`;
export const BEAM_FRAG = `
uniform vec3 uTint; uniform float uTime, uBeam;
varying vec2 vUv; varying vec3 vNormal; varying vec3 vView;
void main() {
  float up = vUv.y;
  float streak = 0.65 + 0.35 * sin(vUv.x * 62.83 * 3.0 + uTime * 0.7) * sin(vUv.x * 62.83 * 7.0 - uTime * 0.4);
  float side = pow(abs(dot(normalize(vNormal), normalize(vView))), 1.5);
  gl_FragColor = vec4(uTint * 1.1, (1.0 - up) * (1.0 - up) * 0.22 * streak * side * uBeam);
}`;

// rising dust in the beam
export const DUST_VERT = `
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
export const DOT_FRAG = `
uniform vec3 uTint; varying float vA;
void main() { float d = length(gl_PointCoord - 0.5); if (d > 0.5) discard; gl_FragColor = vec4(uTint, vA * smoothstep(0.5, 0.0, d)); }`;

// neural lattice: links light up with pulses travelling along them; links above the current stage stay dark
export const NET_VERT = `
attribute float aT; attribute float aPhase; attribute float aStage; varying float vT; varying float vPhase; varying float vOn;
uniform float uStage;
void main() { vT = aT; vPhase = aPhase; vOn = step(aStage, uStage + 0.5);
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`;
export const NET_FRAG = `
uniform vec3 uTint; uniform float uTime, uNeural, uGain; varying float vT; varying float vPhase; varying float vOn;
void main() {
  float p = exp(-pow((fract(vT - uTime * (0.25 + uNeural * 0.5) + vPhase) - 0.5) * 16.0, 2.0));
  float a = (0.04 + 0.05 * uNeural + p * 0.75 * uNeural) * vOn * uGain;
  gl_FragColor = vec4(mix(uTint, vec3(1.0, 0.97, 0.9), p), a);
}`;
export const NODE_VERT = `
attribute float aStage; attribute float aSeed; uniform float uStage, uTime, uNeural, uSize; varying float vA;
void main() { vA = step(aStage, uStage + 0.5) * (0.3 + 0.7 * uNeural) * (0.6 + 0.4 * sin(uTime * 2.0 + aSeed * 30.0));
  vec4 mv = modelViewMatrix * vec4(position, 1.0); gl_PointSize = uSize * (8.0 / -mv.z); gl_Position = projectionMatrix * mv; }`;

// research data streams: short dashes falling in columns around the projection
export const DATA_VERT = `
attribute float aSeed; attribute float aCol; uniform float uTime, uData, uSize; varying float vA;
void main() {
  float ang = -2.5 + aCol * 0.55 + (aCol > 4.5 ? 0.9 : 0.0);
  float r = 1.78 + fract(aSeed * 13.0) * 0.18;
  float t = fract(aSeed + uTime * (0.08 + fract(aSeed * 5.0) * 0.06));
  vec3 p = vec3(sin(ang) * r, mix(5.3, 0.3, t), cos(ang) * r * 0.55 - 0.3);
  vA = uData * sin(t * 3.14159) * (0.4 + 0.6 * fract(aSeed * 7.0));
  vec4 mv = modelViewMatrix * vec4(p, 1.0); gl_PointSize = uSize * (8.0 / -mv.z); gl_Position = projectionMatrix * mv;
}`;
export const DASH_FRAG = `
uniform vec3 uTint; varying float vA;
void main() { vec2 c = gl_PointCoord - 0.5; if (abs(c.y) > 0.1 || abs(c.x) > 0.45) discard; gl_FragColor = vec4(uTint, vA); }`;
