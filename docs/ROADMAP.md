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
| **M4b (v0.14)** | **Touch ID for sensitive approvals on the Mac dashboard** | ✅ done in tests + headless browser · **Mac check pending** |
| **v0.15** | **Proactive JARVIS:** morning briefing (live, never stored), quiet hours, reminders, health alerts | ✅ done in tests + headless browser · **Mac check pending** |
| **M6 (v0.16)** | **Voice:** push-to-talk (Mac + iPhone), local whisper.cpp, on-device spoken replies, interrupt ≠ cancel | ✅ done with a protocol stand-in + headless browser · **real whisper.cpp + Mac check pending** |
| v0.16.1–2 | Pre-Mac review: fixes found by checking whisper.cpp's source and iPhone Safari's rules; `jarvis doctor` | ✅ done in tests + headless browser · **Mac check pending** |
| **v0.17** | **Mac apps, smarter chat (lookups), Briefing 2.0, benchmark (milestone 1), live replies, Help** | ✅ in tests · **Mac check pending** |
| **v0.17.2** | **M-B: release gate (`jarvis gate`) + docs synced with the code** | ✅ |
| M-A | Verification on the Mac: tests, `mac check`, benchmark (local + hybrid), Claude-app baseline, iPhone pairing and a notification, voice (optional) | **next (needs the Mac)** |
| M-C | Outcome Engine v1: goal interpretation, context packing, "no downgrades" routing, per-goal acceptance checks, measured on the benchmark before and after | after M-A |
| M9+ | Mac automation, deeper proactive monitoring (e.g. watched folders), self-improvement proposals (isolated worktrees, owner-approved) | later |
| — | Search by meaning (embeddings) | only if keyword recall proves weak |

### Signature systems (from the engineering constitution): where they stand

| System | Today | Built from |
|---|---|---|
| Flight Recorder | mostly exists | audit hash chain, task steps/checkpoints, approvals, evidence, model routes · missing: one timeline per task, external anchor |
| Outcome Engine | partial | planner + task engine + writes_verified + bench checks · missing: per-goal criteria, broader verification, replanning (M-C) |
| Intelligence Tournament | missing | research source verification only |
| Opportunity Radar | minimal | morning briefing |
| Personal Knowledge Graph | partial | memories with provenance, records, full-text search · no relations |
| Simulation Lab | partial | benchmark throwaway folders, stand-ins |
| Trust Contract | partial | global policy, tiers, privacy gate, budget, approvals · no per-task contract |
| Initiative Engine | missing | notifications only |
| Personal Operations Model | missing | on-demand calendar/reminder reads |
| Self-Test & Recovery Lab | partial | 350+ tests incl. real crash recovery, `jarvis doctor`, `jarvis bench`, `jarvis gate` · no recovery drills on a live install |

Superseded: M3c/SearXNG web search (research now goes through Claude Code; the SearXNG tool is optional and
off by default).
