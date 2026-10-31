"use strict";
// JARVIS demo mode: the real dashboard (app.js, app.css, index.html, unchanged) driven by a simulated JARVIS
// that runs entirely in this browser. Every /api/* request the page makes is answered here, in the same
// shapes the real Python server returns. Nothing is sent anywhere: no AI, no Mac, no network.
//
// Simulated on purpose: AI replies and plans are canned; "files" are never touched; Face ID / Touch ID,
// voice, notifications and phone pairing need the real Mac and say so.
(() => {
  const KEY = "jarvis-demo-v1";
  const VERSION = "0.16.4 · simulation";
  const STOP_MSG = "Emergency stop is on: new actions are blocked until you release it.";
  const MAC_ONLY = "Not available in the simulation: this needs JARVIS running on your Mac.";
  const t = () => Date.now() / 1000;
  const iso = (s = t()) => new Date(s * 1000).toISOString();
  const rid = (p) => `${p}_${Math.random().toString(16).slice(2, 10)}${Math.random().toString(16).slice(2, 6)}`;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  // What each permission category means in the real permission engine (src/jarvis/core/permissions.py).
  const KINDS = {
    read: { tier: 0, label: "Read-only", call: "fs.read", verb: "Read", reason: null },
    reversible: { tier: 1, label: "Reversible", call: "fs.write", verb: "Save", reason: "no standing policy covers this action" },
    sensitive: { tier: 4, label: "Sensitive", call: "fs.delete", verb: "Delete", reason: "tier 4 always requires confirmation" },
  };

  // ---- state ----------------------------------------------------------------------------------
  function step(n, description, kind, resource, preview = null, call = null) {
    return { n, description, call: call || KINDS[kind].call, state: "pending", attempts: 0, error: null, kind, resource, preview };
  }

  function task(goal, steps, state = "queued") {
    const now = iso();
    return { id: rid("task"), goal, request: goal, state, created_at: now, updated_at: now, error: null, next_action: null,
             runner: "dashboard", evidence: null, steps, final_text: null };
  }

  function seed() {
    const s = { tasks: [], approvals: [], jobs: [], audit: [], memories: [], stop: null, seq: 0, created: t() };
    const done = task("Summarise this week's meeting notes", [
      step(0, "Read the notes folder", "read", "~/Documents/JARVIS/Notes"),
      step(1, "Write a one-page summary", "read", null, null, "llm.compose"),
      step(2, "Save the summary as weekly-brief.md", "reversible", "~/Documents/JARVIS/Notes/weekly-brief.md",
           "# Week 44\n- Budget approved\n- Launch moved to Friday"),
    ], "completed");
    done.steps.forEach((x) => { x.state = "done"; x.attempts = 1; });
    done.evidence = { files: [{ path: "~/Documents/JARVIS/Notes/weekly-brief.md", content_matches: true }] };
    done.final_text = "# Week 44\n- Budget approved\n- Launch moved to Friday";
    const waiting = task("Draft a reply to the landlord", [
      step(0, "Read the landlord's letter", "read", "~/Downloads/letter.pdf"),
      step(1, "Save the draft reply", "reversible", "~/Documents/JARVIS/Notes/reply-to-landlord.md",
           "Dear Ms Patel,\nThank you for your letter. I can confirm the inspection on Tuesday at 10am.\nKind regards"),
    ], "running");
    const blocked = task("Clean up old screenshots", [
      step(0, "List screenshots older than 90 days", "read", "~/Desktop"),
      step(1, "Move 42 screenshots to the Trash", "sensitive", "~/Desktop/Screenshot 2026-05-*.png"),
    ], "blocked");
    blocked.steps[0].state = "done"; blocked.steps[0].attempts = 1;
    blocked.next_action = "You rejected “Move 42 screenshots to the Trash”. Resume to be asked again, or cancel.";
    s.tasks = [waiting, blocked, done];
    s.memories = [
      mem("I prefer email over phone calls", "explicit"),
      mem("My weekly review is on Friday afternoons", "explicit", 1),
      mem("Seems to keep receipts in ~/Documents/Receipts", "observed"),
    ];
    log(s, "user:dashboard", "memory.added", null, "Remembered a fact (confirmed)");
    log(s, "system", "task.state", done.id, "Task verifying → completed");
    log(s, "user:dashboard", "approval.rejected", blocked.id, "You rejected a request");
    log(s, "system", "kernel.started", null, "Simulation started in this browser");
    return s;
  }

  function mem(text, origin, important = 0) {
    const now = iso();
    return { id: rid("mem"), text, kind: "fact", origin, confidence: origin === "explicit" ? 1 : 0.6, source_record: null,
             created_at: now, verified_at: origin === "explicit" ? now : null, important };
  }

  function load() {
    try {
      const raw = localStorage.getItem(KEY);
      const s = raw && JSON.parse(raw);
      return s && Array.isArray(s.tasks) ? s : null;
    } catch (e) { return null; }  // private window or blocked storage: start fresh each visit
  }

  let S = load() || seed();
  let persisted = true;
  function save() {
    try { localStorage.setItem(KEY, JSON.stringify(S)); persisted = true; }
    catch (e) { persisted = false; }  // still works, just forgets on reload
    renderLab();
  }

  function log(s, actor, event, taskId, detail) {
    s.seq += 1;
    s.audit.unshift({ seq: s.seq, ts: iso(), actor, event, task_id: taskId, detail });
    s.audit = s.audit.slice(0, 200);
  }
  const audit = (actor, event, taskId, detail) => log(S, actor, event, taskId, detail);

  const findTask = (id) => S.tasks.find((x) => x.id === id);
  const touch = (tk) => { tk.updated_at = iso(); };
  function setState(tk, to, reason) {
    const from = tk.state;
    if (from === to) return;
    tk.state = to;
    touch(tk);
    audit("system", "task.state", tk.id, `Task ${from.replace(/_/g, " ")} → ${to.replace(/_/g, " ")}${reason ? ` (${reason})` : ""}`);
  }

  // ---- the simulated engine: one small step every tick --------------------------------------------
  function requestApproval(tk, st) {
    const k = KINDS[st.kind];
    const a = { id: rid("appr"), task_id: tk.id, step_n: st.n, tool: st.call.split(".")[0], action: st.call.split(".")[1],
                resource: st.resource, tier: k.tier, reason: k.reason, summary: st.description, created_at: iso(),
                preview: st.preview };
    S.approvals.push(a);
    tk.next_action = `approve or reject: ${st.description}`;
    setState(tk, "awaiting_approval", k.reason);
    audit("system", "approval.requested", tk.id, `Asked you to approve ${st.call} ${st.resource ? st.resource.split("/").pop() : ""}`.trim());
  }

  function tick() {
    if (S.stop) return;
    let changed = false;
    for (const tk of S.tasks) {
      if (!["queued", "running"].includes(tk.state)) continue;
      if (tk.state === "queued") { setState(tk, "running"); changed = true; continue; }
      const st = tk.steps.find((x) => x.state !== "done" && x.state !== "skipped");
      if (!st) {
        tk.evidence = { files: tk.steps.filter((x) => x.call === "fs.write").map((x) => ({ path: x.resource, content_matches: true })) };
        tk.final_text = tk.steps.find((x) => x.preview)?.preview || null;
        tk.next_action = null;
        setState(tk, "completed");
        audit("system", "task.verified", tk.id, "Verification passed (simulated)");
        changed = true;
        continue;
      }
      if (st.state === "pending") {
        if (st.kind !== "read" && !st.approved) { requestApproval(tk, st); changed = true; continue; }
        st.state = "started"; st.attempts += 1; touch(tk);
        audit("system", "tool.start", tk.id, `Running ${st.call} (simulated)`);
      } else if (st.state === "started") {
        st.state = "done"; touch(tk);
        audit("system", "tool.result", tk.id, `Finished ${st.call} (simulated, nothing touched)`);
      }
      changed = true;
    }
    for (const j of S.jobs) {
      if (j.state === "planning" && t() - j.started > 1.6) { Object.assign(j, plan(j.request)); changed = true; }
    }
    if (changed) save();
  }

  // ---- canned "AI" (AI calls are off in the preview) --------------------------------------------------
  function plan(request) {
    const r = request.toLowerCase();
    const base = (desc, call, kind, resource) => ({ description: desc, call, args: resource || "", depends_on: [], kind, resource });
    let goal = request.trim().replace(/\.$/, ""), steps;
    if (/delete|clean|remove|tidy/.test(r)) {
      steps = [base("Find the files to remove", "fs.list", "read", "~/Downloads"),
               base("Move them to the Trash", "fs.delete", "sensitive", "~/Downloads/old-drafts")];
    } else if (/move|organi[sz]e|file|archive|sort/.test(r)) {
      steps = [base("List the files", "fs.list", "read", "~/Downloads"),
               base("Move them into Archive", "fs.move", "reversible", "~/Documents/Archive")];
    } else if (/summar|brief|report|notes|draft|write/.test(r)) {
      steps = [base("Read the source files", "fs.read", "read", "~/Documents/JARVIS/Notes"),
               base("Write the text", "llm.compose", "read", null),
               base("Save it as a note", "fs.write", "reversible", "~/Documents/JARVIS/Notes/summary.md")];
    } else {
      return { state: "ready", kind: "clarify", request, message: "Simulated planner: which folder or file should I work with?",
               seconds: 1.6 };
    }
    return { state: "ready", kind: "plan", goal, message: null, model: "demo/simulated-planner", steps, seconds: 1.6,
             note: "Simulated plan: in real JARVIS a local model on your Mac writes this." };
  }

  function chatReply(text) {
    const q = text.toLowerCase();
    if (/what can you do|help|abilities/.test(q)) {
      return "In real JARVIS (on your Mac) I can chat with local models or Claude, research the web with checked sources, read " +
        "PDFs and documents, plan and carry out file tasks with your approval, remember what you tell me, and brief you " +
        "each morning. Here everything is simulated: try the Do tab, the Simulation lab, or the emergency stop.";
    }
    if (/who are you|your name/.test(q)) return "I'm JARVIS. This is a simulation running in your browser, so my replies are canned.";
    return "Simulated reply: AI is turned off in this preview. In real JARVIS, this message would go to a local model on your " +
      "Mac, or to Claude only after you approve sending it.";
  }

  // ---- views in the real server's shapes ----------------------------------------------------------------
  function stateView() {
    const unconfirmed = S.memories.filter((m) => m.origin === "observed").length;
    return {
      version: VERSION, time: t(),
      emergency_stop: S.stop,
      tasks: S.tasks.slice(0, 25).map((tk) => ({ ...tk, steps: tk.steps.map(({ n, description, call, state, attempts, error }) =>
        ({ n, description, call, state, attempts, error })) })),
      approvals: S.approvals.map(({ step_n, ...a }) => a),
      jobs: S.jobs.slice(0, 5).map((j) => ({ ...j, elapsed: j.state === "planning" ? Math.round(t() - j.started) : undefined })),
      models: { budget: { monthly_limit_usd: 0, spent_this_month_usd: 0 }, local_only_categories: [], routing_mode: "local_first",
                providers: [{ name: "simulation", location: "local", configured: ["canned-replies"], available: ["canned-replies"],
                              error: null, data_use: "simulated in this browser: no AI is called" }],
                cloud_usage: [], disabled_providers: [] },
      audit: S.audit.slice(0, 40),  // newest first, like the real server
      audit_chain: { ok: true, checked: S.audit.length, first_bad_seq: null },
      roots: ["~/Documents/JARVIS", "~/Downloads"], policy_loaded: true,
      memory: { memories: S.memories.length, unconfirmed, records: 0, enabled: true },
      research_available: true,
      health: { ok: true, checked: t(), service: false, items: [
        { name: "Simulation", ok: true, detail: "running in this browser · not connected to your Mac" },
        { name: "Backups", ok: true, detail: "not part of the simulation" }] },
      remote: { enabled: false, hostname: null, this_device: null, devices: [] },
      touch_id: { enabled: false, keys: [] },
      briefing: { last_date: null },
      voice: { enabled: false, available: false, managed: false, problems: [] },
    };
  }

  function briefingView() {
    const needs = S.approvals.map((a) => `Approve: ${a.summary}`)
      .concat(S.tasks.filter((x) => x.state === "blocked").map((x) => `Blocked: ${x.goal}`));
    const sections = [];
    if (needs.length) sections.push({ title: "Needs you", items: needs, alert: true });
    const done = S.tasks.filter((x) => x.state === "completed").map((x) => x.goal);
    if (done.length) sections.push({ title: "Finished", items: done });
    const prog = S.tasks.filter((x) => ["queued", "running"].includes(x.state)).map((x) => x.goal);
    if (prog.length) sections.push({ title: "In progress", items: prog });
    if (S.stop) sections.push({ title: "Systems", items: ["The emergency stop is on: new actions are blocked until you release it."], alert: true });
    sections.push({ title: "Simulation", items: ["This briefing is built from the demo data in this browser."] });
    const n = needs.length;
    return { headline: n ? `${n} thing${n === 1 ? "" : "s"} need${n === 1 ? "s" : ""} you.` : "Nothing needs you.",
             since: iso(t() - 86400), generated_at: t(), sections };
  }

  // ---- the /api/* routes the real page calls -------------------------------------------------------------
  class Refused extends Error { constructor(status, msg) { super(msg); this.status = status; } }
  const refuseWhileStopped = () => { if (S.stop) throw new Refused(409, STOP_MSG); };

  function get(path, query) {
    if (path === "/api/state") return stateView();
    if (path === "/api/briefing") return briefingView();
    if (path === "/api/memory") {
      const q = (query.get("q") || "").trim().toLowerCase();
      const list = q ? S.memories.filter((m) => m.text.toLowerCase().includes(q)) : S.memories;
      return { memories: list, counts: stateView().memory, records: [] };
    }
    let m;
    if ((m = path.match(/^\/api\/tasks\/([\w-]+)\/audit$/))) return S.audit.filter((e) => e.task_id === m[1]).reverse();
    if (path === "/api/push/key") throw new Refused(409, MAC_ONLY);
    throw new Refused(404, "not found");
  }

  function post(path, body) {
    let m;
    if (path === "/api/chat") {
      refuseWhileStopped();
      if (!String(body.message || "").trim()) throw new Refused(400, "'message' must be non-empty text");
      return { text: chatReply(body.message), model: "demo/canned-replies", seconds: 0.4, memories_used: 0,
               note: "simulated reply" };
    }
    if (path === "/api/research") {
      refuseWhileStopped();
      return { answer: "Simulated research: web research is off in this preview. In real JARVIS, Claude searches the web " +
                       "after you approve it, and every source it cites is checked against the pages it actually read.",
               sources: [], model: "demo/canned-replies", seconds: 0.6, searches: [], pages_read: [], verified_sources: 0 };
    }
    if (path === "/api/plan") {
      refuseWhileStopped();
      const request = String(body.request || "").trim();
      if (!request) throw new Refused(400, "'request' must be non-empty text");
      const j = { id: rid("job").replace(/-/g, ""), request, state: "planning", started: t() };
      S.jobs.unshift(j);
      return { job_id: j.id };
    }
    if ((m = path.match(/^\/api\/plan\/(\w+)\/(run|discard)$/))) {
      const j = S.jobs.find((x) => x.id === m[1]);
      if (m[2] === "discard") { S.jobs = S.jobs.filter((x) => x !== j); return { ok: true }; }
      refuseWhileStopped();
      if (!j || j.kind !== "plan" || j.task_id) throw new Refused(409, "this plan can't be run (already run or not ready)");
      const tk = task(j.goal, j.steps.map((s, n) => step(n, s.description, s.kind, s.resource,
        s.call === "fs.write" ? `Summary of ${j.goal.toLowerCase()} (simulated content)` : null, s.call)));
      S.tasks.unshift(tk);
      j.task_id = tk.id;
      S.jobs = S.jobs.filter((x) => x !== j);
      audit("user:dashboard", "task.created", tk.id, `New task: ${tk.goal}`);
      return { task_id: tk.id };
    }
    if ((m = path.match(/^\/api\/approvals\/([\w-]+)$/))) {
      if (typeof body.approve !== "boolean") throw new Refused(400, "'approve' must be true or false");
      const a = S.approvals.find((x) => x.id === m[1]);
      if (!a) throw new Refused(409, "this decision was already made");
      S.approvals = S.approvals.filter((x) => x !== a);
      const tk = findTask(a.task_id);
      if (body.approve) {
        audit("user:dashboard", "approval.approved", a.task_id, "You approved a request");
        if (tk) {
          tk.steps[a.step_n].approved = true;
          tk.next_action = null;
          setState(tk, S.stop ? "paused" : "running", S.stop ? "emergency stop" : null);
        }
      } else {
        audit("user:dashboard", "approval.rejected", a.task_id, "You rejected a request");
        if (tk) {
          tk.next_action = `You rejected “${a.summary}”. Resume to be asked again, or cancel.`;
          setState(tk, "blocked", "you rejected a step");
        }
      }
      return { ok: true };
    }
    if ((m = path.match(/^\/api\/tasks\/([\w-]+)\/(pause|resume|cancel)$/))) {
      const tk = findTask(m[1]);
      if (!tk) throw new Refused(409, "unknown task");
      if (m[2] === "pause") setState(tk, "paused", "paused by you");
      else if (m[2] === "resume") { refuseWhileStopped(); setState(tk, "running", "resumed by you"); }
      else {
        S.approvals = S.approvals.filter((a) => a.task_id !== tk.id);
        setState(tk, "cancelled", "cancelled by you");
      }
      return { ok: true, state: tk.state };
    }
    if (path === "/api/stop") { emergencyStop(String(body.reason || "stopped from the dashboard")); return { ok: true }; }
    if (path === "/api/release") {
      if (body.confirm !== true) throw new Refused(409, "releasing the emergency stop needs explicit confirmation");
      S.stop = null;
      audit("user:dashboard", "emergency_stop.released", null, "Emergency stop released");
      return { ok: true };
    }
    if (path === "/api/memory/remember") {
      const text = String(body.text || "").trim();
      if (!text) throw new Refused(400, "'text' must be non-empty text");
      const mm = mem(text.slice(0, 500), "explicit");
      S.memories.unshift(mm);
      audit("user:dashboard", "memory.added", null, "Remembered a fact (confirmed)");
      return { id: mm.id, stored: true };
    }
    if ((m = path.match(/^\/api\/memory\/([\w-]+)\/(confirm|delete|important|edit)$/))) {
      const mm = S.memories.find((x) => x.id === m[1]);
      if (!mm) throw new Refused(409, "unknown memory");
      if (m[2] === "delete") { S.memories = S.memories.filter((x) => x !== mm); audit("user:dashboard", "memory.deleted", null, "Deleted a memory"); }
      if (m[2] === "confirm") { mm.origin = "explicit"; mm.confidence = 1; audit("user:dashboard", "memory.confirmed", null, "Confirmed a memory"); }
      if (m[2] === "important") mm.important = body.important ? 1 : 0;
      if (m[2] === "edit") { mm.text = String(body.text || mm.text).slice(0, 500); mm.origin = "explicit"; audit("user:dashboard", "memory.edited", null, "Corrected a memory"); }
      return { ok: true };
    }
    if (path === "/api/memory/forget") {
      const q = String(body.query || "").trim().toLowerCase();
      const hits = S.memories.filter((x) => q && x.text.toLowerCase().includes(q));
      if (body.confirm === true) {
        S.memories = S.memories.filter((x) => !hits.includes(x));
        audit("user:dashboard", "memory.forget", null, `Forgot ${hits.length} memories and 0 records`);
      }
      return { memories: hits, records: [], tasks: [] };
    }
    if (path.startsWith("/api/devices") || path.startsWith("/api/touchid") || path.startsWith("/api/push")
        || path === "/api/stepup/options" || path === "/api/voice/transcribe" || path === "/api/logout") {
      throw new Refused(409, MAC_ONLY);
    }
    throw new Refused(404, "not found");
  }

  function emergencyStop(reason) {
    if (S.stop) return;
    S.stop = { engaged: true, by: "user:dashboard", reason, ts: iso() };
    for (const tk of S.tasks) {
      if (["queued", "running", "awaiting_approval"].includes(tk.state)) setState(tk, "paused", "emergency stop");
    }
    audit("user:dashboard", "emergency_stop.engaged", null, `EMERGENCY STOP: ${reason}`);
  }

  // Answer the page's /api/* requests here. Anything else (there is nothing else) is refused, so the
  // simulation can never reach the network.
  const json = (status, obj) => new Response(JSON.stringify(obj), { status, headers: { "Content-Type": "application/json" } });
  window.fetch = async (input, init = {}) => {
    const url = new URL(typeof input === "string" ? input : input.url, location.href);
    if (!url.pathname.startsWith("/api/") && !url.pathname.endsWith("/sw.js")) {
      return json(404, { error: "the simulation makes no network requests" });
    }
    await sleep(120 + Math.random() * 200);  // so loading states are visible, as on the real thing
    try {
      let body = {};
      if ((init.method || "GET") === "POST") {
        try { body = JSON.parse(init.body || "{}"); } catch (e) { return json(400, { error: "invalid JSON" }); }
      }
      const out = (init.method || "GET") === "POST" ? post(url.pathname, body) : get(url.pathname, url.searchParams);
      save();
      return json(200, out);
    } catch (e) {
      if (e instanceof Refused) return json(e.status, { error: e.message });
      return json(500, { error: `simulation error: ${e.message}` });
    }
  };

  // ---- the Simulation lab: demo-only controls (task editor, permissions, examples) -----------------------------
  const el = (tag, props = {}, ...kids) => {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
      if (k === "class") n.className = v;
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else if (v !== null && v !== undefined && v !== false) n.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false) n.append(kid instanceof Node ? kid : String(kid));
    return n;
  };
  const say = (text) => (window.note ? window.note(text) : null);
  const refreshPage = () => (typeof window.refresh === "function" ? window.refresh() : null);
  const dialog = (msg, opts) => (typeof window.ask === "function" ? window.ask(msg, opts) : Promise.resolve(opts && opts.input !== undefined ? null : false));

  function createTask(title, kind) {
    if (S.stop) { say(STOP_MSG); return; }
    const k = KINDS[kind];
    const slug = title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 32) || "task";
    const steps = [step(0, `Check what's needed for “${title}”`, "read", "~/Documents/JARVIS")];
    steps.push(step(1, kind === "read" ? `Read ${slug}.md` : `${k.verb} ${slug}.md`, kind,
      `~/Documents/JARVIS/Notes/${slug}.md`, kind === "reversible" ? `Notes for: ${title}` : null));
    const tk = task(title, steps);
    tk.demo_kind = kind;
    S.tasks.unshift(tk);
    audit("user:dashboard", "task.created", tk.id, `New task: ${title} (simulated, ${k.label.toLowerCase()})`);
    save(); refreshPage();
  }

  async function renameTask(tk) {
    const name = await dialog("Rename this task:", { input: tk.goal, ok: "Save" });
    if (!name || !name.trim() || name.trim() === tk.goal) return;
    tk.goal = tk.request = name.trim().slice(0, 120); touch(tk);
    audit("user:dashboard", "task.edited", tk.id, `Renamed a task to “${tk.goal}”`);
    save(); refreshPage();
  }

  function completeTask(tk) {
    if (S.stop) { say(STOP_MSG); return; }
    tk.steps.forEach((x) => { if (x.state !== "done") { x.state = "done"; x.attempts = Math.max(1, x.attempts); } });
    S.approvals = S.approvals.filter((a) => a.task_id !== tk.id);
    tk.next_action = null; tk.error = null;
    setState(tk, "completed", "marked complete in the simulation");
    save(); refreshPage();
  }

  async function deleteTask(tk) {
    if (!await dialog(`Delete “${tk.goal}” from the simulation?`, { ok: "Delete", danger: true })) return;
    S.tasks = S.tasks.filter((x) => x !== tk);
    S.approvals = S.approvals.filter((a) => a.task_id !== tk.id);
    audit("user:dashboard", "task.deleted", null, "Deleted a task and its history");
    save(); refreshPage();
  }

  const EXAMPLES = [
    ["ask", "What can you do?"],
    ["do", "Summarise my meeting notes into a one-page brief"],
    ["do", "Move last month's PDFs from Downloads into Archive"],
    ["do", "Delete old drafts in Downloads"],
    ["research", "Which free note-taking apps work offline?"],
  ];

  const PERMS = [
    ["read", "Tier 0", "Runs straight away inside folders you approved, and is logged.", "Read a file, list a folder, search memory, fetch a public web page"],
    ["reversible", "Tiers 1–2", "Asks you first, showing exactly what will be written, unless you've given a standing permission (like your Notes folder). Previous versions are kept.", "Save a note, create a folder, move or rename a file"],
    ["sensitive", "Tiers 3–4", "Always asks, even with a standing permission. Deletes go to the Trash.", "Delete a file, act outside your Mac"],
  ];

  let labTab = "tasks";
  try { labTab = sessionStorage.getItem("jarvis-demo-tab") || "tasks"; } catch (e) { /* default */ }

  function renderLab() {
    const box = document.getElementById("demo-lab-body");
    if (!box) return;
    const tabBtn = (id, label) => el("button", { type: "button", role: "tab", class: "tab", id: `demo-tab-${id}`,
      "aria-selected": String(labTab === id), onclick: () => { labTab = id; try { sessionStorage.setItem("jarvis-demo-tab", id); } catch (e) { /* ok */ } renderLab(); } }, label);
    const tabs = el("div", { class: "tabs demo-tabs", role: "tablist", "aria-label": "Simulation lab" },
      tabBtn("tasks", "Tasks"), tabBtn("perms", "Permissions"), tabBtn("examples", "Try"));
    let body;
    if (labTab === "tasks") {
      const title = el("input", { id: "demo-new-title", class: "demo-input", placeholder: "New task, e.g. Plan Saturday's errands", maxlength: "120", autocomplete: "off", "aria-label": "New task title" });
      const kind = el("select", { id: "demo-new-kind", class: "demo-input", "aria-label": "What kind of action it needs" },
        Object.entries(KINDS).map(([k, v]) => el("option", { value: k }, `${v.label} (tier ${v.tier})`)));
      const form = el("form", { class: "demo-form", onsubmit: (e) => {
        e.preventDefault();
        const v = title.value.trim();
        if (!v) { title.focus(); return; }
        createTask(v, kind.value);
        title.value = "";
      } }, title, el("div", { class: "row" }, kind, el("button", { class: "btn btn-sm", type: "submit", id: "demo-add" }, "Add task")));
      const rows = S.tasks.length ? S.tasks.map((tk) => el("div", { class: "demo-task" },
        el("div", { class: "demo-task-title" }, tk.goal, el("small", {}, ` · ${tk.state.replace(/_/g, " ")}`)),
        el("div", { class: "row" },
          el("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: () => renameTask(tk) }, "Rename"),
          tk.state === "completed" ? null : el("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: () => completeTask(tk) }, "Complete"),
          el("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: () => deleteTask(tk) }, "Delete"))))
        : [el("div", { class: "empty" }, "No tasks. Add one above, or use the Do tab.")];
      body = [form, el("div", { class: "demo-tasks" }, rows)];
    } else if (labTab === "perms") {
      body = PERMS.map(([k, tiers, what, examples]) => el("div", { class: `demo-perm ${k}` },
        el("div", { class: "demo-perm-head" }, el("b", {}, KINDS[k].label), el("small", {}, tiers)),
        el("p", {}, what), el("p", { class: "demo-eg" }, `e.g. ${examples}`),
        el("button", { class: "btn btn-sm", type: "button", onclick: () => createTask(`Try a ${KINDS[k].label.toLowerCase()} action`, k) }, "Try it")))
        .concat(el("p", { class: "demo-note" }, "From your iPhone, every approval also needs Face ID. On the Mac it can need Touch ID. " +
          "The emergency stop pauses everything and blocks new actions."));
    } else {
      body = [el("div", { class: "demo-examples" }, EXAMPLES.map(([mode, text]) => el("button", { class: "chip", type: "button", onclick: () => {
        if (typeof window.setMode === "function") window.setMode(mode);
        const cmd = document.getElementById("cmd");
        cmd.value = text; cmd.focus();
        cmd.scrollIntoView({ block: "center", behavior: "smooth" });
      } }, el("small", {}, mode), text))),
      el("p", { class: "demo-note" }, "Tap an example to put it in the command box, then press Send.")];
    }
    const foot = el("div", { class: "demo-foot" },
      el("small", {}, persisted ? "Demo data is saved in this browser only." : "This browser isn't saving demo data: it resets on reload."),
      el("button", { class: "btn btn-ghost btn-sm", type: "button", id: "demo-reset", onclick: async () => {
        if (!await dialog("Reset the simulation to its starting data?", { ok: "Reset", danger: true })) return;
        S = seed(); save(); refreshPage();
      } }, "Reset demo"));
    box.replaceChildren(tabs, el("div", { class: "demo-body", role: "tabpanel", "aria-labelledby": `demo-tab-${labTab}` }, body), foot);
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.body.prepend(el("div", { class: "demo-banner", role: "note" },
      el("b", {}, "Simulation"), " Nothing here is connected to your Mac or to any AI. Replies and plans are canned."));
    const rail = document.querySelector(".rail-left");
    rail.prepend(el("section", { class: "panel demo-lab", "aria-labelledby": "demo-lab-h" },
      el("header", { class: "ph" }, el("h2", { id: "demo-lab-h" }, "Simulation lab"), el("span", { class: "ph-count" }, "demo only")),
      el("div", { id: "demo-lab-body" })));
    renderLab();
    setInterval(tick, 1200);
  });

  window.JARVIS_DEMO = { reset: () => { S = seed(); save(); }, state: () => S, tick };
})();
