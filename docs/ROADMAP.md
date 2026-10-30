# Roadmap

Constraints: Intel Mac with 32 GB RAM, the iPhone, a $0 budget, free and local models only for now.
Claude Pro is a consumer subscription without API access, so it is not used by JARVIS.

| # | Milestone | Status |
|---|---|---|
| M0 | Scaffold, docs, test harness | ✅ done |
| M1 | Kernel: task engine, permissions, approvals, audit, emergency stop, CLI | ✅ done |
| M2 | Model router + adapters (Ollama local; free cloud tier adapter **disabled by default**), egress privacy gate (ask per transmission), budget guard at $0 | ✅ done (real-model run pending on Mac) |
| M3a | Production tools: files, web fetch | ✅ done |
| M3b | Web search backend + orchestrator (interpret → plan → check → execute → verify) | next |
| M4 | FastAPI + cinematic dashboard (live state, approvals, chat), passkey auth — **first-release demo: research brief** | |
| M5 | Memory: originals + derived memories with provenance, FTS5 + local embeddings, deletion propagation, memory center | |
| M6 | Mac voice: push-to-talk (whisper.cpp), TTS (`say`/Piper), interruption ≠ cancellation, then local wake word | |
| M7 | iPhone home-screen web app over Tailscale: pairing, approvals, notifications, task handoff | |
| M8 | launchd service, health monitor, encrypted backups + restore test, uninstall | |
| M9+ | Mac automation (Shortcuts/AppleScript/Playwright), proactive monitoring, self-improvement proposals | |

Things that must be validated on the real Mac: local model speed (benchmark before choosing),
whisper latency, Keychain, launchd, microphone, and Touch ID availability.
