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

// Deciding is a protected action: on a paired iPhone it needs Face ID, and on a Mac with Touch ID set up it needs
// Touch ID, exactly as on the dashboard (the server checks; this page just asks the device for the confirmation).
let BIO = null;  // "Face ID", "Touch ID", or null when this device has no step-up
async function loadBio() {
  try {
    const st = await (await fetch("/api/state", { credentials: "same-origin" })).json();
    BIO = st.remote && st.remote.this_device ? "Face ID" : st.touch_id && st.touch_id.enabled ? "Touch ID" : null;
  } catch (e) {
    BIO = null;  // the server still refuses an unconfirmed decision; the error is shown
  }
}
async function post(path, body) {
  const r = await fetch(path, { method: "POST", credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-Requested-By": "jarvis" }, body: JSON.stringify(body) });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || String(r.status));
  return data;
}
const b64u = {
  toBuf: (s) => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4)), (c) => c.charCodeAt(0)).buffer,
  fromBuf: (b) => btoa(String.fromCharCode(...new Uint8Array(b))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, ""),
};
function getAssertion(o, btn) {
  const ask = () => navigator.credentials.get({ publicKey: {
    challenge: b64u.toBuf(o.challenge), rpId: o.rpId, timeout: o.timeout, userVerification: o.userVerification,
    allowCredentials: o.allowCredentials.map((c) => ({ ...c, id: b64u.toBuf(c.id) })) } });
  const t0 = Date.now();
  return ask().catch((e) => {
    // Older iPhone Safari only shows Face ID straight from a tap; we fetched a challenge first, so ask for one more tap.
    if (e.name !== "NotAllowedError" || Date.now() - t0 > 1500) throw e;
    return new Promise((resolve, reject) => {
      btn.disabled = false;
      btn.textContent = `Tap to confirm with ${BIO}`;
      btn.addEventListener("click", (ev) => { ev.stopImmediatePropagation(); btn.disabled = true; ask().then(resolve, reject); },
                          { once: true, capture: true });
    });
  });
}
async function decide(id, what, btn) {
  const path = `/api/proposals/${encodeURIComponent(id)}/${what}`;
  btn.disabled = true;
  try {
    if (!BIO) {
      await post(path, {});
    } else {
      const o = await post("/api/stepup/options", { path, body: {} });
      const a = await getAssertion(o, btn);
      await post(path, { challengeId: o.challengeId, assertion: { id: a.id, rawId: b64u.fromBuf(a.rawId), type: a.type,
        response: { clientDataJSON: b64u.fromBuf(a.response.clientDataJSON), authenticatorData: b64u.fromBuf(a.response.authenticatorData),
                    signature: b64u.fromBuf(a.response.signature) } } });
    }
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
loadBio().then(load);

// Emergency stop on this page too: one tap, never asks — the same request the dashboard sends.
(() => {
  const b = document.getElementById("estop");
  if (!b) return;
  b.addEventListener("click", async () => {
    b.disabled = true;
    try {
      const r = await fetch("/api/stop", { method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-Requested-By": "jarvis" },
        body: JSON.stringify({ reason: "stopped from the dashboard" }) });
      b.textContent = r.ok ? "Stopped · release it on Home" : "Stop failed · use Home";
    } catch (e) {
      b.textContent = "Stop failed · use Home";
    }
  });
})();
