# JARVIS

A personal AI system for Mac and iPhone: persistent, permissioned, auditable, local-first.

**Status: v0.17 — Mac apps, smarter chat, benchmark, release gate.** JARVIS chats (local models + Claude via
your Pro plan) and looks things up in your calendar, reminders, notes and files before answering; researches the
web with verified sources; reads documents; plans and carries out tasks with approvals (files, Calendar, Reminders,
Notes, Mail drafts); remembers what you tell it; runs in the background with encrypted backups; works from your
iPhone over your private Tailscale network with Face ID on every approval, and can require Touch ID on the Mac.
Each morning it tells you what's on today, what needs you and what's wrong. You can talk to it (whisper.cpp on your
Mac). `jarvis bench` measures it on fixed tasks; `jarvis gate` must pass before a release.
**Much of v0.12–v0.17 is not yet confirmed on the Mac** (see the table). **Not built yet:** watched folders,
self-improvement proposals, a personal operations model. See [ROADMAP](docs/ROADMAP.md).

## What works today

"Tests" = automated tests in this repo (some use stand-ins for Ollama/Claude). "On the Mac" = confirmed on
the owner's Intel Mac (macOS 14.1.1). Untested-on-Mac items may still have Mac-specific problems.

| Capability | Tests | On the Mac |
|---|---|---|
| Task engine: state machine, checkpoints, retries, crash recovery, **one process per task (leases)** | ✅ | ✅ basic tasks · leases not yet |
| Permission engine: tiers, approved folders, deny/confirm/allow; approvals bound to exact arguments, single-use | ✅ | ✅ |
| Audit log: hash-chained, append-only, secrets redacted, **free text stored only as fingerprints** | ✅ | ✅ chain intact (`jarvis doctor`) · fingerprinting not checked by hand |
| Emergency stop: blocks new actions; **kills Claude work in progress** | ✅ | not yet (v0.12) |
| Model routing (local-first / best / hybrid) with Ollama | ✅ (stand-in + opt-in live) | ✅ llama3.2:3b 12.7 tok/s, qwen2.5:7b 6.4 tok/s |
| Claude via Claude Code on your Pro plan (tools off, personal settings isolated, asks before private data leaves) | ✅ (stand-in CLI) | ✅ chat · settings isolation not yet |
| Privacy gate, $0 budget guard, usage meter | ✅ | ✅ approval prompts |
| Planning + execution (`jarvis do`, dashboard Do) with verification | ✅ | ✅ text and PDF summaries |
| Web research with source verification (`jarvis research`) | ✅ (stand-in CLI) | ✅ 3/3 sources verified |
| Documents: PDF / Word / text; move & rename with approval | ✅ (real generated files) | ✅ PDF summary · move not yet |
| Web fetch (pinned to the checked address, ports 80/443, one deadline) | ✅ | not yet |
| Memory: archive + facts with provenance, recall, review/correct/delete, forget (incl. task history) | ✅ | not yet |
| Dashboard (holographic HUD), live replies, Help and welcome | ✅ + headless browser | ✅ opens (v0.16.x) · live replies not yet |
| Background service, health checks, encrypted backups | ✅ (plist content, crypto, restore) | ✅ service installed, backup saved + verified, passphrase in Keychain · restore not yet |
| iPhone companion: Tailscale (tailnet only), passkey pairing, Face ID on every approval, private notifications, Home Screen app | ✅ + headless browser with a virtual passkey | **not yet** |
| Touch ID for dashboard approvals on the Mac (optional; recovery via Terminal) | ✅ + headless browser with a virtual passkey | ✅ set up · approving with it not yet |
| Morning briefing (built live, never stored) incl. today's calendar and reminders due, quiet hours, reminders, health alerts | ✅ + headless browser | **not yet** |
| Voice: push-to-talk on Mac and iPhone, local whisper.cpp (loopback only, audio never stored), on-device spoken replies | ✅ protocol stand-in + headless browser with a fake microphone | **not yet** (real whisper.cpp not built here) |
| `jarvis doctor`: one-command check of the whole installation | ✅ | ✅ (v0.16.4) |
| Mac apps: Calendar, Reminders, Notes, Mail drafts, open apps (reads free; changes ask first) | ✅ (osascript stand-in) | **not yet** (`jarvis mac check`) |
| Smarter chat: read-only lookups chosen by the local model; "Make a plan" for changes | ✅ (stand-in models) | **not yet** |
| Benchmark `jarvis bench` (12 tasks, isolated runs, Claude-app baseline) | ✅ (oracle/careless stand-ins) | **not yet** (first run pending) |
| Release gate `jarvis gate` (full suite + linter + 12 security items) | ✅ | n/a (runs from the repo) |
| Flight Recorder: per-task timeline (`jarvis trace`, dashboard Timeline) | ✅ + headless browser | **not yet** |
| Watched folders, self-improvement proposals, personal operations model | — | ⏳ not started |

## Quick start

**Setting up on your Mac: follow [docs/SETUP-MAC.md](docs/SETUP-MAC.md).**

Requires Python ≥ 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run pytest
uv run jarvis init     # creates the data dir and a starter policy — review it
uv run jarvis status
```

### Local models on the Mac

```bash
# install the Ollama app from https://ollama.com/download
ollama pull llama3.2:3b                    # ~2 GB
JARVIS_LIVE_OLLAMA=llama3.2:3b uv run pytest tests/test_live_ollama.py -s   # real speed on your hardware
uv run jarvis ask "What can you do yet?"
```

Data lives in `~/Library/Application Support/JARVIS` on macOS (`~/.local/share/jarvis` on Linux),
or `$JARVIS_HOME`. Nothing runs in the background unless you run `jarvis service install` (plus whisper.cpp while JARVIS runs,
if you turned voice on), and nothing private
is sent over the network without your approval.

## CLI

| Command | Purpose |
|---|---|
| `jarvis bench list\|run\|baseline\|score-baseline\|report` | Benchmark JARVIS on fixed tasks, and the Claude app on the same tasks ([bench/README](bench/README.md)) |
| `jarvis mac check` | Read-only test of Calendar, Reminders and Notes access (lets macOS ask for permission) |
| `jarvis trace TASK_ID [--json]` | Flight Recorder: one task's whole story (also **Timeline** on each mission in the dashboard) |
| `jarvis gate [--json]` | Release gate: full tests, linter and every security item; must pass before a release |
| `jarvis doctor [--json]` | Check the whole installation (database, models, service, backups, HTTPS, phone path, Touch ID, voice) and say what to fix |
| `jarvis status` | Emergency-stop state, task counts, pending approvals |
| `jarvis tasks` / `jarvis show ID` / `jarvis tasks delete ID` | List tasks / inspect one / delete a finished task's history |
| `jarvis approvals` / `approve ID` / `reject ID` | Decide pending approvals |
| `jarvis pause\|resume\|cancel ID` | Task controls |
| `jarvis stop [--reason]` / `jarvis release --yes` | Emergency stop |
| `jarvis audit [--task ID]` / `jarvis verify-audit` | Inspect and verify the audit trail |
| `jarvis dashboard [--port 8765]` | Start the local command centre and open it in your browser |
| `jarvis do "…" [--yes]` | Plan a task, show the plan, run it with approvals, verify and report |
| `jarvis run ID` | Continue a task (after approving, resuming or a restart) |
| `jarvis use-claude on\|off` | Hybrid brain: simple → local, medium → Claude Haiku, hard → Claude Sonnet (Pro plan); or local-only |
| `jarvis service install\|uninstall\|status\|restart` / `jarvis open` | Run JARVIS in the background at login; open the dashboard |
| `jarvis backup now\|list\|verify FILE\|restore FILE --yes` | Encrypted backups of memory, history and settings |
| `jarvis allow-folder PATH [--remove]` / `jarvis folders` | Let JARVIS read a folder such as Downloads (changes still ask) |
| `jarvis research "…" [--deep]` | Search the web and read pages, answer with verified sources |
| `jarvis remote enable\|disable\|status` | Use JARVIS from your iPhone over Tailscale (tailnet only, never the internet) |
| `jarvis voice setup\|enable\|disable\|status\|test FILE` | Local speech recognition (whisper.cpp v1.9.4) |
| `jarvis briefing` | What needs you, what finished or failed since the last briefing, and any problems |
| `jarvis touchid [list\|remove ID\|reset --yes]` | Touch ID keys for dashboard approvals; `reset` is the recovery if Touch ID stops working |
| `jarvis devices [revoke ID]` | List paired phones / remove one (signs it out at once) |
| `jarvis remember "…"` | Tell JARVIS something to remember |
| `jarvis memory list\|search Q\|confirm ID\|delete ID\|forget Q [--yes]\|export FILE` | Review and manage memory; `forget` also removes matching finished tasks |
| `jarvis models` | Configured models, live availability, budget |
| `jarvis ask "…" [--min-quality N] [--local-only]` | One-off question through the router and privacy gate |
| `jarvis grant-egress --category C --provider P` / `revoke-egress ID` / `grants` | Standing privacy grants |

## Documentation

- [ARCHITECTURE](docs/ARCHITECTURE.md) — components, boundaries, data flow
- [SECURITY](docs/SECURITY.md) — permission model, threat model, known limits
- [DEVELOPMENT](docs/DEVELOPMENT.md) — setup, tests, conventions
- [ROADMAP](docs/ROADMAP.md) · [CHANGELOG](CHANGELOG.md)

## Uninstalling

```bash
uv run jarvis service uninstall
rm -rf ~/jarvis
```
Your data stays in `~/Library/Application Support/JARVIS` (memory, history, backups) until you delete that
folder too. The backup passphrase is in Keychain Access under "jarvis".

## Rolling back

Every release is a commit on `main`. Before updating, run `uv run jarvis backup now`. To return to v0.11.0:
```bash
cd ~/jarvis && git checkout 0ad2093 && uv sync -q
```
then restore the backup you made before updating (`uv run jarvis backup restore FILE --yes`), because a newer
database schema can't be opened by older code.
