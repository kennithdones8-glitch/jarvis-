"use strict";
// JARVIS avatar state machine: the one place that decides which state the projection shows. Pure logic (no DOM,
// no rendering, no timers of its own), so it can be tested on its own and used by both renderers.
//
// Input: the state the dashboard derives from real signals on every poll (see avatarState in app.js). The
// machine adds what a single snapshot cannot:
//   - priorities: a critical state replaces anything at once; routine activity cannot replace a more important
//     state until that state has been on screen for its minimum time (no flicker, nothing important missed);
//   - one-shot states end on their own: "completed" (success) shows for at most 4 s, then idle;
//   - stale input: if the dashboard stops reporting (a stalled poll) for 10 s, live-work states fall back to idle
//     instead of showing activity that is no longer confirmed;
//   - lifecycle: dormant before any data, materializing during the startup sequence, dematerializing while the
//     emergency stop takes the projection down;
//   - preview: a requested state shown for at most 10 s and always flagged as a preview, never as real activity;
//     a real critical state ends a preview immediately.
(function (root) {
  // the renderer's states (one look each) -> the profile they belong to (the 14 + 2 of the design brief)
  const PROFILE = {
    unknown: "dormant", idle: "idle", listening: "listening",
    understanding: "thinking", reasoning: "thinking", writing: "thinking", coding: "thinking",
    researching: "researching", planning: "planning", executing: "executing", verifying: "executing",
    speaking: "speaking", completed: "success", warning: "warning", error: "error", recovery: "recovering",
    approval: "approval", halted: "halted",
    learning: "learning", experimenting: "experimenting", analyzing: "analyzing",
  };
  const STATES = Object.keys(PROFILE);
  // higher wins at once; lower waits for the current state's minimum time
  const PRIORITY = { halted: 100, error: 90, approval: 80, warning: 70, recovering: 60, success: 55, speaking: 50,
                     executing: 45, experimenting: 44, researching: 42, analyzing: 41, thinking: 40, planning: 38, learning: 36,
                     listening: 30, idle: 10, dormant: 5 };
  const MIN_MS = { error: 2500, warning: 2000, success: 1200, halted: 1500 };   // others: anti-flicker minimum
  const DEFAULT_MIN_MS = 700;
  const MAX_MS = { success: 4000, learning: 4000 };   // one-shots: a new lesson is shown briefly, never held                  // one-shot: ends on its own even if the input still says so
  const LIVE = new Set(["thinking", "researching", "planning", "executing", "speaking", "listening", "experimenting", "analyzing"]);
  const STALE_MS = 10000, PREVIEW_MS = 10000, CRITICAL = 80;

  function createMachine(opts = {}) {
    const now = opts.now || (() => Date.now());
    const m = {
      raw: "unknown", rawAt: now(),          // latest input and when it arrived
      shown: "unknown", shownAt: now(),      // what the projection shows and since when
      lifecycle: null,                       // "materializing" | "dematerializing" | null
      preview: null, previewUntil: 0,
      expired: null,                         // a one-shot state that already ended (until the input changes)
    };
    const profile = (s) => PROFILE[s] || "idle";
    const prio = (s) => PRIORITY[profile(s)] || 0;
    const minFor = (s) => MIN_MS[profile(s)] ?? DEFAULT_MIN_MS;

    function wanted(t) {
      let s = STATES.includes(m.raw) ? m.raw : "idle";
      if (m.expired === s) s = "idle";                                          // a finished one-shot
      if (LIVE.has(profile(s)) && t - m.rawAt > STALE_MS) s = "idle";          // unconfirmed activity
      return s;
    }
    function resolve() {
      const t = now();
      if (m.preview && (t >= m.previewUntil || prio(m.raw) >= CRITICAL)) m.preview = null;
      const max = MAX_MS[profile(m.shown)];
      if (max && t - m.shownAt >= max && m.shown === m.raw) m.expired = m.shown;
      const want = wanted(t);
      if (want !== m.shown) {
        const held = t - m.shownAt >= minFor(m.shown) || (max && t - m.shownAt >= max);
        if (prio(want) >= prio(m.shown) || held) { m.shown = want; m.shownAt = t; }
      }
      return output();
    }
    function output() {
      const state = m.preview || m.shown;
      return { state, profile: profile(state), preview: !!m.preview, lifecycle: m.lifecycle };
    }
    return {
      // a fresh snapshot from the dashboard
      input(raw) {
        if (raw !== m.raw) { m.raw = raw; m.expired = null; }
        m.rawAt = now();
        return resolve();
      },
      tick: resolve,
      // when the caller should call tick() again (ms from now), or null if nothing is pending
      get nextIn() {
        const t = now(), times = [];
        const max = MAX_MS[profile(m.shown)];
        if (max && m.shown === m.raw && !m.expired) times.push(m.shownAt + max);
        if (wanted(t) !== m.shown) times.push(m.shownAt + minFor(m.shown));
        if (LIVE.has(profile(m.raw))) times.push(m.rawAt + STALE_MS + 1);
        if (m.preview) times.push(m.previewUntil);
        const next = times.filter((x) => x > t);
        return next.length ? Math.max(16, Math.min(...next) - t) : (times.length ? 16 : null);
      },
      previewState(s, ms = PREVIEW_MS) {
        if (!STATES.includes(s) || prio(m.raw) >= CRITICAL) return output();
        m.preview = s; m.previewUntil = now() + Math.min(ms, PREVIEW_MS);
        return output();
      },
      endPreview() { m.preview = null; return resolve(); },
      setLifecycle(phase) { m.lifecycle = phase || null; return output(); },
      get output() { return output(); },
    };
  }

  const api = { createMachine, PROFILE, PRIORITY, STATES, STALE_MS, PREVIEW_MS };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.JarvisAvatarState = api;
})(typeof window !== "undefined" ? window : globalThis);
