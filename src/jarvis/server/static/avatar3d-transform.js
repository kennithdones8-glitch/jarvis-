// JARVIS Avatar 2.5: the mechanical transformation engine. A sequence opens a group of armour plates in seven named
// steps — unlock, separate, move, expose, reconfigure, sync, stabilise — and closes by playing the same steps
// backwards. Plain maths with no imports (Node can test it); the renderer turns the step progress into plate motion.
//
// Sequences are a way to look inside, chosen by you (inspecting the reactor, helmet, hands or shoulders, or the
// Transform buttons). No JARVIS state starts one, so the projection never suggests work that isn't happening.

export const STEPS = ["unlock", "separate", "move", "expose", "reconfigure", "sync", "stabilise"];
// each step: [start s, end s] on the sequence's own clock; overlapping a little so the motion flows
const TIMING = { unlock: [0, 0.3], separate: [0.25, 0.85], move: [0.75, 1.35], expose: [1.25, 1.85],
                 reconfigure: [1.75, 2.25], sync: [2.15, 2.65], stabilise: [2.55, 3.1] };
export const LENGTH = 3.1;
export const SEQUENCES = {
  reactor:   { label: "Expose the reactor", plates: ["chest", "abdomen"] },
  helmet:    { label: "Open the helmet", plates: ["helmet"] },
  arms:      { label: "Open the arms and hands", plates: ["upperarm", "forearm", "hand"] },
  shoulders: { label: "Open the shoulders", plates: ["shoulder", "pauldron"] },
};
// inspection target -> the sequence it opens (anything else closes what is open)
export const FOR_TARGET = { reactor: "reactor", torso: "reactor", helmet: "helmet", hand_r: "arms", hand_l: "arms", shoulders: "shoulders" };

const clamp01 = (x) => Math.min(1, Math.max(0, x));
const smooth = (x) => { const c = clamp01(x); return c * c * (3 - 2 * c); };

export function createSequencer() {
  let name = null, t = 0, dir = 0, next = null;   // dir: 1 opening, -1 closing, 0 still
  const progress = () => Object.fromEntries(STEPS.map((s) => [s, smooth((t - TIMING[s][0]) / (TIMING[s][1] - TIMING[s][0]))]));
  const seq = {
    // open a sequence (closing any other first), or pass null to close
    play(want) {
      if (want !== null && !SEQUENCES[want]) return false;
      if (want === name) { if (want !== null) dir = 1; return true; }
      if (name === null) { name = want; t = 0; dir = want ? 1 : 0; next = null; return true; }
      next = want; dir = -1;   // close the open one first, then open the next
      return true;
    },
    // dt in seconds; instant = true jumps to the end (Low performance / Reduced motion). Returns true while moving.
    update(dt, instant = false) {
      if (!name || dir === 0) return false;
      t = instant ? (dir > 0 ? LENGTH : 0) : Math.min(LENGTH, Math.max(0, t + dir * dt));
      if (dir > 0 && t >= LENGTH) dir = 0;
      if (dir < 0 && t <= 0) {
        name = next; next = null; t = 0; dir = name ? 1 : 0;
        if (name && instant) { t = LENGTH; dir = 0; }
      }
      return dir !== 0;
    },
    get state() {
      return { name, t: +t.toFixed(3), dir, opening: dir > 0, closing: dir < 0, open: !!name && dir === 0 && t >= LENGTH,
               plates: name ? SEQUENCES[name].plates : [], steps: progress() };
    },
  };
  return seq;
}
