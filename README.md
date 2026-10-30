# JARVIS

A personal AI system for Mac and iPhone: persistent, permissioned, auditable, local-first.

**Status: Milestone 2 (kernel + model layer) — no orchestrator, voice or UI yet.** See [ROADMAP](docs/ROADMAP.md).

## What works today

| Capability | Status |
|---|---|
| Durable task engine (state machine, checkpoints, retries, crash recovery) | ✅ implemented, tested |
| Permission engine (tiers, approved roots, deny/confirm/allow rules) | ✅ implemented, tested |
| Approvals bound to exact arguments, single-use; rejections not bypassable | ✅ implemented, tested |
| Hash-chained, append-only audit log with secret redaction | ✅ implemented, tested |
| Global emergency stop | ✅ implemented, tested |
| Operator CLI (`jarvis status`, `approve`, `stop`, …) | ✅ implemented, smoke-tested |
| Model router (local-first) + Ollama and OpenAI-compatible adapters | ✅ implemented, protocol-tested; **not yet run against a real model** |
| Egress privacy gate (ask per transmission, grants, local-only, secret scan) | ✅ implemented, tested |
| Budget guard ($0 default) with usage ledger | ✅ implemented, tested |
| Orchestrator, tools, dashboard, memory, voice, iPhone | ⏳ not started |
| macOS-specific behaviour (launchd, Keychain, Touch ID) | ⏳ not started; not yet tested on a Mac |

## Quick start

Requires Python ≥ 3.11 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run pytest
uv run jarvis init     # creates the data dir and a starter policy — review it
uv run jarvis status
```

### Local models on the Mac

```bash
brew install ollama && ollama serve        # or the Ollama app
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
| `jarvis models` | Configured models, live availability, budget |
| `jarvis ask "…" [--min-quality N] [--local-only]` | One-off question through the router and privacy gate |
| `jarvis grant-egress --category C --provider P` / `revoke-egress ID` / `grants` | Standing privacy grants |

## Documentation

- [ARCHITECTURE](docs/ARCHITECTURE.md) — components, boundaries, data flow
- [SECURITY](docs/SECURITY.md) — permission model, threat model, known limits
- [DEVELOPMENT](docs/DEVELOPMENT.md) — setup, tests, conventions
- [ROADMAP](docs/ROADMAP.md) · [CHANGELOG](CHANGELOG.md)
