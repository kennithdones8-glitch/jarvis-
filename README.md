# JARVIS

A personal AI system for Mac and iPhone: persistent, permissioned, auditable, local-first.

**Status: Milestone 4 — local command-centre dashboard plus terminal. JARVIS plans and carries out file-based tasks. No voice or memory yet.** See [ROADMAP](docs/ROADMAP.md).

## What works today

| Capability | Status |
|---|---|
| Durable task engine (state machine, checkpoints, retries, crash recovery) | ✅ implemented, tested |
| Permission engine (tiers, approved roots, deny/confirm/allow rules) | ✅ implemented, tested |
| Approvals bound to exact arguments, single-use; rejections not bypassable | ✅ implemented, tested |
| Hash-chained, append-only audit log with secret redaction | ✅ implemented, tested |
| Global emergency stop | ✅ implemented, tested |
| Operator CLI (`jarvis status`, `approve`, `stop`, …) | ✅ implemented, smoke-tested |
| Model router (local-first) + Ollama and OpenAI-compatible adapters | ✅ running on the Mac with llama3.2:3b and qwen2.5:7b |
| Egress privacy gate (ask per transmission, grants, local-only, secret scan) | ✅ implemented, tested |
| Budget guard ($0 default) with usage ledger | ✅ implemented, tested |
| File tool (read/list/search/write/delete; atomic, versioned, trash) | ✅ implemented, tested |
| Web fetch tool (SSRF-protected, untrusted-content marking) | ✅ implemented, tested incl. a live fetch |
| Web search via local SearXNG | ✅ implemented, protocol-tested; needs SearXNG on the Mac |
| Orchestrator: plan → review → permission-checked execution → verification (`jarvis do`) | ✅ implemented, tested; planning quality on real models being evaluated |
| Claude as JARVIS's brain via Claude Code on your Pro plan (`jarvis use-claude on`): tools disabled, no API key, asks before sending private content, falls back to local | ✅ implemented, tested with a stand-in CLI; **live check runs on the Mac** |
| Memory: conversation archive + facts with provenance, recall in chat, review/correct/delete, forget-by-topic, exclusions (local only) | ✅ implemented, tested, browser-checked |
| Command-centre dashboard (`jarvis dashboard`): chat, plan review, approvals with previews, missions, systems, activity, emergency stop | ✅ implemented, tested, browser-checked |
| Passkeys / Touch ID, iPhone access, memory, voice, iPhone | ⏳ not started |
| macOS-specific behaviour (launchd, Keychain, Touch ID) | ⏳ not started; not yet tested on a Mac |

## Quick start

**Setting up on your Mac: follow [docs/SETUP-MAC.md](docs/SETUP-MAC.md).**

Requires Python ≥ 3.11 and [uv](https://docs.astral.sh/uv/).

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
or `$JARVIS_HOME`. Nothing runs in the background and nothing is sent over the network.

## CLI

| Command | Purpose |
|---|---|
| `jarvis status` | Emergency-stop state, task counts, pending approvals |
| `jarvis tasks` / `jarvis show ID` | List tasks / inspect one with steps and checkpoint |
| `jarvis approvals` / `approve ID` / `reject ID` | Decide pending approvals |
| `jarvis pause\|resume\|cancel ID` | Task controls |
| `jarvis stop [--reason]` / `jarvis release --yes` | Emergency stop |
| `jarvis audit [--task ID]` / `jarvis verify-audit` | Inspect and verify the audit trail |
| `jarvis dashboard [--port 8765]` | Start the local command centre and open it in your browser |
| `jarvis do "…" [--yes]` | Plan a task, show the plan, run it with approvals, verify and report |
| `jarvis run ID` | Continue a task (after approving, resuming or a restart) |
| `jarvis use-claude on\|off` | Hybrid brain: simple → local, medium → Claude Haiku, hard → Claude Sonnet (Pro plan); or local-only |
| `jarvis remember "…"` | Tell JARVIS something to remember |
| `jarvis memory list\|search Q\|confirm ID\|delete ID\|forget Q [--yes]\|export FILE` | Review and manage memory |
| `jarvis models` | Configured models, live availability, budget |
| `jarvis ask "…" [--min-quality N] [--local-only]` | One-off question through the router and privacy gate |
| `jarvis grant-egress --category C --provider P` / `revoke-egress ID` / `grants` | Standing privacy grants |

## Documentation

- [ARCHITECTURE](docs/ARCHITECTURE.md) — components, boundaries, data flow
- [SECURITY](docs/SECURITY.md) — permission model, threat model, known limits
- [DEVELOPMENT](docs/DEVELOPMENT.md) — setup, tests, conventions
- [ROADMAP](docs/ROADMAP.md) · [CHANGELOG](CHANGELOG.md)
