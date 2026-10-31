"use strict";
// JARVIS command centre. Renders only real state from /api/state. All data is inserted as text
// (never as HTML), so content from files or web pages cannot inject markup or scripts.

const $ = (s) => document.querySelector(s);
const ui = { mode: "ask", data: null, convo: [], chatBusy: false, online: true, open: new Set(), lastFeed: "",
             session: (crypto.randomUUID ? crypto.randomUUID() : String(Math.random()).slice(2)), memQ: "", memKey: "" };

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

// ---------------------------------------------------------------- Face ID (iPhone) / Touch ID (Mac) for sensitive actions
const b64u = {
  toBuf: (s) => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4)), (c) => c.charCodeAt(0)).buffer,
  fromBuf: (b) => btoa(String.fromCharCode(...new Uint8Array(b))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, ""),
};
// Must match the server's STEP_UP list; the server enforces it regardless of what this page does.
const FACE_ID = [/^\/api\/approvals\/[\w-]+$/, /^\/api\/release$/, /^\/api\/plan\/\w+\/run$/,
                 /^\/api\/memory\/[\w-]+\/(delete|edit)$/, /^\/api\/devices\/[\w-]+\/revoke$/];
const TOUCH_ID = [...FACE_ID, /^\/api\/devices\/pair$/, /^\/api\/touchid\/enroll\/options$/, /^\/api\/touchid\/[\w-]+\/remove$/];
const onPhone = () => !!(ui.data && ui.data.remote && ui.data.remote.this_device);
const touchIdOn = () => !onPhone() && !!(ui.data && ui.data.touch_id && ui.data.touch_id.enabled);
const bio = () => (onPhone() ? "Face ID" : "Touch ID");
const cancelled = (e) => (e.name === "NotAllowedError" ? `${bio()} was cancelled.` : e.message);
const credJSON = (c) => ({ id: c.id, rawId: b64u.fromBuf(c.rawId), type: c.type });

async function call(path, body) {
  const list = onPhone() ? FACE_ID : touchIdOn() ? TOUCH_ID : [];
  const needs = list.some((r) => r.test(path)) || ((onPhone() || touchIdOn()) && path === "/api/memory/forget" && body.confirm === true);
  if (!needs) return api(path, body);
  const o = await api("/api/stepup/options", { path, body });
  const a = await navigator.credentials.get({ publicKey: {
    challenge: b64u.toBuf(o.challenge), rpId: o.rpId, timeout: o.timeout, userVerification: o.userVerification,
    allowCredentials: o.allowCredentials.map((c) => ({ ...c, id: b64u.toBuf(c.id) })) } });
  return api(path, { ...body, challengeId: o.challengeId, assertion: { ...credJSON(a),
    response: { clientDataJSON: b64u.fromBuf(a.response.clientDataJSON), authenticatorData: b64u.fromBuf(a.response.authenticatorData),
                signature: b64u.fromBuf(a.response.signature) } } });
}

// ---------------------------------------------------------------- plain-language helpers
const clock = (ts) => new Date(typeof ts === "number" ? ts * 1000 : ts).toLocaleTimeString([], { hour12: false, hour: "2-digit", minute: "2-digit" });
const base = (p) => (p || "").split("/").filter(Boolean).pop() || p || "";
const folder = (p) => { const parts = (p || "").split("/").filter(Boolean); parts.pop(); return parts.length ? parts.slice(-2).join("/") : "/"; };
const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
const STATE_WORDS = {
  queued: "Queued", running: "In progress", awaiting_approval: "Needs your decision", verifying: "Verifying",
  paused: "Paused", blocked: "Blocked — needs you", recovering: "Recovering", completed: "Complete",
  failed: "Failed", cancelled: "Cancelled",
};
const ACTIVE = ["queued", "running", "verifying", "recovering"];
const NEEDS = ["awaiting_approval", "blocked"];

function greeting() {
  const hr = new Date().getHours();
  return hr < 5 ? "Working late" : hr < 12 ? "Good morning" : hr < 18 ? "Good afternoon" : "Good evening";
}

function decisionKind(a) {
  if (a.tool === "egress") return "Send data to the cloud";
  if (a.tier >= 4) return "High-risk action";
  if (a.tier === 3) return "External action";
  if (a.tool === "fs" && a.action === "write") return "Save a file";
  if (a.tool === "fs" && a.action === "mkdir") return "Create a folder";
  if (a.tool === "fs" && a.action === "delete") return "Delete a file";
  if (a.tool === "search") return "Search the web";
  return "Action";
}

// ---------------------------------------------------------------- headline, core, stats
function situation(d) {
  if (!ui.online) return { core: "offline", cls: "stopped", kicker: "Link lost", main: "Connection to JARVIS lost", sub: "Retrying… is `jarvis dashboard` still running in Terminal?" };
  if (!d) return { core: "thinking", cls: "", kicker: "Status", main: "Connecting…", sub: "" };
  if (d.emergency_stop) return { core: "stopped", cls: "stopped", kicker: "Emergency stop", main: "All actions halted", sub: `${d.emergency_stop.reason} — release the stop when you're ready.` };
  if (d.approvals.length) {
    const a = d.approvals[0];
    return { core: "attention", cls: "attention", kicker: "Decision required",
             main: a.summary.split(" — ")[0], sub: d.approvals.length > 1 ? `${d.approvals.length} decisions are waiting in Decisions.` : "Review it in Decisions." };
  }
  const blocked = d.tasks.find((t) => t.state === "blocked");
  if (blocked) return { core: "attention", cls: "attention", kicker: "Blocked", main: blocked.goal, sub: blocked.next_action || "This task needs your input." };
  const run = d.tasks.find((t) => ACTIVE.includes(t.state));
  if (run) {
    const i = run.steps.findIndex((s) => s.state === "started" || s.state === "pending");
    const step = run.steps[i];
    return { core: "executing", cls: "", kicker: run.state === "verifying" ? "Verifying" : "Executing",
             main: run.goal, sub: step ? `Step ${i + 1} of ${run.steps.length} · ${step.description}` : "Checking the result" };
  }
  const job = d.jobs.find((j) => j.state === "planning" || j.state === "waiting_approval");
  if (job) return { core: "thinking", cls: "", kicker: "Planning", main: job.request, sub: `Working out the steps · ${job.elapsed}s (about a minute on this Mac)` };
  if (ui.chatBusy) return { core: "thinking", cls: "", kicker: "Thinking", main: "Composing a reply", sub: "" };
  const online = d.models ? d.models.providers.reduce((n, p) => n + p.available.length, 0) : 0;
  if (d.models && !online) return { core: "attention", cls: "attention", kicker: "Systems", main: "No model available", sub: "Is Ollama running? Open the Ollama app, then wait a few seconds." };
  return { core: "online", cls: "", kicker: "All systems nominal", main: `${greeting()}.`, sub: `${plural(online, "model")} online · nothing needs you right now.` };
}

function renderHead(d) {
  const s = situation(d);
  $("#core").dataset.state = s.core;
  $(".headline").className = `headline ${s.cls}`;
  $("#hl-kicker").textContent = s.kicker;
  $("#hl-main").textContent = s.main;
  $("#hl-sub").textContent = s.sub;
  document.title = s.core === "attention" ? "● JARVIS — decision required" : "JARVIS";
  const stop = d && d.emergency_stop;
  $("#stopbar").hidden = !stop;
  $("#estop").hidden = !!stop;
  if (stop) $("#stoptext").textContent = `Emergency stop engaged at ${clock(stop.ts)} — new actions are blocked.`;
  if (!d) return;
  const active = d.tasks.filter((t) => ACTIVE.includes(t.state)).length;
  const needs = d.approvals.length + d.tasks.filter((t) => t.state === "blocked").length;
  const models = d.models ? d.models.providers.reduce((n, p) => n + p.available.length, 0) : 0;
  const total = d.models ? d.models.providers.reduce((n, p) => n + p.configured.length, 0) : 0;
  const spent = d.models ? d.models.budget.spent_this_month_usd || 0 : 0;
  const claude = d.models && (d.models.cloud_usage || []).find((u) => u.provider === "claude");
  const stat = (v, label, alert) => h("div", { class: `stat${alert ? " alert" : ""}` }, h("b", {}, v), h("span", {}, label));
  $("#stats").replaceChildren(stat(active, "Active"), stat(needs, "Need you", needs > 0), stat(`${models}/${total}`, "Models"),
    claude ? (claude.limited_until ? stat(clock(claude.limited_until), "Claude resets", true) : stat(claude.calls, "Claude · 5h"))
      : stat(`$${spent.toFixed(2)}`, "Spent"));
}

// ---------------------------------------------------------------- feed: conversation + plans
const MODES = {
  ask: ["Ask JARVIS anything…", "Ask: conversation only. JARVIS answers and takes no actions.   ⌘↩ to send"],
  research: ["What should JARVIS look up?", "Research: Claude searches the web and reads pages, then answers with sources. Asks before sending."],
  do: ["Describe a task — e.g. research X and save a brief to my notes", "Do: JARVIS plans the task and shows you the plan. Nothing happens until you press Run."],
};

function setMode(mode) {
  ui.mode = mode;
  for (const m of Object.keys(MODES)) $(`#tab-${m}`).setAttribute("aria-selected", mode === m);
  $("#cmd").placeholder = MODES[mode][0];
  $("#modehint").textContent = MODES[mode][1];
  $("#cmd").focus();
}

async function submitCommand(ev) {
  ev.preventDefault();
  const text = $("#cmd").value.trim();
  if (!text) return;
  if (ui.mode === "do") {
    $("#send").disabled = true;
    try { await api("/api/plan", { request: text }); $("#cmd").value = ""; await refresh(); }
    catch (e) { note(`Could not start planning: ${e.message}`); }
    finally { $("#send").disabled = false; }
    return;
  }
  if (ui.chatBusy) return;
  ui.convo.push({ role: "user", text });
  $("#cmd").value = "";
  if (ui.mode === "research") { await sendChat({ question: text, session: ui.session }, "/api/research"); return; }
  const history = ui.convo.slice(0, -1).filter((m) => !m.error && !m.consent).map((m) => ({ role: m.role, content: m.text }));
  await sendChat({ message: text, history, session: ui.session });
}

// Sends a chat turn. If the best model is in the cloud and your rule is "ask every time", the server
// returns needs_approval instead of sending; we show a consent card and resend the identical request.
async function sendChat(payload, endpoint = "/api/chat") {
  ui.chatBusy = true;
  render();
  try {
    const r = await api(endpoint, payload);
    if (r.needs_approval) ui.convo.push({ role: "assistant", consent: true, payload, endpoint, approval_id: r.approval_id, text: r.summary });
    else if (r.answer !== undefined) ui.convo.push({ role: "assistant", text: r.answer, sources: r.sources,
      meta: [r.model.split("/").pop(), `${r.seconds}s`, `${r.searches.length} searches`, `${r.pages_read.length} pages read`,
             `${r.verified_sources}/${r.sources.length} sources verified`].join(" · ") });
    else if (r.error) ui.convo.push({ role: "assistant", text: r.error, error: true });
    else ui.convo.push({ role: "assistant", text: r.text, meta: [r.model.split("/").pop(), `${r.seconds}s`,
      r.memories_used ? `used ${plural(r.memories_used, "memory").replace("memorys", "memories")}` : null, r.note].filter(Boolean).join(" · ") });
  } catch (e) {
    ui.convo.push({ role: "assistant", text: `Request failed: ${e.message}`, error: true });
  } finally {
    ui.chatBusy = false;
    render();
  }
}

async function consent(m, approve) {
  ui.convo = ui.convo.filter((x) => x !== m);
  try { await call(`/api/approvals/${m.approval_id}`, { approve }); }
  catch (e) { if (e.name === "NotAllowedError") { ui.convo.push(m); render(); return; } /* else: already decided in Decisions */ }
  if (m.endpoint === "/api/research") {
    if (approve) await sendChat(m.payload, m.endpoint);
    else note("Not researched — web research needs to send your question to Claude.");
    return;
  }
  await sendChat(approve ? m.payload : { ...m.payload, local_only: true });
}

function note(text) { ui.convo.push({ role: "assistant", text, error: true }); render(); }

function jobCard(j) {
  const dismiss = h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: () => act(`/api/plan/${j.id}/discard`, {}) }, "Dismiss");
  if (j.state === "waiting_approval") {
    return h("div", { class: "job consent" }, h("div", { class: "kicker" }, "Waiting for you"),
      h("div", { class: "job-title" }, j.request),
      h("div", { class: "d-target" }, "Planning with Claude needs your approval — see Decisions. Reject it to plan locally instead."));
  }
  if (j.state === "planning") {
    return h("div", { class: "job" }, h("div", { class: "kicker" }, `Planning · ${j.elapsed}s`),
      h("div", { class: "job-title typing" }, j.request));
  }
  if (j.kind === "plan") {
    return h("div", { class: "job" },
      h("div", { class: "kicker" }, `Plan ready · ${plural(j.steps.length, "step")} · ${j.model.split("/").pop()}`),
      j.note ? h("div", { class: "d-why" }, j.note) : null,
      h("div", { class: "job-title" }, j.goal || j.request),
      h("ol", { class: "plan-steps" }, j.steps.map((s) => h("li", {}, s.description))),
      h("details", { class: "more" }, h("summary", {}, "Technical details"),
        h("ul", { class: "steps" }, j.steps.map((s) => h("li", {}, h("span", { class: "ic" }, "·"), h("small", {}, `${s.call} ${s.args}`))))),
      h("div", { class: "row mt" },
        h("button", { class: "btn btn-primary", type: "button", onclick: () => act(`/api/plan/${j.id}/run`, {}) }, "Run plan"), dismiss));
  }
  const title = { clarify: "JARVIS has a question", cannot: "Can't do this yet", failed: "Couldn't make a plan" }[j.kind] || j.kind;
  return h("div", { class: "job" }, h("div", { class: "kicker" }, title), h("div", { class: "job-title" }, j.message),
    h("div", { class: "row mt" },
      j.kind === "clarify" ? h("button", { class: "btn btn-primary btn-sm", type: "button", onclick: () => {
        $("#cmd").value = `${j.request}\nAnswer: `; setMode("do"); act(`/api/plan/${j.id}/discard`, {});
      } }, "Answer") : null, dismiss));
}

function renderFeed(d) {
  const items = ui.convo.slice(-30).map((m) => m.role === "user"
    ? h("div", { class: "msg user" }, m.text)
    : m.consent ? h("div", { class: "job consent" },
        h("div", { class: "kicker" }, "Send to Claude?"),
        h("div", { class: "d-target" }, m.text),
        h("div", { class: "row mt" },
          h("button", { class: "btn btn-approve btn-sm", type: "button", onclick: () => consent(m, true) }, "Send to Claude"),
          h("button", { class: "btn btn-sm", type: "button", onclick: () => consent(m, false) },
            m.endpoint === "/api/research" ? "Don't research" : "Answer locally")))
    : m.briefing ? briefingCard(m)
    : h("div", { class: `msg jarvis${m.error ? " err" : ""}` }, h("span", { class: "who" }, "JARVIS"), m.text,
        m.sources && m.sources.length ? h("ul", { class: "sources" }, m.sources.filter((s) => /^https?:\/\//.test(s.url)).map((s) =>
          h("li", { class: s.verified ? "ok" : "warn" },
            h("a", { href: s.url, target: "_blank", rel: "noopener noreferrer" }, s.url.replace(/^https?:\/\//, "")),
            s.verified ? " ✓" : " — not seen by the research tools"))) : null,
        m.meta ? h("span", { class: "meta" }, m.meta) : null));
  if (ui.chatBusy) items.push(h("div", { class: "msg jarvis" }, h("span", { class: "who typing" }, "JARVIS")));
  if (d) items.push(...d.jobs.filter((j) => j.state !== "submitted").reverse().map(jobCard));
  const feed = $("#feed");
  const key = JSON.stringify([ui.convo.length, ui.convo.map((m) => m.approval_id || ""), ui.chatBusy, d && d.jobs.map((j) => [j.id, j.state, j.elapsed, j.kind])]);
  if (key === ui.lastFeed) return;            // avoid re-rendering (and losing scroll/focus) when nothing changed
  ui.lastFeed = key;
  const nearBottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 60;
  feed.replaceChildren(...items);
  if (nearBottom) feed.scrollTop = feed.scrollHeight;
}

// ---------------------------------------------------------------- morning briefing (built live, never stored)
function briefingCard(m) {
  const b = m.briefing;
  return h("div", { class: "job briefing" },
    h("div", { class: "kicker" }, `Briefing · since ${new Date(b.since).toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit", hour12: false })}`),
    h("div", { class: "job-title" }, b.headline),
    b.sections.length ? b.sections.map((s) => h("div", { class: `brief-sec${s.alert ? " alert" : ""}` },
      h("h3", {}, s.title), h("ul", {}, s.items.map((i) => h("li", {}, i)))))
      : h("div", { class: "d-why" }, "All quiet: nothing finished, failed or broke since the last briefing."),
    h("div", { class: "row mt" }, h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: () => {
      ui.convo = ui.convo.filter((x) => x !== m); render(); } }, "Dismiss")));
}

async function showBriefing() {
  try {
    const b = await api("/api/briefing");
    ui.convo = ui.convo.filter((x) => !x.briefing);
    ui.convo.push({ role: "assistant", briefing: b });
    render();
  } catch (e) { note(e.message); }
}

function maybeAutoBriefing(d) {
  // Show today's briefing once per device when it's ready (or when opened from the notification).
  const today = localDate();
  let shown = null;
  try { shown = localStorage.getItem("jarvis-briefing"); } catch (e) { /* storage unavailable: show from the link only */ }
  const fromLink = location.hash === "#briefing";
  if (fromLink) history.replaceState(null, "", location.pathname);
  if (fromLink || (d && d.briefing && d.briefing.last_date && d.briefing.last_date === today && shown !== today)) {
    try { localStorage.setItem("jarvis-briefing", today); } catch (e) { /* ignore */ }
    showBriefing();
  }
}
const localDate = () => { const n = new Date(); return `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, "0")}-${String(n.getDate()).padStart(2, "0")}`; };

// ---------------------------------------------------------------- missions
const ICON = { done: "✓", started: "›", pending: "·", failed: "✗", uncertain: "?", skipped: "–" };

function missionCard(t) {
  const done = t.steps.filter((s) => s.state === "done" || s.state === "skipped").length;
  const cls = NEEDS.includes(t.state) ? "needs" : ACTIVE.includes(t.state) ? "active"
    : t.state === "completed" ? "done" : ["failed", "cancelled"].includes(t.state) ? "bad" : "";
  const cur = t.steps.find((s) => s.state === "started") || t.steps.find((s) => s.state === "pending");
  const files = (t.evidence && t.evidence.files) || [];
  const controls = [];
  if (["queued", "running", "awaiting_approval"].includes(t.state)) controls.push(h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: () => act(`/api/tasks/${t.id}/pause`, {}) }, "Pause"));
  if (["paused", "blocked"].includes(t.state)) controls.push(h("button", { class: "btn btn-sm", type: "button", onclick: () => act(`/api/tasks/${t.id}/resume`, {}) }, "Resume"));
  if (!["completed", "failed", "cancelled"].includes(t.state)) controls.push(h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: () => confirm("Cancel this task? Steps already done are not undone.") && act(`/api/tasks/${t.id}/cancel`, {}) }, "Cancel"));

  const details = h("details", { class: "more" }, h("summary", {}, `${done}/${t.steps.length} steps · details`),
    h("ol", { class: "steps" }, t.steps.map((s) => h("li", { class: s.state }, h("span", { class: "ic" }, ICON[s.state] || "·"),
      h("div", {}, s.description, h("small", {}, s.call + (s.attempts > 1 ? ` · attempt ${s.attempts}` : "")),
        s.error ? h("div", { class: "m-err" }, s.error) : null)))),
    t.final_text ? h("pre", { class: "out" }, t.final_text) : null);
  if (ui.open.has(t.id)) details.open = true;
  details.addEventListener("toggle", () => details.open ? ui.open.add(t.id) : ui.open.delete(t.id));

  return h("article", { class: `mission ${cls}` },
    h("div", { class: "m-state" }, STATE_WORDS[t.state] || t.state),
    h("div", { class: "m-title" }, t.goal),
    h("div", { class: "segs", role: "progressbar", "aria-label": "Progress", "aria-valuemin": 0, "aria-valuemax": t.steps.length, "aria-valuenow": done },
      t.steps.map((s) => h("i", { class: s.state, title: `${s.description} — ${s.state}` }))),
    cur && !["completed", "failed", "cancelled"].includes(t.state) ? h("div", { class: "m-now" }, "Now: ", h("b", {}, cur.description)) : null,
    t.state === "failed" && t.error ? h("div", { class: "m-err" }, t.error) : null,
    t.state === "blocked" && t.next_action ? h("div", { class: "m-err" }, t.next_action) : null,
    files.map((f) => h("div", { class: `m-ok${f.content_matches ? "" : " bad"}`, title: f.path },
      f.content_matches ? `✓ Saved & verified · ${base(f.path)}` : `✗ Verification failed · ${base(f.path)}`)),
    details,
    controls.length ? h("div", { class: "row mt" }, controls) : null);
}

function renderMissions(tasks) {
  const live = tasks.filter((t) => ![...["completed", "failed", "cancelled"]].includes(t.state)).length;
  $("#miscount").textContent = live ? `${live} live` : "";
  $("#missions").replaceChildren(...(tasks.length ? tasks.slice(0, 12).map(missionCard)
    : [h("div", { class: "empty" }, "No missions yet. Switch to Do and describe a task.")]));
}

// ---------------------------------------------------------------- decisions
function renderDecisions(list) {
  const panel = $("#decision-panel");
  panel.classList.toggle("has-items", list.length > 0);
  $("#ap-h").textContent = list.length ? "Decision required" : "Decisions";
  $("#apcount").textContent = list.length > 1 ? String(list.length) : "";
  if (!list.length) { $("#approvals").replaceChildren(h("div", { class: "empty" }, "Nothing waiting for you.")); return; }
  $("#approvals").replaceChildren(...list.map((a) => {
    const target = a.resource && a.tool === "fs" ? h("div", { class: "d-target", title: a.resource }, "→ ", h("b", {}, base(a.resource)), ` in ${folder(a.resource)}`)
      : a.resource ? h("div", { class: "d-target" }, a.resource) : null;
    return h("article", { class: "decision" },
      h("div", { class: "d-kind" }, decisionKind(a)),
      h("div", { class: "d-title" }, a.summary.split(" — ")[0]),
      target,
      h("div", { class: "d-why" }, a.reason === "no standing policy covers this action" ? "Asking because no standing permission covers this." : a.reason),
      a.preview !== null ? h("pre", { class: "out", "aria-label": "Exactly what will be written" }, a.preview) : null,
      h("div", { class: "row mt" },
        h("button", { class: "btn btn-approve", type: "button", onclick: () => act(`/api/approvals/${a.id}`, { approve: true }) }, "Approve"),
        h("button", { class: "btn btn-danger", type: "button", onclick: () => act(`/api/approvals/${a.id}`, { approve: false }) }, "Reject")));
  }));
}

// ---------------------------------------------------------------- systems & activity
function renderSystems(d) {
  const m = d.models || { providers: [], budget: {} };
  const lights = [];
  for (const p of m.providers) {
    for (const id of p.configured) {
      const on = p.available.includes(id);
      lights.push(h("div", { class: `light${on ? " on" : ""}`, title: on ? "online" : (p.error || "not installed") },
        h("i"), id, h("small", {}, on ? (p.location === "local" ? "local" : "cloud") : "offline")));
    }
  }
  const chain = d.audit_chain;
  const ro = (label, value, cls) => h("div", { class: "ro" }, h("span", {}, label), h("b", { class: cls || null }, value));
  const health = d.health;
  const healthBlock = health ? h("div", { class: "health" },
    h("div", { class: `health-head ${health.ok ? "ok" : "bad"}` },
      health.ok ? "✓ All systems healthy" : "⚠ Needs attention", h("small", {}, health.service ? "background service" : "running in Terminal")),
    health.items.filter((i) => !i.ok || ["Backups"].includes(i.name)).map((i) =>
      h("div", { class: `light${i.ok ? " on" : ""}`, title: i.detail }, h("i"), i.name, h("small", {}, i.detail))))
    : null;
  const rem = d.remote || { enabled: false, devices: [] };
  const live = rem.devices.filter((x) => !x.revoked_at);
  const phone = h("div", { class: "devices" },
    h("div", { class: "ro" }, h("span", {}, "Phone"),
      h("b", {}, rem.this_device ? `This device · ${rem.this_device.name}` : !rem.enabled ? "Not set up" : live.length ? plural(live.length, "paired device") : "None paired")),
    live.map((x) => h("div", { class: "device-row" }, x.name,
      h("small", {}, x.last_seen ? `seen ${clock(x.last_seen)}` : "never signed in"),
      h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: () =>
        confirm(`Remove ${x.name}? It will be signed out immediately and can't reconnect without pairing again.`) &&
        act(`/api/devices/${x.id}/revoke`, {}) }, "Remove"))),
    !rem.this_device && rem.enabled ? h("button", { class: "btn btn-sm mt", type: "button", onclick: pairPhone }, "Pair a phone") : null,
    !rem.enabled && !rem.this_device ? h("div", { class: "d-why" }, "Run `uv run jarvis remote enable` on the Mac to use JARVIS from your iPhone.") : null,
    rem.this_device ? h("div", { class: "row mt" },
      "PushManager" in window ? h("button", { class: "btn btn-sm", type: "button", onclick: enableNotifications }, "Enable notifications") : null,
      h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: async () => { await api("/api/logout", {}); location.reload(); } }, "Sign out")) : null);
  const tid = d.touch_id || { enabled: false, keys: [] };
  const touch = onPhone() ? null : h("div", { class: "devices" },
    h("div", { class: "ro" }, h("span", {}, "Touch ID"),
      h("b", { class: tid.enabled ? "ok" : null }, tid.enabled ? `On · ${plural(tid.keys.length, "key")}` : "Off")),
    tid.keys.map((k) => h("div", { class: "device-row" }, k.name,
      h("small", {}, k.last_seen ? `used ${clock(k.last_seen)}` : "not used yet"),
      h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: () =>
        confirm(tid.keys.length === 1 ? "Remove your only Touch ID key? Approvals will stop asking for Touch ID." : `Remove ${k.name}?`) &&
        act(`/api/touchid/${k.id}/remove`, {}) }, "Remove"))),
    h("button", { class: "btn btn-sm mt", type: "button", onclick: setupTouchId }, tid.enabled ? "Add another key" : "Set up Touch ID"),
    tid.enabled ? null : h("div", { class: "d-why" }, "Then every approval here asks for your fingerprint, not just this browser's sign-in."));
  $("#system").replaceChildren(
    healthBlock, touch, phone,
    h("div", { class: "lights" }, lights.length ? lights : h("div", { class: "empty" }, "No models configured")),
    h("div", { class: "readouts" },
      ro("Privacy", (m.disabled_providers || []).length && !m.providers.some((p) => p.location === "cloud") ? "Local only" : "Cloud allowed with approval"),
      ro("Routing", { local_first: "Local first", best: "Best model", hybrid: "Hybrid (saves Claude usage)" }[m.routing_mode] || m.routing_mode || "—"),
      ...(m.cloud_usage || []).map((u) => ro(`${u.provider} · 5h`, u.limited_until
        ? `At limit · resets ~${clock(u.limited_until)}` : `${u.calls} calls · ${(u.tokens / 1000).toFixed(1)}k tokens`, u.limited_until ? "bad" : null)),
      ro("Budget", `$${(m.budget.spent_this_month_usd || 0).toFixed(2)} of $${(m.budget.monthly_limit_usd || 0).toFixed(2)}`),
      ro("Audit log", chain ? (chain.ok ? `Intact · ${chain.checked}` : `Broken at #${chain.first_bad_seq}`) : "Checking…", chain ? (chain.ok ? "ok" : "bad") : null),
      ro("Folders", d.roots.length ? d.roots.map(base).join(", ") : "None approved"),
      ro("Version", d.version)));
}

async function setupTouchId() {
  if (!window.PublicKeyCredential) { note("This browser can't use Touch ID passkeys. Try Safari or Chrome."); return; }
  const name = (prompt("Name this key (e.g. Safari on MacBook):", "This Mac") || "").trim();
  if (!name) return;
  try {
    const o = await call("/api/touchid/enroll/options", { name });
    const p = o.publicKey;
    const c = await navigator.credentials.create({ publicKey: {
      ...p, challenge: b64u.toBuf(p.challenge), user: { ...p.user, id: b64u.toBuf(p.user.id) },
      authenticatorSelection: { ...p.authenticatorSelection, authenticatorAttachment: "platform" },
      excludeCredentials: p.excludeCredentials.map((x) => ({ ...x, id: b64u.toBuf(x.id) })) } });
    await api("/api/touchid/enroll/finish", { name, challengeId: o.challengeId, credential: { ...credJSON(c),
      response: { clientDataJSON: b64u.fromBuf(c.response.clientDataJSON), attestationObject: b64u.fromBuf(c.response.attestationObject) } } });
    ui.convo.push({ role: "assistant", text: "Touch ID is on. Approvals here now ask for your fingerprint." });
  } catch (e) { note(cancelled(e)); }
  await refresh();
}

async function pairPhone() {
  let r;
  try { r = await call("/api/devices/pair", {}); } catch (e) { note(cancelled(e)); return; }
  const qr = qrcode(0, "M");
  qr.addData(r.url);
  qr.make();
  const n = qr.getModuleCount(), scale = 6, canvas = h("canvas", { width: n * scale, height: n * scale, "aria-label": "Pairing QR code" });
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, n * scale, n * scale); ctx.fillStyle = "#000";
  for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) if (qr.isDark(y, x)) ctx.fillRect(x * scale, y * scale, scale, scale);
  const dlg = h("dialog", { class: "pairdlg" },
    h("h2", {}, "Pair your iPhone"),
    h("p", { class: "hl-sub" }, "Make sure Tailscale is on on your iPhone, then scan this with the Camera app. Valid for 10 minutes, once."),
    canvas, h("div", { class: "url" }, r.url),
    h("button", { class: "btn mt", type: "button", onclick: () => { dlg.close(); dlg.remove(); } }, "Done"));
  document.body.append(dlg);
  dlg.showModal();
}

async function enableNotifications() {
  try {
    const reg = await navigator.serviceWorker.ready;
    if (await Notification.requestPermission() !== "granted") { note("Notifications are off for JARVIS in iPhone Settings."); return; }
    const { key } = await api("/api/push/key");
    const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64u.toBuf(key) });
    await api("/api/push/subscribe", { subscription: sub.toJSON() });
    note("Notifications on. They only ever say things like “JARVIS needs a decision” — never your content.");
  } catch (e) { note(`Couldn't turn on notifications: ${e.message}. On iPhone, add JARVIS to your Home Screen first.`); }
}

function renderActivity(entries) {
  $("#ticker").replaceChildren(...entries.slice(0, 6).map((e) => h("li", {}, h("time", {}, clock(e.ts)), e.detail)));
  $("#activity").replaceChildren(...entries.map((e) => h("li", {}, h("time", {}, clock(e.ts)), h("span", {}, e.detail))));
}

// ---------------------------------------------------------------- memory
async function loadMemory(force) {
  const counts = ui.data && ui.data.memory;
  const key = JSON.stringify([ui.memQ, counts]);
  if (!force && key === ui.memKey) return;
  ui.memKey = key;
  let res;
  try { res = await api(`/api/memory?q=${encodeURIComponent(ui.memQ)}`); } catch (e) { return; }
  const c = res.counts;
  $("#memcount").textContent = c.memories ? `${c.memories}${c.unconfirmed ? ` · ${c.unconfirmed} to review` : ""}` : "";
  const items = res.memories.map((m) => {
    const confirmed = m.origin === "explicit";
    return h("article", { class: `mem ${confirmed ? "confirmed" : "unconfirmed"}` },
      h("div", { class: "mem-text" }, m.important ? h("span", { class: "mem-star", title: "Important" }, "★ ") : null, m.text),
      h("div", { class: "mem-meta" }, h("b", {}, confirmed ? "Confirmed" : "Unconfirmed"), ` · ${m.kind} · ${m.created_at.slice(0, 10)}`),
      h("div", { class: "row" },
        confirmed ? null : h("button", { class: "btn btn-sm", type: "button", onclick: () => memAct(`/api/memory/${m.id}/confirm`, {}) }, "Confirm"),
        h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: () => {
          const t = prompt("Correct this memory:", m.text); if (t && t.trim() && t !== m.text) memAct(`/api/memory/${m.id}/edit`, { text: t });
        } }, "Edit"),
        h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: () => memAct(`/api/memory/${m.id}/important`, { important: !m.important }) }, m.important ? "Unstar" : "Star"),
        h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: () => confirm("Delete this memory? JARVIS won't re-learn it.") && memAct(`/api/memory/${m.id}/delete`, {}) }, "Delete")));
  });
  if (ui.memQ && (res.memories.length || res.records.length)) {
    items.push(h("div", { class: "row" }, h("span", { class: "mem-meta" }, `${plural(res.records.length, "conversation")} mention this`),
      h("button", { class: "btn btn-danger btn-sm", type: "button", onclick: forgetMatching }, "Forget all of this")));
  }
  $("#memlist").replaceChildren(...(items.length ? items : [h("div", { class: "empty" },
    ui.memQ ? "Nothing remembered about that." : "Nothing remembered yet. Tell JARVIS something, or say “remember that…” in chat.")]));
}

async function memAct(path, body) {
  try { await call(path, body); } catch (e) { note(cancelled(e)); }
  await refresh(); await loadMemory(true);
}

async function forgetMatching() {
  const preview = await api("/api/memory/forget", { query: ui.memQ });
  const tasks = (preview.tasks || []).filter((t) => t.deletable).length;
  if (!confirm(`Permanently delete ${plural(preview.memories.length, "memory").replace("memorys", "memories")}, ${plural(preview.records.length, "conversation record")} and ${plural(tasks, "finished task")} about “${ui.memQ}”?`)) return;
  await memAct("/api/memory/forget", { query: ui.memQ, confirm: true });
}

// ---------------------------------------------------------------- loop
function render() {
  const d = ui.data;
  renderHead(d);
  renderFeed(d);
  if (!d) return;
  renderMissions(d.tasks);
  renderDecisions(d.approvals);
  renderSystems(d);
  renderActivity(d.audit);
  loadMemory(false);
}

async function act(path, body) {
  try { await call(path, body); } catch (e) { note(cancelled(e)); }
  await refresh();
}

async function refresh() {
  try { ui.data = await api("/api/state"); ui.online = true; }
  catch (e) { ui.online = false; if (/not signed in/.test(e.message)) { location.reload(); return; } }
  render();
  maybeAutoBriefing(ui.data);
}

document.addEventListener("DOMContentLoaded", () => {
  $("#tab-ask").addEventListener("click", () => setMode("ask"));
  $("#tab-do").addEventListener("click", () => setMode("do"));
  $("#tab-research").addEventListener("click", () => setMode("research"));
  $("#cmdform").addEventListener("submit", submitCommand);
  $("#cmd").addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submitCommand(e); });
  $("#estop").addEventListener("click", () => {
    const reason = prompt("Emergency stop — pause every task and block new actions.\nReason (optional):", "");
    if (reason !== null) act("/api/stop", { reason: reason || "stopped from dashboard" });
  });
  $("#briefbtn").addEventListener("click", showBriefing);
  window.addEventListener("hashchange", () => maybeAutoBriefing(ui.data));
  $("#release").addEventListener("click", () => {
    if (confirm("Release the emergency stop? Paused tasks stay paused until you resume them.")) act("/api/release", { confirm: true });
  });
  let memTimer;
  $("#memq").addEventListener("input", () => { clearTimeout(memTimer); memTimer = setTimeout(() => { ui.memQ = $("#memq").value.trim(); loadMemory(true); }, 250); });
  $("#memsearch").addEventListener("submit", (e) => e.preventDefault());
  $("#memadd").addEventListener("submit", async (e) => {
    e.preventDefault();
    const t = $("#memtext").value.trim();
    if (!t) return;
    await memAct("/api/memory/remember", { text: t });
    $("#memtext").value = "";
  });
  $("#logbtn").addEventListener("click", () => $("#logdlg").showModal());
  $("#logclose").addEventListener("click", () => $("#logdlg").close());
  const tick = () => { $("#clock").textContent = new Date().toLocaleTimeString([], { hour12: false }); };
  tick(); setInterval(tick, 1000);
  setMode("ask");
  if ("serviceWorker" in navigator && location.protocol === "https:") navigator.serviceWorker.register("/sw.js").catch(() => {});
  refresh();
  setInterval(refresh, 1500);
});
