# JARVIS phone preview (simulation)

The real JARVIS dashboard (`src/jarvis/server/static/`) running against a **simulated JARVIS inside the browser**
(`demo.js`). It exists so the dashboard can be tried on an iPhone without the Mac. Nothing in it connects to the
Mac, to any AI, or to the network.

```bash
uv run python demo/build.py               # demo/dist/jarvis-demo.html: published as a private claude.ai Artifact
uv run python demo/build.py --standalone  # demo/dist/jarvis-demo-standalone.html: open in any browser
```
The build copies the real `index.html`, `app.css` and `app.js` unchanged and adds `demo.js` + `demo.css`, so the
preview always shows the current dashboard. Rebuild after changing the dashboard.

## Real vs simulated

| Works for real (same code as on the Mac) | Simulated in the preview |
|---|---|
| Whole dashboard UI: HUD, missions, decisions, activity, memory panel, briefing, phone layout | JARVIS's server: answered by `demo.js` in the same data formats |
| Approve / reject, pause / resume / cancel, emergency stop + release (with confirmation) | AI replies, plans and research (canned, labelled) |
| In-page confirmation dialogs | Tasks "run" on a timer and touch no files |
| Simulation lab: create, rename, complete, delete tasks; permissions explainer with "Try it" | Face ID / Touch ID, voice, notifications, phone pairing (say "needs your Mac") |

**Storage:** demo data is kept in this browser's `localStorage` only (key `jarvis-demo-v1`): per device and per
browser, lost if site data is cleared, absent in private browsing (the demo then resets on reload). It never holds
credentials or private data, only the sample tasks and memories you type. **Reset demo** restores the start.

## Test checklist

Automated with Playwright at 390×844 (iPhone) and 1400×900. All 25 pass on the current build:
- Layout: no sideways scroll at 390 px; simulation banner visible; emergency stop fully on screen.
- Tasks: create (each permission kind), rename, complete, delete; Do → plan → run plan → approve → completed.
- Approvals: approving completes the task; rejecting blocks it; read-only actions run without asking;
  sensitive actions show "always requires confirmation".
- Emergency stop: one tap engages it; running tasks pause; new chat and new tasks are refused; release asks
  for confirmation; paused tasks stay paused after release.
- Persistence: demo data survives a reload; Reset restores the starting data; Briefing builds from demo data.
- Safety: zero network requests; no page errors.

By hand on the iPhone: open the link, scroll every panel, try each Simulation lab tab, press Emergency stop.

## Connecting it to the real backend

There's nothing to connect: the preview *is* the real dashboard. On the Mac, `jarvis dashboard` serves the same
page without `demo.js`, and the iPhone reaches it through `jarvis remote enable` (Tailscale + Face ID). The only
demo-only parts are the Simulation lab's task editor and permissions explainer. If they prove useful, they would
become real features with server endpoints (going through the task engine and permission engine, never around them).
