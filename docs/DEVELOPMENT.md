# Development

```bash
uv sync            # creates .venv (runtime deps: pypdf, cryptography; dev: pytest)
uv run pytest      # full suite, ~30 s
```

## Test layout

| File | Covers |
|---|---|
| `tests/test_permissions.py` | Roots, traversal, symlinks, rule precedence, tier floors, URL schemes, policy validation |
| `tests/test_gateway.py` | Unknown tools, approval binding/single-use, rejection bypass, emergency stop, timeouts, output limits, audit content |
| `tests/test_audit.py` | Hash chain, trigger protection, tamper detection, redaction |
| `tests/test_models.py` | Adapters (wire format), routing, egress gate, grants, budget, audit content, config validation |
| `tests/test_live_ollama.py` | Opt-in, real Ollama: `JARVIS_LIVE_OLLAMA=llama3.2:3b uv run pytest tests/test_live_ollama.py -s` |
| `tests/test_leases.py` | One process per task: no takeover of live tasks, dead/expired holders reclaimed, heartbeat, cross-process cancel |
| `tests/test_stop.py` | Emergency stop kills running Claude Code and its children; deadline kills the process group |
| `tests/test_audit_privacy.py` | Free text fingerprinted in the audit log; `forget` removes text from every table and the raw database files |
| `tests/test_orchestrator.py` | Planning, validation, repair, step references, injection resistance, verification |
| `tests/test_tools.py` | File tool, pinned web fetch (rebinding, redirects, ports, deadline), SearXNG |
| `tests/test_documents.py` | PDF/Word/text with generated files, scanned/encrypted/corrupt PDFs, moves, allow-folder |
| `tests/test_memory.py` | Records, explicit/observed memories, recall, edit/delete tombstones, forget, exclusions |
| `tests/test_claude_code.py` | Claude Code flags/env (stand-in CLI), consent flows, hybrid triage, usage limits |
| `tests/test_research.py` | Research flags, source verification, sourced briefs, waiting for usage reset |
| `tests/test_dashboard.py` | Dashboard auth, Host/CSRF checks, real state, plan → approve → complete |
| `tests/test_webauthn.py` | Passkey verification: registration/assertion round trip; wrong origin, RP, challenge, counter, key, missing Face ID; CBOR |
| `tests/test_remote.py` | Pairing codes, device sessions, remote routing (Host split, no token cookie remotely), Face ID step-up bound to the exact request, approve from the phone, revoke, push encryption (RFC 8291 vector), endpoint allowlist, notifier, `jarvis remote`/`devices` with a stand-in `tailscale` |
| `tests/test_touchid.py` | Touch ID: off by default, setup, request-bound step-up, adding/removing keys, pairing gated, phone keys can't confirm Mac actions, CLI reset |
| `tests/test_backup_service.py` | Encryption, tamper detection, restore with deletions kept, retention, LaunchAgent plist |
| `tests/test_persona.py` | Persona honesty and ability list |
| `tests/test_tasks.py` | End-to-end task with approval + verification, retries/backoff, uncertain outcomes, pause/cancel, corrupt checkpoints, **real subprocess crash + recovery** |

Tests use real files in a temp directory and a real SQLite database. They use no mocks for the kernel.
`tests/helpers.py` defines small real tools used only by tests. Ollama, OpenAI-compatible APIs and the
`claude` CLI are replaced by local stand-ins that record exactly what JARVIS sends.

**Tests must be hermetic:** never read or write the real Keychain, real ports (e.g. 8765), the real home
folder or real services. On macOS a test that does can pass in CI and fail on the owner's machine.

## Conventions

- The kernel uses the standard library only. Each new dependency must serve a stated requirement.
- Every tool action must declare `tier`, resource, `idempotent`, and `timeout_s`. Non-idempotent
  actions should provide `reconcile` where possible.
- Schema changes go in a new entry in `db.MIGRATIONS`. Never edit an existing migration.
- Never log secrets or write them into tool arguments.
- Commits are scoped to one milestone or fix.
