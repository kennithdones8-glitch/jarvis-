// JARVIS Avatar 2.5: projection presets. A preset is a named set of the per-device projection settings (the same
// keys as the Display settings in app.js, stored in this browser only). It changes the look on this device and
// nothing else: never what JARVIS can do, never a permission.
//
// Built-in presets can be applied and duplicated; your own can also be renamed, updated from the current settings
// and deleted. Pure functions over a plain state object, so Node can test them; app.js does the storing.
(function (root) {
  "use strict";
  const KEYS = ["projection", "quality", "particles", "animation", "reactor", "orbit", "env", "orbitals", "view", "camspeed", "diag"];
  const BUILTIN = {
    standard:    { label: "Standard", desc: "The everyday look.", s: { projection: "standard", quality: "auto", particles: "normal", animation: "normal", reactor: "normal", orbit: "normal", env: "on", orbitals: "on", view: "front", camspeed: "normal", diag: "off" } },
    cinematic:   { label: "Cinematic", desc: "Brighter, livelier, three-quarter view, highest quality.", s: { projection: "vivid", quality: "high", particles: "high", animation: "lively", reactor: "bright", orbit: "normal", env: "on", orbitals: "on", view: "three", camspeed: "normal", diag: "off" } },
    focus:       { label: "Focus", desc: "Quiet: dimmer, calmer, no environment holograms.", s: { projection: "subtle", quality: "auto", particles: "low", animation: "calm", reactor: "soft", orbit: "slow", env: "off", orbitals: "off", view: "front", camspeed: "slow", diag: "off" } },
    diagnostic:  { label: "Diagnostic", desc: "Shows the renderer's real numbers (frame time, draw calls, triangles).", s: { projection: "standard", quality: "balanced", particles: "low", animation: "normal", reactor: "normal", orbit: "slow", env: "on", orbitals: "on", view: "front", camspeed: "normal", diag: "on" } },
    immersive:   { label: "Immersive", desc: "Opens the focus view, close up, everything on.", enter: "focus", s: { projection: "vivid", quality: "auto", particles: "high", animation: "lively", reactor: "bright", orbit: "normal", env: "on", orbitals: "on", view: "close", camspeed: "normal", diag: "off" } },
    performance: { label: "Performance", desc: "Lightest drawing for slower devices.", s: { projection: "standard", quality: "low", particles: "low", animation: "calm", reactor: "normal", orbit: "slow", env: "off", orbitals: "on", view: "front", camspeed: "normal", diag: "off" } },
  };
  const MAX_CUSTOM = 20, MAX_NAME = 40;

  function cleanName(name) {
    return String(name == null ? "" : name).replace(/[\u0000-\u001f\u007f]/g, " ").replace(/\s+/g, " ").trim().slice(0, MAX_NAME);
  }
  function pick(settings, valid) {   // only known keys with valid values (valid: { key: [allowed values] })
    const out = {};
    for (const k of KEYS) {
      const v = settings ? settings[k] : undefined;
      if (typeof v === "string" && (!valid || !valid[k] || valid[k].includes(v))) out[k] = v;
    }
    return out;
  }
  function empty() { return { active: "standard", custom: [] }; }
  function normalise(raw, valid) {
    const st = empty();
    if (!raw || typeof raw !== "object") return st;
    const seen = new Set();
    for (const c of Array.isArray(raw.custom) ? raw.custom : []) {
      const id = typeof c?.id === "string" && /^c[0-9a-z]{1,16}$/.test(c.id) ? c.id : null;
      const name = cleanName(c?.name);
      if (!id || !name || seen.has(id) || st.custom.length >= MAX_CUSTOM) continue;
      seen.add(id); st.custom.push({ id, name, s: pick(c.s, valid) });
    }
    st.active = typeof raw.active === "string" && find(st, raw.active) ? raw.active : "standard";
    return st;
  }
  function find(st, id) {
    if (BUILTIN[id]) return { id, label: BUILTIN[id].label, desc: BUILTIN[id].desc, s: BUILTIN[id].s, builtin: true, enter: BUILTIN[id].enter || null };
    const c = st.custom.find((x) => x.id === id);
    return c ? { id: c.id, label: c.name, desc: "Your preset.", s: c.s, builtin: false, enter: null } : null;
  }
  function list(st) { return [...Object.keys(BUILTIN).map((id) => find(st, id)), ...st.custom.map((c) => find(st, c.id))]; }
  function matches(preset, display) { return !!preset && Object.entries(preset.s).every(([k, v]) => display[k] === v); }
  // which preset is showing, and whether the settings were changed since (shown as Custom)
  function current(st, display) {
    const p = find(st, st.active) || find(st, "standard");
    return { id: p.id, label: p.label, builtin: p.builtin, modified: !matches(p, display) };
  }
  function uniqueName(st, name) {
    const taken = new Set([...Object.values(BUILTIN).map((b) => b.label.toLowerCase()), ...st.custom.map((c) => c.name.toLowerCase())]);
    if (!taken.has(name.toLowerCase())) return name;
    for (let i = 2; i < 100; i++) { const n = `${name.slice(0, MAX_NAME - 5)} (${i})`; if (!taken.has(n.toLowerCase())) return n; }
    return null;
  }
  function newId(st) {
    for (let i = 0; i < 50; i++) { const id = "c" + Math.random().toString(36).slice(2, 10); if (!st.custom.some((c) => c.id === id)) return id; }
    return "c" + Date.now().toString(36);
  }
  const fail = (st, error) => ({ ok: false, error, state: st });
  function create(st, name, display, valid) {
    const n = cleanName(name);
    if (!n) return fail(st, "Give the preset a name.");
    if (st.custom.length >= MAX_CUSTOM) return fail(st, `You can keep up to ${MAX_CUSTOM} presets. Delete one first.`);
    const u = uniqueName(st, n);
    if (!u) return fail(st, "That name is taken.");
    const id = newId(st);
    return { ok: true, id, state: { active: id, custom: [...st.custom, { id, name: u, s: pick(display, valid) }] } };
  }
  function own(st, id) { return st.custom.find((c) => c.id === id) || null; }
  function rename(st, id, name) {
    if (!own(st, id)) return fail(st, "Built-in presets can't be renamed. Duplicate it first.");
    const n = cleanName(name);
    if (!n) return fail(st, "Give the preset a name.");
    const others = { ...st, custom: st.custom.filter((c) => c.id !== id) };
    const u = uniqueName(others, n);
    if (!u) return fail(st, "That name is taken.");
    return { ok: true, id, state: { ...st, custom: st.custom.map((c) => (c.id === id ? { ...c, name: u } : c)) } };
  }
  function update(st, id, display, valid) {   // "edit": save the current settings into your preset
    if (!own(st, id)) return fail(st, "Built-in presets can't be changed. Save the current settings as a new preset instead.");
    return { ok: true, id, state: { active: id, custom: st.custom.map((c) => (c.id === id ? { ...c, s: pick(display, valid) } : c)) } };
  }
  function duplicate(st, id) {
    const p = find(st, id);
    if (!p) return fail(st, "That preset no longer exists.");
    return create(st, `${p.label} copy`, p.s);
  }
  function remove(st, id) {
    if (!own(st, id)) return fail(st, "Built-in presets can't be deleted.");
    return { ok: true, id, state: { active: st.active === id ? "standard" : st.active, custom: st.custom.filter((c) => c.id !== id) } };
  }
  function activate(st, id) {
    const p = find(st, id);
    if (!p) return fail(st, "That preset no longer exists.");
    return { ok: true, id, preset: p, state: { ...st, active: id } };
  }

  const api = { KEYS, BUILTIN, MAX_CUSTOM, MAX_NAME, cleanName, normalise, find, list, matches, current, create, rename, update, duplicate, remove, activate, empty };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.JarvisPresets = api;
})(typeof window !== "undefined" ? window : globalThis);
