# Changelog

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
