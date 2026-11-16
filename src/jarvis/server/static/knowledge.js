"use strict";
// Knowledge view (Evolution 4.0, Stage 4), part of the Memory page. Everything shown comes from /api/knowledge*:
// what JARVIS's records hold on what you searched for, why each item was picked, where it came from, how sure it
// is, and what connects to it. Nothing is drawn for effect: no item, no line. Uses the page's helpers (h, api, fill,
// $, plural, note) from app.js, which loads after this file; they are only called once the page is running.
(function (root) {
  const KIND = { memory: "Memory", mission: "Mission", objective: "Objective", lesson: "Lesson", decision: "Your decision", doc: "JARVIS's docs", answer: "Answer" };
  const STATUS = { stated: "you said so", confirmed: "confirmed", inferred: "unconfirmed", outdated: "may be out of date", record: "from JARVIS's records" };
  const GROUPS = [["conflicts", "Disagree"], ["outdated", "May be out of date"], ["duplicates", "Say the same thing"],
                  ["missing", "Objectives missing something"], ["patterns", "Keeps coming back"], ["unconfirmed", "Not confirmed"]];
  const state = { q: "", open: null };
  const day = (iso) => (iso || "").slice(0, 10);

  function card(i, onOpen) {
    const canOpen = /^(memory|objective|task):/.test(i.id);
    return h("li", { class: `know-item ${i.status}` },
      h("div", {}, h("b", {}, `${KIND[i.kind] || i.kind}: `), i.text, i.private ? h("span", { class: "know-private", title: "Never leaves this Mac" }, " · private") : null),
      h("small", {}, [(i.why || []).join("; "), STATUS[i.status] || i.status, i.source, i.since ? `since ${day(i.since)}` : null,
        i.confidence !== undefined && i.confidence < 1 ? `confidence ${Math.round(i.confidence * 100)}%` : null].filter(Boolean).join(" · ")),
      canOpen && onOpen ? h("button", { class: "btn btn-ghost btn-xs", type: "button", onclick: () => onOpen(i.id) }, "What connects to this") : null);
  }

  async function open(id) {
    const box = $("#memknow");
    let r;
    try { r = await api(`/api/knowledge/item?id=${encodeURIComponent(id)}`); } catch (e) { note(`Knowledge: ${e.message}`); return; }
    state.open = id;
    fill(box, h("div", { class: "job know" },
      h("div", { class: "row" }, h("b", {}, "Connections"),
        h("button", { class: "btn btn-ghost btn-xs", type: "button", onclick: () => { state.open = null; load(state.q, true); } }, "Back")),
      h("ul", { class: "know-list" }, card(r.item, null)),
      r.related.length ? h("ul", { class: "know-list know-related" }, r.related.map((x) => card(x, open)))
        : h("div", { class: "d-why" }, "Nothing else in JARVIS's records connects to this yet.")));
  }

  async function load(q, force) {
    const box = $("#memknow"), ins = $("#meminsights");
    if (!box || !ins) return;
    if (!force && q === state.q && state.loaded) return;
    state.q = q; state.loaded = true;
    if (state.open && !force) return;
    if (q.trim()) {
      let r = { items: [] };
      try { r = await api(`/api/knowledge?q=${encodeURIComponent(q)}`); } catch (e) { /* the memory list still shows */ }
      const others = r.items.filter((i) => i.kind !== "memory");   // memories are in the list below, with their controls
      fill(box, others.length || r.private_hidden ? h("div", { class: "job know" }, h("b", {}, "Also in JARVIS's records"),
        h("ul", { class: "know-list" }, others.map((i) => card(i, open))),
        r.private_hidden ? h("div", { class: "d-why" }, `${plural(r.private_hidden, "private item")} not shown here (they stay on the Mac).`) : null) : null);
      fill(ins, null);
      return;
    }
    fill(box, null);
    let data;
    try { data = (await api("/api/knowledge/insights")).insights; } catch (e) { fill(ins, null); return; }
    const groups = GROUPS.filter(([k]) => (data[k] || []).length);
    fill(ins, groups.length ? h("div", { class: "job know" }, h("b", {}, "Worth a look in what JARVIS knows"),
      groups.map(([k, label]) => h("details", { class: "know-group" },
        h("summary", {}, `${label} (${data[k].length})`),
        data[k].slice(0, 12).map((f) => h("div", { class: "know-finding" },
          h("div", {}, f.title), h("small", {}, `${f.why}. ${f.do}`),
          h("ul", { class: "know-list" }, f.items.map((i) => card(i, open)))))))) : null);
  }

  root.JarvisKnowledge = { load, open };
})(window);
