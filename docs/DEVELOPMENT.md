# Development

```bash
uv sync            # creates .venv with pytest (the kernel itself needs no packages)
uv run pytest      # full suite, ~2 s
```

## Test layout

| File | Covers |
|---|---|
| `tests/test_permissions.py` | Roots, traversal, symlinks, rule precedence, tier floors, URL schemes, policy validation |
| `tests/test_gateway.py` | Unknown tools, approval binding/single-use, rejection bypass, emergency stop, timeouts, output limits, audit content |
| `tests/test_audit.py` | Hash chain, trigger protection, tamper detection, redaction |
| `tests/test_models.py` | Adapters (wire format), routing, egress gate, grants, budget, audit content, config validation |
| `tests/test_live_ollama.py` | Opt-in, real Ollama: `JARVIS_LIVE_OLLAMA=llama3.2:3b uv run pytest tests/test_live_ollama.py -s` |
| `tests/test_tasks.py` | End-to-end task with approval + verification, retries/backoff, uncertain outcomes, pause/cancel, corrupt checkpoints, **real subprocess crash + recovery** |

Tests use real files in a temp directory and a real SQLite database. They use no mocks for the kernel.
`tests/helpers.py` defines small real tools used only by tests.

## Conventions

- The kernel uses the standard library only. Each new dependency must serve a stated requirement.
- Every tool action must declare `tier`, resource, `idempotent`, and `timeout_s`. Non-idempotent
  actions should provide `reconcile` where possible.
- Schema changes go in a new entry in `db.MIGRATIONS`. Never edit an existing migration.
- Never log secrets or write them into tool arguments.
- Commits are scoped to one milestone or fix.
