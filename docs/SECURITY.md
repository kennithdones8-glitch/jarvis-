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
| Audit tampering | Triggers + hash chain | ✅ tested (edit, delete) — tail truncation not detectable (no external anchor) |
| Secrets in logs | Redaction + bulk content stored as hash/length | ✅ best-effort |
| Prompt injection | Plan-then-execute (content is read only after the plan is fixed); untrusted data blocks in compose; permission engine outside the model | ✅ tested — injected text can still distort the wording of a composed document |
| Private data sent to cloud | Egress gate holds all cloud providers; private categories need a grant or a single-use, request-bound approval; local-only categories are never sent; message content is never written to the audit log | ✅ tested |
| Silent provider fallback | Fallback goes through the same gate; approvals are per provider and per request | ✅ tested |
| Unapproved spending | Budget guard (default $0) checked by router and gate; paid models are excluded | ✅ tested |
| Claude Code acting outside JARVIS's permissions | Runs with `--tools ""`, `--strict-mcp-config`, `--disable-slash-commands`, no session persistence, an empty working folder, and JARVIS's own system prompt. Claude can only return text; JARVIS's tools do every action | ✅ tested (argv recorded) |
| Accidental API billing through Claude Code | API-key/auth/base-URL/cloud-provider variables are removed from its environment, and `--setting-sources project` (an empty folder) stops `~/.claude/settings.json` `env`/`apiKeyHelper` from switching it to an API key | ✅ tested (argv/env recorded) — sign-in with the isolation flag **to be confirmed on the Mac**; enterprise/managed settings would still apply |
| Private text visible in the process list | Prompts go over stdin; only JARVIS's public system prompt is on the command line | ✅ tested |
| Local adapter used as a network bypass | Ollama adapter refuses non-loopback hosts | ✅ tested |
| Unauthorised remote access | Dashboard binds 127.0.0.1 only; per-launch secret link → HttpOnly SameSite=Strict cookie | ✅ tested |
| Other web pages driving the dashboard | Host-header check (DNS rebinding), custom header + Origin check (CSRF), strict CSP, no framing | ✅ tested |
| Content from files injecting into the UI | All data rendered as text, never HTML; CSP forbids inline script | ✅ by construction, browser-checked |
| iPhone / remote access | Reachable only inside your tailnet (`tailscale serve`, never `funnel`); dashboard still bound to 127.0.0.1; phone requests identified by the Tailscale Host and never accept the Mac's token cookie; passkey sign-in (Face ID, user verification required) → Secure HttpOnly SameSite=Strict session cookie | ✅ tested + headless browser (virtual passkey) — **Mac/iPhone check pending** |
| Stolen phone session | Every sensitive action needs a fresh Face ID bound to that exact request (path + body), single use; pairing new devices is Mac-only; `jarvis devices revoke` / dashboard Remove kills sessions at once | ✅ tested |
| Pairing code interception | Code is random, single use, 10 minutes, stored hashed, only shown on the Mac; the passkey is bound to the Tailscale name | ✅ tested |
| Notification content leaking (lock screen, Apple) | Payloads are encrypted for the phone only (RFC 8291) and contain only generic text; details need sign-in | ✅ tested (decrypted as the phone would) |
| Push used to reach arbitrary hosts | Only https endpoints on known push services are accepted | ✅ tested |
| Unsafe shell | No shell tool exists | ✅ by absence |
| SSRF via web fetch (reaching Ollama, router, cloud metadata) | Each hop resolved once, must be public, and the connection is pinned to that address (no rebinding); ports 80/443 only; no embedded credentials; ≤5 redirects; one overall deadline; system HTTP proxies not used | ✅ tested (v0.12) |
| Destructive file operations | Overwrites keep the previous version; delete is Tier 4 and moves to trash | ✅ tested |
| Memory poisoning / inferred "facts" | Memories the model noticed are stored as unconfirmed, shown as such to the model and to you; extraction is local-only and limited to things you stated | ✅ tested |
| Deleted personal data reappearing | Tombstones block re-learning; record deletion cascades to derived memories; `forget` also deletes matching finished task history; the audit log holds only fingerprints of free text (v0.12); `secure_delete` + WAL checkpoint so no copy lingers in the database files | ✅ tested — backups keep old copies until pruned; audit entries written before v0.12 may contain text; your own files are never touched |
| Prompt injection via web pages during research | Claude has only WebSearch/WebFetch (`dontAsk` denies anything else); pages are untrusted per the prompt; the task plan is fixed before research runs | ✅ tested (argv recorded) |
| Fabricated sources | Cited URLs are checked against the URLs the research tools actually returned or read; unverified ones are flagged; briefs must cite a verified source | ✅ tested |
| Backup exposure | AES-256-GCM encrypted, authenticated (tampering detected), passphrase in the Keychain, files 0600; no secrets in backups | ✅ tested |
| Deleted data returning from a backup | Restore re-applies tombstones for memories and records deleted since the backup | ✅ tested — old backups still contain the data until they're pruned (newest 14 kept) |
| Background service | Per-user LaunchAgent, never root; loopback-only dashboard; removable with one command | ✅ (launchd verified on the Mac only) |
| Supply chain | Kernel has zero runtime dependencies; the one runtime dependency (pypdf, pure Python) and dev deps are locked in `uv.lock` | ✅ |
| Hostile documents | Size caps, a .docx decompression cap and page caps; text is marked untrusted; read-only tool | ✅ tested — a pathological PDF could still be slow (in-process threads can't be killed; not yet isolated in a separate process) |
| Moving files somewhere unsafe | The destination is checked against approved folders and protected paths inside the tool, after approval as well | ✅ tested |
| Self-modification | Proposals only in git worktrees; policy/gate/auth files excluded | ⏳ later |
| Two processes running the same task (service + terminal) | Task leases with heartbeat; recovery never touches a live task | ✅ tested (v0.12; was a confirmed bug) |
| Stop not stopping work in progress | Claude Code runs as a tracked process group, killed on emergency stop (from any process) or deadline | ✅ tested (v0.12) — in-process tools still finish their current call |
| Spending one approval twice | Find-and-consume in one transaction | ✅ tested (v0.12) |
| Backup passphrase in the process list | Written to the Keychain via `security -i` on stdin | ✅ tested with a stand-in — **Mac check pending** |
| Dashboard approvals without step-up auth | Same-user local processes could approve via the Mac dashboard cookie (the phone path already needs Face ID) | ⚠ open on the Mac — Touch ID planned |

## Data categories

| Category | Default | Can be made local-only |
|---|---|---|
| system_prompt, web_content | public (still blocked if they contain secret-looking text) | yes |
| conversation, file_content, memory, project, screenshot | private: ask per transmission | yes |

Config can only make a category stricter. It can never make one less strict.

## Known limitations

- Voice identity is not authentication, and neither is "being on the tailnet": a phone also needs its passkey.
  Anyone who can unlock your iPhone (Face ID or passcode) can approve from it. Remove a lost phone from the Mac.
- A process on the Mac itself can send requests with the Tailscale Host header. It still needs a device
  session and a fresh passkey assertion for sensitive actions, but it can see the sign-in page.

- A timed-out or stopped **in-process** tool call (e.g. a file write, a PDF parse) finishes its current call in the
  background; the task is still marked uncertain/paused and nothing further runs. Claude Code calls are killed.
- Truncating the newest audit entries is not detectable from the chain alone. Anchoring the head hash externally is planned.
- Redaction is pattern-based and can miss unusual secret formats. Secrets must not be passed as tool args at all; they will live in the macOS Keychain.
- Free cloud tiers are configured with $0 prices. If you attach billing to such a key, the provider may charge beyond what the guard estimates. Keep billing off, or set real prices and a budget.
- Grants and approvals are in-process checks. Python cannot stop other in-process code from reaching a provider object; the boundary is that models and tools never get Python-level access.
- A crash between "step started" and the gateway's permission check marks a non-idempotent step uncertain even though nothing ran. This is conservative by design.
