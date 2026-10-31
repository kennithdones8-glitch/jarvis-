# Changelog

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
