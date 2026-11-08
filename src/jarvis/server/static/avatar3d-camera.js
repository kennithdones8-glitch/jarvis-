// JARVIS Avatar 2.5: the camera rig (orbit, zoom, pan, views and inspection targets) for the 3D projection.
//
// Plain maths with no imports, so the browser loads nothing extra and Node can test it. It moves the camera only:
// it never fetches, decides or acts. Pointer, wheel and touch input are captured only while inspection is on
// (avatar.js), so scrolling the page and typing in the chat behave exactly as before.
//
// The camera sits on a sphere around a target: az (around the figure, 0 = in front), el (above the horizon) and
// r (distance). A view or target sets the goal; the camera eases toward it while moving and jumps straight there
// in Low performance and Reduced motion modes.

const HOME = { target: [0, 2.68, 0], az: 0, el: 0.0148, r: 11.5 };   // the resting front view (as before)
// Resting and inspection views around the whole figure
export const VIEWS = {
  front: { label: "Front", az: 0, el: 0.0148, r: 11.5 },
  three: { label: "Three-quarter", az: 0.62, el: 0.09, r: 11.2 },
  side:  { label: "Side", az: 1.5708, el: 0.04, r: 11.5 },
  back:  { label: "Back", az: Math.PI, el: 0.06, r: 11.5 },
  top:   { label: "Above", az: 0.35, el: 0.95, r: 12.5 },
  close: { label: "Close", az: 0.12, el: 0.05, r: 8.2, target: [0, 3.2, 0] },
};
// What you can inspect, in world coordinates (the figure is scaled 0.9 and stands 0.2 above the floor)
export const TARGETS = {
  helmet:      { label: "Helmet and sensors", target: [0, 4.42, 0.05], az: 0.25, el: 0.05, r: 3.6 },
  reactor:     { label: "Reactor", target: [0, 3.46, 0.32], az: 0.0, el: 0.02, r: 3.2 },
  hand_r:      { label: "Right hand", target: [-0.95, 2.25, 0.08], az: -0.45, el: 0.1, r: 3.4 },
  hand_l:      { label: "Left hand", target: [0.95, 2.25, 0.08], az: 0.45, el: 0.1, r: 3.4 },
  shoulders:   { label: "Shoulders and pauldrons", target: [0, 3.85, 0], az: 0.5, el: 0.18, r: 4.8 },
  torso:       { label: "Chest and abdomen armour", target: [0, 3.0, 0.1], az: 0.3, el: 0.04, r: 4.8 },
  back:        { label: "Back and spine", target: [0, 3.2, -0.1], az: Math.PI, el: 0.08, r: 5.6 },
  legs:        { label: "Legs and joints", target: [0, 1.15, 0.05], az: 0.4, el: 0.06, r: 5.2 },
  neural:      { label: "Neural network", target: [0, 3.0, 0], az: 0.9, el: 0.1, r: 5.4 },
  orbitals:    { label: "Orbitals and satellites", target: [0, 2.6, 0], az: 0.3, el: 0.55, r: 13.5 },
  platform:    { label: "Platform", target: [0, 0.1, 0], az: 0.2, el: 0.6, r: 6.8 },
  projections: { label: "Projections", target: [2.4, 3.0, 0.3], az: 0.18, el: 0.04, r: 8.5 },
};
const LIMITS = { r: [2.4, 22], el: [-0.2, 1.25], x: [-4, 5], y: [-0.5, 6], z: [-3, 3] };
const SPEED = { slow: 0.5, normal: 1, fast: 1.7 };
const clamp = (v, [lo, hi]) => Math.min(hi, Math.max(lo, v));

export function createRig(camera, opts = {}) {
  const goal = { target: HOME.target.slice(), az: HOME.az, el: HOME.el, r: HOME.r };
  const cur = { target: HOME.target.slice(), az: HOME.az, el: HOME.el, r: HOME.r };
  let inspecting = false, view = "front", rest = "front", focus = null, speed = 1, wide = 0;

  function set(spec) {
    const t = spec.target || HOME.target;
    goal.target = t.slice(); goal.az = spec.az; goal.el = spec.el; goal.r = spec.r;
    // turn the shorter way round to the new angle
    while (goal.az - cur.az > Math.PI) cur.az += Math.PI * 2;
    while (cur.az - goal.az > Math.PI) cur.az -= Math.PI * 2;
  }
  function apply() {
    // while projections are open (and you are not inspecting) the resting view widens to make room for them
    const w = inspecting ? 0 : wide;
    const tx = cur.target[0] + 0.9 * w, ty = cur.target[1] + 0.02 * w, tz = cur.target[2], r = cur.r + 3 * w;
    const ce = Math.cos(cur.el);
    camera.position.set(tx + r * ce * Math.sin(cur.az), ty + r * Math.sin(cur.el), tz + r * ce * Math.cos(cur.az));
    camera.lookAt(tx, ty, tz);
  }
  apply();

  const rig = {
    // per frame: k is the blend (1 = jump). Returns true while the camera is still moving.
    update(k, wideMix = 0) {
      wide = wideMix;
      let d = 0;
      for (const key of ["az", "el", "r"]) { const delta = goal[key] - cur[key]; cur[key] += delta * k; d = Math.max(d, Math.abs(delta)); }
      for (let i = 0; i < 3; i++) { const delta = goal.target[i] - cur.target[i]; cur.target[i] += delta * k; d = Math.max(d, Math.abs(delta)); }
      if (d < 0.0005) { cur.az = goal.az; cur.el = goal.el; cur.r = goal.r; cur.target = goal.target.slice(); }
      apply();
      return d >= 0.0005;
    },
    // dx, dy in screen pixels
    rotate(dx, dy) {
      if (!inspecting) return;
      goal.az -= dx * 0.006 * speed;
      goal.el = clamp(goal.el + dy * 0.006 * speed, LIMITS.el);
      view = "custom"; focus = null;
    },
    zoom(factor) {   // > 1 moves away, < 1 moves closer
      if (!inspecting || !(factor > 0)) return;
      goal.r = clamp(goal.r * factor, LIMITS.r);
      view = "custom";
    },
    pan(dx, dy) {    // moves the target across the screen, scaled by the distance so it tracks the pointer
      if (!inspecting) return;
      const s = goal.r * 0.0016 * speed, ca = Math.cos(goal.az), sa = Math.sin(goal.az);
      goal.target[0] = clamp(goal.target[0] - dx * s * ca, LIMITS.x);
      goal.target[2] = clamp(goal.target[2] + dx * s * sa, LIMITS.z);
      goal.target[1] = clamp(goal.target[1] + dy * s, LIMITS.y);
      view = "custom"; focus = null;
    },
    view(name) {
      if (!VIEWS[name]) return false;
      view = name; focus = null;
      if (!inspecting) rest = name;
      set(VIEWS[name]);
      return true;
    },
    inspectTarget(name) {
      if (!TARGETS[name] || !inspecting) return false;
      focus = name; view = "custom";
      set(TARGETS[name]);
      return true;
    },
    setInspecting(on) {
      inspecting = !!on;
      if (!inspecting) { focus = null; view = rest; set(VIEWS[rest]); }   // leaving returns to the resting view
    },
    setRest(name) { if (!VIEWS[name]) return; rest = name; if (!inspecting) { view = name; set(VIEWS[name]); } },
    setSpeed(name) { speed = SPEED[name] || 1; },
    reset() { focus = null; view = inspecting ? "front" : rest; set(VIEWS[view]); },
    get state() {
      return { inspecting, view, rest, focus, az: +cur.az.toFixed(3), el: +cur.el.toFixed(3), r: +cur.r.toFixed(2),
               target: cur.target.map((x) => +x.toFixed(2)) };
    },
  };
  if (opts.rest) { rig.setRest(opts.rest); rig.update(1); }   // start at the resting view, no ease-in
  return rig;
}
