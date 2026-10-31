# Changelog

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
