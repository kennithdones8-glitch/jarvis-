# Changelog

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
