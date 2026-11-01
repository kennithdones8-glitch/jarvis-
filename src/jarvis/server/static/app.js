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
// Must match the server's STEP_UP list; the server enforces it regardless of what this page does.
const FACE_ID = [/^\/api\/approvals\/[\w-]+$/, /^\/api\/release$/, /^\/api\/plan\/\w+\/run$/,
                 /^\/api\/memory\/[\w-]+\/(delete|edit)$/, /^\/api\/devices\/[\w-]+\/revoke$/];
const TOUCH_ID = [...FACE_ID, /^\/api\/devices\/pair$/, /^\/api\/touchid\/enroll\/options$/, /^\/api\/touchid\/[\w-]+\/remove$/];
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
  const needs = list.some((r) => r.test(path)) || ((onPhone() || touchIdOn()) && path === "/api/memory/forget" && body.confirm === true);
  if (!needs) return api(path, body);
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
  if (ui.chatBusy) return { core: "thinking", cls: "", kicker: "Thinking", main: "Composing a reply", sub: "" };
  const online = d.models ? d.models.providers.reduce((n, p) => n + p.available.length, 0) : 0;
  if (d.models && !online) return { core: "degraded", cls: "attention", kicker: "Systems", main: "No model available", sub: "Is Ollama running? Open the Ollama app, then wait a few seconds." };
  return { core: "online", cls: "", kicker: "All systems nominal", main: `${greeting()}.`, sub: `${plural(online, "model")} online · nothing needs you right now.` };
}

function renderHead(d) {
  const s = situation(d);
  $("#core").dataset.state = s.core;
  $(".headline").className = `headline ${s.cls}`;
  $("#hl-kicker").textContent = s.kicker;
  $("#hl-main").textContent = s.main;
  $("#hl-sub").textContent = s.sub;
  const pill = $("#statuspill");
  pill.dataset.state = s.core;
  $("#statustext").textContent = s.main && s.kicker !== "All systems nominal" ? `${s.kicker} · ${s.main}` : s.kicker;
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
    try { await api("/api/plan", { request: text }); $("#cmd").value = ""; clearDraft(); await refresh(); }
    catch (e) { note(`Could not start planning: ${e.message}`); }
    finally { $("#send").disabled = false; }
    return;
  }
  if (ui.chatBusy) return;
  ui.convo.push({ role: "user", text });
  $("#cmd").value = "";
  clearDraft();
  if (ui.mode === "research") { await sendChat({ question: text, session: ui.session }, "/api/research"); return; }
  const history = ui.convo.slice(0, -1).filter((m) => !m.error && !m.consent).map((m) => ({ role: m.role, content: m.text }));
  await sendChat({ message: text, history, session: ui.session });
}

// Sends a chat turn. If the best model is in the cloud and your rule is "ask every time", the server
// returns needs_approval instead of sending; we show a consent card and resend the identical request.
// Chat with a local model's reply appearing as it's written. Same answer as /api/chat; falls back to it when
// streaming isn't available (an older JARVIS, the phone preview).
async function streamChat(payload) {
  let r;
  try {
    r = await fetch("/api/chat/stream", { method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-Requested-By": "jarvis" }, body: JSON.stringify(payload) });
  } catch (e) { return api("/api/chat", payload); }
  if (!r.ok || !r.body || !(r.headers.get("Content-Type") || "").includes("ndjson")) return api("/api/chat", payload);
  const live = { role: "assistant", text: "", live: true };
  const reader = r.body.getReader(), dec = new TextDecoder();
  let buf = "", done = null, painting = false;
  const paint = () => { painting = false; ui.liveLen = live.text.length; render(); };
  for (;;) {
    const { value, done: end } = await reader.read();
    if (end) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n")) >= 0) {
      const text = buf.slice(0, i); buf = buf.slice(i + 1);
      if (!text.trim()) continue;
      const msg = JSON.parse(text);
      if (typeof msg.t === "string") {
        if (!ui.convo.includes(live)) ui.convo.push(live);
        live.text += msg.t;
        if (!painting) { painting = true; requestAnimationFrame(paint); }
      } else if (msg.done) done = msg.done;
    }
  }
  ui.convo = ui.convo.filter((m) => m !== live);
  if (!done) throw new Error(live.text ? "the reply was interrupted" : "no reply");
  if (done.error && live.text) done.partial = live.text;
  return done;
}

async function sendChat(payload, endpoint = "/api/chat") {
  ui.chatBusy = true;
  ui.chatEndpoint = endpoint;
  render();
  try {
    const r = endpoint === "/api/chat" ? await streamChat(payload) : await api(endpoint, payload);
    if (r.needs_approval) ui.convo.push({ role: "assistant", consent: true, payload, endpoint, approval_id: r.approval_id, text: r.summary });
    else if (r.answer !== undefined) ui.convo.push({ role: "assistant", text: r.answer, sources: r.sources,
      meta: [r.model.split("/").pop(), `${r.seconds}s`, `${r.searches.length} searches`, `${r.pages_read.length} pages read`,
             `${r.verified_sources}/${r.sources.length} sources verified`].join(" · ") });
    else if (r.error) ui.convo.push({ role: "assistant", text: r.partial ? `${r.partial}\n\n— ${r.error}` : r.error, error: true });
    else ui.convo.push({ role: "assistant", text: r.text, checked: r.checked || [], plan: r.offer_plan ? payload.message : null,
      meta: [r.model.split("/").pop(), `${r.seconds}s`,
      r.memories_used ? `used ${plural(r.memories_used, "memory").replace("memorys", "memories")}` : null, r.note].filter(Boolean).join(" · ") });
  } catch (e) {
    ui.convo.push({ role: "assistant", text: `Request failed: ${e.message}`, error: true });
  } finally {
    ui.chatBusy = false;
    render();
  }
  const last = ui.convo[ui.convo.length - 1];
  if (last && last.role === "assistant" && !last.error && !last.consent) say(last.text);
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
        m.meta ? h("span", { class: "meta" }, m.meta) : null));
  if (ui.chatBusy && !ui.convo.some((m) => m.live)) items.push(h("div", { class: "msg jarvis" }, h("span", { class: "who typing" }, "JARVIS")));
  if (d) items.push(...d.jobs.filter((j) => j.state !== "submitted").reverse().map(jobCard));
  const feed = $("#feed");
  const key = JSON.stringify([ui.convo.length, ui.convo.map((m) => (m.help ? "h" : m.welcome ? "w" : "")).join(""), ui.liveLen || 0, ui.convo.map((m) => m.approval_id || ""), ui.chatBusy, d && d.jobs.map((j) => [j.id, j.state, j.elapsed, j.kind])]);
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

function stopSpeaking() { if ("speechSynthesis" in window) speechSynthesis.cancel(); delete $("#core").dataset.speaking; }

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
  u.onstart = () => { core.dataset.speaking = "1"; };
  u.onend = u.onerror = () => { delete core.dataset.speaking; };
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
  $("#core").dataset.listening = "1";
  voice.started = Date.now();
  rec.start();
  micLabel("Stop · 0s", true);
  voice.timer = setInterval(() => {
    const s = (Date.now() - voice.started) / 1000;
    micLabel(`Stop · ${Math.floor(s)}s`, true);
    if (s >= 58 && voice.rec) voice.rec.stop();
  }, 250);
}

async function finishRecording(type) {
  clearInterval(voice.timer);
  voice.stream.getTracks().forEach((t) => t.stop());
  voice.rec = null;
  delete $("#core").dataset.listening;
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
      h("li", {}, h("b", {}, "Command box"), " (bottom): Ask a question, Do a task, or Research the web."),
      h("li", {}, h("b", {}, "Missions"), ": tasks JARVIS is working on, step by step."),
      h("li", {}, h("b", {}, "Decisions"), ": anything JARVIS wants to change waits here for your Approve or Reject."),
      h("li", {}, h("b", {}, "Emergency stop"), " (top): pauses everything at once.")),
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

function missionRow(t) {
  // Home: one line per mission; Open shows its full card in Missions.
  return h("li", { class: `mrow ${NEEDS.includes(t.state) ? "needs" : t.state === "failed" ? "bad" : ""}` },
    h("div", { class: "mrow-text" }, h("small", {}, STATE_WORDS[t.state] || t.state), h("b", {}, t.goal), h("span", {}, stepText(t))),
    h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: () => openMission(t.id) }, "Open"));
}

function openMission(id) {
  ui.open.add(id);
  location.hash = "#/missions";
  setTimeout(() => { const el = document.getElementById(`m-${id}`); if (el) el.scrollIntoView({ block: "start" }); }, 60);
}

function missionCard(t) {
  const done = t.steps.filter((s) => s.state === "done" || s.state === "skipped").length;
  const cls = NEEDS.includes(t.state) ? "needs" : ACTIVE.includes(t.state) ? "active"
    : t.state === "completed" ? "done" : ["failed", "cancelled"].includes(t.state) ? "bad" : "";
  const cur = t.steps.find((s) => s.state === "started") || t.steps.find((s) => s.state === "pending");
  const files = (t.evidence && t.evidence.files) || [];
  const controls = [];
  if (["queued", "running", "awaiting_approval"].includes(t.state)) controls.push(h("button", { class: "btn btn-ghost btn-sm", type: "button",
    title: "Pause: stops after the current step. Nothing is undone; resume any time.", onclick: () => act(`/api/tasks/${t.id}/pause`, {}) }, "Pause"));
  controls.push(h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: () => showTimeline(t.id) }, "Timeline"));
  const uncertain = t.steps.filter((s) => s.state === "uncertain");
  if (["paused", "blocked"].includes(t.state) && !uncertain.length) controls.push(h("button", { class: "btn btn-sm", type: "button", onclick: () => act(`/api/tasks/${t.id}/resume`, {}) }, "Resume"));
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
    h("div", { class: "m-state" }, STATE_WORDS[t.state] || t.state),
    h("div", { class: "m-title" }, t.goal),
    h("div", { class: "segs", role: "progressbar", "aria-label": "Progress", "aria-valuemin": 0, "aria-valuemax": t.steps.length, "aria-valuenow": done,
               "aria-valuetext": stepText(t) },
      t.steps.map((s) => h("i", { class: s.state, title: `${s.description} — ${s.state}` }))),
    h("div", { class: "m-steps" }, stepText(t)),
    cur && !["completed", "failed", "cancelled"].includes(t.state) ? h("div", { class: "m-now" }, "Now: ", h("b", {}, cur.description)) : null,
    t.state === "failed" && t.error ? h("div", { class: "m-err" }, t.error) : null,
    t.state === "blocked" && t.next_action ? h("div", { class: "m-err" }, t.next_action) : null,
    uncertain.length ? h("div", { class: "m-err" }, `${plural(uncertain.length, "step")} with an unknown outcome. Check whether it happened; `
      + "this mission can't be resumed until that's settled, and the dashboard has no control for it yet, so cancel it if needed.") : null,
    files.map((f) => h("div", { class: `m-ok${f.content_matches ? "" : " bad"}`, title: f.path },
      f.content_matches ? `✓ Saved & verified · ${base(f.path)}` : `✗ Verification failed · ${base(f.path)}`)),
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
      h("div", { class: "d-kind" }, decisionKind(a), h("span", { class: "d-risk" }, `${risk.icon} ${risk.label}`)),
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
    // ask first, straight from the tap: iPhone Safari only shows the permission prompt in response to one
    if (await Notification.requestPermission() !== "granted") { note("Notifications are off for JARVIS in iPhone Settings."); return; }
    const reg = await navigator.serviceWorker.ready;
    const { key } = await api("/api/push/key");
    const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64u.toBuf(key) });
    await api("/api/push/subscribe", { subscription: sub.toJSON() });
    note("Notifications on. They only ever say things like “JARVIS needs a decision” — never your content.");
  } catch (e) { note(`Couldn't turn on notifications: ${e.message}. On iPhone, add JARVIS to your Home Screen first.`); }
}

function renderActivity(entries) {
  $("#ticker").replaceChildren(...entries.slice(0, 6).map((e) => h("li", {}, h("time", {}, clock(e.ts)), e.detail)));
  $("#recent").replaceChildren(...(entries.length ? entries.slice(0, 6).map((e) => h("li", {}, h("time", {}, clock(e.ts)), h("span", {}, e.detail)))
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

function renderSummary(d) {
  // The numbers that used to be the stats row, plus health, in one place on Home; full detail is in Systems.
  const m = d.models || { providers: [], budget: {} };
  const online = m.providers.reduce((n, p) => n + p.available.length, 0);
  const total = m.providers.reduce((n, p) => n + p.configured.length, 0);
  const active = d.tasks.filter((t) => ACTIVE.includes(t.state)).length;
  const claude = (m.cloud_usage || []).find((u) => u.provider === "claude");
  const ro = (label, value, cls) => h("div", { class: "ro" }, h("span", {}, label), h("b", { class: cls || null }, value));
  fill($("#summary"),
    ro("Health", !d.health ? "Checking…" : d.health.ok ? "✓ Healthy" : `⚠ ${plural(d.health.items.filter((i) => !i.ok).length, "problem")}`,
       d.health && !d.health.ok ? "bad" : d.health ? "ok" : null),
    ro("Models online", `${online} of ${total}`, total && !online ? "bad" : null),
    ro("Missions active", String(active)),
    claude ? ro("Claude", claude.limited_until ? `resets ${clock(claude.limited_until)}` : `${claude.calls} calls · 5h`) : null,
    ro("Spent this month", `$${(m.budget.spent_this_month_usd || 0).toFixed(2)} of $${(m.budget.monthly_limit_usd || 0).toFixed(2)}`));
}

function render() {
  const d = ui.data;
  renderHead(d);
  renderFeed(d);
  if (!d) return;
  renderMatters(d);
  renderSuggestions(d);
  renderSummary(d);
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

// ---------------------------------------------------------------- shell: sections, badges, sidebar, drafts
// Sections are views of the same live page: switching never pauses, resumes or changes anything.
const VIEWS = ["home", "missions", "decisions", "memory", "systems"];
function viewFromHash() {
  const m = location.hash.match(/^#\/(\w+)/);
  return m && VIEWS.includes(m[1]) ? m[1] : null;
}
function setView(view) {
  if (!VIEWS.includes(view)) view = "home";
  const changed = document.body.dataset.view !== view;
  document.body.dataset.view = view;
  document.querySelectorAll("#sidenav a[data-view]").forEach((a) => {
    if (a.dataset.view === view) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
  if (changed) { window.scrollTo(0, 0); if (ui.data) renderMissions(ui.data.tasks); }
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

async function refresh() {
  try { ui.data = await api("/api/state"); ui.online = true; }
  catch (e) { ui.online = false; if (/not signed in/.test(e.message)) { location.reload(); return; } }
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
  $("#cmd").addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submitCommand(e); });
  // One tap, no questions: stopping is always safe (releasing it is what asks for confirmation).
  $("#estop").addEventListener("click", () => act("/api/stop", { reason: "stopped from the dashboard" }));
  $("#briefbtn").addEventListener("click", showBriefing);
  $("#helpbtn").addEventListener("click", showHelp);
  $("#mic").addEventListener("click", toggleMic);
  $("#speak").addEventListener("click", toggleSpeak);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") stopSpeaking(); });
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
  setView(viewFromHash() || "home");
  window.addEventListener("hashchange", () => { const v = viewFromHash(); if (v) setView(v); });
  // Below 1600px the sidebar starts as icons so Home keeps its three columns; your own choice always wins.
  let collapsed = window.innerWidth < 1600;
  try { const saved = localStorage.getItem("jarvis-nav-collapsed"); if (saved !== null) collapsed = saved === "1"; } catch (e) { /* default */ }
  setNavCollapsed(collapsed);
  $("#navcollapse").addEventListener("click", () => setNavCollapsed(!document.body.classList.contains("nav-collapsed")));
  restoreDraft();
  $("#cmd").addEventListener("input", saveDraft);
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
