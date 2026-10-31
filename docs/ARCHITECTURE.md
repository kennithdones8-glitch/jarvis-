# Architecture

One local Python process (the **Core**) owns all state and enforcement. Clients (dashboard,
iPhone web app, voice, CLI) are thin and talk to it. Models never call tools or the network
directly.

```
clients ─► API (later) ─► Orchestrator (later) ─► TaskEngine ─► ToolGateway ─► tool handlers
                                                       │              │
                                                   TaskStore    PermissionEngine + Approvals
                                                       │              │
                                          SQLite (WAL) ◄──── AuditLog, KillSwitch
```

## Kernel components (implemented, `src/jarvis/core/`)

| Module | Responsibility |
|---|---|
| `db.py` | Single SQLite file, WAL, `synchronous=FULL`, versioned migrations, nested transactions as savepoints |
| `audit.py` | Append-only hash chain; UPDATE/DELETE blocked by triggers; `verify()` |
| `redact.py` | Secret redaction applied to every audit payload |
| `permissions.py` | Pure policy evaluation → allow / confirm / deny |
| `approvals.py` | Approval requests bound to exact args, single-use; rejections block the resource for the task |
| `tools.py` | Tool registry (declared actions, tiers, resources, timeouts) and `ToolGateway`, the only path to a handler |
| `tasks.py` | `TaskStore` (persistence) and `TaskEngine` (execution, retries, recovery, verification) |
| `killswitch.py` | Emergency stop stored in the DB, visible across processes |
| `kernel.py` | Wiring around one data directory |

## Task lifecycle

```
queued ─► running ─► verifying ─► completed
   │        │  ▲          └─────► failed
   │        ▼  │
   │  awaiting_approval        paused ◄── user / emergency stop
   │        │                  blocked ◄── outcome unknown, needs a decision
   └──► cancelled              recovering ◄── process restarted mid-task
```

Transitions are whitelisted (`TRANSITIONS`), use optimistic versioning, and are all audited.

**Write-ahead step execution.** Before a tool runs, the step is durably marked `started` with an
operation id. After a crash, `recover()` finds started steps and:
- asks the tool's `reconcile(args, op_id)` hook whether the operation landed, if it has one;
- otherwise re-runs it only if the action is declared idempotent;
- otherwise marks it `uncertain` and blocks the task until the user says whether it happened.

**Retries** are bounded per step (`max_attempts`) with exponential backoff and reuse the
same operation id. Timeouts and unexpected exceptions on non-idempotent actions are never retried
automatically.

**Verification** is a separate stage. A task completes only if its verifier passes; the evidence
is stored on the task and in the audit trail.

## Model layer (implemented, `src/jarvis/models/`)

| Module | Responsibility |
|---|---|
| `types.py` | Messages tagged with a data **category**, capability records, JSON output validation |
| `providers.py` | `OllamaProvider` (loopback hosts only) and `OpenAICompatProvider` (https only) |
| `egress.py` | `EgressGate`: the only holder of cloud providers; sensitivity policy, grants, budget guard, usage ledger |
| `router.py` | `ModelRouter` (hard filters + local-first ranking, reasons for every exclusion) and `ModelService` (bounded fallback) |
| `config.py` | Strict `jarvis.toml` parsing (no secrets) |
| `secrets.py` | Keychain lookup (macOS), env fallback for development |

```
ModelService.complete(need, request)
   └─ ModelRouter.route ── filters: capability · quality floor · context · availability · local-only · budget
        ├─ local candidate ──► OllamaProvider (127.0.0.1)            [audited: model.local_call]
        └─ cloud candidate ──► EgressGate.send ─► stop? enabled? local-only? secrets? budget?
                                                  private category → grant or single-use approval
                                                  ─► provider ─► cost ledger      [audited: egress.*]
```

`ApprovalRequired` from the gate propagates to the caller and pauses the task. The service never
works around it by trying another provider.

## Orchestrator (implemented, `src/jarvis/orchestrator/`)

```
request ─► Planner (quality model, JSON) ─► deterministic validation ─► (one repair attempt)
        ─► plan shown to owner ─► TaskStore ─► TaskEngine ─► resolve {{steps.N.x}} ─► ToolGateway
        ─► writes_verified (re-hash every written file) ─► report
```

- **Plan-then-execute.** The plan is fixed before any file or web page is read, so text inside
  them cannot add steps, change tools or skip approvals.
- `llm.compose` writes from earlier results with the fast model. Inputs are wrapped as untrusted data blocks.
- References are resolved just before a step runs. Approvals therefore cover, and display, the
  exact content that will be written.
- The planner may only use read, list, search, mkdir, write, fetch, search-query and compose. Delete and
  external actions are not plannable yet.

## Dashboard (implemented, `src/jarvis/server/`)

A standard-library HTTP server bound to 127.0.0.1. The page polls `/api/state` every 1.5 s, and that
snapshot is built from the kernel, so the page never shows simulated data. Actions call the same
kernel APIs as the CLI, with actor `user:dashboard`. A background runner drives only tasks whose
`runner` is `dashboard`. Planning runs as a background job because it takes about a minute on the Mac's CPU.

## Planned components

 FastAPI + dashboard, memory (FTS5 + vectors with provenance), voice, iPhone web app
over Tailscale with passkeys, launchd service, backups. See the [roadmap](ROADMAP.md).
