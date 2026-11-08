// JARVIS avatar: builds the figure's meshes in a background thread, so the dashboard stays responsive while the
// avatar loads (on an older Mac the meshing takes seconds). Same code as the renderer's fallback path; it only
// computes arrays and sends them back (transferred, not copied). It touches no page, storage or network.
import { meshFigure, meshHands } from "/static/avatar3d-geometry.js";

const pack = (g) => {
  const attrs = {};
  for (const [name, a] of Object.entries(g.attributes)) attrs[name] = { array: a.array, itemSize: a.itemSize };
  const index = g.index ? (g.index.array || g.index) : null;
  return { attrs, index: index instanceof Uint32Array ? index : Uint32Array.from(index || []) };
};

self.onmessage = (e) => {
  const phone = !!(e.data && e.data.phone);
  const started = performance.now();
  const out = {
    body: pack(meshFigure(phone ? 0.04 : 0.03, [-1.12, -0.05, -0.48], [1.12, 4.38, 0.48])),
    head: pack(meshFigure(phone ? 0.018 : 0.013, [-0.34, 4.3, -0.44], [0.34, 5.15, 0.38])),
    hands: pack(meshHands(phone ? 0.009 : 0.0065)),
    wire: phone ? null : pack(meshFigure(0.075, [-1.12, -0.05, -0.48], [1.12, 4.38, 0.48])),
    ms: Math.round(performance.now() - started),
  };
  const transfer = [];
  for (const g of [out.body, out.head, out.hands, out.wire]) if (g) { for (const a of Object.values(g.attrs)) transfer.push(a.array.buffer); transfer.push(g.index.buffer); }
  self.postMessage(out, transfer);
};
