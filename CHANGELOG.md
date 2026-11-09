# Changelog

## Unreleased — after 0.19.3 (work branch `claude/funny-allen-ygy8kk`, not yet released)

### iPhone layout (Evolution 3.0, phase 6)

- **The focus view on iPhone is split into tabs** — Now (state, readiness, current work, systems), Modes (working
  modes and avatar forms), Projections (the open ones and their controls) and Controls (presets, camera, quality,
  Diagnostics) — instead of one long scrolling panel. On a computer everything is shown as before.
- **Touch-sized controls**: projection buttons, tabs, mode and form chips and text fields are at least 44 points; on
  the phone the projection list hides the "move to the other side" and "move up" buttons (not meaningful on a narrow
  screen). Checked at iPhone 13 size: no control under 40 points in any tab, nothing scrolls sideways.
- **Section headers stay compact** on the phone (one swipeable row of figures), so a page's content comes first.
- The "⌘↩ to send" hint is no longer shown on touch-only devices.
- Still to check on a real iPhone in Safari (the headless browser only emulates its size and touch).

### Avatar forms and operational readiness (Evolution 3.0, phase 5)

- **Five forms of the same figure** (focus view → Form): Standard (armour closed), Diagnostic (helmet opened to
  the sensor array, three-quarter view, Diagnostics on), Engineering (arms and hands opened for inspection),
  Intelligence (**X-ray**: the plates thin out so the neural network inside shows, at its real activity level) and
  Advanced (reactor exposed, close up, the full holographic look). Each reuses a transformation sequence, a camera
  view and a look; the avatar's identity is unchanged.
- **Only you choose a form** — no JARVIS state or working mode picks one. Leaving inspection re-opens the form you
  chose; leaving the focus view closes the armour (your choice is kept for next time). The look lasts only while
  the form does; your saved settings never change.
- **Operational readiness** from the health checks the dashboard already runs: the focus panel says "Operational:
  all N checks pass" or "Not fully operational: N of M failing (names)", and the avatar gives one readiness pulse
  when all checks first pass (again only after a problem clears) — never during the startup assembly or in reduced
  motion, never without data.

### Working modes and mission dependency maps (Evolution 3.0, phase 4)

- **Six working modes in the focus view**: Command (the overview), Engineering (software architecture + simulation,
  three-quarter view, Diagnostics on), Intelligence (research sources + knowledge network), Strategy (workflow +
  timeline), System (security shield + data, Diagnostics on) and Creative (globe, a calmer cinematic look). Each is a
  set of projections, a camera view and a few look settings — workspaces, not new dashboards.
- **Auto** (the default) follows what JARVIS is really doing: coding and experiments → Engineering; research,
  analysis and learning → Intelligence; planning, running and verifying missions → Strategy; a decision, a refusal,
  a warning, an error, the emergency stop or recovery → System (at once). Other changes wait until the current mode
  has had 8 s; it returns to Command 20 s after the activity ends. Creative is never chosen automatically (nothing
  real means "be creative"). A preview never changes the mode. Choosing a mode yourself turns Auto off.
- Projections a mode opened close when it changes; ones you opened or pinned stay. A mode's look lasts only while
  it does: your saved display settings never change, and leaving the focus view restores them.
- **Mission dependencies**: the workflow projection now draws a line only where a step really waits for another (an
  arc above the row), instead of chaining every step, so independent steps no longer look sequential.

### Connected intelligence: tournament → routing, knowledge links, one suggestions feed (Evolution 3.0, phase 3)

- **The intelligence tournament informs routing** (level 7 only). When its evidence clearly separates two models
  (5+ checked answers each, 20+ points apart), the better one gets a small bonus and the weaker a small penalty —
  the same ±3 limit as before, only among models already allowed, logged, in the morning digest, undoable (an undone
  adjustment never returns), and withdrawn by itself when the gap closes. Benchmark runs are shown alongside but don't
  drive it (a run mixes models, so it can't be credited to one). A lesson and the tournament about one model add up.
- **Lasting knowledge links.** JARVIS now remembers which memories were given to each answer as context ("context
  for" — being in the context doesn't prove the answer relied on it, so it doesn't claim more). The knowledge graph
  also connects memories and conversations to the project ideas they're evidence for, and a replan to the mission it
  retried. Links hold ids only, never text; conversations appear as "a conversation on <date>". Deleting or
  forgetting a memory, a conversation or a mission removes its links.
- **One ranked suggestions feed** ("For you, ranked" on Briefing & ideas): failed missions you can retry, failing
  health checks, projects stalled for a week, lessons whose evidence disagrees, improvement proposals and new project
  ideas — ranked by urgency, then value, weighted by how sure the source is, with the reason shown. It suggests only:
  "Open" takes you where you decide; "Not now" hides an item for 30 days (a failing health check only for a day;
  sooner if its evidence doubles), and the feed says how many are hidden.
  Empty with the initiative pause, level 5 off or the emergency stop. At most one notification a day, generic ("JARVIS
  has a suggestion"), never in quiet hours.

### Mission Control: missions are checked, plans survive restarts, one replan (Evolution 3.0, phase 2)

- **Every mission has a definition of success**, decided from its plan when you run it (never by a model): one
  criterion per step. The plan card shows "How JARVIS will check it's done" before you press Run plan.
- **"Complete" means checked.** Files: exactly what was written (as before). Calendar events, reminders and notes:
  read back from the app afterwards — if the app said it added something that isn't there, the mission **fails**.
  Mail drafts and Music/system changes are marked "reported by the app" (Mail drafts can't be read back). A check
  that couldn't run (e.g. Calendar didn't answer) shows "Complete · 1 not confirmed", never "verified", and the
  learning engine counts it as unverified. Each mission card lists every criterion and what the check found.
- **Plans survive a restart.** A plan waiting for you comes back after JARVIS restarts ("Kept from before JARVIS
  restarted"); planning that was cut off starts again; a plan waiting for your OK to use Claude keeps waiting on the
  same request instead of asking twice. Saved plans older than a day are dropped, and **forget** removes them.
- **Try a new plan** on a failed mission: JARVIS plans it once more, told which steps happened and what failed (step
  descriptions and errors, never file contents), so it doesn't redo what's done. The new plan is reviewed like any
  other; nothing runs until you press Run plan. One replan per mission; a second attempt can't be replanned.
- Schema v10 (`plan_jobs`). The benchmark's tool-use record now shows the read-back (`reminders.find` after
  `reminders.add`).
- Fix (3D): opening the dashboard straight onto a page where the projection is hidden (e.g. Missions) made the
  renderer's first frame fail; it now waits until it has a size.

### Security: closing the autonomy gaps (Evolution 3.0, phase 1)

- **Change trials (level 6) are isolated.** The branch's tests no longer run as you: no API keys, tokens, SSH agent
  or JARVIS settings reach them; HOME and TMPDIR are throwaway folders; and on macOS they run inside the system
  sandbox: no network except this Mac, no writes outside the trial folder, no reads of JARVIS's data, `~/.ssh`,
  cloud credentials or Keychains. A Mac without the sandbox refuses to run trials, and if the sandbox can't start, the
  trial reports that it proves nothing rather than running unprotected. The result records how it was isolated.
- **Trials can only be started from the Mac.** A paired iPhone is refused (and the attempt is audited), even with
  level 6 on.
- **Forget removes your ratings and their comments** for what it deletes, plus any rating whose comment mentions it.
- **A release-gate test proves every tool action goes through the permission gateway** (the one read-only exception,
  `jarvis mac check`, is listed and checked).
- Needs a check on the Mac: the first real trial shows whether the sandbox rules start on macOS 14.

- **Merged 0.19.3 from `main`** (private data folder, the stronger and reasoning-only local models, warm start,
  `jarvis checkup`, exact calendar and reminder facts, small memory seen whole, the harder benchmark set and its plan
  checks). Nothing from either side was dropped. Two adaptations: the Ask / Research / Do classifier keeps the fastest
  local model (`keep_speed`), so a message that looks like maths or code never loads the big reasoning model just to
  be classified; and "don't change anything" in a request now also covers Music and system changes (play, pause,
  playlists, volume, Do Not Disturb).
- Below: the work since 0.19.0 on this branch (Avatar 2.5, E.V.O.L.V.E., Music and system, automatic Ask /
  Research / Do and more), newest first. "Avatar 3.x" headings are early avatar steps, not a product version.

### Avatar 2.5, phase 7: contextual HUD, neural operations, evolution layers, materials

- **Focus panel motion line**: what the figure's movement means right now ("concentrating — working out an answer
  or a plan") plus one real detail when there is one: the mission step (step 2 of 5), decisions waiting, recording
  time, looking things up. Never a percentage that doesn't exist.
- **Neural activity by operation**: the network shows where the work is — toward the head while concentrating,
  flickering nodes while reading sources, out to the limbs while executing, pulsing with each spoken word while
  explaining, the whole network beating as a lesson is stored — chosen by the real state.
- **Evolution 2.5**: the Evolution record now keeps four things apart: verified capability (the milestones), visual
  progression (the displayed stage, never ahead of the record), rendering modules (on and off at this stage), and
  your customisation on this device (preset, quality, view, sound), which never changes a capability.
- **Materials**: brushed-alloy streaks in the plate highlights (faded where they would shimmer), a tight polished
  glint and lighter worn metal along plate edges. Shader-only; no textures added.

### Avatar 2.5, phase 6: mechanical transformations

- **Transformation sequences** (`avatar3d-transform.js`): a group of armour plates opens in seven steps — unlock (the
  seams flash), separate, move, expose, reconfigure (the plates turn about their own centre), sync (one pulse as
  the parts align) and stabilise (a small settling shake) — and closes by playing the same steps backwards.
- Four sequences: **expose the reactor** (the chest plates part, the core comes forward, larger and brighter),
  **open the helmet** (the shell lifts back from the sensor head), **open the arms and hands**, **open the
  shoulders**. Inspecting the reactor, chest, helmet, a hand or the shoulders opens that part; inspecting anything
  else, Exit or Esc closes it. The Transform row in the inspection bar opens them directly.
- Only you start one: no JARVIS state opens the armour, so it never suggests work that isn't happening. Never
  during the startup assembly; Low performance and Reduced motion go straight to the end without animation.

### Avatar 2.5, phase 5: voice-reactive reactor and optional sound

- **Your voice moves the reactor**: while the microphone records, its measured level (RMS from an analyser on the
  same stream, about 20 times a second) brightens the reactor and the helmet sensors. Not played back, not stored,
  not sent; it stops with the recording. Reduced motion: no voice motion. JARVIS's own spoken replies still pulse on
  the word boundaries the browser reports (browsers don't expose the speech audio, so there is no amplitude to use).
- **Sound** (Projection controls → Sound, off by default, this device only, not part of presets): a very quiet low hum
  and short tones for real events (completed, a decision needed, a refusal, an error, the emergency stop, a lesson
  learned). Generated in the browser with Web Audio: no audio files, nothing licensed or downloaded. It fades out
  and stays silent while JARVIS speaks or you record; previews never make a sound; a standing warning or decision
  chimes at most once a minute; turning it off releases the audio device.

### Avatar 2.5, phase 4: recovery and performance profiles

- **3D recovery**: when the browser loses the GPU context, the 2D core shows at once. If the browser restores the
  context within 8 s, the same projection resumes (open projections kept). Otherwise the 3D view is disposed (every
  geometry, material, texture, render target, observer and listener) and built again, up to three times with
  growing waits; open projections reopen. **Rebuild 3D view** (Projection controls) starts over at any time. If the
  renderer couldn't load at all, it is retried when JARVIS is reachable again.
- **Profiles**: Auto, Quality, Balanced, Performance and the new **Low Power** (lower resolution, 20 fps, 15 on a
  phone, fewer particles, no floor reflection). Auto now has hysteresis: any change holds for at least 8 s, stepping
  back up after a step down waits 20 s and needs two good measurements in a row. Auto switches to Low Power only when
  the browser reports the battery at 20% or less and not charging (browsers without the Battery Status API report
  nothing, so nothing changes there).
- Diagnostics shows the profile and why (your setting, or Auto's reason), the last change with the measured average
  frame time, and GPU context losses and restores. No temperatures: browsers don't report them.

### Avatar 2.5, phase 3: schematic controls, the projection area, research sources

- Every open projection has controls: **Expand** (takes the projection area on its own; the others step aside until
  you collapse it), **Collapse**, **Minimise** / Restore, move to the **other side** of the figure, move **up** in the
  order, **Inspect** (the camera goes up close; Esc returns), **Details** (one sentence from its own data and where
  the data comes from), Pin and Close. Up to four at once, two per side; a third on one side moves to the other side
  instead of disappearing. They glide to their new places. None of these controls approves, runs or changes anything.
- **Projection area**: in the focus view on a computer, open projections widen the 3D canvas beside the figure; the
  camera pulls back only as much as the canvas needs. On a phone the list moves into the focus panel.
- **Research sources** projection: the question of your last research answer in this conversation at the centre and
  each cited site around it (green: the research tools really saw the page; amber: cited but not seen), with the
  number of searches and pages read. Built in the browser from that answer (sites only); nothing is fetched. Opens on
  its own in the focus view while JARVIS researches, or say "show me the sources".

### Avatar 2.5, phase 2: one event-to-visual map and personalities

- **`avatar-events.js`**: the one table that says, for every state, how the figure moves, which projection the focus
  view opens on its own, the one-off effect (the completion surge, the shield, the rebuild) and the sound cue for
  later. The dashboard and both renderers read it; the old per-file lists are gone.
- **Personalities** (ways of moving, never feelings): idle, listening, curious (researching, analyzing,
  experimenting), concentrating (understanding, reasoning, writing, coding, planning, learning), explaining
  (speaking), executing, waiting (your decision), confirming (a real completion), recovering (lifts its head as it
  comes back), alert, and **disagreeing**. Glances happen only at rest.
- **Disagreeing** has one real trigger: a new `permission.denied` or `egress.denied` entry in the audit log (your
  rules or the privacy guard refused something). It shows for about 3 s (amber, never red): one small head shake,
  the right hand up, the shield flares. Old refusals never replay on a reload. Your own "no" to an approval is not a
  refusal.
- Fix: a Music or system command refused by your rules now answers "Refused by your rules: …" (403) instead of an
  internal error; a bad argument answers with the reason (400).

### Avatar 2.5, phase 1: 360° inspection and projection presets

- **Inspect in 360°** (focus view → Projection controls → Camera): drag or arrow keys orbit the projection, the
  wheel, a pinch or +/− zooms, shift-drag, right-drag or two fingers pan, 0 resets. Six views (Front,
  Three-quarter, Side, Back, Above, Close) and twelve inspection targets (helmet, reactor, each hand, shoulders,
  chest armour, back, legs, neural network, orbitals, platform, projections). **Exit inspection** or Esc returns to
  the resting view (a second Esc closes the focus view). Gestures are captured only while inspecting, so the page
  scrolls and the chat types exactly as before. The camera eases while moving and jumps straight to the new view in
  Low performance and Reduced motion modes.
- New per-device settings: **Resting view** (Front, Three-quarter, Close), **Inspection speed** and **Diagnostics**.
  Diagnostics shows the renderer's own numbers (measured frame time, draw calls, triangles, quality, camera); no
  frame time is claimed while nothing is animating.
- **Projection presets**: Standard, Cinematic, Focus, Diagnostic, Immersive (opens the focus view) and Performance.
  Save the current settings as your own preset, then rename, update, duplicate or delete it (built-ins can only be
  applied or duplicated). Changing a setting shows "Custom — changed from …". Stored in this browser only, validated
  on load, at most 20; they change the look on this device and never what JARVIS can do.
- New files `avatar3d-camera.js` (the camera rig: plain maths, no imports) and `avatar-presets.js`. No new
  dependencies.

### Music and system abilities

- **Music** (`music` tool): what's playing (read), play / pause / skip / previous, play a playlist by name, Music's own
  volume. **System** (`system` tool): battery, power, Wi-Fi on/off, free disk, macOS version, uptime and volume
  (read, from macOS's own tools with fixed arguments); set the Mac's volume; Do Not Disturb on/off through two
  Shortcuts you make once ("JARVIS Focus On" / "JARVIS Focus Off": macOS has no scripting command for Focus).
- Reads never ask. Volume and Do Not Disturb always ask. Playback asks unless your policy has the new
  **music-controls** allow rule (added to the example policy; add it to yours to skip the question).
- **Say it in chat**: "pause the music", "skip", "play my Focus playlist", "what's playing", "how's my battery?", "set
  volume to 30", "turn on do not disturb". Recognised by rules and run through the permission engine directly, no
  model; changes that need your OK show the usual approval card; the reply is worded from the result.
- Also listed in the Trust Contract and available to the planner. Tested with a stand-in for the Mac apps; the
  scripts themselves run only on macOS.

### smarter answers from your ratings

- Your 👍/👎 now improves later answers: for a question similar to an earlier one (half of the meaningful words in
  common), the answer you rated helpful joins the prompt as a reference, and one you rated unhelpful as an approach
  not to repeat (at most one of each). Read from the conversation records on this Mac, so memory settings, exclusions
  and `forget` apply; it joins as conversation, so the usual privacy rules decide whether a cloud model may see it.
  The reply says "learned from an earlier answer you rated" when it happened (`learn.recalled` in the audit log).
- Ratings are now stored against the exchange's own record id.

### faster avatar loading

- The figure's meshes (body, head, hands, wireframe) are built in a background module worker
  (`avatar3d-worker.js`), so the dashboard stays responsive while the avatar loads. Measured on the cloud test
  machine (software rendering): the longest main-thread freeze during load fell from about 25 s to about 7 s. On a
  real GPU both are far smaller; what remains is shader compilation and cutting the armour plates. Without worker
  support the renderer builds the meshes itself, as before.

### Tier 7: autopilot (owner's choices)

- **Nightly self-checks**: once a day after 03:00 local time, the routing replay, recovery drills and benchmark
  comparison run in the simulation lab by themselves (sandboxed, no model calls).
- **Acting on its own lessons**: a strong, uncontested lesson about a model's answers (≥60% confidence) nudges how
  routing ranks the models already allowed for a request: −3 for one that keeps failing checks, +2 for a reliable one
  (quality counts 10 per point, so a nudge only breaks near-ties). The router still applies every privacy, budget,
  capability and availability rule first; in local-first mode a cloud model can never overtake a local one; a nudge
  can't make a model appear. Every nudge is logged, listed in the Evolution center with **Undo**, and never re-applied
  for the same lesson after you undo it. The emergency stop, tier 7 off or paused experiments clear all nudges.
- **Daily digest**: "Done on its own" in the morning briefing.
- Turn on from the Mac's terminal: `jarvis autonomy enable 6` then `jarvis autonomy enable 7` (stays on).
- Changes to JARVIS's own code stay propose-only.

### Tier 6: change trials

- **Change trials** (`jarvis/learn/trial.py`): name a branch or commit and JARVIS checks it and your current code out
  into two throwaway git worktrees under its data folder, runs the full test suite (results read from pytest's JUnit
  report) and the linter in each, and records an experiment: tests newly failing, newly passing, lint, commits and
  timings, with a recommendation. The worktrees are removed afterwards. A trial where the tests didn't run counts as
  proving nothing. It never switches, merges, commits, pushes or edits the running code, installs anything, or calls
  a model. Branch names are validated (no options, spaces or path tricks).
- Needs **autonomy tier 6**, which can only be switched on from the Mac's terminal; pausing experiments stops trials.
- **New terminal commands**: `jarvis autonomy [show | enable N | disable N | pause WHAT | resume WHAT]`,
  `jarvis lessons`, `jarvis trial REF [--baseline REF]`. The Evolution center's lab has a "Run change trial" box.
- Verified: a candidate that breaks a test is caught as "newly failing" and nothing is merged (tested on a throwaway
  repository); on this repository a trial of the previous commit ran 679 vs 669 tests with no regressions.

### E.V.O.L.V.E. visual and integration (phases F and G)

- **Projection Director** (`avatar3d-projections.js`): eight data-driven projections built in the existing scene and
  drawn by the existing render loop (no second renderer). Up to two at once (a pinned one stays; a data refresh
  replaces a projection in place), the camera eases wider and the avatar turns toward them, drag rotates, pointing at
  a node shows its label, closing disposes every geometry, material and texture. Modules: workflow map (missions,
  steps, dependencies, approvals), software architecture (JARVIS's real modules, imports, API routes, tables),
  knowledge network (memories, lessons, contradictions; the glow is labelled illustrative), globe (places named in
  your conversations, matched to a built-in list; no map download, nothing looked up), data (answer checks per
  model, verified outcomes per day, benchmark categories), timeline (real dates only; no invented forecasts),
  security shield (what JARVIS does alone / asks / never does; pending approvals stay outside the shield, marked
  not authorized; the emergency stop closes it), simulation (lab experiments, labelled as not real-world outcomes).
- **Opening projections**: from what you say ("show me my architecture", "show me what you're doing", "show me
  what you've learned", …: JARVIS opens it and describes it from its own data, no model), from Projection studio, and
  automatically in the focus view from the real state (executing → workflow, approval or emergency stop → security,
  experimenting → simulation, learning → knowledge). A caption bar under the avatar says where each one's data
  comes from, with Pin and Close.
- **Three new avatar states from real signals**: Learning (a lesson was just learned or reinforced; shown 4 s),
  Experimenting (a lab experiment is running), Analyzing (JARVIS is reading its own data for a projection).
- **Evolution center** (new section): last-30-day figures, lessons with evidence and confidence (confirm / reject /
  delete), the tournament table, the simulation lab, improvements (proposals), capability discoveries, autonomy tiers
  and pauses, and Projection studio. **👍/👎 on every answer.**

### E.V.O.L.V.E. backend: continuous intelligence (phases D and E)

- **Schema v9** (one migration, nothing existing changed): `outcomes`, `lessons`, `links`, `experiments`, `feedback`,
  `autonomy`.
- **Learning pipeline** (`jarvis/learn`), in the dashboard's existing maintenance loop. OBSERVE: new audit entries
  become outcomes (chat replies judged by the answer check, missions by their verifier, with time, errors and
  recovery); LEARN: fixed rules turn outcomes, your ratings and audit counts into **lessons** with evidence, a
  confidence that grows with observations, first/last seen, contradictions (opposite conclusions about the same
  subject → both "hypothesis") and expiry (no new evidence in 30 days → "outdated"). No model, nothing leaves the Mac,
  lessons hold counts and names of models/tools, never your text. You can confirm, reject or delete a lesson.
- **Feedback**: 👍/👎 per answer (`POST /api/feedback`), the main signal about quality.
- **Autonomy tiers 1–7** with pauses for learning, experiments and initiative; a tier works only with every tier below
  it; the emergency stop halts all of it. Tiers 6–7 are off and can't be switched on from a browser; changing
  autonomy is Mac-only (like device pairing).
- **Intelligence tournament**: per-model evidence (answer-check rate, median time, your ratings, benchmark categories).
  Its recommendation is a suggestion; routing never changes by itself, and a bigger model is not assumed better.
- **Simulation lab**: experiments with objective, hypothesis, baseline, criteria, environment, results and
  recommendation; three kinds only — routing replay (recorded data, no model calls), recovery drills (throwaway
  folders) and benchmark comparison (results on disk); one at a time.
- **Initiative**: three new proposal detectors (well-supported negative lessons, missions waiting more than 3 days,
  modules no test names), in the existing propose-only proposals; paused with "initiative".
- **Capability discovery** (recommendations only), **self-inspection** (modules, imports, API routes and tables read
  from JARVIS's own source), a **knowledge graph** (memories, lessons, missions, proposals, projects; near-duplicate
  memories and contradictions linked), and real data for eight projections (`GET /api/projection/<module>`).
- New tests (`tests/test_learn.py`), six of them added to the release gate.

### HUD on every section page

- **Section pages** (Command center, Missions, Decisions, Memory, Systems, Workspace) open with a HUD header: a large
  title with a section code, a scale line, and real stat tiles (missions active / queued / needing you / completed /
  failed; decisions waiting and how many are high-risk or send data out; memories, to confirm, records, memory on/off;
  systems OK and needing attention). Command center and Systems add live gauges for CPU, memory and health checks
  passing. Unknown values show "—". Pages use the full 1180 px width and sit flat (the 3D lean is Home only).
- **Decisions are gold** instead of cyan (the owner's palette: gold, silver, green, red).
- The model response trace fills from the right, so the newest call is always at the right edge.

### HUD: activity, system readouts, missions and decisions

- **Recent activity**: an icon ring per kind of event (problems in red, model events in silver), an **activity pulse**
  (real audit events per 5 minutes over the last hour, with the count), and new entries slide in.
- **System readouts around the projection** (desktop): bracketed HUD readouts with a turning status ring and a lit
  connector toward the figure, with a light travelling along it.
- **Missions**: a progress ring per mission on Home (real steps done of total; none when there are no steps).
- **Decisions**: a pulsing risk ring (red for high-risk) and how long it has really been waiting. No countdown:
  approvals have no deadline, so none is shown.
- All of it holds still in Low performance and Reduced motion.

### HUD module: Systems panel, 3D depth (Iron Man direction)

- Chosen with the owner: Iron Man HUD direction, live visuals, 3D depth, HUD detail; constant motion in Normal
  effects, none in Low performance or Reduced motion. Started with the Systems panel.
- **Systems is a HUD module**: three radial gauges (CPU load per core, memory used, models online) with tick rings
  and turning inner rings, values from real telemetry and model availability ("—" and no arc when unknown); a
  **model response-time trace** of the recent real model calls from the audit log (cloud in gold, local in silver);
  compact rows for health, missions, Claude usage and spend. Built once and updated in place, so the rings never jump.
- **3D depth**: on wide screens the side columns lean toward the projection, with a slight mouse parallax in Normal
  effects. The perspective lives on each column (not the page grid), so the focus view's projection stays in place.

### automatic Ask / Research / Do

- **No more mode buttons** (owner's choice): JARVIS works out what a message is (`jarvis/intent.py`). Instant rules on
  this Mac handle the obvious cases ("remind me…", "latest news on…", "how do…"); only when they are unsure does one
  tiny call go to a model **on this Mac** (`local_only`, never the cloud, free). Anything unclear or any failure is
  answered as a question, which takes no action and sends nothing to the web.
- **One tap before anything outward**: research ("Looks like it needs the web…") and tasks ("Looks like a task: JARVIS
  drafts a plan, and nothing runs until you approve it") show *Research it / Plan it · Just answer · ✕* above the bar;
  Esc closes it. Questions are answered straight away. Tasks still only become a plan that waits for approval, and
  research keeps its existing consent rules.
- New endpoint `POST /api/route` (same authentication and request checks as every other API call).

### UI 5: frosted glass, short activity, docked command bar (owner's spec)

- Chosen with the owner (Vision Pro calm + Marvel JARVIS fine lines + HUD structure, subtle glow, balanced layout,
  moderate density): **rounded frosted-glass panels**, glow only on edges and titles, body text plain white, gold
  first with silver secondary, green for healthy and red only for real problems. No blur in Low performance or
  Reduced motion (solid dark glass instead).
- **Recent activity on Home reads in short lines** ("Reply · Sonnet · 5.5 s", "Answer checked ✓"); the full log keeps
  every detail, and hovering a line shows it.
- **Bottom area**: "What matters now" is a slim banner at the top of the centre column; suggestions are one row of
  small chips (swipeable on phones); the **command bar is docked at the bottom** — the field fills it, Ask / Research /
  Do and Quick / Balanced / Deep are small pills inside it, Send at the end.
- Replaces the UI 3 panel look and the UI 4 see-through draft (meters and the wider command center stay).

### UI 3: holographic glass panels

- **Panels** are lit glass that matches the projection: a gold hairline edge, depth and inner glow, a faint scan
  texture, brighter corner brackets, a divider under each header, and a light that catches the top edge now and
  then (Normal effects only; still in Low performance and Reduced motion).
- **Meters** where a real ratio exists: models online, spend against the monthly budget, and CPU load, memory and
  storage in the command center. Unknown values show no meter. Styled through coarse data attributes, no inline
  styles (CSP unchanged).
- **Command center**: the open system spans the full width, its readings in two columns on wide screens.
- **Composer, mode controls and navigation** follow the same language: a lit console input with a focus glow, a gold
  Send, glowing selected tabs and modes, and a glowing current section (a top bar on phones).

### Avatar 3D, step 5: chamber, controls, stage 5, quality presets

- **Projection chamber** (`avatar3d-environment.js`): platform markers and a turning segmented ring; orbital systems
  around the knees (stage 1), diagonally around the torso (stage 2), around the chest (stage 3) and a counter-rotating
  pair above the head (stage 5), their speed following the real activity level; a depth grid and projection boundary
  (stage 3); ground light that follows the reactor, a soft contact shadow and a faint haze.
- **Floating panels** in the focus view only, with the same real status lines as the systems bar (intelligence,
  missions, health: counts and states, never message text or memories).
- **Projection controls** in the focus view (saved per device with the display settings): intensity, quality
  (Auto / High / Balanced / Low), particles, animation, reactor, orbit speed, orbitals on/off, environment holograms
  on/off, motion; a list of visual modules and the stage each needs; **state preview** marked "PREVIEW — not live",
  at most 10 s, ended by Esc or by any real alert.
- **Quality presets**: High (sharper, wireframe, reflection), Balanced, Low (no reflection pass, no aura shell, fewer
  particles); Auto starts Balanced and steps down when frames are slow, up when there is room. Every shader is
  compiled at startup so a change never stalls an animation. Panels and settings redraw only when they change.
- **Evolution: five stages** — Foundational, Advanced, Intelligence, Evolved, and **Signature Projection** (every one
  of the 19 milestones verified, including 30 days reliable and 100 verified missions). Definitions v4 (audited);
  the displayed stage can be capped at any earned stage on this device.

### Avatar 3D, step 4: materialise and dematerialise

- **Reconstruction particles** (`avatar3d-particles.js`): each particle belongs to a point on the body. During the
  startup sequence and any reconstruction they stream in from a cloud over the platform and land as the build edge
  reaches them; during the real emergency stop they lift off and disperse as the body erases from the head down.
  Drawn only while a sequence runs (2,400 on desktop, 800 on phones).
- **Startup order** now follows the brief: platform, scanning ring (riding the build edge), particles gather, legs,
  torso and armour, head, then the circuitry lights, the sensors wake, the reactor ignites and the orbitals
  synchronise.
- **Dematerialisation on the real emergency stop** (Normal mode only): the figure leaves, the platform and orbitals
  stay; releasing the stop rebuilds it. The 3D renderer reports these phases to the state machine (`lifecycle`).

### Avatar 3D, step 3: the reactor and the neural network

- **Reactor** (`avatar3d-reactor.js`), added in depth around the existing rings, rotor, hex cage and arcs: a plasma
  core sphere, an inner ring of twelve segments, two tilted gyroscope rings (stage 2), eight radial energy pathways
  with pulses travelling outward, six mechanical supports locking it into the chest plates (dark alloy with lit
  edges), a swirl of energy particles (not on phones), and a golden confirmation ring that expands only when a task
  really completes. Every level is the real reactor level of the current state.
- **Neural network** (`avatar3d-neural.js`): nodes at the head, neck, sternum, shoulders, elbows, wrists, hips, knees
  and ankles, linked from the reactor to the head, hands and feet; stage 3 adds branches and more nodes. Pulses run
  along the links with the shared flow; brightness follows the real thinking level, and the reactor-to-limb links
  light only while a mission is really executing, coding or verifying. It bends with the arms and turns with the head.

### Avatar 3D, step 2: helmet, hands, layered armour, gold identity

- **Gold identity restored** (owner's brief): warm gold, gold-white and amber for every state; red only for a genuine
  error; teal removed from the projection, the dashboard and the background walls (dashboard tokens back to gold).
- **Faceless adaptive helmet** replaces the sculpted face: a smooth faceplate with a centre keel, a recessed visor
  band with raised rims, framed by the dark alloy shell. The visor holds a sensor array (nine sensors) and an
  internal scanner: dim when idle, brighter when listening and speaking, a working pattern driven by the real
  thinking level, the scanner while researching or verifying, a shutter for blinks and narrowing, warning and
  error colours only from those states.
- **Articulated hands**: their own fine mesh with four three-segment fingers and a thumb, joint knuckles, a heel
  and wrist pistons; per-finger plating with gaps at every joint; fingers curl by the real pose (resting, working,
  open on success) and flex slightly in Normal mode only; the hands turn naturally at the wrist.
- **Layered armour**: pauldrons over the shoulder plates, upper-arm, hip, thigh and knee plates added to chest,
  abdomen, forearm and shin; engraved micro-panels and small sensor points inside every plate; elbow and knee
  hubs and wrist rings; a fine holographic wireframe over the body from stage 2 (not on phones).
- Fixed: the joints now carry local changes, so plates really vent and fingers really curl on bent arms.

### Avatar 3D, step 1: module split and the central state machine

- **Central state machine** (`static/avatar-state.js`): every state the projection shows now passes through one
  place, with priorities, minimum display times, a 4 s success, a fall-back to idle when activity stops being
  reported, lifecycle phases (dormant, materializing, dematerializing) and flagged 10 s previews. Unit-tested in Node.
- **Queued missions no longer look active**: they show the idle look and a "Queued — nothing is running yet" card.
- `JarvisAvatar` gains `previewState`, `endPreview`, `profile`, `preview` and `lifecycle`.
- The 3D renderer is split into modules: shaders and geometry move out of `avatar3d.js` (1,372 → 916 lines);
  dead torso helpers removed. No visual change.

### Avatar 3.5.2: a refined face

- The face is reworked to read as an elegant sculpted mask rather than a crude one: almond-shaped eyes with lifted
  outer corners, a slimmer nose with a soft tip, higher cheekbones with soft hollows, a cleaner jaw and chin, and a
  fine drawn mouth line in place of sculpted lips (which broke up at this mesh resolution).
- Lit as a form: soft wrap light and an even fill on the face, with the hologram rim softened there so small
  features no longer get cartoon outlines; no panel grid across the face.
- Fixed a dark patch under the nose (the helmet plate behind the head showed through; plates now draw before the
  glowing body), a line down the forehead (the rear crest seam showing through), and a streak from the inner spine
  reaching into the head. The helmet now sweeps behind the face instead of capping the forehead.

### Avatar 3.5.1: the eyes, made visible

- Glances now move the eye glow with the head (the shift was too small to see); a horizontal scan line with a moving
  light crosses the eyes while researching or verifying.
- On a genuine error the eyes turn deep red and narrow (the white-hot centre is dropped); the hexagon alert shield no
  longer covers the face, so the eyes stay visible during warnings and errors.
- `JarvisAvatar.eyes` (read-only) reports what the eyes show: glow level, openness (blinks, narrowing), glance offset,
  scan and speech pulse, used by the browser checks.

### Avatar 3.5: sculpted face

- **A face, sculpted subtly in the light body** (owner's choice, replacing the smooth head): brow ridge, eye
  sockets, cheekbones, nose bridge and tip, lips, chin and jaw line. The head is meshed at a finer resolution
  than the body so the features hold up close.
- **Eyes that glow with the real state**: brighter while listening and speaking, dimmer when idle, red only on a
  genuine error; they blink, narrow on warnings and glance (from the existing idle-liveliness logic); a scan light
  sweeps across them while researching or verifying.
- **Speaking**: the face brightens on each spoken word, from the browser's real word-boundary events; nothing moves.
- The aura shell is no longer drawn in the floor reflection (lighter frames); the head crest line no longer runs
  down the face.

### Avatar 3.4: character detail and alloy armour

- **More detail, growing with evolution** (rich now, maximum at stage 4): helmet crest ridge, swept rear fin and temple
  pods; finger grooves, knuckle points, forearm bands and a double wrist band; knee caps, thigh and shin lines;
  glowing soles that light the floor; fine circuit traces with travelling pulses (a finer second layer from stage 3);
  energy veins spreading from the core, pulsing with the reactor. The face stays smooth.
- **Inner energy**: a faint skeleton and nerve network inside the translucent body that brightens only while JARVIS
  is really thinking; it bends with the arms and the head.
- **Particles and aura**: energy wisps peeling off the shoulders and head (Normal mode only), and a soft outline glow
  around the whole figure (not on phones).
- **Dark alloy armour, key plates** (owner's choice): chest (two plates around the core), abdomen, shoulders,
  forearms, shins and a helmet shell over the crown and back. Cut from the figure's own surface so they hug the sleek
  body, with smooth borders and glowing orange seams; they assemble during the startup sequence.
  - Seams brighten while JARVIS is really working; plates part slightly to vent light during coding, executing and
    reasoning (Normal mode only).
  - A hexagon energy shield flares over the body on a real error or warning, and stays faint while an error lasts.

### Avatar 3.3: gestures, live data wall, screen wall

- **Gestures from real states only**: speaking opens the right hand toward you, coding and executing raise both hands
  to work (a small alternating motion in Normal), waiting for approval raises the right hand, a completed mission
  opens both hands; every other state rests. Arms bend at shoulder and elbow in the vertex shader; the suit seams and
  panels stay attached. The unposed wireframe overlay and the arm energy tubes are removed.
- **Live data wall**: the background streams now follow real signals: the orange stream is CPU load, the teal stream
  memory use, the upper stream lights and pulses only while a model is answering, the left network brightens with
  active missions. Unavailable values stay at a resting glow (never invented).
- **Screen wall in the focus view**: seven glowing panels curving around the figure, like a command-centre video wall
  (decoration only; its scan light stops in Low performance and Reduced motion; hidden on phones). The backdrop is
  more opaque so the dashboard no longer shows through.
- The focus view's evolution button no longer clips its label.

### Avatar 3.2: athletic light body, suit contours, warmer dashboard

- **Sculpt refined**: V-taper (lats, trapezius, deltoids), chest, abdominal wall, biceps and forearms, quadriceps,
  knees, closed hands and a swept-back faceless head.
- **Glowing suit contours** drawn in the shader along the body (sternum, collar, chest, flanks, waist, hip lines,
  elbows, wrists, knees, ankles, leg seams, spine, crest over the head) with energy rising along them; they brighten
  with each verified stage. The square panel grid on the body is toned down.
- **More sparkles** (1600 on desktop, 600 on phones), some teal, a few brighter.
- **Dashboard palette follows the figure**: headings and identity accents warm light-orange, healthy status teal-green
  (all text still meets WCAG AA); the background data wall is brighter.

### Avatar 3.1: light-body figure (from the owner's reference)

- **Sleek figure made of light** replaces the armoured robot (owner feedback: "looks like a toy robot", "too much
  gold/orange"): one smooth humanoid sculpted as a distance field in code and meshed once at load, glowing orange
  with teal-green hands, fine surface panelling, flow lines along the body and sparkles drifting off the surface.
- The metal armour, studio reflections and scene lights are gone (lighter startup on the Intel Mac); the reactor now
  sits in the chest of the figure; halo, crown, thought constellation, aura, satellites, surge and startup assembly
  are kept and re-placed around the new body.
- **Floor light strips** (orange and teal arcs) on the platform, and a faint **data wall** behind the dashboard:
  flowing orange/teal ribbons and network graphs (still in Low performance, Reduced motion and Subtle projection).
- State colours re-tuned to the orange family; red stays reserved for genuine errors.

### Avatar 3D (early step): real armour, startup assembly, live data aura

- **Lit metal armour over the hologram** (owner's choice: sleek cinematic armour, metal + hologram): polished gold
  and graphite plates (chest, abdomen, ribs, collar, layered shoulders, arm guards, helm with crest and guards) with
  glowing seams; reflections from a small studio generated in code (no downloaded assets); key and rim lights and a
  reactor light that follows activity; a gold surround framing the reactor.
- **Startup assembly**: platform powers on, the hologram body forms, plates fly in and lock, the reactor ignites last,
  the HUD powers up. Once per browser session, Normal mode only; any key or click skips it.
- **Live data aura**: four bands filled by real CPU load, memory use, active missions and decisions waiting (hidden
  when unavailable); explained in the focus view.
- **Thought constellation**: one node per real stage of the current answer, linked in order, fading after the reply.
- **Reactor surge**: a gold shockwave across the dashboard when a mission really completes (not in Low performance or
  Reduced motion).
- Free models were researched: no permissively licensed sleek full-body armour exists; the closest full-body pack
  forbids redistribution, so the armour is sculpted in code.

### Avatar 2.2: cinematic rendering

- **Bloom**: a small post-processing pipeline written for JARVIS (no extra library): bright edges and cores glow,
  with a slight lens fringe and fine grain. Falls back to direct drawing if the device can't do it.
- **Machined armour**: procedural panel seams and fine detail lines on every armour surface, with light running
  through them; far faces are drawn dimmer, so the figure reads in depth rather than as a flat glow.
- **Gold-white grading**: darker gold interior, crisp pale-gold and white edges, much less orange.
- **Sculpted faceless helm**: one forward-sloping faceplate with a recessed sensor band and a thin centre ridge
  (the brow/cheek frame that read like a face is gone); a V-tapered torso; an inner frame with circuitry seen
  through the armour; calmer shoulders and platform.

### Avatar 2.1: livelier projection, more ways to evolve

- **More alive at rest** (owner's choice): glances toward the message box or the side panels every ~6–11 s,
  mechanical sensor blinks, sparks circling the optical sensors, deeper breathing. Only in the resting look; any
  real activity takes over at once.
- **Helm**: taller crest, forehead and temple plates, hexagonal sensor housings; sensors sweep while researching,
  pulse while reasoning and narrow on warnings.
- **Reactor**: hex frame and spokes; a distinct pattern per state (calm, counter-spin, scan, beat, surge, stutter).
- **Body**: shoulder and elbow joint rings and actuators that work while executing, neck cables, side vents.
- **Environment**: denser neural lattice, light shafts, a polar floor grid and a base glow (all behind the figure).
- **New milestones** (definitions v3, 19 in all): benchmark pass (≥80% of scored tasks), 5 / 25 / 100 verified
  missions, `jarvis doctor` all green and `jarvis mac check` passed (within 30 days), 30 days reliable (no health
  failure or failed recovery drill). `jarvis doctor`, `jarvis mac check` and `jarvis drill` now record their
  outcome for this. Stage thresholds: 5 / 10 / 15 milestones.

### Avatar 2.0: living intelligence projection

- **Faceless helm** with optical sensors, layered visor, internal gear rings and a visor scan line (no mouth).
- **Reactor assembly**: independent rings, a rotor and discharge arcs around the chest core; brightness follows
  real activity and pulses with each spoken word the speech engine reports.
- **Living movement**: breathing, head that attends to the message box, scans while researching and tilts while
  reasoning; arm actuators; smooth ~1 s transitions.
- **Environment**: neural lattice (more of it at higher stages), research data streams, vertical scan ring,
  platform energy pulses, rotating platform geometry, and eight system satellites showing live status.
- **New states from real signals**: listening while you type, speaking, warning (amber), recovery, halted,
  unknown; red only for a failed task, a lost connection, or a failing database/audit log.
- **Projection focus view** (click or Enter on the projection; Esc to leave), clickable satellites, a task hologram
  with the real current step, **Projection intensity** setting, and an **Evolution record** with a per-device
  display stage.
- **Evolution v2**: new stage names, versioned definitions, an earned stage holds 7 days after a capability stops
  verifying (owner's choice), all changes audited.
- Fix: the floor reflection now turns with the figure; satellite picking accounts for the reflection pass.

### Armoured avatar: sentinel helm with knight elements

- New helmet (owner's choice: sentinel faceplate + knight elements): crest blade over the crown, angled V-brow,
  two glowing eye slits that brighten while JARVIS speaks or writes, nose guard, cheek plates with vents, jaw
  plate, swept side guards with sensor discs. Faceted plates for a forged-armour look; calm, slow movement.
- Full armour from the start: layered collar, cuirass with pectoral and abdominal plates, three-lame pauldrons,
  bracers and elbow guards. Evolution now adds only light and energy (glowing seams, circuits, crest energy,
  halo, crown of light), still unlocked only by verified milestones. The 2D fallback follows the same rule.

## 0.19.3 — A harder benchmark, and fixes for what it found (owner-approved after a test on the Mac)

**Proven on the Mac (bench home, local models, ×5):** the new hard set went from 7 to 9 of 17 tasks passing (20261107-141713-local → 20261107-163941-local, verdict MERGE, no new failures; planning-slot 1→5/5 is a clear change). Core + extended: 108 of 110 runs, all 22 scored tasks still passing (20261108-014415-local). The Mac was busy in all three runs (time only). Merged exactly the tested commit (a5569e0); later work on `smarter-v2` (G–J) and `compute-v1` (F) is not in this release. Also: a lookup test used a fixed date and failed from 8 November; it now uses today's date (test only). The briefing test could clash with the dashboard's real-clock background loop after 08:00; it now stops that loop first (test only).

Built on `harder-bench-v1`. Fixes the two gaps the hard set found, where even a perfect model failed.
- **"Overdue or due today" lists both.** Any time window in the question ("today", "tomorrow", "next 3 days") now
  wins over "overdue", and the window's list already includes what's overdue. "Overdue" on its own is unchanged.
- **A small memory is seen whole.** With 150 memories or fewer, a chat answered on this Mac also gets every
  memory the keyword search missed, oldest first, so "take the cat to my mum's" can use "my flight to Lisbon is on
  14 August". Bigger stores use keyword recall as before.
- **Privacy unchanged.** The extra memories are marked local-only: the egress gate can't send them to Claude, and
  they're only added when the answer is sure to stay on the Mac (Quick, local routing, no Claude configured, or
  hybrid rated "simple"). Answers that go to Claude get only the matching memories, still with consent. New
  Privacy gate test: `the_whole_memory_never_goes_to_claude`.
- **A. Reminders are looked up whenever the message asks what's due** ("overdue", "due", "to-dos"; not "due to").
  The hard-set baseline showed "overdue or due today" looking at the calendar only.
- **B. Free slots of the length you ask for are worked out exactly** ("a free 90-minute slot", "an hour", "two
  hours"): JARVIS lists the gaps long enough, or says there are none and gives the longest. The model had called
  11:00–13:15 free.
- **C. A step can only use outputs earlier steps really produce.** "{{steps.1.urgent_item}}" from a writing step
  (which only gives "text") is sent back to the planner once. Only results with a fixed shape are checked.
- **D. A plan that breaks a "don't" in the request becomes a question.** "Save it as summary.md, but don't create
  any new files" now asks which you meant, instead of asking you to approve the write.
- **E. Look before acting.** A task that refers to an existing appointment, meeting, call or reminder ("my dentist
  appointment tomorrow") is planned with the calendar and reminders looked up first (read-only), and the planner
  is told to ask when the request doesn't match what's there. The looked-up data is private like folder contents:
  it reaches Claude only through the privacy gate, with your consent, as before.

### The hard benchmark set (from `harder-bench-v1`)

- **17 held-out hard tasks** (`--set hard`): reasoning ×4, coding ×3 (one is fixing a bug), memory ×3, planning ×3,
  tool use ×2, recovery ×2. Core + extended were all passing (110/110), so they could no longer show a gain or a
  loss. Answers were worked out by script (the five-person puzzle has exactly one solution). Benchmark only: no
  change to how JARVIS answers.
- `--set all` still means core + extended (24 tasks), so earlier runs stay comparable.
- Writing them found **two gaps in JARVIS itself**, which fail even with a perfect model: "overdue or due today"
  leaves out the reminder due today, and keyword recall can't link "take the cat to my mum's" to the flight memory.
  Recorded, not fixed here.
- Baseline of 0.19.2 on the hard set: 38 of 85 runs, 7 of 17 tasks (20261107-141713-local).

## 0.19.2 — Direct answers, one file means one write (owner-approved with the merge rule unmet; see below)

- **"Am I free?" gets a yes or no.** The calendar facts now say "FREE: yes, you're free then" / "BUSY: no, you're
  not free then", and the model is told to answer a yes/no question with yes or no first. On the owner's Mac the
  facts were right but the model hedged ("a free block, but that's not exactly what you're looking for") or only
  said it "couldn't find any events" (planning-free 1/5).
- **One file means one write.** A plan that writes the same file twice is sent back to the planner once to combine
  everything into one write (writes to other files still go to the owner's approval, as before). Real failure: decisions.md written once per meeting, so
  the second write replaced the budget decision, and the owner was asked to approve twice.
- **A task that only saved a file says what it saved** ("Saved decisions.md:" and the text), instead of finishing
  with nothing to read.
- **Proven on the Mac:** planning-free 1/5 → 4/5 and tooluse-decisions 3/5 → 5/5 (subset ×5); full set ×5 with
  `--run-code`: **110 of 110 scored runs passed, no failures** (planning-free and tooluse-decisions 5/5). The Mac
  was busy during the full run (load peak 14.4), which affects time, not pass/fail.
- **Merge rule not met, owner approved anyway.** `bench compare` said DON'T MERGE only because the net gain was +1
  task, under the +2 rule. +2 was unreachable: planning-free was the only task failing at the task level before this
  branch. No new failures, ≥5 runs. The owner was told this and replied "merge".

## 0.19.1 — Smarter answers: a model for maths and code, exact calendar facts, warm start, Mac checkup (owner-approved after a test on the Mac)

- Proven on the owner's Mac (full benchmark ×5, local models only, $0): **103/110 passed vs 88/110** for 0.18.3; verdict MERGE (net +2 tasks, no new failures). Coding 13→20/20, reasoning 5→9/10, planning 12→16/20; everyday tasks faster (planning ~20 s vs ~50 s). Merged branches `checkup-v1`, `smarter-v1` and `bench-load-v1`.
- Still failing: `planning-free` 1/5 (the facts reach the answer, but the model hedges instead of saying "you're free"), `tooluse-decisions` 3/5 (the planner sometimes writes one file per meeting).

- **"Tomorrow" is worked out by JARVIS, not the small model.** Asked late on Fri 6 Nov about tomorrow, the local
  model looked up Friday, found nothing and made up a meeting (benchmark `planning-free`, 0/5). JARVIS now reads
  "today", "tonight", "tomorrow", "the day after tomorrow" and weekday names from the Mac's clock and makes the
  calendar lookup cover those days, and says so in the lookup notes. The label now names the days covered
  ("Calendar, Sat 07 Nov", not "Fri 06 Nov–Sat 07 Nov" for a single day).
- **Warm start:** when the background service starts, the local models are loaded in the background, fastest first,
  so the first question after login doesn't wait 10–30 s. Nothing is generated or sent; the emergency stop skips
  it; recorded in the audit log (model names and seconds).
- **`jarvis checkup`:** a look-only health check of the Mac: macOS version, disk space, clutter (Downloads, Trash,
  caches), CPU load and the busiest apps, memory and swap, battery condition, days since the last restart, startup
  helpers and Time Machine, each with plain advice. `--updates` also lists waiting macOS updates (the only check
  that uses the network, via Software Update). Fixed system commands only; nothing is installed, deleted or
  changed; the audit log gets counts only.
- **A model just for maths, logic and code** (branch `smarter-v1`): a local model listed with
  `capabilities = ["reasoning"]` answers maths, logic and code questions that are answered on this Mac, and nothing
  else: everyday chat, planning, tools and Quick mode never use it, and it isn't loaded at start. Missing or failing,
  JARVIS uses the usual local model. On the owner's Mac, qwen2.5:14b-instruct passed 30/30 maths/code runs vs 20/30
  for the 7B (coding-duration 0/5 → 5/5, reasoning-schedule 1/5 → 5/5), at about 2–3× the wait. When Claude is
  unavailable for such a question, the local fallback also uses it instead of the fastest model.
- **Calendar and reminder facts worked out by JARVIS:** above the looked-up list, the model now gets exact lines:
  the first event of each day, FREE/BUSY for a time the message names ("between 2pm and 3:30pm"), every clash
  (overlapping events), and for reminders, which are overdue and which fall in the window asked about ("next 7
  days", "tomorrow"); reminders outside that window are counted, not listed. Real failures fixed by this: the 13:00
  lunch called the first commitment with a 09:00 standup listed; a clash listed but never called one; a reminder due
  in 9 days listed as "within 7".
- **Nothing left out when combining notes:** when an instruction asks to list/combine items the data labels
  ("Decisions: …"), JARVIS checks each one is in the written text and retries once locally, naming the missing ones;
  anything still missing is shown in the step output ("possibly_left_out"). Real failure: "the budget is approved"
  dropped from a combined decisions list.
- **Time Machine date:** when `tmutil` gives no date, the checkup reads it from Time Machine's own settings
  (`defaults read`, read-only), and otherwise shows what tmutil said.
- **Benchmarks say how busy the Mac was:** Each run records the Mac's 1-minute load average at the start, the busiest point and the end (with the number of
  cores). The report shows it, with a warning when more than half the cores were busy with other work: answers
  were slower than usual, but pass/fail still counts. `bench compare` notes any busy run. Runs from before this
  have no figures and still work. No change to JARVIS's behaviour.

## 0.19.0 — Holographic dashboard, Quick/Balanced/Deep, live Claude replies (owner-approved after a test on the Mac)

- Merged the holographic dashboard work (branch `claude/funny-allen-ygy8kk`, reviewed) with 0.18.1–0.18.3. Sections
  below list what it adds.
- **Quick stays quick:** Quick mode asks for the fastest local model, and the 0.18.3 "stronger local model for maths,
  logic and code" upgrade respects that (it applies to Balanced and to answers kept local by routing).
- Review: replies stream only after consent; local-only data stays local in every mode; the emergency stop kills a
  streaming reply; Three.js 0.160.0 is byte-identical to npm; CSP unchanged; release-gate items only added.
- Tried by the owner on the Mac in a test copy (port 8766) before release.

### Cinematic core: 3D hologram, gold-white environment

- **3D holographic core** (Three.js r160, served from the Mac, pinned by hash): translucent gold-white figure with
  rim light, scan lines, energy pulses along its circuits, a beam and rising dust from the projector, a floor
  reflection, orbit rings, and a materialisation from the pad upward. Every part is replaceable; armour, circuits,
  pauldrons, fins and halo appear only as verified milestones unlock (same rules as before). Falls back to the 2D
  core without WebGL.
- **Gold-white palette**: deep black, metallic gold, champagne and warm white; amber for activity and warnings.
  Metallic-edged glass panels; sections materialise when shown.
- **Living environment** (owner-approved): a gliding perspective grid floor, breathing light and drifting dust.
- **Display → Effects** is now Normal / Low performance / Reduced motion.

### Dashboard theme v2: holographic command deck

- The hologram stands on a projector pad in a beam of light, its torso dissolving into the beam; orbit rings pass in
  front of and behind it; soft glow, scan-line texture, and a flicker as it powers up.
- Wide screens: the eight systems sit around the hologram as HUD callouts with leader lines (chips on smaller screens,
  a swipeable strip on the iPhone).
- Glass panels with a lit top edge, one colour rule (amber = JARVIS, cyan only for listening/speaking, orange/red for
  problems), "What matters now" as a slim alert strip, the message box docked at the bottom, Recent activity as a
  colour-coded timeline with plain wording for more events.
- Fix: the status pill said "All systems nominal" while a health check was failing; it now says how many systems to
  check. iPhone header is more compact.
- Presentation only: no change to what JARVIS does. Still no background animation; Effects Off and reduced motion
  still make everything still.

### Phase 2: holographic core and command center

- **Holographic core**: an amber humanoid hologram (layered SVG, energy motes) with the reactor as its chest core.
  13 states, each from a real signal (the live chat stage, missions, decisions, voice, errors). Helmet, visor and face
  are replaceable parts.
- **Evolution from evidence**: 12 milestones checked against live state; the core gains circuits, plates, pauldrons,
  then fins and a halo as more are verified (Core → Development → Advanced → Mature). Each first verification is in
  the audit log and listed in Command center → Diagnostics. Nothing is awarded for activity.
- **Command center** (sidebar, More menu, or the eight status chips on Home): System health (CPU load, memory,
  storage, network route, services), Intelligence (model, local or cloud, latency, tokens/s), Missions, Security,
  Communications, Research, Personal operations, Diagnostics. Unmeasurable figures say "unavailable".
- **Adaptive layout**: the core steps back during conversation, research and missions, and leads in voice.
- **Display → Effects**: Full / Reduced / Off. Reduced motion is respected; animations pause when the page is hidden.
- iPhone: the Quick/Balanced/Deep choice is one button in the tab row, so the message box keeps its width.

### Phase 3a: faster chat

- **Claude replies appear as they're written.** Chat used Claude Code's whole-reply JSON output, so nothing showed
  until Claude had finished. It now uses `stream-json` with partial messages; every safety flag is unchanged (tools
  off, no MCP, no slash commands, settings isolated, API-key variables removed, prompt over stdin). With a stand-in
  CLI writing 36 words at 50 ms each, first words went from 1.83 s to 0.02 s; real numbers need the Mac.
- A closed page or the emergency stop kills the Claude process mid-reply (also before its first word), and is never
  treated as a model failure that would try another model.
- **Quick / Balanced / Deep** in the Ask box. Quick: the fastest local model and no extra local call before answering
  (hybrid used to make one for every message). Balanced: unchanged. Deep: the strongest approved model (Claude when on,
  after your consent as always) and longer answers; without one it answers locally and says so.
- **Stop, Copy, Regenerate, Retry, Edit and resend** on chat messages; Esc stops a reply.
- **Live stages** (understanding → looked up → context → writing with which model → checking), in the reply, the
  status pill and an Activity list on each answer. Real stages only; no model reasoning is shown.
- Release gate: new streaming tests added to Privacy, Emergency stop, Resource limits and Honest reporting.
- Docs: Outcome Engine is merged (0.18.0), Mac apps exist, proposals exist (propose-only).

## 0.18.3 — Stronger local model for maths, logic and code (owner's choice)

- When a chat answer will come from your Mac anyway (local-first, or kept local), word problems with numbers,
  puzzles, other hard-looking requests and requests to write code go to the strongest local model (e.g.
  qwen2.5:7b) instead of the fastest (llama3.2:3b). Everyday chat stays on the fast one.
- Only the choice between local models changes: whether anything may go to the cloud is never affected, and no
  extra call is made. Recorded in the audit log as `model.reasoning_local` (no question text).
- Proven on the owner's Mac (5 runs each side, pooled): tasks passing 2 → 4 of 6, no new failures, 0 Claude calls.
  reasoning-flour 1/5 → 5/5 (clear change, p=0.048); coding-dedupe 2/5 → 5/5 (could be luck, p=0.17);
  coding-roman 5/5 → 3/5 (could be luck, p=0.44). Those answers take about 2–3× longer.

## 0.18.2 — Private data folder (owner-approved)

- On every start JARVIS makes its data folder readable by you only (`drwx------`) and its database files
  `-rw-------`. Before, a folder made with the Mac's default permissions (`drwxr-xr-x`, `jarvis.db -rw-r--r--`)
  could be read by other accounts on the Mac. A new database is created private from the start.
- It only ever removes access for others, only on files you own, and never follows a symlink. A change is recorded
  in the audit log (`privacy.files_made_private`, modes only).
- `jarvis doctor` has a new "Data folder privacy" check that warns if the folder becomes readable again.

## 0.18.1 — Fairer benchmarks: pooled before/after, 5-run minimum, re-scoring

- `bench compare` pools several runs per side (`--before A B --after C D`). The merge rule now also needs at least
  5 runs of every compared task on each side; otherwise the verdict is **INCONCLUSIVE** (exit code 4). Each changed
  task is marked *clear change* or *could be luck* (two-sided Fisher exact test). The Benchmarks page shows the same.
- `bench rescore RUN_DIR`: after correcting a text check, re-applies it to saved answers (`results.rescored.json`,
  original untouched) so old and new runs are judged alike; `bench compare --rescored` uses it. Refuses tasks whose
  prompt, setup or non-text checks changed.
- `planning-free` also accepts "free time" ("you have a free time slot between 2pm and 3:30pm" means yes). The
  `reasoning-flour` check stays as it is: the task asks for the number on its own line, so that's JARVIS's to fix.
- No change to JARVIS's behaviour.

## 0.18.0 — Redesigned dashboard, Projects for you, Outcome Engine, JARVIS.app, fingerprint at sign-in

Tested on the owner's Mac (Intel, macOS 14.1.1) on an isolated copy of their data before release; release gate
passes on GitHub's macOS Intel, macOS and Ubuntu machines. Database v6/v7 → v8 on first start (adds proposals
and project ideas); back up first, older versions refuse a v8 database.

- **Dashboard redesign** (stages 0–9c): readable contrast and touch targets; sidebar / tab bar sections (Home,
  Workspace, Missions, Decisions, Memory, Systems, Briefing & ideas); a reactor whose colour follows JARVIS's real
  state; missions with honest pause/cancel and uncertain steps you can settle; cinematic mode; display settings
  and keyboard shortcuts; Emergency stop on every page.
- **Projects for you**: the local model suggests growth/side projects and JARVIS projects from your own messages
  and memories, each with the quotes it's based on and a first plan; optional polish with Claude sends only the
  idea list, after you approve.
- **Outcome Engine, answer checks, grounding check**: pooled over 6 runs per task on the owner's Mac, local models
  only: main 14 → 17 of 22 tasks passing (memory-preferences 0/6 → 6/6, recovery-injection 0/6 → 6/6), no task
  worse. Coding self-test included, off by default.
- **Benchmarks, Trust Contract and improvement ideas pages** (from 0.17.15).
- **JARVIS.app** launcher (`jarvis app install`) and the **fingerprint-at-sign-in** model, below.

### Fingerprint at sign-in, then only for the dangerous few

- **Mac:** once Touch ID is set up, the dashboard asks for Touch ID when you sign in (per browser session, at most
  12 hours; a restart of JARVIS signs you out). Setting up Touch ID signs that browser in. While signed out, nothing
  is shown except the header, and the sign-in box has its own **Emergency stop** (stopping never needs signing in).
- **iPhone:** Face ID at sign-in as before (stays signed in up to 30 days, unchanged).
- **One tap once signed in:** ordinary approvals and consent, running a plan, idea decisions, settling an uncertain
  step, rejecting anything.
- **Still a fresh fingerprint bound to that exact request:** releasing the emergency stop, editing, deleting or
  forgetting memories, removing a phone, pairing a phone and adding/removing Touch ID keys (Mac), and approving a
  **high-risk** (tier 4) action.
- Every action still needs your approval exactly as before; only how you confirm it changed. Trust page, security
  notes and setup guide updated. Recovery unchanged: `jarvis touchid reset --yes`.

### JARVIS.app launcher

- `jarvis app install` makes `~/Applications/JARVIS.app`: double-click (or click it in the Dock) to open the
  dashboard. It's a tiny AppleScript applet compiled on your Mac with Apple's `osacompile` (no download, no new
  packages) and runs exactly what `jarvis open` runs, with the same `uv`, repository and data folder as the
  background service. No link or password is stored in it; if JARVIS isn't running it says how to start it. It
  never starts, stops or changes JARVIS. `jarvis app uninstall` removes it; neither command touches an app that
  JARVIS didn't make.

### Coding self-test

- Opt-in (`[coding] self_test = true`; off by default). When a local chat answer contains Python code for a
  coding request, the local model writes 3–6 test cases from the request alone (never seeing the code), the code
  runs on them in the macOS sandbox, and on any failure the model gets one chance to fix it. The fix is kept only
  if it passes at least as many cases. The reply says how many cases ran and passed.
- Sandbox for this: no network, no writing outside a temp folder, no reading files in the home folder (only the
  Python installation), no starting programs, 10 s, empty environment. Nothing runs on other systems.
- `jarvis bench run --coding-self-test` benchmarks with it on.
- CI also runs on `outcome-fixes-*` and `coding-selftest-*` branches.

### Answer checks

Built from real wrong answers a small local model gave on the owner's Mac. Benchmarked before any merge.
- **Chat answer checks** (deterministic, one local retry at most, never for Claude answers): saying "I don't
  have access to your calendar" right after a lookup; ignoring an explicit format ("end with the number on its
  own line", "finish with four lines in the form…"); puzzles with several conditions get one self-check.
  Audit: `chat.answer_check` with counts only, no content.
- Puzzles with several conditions count as hard (hybrid: Claude is offered, with consent as always).
- **Writer:** a planted instruction in the data is ignored *and* the owner's task is still done; a refusal of
  a harmless task is retried once locally. The plan is fixed before data is read, so this changes no
  security boundary.

### Outcome Engine v1

Merged into main only after the benchmark (core + extended, 3 runs, same models) shows net +2 tasks, no new
failures and Claude calls within +25%.
- One local "goal reader" call picks lookups and rates difficulty (hybrid: one local call instead of two).
- No downgrades: clear signs of hard work (code, "prove", "debug", money/legal/medical, several questions, long
  requests) always route as hard.
- Profile memories (name, diet, family, preferences, anything marked important) are always used, not only when
  words overlap. Closes the `memory-preferences` gap found by the extended benchmark (the oracle now passes all 24).
- Grounding check: calendar/reminder answers that mention a time not in the data get one retry, then "Unverified".

- Review fixes: the grounding retry is always local (it can never turn into a consent question); profile
  memories respect exclusions added later, and "I'm …" counts only for facts ("I'm vegetarian", not "I'm
  meeting Sam").

## 0.17.15 — Benchmarks page, Trust Contract, improvement ideas

### Owner-approved extras

- Two owner-approved changes:
  - Deciding on an improvement idea from the phone needs Face ID (added to the phone's Face ID list).
  - The header's Help, Briefing, Benchmarks, Trust and Ideas sit in one **More** menu; the emergency stop stays
    on its own, always visible.

### Benchmark page and failures at a glance

- **Benchmarks page** (`/bench`, linked from the dashboard header; works on the paired iPhone): every run with
  its score per category, one run's tasks with each failure's checks, lookups, approvals and answer, and a
  before/after under the merge rule with any two runs. Read-only; only run folders inside `bench-results` can be
  opened; same sign-in as the rest of the dashboard.
- Reports start with **Failures at a glance** (one block per failing task), and the terminal prints it after a
  run, so failures no longer need a separate script to dig out.
### Trust Contract

- `jarvis trust` and a **Trust** page in the dashboard (phone too): what JARVIS does on its own, always asks
  about, and never does, plus where your data may go and what it may spend. Generated every time from the live
  permission engine (it asks the engine about every action, inside each approved folder), policy, privacy
  settings, grants and budget, so it can't drift. Built-in promises name the release-gate item that proves them;
  a test fails if one names an item that doesn't exist.
### Improvement proposals

- JARVIS studies its own record and suggests improvements: benchmark tasks failing in most runs, actions that
  keep timing out or failing, routine actions you always approve (with the exact policy rule you could add
  yourself), actions you keep rejecting, calendar answers still unverified after a retry, frequent fallbacks.
  Deterministic counts from the audit log, approvals and the latest benchmark; no model, nothing leaves the Mac,
  no private text in the evidence.
- Propose-only: deciding (dashboard **Ideas** page, phone too, or `jarvis proposals approve|reject|done ID`)
  records your answer and changes nothing. `jarvis proposals brief ID` turns an approved idea into a task brief
  for Claude Code that follows the engineering constitution. A rejected idea returns only if its evidence doubles.
- Database v7: `proposals` table.

## 0.17.14 — Review fix

- `bench compare`: a run whose start time has no zone no longer breaks the ordering (read as local time).

## 0.17.13 — `bench compare` orders runs by real time

- With no folders given, `bench compare` picked the two latest runs by folder name (local clock time). On the
  owner's first before/after the clocks went back mid-run, so the "after" folder sorted first. Runs are now
  ordered by their recorded start time, offset included.

## 0.17.12 — `jarvis bench compare`

- `jarvis bench compare [BEFORE AFTER]` (no folders: the two latest runs) puts two benchmark runs side by side
  and applies the owner's merge rule: at least +2 tasks passing, no new failures, Claude calls up at most 25 %,
  and no unapproved change in the "after" run. A task passes when more than half its runs pass. Tasks whose
  definition changed, or that were skipped in either run, are listed as left out, never compared silently.
  Exit code 0 = meets the rule, 3 = doesn't.

## 0.17.11 — Planner understands joined action names

- A plan step written as `"tool": "apps", "action": "mail.draft"` (or `"tool": "mail.draft"`) is read as
  `mail.draft`; a small model gave up on the email task after writing it that way. Only actions that exist are
  ever matched, and the error for a truly unknown one now shows the expected spelling.

## 0.17.10 — Daylight saving, due dates, unrequested steps (from the benchmark on the owner's Mac)

- **Fixed (benchmark):** the stand-in Mac placed "tomorrow 9:00" with today's UTC offset, so across the
  1 Nov clock change it became 8:00 and even a perfect answer failed. Times are now local wall-clock times.
- **Fixed:** whole-day calendar lookups had the same offset mistake across a clock change.
- Reminder lookups say how far off each one is ("OVERDUE by 2 days", "in 5 days") and the lookup carries the
  current time, so a small model doesn't have to do date arithmetic (it called overdue items not overdue).
- A plan that opens an app the owner didn't ask to open is sent back to the model once with the reason
  (a model kept adding "open Mail" before drafting an email: one more approval for nothing).
- `planning-free` also accepts "free slot" / "free between" as a yes (and "no free" as a no). Its task hash
  changes, so compare it only between runs made with this version.

## 0.17.9 — Lookups that ask the right question (from the benchmark on the owner's Mac)

- Calendar lookups cover whole days: asked "am I free 2–3:30, and what's first tomorrow?", the model looked up
  only 2–3:30 and missed the 9:00 meeting.
- A Reminders lookup for a list that doesn't exist or has nothing open (models invent "overdue", "upcoming")
  falls back to every list, and says so in the lookup's label.
- Planner wording: `reminders.list` says to omit the list for due/overdue questions; `apps.open` says it is only
  for opening an app (a model used it to "draft the email").

## 0.17.8 — Chat lookups explain themselves (found by the benchmark on the owner's Mac)

- **Found:** in the first real benchmark run every planning task failed because no lookup ran at all, and the
  reason was thrown away. The lookup step now records why it looked nothing up (no lookup words, the model
  chose none, its reply wasn't usable, a lookup was unknown or missing dates…). Chat replies carry these as
  `lookup_notes`, and benchmark results store them.
- The lookup step accepts what small local models often send: JSON wrapped in prose, a bare list, or
  `"calendar.events"` as one name. It still only ever runs read-only lookups, each checked by the permission
  engine as before.

## 0.17.7 — Calendar reads without `whose` filters (still found on the owner's Mac)

- **Fixed:** 0.17.6's bounded `whose` questions still timed out on the owner's Mac (macOS 14), although the
  calendars hold only ~170 events and each calendar read by itself in at most 10 s. The script now bulk-reads
  each calendar's start, end and repeat rule, picks events that overlap the range (or repeat and began before
  it ends) in the script, and reads the other details only for those. At most 200 events; hitting the cap is
  reported in `incomplete`.
- New test runs the real calendar script under Node against a fake Calendar, so the filtering logic is
  exercised on every platform, not just syntax-checked on macOS.

## 0.17.6 — Calendar speed fix (found on the owner's Mac)

- **Fixed:** reading the calendar asked Calendar for every event that started before the end of the range, i.e. the
  whole history (plus subscribed holiday/birthday calendars). On the owner's Mac that took 73 s, then timed out.
  Now two bounded questions per calendar: events overlapping the range, and repeating events that began before
  it. Events found by both are kept once; a calendar that can't be read is reported as `incomplete`, never hidden.
- `jarvis mac check` shows each calendar's counts and time, so a slow one is easy to spot.

## 0.17.5 — Real-Mac CI, extended benchmark, a chat lookup fix

- **GitHub Actions** runs `jarvis gate` and `jarvis drill` after every push on an Intel Mac, an Apple-silicon Mac
  and Linux (free for public repos; read-only; actions pinned to commits). First run on macOS 26 (Apple silicon):
  gate PASS with all macOS-only checks run, drills 10/10.
- New macOS-only tests (required on a Mac, allowed to skip elsewhere): the Mac-app scripts compile (`osacompile`,
  no permission prompts), the LaunchAgent file passes `plutil`, the code sandbox blocks network and outside writes.
- Tests now find refusing stand-ins for `security`, `osascript` and `launchctl` first on PATH, so no test can
  reach the real Keychain (the doctor test could read it on a Mac), apps or services.
- **Extended benchmark set** (12 tasks: Roman numerals, de-duplication and duration parsing with hidden tests;
  HTTP 418 research; remembered preferences; changed facts; calendar clashes; reminders due this week; a file
  turned into an Apple Note; an email draft; a missing file; a mass-delete request). The 12 core tasks are
  unchanged (`--set core` stays the default).
- **Fixed (found by the extended set):** chat didn't look up the calendar for "clashing appointments in the next
  three days" — the lookup word check knew "appointment" but not "appointments", nor "days". Plurals and words like
  clash, overlap, due, diary now count.
- **Known gap recorded, not fixed:** remembered preferences aren't used unless the words overlap (keyword recall).
  Kept as an Outcome Engine target.

## 0.17.4 — Recovery drills

- **`jarvis drill`**: 10 recovery drills on a throwaway JARVIS (deleted afterwards; real data, Keychain and apps
  never touched): real process crashes right after / just before a one-time action and during a repeatable step;
  emergency stop pressed from another process; four callers racing for one approval; a damaged checkpoint; a
  tampered audit log; a lost database restored from an encrypted backup; a second process trying to take over a
  running task. All 10 pass here. Tests show each protection drill fails when its protection is disabled.
- Building the drills turned up two bugs in the drills themselves (a crash trigger firing one step early; a check
  expecting a trailing full stop JARVIS doesn't store), fixed; no JARVIS bugs found.

## 0.17.3 — Flight Recorder timeline

- **Timeline** for every task (dashboard: Timeline on a mission; Terminal: `jarvis trace TASK_ID`): the request,
  plan, each permission decision, approvals and who gave them, which model did what (on the Mac or Claude), each
  action, the verification and the outcome, in order, with problems flagged and the audit log's integrity shown.
  Read-only; built from what JARVIS already records, so it holds fingerprints, not your private text.
- Three of its tests joined the release gate (privacy, corrupted state, honest reporting).

## 0.17.2 — Release gate and docs sync (M-B)

- **`jarvis gate`**: runs the full test suite and the linter, then checks 12 security items (normal completion,
  prompt injection, permission bypass, interrupted tasks, duplicate actions, network limits, corrupted state,
  resource exhaustion, privacy, honest reporting, emergency stop, budget guard) against the named tests that prove
  each. A failing, skipped or missing covering test fails the gate; security can't be outweighed by anything else.
  Fails closed: its first run failed because of a test-name mismatch rather than passing. Checked with a
  deliberately broken permission test (in a throwaway copy): the gate failed and named it.
- `ruff` 0.6.9 added as a pinned development dependency (dev only, no cost) so the linter result is the same
  everywhere; `[tool.ruff]` targets Python 3.12.
- Docs synced with the code: README status and "On the Mac" column (from what was actually run on the Mac),
  architecture sections for Mac apps, chat lookups, live replies, benchmark and gate; security threats added in
  v0.17; roadmap with milestones M-A/M-B/M-C and where each signature system stands; project description.

## 0.17.1 — Live replies, Help, welcome

- **Live replies:** a local model's answer appears word by word as it's written (`/api/chat/stream`; first words
  in well under a second instead of waiting for the whole reply). Display only: same answer, routing, lookups and
  privacy rules. Claude's answers still arrive whole. Emergency stop cuts a reply off at once (the partial text is
  kept with a note); a closed page stops generation and is never mistaken for a model failure (no retry elsewhere).
  Falls back to the plain request where streaming isn't available.
- **Help → "What can I say?"**: example requests by mode, only those this JARVIS can do (calendar ones only with the
  Mac apps); tap one to put it in the box. A one-time welcome card explains the panels.
- **Fixed:** tests reached the real Mac on the owner's machine (one restarted the background service via launchctl,
  one read the real Calendar). An autouse fixture now stands in for both; the dashboard also stops its background
  loops before shutting down. Found by running the suite on the Mac.
- Small phones: header buttons tighten and wrap so Emergency stop stays fully on screen at 320–430 px.

## 0.17.0 — Mac apps, smarter chat, Briefing 2.0, benchmark (milestone 1)

- **Mac apps** (Calendar, Reminders, Notes, Mail drafts, opening apps) through macOS scripting. Reading is tier 0;
  adding or changing is tier 1 and asks first with an exact preview. Nothing sends, deletes or changes settings.
  Repeating events are expanded (python-dateutil 2.9, pinned below 3). `jarvis mac check` tests access read-only.
- **Smarter chat:** for questions about your calendar, reminders, notes or files, the local model picks up to three
  read-only lookups (the question never leaves the Mac for this), run through the permission engine; results go to
  the answering model as private file content (the privacy gate asks before Claude sees them). Change requests get
  a **Make a plan** button instead of being done in chat. The persona's can/can't list follows.
- **Briefing 2.0:** today's calendar and reminders due or overdue, read on the Mac.
- **Benchmark (Intelligence project, milestone 1):** `jarvis bench` with 12 core tasks in 7 categories, run in
  throwaway data folders with made-up data and a Mac-apps stand-in, no standing permissions, a check that fails any
  unapproved change, a $0-budget requirement, sandboxed code checks, and a baseline file for the Claude app scored
  by the same checks. Results record JARVIS version, git commit and each task file's hash. See `bench/README.md`.
- Planner now knows today's date and time. Approval cards describe Mac-app actions in plain words.
- Not yet run on the Mac: the Mac apps' real scripts, smarter chat with real models, and the first benchmark run.

## 0.16.4 — Phone preview (simulation) and in-page dialogs

- **Phone preview:** `demo/` builds the real dashboard with a simulated JARVIS running in the browser, plus a
  Simulation lab (task editor, permissions explainer, example commands). Published as a private link to try on the
  iPhone without the Mac. Clearly labelled; no AI, no Mac, no network. See `demo/README.md`.
- **Dashboard:** browser `confirm()` / `prompt()` replaced by in-page dialogs (they're unreliable in the iPhone
  Home Screen app and blocked in embedded previews). **Emergency stop is now one tap** with no reason box:
  stopping is always safe; releasing still asks.

## 0.16.3 — Polish (no new features)

- A broken `jarvis.toml` or `policy.toml` now gives a plain message naming the file, the problem and how to put
  back the previous copy, instead of a Python traceback. Same for a database that can't be opened or is newer
  than the code.
- Docs checked against the code: corrected the supply-chain line (cryptography is a runtime dependency; the
  vendored QR library and pinned whisper.cpp are listed), the architecture diagram, "not built yet" lists and
  background-process notes; roadmap in release order; Mac setup guide now starts with "update, then
  `jarvis doctor`", and covers Tailscale's first-time Serve approval and the microphone prompt.
- Code: one config-file writer instead of two; tests lint-clean (ruff), with the shared dashboard fixture in
  `conftest.py`. 1 new test.

## 0.16.2 — iPhone Safari fixes (found by research, not yet on a real iPhone)

- **Fixed: notifications would never have arrived.** Apple's push service rejects VAPID subjects that point at
  localhost (`BadJwtToken`); JARVIS used `mailto:jarvis@localhost`. It now uses its own Tailscale address
  (`https://<mac>.ts.net`), never your email, and refuses subjects Apple would reject.
- **Fixed: notification permission prompt.** It's now requested first, straight from the tap, as iPhone Safari
  requires.
- **Safety net for Face ID prompts:** Safari before iOS 17.4 refuses passkey prompts not made directly from a tap
  (JARVIS fetches a challenge first). If that happens, JARVIS shows a "Confirm with Face ID" button and retries
  from that tap. Checked in a headless browser made to refuse the first prompt (pairing and approval).
- Setup steps: the Home Screen app signs in separately from Safari (once, with Face ID).
- Security review of everything reachable from the phone: every action needs a signed-in device, pairing and
  Touch ID changes are Mac-only, Face ID covers every approval-type action, and actors can't be spoofed by device
  names. Hardening: device names are cleaned (printable, one line, 60 characters); sign-in challenges (requestable
  before sign-in) are capped at 256 in memory. 2 new tests.

## 0.16.1 — Pre-Mac review and `jarvis doctor`

Reviewed the untested v0.13–v0.16 code against whisper.cpp v1.9.4's source and Mac behaviour:
- **Fixed:** voice readiness used any answer from whisper-server; it now uses its `/health` endpoint (503 while
  the model loads) and treats its `{"error": …}` replies as errors.
- **Fixed:** restarting the background service (launchd sends SIGTERM) left whisper-server running. JARVIS now
  shuts down cleanly on SIGTERM (verified with a real signal).
- **Fixed:** a negative or malformed `Content-Length` left a dashboard connection waiting forever. Now 400.
- **Hardened:** HTTPS (Web Push to Apple, web fetch) falls back to macOS's CA bundle if Python's own store is
  empty (some uv-installed Pythons), instead of failing silently. Push failures are now in the audit log.
- whisper.cpp setup builds for CPU (Metal off): steadier on Intel Macs.
- **New: `jarvis doctor`** checks database, audit log, disk, models, dashboard, service, backups (decrypts the
  newest), HTTPS trust, Touch ID, the full phone path (proves Tailscale keeps the Host header), voice (speaks and
  transcribes a test sentence on the Mac) and the briefing, with a fix for each problem.
- Fixed a flaky voice test. 9 new tests.

## 0.16.0 — Milestone 6: voice

- **Push-to-talk** (Talk button, Mac and iPhone): the page records, converts to 16 kHz mono WAV and JARVIS
  transcribes it with **whisper.cpp on the Mac** (`whisper-server`, loopback only, pinned v1.9.4). Audio is held in
  memory only; the audit log records length and timing, not words. The transcript is sent like typed text.
- **Voice replies** toggle: answers read aloud with on-device voices only (cloud voices are skipped).
  Tapping Talk or pressing Escape interrupts speech; it never cancels a task. Voice can't approve anything.
- `jarvis voice setup | enable | disable | status | test FILE`; JARVIS starts/stops `whisper-server` itself.
- `Permissions-Policy` header (microphone only, for JARVIS itself).
- **Fixed:** on phones the v0.15 Briefing button pushed **Emergency stop** partly off-screen (≤390 px wide). The
  header now wraps; checked at 320–430 px. The command box uses the full width on phones.
- 11 new tests (whisper.cpp protocol stand-in). Headless browser with a fake microphone: record → WAV (16 kHz
  mono) → transcript sent. Real whisper.cpp was not built in this environment: **verify on the Mac**.

## 0.15.0 — Proactive JARVIS

- **Morning briefing** (default 08:00): what needs you, what finished or failed since the last briefing,
  what's in progress, system problems, unconfirmed memories and Claude usage. Built from live data when opened
  (dashboard **Briefing** button, the phone notification, or `jarvis briefing`) and never stored, so `forget`
  and task deletion still remove everything. Notification text: "Your morning briefing is ready".
- **Quiet hours** (default 22:00–07:00): notifications are held back; the briefing covers the night.
- **Reminder** once when a decision has waited over an hour; **alert** when a health check turns bad
  (generic wording, rate-limited).
- `[proactive]` config section (validated). Notifications can open a specific JARVIS page (own paths only).
- 11 new tests; headless-browser check of the briefing on desktop and phone sizes. Not yet checked on the Mac.

## 0.14.0 — Touch ID for Mac approvals

- Optional **Touch ID** for the Mac dashboard (Systems → Touch ID). Once set up, approvals, consent, running
  plans, releasing the stop, memory edits/forget, pairing a phone and adding/removing Touch ID keys need a fresh
  Touch ID bound to that exact request. Stopping never needs it.
- `jarvis touchid list | remove ID | reset --yes` (recovery if Touch ID stops working; audited).
- The dashboard page now lives at `http://localhost:PORT` (passkeys can't belong to an IP address); the old
  127.0.0.1 link redirects there.
- Shared passkey code for phone and Mac (`remote/passkeys.py`). Migration v6 (`devices.kind`).
- 8 new tests; headless-browser run with a virtual passkey (set up → approve with Touch ID → unverified refused).
  Phone flow re-checked. Not yet checked on the real Mac.

## 0.13.0 — Milestone 7: iPhone companion

- **Use JARVIS from your iPhone** over your private Tailscale network. `jarvis remote enable` runs
  `tailscale serve` (tailnet only; never `funnel`); the dashboard still listens only on 127.0.0.1.
- **Passkey pairing:** a one-time code (QR on the Mac, 10 minutes, single use, stored hashed) → a Face ID
  passkey on the phone. Sign-in with Face ID gives a Secure HttpOnly SameSite=Strict session (12 h idle,
  30 days max). Pairing more devices is Mac-only.
- **Face ID on every approval:** approvals, consent, running plans, releasing the stop, memory edits/deletes/
  forget and removing devices need a fresh passkey assertion bound to that exact request. Phone actions are
  audited as `user:phone:<name>`. Stopping never needs Face ID.
- **Private notifications:** Web Push (RFC 8291 + VAPID, matches the RFC test vector) with generic text only
  ("JARVIS needs a decision", "A task finished"); batched and rate-limited; Apple's push service only.
- **Home Screen app:** manifest, icons, service worker; phone-sized layout.
- `jarvis devices [revoke ID]`; dashboard Systems → Phone (pair, remove, notifications, sign out).
- Database migration v5 (devices, sessions, pairings, push subscriptions). Vendored qrcode-generator 1.4.4 (MIT).
- New tests: passkeys with a software authenticator, remote routing and step-up, push, CLI with a stand-in
  `tailscale`; a headless-browser run with Chromium's virtual passkey (pair → approve with Face ID → sign-in page
  in a fresh browser). Not yet checked on the real Mac and iPhone.

## 0.12.0 — Reliable multi-process core

From the v0.12 discovery audit (confirmed issues were reproduced before fixing):
- **Fixed (high): two processes could run the same task.** A second process's start-up recovery took over a
  task the background service was still running, ran a step twice and failed the task. Tasks now have
  leases (migration v4) with a heartbeat. Recovery only reclaims expired or dead holders, and `jarvis run`
  reports when another process owns a task.
- **Fixed (high, privacy): private text kept in the append-only audit log.** Free text is now stored only
  as fingerprints (paths/URLs stay readable). `forget` also deletes matching finished task history, and
  `jarvis tasks delete ID` exists. `secure_delete` + WAL checkpoint leave no copy in the database files.
  Entries written before v0.12 are left as they were (by choice).
- **Fixed: the emergency stop didn't stop Claude work in progress.** Claude Code now runs as a tracked
  process group, killed on stop (pressed in any JARVIS process) or deadline. The task pauses with the step
  ready to re-run.
- **Fixed: web fetch DNS rebinding.** Connections are pinned to the checked address; ports 80/443 only; no
  embedded credentials; ≤5 redirects; one overall deadline (drip-feeding servers are cut off).
- Claude Code no longer loads `~/.claude/settings.json` (`--setting-sources project`), so `env`/`apiKeyHelper`
  can't switch it to API billing.
- Approvals are claimed atomically (no double spend); an approval claimed just as Stop is pressed is restored.
- Backup passphrase written to the Keychain via stdin, not the command line.
- Tests made hermetic (no real Keychain or port 8765). The SearXNG search tool is off by default and only
  offered if SearXNG is reachable. Python ≥ 3.12.
- Documentation corrected against the code (README status and verification columns, roadmap model policy,
  architecture, development test table, security claims, Mac setup).
- 21 new tests.

## 0.11.0 — Milestone 8: always-on service, health, encrypted backups

- `jarvis service install|uninstall|status|restart|rotate-link`: a per-user macOS LaunchAgent starts the
  dashboard at login and restarts it after a crash (never as root). `jarvis open` opens the dashboard;
  the link stays the same across restarts so it can be bookmarked.
- Health checks (database, audit chain, local and Claude models, disk space, backup freshness) every
  minute, shown in Systems; changes are recorded in the activity log.
- Encrypted backups (AES-256-GCM, scrypt-derived key; passphrase in the macOS Keychain and shown once so you
  can save it): `jarvis backup now|list|verify|restore`. Each backup is test-restored (decrypted, checksums,
  SQLite integrity check, audit-chain check). Daily automatic backups after the first manual one; the newest
  14 are kept. A restore keeps your current files as `*.before-restore-*` and re-applies deletions made since
  the backup, so deleted memories and conversations don't come back.
- `[backup]` config (auto, keep, dir). New dependency: cryptography.
- 9 new tests.

## 0.10.1 — Ask about missing files before planning

- Found on the Mac: a request naming a file that doesn't exist was planned and run, then failed at step 0.
  JARVIS now checks the files a plan would read *before* showing it, and asks "I can't find X. Did you
  mean …?" with close matches from that folder. The planner also sees the folder of any file you mention.

## 0.10.0 — Documents

- `doc.read` / `doc.info`: PDF (page ranges, scanned-PDF detection, password-protected and corrupt files
  reported clearly), Word .docx (headings, paragraphs, tables), and text, Markdown, CSV, JSON and HTML.
  Size and decompression limits; text marked untrusted.
- `fs.move` (move/rename, Tier 2 so it asks first): never overwrites; the destination must be inside an
  approved folder and not protected, checked even after approval; crash reconciliation.
  Approvals show "Move to: …".
- Planner: knows the document and move actions, and before planning sees the file **names** (not
  contents) in approved folders your request mentions, so it can plan real renames and filing.
- Writing steps accept much larger documents; routing picks a model whose context fits.
- `jarvis allow-folder PATH [--remove]` and `jarvis folders`: give JARVIS read access to a folder
  (changes there still ask). It refuses your whole home folder, the disk root and JARVIS's data folder.
- New dependency: pypdf (pure Python, BSD).
- Not yet: OCR for scanned PDFs, old .doc, Pages, spreadsheets.
- 12 new tests using generated PDF and Word files.

## 0.9.0 — Web research

- Research through Claude Code's own web tools on your Pro plan (no Docker). Only `WebSearch` and
  `WebFetch` are available, pre-approved, with `--permission-mode dontAsk`, so any other tool is
  refused. No file, shell or add-on tools.
- Evidence: JARVIS reads Claude Code's event stream and records the searches made and pages read.
  A cited source is marked **verified** only if the research tools actually saw it; invented
  citations are flagged.
- Research asks before sending your question (your "ask every time" rule) and never falls back to
  a local model. At the usage limit, task steps wait for the reset.
- Dashboard **Research** tab with clickable sources (✓ verified / flagged); `jarvis research "…" [--deep]`.
- The planner can use `research.web`, so `jarvis do "Research X and save a sourced brief to my notes"`
  works. The verifier fails a brief that doesn't cite at least one verified source.
- Haiku by default; `--deep` uses Sonnet. Research is offered only when Claude is enabled.
- 8 new tests.

## 0.8.0 — Milestone 5: memory

- Long-term memory stored only in JARVIS's local database: original conversation records (a
  searchable archive) kept separate from short derived memories with provenance (explicit or observed,
  confidence, source record, created and verified dates, importance).
- Learning: "remember that…" in chat, the Remember box, or `jarvis remember` creates confirmed
  memories. The LOCAL model notices facts you state and saves them as *unconfirmed* until you
  confirm them. Extraction never uses a cloud model.
- Recall: relevant memories are added to chat context (category `memory`, so cloud use still asks you),
  labelled confirmed or unconfirmed and possibly out of date. Replies show "used N memories".
- Control: Memory panel (search, confirm, edit, star, delete, "forget all of this") and
  `jarvis memory list|search|confirm|delete|forget|export`.
- Managed deletion: deletes remove the memory and its index entry; deleting a record removes memories
  derived from it; tombstones stop deleted or corrected facts from being re-learned (saying it again
  yourself overrides); the audit log never holds memory text.
- `[memory]` config: enabled, extract, exclude_topics (never stored), recall_limit.
- Keyword (full-text) search; search by meaning with local embeddings is planned.
- 12 new tests.

## 0.7.2 — Remember sign-in problems

- If Claude Code reports it isn't signed in, JARVIS remembers that for 10 minutes, even across separate
  `jarvis` commands, and routes locally without asking you to approve a send that can't happen.
  `jarvis use-claude on` clears it, tests again, and explains how to sign in.

## 0.7.1 — Fix repeated approval prompts

- Found on the Mac: after you approved sending a question to Claude Haiku, Haiku failed, JARVIS tried
  Sonnet, and Sonnet demanded a second approval, which the CLI reported as an error.
- Consent is now bound to the exact content and the provider (Claude), not the specific model.
  If a call fails, the approval is restored, so the same content can be retried or sent to another
  Claude model without asking again. It still can't be reused for different content or another
  provider, and it is used up once a call succeeds.
- When JARVIS falls back to local, the note now says why the cloud call failed.
- The CLI handles more than one approval prompt in a row.

## 0.7.0 — Stretch Claude usage

- Routing mode `hybrid` (set by `jarvis use-claude on`): a local model rates each chat message.
  Simple ones stay on the Mac, medium ones go to Claude Haiku, hard ones to Claude Sonnet. Planning
  always uses the strongest model; writing steps in tasks use Haiku.
- Usage limits: Claude Code's limit message is recognised and its reset time parsed. Until then
  JARVIS doesn't call Claude at all. Chat and planning answer locally and say so; background task
  steps wait for the reset (no attempt spent) and resume automatically.
- Fallback to local happens only when Claude is genuinely unavailable, never to get around your rules
  (local-only data, budget).
- Usage meter: Claude calls and tokens over the last 5 hours and the reset time, on the dashboard and in `jarvis models`.
- 9 new tests.

## 0.6.0 — Claude as JARVIS's brain

- `claude_code` provider: Claude through the official Claude Code CLI on your Pro login. It runs with
  tools, MCP and slash commands disabled, no session persistence, an empty working folder and API-key
  variables stripped; prompts go over stdin. Usage limits and login problems are reported as
  "unavailable", so JARVIS falls back to local models and records why.
- Routing mode `best` (most capable model first, local as fallback) alongside `local_first`;
  `prefer="auto"` follows the mode.
- Consent: with "ask every time", private content goes to Claude only after you approve that exact
  request. Dashboard chat shows **Send to Claude / Answer locally**; dashboard planning waits for
  your decision and plans locally if you reject it; the CLI asks inline.
- `jarvis use-claude on|off` edits `jarvis.toml` safely (validated, backed up) and checks that Claude
  Code really answers using a probe with no private data.
- Fixed: `Dashboard.shutdown()` hung if the server had never started.
- 12 new tests.

## 0.5.1 — Dashboard redesign

- Holographic HUD in Stark gold & red with an animated arc-reactor core in the centre that changes
  with JARVIS's state (idle, thinking, executing, needs-you, stopped, offline).
- Plain-language status headline ("Executing · Step 2 of 3 · Save the brief"), stat readouts, a
  prominent Decision card with the exact content to be written, and segmented mission progress.
- Technical detail (tool calls, IDs, full paths) moved behind "details"; files shown by name.
- Plans appear in the conversation feed; the activity ticker opens a full log.
- Arc blue is reserved for "needs your decision", red for danger, green for verified results.
- Bundled Rajdhani display font (SIL Open Font License, `server/static/fonts/OFL-Rajdhani.txt`);
  nothing is loaded from the internet.

## 0.5.0 — Milestone 4: dashboard

- `jarvis dashboard`: the local command centre. Ask/Do command panel, background planning with plan
  review, missions with live step progress and verified evidence, approvals showing the exact content
  to be written, models, budget and audit-chain status, readable activity feed, emergency stop and
  release. Works at phone width.
- Security: loopback only, secret launch link to HttpOnly SameSite=Strict cookie, Host check, CSRF
  header and Origin check, strict CSP, text-only rendering.
- Task ownership (`runner`): the dashboard and CLI never drive the same task.
- Chat (`ask`, dashboard) prefers the fastest suitable model.
- 12 new tests; checked in headless Chromium at desktop and phone sizes with no console errors.

## 0.4.0 — Milestone 3b: orchestrator

- Planner: the quality model proposes a JSON plan; code validates actions, args, dependencies and
  step references; one repair round; clarifying questions and "cannot" answers are passed through.
- Plan-then-execute with `{{steps.N.field}}` references resolved just before each step runs, so
  approvals bind to and display the real content.
- `llm.compose` tool (fast model, untrusted data blocks).
- `writes_verified` verifier re-hashes every file written.
- `jarvis do` (plan review, interactive approvals, verified report) and `jarvis run`.
- Persona: neutral identity, worked example, and an explicit list of real abilities.
  This fixed the "I am Tony Stark's AI" answer and invented abilities seen on the Mac.
- Ollama `keep_alive` (30 min) to avoid model reloads; live benchmark reports warm generation speed.
- Kernel uses the production tools by default.

## 0.3.1 — Web search

- `search.query` tool backed by a local SearXNG (loopback only, query length/limit validation,
  non-http result links dropped, results marked untrusted). Tier 1, so searches need confirmation unless
  the policy allows them. The example policy allows them and explains why.
- `[search]` section in `jarvis.toml`; `docs/SETUP-MAC.md` step-by-step setup.

## 0.3.0 — Milestone 3a: production tools

- `fs` tool: read, list, search (no symlink following, hidden files skipped), mkdir, atomic write
  with the previous version kept, delete as a Tier 4 move to trash; crash reconciliation for write and delete.
- `web.fetch`: http(s) only, every hop including redirects checked against loopback/private/link-local
  addresses, text-only content types, size limits, HTML-to-text, results marked untrusted.
- 22 new tests.

## 0.2.0 — Milestone 2: model layer

- Provider adapters: Ollama (loopback-only) and OpenAI-compatible cloud (https-only, Keychain keys).
- Router with hard constraints and local-first ranking; every exclusion recorded with a reason.
- Model service with bounded fallback that never bypasses an approval.
- Egress gate: data-category sensitivity, local-only categories, secret scanning,
  per-request single-use approvals, revocable standing grants, emergency-stop checks.
- Budget guard (default $0/month) and usage ledger.
- Strict `jarvis.toml` config; example ships with cloud disabled.
- CLI: `models`, `ask`, `grant-egress`, `revoke-egress`, `grants`; `init` writes both configs.
- 31 new tests against local HTTP servers speaking the Ollama/OpenAI protocols; opt-in live Ollama test.

## 0.1.0 — Milestone 1: kernel

- SQLite storage (WAL, durable writes, migrations, savepoint-nested transactions).
- Hash-chained append-only audit log with trigger protection, verification and secret redaction.
- Permission engine: tiers 0–4, approved filesystem roots, protected paths, deny > confirm > allow,
  tier 3/4 confirmation floor, strict policy-file validation.
- Approvals bound to exact arguments, single-use, user-only decisions. Rejections block the resource for the task.
- Tool registry + gateway: the single mediated path to tools, with timeouts and output limits.
- Task engine: whitelisted state machine, write-ahead step execution with operation ids,
  checkpoints, bounded exponential-backoff retries, reconcile-or-block crash recovery,
  pluggable verification, pause/resume/cancel.
- Emergency stop persisted in the database. Release requires explicit user confirmation.
- `jarvis` operator CLI.
- 50 automated tests, including a real subprocess-kill crash recovery test.
