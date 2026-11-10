"""Local dashboard server: the JARVIS command centre on http://127.0.0.1.

Security model (local-only, single owner):
- Binds to 127.0.0.1 only. Nothing is reachable from the network.
- A random session token is created at launch; the opening link sets it as an HttpOnly,
  SameSite=Strict cookie. Every request needs it.
- The Host header must be this loopback address (blocks DNS-rebinding attacks from web pages).
- State-changing requests also need a custom header and a same-origin Origin, which other
  websites cannot send (blocks CSRF).
- Every action goes through the same kernel (permissions, approvals, audit) as the CLI, with
  actor "user:dashboard".

Tasks submitted here are driven by this server's runner; tasks submitted from the CLI are left to
the CLI, so two processes never run the same task.
"""

from __future__ import annotations

import concurrent.futures as cf
import hmac
import json
import os
import re
import shutil
import subprocess
import sys
import secrets
import threading
import time
import traceback
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

from .. import __version__
from ..core import Kernel
from ..core.approvals import ApprovalStateError
from ..core.killswitch import EmergencyStop
from ..core.tasks import InvalidTransition, TaskState
from ..core.tools import ApprovalRequired
from ..core.util import now_iso
from ..codecheck import MAX_CASES, TEST_PROMPT, SandboxUnavailable, code_of, parse_cases, run_cases, wants_code
from ..orchestrator.answer_checks import chat_problems, facts_left_out, first_event_left_out
from ..orchestrator.lookup import FACTS_HEAD, lenient_json
from ..orchestrator.grounding import applies, unsupported_times
from ..models import ChatRequest, Message, Need, NoModelAvailable
from ..models.types import Category
from ..orchestrator import Orchestrator
from ..orchestrator.planner import describe_args
from ..persona import chat_abilities, priming_messages
from ..status import models_status

STATIC = Path(__file__).parent / "static"
COOKIE = "jarvis_session"
TOUCHID_COOKIE = "jarvis_touchid"
TOUCHID_SIGNIN = "Touch ID sign-in required"
# Reachable before Touch ID sign-in (once it is set up): the page shell and its files, signing in, and the
# emergency stop, which must always work in one tap.
PRE_SIGNIN_GET = ("/", "/bench", "/trust", "/proposals")
# Intelligence modes for chat. Same identity, memory, permissions and privacy gate in each; only how hard JARVIS
# works on the answer changes.
INTELLIGENCE: dict[str, dict[str, Any]] = {
    "quick": {"label": "Quick", "max_tokens": 600},
    "balanced": {"label": "Balanced", "max_tokens": 600},
    "deep": {"label": "Deep", "max_tokens": 2000},
}


def _mode(body: dict[str, Any]) -> str:
    mode = body.get("mode")
    return mode if isinstance(mode, str) and mode in INTELLIGENCE else "balanced"


PRE_SIGNIN_POST = ("/api/touchid/signin/options", "/api/touchid/signin", "/api/stop")
DEVICE_COOKIE = "jarvis_device"
PUBLIC_REMOTE_GET = {"/sw.js", "/manifest.webmanifest", "/static/phone.js", "/static/app.css", "/static/icon-192.png",
                     "/static/icon-512.png", "/static/apple-touch-icon.png"}
PUBLIC_REMOTE_POST = {"/api/pair/options", "/api/pair/finish", "/api/login/options", "/api/login/finish"}
MAX_BODY = 64 * 1024
RUNNER = "dashboard"
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
                               "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "microphone=(self), camera=(), geolocation=(), payment=(), usb=()",
    "Cache-Control": "no-store",
}


HOME = str(Path.home())


def tilde(value: Any) -> Any:
    """Show the home folder as ~ (display only)."""
    return value.replace(HOME, "~", 1) if isinstance(value, str) and value.startswith(HOME) else value


def _milestone_title(mid: Any) -> str:
    from ..evolution import MILESTONES
    return next((m.title for m in MILESTONES if m.id == mid), str(mid))


def describe_event(event: str, p: dict[str, Any], *, task_id: str | None = None,
                   goals: dict[str, str] | None = None) -> str:
    """One readable line per audit event, for the Activity panel. The full record stays in the log."""
    call = f"{p.get('tool')}.{p.get('action')}" if p.get("tool") else ""
    res = p.get("resource") or ""
    res = Path(res).name if isinstance(res, str) and "/" in res else res
    lines = {
        "task.created": lambda: "New task" + (f": {goals.get(task_id)}" if goals.get(task_id) else ""),
        "task.deleted": lambda: "Deleted a task and its history",
        "egress.grant_created": lambda: f"Standing permission: your {p.get('category')} may go to {p.get('provider')}",
        "egress.grant_revoked": lambda: "Withdrew a standing privacy permission",
        "model.no_route": lambda: "No suitable model for one request (details in Command center → Intelligence)",
        "egress.received": lambda: f"Reply from {p.get('provider')}/{p.get('model')} in {p.get('latency_s')}s",
        "chat.answer_check": lambda: ("Answer checked: fine" if not p.get("problems") else
                                      f"Answer checked: {p.get('problems')} problem(s){', retried' if p.get('retried') else ''}"),
        "evolution.milestone": lambda: f"Core evolution: verified “{_milestone_title(p.get('milestone'))}”",
        "evolution.check": lambda: f"Recorded `jarvis {str(p.get('check', '')).replace('_', ' ')}`: {'passed' if p.get('ok') else 'did not pass'}",
        "evolution.definitions": lambda: f"Projection milestones updated: definitions v{p.get('frm')} → v{p.get('to')}",
        "evolution.tier": lambda: f"Core evolution: tier {p.get('frm')} → {p.get('to')} ({p.get('verified')} milestones verified)",
        "chat.mode_fallback": lambda: f"{str(p.get('mode', '')).capitalize()} mode: answered with {p.get('model')} instead",
        "task.state": lambda: f"Task {p.get('frm', '').replace('_', ' ')} → {p.get('to', '').replace('_', ' ')}"
                              + (f" ({p['reason']})" if p.get("reason") else ""),
        "task.verified": lambda: "Verification " + ("passed" if p.get("ok") else "FAILED"),
        "permission.check": lambda: f"{call} {res} → {p.get('effect')}".strip(),
        "permission.denied": lambda: f"Denied {call}: {p.get('reason')}",
        "approval.requested": lambda: f"Asked you to approve {call} {res}".strip(),
        "approval.approved": lambda: "You approved a request",
        "approval.rejected": lambda: "You rejected a request",
        "approval.consumed": lambda: "Approval used",
        "memory.added": lambda: f"Remembered a {p.get('kind')} ({'confirmed' if p.get('origin') == 'explicit' else 'unconfirmed'})",
        "memory.deleted": lambda: "Deleted a memory",
        "memory.confirmed": lambda: "Confirmed a memory",
        "memory.edited": lambda: "Corrected a memory",
        "backup.created": lambda: f"Backup saved{' automatically' if p.get('automatic') else ''} and verified",
        "backup.failed": lambda: f"Backup FAILED: {p.get('error')}",
        "health.changed": lambda: "All systems healthy" if p.get("ok") else f"Health problem: {', '.join(p.get('problems', []))}",
        "memory.forget": lambda: f"Forgot {p.get('memories')} memories and {p.get('records')} records",
        "tool.start": lambda: f"Running {call}",
        "tool.result": lambda: f"Finished {call}",
        "tool.error": lambda: f"Tool error: {p.get('error')}",
        "model.route": lambda: f"Model chosen: {p.get('rationale', '')}",
        "model.local_call": lambda: f"{p.get('model')} answered ({p.get('output_tokens')} tokens, {p.get('latency_s')}s)",
        "egress.send": lambda: f"Sent {p.get('chars')} chars to {p.get('provider')}",
        "egress.denied": lambda: f"Blocked sending to {p.get('provider')}: {p.get('reason')}",
        "orchestrator.planned": lambda: f"Plan ({p.get('kind')}) by {p.get('model')}",
        "emergency_stop.engaged": lambda: f"EMERGENCY STOP: {p.get('reason')}",
        "emergency_stop.released": lambda: "Emergency stop released",
        "kernel.started": lambda: "JARVIS started",
        "device.pairing_created": lambda: "Made a phone pairing code (valid 10 minutes)",
        "device.paired": lambda: "A phone was paired",
        "device.signed_in": lambda: "Phone signed in with Face ID",
        "device.step_up": lambda: ("Face ID confirmed an action from the phone" if str(p.get("device_id", "")).startswith("dev")
                                   else "Touch ID confirmed an action"),
        "touchid.added": lambda: "Touch ID key added",
        "touchid.reset": lambda: f"Touch ID turned off from Terminal ({p.get('keys')} key(s) removed)",
        "device.denied": lambda: f"Phone request refused: {p.get('reason')}",
        "device.revoked": lambda: "A phone was removed",
        "push.subscribed": lambda: "Phone notifications turned on",
        "push.sent": lambda: f"Notification sent to {p.get('devices')} phone(s)"
                             + (f" — failed: {', '.join(p['errors'])}" if p.get("errors") else ""),
        "briefing.ready": lambda: "Morning briefing ready",
        "voice.transcribed": lambda: f"Heard you ({p.get('chars')} characters, {p.get('seconds')}s on this Mac)",
        "config.remote": lambda: "Phone access " + ("turned on" if p.get("enabled") else "turned off"),
    }
    goals = goals or {}
    try:
        text = lines[event]() if event in lines else json.dumps(p, ensure_ascii=False)
    except Exception:
        text = json.dumps(p, ensure_ascii=False)
    return text[:180]


MAC_TOOLS = ("calendar", "reminders", "notes", "mail", "apps")


def mac_preview(tool: str, action: str, args: dict[str, Any]) -> str:
    """Exactly what a Mac-app action will add or change, in plain words, for the approval card."""
    def when(v: Any) -> str:
        try:
            dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
            return (dt.astimezone() if dt.tzinfo else dt).strftime("%a %d %b %Y, %H:%M")
        except ValueError:
            return str(v)
    lines: list[str] = []
    if tool == "calendar":
        lines = [f"Event: {args.get('title')}", f"From: {when(args.get('start'))}", f"To:   {when(args.get('end'))}"]
        lines += [f"{k.capitalize()}: {args[k]}" for k in ("calendar", "location", "notes") if args.get(k)]
    elif tool == "reminders":
        lines = [f"{'Tick off' if action == 'complete' else 'Reminder'}: {args.get('title')}"]
        lines += [f"Due: {when(args['due'])}"] if args.get("due") else []
        lines += [f"{k.capitalize()}: {args[k]}" for k in ("list", "notes") if args.get(k)]
    elif tool == "notes":
        lines = [f"New note: {args.get('title')}"] + ([f"Folder: {args['folder']}"] if args.get("folder") else [])
        lines += ["", str(args.get("body", ""))]
    elif tool == "mail":
        to = args.get("to")
        lines = [f"Draft to: {', '.join(to) if isinstance(to, list) else to}", f"Subject: {args.get('subject')}",
                 "(saved as a draft: JARVIS never sends it)", "", str(args.get("body", ""))]
    elif tool == "apps":
        lines = [f"Open: {args.get('name')}"]
    return "\n".join(lines)[:4000]


def _content_length(h: BaseHTTPRequestHandler) -> int:
    """A body length we can safely read: a missing, negative or malformed header would otherwise make the
    read wait until the client hangs up."""
    try:
        length = int(h.headers.get("Content-Length") or 0)
    except ValueError:
        raise HttpError(400, "bad Content-Length") from None
    if length < 0:
        raise HttpError(400, "bad Content-Length")
    return length


def _benchtest_status(k) -> dict[str, Any] | None:
    from .. import benchtest
    return benchtest.status(k)


def _update_status(k) -> dict[str, Any] | None:
    from .. import update
    s = update.status(k.home)
    return {key: s.get(key) for key in ("state", "steps", "behind", "started", "finished")} if s else None


def _last_briefing(kernel: Kernel) -> str | None:
    from ..proactive import last_briefing_date

    return last_briefing_date(kernel)


def _tilde_evidence(evidence: Any) -> Any:
    if isinstance(evidence, dict) and isinstance(evidence.get("files"), list):
        evidence = {**evidence, "files": [{**f, "path": tilde(f.get("path"))} for f in evidence["files"]]}
    if isinstance(evidence, dict) and isinstance(evidence.get("checks"), list):
        evidence = {**evidence, "checks": [{**c, "text": str(c.get("text", "")).replace(HOME, "~")} for c in evidence["checks"]]}
    return evidence


class HttpError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _say_mac(tool: str, action: str, args: dict[str, Any], r: Any) -> str:
    """One plain sentence from a Music or system result."""
    r = r if isinstance(r, dict) else {}
    if (tool, action) == ("music", "now"):
        if not r.get("running"):
            return "Music isn't open."
        t = r.get("track") or {}
        return f"{r.get('state', '').capitalize()}: {t.get('name', 'unknown')}" + (f" by {t['artist']}" if t.get("artist") else "") + f" (volume {r.get('volume')}%)."
    if (tool, action) == ("music", "control"):
        return f"Music {r.get('state', 'updated')}" + (f": {r['track']}." if r.get("track") else ".")
    if (tool, action) == ("music", "playlist"):
        return f"Playing your playlist “{r.get('playing')}”."
    if action == "volume":
        return f"{'Music' if tool == 'music' else 'Mac'} volume set to {r.get('volume')}%."
    if (tool, action) == ("system", "focus"):
        return f"Do Not Disturb is {r.get('focus')}."
    parts = []
    if b := r.get("battery"):
        parts.append(f"battery {b['percent']}% ({b['state']}{', ' + b['remaining'] + ' left' if b.get('remaining') else ''})" if "percent" in b
                     else "no battery (on mains power)")
    if w := r.get("wifi"):
        parts.append(f"Wi-Fi {'on' if w['on'] else 'off'}")
    if d := r.get("disk"):
        parts.append(f"{d['free_gb']} GB free of {d['total_gb']} GB")
    if r.get("volume") is not None:
        parts.append(f"volume {r['volume']}%")
    if r.get("macos"):
        parts.append(f"macOS {r['macos']}")
    return ("Your Mac: " + ", ".join(parts) + ".") if parts else "Couldn't read the Mac's status."


class Dashboard:
    def __init__(self, kernel: Kernel, *, host: str = "127.0.0.1", port: int = 8765, token: str | None = None,
                 workers: int = 2, poll_s: float = 1.0, remote=None, local_hosts: set[str] | None = None):
        if host not in ("127.0.0.1", "::1"):
            raise ValueError("the dashboard only listens on loopback")
        self.kernel = kernel
        self.orch = Orchestrator(kernel)
        from ..orchestrator.lookup import LookupService
        self.lookup = LookupService(kernel, [str(r) for r in kernel.policy.roots])
        from ..proposals import Proposals
        self.proposals = Proposals(kernel)
        from ..projects import ProjectIdeas
        self.projects = ProjectIdeas(kernel)
        self._proposals_checked = -1e9
        self.token = token or secrets.token_urlsafe(32)
        self.jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._inflight: set[str] = set()
        self._pool = cf.ThreadPoolExecutor(max_workers=workers, thread_name_prefix="jarvis-runner")
        self._stop = threading.Event()
        self._poll_s = poll_s
        self._models_cache: tuple[float, Any] = (0.0, None)
        self._audit_cache: tuple[float, Any] = (0.0, None)
        self.httpd = ThreadingHTTPServer((host, port), self._handler_class())
        self.httpd.daemon_threads = True
        default_handle_error = self.httpd.handle_error

        def handle_error(request, client_address):  # a client hanging up mid-reply isn't worth a traceback
            if not isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):
                default_handle_error(request, client_address)
        self.httpd.handle_error = handle_error
        self.host, self.port = host, self.httpd.server_address[1]
        self._runner = threading.Thread(target=self._run_loop, name="jarvis-runner-loop", daemon=True)
        self._maint = threading.Thread(target=self._maintenance_loop, name="jarvis-maintenance", daemon=True)
        self._health: dict[str, Any] = {}
        self._evolution: dict[str, Any] | None = None
        self._intel_cache: tuple[float, dict[str, Any]] = (0.0, {})
        from ..telemetry import Telemetry
        self.telemetry = Telemetry(kernel.home)
        self.maintenance_s = 60.0
        self._serving = False
        # iPhone companion (only when `jarvis remote enable` has configured a Tailscale hostname)
        if remote is None:
            cfg = kernel.model_config.remote
            if cfg.get("enabled") and cfg.get("hostname"):
                from ..remote import RemoteAccess
                remote = RemoteAccess(kernel, cfg["hostname"])
        self.remote = remote or None
        self._local_hosts = local_hosts or {f"127.0.0.1:{self.port}", f"localhost:{self.port}", f"[::1]:{self.port}"}
        from ..remote import MacKeys
        from ..voice import Voice
        self.mac = MacKeys(kernel, self.port)  # Touch ID, once set up
        self.voice = Voice(kernel.model_config.voice, kernel.home)  # speech recognition on this Mac
        self.notifier = None
        if self.remote is not None:
            from ..remote import Notifier
            self.notifier = Notifier(kernel, self.remote.push)

    # ---- lifecycle ---------------------------------------------------------------------
    @property
    def url(self) -> str:
        return f"http://localhost:{self.port}/?token={self.token}"  # localhost: Touch ID passkeys need a name

    def start(self) -> None:
        """Run in background threads (used by tests)."""
        self._restore_jobs()
        self._report_update()
        self.voice.start()
        self._runner.start()
        self._maint.start()
        self._serving = True
        threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True).start()

    def serve_forever(self) -> None:
        self._restore_jobs()
        self._report_update()
        self.voice.start()
        self._runner.start()
        self._maint.start()
        self._serving = True
        # Load the local models in the background, so the first question after login doesn't wait for them.
        threading.Thread(target=self._warm_models, name="jarvis-warm-models", daemon=True).start()
        try:
            self.httpd.serve_forever(poll_interval=0.25)
        finally:
            self.shutdown()

    def _warm_models(self) -> None:
        if self._stop.wait(2.0):
            return
        try:
            self.kernel.models.warm_local()
        except Exception:  # never let a warm-up problem affect the dashboard; the next question loads the model
            pass

    def shutdown(self) -> None:
        self._stop.set()
        if self._serving:  # shutdown() waits for serve_forever and would hang if it never started
            self._serving = False
            self.httpd.shutdown()
        self.httpd.server_close()
        self._pool.shutdown(wait=False, cancel_futures=True)
        self.voice.stop()
        # Let the background loops finish their current pass before the caller closes the database.
        for thread in (self._runner, self._maint):
            if thread.is_alive() and thread is not threading.current_thread():
                thread.join(timeout=15)

    # ---- task runner -------------------------------------------------------------------
    def _run_loop(self) -> None:
        drivable = [TaskState.QUEUED, TaskState.RUNNING, TaskState.AWAITING_APPROVAL]
        while not self._stop.is_set():
            try:
                if not self.kernel.killswitch.engaged():
                    for task in self.kernel.tasks.list(drivable, limit=50):
                        tid = task["id"]
                        if task["context"].get("runner") != RUNNER:
                            continue
                        if task["state"] == TaskState.AWAITING_APPROVAL and self.kernel.approvals.pending(task_id=tid):
                            continue
                        with self._lock:
                            if tid in self._inflight:
                                continue
                            self._inflight.add(tid)
                        self._pool.submit(self._drive, tid)
            except Exception as exc:  # keep the loop alive; record what happened
                if self._stop.is_set():
                    return
                self.kernel.audit.record("dashboard.runner_error", error=f"{type(exc).__name__}: {exc}")
            if self.notifier is not None:
                try:
                    self.notifier.poll()
                except Exception as exc:
                    self.kernel.audit.record("push.error", error=f"{type(exc).__name__}: {exc}"[:300])
            self._stop.wait(self._poll_s)

    def benchtest_tick(self) -> str | None:
        """A benchmark you asked for starts when the Mac is idle (and for "tonight", in quiet hours)."""
        from .. import benchtest, proactive
        quiet = proactive.Schedule.from_config(self.kernel.model_config.proactive).quiet(datetime.now())
        return benchtest.tick(self.kernel, quiet=quiet)

    def _report_update(self) -> None:
        from .. import update
        try:
            update.report(self.kernel)
        except (OSError, ValueError, KeyError):
            pass

    # ---- health & automatic backups --------------------------------------------------
    def backup_settings(self) -> dict[str, Any]:
        cfg = self.kernel.model_config.backup
        folder = Path(os.path.expanduser(cfg["dir"])) if cfg.get("dir") else self.kernel.home / "backups"
        return {"auto": bool(cfg.get("auto", True)), "keep": int(cfg.get("keep", 14)), "dir": folder}

    def check_health(self) -> dict[str, Any]:
        from ..backup import get_passphrase, last_backup

        k = self.kernel
        items: list[dict[str, Any]] = []

        def add(name: str, ok: bool, detail: str) -> None:
            items.append({"name": name, "ok": ok, "detail": detail})

        try:
            k.db.one("SELECT 1")
            add("Database", True, "ok")
        except Exception as exc:
            add("Database", False, f"{type(exc).__name__}: {exc}")
        chain = k.audit.verify()
        add("Audit log", chain.ok, f"intact · {chain.checked} entries" if chain.ok else f"broken at #{chain.first_bad_seq}")
        status = models_status(k)
        local = [p for p in status["providers"] if p["location"] == "local"]
        add("Local models", any(p["available"] for p in local),
            "online" if any(p["available"] for p in local) else "Ollama isn't answering — open the Ollama app")
        for p in status["providers"]:
            if p["location"] == "cloud":
                add(p["name"].capitalize(), bool(p["available"]), "ready" if p["available"] else (p["error"] or "unavailable"))
        if self.voice.enabled:
            v = self.voice.status()
            add("Voice", v["available"], "ready" if v["available"] else
                ("; ".join(v["problems"]) or "speech recogniser not running — see `jarvis voice status`"))
        free = shutil.disk_usage(k.home).free / 1e9
        add("Disk space", free > 2, f"{free:.0f} GB free")
        b = self.backup_settings()
        last = last_backup(b["dir"])
        if not get_passphrase():
            add("Backups", False, "not set up — run `jarvis backup now` once")
        elif not last:
            add("Backups", False, "no backups yet")
        else:
            add("Backups", last["age_hours"] < 48, f"last {last['age_hours']:.0f}h ago · {last['count']} kept")
        return {"items": items, "ok": all(i["ok"] for i in items), "checked": time.time(),
                "service": os.environ.get("JARVIS_SERVICE") == "1"}

    def maybe_backup(self) -> dict[str, Any] | None:
        """Daily automatic backup — only once you've set up backups yourself (so you have the passphrase)."""
        from ..backup import BackupError, create_backup, get_passphrase, last_backup

        b = self.backup_settings()
        if not b["auto"] or not get_passphrase():
            return None
        last = last_backup(b["dir"])
        if last and last["age_hours"] < 24:
            return None
        k = self.kernel
        try:
            r = create_backup(k.home, k.policy_path, k.config_path, dest_dir=b["dir"], keep=b["keep"])
        except (BackupError, OSError, ValueError) as exc:
            k.audit.record("backup.failed", error=str(exc)[:300])
            return {"ok": False, "error": str(exc)}
        k.audit.record("backup.created", file=r.path.name, bytes=r.bytes, verified=r.verified, automatic=True)
        return {"ok": True, "path": str(r.path)}

    def maybe_briefing(self, now: datetime | None = None) -> bool:
        """Announce the morning briefing once a day at the configured time (the content is built when opened)."""
        from .. import proactive

        now = now or datetime.now().astimezone()
        schedule = proactive.Schedule.from_config(self.kernel.model_config.proactive)
        if not schedule.briefing_due(now, proactive.last_briefing_date(self.kernel)):
            return False
        proactive.mark_briefing_sent(self.kernel, now)
        self.kernel.audit.record("briefing.ready")
        if self.notifier is not None:
            self.notifier.briefing_ready()
        return True

    def learn_cycle(self) -> dict[str, Any]:
        """OBSERVE + LEARN: new audit entries become outcomes and lessons (respects autonomy and the emergency stop);
        then, with tier 7 on, act on strong lessons and run the nightly self-checks."""
        from ..learn import Pipeline, autopilot
        result = Pipeline(self.kernel).run()
        autopilot.act_on_lessons(self.kernel)
        autopilot.act_on_tournament(self.kernel)
        autopilot.apply_to_router(self.kernel)   # also clears the nudges when tier 7 is off or the stop is on
        autopilot.nightly(self.kernel)
        return result

    def _learn_cached(self) -> dict[str, Any]:
        now = time.monotonic()
        cached = getattr(self, "_learn_cache", None)
        if not cached or now - cached[0] > 5:
            try:
                self._learn_cache = (now, self.learn_state())
            except Exception as exc:  # noqa: BLE001 - never break the dashboard over the learning summary
                self._learn_cache = (now, {"error": f"{type(exc).__name__}"})
        return self._learn_cache[1]

    def learn_state(self) -> dict[str, Any]:
        from .. import learn
        return {"summary": learn.summary(self.kernel), "autonomy": learn.Autonomy(self.kernel).state()}

    def _discovery_facts(self) -> dict[str, Any]:
        status = self._models_cache[1] or models_status(self.kernel)
        evo = self._evolution or {}
        verified = {m["id"] for m in evo.get("milestones", []) if m.get("verified")}
        return {"models_available": [m for p in status["providers"] if p.get("location") == "local" for m in p.get("available", [])],
                "voice": "voice" in verified, "backups": "backups" in verified, "touch_id": "touch_id" in verified,
                "iphone": "iphone" in verified}

    def projection(self, module: str) -> dict[str, Any]:
        """Real data for one projection module (read-only)."""
        from ..learn import projections
        return projections.data(self, module)

    def evolution(self) -> dict[str, Any]:
        """Which milestones are verified right now (and since when): drives the avatar's evolution tier."""
        from .. import evolution

        status = self._models_cache[1] or models_status(self.kernel)
        facts = evolution.facts_from(
            self.kernel, health=self._health or None, providers=status["providers"],
            capabilities={"mac_apps": self.kernel.registry.action("calendar", "events") is not None},
            voice_ready=self.voice.enabled and bool(self.voice.status().get("available")),
            paired_phones=len([d for d in self.remote.devices.list() if not d.get("revoked_at")])
            if self.remote else 0,
            touch_id=self.mac.enabled())
        return evolution.evaluate(self.kernel, facts)

    def intelligence(self) -> dict[str, Any]:
        """Recent model calls from the audit log (model, where, latency, tokens): counts and timings only."""
        now = time.time()
        if now - self._intel_cache[0] < 2:
            return self._intel_cache[1]
        calls = []
        for e in self.kernel.audit.entries(limit=400):
            p = e["payload"]
            if e["event"] == "model.local_call":
                calls.append({"model": p.get("model"), "location": "local", "purpose": p.get("purpose"),
                              "latency_s": p.get("latency_s"), "output_tokens": p.get("output_tokens"), "ts": e["ts"]})
            elif e["event"] == "egress.received":
                calls.append({"model": f"{p.get('provider')}/{p.get('model')}", "location": "cloud", "purpose": None,
                              "latency_s": p.get("latency_s"), "output_tokens": p.get("output_tokens"), "ts": e["ts"]})
        per: dict[str, dict[str, Any]] = {}
        for c in calls[-50:]:
            m = per.setdefault(c["model"], {"model": c["model"], "location": c["location"], "calls": 0, "seconds": 0.0,
                                            "tokens": 0})
            m["calls"] += 1
            m["seconds"] += float(c["latency_s"] or 0)
            m["tokens"] += int(c["output_tokens"] or 0)
        for m in per.values():
            m["avg_latency_s"] = round(m["seconds"] / m["calls"], 2) if m["calls"] else None
            m["tokens_per_s"] = round(m["tokens"] / m["seconds"], 1) if m["seconds"] else None
        out = {"last": calls[-1] if calls else None, "models": sorted(per.values(), key=lambda m: -m["calls"]),
               "window": min(len(calls), 50)}
        self._intel_cache = (now, out)
        return out

    def briefing(self) -> dict[str, Any]:
        from ..proactive import build_briefing

        return build_briefing(self.kernel, health=self._health or None)

    def _maintenance_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.maybe_backup()
                before = self._health.get("ok")
                self._health = self.check_health()
                if before is not None and before != self._health["ok"]:
                    bad = [i["name"] for i in self._health["items"] if not i["ok"]]
                    self.kernel.audit.record("health.changed", ok=self._health["ok"], problems=bad)
                    if self.notifier is not None:
                        self.notifier.health_changed(self._health["ok"])
                self.maybe_briefing()
                self._evolution = self.evolution()
                self.learn_cycle()
                self.benchtest_tick()
            except Exception as exc:
                if self._stop.is_set():
                    return  # shutting down: the database may already be closed
                self.kernel.audit.record("dashboard.maintenance_error", error=f"{type(exc).__name__}: {exc}"[:300])
            self._stop.wait(self.maintenance_s)

    def _drive(self, tid: str) -> None:
        from ..core.tasks import TaskBusy

        try:
            self.kernel.engine.run(tid)
        except TaskBusy:
            pass  # another JARVIS process (e.g. a terminal command) is running it; it will finish there
        except Exception as exc:
            self.kernel.audit.record("dashboard.runner_error", task_id=tid, error=f"{type(exc).__name__}: {exc}",
                                     trace=traceback.format_exc()[-1500:])
        finally:
            with self._lock:
                self._inflight.discard(tid)

    # ---- planning jobs (planning takes ~1 min on CPU, so it runs in the background) ----
    def start_plan(self, request: str, *, replan_of: str | None = None, earlier: str | None = None) -> str:
        job_id = secrets.token_hex(6)
        job = {"id": job_id, "request": request, "state": "planning", "started": time.time()}
        if replan_of:
            job.update(replan_of=replan_of, earlier=earlier)
        with self._lock:
            self.jobs = {k: v for k, v in self.jobs.items() if v["state"] in ("planning", "waiting_approval")
                         or time.time() - v["started"] < 3600}
            self.jobs[job_id] = job
        self._persist_job(job)
        self._pool.submit(self._plan_job, job)
        return job_id

    # ---- Mission Control: planning jobs survive a restart (plan_jobs) ---------------------------------------------
    def _persist_job(self, job: dict[str, Any]) -> None:
        """Save a planning job: a plan waiting for you, or one still being planned, isn't lost if JARVIS restarts."""
        from dataclasses import asdict
        data = {k: v for k, v in job.items() if k != "plan"}
        plan = job.get("plan")
        if plan is not None:
            data["plan"] = {"kind": plan.kind, "goal": plan.goal, "message": plan.message, "model": plan.model,
                            "attempts": plan.attempts, "steps": [asdict(st) for st in plan.steps]}
        state = job["state"] if job["state"] in ("planning", "waiting_approval", "ready", "submitted") else "ready"
        now = now_iso()
        try:
            with self.kernel.db.tx() as c:
                c.execute("INSERT INTO plan_jobs (id, request, state, data, replan_of, created_at, updated_at) VALUES (?,?,?,?,?,?,?) "
                          "ON CONFLICT(id) DO UPDATE SET state = excluded.state, data = excluded.data, updated_at = excluded.updated_at",
                          (job["id"], job["request"], state, json.dumps(data, default=str), job.get("replan_of"), now, now))
        except Exception as exc:  # noqa: BLE001 - saving is a safety net; planning carries on without it
            self.kernel.audit.record("dashboard.plan_save_failed", error=type(exc).__name__)

    def _forget_job(self, job_id: str) -> None:
        with self.kernel.db.tx() as c:
            c.execute("DELETE FROM plan_jobs WHERE id = ?", (job_id,))

    def _restore_jobs(self) -> int:
        """At start: bring back plans that were waiting for you, and restart planning that was cut off (waiting on
        the same approval if it was waiting for one). Old or already-run jobs are dropped."""
        from ..core.tasks import StepSpec
        from ..orchestrator.planner import Plan
        db = self.kernel.db
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        with db.tx() as c:
            c.execute("DELETE FROM plan_jobs WHERE updated_at < ? OR state = 'submitted'", (cutoff,))
        restored = 0
        for row in db.query("SELECT * FROM plan_jobs ORDER BY created_at"):
            try:
                job = json.loads(row["data"])
                p = job.pop("plan", None)
                if p is not None:
                    steps = [StepSpec(**st) for st in p["steps"]]
                    if any(self.kernel.registry.action(st.tool, st.action) is None for st in steps):
                        job.update(state="ready", kind="failed", message="JARVIS's abilities changed since this was planned: plan it again.")
                    else:
                        job["plan"] = Plan(p["kind"], goal=p["goal"], steps=steps, message=p["message"], model=p["model"], attempts=p["attempts"])
            except Exception:  # noqa: BLE001 - an unreadable saved job is dropped, never half-restored
                self._forget_job(row["id"])
                continue
            job["restored"] = True
            with self._lock:
                self.jobs[job["id"]] = job
            if row["state"] in ("planning", "waiting_approval"):
                self._pool.submit(self._plan_job, job)
            restored += 1
        if restored:
            self.kernel.audit.record("dashboard.plans_restored", count=restored)
        return restored

    def replan(self, tid: str, *, actor: str) -> str:
        """One new plan for a failed mission, told what already happened. It goes through the usual review: nothing
        runs until you press Run. A mission gets one replan; a replan can't be replanned."""
        from ..core.tasks import TaskState
        from ..orchestrator import Orchestrator
        k = self.kernel
        try:
            task = k.tasks.get(tid)
        except KeyError:
            raise HttpError(404, "no such mission") from None
        if task["state"] != TaskState.FAILED:
            raise HttpError(409, "only a failed mission can be planned again")
        if task["context"].get("replan_of"):
            raise HttpError(409, "this was already the second attempt: describe the task again to start fresh")
        if self._replanned(tid):
            raise HttpError(409, "this mission has already been planned again")
        job_id = self.start_plan(task["request"], replan_of=tid, earlier=Orchestrator.failure_story(task, k.tasks.steps(tid)))
        k.audit.record("mission.replan", actor=actor, task_id=tid, job=job_id)
        return job_id

    def _replanned(self, tid: str) -> bool:
        db = self.kernel.db
        return bool(db.one("SELECT 1 FROM plan_jobs WHERE replan_of = ?", (tid,))
                    or db.one("SELECT 1 FROM tasks WHERE json_extract(context, '$.replan_of') = ?", (tid,))
                    or any(j.get("replan_of") == tid for j in self.jobs.values()))

    def mac_command(self, body: dict[str, Any]) -> dict[str, Any]:
        """Run one Music or system action through the gateway: reads run, changes ask (unless your policy allows them),
        an approved request runs when sent again. The reply is worded from the result, no model involved."""
        from ..core.tools import ApprovalRequired as Needed
        from ..core.tools import PermissionDenied, ToolError
        tool, action, args = body.get("tool"), body.get("action"), body.get("args") or {}
        if tool not in ("music", "system") or not isinstance(action, str) or not isinstance(args, dict):
            raise HttpError(400, "only Music and system commands run this way")
        started = time.time()
        summary = {("music", "control"): f"Music: {args.get('action')}", ("music", "playlist"): f"Music: play the playlist “{args.get('name')}”",
                   ("music", "volume"): f"Music volume to {args.get('level')}%", ("system", "volume"): f"Mac volume to {args.get('level')}%",
                   ("system", "focus"): f"Do Not Disturb {args.get('state')}"}.get((tool, action))
        try:
            r = self.kernel.gateway.invoke(tool, action, args, summary=summary)
        except Needed as exc:
            return {"needs_approval": True, "approval_id": exc.approval_id, "summary": summary or f"{tool}.{action}"}
        except PermissionDenied as exc:   # refused by your rules (audited as permission.denied by the gateway)
            raise HttpError(403, f"Refused by your rules: {exc}") from None
        except ToolError as exc:          # a bad argument or the Mac app couldn't do it: say so plainly
            raise HttpError(400, str(exc)[:300]) from None
        return {"text": _say_mac(tool, action, args, r), "model": "mac/tools", "location": "local",
                "seconds": round(time.time() - started, 1)}

    def route_message(self, message: str) -> dict[str, str]:
        """Ask, research or do? A suggestion for the dashboard, which confirms research and tasks with one tap.
        Rules first; when they are unsure, one tiny call to a local model (``local_only``: never leaves the Mac)."""
        from .. import intent

        def complete(prompt: str) -> str:
            # keep_speed: a 6-token label never needs the stronger (or reasoning) local model, even when the message
            # itself looks like maths or code
            r = self.kernel.models.complete(Need("chat", prefer="speed", local_only=True, keep_speed=True),
                                            ChatRequest((Message("user", prompt, Category.CONVERSATION),), max_tokens=6),
                                            purpose="message type (local)")
            return r.text

        return intent.classify(message, complete)

    def _plan_job(self, job: dict[str, Any]) -> None:
        try:
            plan = self._plan_with_consent(job)
            job.pop("approval_id", None)
            job.update(kind=plan.kind, goal=plan.goal, message=plan.message, model=plan.model,
                       steps=[{"description": s.description, "call": f"{s.tool}.{s.action}",
                               "args": describe_args(s.args, 200), "depends_on": s.depends_on} for s in plan.steps],
                       plan=plan, state="ready")
            if plan.kind == "plan":   # how JARVIS will check it's done, shown before you press Run
                from ..orchestrator.criteria import criteria_for
                job["criteria"] = [{**c, "text": c["text"].replace(HOME, "~")} for c in criteria_for(plan.steps)]
        except NoModelAvailable as exc:
            job.update(state="ready", kind="failed", message=f"No model can plan this: {exc}",
                       reasons=exc.reasons)
        except Exception as exc:
            job.update(state="ready", kind="failed", message=f"Planning failed: {type(exc).__name__}: {exc}")
        job["seconds"] = round(time.time() - job["started"], 1)
        if not self._stop.is_set():
            self._persist_job(job)

    def _plan_with_consent(self, job: dict[str, Any]):
        """Plan with the best model. If that needs your approval to send the request to the cloud, wait
        for your decision in Decisions: approved → retry the identical request; rejected or ignored for
        15 minutes → plan with a local model instead."""
        earlier = job.get("earlier")
        if job.get("state") == "waiting_approval" and job.get("approval_id"):   # restored: keep waiting on the same request
            approval_id = job["approval_id"]
        else:
            try:
                return self.orch.plan(job["request"], earlier=earlier)
            except ApprovalRequired as exc:
                approval_id = exc.approval_id
        job.update(state="waiting_approval", approval_id=approval_id)
        self._persist_job(job)
        deadline = time.time() + 900
        decision = "expired"
        while time.time() < deadline and not self._stop.is_set():
            try:
                decision = self.kernel.approvals.get(approval_id)["state"]
            except KeyError:
                decision = "expired"
            if decision != "pending":
                break
            time.sleep(0.5)
        else:
            decision = "expired"
        if self._stop.is_set():   # shutting down mid-wait: stays saved as waiting, resumes after the restart
            raise RuntimeError("JARVIS is shutting down")
        job["state"] = "planning"
        if decision == "approved":
            job["started"] = time.time()
            return self.orch.plan(job["request"], earlier=earlier)
        job["note"] = "Planned locally (you kept this request on your Mac)."
        return self.orch.plan(job["request"], local_only=True, earlier=earlier)

    def run_plan(self, job_id: str) -> str:
        job = self.jobs.get(job_id)
        if not job or job.get("kind") != "plan" or job.get("task_id"):
            raise HttpError(409, "this plan cannot be run")
        job["task_id"] = self.orch.submit(job["request"], job["plan"], actor="user:dashboard", runner=RUNNER,
                                          replan_of=job.get("replan_of"))
        job["state"] = "submitted"
        self._persist_job(job)
        return job["task_id"]

    # ---- chat --------------------------------------------------------------------------
    def chat(self, message: str, history: list[dict[str, str]], *, local_only: bool = False,
             session: str = "dashboard", on_token=None, mode: str = "balanced", on_event=None) -> dict[str, Any]:
        """``mode`` (see ``INTELLIGENCE``): quick = fastest local model, no pre-call unless a lookup could help;
        balanced = the routing you configured (hybrid: rated by the goal reader); deep = the strongest approved
        model and longer answers, falling back to the best local model, and saying so. The privacy gate, consent
        and budget apply exactly the same in every mode. ``on_event(dict)`` hears the real stages for display."""
        memory = self.kernel.memory
        started = time.time()
        mode = mode if mode in INTELLIGENCE else "balanced"
        stage = on_event or (lambda event: None)
        stage({"stage": "understanding", "mode": mode})
        # Goal reader: one local call picks read-only lookups (calendar, reminders, notes, files) and, in hybrid mode,
        # rates difficulty so routing needs no second call. Quick and Deep don't need a rating, so they only make
        # the call when the message could need a lookup.
        found = self.lookup.run(message, rate=mode == "balanced" and self.kernel.models.router.mode == "hybrid")
        if found.checked:
            stage({"stage": "lookup", "checked": list(found.checked)})
        msgs = list(priming_messages(chat_abilities(memory.settings.enabled, lookups=bool(self.lookup.available()))))
        recalled = memory.recall(message)
        if context := memory.context_message(recalled):
            msgs.append(context)
        stays_here = mode == "quick" or self.kernel.models.chat_stays_local(
            message, local_only=local_only, level=found.level if mode == "balanced" else None)
        rest = []
        if stays_here and (rest := memory.everything_else(recalled)):  # small store: the rest too, never sent off
            msgs.append(memory.context_message(rest, local_only=True, heading=(
                "Everything else you remember about the owner, oldest first (a later fact replaces an earlier one; "
                "use only what's relevant):")))
            recalled = recalled + rest
        # Careful (strongest local model) only when the answer has to read JARVIS's worked-out facts, or the question
        # matched a memory and the rest of a small store came with it (combining them is the hard part). Not for
        # every chat just because memories exist: "tell me a joke" stays on the fast model.
        profile_ids = {m["id"] for m in memory.profile()}
        matched = any(m["id"] not in profile_ids for m in recalled[:len(recalled) - len(rest)])
        careful = (bool(rest) and matched) or bool(found.context and FACTS_HEAD in found.context.content)
        turns = 0
        for turn in history[-10:]:
            if turn.get("role") in ("user", "assistant") and isinstance(turn.get("content"), str):
                msgs.append(Message(turn["role"], turn["content"][:4000], Category.CONVERSATION))
                turns += 1
        if found.context:
            msgs.append(found.context)
        from ..learn import recall
        past, past_n = recall.context_message(self.kernel, message)   # answers you rated, for a similar question
        if past:
            msgs.append(past)
        msgs.append(Message("user", message, Category.CONVERSATION))
        stage({"stage": "context", "memories": len(recalled), "turns": turns, "past": past_n})
        max_tokens = INTELLIGENCE[mode]["max_tokens"]
        mode_note = None
        try:
            if mode == "quick":
                need = Need("chat", prefer="speed", local_only=True, keep_speed=True)
            elif mode == "deep":
                need = Need("chat", min_quality=5, prefer="quality", local_only=local_only)
            else:
                need = Need("chat", prefer="auto", local_only=local_only, careful=careful)
            request = ChatRequest(tuple(msgs), max_tokens=max_tokens)
            try:
                r = self.kernel.models.complete(need, request, purpose="dashboard chat", on_token=on_token,
                                                level=found.level, on_event=on_event)
            except NoModelAvailable:
                # Quick with no local model, or Deep with no stronger model approved: use the best model there is
                # and say so, rather than fail. Same gate, same consent.
                if mode == "balanced" or (mode == "quick" and local_only):
                    raise
                fallback = Need("chat", prefer="speed" if mode == "quick" else "quality", local_only=local_only,
                                keep_speed=mode == "quick")
                r = self.kernel.models.complete(fallback, request, purpose="dashboard chat", on_token=on_token,
                                                on_event=on_event)
                why = ("no local model is available" if mode == "quick"
                       else "no stronger model is available (is Claude turned on?)")
                mode_note = f"{INTELLIGENCE[mode]['label']}: {why}; answered with {r.model}."
                self.kernel.audit.record("chat.mode_fallback", mode=mode, model=f"{r.provider}/{r.model}")
            if mode_note:
                r = replace(r, note=((r.note + " ") if r.note else "") + mode_note)
            # Retries and fixes are local-only at any quality: they must never become a consent question.
            local_need = replace(need, local_only=True, min_quality=1)
            grounded, retried = None, False
            checks_times = found.context is not None and applies(found.checked)
            bad = unsupported_times(r.text, found.context.content, message) if checks_times else []
            problems = ([f"your answer mentions {', '.join(bad)}, which isn't in the looked-up data: use only times "
                         "from the <lookup> data"] if bad else [])
            problems += chat_problems(message, r.text, looked_up=found.context is not None)
            if found.context is not None and (left := facts_left_out(r.text, found.context.content)):
                problems.append(f"your answer leaves out {', '.join(left)}, which JARVIS listed as overdue or due in "
                                "the time asked about: include every item JARVIS listed")
            if found.context is not None and (first := first_event_left_out(message, r.text, found.context.content)):
                problems.append(f"the first event JARVIS worked out is {', '.join(first)} (see \"First event on\" in "
                                "the <lookup> data): give that as the first commitment, with its time")
            # One retry with the problems pointed out, then show what's still wrong rather than hide it. Only for a
            # local answer: retrying a Claude answer would be a new request needing your consent again.
            if problems and r.provider in self.kernel.models.router.local:
                retried = True
                stage({"stage": "checking", "problems": len(problems)})
                retry = msgs + [Message("assistant", r.text, Category.CONVERSATION),
                                Message("user", "Check before answering again:\n" + "\n".join(f"- {x}" for x in problems)
                                        + "\nReply with the corrected answer only.", Category.CONVERSATION)]
                # always local: the first answer was, and a retry must never become a consent question
                r = self.kernel.models.complete(local_need, ChatRequest(tuple(retry), max_tokens=max_tokens),
                                                purpose="dashboard chat (answer check retry)", level=found.level,
                                                question=message)
                bad = unsupported_times(r.text, found.context.content, message) if checks_times else []
            self.kernel.audit.record("chat.answer_check", problems=len(problems), retried=retried,
                                     still=len(chat_problems(message, r.text, looked_up=found.context is not None, puzzle=False)))
            if checks_times:
                grounded = not bad
                self.kernel.audit.record("chat.grounding", ok=grounded, unsupported_times=len(bad), retried=retried)
                if bad:
                    r = replace(r, note=((r.note + " ") if r.note else "")
                                + f"⚠ Unverified: mentions {', '.join(bad)}, not found in your calendar or reminders.")
            code_test = None
            if (self.kernel.model_config.coding.get("self_test") and r.provider in self.kernel.models.router.local
                    and wants_code(message) and code_of(r.text)):
                stage({"stage": "checking", "code_test": True})
                r, code_test = self._self_test(message, msgs, r, local_need, found.level)
        except NoModelAvailable as exc:
            return {"error": f"No model available: {exc}", "reasons": exc.reasons}
        except ApprovalRequired as exc:
            appr = self.kernel.approvals.get(exc.approval_id)
            return {"needs_approval": True, "approval_id": exc.approval_id, "summary": appr["summary"]}
        record = memory.learn_from(session, message, r.text)
        memory.link_informed([m["id"] for m in recalled if m.get("id")], record)   # which memories this answer was given
        return {"record": record, "past": past_n, "code_test": code_test, "text": r.text, "model": f"{r.provider}/{r.model}", "seconds": round(time.time() - started, 1),
                "tokens": r.usage.output_tokens, "note": r.note, "memories_used": len(recalled),
                "checked": found.checked, "offer_plan": found.change, "grounded": grounded,
                "lookup_notes": found.why + found.notes, "mode": mode,
                "location": "local" if r.provider in self.kernel.models.router.local else "cloud"}

    def _self_test(self, message: str, msgs: list, r, need, level) -> tuple[Any, dict | None]:
        """Coding self-test (opt-in): local tests from the request alone, run in the sandbox, one fix if any fail.
        Returns the answer to show and a summary (counts only); never raises."""
        code, name = code_of(r.text, message)
        prompt = TEST_PROMPT.format(name=name, max=MAX_CASES)
        try:
            t = self.kernel.models.complete(
                Need("json", prefer="auto", local_only=True),
                ChatRequest((Message("system", prompt, Category.SYSTEM_PROMPT),
                             Message("user", message, Category.CONVERSATION, local_only=True)),
                            max_tokens=500, temperature=0.0, json_mode=True), purpose="coding self-test cases")
            cases = parse_cases(lenient_json(t.text), name)
        except Exception as exc:  # no local model, bad JSON…: show the answer untested, and say so
            self.kernel.audit.record("chat.code_test", ran=False, reason=type(exc).__name__)
            return r, {"ran": False, "reason": "couldn't write test cases"}
        if not cases:
            self.kernel.audit.record("chat.code_test", ran=False, reason="no usable cases")
            return r, {"ran": False, "reason": "no usable test cases"}
        try:
            first = run_cases(code, cases)
        except SandboxUnavailable as exc:
            self.kernel.audit.record("chat.code_test", ran=False, reason="no sandbox")
            return r, {"ran": False, "reason": str(exc)}
        best, best_run, fixed = r, first, False
        if not first.all_passed:
            retry = msgs + [Message("assistant", r.text, Category.CONVERSATION),
                            Message("user", "JARVIS ran your code on test cases written from my request:\n"
                                    + first.describe()[:1500] + "\nFix the code if it is wrong. If a case contradicts "
                                    "my request, keep the code right and say which case. Reply with the complete "
                                    "corrected code in one Python code block.", Category.CONVERSATION)]
            # always local: the first answer was, and a fix must never become a consent question
            r2 = self.kernel.models.complete(replace(need, local_only=True, min_quality=1), ChatRequest(tuple(retry), max_tokens=900),
                                             purpose="dashboard chat (coding self-test fix)", level=level,
                                             question=message)
            again = code_of(r2.text, message)
            if again:
                second = run_cases(again[0], cases)
                if second.error is None and (first.error is not None or second.passed >= first.passed):
                    best, best_run, fixed = r2, second, True
        self.kernel.audit.record("chat.code_test", ran=True, cases=best_run.cases, passed=best_run.passed,
                                 first_passed=first.passed, fixed=fixed, error=best_run.error is not None)
        summary = {"ran": True, "cases": best_run.cases, "passed": best_run.passed, "fixed": fixed,
                   "error": best_run.error}
        note = (f"🧪 Tested on {best_run.cases} case(s) JARVIS wrote: {best_run.passed} passed"
                + (" (after one fix)" if fixed else "") + (f"; it failed to run: {best_run.error}" if best_run.error else ""))
        return replace(best, note=((best.note + " ") if best.note else "") + note), summary

    def research(self, question: str, *, deep: bool = False, session: str = "dashboard") -> dict[str, Any]:
        from ..orchestrator.research import research_request, result_payload

        memory = self.kernel.memory
        recalled = memory.recall(question)
        context = memory.context_message(recalled)
        started = time.time()
        try:
            r = self.kernel.models.research(research_request(question, context.content if context else None),
                                            purpose="dashboard web research", deep=deep)
        except ApprovalRequired as exc:
            appr = self.kernel.approvals.get(exc.approval_id)
            return {"needs_approval": True, "approval_id": exc.approval_id, "summary": appr["summary"]}
        except NoModelAvailable as exc:
            return {"error": "Web research needs Claude. Run `jarvis use-claude on` (and make sure you're signed in).",
                    "reasons": exc.reasons}
        memory.learn_from(session, question, r.text)
        return {**result_payload(r), "seconds": round(time.time() - started, 1), "memories_used": len(recalled)}

    # ---- state snapshot ----------------------------------------------------------------
    def state(self, device: dict | None = None) -> dict[str, Any]:
        k = self.kernel
        now = time.time()
        if now - self._models_cache[0] > 5:
            self._models_cache = (now, models_status(k))
        if now - self._audit_cache[0] > 60:
            self._audit_cache = (now, k.audit.verify().__dict__)

        tasks = []
        for t in k.tasks.list(limit=25):
            steps = k.tasks.steps(t["id"])
            tasks.append({
                "id": t["id"], "goal": t["goal"], "request": t["request"], "state": t["state"],
                "created_at": t["created_at"], "updated_at": t["updated_at"], "error": t["error"],
                "next_action": t["next_action"], "runner": t["context"].get("runner"),
                "evidence": _tilde_evidence((t["result"] or {}).get("evidence")),
                # Mission Control: what "done" means for this mission, and whether it can be planned once more
                "criteria": [{**c, "text": str(c.get("text", "")).replace(HOME, "~")} for c in t["context"].get("criteria") or []] or None,
                "replan_of": t["context"].get("replan_of"),
                "replannable": t["state"] == TaskState.FAILED and not t["context"].get("replan_of") and not self._replanned(t["id"]),
                "steps": [{"id": s["id"], "n": s["idx"], "description": s["description"], "call": f"{s['tool']}.{s['action']}",
                           "state": s["state"], "attempts": s["attempts"], "error": s["error"]} for s in steps],
                "final_text": next((s["result"].get("text") for s in reversed(steps) if s["tool"] == "llm"
                                    and s["state"] == "done" and isinstance(s["result"], dict)), None),
            })

        approvals = []
        for a in k.approvals.pending():
            preview = None
            if a["task_id"] and a["step_id"] and a["tool"] in ("fs", *MAC_TOOLS):
                try:
                    args = self.orch.preview_args(a["task_id"], a["step_id"])
                    if a["tool"] == "fs":
                        preview = args.get("content")
                        if preview is None and a["action"] == "move":
                            preview = f"Move to: {tilde(str(args.get('to')))}"
                    else:
                        preview = mac_preview(a["tool"], a["action"], args)
                except Exception:
                    preview = None
            approvals.append({"id": a["id"], "task_id": a["task_id"], "tool": a["tool"], "action": a["action"],
                              "resource": tilde(a["resource"]), "tier": a["tier"], "reason": a["reason"],
                              "summary": a["summary"].replace(HOME, "~"), "created_at": a["created_at"],
                              "preview": preview[:4000] if isinstance(preview, str) else None})

        jobs = [{k2: v for k2, v in j.items() if k2 not in ("plan", "earlier")} for j in
                sorted(self.jobs.values(), key=lambda j: j["started"], reverse=True)[:5]]
        for j in jobs:
            if j["state"] in ("planning", "waiting_approval"):
                j["elapsed"] = round(now - j["started"])

        goals = {t["id"]: t["goal"] for t in tasks}
        audit = [{"seq": e["seq"], "ts": e["ts"], "actor": e["actor"], "event": e["event"], "task_id": e["task_id"],
                  "detail": describe_event(e["event"], e["payload"], task_id=e["task_id"], goals=goals)}
                 for e in k.audit.entries(limit=40) if e["event"] not in ("approval.consumed",)]
        return {
            "version": __version__, "time": now,
            "emergency_stop": k.killswitch.state(),
            "tasks": tasks, "approvals": approvals, "jobs": jobs, "models": self._models_cache[1],
            "audit": list(reversed(audit)), "audit_chain": self._audit_cache[1],
            "roots": [tilde(str(r)) for r in k.policy.roots], "policy_loaded": k.policy_path.exists(),
            "memory": {**k.memory.counts(), "enabled": k.memory.settings.enabled},
            "research_available": self.kernel.registry.get("research") is not None,
            "capabilities": {"mac_apps": self.kernel.registry.action("calendar", "events") is not None,
                             "research": self.kernel.registry.get("research") is not None,
                             "voice": self.voice.enabled},
            "health": self._health or None,
            "remote": {"enabled": self.remote is not None, "hostname": self.remote.hostname if self.remote else None,
                       "this_device": {"id": device["id"], "name": device["name"]} if device else None,
                       "devices": self.remote.devices.list() if self.remote else []},
            "touch_id": {"enabled": self.mac.enabled(), "keys": self.mac.keys()},
            "update": None if device else _update_status(k),
            "benchtest": None if device else _benchtest_status(k),
            "briefing": {"last_date": _last_briefing(k)},
            "voice": self.voice.status(),
            "telemetry": self.telemetry.snapshot(),
            "evolution": self._evolution,
            "intelligence": self.intelligence(),
            "learn": self._learn_cached(),
        }

    # ---- HTTP plumbing -----------------------------------------------------------------
    def _handler_class(self) -> type[BaseHTTPRequestHandler]:
        app = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "JARVIS"
            sys_version = ""

            def log_message(self, *args: Any) -> None:
                pass

            def do_GET(self) -> None:  # noqa: N802
                app._dispatch(self, "GET")

            def do_POST(self) -> None:  # noqa: N802
                app._dispatch(self, "POST")

        return Handler

    def _send(self, h: BaseHTTPRequestHandler, status: int, body: bytes, ctype: str,
              extra: dict[str, str] | None = None) -> None:
        h.send_response(status)
        h.send_header("Content-Type", ctype)
        h.send_header("Content-Length", str(len(body)))
        for k, v in {**SECURITY_HEADERS, **(extra or {})}.items():
            h.send_header(k, v)
        h.end_headers()
        h.wfile.write(body)

    def _json(self, h: BaseHTTPRequestHandler, status: int, obj: Any, extra: dict[str, str] | None = None) -> None:
        self._send(h, status, json.dumps(obj, default=str).encode(), "application/json", extra)

    @staticmethod
    def _cookie(h: BaseHTTPRequestHandler, name: str) -> str | None:
        for part in (h.headers.get("Cookie") or "").split(";"):
            key, _, value = part.strip().partition("=")
            if key == name:
                return value
        return None

    def _authed(self, h: BaseHTTPRequestHandler) -> bool:
        for part in (h.headers.get("Cookie") or "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == COOKIE and hmac.compare_digest(value, self.token):
                return True
        return False

    def _dispatch(self, h: BaseHTTPRequestHandler, method: str) -> None:
        try:
            host = h.headers.get("Host")
            if host in self._local_hosts:
                is_remote = False
            elif self.remote is not None and host in self.remote.hosts:
                is_remote = True
            else:
                raise HttpError(403, "unexpected Host header")
            url = urlsplit(h.path)
            if is_remote:
                return self._dispatch_remote(h, method, url)

            if method == "GET" and url.path == "/" and not host.startswith("localhost:"):
                # Touch ID passkeys belong to "localhost" (never to an IP address), so the page lives there.
                return self._send(h, 303, b"", "text/plain",
                                  {"Location": f"http://localhost:{self.port}/" + (f"?{url.query}" if url.query else "")})
            if method == "GET" and url.path == "/":
                token = parse_qs(url.query).get("token", [""])[0]
                if token and hmac.compare_digest(token, self.token):
                    cookie = f"{COOKIE}={self.token}; HttpOnly; SameSite=Strict; Path=/"
                    return self._send(h, 303, b"", "text/plain", {"Location": "/", "Set-Cookie": cookie})
                if not self._authed(h):
                    page = (b"<!doctype html><meta charset=utf-8><title>JARVIS</title><body style='font-family:"
                            b"system-ui;background:#05080d;color:#cfe3f0;padding:3rem'><h1>JARVIS</h1><p>Open the link "
                            b"printed by <code>jarvis dashboard</code> in Terminal.</p>")
                    return self._send(h, 401, page, "text/html; charset=utf-8")
                return self._send(h, 200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")

            if not self._authed(h):
                raise HttpError(401, "not signed in")
            if self.mac.enabled() and not self.mac.signed_in(self._cookie(h, TOUCHID_COOKIE)):
                ok = (url.path in PRE_SIGNIN_GET or url.path.startswith("/static/")) if method == "GET" \
                    else url.path in PRE_SIGNIN_POST
                if not ok:
                    raise HttpError(401, TOUCHID_SIGNIN)
            if method == "GET":
                return self._get(h, url, device=None)
            if url.path == "/api/voice/transcribe":
                return self._json(h, 200, self._transcribe(h, origin=f"http://{host}", actor="user:dashboard"))
            if url.path == "/api/chat/stream":
                return self._stream_chat(h, self._read_post(h, origin=f"http://{host}"))
            body = self._read_post(h, origin=f"http://{host}")
            if url.path == "/api/touchid/signin":
                return self._touchid_signin(h, body)
            result = self._post_local(url.path, body)
            if url.path == "/api/touchid/enroll/finish" and not self.mac.signed_in(self._cookie(h, TOUCHID_COOKIE)):
                # you just used Touch ID to set it up: that counts as signing in on this browser
                return self._json(h, 200, result, {"Set-Cookie": self._touchid_cookie(self.mac.new_session())})
            return self._json(h, 200, result)
        except HttpError as exc:
            self._json(h, exc.status, {"error": str(exc)})
        except (InvalidTransition, ApprovalStateError, KeyError, ValueError, PermissionError) as exc:
            self._json(h, 409 if not isinstance(exc, PermissionError) else 403, {"error": str(exc)})
        except Exception as exc:
            self.kernel.audit.record("dashboard.error", error=f"{type(exc).__name__}: {exc}")
            self._json(h, 500, {"error": "internal error (recorded in the audit log)"})

    def _stream_chat(self, h: BaseHTTPRequestHandler, body: dict[str, Any]) -> None:
        """Chat, with a local model's reply shown as it's written: one JSON object per line ({"t": text} pieces),
        then {"done": <the same result /api/chat returns>}. Same answer as /api/chat; only the delivery differs."""
        message = body.get("message")
        if not isinstance(message, str) or not message.strip() or len(message) > 4000:
            raise HttpError(400, "'message' must be non-empty text under 4000 characters")
        history = body.get("history") if isinstance(body.get("history"), list) else []
        session = body.get("session") if isinstance(body.get("session"), str) else "dashboard"
        h.send_response(200)
        h.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        for k, v in SECURITY_HEADERS.items():
            h.send_header(k, v)
        h.send_header("Connection", "close")  # the reply ends when the connection does (no length known upfront)
        h.end_headers()

        def line(obj: Any) -> None:
            h.wfile.write((json.dumps(obj) + "\n").encode())
            h.wfile.flush()

        def on_token(piece: str) -> None:
            if self.kernel.killswitch.engaged():
                raise EmergencyStop("emergency stop")
            if piece:
                line({"t": piece})
            else:  # no words yet: a bare newline (ignored by the page) shows whether the page is still there
                h.wfile.write(b"\n")
                h.wfile.flush()

        def on_event(event: dict[str, Any]) -> None:
            line({"s": event})
        try:
            result = self.chat(message.strip(), history, local_only=body.get("local_only") is True,
                               session=session[:64], on_token=on_token, mode=_mode(body), on_event=on_event)
        except (BrokenPipeError, ConnectionResetError):
            return  # the page was closed; generation has already stopped
        except EmergencyStop:
            result = {"error": "Emergency stop: the reply was cut off.", "stopped": True}
        except Exception as exc:
            self.kernel.audit.record("dashboard.error", error=f"{type(exc).__name__}: {exc}"[:300])
            result = {"error": "internal error (recorded in the audit log)"}
        try:
            line({"done": result})
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _transcribe(self, h: BaseHTTPRequestHandler, *, origin: str, actor: str) -> dict[str, Any]:
        """Speech → text on this Mac. Same CSRF defences as other POSTs; the audio is never written to disk."""
        from ..voice import MAX_BYTES, VoiceError

        if h.headers.get("X-Requested-By") != "jarvis":
            raise HttpError(403, "missing request header")
        if h.headers.get("Origin") not in (None, origin):
            raise HttpError(403, "cross-origin request refused")
        if not self.voice.enabled:
            raise HttpError(409, "voice is off — run `jarvis voice enable` on the Mac")
        if (h.headers.get("Content-Type") or "").split(";")[0].strip() != "audio/wav":
            raise HttpError(415, "expected audio/wav")
        length = _content_length(h)
        if length > MAX_BYTES:
            raise HttpError(413, "recordings are limited to 60 seconds")
        audio = h.rfile.read(length)
        started = time.monotonic()
        try:
            text = self.voice.client.transcribe(audio)
        except VoiceError as exc:
            raise HttpError(422, str(exc)) from None
        finally:
            del audio
        self.kernel.audit.record("voice.transcribed", actor=actor, chars=len(text),
                                 seconds=round(time.monotonic() - started, 1))
        return {"text": text, "seconds": round(time.monotonic() - started, 1)}

    def _read_post(self, h: BaseHTTPRequestHandler, *, origin: str) -> dict[str, Any]:
        """CSRF defences + body parsing for every state-changing request."""
        if h.headers.get("X-Requested-By") != "jarvis":
            raise HttpError(403, "missing request header")
        if h.headers.get("Origin") not in (None, origin):
            raise HttpError(403, "cross-origin request refused")
        length = _content_length(h)
        if length > MAX_BODY:
            raise HttpError(413, "request too large")
        try:
            body = json.loads(h.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            raise HttpError(400, "invalid JSON") from None
        if not isinstance(body, dict):
            raise HttpError(400, "expected a JSON object")
        return body

    def _get(self, h: BaseHTTPRequestHandler, url, *, device: dict | None) -> None:
        if url.path in ("/static/app.js", "/static/app.css", "/static/phone.js", "/static/qrcode.js",
                        "/static/bench.js", "/static/bench.css", "/static/trust.js", "/static/proposals.js",
                        "/static/avatar.js", "/static/avatar.css", "/static/avatar3d.js", "/static/avatar-state.js",
                        "/static/avatar3d-shaders.js", "/static/avatar3d-geometry.js",
                        "/static/avatar3d-reactor.js", "/static/avatar3d-neural.js", "/static/avatar3d-particles.js",
                        "/static/avatar3d-environment.js", "/static/avatar3d-projections.js",
                        "/static/avatar3d-worker.js", "/static/avatar3d-camera.js", "/static/avatar-presets.js",
                        "/static/avatar-events.js", "/static/avatar-sound.js",
                        "/static/avatar3d-transform.js"):
            ctype = "text/javascript" if url.path.endswith(".js") else "text/css"
            return self._send(h, 200, (STATIC / url.path.rsplit("/", 1)[1]).read_bytes(), f"{ctype}; charset=utf-8")
        if url.path == "/static/vendor/three.module.min.js":  # Three.js r160, served from this Mac (MIT)
            return self._send(h, 200, (STATIC / "vendor" / "three.module.min.js").read_bytes(), "text/javascript; charset=utf-8")
        if m := re.fullmatch(r"/static/fonts/(rajdhani-[567]00\.woff2)", url.path):
            return self._send(h, 200, (STATIC / "fonts" / m.group(1)).read_bytes(), "font/woff2",
                              {"Cache-Control": "max-age=86400"})
        if m := re.fullmatch(r"/static/((?:icon-(?:192|512)|apple-touch-icon)\.png)", url.path):
            return self._send(h, 200, (STATIC / m.group(1)).read_bytes(), "image/png", {"Cache-Control": "max-age=86400"})
        if url.path == "/manifest.webmanifest":
            return self._send(h, 200, (STATIC / "manifest.webmanifest").read_bytes(), "application/manifest+json")
        if url.path == "/sw.js":
            return self._send(h, 200, (STATIC / "sw.js").read_bytes(), "text/javascript; charset=utf-8",
                              {"Service-Worker-Allowed": "/"})
        if url.path == "/api/state":
            return self._json(h, 200, self.state(device=device))
        if url.path == "/api/memory":
            q = parse_qs(url.query).get("q", [""])[0][:200]
            mem = self.kernel.memory
            items = mem.search(q) if q.strip() else mem.list(limit=50)
            return self._json(h, 200, {"memories": items, "counts": mem.counts(),
                                       "records": mem.search_records(q, limit=10) if q.strip() else []})
        if m := re.fullmatch(r"/api/tasks/([\w-]+)/timeline", url.path):
            from ..flight import timeline
            return self._json(h, 200, timeline(self.kernel, m.group(1)))
        if m := re.fullmatch(r"/api/tasks/([\w-]+)/audit", url.path):
            return self._json(h, 200, self.kernel.audit.entries(task_id=m.group(1), limit=300))
        if url.path == "/api/briefing":
            return self._json(h, 200, self.briefing())
        if url.path == "/api/initiative":   # one ranked list of suggestions (suggests only; nothing runs)
            from .. import initiative
            return self._json(h, 200, initiative.feed(self.kernel, health=self._health or None))
        if url.path == "/bench":
            return self._send(h, 200, (STATIC / "bench.html").read_bytes(), "text/html; charset=utf-8")
        if url.path.startswith("/api/bench"):
            return self._bench_api(h, url)
        if url.path == "/trust":
            return self._send(h, 200, (STATIC / "trust.html").read_bytes(), "text/html; charset=utf-8")
        if url.path == "/api/trust":
            from ..trust import contract
            return self._json(h, 200, contract(self.kernel).as_dict())
        if url.path == "/proposals":
            return self._send(h, 200, (STATIC / "proposals.html").read_bytes(), "text/html; charset=utf-8")
        if url.path == "/api/projects":
            return self._json(h, 200, {"ideas": self.projects.list(), **self.projects.status()})
        if url.path == "/api/proposals":
            if time.monotonic() - self._proposals_checked > 600:  # look for new findings at most every 10 minutes
                self.proposals.refresh()
                self._proposals_checked = time.monotonic()
            return self._json(h, 200, {"proposals": self.proposals.list()})
        if url.path == "/api/learn":
            from .. import learn
            from ..learn import analysis
            from ..learn import autopilot
            return self._json(h, 200, {**self.learn_state(), "lessons": learn.lessons(self.kernel),
                                       "adjustments": autopilot.adjustments(self.kernel),
                                       "experiments": analysis.Lab(self.kernel).list(), "kinds": analysis.KINDS,
                                       "discoveries": analysis.discover(self.kernel, self._discovery_facts())})
        if url.path == "/api/learn/tournament":
            from ..learn import analysis
            return self._json(h, 200, analysis.tournament(self.kernel))
        if m := re.fullmatch(r"/api/projection/(\w+)", url.path):
            try:
                return self._json(h, 200, self.projection(m.group(1)))
            except KeyError:
                raise HttpError(404, "no such projection") from None
        if url.path == "/api/push/key" and self.remote is not None:
            return self._json(h, 200, {"key": self.remote.push.public_key})
        raise HttpError(404, "not found")

    def _bench_api(self, h: BaseHTTPRequestHandler, url) -> None:
        """Benchmark history (read-only): ``/api/bench``, ``/api/bench/<run id>``, ``/api/bench/compare``."""
        from ..bench import history
        out = self.kernel.home / "bench-results"
        q = parse_qs(url.query)
        try:
            if url.path == "/api/bench":
                return self._json(h, 200, {"runs": history.runs(out)})
            if url.path == "/api/bench/compare":
                return self._json(h, 200, history.before_after(out, q.get("before", [None])[0], q.get("after", [None])[0]))
            if m := re.fullmatch(r"/api/bench/([\w-]+)", url.path):
                return self._json(h, 200, history.detail(out, m.group(1)))
        except history.HistoryError as exc:
            raise HttpError(404, str(exc)) from None
        raise HttpError(404, "not found")

    def _dispatch_remote(self, h: BaseHTTPRequestHandler, method: str, url) -> None:
        """Requests from the paired iPhone, via Tailscale. A device session is required for everything
        except the pairing/sign-in ceremonies and static assets. Signing in uses Face ID; after that only the dangerous
        few (see STEP_UP and high-risk approvals) need it again."""
        from ..remote import LOCAL_ONLY, STEP_UP, DeviceError
        from ..remote.passkeys import needs_step_up
        from ..remote.webauthn import WebAuthnError

        remote = self.remote
        session = self._cookie(h, DEVICE_COOKIE)
        device = remote.devices.session_device(session)
        secure_cookie = "; HttpOnly; Secure; SameSite=Strict; Path=/"
        try:
            if method == "GET":
                if url.path == "/":
                    page = "index.html" if device else "phone.html"
                    return self._send(h, 200, (STATIC / page).read_bytes(), "text/html; charset=utf-8")
                if url.path in PUBLIC_REMOTE_GET or url.path.startswith("/static/fonts/"):
                    return self._get(h, url, device=device)
                if device is None:
                    raise HttpError(401, "not signed in")
                return self._get(h, url, device=device)

            if url.path == "/api/voice/transcribe":
                if device is None:
                    raise HttpError(401, "not signed in")
                return self._json(h, 200, self._transcribe(h, origin=remote.origin,
                                                           actor=f"user:phone:{device['name']}"))
            if url.path == "/api/chat/stream":
                if device is None:
                    raise HttpError(401, "not signed in")
                return self._stream_chat(h, self._read_post(h, origin=remote.origin))
            body = self._read_post(h, origin=remote.origin)
            path = url.path
            if path in PUBLIC_REMOTE_POST:
                def text(name: str, limit: int = 200) -> str:
                    value = body.get(name)
                    if not isinstance(value, str) or len(value) > limit:
                        raise HttpError(400, f"'{name}' is required")
                    return value
                if path == "/api/pair/options":
                    return self._json(h, 200, remote.pairing_options(text("code"), body.get("name") or "iPhone"))
                if path == "/api/pair/finish":
                    token = remote.pairing_finish(text("code"), str(body.get("name") or "iPhone")[:60],
                                                  body.get("credential"))
                    return self._json(h, 200, {"ok": True},
                                      {"Set-Cookie": f"{DEVICE_COOKIE}={token}; Max-Age=2592000{secure_cookie}"})
                if path == "/api/login/options":
                    return self._json(h, 200, remote.login_options())
                token = remote.login_finish(text("challengeId"), body.get("credential"))
                return self._json(h, 200, {"ok": True},
                                  {"Set-Cookie": f"{DEVICE_COOKIE}={token}; Max-Age=2592000{secure_cookie}"})

            if device is None:
                raise HttpError(401, "not signed in")
            actor = f"user:phone:{device['name']}"
            if any(re.fullmatch(p, path) for p in LOCAL_ONLY):
                raise HttpError(403, "only possible from the Mac")
            if path == "/api/experiments" and body.get("kind") == "trial":   # runs code: never started from the phone
                self.kernel.audit.record("device.denied", path=path, reason="change trials can only be started from the Mac")
                raise HttpError(403, "change trials can only be started from the Mac")
            if path == "/api/stepup/options":
                target, target_body = body.get("path"), body.get("body")
                if not isinstance(target, str) or not isinstance(target_body, dict):
                    raise HttpError(400, "path and body are required")
                return self._json(h, 200, remote.stepup_options(device, target, target_body))
            if path == "/api/logout":
                remote.devices.end_session(session)
                return self._json(h, 200, {"ok": True}, {"Set-Cookie": f"{DEVICE_COOKIE}=; Max-Age=0{secure_cookie}"})
            if path == "/api/push/subscribe":
                remote.push.subscribe(device["id"], body.get("subscription") or {})
                return self._json(h, 200, {"ok": True})
            needs_face_id = needs_step_up(path, body, STEP_UP, self._approval_tier)
            if needs_face_id:
                remote.verify_stepup(device, path, body, actor=actor)
                body = {k: v for k, v in body.items() if k not in ("assertion", "challengeId")}
            return self._json(h, 200, self._post(path, body, actor=actor, device=device))
        except (DeviceError, WebAuthnError) as exc:
            self.kernel.audit.record("device.denied", path=url.path, reason=str(exc)[:200])
            raise HttpError(403, str(exc)) from None

    def _approval_tier(self, approval_id: str) -> int:
        return int(self.kernel.approvals.get(approval_id)["tier"])

    @staticmethod
    def _touchid_cookie(token: str) -> str:
        return f"{TOUCHID_COOKIE}={token}; HttpOnly; SameSite=Strict; Path=/"  # ends with the browser session

    def _touchid_signin(self, h: BaseHTTPRequestHandler, body: dict[str, Any]) -> None:
        from ..remote import DeviceError, WebAuthnError
        try:
            token = self.mac.signin_finish(body.get("challengeId"), body.get("credential"))
        except (DeviceError, WebAuthnError) as exc:
            self.kernel.audit.record("device.denied", path="/api/touchid/signin", reason=str(exc)[:200])
            raise HttpError(403, str(exc)) from None
        return self._json(h, 200, {"ok": True}, {"Set-Cookie": self._touchid_cookie(token)})

    def _post_local(self, path: str, body: dict[str, Any]) -> Any:
        """The Mac dashboard. Once Touch ID is set up you sign in with it; then only the dangerous few (MAC_STEP_UP and
        high-risk approvals) need a fresh Touch ID for that exact request."""
        from ..remote import DeviceError, WebAuthnError
        from ..remote.mac import MAC_STEP_UP
        from ..remote.passkeys import needs_step_up

        actor = "user:dashboard"
        try:
            if path == "/api/touchid/signin/options":
                return self.mac.signin_options()
            if path == "/api/stepup/options":
                target, target_body = body.get("path"), body.get("body")
                if not isinstance(target, str) or not isinstance(target_body, dict):
                    raise HttpError(400, "path and body are required")
                return self.mac.stepup_options(None, target, target_body)
            if path == "/api/touchid/enroll/finish":
                name, cid = body.get("name"), body.get("challengeId")
                if not isinstance(name, str) or not isinstance(cid, str):
                    raise HttpError(400, "name and challengeId are required")
                return {"id": self.mac.enroll_finish(cid, name[:60], body.get("credential"), by=actor)}
            needs_touch_id = needs_step_up(path, body, MAC_STEP_UP, self._approval_tier)
            if needs_touch_id and self.mac.enabled():
                self.mac.verify_stepup(None, path, body, actor=actor)
                body = {k: v for k, v in body.items() if k not in ("assertion", "challengeId")}
        except (DeviceError, WebAuthnError) as exc:
            self.kernel.audit.record("device.denied", path=path, reason=str(exc)[:200])
            raise HttpError(403, str(exc)) from None
        return self._post(path, body, actor=actor, device=None)

    def _post(self, path: str, body: dict[str, Any], *, actor: str = "user:dashboard",
              device: dict | None = None) -> Any:
        k = self.kernel

        def text(name: str, limit: int = 4000) -> str:
            value = body.get(name)
            if not isinstance(value, str) or not value.strip() or len(value) > limit:
                raise HttpError(400, f"'{name}' must be non-empty text under {limit} characters")
            return value.strip()

        if path == "/api/chat":
            history = body.get("history") if isinstance(body.get("history"), list) else []
            session = body.get("session") if isinstance(body.get("session"), str) else "dashboard"
            return self.chat(text("message"), history, local_only=body.get("local_only") is True, mode=_mode(body),
                             session=session[:64])
        if path == "/api/research":
            session = body.get("session") if isinstance(body.get("session"), str) else "dashboard"
            return self.research(text("question", 2000), deep=body.get("deep") is True, session=session[:64])
        if path == "/api/memory/remember":
            mid = self.kernel.memory.remember(text("text", 500), origin="explicit", by=actor)
            return {"id": mid, "stored": mid is not None}
        if m := re.fullmatch(r"/api/memory/([\w-]+)/(confirm|delete|important|edit)", path):
            mem, op = self.kernel.memory, m.group(2)
            if op == "confirm":
                mem.confirm(m.group(1), by=actor)
            elif op == "delete":
                mem.delete(m.group(1), by=actor)
            elif op == "important":
                mem.set_important(m.group(1), body.get("important") is True, by=actor)
            else:
                mem.edit(m.group(1), text("text", 500), by=actor)
            return {"ok": True}
        if path == "/api/memory/forget":
            query, dry = text("query", 200), body.get("confirm") is not True
            out = self.kernel.forget(query, by=actor, dry_run=dry)
            if not dry and query.strip():   # the dashboard's own copy of saved plans goes too
                with self._lock:
                    self.jobs = {i: j for i, j in self.jobs.items() if query.strip().lower() not in j["request"].lower()}
            return out
        if path == "/api/feedback":
            from .. import learn
            rating = body.get("rating")
            if rating not in (-1, 1):
                raise HttpError(400, "rating must be -1 or 1")
            target = body.get("target") if body.get("target") in ("reply", "task") else "reply"
            return {"id": learn.add_feedback(k, target=target, ref=text("ref", 120), rating=rating,
                                             model=body.get("model") if isinstance(body.get("model"), str) else None,
                                             mode=body.get("mode") if isinstance(body.get("mode"), str) else None,
                                             reason=body.get("reason") if isinstance(body.get("reason"), str) else None, by=actor)}
        if m := re.fullmatch(r"/api/lessons/(les_\w+)/(confirm|reject|delete)", path):
            from .. import learn
            try:
                learn.decide_lesson(k, m.group(1), m.group(2), by=actor)
            except KeyError:
                raise HttpError(404, "no such lesson") from None
            return {"ok": True}
        if path == "/api/autonomy":
            from ..learn import Autonomy, AutonomyError
            a = Autonomy(k)
            try:
                if "tier" in body:
                    a.set_tier(int(body["tier"]), body.get("on") is True, by=actor)
                elif "pause" in body:
                    a.set_pause(str(body["pause"]), body.get("paused") is True, by=actor)
                else:
                    raise HttpError(400, "tier or pause is required")
            except (AutonomyError, ValueError) as exc:
                raise HttpError(400, str(exc)) from None
            return a.state()
        if path == "/api/adjustments/undo":
            from ..learn import autopilot
            autopilot.undo(k, text("lesson", 200), by=actor)
            return {"adjustments": autopilot.adjustments(k)}
        if path == "/api/experiments":
            from ..learn import analysis
            try:
                kind = text("kind", 40)
                if kind == "trial" and not actor.startswith("user:dashboard"):   # second check: only the Mac's own dashboard
                    raise HttpError(403, "change trials can only be started from the Mac")
                return {"id": analysis.Lab(k).start(kind, by=actor, ref=body.get("ref") if isinstance(body.get("ref"), str) else None,
                                                    baseline=body.get("baseline") if isinstance(body.get("baseline"), str) else "HEAD")}
            except analysis.LabError as exc:
                raise HttpError(409, str(exc)) from None
        if path == "/api/command":   # a direct Mac command (Music, system), through the permission engine
            return self.mac_command(body)
        if path == "/api/route":   # which kind of message: rules, then a model on this Mac (never the cloud)
            return self.route_message(text("text", 2000))
        if path == "/api/plan":
            return {"job_id": self.start_plan(text("request"))}
        if m := re.fullmatch(r"/api/plan/(\w+)/(run|discard)", path):
            if m.group(2) == "run":
                return {"task_id": self.run_plan(m.group(1))}
            self.jobs.pop(m.group(1), None)
            self._forget_job(m.group(1))
            return {"ok": True}
        if path == "/api/health/check":
            self._health = self.check_health()
            return self._health
        if path == "/api/backup/now":   # Mac only (LOCAL_ONLY)
            from ..backup import BackupError, create_backup, get_passphrase
            if not get_passphrase():   # the first backup prints its passphrase once; that belongs in Terminal, not here
                raise HttpError(400, "set up backups once in Terminal first: uv run jarvis backup now (save the passphrase it prints)")
            b = self.backup_settings()
            try:
                r = create_backup(k.home, k.policy_path, k.config_path, dest_dir=b["dir"], keep=b["keep"])
            except (BackupError, OSError, ValueError) as exc:
                k.audit.record("backup.failed", error=str(exc)[:300])
                raise HttpError(400, f"backup failed: {exc}") from None
            k.audit.record("backup.created", actor=actor, file=r.path.name, bytes=r.bytes, verified=r.verified)
            self._health = self.check_health()
            return {"ok": True, "file": r.path.name}
        if path == "/api/benchtest":   # Mac only (LOCAL_ONLY): you ask; it runs when the Mac is idle
            from .. import benchtest
            try:
                benchtest.request(k, by=actor, when=str(body.get("when", "tonight")), set_=str(body.get("set", "hard")),
                                  repeat=int(body.get("repeat", 5)))
            except (ValueError, TypeError) as exc:
                raise HttpError(400, str(exc)) from None
            self.benchtest_tick()
            return benchtest.status(k)
        if path == "/api/benchtest/cancel":
            from .. import benchtest
            benchtest.cancel(k, by=actor)
            return benchtest.status(k)
        if path == "/api/update/check":   # Mac only (LOCAL_ONLY): fetches the branch, changes nothing
            from .. import update
            try:
                c = update.check()
            except (update.UpdateError, OSError, subprocess.TimeoutExpired) as exc:
                raise HttpError(400, f"couldn't check for updates: {exc}") from None
            k.audit.record("update.checked", actor=actor, behind=c.get("behind", 0))
            return c
        if path == "/api/update/start":   # Mac only, and Touch ID when it's set up (MAC_STEP_UP)
            from .. import update
            try:
                return update.start(k, port=self.port, by=actor)
            except (update.UpdateError, OSError, subprocess.TimeoutExpired) as exc:
                raise HttpError(400, str(exc)) from None
        if path == "/api/initiative/dismiss":
            from .. import initiative
            size = body.get("size") if isinstance(body.get("size"), int) else 1
            initiative.dismiss(self.kernel, text("key", 200), by=actor, size=size)
            return {"ok": True}
        if m := re.fullmatch(r"/api/tasks/([\w-]+)/replan", path):   # one new plan for a failed mission (reviewed as usual)
            return {"job_id": self.replan(m.group(1), actor=actor)}
        if m := re.fullmatch(r"/api/approvals/([\w-]+)", path):
            approve = body.get("approve")
            if not isinstance(approve, bool):
                raise HttpError(400, "'approve' must be true or false")
            k.approvals.decide(m.group(1), approve=approve, by=actor)
            return {"ok": True}
        if m := re.fullmatch(r"/api/tasks/([\w-]+)/steps/([\w-]+)/resolve", path):
            # You say whether an interrupted step (outcome unknown) actually happened. Never guessed by JARVIS.
            happened = body.get("happened")
            if not isinstance(happened, bool):
                raise HttpError(400, "happened must be true or false")
            k.engine.resolve_uncertain(m.group(1), m.group(2), happened=happened, actor=actor)
            return {"ok": True, "state": k.tasks.get(m.group(1))["state"]}
        if m := re.fullmatch(r"/api/tasks/([\w-]+)/(pause|resume|cancel)", path):
            action: Callable[..., None] = getattr(k.engine, m.group(2))
            action(m.group(1), actor=actor)
            return {"ok": True, "state": k.tasks.get(m.group(1))["state"]}
        if path == "/api/projects/generate":
            # local model only; runs in the background (about a minute on this Mac), the page polls /api/projects
            return {"started": self.projects.start()}
        if path == "/api/projects/polish":
            try:
                return self.projects.polish()
            except ApprovalRequired as exc:  # the usual consent: approve the send in Decisions, then polish again
                appr = k.approvals.get(exc.approval_id)
                return {"needs_approval": True, "approval_id": exc.approval_id, "summary": appr["summary"]}
        if m := re.fullmatch(r"/api/projects/([\w-]+)/(accept|dismiss|done|reopen)", path):
            state = {"accept": "active", "dismiss": "dismissed", "done": "done", "reopen": "open"}[m.group(2)]
            try:
                self.projects.decide(m.group(1), state, by=actor)
            except KeyError:
                raise HttpError(404, "no such idea") from None
            return {"ok": True, "state": state}
        if m := re.fullmatch(r"/api/projects/([\w-]+)/steps/(\d+)", path):
            if not isinstance(body.get("done"), bool):
                raise HttpError(400, "done must be true or false")
            try:
                self.projects.tick(m.group(1), int(m.group(2)), body["done"], by=actor)
            except KeyError:
                raise HttpError(404, "no such idea") from None
            except ValueError as exc:
                raise HttpError(400, str(exc)) from None
            return {"ok": True}
        if m := re.fullmatch(r"/api/proposals/([\w-]+)/(approve|reject|done|reopen)", path):
            # Records your answer only; a proposal never changes JARVIS by itself (propose-only policy).
            state = {"approve": "approved", "reject": "rejected", "done": "done", "reopen": "open"}[m.group(2)]
            try:
                self.proposals.decide(m.group(1), state, by=actor)
            except KeyError:
                raise HttpError(404, "no such proposal") from None
            return {"ok": True, "state": state}
        if path == "/api/stop":
            k.engine.emergency_stop(by=actor, reason=str(body.get("reason") or "stopped from dashboard")[:200])
            return {"ok": True}
        if path == "/api/release":
            k.killswitch.release(by=actor, confirm=body.get("confirm") is True)
            return {"ok": True}
        if path == "/api/devices/pair":
            if self.remote is None:
                raise HttpError(409, "phone access isn't set up — run `jarvis remote enable` on the Mac first")
            code = self.remote.devices.create_pairing(by=actor)
            return {"url": self.remote.pair_url(code), "expires_in": 600}
        if path == "/api/touchid/enroll/options":
            name = body.get("name")
            return self.mac.enroll_options(name[:60] if isinstance(name, str) else "This Mac")
        if m := re.fullmatch(r"/api/touchid/([\w-]+)/remove", path):
            self.mac.remove(m.group(1), by=actor)
            return {"ok": True}
        if m := re.fullmatch(r"/api/devices/([\w-]+)/revoke", path):
            if self.remote is None:
                raise HttpError(409, "phone access isn't set up")
            self.remote.devices.revoke(m.group(1), by=actor)
            return {"ok": True}
        raise HttpError(404, "not found")
