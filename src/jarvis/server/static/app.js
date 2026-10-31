"use strict";
// JARVIS command centre. Renders only real state from /api/state. All data is inserted as text
// (never as HTML), so content from files or web pages cannot inject markup or scripts.

const $ = (s) => document.querySelector(s);
const state = { mode: "ask", data: null, convo: [], chatBusy: false, expanded: new Set(), online: true };

function h(tag, props = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined && v !== false) el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : String(kid));
  }
  return el;
}

async function api(path, body) {
  const opts = body === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Requested-By": "jarvis" },
    body: JSON.stringify(body),
  };
  const r = await fetch(path, { credentials: "same-origin", ...opts });
  const data = await r.json().catch(() => ({ error: `HTTP ${r.status}` }));
  if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
  return data;
}

// CSP forbids style attributes; setting the style property from script is allowed.
function fill(pct) { const el = h("span"); el.style.width = `${pct}%`; return el; }

const time = (ts) => new Date(typeof ts === "number" ? ts * 1000 : ts).toLocaleTimeString([], { hour12: false });
const label = (s) => s.replaceAll("_", " ");

// ---------------------------------------------------------------- command
function setMode(mode) {
  state.mode = mode;
  $("#tab-ask").setAttribute("aria-selected", mode === "ask");
  $("#tab-do").setAttribute("aria-selected", mode === "do");
  $("#cmd").placeholder = mode === "ask" ? "Ask JARVIS…" : "Describe a task, e.g. Summarise ~/Documents/JARVIS/Notes/x.txt and save it…";
  $("#modehint").textContent = mode === "ask"
    ? "Conversation only — JARVIS answers from its own knowledge and takes no actions."
    : "JARVIS plans the task, shows you the plan, and acts only after you press Run. Planning takes about a minute on this Mac.";
}

async function submitCommand(ev) {
  ev.preventDefault();
  const text = $("#cmd").value.trim();
  if (!text) return;
  if (state.mode === "do") {
    $("#send").disabled = true;
    try { await api("/api/plan", { request: text }); $("#cmd").value = ""; await refresh(); }
    catch (e) { flash(`Could not start planning: ${e.message}`); }
    finally { $("#send").disabled = false; }
    return;
  }
  if (state.chatBusy) return;
  const history = state.convo.filter((m) => !m.error).map((m) => ({ role: m.role, content: m.text }));
  state.convo.push({ role: "user", text });
  state.chatBusy = true;
  $("#cmd").value = "";
  renderConvo();
  try {
    const r = await api("/api/chat", { message: text, history });
    if (r.error) state.convo.push({ role: "assistant", text: r.error, error: true });
    else state.convo.push({ role: "assistant", text: r.text, meta: `${r.model} · ${r.seconds}s · ${r.tokens} tokens` });
  } catch (e) {
    state.convo.push({ role: "assistant", text: `Request failed: ${e.message}`, error: true });
  } finally {
    state.chatBusy = false;
    renderConvo();
    renderStatus();
  }
}

function flash(text) { state.convo.push({ role: "assistant", text, error: true }); renderConvo(); }

function renderConvo() {
  const items = state.convo.slice(-30).map((m) => m.role === "user"
    ? h("div", { class: "msg user" }, m.text)
    : h("div", { class: `msg jarvis${m.error ? " err" : ""}` }, m.text, m.meta ? h("div", { class: "meta" }, m.meta) : null));
  if (state.chatBusy) items.push(h("div", { class: "msg jarvis thinking" }, "Thinking"));
  $("#convo").replaceChildren(...items);
  if (items.length) items[items.length - 1].scrollIntoView({ block: "nearest" });
}

function renderJobs(jobs) {
  $("#jobs").replaceChildren(...jobs.filter((j) => j.state !== "submitted").map((j) => {
    if (j.state === "planning") {
      return h("div", { class: "card" },
        h("div", { class: "row" }, h("span", { class: "chip planning" }, "planning"), h("span", { class: "meta mono" }, `${j.elapsed}s`)),
        h("p", { class: "card-title" }, j.request),
        h("div", { class: "meta thinking" }, "Working out the steps"));
    }
    const discard = h("button", { class: "btn btn-sm btn-ghost", onclick: () => act(`/api/plan/${j.id}/discard`, {}) }, "Dismiss");
    if (j.kind === "plan") {
      return h("div", { class: "card" },
        h("div", { class: "row" }, h("span", { class: "chip" }, "plan ready"), h("span", { class: "meta mono" }, `${j.model} · ${j.seconds}s`)),
        h("p", { class: "card-title" }, j.goal || j.request),
        h("ol", { class: "steps" }, j.steps.map((s, i) => h("li", {}, h("span", { class: "ic" }, String(i)),
          h("div", {}, s.description, h("div", { class: "call" }, `${s.call} ${s.args}`))))),
        h("div", { class: "row mt10" },
          h("button", { class: "btn btn-primary btn-sm", onclick: () => act(`/api/plan/${j.id}/run`, {}) }, "Run plan"), discard));
    }
    const chip = { clarify: "question", cannot: "can't do", failed: "failed" }[j.kind] || j.kind;
    return h("div", { class: "card" },
      h("div", { class: "row" }, h("span", { class: `chip ${j.kind === "clarify" ? "clarify" : "failed"}` }, chip)),
      h("p", { class: "card-title" }, j.request),
      h("p", {}, j.message),
      h("div", { class: "row" },
        j.kind === "clarify" ? h("button", { class: "btn btn-sm", onclick: () => {
          $("#cmd").value = `${j.request}\nClarification: `; $("#cmd").focus(); act(`/api/plan/${j.id}/discard`, {});
        } }, "Answer") : null, discard));
  }));
}

// ---------------------------------------------------------------- missions
const ICON = { done: "✓", started: "›", pending: "·", failed: "✗", uncertain: "?", skipped: "–" };
const ACTIVE = ["queued", "running", "awaiting_approval", "verifying", "paused", "blocked", "recovering"];

function renderMissions(tasks) {
  $("#miscount").textContent = tasks.length ? `${tasks.filter((t) => ACTIVE.includes(t.state)).length} active` : "";
  if (!tasks.length) { $("#missions").replaceChildren(h("div", { class: "empty" }, "No tasks yet. Switch to Do and describe one.")); return; }
  $("#missions").replaceChildren(...tasks.map((t) => {
    const done = t.steps.filter((s) => s.state === "done" || s.state === "skipped").length;
    const open = ACTIVE.includes(t.state) || state.expanded.has(t.id);
    const controls = [];
    if (["queued", "running", "awaiting_approval"].includes(t.state)) controls.push(h("button", { class: "btn btn-sm", onclick: () => act(`/api/tasks/${t.id}/pause`, {}) }, "Pause"));
    if (["paused", "blocked"].includes(t.state)) controls.push(h("button", { class: "btn btn-sm", onclick: () => act(`/api/tasks/${t.id}/resume`, {}) }, "Resume"));
    if (!["completed", "failed", "cancelled"].includes(t.state)) controls.push(h("button", { class: "btn btn-sm btn-danger", onclick: () => confirm("Cancel this task? Completed steps are not undone.") && act(`/api/tasks/${t.id}/cancel`, {}) }, "Cancel"));
    const files = (t.evidence && t.evidence.files) || [];
    return h("article", { class: "card" },
      h("div", { class: "row between" },
        h("span", { class: `chip ${t.state}` }, label(t.state)),
        h("span", { class: "meta mono" }, `${time(t.updated_at)}${t.runner ? " · " + t.runner : ""}`)),
      h("p", { class: "card-title mt8" }, t.goal),
      h("div", { class: "bar", role: "progressbar", "aria-valuemin": 0, "aria-valuemax": t.steps.length, "aria-valuenow": done },
        fill(t.steps.length ? (100 * done) / t.steps.length : 0)),
      open ? h("ol", { class: "steps" }, t.steps.map((s) => h("li", { class: s.state },
        h("span", { class: "ic", title: s.state }, ICON[s.state] || "·"),
        h("div", {}, s.description, h("div", { class: "call" }, s.call + (s.attempts > 1 ? ` · attempt ${s.attempts}` : "")),
          s.error ? h("div", { class: "err" }, s.error) : null)))) : h("button", { class: "btn btn-sm btn-ghost", onclick: () => { state.expanded.add(t.id); render(); } }, `${done}/${t.steps.length} steps · details`),
      t.error ? h("div", { class: "err" }, t.error) : null,
      t.next_action ? h("div", { class: "next" }, `Next: ${t.next_action}`) : null,
      files.map((f) => h("div", { class: "evidence" }, `${f.content_matches ? "✓ verified" : "✗ NOT verified"} ${f.path}`)),
      open && t.final_text && !files.length ? h("pre", { class: "preview" }, t.final_text) : null,
      controls.length ? h("div", { class: "row mt10" }, controls) : null);
  }));
}

// ---------------------------------------------------------------- approvals
function renderApprovals(list) {
  $("#apcount").textContent = list.length ? String(list.length) : "";
  $("#ap-h").closest(".panel").classList.toggle("has-items", list.length > 0);
  if (!list.length) { $("#approvals").replaceChildren(h("div", { class: "empty" }, "Nothing waiting for you.")); return; }
  $("#approvals").replaceChildren(...list.map((a) => h("article", { class: "card approval" },
    h("div", { class: "row between" },
      h("span", { class: "tier" }, `TIER ${a.tier} · ${a.tool}.${a.action}`), h("span", { class: "meta mono" }, time(a.created_at))),
    h("p", { class: "card-title mt6" }, a.summary),
    h("div", { class: "meta" }, a.reason),
    a.resource ? h("div", { class: "meta mono mt4" }, a.resource) : null,
    a.preview !== null ? h("pre", { class: "preview", "aria-label": "Content that will be written" }, a.preview) : null,
    h("div", { class: "row mt8" },
      h("button", { class: "btn btn-ok btn-sm", onclick: () => act(`/api/approvals/${a.id}`, { approve: true }) }, "Approve"),
      h("button", { class: "btn btn-danger btn-sm", onclick: () => act(`/api/approvals/${a.id}`, { approve: false }) }, "Reject")))));
}

// ---------------------------------------------------------------- systems & activity
function renderSystem(d) {
  const m = d.models || { providers: [], budget: {} };
  const models = [];
  for (const p of m.providers) {
    for (const id of p.configured) {
      const on = p.available.includes(id);
      models.push(h("li", { title: on ? "available" : (p.error || "not installed") }, h("span", { class: `dot${on ? " on" : ""}` }), `${p.name}/${id}`));
    }
  }
  const chain = d.audit_chain;
  $("#system").replaceChildren(
    h("ul", { class: "models", "aria-label": "Models" }, models.length ? models : h("li", {}, "No models configured")),
    h("dl", { class: "kv" },
      h("dt", {}, "Budget"), h("dd", { class: "mono" }, `$${(m.budget.spent_this_month_usd || 0).toFixed(2)} of $${(m.budget.monthly_limit_usd || 0).toFixed(2)} this month`),
      h("dt", {}, "Cloud"), h("dd", {}, (m.disabled_providers || []).length ? `disabled (${m.disabled_providers.join(", ")})` : "none configured"),
      h("dt", {}, "Audit log"), h("dd", {}, chain ? (chain.ok ? `intact · ${chain.checked} entries` : `⚠ broken at #${chain.first_bad_seq}`) : "checking…"),
      h("dt", {}, "Folders"), h("dd", { class: "mono" }, d.roots.length ? d.roots.join(", ") : "none approved"),
      h("dt", {}, "Version"), h("dd", { class: "mono" }, d.version)));
}

function renderActivity(entries) {
  $("#activity").replaceChildren(...entries.map((e) => h("li", {},
    h("span", { class: "mono muted" }, time(e.ts)),
    h("div", {}, h("span", { class: "ev" }, e.event), " ", h("span", { class: "d" }, e.detail)))));
}

function renderStatus() {
  const d = state.data;
  let s = "online", text = "All systems nominal";
  if (!state.online) { s = "offline"; text = "Connection to JARVIS lost — retrying"; }
  else if (d && d.emergency_stop) { s = "stopped"; text = "Emergency stop engaged"; }
  else if (d && (d.approvals.length || d.tasks.some((t) => t.state === "blocked"))) { s = "attention"; text = d.approvals.length ? `${d.approvals.length} decision${d.approvals.length > 1 ? "s" : ""} waiting for you` : "A task is blocked"; }
  else if (d && d.tasks.some((t) => ["running", "verifying", "queued"].includes(t.state))) { s = "executing"; text = "Executing"; }
  else if (state.chatBusy || (d && d.jobs.some((j) => j.state === "planning"))) { s = "thinking"; text = "Thinking"; }
  else if (d && d.models && !d.models.providers.some((p) => p.available.length)) { s = "attention"; text = "No model available — is Ollama running?"; }
  $("#orb").dataset.state = s;
  $("#statusline").textContent = text;
  const stop = d && d.emergency_stop;
  $("#stopbar").hidden = !stop;
  $("#estop").hidden = !!stop;
  if (stop) $("#stoptext").textContent = `Emergency stop engaged by ${stop.by} at ${time(stop.ts)} — ${stop.reason}. New actions are blocked.`;
}

function render() {
  const d = state.data;
  renderStatus();
  if (!d) return;
  renderJobs(d.jobs);
  renderMissions(d.tasks);
  renderApprovals(d.approvals);
  renderSystem(d);
  renderActivity(d.audit);
}

async function act(path, body) {
  try { await api(path, body); } catch (e) { flash(e.message); }
  await refresh();
}

async function refresh() {
  try { state.data = await api("/api/state"); state.online = true; }
  catch (e) { state.online = false; if (/not signed in/.test(e.message)) { location.reload(); return; } }
  render();
}

document.addEventListener("DOMContentLoaded", () => {
  $("#tab-ask").addEventListener("click", () => setMode("ask"));
  $("#tab-do").addEventListener("click", () => setMode("do"));
  $("#cmdform").addEventListener("submit", submitCommand);
  $("#cmd").addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submitCommand(e); });
  $("#estop").addEventListener("click", () => {
    const reason = prompt("Emergency stop: pause all tasks and block new actions.\nReason (optional):", "");
    if (reason !== null) act("/api/stop", { reason: reason || "stopped from dashboard" });
  });
  $("#release").addEventListener("click", () => {
    if (confirm("Release the emergency stop? Paused tasks stay paused until you resume them.")) act("/api/release", { confirm: true });
  });
  setInterval(() => { $("#clock").textContent = new Date().toLocaleTimeString([], { hour12: false }); }, 1000);
  setMode("ask");
  renderConvo();
  refresh();
  setInterval(refresh, 1500);
});
