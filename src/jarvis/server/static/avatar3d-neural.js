// JARVIS avatar: the neural network inside the projection. Nodes at the body's centres (head, neck, sternum,
// shoulders, elbows, wrists, hips, knees, ankles) joined by links that run from the reactor out to the head,
// the hands and the feet; stage 3 adds branches and more nodes. Pulses travel along the links (the shared flow
// value: outward while working, toward the head while thinking). Brightness follows the real thinking level, and
// the reactor-to-limb links light while JARVIS is really executing. Built in rest coordinates and drawn with the
// figure's vertex shader, so it bends with the arms and turns with the head.
import * as THREE from "/static/vendor/three.module.min.js";

const V = (x, y, z) => new THREE.Vector3(x, y, z);
const CORE = V(0, 3.62, 0.18);

// stage 1: the backbone (core links: reactor to head and pelvis; limb links: reactor to hands, pelvis to feet).
// stage 3: only the added branches and nodes.
function nodesAndLinks(stage3) {
  const nodes = [], core = [], limb = [];
  if (!stage3) {
    nodes.push(V(0, 4.68, 0.02), V(0, 4.25, -0.02), CORE, V(0, 3.05, 0.05), V(0, 2.55, 0.0));
    core.push([CORE, V(0, 4.0, 0.05), V(0, 4.25, -0.02), V(0, 4.68, 0.02)], [CORE, V(0, 3.3, 0.08), V(0, 3.05, 0.05), V(0, 2.55, 0.0)]);
  }
  for (const s of [1, -1]) {
    if (!stage3) {
      nodes.push(V(s * 0.62, 3.92, 0.0), V(s * 0.8, 3.04, -0.03), V(s * 0.88, 2.3, 0.05), V(s * 0.25, 2.45, 0.02), V(s * 0.26, 1.34, 0.03), V(s * 0.25, 0.32, -0.03));
      limb.push([CORE, V(s * 0.3, 3.82, 0.1), V(s * 0.62, 3.92, 0.0), V(s * 0.74, 3.45, 0.0), V(s * 0.8, 3.04, -0.03), V(s * 0.85, 2.65, 0.01), V(s * 0.88, 2.3, 0.05), V(s * 0.9, 2.1, 0.06)]);
      limb.push([V(0, 2.55, 0.0), V(s * 0.25, 2.45, 0.02), V(s * 0.26, 1.9, 0.02), V(s * 0.26, 1.34, 0.03), V(s * 0.255, 0.85, -0.01), V(s * 0.25, 0.32, -0.03), V(s * 0.26, 0.12, 0.1)]);
    } else {
      core.push([CORE, V(s * 0.22, 3.5, 0.15), V(s * 0.38, 3.3, 0.06), V(s * 0.3, 2.8, 0.05), V(s * 0.25, 2.45, 0.02)],   // ribs of light
                [V(0, 4.25, -0.02), V(s * 0.3, 4.08, 0.0), V(s * 0.62, 3.92, 0.0)],                                    // across the shoulders
                [CORE, V(s * 0.18, 3.85, 0.14), V(s * 0.3, 4.0, 0.08)]);
      nodes.push(V(s * 0.38, 3.3, 0.06), V(s * 0.3, 4.08, 0.0), V(s * 0.74, 3.45, 0.0), V(s * 0.26, 1.9, 0.02), V(s * 0.255, 0.85, -0.01));
    }
  }
  return { nodes, core, limb };
}

// ctx: { holo, part, mergeGeos }; to: the group the network lives in (the figure body).
export function buildNeural(ctx, to) {
  const { holo, part, mergeGeos } = ctx;
  const mats = { links: [], limbs: [], nodes: [] };
  const build = (stage3) => (add) => {
    const { nodes, core: corePts, limb: limbPts } = nodesAndLinks(stage3);
    const tube = (pts) => new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts), pts.length * 10, stage3 ? 0.0045 : 0.006, 4, false);
    const core = corePts.map(tube), limb = limbPts.map(tube);
    if (core.length) { const m = holo({ opacity: 0.3, rim: 0.6, flow: true, core: 0.6, head: true }); mats.links.push(m); add(new THREE.Mesh(mergeGeos(core), m), to); }
    if (limb.length) { const m = holo({ opacity: 0.3, rim: 0.6, flow: true, core: 0.6, head: true }); mats.limbs.push(m); add(new THREE.Mesh(mergeGeos(limb), m), to); }
    const dots = nodes.map((p) => { const g = new THREE.SphereGeometry(stage3 ? 0.014 : 0.02, 10, 8); g.translate(p.x, p.y, p.z); return g; });
    const nm = holo({ opacity: 0.6, rim: 1.0, core: 0.9, head: true }); mats.nodes.push(nm);
    add(new THREE.Mesh(mergeGeos(dots), nm), to);
  };
  part("neural", 1, build(false));    // the backbone: reactor to head, hands and feet
  part("neural3", 3, build(true));    // stage 3: branches and more nodes
  return {
    // thinking: the real neural level; executing: whether a mission is really running; reactor: its real level
    update(thinking, executing, reactor) {
      for (const m of mats.links) m.uniforms.uOpacity.value = 0.12 + thinking * 0.6;
      for (const m of mats.limbs) m.uniforms.uOpacity.value = 0.1 + thinking * 0.25 + (executing ? 0.55 : 0) + reactor * 0.1;
      for (const m of mats.nodes) m.uniforms.uOpacity.value = 0.3 + thinking * 0.5 + reactor * 0.15;
    },
  };
}
