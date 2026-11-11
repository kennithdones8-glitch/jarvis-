"use strict";
// Kerbside Grand Prix: the game's menus and flow, drawn inside the race stage (racer.js) as overlay screens. Main
// menu, career headquarters, story dialogue and choices, the world map with event discovery, the garage (cars,
// upgrades, looks), championships, Quick Race, Free Play, results, profile, achievements and settings (including
// save export and import). Progress lives in KerbsideCareer and is saved to this browser after every change.
(function (root) {
  const D = root.KerbsideData, C = root.KerbsideCareer, R = root.JarvisRacer;
  const doc = root.document;
  const fmt = (s) => R.fmt(s), money = (v) => "₭" + Math.round(v).toLocaleString();   // ₭: Kerbside credits
  const uid = () => (root.crypto && root.crypto.randomUUID ? root.crypto.randomUUID() : Date.now().toString(36) + Math.random().toString(36).slice(2));
  const el = (tag, cls, ...kids) => {
    const e = doc.createElement(tag);
    if (cls) e.className = cls;
    for (const k of kids.flat()) if (k !== null && k !== undefined && k !== false) e.append(k instanceof root.Node ? k : String(k));
    return e;
  };
  const MODE_NAME = Object.fromEntries(Object.entries(D.MODES).map(([k, v]) => [k, v.name]));
  const TOD = { day: "Day", dawn: "Dawn", dusk: "Dusk", night: "Night" }, WX = { dry: "Dry", rain: "Rain", fog: "Fog" };
  const LAPLESS = ["pursuit", "drag", "delivery"];
  const SOLO_NOTE = { drift: "Just you and the clock. Slide for points.", pursuit: "Just you and the Port Kerbside Police.", delivery: "Just you, the clock and the cargo." };

  function attach(view) {
    const store = (() => { try { const s = root.localStorage; s.getItem("x"); return s; } catch { const m = {}; return { getItem: (k) => (k in m ? m[k] : null), setItem: (k, v) => { m[k] = String(v); }, removeItem: (k) => { delete m[k]; } }; } })();
    const loaded = C.load(store);
    let save = loaded.save, screen = null, history = [], previewRaf = 0, alive = true;
    const audio = root.KerbsideAudio ? root.KerbsideAudio.create(save.settings) : null;
    if (audio) view.setAudio(audio);
    view.applySettings(save.settings);
    const toastBox = el("div", "race-toasts"); toastBox.setAttribute("aria-live", "polite"); view.stage.append(toastBox);
    function toast(text, kind) {
      const t = el("div", "race-toast" + (kind ? " " + kind : ""), text); toastBox.append(t);
      setTimeout(() => t.remove(), 4200);
    }
    function persist() {
      const r = C.persist(store, save);
      if (!r.ok) toast("Couldn't save to this browser (storage blocked or full). Export your save from Settings to keep a copy.", "warn");
      else if (r.trimmed) toast("Storage was full, so some ghost laps were dropped to keep your progress.", "warn");
    }
    if (loaded.migrated || loaded.fresh || loaded.notes.length) persist();
    for (const n of loaded.notes) toast(n, "info");
    // one gesture unlocks sound for the whole visit
    const unlock = () => { if (audio) audio.unlock(); };
    view.stage.addEventListener("pointerdown", unlock, { once: true });
    view.stage.addEventListener("keydown", unlock, { once: true });

    // ---------------------------------------------------------------- helpers
    const btn = (label, fn, cls = "", attrs = {}) => {
      const b = el("button", "race-go" + (cls ? " " + cls : ""), label); b.type = "button";
      for (const [k, v] of Object.entries(attrs)) b.setAttribute(k, v);
      b.addEventListener("click", (e) => { if (audio) audio.click(); fn(e); });
      return b;
    };
    const chip = (text, cls = "") => el("span", "race-tag" + (cls ? " " + cls : ""), text);
    const swatch = (color) => { const s = el("span", "race-sw"); s.style.background = color; return s; };
    function show(fn, opts = {}) {
      cancelAnimationFrame(previewRaf);
      if (screen && !opts.replace && screen !== fn) history.push(screen);
      screen = fn;
      const node = fn();
      view.overlay(node, true);
    }
    function back() { const prev = history.pop(); if (prev) { screen = null; show(prev, { replace: true }); screen = prev; } else show(mainMenu, { replace: true }); }
    function frame(title, eyebrow, body, opts = {}) {
      const head = el("div", "race-menu-h", el("div", "", eyebrow ? el("p", "race-eyebrow", eyebrow) : null, opts.hero ? wordmark() : el("h3", "race-h", title)),
        opts.noBack ? null : btn("Back", () => back(), "alt small", { "aria-label": "Back" }));
      const box = el("div", "race-menu" + (opts.hero ? " hero" : ""), head, ...[].concat(body));
      box.addEventListener("keydown", (e) => { if (e.key === "Escape" && !opts.noBack) { e.stopPropagation(); back(); } });
      return box;
    }
    // The title wordmark: KERBSIDE in heavy italic, GRAND PRIX on a gold chevron band.
    const wordmark = () => el("h3", "race-wordmark", el("span", "k", "Kerbside"), el("span", "gp", "Grand Prix"));
    const wallet = () => el("p", "race-wallet", chip(`Level ${C.level(save.xp)}`), chip(money(save.money), "gold"), chip(`${save.rep} rep · ${C.repTitle(save)}`));

    // ---------------------------------------------------------------- main menu
    function mainMenu() {
      history = [];
      const ch = D.CHAPTERS.find((c) => c.id === save.story.chapter), next = C.nextMission(save);
      view.backdrop(D.DISTRICTS[ch ? ch.district : "park"].track, "dusk");
      view.status("Kerbside Grand Prix: pick a mode.");
      const career = save.story.ended ? "Career: champion. Free roam" : next ? `Career · Chapter ${save.story.chapter}: ${ch.title}` : "Career";
      const hero = el("canvas", "race-hero"); hero.width = 720; hero.height = 400; hero.setAttribute("aria-hidden", "true");
      startPreview(hero, save.garage.current, save.garage.owned[save.garage.current], true);
      return frame("Kerbside Grand Prix", `${save.profile.name} · ${D.CARS[save.garage.current].name}`, [hero,
        wallet(),
        el("div", "race-grid2",
          btn(career, () => show(hq), "", { "data-autofocus": "" }),
          btn("World map", () => show(worldMap)),
          btn("Quick race vs JARVIS", () => show(quickRace), "alt"),
          btn("Police pursuit", () => show(pursuitScreen), "alt"),
          btn("Championships and tournaments", () => show(champs), "alt"),
          btn("Free play", () => show(freePlay), "alt"),
          btn("Garage", () => show(garage), "alt"),
          btn("Profile and stats", () => show(profile), "alt"),
          btn("Achievements", () => show(achievements), "alt"),
          btn("Settings", () => show(settings), "alt")),
        el("p", "race-note", "Arrow keys or WASD to drive, Space for nitro, P to pause. On a phone or iPad, use the pads.")], { noBack: true, hero: true });
    }

    // ---------------------------------------------------------------- career HQ
    function hq() {
      const next = C.nextMission(save), chs = C.missions(save);
      view.status("Career headquarters.");
      const nextCard = next ? missionCard(next, true) : el("div", "race-panel", el("p", "race-note", save.story.ended
        ? "You're the Kerbside champion. Every district and event is open: replay missions, chase medals, win the championships."
        : "Chapter complete. Check the world map."));
      const chapters = el("div", "race-chapters", ...chs.map((c) => el("details", "race-chapter" + (c.state === "current" ? " current" : ""),
        el("summary", "", el("b", "", `Chapter ${c.id}: ${c.title}`), " ", chip(c.state === "done" ? "Done" : c.state === "current" ? "Now" : "Locked", c.state)),
        el("p", "race-note", c.blurb),
        el("ul", "race-list", ...c.missions.map((m) => el("li", "race-li " + m.state, el("span", "", (m.state === "done" ? "✓ " : m.state === "available" ? "▸ " : "· ") + m.title),
          el("span", "race-sub", `${MODE_NAME[m.mode]} · ${R.TRACKS[m.track].name}`),
          m.state !== "locked" ? btn(m.state === "done" ? "Replay" : "Race", () => brief({ kind: "story", event: m }), "small" + (m.state === "done" ? " alt" : "")) : null))))));
      chapters.querySelector(".race-chapter.current")?.setAttribute("open", "");
      const rivals = Object.entries(save.rivals).filter(([id]) => !["jarvis", "bleu", "whitlock"].includes(id));
      return frame("Career headquarters", `${save.team.name} · Chapter ${Math.min(save.story.chapter, D.CHAPTERS.length)}${save.ng ? ` · New Game+ ${save.ng}` : ""}`, [wallet(), nextCard,
        el("div", "race-grid2", btn("World map", () => show(worldMap), "alt"), btn("Garage", () => show(garage), "alt"), btn("Team and sponsors", () => show(teamScreen), "alt")),
        save.sponsor ? el("p", "race-note", `Sponsor: ${D.SPONSORS[save.sponsor].name}. ${D.SPONSORS[save.sponsor].blurb}`) : null,
        chapters,
        mattersPanel(), storiesPanel(), crewPanel(), rivalPanel()]);
    }
    // Crew matters: two of your people disagree, and you settle it. Each stays settled the way you chose.
    function mattersPanel() {
      const list = C.matters(save);
      if (!list.length) return null;
      return el("div", "race-panel mission", el("p", "race-lbl", "Garage matters"), ...list.map((M) => el("div", "race-matter",
        el("div", "race-matterfaces", ...M.who.map((w) => portraitOf(w, 64))),
        el("div", "", el("b", "", M.who.map((w) => ((D.CAST[w] || {}).name || w).split(" ")[0]).join(" and ")), el("p", "race-note", M.prompt),
          el("div", "race-choices", ...M.options.map((o, i) => btn(o.label, () => {
            const r = C.settle(save, M.id, i);
            if (!r.ok) { toast(r.error, "warn"); return; }
            persist(); toast(r.text, "info"); show(hq, { replace: true });
          }, "small alt")))))));
    }
    // Character stories: one card per person, their next mission or what opens it.
    function storiesPanel() {
      const list = C.arcs(save);
      return el("div", "race-panel", el("p", "race-lbl", "Character stories"), el("div", "race-stories", ...list.map((a) => {
        const face = portraitOf(a.who, 96), state = a.complete ? "Complete" : a.open ? `${a.done} of ${a.total}` : a.why;
        return el("div", "race-story" + (a.open && !a.complete ? "" : " dim"), face, el("div", "", el("b", "", a.title), el("span", "race-sub", `${(D.CAST[a.who] || {}).name || a.who} · ${state}`),
          el("p", "race-note", a.blurb), a.next ? btn(`Race: ${a.next.title}`, () => brief({ kind: "arc", event: a.next }), "small") : null));
      })));
    }
    // ---------------------------------------------------------------- team, sponsors, New Game+
    function teamLevelPanel() {
      const lv = C.teamLevel(save), bar = el("div", "race-bar"), i = el("i", "up"), nx = lv.next;
      i.style.width = (nx ? Math.round(Math.min(1, (save.team.rep - lv.rep) / (nx.rep - lv.rep)) * 100) : 100) + "%"; bar.append(i);
      return el("div", "race-panel", el("p", "race-lbl", `${save.team.name}: ${lv.name}`),
        el("div", "race-barrow", el("span", "race-lbl", `Team reputation ${save.team.rep}`), bar, el("span", "race-delta", nx ? `${nx.rep} for ${nx.name}` : "Top level")),
        el("ul", "race-list", ...D.TEAM_LEVELS.slice(1).map((L, k) => el("li", "race-li" + (k + 1 <= lv.i ? " done" : " locked"), el("span", "", (k + 1 <= lv.i ? "✓ " : "") + L.name), el("span", "race-sub", `${L.rep} team reputation · ${L.perk}`)))),
        el("p", "race-note", "Team reputation comes from wins (+2), podiums (+1), sponsor contracts and team championship seasons."));
    }
    function teamScreen() {
      const T = save.team, name = el("input", "race-select"); name.id = "t-name"; name.maxLength = 24; name.value = T.name; name.autocomplete = "off";
      const sw = (key) => el("div", "race-swatches", ...D.LOOKS.paint.map((c) => { const b = el("button", "race-swbtn" + (T[key] === c ? " on" : "")); b.type = "button"; b.style.background = c;
        b.setAttribute("aria-label", (key === "color" ? "Team colour " : "Second team colour ") + c); b.addEventListener("click", () => { C.setTeam(save, { [key]: c }); persist(); show(teamScreen, { replace: true }); }); return b; }));
      const table = C.teamTable(save);
      const active = save.contracts.map((c) => {
        const k = D.CONTRACTS[c.id], bar = el("div", "race-bar"), i = el("i", "up"); i.style.width = Math.round(Math.min(1, c.progress / k.goal.n) * 100) + "%"; bar.append(i);
        return el("li", "race-li", el("span", "", `${k.sponsor}: ${k.title}`), el("span", "race-sub", `${k.blurb} ${c.progress.toLocaleString()} of ${k.goal.n.toLocaleString()} · ${c.left} race${c.left === 1 ? "" : "s"} left · pays ${money(k.pay)}`), bar,
          confirmBtn("Walk away", "Walk away (−5 rep)?", () => { C.dropContract(save, c.id); persist(); show(teamScreen, { replace: true }); }));
      });
      const offers = C.contractOffers(save).map((k) => el("li", "race-li", el("span", "", `${k.sponsor}: ${k.title}`), el("span", "race-sub", `${k.blurb} Pays ${money(k.pay)} and ${k.rep} rep.`),
        save.contracts.length < C.contractSlots(save) ? btn("Sign", () => { const r = C.signContract(save, k.id); if (!r.ok) return toast(r.error, "warn"); persist(); toast(`Signed with ${k.sponsor}.`, "info"); show(teamScreen, { replace: true }); }, "small") : null));
      const locked = Object.values(D.CONTRACTS).filter((k) => k.minRep > save.rep).length;
      const ng = save.story.ended ? el("div", "race-panel", el("p", "race-lbl", `New Game+${save.ng ? ` (you're on cycle ${save.ng})` : ""}`),
        el("p", "race-note", "Start the story again from chapter 1. You keep your cars and upgrades, money, level, crew, team, records, medals, best laps, ghosts, endings and achievements. The story, districts, rivals' memory, the map, championships in progress and contracts start over. The field is 1% quicker and prizes are 25% bigger for each cycle."),
        confirmBtn("Start New Game+", "Start New Game+? (a copy of this save is kept)", () => {
          const r = C.newGamePlus(save); if (!r.ok) return toast(r.error, "warn");
          try { store.setItem(C.KEY + "-before-ngplus", C.exportSave(save)); } catch { /* best effort, like a reset */ }
          save = r.save; persist(); r.achievements.forEach((a) => toast(`Achievement unlocked: ${D.ACHIEVEMENTS[a].name}${D.ACH_REWARDS[a] ? " · reward: " + D.ACH_REWARDS[a].text : ""}`, "gold")); toast(`New Game+ ${save.ng}: chapter 1 again.`, "gold"); show(hq, { replace: true });
        })) : null;
      return frame("Team and sponsors", `${T.name} · season ${T.season}`, [wallet(),
        el("div", "race-fields", el("label", "race-field", el("span", "race-lbl", "Team name"), name),
          btn("Save name", () => { const r = C.setTeam(save, { name: name.value }); if (!r.ok) return toast(r.error, "warn"); persist(); toast("Team name saved.", "info"); show(teamScreen, { replace: true }); }, "small")),
        el("p", "race-lbl", "Team colour"), sw("color"), el("p", "race-lbl", "Second colour"), sw("color2"),
        btn("Paint my car in team colours", () => { C.teamLivery(save); persist(); toast("Your car wears the team colours.", "info"); }, "alt small"),
        teamLevelPanel(),
        el("p", "race-lbl", `Team championship · season ${T.season}, race day ${T.days} of ${D.TEAM_SEASON}`),
        el("table", "race-classif", el("tbody", "", ...table.map((r, i) => el("tr", r.you ? "me" : "", el("td", "", `P${i + 1}`), el("td", "", r.name), el("td", "", `${r.points} pts`))))),
        el("p", "race-note", `Your finishes score ${D.POINTS.join("/")} (team races: the team's points). Prizes at the end of a season: ${D.SEASON_PRIZE.filter(Boolean).map(money).join(", ")} for the top three. Titles won: ${T.titles}.`),
        el("p", "race-lbl", `Sponsor contracts (${save.contracts.length} of ${C.contractSlots(save)})`),
        active.length ? el("ul", "race-list", ...active) : el("p", "race-note", "No contracts signed. Quick races and free play don't count toward them."),
        offers.length ? el("ul", "race-list", ...offers) : null,
        locked ? el("p", "race-note", `${locked} more sponsor${locked > 1 ? "s want" : " wants"} more reputation first.`) : null,
        ng]);
    }
    const STAGE = { feud: ["Feud", "bad"], rival: ["Rival", ""], respect: ["Respect", "current"], ally: ["Ally", "done"], stranger: ["Not met", "locked"] };
    function crewPanel() {
      return el("div", "race-panel", el("p", "race-lbl", "Your crew"), el("ul", "race-list", ...Object.entries(D.CREW).map(([id, c]) => {
        const m = save.crew.members[id], on = m && m.hired, bar = el("span", "race-pips", ...[0, 2, 4, 6, 8].map((v) => el("i", on && m.loyalty > v ? "on" : "")));
        return el("li", "race-li" + (on ? "" : " locked"), el("span", "", `${c.name} · ${c.role} `, on ? bar : null),
          el("span", "race-sub", on ? `${c.perk}${m.level > 1 ? ` · level ${m.level}` : ""}` : `Not yet with you. ${c.recruit}`), on ? chip(`Loyalty ${m.loyalty}`, "small") : null);
      })));
    }
    function rivalPanel() {
      const ids = Object.keys(D.RIVAL_LINES).filter((id) => save.rivals[id]);
      if (!ids.length) return null;
      return el("div", "race-panel", el("p", "race-lbl", "Rivals: what they remember"), el("ul", "race-list", ...ids.map((id) => {
        const r = save.rivals[id], st = C.rivalStage(save, id), [name, cls] = STAGE[st];
        const mem = [`${r.wins}–${r.losses}`, r.passedThem ? `you've passed them ${r.passedThem}×` : null, r.passedYou ? `they've passed you ${r.passedYou}×` : null,
          r.youHit ? `you hit them ${r.youHit}×` : null, r.theyHit ? `they hit you ${r.theyHit}×` : null, r.close ? `${r.close} photo finish${r.close > 1 ? "es" : ""}` : null].filter(Boolean).join(" · ");
        return el("li", "race-li", el("span", "", D.DRIVERS[id].name), el("span", "race-sub", mem), chip(name, cls));
      })));
    }
    function missionCard(m, primary) {
      return el("div", "race-panel mission", el("p", "race-eyebrow", `Story · Chapter ${m.chapter}`), el("b", "race-title", m.title),
        el("p", "race-note", `${MODE_NAME[m.mode]} · ${R.TRACKS[m.track].name} · ${TOD[m.time || "day"]}, ${WX[m.weather || "dry"].toLowerCase()} · ${C.goalText(m.goal)}`),
        btn(primary ? "Race" : "Open", () => brief({ kind: "story", event: m }), "", primary ? { "data-autofocus": "" } : {}));
    }

    // ---------------------------------------------------------------- briefing → choice → dialogue → race
    function brief(ctx) {
      show(() => {
        const ev = ctx.event, cfg = C.config(save, ev, ctx.kind), car = D.CARS[save.garage.current];
        view.backdrop(ev.track, ev.time || "day", ev.weather || "dry", cfg.field.length ? cfg.field : undefined);
        const field = cfg.field.length ? el("div", "race-field-list", ...cfg.field.map((d) => el("span", "race-driver", swatch(d.look.paint), `${d.name}`, chip(d.team === "you" ? "your team" : d.personality, "small"))))
          : el("p", "race-note", SOLO_NOTE[ev.mode] || "Just you, the clock and your ghost.");
        const allowed = C.carAllowed(save, ev), stakes = ctx.kind === "rival" ? C.wagerOptions(save) : [];
        const wagerSel = stakes.length > 1 ? select("b-wager", "Wager (win pays double)", ctx.wager || 0, stakes.map((v) => [v, v ? money(v) : "No bet"]), (v) => { ctx.wager = Number(v); }) : null;
        const medalLine = ev.mode === "timetrial" ? el("p", "race-note", `Medals: gold ${fmt(D.PAR[ev.track] * cfg.laps)}, silver ${fmt(D.PAR[ev.track] * cfg.laps * 1.05)}, bronze ${fmt(D.PAR[ev.track] * cfg.laps * 1.12)}.`) : null;
        return frame(ev.title || "Race", `${{ story: "Story mission", arc: "Character story", champ: "Championship", side: "Event", rival: "Rival challenge", tourney: "Tournament", pursuit: "Police pursuit" }[ctx.kind] || "Race"} · ${R.TRACKS[cfg.track].name}`, [
          el("div", "race-tags", chip(MODE_NAME[ev.mode]), LAPLESS.includes(ev.mode) ? null : chip(`${cfg.laps} lap${cfg.laps > 1 ? "s" : ""}`), chip(TOD[cfg.time]), chip(WX[cfg.weather]),
            cfg.weatherChange ? chip(`then ${WX[cfg.weatherChange.to].toLowerCase()}`) : null, ev.cls ? chip(`Class ${ev.cls} only`, allowed.ok ? "" : "bad") : null, chip(`AI ${cfg.level}`)),
          el("p", "race-note", D.MODES[ev.mode] ? D.MODES[ev.mode].blurb : ""),
          el("p", "race-goal", "Goal: " + (ctx.kind === "quick" || ctx.kind === "free" ? "win" : C.goalText(ev.goal))), medalLine,
          el("p", "race-lbl", "Field"), field,
          el("p", "race-note", `Your car: ${car.name} (class ${car.cls}). ${save.best[ev.track] && !LAPLESS.includes(ev.mode) ? "Your best lap here: " + fmt(save.best[ev.track]) + "." : ""}`),
          (() => { const mine = C.rating(cfg.player.spec), rec = C.recommended(save, ev), gap = mine - rec;
            return el("p", "race-goal " + (gap < -60 ? "bad" : ""), `Rating ${mine} · ${cfg.field.length ? "the field averages" : "suggested"} ${rec}${gap < -60 ? ". You're well short: an upgrade or a quicker car would help." : gap > 80 ? ". You have the faster car." : "."}`); })(),
          allowed.ok ? null : el("p", "race-goal bad", allowed.why + (allowed.owned.length ? ` You own: ${allowed.owned.map((id) => D.CARS[id].name).join(", ")}. Switch in the garage.` : " Buy one in the garage.")),
          wagerSel, ev.mode === "drag" ? el("p", "race-note", "Hold the throttle during the lights to rev (launch in the green), then E or the SHIFT pad to change up near the top of the revs.") : null,
          ev.mode === "endurance" ? el("p", "race-note", "Tyres wear as you go. Stop in the yellow pit box just before the line for fresh tyres and repairs (about 2.5 s).") : null,
          el("div", "race-grid2", allowed.ok ? btn("Start", () => go(ctx), "", { "data-autofocus": "" }) : null, btn("Garage", () => show(garage), allowed.ok ? "alt" : "", allowed.ok ? {} : { "data-autofocus": "" }))]);
      });
    }
    function go(ctx) {
      const m = ctx.event;
      if ((ctx.kind === "story" || ctx.kind === "arc") && C.needsChoice(save, m)) return show(() => choiceScreen(m, () => intro(ctx)), { replace: true });
      intro(ctx);
    }
    function intro(ctx) {
      const lines = ctx.kind === "story" || ctx.kind === "arc" ? C.lines(save, ctx.event.intro) : [];
      if (lines.length) dialogue(lines, () => run(ctx), ctx.kind === "story" || ctx.kind === "arc" ? ctx.event.scene : null); else run(ctx);
    }
    // A drawn portrait: head and shoulders in the speaker's colours, with their hair, jacket and one detail.
    function portraitOf(who, size = 160) {
      const c = D.CAST[who] || D.CAST.you, F = c.face || { skin: "#c68863", hair: "#2a1d14", style: "short", jacket: c.color || "#888888", extra: "" };
      const cv = el("canvas", "race-face"); cv.width = cv.height = size; cv.setAttribute("aria-hidden", "true");
      const g = cv.getContext("2d"), s = size / 160, sh = (hex, f) => { const n = parseInt(hex.slice(1), 16), m = (v) => Math.max(0, Math.min(255, Math.round(v * f))); return `rgb(${m(n >> 16)},${m((n >> 8) & 255)},${m(n & 255)})`; };
      g.scale(s, s);
      const bg = g.createRadialGradient(80, 60, 10, 80, 80, 90); bg.addColorStop(0, sh(c.color || "#888888", 0.75)); bg.addColorStop(1, sh(c.color || "#888888", 0.22));
      g.fillStyle = bg; g.beginPath(); g.arc(80, 80, 80, 0, 7); g.fill();
      g.save(); g.beginPath(); g.arc(80, 80, 79, 0, 7); g.clip();
      const back = { long: true, braid: true, bob: true, puff: true }[F.style];
      if (back) { g.fillStyle = F.hair; g.beginPath(); F.style === "puff" ? g.arc(80, 58, 44, 0, 7) : g.ellipse(80, 82, F.style === "bob" ? 38 : 40, F.style === "long" ? 56 : 44, 0, 0, 7); g.fill(); }
      // shoulders and jacket
      g.fillStyle = sh(F.jacket, 1); g.beginPath(); g.ellipse(80, 168, 66, 44, 0, 0, 7); g.fill();
      g.fillStyle = sh(F.jacket, 0.7); g.beginPath(); g.moveTo(58, 132); g.lineTo(80, 158); g.lineTo(102, 132); g.lineTo(96, 128); g.lineTo(80, 146); g.lineTo(64, 128); g.closePath(); g.fill();
      g.fillStyle = sh(F.skin, 0.85); g.fillRect(70, 104, 20, 28);   // neck
      // head
      const hg = g.createLinearGradient(52, 0, 108, 0); hg.addColorStop(0, sh(F.skin, 1.08)); hg.addColorStop(1, sh(F.skin, 0.82));
      g.fillStyle = hg; g.beginPath(); g.ellipse(80, 78, 27, 33, 0, 0, 7); g.fill();
      g.fillStyle = sh(F.skin, 0.9); g.beginPath(); g.ellipse(53, 82, 4, 7, 0, 0, 7); g.ellipse(107, 82, 4, 7, 0, 0, 7); g.fill();   // ears
      // face
      if (F.style !== "visor") {
        g.fillStyle = "#1a1210"; g.beginPath(); g.ellipse(70, 78, 3.2, 3.8, 0, 0, 7); g.ellipse(90, 78, 3.2, 3.8, 0, 0, 7); g.fill();
        g.fillStyle = "rgba(255,255,255,0.8)"; g.fillRect(70.5, 76, 1.4, 1.4); g.fillRect(90.5, 76, 1.4, 1.4);
        g.strokeStyle = sh(F.hair === "#e6e2da" || F.hair === "#f2f2f2" ? "#8a8070" : F.hair, 0.9); g.lineWidth = 2.4; g.beginPath(); g.moveTo(64, 70); g.lineTo(75, 69); g.moveTo(85, 69); g.lineTo(96, 70); g.stroke();
        g.strokeStyle = sh(F.skin, 0.68); g.lineWidth = 2; g.beginPath(); g.moveTo(80, 80); g.lineTo(77, 92); g.lineTo(81, 93); g.stroke();
        g.strokeStyle = sh(F.skin, 0.55); g.lineWidth = 2.2; g.beginPath(); g.moveTo(72, 101); g.quadraticCurveTo(80, 105, 88, 101); g.stroke();
      }
      // hair on top
      g.fillStyle = F.hair;
      const top = { short: () => { g.beginPath(); g.ellipse(80, 56, 28, 16, 0, Math.PI, 0); g.fill(); g.fillRect(52, 54, 6, 14); g.fillRect(102, 54, 6, 14); },
        buzz: () => { g.globalAlpha = 0.7; g.beginPath(); g.ellipse(80, 58, 27, 14, 0, Math.PI, 0); g.fill(); g.globalAlpha = 1; },
        long: () => { g.beginPath(); g.ellipse(80, 54, 30, 18, 0, Math.PI, 0); g.fill(); g.beginPath(); g.moveTo(52, 56); g.quadraticCurveTo(62, 60, 70, 50); g.lineTo(52, 50); g.fill(); },
        bob: () => { g.beginPath(); g.ellipse(80, 55, 30, 18, 0, Math.PI, 0); g.fill(); g.fillRect(50, 54, 9, 40); g.fillRect(101, 54, 9, 40); },
        bun: () => { g.beginPath(); g.ellipse(80, 54, 28, 15, 0, Math.PI, 0); g.fill(); g.beginPath(); g.arc(80, 34, 11, 0, 7); g.fill(); },
        braid: () => { g.beginPath(); g.ellipse(80, 54, 29, 16, 0, Math.PI, 0); g.fill(); for (let i = 0; i < 5; i++) { g.beginPath(); g.ellipse(106, 88 + i * 9, 5, 5.5, 0, 0, 7); g.fill(); } },
        puff: () => { g.beginPath(); g.arc(80, 50, 30, Math.PI, 0); g.fill(); },
        curly: () => { for (let i = 0; i < 9; i++) { g.beginPath(); g.arc(56 + i * 6, 52 - Math.sin(i / 8 * Math.PI) * 8, 7, 0, 7); g.fill(); } },
        slick: () => { g.beginPath(); g.ellipse(80, 55, 28, 15, 0, Math.PI, 0); g.fill(); g.strokeStyle = "rgba(255,255,255,0.35)"; g.lineWidth = 2; g.beginPath(); g.moveTo(62, 50); g.quadraticCurveTo(78, 42, 98, 48); g.stroke(); },
        messy: () => { g.beginPath(); for (let i = 0; i < 8; i++) { const x = 54 + i * 7; g.moveTo(x, 58); g.lineTo(x + 4, 36 + (i % 3) * 5); g.lineTo(x + 8, 58); } g.fill(); g.beginPath(); g.ellipse(80, 56, 27, 13, 0, Math.PI, 0); g.fill(); },
        bald: () => { g.globalAlpha = 0.9; g.fillRect(52, 64, 5, 18); g.fillRect(103, 64, 5, 18); g.globalAlpha = 1; g.fillStyle = "rgba(255,255,255,0.25)"; g.beginPath(); g.ellipse(72, 52, 9, 5, -0.4, 0, 7); g.fill(); },
        visor: () => { g.fillStyle = "#0b2a33"; rrect(g, 52, 68, 56, 18, 8); g.fill(); g.fillStyle = F.skin; g.fillRect(56, 75, 48, 3); },
      }[F.style];
      if (top) top();
      // one detail
      const X = F.extra;
      if (X === "glasses") { g.strokeStyle = "#141414"; g.lineWidth = 2.2; g.beginPath(); g.arc(70, 78, 7.5, 0, 7); g.moveTo(97.5, 78); g.arc(90, 78, 7.5, 0, 7); g.moveTo(77.5, 78); g.lineTo(82.5, 78); g.stroke(); }
      else if (X === "cap") { g.fillStyle = sh(F.jacket, 0.8); g.beginPath(); g.ellipse(80, 52, 30, 14, 0, Math.PI, 0); g.fill(); g.fillRect(80, 48, 36, 6); }
      else if (X === "headset") { g.strokeStyle = "#1a1a1a"; g.lineWidth = 4; g.beginPath(); g.arc(80, 76, 31, Math.PI * 1.05, Math.PI * 1.95); g.stroke(); g.fillStyle = "#1a1a1a"; g.fillRect(48, 76, 8, 14); g.lineWidth = 2; g.beginPath(); g.moveTo(52, 90); g.quadraticCurveTo(58, 104, 72, 103); g.stroke(); }
      else if (X === "scar") { g.strokeStyle = sh(F.skin, 0.6); g.lineWidth = 1.6; g.beginPath(); g.moveTo(93, 68); g.lineTo(99, 88); g.stroke(); }
      else if (X === "earring") { g.fillStyle = "#ffd23a"; g.beginPath(); g.arc(107, 92, 2.6, 0, 7); g.fill(); }
      else if (X === "chain") { g.strokeStyle = "#ffd23a"; g.lineWidth = 2.4; g.beginPath(); g.arc(80, 126, 18, 0.25, Math.PI - 0.25); g.stroke(); }
      else if (X === "moustache") { g.fillStyle = "#e6e2da"; g.beginPath(); g.ellipse(74, 97, 8, 3.4, 0.2, 0, 7); g.ellipse(86, 97, 8, 3.4, -0.2, 0, 7); g.fill(); }
      else if (X === "wrench") { g.save(); g.translate(118, 136); g.rotate(-0.7); g.fillStyle = "#b8bcc4"; g.fillRect(-4, -26, 8, 40); g.beginPath(); g.arc(0, -28, 9, 0, 7); g.fill(); g.fillStyle = sh(F.jacket, 1); g.fillRect(-3, -40, 6, 10); g.restore(); }
      else if (X === "helmet") { g.fillStyle = "#e9c44a"; g.beginPath(); g.arc(122, 136, 20, 0, 7); g.fill(); g.fillStyle = "#14100a"; rrect(g, 108, 128, 26, 10, 4); g.fill(); }
      else if (X === "glow") { g.globalCompositeOperation = "lighter"; const gl = g.createRadialGradient(80, 77, 2, 80, 77, 40); gl.addColorStop(0, "rgba(168,236,255,0.5)"); gl.addColorStop(1, "rgba(168,236,255,0)"); g.fillStyle = gl; g.fillRect(30, 30, 100, 100); g.globalCompositeOperation = "source-over"; }
      g.restore();
      g.strokeStyle = sh(c.color || "#888888", 1.15); g.lineWidth = 3; g.beginPath(); g.arc(80, 80, 78.5, 0, 7); g.stroke();
      return cv;
    }
    function rrect(g, x, y, w, h, r) { g.beginPath(); g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r); g.arcTo(x + w, y + h, x, y + h, r); g.arcTo(x, y + h, x, y, r); g.arcTo(x, y, x + w, y, r); g.closePath(); }
    // A conversation: the speaker's portrait lit, the person they're talking to dimmed, a name plate, and the line
    // typed out (instantly with reduced motion). A scene can set a place and point the backdrop's camera at a car.
    function dialogue(lines, done, scene) {
      let i = 0, typing = 0;
      if (scene && scene.focus) view.focus(scene.focus);
      const finish = () => { if (scene && scene.focus) view.focus(null); done(); };
      const render = () => {
        const L = lines[i], prev = lines.slice(0, i).reverse().find((x) => x.who !== L.who) || lines.slice(i + 1).find((x) => x.who !== L.who);
        const other = prev ? prev.who : L.who === "jarvis" || L.who === "you" ? null : "you";
        const speaker = el("div", "race-convo-p on", portraitOf(L.who)), listener = other ? el("div", "race-convo-p", portraitOf(other)) : null;
        const text = el("p", "race-line", ""), full = L.text;
        const reduce = root.matchMedia && root.matchMedia("(prefers-reduced-motion: reduce)").matches;
        clearInterval(typing);
        if (reduce) text.textContent = full;
        else { let n = 0; typing = setInterval(() => { n = Math.min(full.length, n + 2); text.textContent = full.slice(0, n); if (n >= full.length) clearInterval(typing); }, 16); }
        const next = () => { if (text.textContent !== full) { clearInterval(typing); text.textContent = full; return; } i++; if (i < lines.length) view.overlay(render(), true); else { clearInterval(typing); finish(); } };
        const box = frame(L.name, (scene && scene.place) || L.cast.role || "", [
          el("div", "race-convo" + (L.who === "you" ? " right" : ""), speaker, listener),
          el("div", "race-plate", el("b", "", L.name), L.cast.role ? el("span", "", L.cast.role) : null), text,
          el("div", "race-grid2", btn(i < lines.length - 1 ? "Next" : "Continue", next, "", { "data-autofocus": "" }),
            lines.length > 1 && i < lines.length - 1 ? btn("Skip", () => { clearInterval(typing); finish(); }, "alt") : null),
          el("p", "race-note", `${i + 1} of ${lines.length}`)], { noBack: true });
        return box;
      };
      view.overlay(render(), true);
    }
    function choiceScreen(m, done) {
      const ch = m.choice;
      return frame("Your call", m.title, [el("p", "race-line", ch.prompt),
        el("div", "race-stack", ...ch.options.map((o, i) => btn(o.label, () => {
          const r = C.choose(save, m.id, i); if (!r.ok) return toast(r.error, "warn"); persist();
          if (r.ok && r.consequence) toast(`This will be remembered: ${r.consequence}`, "gold");
          if (r.ok && r.lines.length) dialogue(r.lines, done); else done();
        }, "alt"))), el("p", "race-note", "Choices change what happens later: who races you, how they race, what people say and which events open.")], { noBack: true });
    }
    function run(ctx) {
      ctx.event = C.resolve(save, ctx.event);
      const cfg = C.config(save, ctx.event, ctx.kind), raceId = uid();
      if (ctx.kind === "rival") { const w = C.placeWager(save, ctx.event, ctx.wager || 0); if (!w.ok) { toast(w.error, "warn"); ctx.wager = 0; } }
      history = [mainMenu]; screen = null;   // after a race, Back always leads home rather than to stale screens
      ctx.raceId = raceId;
      save.interrupted = { title: ctx.event.title || "a race", at: Date.now() }; persist();
      view.overlay(null);
      view.start(cfg, {
        pause: () => pauseMenu(ctx),
        event: (e) => { if (e.ghost) { const g = save.ghosts[cfg.track]; if (!g || e.ghost.time < g.time) save.ghosts[cfg.track] = { time: e.ghost.time, pts: e.ghost.pts }; } },
        end: (s) => results(ctx, s),
      });
    }
    function pauseMenu(ctx) {
      view.overlay(frame("Paused", ctx.event.title || "Race", [
        el("div", "race-stack", btn("Resume", () => view.resume(), "", { "data-autofocus": "" }), btn("Restart", () => { view.quit(); run(ctx); }, "alt"),
          view.photo ? btn("Photo mode", () => view.photo(() => pauseMenu(ctx)), "alt") : null,
          btn(save.settings.sound ? "Sound: on" : "Sound: off", (e) => { save.settings.sound = !save.settings.sound; audio && audio.settings(save.settings); persist(); e.target.textContent = save.settings.sound ? "Sound: on" : "Sound: off"; }, "alt"),
          btn(save.wager ? `Quit (forfeits your ${money(save.wager.amount)} stake)` : "Quit to menu (no result)", () => { view.quit(); save.interrupted = null; save.wager = null; persist(); show(ctx.kind === "story" || ctx.kind === "arc" ? hq : ctx.kind === "pursuit" ? pursuitScreen : mainMenu, { replace: true }); }, "alt"))],
        { noBack: true }), true);
    }

    // ---------------------------------------------------------------- results
    function results(ctx, s) {
      const out = C.applyResult(save, ctx, s);
      persist();
      if (out.already) return show(mainMenu, { replace: true });
      const ev = ctx.event;
      const headline = s.pursuit ? (s.pursuit.result === "escaped" ? "Escaped" : s.pursuit.result === "busted" ? "Busted" : "Pursuit over")
        : s.delivery ? (s.delivery.delivered ? "Delivered" : "Out of time")
        : s.eliminated ? "Eliminated" : s.mode === "timetrial" ? (out.medal ? `${out.medal[0].toUpperCase() + out.medal.slice(1)} medal` : "Time trial")
        : s.mode === "drift" ? `${s.drift.toLocaleString()} points` : s.team ? (s.team.won ? `Team win · ${s.team.you}–${s.team.them}` : `Team loss · ${s.team.you}–${s.team.them}`)
        : s.place === 1 ? "Victory · P1" : `P${s.place} of ${s.of}`;
      const passLine = ctx.kind === "story" || ctx.kind === "arc" || ctx.kind === "side" || ctx.kind === "rival" || ctx.kind === "champ" || ctx.kind === "tourney"
        ? el("p", "race-goal " + (out.passed ? "ok" : "bad"), (out.passed ? "Goal met: " : "Goal missed: ") + C.goalText(ev.goal)) : null;
      const unlocks = out.unlocked.map((u) => el("li", "race-li", u.type === "district" ? `New district: ${u.name}` : u.gift ? `New car in your garage: ${u.name}` : `Car unlocked to buy: ${u.name}`));
      const ach = out.achievements.map((id) => el("li", "race-li", `Achievement: ${D.ACHIEVEMENTS[id].name}`));
      for (const id of out.achievements) toast(`Achievement unlocked: ${D.ACHIEVEMENTS[id].name}${D.ACH_REWARDS[id] ? " · reward: " + D.ACH_REWARDS[id].text : ""}`, "gold");
      const champ = out.champ ? el("div", "race-panel", el("p", "race-lbl", out.champ.done ? `${out.champ.name}: final standings` : `${out.champ.name}: standings after round ${out.champ.round}`),
        el("table", "race-classif", el("tbody", "", ...out.champ.table.map((r, i) => el("tr", r.id === "YOU" ? "me" : "", el("td", "", `P${i + 1}`), el("td", "", r.name), el("td", "", `${r.points} pts`))))),
        out.champ.done ? el("p", "race-note", `You finished P${out.champ.place}. Prize ${money(out.champ.prize)}.`) : null) : null;
      const r = view.race, order = r ? R.standings(r) : [];
      const classification = s.of > 1 && !s.pursuit && !s.delivery ? el("table", "race-classif", el("tbody", "", ...order.map((c, i) => {
        const sw = swatch((c.look && c.look.paint) || c.color);
        return el("tr", c.ai ? "" : "me", el("td", "", `P${i + 1}`), el("td", "", sw, c.ai ? c.name : save.profile.name), el("td", "", c.out ? "Out" : c.done ? (i === 0 ? fmt(c.finish) : `+${(c.finish - order[0].finish).toFixed(2)}s`) : `Lap ${Math.min(r.laps, c.laps + 1)}`));
      }))) : null;
      const cont = () => {
        if (out.ending) return show(() => endingScreen(out.ending), { replace: true });
        if (out.chapter) return show(() => chapterScreen(out.chapter), { replace: true });
        show(ctx.kind === "story" || ctx.kind === "arc" ? hq : ctx.kind === "champ" || ctx.kind === "tourney" ? champs : ctx.kind === "side" || ctx.kind === "rival" ? worldMap : ctx.kind === "pursuit" ? pursuitScreen : mainMenu, { replace: true });
      };
      const next = () => {
        if (out.choice) return show(() => choiceScreen(ev, () => cont()), { replace: true });
        cont();
      };
      const stat = (l, v, cls = "") => el("div", "race-stat", el("div", "race-lbl", l), el("div", "race-v " + cls, v));
      const earned = stat(out.fine ? "Fined" : "Earned", out.fine ? `−${money(out.fine)}` : `${money(out.money)} · ${out.xp} XP`);
      const P = s.pursuit, Dg = s.drag, Dl = s.delivery;
      const stats = P ? [stat("Heat", `${P.heat} of 5`), stat("Bounty", P.bounty.toLocaleString()), stat("Time", fmt(P.time)), stat("Units disabled", String(P.disabled)), earned]
        : Dg ? [stat("Elapsed", Dg.et ? Dg.et.toFixed(3) + " s" : "–", "best"), stat("Trap speed", `${Math.round(Dg.trap * 0.36)} km/h`), stat("Launch", `${Math.round(Dg.launch * 100)}%`), stat("Perfect shifts", `${Dg.perfect} of ${Dg.shifts}`), earned]
        : Dl ? [stat("Stops", `${Dl.reached} of ${Dl.stops}`), stat("Cargo", `${Math.round(Dl.cargo * 100)}%`), stat("Time left", Dl.delivered ? Dl.left.toFixed(1) + " s" : "–"), earned]
        : [stat("Time", s.finished ? fmt(s.total) : "–"), stat("Best lap", fmt(s.best) + (out.newBest ? " · PB" : ""), "best"), earned,
          ...(s.endurance ? [stat("Pit stops", String(s.endurance.pits))] : []), ...(s.touge ? [stat("Decided", s.touge.how === "gap" ? "Pulled clear" : "At the line")] : [])];
      const extraLines = [
        out.wager ? el("p", "race-goal " + (out.wager.won ? "ok" : "bad"), out.wager.won ? `Wager won: ${money(out.wager.amount * 2)} back.` : `Wager lost: ${money(out.wager.amount)}.`) : null,
        out.tourney ? el("p", "race-goal " + (out.tourney.out ? "bad" : "ok"), out.tourney.out ? `Out of the ${out.tourney.name} at the ${out.tourney.stage.toLowerCase()}.` : out.tourney.won ? `You won the ${out.tourney.name}: ${money(out.tourney.prize)}.` : `Through to the ${out.tourney.next.toLowerCase()}.`) : null];
      if (out.tourney && out.tourney.achievements) for (const id of out.tourney.achievements) toast(`Achievement unlocked: ${D.ACHIEVEMENTS[id].name}${D.ACH_REWARDS[id] ? " · reward: " + D.ACH_REWARDS[id].text : ""}`, "gold");
      const body = [
        el("div", "race-stats", ...stats), ...extraLines,
        out.breakdown && out.breakdown.length > 1 ? el("div", "race-panel", el("p", "race-lbl", "Prize money"), el("ul", "race-list", ...out.breakdown.map((b) => el("li", "race-li", el("span", "", b.label), el("span", "race-sub", (b.amount >= 0 ? "+" : "−") + money(Math.abs(b.amount))))))) : null,
        out.teamRep ? el("p", "race-note", `${save.team.name}: +${out.teamRep} team reputation.`) : null,
        passLine, s.lapTimes.length && !LAPLESS.includes(s.mode) ? el("div", "race-laps", ...s.lapTimes.map((t, i) => el("span", t === s.best ? "best" : "", `L${i + 1} ${fmt(t)}`))) : null,
        out.levelUp ? el("p", "race-goal ok", `Level up: you're level ${out.levelUp}.`) : null,
        ...(out.rumours || []).map((r) => el("p", "race-note", `Rumour from ${(D.CAST[r.from] || {}).name || r.from}: “${r.text}” New secret event on the map.`)),
        out.influence ? el("p", "race-note", `${D.DISTRICTS[out.influence.district].name}: your share ${Math.round(out.influence.before)}% → ${Math.round(out.influence.after)}%.`) : null,
        out.news ? el("p", "race-note", `Elsewhere: ${save.world.news[save.world.news.length - 1].text}`) : null,
        out.teamPts ? el("p", "race-note", `${save.team.name}: +${out.teamPts} championship points.`) : null,
        out.season ? el("p", "race-goal " + (out.season.place === 1 ? "ok" : ""), `Season ${out.season.season} over: ${save.team.name} finished P${out.season.place}${out.season.prize ? `, prize ${money(out.season.prize)}` : ""}.`) : null,
        unlocks.length || ach.length ? el("ul", "race-list", ...unlocks, ...ach) : null, ...out.notes.map((n) => el("p", "race-note", n)), champ, classification,
        el("div", "race-grid2", btn("Continue", () => { const talk = [...out.lines, ...(out.reactions || [])]; return talk.length ? dialogue(talk, next) : next(); }, "", { "data-autofocus": "" }),
          view.canReplay ? btn("Watch replay", () => { if (!view.replay(() => card())) toast("Nothing was recorded for this race.", "warn"); }, "alt") : null,
          ctx.kind !== "champ" && ctx.kind !== "tourney" ? btn(ctx.kind === "pursuit" ? "Go again" : "Race again", () => brief({ ...ctx, event: ctx.kind === "pursuit" ? C.pursuitEvent(save, { heat: ctx.event.heat, track: ctx.event.track, time: ctx.event.time }) : ctx.event }), "alt") : null)];
      const card = () => show(() => frame(headline, `${ev.title || "Race"} · ${R.TRACKS[s.track].name}`, body, { noBack: true }), { replace: true });
      // the podium first (top three on the plinths, confetti), then the results; a tap or key skips it
      if (s.of > 1 && !s.eliminated && !s.pursuit && !s.delivery && view.podium) {
        view.overlay(null); view.podium(); view.status(s.place <= 3 ? `On the podium: P${s.place}.` : `P${s.place}. The podium belongs to someone else today.`);
        let shown = false; const go = () => { if (shown) return; shown = true; view.stage.removeEventListener("pointerdown", go); root.removeEventListener("keydown", go); card(); };
        view.stage.addEventListener("pointerdown", go); root.addEventListener("keydown", go); setTimeout(go, 3200);
      } else card();
    }
    function chapterScreen(c) {
      view.backdrop(D.DISTRICTS[D.CHAPTERS.find((x) => x.id === c.id).district].track, "dawn");
      return frame(c.title, `Chapter ${c.id}`, [el("p", "race-line", c.blurb), el("p", "race-note", "New district and events are on the world map."),
        el("div", "race-grid2", btn("Career", () => show(hq, { replace: true }), "", { "data-autofocus": "" }), btn("World map", () => show(worldMap, { replace: true }), "alt"))], { noBack: true });
    }
    function endingScreen(id) {
      view.backdrop("kerbside", "night", "rain");
      const f = save.story.flags, E = D.ENDINGS.find((e) => e.id === id) || D.ENDINGS[D.ENDINGS.length - 1];
      const epilogue = [f.dex_respect ? "Dex Varga now runs Ironclad's junior programme. He tells every rookie about club night." : "Dex Varga still won't say your name. He watches every one of your races.",
        f.crew_pip ? "Pip Hollis races for Okafor Motors, and blocks for you like a wall." : "Otto Brandt coaches at Okafor Motors and swears your tyres were his idea.",
        f.nia_engine ? "Samuel Okafor's V8 sits on a stand in the garage window. Nia polishes it on Sundays." : "",
        f.harlan_exposed ? "Victor Harlan sold the League at a loss. The new owners are the crews." : f.harlan_signed ? "Harlan Holdings owns the League, the circuit and your next three seasons." : f.harlan_refused ? "Victor Harlan still owns the circuit. He never comes to watch any more." : "",
        f.mara_home ? "Tidewater still works out of your garage. Nobody mentions moving." : "", f.benny_saved ? "The Brickyard runs night races again, every Friday." : f.benny_lost ? "The Brickyard is flats now. Benny drives a taxi past it every night." : "",
        save.sponsor ? `${D.SPONSORS[save.sponsor].name} renewed your contract for three years.` : "", "Valentina Corsa has asked for a rematch. Next season."].filter(Boolean);
      const seen = Object.keys(save.endings).length;
      const turns = D.TURNING_POINTS.filter(([k]) => f[k]).map(([, t]) => t);
      const people = ["dex", "mara", "benny", "sora", "valentina"].filter((id) => save.rivals[id]).map((id) => {
        const st = C.rivalStage(save, id); return el("div", "race-endperson", portraitOf(id, 72), el("b", "", D.DRIVERS[id].name.split(" ")[0]), el("span", "race-sub", { feud: "Feud", rival: "Rival", respect: "Respect", ally: "Ally", stranger: "" }[st])); });
      const crew = Object.entries(save.crew.members).filter(([, m]) => m.hired).map(([id, m]) => el("div", "race-endperson", portraitOf(id, 72), el("b", "", D.CREW[id].name.split(" ")[0]), el("span", "race-sub", `Loyalty ${m.loyalty}/10`)));
      const look = el("div", "race-panel", el("p", "race-lbl", "How you got here"), el("ul", "race-list", ...turns.map((t) => el("li", "race-li", t))),
        el("p", "race-lbl", "The rivals"), el("div", "race-endrow", ...people), el("p", "race-lbl", "Your crew"), el("div", "race-endrow", ...crew),
        el("p", "race-note", `${save.stats.wins} wins in ${save.stats.races} races · ${Object.keys(save.garage.owned).length} cars · ${Object.values(save.champWins).reduce((a, b) => a + b, 0)} championship titles`));
      return frame(E.title, `Ending ${D.ENDINGS.indexOf(E) + 1} of ${D.ENDINGS.length} · the end of the story, not of the racing`, [...E.lines.map((t) => el("p", "race-line", t)), ...epilogue.map((t) => el("p", "race-note", t)), look,
        el("p", "race-note", `You've seen ${seen} of ${D.ENDINGS.length} endings. Other roads: ${D.ENDINGS.filter((e) => e.id !== E.id).map((e) => `${e.title} (${e.needs})`).join(" ")}`),
        el("p", "race-note", "Every district and event stays open. The Champions' Masters is now open."),
        el("div", "race-grid2", btn("Main menu", () => show(mainMenu, { replace: true }), "", { "data-autofocus": "" }), btn("Championships", () => show(champs, { replace: true }), "alt"))], { noBack: true });
    }

    // ---------------------------------------------------------------- world map
    let mapSel = null;
    function worldMap() {
      view.status("World map.");
      const sel = mapSel && save.districts.includes(mapSel) ? mapSel : save.districts[save.districts.length - 1];
      mapSel = sel;
      view.backdrop(D.DISTRICTS[sel].track, "day");
      const map = el("div", "race-map");
      const roads = el("div", "race-map-roads"); map.append(roads);
      for (const [id, d] of Object.entries(D.DISTRICTS)) {
        const open = save.districts.includes(id), ch = D.CHAPTERS.find((c) => c.district === id && id !== "park"), b = el("button", "race-pin" + (open ? "" : " locked") + (id === sel ? " on" : ""), el("b", "", d.name), el("span", "", open ? countEvents(id) : `Chapter ${ch ? ch.id : 1}`));
        b.type = "button"; b.style.left = d.x + "%"; b.style.top = d.y + "%"; b.disabled = !open;
        b.setAttribute("aria-label", open ? `${d.name}: ${countEvents(id)}` : `${d.name}: locked until chapter ${ch ? ch.id : 1}`);
        b.addEventListener("click", () => { mapSel = id; if (audio) audio.click(); if (!save.discovered["d-" + id]) { save.discovered["d-" + id] = Date.now(); save.rep += 5; persist(); toast(`Discovered ${d.name}: +5 rep`, "info"); } show(worldMap, { replace: true }); });
        map.append(b);
      }
      if (!save.discovered["d-" + sel]) { save.discovered["d-" + sel] = Date.now(); persist(); }
      const d = D.DISTRICTS[sel], story = C.missions(save).flatMap((c) => c.missions).filter((m) => m.state === "available" && m.track === d.track);
      const side = C.sideEvents(save).filter((e) => e.district === sel), rivals = C.rivalEvents(save).filter((r) => r.district === sel);
      persist();
      const row = (title, sub, action, cls = "") => el("li", "race-li " + cls, el("span", "", title), el("span", "race-sub", sub), action);
      const list = el("ul", "race-list",
        ...story.map((m) => row("★ " + m.title, `Story · ${MODE_NAME[m.mode]} · ${C.goalText(m.goal)}`, btn("Race", () => brief({ kind: "story", event: m }), "small"), "story")),
        ...side.map((e) => e.open ? row((e.done ? "✓ " : e.fresh ? "New · " : "") + e.title, `${MODE_NAME[e.mode]} · ${e.laps} lap${e.laps > 1 ? "s" : ""}${e.weather && e.weather !== "dry" ? " · " + WX[e.weather].toLowerCase() : ""}${e.time && e.time !== "day" ? " · " + TOD[e.time].toLowerCase() : ""}`, btn("Race", () => brief({ kind: "side", event: { ...e, goal: e.goal || (e.mode === "timetrial" ? { type: "time", max: D.PAR[e.track] * e.laps * 1.12 } : { type: "place", max: e.mode === "elimination" ? 2 : 3 }) } }), "small" + (e.done ? " alt" : "")))
          : row("? Undiscovered event", `Reach ${e.rep} reputation to reveal it (you have ${save.rep}).`, null, "locked")),
        ...rivals.map((r) => row(r.title, `Rival · ${R.TRACKS[r.track].name}`, btn("Race", () => brief({ kind: "rival", event: r }), "small"))));
      // this district's crew and your share of it; secret events found through rumours; turf wars once you run it
      const T = D.TURF[sel], inf = Math.round(C.influence(save, sel)), infBar = el("div", "race-bar"), infI = el("i", "up"); infI.style.width = inf + "%"; infBar.append(infI);
      const extra = [...C.secretEvents(save).filter((e) => e.district === sel).map((e) => row((e.done ? "✓ " : "Secret · ") + e.title, `${MODE_NAME[e.mode]} · ${C.goalText(e.goal)} · ${e.reward.text}`, e.done ? chip("Won", "done") : btn("Race", () => brief({ kind: "side", event: e }), "small"), "story")),
        ...C.turfEvents(save).filter((e) => e.district === sel).map((e) => row(e.title, "Crew battle: beat the home crew on their own streets", btn("Race", () => brief({ kind: "side", event: e }), "small"), "story"))];
      for (const x of extra) list.append(x);
      const fe = C.featured(save), tn = C.tonight(save), left = 3 - ((save.world.day - 1) % 3);
      const tonightBox = tn.length ? el("div", "race-panel mission", el("p", "race-eyebrow", `Tonight only · gone in ${left} race day${left > 1 ? "s" : ""}`),
        el("ul", "race-list", ...tn.map((e) => row((e.done ? "✓ " : "") + e.title, `${D.DISTRICTS[e.district].name} · ${MODE_NAME[e.mode]} · ${C.goalText(e.goal)} · ${e.blurb}`,
          e.done ? chip("Won", "done") : btn("Race", () => brief({ kind: "side", event: e }), "small"), e.showdown ? "story" : "")))) : null;
      const ranks = C.rankings(save);
      const rankBox = ranks.length > 1 ? el("div", "race-panel", el("p", "race-lbl", "Street rankings"), el("ol", "race-list", ...ranks.map((x, k) => el("li", "race-li" + (x.you ? " story" : ""),
        el("span", "", `${k + 1}. ${x.name}`), el("span", "race-sub", `${x.w} won · ${x.l} lost`), chip(`${x.pts} pts`))))) : null;
      const special = fe ? el("div", "race-panel mission", el("p", "race-eyebrow", `${C.weekday(save)} · day ${save.world.day} · weekly special`), el("b", "race-title", fe.title),
        el("p", "race-note", `${D.DISTRICTS[fe.district].name} · ${MODE_NAME[fe.mode]} · pays 50% more today.`), btn("Race it", () => brief({ kind: "side", event: { ...fe, goal: fe.goal || (fe.mode === "timetrial" ? { type: "time", max: D.PAR[fe.track] * fe.laps * 1.12 } : { type: "place", max: fe.mode === "elimination" ? 2 : 3 }) } }), "small")) : null;
      const heard = D.RUMORS.filter((r) => save.world.rumors[r.id]);
      const rumours = el("div", "race-panel", el("p", "race-lbl", "Rumours"), heard.length ? el("ul", "race-list", ...heard.map((r) => el("li", "race-li" + (save.world.rumors[r.id] === "done" ? " done" : ""),
        el("span", "", `${(D.CAST[r.from] || {}).name || r.from}: “${r.text}”`), el("span", "race-sub", `${D.DISTRICTS[r.event.district].name} · ${r.event.title}${save.world.rumors[r.id] === "done" ? " · won" : ""}`)))) : el("p", "race-note", C.hired(save, "lio") ? "Nothing yet. Lio is listening." : "Nothing yet. Win races and people talk. (A scout would hear things sooner.)"));
      const wire = save.world.news.length ? el("div", "race-panel", el("p", "race-lbl", "Port Kerbside news wire"), el("ul", "race-list", ...save.world.news.slice(-5).reverse().map((n) => el("li", "race-li", el("span", "", n.text), el("span", "race-sub", `Day ${n.day}`))))) : null;
      return frame("Port Kerbside", `World map · ${C.weekday(save)}, day ${save.world.day}`, [wallet(), map, tonightBox, special,
        el("div", "race-panel", el("b", "race-title", d.name), el("p", "race-note", d.blurb),
          el("div", "race-barrow", el("span", "race-lbl", `You ${inf}%`), infBar, el("span", "race-delta", T.crew)),
          el("p", "race-note", C.runs(save, sel) ? `You run ${d.name}: +10% prize money here, and ${T.crew} wants a turf war.` : `${T.crew} runs ${d.name}. Win here to take it over (75%).`), list),
        rumours, rankBox, wire]);
    }
    function countEvents(id) {
      const n = C.sideEvents(save).filter((e) => e.district === id && e.open && !e.done).length + C.rivalEvents(save).filter((r) => r.district === id).length + C.tonight(save).filter((e) => e.district === id && !e.done).length
        + C.missions(save).flatMap((c) => c.missions).filter((m) => m.state === "available" && m.track === D.DISTRICTS[id].track).length;
      return n ? `${n} to race` : "All done";
    }

    // ---------------------------------------------------------------- championships
    function champs() {
      view.status("Championships.");
      const cur = save.champ && D.CHAMPIONSHIPS.find((c) => c.id === save.champ.id);
      const curBox = cur ? el("div", "race-panel", el("p", "race-eyebrow", "In progress"), el("b", "race-title", cur.name),
        el("p", "race-note", `Round ${save.champ.round + 1} of ${cur.rounds.length}: ${R.TRACKS[cur.rounds[save.champ.round].track].name}. Points ${D.POINTS.join("/")}.`),
        el("table", "race-classif", el("tbody", "", ...C.champTable(save).map((r, i) => el("tr", r.id === "YOU" ? "me" : "", el("td", "", `P${i + 1}`), el("td", "", r.name), el("td", "", `${r.points} pts`))))),
        el("div", "race-grid2", btn("Next round", () => brief({ kind: "champ", event: C.champEvent(save) }), "", { "data-autofocus": "" }), confirmBtn("Abandon", "Abandon this championship?", () => { save.champ = null; persist(); show(champs, { replace: true }); }))) : null;
      const list = el("ul", "race-list", ...D.CHAMPIONSHIPS.map((c) => {
        const open = C.champOpen(save, c);
        return el("li", "race-li" + (open ? "" : " locked"), el("span", "", c.name + (save.champWins[c.id] ? ` · won ×${save.champWins[c.id]}` : "")),
          el("span", "race-sub", open ? c.rounds.map((r) => R.TRACKS[r.track].name.split(" ")[0]).join(" → ") : c.after >= 6 ? "Opens after the story" : `Opens after chapter ${c.after}`),
          open && !save.champ ? btn("Enter", () => { C.startChamp(save, c.id); persist(); show(champs, { replace: true }); }, "small") : null);
      }));
      const tc = save.tourney && D.TOURNAMENTS.find((t) => t.id === save.tourney.id);
      const tBox = tc ? el("div", "race-panel mission", el("p", "race-eyebrow", "Tournament in progress"), el("b", "race-title", tc.name),
        el("p", "race-note", tc.stages.map((st, i) => (i < save.tourney.stage ? "✓ " : i === save.tourney.stage ? "▶ " : "") + st.title + ` (${MODE_NAME[st.mode]})`).join("  ·  ")),
        el("div", "race-grid2", btn(`Race the ${tc.stages[save.tourney.stage].title.toLowerCase()}`, () => brief({ kind: "tourney", event: C.tourneyEvent(save) }), "", { "data-autofocus": "" }),
          confirmBtn("Withdraw", "Withdraw from the tournament?", () => { save.tourney = null; persist(); show(champs, { replace: true }); }))) : null;
      const tList = el("ul", "race-list", ...D.TOURNAMENTS.map((t) => {
        const open = C.tourneyOpen(save, t);
        return el("li", "race-li" + (open ? "" : " locked"), el("span", "", `${t.name} · prize ${money(t.prize)}`),
          el("span", "race-sub", open ? t.stages.map((st) => `${st.title}: ${MODE_NAME[st.mode]}`).join(" → ") + ". Lose a stage and you're out." : `Opens after chapter ${t.after}`),
          open && !save.tourney ? btn("Enter", () => { const r = C.startTourney(save, t.id); if (!r.ok) return toast(r.error, "warn"); persist(); show(champs, { replace: true }); }, "small") : null);
      }));
      return frame("Championships", "Series for points, tournaments by knockout", [wallet(), curBox, list, el("p", "race-lbl", "Tournaments"), tBox, tList]);
    }
    function confirmBtn(label, question, fn) {
      const b = btn(label, () => {
        if (b.dataset.armed) { fn(); return; }
        b.dataset.armed = "1"; b.textContent = question + " Tap again"; b.classList.add("danger");
        setTimeout(() => { if (b.isConnected) { delete b.dataset.armed; b.textContent = label; b.classList.remove("danger"); } }, 4000);
      }, "alt");
      return b;
    }

    // ---------------------------------------------------------------- quick race and free play
    const select = (id, label, value, options, onChange) => {
      const s = el("select", "race-select"); s.id = id;
      for (const [v, l] of options) { const o = el("option", "", l); o.value = v; if (String(v) === String(value)) o.selected = true; s.append(o); }
      s.addEventListener("change", () => onChange(s.value));
      return el("label", "race-field", el("span", "race-lbl", label), s);
    };
    const trackOpts = () => Object.entries(R.TRACKS).map(([k, t]) => [k, t.name]);
    function quickRace() {
      const q = save.quick;
      view.backdrop(q.track, "dusk");
      const ev = () => ({ id: "quick", title: "Quick race", track: q.track, mode: "circuit", laps: 3, field: ["jarvis", "bleu", "whitlock"], tier: 3, level: q.level });
      return frame("Quick race", "You, JARVIS, Bleu and Whitlock", [
        el("div", "race-fields", select("q-track", "Track", q.track, trackOpts(), (v) => { q.track = v; persist(); view.backdrop(v, "dusk"); }),
          select("q-level", "JARVIS drives", q.level, [["easy", "Easy"], ["medium", "Medium"], ["hard", "Hard"]], (v) => { q.level = v; persist(); })),
        el("p", "race-note", "Three laps in your current car. Practice pays a little; your best laps and ghost are saved."),
        btn("Start race", () => go({ kind: "quick", event: ev() }), "", { "data-autofocus": "" })]);
    }
    // ---------------------------------------------------------------- police pursuit (its own mode, apart from the Grand Prix)
    const pur = { track: "kerbside", heat: 1, time: "night", weather: "dry" };
    function pursuitScreen() {
      const max = C.pursuitHeats(save), rec = save.records.pursuit;
      pur.heat = Math.min(pur.heat, max);
      view.backdrop(pur.track, pur.time, pur.weather);
      view.status("Police pursuit.");
      const upd = (k) => (v) => { pur[k] = k === "heat" ? Number(v) : v; show(pursuitScreen, { replace: true }); };
      const heatInfo = { 1: "Two units. They follow and try to box you in.", 2: "Three units; they block from ahead and use nitro.", 3: "Upgraded units ram you and set roadblocks.", 4: "Four units, harder rams, more roadblocks.", 5: "Everything they have." }[pur.heat];
      const cover = { ridge: "The rock tunnel hides you: the escape meter fills twice as fast inside.", oldtown: "The canal bridges hide you: the escape meter fills twice as fast under them.", harbour: "Open water: nowhere to hide, so outrun them.", kerbside: "No cover in the park: outrun them or take units out." }[pur.track];
      return frame("Police pursuit", "Separate from the Grand Prix · your current car", [wallet(),
        el("div", "race-fields",
          select("p-track", "Where", pur.track, trackOpts(), upd("track")),
          select("p-heat", "Starting heat", pur.heat, [1, 2, 3, 4, 5].map((h) => [h, h <= max ? `Heat ${h}` : `Heat ${h} (escape at heat ${h - 1} first)`]).filter(([h]) => h <= max), upd("heat")),
          select("p-time", "Time", pur.time, Object.entries(TOD), upd("time")),
          select("p-wx", "Weather", pur.weather, Object.entries(WX), upd("weather"))),
        el("p", "race-goal", `Heat ${pur.heat}: ${heatInfo}`),
        el("p", "race-note", cover),
        el("ul", "race-list",
          el("li", "race-li", el("span", "", "Busted meter"), el("span", "race-sub", "Fills while a unit is right on you and you're slow or stopped. Full: busted, and you pay a fine.")),
          el("li", "race-li", el("span", "", "Escape meter"), el("span", "race-sub", "Fills while no unit can see you (fog and night shorten their sight), slowly while you keep well clear. Full: escaped, and 30% of the bounty is yours.")),
          el("li", "race-li", el("span", "", "Heat"), el("span", "race-sub", "Rises over time and every time you ram a unit. Four big hits disable a unit (bounty bonus). Roadblocks always leave a gap."))),
        el("div", "race-stats",
          el("div", "race-stat", el("div", "race-lbl", "Escapes"), el("div", "race-v", String(rec.escapes))),
          el("div", "race-stat", el("div", "race-lbl", "Busted"), el("div", "race-v", String(rec.busts))),
          el("div", "race-stat", el("div", "race-lbl", "Best bounty"), el("div", "race-v best", rec.best ? rec.best.toLocaleString() : "–")),
          el("div", "race-stat", el("div", "race-lbl", "Highest heat escaped"), el("div", "race-v", rec.heat ? String(rec.heat) : "–"))),
        btn("Start pursuit", () => brief({ kind: "pursuit", event: C.pursuitEvent(save, pur) }), "", { "data-autofocus": "" })]);
    }

    const free = { track: "kerbside", mode: "circuit", laps: 3, weather: "dry", time: "day", n: 3, change: "none", level: "medium", nitro: "on", collisions: "on", damage: "on", cls: "any", stops: 4 };
    function freePlay() {
      view.backdrop(free.track, free.time, free.weather);
      const met = Object.keys(save.rivals).filter((id) => D.DRIVERS[id] && !["jarvis", "bleu", "whitlock"].includes(id));
      const pool = [...met, "jarvis", "bleu", "whitlock", "pip", "otto"].filter((v, i, a) => a.indexOf(v) === i);
      const one = ["drag", "touge"].includes(free.mode), solo = ["timetrial", "drift", "delivery"].includes(free.mode);
      const ev = () => ({ id: "free", title: "Free play", track: free.mode === "drag" ? "harbour" : free.track, mode: free.mode, laps: free.mode === "sprint" || one ? 1 : free.laps, weather: free.weather, time: free.time,
        field: free.mode === "team" ? pool.filter((id) => id !== C.teammate(save).id).slice(0, 2) : pool.slice(0, one ? 1 : free.n), tier: 3, level: free.level, team: free.mode === "team", stops: free.stops, aiCls: free.cls === "any" ? null : free.cls,
        rules: { nitro: free.nitro === "on", collisions: free.collisions === "on", damage: free.damage === "on" },
        weatherChange: free.change === "none" ? null : { at: 20, to: free.change } });
      const upd = (k) => (v) => { free[k] = ["laps", "n", "stops"].includes(k) ? Number(v) : v; if (k === "mode" && v !== "endurance" && free.laps > 6) free.laps = 3; show(freePlay, { replace: true }); };
      const onOff = [["on", "On"], ["off", "Off"]];
      return frame("Free play", "Any track, any conditions", [
        el("div", "race-fields",
          select("f-track", "Track", free.track, trackOpts(), upd("track")),
          select("f-mode", "Mode", free.mode, Object.entries(MODE_NAME).filter(([k]) => k !== "rival" && k !== "pursuit"), upd("mode")),
          LAPLESS.includes(free.mode) || one || free.mode === "sprint" ? null : select("f-laps", "Laps", free.laps, (free.mode === "endurance" ? [4, 6, 8, 10, 12] : [1, 2, 3, 4, 5, 6]).map((n) => [n, String(n)]), upd("laps")),
          free.mode === "delivery" ? select("f-stops", "Stops", free.stops, [2, 3, 4, 5, 6, 8].map((n) => [n, String(n)]), upd("stops")) : null,
          solo || one || free.mode === "team" ? null : select("f-n", "Opponents", free.n, [1, 2, 3, 4, 5].map((n) => [n, String(n)]), upd("n")),
          solo ? null : select("f-level", "AI difficulty", free.level, [["easy", "Easy"], ["medium", "Medium"], ["hard", "Hard"]], upd("level")),
          solo ? null : select("f-cls", "Opponents' cars", free.cls, [["any", "Their own"], ["C", "Class C"], ["B", "Class B"], ["A", "Class A"], ["S", "Class S"]], upd("cls")),
          select("f-nitro", "Nitro", free.nitro, onOff, upd("nitro")),
          solo ? null : select("f-coll", "Collisions", free.collisions, onOff, upd("collisions")),
          select("f-dmg", "Damage", free.damage, onOff, upd("damage")),
          select("f-time", "Time of day", free.time, Object.entries(TOD), upd("time")),
          select("f-wx", "Weather", free.weather, Object.entries(WX), upd("weather")),
          select("f-change", "Weather change", free.change, [["none", "None"], ["rain", "Rain arrives"], ["dry", "Clears up"], ["fog", "Fog rolls in"]], upd("change"))),
        el("p", "race-note", D.MODES[free.mode].blurb + (free.mode === "drag" ? " Drag races run on the Harbour waterfront." : "")),
        el("p", "race-note", free.mode === "team" ? `2 v 2: you and ${D.DRIVERS[C.teammate(save).id].name} against ${pool.filter((id) => id !== C.teammate(save).id).slice(0, 2).map((id) => D.DRIVERS[id].name).join(" and ")}.`
          : `Opponents: ${solo ? "none in this mode" : pool.slice(0, one ? 1 : free.n).map((id) => D.DRIVERS[id].name).join(", ")}. Rivals you've raced in the story join the pool.`),
        btn("Start", () => go({ kind: "free", event: ev() }), "", { "data-autofocus": "" })]);
    }

    // ---------------------------------------------------------------- garage
    // The car list (filter by class), the selected car on a lit turntable, its numbers against the car you drive,
    // a test lap run on the spot, and tabs: upgrades (with a preview of the next level), tuning, and looks.
    let gSel = null, gTab = "upgrades", gClass = "all", gTest = {};
    const KMH = (spec) => Math.round(spec.acc * (1 + (spec.turbo || 0)) / spec.drag * 0.34);
    const TRAITS = (c) => [c.band <= -0.4 && "Torque monster", c.band >= 0.5 && "High-revving", c.turbo && "Turbo", c.voice && c.voice.sc && "Supercharged", c.slide && "Drifts easily",
      c.offroad && "Shrugs off gravel", c.wet && "Wet-weather grip", c.mass >= 1.3 && "Heavy: wins the shoving", c.mass <= 0.85 && "Featherweight", c.voice && c.voice.cyl && `${{ 3: "Three", 4: "Four", 5: "Five", 6: "Six", 8: "V8", 10: "V10", 12: "V12" }[c.voice.cyl]}${c.voice.cyl < 8 ? "-cylinder" : ""}`].filter(Boolean);
    function testLap(spec, track) {   // one standing lap and one flying lap, driven by the AI line, timed on the flying one
      const r = R.newRace({ track, mode: "timetrial", laps: 2, player: { spec } }); let t = 0;
      while (!r.cars[0].done && t < 120) { R.step(r, 1 / 120, null); t += 1 / 120; }
      return r.cars[0].lapTimes[1] || 0;
    }
    function garage() {
      view.status("Garage.");
      const id = gSel && D.CARS[gSel] && !D.CARS[gSel].police ? gSel : save.garage.current; gSel = id;
      const car = D.CARS[id], st = save.garage.owned[id], owned = !!st, av = C.carAvailable(save, id);
      const shown = st || C.carState(id), spec = C.carStats(id, shown, save.sponsor), stock = C.carStats(id, C.carState(id));
      const curId = save.garage.current, cur = C.carStats(curId, save.garage.owned[curId], save.sponsor);
      const filter = el("div", "race-tabs", ...["all", "C", "B", "A", "S"].map((k) => { const b = el("button", "race-tab" + (k === gClass ? " on" : ""), k === "all" ? "All" : "Class " + k); b.type = "button"; b.addEventListener("click", () => { gClass = k; show(garage, { replace: true }); }); return b; }));
      const col = C.collection(save), colBar = el("div", "race-bar"), colI = el("i", "up"); colI.style.width = Math.round(col.owned / col.total * 100) + "%"; colBar.append(colI);
      const collectionPanel = el("div", "race-panel race-collection", el("div", "race-barrow", el("span", "race-lbl", `Collection ${col.owned} / ${col.total}`), colBar),
        el("p", "race-note", ["C", "B", "A", "S"].map((k) => `Class ${k}: ${col.by[k].owned}/${col.by[k].total}`).join("  ·  ") + ". Some cars can't be bought until you earn them: a drift score, gold medals, a pursuit, a tournament, a grudge match, a crew member."));
      // the cars you're closest to unlocking, and what it takes
      const progress = (cid) => { const U = D.CARS[cid].unlock || {}, golds = Object.values(save.medals).filter((m) => m === "gold").length;
        return U.rep ? save.rep / U.rep : U.chapter ? save.story.chapter / U.chapter : U.medals ? golds / U.medals : U.rival ? ((save.rivals[U.rival] || {}).wins || 0) / U.wins : 0.1; };
      const near = Object.entries(D.CARS).filter(([cid, c]) => !c.police && c.price !== null && !save.garage.owned[cid] && !C.carAvailable(save, cid).ok).sort((a, b) => progress(b[0]) - progress(a[0])).slice(0, 3);
      const nearPanel = near.length ? el("div", "race-panel", el("p", "race-lbl", "Close to unlocking"), el("ul", "race-list", ...near.map(([cid, c]) => el("li", "race-li", el("span", "", `${c.name} · ${c.cls}`), el("span", "race-sub", C.carAvailable(save, cid).why))))) : null;
      const cars = el("div", "race-carlist", ...Object.entries(D.CARS).filter(([, c]) => !c.police && (gClass === "all" || c.cls === gClass)).map(([k, c]) => {
        const o = !!save.garage.owned[k], a = C.carAvailable(save, k);
        const b = el("button", "race-carbtn" + (k === id ? " on" : "") + (o ? " owned" : a.ok ? "" : " locked"), el("b", "", o || a.ok ? c.name : "???"),
          el("span", "", `${c.cls} · ${c.cat}`), el("span", "", o ? (k === curId ? "Driving" : "Owned") : c.price === null ? "Story reward" : a.ok ? money(c.price) : a.why),
          c.unlock && !c.unlock.chapter && !c.unlock.rep && !c.unlock.ended && !o ? el("span", "race-earn", a.ok ? "Earned · now for sale" : "Earn it") : null);
        b.type = "button"; b.addEventListener("click", () => { gSel = k; if (audio) audio.click(); show(garage, { replace: true }); }); return b;
      }));
      const preview = el("canvas", "race-preview"); preview.width = 720; preview.height = 400;
      startPreview(preview, id, shown);
      const barBox = el("div", "race-bars");
      const drawBars = (sp2) => {
        const now = C.bars(sp2), base = C.bars(stock), you = C.bars(cur);
        barBox.replaceChildren(...Object.entries(now).map(([k, v]) => {
          const label = { acceleration: "Acceleration", topSpeed: "Top speed", grip: "Grip", braking: "Braking", nitro: "Nitro" }[k];
          const bar = el("div", "race-bar"), b0 = el("i", "base"), b1 = el("i", "up"), mark = el("i", "you");
          b0.style.width = Math.max(2, base[k] * 100) + "%"; b1.style.width = Math.max(2, v * 100) + "%"; mark.style.left = (you[k] * 100) + "%"; bar.append(b1, b0, mark);
          const d = Math.round((v - you[k]) * 100);
          return el("div", "race-barrow", el("span", "race-lbl", label), bar, el("span", "race-delta " + (d > 0 ? "up" : d < 0 ? "down" : ""), id === curId ? "" : (d > 0 ? "+" : "") + d));
        }));
      };
      drawBars(spec);
      const tl = gTest[id + JSON.stringify(shown.upgrades) + JSON.stringify(shown.tune)];
      const testBtn = btn(tl ? `Test lap · Ridge ${fmt(tl.mine)} (yours ${fmt(tl.cur)})` : "Run a test lap on the Ridge", () => {
        const mine = testLap(spec, "ridge"), c2 = id === curId ? mine : testLap(cur, "ridge");
        gTest[id + JSON.stringify(shown.upgrades) + JSON.stringify(shown.tune)] = { mine, cur: c2 }; show(garage, { replace: true });
      }, "alt small");
      const handling = car.handling ? el("p", "race-note race-handling", car.handling) : null;
      const facts = el("div", "race-tags", chip(`Rating ${car.cls} ${C.rating(spec)}`, "gold"), chip(`${car.cls} · ${car.cat}`), chip(`Top ≈ ${KMH(spec)} km/h`), chip(`${Math.round((spec.mass || 1) * 1000)} kg`), ...TRAITS(car).map((t) => chip(t, "small")));
      const action = owned ? (id === curId ? chip("Driving this car", "gold") : btn("Drive this car", () => { save.garage.current = id; persist(); show(garage, { replace: true }); }))
        : av.ok && car.price !== null ? btn(`Buy for ${money(car.price)}`, () => { const r = C.buyCar(save, id); if (!r.ok) return toast(r.error, "warn"); persist(); toast(`${car.name} is yours.`, "gold"); r.achievements.forEach((a) => toast(`Achievement unlocked: ${D.ACHIEVEMENTS[a].name}${D.ACH_REWARDS[a] ? " · reward: " + D.ACH_REWARDS[a].text : ""}`, "gold")); show(garage, { replace: true }); }, save.money >= car.price ? "" : "alt")
          : el("p", "race-note", av.why);
      const repairBtn = owned && st.dmg > 0.01 ? btn(`Repair ${Math.round(st.dmg * 100)}% damage · ${money(C.repairCost(id, st) * (save.crew.members.nia && save.crew.members.nia.hired ? 0.7 : 1))}`, () => { const r = C.repair(save, id); if (!r.ok) return toast(r.error, "warn"); persist(); toast(`Repaired for ${money(r.cost)}.`, "info"); show(garage, { replace: true }); }, "alt small") : null;
      const TABS = { upgrades: "Upgrades", tune: "Tuning", paint: "Paint", decal: "Decals", wheels: "Wheels", tyres: "Tyres", body: "Arches", bumper: "Bumper", bonnet: "Bonnet", spoiler: "Spoiler", finish: "Finish", tint: "Glass", lights: "Lights", exhaust: "Exhaust", number: "Number" };
      const tabs = el("div", "race-tabs", ...Object.entries(TABS).map(([t, n]) => {
        const b = el("button", "race-tab" + (t === gTab ? " on" : ""), n); b.type = "button"; b.setAttribute("aria-pressed", String(t === gTab)); b.disabled = !owned;
        b.addEventListener("click", () => { gTab = t; show(garage, { replace: true }); }); return b;
      }));
      return frame("Garage", `${save.team.name} · ${Object.keys(save.garage.owned).length} car${Object.keys(save.garage.owned).length === 1 ? "" : "s"}`, [wallet(), collectionPanel, nearPanel, el("div", "race-garage", el("div", "race-garage-l", filter, cars),
        el("div", "race-garage-r", el("b", "race-title", owned || av.ok ? car.name : "Locked car"), el("p", "race-note", owned || av.ok ? car.blurb : av.why), preview, facts, owned || av.ok ? handling : null, barBox,
          el("p", "race-note", id === curId ? "Grey: stock. Gold: as built. The line marks your car." : "Grey: stock. Gold: as built. The line and the numbers compare it with the car you drive."),
          el("div", "race-stack row", action, testBtn, repairBtn), owned ? tabs : null, owned ? tabBody(id, st, drawBars) : null))]);
    }
    function tabBody(id, st, drawBars) {
      const set = (key, value) => { const r = C.setLook(save, id, key, value); if (!r.ok) return toast(r.error, "warn"); if (r.cost) toast(`Bought for ${money(r.cost)}.`, "info"); persist(); show(garage, { replace: true }); };
      if (gTab === "upgrades") return el("ul", "race-list", ...Object.entries(D.UPGRADES).map(([p, u]) => {
        const lv = st.upgrades[p], cost = C.upgradeCost(id, p, lv, save);
        const b = cost === null ? chip("Max", "gold") : btn(money(cost), () => { const r = C.buyUpgrade(save, id, p); if (!r.ok) return toast(r.error, "warn"); persist(); r.achievements.forEach((a) => toast(`Achievement unlocked: ${D.ACHIEVEMENTS[a].name}${D.ACH_REWARDS[a] ? " · reward: " + D.ACH_REWARDS[a].text : ""}`, "gold")); show(garage, { replace: true }); }, "small" + (save.money >= cost ? "" : " alt"));
        if (cost !== null) {   // preview: hover or focus shows the next level on the bars
          const next = { ...st, upgrades: { ...st.upgrades, [p]: lv + 1 } };
          const on = () => drawBars(C.carStats(id, next, save.sponsor)), off = () => drawBars(C.carStats(id, st, save.sponsor));
          b.addEventListener("pointerenter", on); b.addEventListener("pointerleave", off); b.addEventListener("focus", on); b.addEventListener("blur", off);
        }
        return el("li", "race-li", el("span", "", `${u.name} `, el("span", "race-pips", ...[0, 1, 2].map((i) => el("i", i < lv ? "on" : "")))), el("span", "race-sub", u.per + " per level"), b);
      }));
      if (gTab === "tune") {
        const T = st.tune, live = () => drawBars(C.carStats(id, st, save.sponsor));
        const slider = (key, label, min, max, hint) => {
          const i = el("input", "race-range"); i.type = "range"; i.min = String(min * 100); i.max = String(max * 100); i.value = String(Math.round(T[key] * 100)); i.id = "t-" + key;
          i.addEventListener("input", () => { C.setTune(save, id, { [key]: Number(i.value) / 100 }); live(); });
          i.addEventListener("change", () => { persist(); show(garage, { replace: true }); });
          return el("label", "race-field", el("span", "race-lbl", `${label} · ${hint}`), i);
        };
        return el("div", "race-stack", el("div", "race-stack row", ...Object.entries(D.PRESETS).map(([k, P]) => btn(P.name + (T.preset === k ? " ✓" : ""), () => { C.setTune(save, id, { preset: k }); persist(); show(garage, { replace: true }); }, T.preset === k ? "small" : "small alt"))),
          slider("gearing", "Gearing", -1, 1, "left: punchier, right: faster at the top"), slider("aero", "Downforce", 0, 1, "grip at speed, a little drag"), slider("diff", "Differential", 0, 1, "right: looser, slides more"),
          select("t-tyre", "Tyres", T.tyre, Object.entries(D.TYRES).map(([k, t]) => [k, `${t.name} (dry ${Math.round(t.dry * 100)}%, wet ${Math.round(t.wet * 100)}%)`]), (v) => { C.setTune(save, id, { tyre: v }); persist(); show(garage, { replace: true }); }),
          el("p", "race-note", `Tune: ${T.preset === "custom" ? "custom" : D.PRESETS[T.preset].name}. Tuning is free; run a test lap to compare.`));
      }
      if (gTab === "paint") {
        const sw = (key, cur) => el("div", "race-swatches", ...D.LOOKS.paint.map((c) => { const b = el("button", "race-swbtn" + (cur === c ? " on" : "")); b.type = "button"; b.style.background = c; b.setAttribute("aria-label", (key === "paint" ? "Paint " : "Livery colour ") + c); b.addEventListener("click", () => set(key, c)); return b; }));
        return el("div", "race-stack", el("p", "race-lbl", "Body colour"), sw("paint", st.paint), el("p", "race-lbl", "Livery colour (stripes, hoops, sash)"), sw("paint2", st.paint2));
      }
      if (gTab === "number") {
        const inp = el("input", "race-select"); inp.type = "number"; inp.min = "1"; inp.max = "99"; inp.value = String(st.number); inp.id = "g-number";
        return el("div", "race-stack", el("div", "race-fields", el("label", "race-field", el("span", "race-lbl", "Racing number"), inp), btn("Set number", () => set("number", inp.value), "small")),
          el("div", "race-stack row", ...Object.entries(D.LOOKS.numpos).map(([k, o]) => btn(o.name + (st.numpos === k ? " ✓" : ""), () => set("numpos", k), st.numpos === k ? "small" : "small alt"))));
      }
      const opts = D.LOOKS[gTab], fit = Object.entries(opts).filter(([k]) => C.fits(id, gTab, k)), left = Object.keys(opts).length - fit.length;
      return el("div", "race-stack", el("div", "race-stack row", ...fit.map(([k, o]) => o.earn && !save.achievements[o.earn] ? btn(`${o.name} · earn “${D.ACHIEVEMENTS[o.earn].name}”`, () => toast(`${D.ACHIEVEMENTS[o.earn].how}`, "info"), "small alt") : btn(`${o.name}${st[gTab] === k ? " ✓" : st.bought[gTab].includes(k) || !o.price ? "" : " · " + money(Math.round(o.price * D.CLASS_COST[D.CARS[id].cls] / 10) * 10)}`, () => set(gTab, k), st[gTab] === k ? "small" : "small alt"))),
        ["bumper", "bonnet", "tyres", "body"].includes(gTab) ? el("p", "race-note", `Looks only: body parts don't change performance.${left ? ` ${left} option${left > 1 ? "s don't" : " doesn't"} fit the ${D.CARS[id].name}.` : ""}`) : null);
    }
    // A lit turntable: spotlight, a rotating platform with ticks, a floor reflection and spinning wheels.
    // The studio: a dark stage with two softboxes overhead (mirrored on the polished floor), a perspective floor grid,
    // a turntable, a rim light, and the car turning slowly with its lights and steering working.
    function startPreview(cv, id, st, hero) {
      const ctx = cv.getContext("2d"), car = D.CARS[id], t0 = performance.now(), W = cv.width, H = cv.height, k = W / 360;
      const look = C.lookOf(st), off = document.createElement("canvas"); off.width = W; off.height = H; const og = off.getContext("2d");
      const stage = document.createElement("canvas"); stage.width = W; stage.height = H; const sg = stage.getContext("2d");
      const cx = W / 2, cy = H * 0.56;
      if (!hero) {   // the stage is drawn once
        const wall = sg.createLinearGradient(0, 0, 0, H); wall.addColorStop(0, "#15120d"); wall.addColorStop(0.5, "#221d15"); wall.addColorStop(0.52, "#0d0b08"); wall.addColorStop(1, "#050403");
        sg.fillStyle = wall; sg.fillRect(0, 0, W, H);
        for (const sx of [0.3, 0.7]) {   // softboxes and their reflections on the floor
          const bx = W * sx, g1 = sg.createRadialGradient(bx, H * 0.08, 2, bx, H * 0.08, W * 0.2); g1.addColorStop(0, "rgba(255,244,214,0.55)"); g1.addColorStop(1, "rgba(255,244,214,0)");
          sg.fillStyle = g1; sg.fillRect(0, 0, W, H * 0.5);
          sg.fillStyle = "rgba(255,246,220,0.85)"; sg.fillRect(bx - 34 * k, H * 0.05, 68 * k, 6 * k);
          const g2 = sg.createLinearGradient(0, H * 0.55, 0, H); g2.addColorStop(0, "rgba(255,240,205,0.12)"); g2.addColorStop(1, "rgba(255,240,205,0)");
          sg.fillStyle = g2; sg.beginPath(); sg.moveTo(bx - 20 * k, H * 0.53); sg.lineTo(bx + 20 * k, H * 0.53); sg.lineTo(bx + 60 * k, H); sg.lineTo(bx - 60 * k, H); sg.closePath(); sg.fill();
        }
        sg.strokeStyle = "rgba(217,180,95,0.10)"; sg.lineWidth = 1;   // floor grid in perspective
        for (let i = -12; i <= 12; i++) { sg.beginPath(); sg.moveTo(cx + i * 14 * k, H * 0.52); sg.lineTo(cx + i * 60 * k, H); sg.stroke(); }
        for (let j = 0; j < 7; j++) { const y = H * 0.52 + (H * 0.48) * Math.pow(j / 6, 1.7); sg.beginPath(); sg.moveTo(0, y); sg.lineTo(W, y); sg.stroke(); }
      }
      const draw = (now) => {
        if (!cv.isConnected || !alive) return;
        const t = (now - t0) / 1000, a = t * 0.5;
        ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, W, H);
        if (!hero) ctx.drawImage(stage, 0, 0);
        // turntable: a lit disc with a ring of ticks that turns with the car
        const tg = ctx.createRadialGradient(cx, cy, 4, cx, cy, W * 0.36); tg.addColorStop(0, "rgba(255,236,190,0.30)"); tg.addColorStop(0.7, "rgba(255,236,190,0.08)"); tg.addColorStop(1, "rgba(255,236,190,0)");
        ctx.fillStyle = tg; ctx.beginPath(); ctx.ellipse(cx, cy, W * 0.38, H * 0.3, 0, 0, 7); ctx.fill();
        ctx.strokeStyle = "rgba(217,180,95,0.5)"; ctx.lineWidth = 1.5 * k; ctx.beginPath(); ctx.ellipse(cx, cy, W * 0.33, H * 0.26, 0, 0, 7); ctx.stroke();
        ctx.strokeStyle = "rgba(217,180,95,0.28)"; ctx.lineWidth = 1.2 * k;
        for (let i = 0; i < 36; i++) { const q = i / 36 * 6.283 + a; ctx.beginPath(); ctx.moveTo(cx + Math.cos(q) * W * 0.3, cy + Math.sin(q) * H * 0.235); ctx.lineTo(cx + Math.cos(q) * W * 0.33, cy + Math.sin(q) * H * 0.26); ctx.stroke(); }
        const c = { x: 0, y: 0, a, color: st.paint, look, shape: car.shape, art: car.art, car: id, num: st.number, steerIn: Math.sin(t * 1.1) * 0.6, dmg: 0, wheelPh: t * 18, brakeOn: Math.sin(t * 0.7) > 0.85, id };
        // reflection: the car squashed below itself, faded out toward the viewer
        og.setTransform(1, 0, 0, 1, 0, 0); og.clearRect(0, 0, W, H);
        og.setTransform(3.4 * k, 0, 0, -1.2 * k, cx, cy + 34 * k); view.drawCar(og, { ...c }, { lights: true });
        og.setTransform(1, 0, 0, 1, 0, 0); og.globalCompositeOperation = "destination-in";
        const fade = og.createLinearGradient(0, cy, 0, H); fade.addColorStop(0, "rgba(0,0,0,0.3)"); fade.addColorStop(1, "rgba(0,0,0,0)"); og.fillStyle = fade; og.fillRect(0, 0, W, H); og.globalCompositeOperation = "source-over";
        ctx.drawImage(off, 0, 0);
        ctx.setTransform(3.4 * k, 0, 0, 3.4 * k, cx, cy - 4 * k);
        view.drawCar(ctx, c, { lights: true });
        // a rim light sweeping over the body
        ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.globalCompositeOperation = "lighter";
        const rx = cx + Math.cos(t * 0.9) * W * 0.18, rim = ctx.createRadialGradient(rx, cy - 30 * k, 0, rx, cy - 30 * k, 70 * k); rim.addColorStop(0, "rgba(255,240,210,0.10)"); rim.addColorStop(1, "rgba(255,240,210,0)");
        ctx.fillStyle = rim; ctx.fillRect(0, 0, W, H); ctx.globalCompositeOperation = "source-over";
        previewRaf = requestAnimationFrame(draw);
      };
      previewRaf = requestAnimationFrame(draw);
    }

    // ---------------------------------------------------------------- profile, achievements
    function profile() {
      const lv = C.level(save.xp), cur = C.xpFor(lv), nxt = C.xpFor(lv + 1), st = save.stats;
      const name = el("input", "race-select"); name.id = "p-name"; name.maxLength = 18; name.value = save.profile.name; name.autocomplete = "off";
      const xpBar = el("div", "race-bar"), xi = el("i", "up"); xi.style.width = Math.round(((save.xp - cur) / (nxt - cur)) * 100) + "%"; xpBar.append(xi);
      const rivals = Object.entries(save.rivals).filter(([id]) => D.DRIVERS[id]);
      return frame("Driver profile", save.profile.name, [
        el("div", "race-fields", el("label", "race-field", el("span", "race-lbl", "Driver name"), name),
          btn("Save name", () => { const v = name.value.trim().slice(0, 18); if (!v) return toast("Your name can't be empty.", "warn"); save.profile.name = v; persist(); toast("Name saved.", "info"); show(profile, { replace: true }); }, "small")),
        el("div", "race-barrow", el("span", "race-lbl", `Level ${lv} · ${save.xp - cur} / ${nxt - cur} XP`), xpBar),
        el("div", "race-stats", ...[["Races", st.races], ["Wins", st.wins], ["Podiums", st.podiums], ["Credits", money(save.money)], ["Reputation", save.rep], ["Did not finish", st.dnfs]]
          .map(([k, v]) => el("div", "race-stat", el("div", "race-lbl", k), el("div", "race-v", String(v))))),
        el("p", "race-lbl", "Best laps"),
        el("ul", "race-list", ...Object.entries(R.TRACKS).map(([k, t]) => el("li", "race-li", el("span", "", t.name), el("span", "race-sub", `${save.best[k] ? fmt(save.best[k]) : "–"}${save.medals[k] ? " · " + save.medals[k] + " medal" : ""}${save.ghosts[k] ? " · ghost saved" : ""}`)))),
        rivals.length ? el("p", "race-lbl", "Rivals") : null,
        rivals.length ? el("ul", "race-list", ...rivals.map(([id, r]) => el("li", "race-li", el("span", "", D.DRIVERS[id].name), el("span", "race-sub", `${r.wins} wins, ${r.losses} losses · respect ${r.respect}`)))) : null,
        el("p", "race-lbl", "Recent races"),
        save.history.length ? el("ul", "race-list", ...save.history.slice(-8).reverse().map((h) => el("li", "race-li", el("span", "", h.title), el("span", "race-sub", `${R.TRACKS[h.track] ? R.TRACKS[h.track].name : h.track} · ${h.mode === "drift" ? h.drift + " pts" : "P" + h.place + "/" + h.of} · ${money(h.money)}`)))) : el("p", "race-note", "No races yet.")]);
    }
    function achievements() {
      const all = Object.entries(D.ACHIEVEMENTS), got = all.filter(([id]) => save.achievements[id]).length;
      return frame("Achievements", `${got} of ${all.length}`, [el("ul", "race-list", ...all.map(([id, a]) => el("li", "race-li" + (save.achievements[id] ? " done" : " locked"),
        el("span", "", (save.achievements[id] ? "★ " : "☆ ") + a.name), el("span", "race-sub", (save.achievements[id] ? `${a.how} · ${new Date(save.achievements[id]).toLocaleDateString()}` : a.how) + (D.ACH_REWARDS[id] ? ` · Reward: ${D.ACH_REWARDS[id].text}` : "")))))]);
    }

    // ---------------------------------------------------------------- settings and saves
    function settings() {
      const S = save.settings, apply = () => { view.applySettings(S); if (audio) audio.settings(S); persist(); };
      const toggle = (key, label) => btn(`${label}: ${S[key] ? "on" : "off"}`, (e) => { S[key] = !S[key]; apply(); e.target.textContent = `${label}: ${S[key] ? "on" : "off"}`; }, "alt small");
      const vol = el("input", "race-range"); vol.type = "range"; vol.min = "0"; vol.max = "100"; vol.value = String(Math.round(S.volume * 100)); vol.id = "s-volume";
      vol.addEventListener("input", () => { S.volume = Number(vol.value) / 100; apply(); });
      const out = el("textarea", "race-text"); out.id = "s-export"; out.readOnly = true; out.rows = 3; out.setAttribute("aria-label", "Your save, as text");
      const inp = el("textarea", "race-text"); inp.id = "s-import"; inp.rows = 3; inp.placeholder = "Paste a Kerbside save here"; inp.setAttribute("aria-label", "Save to import");
      const dl = el("a", "race-go alt small", "Download file"); dl.hidden = true;
      return frame("Settings", `Graphics now: ${view.quality}`, [
        el("div", "race-fields",
          select("s-quality", "Graphics", S.quality, [["auto", "Auto (adapts)"], ["low", "Low"], ["medium", "Medium"], ["high", "High"]], (v) => { S.quality = v; apply(); show(settings, { replace: true }); }),
          select("s-camera", "Camera", S.camera, [["chase", "Chase (turns with your car)"], ["classic", "Classic (north up)"]], (v) => { S.camera = v; apply(); }),
          select("s-motion", "Reduced motion", S.reducedMotion === null ? "system" : S.reducedMotion ? "on" : "off", [["system", "Follow system"], ["on", "On"], ["off", "Off"]], (v) => { S.reducedMotion = v === "system" ? null : v === "on"; apply(); }),
          select("s-diff", "Career AI", S.difficulty, [["easy", "Easy"], ["medium", "Medium"], ["hard", "Hard"]], (v) => { S.difficulty = v; apply(); }),
          select("s-damage", "Damage", S.damage, [["cosmetic", "Cosmetic only"], ["persistent", "Carries over (repairs cost money)"]], (v) => { S.damage = v; apply(); })),
        el("div", "race-stack row", toggle("shake", "Camera shake"), toggle("ghost", "Ghost car"), toggle("sound", "Sound"), toggle("music", "Music")),
        el("label", "race-field", el("span", "race-lbl", "Volume"), vol),
        el("p", "race-lbl", "Controls"),
        el("p", "race-note", "Arrows or WASD drive · Space or Shift: nitro · P or Esc: pause · Esc in menus: back. Touch: steering pads left, NOS, brake and gas right."),
        el("p", "race-lbl", "Your save"),
        el("p", "race-note", "Progress is kept in this browser only. Export it to keep a copy or move it to another device."),
        el("div", "race-stack row", btn("Export", () => {
          out.value = C.exportSave(save); out.select();
          try { const url = URL.createObjectURL(new Blob([out.value], { type: "application/json" })); dl.href = url; dl.download = "kerbside-save.json"; dl.hidden = false; } catch { /* text only */ }
          const p = navigator.clipboard && navigator.clipboard.writeText ? navigator.clipboard.writeText(out.value) : Promise.reject();
          p.then(() => toast("Save copied to the clipboard.", "info"), () => toast("Save shown below: select it and copy.", "info"));
        }, "small"), dl), out,
        inp, el("div", "race-stack row", confirmBtn("Import", "Replace your current career?", () => {
          const r = C.importSave(inp.value);
          if (!r.ok) return toast(r.error, "warn");
          const old = C.exportSave(save);
          try { store.setItem(C.KEY + "-before-import", old); } catch { /* best effort */ }
          save = r.save; persist(); view.applySettings(save.settings); toast(r.migrated ? "Quick Race records imported into a new career." : "Save imported.", "gold"); show(mainMenu, { replace: true });
        }), confirmBtn("Start a new career", "Erase this career? (a copy is kept)", () => {
          try { store.setItem(C.KEY + "-before-reset", C.exportSave(save)); } catch { /* best effort */ }
          const s = C.fresh(); s.settings = save.settings; save = s; persist(); toast("New career started. The old one is kept as a copy in this browser.", "info"); show(mainMenu, { replace: true });
        }))]);
    }

    show(mainMenu);
    return { detach: () => { alive = false; cancelAnimationFrame(previewRaf); toastBox.remove(); }, get save() { return save; }, show: (name) => show({ main: mainMenu, hq, map: worldMap, garage, champs, quick: quickRace, free: freePlay, profile, achievements, settings }[name] || mainMenu) };
  }
  const api = { attach };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.KerbsideUI = api;
})(typeof self !== "undefined" ? self : globalThis);
