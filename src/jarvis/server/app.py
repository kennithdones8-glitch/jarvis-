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
import re
import secrets
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

from .. import __version__
from ..core import Kernel
from ..core.approvals import ApprovalStateError
from ..core.tasks import InvalidTransition, TaskState
from ..core.tools import ApprovalRequired
from ..models import ChatRequest, Message, Need, NoModelAvailable
from ..models.types import Category
from ..orchestrator import Orchestrator
from ..orchestrator.planner import describe_args
from ..persona import priming_messages
from ..status import models_status

STATIC = Path(__file__).parent / "static"
COOKIE = "jarvis_session"
MAX_BODY = 64 * 1024
RUNNER = "dashboard"
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
                               "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


HOME = str(Path.home())


def tilde(value: Any) -> Any:
    """Show the home folder as ~ (display only)."""
    return value.replace(HOME, "~", 1) if isinstance(value, str) and value.startswith(HOME) else value


def describe_event(event: str, p: dict[str, Any]) -> str:
    """One readable line per audit event, for the Activity panel. The full record stays in the log."""
    call = f"{p.get('tool')}.{p.get('action')}" if p.get("tool") else ""
    res = p.get("resource") or ""
    res = Path(res).name if isinstance(res, str) and "/" in res else res
    lines = {
        "task.created": lambda: f"New task: {p.get('goal')}",
        "task.state": lambda: f"Task {p.get('frm', '').replace('_', ' ')} → {p.get('to', '').replace('_', ' ')}"
                              + (f" ({p['reason']})" if p.get("reason") else ""),
        "task.verified": lambda: "Verification " + ("passed" if p.get("ok") else "FAILED"),
        "permission.check": lambda: f"{call} {res} → {p.get('effect')}".strip(),
        "permission.denied": lambda: f"Denied {call}: {p.get('reason')}",
        "approval.requested": lambda: f"Asked you to approve {call} {res}".strip(),
        "approval.approved": lambda: "You approved a request",
        "approval.rejected": lambda: "You rejected a request",
        "approval.consumed": lambda: "Approval used",
        "tool.start": lambda: f"Running {call}",
        "tool.result": lambda: f"Finished {call}",
        "tool.error": lambda: f"Tool error: {p.get('error')}",
        "model.route": lambda: f"Model chosen: {p.get('rationale', '')}",
        "model.local_call": lambda: f"{p.get('model')} answered ({p.get('output_tokens')} tokens, {p.get('latency_s')}s)",
        "egress.send": lambda: f"Sent {p.get('chars')} chars to {p.get('provider')}",
        "egress.denied": lambda: f"Blocked sending to {p.get('provider')}: {p.get('reason')}",
        "orchestrator.planned": lambda: f"Plan ({p.get('kind')}) by {p.get('model')}: {p.get('goal') or p.get('message')}",
        "emergency_stop.engaged": lambda: f"EMERGENCY STOP: {p.get('reason')}",
        "emergency_stop.released": lambda: "Emergency stop released",
        "kernel.started": lambda: "JARVIS started",
    }
    try:
        text = lines[event]() if event in lines else json.dumps(p, ensure_ascii=False)
    except Exception:
        text = json.dumps(p, ensure_ascii=False)
    return text[:180]


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
                 workers: int = 2, poll_s: float = 1.0):
        if host not in ("127.0.0.1", "::1"):
            raise ValueError("the dashboard only listens on loopback")
        self.kernel = kernel
        self.orch = Orchestrator(kernel)
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
        self.host, self.port = host, self.httpd.server_address[1]
        self._runner = threading.Thread(target=self._run_loop, name="jarvis-runner-loop", daemon=True)
        self._serving = False

    # ---- lifecycle ---------------------------------------------------------------------
    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/?token={self.token}"

    def start(self) -> None:
        """Run in background threads (used by tests)."""
        self._runner.start()
        self._serving = True
        threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True).start()

    def serve_forever(self) -> None:
        self._runner.start()
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
                self.kernel.audit.record("dashboard.runner_error", error=f"{type(exc).__name__}: {exc}")
            self._stop.wait(self._poll_s)

    def _drive(self, tid: str) -> None:
        try:
            self.kernel.engine.run(tid)
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
    def chat(self, message: str, history: list[dict[str, str]], *, local_only: bool = False) -> dict[str, Any]:
        msgs = list(priming_messages())
        for turn in history[-10:]:
            if turn.get("role") in ("user", "assistant") and isinstance(turn.get("content"), str):
                msgs.append(Message(turn["role"], turn["content"][:4000], Category.CONVERSATION))
        msgs.append(Message("user", message, Category.CONVERSATION))
        started = time.time()
        try:
            r = self.kernel.models.complete(Need("chat", prefer="auto", local_only=local_only),
                                            ChatRequest(tuple(msgs), max_tokens=600), purpose="dashboard chat")
        except NoModelAvailable as exc:
            return {"error": f"No model available: {exc}", "reasons": exc.reasons}
        except ApprovalRequired as exc:
            appr = self.kernel.approvals.get(exc.approval_id)
            return {"needs_approval": True, "approval_id": exc.approval_id, "summary": appr["summary"]}
        return {"text": r.text, "model": f"{r.provider}/{r.model}", "seconds": round(time.time() - started, 1),
                "tokens": r.usage.output_tokens, "note": r.note}

    # ---- state snapshot ----------------------------------------------------------------
    def state(self) -> dict[str, Any]:
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
                "steps": [{"n": s["idx"], "description": s["description"], "call": f"{s['tool']}.{s['action']}",
                           "state": s["state"], "attempts": s["attempts"], "error": s["error"]} for s in steps],
                "final_text": next((s["result"].get("text") for s in reversed(steps) if s["tool"] == "llm"
                                    and s["state"] == "done" and isinstance(s["result"], dict)), None),
            })

        approvals = []
        for a in k.approvals.pending():
            preview = None
            if a["task_id"] and a["step_id"] and a["tool"] == "fs":
                try:
                    preview = self.orch.preview_args(a["task_id"], a["step_id"]).get("content")
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

        audit = [{"seq": e["seq"], "ts": e["ts"], "actor": e["actor"], "event": e["event"], "task_id": e["task_id"],
                  "detail": describe_event(e["event"], e["payload"])}
                 for e in k.audit.entries(limit=40) if e["event"] not in ("approval.consumed",)]
        return {
            "version": __version__, "time": now,
            "emergency_stop": k.killswitch.state(),
            "tasks": tasks, "approvals": approvals, "jobs": jobs, "models": self._models_cache[1],
            "audit": list(reversed(audit)), "audit_chain": self._audit_cache[1],
            "roots": [tilde(str(r)) for r in k.policy.roots], "policy_loaded": k.policy_path.exists(),
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

    def _json(self, h: BaseHTTPRequestHandler, status: int, obj: Any) -> None:
        self._send(h, status, json.dumps(obj, default=str).encode(), "application/json")

    def _authed(self, h: BaseHTTPRequestHandler) -> bool:
        for part in (h.headers.get("Cookie") or "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == COOKIE and hmac.compare_digest(value, self.token):
                return True
        return False

    def _dispatch(self, h: BaseHTTPRequestHandler, method: str) -> None:
        try:
            allowed_hosts = {f"127.0.0.1:{self.port}", f"localhost:{self.port}", f"[::1]:{self.port}"}
            if h.headers.get("Host") not in allowed_hosts:
                raise HttpError(403, "unexpected Host header")
            url = urlsplit(h.path)

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
                if url.path in ("/static/app.js", "/static/app.css"):
                    ctype = "text/javascript" if url.path.endswith(".js") else "text/css"
                    return self._send(h, 200, (STATIC / url.path.rsplit("/", 1)[1]).read_bytes(),
                                      f"{ctype}; charset=utf-8")
                if m := re.fullmatch(r"/static/fonts/(rajdhani-[567]00\.woff2)", url.path):
                    return self._send(h, 200, (STATIC / "fonts" / m.group(1)).read_bytes(), "font/woff2",
                                      {"Cache-Control": "max-age=86400"})
                if url.path == "/api/state":
                    return self._json(h, 200, self.state())
                if m := re.fullmatch(r"/api/tasks/([\w-]+)/audit", url.path):
                    return self._json(h, 200, self.kernel.audit.entries(task_id=m.group(1), limit=300))
                raise HttpError(404, "not found")

            # POST: CSRF defences
            if h.headers.get("X-Requested-By") != "jarvis":
                raise HttpError(403, "missing request header")
            origin = h.headers.get("Origin")
            if origin is not None and origin != f"http://{h.headers.get('Host')}":
                raise HttpError(403, "cross-origin request refused")
            length = int(h.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                raise HttpError(413, "request too large")
            try:
                body = json.loads(h.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                raise HttpError(400, "invalid JSON") from None
            if not isinstance(body, dict):
                raise HttpError(400, "expected a JSON object")
            return self._json(h, 200, self._post(url.path, body))
        except HttpError as exc:
            self._json(h, exc.status, {"error": str(exc)})
        except (InvalidTransition, ApprovalStateError, KeyError, ValueError, PermissionError) as exc:
            self._json(h, 409, {"error": str(exc)})
        except Exception as exc:
            self.kernel.audit.record("dashboard.error", error=f"{type(exc).__name__}: {exc}")
            self._json(h, 500, {"error": "internal error (recorded in the audit log)"})

    def _post(self, path: str, body: dict[str, Any]) -> Any:
        k = self.kernel
        actor = "user:dashboard"

        def text(name: str, limit: int = 4000) -> str:
            value = body.get(name)
            if not isinstance(value, str) or not value.strip() or len(value) > limit:
                raise HttpError(400, f"'{name}' must be non-empty text under {limit} characters")
            return value.strip()

        if path == "/api/chat":
            history = body.get("history") if isinstance(body.get("history"), list) else []
            return self.chat(text("message"), history, local_only=body.get("local_only") is True)
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
        if m := re.fullmatch(r"/api/tasks/([\w-]+)/(pause|resume|cancel)", path):
            action: Callable[..., None] = getattr(k.engine, m.group(2))
            action(m.group(1), actor=actor)
            return {"ok": True, "state": k.tasks.get(m.group(1))["state"]}
        if path == "/api/stop":
            k.engine.emergency_stop(by=actor, reason=str(body.get("reason") or "stopped from dashboard")[:200])
            return {"ok": True}
        if path == "/api/release":
            k.killswitch.release(by=actor, confirm=body.get("confirm") is True)
            return {"ok": True}
        raise HttpError(404, "not found")
