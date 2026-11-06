# Architecture

One local Python process (the **Core**) owns all state and enforcement. Clients (dashboard,
iPhone web app, voice, CLI) are thin and talk to it. Models never call tools or the network
directly.

```
clients ─► dashboard API ─► Orchestrator ─► TaskEngine ─► ToolGateway ─► tool handlers
                                                       │              │
                                                   TaskStore    PermissionEngine + Approvals
                                                       │              │
                                          SQLite (WAL) ◄──── AuditLog, KillSwitch
```

## Kernel components (implemented, `src/jarvis/core/`)

| Module | Responsibility |
|---|---|
| `db.py` | Single SQLite file, WAL, `synchronous=FULL`, versioned migrations, nested transactions as savepoints |
| `audit.py` | Append-only hash chain; UPDATE/DELETE blocked by triggers; `verify()` |
| `redact.py` | Secret redaction applied to every audit payload |
| `permissions.py` | Pure policy evaluation → allow / confirm / deny |
| `approvals.py` | Approval requests bound to exact args, single-use; rejections block the resource for the task |
| `tools.py` | Tool registry (declared actions, tiers, resources, timeouts) and `ToolGateway`, the only path to a handler |
| `tasks.py` | `TaskStore` (persistence) and `TaskEngine` (execution, retries, recovery, verification) |
| `killswitch.py` | Emergency stop stored in the DB, visible across processes |
| `kernel.py` | Wiring around one data directory |

## Task lifecycle

```
queued ─► running ─► verifying ─► completed
   │        │  ▲          └─────► failed
   │        ▼  │
   │  awaiting_approval        paused ◄── user / emergency stop
   │        │                  blocked ◄── outcome unknown, needs a decision
   └──► cancelled              recovering ◄── process restarted mid-task
```

Transitions are whitelisted (`TRANSITIONS`), use optimistic versioning, and are all audited.

**Write-ahead step execution.** Before a tool runs, the step is durably marked `started` with an
operation id. After a crash, `recover()` finds started steps and:
- asks the tool's `reconcile(args, op_id)` hook whether the operation landed, if it has one;
- otherwise re-runs it only if the action is declared idempotent;
- otherwise marks it `uncertain` and blocks the task until the user says whether it happened.

**Retries** are bounded per step (`max_attempts`) with exponential backoff and reuse the
same operation id. Timeouts and unexpected exceptions on non-idempotent actions are never retried
automatically.

**Verification** is a separate stage. A task completes only if its verifier passes; the evidence
is stored on the task and in the audit trail.

## Model layer (implemented, `src/jarvis/models/`)

| Module | Responsibility |
|---|---|
| `types.py` | Messages tagged with a data **category**, capability records, JSON output validation |
| `providers.py` | `OllamaProvider` (loopback hosts only) and `OpenAICompatProvider` (https only) |
| `egress.py` | `EgressGate`: the only holder of cloud providers; sensitivity policy, grants, budget guard, usage ledger |
| `router.py` | `ModelRouter` (hard filters + local-first ranking, reasons for every exclusion) and `ModelService` (bounded fallback) |
| `config.py` | Strict `jarvis.toml` parsing (no secrets) |
| `secrets.py` | Keychain lookup (macOS), env fallback for development |

```
ModelService.complete(need, request)
   └─ ModelRouter.route ── filters: capability · quality floor · context · availability · local-only · budget
        ├─ local candidate ──► OllamaProvider (127.0.0.1)            [audited: model.local_call]
        └─ cloud candidate ──► EgressGate.send ─► stop? enabled? local-only? secrets? budget?
                                                  private category → grant or single-use approval
                                                  ─► provider ─► cost ledger      [audited: egress.*]
```

`ApprovalRequired` from the gate propagates to the caller and pauses the task. The service never
works around it by trying another provider.

## Orchestrator (implemented, `src/jarvis/orchestrator/`)

```
request ─► Planner (quality model, JSON) ─► deterministic validation ─► (one repair attempt)
        ─► plan shown to owner ─► TaskStore ─► TaskEngine ─► resolve {{steps.N.x}} ─► ToolGateway
        ─► writes_verified (re-hash every written file) ─► report
```

- **Plan-then-execute.** The plan is fixed before any file or web page is read, so text inside
  them cannot add steps, change tools or skip approvals.
- `llm.compose` writes from earlier results with the fast model. Inputs are wrapped as untrusted data blocks.
- References are resolved just before a step runs. Approvals therefore cover, and display, the
  exact content that will be written.
- The planner may use file read/list/search/mkdir/write/move, document read, web fetch, research, compose, and the
  Mac-app actions (calendar events/add, reminders list/add/complete, notes search/read/create, mail draft, open
  app). Delete, sending mail or messages, and other external actions are not plannable. The planner prompt
  includes the current local date and time.

## Dashboard (implemented, `src/jarvis/server/`)

A standard-library HTTP server bound to 127.0.0.1. The page polls `/api/state` every 1.5 s, and that
snapshot is built from the kernel, so the page never shows simulated data. Actions call the same
kernel APIs as the CLI, with actor `user:dashboard`. A background runner drives only tasks whose
`runner` is `dashboard`. Planning runs as a background job because it takes about a minute on the Mac's CPU.

## Several processes, one database (v0.12)

The background service, the dashboard and terminal commands are separate processes sharing one SQLite
file. Each task has a **lease** (`tasks.lease_owner`, `lease_until`, migration v4): `TaskEngine.run` claims
it atomically and renews it with a heartbeat thread, so only one process executes a task. Start-up
recovery only reclaims tasks whose lease expired or whose holder process is gone (same host, pid not alive);
a live task in another process is never touched. Pause/cancel from another process set a control flag the
owner obeys. The emergency stop is a database flag read by every process.

## Memory (`src/jarvis/memory/`)

Original conversation **records** and derived **memories** (explicit or observed, confidence, source,
dates) in the same database, each with an FTS5 index (keyword search with stemming; no embeddings).
Deletions leave **tombstones** so facts aren't re-learned and restores re-apply them. `Kernel.forget`
removes matching memories, records and finished task history, then checkpoints the WAL; `secure_delete`
overwrites freed pages.

## Research and documents

`research.web` runs Claude Code with only its read-only `WebSearch`/`WebFetch` tools and parses the event
stream to record searches and pages read; cited sources count as verified only if seen there. `doc.read`
handles PDF (pypdf), .docx and text formats with size/page/decompression caps.

## Audit privacy (v0.12)

Audit payload fields that carry free text (requests, goals, plans, contents, model output…) are stored as
`{"chars", "sha256"}` fingerprints; tools, actions, decisions, ids, file paths and URLs stay readable. The
words themselves live only in deletable tables. Entries written before v0.12 may contain text.

## iPhone companion (`src/jarvis/remote/`, v0.13)

The dashboard still listens only on 127.0.0.1. `jarvis remote enable` runs `tailscale serve`, which forwards
HTTPS from your tailnet (devices signed in to your Tailscale account) to it; `funnel` (public internet) is
never used. Requests are told apart by Host: the loopback names get the Mac dashboard (token cookie); the
Mac's `*.ts.net` name gets the phone path, where the Mac's token cookie is never accepted.

- `webauthn.py`: passkey verification (ES256, "none" attestation, user verification required, exact
  origin/RP ID/challenge, signature counter).
- `devices.py`: one-time pairing codes (hash stored, 10 min, single use), paired devices, device sessions
  (hash stored, 12 h idle / 30 days max, deleted on revoke).
- `__init__.py` (`RemoteAccess`): pairing, sign-in, and **step-up**: every sensitive phone action
  (approvals, consent, running a plan, releasing the stop, editing/deleting/forgetting memory, removing a
  device) needs a fresh Face ID assertion whose challenge is bound to that exact path and body. Pairing new
  devices is Mac-only. Phone actions are audited as `user:phone:<name>`.
- `push.py`: Web Push (RFC 8291 encryption, RFC 8292 VAPID) to Apple's push service only, with generic
  text ("JARVIS needs a decision"); `Notifier` batches and rate-limits.
- `tailscale.py`: the few `tailscale` commands `jarvis remote` runs.
- `passkeys.py`: the ceremonies shared by phone (Face ID) and Mac (Touch ID): single-use challenges bound
  to a purpose, assertion checks, request-bound step-up.
- `mac.py` (`MacKeys`, v0.14): optional Touch ID for the Mac dashboard. Keys are stored as devices of kind
  `mac` (they never sign in a phone). Once one exists, the phone's step-up list plus pairing a phone and
  adding/removing Touch ID keys need a fresh Touch ID. The passkey's site is `localhost`, so the dashboard
  page redirects from 127.0.0.1 to `http://localhost:PORT`.

## Proactive JARVIS (`src/jarvis/proactive.py`, v0.15)

The dashboard's maintenance loop (once a minute, in the existing process; no new background service)
announces the morning briefing at `[proactive] briefing_time` (at most 4 hours late), and sends a generic
alert when health turns bad. `Notifier` holds notifications back during quiet hours and reminds you once about
a decision that has waited longer than `approval_reminder_min`. The briefing is computed from live state when
opened (`/api/briefing`, `jarvis briefing`) and covers the time since the previous briefing. Only the date and
time it was announced are stored (`meta` table). It calls no model and sends nothing off the Mac except the
generic push.

## Voice (`src/jarvis/voice/`, v0.16)

The browser records (MediaRecorder), converts to 16 kHz mono 16-bit WAV (Web Audio, in the page) and posts it
to `/api/voice/transcribe` (same CSRF/Origin checks; Mac cookie or phone session). JARVIS checks the WAV
(format, ≤60 s), passes it in memory to whisper.cpp's `whisper-server` on 127.0.0.1 (`POST /inference`;
loopback enforced, no system proxy) and returns the cleaned transcript, which the page sends like typed text.
With `whisper_binary` and `model` configured, the dashboard process starts `whisper-server` and stops it on
exit (no extra LaunchAgent). Spoken replies use `speechSynthesis` with on-device (`localService`) voices only.

## Mac apps (`src/jarvis/tools/mac.py`, v0.17)

Five small tools (calendar, reminders, notes, mail, apps) run JavaScript-for-Automation scripts with
`osascript -l JavaScript`; arguments go as one JSON argv string, never into script text. Reads are tier 0; adding
or changing is tier 1 (asks, with a plain-words preview built by `mac_preview`). Nothing sends, deletes or changes
settings. Calendar scripting returns repeating events as one master with an RRULE, so `expand()` turns them into
occurrences (python-dateutil). Changes that time out are marked outcome-unknown (never retried); adds have
reconcile checks. Registered only on macOS; tests use a stand-in runner.

## Smarter chat (`src/jarvis/orchestrator/lookup.py`, v0.17)

Before a chat answer, a word check decides whether a lookup could help. If so, the local model (message marked
local-only) picks up to three **read-only** lookups (calendar, reminders, notes, files). Each is checked with the
permission engine first (anything not plainly allowed is skipped, so no approval is ever left behind) and run
through the gateway. Results go to the answering model as a private `file_content` message inside `<lookup>`
tags; if that model is Claude, the privacy gate asks first. Requests to change something get a "Make a plan" offer
instead (the plan then goes through approvals). The persona's can/can't list changes with the ability.

## Live replies (v0.17.1; Claude and stages since Phase 3a)

`POST /api/chat/stream` returns newline-delimited JSON: `{"s": stage}` as each real stage starts, `{"t": piece}` as
the model writes, then `{"done": result}` with exactly what `/api/chat` returns. Stages: `understanding`, `lookup`
(what was checked), `context` (memories and earlier messages used), `generating` (which model, local or cloud, and
whether it streams; sent again before each fallback attempt so the page drops a failed attempt's words), `checking`
(answer check or coding self-test). They describe what the code is doing, never the model's reasoning.

Both Ollama and Claude stream. Claude Code runs with `--output-format stream-json --verbose
--include-partial-messages` (all other flags unchanged) through `run_streaming`, which keeps `run_tracked`'s
protections: own process group, killed on the emergency stop, the deadline, or when the page goes away. While no
words arrive, the server writes a bare newline about once a second, so a closed page is noticed before the first
word too. Streaming starts only after the privacy gate, consent and budget checks, exactly as a whole reply would.
A provider that can't stream says so (`streams: false`) and the page shows that instead of a fake typing effect.

**Intelligence modes** (`mode` in the request): **Quick** = fastest local model, and no goal-reader call unless the
message could need a lookup; **Balanced** (default) = the configured routing; **Deep** = `Need(min_quality=5,
prefer="quality")` and up to 2000 tokens, falling back to the best available model with a note (`chat.mode_fallback`).
`local_only` always wins. Answer-check retries are local at any quality, so they never become consent questions.

## Holographic core, adaptive layout and the command center (Phase 2)

- **Avatar** (`static/avatar.js`, `avatar.css`): a humanoid hologram in layered SVG around the existing reactor
  (`#core`, now its chest core; its states and tests are unchanged). Parts are named layers (aura, orbits, body,
  circuits, plates, pauldrons, gorget, helmet, fins, face, visor, scan, halo); `JarvisAvatar.registerPart(name, svg)`
  replaces one (e.g. a new helmet or face) without touching the rest. It never fetches or decides anything.
- **13 states** (`avatarState()` in `app.js`) come only from `situation()`, the live chat stage and voice events:
  idle, listening, understanding, planning, researching, reasoning (model working, no words yet), writing, coding
  (code arriving or being tested), verifying, approval, executing, completed, error.
- **Evolution** (`src/jarvis/evolution.py`): 12 milestones checked against live state once a minute (models answering,
  a confirmed memory, a verified mission, Mac apps, voice, a paired phone, Touch ID, a verified backup, a benchmark
  run, all health checks). Tier = milestones verified *now* (Core 0–3, Development 4–6, Advanced 7–9, Mature 10–12);
  the first verification of each is stored in `meta` and audited (`evolution.milestone`, `evolution.tier`). The page
  can only display the server's tier.
- **Performance**: loaded after the page is usable; CSS animates only transform/opacity/stroke-dashoffset; the
  particle canvas runs ≤30 fps and only while on screen, the page is visible and Display → Effects is Full; reduced
  motion or Effects Off makes it still. Chat rendering never waits for it.
- **Adaptive layout**: `body[data-activity]` = voice / research / mission / conversation / idle from real state; the
  avatar steps back while you work and leads in voice.
- **Command center** (`#/command`, Home status chips): eight systems built from `/api/state` only — health
  (`src/jarvis/telemetry.py`: load average, `vm_stat`/`/proc/meminfo`, disk, a no-packet route check, JARVIS's own
  peak memory; anything unreadable is reported unavailable), intelligence (recent model timings from the audit log,
  counts only), missions, security, communications, research, personal operations, diagnostics (incl. the
  evolution record).

## Benchmark and release gate (`src/jarvis/bench/`, `src/jarvis/gate.py`, v0.17)

`jarvis bench` runs fixed tasks (`bench/tasks/*.toml`) through the real chat, research and plan→task→approval
paths, each in a throwaway data folder with made-up data, a Mac-apps stand-in and no standing permissions; an
audit-log check fails any change made without an approval. `jarvis gate` runs the full suite (JUnit XML) and the
pinned linter, and maps each security item to the specific tests that prove it: any of those failing, being
skipped or missing fails the gate.

## Flight Recorder (`src/jarvis/flight.py`, v0.17.3)

`timeline(kernel, task_id)` orders everything recorded about one task: the audit entries for it (plus approval
"used"/"restored" entries, which carry only an approval id), its steps and approvals, with counts (steps, tool runs,
local and Claude model calls, approvals asked/approved/rejected, verification) and the audit chain's integrity.
Read-only, and limited to what the audit log holds (fingerprints, not private text). Exposed as `jarvis trace`,
`GET /api/tasks/<id>/timeline` and the dashboard's Timeline button.

## Recovery drills (`src/jarvis/drill.py`, v0.17.4)

Each drill builds a throwaway JARVIS in a temporary folder (own database, approved folder, policy and small drill
tools), breaks it the way real life does, checks the outcome and deletes the folder: crashes are real (a child
process exits with `os._exit` mid-action, recovery runs in a new process), the stop is pressed from a second
Kernel on the same database, approvals are raced from four threads, a checkpoint and an audit entry are damaged,
and the database is deleted and restored from an encrypted backup (throwaway passphrase; the Keychain is never
used). Tests prove each protection drill fails when its protection is disabled.

## Outcome Engine v1 (merged in 0.18.0)

- **Goal reader:** the chat lookup call (local model, message local-only) also rates difficulty in hybrid mode,
  replacing the separate triage call; `ModelService.complete(level=…)` uses it.
- **No downgrades:** `hard_signals()` (code, reasoning words, high-stakes topics, 3+ questions, long requests) forces
  "hard" whatever a small model said, in both the goal reader and triage paths.
- **Profile memories:** `MemoryStore.recall()` always includes up to 8 confirmed profile facts (marked important,
  or phrased "call me…", "I'm…", "I prefer…", "my sister…"), plus the keyword matches. Still `Category.MEMORY`, so the
  privacy gate decides whether Claude may see them.
- **Grounding check:** answers built on calendar or reminder lookups may only mention times found in that data or
  in the question; otherwise one retry with the problem pointed out, then the reply is marked "Unverified". Logged
  as `chat.grounding` (outcome and counts only).

## Service and backups

`service.py` writes a per-user LaunchAgent that runs `uv run jarvis dashboard --no-open` at login and after
crashes. `backup.py` makes AES-256-GCM encrypted archives (SQLite snapshot + configs + manifest), test-restores
each one, prunes to the newest N, and restores with tombstones re-applied.

## Not built yet

Deeper monitoring (e.g. watched folders), applying self-improvement proposals (today they are propose-only:
`src/jarvis/proposals.py`), a personal operations model. See the [roadmap](ROADMAP.md).
