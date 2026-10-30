# Security

Security is enforced in code below the model layer. Prompts are not a security boundary.

## Permission model

Each tool **action** declares a tier, which resource argument it touches, whether it is idempotent,
and its timeout. The policy file (`policy.toml` in the data dir) adds rules.

| Tier | Meaning | Default without a rule |
|---|---|---|
| 0 Read | Inspect approved resources | allow (within approved roots) |
| 1 Routine | Reversible work in approved places | confirm |
| 2 Review | Meaningful modifications | confirm |
| 3 External | Send, publish, spend | **always confirm** — policy cannot allow |
| 4 High-risk | Delete important data, change security | **always confirm** — policy cannot allow |

Fixed guarantees, independent of policy:
- Paths are canonicalised (`~`, `..`, symlinks resolved) before checking. Anything outside the
  approved roots is denied.
- The data directory and the policy file are protected: tools can never write them.
- Rule precedence is deny > confirm > allow.
- Approvals are bound to the exact tool, action, resource and argument hash, and are single-use.
- After a rejection, any further non-read action on that resource in the same task is denied,
  through any tool.
- Only actors named `user…` can decide approvals or release the emergency stop. (Real user
  authentication — passkeys / Touch ID — arrives with the dashboard; today the CLI trusts the local
  OS user.)
- The emergency stop is checked before the permission check and again immediately before a handler runs.

## Threat model (status)

| Threat | Mitigation | Status |
|---|---|---|
| Unauthorised tool execution | Single gateway, declared actions, default confirm/deny | ✅ |
| Path traversal / symlink escape | Canonical paths + root containment | ✅ tested |
| Approval reuse or argument swapping | Arg-hash binding, single use | ✅ tested |
| Bypassing a rejection with another tool | Resource-level rejection per task | ✅ tested |
| Repeated external action after crash | Write-ahead `started`, reconcile, `uncertain` + block | ✅ tested with real process kill |
| Audit tampering | Triggers + hash chain | ✅ tested (edit, delete) — tail truncation not yet detectable |
| Secrets in logs | Redaction + bulk content stored as hash/length | ✅ best-effort |
| Prompt injection | External content treated as data; policy outside model | ⏳ orchestrator milestone |
| Private data sent to cloud | Egress gate holds all cloud providers; private categories need a grant or a single-use, request-bound approval; local-only categories are never sent; content is never written to the audit log | ✅ tested |
| Silent provider fallback | Fallback goes through the same gate; approvals are per provider and per request | ✅ tested |
| Unapproved spending | Budget guard (default $0) checked by router and gate; paid models are excluded | ✅ tested |
| Local adapter used as a network bypass | Ollama adapter refuses non-loopback hosts | ✅ tested |
| Unauthorised remote access | Localhost only; Tailscale + passkeys for phone | ⏳ M4/M7 |
| Unsafe shell | No shell tool exists | ✅ by absence |
| SSRF via web fetch (reaching Ollama, router, cloud metadata) | Every hop is resolved and must be a public address | ✅ tested — DNS rebinding remains a residual risk |
| Destructive file operations | Overwrites keep the previous version; delete is Tier 4 and moves to trash | ✅ tested |
| Supply chain | Kernel has zero runtime dependencies; dev deps locked in `uv.lock` | ✅ |
| Self-modification | Proposals only in git worktrees; policy/gate/auth files excluded | ⏳ later |

## Data categories

| Category | Default | Can be made local-only |
|---|---|---|
| system_prompt, web_content | public (still blocked if they contain secret-looking text) | yes |
| conversation, file_content, memory, project, screenshot | private: ask per transmission | yes |

Config can only make a category stricter. It can never make one less strict.

## Known limitations

- A timed-out handler thread cannot be killed in Python. Tools that do slow I/O must enforce their own deadlines.
- Truncating the newest audit entries is not detectable from the chain alone. Anchoring the head hash externally is planned.
- Redaction is pattern-based and can miss unusual secret formats. Secrets must not be passed as tool args at all; they will live in the macOS Keychain.
- Free cloud tiers are configured with $0 prices. If you attach billing to such a key, the provider may charge beyond what the guard estimates. Keep billing off, or set real prices and a budget.
- Grants and approvals are in-process checks. Python cannot stop other in-process code from reaching a provider object; the boundary is that models and tools never get Python-level access.
- A crash between "step started" and the gateway's permission check marks a non-idempotent step uncertain even though nothing ran. This is conservative by design.
