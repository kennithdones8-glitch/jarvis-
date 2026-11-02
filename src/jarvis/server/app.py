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
import sys
import secrets
import threading
import time
import traceback
from dataclasses import replace
from datetime import datetime
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
from ..codecheck import MAX_CASES, TEST_PROMPT, SandboxUnavailable, code_of, parse_cases, run_cases, wants_code
from ..orchestrator.answer_checks import chat_problems
from ..orchestrator.lookup import lenient_json
from ..orchestrator.grounding import applies, unsupported_times
from ..models import ChatRequest, Message, Need, NoModelAvailable
from ..models.types import Category
from ..orchestrator import Orchestrator
from ..orchestrator.planner import describe_args
from ..persona import chat_abilities, priming_messages
from ..status import models_status

STATIC = Path(__file__).parent / "static"
COOKIE = "jarvis_session"
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


def describe_event(event: str, p: dict[str, Any], *, task_id: str | None = None,
                   goals: dict[str, str] | None = None) -> str:
    """One readable line per audit event, for the Activity panel. The full record stays in the log."""
    call = f"{p.get('tool')}.{p.get('action')}" if p.get("tool") else ""
    res = p.get("resource") or ""
    res = Path(res).name if isinstance(res, str) and "/" in res else res
    lines = {
        "task.created": lambda: "New task" + (f": {goals.get(task_id)}" if goals.get(task_id) else ""),
        "task.deleted": lambda: "Deleted a task and its history",
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


def _last_briefing(kernel: Kernel) -> str | None:
    from ..proactive import last_briefing_date

    return last_briefing_date(kernel)


def _tilde_evidence(evidence: Any) -> Any:
    if isinstance(evidence, dict) and isinstance(evidence.get("files"), list):
        return {**evidence, "files": [{**f, "path": tilde(f.get("path"))} for f in evidence["files"]]}
    return evidence


class HttpError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


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
        self.voice.start()
        self._runner.start()
        self._maint.start()
        self._serving = True
        threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True).start()

    def serve_forever(self) -> None:
        self.voice.start()
        self._runner.start()
        self._maint.start()
        self._serving = True
        try:
            self.httpd.serve_forever(poll_interval=0.25)
        finally:
            self.shutdown()

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
    def start_plan(self, request: str) -> str:
        job_id = secrets.token_hex(6)
        job = {"id": job_id, "request": request, "state": "planning", "started": time.time()}
        with self._lock:
            self.jobs = {k: v for k, v in self.jobs.items() if v["state"] == "planning"
                         or time.time() - v["started"] < 3600}
            self.jobs[job_id] = job
        self._pool.submit(self._plan_job, job)
        return job_id

    def _plan_job(self, job: dict[str, Any]) -> None:
        try:
            plan = self._plan_with_consent(job)
            job.pop("approval_id", None)
            job.update(kind=plan.kind, goal=plan.goal, message=plan.message, model=plan.model,
                       steps=[{"description": s.description, "call": f"{s.tool}.{s.action}",
                               "args": describe_args(s.args, 200), "depends_on": s.depends_on} for s in plan.steps],
                       plan=plan, state="ready")
        except NoModelAvailable as exc:
            job.update(state="ready", kind="failed", message=f"No model can plan this: {exc}",
                       reasons=exc.reasons)
        except Exception as exc:
            job.update(state="ready", kind="failed", message=f"Planning failed: {type(exc).__name__}: {exc}")
        job["seconds"] = round(time.time() - job["started"], 1)

    def _plan_with_consent(self, job: dict[str, Any]):
        """Plan with the best model. If that needs your approval to send the request to the cloud, wait
        for your decision in Decisions: approved → retry the identical request; rejected or ignored for
        15 minutes → plan with a local model instead."""
        try:
            return self.orch.plan(job["request"])
        except ApprovalRequired as exc:
            job.update(state="waiting_approval", approval_id=exc.approval_id)
            deadline = time.time() + 900
            while time.time() < deadline and not self._stop.is_set():
                decision = self.kernel.approvals.get(exc.approval_id)["state"]
                if decision != "pending":
                    break
                time.sleep(0.5)
            else:
                decision = "expired"
            job["state"] = "planning"
            if decision == "approved":
                job["started"] = time.time()
                return self.orch.plan(job["request"])
            job["note"] = "Planned locally (you kept this request on your Mac)."
            return self.orch.plan(job["request"], local_only=True)

    def run_plan(self, job_id: str) -> str:
        job = self.jobs.get(job_id)
        if not job or job.get("kind") != "plan" or job.get("task_id"):
            raise HttpError(409, "this plan cannot be run")
        job["task_id"] = self.orch.submit(job["request"], job["plan"], actor="user:dashboard", runner=RUNNER)
        job["state"] = "submitted"
        return job["task_id"]

    # ---- chat --------------------------------------------------------------------------
    def chat(self, message: str, history: list[dict[str, str]], *, local_only: bool = False,
             session: str = "dashboard", on_token=None) -> dict[str, Any]:
        memory = self.kernel.memory
        started = time.time()
        # Goal reader: one local call picks read-only lookups (calendar, reminders, notes, files) and, in hybrid mode,
        # rates difficulty so routing needs no second call.
        found = self.lookup.run(message, rate=self.kernel.models.router.mode == "hybrid")
        msgs = list(priming_messages(chat_abilities(memory.settings.enabled, lookups=bool(self.lookup.available()))))
        recalled = memory.recall(message)
        if context := memory.context_message(recalled):
            msgs.append(context)
        for turn in history[-10:]:
            if turn.get("role") in ("user", "assistant") and isinstance(turn.get("content"), str):
                msgs.append(Message(turn["role"], turn["content"][:4000], Category.CONVERSATION))
        if found.context:
            msgs.append(found.context)
        msgs.append(Message("user", message, Category.CONVERSATION))
        try:
            need = Need("chat", prefer="auto", local_only=local_only)
            r = self.kernel.models.complete(need, ChatRequest(tuple(msgs), max_tokens=600), purpose="dashboard chat",
                                            on_token=on_token, level=found.level)
            grounded, retried = None, False
            checks_times = found.context is not None and applies(found.checked)
            bad = unsupported_times(r.text, found.context.content, message) if checks_times else []
            problems = ([f"your answer mentions {', '.join(bad)}, which isn't in the looked-up data: use only times "
                         "from the <lookup> data"] if bad else [])
            problems += chat_problems(message, r.text, looked_up=found.context is not None)
            # One retry with the problems pointed out, then show what's still wrong rather than hide it. Only for a
            # local answer: retrying a Claude answer would be a new request needing your consent again.
            if problems and r.provider in self.kernel.models.router.local:
                retried = True
                retry = msgs + [Message("assistant", r.text, Category.CONVERSATION),
                                Message("user", "Check before answering again:\n" + "\n".join(f"- {x}" for x in problems)
                                        + "\nReply with the corrected answer only.", Category.CONVERSATION)]
                # always local: the first answer was, and a retry must never become a consent question
                r = self.kernel.models.complete(replace(need, local_only=True), ChatRequest(tuple(retry), max_tokens=600),
                                                purpose="dashboard chat (answer check retry)", level=found.level)
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
                r, code_test = self._self_test(message, msgs, r, need, found.level)
        except NoModelAvailable as exc:
            return {"error": f"No model available: {exc}", "reasons": exc.reasons}
        except ApprovalRequired as exc:
            appr = self.kernel.approvals.get(exc.approval_id)
            return {"needs_approval": True, "approval_id": exc.approval_id, "summary": appr["summary"]}
        memory.learn_from(session, message, r.text)
        return {"code_test": code_test, "text": r.text, "model": f"{r.provider}/{r.model}", "seconds": round(time.time() - started, 1),
                "tokens": r.usage.output_tokens, "note": r.note, "memories_used": len(recalled),
                "checked": found.checked, "offer_plan": found.change, "grounded": grounded,
                "lookup_notes": found.why + found.notes}

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
            r2 = self.kernel.models.complete(replace(need, local_only=True), ChatRequest(tuple(retry), max_tokens=900),
                                             purpose="dashboard chat (coding self-test fix)", level=level)
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

        jobs = [{k2: v for k2, v in j.items() if k2 != "plan"} for j in
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
            "briefing": {"last_date": _last_briefing(k)},
            "voice": self.voice.status(),
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
            if method == "GET":
                return self._get(h, url, device=None)
            if url.path == "/api/voice/transcribe":
                return self._json(h, 200, self._transcribe(h, origin=f"http://{host}", actor="user:dashboard"))
            if url.path == "/api/chat/stream":
                return self._stream_chat(h, self._read_post(h, origin=f"http://{host}"))
            body = self._read_post(h, origin=f"http://{host}")
            return self._json(h, 200, self._post_local(url.path, body))
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
            line({"t": piece})
        try:
            result = self.chat(message.strip(), history, local_only=body.get("local_only") is True,
                               session=session[:64], on_token=on_token)
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
                        "/static/bench.js", "/static/bench.css", "/static/trust.js", "/static/proposals.js"):
            ctype = "text/javascript" if url.path.endswith(".js") else "text/css"
            return self._send(h, 200, (STATIC / url.path.rsplit("/", 1)[1]).read_bytes(), f"{ctype}; charset=utf-8")
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
        except the pairing/sign-in ceremonies and static assets; sensitive actions need Face ID."""
        from ..remote import LOCAL_ONLY, STEP_UP, DeviceError
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
            needs_face_id = any(re.fullmatch(p, path) for p in STEP_UP)
            if path == "/api/memory/forget" and body.get("confirm") is not True:
                needs_face_id = False  # a preview changes nothing
            if needs_face_id:
                remote.verify_stepup(device, path, body, actor=actor)
                body = {k: v for k, v in body.items() if k not in ("assertion", "challengeId")}
            return self._json(h, 200, self._post(path, body, actor=actor, device=device))
        except (DeviceError, WebAuthnError) as exc:
            self.kernel.audit.record("device.denied", path=url.path, reason=str(exc)[:200])
            raise HttpError(403, str(exc)) from None

    def _post_local(self, path: str, body: dict[str, Any]) -> Any:
        """The Mac dashboard. Once Touch ID is set up, sensitive actions need a fresh Touch ID for that request."""
        from ..remote import DeviceError, WebAuthnError
        from ..remote.mac import MAC_STEP_UP

        actor = "user:dashboard"
        try:
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
            needs_touch_id = any(re.fullmatch(p, path) for p in MAC_STEP_UP)
            if path == "/api/memory/forget" and body.get("confirm") is not True:
                needs_touch_id = False  # a preview changes nothing
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
            return self.chat(text("message"), history, local_only=body.get("local_only") is True,
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
            return self.kernel.forget(text("query", 200), by=actor, dry_run=body.get("confirm") is not True)
        if path == "/api/plan":
            return {"job_id": self.start_plan(text("request"))}
        if m := re.fullmatch(r"/api/plan/(\w+)/(run|discard)", path):
            if m.group(2) == "run":
                return {"task_id": self.run_plan(m.group(1))}
            self.jobs.pop(m.group(1), None)
            return {"ok": True}
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
