"use strict";
// Kerbside Grand Prix: sound. Everything is synthesised with Web Audio (no audio files):
//   engine   — each body style has its own voice (a buzzy kei three-cylinder, a club four, a flat-six coupe, a V8 muscle
//              car and police sedan, a screaming V10 supercar, a prototype's whine), with gears you hear change, a
//              turbo that whistles as it spools and blows off when you lift, and backfire pops;
//   car      — tyre squeal from the slip angle, the nitro rush, impacts, the overtake whoosh;
//   world    — the crowd (louder near the grandstands and at the start and finish), rain on the car (silent in the
//              tunnel), police sirens that rise as units close in, and police radio chatter;
//   music    — a loop that follows the race: calm in menus, drums once you're racing, an extra layer on the final lap,
//              and a darker, faster mood in a pursuit;
//   cues     — start-light beeps, lap chimes, the finish fanfare and menu clicks.
// Browsers only allow sound after a tap or key press, so nothing plays until unlock(). Without Web Audio every call
// is a harmless no-op, so the game never fails to load because of sound.
(function (root) {
  const NOOP = new Proxy({}, { get: () => () => {} });
  // Engine voices by body style: idle pitch (Hz), rev range, waveform mix, a sub-octave, drive (growl), gears.
  const VOICES = {
    kei: { idle: 70, span: 150, sub: 0.2, drive: 0.15, gears: 5, cut: 2600 },
    open: { idle: 62, span: 130, sub: 0.35, drive: 0.25, gears: 5, cut: 2800 },
    hatch: { idle: 58, span: 120, sub: 0.4, drive: 0.25, gears: 5, cut: 2600 },
    rally: { idle: 55, span: 120, sub: 0.45, drive: 0.4, gears: 5, cut: 2400 },
    coupe: { idle: 52, span: 125, sub: 0.45, drive: 0.35, gears: 6, cut: 3000 },
    roadster: { idle: 54, span: 120, sub: 0.4, drive: 0.3, gears: 6, cut: 2800 },
    wagon: { idle: 46, span: 105, sub: 0.55, drive: 0.4, gears: 6, cut: 2300 },
    sedan: { idle: 40, span: 90, sub: 0.7, drive: 0.55, gears: 5, cut: 2000 },
    muscle: { idle: 36, span: 85, sub: 0.8, drive: 0.7, gears: 5, cut: 1800 },
    gt: { idle: 48, span: 130, sub: 0.5, drive: 0.4, gears: 6, cut: 3200 },
    super: { idle: 60, span: 170, sub: 0.35, drive: 0.35, gears: 7, cut: 4200 },
    proto: { idle: 68, span: 190, sub: 0.25, drive: 0.2, gears: 7, cut: 4800, whine: 0.04 },
    truck: { idle: 36, span: 84, sub: 0.75, drive: 0.6, gears: 5, cut: 1700 },
  };
  function create(settings = {}) {
    const AC = root.AudioContext || root.webkitAudioContext;
    if (!AC) return NOOP;
    let ac = null, nodes = null, set = { sound: true, music: true, announcer: true, volume: 0.7, ...settings }, musicTimer = null, step = 0, paused = false;
    let mood = "menu", intensity = 0, voice = VOICES.open, lastGear = 0, shiftDip = 0, spool = 0, lastThr = false;
    const safe = (fn) => (...a) => { try { return fn(...a); } catch { return undefined; } };
    function init() {
      if (ac) return true;
      ac = new AC();
      const master = ac.createGain(), sfx = ac.createGain(), music = ac.createGain(), amb = ac.createGain();
      master.connect(ac.destination); sfx.connect(master); music.connect(master); amb.connect(master);
      // engine: saw + square an octave down + a sine sub, through a waveshaper (growl) and a low-pass that opens with revs
      const o1 = ac.createOscillator(), o2 = ac.createOscillator(), o3 = ac.createOscillator(), sub = ac.createGain(), mix = ac.createGain();
      const shaper = ac.createWaveShaper(), lp = ac.createBiquadFilter(), eg = ac.createGain();
      o1.type = "sawtooth"; o2.type = "square"; o3.type = "sine"; lp.type = "lowpass"; lp.Q.value = 3; eg.gain.value = 0;
      // a peak for exhaust rasp, and a slow wobble in the volume for a V8's lumpy idle (the lope)
      const pk = ac.createBiquadFilter(), amp = ac.createGain(), lfo2 = ac.createOscillator(), lope = ac.createGain();
      pk.type = "peaking"; pk.frequency.value = 1800; pk.Q.value = 2; pk.gain.value = 0; amp.gain.value = 1; lfo2.frequency.value = 6; lope.gain.value = 0;
      lfo2.connect(lope); lope.connect(amp.gain);
      o1.connect(mix); o2.connect(mix); o3.connect(sub); sub.connect(mix); mix.connect(shaper); shaper.connect(pk); pk.connect(lp); lp.connect(amp); amp.connect(eg); eg.connect(sfx);
      o1.start(); o2.start(); o3.start(); lfo2.start();
      // turbo whistle and the prototype's motor whine
      const tw = ac.createOscillator(), twg = ac.createGain(); tw.type = "sine"; tw.frequency.value = 2200; twg.gain.value = 0; tw.connect(twg); twg.connect(sfx); tw.start();
      // noise for tyres, nitro, crowd and rain
      const buf = ac.createBuffer(1, ac.sampleRate * 2, ac.sampleRate), d = buf.getChannelData(0);
      for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
      const noise = () => { const n = ac.createBufferSource(); n.buffer = buf; n.loop = true; n.start(); return n; };
      const band = (type, f, q, g0, dest) => { const f1 = ac.createBiquadFilter(), g = ac.createGain(); f1.type = type; f1.frequency.value = f; f1.Q.value = q; g.gain.value = g0; noise().connect(f1); f1.connect(g); g.connect(dest); return { f: f1, g }; };
      const tyre = band("bandpass", 1800, 6, 0, sfx), nitro = band("highpass", 900, 0.7, 0, sfx);
      const crowd = band("bandpass", 650, 0.8, 0, amb), rain = band("highpass", 3200, 0.5, 0, amb);
      // siren: a triangle wave whose pitch is swept by a slow LFO (the wail)
      const sr = ac.createOscillator(), srg = ac.createGain(), lfo = ac.createOscillator(), lfoG = ac.createGain();
      sr.type = "triangle"; sr.frequency.value = 950; lfo.frequency.value = 0.42; lfoG.gain.value = 380; srg.gain.value = 0;
      lfo.connect(lfoG); lfoG.connect(sr.frequency); sr.connect(srg); srg.connect(amb); sr.start(); lfo.start();
      nodes = { master, sfx, music, amb, o1, o2, o3, sub, shaper, pk, lp, amp, lfo2, lope, eg, tw, twg, tyre, nitro, crowd, rain, sr, srg, lfo, buf };
      setVoice("open");
      apply();
      return true;
    }
    function curve(k) {   // a soft-clip curve; more drive, more growl
      const n = 256, c = new Float32Array(n);
      for (let i = 0; i < n; i++) { const x = i / (n - 1) * 2 - 1; c[i] = Math.tanh(x * (1 + k * 6)) / Math.tanh(1 + k * 6); }
      return c;
    }
    // A car's voice: its body style's voice with the car's own settings on top (cylinders, revs, lope, rasp, whine).
    function setVoice(shape, own) {
      voice = { ...(VOICES[shape] || VOICES.open), ...(own || {}) };
      if (!nodes) return;
      nodes.shaper.curve = curve(voice.drive); nodes.sub.gain.value = voice.sub;
      nodes.pk.gain.value = (voice.rasp || 0) * 12;
      // the second oscillator sets the character: an octave down for fours and V8s, a fifth for sixes, an octave up (smooth) for V10s and V12s
      if (voice.electric) { voice.gears = 1; voice.whine = 0.06; voice.drive = 0.05; voice.sub = 0.1; voice.cut = 6000; nodes.shaper.curve = curve(0.05); nodes.sub.gain.value = 0.1; }
      const cyl = voice.cyl || 4; voice.ratio = cyl >= 10 ? 2 : cyl === 6 || cyl === 5 ? 1.5 : cyl === 3 ? 0.75 : 0.5;
      nodes.o2.type = cyl >= 10 ? "sawtooth" : "square";
    }
    function apply() {
      if (!nodes) return;
      const t = ac.currentTime;
      nodes.master.gain.setTargetAtTime(set.volume, t, 0.05);
      nodes.sfx.gain.setTargetAtTime(set.sound ? 1 : 0, t, 0.05);
      nodes.amb.gain.setTargetAtTime(set.sound ? 1 : 0, t, 0.05);
      nodes.music.gain.setTargetAtTime(set.music ? (mood === "menu" ? 0.35 : 0.2) : 0, t, 0.2);
      if (set.music && !musicTimer) musicTimer = setInterval(tick, 30);
      if (!set.music && musicTimer) { clearInterval(musicTimer); musicTimer = null; }
    }
    function blip(freq, dur, type = "square", gain = 0.2, to = null, dest = "sfx", when = 0) {
      if (!nodes) return;
      const t = ac.currentTime + when, o = ac.createOscillator(), g = ac.createGain();
      o.type = type; o.frequency.setValueAtTime(freq, t); if (to) o.frequency.exponentialRampToValueAtTime(to, t + dur);
      g.gain.setValueAtTime(gain, t); g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
      o.connect(g); g.connect(nodes[dest]); o.start(t); o.stop(t + dur + 0.02);
    }
    function burst(type, f0, f1, dur, gain, dest = "sfx", q = 1, when = 0) {   // a filtered noise burst with a sweep
      if (!nodes) return;
      const t = ac.currentTime + when, n = ac.createBufferSource(), f = ac.createBiquadFilter(), g = ac.createGain();
      n.buffer = nodes.buf; f.type = type; f.Q.value = q; f.frequency.setValueAtTime(f0, t); f.frequency.exponentialRampToValueAtTime(f1, t + dur);
      g.gain.setValueAtTime(gain, t); g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
      n.connect(f); f.connect(g); g.connect(nodes[dest]); n.start(t, Math.random()); n.stop(t + dur + 0.02);
    }
    // music: a step sequencer on sixteenths. Menu: bass and a soft arpeggio (Am F C G). Racing: plus kick and hats.
    // Final lap or high heat: plus a snare and an octave-up lead. Pursuit: a minor loop (Dm Bb Gm A), faster.
    const LOOPS = { calm: { ch: [[57, 60, 64], [53, 57, 60], [48, 52, 55], [55, 59, 62]], bpm: 112 }, chase: { ch: [[50, 53, 57], [46, 50, 53], [43, 46, 50], [45, 49, 52]], bpm: 138 } };
    const hz = (m) => 440 * Math.pow(2, (m - 69) / 12);
    let nextT = 0;
    function tick() {   // schedules ahead on the audio clock, so the beat stays steady even if a frame is slow
      if (!nodes || paused || ac.state !== "running") return;
      const L = mood === "pursuit" ? LOOPS.chase : LOOPS.calm, sixteenth = 60 / L.bpm / 4;
      if (nextT < ac.currentTime) nextT = ac.currentTime + 0.05;
      while (nextT < ac.currentTime + 0.12) {
        const when = nextT - ac.currentTime, ch = L.ch[Math.floor(step / 16) % 4], s = step % 16, racing = mood !== "menu";
        if (s % 4 === 0) blip(hz(ch[0] - 24), 0.22, "triangle", 0.28, null, "music", when);
        if (s % 2 === 0) blip(hz(ch[(s / 2) % 3] + 12), 0.12, "square", racing ? 0.04 : 0.05, null, "music", when);
        if (s === 8) blip(hz(ch[2] + 24), 0.3, "sine", 0.05, null, "music", when);
        if (racing) {
          if (s % 4 === 0) blip(110, 0.12, "sine", 0.35, 40, "music", when);                // kick
          if (s % 2 === 1) burst("highpass", 7000, 6000, 0.04, 0.05, "music", 0.7, when);    // hats
        }
        if (racing && intensity >= 2) {
          if (s === 4 || s === 12) burst("bandpass", 1800, 900, 0.14, 0.12, "music", 0.8, when);   // snare
          if (s % 4 === 2) blip(hz(ch[(s >> 2) % 3] + 24), 0.1, "sawtooth", 0.025, null, "music", when);
        }
        step++; nextT += sixteenth;
      }
    }
    // The race announcer: the browser's own speech synthesis (free, offline on most devices). Lines are short and
    // throttled; a more important line interrupts a less important one. Silent where speech isn't available.
    const SP = typeof speechSynthesis !== "undefined" && typeof SpeechSynthesisUtterance !== "undefined" ? speechSynthesis : null;
    let sayUntil = 0, sayPri = 0, sayVoice;
    function say(text, pri = 1) {
      if (!SP || !set.sound || !set.announcer || paused || !text) return false;
      const now = Date.now();
      if (now < sayUntil && pri <= sayPri) return false;
      if (now < sayUntil) SP.cancel();
      if (sayVoice === undefined) { const vs = SP.getVoices ? SP.getVoices() : []; sayVoice = vs.find((v) => /^en[-_]GB/i.test(v.lang)) || vs.find((v) => /^en/i.test(v.lang)) || null; if (!vs.length) sayVoice = undefined; }
      const u = new SpeechSynthesisUtterance(text); if (sayVoice) u.voice = sayVoice;
      u.rate = 1.12; u.pitch = 0.9; u.volume = Math.max(0, Math.min(1, set.volume * 1.3));
      SP.speak(u); sayUntil = now + 900 + text.length * 70; sayPri = pri;
      return true;
    }
    // The crowd: shaped noise. A cheer swells and fades, a gasp is a sharp intake, an "ooh" rises and falls.
    function crowd(kind) {
      if (!nodes) return;
      if (kind === "cheer") { burst("bandpass", 500, 1400, 1.8, 0.16, "amb", 0.6); burst("bandpass", 900, 2200, 1.4, 0.1, "amb", 0.9, 0.15); }
      else if (kind === "gasp") { burst("highpass", 2600, 1200, 0.35, 0.14, "amb", 0.7); burst("bandpass", 700, 400, 0.6, 0.08, "amb", 1.2, 0.08); }
      else if (kind === "ooh") { burst("bandpass", 380, 760, 0.5, 0.1, "amb", 4, 0); burst("bandpass", 760, 340, 0.8, 0.1, "amb", 4, 0.45); }
    }
    // Menu sounds: each action has its own.
    function ui(kind) {
      if (!nodes) return;
      if (kind === "confirm") { blip(880, 0.06, "square", 0.08); blip(1320, 0.09, "square", 0.07, null, "sfx", 0.06); }
      else if (kind === "back") { blip(700, 0.06, "square", 0.07); blip(470, 0.09, "square", 0.06, null, "sfx", 0.05); }
      else if (kind === "buy") { blip(1568, 0.07, "triangle", 0.14); blip(2093, 0.18, "triangle", 0.14, null, "sfx", 0.08); burst("highpass", 6000, 9000, 0.12, 0.06, "sfx", 1, 0.08); }
      else if (kind === "error") { blip(150, 0.16, "sawtooth", 0.1); blip(140, 0.16, "sawtooth", 0.1, null, "sfx", 0.18); }
      else if (kind === "unlock") [523, 659, 784, 1047, 1319].forEach((f, i) => blip(f, 0.22, "triangle", 0.12, null, "sfx", i * 0.07));
      else if (kind === "achievement") { [784, 988, 1175].forEach((f, i) => blip(f, 0.16, "square", 0.07, null, "sfx", i * 0.09)); blip(1568, 0.5, "triangle", 0.14, null, "sfx", 0.3); }
    }
    const api = {
      unlock: safe(() => { init(); if (ac.state === "suspended") ac.resume(); }),
      settings: safe((s) => { set = { ...set, ...s }; if (SP && (!set.sound || !set.announcer)) { SP.cancel(); sayUntil = 0; } apply(); }),
      voice: safe((shape, own) => setVoice(shape, own)),
      // p: { speed, top, slip, boost, on, thr, turbo (0..1 of the car's turbo), gear and rpm (drag: real gears), wet, tunnel, crowd }
      update: safe((p) => {
        if (!nodes) return;
        const t = ac.currentTime;
        if (!p) {
          for (const g of [nodes.eg.gain, nodes.tyre.g.gain, nodes.nitro.g.gain, nodes.twg.gain, nodes.crowd.g.gain, nodes.rain.g.gain, nodes.srg.gain]) g.setTargetAtTime(0, t, 0.1);
          return;
        }
        const V = voice, r = Math.min(1.2, p.speed / Math.max(300, p.top));
        // gears: the real ones in a drag race; otherwise the revs climb through the voice's gears as speed builds
        let gear, within;
        if (p.gear !== undefined) { gear = p.gear; within = Math.min(1, p.rpm || 0); }
        else { const g = r * V.gears; gear = Math.min(V.gears - 1, Math.floor(g)); within = g - gear; }
        if (gear !== lastGear) { if (gear > lastGear) { shiftDip = 0.12; blip(V.idle * 0.8, 0.05, "square", 0.05); } lastGear = gear; }
        shiftDip = Math.max(0, shiftDip - 1 / 60);
        const f = V.idle + V.span * (0.25 + 0.75 * within) * (1 + gear * 0.04);
        nodes.o1.frequency.setTargetAtTime(f, t, 0.03); nodes.o2.frequency.setTargetAtTime(f * (V.ratio || 0.5), t, 0.03); nodes.o3.frequency.setTargetAtTime(f / 4, t, 0.03);
        nodes.lfo2.frequency.setTargetAtTime(Math.max(3, f / 5), t, 0.05); nodes.lope.gain.setTargetAtTime((V.lope || 0) * 0.6 * Math.max(0, 1 - r * 1.6), t, 0.08);
        nodes.lp.frequency.setTargetAtTime(350 + V.cut * (0.25 + 0.75 * Math.min(1, r)) * (p.thr === false ? 0.6 : 1), t, 0.05);
        nodes.eg.gain.setTargetAtTime((V.electric ? 0.012 : (0.05 + 0.1 * Math.min(1, r)) * (shiftDip > 0 ? 0.35 : 1)) * (p.thr === false ? 0.75 : 1), t, 0.03);
        nodes.tyre.g.gain.setTargetAtTime(p.on && p.slip > 90 ? Math.min(0.12, (p.slip - 90) / 900) : 0, t, 0.04);
        nodes.nitro.g.gain.setTargetAtTime(p.boost ? 0.09 : 0, t, 0.06);
        // turbo: whistles as it spools, blows off when you lift
        const tb = p.turbo || 0;
        spool = Math.max(0, Math.min(1, spool + (p.thr ? 0.035 : -0.08)));
        // a supercharger whines with the revs; a turbo whistles with the boost
        nodes.tw.frequency.setTargetAtTime(V.electric ? 600 + 5200 * Math.min(1, r) : V.sc ? 1800 + 3000 * within : 1600 + 2400 * spool, t, 0.05);
        nodes.twg.gain.setTargetAtTime(V.sc ? V.sc * Math.min(1, r * 1.4) : tb > 0 ? 0.012 * tb * spool * (p.thr ? 1 : 0.3) : V.whine ? V.whine * Math.min(1, r) : 0, t, 0.05);
        if ((tb > 0 || V.whoosh) && lastThr && !p.thr && spool > 0.5) burst("bandpass", 3800, 900, 0.35, 0.12 * Math.min(1, Math.max(tb, 0.25) * 2), "sfx", 2);
        lastThr = !!p.thr;
        // the world around you
        nodes.crowd.g.gain.setTargetAtTime(0.05 * Math.min(1, p.crowd || 0), t, 0.3);
        nodes.rain.g.gain.setTargetAtTime(p.tunnel ? 0 : 0.035 * Math.min(1, p.wet || 0), t, 0.3);
      }),
      raceStart: safe(() => { mood = "race"; intensity = 1; lastGear = 0; apply(); }),
      idle: safe(() => { mood = "menu"; intensity = 0; apply(); }),
      // mood: "race" or "pursuit"; level 1 normal, 2 the final lap or a hot pursuit
      music: safe((m, level) => { if (m) mood = m; if (level !== undefined) intensity = level; apply(); }),
      beep: safe((n) => blip(n >= 5 ? 660 : 440, 0.16, "square", 0.18)),
      go: safe(() => { blip(880, 0.45, "square", 0.22); burst("bandpass", 700, 500, 1.6, 0.12, "amb", 0.7); }),   // the crowd roars
      lap: safe(() => { blip(660, 0.1, "triangle", 0.15); blip(990, 0.14, "triangle", 0.15, null, "sfx", 0.11); }),
      impact: safe((v) => { blip(120, 0.18, "sawtooth", Math.min(0.4, v / 600), 40); burst("lowpass", 2400, 300, 0.2, Math.min(0.3, v / 800)); }),
      pop: safe(() => { blip(70, 0.07, "square", 0.22, 40); burst("bandpass", 1600, 500, 0.08, 0.18, "sfx", 1.5); }),
      whoosh: safe(() => burst("bandpass", 600, 2600, 0.45, 0.16, "sfx", 1.2)),
      shift: safe(() => blip(220, 0.04, "square", 0.08)),
      siren: safe((level) => { if (!nodes) return; const t = ac.currentTime; nodes.srg.gain.setTargetAtTime(set.sound ? 0.05 * Math.max(0, Math.min(1, level)) : 0, t, 0.15); nodes.lfo.frequency.setTargetAtTime(level > 0.7 ? 1.6 : 0.42, t, 0.5); }),
      radio: safe(() => {   // a squelch, a burst of garbled voice, a squelch
        blip(1400, 0.04, "square", 0.05, null, "amb");
        for (let i = 0; i < 6; i++) burst("bandpass", 900 + Math.random() * 900, 700 + Math.random() * 500, 0.09, 0.07, "amb", 5, 0.06 + i * 0.1);
        blip(1100, 0.05, "square", 0.05, null, "amb", 0.7);
      }),
      finish: safe((win) => { const notes = win ? [523, 659, 784, 1047] : [523, 494, 440]; notes.forEach((f, i) => blip(f, 0.35, "triangle", 0.2, null, "sfx", i * 0.14)); if (win) burst("bandpass", 700, 500, 2.2, 0.14, "amb", 0.7); }),
      click: safe(() => blip(1200, 0.05, "square", 0.08)),
      say: safe((text, pri) => say(text, pri)),
      canSpeak: !!SP,
      crowd: safe((k) => crowd(k)),
      ui: safe((k) => ui(k)),
      pause: safe((p) => {
        paused = p; if (p && SP) { SP.cancel(); sayUntil = 0; }
        if (p && nodes) { const t = ac.currentTime; for (const g of [nodes.eg.gain, nodes.tyre.g.gain, nodes.nitro.g.gain, nodes.twg.gain, nodes.srg.gain, nodes.crowd.g.gain, nodes.rain.g.gain]) g.setTargetAtTime(0, t, 0.05); }
      }),
      stop: safe(() => { if (SP) SP.cancel(); if (musicTimer) clearInterval(musicTimer); musicTimer = null; if (ac) ac.close(); ac = null; nodes = null; }),
      get ready() { return !!(ac && ac.state === "running"); },
    };
    return api;
  }
  const api = { create, VOICES };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.KerbsideAudio = api;
})(typeof self !== "undefined" ? self : globalThis);
