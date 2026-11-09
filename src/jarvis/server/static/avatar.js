"use strict";
// JARVIS holographic core: a modular humanoid hologram drawn as layered SVG, with an optional canvas of energy motes.
// It is decoration that *shows* state it is given (setState / setTier). It never fetches, decides or acts, and
// the chat never waits for it. Every layer is a named part so the helmet, visor and face can be redesigned later
// with JarvisAvatar.registerPart(name, svgMarkup) without touching the rest.
//
// Performance: CSS animates only transform / opacity / stroke-dashoffset; the canvas runs at most 30 frames a
// second, only while the avatar is on screen, the page is visible and Effects is "Full" without reduced motion.
(() => {
  const NS = "http://www.w3.org/2000/svg";
  const STATES = ["idle", "listening", "understanding", "planning", "researching", "reasoning", "writing", "coding",
                  "verifying", "approval", "executing", "completed", "error",
                  "speaking", "warning", "recovery", "halted", "unknown", "learning", "experimenting", "analyzing", "disagreeing"];
  // The 2D fallback has no separate look for the newer states; each borrows the closest existing one.
  const LOOK_2D = { speaking: "writing", warning: "approval", recovery: "verifying", halted: "idle", unknown: "idle",
                    learning: "understanding", experimenting: "verifying", analyzing: "researching", disagreeing: "approval" };
  const ACTIVE = new Set(["understanding", "planning", "researching", "reasoning", "writing", "coding", "verifying", "executing"]);

  // A path drawn on both sides of the centre line (x = 200).
  const mirror = (d) => d.replace(/(-?\d+(?:\.\d+)?) (-?\d+(?:\.\d+)?)/g, (_, x, y) => `${400 - Number(x)} ${y}`);
  const pair = (cls, d) => `<path class="${cls}" pathLength="1" d="${d}"/><path class="${cls}" pathLength="1" d="${mirror(d)}"/>`;

  // [id, minimum evolution tier, markup]. Order is paint order (back to front).
  const PARTS = [
    ["aura", 1, `<ellipse class="av-aura" cx="200" cy="230" rx="190" ry="230" fill="url(#av-aura)"/>`],
    ["pad", 1, `<path class="av-beam" d="M118 506 L168 150 L232 150 L282 506 Z" fill="url(#av-beam)"/>
                <ellipse class="av-padglow" cx="200" cy="506" rx="170" ry="26" fill="url(#av-padglow)"/>
                <ellipse class="av-wire" pathLength="1" cx="200" cy="506" rx="124" ry="15"/>
                <ellipse class="av-thin av-padring" pathLength="1" cx="200" cy="506" rx="146" ry="19"/>
                <ellipse class="av-thin" pathLength="1" cx="200" cy="506" rx="88" ry="10"/>
                <path class="av-thin" pathLength="1" d="M60 506 L20 506 M340 506 L380 506"/>`],
    ["halo", 4, `<circle class="av-wire av-halo-ring" pathLength="1" cx="200" cy="140" r="112"/>
                 <circle class="av-thin av-halo-ring2" pathLength="1" cx="200" cy="140" r="124"/>`],
    ["orbits", 1, `<g class="av-orbit o1"><ellipse class="av-thin" pathLength="1" cx="200" cy="330" rx="178" ry="34"/></g>
                   <g class="av-orbit o2"><ellipse class="av-thin" pathLength="1" cx="200" cy="330" rx="150" ry="22"/></g>
                   <g class="av-orbit o3"><ellipse class="av-thin" pathLength="1" cx="200" cy="140" rx="110" ry="16"/></g>`],
    ["body", 1, `<g class="av-mesh">
        ${pair("av-wire", "M172 248 C130 250 82 258 54 282 C40 294 36 314 40 336 L60 476")}
        <path class="av-thin" pathLength="1" d="M74 300 C140 284 260 284 326 300"/>
        <path class="av-thin" pathLength="1" d="M58 352 C140 336 260 336 342 352"/>
        <path class="av-thin" pathLength="1" d="M60 404 C140 390 260 390 340 404"/>
        <path class="av-thin" pathLength="1" d="M62 452 C140 440 260 440 338 452"/>
        <path class="av-thin" pathLength="1" d="M200 252 L200 476"/>
        ${pair("av-thin", "M150 262 C140 330 132 400 128 476")}
        ${pair("av-wire", "M178 220 L172 252")}
        <path class="av-thin" pathLength="1" d="M176 232 C190 238 210 238 224 232"/>
      </g>`],
    ["sideplates", 1, `${pair("av-plate", "M42 344 L70 334 L80 424 L58 436 Z")}`],
    ["circuits", 2, `<g class="av-circuits">
        ${pair("av-trace", "M200 300 L200 282 L170 272 L136 272")}
        ${pair("av-trace", "M156 330 L112 330 L96 352")}
        ${pair("av-trace", "M178 384 L152 412 L118 412")}
        ${pair("av-trace", "M172 112 L184 122 L196 122")}
        <circle class="av-node" cx="136" cy="272" r="3"/><circle class="av-node" cx="264" cy="272" r="3"/>
        <circle class="av-node" cx="96" cy="352" r="3"/><circle class="av-node" cx="304" cy="352" r="3"/>
        <circle class="av-node" cx="118" cy="412" r="3"/><circle class="av-node" cx="282" cy="412" r="3"/>
      </g>`],
    ["plates", 1, `${pair("av-plate", "M120 290 C150 280 184 282 195 296 L195 300 C190 304 186 312 186 322 L120 376 C116 350 116 316 120 290 Z")}
                   ${pair("av-plate", "M160 400 L195 398 L195 418 L164 420 Z")}
                   ${pair("av-plate", "M166 426 L195 424 L195 444 L170 446 Z")}`],
    ["pauldrons", 1, `${pair("av-plate av-heavy", "M58 282 C70 250 120 238 162 252 L152 292 C120 286 90 292 62 314 Z")}
                      ${pair("av-thin", "M74 280 C96 264 124 258 150 262")}`],
    ["gorget", 1, `<path class="av-plate av-heavy" pathLength="1" d="M160 236 C180 250 220 250 240 236 L252 262 C222 278 178 278 148 262 Z"/>`],
    ["helmet", 1, `<path class="av-glow" d="M200 58 C240 58 266 86 268 128 L266 168 C262 192 246 212 222 222 L200 228 L178 222 C154 212 138 192 134 168 L132 128 C134 86 160 58 200 58 Z"/>
                   <path class="av-glow" d="M172 248 C130 250 82 258 54 282 M228 248 C270 250 318 258 346 282"/>
                   <path class="av-helm" pathLength="1" d="M200 58 C240 58 266 86 268 128 L266 168 C262 192 246 212 222 222 L200 228 L178 222 C154 212 138 192 134 168 L132 128 C134 86 160 58 200 58 Z"/>
                   <path class="av-thin" pathLength="1" d="M200 58 L200 104"/>
                   ${pair("av-thin", "M150 90 C165 110 168 130 166 150")}
                   ${pair("av-wire", "M146 126 C164 118 184 116 198 118")}
                   ${pair("av-plate", "M136 164 L158 176 L174 214 L160 208 C148 196 140 182 136 164 Z")}
                   <path class="av-plate" pathLength="1" d="M186 218 L200 222 L214 218 L210 230 L190 230 Z"/>
                   <circle class="av-wire" pathLength="1" cx="132" cy="148" r="9"/><circle class="av-wire" pathLength="1" cx="268" cy="148" r="9"/>
                   <circle class="av-node" cx="132" cy="148" r="2.5"/><circle class="av-node" cx="268" cy="148" r="2.5"/>`],
    ["fins", 4, `${pair("av-plate av-heavy", "M130 128 L104 104 L110 178 L132 172 Z")}
                 ${pair("av-thin", "M112 116 L114 168")}`],
    ["face", 1, `<g class="av-face">
        ${pair("av-thin", "M140 172 L170 188")}
        <path class="av-thin" pathLength="1" d="M184 196 L216 196"/>
        <path class="av-thin" pathLength="1" d="M187 204 L213 204"/>
        <path class="av-thin" pathLength="1" d="M191 212 L209 212"/>
      </g>`],
    ["visor", 1, `<path class="av-visor" d="M146 136 L186 145 L200 149 L214 145 L254 136 L249 156 L214 163 L200 167 L186 163 L151 156 Z"/>
                  <path class="av-visor-glint" d="M156 142 L186 149 L188 153 L158 148 Z"/>`],
    ["orbitfront", 1, `<path class="av-front f1" pathLength="1" d="M22 330 A178 34 0 0 0 378 330"/>
                       <path class="av-front f2" pathLength="1" d="M50 330 A150 22 0 0 0 350 330"/>
                       <path class="av-front f3" pathLength="1" d="M90 140 A110 16 0 0 0 310 140"/>`],
    ["scan", 1, `<rect class="av-scan" x="20" y="0" width="360" height="5"/>`],
  ];

  const FADED = new Set(["body", "sideplates", "circuits", "plates"]);

  function nodes(markup) {
    const doc = new DOMParser().parseFromString(`<svg xmlns="${NS}">${markup}</svg>`, "image/svg+xml");
    return [...doc.documentElement.childNodes].map((n) => document.importNode(n, true));
  }

  const av = { svg: null, wrap: null, canvas: null, state: "idle", tier: 1, layers: {}, visible: true, raf: 0,
               motes: [], last: 0, color: "242,184,75",
               status: "loading", attempts: 0, restoreTimer: 0, reopen: null };   // 3D status: see recovery below

  function fxLevel() {
    const reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const fx = document.documentElement.dataset.fx || "full";
    return reduced ? "off" : fx;
  }

  function mount(wrap) {
    if (av.svg || !wrap) return;
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 400 540");
    svg.setAttribute("class", "avatar materialize");
    svg.setAttribute("aria-hidden", "true");
    svg.dataset.state = "idle";
    svg.append(...nodes(`<defs>
        <radialGradient id="av-aura"><stop offset="0%" class="av-a0"/><stop offset="60%" class="av-a1"/><stop offset="100%" class="av-a2"/></radialGradient>
        <linearGradient id="av-glass" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" class="av-g0"/><stop offset="100%" class="av-g1"/></linearGradient>
        <linearGradient id="av-beam" x1="0" y1="1" x2="0" y2="0"><stop offset="0%" class="av-b0"/><stop offset="55%" class="av-b1"/><stop offset="100%" class="av-b2"/></linearGradient>
        <radialGradient id="av-padglow"><stop offset="0%" class="av-p0"/><stop offset="100%" class="av-p1"/></radialGradient>
        <linearGradient id="av-fadegrad" gradientUnits="userSpaceOnUse" x1="0" y1="380" x2="0" y2="500">
          <stop offset="0%" stop-color="#fff"/><stop offset="100%" stop-color="#000"/></linearGradient>
        <mask id="av-fade" maskUnits="userSpaceOnUse" x="0" y="0" width="400" height="540"><rect x="0" y="0" width="400" height="540" fill="url(#av-fadegrad)"/></mask>
      </defs>`));
    for (const [id, tier, markup] of PARTS) {
      const g = document.createElementNS(NS, "g");
      g.setAttribute("class", `av-layer av-${id}`);
      g.dataset.part = id;
      g.dataset.tier = String(tier);
      if (FADED.has(id)) g.setAttribute("mask", "url(#av-fade)"); // the torso dissolves into the projector beam
      g.append(...nodes(markup));
      svg.append(g);
      av.layers[id] = g;
    }
    const lines = document.createElement("div");
    lines.className = "avatar-lines";
    lines.setAttribute("aria-hidden", "true");
    wrap.prepend(lines);
    const canvas = document.createElement("canvas");
    canvas.className = "avatar-fx";
    canvas.setAttribute("aria-hidden", "true");
    wrap.prepend(canvas);
    wrap.prepend(svg);
    wrap.classList.add("has-avatar");
    bindInteraction(wrap);
    av.svg = svg; av.wrap = wrap; av.canvas = canvas;
    applyTier(1, false);
    setTimeout(() => svg.classList.remove("materialize"), 2400);
    if ("IntersectionObserver" in window) {
      new IntersectionObserver((entries) => { av.visible = entries.some((e) => e.isIntersecting); loop(); }).observe(wrap);
    }
    document.addEventListener("visibilitychange", loop);
    if (window.matchMedia) window.matchMedia("(prefers-reduced-motion: reduce)").addEventListener?.("change", loop);
    loop();
    tryThree();
    setTimeout(() => { av.cueReady = true; }, 3000);
  }

  // ---- 3D renderer (avatar3d.js, Three.js) --------------------------------------------------------------------
  // Used when WebGL works; the 2D core above stays underneath as the fallback (no WebGL, a lost GPU context, or
  // a failed load). Same states, same tier, same rules.
  function webgl() {
    try { const c = document.createElement("canvas"); return !!(c.getContext("webgl2") || c.getContext("webgl")); }
    catch (e) { return false; }
  }
  // The figure's meshes, computed in a module worker (null if workers aren't available: the renderer then builds them)
  function buildMeshes() {
    return new Promise((resolve) => {
      let w;
      try { w = new Worker("/static/avatar3d-worker.js", { type: "module" }); } catch (e) { resolve(null); return; }
      const done = (v) => { clearTimeout(timer); try { w.terminate(); } catch (e) { /* gone */ } resolve(v); };
      const timer = setTimeout(() => done(null), 60000);
      w.onmessage = (e) => { av.meshMs = e.data && e.data.ms; done(e.data); };
      w.onerror = () => done(null);
      w.postMessage({ phone: matchMedia("(max-width: 760px)").matches });
    });
  }
  async function tryThree() {
    if (av.three || av.trying) return;
    if (!webgl()) { av.status = "2d"; return; }
    av.trying = true;
    try {
      const mod = await import("/static/avatar3d.js");
      // the startup assembly plays once per browser session, in Normal mode only; any key or click skips it
      let boot = false;
      try { boot = fxLevel() === "full" && !sessionStorage.getItem("jarvis-booted"); } catch (e) { boot = false; }
      const endBoot = () => {
        if (SM) SM.setLifecycle(null);
        document.body.classList.remove("booting");
        try { sessionStorage.setItem("jarvis-booted", "1"); } catch (e) { /* plays again next time */ }
        document.removeEventListener("keydown", skip, true); document.removeEventListener("pointerdown", skip, true);
      };
      const skip = () => { if (av.three) av.three.skipBoot(); };
      const meshes = await buildMeshes();   // in the background: the page stays responsive meanwhile
      const three = mod.create(av.wrap, { state: av.state, tier: av.tier, mode: fxLevel(), intensity: intensity(), boot, onBootEnd: endBoot, options: av.options, meshes,
                                        onLifecycle: (phase) => { if (SM) show(SM.setLifecycle(phase)); } });
      if (!three) { av.status = "2d"; return; }
      av.three = three; av.status = "3d";
      if (av.systems) three.setSystems(av.systems);
      if (av.aura) three.setAura(av.aura);
      if (av.panels) three.setPanels(av.panels);
      three.setPersonality(personality(av.state));
      if (boot) { if (SM) SM.setLifecycle("materializing"); document.body.classList.add("booting"); document.addEventListener("keydown", skip, true); document.addEventListener("pointerdown", skip, true); }
      three.onLost = () => lost(three);
      three.onRestored = () => restored(three);
      av.wrap.classList.add("has-3d");
      loop();
      if (av.reopen && api.onRebuilt) { const list = av.reopen; av.reopen = null; api.onRebuilt(list); }   // reopen what was open
    } catch (e) {
      av.status = "unavailable";   // the renderer couldn't load (offline from JARVIS?): the 2D core stays; retried later
    } finally { av.trying = false; }
  }

  // ---- recovery: a lost GPU context shows the 2D core at once. If the browser restores the context within 8 s, the
  // same 3D projection resumes; otherwise it is disposed (every geometry, material, texture and listener) and built
  // again, up to three times with growing waits. Rebuild (Projection controls) starts over; nothing is faked meanwhile.
  const RESTORE_WAIT = 8000, RETRY_WAIT = [1500, 6000, 20000];
  function lost(three) {
    if (av.three !== three) return;
    av.status = "lost";
    av.wrap.classList.remove("has-3d"); av.wrap.classList.remove("inspecting"); av.inspecting = false;
    document.body.classList.remove("inspecting");
    loop();
    clearTimeout(av.restoreTimer);
    av.restoreTimer = setTimeout(() => { if (av.three === three && three.lost) rebuild(false); }, RESTORE_WAIT);
  }
  function restored(three) {
    if (av.three !== three) return;
    clearTimeout(av.restoreTimer);
    av.status = "3d"; av.attempts = 0;
    av.wrap.classList.add("has-3d");
    three.setState(av.state); loop();
  }
  // manual: true when you asked for it (resets the retry count)
  function rebuild(manual = true) {
    clearTimeout(av.restoreTimer);
    if (manual) av.attempts = 0;
    if (av.three) {
      const open = av.three.projections.map((p) => p.module);
      if (open.length) av.reopen = open;
      try { av.three.dispose(); } catch (e) { /* the context is gone already */ }
      av.three = null;
    }
    av.wrap && av.wrap.classList.remove("has-3d", "inspecting"); av.inspecting = false; document.body.classList.remove("inspecting");
    loop();
    if (av.attempts >= RETRY_WAIT.length) { av.status = "failed"; return false; }
    av.status = "restarting";
    const wait = manual ? 0 : RETRY_WAIT[av.attempts];
    av.attempts++;
    setTimeout(() => { tryThree().then(() => { if (av.three) av.attempts = manual ? 0 : av.attempts; else if (av.status !== "2d") rebuild(false); }); }, wait);
    return true;
  }
  // after JARVIS is reachable again (or the browser is back online): try the 3D renderer again if it never loaded
  function retry3d() { if (!av.three && !av.trying && (av.status === "unavailable" || av.status === "failed")) { av.attempts = 0; tryThree(); } }
  window.addEventListener("online", retry3d);

  // ---- interaction: hover a system satellite for its live status; click it to open that system; click anywhere
  // else on the projection (or press Enter) to open the projection focus view. The page decides what those do.
  const INTENSITY = { subtle: 0.75, standard: 1, vivid: 1.3 };
  function intensity() { return INTENSITY[document.documentElement.dataset.projection] || 1; }
  function bindInteraction(wrap) {
    wrap.setAttribute("role", "button");
    wrap.setAttribute("tabindex", "0");
    wrap.setAttribute("aria-label", "JARVIS projection: open the focus view");
    const label = document.createElement("div");
    label.className = "av-label"; label.hidden = true; label.setAttribute("role", "status");
    wrap.append(label);
    let lastMove = 0, drag = null;
    // Inspection (focus view): drag orbits the camera, the wheel or a pinch zooms, shift-drag / right-drag or two
    // fingers pan. Input is captured only while inspecting, so the page scrolls and the chat types as before.
    const touches = new Map();
    let pinch = null;
    const inspecting = () => !!(av.three && av.inspecting);
    wrap.addEventListener("pointerdown", (e) => {
      if (inspecting()) {
        touches.set(e.pointerId, { x: e.clientX, y: e.clientY });
        try { wrap.setPointerCapture(e.pointerId); } catch (err) { /* fine without */ }
        drag = { x: e.clientX, y: e.clientY, moved: 0, pan: e.shiftKey || e.button === 2 };
        if (touches.size === 2) { const [a, b] = [...touches.values()]; pinch = { d: Math.hypot(a.x - b.x, a.y - b.y), x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }; }
        return;
      }
      if (av.three && av.three.projections.length) drag = { x: e.clientX, y: e.clientY, moved: 0 };
    });
    const release = (e) => { touches.delete(e.pointerId); if (touches.size < 2) pinch = null; setTimeout(() => { if (!touches.size) drag = null; }, 0); };
    wrap.addEventListener("pointerup", release);
    wrap.addEventListener("pointercancel", release);
    wrap.addEventListener("contextmenu", (e) => { if (inspecting()) e.preventDefault(); });   // right-drag pans
    wrap.addEventListener("wheel", (e) => {
      if (!inspecting()) return;   // not inspecting: the page scrolls normally
      e.preventDefault();
      av.three.zoomCamera(Math.exp(Math.max(-1, Math.min(1, e.deltaY / 240))));
    }, { passive: false });
    wrap.addEventListener("pointermove", (e) => {
      if (inspecting() && drag) {
        if (touches.has(e.pointerId)) touches.set(e.pointerId, { x: e.clientX, y: e.clientY });
        if (pinch && touches.size >= 2) {   // two fingers: pinch zooms, moving both pans
          const [a, b] = [...touches.values()];
          const d = Math.hypot(a.x - b.x, a.y - b.y), mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
          if (d > 0 && pinch.d > 0) av.three.zoomCamera(pinch.d / d);
          av.three.panCamera(mx - pinch.x, my - pinch.y);
          pinch = { d, x: mx, y: my }; drag.moved += 10;
          return;
        }
        const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
        if (drag.pan || e.shiftKey) av.three.panCamera(dx, dy); else av.three.rotateCamera(dx, dy);
        drag.moved += Math.abs(dx) + Math.abs(dy); drag.x = e.clientX; drag.y = e.clientY;
        return;
      }
      if (!av.three || e.timeStamp - lastMove < 60) return;
      lastMove = e.timeStamp;
      if (drag && e.buttons === 1) {   // drag rotates the newest projection
        av.three.rotateProjection(e.clientX - drag.x, e.clientY - drag.y);
        drag.moved += Math.abs(e.clientX - drag.x) + Math.abs(e.clientY - drag.y); drag.x = e.clientX; drag.y = e.clientY;
        return;
      }
      const sys = av.three.pick(e.clientX, e.clientY);
      wrap.classList.toggle("on-system", !!sys);
      label.hidden = !sys;
      if (sys) {
        label.textContent = sys.projection ? sys.label : `${sys.label}: ${sys.value}`;
        const r = wrap.getBoundingClientRect();
        label.style.setProperty("--x", `${e.clientX - r.left}px`); label.style.setProperty("--y", `${e.clientY - r.top}px`);
      }
    });
    wrap.addEventListener("pointerleave", () => { label.hidden = true; wrap.classList.remove("on-system"); });
    wrap.addEventListener("click", (e) => {
      if (inspecting()) return;             // inspecting: clicks only steer the camera
      if (drag && drag.moved > 6) return;   // that was a rotation, not a click
      const sys = av.three && av.three.pick(e.clientX, e.clientY);
      if (sys && sys.projection) return;    // pointing at a projection node only inspects it
      if (sys && api.onSystem) api.onSystem(sys.id); else if (api.onFocus) api.onFocus();
    });
    wrap.addEventListener("keydown", (e) => {
      if (inspecting()) {   // keyboard inspection: arrows orbit, shift+arrows pan, + and - zoom, 0 resets
        const step = { ArrowLeft: [-24, 0], ArrowRight: [24, 0], ArrowUp: [0, -24], ArrowDown: [0, 24] }[e.key];
        if (step) { e.preventDefault(); if (e.shiftKey) av.three.panCamera(step[0], step[1]); else av.three.rotateCamera(step[0], step[1]); }
        else if (e.key === "+" || e.key === "=") { e.preventDefault(); av.three.zoomCamera(0.85); }
        else if (e.key === "-" || e.key === "_") { e.preventDefault(); av.three.zoomCamera(1 / 0.85); }
        else if (e.key === "0") { e.preventDefault(); av.three.resetCamera(); }
        return;
      }
      if ((e.key === "Enter" || e.key === " ") && api.onFocus) { e.preventDefault(); api.onFocus(); }
    });
  }
  // Which system satellite (if any) is under a screen point: used by hover/click, and by tests.
  function systemAt(x, y) { return av.three ? av.three.pick(x, y) : null; }
  function setSystems(list) { av.systems = list; if (av.three) av.three.setSystems(list); }
  // live data aura (real values 0..1, or null when unavailable) and the thought constellation (real chat stages)
  function setAura(values) { av.aura = values; if (av.three) av.three.setAura(values); }
  function setThought(count, active) { if (av.three) av.three.setThought(count, active); }
  // a gold shockwave across the dashboard when a mission really completes (Normal mode, no reduced motion)
  function surge() {
    if (fxLevel() !== "full" || !av.wrap) return;
    const r = av.wrap.getBoundingClientRect();
    const el = document.createElement("div");
    el.className = "surge"; el.setAttribute("aria-hidden", "true");
    el.style.setProperty("--x", `${r.left + r.width / 2}px`); el.style.setProperty("--y", `${r.top + r.height * 0.61}px`);
    document.body.append(el);
    setTimeout(() => el.remove(), 1800);
  }
  function pulse(strength) { if (av.three) av.three.pulse(strength); }
  // the microphone's measured level while recording (0..1), from app.js; 0 when it stops
  function voiceLevel(v) { if (av.three) av.three.setVoice(v); }

  function applyTier(tier, animate) {
    for (const g of Object.values(av.layers)) {
      const need = Number(g.dataset.tier);
      const show = tier >= need;
      const was = g.getAttribute("display") !== "none";
      if (show) g.removeAttribute("display"); else g.setAttribute("display", "none");
      if (show && !was && animate) {
        g.classList.add("materialize");
        setTimeout(() => g.classList.remove("materialize"), 2400);
      }
    }
    av.svg.dataset.tier = String(tier);
  }

  function setTier(tier) {
    tier = Math.max(1, Math.min(5, Number(tier) || 1));
    if (!av.svg || tier === av.tier) return;
    const up = tier > av.tier;
    av.tier = tier;
    applyTier(tier, up);
    if (av.three) av.three.setTier(tier);
  }

  // Every state goes through the central state machine (avatar-state.js): priorities, minimum times, the 4 s
  // success, stale-input fallback and previews live there, not here.
  const SM = window.JarvisAvatarState ? window.JarvisAvatarState.createMachine() : null;
  let smTimer = 0, smOut = { state: "idle", profile: "idle", preview: false, lifecycle: null };
  function schedule() {
    clearTimeout(smTimer); smTimer = 0;
    const next = SM && SM.nextIn;
    if (next !== null && next !== undefined) smTimer = setTimeout(() => { show(SM.tick()); schedule(); }, next);
  }
  function setState(state) {
    if (!STATES.includes(state)) state = "idle";
    if (!SM) return show({ state, profile: state, preview: false, lifecycle: null });
    show(SM.input(state)); schedule();
  }
  // projection settings (per device) and the floating panels' real status lines; the 2D core ignores both
  function setOptions(o) { av.options = { ...(av.options || {}), ...o }; if (av.three) av.three.setOptions(o); }
  function setPanels(items) { av.panels = items; if (av.three) av.three.setPanels(items); }
  function previewState(state) {   // shows a state for at most 10 s, always flagged as a preview
    if (!SM) return null;
    show(SM.previewState(state)); schedule();
    return smOut;
  }
  function endPreview() { if (SM) { show(SM.endPreview()); schedule(); } }
  function show(out) {
    smOut = out;
    if (av.wrap) av.wrap.dataset.preview = out.preview ? "1" : "";
    applyState(out.state);
  }
  function applyState(state) {
    if (!av.svg || state === av.state) return;
    av.state = state;
    av.svg.dataset.state = LOOK_2D[state] || state;
    av.svg.dataset.avatar = state;
    if (av.three) { av.three.setState(state); av.three.setPersonality(personality(state)); }
    av.color = getComputedStyle(av.svg).getPropertyValue("--av-rgb").trim() || av.color;
    if (effect(state) === "surge") { burst(); surge(); }   // the one-off for a real completion (avatar-events.js)
    // the sound cue (only if sound is on): real states only, never a preview, and not for the state found on load
    if (EV && window.JarvisSound && !smOut.preview && av.cueReady) window.JarvisSound.cue(EV.soundOf(state));
    loop();
  }

  // the central event-to-visual table (avatar-events.js); without it, the renderer's own defaults
  const EV = window.JarvisEvents || null;
  function personality(state) {
    if (!EV) return null;
    const name = EV.personalityOf(state);
    return { name, ...EV.PERSONALITY[name] };
  }
  function effect(state) { return EV ? EV.effectOf(state) : (state === "completed" ? "surge" : null); }

  function registerPart(name, markup) {
    const g = av.layers[name];
    if (!g || typeof markup !== "string") return false;
    g.replaceChildren(...nodes(markup));
    return true;
  }

  // ---- energy motes (canvas) -----------------------------------------------------------------------------------
  function running() { return av.canvas && !av.three && av.visible && !document.hidden && fxLevel() === "full"; }

  function size() {
    const r = av.canvas.getBoundingClientRect();
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const w = Math.max(1, Math.round(r.width * dpr)), hgt = Math.max(1, Math.round(r.height * dpr));
    if (av.canvas.width !== w || av.canvas.height !== hgt) { av.canvas.width = w; av.canvas.height = hgt; }
    return [w, hgt];
  }

  function spawn(w, hgt, fast) {
    const x = w * (0.25 + Math.random() * 0.5), y = hgt * (0.72 + Math.random() * 0.22); // rise from the projector
    av.motes.push({ x, y, vx: (Math.random() - 0.5) * 0.3, vy: -(0.2 + Math.random() * (fast ? 1.1 : 0.4)),
                    life: 1, r: 0.6 + Math.random() * 1.6 });
  }

  function burst() {
    if (!running()) return;
    const [w, hgt] = size();
    for (let i = 0; i < 40; i++) {
      const a = Math.random() * Math.PI * 2, s = 1 + Math.random() * 2.5;
      av.motes.push({ x: w / 2, y: hgt * 0.61, vx: Math.cos(a) * s, vy: Math.sin(a) * s, life: 1, r: 1 + Math.random() * 1.5 });
    }
  }

  function frame(t) {
    av.raf = 0;
    if (!running()) { clear(); return; }
    av.raf = requestAnimationFrame(frame);
    if (t - av.last < 33) return; // at most ~30 frames a second
    av.last = t;
    const [w, hgt] = size();
    const ctx = av.canvas.getContext("2d");
    ctx.clearRect(0, 0, w, hgt);
    const active = ACTIVE.has(av.state);
    const target = av.state === "error" ? 4 : active ? 36 : 14;
    if (av.motes.length < target && Math.random() < (active ? 0.9 : 0.35)) spawn(w, hgt, active);
    ctx.fillStyle = `rgb(${av.color})`;
    av.motes = av.motes.filter((m) => {
      m.x += m.vx; m.y += m.vy; m.life -= active ? 0.012 : 0.007;
      if (m.life <= 0) return false;
      ctx.globalAlpha = Math.max(0, m.life) * 0.8;
      ctx.beginPath(); ctx.arc(m.x, m.y, m.r * (window.devicePixelRatio > 1 ? 2 : 1), 0, Math.PI * 2); ctx.fill();
      return true;
    });
    ctx.globalAlpha = 1;
  }

  function clear() {
    av.motes = [];
    if (av.canvas && av.canvas.width) av.canvas.getContext("2d").clearRect(0, 0, av.canvas.width, av.canvas.height);
  }

  function loop() {
    if (av.three && av.lastMode !== fxLevel()) { av.lastMode = fxLevel(); av.three.setMode(av.lastMode); }
    if (av.three && av.lastIntensity !== intensity()) { av.lastIntensity = intensity(); av.three.setIntensity(av.lastIntensity); }
    if (running()) { if (!av.raf) av.raf = requestAnimationFrame(frame); }
    else { if (av.raf) cancelAnimationFrame(av.raf); av.raf = 0; clear(); }
  }

  // projections: real data from the dashboard, drawn by the 3D renderer (nothing in 2D: the core shows no projections)
  function showProjection(m, data) { return av.three ? av.three.showProjection(m, data) : false; }
  function closeProjection(m) { if (av.three) av.three.closeProjection(m); }
  function closeProjections() { if (av.three) av.three.closeProjections(); }
  function pinProjection(m, on) { if (av.three) av.three.pinProjection(m, on); }
  // projection panel controls (expand, collapse, minimise, side, order): the look only, never the data or an action
  function projectionControl(op, m, arg) {
    if (!av.three) return false;
    const t = av.three;
    return op === "expand" ? t.expandProjection(m) : op === "collapse" ? (t.collapseProjection(), true) : op === "minimize" ? t.minimizeProjection(m, arg !== false)
      : op === "side" ? t.sideProjection(m, arg) : op === "move" ? t.moveProjection(m, arg) : op === "inspect" ? (inspect(true) && t.inspectProjection(m)) : false;
  }
  // camera and inspection (3D only): moving the camera never changes what JARVIS is doing
  function inspect(on) {
    if (!av.three || !av.wrap) { av.inspecting = false; return false; }
    av.inspecting = !!on; av.three.inspect(av.inspecting);
    av.wrap.classList.toggle("inspecting", av.inspecting);
    av.wrap.setAttribute("aria-label", av.inspecting ? "JARVIS projection, inspecting: drag or arrow keys to orbit, scroll or + and - to zoom, shift to pan, Esc to exit"
                                                      : "JARVIS projection: open the focus view");
    return av.inspecting;
  }
  function cameraView(name) { return av.three ? av.three.cameraView(name) : false; }
  function inspectTarget(name) { return av.three ? av.three.inspectTarget(name) : false; }
  function resetCamera() { if (av.three) av.three.resetCamera(); }
  // transformation sequences (look only; avatar3d-transform.js): name or null to close
  function transform(name) { return av.three ? av.three.transform(name) : false; }
  const api = { mount, setState, previewState, endPreview, setOptions, setPanels, showProjection, closeProjection, closeProjections, pinProjection, projectionControl, inspect, rebuild: () => rebuild(true), retry3d, onRebuilt: null, cameraView, inspectTarget, resetCamera, transform, setTier, setSystems, setAura, setThought, systemAt, pulse, voiceLevel, registerPart, refresh: loop, STATES, onFocus: null, onSystem: null,
                          get state() { return av.state; }, get profile() { return smOut.profile; }, get preview() { return smOut.preview; },
                          get lifecycle() { return smOut.lifecycle; },
                          get quality() { return av.three ? av.three.quality : null; },
                          get qualityInfo() { return av.three ? av.three.qualityInfo : null; },
                          get status() { return av.status; }, get context() { return av.three ? av.three.context : null; },
                          get projections() { return av.three ? av.three.projections : []; }, get modules() { return av.three ? av.three.modules : []; }, get tier() { return av.tier; },
                          get animating() { return av.raf !== 0 || !!(av.three && av.three.animating); },
                          get renderer() { return av.three ? "3d" : "2d"; },
                          get stats() { return av.three ? av.three.stats : null; },
                          get voiceNow() { return av.three ? av.three.voice : null; },
                          get neuralOp() { return av.three ? av.three.neuralOp : null; },
                          get personality() { const p = personality(av.state); return p ? p.name : null; },
                          get camera() { return av.three ? av.three.camera : null; }, get inspecting() { return !!(av.three && av.inspecting); },
                          get views() { return av.three ? av.three.VIEWS : {}; }, get sequences() { return av.three ? av.three.SEQUENCES : {}; },
                          get transformState() { return av.three ? av.three.transformState : null; }, get targets() { return av.three ? av.three.TARGETS : {}; },
                          get eyes() { return av.three ? av.three.eyes : null; } };   // read-only: what the eyes are showing
  window.JarvisAvatar = api;
})();
