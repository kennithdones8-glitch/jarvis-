// Improvement ideas: found by JARVIS in its own record. Deciding only records your answer; nothing changes by itself.
"use strict";

function h(tag, props, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") n.className = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v);
  }
  for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false) n.append(kid instanceof Node ? kid : String(kid));
  return n;
}
const LABEL = { open: "Waiting for you", approved: "Approved: on the to-do list", rejected: "Rejected", done: "Done" };

async function decide(id, what, btn) {
  btn.disabled = true;
  try {
    const r = await fetch(`/api/proposals/${encodeURIComponent(id)}/${what}`, {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-Requested-By": "jarvis" }, body: "{}",
    });
    if (!r.ok) throw new Error(String(r.status));
    await load();
  } catch (e) {
    btn.disabled = false;
    btn.textContent = `Failed (${e.message})`;
  }
}

function card(p) {
  const buttons = p.state === "open"
    ? [h("button", { class: "btn", type: "button", onclick: (e) => decide(p.id, "approve", e.target) }, "Approve"),
       h("button", { class: "btn btn-ghost", type: "button", onclick: (e) => decide(p.id, "reject", e.target) }, "Reject")]
    : p.state === "approved"
      ? [h("button", { class: "btn btn-ghost", type: "button", onclick: (e) => decide(p.id, "done", e.target) }, "Mark done")]
      : [h("button", { class: "btn btn-ghost", type: "button", onclick: (e) => decide(p.id, "reopen", e.target) }, "Reopen")];
  return h("section", { class: "panel", "aria-label": p.title },
    h("header", { class: "ph" }, h("h2", {}, p.title)),
    h("p", { class: "lead" }, `${LABEL[p.state] || p.state} · ${p.kind}`),
    h("p", {}, p.problem),
    h("ul", {}, p.evidence.map((e) => h("li", {}, e))),
    h("p", {}, h("b", {}, "Suggestion: "), h("span", { class: "pre" }, p.suggestion)),
    h("p", { class: "lead" }, `Risk: ${p.risk}`),
    p.state === "approved" && p.kind === "code"
      ? h("p", { class: "lead" }, `On the Mac: jarvis proposals brief ${p.id} gives Claude Code the task.`) : null,
    h("div", { class: "row" }, buttons));
}

async function load() {
  const main = document.getElementById("ideas");
  try {
    const r = await fetch("/api/proposals", { credentials: "same-origin" });
    if (!r.ok) throw new Error(String(r.status));
    const items = (await r.json()).proposals;
    main.replaceChildren(
      h("p", { class: "lead" }, "JARVIS looks at its own record (benchmark results, timeouts, errors, what you approve and reject) and suggests improvements. It never changes itself: approving puts an idea on the to-do list, and any code change still goes through a branch, tests and a benchmark that you review."),
      ...(items.length ? items.map(card) : [h("p", { class: "lead" }, "No ideas right now: nothing in the record suggests a change.")]));
  } catch (e) {
    main.replaceChildren(h("p", { class: "lead" }, `Couldn't load ideas (${e.message}).`));
  }
}
load();
