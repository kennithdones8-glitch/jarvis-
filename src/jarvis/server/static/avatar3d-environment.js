// JARVIS avatar: the projection chamber around the figure.
//   - platform detail: a ring of radial markers and a turning segmented ring;
//   - orbital systems at different heights and angles (knees, a diagonal around the torso, the chest, and a
//     counter-rotating pair above the head at stage 5); their speed follows the real activity level;
//   - a depth grid behind the figure and a faint projection boundary (stage 3);
//   - ground light that follows the reactor, a soft contact shadow under the feet, and a faint haze;
//   - floating panels with real status lines from the dashboard (counts and states only, never message text or
//     memories), shown only in the focus view.
import * as THREE from "/static/vendor/three.module.min.js";

const GRID_FRAG = `uniform vec3 uTint; uniform float uGain, uAlpha; varying vec2 vUv;
void main() { vec2 g = abs(fract(vUv * vec2(24.0, 24.0)) - 0.5) / fwidth(vUv * 24.0);
  float line = 1.0 - min(min(g.x, g.y), 1.0);
  float fade = smoothstep(0.0, 0.35, vUv.y) * smoothstep(1.0, 0.6, vUv.y) * smoothstep(0.0, 0.25, vUv.x) * smoothstep(1.0, 0.75, vUv.x);
  gl_FragColor = vec4(uTint, line * fade * uAlpha * uGain); }`;
const BOUND_FRAG = `uniform vec3 uTint; uniform float uGain, uAlpha, uTime; varying vec2 vUv;
void main() { float l = 1.0 - smoothstep(0.0, 0.04, abs(fract(vUv.x * 48.0) - 0.5) - 0.46);
  float rise = exp(-pow((fract(vUv.y - uTime * 0.08) - 0.5) * 6.0, 2.0));
  gl_FragColor = vec4(uTint, l * (0.5 + rise * 0.5) * pow(1.0 - vUv.y, 2.0) * uAlpha * uGain); }`;   // fine lines only, fading upward
const UV_VERT = `varying vec2 vUv; void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`;

// ctx: { holo, part, U, REACTOR, glowTexture, phone }; places: { scene, figure, SCALE, BASE_Y }
export function buildEnvironment(ctx, places) {
  const { holo, part, U, glowTexture, phone } = ctx;
  const { scene, figure, SCALE, BASE_Y } = places;
  const floor = BASE_Y + 0.06;
  const spin = [], orbitals = [];
  const envGroup = new THREE.Group(); scene.add(envGroup);   // toggled by the owner's setting; stages show their own parts inside
  let groundGlow = null;

  part("platform2", 1, (add) => {   // radial markers and a turning segmented ring on the platform
    const marks = [];
    for (let i = 0; i < 36; i++) {
      const g = new THREE.BoxGeometry(i % 3 === 0 ? 0.16 : 0.08, 0.006, 0.012), a = (i / 36) * Math.PI * 2;
      g.translate(1.62, 0, 0); g.rotateY(a); marks.push(g);
    }
    const m = add(new THREE.Mesh(merge(marks), holo({ opacity: 0.9, rim: 1.0, core: 0.7 })), scene);
    m.position.y = floor; m.scale.setScalar(SCALE);
    const seg = new THREE.Group(); seg.position.y = floor + 0.01; seg.scale.setScalar(SCALE); scene.add(seg);
    for (let i = 0; i < 12; i++) {
      const r = add(new THREE.Mesh(new THREE.TorusGeometry(1.32, 0.01, 4, 16, 0.32), holo({ opacity: 0.85, rim: 1.3, flow: true, core: 0.5 })), seg);
      r.rotation.x = Math.PI / 2; r.rotation.z = (i / 12) * Math.PI * 2;
    }
    spin.push({ obj: seg, axis: "y", speed: 0.12 });
  });
  const orbital = (name, tier, y, r, tilt, speed, nodes, pair = false) => part(name, tier, (add) => {
    for (const k of pair ? [1, -1] : [1]) {
      const pivot = new THREE.Group(); pivot.position.y = y; pivot.rotation.set(tilt[0] * k, 0, tilt[1] * k); figure.add(pivot);
      const ring = new THREE.Group(); pivot.add(ring);
      add(new THREE.Mesh(new THREE.TorusGeometry(r * (k > 0 ? 1 : 1.12), 0.006, 6, 160), holo({ opacity: 0.8, rim: 1.4, flow: true, core: 0.45 })), ring).rotation.x = Math.PI / 2;
      for (let i = 0; i < nodes; i++) {
        const a = (i / nodes) * Math.PI * 2, rr = r * (k > 0 ? 1 : 1.12);
        const n = add(new THREE.Mesh(new THREE.OctahedronGeometry(0.035), holo({ opacity: 1, rim: 1.2, core: 0.9 })), ring);
        n.position.set(Math.cos(a) * rr, 0, Math.sin(a) * rr);
      }
      orbitals.push({ obj: ring, speed: speed * k, pivot });
    }
  });
  orbital("orbit_low", 1, 1.1, 1.3, [0.08, 0.05], 0.3, 2);           // around the knees
  orbital("orbit_diag", 2, 3.0, 1.65, [0.45, 0.2], -0.22, 3);        // diagonal, around the torso
  orbital("orbit_upper", 3, 3.65, 1.15, [-0.25, -0.1], 0.4, 2);      // around the chest
  orbital("orbit_sig", 5, 5.45, 0.62, [0.12, 0.0], 0.55, 3, true);   // stage 5: a counter-rotating pair above the head

  part("chamber", 3, (add) => {   // stage 3: a depth grid behind the figure and the projection boundary
    const gm = new THREE.ShaderMaterial({ vertexShader: UV_VERT, fragmentShader: GRID_FRAG, transparent: true, depthWrite: false,
      blending: THREE.AdditiveBlending, uniforms: { uTint: U.uTint, uGain: U.uGain, uAlpha: { value: 0.12 } }, extensions: { derivatives: true } });
    for (const [z, x, ry] of [[-2.2, 0, 0], [-1.5, -1.75, 0.8], [-1.5, 1.75, -0.8]]) {   // sized to fade out inside the view (no visible canvas edge)
      const g = add(new THREE.Mesh(new THREE.PlaneGeometry(2.6, 4.6), gm), envGroup); g.position.set(x, 2.9, z); g.rotation.y = ry;
    }
    const bm = new THREE.ShaderMaterial({ vertexShader: UV_VERT, fragmentShader: BOUND_FRAG, transparent: true, depthWrite: false, side: THREE.DoubleSide,
      blending: THREE.AdditiveBlending, uniforms: { uTint: U.uTint, uGain: U.uGain, uTime: U.uTime, uAlpha: { value: 0.18 } } });
    const b = add(new THREE.Mesh(new THREE.CylinderGeometry(1.9, 1.9, 1.3, 64, 1, true), bm), envGroup); b.position.y = floor + 0.65;   // a low boundary at the platform's edge
  });
  part("ground", 1, (add) => {   // ground light (follows the reactor) and a soft contact shadow under the feet
    const shadow = add(new THREE.Mesh(new THREE.PlaneGeometry(1.4, 0.9), new THREE.MeshBasicMaterial({ map: glowTexture(), color: 0x000000,
      transparent: true, opacity: 0.55, depthWrite: false })), scene);
    shadow.rotation.x = -Math.PI / 2; shadow.position.set(0, floor + 0.002, 0.04); shadow.renderOrder = -2;
    groundGlow = add(new THREE.Mesh(new THREE.PlaneGeometry(3.0, 2.0), new THREE.MeshBasicMaterial({ map: glowTexture(), color: new THREE.Color("#ffcf7a"),
      transparent: true, opacity: 0.35, blending: THREE.AdditiveBlending, depthWrite: false })), scene);
    groundGlow.rotation.x = -Math.PI / 2; groundGlow.position.set(0, floor + 0.004, 0);
    if (!phone) {   // a faint haze behind the chest
      const haze = add(new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTexture(), color: new THREE.Color("#ffd98f"), transparent: true,
        opacity: 0.08, blending: THREE.AdditiveBlending, depthWrite: false })), envGroup);
      haze.position.set(0, 3.2, -1.2); haze.scale.set(3.4, 4.6, 1);
    }
  });

  // floating panels: real status lines only (titles and values from the dashboard's systems model)
  const panels = [];
  part("panels", 1, (add) => {
    for (const [x, y, z, ry] of [[-1.5, 4.6, -0.7, 0.3], [1.5, 4.6, -0.7, -0.3], [1.55, 2.75, -0.6, -0.32]]) {   // inside the projection's view
      const c = document.createElement("canvas"); c.width = 512; c.height = 200;
      const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace;
      const m = add(new THREE.Mesh(new THREE.PlaneGeometry(1.15, 0.45), new THREE.MeshBasicMaterial({ map: tex, transparent: true, opacity: 0.9,
        blending: THREE.AdditiveBlending, depthWrite: false })), scene);
      m.position.set(x, y, z); m.rotation.y = ry; m.visible = false;
      panels.push({ mesh: m, canvas: c, tex, key: "" });
    }
  });
  function drawPanel(p, item) {
    const key = JSON.stringify(item);
    if (key === p.key) return;
    p.key = key;
    const g = p.canvas.getContext("2d"); g.clearRect(0, 0, 512, 200);
    g.strokeStyle = "rgba(242, 196, 109, 0.75)"; g.lineWidth = 2;
    g.beginPath(); g.moveTo(14, 2); g.lineTo(498, 2); g.lineTo(510, 14); g.lineTo(510, 198); g.lineTo(2, 198); g.lineTo(2, 14); g.closePath(); g.stroke();
    g.fillStyle = "rgba(242, 196, 109, 0.08)"; g.fill();
    g.fillStyle = item.status === "bad" ? "#ff6b5e" : "#f2c46d";
    g.font = "600 30px Rajdhani, system-ui, sans-serif"; g.fillText(String(item.title).toUpperCase(), 26, 54);
    g.fillStyle = "#fbf6ec"; g.font = "500 34px system-ui, sans-serif";
    g.fillText(String(item.value).slice(0, 26), 26, 118);
    if (item.sub) { g.fillStyle = "#b9aa91"; g.font = "400 24px system-ui, sans-serif"; g.fillText(String(item.sub).slice(0, 34), 26, 166); }
    p.tex.needsUpdate = true;
  }

  return {
    // levels: { ring: real activity, reactor: real reactor level, animK, orbitK }
    update(dt, moving, lv) {
      if (moving) {
        for (const s of spin) s.obj.rotation[s.axis] += dt * s.speed * lv.animK;
        for (const o of orbitals) o.obj.rotation.y += dt * o.speed * (0.4 + lv.ring) * lv.orbitK;
      }
      if (groundGlow) groundGlow.material.opacity = Math.min(0.6, 0.18 + lv.reactor * 0.22);
    },
    // items: [{ title, value, status, sub }]; shown only while the focus view is open and environment holograms are on
    setPanels(items, show) {
      panels.forEach((p, i) => { const it = items && items[i]; p.mesh.visible = !!(show && it); if (it && show) drawPanel(p, it); });
    },
    setVisible(env, orbits) {
      envGroup.visible = env;
      for (const o of orbitals) o.pivot.visible = orbits;
    },
    hidden: () => [...panels.map((p) => p.mesh), envGroup, ...orbitals.map((o) => o.pivot)],
  };
}

function merge(geos) {
  const parts = geos.map((g) => (g.index ? g.toNonIndexed() : g));
  let n = 0; for (const g of parts) n += g.attributes.position.count;
  const pos = new Float32Array(n * 3), nrm = new Float32Array(n * 3), uv = new Float32Array(n * 2);
  let o = 0;
  for (const g of parts) { pos.set(g.attributes.position.array, o * 3); nrm.set(g.attributes.normal.array, o * 3); uv.set(g.attributes.uv.array, o * 2); o += g.attributes.position.count; }
  const out = new THREE.BufferGeometry();
  out.setAttribute("position", new THREE.BufferAttribute(pos, 3)); out.setAttribute("normal", new THREE.BufferAttribute(nrm, 3)); out.setAttribute("uv", new THREE.BufferAttribute(uv, 2));
  return out;
}
