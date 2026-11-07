// JARVIS avatar: reconstruction particles. Each particle belongs to a point on the figure's surface.
//   Materialising (dir > 0): particles stream in from a cloud above the platform and land on their point just as
//     the build edge reaches it, so the body is seen to be assembled from light.
//   Dematerialising (dir < 0): as the edge comes down, particles lift off the surface and disperse upward.
// The edge is the same height the figure's shader reveals to, so particles and surface stay in step. The system
// is only drawn while a sequence runs (startup, a reconstruction, or the real emergency stop).
import * as THREE from "/static/vendor/three.module.min.js";

const VERT = `attribute vec3 aCloud; attribute float aSeed; uniform float uEdge, uDir, uTime; varying float vA;
void main() {
  vec4 wt = modelMatrix * vec4(position, 1.0);
  float a = uDir > 0.0 ? smoothstep(wt.y - 0.9, wt.y + 0.05, uEdge)          // arriving as the edge reaches it
                       : smoothstep(wt.y + 0.05, wt.y - 0.9, uEdge);         // leaving as the edge passes below it
  vec3 cloud = uDir > 0.0 ? aCloud : position + (aCloud - vec3(0.0, 2.0, 0.0)) * 0.6 + vec3(0.0, 1.6, 0.0);
  vec3 p = uDir > 0.0 ? mix(cloud, position, a) : mix(position, cloud, a);
  p += vec3(sin(aSeed * 50.0 + uTime * 3.0), cos(aSeed * 31.0 + uTime * 2.0), 0.0) * 0.03 * (1.0 - abs(a * 2.0 - 1.0));
  vA = 4.0 * a * (1.0 - a);   // visible in transit only
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  gl_PointSize = (2.0 + fract(aSeed * 7.0) * 3.0) * (8.0 / -mv.z);
  gl_Position = projectionMatrix * mv;
}`;
const FRAG = `uniform vec3 uTint; uniform float uGain; varying float vA;
void main() { float d = length(gl_PointCoord - 0.5); if (d > 0.5 || vA < 0.01) discard;
  gl_FragColor = vec4(mix(uTint, vec3(1.0, 0.97, 0.9), 0.5), vA * smoothstep(0.5, 0.0, d) * uGain); }`;

// geo: the figure geometry (rest coordinates); to: the group to live in; count: by device / quality.
export function buildReconstruction({ U, rng }, geo, to, count) {
  const src = geo.attributes.position.array, n = src.length / 3, r = rng(91);
  const P = new Float32Array(count * 3), C = new Float32Array(count * 3), S = new Float32Array(count);
  for (let i = 0; i < count; i++) {
    const q = Math.floor(r() * n);
    P.set([src[q * 3], src[q * 3 + 1], src[q * 3 + 2]], i * 3);
    const ang = r() * Math.PI * 2, rad = 0.4 + r() * 1.4;
    C.set([Math.cos(ang) * rad, 0.2 + r() * 0.8, Math.sin(ang) * rad * 0.6], i * 3);   // a cloud low over the platform
    S[i] = r();
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(P, 3)); g.setAttribute("aCloud", new THREE.BufferAttribute(C, 3));
  g.setAttribute("aSeed", new THREE.BufferAttribute(S, 1));
  const mat = new THREE.ShaderMaterial({ vertexShader: VERT, fragmentShader: FRAG, transparent: true, depthWrite: false,
    blending: THREE.AdditiveBlending, uniforms: { uTint: U.uTint, uTime: U.uTime, uGain: U.uGain, uEdge: { value: -2 }, uDir: { value: 1 } } });
  const points = new THREE.Points(g, mat); points.frustumCulled = false; points.visible = false; to.add(points);
  return {
    points,
    // edge: the reveal height; dir: +1 materialising, -1 dematerialising, 0 = nothing running (hidden)
    update(edge, dir) {
      points.visible = dir !== 0;
      if (dir !== 0) { mat.uniforms.uEdge.value = edge; mat.uniforms.uDir.value = dir; }
    },
  };
}
