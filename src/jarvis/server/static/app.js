"use strict";
// JARVIS command centre. Renders only real state from /api/state. All data is inserted as text
// (never as HTML), so content from files or web pages cannot inject markup or scripts.

const $ = (s) => document.querySelector(s);
const ui = { mode: "ask", data: null, convo: [], chatBusy: false, online: true, open: new Set(), lastFeed: "",
             intel: "balanced", stage: null, abort: null, editIndex: null, copied: null,
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

// In-page confirm/prompt. The browser's own dialogs are unreliable in the iPhone Home Screen app and blocked in
// embedded previews. Resolves to true/false, or to the typed text / null when `input` is given.
function ask(message, { input = null, ok = "OK", danger = false } = {}) {
  return new Promise((resolve) => {
    const field = input === null ? null : h("input", { class: "ask-input", id: "ask-input", autocomplete: "off", "aria-label": message });
    if (field) field.value = input;
    const finish = (v) => { dlg.close(); dlg.remove(); resolve(v); };
    const yes = h("button", { class: `btn ${danger ? "btn-danger" : "btn-approve"}`, type: "submit" }, ok);
    const dlg = h("dialog", { class: "pairdlg askdlg", "aria-label": message },
      h("form", { onsubmit: (e) => { e.preventDefault(); finish(field ? field.value : true); } },
        h("p", { class: "ask-msg" }, message), field,
        h("div", { class: "row mt center" }, yes,
          h("button", { class: "btn btn-ghost", type: "button", onclick: () => finish(field ? null : false) }, "Cancel"))));
    dlg.addEventListener("cancel", (e) => { e.preventDefault(); finish(field ? null : false); });
    document.body.append(dlg);
    dlg.showModal();
    (field || yes).focus();
  });
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
// The fingerprint is for signing in. After that only the dangerous few ask again (must match the server's STEP_UP,
// which enforces it regardless of what this page does): releasing the emergency stop, changing or forgetting
// memories, removing a phone, plus approving a high-risk action (risk tier 4).
const FACE_ID = [/^\/api\/release$/, /^\/api\/memory\/[\w-]+\/(delete|edit)$/, /^\/api\/devices\/[\w-]+\/revoke$/];
const TOUCH_ID = [...FACE_ID, /^\/api\/update\/start$/, /^\/api\/devices\/pair$/, /^\/api\/touchid\/enroll\/options$/, /^\/api\/touchid\/[\w-]+\/remove$/];
const HIGH_RISK = 4;
const highRiskApproval = (path, body) => {
  const m = path.match(/^\/api\/approvals\/([\w-]+)$/);
  if (!m || !body || body.approve !== true) return false;
  const a = ui.data && ui.data.approvals.find((x) => x.id === m[1]);
  return !!a && a.tier >= HIGH_RISK;
};
const onPhone = () => !!(ui.data && ui.data.remote && ui.data.remote.this_device);
const touchIdOn = () => !onPhone() && !!(ui.data && ui.data.touch_id && ui.data.touch_id.enabled);
const bio = () => (onPhone() ? "Face ID" : "Touch ID");
const cancelled = (e) => (e.name === "NotAllowedError" ? `${bio()} was cancelled.` : e.message);
const credJSON = (c) => ({ id: c.id, rawId: b64u.fromBuf(c.rawId), type: c.type });

// iPhone Safari before iOS 17.4 only shows Face ID when it's called straight from a tap, and we fetch a
// challenge first. If Safari refuses at once, ask for one more tap and call it again from inside that tap.
async function withTap(op, label) {
  const t0 = Date.now();
  try { return await op(); } catch (e) {
    if (e.name !== "NotAllowedError" || Date.now() - t0 > 1500) throw e;
    return new Promise((resolve, reject) => {
      const done = () => { dlg.close(); dlg.remove(); };
      const dlg = h("dialog", { class: "pairdlg" },
        h("h2", {}, label),
        h("p", { class: "hl-sub" }, `Your device needs one more tap to show ${bio()}.`),
        h("div", { class: "row mt center" },
          h("button", { class: "btn btn-approve", type: "button", onclick: () => { done(); op().then(resolve, reject); } }, label),
          h("button", { class: "btn", type: "button", onclick: () => { done(); reject(e); } }, "Cancel")));
      document.body.append(dlg);
      dlg.showModal();
    });
  }
}

async function call(path, body) {
  const list = onPhone() ? FACE_ID : touchIdOn() ? TOUCH_ID : [];
  const needs = list.some((r) => r.test(path)) || ((onPhone() || touchIdOn()) && path === "/api/memory/forget" && body.confirm === true)
    || ((onPhone() || touchIdOn()) && highRiskApproval(path, body));
  if (!needs) {
    try { return await api(path, body); }
    catch (e) { if (!/is required for this action/.test(e.message)) throw e; }  // the server knows best: ask, then retry
  }
  const o = await api("/api/stepup/options", { path, body });
  const a = await withTap(() => navigator.credentials.get({ publicKey: {
    challenge: b64u.toBuf(o.challenge), rpId: o.rpId, timeout: o.timeout, userVerification: o.userVerification,
    allowCredentials: o.allowCredentials.map((c) => ({ ...c, id: b64u.toBuf(c.id) })) } }), `Confirm with ${bio()}`);
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
  const mac = { "calendar.add": "Add a calendar event", "reminders.add": "Add a reminder", "reminders.complete": "Tick off a reminder",
                "notes.create": "Create a note", "mail.draft": "Create an email draft", "apps.open": "Open an app" };
  if (mac[`${a.tool}.${a.action}`]) return mac[`${a.tool}.${a.action}`];
  return "Action";
}

// ---------------------------------------------------------------- headline, core, stats
function situation(d) {
  if (!ui.online) return { core: "offline", cls: "stopped", kicker: "Link lost", main: "Connection to JARVIS lost", sub: "Retrying… is `jarvis dashboard` still running in Terminal?" };
  if (!d) return { core: "connecting", cls: "", kicker: "Status", main: "Connecting…", sub: "" };
  if (d.emergency_stop) return { core: "stopped", cls: "stopped", kicker: "Emergency stop", main: "All actions halted", sub: `${d.emergency_stop.reason} — release the stop when you're ready.` };
  if (d.approvals.length) {
    const a = d.approvals[0];
    return { core: "attention", cls: "attention", kicker: "Decision required",
             main: a.summary.split(" — ")[0], sub: d.approvals.length > 1 ? `${d.approvals.length} decisions are waiting in Decisions.` : "Review it in Decisions." };
  }
  const blocked = d.tasks.find((t) => t.state === "blocked");
  if (blocked) return { core: "blocked", cls: "attention", kicker: "Needs your input", main: blocked.goal, sub: blocked.next_action || "This task needs your input." };
  // a mission that is actually doing something outranks one that is only queued
  const run = d.tasks.find((t) => ACTIVE.includes(t.state) && t.state !== "queued") || d.tasks.find((t) => t.state === "queued");
  if (run && run.state === "queued") return { core: "queued", cls: "", kicker: "Queued", main: run.goal, sub: "Starts as soon as the runner picks it up." };
  if (run) {
    const i = run.steps.findIndex((s) => s.state === "started" || s.state === "pending");
    const step = run.steps[i];
    if (run.state === "recovering") return { core: "recovering", cls: "", kicker: "Recovering", main: run.goal,
                                             sub: "Checking what finished before the interruption; uncertain steps are never repeated automatically." };
    return { core: "executing", cls: "", kicker: run.state === "verifying" ? "Verifying" : "Executing",
             main: run.goal, sub: step ? `Step ${i + 1} of ${run.steps.length} · ${step.description}` : "Checking the result" };
  }
  const job = d.jobs.find((j) => j.state === "planning" || j.state === "waiting_approval");
  if (job) return { core: "planning", cls: "", kicker: "Planning", main: job.request, sub: `Working out the steps · ${job.elapsed}s (about a minute on this Mac)` };
  if (ui.chatBusy && ui.chatEndpoint === "/api/research") return { core: "researching", cls: "", kicker: "Researching", main: "Searching the web", sub: "Every source is checked before it's cited." };
  if (ui.chatBusy && ui.stage) return { core: "thinking", cls: "", kicker: STAGE_KICKER[ui.stage.stage] || "Thinking", main: stageLabel(ui.stage).replace(/^Writing · /, ""), sub: "" };
  if (ui.chatBusy) return { core: "thinking", cls: "", kicker: "Thinking", main: "Composing a reply", sub: "" };
  const online = d.models ? d.models.providers.reduce((n, p) => n + p.available.length, 0) : 0;
  if (d.models && !online) return { core: "degraded", cls: "attention", kicker: "Systems", main: "No model available", sub: "Is Ollama running? Open the Ollama app, then wait a few seconds." };
  const problems = d.health && d.health.items ? d.health.items.filter((x) => !x.ok) : [];
  if (problems.length) return { core: "online", cls: "", warn: true, kicker: `${plural(problems.length, "system")} to check`, main: `${greeting()}.`,
    sub: `${plural(online, "model")} online · ${problems.map((x) => x.name).join(", ")} — details in Command center.` };
  return { core: "online", cls: "", kicker: "All systems nominal", main: `${greeting()}.`, sub: `${plural(online, "model")} online · nothing needs you right now.` };
}

// ---------------------------------------------------------------- holographic core (avatar.js) and adaptive layout
// The avatar shows the same truth as the reactor, in more detail: each of its states comes from situation(), the
// live chat stage or a voice event; nothing is staged for effect.
function avatarState(s, d) {
  const core = $("#core");
  if (core.dataset.flash === "done") return "completed";              // a task just completed
  if (core.dataset.flash === "failed") return "error";                // a task just failed
  if (core.dataset.listening) return "listening";                     // the microphone is recording
  if (refusedJustNow(d) && s.core !== "stopped" && s.core !== "offline") return "disagreeing";   // your rules refused an action
  switch (s.core) {
    case "connecting": return "unknown";                              // no data yet: neutral
    case "offline": return "error";                                   // the dashboard lost JARVIS
    case "stopped": return "halted";                                  // you pressed the emergency stop
    case "degraded": return "warning";                                // no model available
    case "attention": case "blocked": return "approval";              // a decision or input is needed
    case "executing": return s.kicker === "Verifying" ? "verifying" : "executing";
    case "recovering": return "recovery";                             // a task is being recovered after a restart
    case "planning": return "planning";
    case "queued": return "idle";                                     // waiting for the runner: nothing is running yet
    case "researching": return "researching";
    case "thinking": {                                                // the live chat stream's real stages
      const st = ui.stage && ui.stage.stage;
      const live = ui.convo.find((m) => m.live);
      if (st === "lookup") return "researching";
      if (st === "checking") return ui.stage.code_test ? "coding" : "verifying";
      if (st === "generating") return !live || !live.text ? "reasoning" : (live.text.includes("```") ? "coding" : "writing");
      return "understanding";
    }
    default: break;
  }
  if (core.dataset.speaking) return "speaking";                       // the speech engine is speaking
  if (ui.reconnectedAt && Date.now() - ui.reconnectedAt < 4000) return "recovery";
  if (criticalProblem(d)) return "error";                             // database or audit log failing
  if (ui.typingAt && Date.now() - ui.typingAt < 2500 && !ui.chatBusy) return "listening";   // you are typing to JARVIS
  const L = d && d.learn && d.learn.summary;
  if (L && L.experiments_running) return "experimenting";              // a lab experiment is really running
  if (ui.analyzingUntil && Date.now() < ui.analyzingUntil) return "analyzing";   // JARVIS is reading its own data for a projection
  if (L && L.lessons_new_at && L.lessons_new_at !== ui.seenLessonAt) {   // a lesson was just learned or reinforced
    if (ui.seenLessonAt !== undefined) { ui.learnedAt = Date.now(); }
    ui.seenLessonAt = L.lessons_new_at;
  }
  if (ui.learnedAt && Date.now() - ui.learnedAt < 4000) return "learning";
  if (s.warn) return "warning";                                       // a health check is failing (standing condition)
  return "idle";
}

// A new permission.denied / egress.denied entry in the audit log since the last poll (avatar-events.js). The first
// poll only records where the log is, so an old refusal never replays; each new one shows for about 3 s.
function refusedJustNow(d) {
  if (!d || !Array.isArray(d.audit) || !window.JarvisEvents) return false;
  const newest = d.audit.length ? d.audit[0].seq : 0;
  if (ui.auditSeen === undefined) { ui.auditSeen = newest; return false; }
  const hit = JarvisEvents.fromAudit(d.audit, ui.auditSeen);
  if (newest > ui.auditSeen) ui.auditSeen = newest;
  if (hit) ui.refusedAt = Date.now();
  return !!ui.refusedAt && Date.now() - ui.refusedAt < 3000;
}

// Only these count as critical (red): JARVIS's own records can't be trusted.
function criticalProblem(d) {
  if (!d) return false;
  if (d.audit_chain && d.audit_chain.ok === false) return true;
  return !!(d.health && d.health.items && d.health.items.some((i) => !i.ok && (i.name === "Database" || i.name === "Audit log")));
}

// What the page is mostly about right now; CSS gives that work the space (avatar.css: data-activity).
function activityOf(d) {
  const core = $("#core");
  if (core.dataset.listening || core.dataset.speaking) return "voice";
  if (ui.chatBusy && ui.chatEndpoint === "/api/research") return "research";
  if (d && (d.tasks.some((t) => ACTIVE.includes(t.state)) || d.jobs.some((j) => j.state === "planning" || j.state === "waiting_approval"))) return "mission";
  const last = [...ui.convo].reverse().find((m) => m.role === "assistant" && !m.consent && !m.help && !m.welcome && !m.briefing);
  if (last && last.sources && last.sources.length) return "research";
  if (ui.convo.some((m) => m.role === "user")) return "conversation";
  return "idle";
}

function renderHead(d) {
  const s = situation(d);
  $("#core").dataset.state = s.core;
  document.body.dataset.activity = activityOf(d);
  if (window.JarvisAvatar) {
    JarvisAvatar.setState(avatarState(s, d));
    if (d && d.evolution) JarvisAvatar.setTier(displayStage(d.evolution));
  }
  renderAvTask(d);
  ui.readyText = readiness(d);
  if (window.JarvisAvatar && d && d.telemetry) JarvisAvatar.setAura(auraValues(d));
  renderWall(d);
  renderPageHud(d);
  if (window.JarvisAvatar) { autoProjection(JarvisAvatar.state); refreshProjections(); }
  if (window.JarvisAvatar && d) JarvisAvatar.setPanels(panelItems(d));
  const wrap = $(".core-wrap");
  if (d && d.evolution && wrap) wrap.title = `Core evolution: ${d.evolution.name} · ${d.evolution.verified} of ${d.evolution.total} milestones verified (details in Command center → Diagnostics)`;
  $(".headline").className = `headline ${s.cls}`;
  $("#hl-kicker").textContent = s.kicker;
  $("#hl-main").textContent = s.main;
  $("#hl-sub").textContent = s.sub;
  const pill = $("#statuspill");
  pill.dataset.state = s.core;
  if (s.warn) pill.dataset.warn = "1"; else delete pill.dataset.warn;
  $("#statustext").textContent = s.main && s.kicker !== "All systems nominal" && !s.warn ? `${s.kicker} · ${s.main}` : s.kicker;
  pill.setAttribute("href", d && d.approvals && d.approvals.length ? "#/decisions" : "#/home");
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
  ask: ["Ask JARVIS anything: a question, something to look up, or a task…",
        "JARVIS works out what you mean: questions are answered; looking things up or doing a task asks you first.   ⌘↩ to send"],
  research: ["What should JARVIS look up?", "Research: Claude searches the web and reads pages, then answers with sources. Asks before sending."],
  do: ["Describe a task — e.g. research X and save a brief to my notes", "Do: JARVIS plans the task and shows you the plan. Nothing happens until you press Run."],
};

// ---------------------------------------------------------------- intelligence modes (chat only)
const INTEL = ["quick", "balanced", "deep"];
const INTEL_LABEL = { quick: "Quick", balanced: "Balanced", deep: "Deep" };
function setIntel(mode) {
  ui.intel = INTEL.includes(mode) ? mode : "balanced";
  document.querySelectorAll("#intelmodes .imode").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.intel === ui.intel)));
  const cycle = $("#intelcycle");
  if (cycle) { cycle.textContent = INTEL_LABEL[ui.intel]; cycle.setAttribute("aria-label", `Intelligence: ${INTEL_LABEL[ui.intel]} (tap to change)`); }
  try { localStorage.setItem("jarvis-intel", ui.intel); } catch (e) { /* this visit only */ }
}

// The real stages of a chat answer, as the server reports them (never the model's private reasoning).
const STAGE_KICKER = { understanding: "Understanding", lookup: "Looking up", context: "Gathering context",
                       generating: "Writing", checking: "Verifying" };
function stageLabel(e) {
  if (!e) return "";
  if (e.stage === "understanding") return "Understanding your message";
  if (e.stage === "lookup") return `Looked up ${e.checked.join(", ")}`;
  if (e.stage === "context") return `Context: ${plural(e.memories, "memory").replace("memorys", "memories")}, ${plural(e.turns, "earlier message")}`;
  if (e.stage === "generating") {
    const where = e.location === "local" ? "on this Mac" : "in the cloud";
    return `${e.streams ? "Writing" : "Writing (this model sends its reply in one piece)"} · ${e.model.split("/").pop()} ${where}`;
  }
  if (e.stage === "checking") return e.code_test ? "Testing the code" : "Checking the answer";
  return e.stage;
}

function stopReply() { if (ui.abort) ui.abort.abort(); }

function setMode(mode) {
  ui.mode = mode;
  for (const m of Object.keys(MODES)) $(`#tab-${m}`).setAttribute("aria-selected", mode === m);
  $("#cmd").placeholder = MODES[mode][0];
  $("#modehint").textContent = touchOnly() ? MODES[mode][1].replace(/\s+⌘↩ to send$/, "") : MODES[mode][1];   // no keyboard hint on a phone
  $("#intelmodes").hidden = mode !== "ask";
  $("#intelcycle").hidden = mode !== "ask" || !!ui.abort;
  if (ui.data && $("#context")) renderContext(ui.data);
  $("#cmd").focus();
}

// The owner removed the Ask / Research / Do buttons: JARVIS works out the kind of message (rules, then a model on
// this Mac; never the cloud) and asks with one tap before looking things up or planning a task.
async function routeMessage(text) {
  try { return await api("/api/route", { text }); } catch (e) { return { mode: "ask" }; }
}
function showRouteConfirm(r) {
  const box = $("#routeconfirm");
  const task = r.mode === "do";
  const go = (mode) => () => { box.hidden = true; if (mode === "ask") ui.skipRoute = true; else setMode(mode); submitCommand({ preventDefault() {} }); };
  box.replaceChildren(
    h("span", { class: "rc-text" }, task ? "Looks like a task: JARVIS drafts a plan, and nothing runs until you approve it."
                                         : "Looks like it needs the web: JARVIS searches and answers with sources."),
    h("button", { class: "chip on", type: "button", onclick: go(r.mode) }, task ? "Plan it" : "Research it"),
    h("button", { class: "chip", type: "button", onclick: go("ask") }, "Just answer"),
    h("button", { class: "chip", type: "button", "aria-label": "Cancel", onclick: () => { box.hidden = true; $("#cmd").focus(); } }, "✕"));
  box.hidden = false;
  box.querySelector("button").focus();
}

async function submitCommand(ev) {
  ev.preventDefault();
  const text = $("#cmd").value.trim();
  if (!text) return;
  $("#routeconfirm").hidden = true;
  if (ui.mode === "ask" && !ui.skipRoute && !ui.chatBusy && ui.editIndex === null) {
    $("#send").disabled = true;
    const r = await routeMessage(text);
    $("#send").disabled = false;
    if (r.mode === "research" || r.mode === "do") { showRouteConfirm(r); return; }
    if (r.mode === "command" && r.tool) {   // a direct Mac command: no model, the permission engine decides
      ui.convo.push({ role: "user", text });
      $("#cmd").value = ""; clearDraft();
      await sendChat({ tool: r.tool, action: r.action, args: r.args }, "/api/command");
      return;
    }
    if (r.mode === "show" && r.module) {   // "show me …": open the projection and say what it shows (from its data, no model)
      ui.convo.push({ role: "user", text });
      $("#cmd").value = ""; clearDraft();
      const data = await openProjectionModule(r.module);
      ui.convo.push({ role: "assistant", text: data ? `${PROJ_TITLE[r.module]}: ${describeProjection(r.module, data)} ${data.basis}` :
        `I couldn't open the ${PROJ_TITLE[r.module]} projection here.`, meta: "projection" });
      render(); return;
    }
  }
  ui.skipRoute = false;
  if (ui.mode === "do") {
    $("#send").disabled = true;
    try { await api("/api/plan", { request: text }); $("#cmd").value = ""; clearDraft(); await refresh(); }
    catch (e) { note(`Could not start planning: ${e.message}`); }
    finally { $("#send").disabled = false; setMode("ask"); }
    return;
  }
  if (ui.chatBusy) return;
  if (ui.editIndex !== null) { ui.convo = ui.convo.slice(0, ui.editIndex); ui.editIndex = null; setMode(ui.mode); }
  ui.convo.push({ role: "user", text });
  $("#cmd").value = "";
  clearDraft();
  if (ui.mode === "research") { setMode("ask"); await sendChat({ question: text, session: ui.session }, "/api/research"); return; }
  await sendChat({ message: text, history: historyBefore(ui.convo.length - 1), session: ui.session, mode: ui.intel });
}

// The conversation before message i, as the server expects it (your messages and JARVIS's answers only).
function historyBefore(i) {
  return ui.convo.slice(0, i).filter((m) => (m.role === "user" || m.role === "assistant") && !m.error && !m.consent
    && !m.help && !m.welcome && !m.briefing && typeof m.text === "string").map((m) => ({ role: m.role, content: m.text }));
}

// Regenerate / retry: drop this answer and ask again with exactly the same message, history and mode.
async function regenerate(m) {
  if (ui.chatBusy || !m.request) return;
  ui.convo = ui.convo.filter((x) => x !== m);
  await sendChat(m.request, m.endpoint || "/api/chat");
}

// Edit and resend: your message goes back in the box; sending replaces it and everything after it.
function editMessage(i) {
  if (ui.chatBusy) return;
  ui.editIndex = i;
  setMode("ask");
  $("#cmd").value = ui.convo[i].text;
  $("#modehint").textContent = "Editing: sending replaces this message and the replies after it. Esc to cancel.";
  render();
}

function cancelEdit() {
  if (ui.editIndex === null) return;
  ui.editIndex = null;
  $("#cmd").value = "";
  setMode(ui.mode);
  render();
}

async function copyText(m) {
  try { await navigator.clipboard.writeText(m.text); ui.copied = m; }
  catch (e) { ui.copied = null; note("Couldn't copy: this browser didn't allow it."); return; }
  render();
  setTimeout(() => { if (ui.copied === m) { ui.copied = null; ui.lastFeed = ""; render(); } }, 1500);
}

// Sends a chat turn. If the best model is in the cloud and your rule is "ask every time", the server
// returns needs_approval instead of sending; we show a consent card and resend the identical request.
// Chat with a local model's reply appearing as it's written. Same answer as /api/chat; falls back to it when
// streaming isn't available (an older JARVIS, the phone preview).
async function streamChat(payload) {
  let r;
  const controller = new AbortController();
  ui.abort = controller;
  const started = performance.now();
  const live = { role: "assistant", text: "", live: true, activity: [] };
  try {
    r = await fetch("/api/chat/stream", { method: "POST", credentials: "same-origin", signal: controller.signal,
      headers: { "Content-Type": "application/json", "X-Requested-By": "jarvis" }, body: JSON.stringify(payload) });
  } catch (e) {
    if (e.name === "AbortError") return { stopped: true, partial: "", activity: live.activity };
    return api("/api/chat", payload);
  }
  if (!r.ok || !r.body || !(r.headers.get("Content-Type") || "").includes("ndjson")) return api("/api/chat", payload);
  ui.convo.push(live);
  render();
  const reader = r.body.getReader(), dec = new TextDecoder();
  let buf = "", done = null, painting = false;
  const paint = () => { painting = false; ui.liveLen = live.text.length; render(); };
  for (;;) {
    let chunk;
    try { chunk = await reader.read(); }
    catch (e) {
      ui.convo = ui.convo.filter((m) => m !== live);
      if (e.name === "AbortError") return { stopped: true, partial: live.text, activity: live.activity };
      throw e;
    }
    const { value, done: end } = chunk;
    if (end) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n")) >= 0) {
      const text = buf.slice(0, i); buf = buf.slice(i + 1);
      if (!text.trim()) continue;
      const msg = JSON.parse(text);
      if (typeof msg.t === "string") {
        if (!live.first) live.first = Math.round(performance.now() - started) / 1000;
        live.text += msg.t;
        if (!painting) { painting = true; requestAnimationFrame(paint); }
      } else if (msg.s) {
        // A new "generating" means a new attempt (the previous model failed): its words are dropped.
        if (msg.s.stage === "generating") live.text = "";
        live.activity.push({ ...msg.s, at: Math.round(performance.now() - started) / 1000 });
        ui.stage = msg.s;
        if (window.JarvisAvatar) JarvisAvatar.setThought(new Set(live.activity.map((a) => a.stage)).size, true);
        ui.liveLen = -live.activity.length;
        render();
      } else if (msg.done) done = msg.done;
    }
  }
  ui.convo = ui.convo.filter((m) => m !== live);
  if (!done) throw new Error(live.text ? "the reply was interrupted" : "no reply");
  if (done.error && live.text) done.partial = live.text;
  done.activity = live.activity;
  done.first = live.first;
  return done;
}

async function sendChat(payload, endpoint = "/api/chat") {
  ui.chatBusy = true;
  ui.chatEndpoint = endpoint;
  ui.stage = null;
  render();
  const base = { role: "assistant", request: payload, endpoint };
  try {
    const r = endpoint === "/api/chat" ? await streamChat(payload) : await api(endpoint, payload);
    if (r.stopped) ui.convo.push({ ...base, text: r.partial ? `${r.partial}\n\n— Stopped.` : "Stopped before JARVIS replied.",
      error: !r.partial, stopped: true, activity: r.activity });
    else if (r.needs_approval) ui.convo.push({ role: "assistant", consent: true, payload, endpoint, approval_id: r.approval_id, text: r.summary });
    else if (r.answer !== undefined) ui.convo.push({ ...base, text: r.answer, sources: r.sources, question: payload.question,
      rstats: { searches: r.searches.length, pages: r.pages_read.length },
      meta: [r.model.split("/").pop(), `${r.seconds}s`, `${r.searches.length} searches`, `${r.pages_read.length} pages read`,
             `${r.verified_sources}/${r.sources.length} sources verified`].join(" · ") });
    else if (r.error) ui.convo.push({ ...base, text: r.partial ? `${r.partial}\n\n— ${r.error}` : r.error, error: true, activity: r.activity });
    else ui.convo.push({ ...base, text: r.text, checked: r.checked || [], plan: r.offer_plan ? payload.message : null, activity: r.activity,
      ref: r.record || `${ui.session}:${Date.now()}`, rmodel: r.location === "local" ? `local/${String(r.model).split("/").pop()}` : r.model, rmode: r.mode,
      meta: [r.model.split("/").pop(), r.location === "cloud" ? "cloud" : null, r.mode && r.mode !== "balanced" ? INTEL_LABEL[r.mode] : null,
      r.first ? `first words ${r.first.toFixed(2)}s` : null, `${r.seconds}s`,
      r.memories_used ? `used ${plural(r.memories_used, "memory").replace("memorys", "memories")}` : null,
      r.past ? "learned from an earlier answer you rated" : null, r.note].filter(Boolean).join(" · ") });
  } catch (e) {
    ui.convo.push({ ...base, text: `Request failed: ${e.message}`, error: true });
  } finally {
    ui.chatBusy = false;
    ui.abort = null;
    ui.stage = null;
    if (window.JarvisAvatar) JarvisAvatar.setThought(0, false);
    render();
  }
  const last = ui.convo[ui.convo.length - 1];
  if (last && last.role === "assistant" && !last.error && !last.consent) say(last.text);
}

async function consent(m, approve) {
  ui.convo = ui.convo.filter((x) => x !== m);
  try { await call(`/api/approvals/${m.approval_id}`, { approve }); }
  catch (e) { if (e.name === "NotAllowedError") { ui.convo.push(m); render(); return; } /* else: already decided in Decisions */ }
  if (m.endpoint === "/api/command") {
    if (approve) await sendChat(m.payload, m.endpoint);
    else note("Not done — you said no.");
    return;
  }
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
      h("div", { class: "kicker" }, `${j.replan_of ? "New plan (second attempt)" : "Plan ready"} · ${plural(j.steps.length, "step")} · ${j.model.split("/").pop()}`),
      j.note ? h("div", { class: "d-why" }, j.note) : null,
      j.restored ? h("div", { class: "d-why" }, "Kept from before JARVIS restarted.") : null,
      j.replan_of ? h("div", { class: "d-why" }, "Planned with what happened on the first attempt, so it doesn't redo what's done.") : null,
      h("div", { class: "job-title" }, j.goal || j.request),
      h("ol", { class: "plan-steps" }, j.steps.map((s) => h("li", {}, s.description))),
      j.criteria && j.criteria.length ? h("details", { class: "more" }, h("summary", {}, "How JARVIS will check it's done"),
        h("ul", { class: "criteria" }, j.criteria.map((c) => h("li", { class: c.check }, c.text)))) : null,
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
  $("#stopgen").hidden = !ui.abort;
  $("#send").hidden = !!ui.abort;
  $("#intelmodes").hidden = ui.mode !== "ask";
  $("#intelcycle").hidden = ui.mode !== "ask" || !!ui.abort;
  const start = Math.max(0, ui.convo.length - 30);
  const items = ui.convo.slice(start).map((m, j) => m.role === "user"
    ? h("div", { class: `msg user${ui.editIndex === start + j ? " editing" : ""}` }, m.text,
        !ui.chatBusy && m.text ? h("div", { class: "msg-actions" },
          h("button", { class: "btn btn-ghost btn-xs", type: "button", title: "Edit and resend", onclick: () => editMessage(start + j) }, "Edit")) : null)
    : m.consent ? h("div", { class: "job consent" },
        h("div", { class: "kicker" }, "Send to Claude?"),
        h("div", { class: "d-target" }, m.text),
        h("div", { class: "row mt" },
          h("button", { class: "btn btn-approve btn-sm", type: "button", onclick: () => consent(m, true) }, "Send to Claude"),
          h("button", { class: "btn btn-sm", type: "button", onclick: () => consent(m, false) },
            m.endpoint === "/api/research" ? "Don't research" : "Answer locally")))
    : m.briefing ? briefingCard(m)
    : m.help ? helpCard(m)
    : m.welcome ? welcomeCard(m)
    : h("div", { class: `msg jarvis${m.error ? " err" : ""}${m.live ? " live" : ""}`, "aria-busy": m.live ? "true" : null },
        h("span", { class: "who" }, "JARVIS"), m.text,
        m.sources && m.sources.length ? h("ul", { class: "sources" }, m.sources.filter((s) => /^https?:\/\//.test(s.url)).map((s) =>
          h("li", { class: s.verified ? "ok" : "warn" },
            h("a", { href: s.url, target: "_blank", rel: "noopener noreferrer" }, s.url.replace(/^https?:\/\//, "")),
            s.verified ? " ✓" : " — not seen by the research tools"))) : null,
        m.checked && m.checked.length ? h("div", { class: "checked" }, "Checked: ", m.checked.join(" · ")) : null,
        m.plan ? h("div", { class: "row mt" }, h("button", { class: "btn btn-sm", type: "button", onclick: () => makePlan(m) },
          "Make a plan")) : null,
        m.live && ui.stage ? h("div", { class: "stage-line", role: "status" }, stageLabel(ui.stage)) : null,
        m.meta ? h("span", { class: "meta" }, m.meta) : null,
        !m.live && m.activity && m.activity.length ? h("details", { class: "activity-trail" },
          h("summary", {}, "Activity"),
          h("ol", {}, m.activity.map((e) => h("li", {}, h("span", { class: "at" }, `${e.at.toFixed(1)}s`), " ", stageLabel(e))))) : null,
        !m.live && !ui.chatBusy && m.request ? h("div", { class: "msg-actions" },
          m.text && !(m.error && !m.stopped) ? h("button", { class: "btn btn-ghost btn-xs", type: "button", title: "Copy this answer", onclick: () => copyText(m) },
            ui.copied === m ? "Copied" : "Copy") : null,
          h("button", { class: "btn btn-ghost btn-xs", type: "button", title: "Ask again with the same message",
                        onclick: () => regenerate(m) }, m.error ? "Retry" : "Regenerate"),
          m.ref ? h("span", { class: "rate", role: "group", "aria-label": "Was this helpful?" },
            [[1, "👍", "Helpful"], [-1, "👎", "Not helpful"]].map(([v, icon, label]) =>
              h("button", { class: `btn btn-ghost btn-xs${m.rated === v ? " on" : ""}`, type: "button", title: label, "aria-label": label,
                            "aria-pressed": String(m.rated === v), onclick: () => rateAnswer(m, v) }, icon))) : null) : null));
  if (ui.chatBusy && !ui.convo.some((m) => m.live)) items.push(h("div", { class: "msg jarvis" }, h("span", { class: "who typing" }, "JARVIS")));
  if (d) items.push(...d.jobs.filter((j) => j.state !== "submitted").reverse().map(jobCard));
  const feed = $("#feed");
  const key = JSON.stringify([ui.editIndex, ui.copied ? ui.convo.indexOf(ui.copied) : -1, ui.stage && ui.stage.stage, ui.convo.length, ui.convo.map((m) => (m.help ? "h" : m.welcome ? "w" : "")).join(""), ui.liveLen || 0, ui.convo.map((m) => m.approval_id || ""), ui.chatBusy, d && d.jobs.map((j) => [j.id, j.state, j.elapsed, j.kind])]);
  if (key === ui.lastFeed) return;            // avoid re-rendering (and losing scroll/focus) when nothing changed
  ui.lastFeed = key;
  const nearBottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 60;
  feed.replaceChildren(...items);
  if (nearBottom) feed.scrollTop = feed.scrollHeight;
}

// ---------------------------------------------------------------- voice
// Speech → text runs on the Mac (whisper.cpp, loopback only). Replies are read with on-device voices only
// (voices that would send text to a server are skipped). Interrupting speech never cancels a task.
const voice = { rec: null, stream: null, chunks: [], timer: null, started: 0, speak: false, warned: false };
try { voice.speak = localStorage.getItem("jarvis-speak") === "1"; } catch (e) { /* default off */ }

function renderVoice(d) {
  const v = d && d.voice;
  const mic = $("#mic");
  mic.hidden = !(v && v.enabled && navigator.mediaDevices && window.MediaRecorder);
  if (!voice.rec && mic.textContent !== "Listening…") {
    mic.disabled = !(v && v.available);
    mic.title = v && v.available ? "Tap to talk, tap again to stop" : "The speech recogniser isn't running on the Mac";
  }
  const sp = $("#speak");
  sp.hidden = !("speechSynthesis" in window);
  sp.setAttribute("aria-pressed", String(voice.speak));
  sp.textContent = `Voice replies: ${voice.speak ? "on" : "off"}`;
}

function stopSpeaking() { if ("speechSynthesis" in window) speechSynthesis.cancel(); delete $("#core").dataset.speaking; duckSound(); }
// ambient sound (avatar-sound.js) steps aside whenever JARVIS speaks or the microphone records
function duckSound() { if (window.JarvisSound) JarvisSound.duck(!!($("#core").dataset.speaking || $("#core").dataset.listening)); }

async function localVoices() {
  let all = speechSynthesis.getVoices();
  if (!all.length) {
    await new Promise((res) => { speechSynthesis.addEventListener("voiceschanged", res, { once: true }); setTimeout(res, 1500); });
    all = speechSynthesis.getVoices();
  }
  return all.filter((v) => v.localService);
}

async function say(text) {
  if (!voice.speak || !("speechSynthesis" in window) || !text) return;
  const voices = await localVoices();
  if (!voices.length) {
    if (!voice.warned) { voice.warned = true; note("This browser has no on-device voice, so replies aren't read aloud."); }
    return;
  }
  const lang = navigator.language || "en-US";
  const pick = voices.find((v) => v.lang === lang && v.default) || voices.find((v) => v.lang === lang)
    || voices.find((v) => v.lang.startsWith(lang.slice(0, 2))) || voices[0];
  const u = new SpeechSynthesisUtterance(text.replace(/https?:\/\/\S+/g, "a link").slice(0, 1500));
  u.voice = pick; u.lang = pick.lang;
  const core = $("#core");
  u.onstart = () => { core.dataset.speaking = "1"; duckSound(); };
  u.onend = u.onerror = () => { delete core.dataset.speaking; duckSound(); };
  // The reactor pulses on each word the speech engine reports (no lip sync on a faceless helm). Browsers that
  // don't report word boundaries simply show the steady speaking look.
  u.onboundary = (e) => { if (e.name === "word" && window.JarvisAvatar) JarvisAvatar.pulse(1); };
  stopSpeaking();
  speechSynthesis.speak(u);
}

function toggleSpeak() {
  voice.speak = !voice.speak;
  try { localStorage.setItem("jarvis-speak", voice.speak ? "1" : "0"); } catch (e) { /* this session only */ }
  if (voice.speak) say("Voice replies on."); else stopSpeaking();  // speaking inside the tap also unlocks audio on iPhone
  renderVoice(ui.data);
}

function micLabel(text, busy) { const m = $("#mic"); m.textContent = text; m.classList.toggle("rec", !!busy); }

async function toggleMic() {
  stopSpeaking();  // barge in: interrupting JARVIS's voice doesn't cancel anything it's doing
  if (voice.rec) { voice.rec.stop(); return; }
  try {
    voice.stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
  } catch (e) {
    note(e.name === "NotAllowedError" ? "Microphone access is blocked for this page (check the browser's site settings)." : `Microphone unavailable: ${e.message}`);
    return;
  }
  voice.chunks = [];
  const rec = new MediaRecorder(voice.stream);
  rec.ondataavailable = (e) => { if (e.data.size) voice.chunks.push(e.data); };
  rec.onstop = () => finishRecording(rec.mimeType);
  voice.rec = rec;
  $("#core").dataset.listening = "1"; duckSound();
  voice.started = Date.now();
  rec.start();
  startMicLevel(voice.stream);
  micLabel("Stop · 0s", true);
  voice.timer = setInterval(() => {
    const s = (Date.now() - voice.started) / 1000;
    micLabel(`Stop · ${Math.floor(s)}s`, true);
    if (s >= 58 && voice.rec) voice.rec.stop();
  }, 250);
}

// The reactor follows your real voice while recording: an analyser on the same microphone stream measures its level
// (RMS, ~20 times a second). Not connected to the speakers, not stored, not sent; it stops with the recording.
function startMicLevel(stream) {
  stopMicLevel();
  const AC = window.AudioContext || window.webkitAudioContext;
  if (!AC || !window.JarvisAvatar) return;
  try {
    const ctx = new AC(), an = ctx.createAnalyser();
    an.fftSize = 512; ctx.createMediaStreamSource(stream).connect(an);
    const buf = new Float32Array(an.fftSize);
    voice.level = { ctx, timer: setInterval(() => {
      an.getFloatTimeDomainData(buf);
      let sum = 0; for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
      JarvisAvatar.voiceLevel(Math.min(1, Math.sqrt(sum / buf.length) * 5));
    }, 50) };
  } catch (e) { voice.level = null; }   // no analyser: the projection still shows "listening"
}
function stopMicLevel() {
  if (!voice.level) return;
  clearInterval(voice.level.timer); voice.level.ctx.close().catch(() => {}); voice.level = null;
  if (window.JarvisAvatar) JarvisAvatar.voiceLevel(0);
}

async function finishRecording(type) {
  clearInterval(voice.timer);
  stopMicLevel();
  voice.stream.getTracks().forEach((t) => t.stop());
  voice.rec = null;
  delete $("#core").dataset.listening; duckSound();
  const blob = new Blob(voice.chunks, { type });
  voice.chunks = [];
  micLabel("Listening…", false);
  $("#mic").disabled = true;
  try {
    const body = await toWav16k(await blob.arrayBuffer());
    const r = await fetch("/api/voice/transcribe", { method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "audio/wav", "X-Requested-By": "jarvis" }, body });
    const data = await r.json().catch(() => ({ error: `HTTP ${r.status}` }));
    if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
    if (!data.text) { note("I didn't catch that — try again a little closer to the microphone."); return; }
    $("#cmd").value = data.text;
    $("#cmdform").requestSubmit();
  } catch (e) {
    note(`Voice: ${e.message}`);
  } finally {
    micLabel("Talk", false);
    renderVoice(ui.data);
  }
}

// Any recorded format the browser can decode → 16 kHz mono 16-bit WAV (what whisper.cpp expects).
async function toWav16k(buf) {
  const AC = window.AudioContext || window.webkitAudioContext;
  const ctx = new AC();
  let decoded;
  try { decoded = await ctx.decodeAudioData(buf); } finally { ctx.close(); }
  const off = new OfflineAudioContext(1, Math.max(1, Math.ceil(decoded.duration * 16000)), 16000);
  const src = off.createBufferSource();
  src.buffer = decoded;
  src.connect(off.destination);
  src.start();
  const pcm = (await off.startRendering()).getChannelData(0);
  const out = new DataView(new ArrayBuffer(44 + pcm.length * 2));
  const str = (o, s) => { for (let i = 0; i < s.length; i++) out.setUint8(o + i, s.charCodeAt(i)); };
  str(0, "RIFF"); out.setUint32(4, 36 + pcm.length * 2, true); str(8, "WAVE"); str(12, "fmt ");
  out.setUint32(16, 16, true); out.setUint16(20, 1, true); out.setUint16(22, 1, true);
  out.setUint32(24, 16000, true); out.setUint32(28, 32000, true); out.setUint16(32, 2, true); out.setUint16(34, 16, true);
  str(36, "data"); out.setUint32(40, pcm.length * 2, true);
  for (let i = 0; i < pcm.length; i++) out.setInt16(44 + i * 2, Math.max(-1, Math.min(1, pcm[i])) * 0x7fff, true);
  return new Blob([out.buffer], { type: "audio/wav" });
}

// "Add the dentist on Thursday": chat can't change things, so it offers a plan, which asks before doing anything.
async function makePlan(m) {
  const request = m.plan;
  m.plan = null;
  ui.lastFeed = "";
  setMode("do");
  try { await api("/api/plan", { request }); await refresh(); }
  catch (e) { note(`Could not start planning: ${e.message}`); }
}

// ---------------------------------------------------------------- Flight Recorder: one task's whole story
const PHASE_WORDS = { request: "Asked", plan: "Plan", state: "Status", permission: "Permission", approval: "Approval",
                      tool: "Action", model: "Model", cloud: "Claude", verify: "Check", stop: "Stop", other: "Other" };

async function showTimeline(taskId) {
  let t;
  try { t = await api(`/api/tasks/${taskId}/timeline`); } catch (e) { note(`Couldn't load the timeline: ${e.message}`); return; }
  const s = t.summary;
  const verified = s.verified === true ? "passed" : s.verified === false ? "FAILED" : "not run";
  const close = () => { dlg.close(); dlg.remove(); };
  const dlg = h("dialog", { class: "logdlg timeline", "aria-labelledby": "tl-h" },
    h("header", { class: "ph" }, h("h2", { id: "tl-h" }, "Timeline"),
      h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: close }, "Close")),
    h("div", { class: "tl-goal" }, t.task.goal),
    h("div", { class: "tl-sum" },
      `${STATE_WORDS[t.task.state] || t.task.state} · ${s.steps_done}/${s.steps} steps · `,
      `models: ${s.local_model_calls} on the Mac, ${s.claude_calls} Claude · `,
      `approvals: ${s.approvals_requested} asked, ${s.approved} approved, ${s.rejected} rejected · check ${verified}`),
    h("div", { class: `tl-integrity${t.integrity.audit_chain_ok ? "" : " bad"}` },
      t.integrity.audit_chain_ok ? `✓ Audit log intact (${t.integrity.entries_checked} entries checked)`
        : `✗ Audit log damaged at entry ${t.integrity.first_bad_seq}: this timeline may be incomplete`),
    h("ol", { class: "activity tl-events" }, t.events.map((e) => h("li", { class: e.problem ? "problem" : null },
      h("time", {}, clock(e.ts)),
      h("span", {}, h("b", { class: `tl-phase ${e.phase}` }, PHASE_WORDS[e.phase] || e.phase), " ", e.text,
        e.actor && e.actor !== "system" ? h("small", {}, ` · ${e.actor.replace("user:", "")}`) : null)))));
  dlg.addEventListener("close", () => dlg.remove());
  document.body.append(dlg);
  dlg.showModal();
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

// ---------------------------------------------------------------- help: what can I say?
// Only examples this JARVIS can actually do right now (e.g. calendar ones only when the Mac apps are available).
function helpExamples(d) {
  const cap = (d && d.capabilities) || {};
  const ask = [["What do you remember about me?"], ["Remember that I prefer email over phone calls"],
               ["Explain the difference between a Roth and a traditional IRA"]];
  const doIt = [["Summarise the PDFs in my Downloads folder into one note"],
                ["Move last month's screenshots from Downloads into an Archive folder"]];
  if (cap.mac_apps) {
    ask.unshift(["What's on my calendar tomorrow?"], ["Which of my reminders are overdue?"], ["What did my notes say about the trip?"]);
    doIt.unshift(["Add a reminder to call the dentist tomorrow at 10am"], ["Draft an email to Sam about Friday's meeting"],
                 ["Put lunch with Alex on Thursday at 1pm in my calendar"]);
  }
  const groups = [["ask", "Ask", "Answers, and looks things up when it needs to. Changes nothing.", ask],
                  ["do", "Do", "Makes a plan, then asks you before every change.", doIt]];
  if (cap.research) groups.push(["research", "Research", "Searches the web with Claude (asks first) and checks every source.",
                                 [["Which free note-taking apps work offline?"], ["What changed in the latest macOS release?"]]]);
  return groups;
}

function helpCard(m) {
  const pick = (mode, text) => {
    setMode(mode);
    const cmd = $("#cmd");
    cmd.value = text;
    cmd.focus();
  };
  return h("div", { class: "job helpcard" },
    h("div", { class: "kicker" }, "What can I say?"),
    helpExamples(ui.data).map(([mode, label, what, examples]) => h("div", { class: "help-group" },
      h("h3", {}, label), h("p", { class: "d-why" }, what),
      h("div", { class: "help-examples" }, examples.map(([text]) =>
        h("button", { class: "chip", type: "button", onclick: () => pick(mode, text) }, text))))),
    h("p", { class: "d-why" }, "Tap an example to put it in the box, then Send. Nothing changes without your approval; ",
      "Emergency stop pauses everything."),
    h("div", { class: "row mt" }, h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: () => dismiss(m) }, "Close")));
}

function welcomeCard(m) {
  return h("div", { class: "job helpcard" },
    h("div", { class: "kicker" }, "Welcome to JARVIS"),
    h("ul", { class: "welcome" },
      h("li", {}, h("b", {}, "Home"), " shows what JARVIS is doing, what matters now, and the box to ask, do or research."),
      h("li", {}, h("b", {}, "Decisions"), ": nothing changes until you approve it. The badge shows when something is waiting."),
      h("li", {}, h("b", {}, "Missions"), ": tasks step by step; pause or cancel any time. ", h("b", {}, "Workspace"), " puts sources and context beside the chat."),
      h("li", {}, h("b", {}, "The reactor"), "'s colour tells you the state: blue ready, gold working, amber needs you, red stopped."),
      h("li", {}, h("b", {}, "Emergency stop"), " (top right) pauses everything at once, on every page."),
      isPhone() ? null : h("li", {}, "Keyboard: ", h("kbd", {}, "/"), " to type, ", h("kbd", {}, "g"), " then a letter to jump, ", h("kbd", {}, "?"), " for all shortcuts.")),
    h("div", { class: "row mt" },
      h("button", { class: "btn btn-sm", type: "button", onclick: () => { dismiss(m); showHelp(); } }, "What can I say?"),
      h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: () => dismiss(m) }, "Got it")));
}

function dismiss(m) {
  ui.convo = ui.convo.filter((x) => x !== m);
  if (m.welcome) { try { localStorage.setItem("jarvis-welcomed", "1"); } catch (e) { /* shows again next time */ } }
  render();
}

function showHelp() {
  ui.convo = ui.convo.filter((x) => !x.help);
  ui.convo.push({ role: "assistant", help: true });
  render();
  const feed = $("#feed");
  feed.scrollTop = feed.scrollHeight;
}

function maybeWelcome() {
  if (ui.welcomeChecked) return;
  ui.welcomeChecked = true;
  let seen = false;
  try { seen = localStorage.getItem("jarvis-welcomed") === "1"; } catch (e) { /* show it */ }
  if (!seen) { ui.convo.unshift({ role: "assistant", welcome: true }); render(); }
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

function stepText(t) {
  // Counts of real steps only; never a percentage or an estimate.
  const n = t.steps.length;
  const done = t.steps.filter((s) => s.state === "done" || s.state === "skipped").length;
  if (!n) return "No steps yet";
  if (["completed", "failed", "cancelled"].includes(t.state) || done === n) return `${done} of ${n} steps done`;
  return `Step ${Math.min(done + 1, n)} of ${n}`;
}

// a small ring: done of total (real steps); no ring when there are no steps
function stepRing(t) {
  const n = t.steps.length, done = t.steps.filter((x) => x.state === "done" || x.state === "skipped").length;
  if (!n) return null;
  const C = 2 * Math.PI * 15;
  return sv("svg", { viewBox: "0 0 40 40", class: `step-ring ${t.state}`, role: "img", "aria-label": `${done} of ${n} steps done` },
    sv("circle", { cx: 20, cy: 20, r: 15, class: "sr-track" }),
    sv("circle", { cx: 20, cy: 20, r: 15, class: "sr-val", "stroke-dasharray": `${(C * done) / n} ${C}`, transform: "rotate(-90 20 20)" }),
    sv("text", { x: 20, y: 24, "text-anchor": "middle", class: "sr-num" }, `${done}/${n}`));
}
function missionRow(t) {
  // Home: one line per mission; Open shows its full card in Missions.
  return h("li", { class: `mrow ${NEEDS.includes(t.state) ? "needs" : t.state === "failed" ? "bad" : ""}` }, stepRing(t),
    h("div", { class: "mrow-text" }, h("small", {}, STATE_WORDS[t.state] || t.state), h("b", {}, t.goal), h("span", {}, stepText(t))),
    h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: () => openMission(t.id) }, "Open"));
}

function openMission(id) {
  ui.open.add(id);
  location.hash = "#/missions";
  setTimeout(() => { const el = document.getElementById(`m-${id}`); if (el) el.scrollIntoView({ block: "start" }); }, 60);
}

async function settleStep(t, s, happened) {
  const q = happened
    ? `Mark “${s.description}” as done?\n\nJARVIS will treat it as finished and carry on with the next step when the mission continues.`
    : `Mark “${s.description}” as not done?\n\nWhen the mission continues, JARVIS will do this step again. Only choose this if you've checked it really didn't happen; otherwise it may happen twice.`;
  if (!await ask(q, { ok: happened ? "Yes, it happened" : "Do it again", danger: !happened })) return;
  act(`/api/tasks/${t.id}/steps/${s.id}/resolve`, { happened });
}

const CHECK_ICON = { verified: "✓", failed: "✗", unconfirmed: "?", reported: "•", skipped: "–" };
const CHECK_WORD = { verified: "verified", failed: "not found / didn't hold", unconfirmed: "couldn't be checked (not counted as verified)",
                     reported: "reported by the app", skipped: "skipped" };
// "Complete · verified" only when every check held; something that couldn't be checked is said so
function missionWord(t) {
  if (t.state !== "completed" || !t.evidence || !t.evidence.checks) return STATE_WORDS[t.state] || t.state;
  return t.evidence.unconfirmed ? `Complete · ${t.evidence.unconfirmed} not confirmed` : "Complete · verified";
}
function missionCard(t) {
  const done = t.steps.filter((s) => s.state === "done" || s.state === "skipped").length;
  const cls = NEEDS.includes(t.state) ? "needs" : ACTIVE.includes(t.state) ? "active"
    : t.state === "completed" ? "done" : ["failed", "cancelled"].includes(t.state) ? "bad" : "";
  const cur = t.steps.find((s) => s.state === "started") || t.steps.find((s) => s.state === "pending");
  const files = (t.evidence && t.evidence.files) || [];
  const checks = (t.evidence && t.evidence.checks) || [];
  const controls = [];
  if (["queued", "running", "awaiting_approval"].includes(t.state)) controls.push(h("button", { class: "btn btn-ghost btn-sm", type: "button",
    title: "Pause: stops after the current step. Nothing is undone; resume any time.", onclick: () => act(`/api/tasks/${t.id}/pause`, {}) }, "Pause"));
  controls.push(h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: () => showTimeline(t.id) }, "Timeline"));
  const uncertain = t.steps.filter((s) => s.state === "uncertain");
  if (["paused", "blocked"].includes(t.state) && !uncertain.length) controls.push(h("button", { class: "btn btn-sm", type: "button", onclick: () => act(`/api/tasks/${t.id}/resume`, {}) }, "Resume"));
  if (t.replannable) controls.push(h("button", { class: "btn btn-sm", type: "button",
    title: "JARVIS plans this once more, told what already happened. You review the new plan before anything runs.",
    onclick: async () => { try { await call(`/api/tasks/${t.id}/replan`, {}); note("Planning a second attempt — it appears in the chat when ready. Nothing runs until you press Run plan."); }
      catch (e) { note(cancelled(e)); } } }, "Try a new plan"));
  if (!["completed", "failed", "cancelled"].includes(t.state)) controls.push(h("button", { class: "btn btn-ghost btn-sm", type: "button",
    title: "Cancel: ends the mission for good, after the current step. Anything already done stays done.",
    onclick: async () => (await ask(`Cancel “${t.goal}”?\n\nIt stops for good after the current step. Anything already done (files saved, events added, drafts created) is not undone.`,
      { ok: "Cancel mission", danger: true })) && act(`/api/tasks/${t.id}/cancel`, {}) }, "Cancel"));

  const details = h("details", { class: "more" }, h("summary", {}, `${done}/${t.steps.length} steps · details`),
    h("ol", { class: "steps" }, t.steps.map((s) => h("li", { class: s.state }, h("span", { class: "ic" }, ICON[s.state] || "·"),
      h("div", {}, s.description, h("small", {}, s.call + (s.attempts > 1 ? ` · attempt ${s.attempts}` : "")),
        s.state === "uncertain" ? h("div", { class: "m-err" }, "Outcome unknown: JARVIS never repeats this automatically.") : null,
        s.error ? h("div", { class: "m-err" }, s.error) : null)))),
    t.final_text ? h("pre", { class: "out" }, t.final_text) : null);
  if (ui.open.has(t.id)) details.open = true;
  details.addEventListener("toggle", () => details.open ? ui.open.add(t.id) : ui.open.delete(t.id));

  return h("article", { class: `mission ${cls}`, id: `m-${t.id}` },
    h("div", { class: "m-state" }, missionWord(t)),
    h("div", { class: "m-title" }, t.goal),
    h("div", { class: "segs", role: "progressbar", "aria-label": "Progress", "aria-valuemin": 0, "aria-valuemax": t.steps.length, "aria-valuenow": done,
               "aria-valuetext": stepText(t) },
      t.steps.map((s) => h("i", { class: s.state, title: `${s.description} — ${s.state}` }))),
    h("div", { class: "m-steps" }, stepText(t)),
    cur && !["completed", "failed", "cancelled"].includes(t.state) ? h("div", { class: "m-now" }, "Now: ", h("b", {}, cur.description)) : null,
    t.state === "failed" && t.error ? h("div", { class: "m-err" }, t.error) : null,
    t.state === "blocked" && t.next_action ? h("div", { class: "m-err" }, t.next_action) : null,
    uncertain.map((s) => h("div", { class: "settle" },
      h("div", { class: "m-err" }, `Outcome unknown: “${s.description}”. JARVIS never repeats this by itself. Check whether it happened, then tell it:`),
      h("div", { class: "row" },
        h("button", { class: "btn btn-sm", type: "button", onclick: () => settleStep(t, s, true) }, "Yes, it happened"),
        h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: () => settleStep(t, s, false) }, "No, it didn't")))),
    // Mission Control: each success criterion and what the check found (verified / failed / unconfirmed / reported)
    checks.length ? h("ul", { class: "criteria checked", "aria-label": "How it was checked" }, checks.map((c) =>
      h("li", { class: c.status }, h("span", { class: "ic" }, CHECK_ICON[c.status] || "·"), `${c.text}${CHECK_WORD[c.status] ? ` — ${CHECK_WORD[c.status]}` : ""}`)))
      : files.map((f) => h("div", { class: `m-ok${f.content_matches ? "" : " bad"}`, title: f.path },
        f.content_matches ? `✓ Saved & verified · ${base(f.path)}` : `✗ Verification failed · ${base(f.path)}`)),
    t.replan_of ? h("div", { class: "d-why" }, "Second attempt at a mission that failed.") : null,
    details,
    controls.length ? h("div", { class: "row mt" }, controls) : null);
}

function renderMissions(tasks) {
  const live = tasks.filter((t) => ![...["completed", "failed", "cancelled"]].includes(t.state)).length;
  $("#miscount").textContent = live ? `${live} live` : "";
  badge("missions", live);
  if (!tasks.length) {
    $("#missions").replaceChildren(h("div", { class: "empty" }, "No missions yet. Switch to Do and describe a task."));
    return;
  }
  const finished = (t) => ["completed", "failed", "cancelled"].includes(t.state);
  if (document.body.dataset.view !== "missions") {
    // what needs you first, then what's running, paused, failed, and only then what finished fine
    const rank = (t) => NEEDS.includes(t.state) ? 0 : ACTIVE.includes(t.state) ? 1 : t.state === "paused" ? 2 : t.state === "failed" ? 3 : 4;
    const list = tasks.map((t, i) => [rank(t), i, t]).sort((x, y) => x[0] - y[0] || x[1] - y[1]).map((x) => x[2]).slice(0, 5);
    fill($("#missions"), h("ol", { class: "mrows" }, list.map(missionRow)),
      tasks.length > list.length ? h("a", { class: "btn btn-ghost btn-sm", href: "#/missions" }, `All ${tasks.length} missions`) : null);
    return;
  }
  const groups = [["Needs you", (t) => NEEDS.includes(t.state)], ["In progress", (t) => ACTIVE.includes(t.state)],
                  ["Paused", (t) => t.state === "paused"], ["Finished", finished]];
  fill($("#missions"), groups.map(([title, test]) => {
    const g = tasks.filter(test);
    return g.length ? [h("h3", { class: "m-group" }, `${title} · ${g.length}`), g.map(missionCard)] : null;
  }));
}

// ---------------------------------------------------------------- decisions
// How much a decision shows grows with its risk (from the tier the action declares, and whether data leaves the Mac).
function riskOf(a) {
  if (a.tool === "egress") return { level: "data", icon: "⇪", label: "Data leaves this Mac" };
  if (a.tier >= 4 || a.action === "delete") return { level: "high", icon: "▲", label: "High risk" };
  if (a.tier === 3) return { level: "high", icon: "▲", label: "External action" };
  if (a.tier === 2) return { level: "review", icon: "◆", label: "Review carefully" };
  return { level: "routine", icon: "·", label: "Routine" };
}

function egressLines(text) {
  // The consent summary already says what is sent and why; show those parts instead of hiding them.
  const purpose = (text.match(/purpose: (.*?)(\. Provider data use:|$)/) || [])[1];
  const use = (text.match(/Provider data use: (.*?)\.?$/) || [])[1];
  return h("ul", { class: "d-facts" },
    purpose ? h("li", {}, h("b", {}, "Why: "), purpose) : null,
    use ? h("li", {}, h("b", {}, "Provider's data use: "), use) : null,
    !purpose && !use ? h("li", {}, text) : null);
}

function renderDecisions(list) {
  const panel = $("#decision-panel");
  panel.classList.toggle("has-items", list.length > 0);
  $("#ap-h").textContent = list.length ? "Decision required" : "Decisions";
  $("#apcount").textContent = list.length > 1 ? String(list.length) : "";
  badge("decisions", list.length);
  if (!list.length) { $("#approvals").replaceChildren(h("div", { class: "empty" }, "Nothing waiting for you.")); return; }
  $("#approvals").replaceChildren(...list.map((a) => {
    const target = a.resource && a.tool === "fs" ? h("div", { class: "d-target", title: a.resource }, "→ ", h("b", {}, base(a.resource)), ` in ${folder(a.resource)}`)
      : a.resource ? h("div", { class: "d-target" }, a.resource) : null;
    const risk = riskOf(a);
    const [head, ...rest] = a.summary.split(" — ");
    const more = rest.join(" — ");
    const preview = a.preview === null ? null : risk.level === "routine"
      ? h("details", { class: "d-preview" }, h("summary", {}, "Show exactly what will be written"), h("pre", { class: "out" }, a.preview))
      : h("pre", { class: "out", "aria-label": "Exactly what will be written" }, a.preview);
    return h("article", { class: `decision risk-${risk.level}` },
      h("div", { class: "d-kind" }, h("i", { class: "d-ring", "aria-hidden": "true" }), decisionKind(a), h("span", { class: "d-risk" }, `${risk.icon} ${risk.label}`),
        a.created_at ? h("span", { class: "d-wait" }, `waiting ${since(a.created_at)}`) : null),
      h("div", { class: "d-title" }, head),
      target,
      a.tool === "egress" && more ? egressLines(more) : more && risk.level !== "routine" ? h("div", { class: "d-why" }, more) : null,
      h("div", { class: "d-why" }, a.reason === "no standing policy covers this action" ? "Asking because no standing permission covers this." : a.reason),
      preview,
      risk.level !== "routine" ? h("div", { class: "d-scope" }, "Approving applies once, to exactly this. Any change asks you again.") : null,
      a.task_id && a.tool !== "egress" ? h("div", { class: "d-scope" }, "Rejecting stops this step; JARVIS won't try this on the same target again in this mission.") : null,
      h("div", { class: "row mt" },
        h("button", { class: "btn btn-approve", type: "button", onclick: () => act(`/api/approvals/${a.id}`, { approve: true }) }, "Approve"),
        h("button", { class: "btn btn-danger", type: "button", onclick: () => act(`/api/approvals/${a.id}`, { approve: false }) }, "Reject")));
  }));
}

// ---------------------------------------------------------------- systems & activity
// Updates (Mac only): "Check" lists what's new; "Update" backs up, installs, runs the release gate, restarts, and puts
// the old version back by itself if anything fails. Progress comes from the server's update/state.json, step by step.
const UPDATE_WORD = { running: "Updating…", done: "Updated", failed: "The update didn't go ahead", rolled_back: "Update undone: the old version is back" };
function updateBlock(st) {
  const c = ui.updateCheck;
  const steps = st && st.steps && st.steps.length ? h("ol", { class: "upd-steps" }, st.steps.map((x) =>
    h("li", { class: x.ok ? "ok" : "bad" }, `${x.ok ? "✓" : "✗"} ${x.name}`, x.detail ? h("small", {}, ` ${x.detail}`) : null))) : null;
  const recent = st && (st.state === "running" || (st.finished && Date.now() / 1000 - st.finished < 86400));
  return h("div", { class: "updates" },
    recent ? h("div", { class: `ro ${st.state === "done" ? "ok" : st.state === "running" ? "" : "bad"}` },
      h("span", {}, UPDATE_WORD[st.state] || st.state), h("b", {}, st.behind ? plural(st.behind, "new commit") : "")) : null,
    recent ? steps : null,
    c ? h("div", { class: "d-why" }, c.can_update ? `${plural(c.behind, "update")} on ${c.branch}:` : `No update: ${c.why}.`) : null,
    c && c.can_update ? h("ul", { class: "upd-commits" }, c.commits.slice(0, 8).map((x) => h("li", {}, x))) : null,
    h("div", { class: "row mt" },
      h("button", { class: "btn btn-ghost btn-sm", type: "button", disabled: st && st.state === "running", onclick: async () => {
        try { ui.updateCheck = await api("/api/update/check", {}); } catch (e) { note(e.message); }
        renderSystems(ui.data);
      } }, "Check for updates"),
      c && c.can_update && !(st && st.state === "running") ? h("button", { class: "btn btn-sm", type: "button", onclick: async () => {
        if (!(await ask(`Update JARVIS (${plural(c.behind, "commit")})? It backs up first, runs the release gate, and restarts. If anything fails, the old version comes back by itself.`, { ok: "Update" }))) return;
        ui.updateCheck = null;
        await act("/api/update/start", {});
      } }, "Update") : null));
}

// "Test this version": the hard benchmark set ×5 on a throwaway folder, local models only, started when the Mac is idle
// (tonight = in your quiet hours). The verdict compares it with the last run of the same tasks on another commit.
const BENCH_WORD = { MERGE: "Better: meets the merge rule", "DON'T MERGE": "Not better", INCONCLUSIVE: "Too close to call",
  "FIRST RUN": "Baseline recorded", "NO RESULT": "No result" };
function benchBlock(bt) {
  if (!bt) return null;
  const r = bt.request, last = bt.last;
  return h("div", { class: "updates" },
    r ? h("div", { class: "ro" }, h("span", {}, bt.running ? "Testing now…" : r.when === "tonight" ? "Waiting for tonight (quiet hours, Mac idle)" : "Waiting for the Mac to be idle"),
      h("b", {}, `${r.set} ×${r.repeat}`)) : null,
    last ? h("div", { class: `ro ${last.verdict === "MERGE" ? "ok" : last.verdict === "DON'T MERGE" ? "bad" : ""}` },
      h("span", {}, `Last test · ${clock(last.finished)}`),
      h("b", {}, `${BENCH_WORD[last.verdict] || last.verdict}${last.scored ? ` · ${last.passed}/${last.scored} passed` : ""}`)) : null,
    last && last.reasons && last.reasons.length ? h("div", { class: "d-why" }, last.reasons.join(" · ")) : null,
    last && last.fixed && last.fixed.length ? h("div", { class: "d-why" }, `Fixed: ${last.fixed.join(", ")}`) : null,
    last && last.new_failures && last.new_failures.length ? h("div", { class: "d-why" }, `New failures: ${last.new_failures.join(", ")}`) : null,
    h("div", { class: "row mt" }, r ? h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: () => act("/api/benchtest/cancel", {}) }, bt.running ? "Stop the test" : "Cancel")
      : [h("button", { class: "btn btn-sm", type: "button", onclick: () => act("/api/benchtest", { when: "tonight" }) }, "Test tonight"),
         h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: () => act("/api/benchtest", { when: "now" }) }, "Test now")]));
}

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
    health.items.map((i) =>
      h("div", { class: `light${i.ok ? " on" : ""}`, title: i.detail }, h("i"), i.name, h("small", {}, i.detail))))
    : null;
  const rem = d.remote || { enabled: false, devices: [] };
  const live = rem.devices.filter((x) => !x.revoked_at);
  const phone = h("div", { class: "devices" },
    h("div", { class: "ro" }, h("span", {}, "Phone"),
      h("b", {}, rem.this_device ? `This device · ${rem.this_device.name}` : !rem.enabled ? "Not set up" : live.length ? plural(live.length, "paired device") : "None paired")),
    live.map((x) => h("div", { class: "device-row" }, x.name,
      h("small", {}, x.last_seen ? `seen ${clock(x.last_seen)}` : "never signed in"),
      h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: async () =>
        (await ask(`Remove ${x.name}? It will be signed out immediately and can't reconnect without pairing again.`, { ok: "Remove", danger: true })) &&
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
      h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: async () =>
        (await ask(tid.keys.length === 1 ? "Remove your only Touch ID key? Approvals will stop asking for Touch ID." : `Remove ${k.name}?`, { ok: "Remove", danger: true })) &&
        act(`/api/touchid/${k.id}/remove`, {}) }, "Remove"))),
    h("button", { class: "btn btn-sm mt", type: "button", onclick: setupTouchId }, tid.enabled ? "Add another key" : "Set up Touch ID"),
    tid.enabled ? null : h("div", { class: "d-why" }, "Then every approval here asks for your fingerprint, not just this browser's sign-in."));
  const part = (title) => h("h3", { class: "sys-part" }, title);
  fill($("#system"),
    part("Health"), healthBlock || h("div", { class: "empty" }, "Checking…"),
    onPhone() ? null : h("div", { class: "row mt" },
      h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: () => act("/api/health/check", {}) }, "Check again"),
      h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: () => act("/api/backup/now", {}) }, "Back up now")),
    onPhone() ? null : part("Updates"), onPhone() ? null : updateBlock(d.update),
    onPhone() ? null : part("Test this version"), onPhone() ? null : benchBlock(d.benchtest),
    h("div", { class: "lights" }, lights.length ? lights : h("div", { class: "empty" }, "No models configured")),
    part("Setup"), touch, phone,
    part("Configuration"),
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
  const name = ((await ask("Name this key (e.g. Safari on MacBook):", { input: "This Mac", ok: "Continue" })) || "").trim();
  if (!name) return;
  try {
    const o = await call("/api/touchid/enroll/options", { name });
    const p = o.publicKey;
    const c = await withTap(() => navigator.credentials.create({ publicKey: {
      ...p, challenge: b64u.toBuf(p.challenge), user: { ...p.user, id: b64u.toBuf(p.user.id) },
      authenticatorSelection: { ...p.authenticatorSelection, authenticatorAttachment: "platform" },
      excludeCredentials: p.excludeCredentials.map((x) => ({ ...x, id: b64u.toBuf(x.id) })) } }), "Set up Touch ID");
    await api("/api/touchid/enroll/finish", { name, challengeId: o.challengeId, credential: { ...credJSON(c),
      response: { clientDataJSON: b64u.fromBuf(c.response.clientDataJSON), attestationObject: b64u.fromBuf(c.response.attestationObject) } } });
    ui.convo.push({ role: "assistant", text: "Touch ID is on. You sign in with it; after that only dangerous actions ask again (releasing the stop, changing memories, high-risk approvals)." });
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
    // ask first, straight from the tap: iPhone Safari only shows the permission prompt in response to one
    if (await Notification.requestPermission() !== "granted") { note("Notifications are off for JARVIS in iPhone Settings."); return; }
    const reg = await navigator.serviceWorker.ready;
    const { key } = await api("/api/push/key");
    const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64u.toBuf(key) });
    await api("/api/push/subscribe", { subscription: sub.toJSON() });
    note("Notifications on. They only ever say things like “JARVIS needs a decision” — never your content.");
  } catch (e) { note(`Couldn't turn on notifications: ${e.message}. On iPhone, add JARVIS to your Home Screen first.`); }
}

// Events the server has no plain-English wording for yet (it falls back to raw data); worded here, nothing hidden.
const EVENT_WORDS = { "proposals.refreshed": () => "Checked its own record for improvement ideas",
                      "proposals.decided": (p) => `Recorded your decision on an improvement idea${p.state ? ` (${p.state})` : ""}`,
                      "memory.important": (p) => (p.important ? "Starred a memory" : "Unstarred a memory") };
function wordEvent(e) {
  if (!/^\s*[{[]/.test(e.detail || "")) return e;  // the server already worded it
  let payload = {};
  try { payload = JSON.parse(e.detail) || {}; } catch (err) { payload = {}; }
  const words = EVENT_WORDS[e.event] ? EVENT_WORDS[e.event](payload)
    : e.event.replace(/[._]/g, " ").replace(/^\w/, (c) => c.toUpperCase());  // e.g. "Device step up"
  return { ...e, detail: words };
}
// A short, friendly line for the Home timeline. The full wording stays in the full log (and on hover).
const modelName = (m) => { const n = String(m || "").split("/").pop(); return n ? n.charAt(0).toUpperCase() + n.slice(1) : "a model"; };
function shortEvent(e) {
  const d = e.detail || "";
  let m;
  if (e.event === "model.route" && (m = d.match(/Model chosen: ([\w./:-]+) \((cloud|local)/))) return `Routed to ${modelName(m[1])} · ${m[2] === "local" ? "on this Mac" : "cloud"}`;
  if (e.event === "egress.received" && (m = d.match(/Reply from ([\w./:-]+) in ([\d.]+)s/))) return `Reply · ${modelName(m[1])} · ${Number(m[2]).toFixed(1)} s`;
  if (e.event === "model.local_call" && (m = d.match(/^(.+?) answered \(.*?, ([\d.]+)s\)/))) return `Reply · ${modelName(m[1])} · ${Number(m[2]).toFixed(1)} s · on this Mac`;
  if (e.event === "egress.send" && (m = d.match(/ to (\w+)/))) return `Request sent to ${modelName(m[1])}`;
  if (e.event === "chat.answer_check") return d === "Answer checked: fine" ? "Answer checked ✓" : d;
  if (e.event === "model.no_route") return "No model available for a request";
  if (e.event === "evolution.milestone" && (m = d.match(/verified “(.+)”/))) return `Milestone verified · ${m[1]}`;
  return d.length > 64 ? `${d.slice(0, 62).trimEnd()}…` : d;
}
// Colour of an event's node in the Recent activity timeline.
function eventKind(event) {
  if (/error|failed|denied|no_route|rejected|stop/.test(event)) return "bad";
  if (/^approval|^device/.test(event)) return "decision";
  if (/^evolution/.test(event)) return "evolution";
  if (/^memory/.test(event)) return "memory";
  if (/^task/.test(event)) return "mission";
  if (/^model|^egress|^chat/.test(event)) return "model";
  return "other";
}
const KIND_ICON = { bad: "⚠", decision: "◆", evolution: "✦", memory: "❖", mission: "▤", model: "◈", other: "•" };
// the activity pulse: real audit events per 5 minutes over the last hour (the newest bar on the right)
function activityPulse(entries) {
  const now = Date.now(), bins = new Array(12).fill(0);
  for (const e of entries) { const age = (now - Date.parse(e.ts)) / 300000; if (age >= 0 && age < 12) bins[11 - Math.floor(age)]++; }
  const max = Math.max(1, ...bins);
  return sv("svg", { viewBox: "0 0 60 14", class: "pulse-svg", "aria-hidden": "true" },
    ...bins.map((n, i) => sv("rect", { x: i * 5 + 0.5, y: 14 - Math.max(1, (n / max) * 13), width: 4, height: Math.max(1, (n / max) * 13), class: n ? "on" : "" })));
}
function renderActivity(entries) {
  entries = entries.map(wordEvent);
  const hour = entries.filter((e) => Date.now() - Date.parse(e.ts) < 3600000).length;
  $("#recentpulse").replaceChildren(activityPulse(entries), h("span", {}, `${hour} in the last hour`));
  const newest = entries.length ? entries[0].seq : 0, seen = ui.recentSeq || 0;
  ui.recentSeq = Math.max(seen, newest);
  $("#ticker").replaceChildren(...entries.slice(0, 6).map((e) => h("li", {}, h("time", {}, clock(e.ts)), e.detail)));
  $("#recent").replaceChildren(...(entries.length ? entries.slice(0, 6).map((e) => h("li", { class: `ev-${eventKind(e.event)}${seen && e.seq > seen ? " new" : ""}`, title: e.detail },
      h("i", { class: "ev-icon", "aria-hidden": "true" }, KIND_ICON[eventKind(e.event)]), h("time", {}, clock(e.ts)), h("span", {}, shortEvent(e))))
    : [h("li", { class: "empty" }, "Nothing yet.")]));
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
  const all = res.memories;
  const mc = { all: all.length, explicit: all.filter((m) => m.origin === "explicit").length,
                   observed: all.filter((m) => m.origin !== "explicit").length, starred: all.filter((m) => m.important).length };
  const shown = all.filter(MEM_FILTERS[ui.memFilter || "all"][1]);
  renderMemFilters(mc);
  const items = shown.map((m) => {
    const confirmed = m.origin === "explicit";
    const day = (iso) => (iso || "").slice(0, 10);
    const reconfirmed = confirmed && m.verified_at && day(m.verified_at) !== day(m.created_at);
    return h("article", { class: `mem ${confirmed ? "confirmed" : "unconfirmed"}` },
      h("div", { class: "mem-text" }, m.important ? h("span", { class: "mem-star", title: "Starred: always worth remembering" }, "★ ") : null, m.text),
      h("div", { class: "mem-origin" }, confirmed
        ? reconfirmed ? ["✓ ", h("b", {}, "Confirmed by you"), " · noticed earlier, then confirmed"]
          : ["✓ ", h("b", {}, "Stated by you"), m.source_record ? " · in a conversation" : " · added here"]
        : ["? ", h("b", {}, "Inferred by JARVIS"), " from a conversation · already used in answers · confirm it or delete it"]),
      h("div", { class: "mem-meta" }, `${m.kind} · added ${day(m.created_at)}` + (reconfirmed ? ` · confirmed ${day(m.verified_at)}` : "")),
      h("div", { class: "row" },
        confirmed ? null : h("button", { class: "btn btn-sm", type: "button", onclick: () => memAct(`/api/memory/${m.id}/confirm`, {}) }, "Confirm"),
        h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: () => {
          ask("Correct this memory:", { input: m.text, ok: "Save" }).then((t) => { if (t && t.trim() && t !== m.text) memAct(`/api/memory/${m.id}/edit`, { text: t }); });
        } }, "Edit"),
        h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: () => memAct(`/api/memory/${m.id}/important`, { important: !m.important }) }, m.important ? "Unstar" : "Star"),
        h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: async () => (await ask("Delete this memory? JARVIS won't re-learn it.", { ok: "Delete", danger: true })) && memAct(`/api/memory/${m.id}/delete`, {}) }, "Delete")));
  });
  if (ui.memQ && (res.memories.length || res.records.length)) {
    items.push(h("div", { class: "row" }, h("span", { class: "mem-meta" }, `${plural(res.records.length, "conversation")} mention this`),
      h("button", { class: "btn btn-danger btn-sm", type: "button", onclick: forgetMatching }, "Forget all of this")));
  }
  $("#memlist").replaceChildren(...(items.length ? items : [h("div", { class: "empty" },
    all.length && ui.memFilter && ui.memFilter !== "all" ? `No ${MEM_FILTERS[ui.memFilter][0].toLowerCase()} memories${ui.memQ ? " match" : ""}.`
      : ui.memQ ? "Nothing remembered about that." : "Nothing remembered yet. Tell JARVIS something, or say “remember that…” in chat.")]));
}

// Filters only change what's shown; they never change what JARVIS remembers or uses.
const MEM_FILTERS = {
  all: ["All", () => true],
  explicit: ["Stated by you", (m) => m.origin === "explicit"],
  observed: ["Inferred", (m) => m.origin !== "explicit"],
  starred: ["Starred", (m) => !!m.important],
};
function renderMemFilters(counts) {
  const cur = ui.memFilter || "all";
  $("#memfilters").replaceChildren(...Object.entries(MEM_FILTERS).map(([key, [label]]) =>
    h("button", { class: `chip memf${key === cur ? " on" : ""}${key === "observed" && counts.observed ? " review" : ""}`, type: "button",
                  "aria-pressed": String(key === cur), onclick: () => { ui.memFilter = key; ui.memKey = null; loadMemory(true); } },
      `${label} · ${counts[key]}`)));
}

// ---------------------------------------------------------------- briefing & ideas (read-only here)
const IDEA_STATES = { open: "Waiting for you", approved: "Approved · to do", rejected: "Rejected", done: "Done" };
// "Not now" on a suggestion: hides it on this page (a display choice; it decides nothing and changes nothing else)
async function dismissSuggestion(it) {
  try { await call("/api/initiative/dismiss", { key: it.key, size: it.size }); } catch (e) { note(cancelled(e)); }
  loadIntel();
}
const INITIATIVE_SOURCE = { mission: "Mission", health: "Problem", project: "Project", lesson: "Lesson", proposal: "Improvement" };
async function loadIntel() {
  const box = $("#intel");
  box.replaceChildren(h("div", { class: "empty" }, "Loading…"));
  let brief = null, ideas = null, feed = null;
  try { feed = await api("/api/initiative"); } catch (e) { feed = { error: e.message }; }
  try { brief = await api("/api/briefing"); } catch (e) { brief = { error: e.message }; }
  try { ideas = (await api("/api/proposals")).proposals; } catch (e) { ideas = { error: e.message }; }
  const sections = brief.error ? [h("div", { class: "empty" }, `Couldn't build the briefing: ${brief.error}`)]
    : [h("div", { class: "kicker" }, `Today's briefing · since ${new Date(brief.since).toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" })}`),
       h("div", { class: "job-title" }, brief.headline),
       brief.sections.length ? brief.sections.map((x) => h("div", { class: `brief-sec${x.alert ? " alert" : ""}` }, h("h3", {}, x.title),
         h("ul", {}, x.items.map((i) => h("li", {}, i))))) : h("div", { class: "d-why" }, "All quiet: nothing finished, failed or broke since the last briefing.")];
  const ideaList = ideas.error ? [h("div", { class: "empty" }, `Couldn't load ideas: ${ideas.error}`)]
    : !ideas.length ? [h("div", { class: "empty" }, "No ideas right now: nothing in JARVIS's record suggests a change.")]
    : [h("ul", { class: "ideas" }, ideas.slice(0, 8).map((x) => h("li", { class: `idea ${x.state}` },
        h("small", {}, `${IDEA_STATES[x.state] || x.state} · ${x.kind}`), h("b", {}, x.title), h("span", {}, x.problem))))];
  // The Initiative feed: one ranked list. It suggests; opening an item takes you to where you decide.
  const open = (it) => (it.key.startsWith("mission-failed:") ? openMission(it.key.split(":")[1]) : (location.hash = it.href));
  const feedPart = h("section", { class: "intel-part" }, h("h3", { class: "sys-part" }, "For you, ranked"),
    feed.error ? h("div", { class: "empty" }, `Couldn't load suggestions: ${feed.error}`)
    : feed.paused ? h("div", { class: "empty" }, `Suggestions are off: ${feed.why}.`)
    : !feed.items.length ? h("div", { class: "empty" }, feed.hidden
      ? `Nothing new. ${feed.hidden} suggestion(s) hidden with “Not now” (problems come back after a day).`
      : "Nothing needs you: no failed missions, problems, stalled projects or open ideas.")
    : h("ul", { class: "ideas initiative" }, feed.items.map((it) => h("li", { class: `idea ${it.source}` },
        h("small", {}, `${INITIATIVE_SOURCE[it.source] || it.source} · ${it.urgency === 3 ? "urgent" : it.urgency === 2 ? "soon" : "when you like"}`),
        h("b", {}, it.title), h("span", {}, it.why),
        h("small", { class: "why-rank", title: "Ranked by urgency first, then value, weighted by how sure the source is (fixed per kind of suggestion)" },
          `Why here: ${["", "when you like", "soon", "urgent"][it.urgency]} · ${["", "small", "useful", "important"][it.value]} · ${it.confidence >= 0.95 ? "certain (it happened)" : it.confidence >= 0.7 ? "likely" : "possible"}`),
        h("div", { class: "row" }, h("button", { class: "btn btn-sm", type: "button", onclick: () => open(it) }, "Open"),
          h("button", { class: "btn btn-ghost btn-sm", type: "button", title: "Hide for 30 days (it comes back sooner only if the evidence doubles)",
            onclick: () => dismissSuggestion(it) }, "Not now"))))),
    h("p", { class: "d-why" }, "Suggestions only: nothing here runs by itself. At most one notification a day, never in quiet hours."));
  fill(box, feedPart, h("section", { class: "intel-part" }, sections.flat(Infinity)),
    h("section", { class: "intel-part" }, h("h3", { class: "sys-part" }, "Improvement ideas"),
      h("p", { class: "d-why" }, "JARVIS suggests these from its own record. It never changes itself: approving puts an idea on your to-do list."),
      ideaList, h("div", { class: "row mt" }, h("a", { class: "btn btn-sm", href: "/proposals" }, "Open Ideas to decide"),
        h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: loadIntel }, "Refresh"))));
}

// ---------------------------------------------------------------- projects for you
// Ideas found by the local model in your own messages and memories; each shows the words it came from.
// Nothing runs by itself: accepting makes a checklist, and a step becomes a reminder only through plan -> approve.
const PROJ = { busy: false, timer: null, autoTried: false, notice: null };
async function loadProjects(entering = false) {
  const box = $("#projects");
  if (!box) return;
  if (entering && !box.childElementCount) box.replaceChildren(h("div", { class: "empty" }, "Loading…"));
  let d;
  try { d = await api("/api/projects"); } catch (e) { box.replaceChildren(h("div", { class: "empty" }, `Couldn't load projects: ${e.message}`)); return; }
  // "On its own": at most once a day, when you open this page and there's enough to go on.
  if (entering && !PROJ.autoTried && d.due && d.enough && !d.running) {
    PROJ.autoTried = true;
    try { await api("/api/projects/generate", {}); d.running = true; } catch (e) { /* the button still works */ }
  }
  renderProjects(d);
  clearTimeout(PROJ.timer);
  if (d.running && document.body.dataset.view === "projects") PROJ.timer = setTimeout(() => loadProjects(), 2000);
}
async function projAct(path, body = {}) {
  if (PROJ.busy) return;
  PROJ.busy = true;
  try { await api(path, body); } catch (e) { PROJ.notice = e.message; }
  PROJ.busy = false;
  await loadProjects();
}
async function polishProjects() {
  PROJ.notice = "Asking Claude…";
  renderProjectsNotice();
  let r;
  try { r = await api("/api/projects/polish", {}); } catch (e) { PROJ.notice = `Couldn't polish: ${e.message}`; await loadProjects(); return; }
  if (r.needs_approval) { PROJ.notice = null; PROJ.consent = r; await loadProjects(); return; }
  PROJ.notice = r.polished ? `Polished ${plural(r.polished, "idea")} with ${(r.model || "").split("/").pop()}.` : r.reason;
  await loadProjects();
}
async function projConsent(approve) {
  const c = PROJ.consent;
  PROJ.consent = null;
  try { await call(`/api/approvals/${c.approval_id}`, { approve }); }
  catch (e) { if (e.name === "NotAllowedError") { PROJ.consent = c; PROJ.notice = cancelled(e); await loadProjects(); return; } }
  if (approve) await polishProjects();
  else { PROJ.notice = "Not sent. Your ideas stay as they are."; await loadProjects(); }
}
async function stepReminder(idea, step) {
  ui.lastFeed = "";
  setMode("do");
  try {
    await api("/api/plan", { request: `Add a reminder: ${step.text} (project: ${idea.title})` });
    location.hash = "#/home";
    await refresh();
  } catch (e) { PROJ.notice = `Could not start planning: ${e.message}`; await loadProjects(); }
}
function renderProjectsNotice() {
  const n = $("#proj-notice");
  if (n) { n.textContent = PROJ.notice || ""; n.hidden = !PROJ.notice; }
}
function projCard(x) {
  const open = x.state === "open";
  const evidence = x.evidence.length ? h("details", {},
    h("summary", {}, `Based on ${plural(x.evidence.length, "thing")} you said or JARVIS remembers`),
    x.evidence.map((q) => h("blockquote", {}, `${q.type === "memory" ? "Memory" : "You said"}: “${q.text}”`))) : null;
  const steps = h("ol", {}, x.steps.map((st, i) => h("li", { class: `step${st.done ? " done" : ""}` },
    open ? h("span", {}, `${i + 1}. ${st.text}`)
      : [h("label", {}, h("input", { type: "checkbox", checked: st.done ? true : null,
          onchange: (e) => projAct(`/api/projects/${x.id}/steps/${i}`, { done: e.target.checked }) }), h("span", {}, st.text)),
         st.done ? null : h("button", { class: "btn btn-ghost btn-sm", type: "button", title: "Plan a reminder for this step; you approve it before anything is added",
           onclick: () => stepReminder(x, st) }, "Remind me")])));
  const buttons = open
    ? [h("button", { class: "btn btn-approve btn-sm", type: "button", onclick: () => projAct(`/api/projects/${x.id}/accept`) }, "Start this project"),
       h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: () => projAct(`/api/projects/${x.id}/dismiss`) }, "Not for me")]
    : [h("button", { class: "btn btn-sm", type: "button", onclick: () => projAct(`/api/projects/${x.id}/done`) }, "Mark finished"),
       h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: () => projAct(`/api/projects/${x.id}/reopen`) }, "Back to ideas")];
  const doneCount = x.steps.filter((st) => st.done).length;
  return h("li", { class: `proj ${x.state}` },
    h("small", {}, [x.kind_label, x.time, open ? null : `${doneCount}/${x.steps.length} steps done`, x.source === "polished" ? "polished by Claude" : null].filter(Boolean).join(" · ")),
    h("b", {}, x.title),
    x.why ? h("div", { class: "why" }, x.why) : null,
    evidence,
    h("div", { class: "kicker" }, open ? "First plan" : "Checklist"),
    steps,
    h("div", { class: "row mt" }, buttons));
}
function renderProjects(d) {
  const active = d.ideas.filter((x) => x.state === "active"), open = d.ideas.filter((x) => x.state === "open");
  const status = d.running ? h("p", { class: "d-why proj-thinking", role: "status" }, "Thinking of ideas on this Mac… (about a minute)")
    : d.error ? h("p", { class: "d-why" }, d.error)
    : d.last_run ? h("p", { class: "d-why" }, `Last looked ${new Date(d.last_run * 1000).toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" })}.`) : null;
  const consent = PROJ.consent ? h("div", { class: "job consent", role: "alert" },
    h("p", {}, PROJ.consent.summary),
    h("p", { class: "d-why" }, "Only the idea titles, times and steps are sent. Never your messages, memories or the reasons."),
    h("div", { class: "row mt" },
      h("button", { class: "btn btn-approve btn-sm", type: "button", onclick: () => projConsent(true) }, "Send to Claude"),
      h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: () => projConsent(false) }, "Don't send"))) : null;
  fill($("#projects"),
    h("section", { class: "proj-part" },
      h("p", { class: "d-why" }, "JARVIS reads what you've told it and what it remembers, on this Mac only, and suggests projects that fit you: growth and side projects, and things to build into JARVIS. Each shows where the idea came from."),
      status, h("p", { id: "proj-notice", class: "d-why", role: "status", hidden: PROJ.notice ? null : true }, PROJ.notice || ""), consent,
      h("div", { class: "row mt" },
        h("button", { class: "btn btn-sm", type: "button", disabled: d.running ? true : null, onclick: () => projAct("/api/projects/generate") }, "Find new ideas"),
        open.length ? h("button", { class: "btn btn-ghost btn-sm", type: "button", disabled: d.running ? true : null,
          title: "Sends only the idea list to Claude, after you approve", onclick: polishProjects }, "Polish with Claude") : null)),
    active.length ? h("section", { class: "proj-part" }, h("h3", { class: "sys-part" }, "Your projects"), h("ul", { class: "proj-list" }, active.map(projCard))) : null,
    h("section", { class: "proj-part" }, h("h3", { class: "sys-part" }, "Ideas"),
      open.length ? h("ul", { class: "proj-list" }, open.map(projCard))
        : h("div", { class: "empty" }, d.enough ? "No ideas waiting. Tap “Find new ideas”." : "Not enough to go on yet: talk with JARVIS a little, or tell it about your goals.")));
}

// ---------------------------------------------------------------- cinematic mode (presentation only)
// A view of the same live page: big reactor, the conversation as subtitles, voice up front. Switching sends
// nothing and changes nothing; decisions and problems stay visible in a slim strip, and Emergency stop stays put.
function setCinematic(on) {
  document.body.classList.toggle("cinematic", on);
  $("#cinebtn").setAttribute("aria-pressed", String(on));
  $("#cinebtn").textContent = on ? "Leave cinematic mode" : "Cinematic mode";
  try { localStorage.setItem("jarvis-cinematic", on ? "1" : "0"); } catch (e) { /* this visit only */ }
  if (ui.data) renderCineStrip(ui.data);
}
function renderCineStrip(d) {
  const strip = $("#cinestrip");
  const day = Date.now() - 24 * 3600 * 1000;
  const parts = [];
  if (d.approvals.length) parts.push(["◆", plural(d.approvals.length, "decision") + " waiting", "#/decisions"]);
  const blocked = d.tasks.filter((t) => t.state === "blocked").length;
  if (blocked) parts.push(["!", `${blocked} need${blocked === 1 ? "s" : ""} your input`, "#/missions"]);
  const failed = d.tasks.filter((t) => t.state === "failed" && Date.parse(t.updated_at) > day).length;
  if (failed) parts.push(["✗", `${failed} failed today`, "#/missions"]);
  const problems = d.health && !d.health.ok ? d.health.items.filter((i) => !i.ok).length : 0;
  if (problems) parts.push(["⚠", plural(problems, "system problem"), "#/systems"]);
  strip.hidden = !parts.length || !document.body.classList.contains("cinematic");
  if (parts.length > 1 && window.innerHeight < 720 && window.innerWidth <= 760) {
    // short phone screens: one line instead of several, so the conversation keeps its room
    parts.splice(0, parts.length, ["◆", `${parts.length} things need you`, "#/home"]);
  }
  strip.replaceChildren(...parts.map(([icon, text, hash]) => h("button", { class: "cine-item", type: "button", onclick: () => {
    setCinematic(false); location.hash = hash; } }, h("span", { "aria-hidden": "true" }, icon), " ", text)));
}

// ---------------------------------------------------------------- workspace: context beside the conversation
// Only what the latest reply and the live state already contain; contexts JARVIS can't support (code, files)
// are not shown at all rather than shown empty.
function renderContext(d) {
  const box = $("#context");
  const part = (title) => h("h3", { class: "sys-part" }, title);
  const last = [...ui.convo].reverse().find((m) => m.role === "assistant" && !m.welcome && !m.help && !m.briefing
                                                  && !m.consent && !m.error && !m.live && typeof m.text === "string");
  const answer = [];
  if (!last) {
    answer.push(part("The latest answer"), h("div", { class: "empty" }, "Ask something: what JARVIS looked up and its sources appear here."));
  } else {
    const srcs = (last.sources || []).filter((x) => /^https?:\/\//.test(x.url));
    answer.push(part(srcs.length ? "Sources for the latest answer" : "The latest answer"));
    if (srcs.length) answer.push(h("ul", { class: "sources" }, srcs.map((x) => h("li", { class: x.verified ? "ok" : "warn" },
      h("a", { href: x.url, target: "_blank", rel: "noopener noreferrer" }, x.url.replace(/^https?:\/\//, "")),
      x.verified ? " ✓ verified" : " · not seen by the research tools"))));
    if (last.checked && last.checked.length) answer.push(h("div", { class: "ctx-line" }, h("b", {}, "Looked up: "), last.checked.join(" · ")));
    else if (!srcs.length) answer.push(h("div", { class: "ctx-line" }, "Nothing was looked up for this answer."));
    if (last.meta) answer.push(h("div", { class: "ctx-line" }, h("b", {}, "Answered by: "), last.meta));
    if (last.plan) answer.push(h("div", { class: "ctx-line" }, "This sounds like something to do: the reply offers to turn it into a plan."));
  }
  const t = d.tasks.find((x) => NEEDS.includes(x.state)) || d.tasks.find((x) => ACTIVE.includes(x.state));
  const mission = [part("Current mission")];
  if (!t) {
    mission.push(h("div", { class: "empty" }, "No mission running. Switch to Do to start one."));
  } else {
    mission.push(h("div", { class: "ctx-mission" }, h("small", {}, `${STATE_WORDS[t.state] || t.state} · ${stepText(t)}`), h("b", {}, t.goal)),
      h("ol", { class: "steps" }, t.steps.map((x) => h("li", { class: x.state }, h("span", { class: "ic" }, ICON[x.state] || "·"), h("div", {}, x.description)))),
      t.next_action && t.state === "blocked" ? h("div", { class: "m-err" }, t.next_action) : null,
      h("div", { class: "row mt" }, h("button", { class: "btn btn-sm", type: "button", onclick: () => openMission(t.id) }, "Open in Missions"),
        h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: () => showTimeline(t.id) }, "Timeline")));
  }
  fill(box, answer, mission, part("Mode"), h("div", { class: "ctx-line" }, MODES[ui.mode][1]));
}

const touchOnly = () => window.matchMedia("(hover: none) and (pointer: coarse)").matches;
const isPhone = () => window.matchMedia("(max-width: 760px), (pointer: coarse)").matches;

// ---------------------------------------------------------------- display settings (this device only)
const DISPLAY_KEY = "jarvis-display";
const DISPLAY = { text: [["normal", "Normal"], ["large", "Large"], ["larger", "Larger"]],
                  density: [["comfortable", "Comfortable"], ["compact", "Compact"]],
                  fx: [["full", "Normal"], ["reduced", "Low performance"], ["off", "Reduced motion"]],
                  projection: [["subtle", "Subtle"], ["standard", "Standard"], ["vivid", "Vivid"]],
                  // projection controls (focus view): each changes the 3D projection only, on this device
                  // profiles (Avatar 2.5): the stored values stay the same; "lowpower" is new
                  quality: [["auto", "Auto"], ["high", "Quality"], ["balanced", "Balanced"], ["low", "Performance"], ["lowpower", "Low Power"]],
                  particles: [["low", "Low"], ["normal", "Normal"], ["high", "High"]],
                  animation: [["calm", "Calm"], ["normal", "Normal"], ["lively", "Lively"]],
                  reactor: [["soft", "Soft"], ["normal", "Normal"], ["bright", "Bright"]],
                  orbit: [["slow", "Slow"], ["normal", "Normal"], ["fast", "Fast"]],
                  env: [["on", "On"], ["off", "Off"]],
                  orbitals: [["on", "On"], ["off", "Off"]],
                  // camera (Avatar 2.5): the resting view, how fast inspection turns, and the renderer's real numbers
                  view: [["front", "Front"], ["three", "Three-quarter"], ["close", "Close"]],
                  camspeed: [["slow", "Slow"], ["normal", "Normal"], ["fast", "Fast"]],
                  diag: [["off", "Off"], ["on", "On"]],
                  sound: [["off", "Off"], ["on", "On"]] };   // ambient sound: off unless you turn it on (not part of presets)
const DISPLAY_DEFAULT = { text: "normal", density: "comfortable", fx: "full", projection: "standard", quality: "auto", particles: "normal",
                          animation: "normal", reactor: "normal", orbit: "normal", env: "on", orbitals: "on", view: "front", camspeed: "normal", diag: "off", sound: "off" };
function loadDisplay() {
  let d = {};
  try { d = JSON.parse(localStorage.getItem(DISPLAY_KEY) || "{}") || {}; } catch (e) { d = {}; }
  const out = {};
  for (const [key, def] of Object.entries(DISPLAY_DEFAULT)) out[key] = DISPLAY[key].some(([k]) => k === d[key]) ? d[key] : def;
  return out;
}
function saveDisplay(d) { try { localStorage.setItem(DISPLAY_KEY, JSON.stringify(d)); } catch (e) { /* this visit only */ } }
function avatarOptions(d) {
  return { quality: d.quality, particles: d.particles, animation: d.animation, reactor: d.reactor, orbit: d.orbit,
           env: d.env === "on", orbitals: d.orbitals === "on", panels: document.body.classList.contains("projection"), view: d.view, camspeed: d.camspeed,
           xray: d.xray === "on" };
}
// The working mode's look (focus view only) on top of your saved settings; the saved settings are never changed
function effectiveDisplay(d) {
  if (!document.body.classList.contains("projection")) return d;
  return { ...d, ...(ui.wlook || {}), ...(ui.flook || {}) };   // the form (your choice) wins over the mode
}
function applyDisplay(d) {
  const root = document.documentElement;
  root.dataset.text = d.text;
  root.dataset.density = d.density;
  root.dataset.fx = d.fx;
  const e = effectiveDisplay(d);
  root.dataset.projection = e.projection;
  if (window.JarvisAvatar) { JarvisAvatar.setOptions(avatarOptions(e)); JarvisAvatar.refresh(); }
  if (window.JarvisSound && JarvisSound.enabled !== (d.sound === "on")) { JarvisSound.setEnabled(d.sound === "on"); duckSound(); }
  renderDiag();
}

// ---- projection presets (Avatar 2.5): named sets of the settings above, on this device only (avatar-presets.js) ----
const PRESET_KEY = "jarvis-presets";
const displayValid = () => Object.fromEntries(Object.entries(DISPLAY).map(([k, v]) => [k, v.map(([x]) => x)]));
function loadPresets() {
  if (!window.JarvisPresets) return null;
  let raw = null;
  try { raw = JSON.parse(localStorage.getItem(PRESET_KEY) || "null"); } catch (e) { raw = null; }
  return JarvisPresets.normalise(raw, displayValid());
}
function savePresets(st) { try { localStorage.setItem(PRESET_KEY, JSON.stringify(st)); } catch (e) { /* this visit only */ } }
function applyPreset(id) {
  const st = loadPresets();
  if (!st) return;
  const r = JarvisPresets.activate(st, id);
  if (!r.ok) { note(r.error); return; }
  const d = { ...loadDisplay(), ...r.preset.s };
  saveDisplay(d); savePresets(r.state); applyDisplay(d);
  if (r.preset.enter === "focus" && !document.body.classList.contains("projection")) openProjection();
  renderProjControls();
}
function presetChange(op, id, name) {   // create / rename / update / duplicate / remove; built-ins are protected in avatar-presets.js
  const st = loadPresets();
  if (!st) return;
  const P = JarvisPresets, cur = loadDisplay(), v = displayValid();
  const r = op === "create" ? P.create(st, name, cur, v) : op === "rename" ? P.rename(st, id, name) : op === "update" ? P.update(st, id, cur, v)
    : op === "duplicate" ? P.duplicate(st, id) : P.remove(st, id);
  if (!r.ok) { note(r.error); return; }
  savePresets(r.state);
  if (op === "duplicate") { const p = P.find(r.state, r.id); saveDisplay({ ...cur, ...p.s }); applyDisplay({ ...cur, ...p.s }); }
  renderProjControls();
}
function presetSection() {
  const st = loadPresets();
  if (!st) return [];
  const P = JarvisPresets, cur = loadDisplay(), now = P.current(st, cur);
  const nameBox = (value, label, done) => {
    const input = h("input", { type: "text", maxlength: String(P.MAX_NAME), value: value || "", "aria-label": label, class: "pp-name", placeholder: "Preset name" });
    const go = () => done(input.value);
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); go(); } if (e.key === "Escape") { e.stopPropagation(); renderProjControls(); } });
    setTimeout(() => input.focus(), 0);
    return h("div", { class: "row pp-namerow" }, input, h("button", { class: "btn btn-sm", type: "button", onclick: go }, "Save"),
      h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: () => renderProjControls() }, "Cancel"));
  };
  const actions = h("div", { class: "row", role: "group", "aria-label": "Preset actions" });
  const edit = h("div");
  const btn = (text, fn, title) => h("button", { class: "btn btn-ghost btn-xs", type: "button", title: title || text, onclick: fn }, text);
  actions.append(btn("Save as new…", () => edit.replaceChildren(nameBox(now.modified ? "" : `${now.label} copy`, "Name for the new preset", (n) => presetChange("create", null, n)))),
    btn("Duplicate", () => presetChange("duplicate", now.id), `Copy “${now.label}” as your own preset`));
  if (!now.builtin) {
    actions.append(btn("Rename", () => edit.replaceChildren(nameBox(now.label, `New name for ${now.label}`, (n) => presetChange("rename", now.id, n)))),
      now.modified ? btn("Update", () => presetChange("update", now.id), `Save the current settings into “${now.label}”`) : null,
      btn("Delete", () => ask(`Delete the preset “${now.label}”? This only removes it from this device.`, { ok: "Delete" }).then((yes) => yes && presetChange("remove", now.id))));
  }
  return [h("h3", { class: "sys-part" }, "Presets"),
    h("p", { class: "hl-sub pp-now" }, now.modified ? `Custom — changed from ${now.label}` : `${now.label}: ${(P.find(st, now.id) || {}).desc || ""}`),
    h("div", { class: "row", role: "group", "aria-label": "Presets" }, P.list(st).map((p) =>
      h("button", { class: `chip${p.id === now.id && !now.modified ? " on" : ""}`, type: "button", "aria-pressed": String(p.id === now.id && !now.modified),
        title: p.desc, onclick: () => applyPreset(p.id) }, p.label))),
    actions, edit];
}

const QUALITY_WORD = { auto: "Auto", high: "Quality", balanced: "Balanced", low: "Performance", lowpower: "Low Power" };
const RENDER_STATUS = { loading: "Loading the 3D view…", "2d": "2D core (no 3D on this device)", lost: "GPU context lost: showing the 2D core, waiting for the browser to restore it",
  restarting: "Rebuilding the 3D view…", unavailable: "2D core: the 3D view couldn't load (it retries when JARVIS is reachable)",
  failed: "2D core: the 3D view failed three times (Projection controls → Rebuild 3D view)" };

// Low Power on battery: Auto switches to it only when the browser reports the battery low (20% or less) and not
// charging. Browsers without the Battery Status API (Safari, Firefox) report nothing, so nothing changes there.
function watchBattery() {
  if (!navigator.getBattery || !window.JarvisAvatar) return;
  navigator.getBattery().then((b) => {
    const upd = () => JarvisAvatar.setOptions({ lowBattery: !b.charging && b.level <= 0.2 });
    b.addEventListener("levelchange", upd); b.addEventListener("chargingchange", upd); upd();
  }).catch(() => { /* not available: nothing to do */ });
}

// ---- inspection (Avatar 2.5): orbit, zoom and pan around the projection in the focus view ----------------------
function startInspect() {
  if (!window.JarvisAvatar || JarvisAvatar.renderer !== "3d") { note("Inspection needs the 3D view (this device is showing the 2D core)."); return; }
  if (!document.body.classList.contains("projection")) openProjection();
  if (!JarvisAvatar.inspect(true)) return;
  document.body.classList.add("inspecting");
  renderInspectBar();
  $(".core-wrap").focus();
}
function stopInspect() {
  if (!document.body.classList.contains("inspecting")) return false;
  document.body.classList.remove("inspecting");
  if (window.JarvisAvatar) JarvisAvatar.inspect(false);
  reapplyForm();   // leaving inspection closes the armour: the form you chose opens it again
  const bar = $("#inspectbar"); if (bar) bar.hidden = true;
  renderProjControls();
  return true;
}
function renderInspectBar() {
  const bar = $("#inspectbar");
  if (!bar || !window.JarvisAvatar) return;
  const cam = JarvisAvatar.camera || {};
  bar.hidden = false;
  const chips = (items, on, fn, label) => h("div", { class: "ib-row", role: "group", "aria-label": label }, Object.entries(items).map(([k, text]) =>
    h("button", { class: `chip${on === k ? " on" : ""}`, type: "button", "aria-pressed": String(on === k), onclick: () => { fn(k); renderInspectBar(); } }, text)));
  bar.replaceChildren(
    h("div", { class: "ib-head" }, h("b", {}, "Inspecting"),
      h("small", {}, isPhone() ? "Drag to orbit · pinch to zoom · two fingers to pan" : "Drag or arrows to orbit · scroll or +/− to zoom · shift-drag to pan · Esc to exit"),
      h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: () => { JarvisAvatar.resetCamera(); renderInspectBar(); } }, "Reset"),
      h("button", { class: "btn btn-sm", type: "button", id: "inspectexit", onclick: stopInspect }, "Exit inspection")),
    chips(JarvisAvatar.views, cam.view, (k) => JarvisAvatar.cameraView(k), "Camera views"),
    chips(JarvisAvatar.targets, cam.focus, (k) => JarvisAvatar.inspectTarget(k), "Inspect a part"),
    chips({ ...JarvisAvatar.sequences, close: "Close the armour" }, (JarvisAvatar.transformState || {}).name || "close",
      (k) => JarvisAvatar.transform(k === "close" ? null : k), "Transform"));
}

// ---- diagnostics: the renderer's own numbers (measured, never estimated), shown when the Diagnostics setting is on ----
function renderDiag() {
  const el = $("#avdiag");
  if (!el) return;
  const on = effectiveDisplay(loadDisplay()).diag === "on" && document.body.classList.contains("projection") && window.JarvisAvatar;
  el.hidden = !on;
  clearInterval(ui.diagTimer); ui.diagTimer = 0;
  if (!on) return;
  const draw = () => {
    if (!document.body.classList.contains("projection")) { clearInterval(ui.diagTimer); ui.diagTimer = 0; el.hidden = true; return; }
    const s = JarvisAvatar.stats, cam = JarvisAvatar.camera, q = JarvisAvatar.qualityInfo, cx = JarvisAvatar.context;
    const limit = q && q.current === "lowpower" ? (isPhone() ? 15 : 20) : isPhone() ? 24 : 30;
    const t = (ms) => new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    const rows = JarvisAvatar.renderer !== "3d" || !s ? [["Renderer", RENDER_STATUS[JarvisAvatar.status] || "2D core"]] : [
      ["Renderer", "3D (WebGL)"], ["Quality", q ? `${QUALITY_WORD[q.current] || q.current} · ${q.setting === "auto" ? `Auto: ${q.reason}` : "your setting"}` : "—"],
      ...(q && q.log.length ? [["Last change", (() => { const l = q.log[q.log.length - 1]; return `${t(l.at)} ${QUALITY_WORD[l.from] || l.from} → ${QUALITY_WORD[l.to] || l.to} (${l.why}${l.avgMs ? `, ${l.avgMs} ms avg` : ""})`; })()]] : []),
      ["Frame time", s.frameMs ? `${s.frameMs.toFixed(1)} ms (${Math.round(1000 / s.frameMs)} fps; limit ${limit})` : "idle — drawn only when something changes"],
      ...(cx && cx.losses ? [["GPU context", `lost ${cx.losses}×, restored ${cx.restores}×`]] : []),
      ["Draw calls", String(s.calls)], ["Triangles", s.triangles.toLocaleString()],
      ["Camera", cam ? `${cam.inspecting ? "inspecting" : "resting"} · ${cam.focus || cam.view}` : "—"]];
    el.replaceChildren(h("b", {}, "Diagnostics"), ...rows.map(([k, v]) => h("div", {}, h("span", {}, k), h("span", {}, v))));
  };
  draw();
  ui.diagTimer = setInterval(draw, 1000);
}
function showDisplaySettings() {
  const cur = loadDisplay();
  const choose = (key) => h("div", { class: "row", role: "group", "aria-label": { text: "Text size", density: "Density", fx: "Effects", projection: "Projection intensity" }[key] },
    DISPLAY[key].map(([value, label]) => h("button", { class: `chip${cur[key] === value ? " on" : ""}`, type: "button", "aria-pressed": String(cur[key] === value),
      onclick: (e) => {
        cur[key] = value;
        try { localStorage.setItem(DISPLAY_KEY, JSON.stringify(cur)); } catch (err) { /* this visit only */ }
        applyDisplay(cur);
        e.target.parentNode.querySelectorAll("button").forEach((b) => { const on = b === e.target; b.classList.toggle("on", on); b.setAttribute("aria-pressed", String(on)); });
      } }, label)));
  const dlg = h("dialog", { class: "pairdlg askdlg", "aria-labelledby": "disp-h" },
    h("h2", { id: "disp-h" }, "Display"),
    h("p", { class: "hl-sub" }, "Only for this device. Reduced motion follows your system setting."),
    h("h3", { class: "sys-part" }, "Text size"), choose("text"),
    h("h3", { class: "sys-part" }, "Density"), choose("density"),
    h("h3", { class: "sys-part" }, "Effects"),
    h("p", { class: "hl-sub" }, "Normal: the full 3D hologram and a gently moving environment. Low performance: the hologram is redrawn only when JARVIS's state changes, and the background is still. Reduced motion: nothing moves (also follows your system setting). Chat is never slowed by any of them."),
    choose("fx"),
    h("h3", { class: "sys-part" }, "Projection intensity"),
    h("p", { class: "hl-sub" }, "How bright the holographic projection and its surroundings are. Separate from Effects: it changes light, not motion."),
    choose("projection"),
    h("div", { class: "row mt" }, h("button", { class: "btn", type: "button", onclick: () => { dlg.close(); dlg.remove(); } }, "Done")));
  dlg.addEventListener("close", () => dlg.remove());
  document.body.append(dlg);
  dlg.showModal();
}

// ---------------------------------------------------------------- keyboard shortcuts (Mac): they only move around
// None of them approves, rejects, sends, runs, pauses, cancels or stops anything.
const GO_KEYS = { h: "home", w: "workspace", m: "missions", d: "decisions", r: "memory", s: "systems", i: "intelligence" };
function showShortcuts() {
  const row = (keys, what) => h("li", {}, keys.map((k) => h("kbd", {}, k)), " ", what);
  const dlg = h("dialog", { class: "pairdlg askdlg", "aria-labelledby": "keys-h" },
    h("h2", { id: "keys-h" }, "Keyboard shortcuts"),
    h("ul", { class: "keys" },
      row(["/"], "type a message"), row(["g", "h"], "Home"), row(["g", "w"], "Workspace"), row(["g", "m"], "Missions"),
      row(["g", "d"], "Decisions"), row(["g", "r"], "Memory"), row(["g", "s"], "Systems"), row(["g", "i"], "Briefing & ideas"),
      row(["c"], "cinematic mode on / off"), row(["Esc"], "stop reading aloud, close menus"), row(["?"], "this list")),
    h("p", { class: "hl-sub" }, "Shortcuts only move around. Approving, sending and stopping always need a click or tap."),
    h("div", { class: "row mt" }, h("button", { class: "btn", type: "button", onclick: () => { dlg.close(); dlg.remove(); } }, "Close")));
  dlg.addEventListener("close", () => dlg.remove());
  document.body.append(dlg);
  dlg.showModal();
}
function onShortcut(e) {
  const t = e.target;
  if (e.metaKey || e.ctrlKey || e.altKey || document.querySelector("dialog[open]")) return;
  if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
  if (ui.goPending) {
    ui.goPending = false;
    if (GO_KEYS[e.key]) { e.preventDefault(); location.hash = `#/${GO_KEYS[e.key]}`; }
    return;
  }
  if (e.key === "/") {
    e.preventDefault();
    if (!["home", "workspace"].includes(document.body.dataset.view)) { location.hash = "#/home"; setView("home"); }  // show the box before focusing it
    $("#cmd").focus();
  }
  else if (e.key === "g") { ui.goPending = true; setTimeout(() => { ui.goPending = false; }, 1200); }
  else if (e.key === "c") setCinematic(!document.body.classList.contains("cinematic"));
  else if (e.key === "?") showShortcuts();
}

async function memAct(path, body) {
  try { await call(path, body); } catch (e) { note(cancelled(e)); }
  await refresh(); await loadMemory(true);
}

async function forgetMatching() {
  const preview = await api("/api/memory/forget", { query: ui.memQ });
  const tasks = (preview.tasks || []).filter((t) => t.deletable).length;
  if (!await ask(`Permanently delete ${plural(preview.memories.length, "memory").replace("memorys", "memories")}, ${plural(preview.records.length, "conversation record")} and ${plural(tasks, "finished task")} about “${ui.memQ}”?\n\nThis can't be undone. If you later restore an older backup, these deletions are applied again, so nothing comes back.`, { ok: "Forget", danger: true })) return;
  await memAct("/api/memory/forget", { query: ui.memQ, confirm: true });
}

// ---------------------------------------------------------------- loop
// ---------------------------------------------------------------- Home: what matters now, suggestions, systems summary
// Everything here is read from the same /api/state snapshot; nothing is estimated or invented.
// Decisions are not repeated here: their own panel sits beside (Mac) or above (iPhone) this list on Home.
const DAY_MS = 24 * 3600 * 1000;
// replaceChildren with optional parts: leaves out null/false instead of printing "null"
const fill = (el, ...kids) => el.replaceChildren(...kids.flat(Infinity).filter((k) => k !== null && k !== undefined && k !== false));
function renderMatters(d) {
  const items = [];
  const go = (hash) => () => { location.hash = hash; };
  for (const t of d.tasks) {
    if (t.state === "blocked") {
      items.push({ cls: "attention", icon: "!", label: "Needs your input", title: t.goal,
                   sub: t.next_action || "This mission is waiting for you.", action: ["Open", () => showTimeline(t.id)] });
    } else if (t.state === "paused") {
      items.push({ cls: "", icon: "Ⅱ", label: "Paused", title: t.goal, sub: "Nothing runs until you resume it in Missions.",
                   action: ["Missions", go("#/missions")] });
    } else if (t.state === "failed" && Date.now() - Date.parse(t.updated_at) < DAY_MS) {
      items.push({ cls: "bad", icon: "✗", label: "Failed", title: t.goal, sub: t.error || "The timeline shows what happened.",
                   action: ["Timeline", () => showTimeline(t.id)] });
    }
  }
  if (d.health && !d.health.ok) {
    for (const i of d.health.items.filter((x) => !x.ok)) {
      items.push({ cls: "bad", icon: "⚠", label: "System", title: i.name, sub: i.detail, action: ["Details", go("#/systems")] });
    }
  }
  const box = $("#matters");
  document.body.classList.toggle("has-matters", items.length > 0);
  if (!items.length) {
    box.replaceChildren(h("p", { class: "matters-quiet" }, d.approvals.length ? "Nothing else needs you." : "Nothing needs you right now."));
    return;
  }
  fill(box, h("h2", { class: "matters-h" }, "What matters now"),
    h("ul", { class: "matters-list" }, items.slice(0, 3).map((x) => h("li", { class: `matter ${x.cls}` },
      h("span", { class: "m-icon", "aria-hidden": "true" }, x.icon),
      h("div", { class: "m-text" }, h("small", {}, x.label), h("b", {}, x.title), h("span", {}, x.sub)),
      h("button", { class: "btn btn-sm", type: "button", onclick: x.action[1] }, x.action[0])))),
    items.length > 3 ? h("p", { class: "matters-quiet" }, `+${items.length - 3} more in `,
      h("a", { href: "#/missions" }, "Missions"), " and ", h("a", { href: "#/systems" }, "Systems"), ".") : null);
}

function renderSuggestions(d) {
  // Three things this JARVIS can do right now (same capability-aware list as Help); hidden once you're mid-conversation.
  const box = $("#suggest");
  if (ui.convo.some((m) => m.role === "user")) { box.replaceChildren(); return; }
  const key = JSON.stringify(d.capabilities || {});
  if (box.dataset.key === key && box.childElementCount) return;
  box.dataset.key = key;
  const picks = helpExamples(d).map(([mode, , , ex]) => [mode, ex[0][0]]).slice(0, 3);
  box.replaceChildren(...picks.map(([mode, text]) => h("button", { class: "chip", type: "button", onclick: () => {
    setMode(mode);
    $("#cmd").value = text;
    saveDraft();
    $("#cmd").focus();
  } }, h("small", {}, mode === "do" ? "Do" : mode === "research" ? "Research" : "Ask"), text)));
}

// ---- Systems panel as an Iron Man-style HUD module: radial gauges, a response-time trace, compact rows ----------
// Every figure is real (telemetry, model availability, the audit log, the budget); unknown values show "—" and no arc.
// Built once and updated in place, so the rings keep turning smoothly between polls.
const SVGNS = "http://www.w3.org/2000/svg";
const sv = (tag, attrs = {}, ...kids) => { const el = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v); kids.forEach((k) => el.append(k)); return el; };
const ARC = 2 * Math.PI * 44, SWEEP = ARC * 0.75;   // a 270-degree gauge on r = 44
function hudGauge(label) {
  const ticks = sv("g", { class: "g-ticks" });
  for (let i = 0; i < 60; i++) {
    const a = (i / 60) * Math.PI * 2, long = i % 5 === 0, r0 = long ? 50 : 53;
    ticks.append(sv("line", { x1: 60 + Math.cos(a) * r0, y1: 60 + Math.sin(a) * r0, x2: 60 + Math.cos(a) * 57, y2: 60 + Math.sin(a) * 57, class: long ? "t-major" : "t-minor" }));
  }
  const value = sv("circle", { cx: 60, cy: 60, r: 44, class: "g-value", "stroke-dasharray": `0 ${ARC}`, transform: "rotate(135 60 60)" });
  const num = sv("text", { x: 60, y: 62, class: "g-num", "text-anchor": "middle" }, "—");
  const unit = sv("text", { x: 60, y: 78, class: "g-unit", "text-anchor": "middle" }, "");
  const svg = sv("svg", { viewBox: "0 0 120 120", class: "g-svg", "aria-hidden": "true" },
    sv("g", { class: "g-spin" }, ticks),
    sv("circle", { cx: 60, cy: 60, r: 44, class: "g-track", "stroke-dasharray": `${SWEEP} ${ARC}`, transform: "rotate(135 60 60)" }),
    value,
    sv("g", { class: "g-spin-rev" }, sv("circle", { cx: 60, cy: 60, r: 35, class: "g-inner" })),
    num, unit);
  const wrap = h("div", { class: "hud-gauge" }, svg, h("span", { class: "g-label" }, label));
  wrap.set = (ratio, text, unitText, cls) => {
    const known = ratio !== null && ratio !== undefined && Number.isFinite(ratio);
    value.setAttribute("stroke-dasharray", `${known ? SWEEP * Math.max(0, Math.min(1, ratio)) : 0} ${ARC}`);
    num.textContent = text; unit.textContent = unitText || "";
    wrap.className = `hud-gauge${cls ? ` ${cls}` : ""}${known ? "" : " unknown"}`;
    wrap.setAttribute("aria-label", `${label}: ${text}${unitText ? ` ${unitText}` : ""}`);
  };
  return wrap;
}
// recent model response times, from the audit log (oldest first)
function responseTimes(d) {
  const out = [];
  for (const e of [...(d.audit || [])].reverse()) {
    const m = e.event === "egress.received" ? /in ([\d.]+)s/.exec(e.detail || "") : e.event === "model.local_call" ? /, ([\d.]+)s\)/.exec(e.detail || "") : null;
    if (m) out.push({ s: Number(m[1]), local: e.event === "model.local_call" });
  }
  return out.slice(-18);
}
function renderSummary(d) {
  const box = $("#summary");
  if (!box.hud) {
    const g = { cpu: hudGauge("CPU"), mem: hudGauge("Memory"), models: hudGauge("Models") };
    const trace = sv("svg", { viewBox: "0 0 180 36", class: "trace-svg", preserveAspectRatio: "none", "aria-hidden": "true" });
    const traceVal = h("b", {}, "—");
    const rows = h("div", { class: "hud-rows" });
    box.replaceChildren(h("div", { class: "hud-gauges" }, g.cpu, g.mem, g.models),
      h("div", { class: "hud-trace" }, h("div", { class: "trace-h" }, h("span", {}, "Model response"), traceVal), trace), rows);
    box.hud = { g, trace, traceVal, rows };
  }
  const { g, trace, traceVal, rows } = box.hud;
  const t = d.telemetry || {};
  const m = d.models || { providers: [], budget: {} };
  const online = m.providers.reduce((n, p) => n + p.available.length, 0);
  const total = m.providers.reduce((n, p) => n + p.configured.length, 0);
  if (t.cpu && t.cpu.available) g.cpu.set(Math.min(1, t.cpu.load_per_core / 1.5), String(t.cpu.load_per_core), "per core", t.cpu.load_per_core > 1.5 ? "bad" : "");
  else g.cpu.set(null, "—", "no data");
  if (t.memory && t.memory.available) g.mem.set(t.memory.used_pct / 100, `${Math.round(t.memory.used_pct)}%`, "used", t.memory.used_pct > 90 ? "bad" : "");
  else g.mem.set(null, "—", "no data");
  g.models.set(total ? online / total : null, total ? `${online}/${total}` : "—", "online", total && !online ? "bad" : "");
  // the response-time trace: one bar per recent model call (taller = slower), local calls in silver
  const times = responseTimes(d);
  const max = Math.max(1, ...times.map((x) => x.s));
  trace.replaceChildren(sv("line", { x1: 0, y1: 35.5, x2: 180, y2: 35.5, class: "trace-base" }),
    ...times.map((x, i) => { const hgt = Math.max(2, (x.s / max) * 32), w = 180 / 18;
      return sv("rect", { x: (18 - times.length + i) * w + 1.5, y: 35 - hgt, width: w - 3, height: hgt, class: x.local ? "tr-local" : "tr-cloud" }); }));
  traceVal.textContent = times.length ? `${times[times.length - 1].s.toFixed(1)} s` : "no calls yet";
  const active = d.tasks.filter((x) => ACTIVE.includes(x.state)).length;
  const claude = (m.cloud_usage || []).find((u) => u.provider === "claude");
  const ro = (label, value, cls, ratio) => h("div", { class: "ro" }, h("span", {}, label), h("b", { class: cls || null }, value), meter(ratio));
  rows.replaceChildren(
    ro("Health", !d.health ? "Checking…" : d.health.ok ? "✓ Healthy" : `⚠ ${plural(d.health.items.filter((i) => !i.ok).length, "problem")}`,
       d.health && !d.health.ok ? "bad" : d.health ? "ok" : null),
    ro("Missions active", String(active)),
    claude ? ro("Claude", claude.limited_until ? `resets ${clock(claude.limited_until)}` : `${claude.calls} calls · 5h`) : null,
    ro("Spent this month", `$${(m.budget.spent_this_month_usd || 0).toFixed(2)} of $${(m.budget.monthly_limit_usd || 0).toFixed(2)}`, null,
       m.budget.monthly_limit_usd ? (m.budget.spent_this_month_usd || 0) / m.budget.monthly_limit_usd : null));
}

function render() {
  const d = ui.data;
  renderHead(d);
  renderFeed(d);
  if (!d) return;
  renderMatters(d);
  renderCineStrip(d);
  renderContext(d);
  renderSuggestions(d);
  renderSummary(d);
  renderSysbar(d);
  if (document.body.dataset.view === "command") renderCommand(d);
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

// Your rating is the learning engine's main signal about quality (stored on this Mac; it changes nothing by itself).
async function rateAnswer(m, rating) {
  try {
    await api("/api/feedback", { target: "reply", ref: m.ref, rating, model: m.rmodel || null, mode: m.rmode || null });
    m.rated = rating; ui.lastFeed = ""; render();
  } catch (e) { note(`Couldn't save your rating: ${e.message}`); }
}

// ---------------------------------------------------------------- Evolution center: learning, experiments, autonomy
// Every number comes from /api/learn (outcomes, lessons, experiments, autonomy) or the tournament; nothing is estimated.
async function loadEvolution() {
  const el = $("#evo");
  if (!el) return;
  let data, tour;
  try { [data, tour] = await Promise.all([api("/api/learn"), api("/api/learn/tournament")]); }
  catch (e) { el.replaceChildren(h("p", { class: "empty" }, `Couldn't load: ${e.message}`)); return; }
  ui.evo = data;
  const s = data.summary, a = data.autonomy;
  const pct = (x, n) => (n ? `${Math.round((100 * x) / n)}%` : "—");
  const kindWord = { confirmed: "Confirmed by you", user: "Stated by you", inferred: "Inferred", hypothesis: "Hypothesis (contested)", outdated: "Outdated" };
  const lessonRow = (l) => h("li", { class: `lesson ${l.kind} ${l.polarity > 0 ? "good" : l.polarity < 0 ? "bad" : ""}` },
    h("div", { class: "l-head" }, h("span", { class: `l-kind ${l.kind}` }, kindWord[l.kind] || l.kind),
      h("span", { class: "l-conf", title: "Confidence grows with the number of observations" }, `confidence ${Math.round(l.confidence * 100)}%`),
      h("span", { class: "l-when" }, `first ${since(l.first_seen)} · last ${since(l.last_seen)}`)),
    h("b", {}, l.statement),
    h("small", { class: "l-ev" }, "Evidence: ", Object.entries(l.evidence).filter(([k]) => k !== "task_ids" && k !== "contested")
      .map(([k, v]) => `${k.replace(/_/g, " ")} ${v}`).join(" · ") || "—"),
    h("div", { class: "row" }, ["confirm", "reject", "delete"].map((dec) => h("button", { class: "btn btn-ghost btn-xs", type: "button",
      onclick: async () => { try { await api(`/api/lessons/${l.id}/${dec}`, {}); loadEvolution(); } catch (e) { note(e.message); } } },
      dec === "confirm" ? "Confirm" : dec === "reject" ? "Reject" : "Delete"))));
  const exp = (x) => h("li", { class: `exp ${x.state}` }, h("div", { class: "l-head" }, h("span", { class: `l-kind ${x.state}` }, x.state),
      h("span", {}, x.kind), h("span", { class: "l-when" }, since(x.created_at))),
    h("b", {}, x.objective), h("small", {}, `Hypothesis: ${x.hypothesis} · Baseline: ${x.baseline} · Criteria: ${x.criteria} · Environment: ${x.environment}`),
    x.recommendation ? h("p", { class: "exp-rec" }, x.recommendation) : null);
  const tier = (t) => h("li", { class: `tier ${t.on ? "on" : ""}` },
    h("label", {}, h("input", { type: "checkbox", checked: t.on, disabled: t.tier > 5 && !t.on,
      onchange: async (e) => { try { await api("/api/autonomy", { tier: t.tier, on: e.target.checked }); loadEvolution(); } catch (err) { note(err.message); e.target.checked = !e.target.checked; } } }),
      h("b", {}, `Tier ${t.tier} · ${t.name}`)), h("small", {}, t.tier > 5 && !t.on ? `${t.about} Only from the Mac's terminal.` : t.about));
  const pause = (p) => h("button", { class: `chip${a.paused[p] ? " on" : ""}`, type: "button", "aria-pressed": String(a.paused[p]),
    onclick: async () => { try { await api("/api/autonomy", { pause: p, paused: !a.paused[p] }); loadEvolution(); } catch (e) { note(e.message); } } },
    `${a.paused[p] ? "Resume" : "Pause"} ${p}`);
  const prof = (p) => h("tr", {}, h("td", {}, p.model), h("td", {}, p.replies ? `${p.verified}/${p.replies}` : "—"),
    h("td", {}, p.median_s !== null ? `${p.median_s} s` : "—"), h("td", {}, p.helpful + p.not_helpful ? `👍 ${p.helpful} · 👎 ${p.not_helpful}` : "—"),
    h("td", {}, Object.entries(p.bench).map(([c, b]) => `${c} ${b.passed}/${b.scored}`).join(" · ") || "—"));
  el.replaceChildren(
    h("section", { class: "evo-sec" }, h("h3", { class: "sys-part" }, `Last ${s.window_days} days`),
      h("div", { class: "page-stats" },
        statTile("Missions verified", `${s.missions.verified}/${s.missions.total}`, pct(s.missions.verified, s.missions.total)),
        statTile("Answers passing checks", `${s.replies.verified}/${s.replies.total}`, pct(s.replies.verified, s.replies.total)),
        statTile("Recovered", String(s.recovered), "after a problem"), statTile("Your ratings", `👍 ${s.feedback.helpful} · 👎 ${s.feedback.not_helpful}`),
        statTile("Lessons", String(s.lessons)), statTile("Last learning cycle", s.last_cycle ? since(s.last_cycle) : "not yet")),
      a.stopped ? h("p", { class: "warn-line" }, "The emergency stop is on: observing, learning, experiments and proposals are all halted.") : null),
    h("section", { class: "evo-sec" }, h("h3", { class: "sys-part" }, "What JARVIS has learned"),
      h("p", { class: "hl-sub" }, "Lessons come from fixed rules over JARVIS's own record (no model, nothing leaves the Mac). They change nothing by themselves; strong negative ones become proposals."),
      data.lessons.length ? h("ul", { class: "lessons" }, data.lessons.map(lessonRow)) : h("p", { class: "empty" }, "No lessons yet: they appear once there's enough evidence (e.g. 5 checked answers from one model).")),
    h("section", { class: "evo-sec" }, h("h3", { class: "sys-part" }, "Intelligence tournament"),
      h("p", { class: "hl-sub" }, "Evidence per model: answers passing the check, median time, your ratings and benchmark categories. A suggestion never changes routing by itself."),
      tour.profiles.length ? h("table", { class: "tour" }, h("thead", {}, h("tr", {}, ["Model", "Checks passed", "Median", "Your ratings", "Benchmark"].map((x) => h("th", {}, x)))),
        h("tbody", {}, tour.profiles.map(prof))) : h("p", { class: "empty" }, "No answers or benchmark runs recorded yet."),
      tour.recommendation ? h("p", { class: "exp-rec" }, tour.recommendation.text) : null),
    h("section", { class: "evo-sec" }, h("h3", { class: "sys-part" }, "Done on its own (tier 7)"),
      h("p", { class: "hl-sub" }, a.allowed.operate ? "On: nightly self-checks after 03:00 and small routing nudges from strong lessons (only among models already allowed). Each nudge can be undone."
        : "Off. Turn on from the Mac's terminal: jarvis autonomy enable 7 (needs tiers 1–6)."),
      (data.adjustments || []).length ? h("ul", { class: "lessons" }, data.adjustments.map((x) => h("li", { class: x.active ? (x.bonus > 0 ? "good" : "bad") : "" },
        h("div", { class: "l-head" }, h("span", { class: `l-kind ${x.active ? "confirmed" : "outdated"}` }, x.active ? "Active" : "Undone"),
          h("span", {}, `${x.model} ${x.bonus > 0 ? "+" : ""}${x.bonus}`), h("span", { class: "l-when" }, since(x.at))),
        h("small", {}, x.why),
        x.active ? h("div", { class: "row" }, h("button", { class: "btn btn-ghost btn-xs", type: "button",
          onclick: async () => { try { await api("/api/adjustments/undo", { lesson: x.lesson }); loadEvolution(); } catch (e) { note(e.message); } } }, "Undo")) : null)))
        : h("p", { class: "empty" }, "Nothing adjusted yet.")),
    h("section", { class: "evo-sec" }, h("h3", { class: "sys-part" }, "Simulation lab"),
      h("form", { class: "row trial-form", onsubmit: async (e) => { e.preventDefault();
          const ref = e.target.querySelector("input").value.trim();
          try { await api("/api/experiments", { kind: "trial", ref }); setTimeout(loadEvolution, 400); } catch (err) { note(err.message); } } },
        h("label", { class: "sr", for: "trialref" }, "Branch or commit to try"),
        h("input", { id: "trialref", type: "text", placeholder: a.allowed.execute ? "Branch or commit to try (e.g. my-fix)" : "Change trials need tier 6 (Mac terminal: jarvis autonomy enable 6)",
                     disabled: !a.allowed.execute, maxlength: "120", autocomplete: "off" }),
        h("button", { class: "btn btn-sm", type: "submit", disabled: !a.allowed.execute || s.experiments_running > 0 }, "Run change trial")),
      h("div", { class: "row" }, Object.entries(data.kinds).filter(([kind]) => kind !== "trial").map(([kind, about]) => h("button", { class: "btn btn-sm", type: "button", title: about,
        disabled: !a.allowed.experiment || s.experiments_running > 0,
        onclick: async () => { try { await api("/api/experiments", { kind }); setTimeout(loadEvolution, 400); } catch (e) { note(e.message); } } },
        { replay: "Run routing replay", drill: "Run recovery drills", bench_compare: "Compare benchmarks" }[kind] || kind))),
      h("ul", { class: "hl-sub kinds" }, Object.entries(data.kinds).map(([k, v]) => h("li", {}, h("b", {}, k), ` — ${v}`))),
      data.experiments.length ? h("ul", { class: "lessons" }, data.experiments.map(exp)) : h("p", { class: "empty" }, "No experiments yet.")),
    h("section", { class: "evo-sec" }, h("h3", { class: "sys-part" }, "Improvements"),
      h("p", { class: "hl-sub" }, "Proposals are propose-only: you approve or reject each; code changes go through a reviewed branch."),
      h("a", { class: "btn btn-sm", href: "/proposals" }, "Open proposals")),
    h("section", { class: "evo-sec" }, h("h3", { class: "sys-part" }, "Capabilities JARVIS could use"),
      h("ul", { class: "lessons" }, data.discoveries.map((x) => h("li", { class: `disc ${x.available ? "on" : ""}` },
        h("div", { class: "l-head" }, h("span", { class: `l-kind ${x.available ? "confirmed" : "inferred"}` }, x.available ? "In use" : "Available"),
          h("span", {}, `cost ${x.cost}`), h("span", {}, x.privacy)), h("b", {}, x.title), h("small", {}, x.why), x.available ? null : h("small", { class: "l-ev" }, `How: ${x.how}`))))),
    h("section", { class: "evo-sec" }, h("h3", { class: "sys-part" }, "Autonomy"),
      h("p", { class: "hl-sub" }, "A tier works only when every tier below it is on. External messages, spending, sensitive data, destructive actions and changes to JARVIS itself always ask you."),
      h("ul", { class: "tiers" }, a.tiers.map(tier)), h("div", { class: "row" }, ["learning", "experiments", "initiative"].map(pause))),
    h("section", { class: "evo-sec" }, h("h3", { class: "sys-part" }, "Projection studio"),
      h("p", { class: "hl-sub" }, "Open a projection around the avatar (real data only; each one says where its data comes from)."),
      h("div", { class: "row" }, PROJ_MODULES.map(([m, label]) => h("button", { class: "btn btn-sm", type: "button",
        onclick: () => { location.hash = "#/home"; setTimeout(() => openProjectionModule(m), 300); } }, label))),
      h("p", { class: "hl-sub" }, "Intensity, particles, animation, quality and the rest are under Projection controls in the focus view (click the avatar).")));
}
const PROJ_MODULES = [["workflow", "Workflow map"], ["architecture", "Software architecture"], ["neural", "Knowledge network"], ["globe", "Globe"],
  ["data", "Data"], ["timeline", "Timeline"], ["security", "Security shield"], ["simulation", "Simulation"], ["research", "Research sources"]];

// ---------------------------------------------------------------- shell: sections, badges, sidebar, drafts
// Sections are views of the same live page: switching never pauses, resumes or changes anything.
const VIEWS = ["home", "command", "workspace", "missions", "decisions", "memory", "systems", "evolution", "intelligence", "projects"];
function viewFromHash() {
  const m = location.hash.match(/^#\/(\w+)/);
  return m && VIEWS.includes(m[1]) ? m[1] : null;
}
function setView(view) {
  if (!VIEWS.includes(view)) view = "home";
  const changed = document.body.dataset.view !== view;
  document.body.dataset.view = view;
  if (ui.data) renderPageHud(ui.data);
  document.querySelectorAll("#sidenav a[data-view]").forEach((a) => {
    if (a.dataset.view === view) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
  if (changed) { window.scrollTo(0, 0); if (ui.data) renderMissions(ui.data.tasks); if (view === "intelligence") loadIntel(); if (view === "evolution") loadEvolution(); if (view === "projects") loadProjects(true); if (view === "command" && ui.data) { ui.ccKey = ""; renderCommand(ui.data); } }
}
function badge(name, n) {
  const el = $(`#badge-${name}`);
  if (!el) return;
  el.hidden = !n;
  el.textContent = n > 9 ? "9+" : String(n || "");
  el.setAttribute("aria-label", `${n} ${name === "decisions" ? "waiting for you" : "live"}`);
}
function setNavCollapsed(collapsed) {
  document.body.classList.toggle("nav-collapsed", collapsed);
  $("#navcollapse").setAttribute("aria-expanded", String(!collapsed));
  try { localStorage.setItem("jarvis-nav-collapsed", collapsed ? "1" : "0"); } catch (e) { /* this visit only */ }
}
// The unsent message survives reloads and section changes (this browser tab only; gone when the tab closes).
const DRAFT_KEY = "jarvis-draft";
function saveDraft() { try { sessionStorage.setItem(DRAFT_KEY, $("#cmd").value); } catch (e) { /* not kept */ } }
function clearDraft() { try { sessionStorage.removeItem(DRAFT_KEY); } catch (e) { /* nothing kept */ } }
function restoreDraft() {
  try { const d = sessionStorage.getItem(DRAFT_KEY); if (d && !$("#cmd").value) $("#cmd").value = d; } catch (e) { /* none */ }
}

function flashOnFinish(d) {
  const now = new Map(d.tasks.map((t) => [t.id, t.state]));
  const before = ui.taskStates;
  ui.taskStates = now;
  if (!before) return;
  let flash = null;
  for (const [id, state] of now) {
    if (before.get(id) === state || !before.has(id)) continue;
    if (state === "failed") flash = "failed";
    else if (state === "completed" && flash !== "failed") flash = "done";
  }
  if (!flash) return;
  const core = $("#core");
  core.dataset.flash = flash;
  clearTimeout(ui.flashTimer);
  ui.flashTimer = setTimeout(() => { delete core.dataset.flash; }, 4000);
}

// ---------------------------------------------------------------- Touch ID sign-in (Mac, once Touch ID is set up)
// The one fingerprint per browser session (at most every 12 hours). Emergency stop works without it.
function showSignIn() {
  document.body.classList.add("locked");  // nothing readable behind the sign-in box; the header and Emergency stop stay
  if (document.getElementById("signin")) return;
  const msg = h("p", { class: "hl-sub", role: "status" }, "Your dashboard is protected with Touch ID.");
  const btn = h("button", { class: "btn btn-approve", type: "button", onclick: async () => {
    btn.disabled = true;
    msg.textContent = "Touch the sensor…";
    try {
      const o = await api("/api/touchid/signin/options", {});
      const a = await withTap(() => navigator.credentials.get({ publicKey: {
        challenge: b64u.toBuf(o.challenge), rpId: o.rpId, timeout: o.timeout, userVerification: o.userVerification,
        allowCredentials: o.allowCredentials.map((c) => ({ ...c, id: b64u.toBuf(c.id) })) } }), "Sign in with Touch ID");
      await api("/api/touchid/signin", { challengeId: o.challengeId, credential: { ...credJSON(a),
        response: { clientDataJSON: b64u.fromBuf(a.response.clientDataJSON), authenticatorData: b64u.fromBuf(a.response.authenticatorData),
                    signature: b64u.fromBuf(a.response.signature) } } });
      location.reload();
    } catch (e) {
      msg.textContent = e.name === "NotAllowedError" ? "Touch ID was cancelled. Try again." : `Couldn't sign in: ${e.message}`;
      btn.disabled = false;
    }
  } }, "Sign in with Touch ID");
  // The sign-in box blocks the rest of the page, so Emergency stop is right here too (it never needs signing in).
  const stop = h("button", { class: "btn btn-danger", type: "button", onclick: async () => {
    stop.disabled = true;
    try { await api("/api/stop", { reason: "stopped from the sign-in screen" }); stop.textContent = "Stopped · sign in to release it"; }
    catch (e) { stop.disabled = false; stop.textContent = `Stop failed: ${e.message}`; }
  } }, "Emergency stop");
  const dlg = h("dialog", { class: "pairdlg", id: "signin" },
    h("h2", {}, "Sign in"), msg, h("div", { class: "row mt center" }, btn, stop),
    h("p", { class: "d-why" }, "Emergency stop works without signing in. Touch ID not working? In Terminal: uv run jarvis touchid reset --yes"));
  dlg.addEventListener("cancel", (e) => e.preventDefault());  // Esc doesn't skip sign-in
  document.body.append(dlg);
  dlg.showModal();
}

async function refresh() {
  const wasOffline = ui.online === false;
  try { ui.data = await api("/api/state"); ui.online = true; if (wasOffline) { ui.reconnectedAt = Date.now(); if (window.JarvisAvatar) JarvisAvatar.retry3d(); } }
  catch (e) {
    ui.online = false;
    if (/Touch ID sign-in required/.test(e.message)) { showSignIn(); return; }
    if (/not signed in/.test(e.message)) { location.reload(); return; }
  }
  if (ui.data) flashOnFinish(ui.data);
  render();
  maybeAutoBriefing(ui.data);
  maybeWelcome();
  renderVoice(ui.data);
}

document.addEventListener("DOMContentLoaded", () => {
  $("#tab-ask").addEventListener("click", () => setMode("ask"));
  $("#tab-do").addEventListener("click", () => setMode("do"));
  $("#tab-research").addEventListener("click", () => setMode("research"));
  $("#cmdform").addEventListener("submit", submitCommand);
  document.querySelectorAll("#intelmodes .imode").forEach((b) => b.addEventListener("click", () => setIntel(b.dataset.intel)));
  let intel = "balanced";
  try { intel = localStorage.getItem("jarvis-intel") || "balanced"; } catch (e) { /* default */ }
  setIntel(intel);
  $("#stopgen").addEventListener("click", stopReply);
  $("#intelcycle").addEventListener("click", () => setIntel(INTEL[(INTEL.indexOf(ui.intel) + 1) % INTEL.length]));
  // The holographic core loads after the page is usable, so it never delays the first paint or the chat.
  (window.requestIdleCallback || ((f) => setTimeout(f, 200)))(() => {
    if (!window.JarvisAvatar) return;
    JarvisAvatar.onFocus = openProjection;
    JarvisAvatar.onSystem = (id) => { closeProjection(); ui.ccOpen = new Set([id]); ui.ccKey = ""; location.hash = "#/command"; };
    JarvisAvatar.onRebuilt = (modules) => { for (const m of modules) openProjectionModule(m, { quiet: true }); };   // after a 3D rebuild
    JarvisAvatar.mount($(".core-wrap"));
    watchBattery();
    document.addEventListener("pointerdown", () => window.JarvisSound && JarvisSound.resume());   // browsers start sound only after a tap
    document.addEventListener("visibilitychange", () => window.JarvisSound && JarvisSound.visibility());
    ui.sysbarKey = ""; render();
  });
  $("#projexit").addEventListener("click", closeProjection);
  document.querySelectorAll("#projpanel .pp-tabs [role=tab]").forEach((b) => b.addEventListener("click", () => setPanelTab(b.dataset.tab)));
  $("#projback").addEventListener("click", closeProjection);
  $("#projevo").addEventListener("click", () => showEvolution());
  $("#cmd").addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submitCommand(e); });
  // One tap, no questions: stopping is always safe (releasing it is what asks for confirmation).
  $("#estop").addEventListener("click", () => act("/api/stop", { reason: "stopped from the dashboard" }));
  $("#briefbtn").addEventListener("click", showBriefing);
  $("#helpbtn").addEventListener("click", showHelp);
  $("#mic").addEventListener("click", toggleMic);
  $("#speak").addEventListener("click", toggleSpeak);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") { $("#routeconfirm").hidden = true; stopSpeaking(); stopReply(); cancelEdit(); if (!stopInspect()) closeProjection(); } });
  window.addEventListener("hashchange", () => maybeAutoBriefing(ui.data));
  $("#release").addEventListener("click", () => {
    ask("Release the emergency stop? Paused tasks stay paused until you resume them.", { ok: "Release" })
      .then((yes) => yes && act("/api/release", { confirm: true }));
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
  $("#recentlog").addEventListener("click", () => $("#logdlg").showModal());
  $("#logclose").addEventListener("click", () => $("#logdlg").close());
  const tick = () => { $("#clock").textContent = new Date().toLocaleTimeString([], { hour12: false }); };
  tick(); setInterval(tick, 1000);
  setMode("ask");
  applyDisplay(loadDisplay());
  initParallax();
  document.addEventListener("keydown", onShortcut);
  $("#displaybtn").addEventListener("click", showDisplaySettings);
  $("#keysbtn").addEventListener("click", showShortcuts);
  setView(viewFromHash() || "home");
  let cine = false;
  try { cine = localStorage.getItem("jarvis-cinematic") === "1"; } catch (e) { /* default off */ }
  setCinematic(cine);
  $("#cinebtn").addEventListener("click", () => setCinematic(!document.body.classList.contains("cinematic")));
  $("#cineexit").addEventListener("click", () => setCinematic(false));
  window.addEventListener("hashchange", () => { const v = viewFromHash(); if (v) setView(v); });
  // Below 1600px the sidebar starts as icons so Home keeps its three columns; your own choice always wins.
  let collapsed = window.innerWidth < 1600;
  try { const saved = localStorage.getItem("jarvis-nav-collapsed"); if (saved !== null) collapsed = saved === "1"; } catch (e) { /* default */ }
  setNavCollapsed(collapsed);
  $("#navcollapse").addEventListener("click", () => setNavCollapsed(!document.body.classList.contains("nav-collapsed")));
  restoreDraft();
  $("#cmd").addEventListener("input", saveDraft);
  $("#cmd").addEventListener("input", () => { ui.typingAt = Date.now(); renderHead(ui.data); });
  if ("serviceWorker" in navigator && location.protocol === "https:") navigator.serviceWorker.register("/sw.js").catch(() => {});
  refresh();
  setInterval(refresh, 1500);
});

// Pause every animation while the page is in the background (saves battery; CSS: .page-hidden).
(() => {
  const sync = () => document.documentElement.classList.toggle("page-hidden", document.hidden);
  document.addEventListener("visibilitychange", sync);
  sync();
})();

// Header "More" menu: close after choosing, or when tapping elsewhere.
(() => {
  const more = document.getElementById("moremenu");
  if (!more) return;
  more.querySelectorAll(".more-menu .btn").forEach((b) => b.addEventListener("click", () => { more.open = false; }));
  document.addEventListener("click", (e) => { if (more.open && !more.contains(e.target)) more.open = false; });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") more.open = false; });
})();

// ---------------------------------------------------------------- command center: eight systems from live state
// Every figure comes from /api/state (or, for this conversation, the page itself). A figure that can't be measured
// is shown as unavailable with the reason; nothing is estimated to fill a gap.
const GB = (b) => `${(b / 1e9).toFixed(b >= 1e11 ? 0 : 1)} GB`;
const MB = (b) => `${Math.round(b / 1e6)} MB`;
function since(ts) {
  const t = typeof ts === "number" ? ts * 1000 : Date.parse(ts);
  if (!t) return "";
  const s = Math.max(0, (Date.now() - t) / 1000);
  return s < 90 ? "just now" : s < 5400 ? `${Math.round(s / 60)} min ago` : s < 129600 ? `${Math.round(s / 3600)} h ago` : `${Math.round(s / 86400)} d ago`;
}

// a real ratio (0-1) as a slim meter; nothing when the value is unknown
function meter(ratio) {
  if (ratio === null || ratio === undefined || !Number.isFinite(ratio)) return null;
  return h("i", { class: "meter", "data-fill": String(Math.max(0, Math.min(10, Math.round(ratio * 10)))), "aria-hidden": "true" });
}
function systems(d) {
  const t = d.telemetry || {};
  const health = d.health || { ok: null, items: [] };
  const problems = health.items.filter((i) => !i.ok);
  const providers = d.models ? d.models.providers : [];
  const online = providers.reduce((n, p) => n + p.available.length, 0);
  const active = d.tasks.filter((x) => ACTIVE.includes(x.state));
  const blocked = d.tasks.filter((x) => x.state === "blocked");
  const failed = d.tasks.filter((x) => x.state === "failed");
  const research = ui.convo.filter((m) => m.sources);
  const mem = t.memory && t.memory.available ? `RAM ${Math.round(t.memory.used_pct)}%` : "RAM unavailable";
  const intel = d.intelligence || {};
  const last = intel.last;
  const errors = d.audit.filter((e) => /error|failed|denied|no_route/.test(e.event));
  const sensitive = d.audit.filter((e) => /^(approval\.(approved|rejected|requested)|egress\.send|permission\.denied|stop\.|killswitch|device\.)/.test(e.event));
  const vs = d.voice || {};
  const row = (k, v, cls, fill) => ({ k, v, cls, fill });
  return [
    { id: "health", short: "Health", icon: "◉", label: "System health",
      status: health.ok === false ? "bad" : "ok", value: health.ok === false ? `${plural(problems.length, "problem")}` : mem,
      rows: [
        t.cpu && t.cpu.available ? row("CPU load", `${t.cpu.load_per_core} per core · ${t.cpu.cores} cores`, t.cpu.load_per_core > 1.5 ? "bad" : "", Math.min(1, t.cpu.load_per_core / 1.5)) : row("CPU load", `unavailable — ${(t.cpu || {}).reason || "no data"}`, "muted"),
        t.memory && t.memory.available ? row("Memory", `${GB(t.memory.used_bytes)} of ${GB(t.memory.total_bytes)} (${Math.round(t.memory.used_pct)}%)`, t.memory.used_pct > 90 ? "bad" : "", t.memory.used_pct / 100) : row("Memory", `unavailable — ${(t.memory || {}).reason || "no data"}`, "muted"),
        t.storage && t.storage.available ? row("Storage", `${GB(t.storage.free_bytes)} free of ${GB(t.storage.total_bytes)}`, t.storage.free_bytes < 2e9 ? "bad" : "", 1 - t.storage.free_bytes / t.storage.total_bytes) : row("Storage", "unavailable", "muted"),
        t.network ? row("Network", t.network.route ? "route available" : "no network route", t.network.route ? "" : "bad") : row("Network", "unavailable", "muted"),
        t.process && t.process.available ? row("JARVIS process", `peak ${MB(t.process.peak_bytes)}`) : row("JARVIS process", "unavailable", "muted"),
        ...health.items.map((i) => row(i.name, i.detail, i.ok ? "ok" : "bad")),
      ],
      note: t.cpu ? "CPU is the load average (work waiting per core), not a percentage. Memory is like Activity Monitor's “Memory Used”." : null },
    { id: "intelligence", short: "Intel", icon: "◈", label: "Intelligence",
      status: online ? "ok" : "bad", value: `${plural(online, "model")} · ${INTEL_LABEL[ui.intel]}`,
      rows: [
        row("Routing", d.models ? d.models.routing_mode.replace("_", "-") : "unknown"),
        row("Chat mode", `${INTEL_LABEL[ui.intel]} (change it under the message box)`),
        last ? row("Last model call", `${last.model} · ${last.location === "local" ? "on this Mac" : "cloud"} · ${last.latency_s}s · ${last.output_tokens ?? "?"} tokens · ${since(last.ts)}`) : row("Last model call", "none yet", "muted"),
        ...(intel.models || []).map((m) => row(m.model, `${m.location} · avg ${m.avg_latency_s}s over ${plural(m.calls, "call")}${m.tokens_per_s ? ` · ${m.tokens_per_s} tokens/s` : ""}`)),
        ...providers.map((p) => row(`${p.name} (${p.location})`, p.available.length ? `online: ${p.available.join(", ")}` : (p.error || "unavailable"), p.available.length ? "ok" : "bad")),
        ...((d.models && d.models.cloud_usage) || []).map((u) => row(`${u.provider} usage`, u.limited_until ? `at its limit until ${clock(u.limited_until)}` : `${plural(u.calls, "call")} in 5 h`, u.limited_until ? "bad" : "")),
      ],
      note: intel.window ? `Timings from the last ${intel.window} model calls in the audit log (no content).` : null },
    { id: "missions", short: "Missions", icon: "▤", label: "Missions",
      status: blocked.length ? "warn" : failed.length ? "warn" : "ok",
      value: active.length ? `${active.length} active` : blocked.length ? `${blocked.length} blocked` : "none active",
      rows: [
        row("Active", String(active.length)), row("Needs your input", String(blocked.length), blocked.length ? "bad" : ""),
        row("Paused", String(d.tasks.filter((x) => x.state === "paused").length)),
        row("Failed (recent)", String(failed.length), failed.length ? "bad" : ""),
        row("Completed (recent)", String(d.tasks.filter((x) => x.state === "completed").length)),
        row("Planning now", String(d.jobs.filter((j) => j.state === "planning" || j.state === "waiting_approval").length)),
        ...active.slice(0, 4).map((x) => { const done = x.steps.filter((st) => st.state === "done").length; return row(x.goal, `${x.state.replace("_", " ")} · step ${Math.min(done + 1, x.steps.length)} of ${x.steps.length}`); }),
      ],
      link: ["#/missions", "Open Missions"] },
    { id: "security", short: "Security", icon: "⛨", label: "Security",
      status: d.emergency_stop ? "bad" : d.approvals.length ? "warn" : "ok",
      value: d.emergency_stop ? "STOPPED" : d.approvals.length ? `${d.approvals.length} waiting` : "guarded",
      rows: [
        row("Emergency stop", d.emergency_stop ? `ENGAGED — ${d.emergency_stop.reason}` : "off (ready)", d.emergency_stop ? "bad" : "ok"),
        row("Decisions waiting", String(d.approvals.length), d.approvals.length ? "bad" : ""),
        row("Mac sign-in", d.touch_id && d.touch_id.enabled ? "Touch ID" : "secret link (Touch ID not set up)"),
        row("Paired phones", String(d.remote ? d.remote.devices.filter((x) => !x.revoked_at).length : 0)),
        row("Budget", d.models ? `$${(d.models.budget.spent_this_month_usd || 0).toFixed(2)} of $${d.models.budget.monthly_limit_usd.toFixed(2)} this month` : "unknown"),
        row("Audit chain", d.audit_chain ? (d.audit_chain.ok ? `intact · ${d.audit_chain.checked} entries` : `BROKEN at #${d.audit_chain.first_bad_seq}`) : "not checked yet", d.audit_chain && !d.audit_chain.ok ? "bad" : "ok"),
        ...sensitive.slice(0, 5).map((e) => row(clockOf(e.ts), e.detail)),
      ],
      link: ["/trust", "What JARVIS may and may not do"] },
    { id: "communications", short: "Comms", icon: "◌", label: "Communications",
      status: vs.enabled && !vs.available ? "warn" : "ok",
      value: $("#core").dataset.listening ? "listening" : $("#core").dataset.speaking ? "speaking" : vs.enabled ? (vs.available ? "voice ready" : "voice not ready") : "chat",
      rows: [
        row("Chat (this page)", `${plural(ui.convo.filter((m) => m.role === "user").length, "message")} · streaming replies`),
        row("Voice recognition", vs.enabled ? (vs.available ? "ready (whisper.cpp on this Mac)" : (vs.problems || []).join("; ") || "not running") : "off — `jarvis voice setup`", vs.enabled && !vs.available ? "bad" : ""),
        row("Listening now", $("#core").dataset.listening ? "yes" : "no"),
        row("Speaking now", $("#core").dataset.speaking ? "yes" : "no"),
        row("Voice replies", voice.speak ? "on (this device's built-in voice)" : "off"),
        row("iPhone", d.remote && d.remote.enabled ? `over Tailscale · ${plural(d.remote.devices.filter((x) => !x.revoked_at).length, "paired phone")}` : "off — `jarvis remote enable`"),
      ] },
    { id: "research", short: "Research", icon: "⌕", label: "Research",
      status: d.research_available ? "ok" : "off", value: d.research_available ? (research.length ? `${research.length} this session` : "ready") : "needs Claude",
      rows: [
        row("Web research", d.research_available ? "available (Claude's read-only web tools; asks before sending)" : "unavailable — needs Claude (`jarvis use-claude on`)", d.research_available ? "ok" : "muted"),
        row("This session", plural(research.length, "research answer")),
        row("Sources verified", research.length ? `${research.reduce((n, m) => n + m.sources.filter((x) => x.verified).length, 0)} of ${research.reduce((n, m) => n + m.sources.length, 0)}` : "—"),
        ...research.slice(-3).map((m) => row("Answer", m.text.slice(0, 90) + (m.text.length > 90 ? "…" : ""))),
      ],
      note: "Research history beyond this page isn't kept: the audit log stores only fingerprints of what was asked." },
    { id: "personal", short: "Personal", icon: "◷", label: "Personal ops",
      status: d.capabilities && d.capabilities.mac_apps ? "ok" : "off",
      value: d.capabilities && d.capabilities.mac_apps ? "Mac apps ready" : "not set up",
      rows: [
        row("Calendar, Reminders, Notes", d.capabilities && d.capabilities.mac_apps ? "available (reads are free; changes ask first)" : "not available here (macOS only; `jarvis mac check`)", d.capabilities && d.capabilities.mac_apps ? "ok" : "muted"),
        row("Morning briefing", d.briefing && d.briefing.last_date ? `last announced ${d.briefing.last_date}` : "not announced yet"),
        row("Decisions waiting", String(d.approvals.length)),
        row("Queued or paused missions", String(d.tasks.filter((x) => x.state === "queued" || x.state === "paused").length)),
        row("Email and other accounts", "not connected (no integration exists)", "muted"),
      ],
      action: ["Open today's briefing", () => showBriefing()] },
    { id: "diagnostics", short: "Diagnose", icon: "⚙", label: "Diagnostics",
      status: problems.length || (d.audit_chain && !d.audit_chain.ok) ? "bad" : errors.length ? "warn" : "ok",
      value: problems.length ? plural(problems.length, "problem") : errors.length ? `${plural(errors.length, "recent error")}` : "all checks pass",
      rows: [
        row("Health checks", health.items.length ? `${health.items.length - problems.length} of ${health.items.length} pass` : "first check runs within a minute", problems.length ? "bad" : "ok"),
        ...problems.map((i) => row(i.name, i.detail, "bad")),
        row("Audit chain", d.audit_chain ? (d.audit_chain.ok ? "intact" : "BROKEN") : "not checked yet", d.audit_chain && !d.audit_chain.ok ? "bad" : "ok"),
        ...errors.slice(-5).map((e) => row(clockOf(e.ts), e.detail, "bad")),
        d.evolution ? row("Core evolution", `${d.evolution.name} (tier ${d.evolution.tier}) · ${d.evolution.verified} of ${d.evolution.total} milestones verified${d.evolution.next ? ` · ${d.evolution.next.name} needs ${d.evolution.next.needs} more` : ""}`) : row("Core evolution", "first check runs within a minute", "muted"),
        ...(d.evolution ? d.evolution.milestones.map((m) => row(`${m.verified ? "✓" : "·"} ${m.title}`, m.verified ? `${m.evidence} · first verified ${m.first_verified.slice(0, 10)}` : m.first_verified ? `not verified right now (first verified ${m.first_verified.slice(0, 10)})` : `not yet: ${m.evidence}`, m.verified ? "ok" : "muted")) : []),
        row("Self-tests", "run `jarvis doctor`, `jarvis gate` or `jarvis drill` in Terminal", "muted"),
      ],
      action: ["Evolution record", () => showEvolution()] },
  ];
}

function clockOf(ts) {
  const t = Date.parse(ts);
  return t ? new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false }) : "";
}

function renderSysbar(d) {
  const list = systems(d);
  const key = JSON.stringify(list.map((x) => [x.id, x.status, x.value]));
  if (key === ui.sysbarKey) return;
  ui.sysbarKey = key;
  if (window.JarvisAvatar) JarvisAvatar.setSystems(list.map((x) => ({ id: x.id, label: x.label, status: x.status, value: x.value })));
  $("#sysbar").replaceChildren(...list.map((x) => h("a", { class: `sys-chip ${x.status}`, href: `#/command`, title: `${x.label}: ${x.value}`,
    onclick: () => { ui.ccOpen = new Set([x.id]); ui.ccKey = ""; } },
    h("span", { class: "sc-dot", "aria-hidden": "true" }), h("span", { class: "sc-icon", "aria-hidden": "true" }, x.icon),
    h("span", { class: "sc-label" }, x.label), h("span", { class: "sc-short", "aria-hidden": "true" }, x.short),
    h("span", { class: "sc-value" }, x.value))));
}

function renderCommand(d) {
  const list = systems(d);
  if (!ui.ccOpen) ui.ccOpen = new Set(["health"]);
  const key = JSON.stringify([...ui.ccOpen, list]);
  if (key === ui.ccKey) return;
  ui.ccKey = key;
  const bad = list.filter((x) => x.status === "bad").length, warn = list.filter((x) => x.status === "warn").length;
  $("#ccsum").textContent = bad ? `${bad} need attention` : warn ? `${warn} to look at` : "all nominal";
  $("#command").replaceChildren(...list.map((x) => {
    const det = h("details", { class: `cc-sys ${x.status}`, id: `cc-${x.id}`, open: ui.ccOpen.has(x.id) },
      h("summary", {}, h("span", { class: "sc-dot", "aria-hidden": "true" }), h("span", { class: "sc-icon", "aria-hidden": "true" }, x.icon),
        h("span", { class: "cc-label" }, x.label), h("span", { class: "cc-value" }, x.value)),
      h("dl", { class: "cc-rows" }, x.rows.map((r) => h("div", { class: `cc-row ${r.cls || ""}` }, h("dt", {}, r.k), h("dd", {}, r.v), meter(r.fill)))),
      x.note ? h("p", { class: "cc-note" }, x.note) : null,
      x.link || x.action ? h("div", { class: "row mt" },
        x.link ? h("a", { class: "btn btn-sm", href: x.link[0] }, x.link[1]) : null,
        x.action ? h("button", { class: "btn btn-sm", type: "button", onclick: x.action[1] }, x.action[0]) : null) : null);
    det.addEventListener("toggle", () => { if (det.open) ui.ccOpen.add(x.id); else ui.ccOpen.delete(x.id); });
    return det;
  }));
}

// ---------------------------------------------------------------- projection focus, task hologram, evolution
// Everything shown here is read from the same live snapshot as the rest of the page.
const AVATAR_WORDS = { unknown: "Connecting", idle: "Aware", listening: "Listening", understanding: "Understanding",
  reasoning: "Reasoning", planning: "Planning", researching: "Researching", writing: "Responding", speaking: "Speaking",
  coding: "Writing code", verifying: "Verifying", executing: "Executing", approval: "Waiting for you", warning: "Diagnostic warning",
  completed: "Completed", error: "Error", recovery: "Recovering", halted: "Halted (emergency stop)", learning: "Learning",
  experimenting: "Experimenting", analyzing: "Analyzing", disagreeing: "Refused by your rules" };

function liveWork(d) {
  if (!d) return null;
  const run = d.tasks.find((t) => ACTIVE.includes(t.state) && t.state !== "queued");
  if (run) {
    const i = run.steps.findIndex((st) => st.state === "started" || st.state === "pending");
    return { kind: "Mission", text: run.goal, sub: i >= 0 ? `Step ${i + 1} of ${run.steps.length} · ${run.steps[i].description}` : "Checking the result" };
  }
  if (ui.chatBusy && ui.chatEndpoint === "/api/research") return { kind: "Research", text: "Searching the web and reading pages", sub: "Sources are checked before they're cited" };
  if (ui.chatBusy && ui.stage && ui.stage.stage === "generating") return { kind: "Reply", text: `${ui.stage.model.split("/").pop()} ${ui.stage.location === "local" ? "on this Mac" : "in the cloud"}`, sub: stageLabel(ui.stage) };
  const job = d.jobs.find((j) => j.state === "planning");
  if (job) return { kind: "Planning", text: job.request, sub: `${job.elapsed}s` };
  const queued = d.tasks.find((t) => t.state === "queued");
  if (queued) return { kind: "Queued", text: queued.goal, sub: "Waiting for the runner — nothing is running yet" };
  return null;
}

// The data aura shows real values only; anything unavailable is left out (its band disappears).
function auraValues(d) {
  const t = d.telemetry || {};
  return {
    cpu: t.cpu && t.cpu.available ? Math.min(1, t.cpu.load_per_core / 1.5) : null,
    memory: t.memory && t.memory.available ? t.memory.used_pct / 100 : null,
    missions: Math.min(1, d.tasks.filter((x) => ACTIVE.includes(x.state)).length / 5),
    decisions: Math.min(1, d.approvals.length / 5),
  };
}

// The background data wall shows real signals only: the orange stream is CPU load, the teal stream memory use, the
// faint upper stream lights while a model is actually answering, and the left network brightens with active missions.
// Levels are coarse (0–4) data attributes, styled in app.css; "na" (unavailable) leaves that stream at its resting glow.
// The floating panels in the focus view: the same real status lines as the systems bar (counts and states only;
// never message text, memories or anything private).
function panelItems(d) {
  const by = Object.fromEntries(systems(d).map((x) => [x.id, x]));
  return ["intelligence", "missions", "health"].filter((id) => by[id]).map((id) => ({ title: by[id].label, value: by[id].value, status: by[id].status }));
}

// Projection controls (focus view): every control changes the projection on this device and nothing else.
const MODULE_LABEL = { figure: "Light body", hands: "Articulated hands", armour: "Alloy armour", joints: "Joint hubs", inner: "Inner skeleton",
  neural: "Neural backbone", neural3: "Neural branches", wire: "Wireframe (High quality)", reactor: "Reactor rings", reactorcore: "Reactor cage",
  reactorcore2: "Plasma core", reactorgyro: "Gyroscope rings", reactorpaths: "Energy pathways", reactorsupports: "Reactor supports",
  reactorswirl: "Reactor particles", reactor2: "Outer reactor ring", platform2: "Platform markers", orbit_low: "Lower orbital",
  orbit_diag: "Diagonal orbital", orbit_upper: "Upper orbital", orbit_sig: "Signature orbitals", chamber: "Chamber grid and boundary",
  ground: "Ground light and shadow", panels: "Floating panels", halo: "Halo", crown: "Crown", meridians: "Energy meridians", shield: "Alert shield" };
const PREVIEW_STATES = ["idle", "listening", "reasoning", "researching", "planning", "executing", "speaking", "completed", "disagreeing", "warning", "error", "recovery"];
function renderProjControls() {
  const el = $("#projctlbody");
  if (!el || !window.JarvisAvatar) return;
  const cur = loadDisplay();
  const choose = (key, label) => [h("h3", { class: "sys-part" }, label), h("div", { class: "row", role: "group", "aria-label": label },
    DISPLAY[key].map(([value, text]) => h("button", { class: `chip${cur[key] === value ? " on" : ""}`, type: "button", "aria-pressed": String(cur[key] === value),
      onclick: () => { cur[key] = value; saveDisplay(cur); applyDisplay(cur); renderProjControls(); } }, text)))];
  const mods = JarvisAvatar.modules || [];
  const three = JarvisAvatar.renderer === "3d";
  el.replaceChildren(
    ...presetSection(),
    h("h3", { class: "sys-part" }, "Camera"),
    h("div", { class: "row" }, h("button", { class: "btn btn-sm", type: "button", disabled: three ? null : true, onclick: startInspect,
      title: three ? "Orbit, zoom and pan around the projection" : "Needs the 3D view" }, "Inspect in 360°")),
    ...choose("view", "Resting view"), ...choose("camspeed", "Inspection speed"), ...choose("diag", "Diagnostics"),
    ...choose("sound", "Sound"),
    h("p", { class: "hl-sub" }, "A very quiet hum and short tones for real events (a completed task, a decision, a refusal, an error). Made in the browser; it steps aside while JARVIS speaks or you record."),
    h("h3", { class: "sys-part" }, "3D view"),
    h("p", { class: "hl-sub" }, RENDER_STATUS[JarvisAvatar.status] || "3D view running."),
    h("div", { class: "row" }, h("button", { class: "btn btn-ghost btn-sm", type: "button", title: "Dispose the 3D view and build it again (open projections reopen)",
      onclick: () => { JarvisAvatar.rebuild(); note("Rebuilding the 3D view…"); setTimeout(renderProjControls, 1500); } }, "Rebuild 3D view")),
    ...choose("projection", "Intensity"), ...choose("quality", `Quality${JarvisAvatar.quality ? ` (now ${QUALITY_WORD[JarvisAvatar.quality] || JarvisAvatar.quality})` : ""}`),
    ...choose("particles", "Particles"), ...choose("animation", "Animation"), ...choose("reactor", "Reactor"),
    ...choose("orbit", "Orbit speed"), ...choose("orbitals", "Orbitals"), ...choose("env", "Environment holograms"),
    ...choose("fx", "Motion"),
    h("h3", { class: "sys-part" }, "Preview a state"),
    h("p", { class: "hl-sub" }, "Shows a look for up to 10 seconds, marked PREVIEW. It is not real activity, and a real alert ends it at once."),
    h("div", { class: "row", role: "group", "aria-label": "Preview a state" }, PREVIEW_STATES.map((st) =>
      h("button", { class: "chip", type: "button", onclick: () => JarvisAvatar.previewState(st) }, st))),
    h("h3", { class: "sys-part" }, "Visual modules"),
    h("ul", { class: "pp-mods" }, mods.filter((m) => MODULE_LABEL[m.name]).map((m) =>
      h("li", { class: m.on ? "ok" : "no" }, `${m.on ? "✓" : "·"} ${MODULE_LABEL[m.name]}${m.on ? "" : ` (stage ${m.tier})`}`))),
    h("p", { class: "hl-sub" }, "Modules follow the displayed evolution stage. Settings here change only the look on this device; they never change what JARVIS can do."));
}

// 3D depth: the side columns lean toward the projection; the mouse adds a slight parallax (Normal effects only)
function initParallax() {
  const hud = document.querySelector(".hud");
  if (!hud || !window.matchMedia) return;
  let raf = 0, px = 0, py = 0;
  window.addEventListener("pointermove", (e) => {
    if (document.documentElement.dataset.fx !== "full" || matchMedia("(prefers-reduced-motion: reduce)").matches || innerWidth < 1200) return;
    px = (e.clientX / innerWidth - 0.5) * 2; py = (e.clientY / innerHeight - 0.5) * 2;
    if (!raf) raf = requestAnimationFrame(() => { raf = 0; hud.style.setProperty("--px", px.toFixed(3)); hud.style.setProperty("--py", py.toFixed(3)); });
  }, { passive: true });
}

// ---- section pages: a HUD header (title, code, real stats). Gauges only where a real ratio exists. -------------
const PAGES = { evolution: ["Evolution center", "EVO"], command: ["Command center", "CMD"], missions: ["Missions", "MSN"], decisions: ["Decisions", "DCN"],
                memory: ["Memory", "MEM"], systems: ["Systems", "SYS"], workspace: ["Workspace", "WRK"] };
function statTile(label, value, sub, cls) {
  return h("div", { class: `ph-stat${cls ? ` ${cls}` : ""}` }, h("b", {}, value), h("span", {}, label), sub ? h("small", {}, sub) : null);
}
function renderPageHud(d) {
  const view = document.body.dataset.view, box = $("#pagehud");
  if (!box) return;
  if (!PAGES[view] || !d) { box.hidden = true; return; }
  box.hidden = false;
  if (box.dataset.view !== view || !box.hud) {
    const gauges = h("div", { class: "page-gauges" });
    box.replaceChildren(h("div", { class: "page-title" }, h("small", {}, `JARVIS · ${PAGES[view][1]}`), h("h1", {}, PAGES[view][0])),
      h("div", { class: "page-stats" }), gauges);
    box.dataset.view = view; box.hud = { gauges, g: null };
  }
  const stats = box.querySelector(".page-stats");
  const tasks = d.tasks || [];
  const n = (pred) => tasks.filter(pred).length;
  let tiles = [], wantGauges = false;
  if (view === "missions") {
    tiles = [statTile("Active", String(n((t) => ACTIVE.includes(t.state) && t.state !== "queued"))), statTile("Queued", String(n((t) => t.state === "queued"))),
             statTile("Need you", String(n((t) => NEEDS.includes(t.state))), null, n((t) => NEEDS.includes(t.state)) ? "warn" : ""),
             statTile("Completed", String(n((t) => t.state === "completed"))), statTile("Failed", String(n((t) => t.state === "failed")), null, n((t) => t.state === "failed") ? "bad" : "")];
  } else if (view === "decisions") {
    const high = d.approvals.filter((a) => riskOf(a).level === "high" || riskOf(a).level === "data").length;
    tiles = [statTile("Waiting", String(d.approvals.length), null, d.approvals.length ? "warn" : ""), statTile("High risk or data out", String(high), null, high ? "bad" : "")];
  } else if (view === "memory") {
    const m = d.memory || {};
    tiles = [statTile("Memories", String(m.memories ?? "—")), statTile("To confirm", String(m.unconfirmed ?? "—"), "noticed, not stated by you"),
             statTile("Records", String(m.records ?? "—")), statTile("Memory", m.enabled === false ? "Off" : "On", null, m.enabled === false ? "warn" : "")];
  } else if (view === "systems" || view === "command") {
    const list = systems(d), bad = list.filter((x) => x.status === "bad").length;
    tiles = [statTile("Systems OK", `${list.length - bad}/${list.length}`, null, bad ? "warn" : ""), statTile("Need attention", String(bad), null, bad ? "bad" : "")];
    wantGauges = true;
  } else if (view === "evolution" && d.learn && d.learn.summary) {
    const ls = d.learn.summary;
    tiles = [statTile("Lessons", String(ls.lessons)), statTile("Missions verified", `${ls.missions.verified}/${ls.missions.total}`),
             statTile("Answers passing", `${ls.replies.verified}/${ls.replies.total}`), statTile("Experiments running", String(ls.experiments_running))];
  } else if (view === "workspace") {
    tiles = [statTile("Projects", String((d.projects || []).length))];
  }
  stats.replaceChildren(...tiles);
  const { gauges } = box.hud;
  gauges.hidden = !wantGauges;
  if (wantGauges) {
    if (!box.hud.g) { box.hud.g = { cpu: hudGauge("CPU"), mem: hudGauge("Memory"), checks: hudGauge("Checks") }; gauges.replaceChildren(box.hud.g.cpu, box.hud.g.mem, box.hud.g.checks); }
    const g = box.hud.g, t = d.telemetry || {}, items = (d.health && d.health.items) || [];
    if (t.cpu && t.cpu.available) g.cpu.set(Math.min(1, t.cpu.load_per_core / 1.5), String(t.cpu.load_per_core), "per core", t.cpu.load_per_core > 1.5 ? "bad" : ""); else g.cpu.set(null, "—", "no data");
    if (t.memory && t.memory.available) g.mem.set(t.memory.used_pct / 100, `${Math.round(t.memory.used_pct)}%`, "used", t.memory.used_pct > 90 ? "bad" : ""); else g.mem.set(null, "—", "no data");
    const ok = items.filter((i) => i.ok).length;
    g.checks.set(items.length ? ok / items.length : null, items.length ? `${ok}/${items.length}` : "—", "passing", items.length && ok < items.length ? "bad" : "");
  }
}

// ---- projections ------------------------------------------------------------------------------------------------
const PROJ_TITLE = Object.fromEntries(PROJ_MODULES);
async function openProjectionModule(m, { quiet = false } = {}) {
  if (!window.JarvisAvatar || !PROJ_TITLE[m]) return null;
  ui.analyzingUntil = Date.now() + 1500; renderHead(ui.data);
  let data;
  if (m === "research") data = researchProjection();   // built here from this conversation's last research answer
  else try { data = await api(`/api/projection/${m}`); } catch (e) { if (!quiet) note(`Couldn't open ${PROJ_TITLE[m]}: ${e.message}`); return null; }
  ui.analyzingUntil = 0;
  if (!JarvisAvatar.showProjection(m, data)) { if (!quiet) note("Projections need the 3D view (this device is showing the 2D core)."); return null; }
  ui.projData = { ...(ui.projData || {}), [m]: data };
  renderProjBar();
  return data;
}
// The last research answer in this conversation, as projection data: the question, each source's site and whether the
// research tools really saw it. Nothing is fetched; with no research yet the projection says so.
function researchProjection() {
  const last = [...ui.convo].reverse().find((m) => m.role === "assistant" && m.sources && m.question);
  if (!last) return { question: null, sources: [], searches: 0, pages: 0, basis: "No research in this conversation yet." };
  const host = (u) => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch (e) { return null; } };
  const sources = last.sources.map((x) => ({ host: host(x.url), verified: !!x.verified })).filter((x) => x.host);
  return { question: String(last.question).slice(0, 80), sources, searches: (last.rstats || {}).searches || 0, pages: (last.rstats || {}).pages || 0,
           basis: "Your last research answer in this conversation (sites only; green = the research tools saw the page)." };
}
// Open projections, each with its panel controls. Every control changes the look only: none of them approves, runs or
// changes anything (pending actions still need the approval card).
// iPhone: one tab of the focus panel at a time (CSS shows every part on a computer)
function setPanelTab(name) {
  const panel = $("#projpanel");
  if (!panel) return;
  ui.panelTab = name;
  panel.dataset.tab = name;
  panel.querySelectorAll(".pp-tabs [role=tab]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === name)));
  if (name === "controls") $("#projctl").open = true;
  panel.scrollTop = 0;
}
function renderProjBar() {
  const bar = $("#projbar");
  if (!bar || !window.JarvisAvatar) return;
  const list = JarvisAvatar.projections, focus = document.body.classList.contains("projection");
  const tab = $("#pptab-proj");
  if (tab) tab.textContent = list.length ? `Projections (${list.length})` : "Projections";
  bar.hidden = !list.length;
  document.body.classList.toggle("proj-area", focus && list.some((p) => !p.minimized));   // the wider projection area
  const ctl = (op, m, arg) => (e) => { e.stopPropagation(); JarvisAvatar.projectionControl(op, m, arg); if (op === "inspect") { document.body.classList.add("inspecting"); renderInspectBar(); } renderProjBar(); };
  const b = (text, label, fn, on, extra = "") => h("button", { class: `btn btn-ghost btn-xs${on ? " on" : ""}${extra}`, type: "button", "aria-label": label, title: label,
    "aria-pressed": on === undefined ? null : String(!!on), onclick: fn }, text);
  bar.replaceChildren(...list.map((p, i) => {
    const d = ui.projData && ui.projData[p.module];
    const open = ui.projDetail === p.module;
    return h("div", { class: `pj${p.minimized ? " min" : ""}${p.expanded ? " exp" : ""}` },
      h("b", {}, p.title), h("small", {}, p.minimized ? "Minimised" : (d && d.basis) || ""),
      h("div", { class: "pj-ctl", role: "group", "aria-label": `${p.title} controls` },
        p.minimized ? b("Restore", `Restore ${p.title}`, ctl("minimize", p.module, false))
          : [p.expanded ? b("Collapse", `Collapse ${p.title}`, ctl("collapse")) : b("Expand", `Expand ${p.title} into the projection area`, ctl("expand", p.module)),
             b("–", `Minimise ${p.title}`, ctl("minimize", p.module, true)),
             !p.expanded ? b(p.side === "left" ? "▶" : "◀", `Move ${p.title} to the ${p.side === "left" ? "right" : "left"} side`, ctl("side", p.module, p.side === "left" ? "right" : "left"), undefined, " pj-arrange") : null,
             i > 0 ? b("↑", `Move ${p.title} up`, ctl("move", p.module, -1), undefined, " pj-arrange") : null,
             focus ? b("Inspect", `Inspect ${p.title} up close`, ctl("inspect", p.module)) : null],
        b("Details", `Details of ${p.title}`, (e) => { e.stopPropagation(); ui.projDetail = open ? null : p.module; renderProjBar(); }, open),
        b(p.pinned ? "Pinned" : "Pin", "Keep this projection open", (e) => { e.stopPropagation(); JarvisAvatar.pinProjection(p.module, !p.pinned); renderProjBar(); }, p.pinned),
        b("✕", `Close ${p.title}`, (e) => { e.stopPropagation(); JarvisAvatar.closeProjection(p.module); if (ui.projDetail === p.module) ui.projDetail = null; renderProjBar(); })),
      open && d ? h("div", { class: "pj-detail" }, h("p", {}, describeProjection(p.module, d)), h("p", { class: "hl-sub" }, d.basis || "")) : null);
  }));
}
// what an opened projection shows, in one sentence from its own data (no model)
function describeProjection(m, d) {
  if (m === "workflow") { const ms = d.nodes.filter((n) => n.kind === "mission"); return ms.length ? `${ms.length} mission(s): ${ms.filter((x) => ["running", "verifying"].includes(x.state)).length} running, ${ms.filter((x) => x.state === "queued").length} queued, ${d.nodes.filter((n) => n.kind === "approval" && n.state === "pending").length} approval(s) waiting for you.` : "No missions yet."; }
  if (m === "architecture") return `${d.nodes.filter((n) => n.kind === "python").length} Python modules, ${d.nodes.filter((n) => n.kind === "frontend").length} dashboard scripts, ${d.routes} API routes and ${d.tables} database tables. Largest: ${d.largest.slice(0, 2).map((x) => `${x.id} (${x.lines} lines)`).join(", ")}.`;
  if (m === "neural") { const ls = d.nodes.filter((n) => n.kind === "lesson"); return `${d.nodes.length} pieces of knowledge, ${ls.length} lesson(s) (${ls.filter((x) => x.status === "hypothesis").length} contested), ${d.edges.filter((e) => e.rel === "contradicts").length} contradiction(s).`; }
  if (m === "globe") return d.points.length ? `${d.points.length} place(s) from your conversations; most mentioned: ${d.points[0].name}.` : "No places in your conversations yet.";
  if (m === "data") return d.models.length ? `Answer checks per model: ${d.models.map((x) => `${x.label} ${Math.round((x.check_rate || 0) * 100)}% of ${x.n}`).join(", ")}.` : "No measured answers yet.";
  if (m === "timeline") return `${d.events.length} dated event(s) and ${d.upcoming.length} open item(s) (no invented dates).`;
  if (m === "security") return `${d.stop ? "The emergency stop is ON. " : ""}${d.pending.length} action(s) waiting for your approval (not authorized), ${d.denied_7d} blocked in 7 days.`;
  if (m === "research") return d.question ? `“${d.question}”: ${d.sources.length} source(s), ${d.sources.filter((x) => x.verified).length} seen by the research tools; ${d.searches} searches, ${d.pages} pages read.` : "No research in this conversation yet.";
  if (m === "simulation") return d.experiments.length ? `${d.experiments.length} experiment(s); latest: ${d.experiments[0].state} — ${d.experiments[0].recommendation || d.experiments[0].objective}` : "No experiments yet.";
  return "";
}
// automatic selection in the focus view: what JARVIS is really doing picks the projection (avatar-events.js)
function autoProjection(state) {
  if (!document.body.classList.contains("projection") || !window.JarvisAvatar || !window.JarvisEvents) return;
  if (JarvisAvatar.preview) return;   // a preview is not real activity: it never opens projections or changes the mode
  if (JarvisEvents.MODES) { workModeTick(state); return; }   // the working modes decide (below)
  const m = JarvisEvents.projectionFor(state);
  if (!m || ui.autoProj === `${state}:${m}`) return;
  ui.autoProj = `${state}:${m}`;
  if (!JarvisAvatar.projections.some((p) => p.module === m)) openProjectionModule(m, { quiet: true });
}

// ---- working modes (Evolution 3.0, phase 4): contextual workspaces in the focus view ---------------------------
// A mode is a set of projections, a camera view and a few look settings (avatar-events.js MODES). On Auto the real
// activity picks it: System at once (errors, the emergency stop, a refusal, a decision), others after the current mode
// has had 8 s, and back to Command 20 s after the activity ends. Choosing a mode yourself turns Auto off. Projections
// a mode opened close when it changes; ones you opened or pinned stay. Your saved display settings never change.
const WMODE_KEY = "jarvis-workmode";
const MODE_HOLD_MS = 8000, MODE_RETURN_MS = 20000;
function loadWorkMode() {
  let v = {};
  try { v = JSON.parse(localStorage.getItem(WMODE_KEY) || "{}") || {}; } catch (e) { v = {}; }
  const modes = (window.JarvisEvents && JarvisEvents.MODES) || {};
  return { auto: v.auto !== false, mode: modes[v.mode] ? v.mode : "command" };
}
function saveWorkMode(w) { try { localStorage.setItem(WMODE_KEY, JSON.stringify(w)); } catch (e) { /* this visit only */ } }
function setWorkMode(name, by) {
  const M = window.JarvisEvents && JarvisEvents.MODES[name];
  if (!M || !window.JarvisAvatar || ui.settingMode) return;
  ui.settingMode = true;   // opening a projection re-renders the page, which runs the Auto check: never re-enter
  ui.wmode = name; ui.wmodeAt = Date.now(); ui.wmodeWhy = by;   // recorded first, so that check sees the new mode
  try {
    switchProjections(M);
  } finally { ui.settingMode = false; }
  ui.wlook = { ...M.look, ...(M.view ? { view: M.view } : {}) };
  applyDisplay(loadDisplay());
  renderProjBar(); renderModeBar();
}
function switchProjections(M) {
  const keep = new Set(M.projections);
  for (const p of JarvisAvatar.projections) {
    if ((ui.modeProj || new Set()).has(p.module) && !p.pinned && !keep.has(p.module)) JarvisAvatar.closeProjection(p.module);
  }
  const mine = new Set([...(ui.modeProj || [])].filter((m) => keep.has(m)));
  for (const m of M.projections) {
    if (!JarvisAvatar.projections.some((p) => p.module === m)) { mine.add(m); openProjectionModule(m, { quiet: true }); }
  }
  ui.modeProj = mine;
}
function workModeTick(state) {
  const w = loadWorkMode();
  if (!w.auto) return;
  const want = JarvisEvents.modeFor(state), now = Date.now();
  if (want) ui.wmodeSignalAt = now;
  const held = now - (ui.wmodeAt || 0) > MODE_HOLD_MS;
  if (want && want !== ui.wmode && (held || want === "system")) setWorkMode(want, state);
  else if (!want && ui.wmode && ui.wmode !== "command" && held && now - (ui.wmodeSignalAt || 0) > MODE_RETURN_MS) setWorkMode("command", "activity ended");
}
function enterWorkMode() {
  const w = loadWorkMode();
  ui.wmodeAt = 0;
  if (!w.auto) setWorkMode(w.mode, "you");
  else setWorkMode((window.JarvisAvatar && JarvisEvents.modeFor(JarvisAvatar.state)) || "command", window.JarvisAvatar ? JarvisAvatar.state : "");
}
// ---- avatar forms (Evolution 3.0, phase 5): chosen only by you, in the focus view -------------------------------
// A form is a transformation, a camera view, a look and (Intelligence) X-ray, from avatar-events.js FORMS. It never
// changes on its own: no JARVIS state picks a form. Leaving the focus view returns to Standard; your choice is kept.
const FORM_KEY = "jarvis-form";
function savedForm() {
  let v = null;
  try { v = localStorage.getItem(FORM_KEY); } catch (e) { v = null; }
  return window.JarvisEvents && JarvisEvents.FORMS && JarvisEvents.FORMS[v] ? v : "standard";
}
function setForm(name, { save = true } = {}) {
  const F = window.JarvisEvents && JarvisEvents.FORMS && JarvisEvents.FORMS[name];
  if (!F || !window.JarvisAvatar) return;
  if (save) { try { localStorage.setItem(FORM_KEY, name); } catch (e) { /* this visit only */ } }
  ui.form = name;
  ui.flook = { ...F.look, ...(F.view ? { view: F.view } : {}), xray: F.xray ? "on" : "off" };
  JarvisAvatar.transform(F.transform || null);
  applyDisplay(loadDisplay());
  renderFormBar();
}
function reapplyForm() {
  const F = ui.form && window.JarvisEvents && JarvisEvents.FORMS[ui.form];
  if (F && window.JarvisAvatar) JarvisAvatar.transform(F.transform || null);
}
function leaveForm() {
  ui.form = null; ui.flook = null;
  if (window.JarvisAvatar) JarvisAvatar.transform(null);
}
function renderFormBar() {
  const el = $("#projforms");
  if (!el || !window.JarvisEvents || !JarvisEvents.FORMS) return;
  const F = JarvisEvents.FORMS[ui.form || "standard"];
  el.replaceChildren(
    h("div", { class: "row", role: "group", "aria-label": "Avatar form" }, Object.entries(JarvisEvents.FORMS).map(([k, f]) =>
      h("button", { class: `chip${(ui.form || "standard") === k ? " on" : ""}`, type: "button", "aria-pressed": String((ui.form || "standard") === k),
        title: f.means, onclick: () => setForm(k) }, f.label))),
    h("div", { class: "pp-mode-now" }, h("b", {}, `Form: ${F.label}`), ` — ${F.means} · only you change it`));
}

// ---- operational readiness: a real event, from the health checks the dashboard already runs ---------------------
// "Operational" means every check passes. The avatar pulses once when that first becomes true, and again only after a
// problem clears. While a check fails it says how many, and never pulses.
function readiness(d) {
  const items = (d && d.health && d.health.items) || [];
  if (!items.length) return null;
  const bad = items.filter((i) => !i.ok);
  const ok = !bad.length;
  if (ok && ui.wasReady !== true && window.JarvisAvatar) JarvisAvatar.ready();
  ui.wasReady = ok;
  return ok ? `Operational: all ${items.length} checks pass` : `Not fully operational: ${bad.length} of ${items.length} checks failing (${bad.map((i) => i.name).join(", ")})`;
}

function leaveWorkMode() {
  if (window.JarvisAvatar) for (const p of JarvisAvatar.projections) if ((ui.modeProj || new Set()).has(p.module) && !p.pinned) JarvisAvatar.closeProjection(p.module);
  ui.modeProj = new Set(); ui.wlook = null; ui.wmode = null;
  applyDisplay(loadDisplay());
}
function renderModeBar() {
  const el = $("#projmodes");
  if (!el || !window.JarvisEvents || !JarvisEvents.MODES) return;
  const w = loadWorkMode(), M = JarvisEvents.MODES[ui.wmode] || JarvisEvents.MODES.command;
  const chip = (label, on, fn, title) => h("button", { class: `chip${on ? " on" : ""}`, type: "button", "aria-pressed": String(on), title, onclick: fn }, label);
  const why = !w.auto ? "you chose it" : ui.wmodeWhy === "activity ended" ? "Auto: the activity ended"
    : `Auto: ${(AVATAR_WORDS[ui.wmodeWhy] || ui.wmodeWhy || "at rest").toLowerCase()}`;
  el.replaceChildren(
    h("div", { class: "row", role: "group", "aria-label": "Working mode" },
      chip("Auto", w.auto, () => { saveWorkMode({ auto: true, mode: ui.wmode || "command" }); enterWorkMode(); }, "Follow what JARVIS is really doing"),
      ...Object.entries(JarvisEvents.MODES).map(([k, m]) => chip(m.label, !w.auto && ui.wmode === k,
        () => { saveWorkMode({ auto: false, mode: k }); setWorkMode(k, "you"); }, m.means))),
    h("div", { class: "pp-mode-now" }, h("b", {}, M.label), ` — ${M.means} · ${why}`,
      Object.keys(ui.wlook || {}).length ? h("small", {}, " (its look lasts while the mode does; your saved settings are unchanged)") : null));
}
function refreshProjections() {   // open projections follow the live data (every ~10 s)
  if (!window.JarvisAvatar || Date.now() - (ui.projRefreshed || 0) < 10000) return;
  ui.projRefreshed = Date.now();
  for (const p of JarvisAvatar.projections) openProjectionModule(p.module, { quiet: true });
}

function renderWall(d) {
  const w = $(".env-ribbons");
  if (!w) return;
  const a = d && d.telemetry ? auraValues(d) : { cpu: null, memory: null, missions: null };
  const lvl = (v) => (v === null || v === undefined ? "na" : String(Math.max(0, Math.min(4, Math.round(v * 4)))));
  w.dataset.cpu = lvl(a.cpu);
  w.dataset.mem = lvl(a.memory);
  w.dataset.work = lvl(a.missions);
  w.dataset.model = ui.chatBusy ? "on" : "off";
}

function renderAvTask(d) {
  const el = $("#avtask");
  if (!el) return;
  const w = liveWork(d);
  el.hidden = !w;
  if (w) el.replaceChildren(h("b", {}, w.kind), h("span", {}, w.text));
  if (document.body.classList.contains("projection")) renderProjection(d);
}

function openProjection() {
  if (document.body.dataset.view !== "home" && document.body.dataset.view !== "workspace") return;
  document.body.classList.add("projection");
  $("#projpanel").hidden = false; $("#projback").hidden = false;
  if (window.JarvisAvatar) JarvisAvatar.setOptions({ panels: true });   // the floating panels appear in the focus view only
  renderProjControls();
  renderProjection(ui.data);
  enterWorkMode();
  setForm(savedForm(), { save: false });
  if (isPhone()) $("#projpanel").insertBefore($("#projbar"), $("#projstate"));   // phone: the list scrolls inside the focus panel
  setPanelTab(ui.panelTab || "now");
  renderProjBar();
  renderDiag();
  $("#projexit").focus();
}
function closeProjection() {
  if (!document.body.classList.contains("projection")) return;
  stopInspect();
  leaveWorkMode();
  leaveForm();
  document.body.classList.remove("projection");
  $("#projpanel").hidden = true; $("#projback").hidden = true;
  if (window.JarvisAvatar) { JarvisAvatar.setOptions({ panels: false }); JarvisAvatar.endPreview(); }
  const bar = $("#projbar"), home = $("#projbar-home");
  if (bar && home && bar.parentElement !== home.parentElement) home.after(bar);   // back to its place on the page
  renderProjBar();   // leaves the wider projection area
}

// one real detail for the focus panel's motion line: never a percentage that doesn't exist
function hudDetail(st, d) {
  if (!d) return "";
  const core = $("#core");
  if (core.dataset.listening && voice.started) return `recording ${Math.floor((Date.now() - voice.started) / 1000)}s`;
  if (st === "executing" || st === "verifying") {
    const t = d.tasks.find((x) => ACTIVE.includes(x.state));
    if (t && t.steps.length) return `step ${Math.min(t.steps.length, t.steps.filter((x) => ["done", "skipped"].includes(x.state)).length + 1)} of ${t.steps.length}`;
  }
  if (st === "approval") return `${d.approvals.length} waiting for you`;
  if (st === "researching" && ui.stage && ui.stage.stage === "lookup") return "looking things up";
  if (st === "disagreeing") return "see the audit log in the Activity log";
  return "";
}
function renderProjection(d) {
  const st = window.JarvisAvatar ? JarvisAvatar.state : "unknown";
  const s = situation(d), w = liveWork(d), evo = d && d.evolution;
  const list = d ? systems(d) : [];
  $("#projstate").textContent = AVATAR_WORDS[st] || st;
  const rd = $("#projready");
  if (rd) { rd.textContent = ui.readyText || ""; rd.className = `pp-ready${ui.wasReady === false ? " warn" : ""}`; }
  // what the movement means right now (avatar-events.js), plus the one live detail that matters for it
  const pname = window.JarvisEvents ? JarvisEvents.personalityOf(st) : null;
  const pm = pname && JarvisEvents.PERSONALITY[pname];
  const detail = hudDetail(st, d);
  $("#projmotion").replaceChildren(...(pm && pname !== "idle" ? [h("b", {}, pname), ` — ${pm.means}${detail ? ` · ${detail}` : ""}`] : []));
  $("#projmain").textContent = s.main || "";
  $("#projsub").textContent = s.sub || "";
  $("#projwork").replaceChildren(...(w ? [h("div", { class: "kicker" }, w.kind), h("div", { class: "pw-text" }, w.text), h("div", { class: "pw-sub" }, w.sub)]
    : [h("div", { class: "pw-sub" }, "No task, research or reply in progress.")]));
  $("#projsystems").replaceChildren(...list.map((x) => h("button", { class: `ps-sys ${x.status}`, type: "button", title: `Open ${x.label} in the Command center`,
    onclick: () => { closeProjection(); ui.ccOpen = new Set([x.id]); ui.ccKey = ""; location.hash = "#/command"; } },
    h("span", { class: "sc-dot", "aria-hidden": "true" }), h("span", {}, x.label), h("small", {}, x.value))));
  const av = d ? auraValues(d) : {};
  const pct = (v) => (typeof v === "number" ? `${Math.round(v * 100)}%` : "unavailable");
  $("#projaura").textContent = d ? `Aura (inner to outer): CPU load ${pct(av.cpu)} · memory ${pct(av.memory)} · missions ${d.tasks.filter((x) => ACTIVE.includes(x.state)).length} · decisions ${d.approvals.length}` : "";
  $("#projevo").textContent = evo ? `Stage ${displayStage(evo)} · ${evo.stages ? evo.stages[displayStage(evo) - 1] : evo.name} — evolution record` : "Evolution record";
}

// Evolution 2.5 keeps four things apart: what JARVIS can verifiably do (the milestones above), how far the look has
// progressed (the displayed stage), which rendering modules that stage switches on, and what you customised here.
function evolutionLayers(evo) {
  const mods = window.JarvisAvatar ? JarvisAvatar.modules.filter((m) => MODULE_LABEL[m.name]) : [];
  const d = loadDisplay(), st = loadPresets(), now = st && window.JarvisPresets ? JarvisPresets.current(st, d) : null;
  return [
    h("h3", { class: "sys-part" }, "Visual progression"),
    h("p", { class: "hl-sub" }, `Showing stage ${displayStage(evo)} of 5${evoCap() ? " (capped on this device)" : ""}. It follows the verified record; it never runs ahead of it.`),
    h("h3", { class: "sys-part" }, "Rendering modules"),
    mods.length ? h("p", { class: "hl-sub" }, `${mods.filter((m) => m.on).length} of ${mods.length} on at this stage. Off: ${mods.filter((m) => !m.on).map((m) => `${MODULE_LABEL[m.name]} (stage ${m.tier})`).join(", ") || "none"}.`)
      : h("p", { class: "hl-sub" }, "The 2D core is showing on this device: no 3D modules."),
    h("h3", { class: "sys-part" }, "Your customisation (this device)"),
    h("p", { class: "hl-sub" }, `${now ? (now.modified ? `Custom (changed from ${now.label})` : `Preset: ${now.label}`) : "Default look"} · quality ${QUALITY_WORD[d.quality] || d.quality} · resting view ${d.view} · sound ${d.sound}. Looks only: none of this changes a capability or a milestone.`),
  ];
}

// Evolution: the stage comes from the server (verified milestones). This device may choose to show a lower stage.
const EVO_CAP_KEY = "jarvis-evo-cap";
function evoCap() { try { const v = Number(localStorage.getItem(EVO_CAP_KEY)); return v >= 1 && v <= 5 ? v : 0; } catch (e) { return 0; } }
function displayStage(evo) { const cap = evoCap(); return cap ? Math.min(cap, evo.tier) : evo.tier; }

function showEvolution() {
  const evo = ui.data && ui.data.evolution;
  const names = (evo && evo.stages) || ["Foundational Projection", "Advanced Projection", "Intelligence Projection", "Evolved Projection", "Signature Projection"];
  const body = !evo ? [h("p", { class: "hl-sub" }, "The first check runs within a minute of starting JARVIS.")] : [
    h("p", { class: "hl-sub" }, `Earned: stage ${evo.tier} — ${names[evo.tier - 1]} (${evo.verified} of ${evo.total} milestones count). `
      + (evo.next ? `${names[evo.next.tier - 1]} needs ${evo.next.needs} more.` : "Highest stage.")
      + ` Milestone definitions v${evo.version}. A milestone keeps counting for ${evo.grace_days} days after it stops verifying, then drops.`),
    h("ul", { class: "evo-list" }, evo.milestones.map((m) => h("li", { class: m.verified ? "ok" : m.held ? "held" : "no" },
      h("b", {}, `${m.verified ? "✓" : m.held ? "◐" : "·"} ${m.title}`),
      h("span", {}, m.verified ? `${m.evidence} · first verified ${m.first_verified.slice(0, 10)}`
        : m.held ? `not verifying now; still counts until ${m.held_until.slice(0, 10)}`
        : m.first_verified ? `lost (last verified ${(m.last_verified || m.first_verified).slice(0, 10)})` : `not yet: ${m.evidence}`)))),
    h("h3", { class: "sys-part" }, "Show on this device"),
    h("div", { class: "row", role: "group", "aria-label": "Displayed stage" },
      [[0, "Earned stage"], ...[1, 2, 3, 4, 5].filter((n) => n <= evo.tier).map((n) => [n, `Stage ${n}`])].map(([v, label]) =>
        h("button", { class: `chip${evoCap() === v || (!evoCap() && v === 0) ? " on" : ""}`, type: "button", "aria-pressed": String(evoCap() === v),
          onclick: () => { try { if (v) localStorage.setItem(EVO_CAP_KEY, String(v)); else localStorage.removeItem(EVO_CAP_KEY); } catch (e) { /* this visit only */ }
            dlg.close(); renderHead(ui.data); showEvolution(); } }, label))),
    h("p", { class: "hl-sub" }, "Showing a lower stage only changes the look on this device; it never changes what JARVIS can do or the record above."),
    ...evolutionLayers(evo),
  ];
  const dlg = h("dialog", { class: "pairdlg askdlg evodlg", "aria-labelledby": "evo-h" },
    h("h2", { id: "evo-h" }, "Projection evolution"), ...body,
    h("div", { class: "row mt" }, h("button", { class: "btn", type: "button", onclick: () => dlg.close() }, "Done")));
  dlg.addEventListener("close", () => dlg.remove());
  document.body.append(dlg);
  dlg.showModal();
}
