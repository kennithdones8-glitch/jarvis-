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
    sub.add_parser("tasks", help="list recent tasks")
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

    recovered = kernel.start()
    dash = Dashboard(kernel, port=args.port)
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
    try:
        r = probe.chat("haiku" if "haiku" in pc.models else next(iter(pc.models)), ChatRequest((
            Message("system", "Reply with exactly: JARVIS link online.", Category.SYSTEM_PROMPT),
            Message("user", "Status check.", Category.SYSTEM_PROMPT))))
    except ProviderError as exc:
        print(f"Claude Code did not answer: {exc}\nJARVIS will keep using local models until it does.")
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

    from .core.tasks import TaskState

    while True:
        state = kernel.engine.run(task_id)
        if state is TaskState.AWAITING_APPROVAL:
            for appr in kernel.approvals.pending(task_id=task_id):
                print(f"\nApproval needed (tier {appr['tier']}): {appr['summary']}\n  reason: {appr['reason']}")
                if appr["tool"] == "fs" and appr["step_id"]:
                    preview = orch.preview_args(task_id, appr["step_id"]).get("content")
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


def _ask(kernel: Kernel, args) -> int:
    from .models import ChatRequest, Message, Need, NoModelAvailable
    from .models.types import Category
    from .persona import priming_messages

    request = ChatRequest((
        *priming_messages(),
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
    print(r.text)
    if r.note:
        print(f"\n({r.note})", file=sys.stderr)
    print(f"\n[{r.provider}/{r.model} · {r.latency_s:.1f}s · {r.usage.output_tokens} tokens · ${r.cost_usd:.4f}]",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
