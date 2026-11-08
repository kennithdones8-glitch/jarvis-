"use strict";
// JARVIS Avatar 2.5: the one table that says what each real signal looks like. Every visual decision that follows
// from a state lives here: how the figure moves (its personality), which projection the focus view opens on its
// own, the one-off effect, and the sound cue (used only if you turn ambient sound on). Pure data and lookups, no
// DOM, so Node can test it and both renderers read the same answers.
//
// Personalities are ways of moving, not feelings: the projection never claims an emotion. Each one is chosen only
// by a state, and every state comes from a real signal (avatarState in app.js; priorities and timing in
// avatar-state.js). "disagreeing" means one thing only: the permission engine or the privacy guard refused an
// action (a new permission.denied or egress.denied entry in the audit log).
(function (root) {
  // how the figure moves: head behaviour, arm gesture, whether it glances around, and what the motion means
  const PERSONALITY = {
    idle:          { head: "aware", gesture: "rest", glances: true, means: "nothing in progress" },
    listening:     { head: "attend", gesture: "rest", glances: false, means: "you are speaking or typing" },
    curious:       { head: "scan", gesture: "rest", glances: false, means: "reading sources or its own data" },
    concentrating: { head: "think", gesture: "rest", glances: false, means: "working out an answer or a plan" },
    explaining:    { head: "speak", gesture: "present", glances: false, means: "reading a reply aloud" },
    disagreeing:   { head: "shake", gesture: "halt", glances: false, means: "an action was refused by your rules" },
    executing:     { head: "aware", gesture: "work", glances: false, means: "a task step is running" },
    waiting:       { head: "attend", gesture: "raise", glances: false, means: "waiting for your decision" },
    confirming:    { head: "aware", gesture: "open", glances: false, means: "a task really completed" },
    recovering:    { head: "rise", gesture: "rest", glances: false, means: "coming back after a restart or reconnect" },
    alert:         { head: "still", gesture: "rest", glances: false, means: "a warning, an error or the emergency stop" },
  };
  // renderer state -> visual decisions. projection: the focus view's automatic projection (null = none).
  // effect: a one-off on entering the state. sound: the cue name for avatar-sound.js (null = silent).
  const MAP = {
    unknown:       { personality: "idle", projection: null, effect: null, sound: null },
    idle:          { personality: "idle", projection: null, effect: null, sound: null },
    listening:     { personality: "listening", projection: null, effect: null, sound: null },
    understanding: { personality: "concentrating", projection: null, effect: null, sound: null },
    reasoning:     { personality: "concentrating", projection: null, effect: null, sound: null },
    writing:       { personality: "concentrating", projection: null, effect: null, sound: null },
    coding:        { personality: "concentrating", projection: null, effect: null, sound: null },
    planning:      { personality: "concentrating", projection: "workflow", effect: null, sound: null },
    researching:   { personality: "curious", projection: null, effect: null, sound: null },
    analyzing:     { personality: "curious", projection: null, effect: null, sound: null },
    experimenting: { personality: "curious", projection: "simulation", effect: null, sound: null },
    learning:      { personality: "concentrating", projection: "neural", effect: null, sound: "learn" },
    executing:     { personality: "executing", projection: "workflow", effect: null, sound: null },
    verifying:     { personality: "executing", projection: "workflow", effect: null, sound: null },
    speaking:      { personality: "explaining", projection: null, effect: null, sound: null },
    approval:      { personality: "waiting", projection: "security", effect: null, sound: "attention" },
    disagreeing:   { personality: "disagreeing", projection: "security", effect: "shield", sound: "deny" },
    completed:     { personality: "confirming", projection: null, effect: "surge", sound: "confirm" },
    warning:       { personality: "alert", projection: null, effect: "shield", sound: "attention" },
    error:         { personality: "alert", projection: null, effect: "shield", sound: "error" },
    recovery:      { personality: "recovering", projection: null, effect: "rebuild", sound: null },
    halted:        { personality: "alert", projection: "security", effect: "dematerialize", sound: "halt" },
  };
  // audit-log events that briefly show a state of their own (shown once per new entry)
  const AUDIT_STATES = { "permission.denied": "disagreeing", "egress.denied": "disagreeing" };
  const PROJECTIONS = ["architecture", "workflow", "neural", "timeline", "data", "security", "globe", "simulation"];

  const visual = (state) => MAP[state] || MAP.idle;
  const personalityOf = (state) => visual(state).personality;
  // the newest audit entry (seq above `after`) that maps to a state, or null. Entries are newest first.
  function fromAudit(entries, after) {
    for (const e of entries || []) {
      if (!(e && typeof e.seq === "number") || e.seq <= after) break;
      if (AUDIT_STATES[e.event]) return { state: AUDIT_STATES[e.event], seq: e.seq };
    }
    return null;
  }
  const api = { PERSONALITY, MAP, AUDIT_STATES, PROJECTIONS, visual, personalityOf, fromAudit,
                projectionFor: (state) => visual(state).projection, effectOf: (state) => visual(state).effect,
                soundOf: (state) => visual(state).sound };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.JarvisEvents = api;
})(typeof window !== "undefined" ? window : globalThis);
