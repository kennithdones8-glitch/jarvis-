# Kerbside Grand Prix — audit and architecture

## 1. Audit of the starting point (before the transformation)

### Where the game lives
- **Embedded:** the Race tab on the JARVIS dashboard's Games page. `src/jarvis/server/static/racer.js` and
  `racer.css` are served by `src/jarvis/server/app.py` from an explicit whitelist of static paths. The page's CSP is
  `default-src 'self'; style-src 'self'; script-src 'self'`, so there is **no inline code and no inline `style=""`**;
  styles set through the CSSOM (`el.style.x = …`) are allowed. `app.js` (`renderRace`) calls `JarvisRacer.mount()`.
- **Standalone:** `games/kerbside/index.html` plus the same `racer.js`/`racer.css` and the Rajdhani font (OFL).
  `games/kerbside/make_zip.py` builds `kerbside-grand-prix.zip`. It opens from `file://` with no network.
- No dependencies: no library, no network, no build step. No image assets: a dashboard test (`test_avatar25`) allows
  no PNG textures in `static/` besides the app icons, so all art is procedural (Canvas 2D).

### Architecture (one file, two halves)
- **Simulation (pure, Node-testable):** track splines (Catmull-Rom, resampled every 12 units), `nearest()` centreline
  search, `newRace()`, fixed-step `step()` at 120 Hz, `physics()` (heading-relative velocity, drag, grip, brake →
  reverse), `aiInput()` (look-ahead target, curvature braking, nitro on straights above Easy), `collide()` (circle
  separation + impulse), continuous-progress lap counting, `standings()`, ghost record/playback (`ghostPose`).
- **Page (browser only):** `mount()` builds a stage (canvas + DOM HUD + touch pads + overlay card), `paintTrack()`
  paints a static world picture per race, `render()` draws cars/ghost/minimap/HUD, `frame()` runs the loop and pauses
  when the page or Games view is hidden; `localStorage` key `jarvis-racer-v2` holds prefs, best laps, wins, ghosts.

### Public contract (must keep)
`JarvisRacer.mount({onStatus}) → stage element` (idempotent while connected), `unmount()`, `restart()`; simulation
API used by tests: `TRACKS, LAPS, TW, SP, LEVELS, ROSTER, NITRO, GHOST_DT, track, nearest, newRace, step, standings,
aiInput, ghostPose, fmt`. `app.js` depends only on `mount`/`restart`. Existing saves under `jarvis-racer-v2`.

### Features present
3 tracks, 3 levels, 4-car field (you, JARVIS, Bleu, Whitlock), start lights, nitro, ghost of best flying lap,
timing tower, minimap, lap/best/ghost HUD, wrong-way warning, skid marks, results with classification, pause
(P / hidden page), keyboard + touch pads, best lap/race per track+level, wins.

### Bugs, debt and limits found
1. **Per-frame storage parsing.** `render()` and `handleEvents()` call `store.get()` every frame, which
   `JSON.parse`s the whole save including ghost recordings (~1,500 numbers per track): wasted CPU and battery.
2. The timing tower is rebuilt (DOM) whenever any car moves 4 centreline points: ~10–15 rebuilds a second.
3. One hard-coded roster and grid of 4; physics constants are global, so cars can't differ.
4. AI never overtakes or avoids traffic: it drives its own lane offset and bumps through.
5. No recovery for a car pointed the wrong way at low speed besides slow re-steering.
6. Save format has no version field, no validation, no backup, no export.
7. Only one mode (3-lap circuit). No menus beyond the start card; no progression; no audio.
8. Tall scenery is flat; no lighting, weather or particles; one car silhouette in four colours.
9. A single global game instance (`G`) — fine for the dashboard (one Race tab) but worth stating.
10. iPhone was only checked in Playwright's iPhone emulation, never on hardware.

## 2. Target architecture

All plain scripts (UMD: `module.exports` in Node, a global in the browser), loaded in this order:

| File | Role | Node-testable |
|---|---|---|
| `racer-data.js` → `KerbsideData` | Cars, upgrades, characters, districts, events, story chapters, achievements, par times | yes (data) |
| `racer-career.js` → `KerbsideCareer` | Save schema v3, validation, migration from v2, safe writes, export/import, economy, car stats with upgrades, rewards with duplicate guard, unlocks, story engine, championship, achievements | yes |
| `racer.js` → `JarvisRacer` | Simulation (now with car stats, modes, personalities, weather grip, damage, elimination, drift scoring) and the race view (2.5D scenery, lighting, weather, particles, cinematics, HUD) | simulation yes |
| `racer-audio.js` → `KerbsideAudio` | Web Audio synthesis (engine, tyres, nitro, impacts, countdown, finish, menus, music); silent no-op when unsupported | API shape |
| `racer-ui.js` → `KerbsideUI` | Menus: main menu, career HQ, story dialogue, world map, garage, event setup, championship, free play, results, profile, achievements, settings, save export/import | via browser checks |
| `racer.css` | All styles; dashboard tokens with fallbacks; no text under 12px | — |

`mount()` keeps its contract. When `KerbsideUI` is present it shows the main menu; without it, the original start
card still works (fallback). Races are described by a **race config** (track, mode, laps, field, player car, weather,
time of day, ghost); the UI builds configs, the engine runs them, and the career module turns results into rewards.

## 3. Plan and acceptance (per phase)
- **A** audit + tests baseline (this file; existing 11 race tests green).
- **B** engine: car stats, n-car grid, modes, weather grip, damage; renderer: 2.5D scenery, lights, weather,
  particles, cinematics, quality levels, storage-read fix. *Accept:* old tests pass; new physics/mode tests pass;
  screenshots of each track in day/night/rain/fog.
- **C** save v3 + menus. *Accept:* v2 saves migrate without loss (test), malformed saves recover from backup (test),
  export → import round-trips (test); every menu button leads somewhere real (browser check).
- **D** story: 5 chapters, missions with goals, dialogue with choices and consequences. *Accept:* the whole campaign
  can be completed in simulation with every branch (test).
- **E** world map + modes: sprint, elimination, time trial, drift, rival, championship, free play.
- **F** garage: 8 cars, purchases, paint/decal/number/wheels/body/spoiler, 5 upgrade paths with real effects (tests).
- **G** AI personalities, overtaking, recovery; audio; ambience.
- **H** performance (auto quality), accessibility (reduced motion, focus, labels), regression, zip.

## 4. Risks
- Scope: a full campaign plus garage is large; each part ships as a working slice, limits documented below.
- Balance can only be simulated (AI vs AI), not felt; difficulty settings are the safety valve.
- Canvas memory on iPhone (16.7M-pixel cap per canvas): world pictures stay under ~10M pixels.
- Dashboard CSP: no inline styles or scripts; every new file must be added to the server whitelist.

## 5. What was delivered (state at the end of this transformation)

### Files
| File | Lines | Status |
|---|---|---|
| `static/racer-data.js` | 306 | new: 8 cars, 5 upgrade paths, looks, 10 drivers with personalities, cast, 2 sponsors, 4 districts, 5 chapters / 18 missions, 12 side events, 5 rival challenges, 3 championships, 16 achievements |
| `static/racer-career.js` | 422 | new: save v3, validation, v2 migration, backup/corrupt handling, export/import with checksum, economy, story engine, championships, achievements |
| `static/racer.js` | 1,087 | rewritten on the original engine: same public API; car specs, 6-car grids, 6 modes, personalities, lateral grip limit, rain, damage, off-track recovery; 2.5D renderer, lighting, weather, particles, cinematics, quality levels |
| `static/racer-audio.js` | 92 | new: Web Audio synthesis, no files |
| `static/racer-ui.js` | 466 | new: every menu and screen |
| `static/racer.css` | 198 | extended |
| `app.py`, `index.html`, `app.js` | small | whitelist, script order, Race tab text |
| `games/kerbside/*` | small | standalone page, README, zip builder (now ships all modules) |
| `tests/test_racer.py` | updated | original 12 tests (4 tracks now) |
| `tests/test_racer_engine.py`, `tests/test_racer_career.py` | new | 23 tests incl. two full simulated campaigns |

### Physics changes found necessary (with evidence)
- **Lateral grip limit.** Simulation showed every corner of every track could be taken flat out without braking:
  grip had no limit, so braking, tyres and the grip upgrades barely mattered. Tyres now hold at most grip × 90
  units/s² of cornering force; flat out now leaves the road (3–13 s off track per race in the test bot).
- **AI corner speed.** Rebuilt from the car's steering authority and tyre limit plus braking distance (it was a
  fixed curvature penalty that made the AI ~20% slower than a full-throttle bot).
- **Off-track recovery.** A car could fly into the edge of the world at nitro speed and stay pinned there; cars
  beyond the gravel for 3 s are now put back on the road (you get a "Back on track" notice).
- **Frame delta clamp.** The first animation frame could carry a time stamp earlier than mount, giving a negative
  step and an out-of-range index in the menu camera (an intermittent page error seen in the browser runs).

### Balance (simulated, not felt)
- Lap times per track/car were measured in simulation; time-trial medals use a clean Class B lap + 5%.
- Full campaign, simulated player (the AI driving your car, a corner-committing bot in drift events, side events
  for money after a loss, sensible spending): Easy finished in 34–38 races, Medium 44–48, Hard 72 in one run and
  blocked at the finale after 15 attempts in the other. Two of these runs (Easy pick 0, Medium pick 1) are tests.

### Performance
- Headless Chromium on this container, 1280×800, six cars: 16.7 ms median and p95 frame time on every condition
  tried (day, night with lighting, rain, fog, drift) — i.e. locked at 60 fps. This is a desktop CPU without a GPU
  and **is not a phone measurement**. Auto quality steps down (high → medium → low) if frames average over 26 ms
  for 3 s; world pictures stay under 10M pixels (iPhone canvas limit is 16.7M).

### Known limits and remaining work
- **Not tested on real iPhone or iPad hardware**; only Playwright's iPhone 13 emulation (layout, touch pads).
- Balance and "feel" are untested with a human; difficulty settings are the safety valve.
- Drift targets were set from a bot that slides by accident; a skilled human may find them easy.
- Audio was exercised only for "doesn't break without Web Audio"; nobody has listened to it here.
- Race recovery is partial: an interrupted race is reported (no result, nothing lost) and championship progress
  persists between rounds, but a race can't be resumed mid-lap.
- The world map is a district hub, not a drivable open world (by design, per the brief's performance caution).
- Story is complete for five chapters; more chapters are data-only additions in `racer-data.js`.
- No cloud sync (not authorised); export/import is the way to move a career.

## 6. Graphics upgrade (cinematic arcade pass)

Only the page half of `racer.js`, `racer.css`, a camera setting (`racer-ui.js`, `racer-career.js`) changed; the
simulation (physics, AI, tracks, modes) is untouched and its tests are unchanged.

- **Frame order:** world picture → water glints → ground particles → reflections/underglow → nitro trails → ghost →
  cars → 2.5D scenery (collects emissive lights) → sparks/confetti → cloud shadows → colour grade → darkness with
  light holes (half resolution) → glow pass (additive sprites) → sun flare → fog → rain/lightning → speed streaks →
  vignette (cached) → cinematic bars → HUD (DOM + canvas gauge).
- **Camera:** critically damped spring on a look-ahead point; chase mode rotates the world (`setTransform` with a
  rotation) so the car points up and sits at 62% height; 2.5D lean, light holes and headlight cones use the same
  world→screen mapping. Classic (north-up) is a setting and is forced by reduced motion.
- **Cars:** one sprite per look at 3× (`sprite()`, ≤80 cached), drawn with `drawImage`; wheels, lights, flames and
  damage are live. Glows are pre-rendered per colour (`glowSprite`), not a gradient per light.
- **Performance (headless Chromium, CPU rasteriser, 1280×800, 6 cars):** Low 16.7 ms median; Medium 16.7 ms median
  with some 33 ms frames; High ~33 ms in busy night/rain scenes. Auto quality steps down after 2 s of slow frames and
  did so in the test runs. Desktop browsers and iPhone Safari draw canvas on the GPU, so they should do better, but
  **this was not measured on a phone or a GPU here.** Touch devices start at Medium.
- Bugs found while testing the pass: the menu light sweep made the overlay scrollable, so focusing a garage button
  slid the card off-screen (the sweep now animates its background inside the overlay); water glints ran a full
  track search per glint (now cached per cell); the phone HUD overlapped (compact lap panel on touch).

## 7. Next generation (phases 1–8)

Section 5's file table describes the first transformation; this section is the current state.

### Files (load order)
| File | Lines | Role |
|---|---|---|
| `static/racer-data.js` → `KerbsideData` | 524 | 29 cars (27 for sale, the Countess as a story reward, the police Interceptor), 9 upgrades, tyres, tuning presets, looks, drivers, cast, crew of six, rival lines, 5 endings, sponsors, districts and turf, 5 chapters, 26 side events, rumours, 4 championships, 2 tournaments, 8 sponsor contracts, team-championship crews, achievements |
| `static/racer-career.js` → `KerbsideCareer` | 881 | save v4 (key `kerbside-save-v3`, v3 saves upgrade in place), validation of every field, migration, backups, export/import; economy, car stats with traits, upgrades and tuning; crew, rival memory and stages, endings; the living world; class rules, team fields, pursuits, tournaments, wagers, contracts, team championship, New Game+ |
| `static/racer.js` → `JarvisRacer` | 448 | simulation only: tracks, physics (mass, turbo spool, aero, slide, tyres, offroad, tyre wear), AI, collisions, laps, overtakes and contact log, custom rules (nitro / collisions / damage) and the mode hooks |
| `static/racer-modes.js` | 356 | rules of pursuit, drag, touge, endurance, delivery and team races, registered on `JarvisRacer.HOOKS` (`init`, `input`, `post`, `summary`) |
| `static/racer-audio.js` → `KerbsideAudio` | 192 | synthesised sound (engine voices, turbo, crowd, rain, sirens, radio, adaptive music) |
| `static/racer-render.js` | 1,541 | the race view: world art, 2.5D scenery, lighting, weather, cars, camera, HUD and mode meters, touch pads, replay recorder and viewer, photo mode; `mount` / `unmount` / `restart` / `view` |
| `static/racer-ui.js` → `KerbsideUI` | 691 | every menu and screen |
| `static/racer.css` | 315 | the look; no text under 12px |

The public contract is unchanged: `JarvisRacer.mount()`, `unmount()`, `restart()`; `app.js` calls only those.

### How a mode plugs in
`newRace(opts)` looks up `HOOKS[mode]`: `init(race, opts, rand)` sets the mode up (it can pin the track, cap the
field and add cars); every step `input(race, car, inp, you)` can replace a car's input (police AI, drag gears and
auto-steer, pit stops); `post(race, dt)` applies the rules after physics and laps; `summary(race, out)` adds the
mode's result (`out.pursuit`, `out.drag`, `out.touge`, `out.endurance`, `out.delivery`, `out.team`). Police and
roadblock cars carry `police` / `parked` and are left out of standings, overtakes and the rival log.

### Police pursuit rules (all in `racer-modes.js`)
Heat 1–5 sets the number of units (2–5), their skill and whether they ram and set roadblocks; heat rises over time
(35 s a level) and with each ram. Units follow the road on your line, steer straight at you within 130 units, pin you
when you're slow (reversing back to you if they've passed), and cut across your line from ahead at heat 2+. Four big
hits disable a unit. Roadblocks are two parked units across the road ahead with a gap of at least 2 car widths.
Sight: 650 units (540 at night, 400 in fog); in the Ridge tunnel or under the Old Town bridges only a unit within
200 sees you. Busted meter: fills while any unit is within 115 and you're under 150. Escape meter: fills out of
sight (twice as fast in cover), slowly while every unit is over 420 away. Balance measured with bots: a car
noticeably faster than the police escapes heat 1 in about 25 s; an even car is held but not caught, so escaping
takes nitro, cover or rams; driving into a roadblock busts you.

### Tests (74 for the game; 1,082 in the repository, all passing)
`test_racer.py` 9, `test_racer_engine.py` 12, `test_racer_career.py` 14 (two full simulated campaigns),
`test_racer_garage.py` 5, `test_racer_story.py` 6, `test_racer_world.py` 4, `test_racer_modes.py` 11,
`test_racer_team.py` 4, `test_racer_media.py` 4. The campaign bot drives drift events in the car that slides best,
lifting when the slide gets too big, and grinds only the classic modes (it doesn't pit or deliver).

### Browser checks (Playwright, Chromium)
Standalone page and the JARVIS dashboard (with its CSP), desktop 1280×800 and iPhone 13 emulation: every menu,
a pursuit, a drag race with the SHIFT pad, endurance and delivery HUDs, the team screen, the replay viewer with all
four cameras and highlights, photo mode with a filter and a real PNG download — no page errors.

### Known limits
- Not tested on real iPhone/iPad hardware or a GPU; performance figures are from a CPU-only headless browser.
- Nobody has listened to the audio here; the tests check what is scheduled, not how it sounds.
- Pursuit and mode balance are bot-measured, not human-felt.
- Replays live in memory for the session (not saved), up to ten minutes per race.
- `save.team.rep` grows with contracts and seasons but nothing spends it yet.

## 8. Quality overhaul (phases 1–7)

Section 7 describes the next generation; this section is the current state after the overhaul.

### Files
| File | Lines | What changed |
|---|---|---|
| `static/racer-data.js` | 930 | 39 cars (38 drivable: C 6, B 15, A 10, S 7; the police Interceptor) with an `IDENTITY` per car (handling, power `band`, `voice`, `art`, `factory` livery); body parts with `fits`; earned looks; cast faces; Victor Harlan; 11 character stories (`ARCS`, 17 missions); 22 turning points; grudges; team levels; achievement rewards; `WORLD_NEWS`, `REP_TITLES`, `MATTERS`, `TONIGHT`; 34 side events (some open or close on story flags) |
| `static/racer-career.js` | 1,113 | signature cars, `resolve` (story variants by flag), refused choices you can't afford, arc missions, team levels, ratings, prize breakdown, collection; the living world: `tonight`, `rankings`, showdowns, `matters` / `settle`, `repTitle` |
| `static/racer.js` | 451 | the power band in the physics |
| `static/racer-render.js` | 1,905 | car bodies from outlines, lamps, details, damage; track furniture; rooftops; reflections; grid intro; announcer and crowd hooks on race events |
| `static/racer-audio.js` | 241 | per-car voices (cylinders, rasp, lope, supercharger, electric); `say` (speech synthesis, throttled by priority), `crowd`, `ui` |
| `static/racer-ui.js` | 865 | dialogue scenes with portraits, character stories, garage tabs for parts, ratings, team levels, garage matters, tonight-only panel, street rankings, announcer setting |

Save: still v4 under `kerbside-save-v3`. New fields (`world.ranks`, `world.matters`, `world.tonightWins`,
`world.showdown`, `settings.announcer`, the new look keys) are validated and default safely on older saves. Story
state lives in boolean flags, so no migration was needed.

### Tests (105 for the game)
Added: `test_racer_phase1.py` 5 (graphics, with a browser test), `test_racer_cars.py` 7, `test_racer_story2.py` 5,
`test_racer_progress.py` 4, `test_racer_city.py` 5, `test_racer_sound.py` 5 (with a browser race that records the
announcer). The browser tests skip themselves where Playwright isn't installed.

### Known limits
- The announcer uses whatever voice the device offers; it was checked with a stub in headless Chromium, not heard.
- Performance: Medium holds 60 fps in the worst scene in 3 of 4 runs on a CPU-only headless browser; High runs at
  30 fps there. Not measured on a GPU or a phone.
- Not yet played on a real iPhone.
