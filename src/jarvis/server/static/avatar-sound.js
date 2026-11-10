"use strict";
// JARVIS Avatar 2.5: optional ambient sound. Off unless you turn it on (Projection controls → Sound), on this device
// only. Every sound is generated here with the Web Audio API (no audio files, nothing licensed or downloaded): a very
// quiet low hum while the page is visible, and short tones for real events (the cue names come from avatar-events.js:
// a task completed, your decision needed, a refusal, an error, the emergency stop, a lesson learned).
//
// It never competes with speech: while JARVIS reads a reply aloud or the microphone is recording, the hum fades out
// and no tones play. Nothing here listens, records or sends anything.
(function (root) {
  const CUES = {   // [frequency Hz, start s, length s, kind] per note; quiet by design
    confirm:   [[660, 0, 0.18, "sine"], [990, 0.12, 0.32, "sine"]],
    attention: [[523, 0, 0.22, "sine"]],
    learn:     [[880, 0, 0.1, "sine"], [1046, 0.09, 0.1, "sine"], [1318, 0.18, 0.2, "sine"]],
    deny:      [[294, 0, 0.16, "triangle"], [220, 0.13, 0.26, "triangle"]],
    error:     [[185, 0, 0.18, "triangle"], [185, 0.26, 0.22, "triangle"]],
    halt:      [[392, 0, 0.5, "sine", 196]],   // a falling sweep
  };
  // the same cue at most once per gap; standing conditions (a decision waiting, a warning, an error) much less often
  const GAP_MS = { attention: 60000, error: 30000 }, DEFAULT_GAP = 4000;
  let ctx = null, master = null, hum = null, enabled = false, ducked = false, last = {};

  function ensure() {
    if (ctx) return ctx;
    const AC = root.AudioContext || root.webkitAudioContext;
    if (!AC) return null;
    ctx = new AC();
    master = ctx.createGain(); master.gain.value = 0; master.connect(ctx.destination);
    // the hum: two soft, slightly detuned low tones through a low-pass filter, breathing very slowly
    const lp = ctx.createBiquadFilter(); lp.type = "lowpass"; lp.frequency.value = 240; lp.connect(master);
    const humGain = ctx.createGain(); humGain.gain.value = 0.012; humGain.connect(lp);
    const oscs = [55, 82.6].map((f) => { const o = ctx.createOscillator(); o.frequency.value = f; o.connect(humGain); o.start(); return o; });
    const lfo = ctx.createOscillator(), lfoGain = ctx.createGain(); lfo.frequency.value = 0.08; lfoGain.gain.value = 0.004;
    lfo.connect(lfoGain); lfoGain.connect(humGain.gain); lfo.start();
    hum = { oscs, lfo, humGain };
    return ctx;
  }
  function level() { return enabled && !ducked && !(root.document && root.document.hidden) ? 1 : 0; }
  function apply() {
    if (!ctx) return;
    const now = ctx.currentTime;
    master.gain.cancelScheduledValues(now);
    master.gain.setTargetAtTime(level(), now, ducked ? 0.08 : 0.6);   // duck fast, return gently
  }
  const api = {
    get enabled() { return enabled; }, get ducked() { return ducked; }, get running() { return !!ctx && ctx.state === "running"; },
    CUES: Object.keys(CUES),
    // on: only after a click or tap (browsers require one before sound); off: silence and release the audio device
    setEnabled(on) {
      enabled = !!on;
      if (enabled) { if (!ensure()) return false; if (ctx.state === "suspended") ctx.resume().catch(() => {}); apply(); return true; }
      if (ctx) { const c = ctx; ctx = null; master = null; hum = null; c.close().catch(() => {}); }
      return false;
    },
    resume() { if (enabled && ctx && ctx.state === "suspended") ctx.resume().catch(() => {}); },
    // while JARVIS speaks or the microphone records: the hum fades out and no tones play
    duck(on) { ducked = !!on; apply(); },
    visibility() { apply(); },
    cue(name) {
      const notes = CUES[name];
      if (!notes || !enabled || ducked || !ctx || ctx.state !== "running") return false;
      const t0 = Date.now();
      if (last[name] && t0 - last[name] < (GAP_MS[name] || DEFAULT_GAP)) return false;
      last[name] = t0;
      const now = ctx.currentTime;
      for (const [f, at, len, type, to] of notes) {
        const o = ctx.createOscillator(), g = ctx.createGain();
        o.type = type; o.frequency.setValueAtTime(f, now + at);
        if (to) o.frequency.exponentialRampToValueAtTime(to, now + at + len);
        g.gain.setValueAtTime(0, now + at); g.gain.linearRampToValueAtTime(0.045, now + at + 0.02);
        g.gain.exponentialRampToValueAtTime(0.0001, now + at + len);
        o.connect(g); g.connect(master); o.start(now + at); o.stop(now + at + len + 0.05);
      }
      return true;
    },
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.JarvisSound = api;
})(typeof window !== "undefined" ? window : globalThis);
