# Changelog

## Unreleased: fixes for what the hard set found (branch `smarter-v2`, owner's choice: fixes 1, 2A and A–J)

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
- **Measured on the Mac with A–E** (20261107-163941-local): hard set 47/85 runs (was 38/85); planning-slot 1→5/5,
  tooluse-urgent 3→5/5, expenses 4→5/5. Still failing, traced to the cause: the 3B answering chat in local runs,
  the planner ignoring the "ask" rule, and a contradiction answered by quietly dropping the file. Hence G–J:
- **G. Careful answers use the strongest local model.** When the answer must read JARVIS's worked-out facts, or the
  question matched a memory and the rest of a small store came with it, the 7B answers instead of the 3B. Never
  moves an answer to the cloud; Quick mode stays fast; "tell me a joke" stays on the fast model.
- **H. A premise check in code.** "Before my dentist appointment tomorrow": JARVIS reads the calendar itself
  (read-only, only when already allowed without asking) and, if there's no "dentist" event that day, asks before
  planning and says where the nearest one is.
- **I. A request that contradicts itself is asked about before planning** ("save it as summary.md, but don't create
  any new files"; also reminders, emails, events, notes).
- **J. Nothing JARVIS listed is left out.** If an answer misses a reminder JARVIS listed as overdue or due in the
  window asked about, it gets one local retry naming what's missing.
- **Measured on the Mac with G–J (c08983b).** Hard set 58/85 (20261108-033633-local); pooled against both earlier
  hard runs 8 → 11 tasks, verdict MERGE (planning-today, contradiction, false-premise 0 → 5/5). But core + extended
  (20261108-114935-local) was 104/110 with reasoning-schedule down to 1/5 (5/5 before): a new failure, so not
  mergeable as it stood. Hence:
- **A retry stays on the model that answered.** Every puzzle answer gets one "check your answer" retry, and the
  model for it was chosen from the retry's own instruction text, never maths, so it skipped the 14B reasoning model.
  With G a calendar lookup marks the answer careful, so the 7B (not the 3B) did the retry and re-solved the puzzle
  wrongly. Retries and coding fixes are now routed by the owner's question. Also: a careful answer in hybrid routing
  ("simple", kept here) still gets the reasoning model for maths, logic and code, instead of the 7B.
- **Measured with the retry fix (a2a1727, 20261108-135847-local):** reasoning-schedule back to 5/5, 105/110. But
  planning-free 1/5: the facts said "First event on Mon 09 Nov: 09:00–09:30 Standup" and the 7B (careful, G) still
  called the 13:00 lunch the first commitment. Pooled: 9/10 with the 3B (before G), 4/10 with the 7B. Hence:
- **The first event JARVIS worked out is checked.** When the question asks what comes first ("first commitment",
  "earliest meeting") and JARVIS listed the first event of 1–3 days, an answer that doesn't name it with its start
  time gets one local retry that names it. Nothing else is judged.
- To be proven on the Mac: core + extended ×5 (no new failures against 20261108-014415-local), and the hard set ×5.

## Unreleased: a harder benchmark set (branch `harder-bench-v1`, owner's choice)

- **17 held-out hard tasks** (`--set hard`): reasoning ×4, coding ×3 (one is fixing a bug), memory ×3, planning ×3,
  tool use ×2, recovery ×2. Core + extended were all passing (110/110), so they could no longer show a gain or a
  loss. Answers were worked out by script (the five-person puzzle has exactly one solution). Benchmark only: no
  change to how JARVIS answers.
- `--set all` still means core + extended (24 tasks), so earlier runs stay comparable.
- Writing them found **two gaps in JARVIS itself**, which fail even with a perfect model: "overdue or due today"
  leaves out the reminder due today, and keyword recall can't link "take the cat to my mum's" to the flight memory.
  Recorded, not fixed here.
- To do on the Mac: a baseline of 0.19.2 on the hard set, ×5 with `--run-code`.

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
