# Changelog

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
