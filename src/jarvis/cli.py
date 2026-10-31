"""Operator CLI for inspecting and controlling the kernel.

Commands run as the local OS user, who is treated as the authenticated owner.
Stronger authentication (passkeys / Touch ID) arrives with the dashboard milestone.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from .core import Kernel

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
EXAMPLE_POLICY = CONFIG_DIR / "policy.example.toml"
EXAMPLE_MODELS = CONFIG_DIR / "jarvis.example.toml"


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jarvis")
    parser.add_argument("--home", help="data directory (default: platform location or $JARVIS_HOME)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="create the data directory and a starter policy")
    sub.add_parser("status", help="show emergency-stop state, task counts and pending approvals")
    p = sub.add_parser("tasks", help="list recent tasks, or delete a finished one: tasks [delete ID]")
    p.add_argument("op", nargs="?", choices=["list", "delete"], default="list")
    p.add_argument("task_id", nargs="?")
    p = sub.add_parser("show", help="show a task with its steps and audit history")
    p.add_argument("task_id")
    p = sub.add_parser("audit", help="show recent audit entries")
    p.add_argument("--task")
    p.add_argument("--limit", type=int, default=50)
    sub.add_parser("verify-audit", help="verify the audit hash chain")
    sub.add_parser("approvals", help="list pending approvals")
    for name in ("approve", "reject"):
        p = sub.add_parser(name)
        p.add_argument("approval_id")
    p = sub.add_parser("stop", help="engage the emergency stop")
    p.add_argument("--reason", default="manual stop")
    p = sub.add_parser("release", help="release the emergency stop")
    p.add_argument("--yes", action="store_true", help="confirm release")
    for name in ("cancel", "pause", "resume"):
        p = sub.add_parser(name)
        p.add_argument("task_id")
    p = sub.add_parser("do", help="plan and carry out a task (shows the plan and asks before running)")
    p.add_argument("request")
    p.add_argument("--yes", action="store_true", help="run the plan without asking (approvals are still asked)")
    p = sub.add_parser("run", help="continue a task after approving or resuming it")
    p.add_argument("task_id")
    p = sub.add_parser("dashboard", help="start the local command centre in your browser")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-open", action="store_true", help="do not open the browser")
    p = sub.add_parser("use-claude", help="turn the Claude (Claude Code on your Pro plan) brain on or off")
    p.add_argument("state", choices=["on", "off"])
    p = sub.add_parser("service", help="run JARVIS in the background at login: install | uninstall | status | restart | rotate-link")
    p.add_argument("op", choices=["install", "uninstall", "status", "restart", "rotate-link"])
    p.add_argument("--port", type=int, default=8765)
    p = sub.add_parser("open", help="open the dashboard in your browser")
    p.add_argument("--port", type=int, default=8765)
    p = sub.add_parser("backup", help="encrypted backups: now [--to DIR] | list | verify FILE | restore FILE --yes")
    p.add_argument("op", choices=["now", "list", "verify", "restore"])
    p.add_argument("file", nargs="?")
    p.add_argument("--to", help="folder for this backup (default: [backup] dir or the data folder)")
    p.add_argument("--yes", action="store_true", help="confirm a restore")
    p.add_argument("--keep-config", action="store_true", help="restore: keep your current policy and model settings")
    p = sub.add_parser("allow-folder", help="let JARVIS read a folder (writes there still ask you first)")
    p.add_argument("path")
    p.add_argument("--remove", action="store_true", help="take the folder off the list")
    sub.add_parser("folders", help="list folders JARVIS may access")
    p = sub.add_parser("research", help="search the web and read pages to answer, with sources (uses Claude)")
    p.add_argument("question")
    p.add_argument("--deep", action="store_true", help="use the strongest model (more of your Claude allowance)")
    p = sub.add_parser("remember", help="tell JARVIS something to remember")
    p.add_argument("text")
    p = sub.add_parser("memory", help="review memory: list | search Q | confirm ID | delete ID | forget Q | export FILE")
    p.add_argument("op", choices=["list", "search", "confirm", "delete", "forget", "export"])
    p.add_argument("arg", nargs="?")
    p.add_argument("--yes", action="store_true", help="for forget: actually delete (default is a preview)")
    sub.add_parser("models", help="show configured models, availability and budget")
    p = sub.add_parser("ask", help="one-off question to the best available model")
    p.add_argument("question")
    p.add_argument("--min-quality", type=int, default=1)
    p.add_argument("--local-only", action="store_true")
    p = sub.add_parser("grant-egress", help="standing permission to send a data category to a cloud provider")
    p.add_argument("--category", required=True)
    p.add_argument("--provider", required=True)
    p.add_argument("--expires", help="ISO timestamp")
    p = sub.add_parser("revoke-egress")
    p.add_argument("grant_id")
    sub.add_parser("grants", help="list egress grants")
    p = sub.add_parser("remote", help="use JARVIS from your iPhone over Tailscale: enable | disable | status")
    p.add_argument("op", choices=["enable", "disable", "status"])
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--hostname", help="this Mac's Tailscale name (default: asked from the Tailscale app)")
    p = sub.add_parser("devices", help="paired phones: list | revoke ID")
    p.add_argument("op", nargs="?", choices=["list", "revoke"], default="list")
    p.add_argument("device_id", nargs="?")
    args = parser.parse_args(argv)

    kernel = Kernel(args.home)
    try:
        if args.cmd == "init":
            for src, dst in ((EXAMPLE_POLICY, kernel.policy_path), (EXAMPLE_MODELS, kernel.config_path)):
                if not dst.exists():
                    shutil.copyfile(src, dst)
                    dst.chmod(0o600)
                    print(f"wrote {dst} — review it before use")
            print(f"data directory: {kernel.home}")
        elif args.cmd == "status":
            counts = {r[0]: r[1] for r in kernel.db.query("SELECT state, COUNT(*) FROM tasks GROUP BY state")}
            _print({"home": str(kernel.home), "emergency_stop": kernel.killswitch.state(),
                    "policy_loaded": kernel.policy_path.exists(), "tasks": counts,
                    "pending_approvals": len(kernel.approvals.pending())})
        elif args.cmd == "tasks" and args.op == "delete":
            if not args.task_id:
                print("usage: jarvis tasks delete TASK_ID", file=sys.stderr)
                return 1
            kernel.tasks.delete(args.task_id, by="user:cli")
            print("Deleted the task and its steps, results and approvals. The audit log keeps only ids and fingerprints.")
        elif args.cmd == "tasks":
            for t in kernel.tasks.list(limit=50):
                print(f"{t['id']}  {t['state']:<17} p{t['priority']:<3} {t['goal'][:70]}")
        elif args.cmd == "show":
            _print({"task": kernel.tasks.get(args.task_id), "steps": kernel.tasks.steps(args.task_id),
                    "checkpoint": kernel.tasks.latest_checkpoint(args.task_id)})
        elif args.cmd == "audit":
            for e in kernel.audit.entries(task_id=args.task, limit=args.limit):
                print(f"{e['seq']:>6} {e['ts']} {e['actor']:<8} {e['event']:<24} {json.dumps(e['payload'])[:160]}")
        elif args.cmd == "verify-audit":
            r = kernel.audit.verify()
            _print(r.__dict__)
            return 0 if r.ok else 2
        elif args.cmd == "approvals":
            _print(kernel.approvals.pending())
        elif args.cmd in ("approve", "reject"):
            kernel.approvals.decide(args.approval_id, approve=args.cmd == "approve", by="user:cli")
            print(f"{args.cmd}d {args.approval_id}")
        elif args.cmd == "stop":
            kernel.engine.emergency_stop(by="user:cli", reason=args.reason)
            print("emergency stop engaged")
        elif args.cmd == "release":
            kernel.killswitch.release(by="user:cli", confirm=args.yes)
            print("emergency stop released; paused tasks stay paused until resumed individually")
        elif args.cmd in ("cancel", "pause", "resume"):
            getattr(kernel.engine, args.cmd)(args.task_id, actor="user:cli")
            print(f"{args.cmd}: {kernel.tasks.get(args.task_id)['state']}")
        elif args.cmd == "service":
            return _service(kernel, args)
        elif args.cmd == "open":
            import webbrowser

            from .service import dashboard_url, responding
            url = dashboard_url(kernel.home, args.port)
            if not responding(args.port):
                print("JARVIS isn't running. Start it with `jarvis dashboard` or `jarvis service install`.")
                return 1
            webbrowser.open(url)
            print(url)
        elif args.cmd == "backup":
            return _backup(kernel, args)
        elif args.cmd == "remote":
            return _remote(kernel, args)
        elif args.cmd == "devices":
            return _devices(kernel, args)
        elif args.cmd == "allow-folder":
            return _allow_folder(kernel, args)
        elif args.cmd == "folders":
            for r in kernel.policy.roots:
                print(r)
        elif args.cmd == "research":
            return _research(kernel, args)
        elif args.cmd == "remember":
            mid = kernel.memory.remember(args.text, origin="explicit", by="user:cli")
            print(f"Remembered ({mid})." if mid else "Not stored (memory is off, or the text matches an excluded topic).")
        elif args.cmd == "memory":
            return _memory(kernel, args)
        elif args.cmd == "use-claude":
            return _use_claude(kernel, args.state == "on")
        elif args.cmd == "dashboard":
            return _dashboard(kernel, args)
        elif args.cmd == "do":
            return _do(kernel, args)
        elif args.cmd == "run":
            return _drive(kernel, _orchestrator(kernel), args.task_id)
        elif args.cmd == "models":
            from .status import models_status

            _print(models_status(kernel))
        elif args.cmd == "ask":
            return _ask(kernel, args)
        elif args.cmd == "grant-egress":
            gate = kernel.models.router.gate
            gid = gate.grants.grant(category=args.category, provider=args.provider, by="user:cli",
                                    expires_at=args.expires)
            print(f"granted {gid}: {args.category} -> {args.provider}")
        elif args.cmd == "revoke-egress":
            kernel.models.router.gate.grants.revoke(args.grant_id, by="user:cli")
            print(f"revoked {args.grant_id}")
        elif args.cmd == "grants":
            _print(kernel.models.router.gate.grants.list())
    except (KeyError, ValueError, RuntimeError, PermissionError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        kernel.close()
    return 0


def _dashboard(kernel: Kernel, args) -> int:
    import webbrowser

    from .server import Dashboard

    from .service import dashboard_token, responding

    if responding(args.port):
        print(f"JARVIS is already running on port {args.port} (the background service?). Open it with `jarvis open`.")
        return 0
    recovered = kernel.start()
    dash = Dashboard(kernel, port=args.port, token=dashboard_token(kernel.home))
    print(f"JARVIS dashboard running. Open (keep this link private):\n\n  {dash.url}\n")
    if recovered:
        print(f"Recovered {len(recovered)} interrupted task(s).")
    print("Press Ctrl+C to stop. A task interrupted mid-step is recovered safely the next time JARVIS starts.")
    if not args.no_open:
        webbrowser.open(dash.url)
    try:
        dash.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
    return 0


CLAUDE_BLOCK = """
[providers.claude]
kind = "claude_code"
enabled = false
data_use_note = "Anthropic, via your Claude Pro plan"

[[providers.claude.models]]
id = "sonnet"
capabilities = ["chat", "plan", "code", "summarize", "classify", "json", "extract"]
context_tokens = 200000
quality = 5
speed = 3
"""

HAIKU_BLOCK = """
[[providers.claude.models]]
id = "haiku"
capabilities = ["chat", "summarize", "classify", "json", "extract"]
context_tokens = 200000
quality = 4
speed = 5
"""


def _use_claude(kernel: Kernel, on: bool) -> int:
    """Edit jarvis.toml: enable/disable the Claude provider and switch routing to best/local-first.
    Validates the result before writing and keeps a backup. Then checks Claude Code really answers."""
    import re
    import tomllib

    from .models.config import parse_model_config

    path = kernel.config_path
    text = path.read_text() if path.exists() else EXAMPLE_MODELS.read_text()
    data = tomllib.loads(text)
    if "claude" not in data.get("providers", {}):
        text = text.rstrip() + "\n" + CLAUDE_BLOCK
    if not any(m.get("id") == "haiku" for m in data.get("providers", {}).get("claude", {}).get("models", [])):
        text = text.rstrip() + "\n" + HAIKU_BLOCK
    if "routing" not in data:
        text = text.rstrip() + '\n\n[routing]\nmode = "local_first"\n'
    text = re.sub(r'(\[providers\.claude\][^\[]*?enabled\s*=\s*)(true|false)', lambda m: m.group(1) + ("true" if on else "false"),
                  text, count=1)
    text = re.sub(r'(\[routing\][^\[]*?mode\s*=\s*)"[^"]*"', lambda m: m.group(1) + ('"hybrid"' if on else '"local_first"'),
                  text, count=1)
    parse_model_config(tomllib.loads(text))  # never write an invalid config
    if path.exists():
        path.with_suffix(".toml.bak").write_text(path.read_text())
    path.write_text(text)
    path.chmod(0o600)
    kernel.audit.record("config.claude", actor="user:cli", enabled=on)
    if not on:
        print("Claude is off. JARVIS uses only local models.")
        return 0
    print("Claude is on (hybrid): simple requests stay on this Mac, medium ones use Claude Haiku, hard ones\n"
          "Claude Sonnet. JARVIS asks before sending any private content.")
    print("Checking that Claude Code answers (a test with no private data)…")
    from .models import ChatRequest, Message
    from .models.providers import ClaudeCodeProvider
    from .models.types import Category, ProviderError

    reloaded = parse_model_config(tomllib.loads(text))
    pc = next(p for p in reloaded.providers if p.name == "claude")
    probe = ClaudeCodeProvider("claude", pc.models, workdir=kernel.home / "claude-workdir", command=pc.command)
    probe.clear_status()
    try:
        r = probe.chat("haiku" if "haiku" in pc.models else next(iter(pc.models)), ChatRequest((
            Message("system", "Reply with exactly: JARVIS link online.", Category.SYSTEM_PROMPT),
            Message("user", "Status check.", Category.SYSTEM_PROMPT))))
    except ProviderError as exc:
        print(f"Claude Code did not answer: {exc}\nJARVIS will keep using local models until it does.")
        if "login" in str(exc).lower():
            print("Sign in: run `claude`, type /login, choose your Claude account (Pro), then /exit and re-run this.")
        return 7
    print(f"Claude replied: {r.text.strip()!r} ({r.latency_s:.1f}s)")
    return 0


def _orchestrator(kernel: Kernel):
    from .orchestrator import Orchestrator

    return Orchestrator(kernel)


def _confirm(question: str) -> bool:
    try:
        return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def _do(kernel: Kernel, args) -> int:
    import time

    from .models import NoModelAvailable
    from .orchestrator.planner import describe_args

    kernel.start()
    orch = _orchestrator(kernel)
    print("Planning…", file=sys.stderr)
    started = time.monotonic()
    try:
        plan = _with_consent(kernel, lambda local: orch.plan(args.request, local_only=local))
    except NoModelAvailable as exc:
        print(f"no model can plan this: {exc}")
        for model, reason in exc.reasons.items():
            print(f"  {model}: {reason}")
        return 4
    took = time.monotonic() - started
    if plan.kind == "clarify":
        print(f"JARVIS asks: {plan.message}\n(re-run `jarvis do` with a more specific request)")
        return 0
    if plan.kind == "cannot":
        print(f"JARVIS can't do this yet: {plan.message}")
        return 0
    if plan.kind == "failed":
        print(f"JARVIS could not produce a valid plan ({plan.model}, {plan.attempts} attempts): {plan.message}")
        return 5
    print(f"\nGoal: {plan.goal}   [{plan.model} · {took:.0f}s]")
    for i, s in enumerate(plan.steps):
        deps = f"  (after {', '.join(map(str, s.depends_on))})" if s.depends_on else ""
        print(f"  {i}. {s.description}\n     {s.tool}.{s.action} {describe_args(s.args)}{deps}")
    if not args.yes and not _confirm("\nRun this plan?"):
        print("Not run. Nothing was changed.")
        return 0
    task_id = orch.submit(args.request, plan, actor="user:cli")
    print(f"Task {task_id}")
    return _drive(kernel, orch, task_id)


def _drive(kernel: Kernel, orch, task_id: str) -> int:
    import time

    from .core.tasks import TaskBusy, TaskState

    while True:
        try:
            state = kernel.engine.run(task_id)
        except TaskBusy:
            print("This task is being run by another JARVIS process (probably the dashboard / background service).\n"
                  "Follow it there, or try again once it finishes.")
            return 8
        if state is TaskState.AWAITING_APPROVAL:
            for appr in kernel.approvals.pending(task_id=task_id):
                print(f"\nApproval needed (tier {appr['tier']}): {appr['summary']}\n  reason: {appr['reason']}")
                if appr["tool"] == "fs" and appr["step_id"]:
                    step_args = orch.preview_args(task_id, appr["step_id"])
                    if appr["action"] == "move":
                        print(f"  move to: {step_args.get('to')}")
                    preview = step_args.get("content")
                    if isinstance(preview, str):
                        print("  content:\n    " + preview[:600].replace("\n", "\n    ")
                              + ("\n    …" if len(preview) > 600 else ""))
                approve = _confirm("Approve?")
                kernel.approvals.decide(appr["id"], approve=approve, by="user:cli")
            continue
        if state is TaskState.RUNNING:  # waiting out a retry backoff
            time.sleep(1)
            continue
        break
    rep = orch.report(task_id)
    print(f"\nResult: {rep['state'].upper()}")
    for s in rep["steps"]:
        print(f"  {s['n']}. [{s['state']}] {s['description']}" + (f" — {s['error']}" if s["error"] else ""))
    if rep["error"]:
        print(f"Error: {rep['error']}")
    if rep["next_action"]:
        print(f"Next: {rep['next_action']}")
    for f in (rep["evidence"] or {}).get("files", []):
        print(f"Verified: {f['path']} (on disk: {f['exists']}, content matches: {f['content_matches']})")
    if rep["final_text"] and not (rep["evidence"] or {}).get("files"):
        print(f"\n{rep['final_text']}")
    return 0 if rep["state"] == "completed" else 6


def _with_consent(kernel: Kernel, call):
    """Run ``call(local_only)``. If it needs approval to send private content to a cloud model, ask in
    the terminal: yes → approve and retry the identical request; no → retry with local models only."""
    from .core.tools import ApprovalRequired

    local = False
    for _ in range(3):
        try:
            return call(local)
        except ApprovalRequired as exc:
            appr = kernel.approvals.get(exc.approval_id)
            print(f"\n{appr['summary']}", file=sys.stderr)
            approve = _confirm("Send it?")
            kernel.approvals.decide(exc.approval_id, approve=approve, by="user:cli")
            if not approve:
                print("Keeping it on this Mac — using a local model.", file=sys.stderr)
                local = True
    return call(True)


def _service(kernel: Kernel, args) -> int:
    from . import service as svc

    custom = bool(args.home) or "JARVIS_HOME" in __import__("os").environ
    try:
        if args.op == "install":
            path = svc.install(kernel.home, port=args.port, custom_home=custom)
            print(f"Installed {path.name}. JARVIS now starts when you log in and restarts if it crashes.")
            print("Open the dashboard any time with `uv run jarvis open` (the link stays the same — bookmark it).")
            print("Make sure the Ollama app is set to open at login too (Ollama menu → Launch at login).")
            print("After `git pull`, run `uv run jarvis service restart` to load the new version.")
        elif args.op == "uninstall":
            print("Removed the background service." if svc.uninstall() else "The background service wasn't installed.")
            print("Your data, memory and settings are untouched.")
        elif args.op == "restart":
            svc.restart()
            print("Restarted.")
        elif args.op == "rotate-link":
            svc.dashboard_token(kernel.home, rotate=True)
            print("New dashboard link created; the old one stops working after a restart.")
            if svc.is_loaded():
                svc.restart()
            print(svc.dashboard_url(kernel.home, args.port))
        else:
            _print(svc.status(args.port))
    except svc.ServiceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def _write_remote_config(kernel: Kernel, *, enabled: bool, hostname: str) -> None:
    import re
    import tomllib

    from .models.config import parse_model_config

    path = kernel.config_path
    text = path.read_text() if path.exists() else EXAMPLE_MODELS.read_text()
    block = f'[remote]\nenabled = {"true" if enabled else "false"}\nhostname = "{hostname}"\n'
    if re.search(r"(?m)^\[remote\]", text):
        text = re.sub(r"(?ms)^\[remote\]\n.*?(?=^\[|\Z)", lambda m: block + "\n", text, count=1)
    else:
        text = text.rstrip() + "\n\n" + block
    parse_model_config(tomllib.loads(text))  # never write an invalid config
    if path.exists():
        path.with_suffix(".toml.bak").write_text(path.read_text())
    path.write_text(text)
    path.chmod(0o600)
    kernel.audit.record("config.remote", actor="user:cli", enabled=enabled)


def _remote(kernel: Kernel, args) -> int:
    from . import service as svc
    from .remote import tailscale as ts

    cfg = kernel.model_config.remote
    try:
        if args.op == "status":
            devices = [d for d in _device_store(kernel).list() if not d["revoked_at"]]
            _print({"enabled": bool(cfg.get("enabled")), "hostname": cfg.get("hostname"),
                    "phone_url": f"https://{cfg['hostname']}" if cfg.get("enabled") else None,
                    "paired_devices": len(devices)})
        elif args.op == "enable":
            host = (args.hostname or ts.hostname()).rstrip(".")
            _write_remote_config(kernel, enabled=True, hostname=host)
            print(f"Sharing the dashboard inside your tailnet only: https://{host}")
            ts.serve(args.port)
            if svc.is_loaded():
                svc.restart()
                print("Restarted the background service.")
            else:
                print("Restart JARVIS (`uv run jarvis service restart`, or stop and start `jarvis dashboard`).")
            print("Next: open the dashboard on this Mac → Systems → Phone → Pair a phone, and scan the code\n"
                  "with your iPhone's camera (the iPhone must be signed in to the same Tailscale account).")
        else:
            try:
                ts.unserve()
            except ts.TailscaleError as exc:
                print(f"note: {exc}")
            _write_remote_config(kernel, enabled=False, hostname=cfg.get("hostname") or "")
            if svc.is_loaded():
                svc.restart()
            print("Phone access is off. Paired phones stay listed (remove them with `jarvis devices revoke ID`).")
    except ts.TailscaleError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def _device_store(kernel: Kernel):
    from .remote.devices import DeviceStore

    return DeviceStore(kernel.db, kernel.audit)


def _devices(kernel: Kernel, args) -> int:
    store = _device_store(kernel)
    if args.op == "revoke":
        if not args.device_id:
            print("usage: jarvis devices revoke DEVICE_ID", file=sys.stderr)
            return 1
        store.revoke(args.device_id, by="user:cli")
        print("Removed. That phone is signed out and its passkey no longer opens JARVIS.")
        return 0
    for d in store.list():
        state = f"removed {d['revoked_at'][:10]}" if d["revoked_at"] else f"last used {(d['last_seen'] or 'never')[:16]}"
        print(f"{d['id']}  {d['name']:<20} paired {d['created_at'][:10]}  {state}")
    return 0


def _backup(kernel: Kernel, args) -> int:
    import time as _time

    from . import backup as bk

    cfg = kernel.model_config.backup
    folder = Path(args.to).expanduser() if args.to else (Path(cfg["dir"]).expanduser() if cfg.get("dir")
                                                         else kernel.home / "backups")
    try:
        if args.op == "now":
            r = bk.create_backup(kernel.home, kernel.policy_path, kernel.config_path, dest_dir=folder,
                                 keep=int(cfg.get("keep", 14)))
            kernel.audit.record("backup.created", actor="user:cli", file=r.path.name, bytes=r.bytes, verified=True)
            c = r.detail["counts"]
            print(f"Backup saved and verified: {r.path}")
            print(f"  {r.bytes / 1024:.0f} KB · {c.get('memories', 0)} memories · {c.get('records', 0)} conversation "
                  f"records · {c.get('tasks', 0)} tasks · audit log intact ({r.detail['audit_entries']} entries)")
            if r.new_passphrase:
                print("\nYour backups are encrypted. The passphrase is stored in your Mac's Keychain.")
                print("SAVE A COPY NOW (e.g. in your password manager) — without it, backups can't be restored")
                print("on another Mac:\n")
                print(f"    {r.new_passphrase}\n")
                print("Daily automatic backups are now on while JARVIS runs.")
        elif args.op == "list":
            found = bk.list_backups(folder)
            print(f"{len(found)} backup(s) in {folder}")
            for p in found:
                st = p.stat()
                print(f"  {p.name}  {st.st_size / 1024:.0f} KB  {_time.strftime('%Y-%m-%d %H:%M', _time.localtime(st.st_mtime))}")
        elif args.op == "verify":
            if not args.file:
                print("usage: jarvis backup verify FILE", file=sys.stderr)
                return 1
            d = bk.verify_backup(Path(args.file).expanduser())
            print(f"OK — decrypts, checksums match, database and audit log intact. Contents: {d['counts']}")
        elif args.op == "restore":
            if not args.file:
                print("usage: jarvis backup restore FILE --yes", file=sys.stderr)
                return 1
            from .service import responding
            if responding():
                print("Stop JARVIS first (`jarvis service uninstall`, or Ctrl+C the dashboard), then restore.",
                      file=sys.stderr)
                return 1
            if not args.yes:
                print("This replaces JARVIS's memory, task history and settings with the backup (your current "
                      "files are kept as *.before-restore-*). Add --yes to go ahead.")
                return 0
            kernel.close()
            res = bk.restore_backup(Path(args.file).expanduser(), kernel.home, kernel.policy_path,
                                    kernel.config_path, include_config=not args.keep_config)
            print(f"Restored from {Path(args.file).name}. Re-applied deletions made since: {res['reapplied_deletions']}.")
            print(f"Your previous files were kept as {res['previous_files_kept_as']}.")
    except bk.BackupError as exc:
        print(f"backup error: {exc}", file=sys.stderr)
        return 1
    return 0


def _allow_folder(kernel: Kernel, args) -> int:
    """Add/remove a folder in policy.toml [filesystem].roots. Reading inside it is allowed; writing,
    moving or deleting there still needs your approval unless a rule says otherwise."""
    import re
    import tomllib

    from .core.permissions import Policy, canonical_path

    path = kernel.policy_path
    text = path.read_text() if path.exists() else EXAMPLE_POLICY.read_text()
    data = tomllib.loads(text)
    roots = list(data.get("filesystem", {}).get("roots", []))
    folder = canonical_path(args.path)
    if not args.remove and not folder.is_dir():
        print(f"Not a folder: {folder}", file=sys.stderr)
        return 1
    home = str(Path.home())
    if not args.remove and (str(folder) in ("/", home) or str(folder).startswith(str(kernel.home))):
        print("For safety JARVIS won't take your whole home folder, the disk root or its own data folder. "
              "Pick a specific folder.", file=sys.stderr)
        return 1
    display = "~" + str(folder)[len(home):] if str(folder).startswith(home + "/") else str(folder)
    same = lambda r: canonical_path(r) == folder  # noqa: E731
    if args.remove:
        roots = [r for r in roots if not same(r)]
    elif not any(same(r) for r in roots):
        roots.append(display)
    new_line = "roots = [" + ", ".join(f'"{r}"' for r in roots) + "]"
    if re.search(r"(?m)^roots\s*=.*$", text):
        text = re.sub(r"(?m)^roots\s*=.*$", lambda m: new_line, text, count=1)
    else:
        text = text.replace("[filesystem]", "[filesystem]\n" + new_line, 1) if "[filesystem]" in text \
            else f"[filesystem]\n{new_line}\n\n" + text
    Policy.from_dict(tomllib.loads(text), protected=[kernel.home, kernel.policy_path])  # validate before writing
    path.write_text(text)
    path.chmod(0o600)
    kernel.audit.record("policy.roots_changed", actor="user:cli", folder=str(folder), removed=args.remove)
    verb = "removed" if args.remove else "added"
    print(f"{display} {verb}. JARVIS can {'no longer read it' if args.remove else 'read files there; changes still ask you first'}.")
    return 0


def _research(kernel: Kernel, args) -> int:
    from .models import NoModelAvailable
    from .orchestrator.research import research_request

    mem = kernel.memory
    context = mem.context_message(mem.recall(args.question))
    request = research_request(args.question, context.content if context else None)
    print("Researching… (Claude searches and reads pages; this can take a minute)", file=sys.stderr)
    try:
        r = _with_consent(kernel, lambda local: _research_or_decline(kernel, request, local, args.deep))
    except NoModelAvailable as exc:
        print("Web research needs Claude. Run `uv run jarvis use-claude on` (and make sure you're signed in).")
        for model, reason in exc.reasons.items():
            print(f"  {model}: {reason}")
        return 4
    if r is None:
        print("Not researched — web research needs to send your question to Claude.")
        return 0
    meta = r.meta or {}
    print(r.text, flush=True)
    sources = meta.get("sources", [])
    print(f"\n[{r.provider}/{r.model} · {r.latency_s:.0f}s · {len(meta.get('searches', []))} searches · "
          f"{len(meta.get('fetched', []))} pages read · {meta.get('verified_sources', 0)}/{len(sources)} sources verified]",
          file=sys.stderr)
    for s in sources:
        if not s["verified"]:
            print(f"  ⚠ cited but not seen by the research tools: {s['url']}", file=sys.stderr)
    mem.learn_from("cli", args.question, r.text, background=False)
    return 0


def _research_or_decline(kernel: Kernel, request, local: bool, deep: bool):
    if local:  # you declined sending it to Claude; there is no local web research
        return None
    return kernel.models.research(request, purpose="cli web research", deep=deep)


def _memory(kernel: Kernel, args) -> int:
    import json as _json

    from .memory import iter_lines

    mem = kernel.memory
    needs_arg = {"search", "confirm", "delete", "forget", "export"}
    if args.op in needs_arg and not args.arg:
        print(f"`jarvis memory {args.op}` needs an argument", file=sys.stderr)
        return 1
    if args.op == "list":
        c = mem.counts()
        print(f"{c['memories']} memories ({c['unconfirmed']} unconfirmed, marked ?), {c['records']} conversation records")
        for line in iter_lines(mem.list()):
            print(line)
    elif args.op == "search":
        for line in iter_lines(mem.search(args.arg)):
            print(line)
        for r in mem.search_records(args.arg, limit=10):
            print(f"  record {r['id']} ({r['created_at'][:10]}, {r['role']}): {r['snippet']}")
    elif args.op == "confirm":
        mem.confirm(args.arg, by="user:cli")
        print("Confirmed.")
    elif args.op == "delete":
        mem.delete(args.arg, by="user:cli")
        print("Deleted. JARVIS won't re-learn it from conversations.")
    elif args.op == "forget":
        res = kernel.forget(args.arg, by="user:cli", dry_run=not args.yes)
        deletable = [t for t in res["tasks"] if t["deletable"]]
        print(f"{'Deleted' if args.yes else 'Would delete'} {len(res['memories'])} memories, "
              f"{len(res['records'])} conversation records and {len(deletable)} finished tasks matching {args.arg!r}.")
        for t in res["tasks"]:
            if not t["deletable"]:
                print(f"  (still {t['state']}, not touched: {t['id']} — cancel it first)")
        for m in res["memories"][:20]:
            print(f"  - {m['text']}")
        if not args.yes:
            print("Run again with --yes to delete them.")
    elif args.op == "export":
        Path(args.arg).expanduser().write_text(_json.dumps(mem.export(), indent=2, default=str))
        print(f"Exported to {args.arg}")
    return 0


def _ask(kernel: Kernel, args) -> int:
    from .models import ChatRequest, Message, Need, NoModelAvailable
    from .models.types import Category
    from .persona import chat_abilities, priming_messages

    mem = kernel.memory
    recalled = mem.recall(args.question)
    context = mem.context_message(recalled)
    request = ChatRequest((
        *priming_messages(chat_abilities(mem.settings.enabled)),
        *([context] if context else []),
        Message("user", args.question, Category.CONVERSATION, local_only=args.local_only),
    ))
    try:
        r = _with_consent(kernel, lambda local: kernel.models.complete(
            Need("chat", min_quality=args.min_quality, prefer="auto", local_only=local or args.local_only),
            request, purpose="cli question"))
    except NoModelAvailable as exc:
        print(f"no model available: {exc}")
        for model, reason in exc.reasons.items():
            print(f"  {model}: {reason}")
        return 4
    print(r.text, flush=True)
    if recalled:
        print(f"\n(used {len(recalled)} memor{'y' if len(recalled) == 1 else 'ies'})", file=sys.stderr)
    if r.note:
        print(f"\n({r.note})", file=sys.stderr)
    print(f"\n[{r.provider}/{r.model} · {r.latency_s:.1f}s · {r.usage.output_tokens} tokens · ${r.cost_usd:.4f}]",
          file=sys.stderr, flush=True)
    mem.learn_from("cli", args.question, r.text, background=False)  # local model; after you've seen the answer
    return 0


if __name__ == "__main__":
    sys.exit(main())
