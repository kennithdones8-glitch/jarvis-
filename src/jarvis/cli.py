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
        elif args.cmd == "models":
            _print(_models_status(kernel))
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


def _models_status(kernel: Kernel) -> dict:
    from .models.types import ProviderError

    router = kernel.models.router
    out = {"budget": {"monthly_limit_usd": router.gate.budget.monthly_limit_usd,
                      "spent_this_month_usd": router.gate.budget.spent_this_month()},
           "local_only_categories": list(kernel.model_config.local_only_categories), "providers": []}
    sources = [(p.name, "local", p.models, p.available_models, p.data_use_note) for p in router.local.values()]
    sources += [(s.name, "cloud", s.models, lambda n=s.name: router.gate.available_models(n), s.data_use_note)
                for s in router.gate.summaries()]
    for name, location, models, available_fn, note in sources:
        try:
            available, error = sorted(available_fn()), None
        except ProviderError as exc:
            available, error = [], str(exc)
        out["providers"].append({"name": name, "location": location, "configured": sorted(models),
                                 "available": available, "error": error, "data_use": note})
    disabled = [p.name for p in kernel.model_config.providers if not p.enabled]
    out["disabled_providers"] = disabled
    return out


def _ask(kernel: Kernel, args) -> int:
    from .core.tools import ApprovalRequired
    from .models import ChatRequest, Message, Need, NoModelAvailable
    from .models.types import Category
    from .persona import system_message

    request = ChatRequest((
        system_message(),
        Message("user", args.question, Category.CONVERSATION, local_only=args.local_only),
    ))
    try:
        r = kernel.models.complete(Need("chat", min_quality=args.min_quality), request, purpose="cli question")
    except ApprovalRequired as exc:
        print(f"needs your approval first: jarvis approvals  (then: jarvis approve {exc.approval_id} and re-ask)")
        return 3
    except NoModelAvailable as exc:
        print(f"no model available: {exc}")
        for model, reason in exc.reasons.items():
            print(f"  {model}: {reason}")
        return 4
    print(r.text)
    print(f"\n[{r.provider}/{r.model} · {r.latency_s:.1f}s · {r.usage.output_tokens} tokens · ${r.cost_usd:.4f}]",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
