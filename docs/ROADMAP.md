# Roadmap

Constraints: Intel Mac (i7-9750H, 32 GB, macOS 14.1.1), an iPhone, and a **$0 budget**.

Approved model paths and what they cost:
- **Local (Ollama):** llama3.2:3b and qwen2.5:7b. Free; nothing leaves the Mac.
- **Claude via Claude Code on the owner's Claude Pro plan:** no extra charge, but every call counts toward the
  Pro usage limits shared with claude.ai, and Anthropic's consumer terms apply. Not the paid API; API-key
  billing is blocked (environment variables stripped, personal Claude Code settings not loaded).
- **Paid APIs:** none enabled. The budget guard is $0.

| # | Milestone | Status |
|---|---|---|
| M0–M1 | Scaffold; kernel (tasks, permissions, approvals, audit, emergency stop, CLI) | ✅ done |
| M2 | Model router, Ollama + OpenAI-compatible adapters, egress privacy gate, $0 budget guard | ✅ done · on the Mac |
| M3 | Files, web fetch, orchestrator (plan → review → execute → verify), persona | ✅ done · on the Mac |
| M4 | Dashboard (HUD), Claude via Claude Code (hybrid routing, consent, usage limits) | ✅ done · Claude on the Mac |
| M5 | Memory: archive + facts with provenance, full-text search, deletion with tombstones | ✅ done · Mac check pending |
| M5b | Web research through Claude Code's read-only web tools, with source verification | ✅ done · on the Mac |
| M5c | Documents (PDF/Word/text), move/rename, allow-folder | ✅ done · PDF on the Mac |
| M8 | Background service, health checks, encrypted backups | ✅ done · **Mac check pending** |
| **v0.12** | **Reliable multi-process core:** task leases, audit privacy, stop kills Claude work, pinned web fetch, atomic approvals, hermetic tests | ✅ done in tests · **Mac checklist pending** |
| **M7 (v0.13)** | **iPhone companion:** Tailscale (tailnet only), passkey pairing, Face ID on every approval, private push notifications, Home Screen app | ✅ done in tests + headless browser · **Mac/iPhone check pending** |
| M6 | Mac voice: push-to-talk, local speech recognition, spoken replies, interrupt ≠ cancel | next |
| M4b | Touch ID for sensitive approvals on the Mac dashboard | later |
| M9+ | Mac automation, proactive monitoring, self-improvement proposals (isolated worktrees, owner-approved) | later |
| — | Search by meaning (embeddings) | only if keyword recall proves weak |

Superseded: M3c/SearXNG web search (research now goes through Claude Code; the SearXNG tool is optional and
off by default).
