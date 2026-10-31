"""Run benchmark tasks against the real JARVIS code paths (dashboard chat, research, plan → task → approvals),
each inside its own throwaway data folder, and score them.

Isolation, per task:
- a fresh JARVIS data folder and approved folder (made-up files only), and a permission policy with no standing
  permissions, so every change needs an approval and the harness can check none slipped through;
- a stand-in for the Mac apps seeded from the task (nothing reaches your real Calendar, Reminders or Notes);
- your model settings (which local models, Claude on/off), never your memory, history, approvals or grants.

Models: ``local`` turns Claude off. ``hybrid`` uses your settings as they are, and gives the throwaway folder a
standing permission to send its made-up data to Claude, so the run isn't stopped by consent questions. Your real
JARVIS keeps asking every time. The $0 budget is required: a run refuses to start with any spending allowed.
"""

from __future__ import annotations

import json
import platform
import re
import shutil
import subprocess
import tempfile
import time
import tomllib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from .. import __version__
from ..core import Kernel
from ..core.permissions import Tier
from . import Task
from .scoring import score

PRIVATE = ("conversation", "file_content", "memory", "project")


class BenchError(RuntimeError):
    pass


# ---- a stand-in for Calendar / Reminders / Notes, seeded from the task -----------------------------------------
class FixtureMac:
    def __init__(self, mac: dict[str, Any], now: datetime | None = None):
        now = now or datetime.now().astimezone()

        def at(day: int, hhmm: str) -> str:
            h, m = (int(x) for x in hhmm.split(":"))
            return (now + timedelta(days=day)).replace(hour=h, minute=m, second=0, microsecond=0).isoformat()
        self.events = [{"title": e["title"], "start": at(e.get("day", 0), e["start"]), "end": at(e.get("day", 0), e["end"]),
                        "all_day": False, "location": e.get("location", ""), "calendar": e.get("calendar", "Home"),
                        "recurrence": None, "excluded": []} for e in mac.get("events", [])]
        self.reminders = [{"title": r["title"], "due": at(r["due_day"], r.get("due_time", "09:00")) if "due_day" in r else None,
                           "completed": False, "notes": "", "list": r.get("list", "Reminders")} for r in mac.get("reminders", [])]
        self.notes = [{"title": n["title"], "body": n["body"]} for n in mac.get("notes", [])]
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, name: str, args: dict, timeout: float) -> Any:
        self.calls.append((name, dict(args)))
        if name == "calendar.events":
            to, frm = args["to"], args["from"]
            return [e for e in self.events if e["start"] < to and e["end"] > frm]
        if name == "calendar.add":
            self.events.append({**{k: args.get(k) for k in ("title", "start", "end")}, "all_day": False,
                                "location": args.get("location", ""), "calendar": args.get("calendar") or "Home",
                                "recurrence": None, "excluded": []})
            return {"title": args["title"], "start": args["start"], "end": args["end"], "calendar": args.get("calendar") or "Home"}
        if name == "reminders.list":
            return [r for r in self.reminders if not r["completed"] and (not args.get("list") or r["list"] == args["list"])]
        if name == "reminders.add":
            self.reminders.append({"title": args["title"], "due": args.get("due"), "completed": False, "notes": "",
                                   "list": args.get("list") or "Reminders"})
            return {"title": args["title"], "list": args.get("list") or "Reminders", "due": args.get("due")}
        if name == "reminders.complete":
            hits = [r for r in self.reminders if r["title"] == args["title"] and not r["completed"]]
            if not hits:
                return {"error": "not_found"}
            hits[0]["completed"] = True
            return {"title": args["title"], "list": hits[0]["list"]}
        if name == "notes.search":
            q = args["query"].lower()
            hits = [n for n in self.notes if q in (n["title"] + n["body"]).lower()]
            return {"total": len(hits), "results": [{"title": n["title"], "modified": None, "snippet": n["body"][:240]}
                                                    for n in hits][: args.get("limit", 20)]}
        if name == "notes.read":
            hits = [n for n in self.notes if n["title"] == args["title"]]
            return {"error": "not_found"} if not hits else {"title": hits[0]["title"], "modified": None, "content": hits[0]["body"]}
        if name == "notes.create":
            self.notes.append({"title": args["title"], "body": args.get("html", "")})
            return {"title": args["title"], "folder": "Notes"}
        if name == "mail.draft":
            return {"subject": args["subject"], "to": args["to"], "saved_as": "draft"}
        if name == "apps.open":
            return {"opened": args["name"]}
        if name.endswith(".find"):
            return {"found": False}
        raise BenchError(f"the Mac stand-in doesn't know {name}")


# ---- settings for the throwaway folder ----------------------------------------------------------------------
def _drop_sections(text: str, names: tuple[str, ...]) -> str:
    out, skip = [], False
    for line in text.splitlines():
        m = re.match(r"^\s*\[\[?([^\]]+)\]\]?\s*$", line)
        if m:
            skip = m.group(1).split(".")[0].strip() in names
        if not skip:
            out.append(line)
    return "\n".join(out) + "\n"


def bench_config(real_config: Path, models: str) -> str:
    """Your model settings for a benchmark run: providers, routing and privacy rules kept; phone access, voice,
    backups and the briefing schedule dropped; Claude switched off for ``local``."""
    from ..models.config import parse_model_config

    text = real_config.read_text() if real_config.exists() else ""
    text = _drop_sections(text, ("remote", "voice", "backup", "proactive", "search"))
    if models == "local":
        text = re.sub(r"(\[providers\.claude\][^\[]*?enabled\s*=\s*)true", r"\1false", text, count=1)
        text = re.sub(r'(\[routing\][^\[]*?mode\s*=\s*)"[^"]*"', r'\1"local_first"', text, count=1)
    cfg = parse_model_config(tomllib.loads(text))
    if cfg.monthly_limit_usd != 0:
        raise BenchError("the benchmark only runs with a $0 budget (your jarvis.toml allows spending)")
    return text


# ---- one task -------------------------------------------------------------------------------------------------
def _setup(task: Task, base: Path, config_text: str, models: str, mac_runner) -> tuple[Kernel, Path]:
    from ..tools import default_registry

    home, work = base / "home", base / "work"
    (work / "notes").mkdir(parents=True)
    for f in task.setup.get("files", []):
        p = (work / f["path"]).resolve()
        if not str(p).startswith(str(work.resolve())):
            raise BenchError(f"{task.id}: setup file escapes the work folder")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f["content"])
    (base / "policy.toml").write_text(f'[filesystem]\nroots = ["{work}"]\n')  # no standing permissions at all
    (base / "jarvis.toml").write_text(config_text)
    k = Kernel(home, policy_path=base / "policy.toml", config_path=base / "jarvis.toml",
               registry=default_registry(home, mac_runner=mac_runner))
    if models == "hybrid":
        for cat in PRIVATE:  # made-up data only, and only in this throwaway folder
            k.models.router.gate.grants.grant(category=cat, provider="claude", by="user:bench")
    for text in task.setup.get("memories", []):
        k.memory.remember(text, origin="explicit", by="user:bench")
    for query in task.setup.get("forget", []):
        k.forget(query, by="user:bench", dry_run=False)
    return k, work


def _approve(task: Task, appr: dict, preview: str) -> bool:
    text = " ".join(str(x) for x in (appr.get("summary"), appr.get("resource"), preview)).lower()
    return any(m.lower() in text for m in task.approve)


def _run_do(task: Task, k: Kernel, work: Path, outcome: dict) -> None:
    from ..core.tasks import TaskState
    from ..orchestrator import Orchestrator
    from ..server.app import mac_preview

    orch = Orchestrator(k, notes_dir=str(work / "notes"))
    plan = orch.plan(task.prompt)
    outcome["plan_kind"] = plan.kind
    if plan.kind != "plan":
        outcome["answer"] = plan.message
        return
    tid = orch.submit(task.prompt, plan, actor="user:bench", runner="bench")
    deadline = time.monotonic() + task.time_limit_s
    while time.monotonic() < deadline:
        state = k.engine.run(tid)
        if state is TaskState.AWAITING_APPROVAL:
            for appr in k.approvals.pending(task_id=tid):
                args = orch.preview_args(tid, appr["step_id"]) if appr["step_id"] else {}
                preview = (args.get("content") or "") if appr["tool"] == "fs" else mac_preview(appr["tool"], appr["action"], args)
                ok = _approve(task, appr, str(preview))
                outcome["approvals"].append({"tool": appr["tool"], "action": appr["action"], "summary": appr["summary"],
                                             "approved": ok})
                k.approvals.decide(appr["id"], approve=ok, by="user:bench")
            continue
        if state is TaskState.RUNNING:
            time.sleep(0.5)
            continue
        break
    rep = orch.report(tid)
    outcome["task_state"] = rep["state"]
    outcome["answer"] = "\n".join(x for x in (rep.get("final_text") or "", rep.get("error") or "") if x)


def run_task(task: Task, *, config_text: str, models: str, keep: Path | None = None,
             mac_factory: Callable[[dict], FixtureMac] = FixtureMac) -> dict[str, Any]:
    from ..server import Dashboard

    base = Path(tempfile.mkdtemp(prefix=f"jarvis-bench-{task.id}-"))
    mac = mac_factory(task.setup.get("mac", {}))
    outcome: dict[str, Any] = {"answer": "", "files": str(base / "work"), "mac_calls": mac.calls, "approvals": [],
                               "tool_calls": [], "plan_kind": None, "sources": None, "violations": [], "error": None}
    started = time.monotonic()
    k = None
    try:
        k, work = _setup(task, base, config_text, models, mac)
        if task.mode == "do":
            _run_do(task, k, work, outcome)
        else:
            d = Dashboard(k, port=0, token="bench")
            try:
                if task.mode == "chat":
                    r = d.chat(task.prompt, [], session="bench")
                    outcome["answer"] = r.get("text") or r.get("error") or ("(needed approval: " + r.get("summary", "") + ")"
                                                                           if r.get("needs_approval") else "")
                    outcome["checked"] = r.get("checked", [])
                else:
                    r = d.research(task.prompt, session="bench")
                    outcome["answer"] = r.get("answer") or r.get("error") or ""
                    outcome["sources"] = r.get("sources") or []
            finally:
                d.httpd.server_close()
        _account(k, outcome)
    except Exception as exc:  # a crash is a failed task, with the reason
        outcome["error"] = f"{type(exc).__name__}: {exc}"
        if k is not None:
            _account(k, outcome)
    outcome["seconds"] = round(time.monotonic() - started, 1)
    if outcome["seconds"] > task.time_limit_s:
        outcome["error"] = (outcome["error"] or "") + f" over the {task.time_limit_s}s time limit"
    result = {"id": task.id, "category": task.category, "title": task.title, "mode": task.mode, "task_sha256": task.sha256,
              **{key: outcome[key] for key in ("answer", "seconds", "approvals", "tool_calls", "plan_kind", "violations",
                                               "error")},
              "mac_calls": [n for n, _ in outcome["mac_calls"]], "usage": outcome.get("usage", {}),
              "checked": outcome.get("checked", []), "outcome": outcome}
    if k is not None:
        k.close()
    if keep is not None:
        shutil.copytree(base / "work", keep / task.id / "work", dirs_exist_ok=True)
        outcome["files"] = str(keep / task.id / "work")
    shutil.rmtree(base, ignore_errors=True)
    return result


def _account(k: Kernel, outcome: dict) -> None:
    """From the audit log: which tools ran, model calls, and any change made without an approval."""
    entries = k.audit.entries(limit=5000)
    starts = [(e["payload"].get("tool"), e["payload"].get("action")) for e in entries if e["event"] == "tool.start"]
    outcome["tool_calls"] = starts
    approved: dict[tuple[str, str], int] = {}
    for row in k.db.query("SELECT tool, action FROM approvals WHERE state IN ('consumed', 'approved')"):
        approved[(row["tool"], row["action"])] = approved.get((row["tool"], row["action"]), 0) + 1
    for tool, action in starts:
        spec = k.registry.action(tool, action)
        if spec is None or spec.tier is Tier.READ:
            continue
        if approved.get((tool, action), 0) > 0:
            approved[(tool, action)] -= 1
        else:
            outcome["violations"].append(f"{tool}.{action} ran without an approval")
    outcome["usage"] = {
        "claude_calls": sum(1 for e in entries if e["event"] == "egress.send"),
        "local_calls": sum(1 for e in entries if e["event"] == "model.local_call"),
        "cost_usd": round(sum(float(e["payload"].get("estimated_cost_usd") or 0) for e in entries if e["event"] == "egress.send"), 4),
    }


# ---- a whole run ----------------------------------------------------------------------------------------------
def git_commit() -> str | None:
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=Path(__file__).resolve().parents[3],
                           capture_output=True, text=True, timeout=5)
        return r.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def run_suite(tasks: list[Task], *, real_config: Path, out_dir: Path, models: str = "local", repeat: int = 1,
              run_code: bool = False, mac_factory=FixtureMac, progress: Callable[[str], None] = lambda s: None) -> Path:
    if models not in ("local", "hybrid"):
        raise BenchError("models must be 'local' or 'hybrid'")
    config_text = bench_config(real_config, models)
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + f"-{models}"
    run_dir = out_dir / run_id
    run_dir.mkdir(parents=True)
    meta = {"run_id": run_id, "started": datetime.now().astimezone().isoformat(), "jarvis_version": __version__,
            "git_commit": git_commit(), "models": models, "repeat": repeat, "run_code": run_code,
            "platform": f"{platform.system()} {platform.release()} {platform.machine()}", "tasks": {}}
    results = []
    for task in tasks:
        meta["tasks"][task.id] = task.sha256
        for n in range(repeat):
            if task.needs_claude and models == "local":
                results.append({"id": task.id, "category": task.category, "title": task.title, "run": n + 1,
                                "status": "skipped", "passed": False, "checks": [],
                                "note": "needs Claude: run with --models hybrid"})
                continue
            progress(f"{task.id} (run {n + 1}/{repeat}) …")
            r = run_task(task, config_text=config_text, models=models, keep=run_dir / "files" / f"run{n + 1}",
                         mac_factory=mac_factory)
            graded = score(r.pop("outcome"), task.checks, run_code=run_code)
            r.update(run=n + 1, **graded)
            results.append(r)
            progress(f"  {graded['status'].upper()} · {r['seconds']}s")
    meta["finished"] = datetime.now().astimezone().isoformat()
    (run_dir / "results.json").write_text(json.dumps({"meta": meta, "results": results}, indent=2, default=str))
    (run_dir / "report.md").write_text(report(meta, results))
    return run_dir


def report(meta: dict, results: list[dict]) -> str:
    scored = [r for r in results if r.get("status") in ("pass", "fail")]
    lines = [f"# JARVIS benchmark · {meta['run_id']}", "",
             f"JARVIS {meta['jarvis_version']} ({meta.get('git_commit') or 'no git'}) · models: {meta['models']} · "
             f"{meta['platform']} · repeats: {meta['repeat']}", "",
             f"**Passed {sum(r['passed'] for r in scored)} of {len(scored)} scored runs.** "
             f"Partial (some checks not run): {sum(r.get('status') == 'partial' for r in results)} · "
             f"skipped: {sum(r.get('status') == 'skipped' for r in results)}", "",
             "| Category | Passed | Scored |", "|---|---|---|"]
    for cat in sorted({r["category"] for r in results}):
        rs = [r for r in scored if r["category"] == cat]
        lines.append(f"| {cat} | {sum(r['passed'] for r in rs)} | {len(rs)} |")
    claude = sum(r.get("usage", {}).get("claude_calls", 0) for r in results)
    local = sum(r.get("usage", {}).get("local_calls", 0) for r in results)
    cost = sum(r.get("usage", {}).get("cost_usd", 0) for r in results)
    secs = sum(r.get("seconds", 0) for r in results)
    lines += ["", f"Claude calls: {claude} · local model calls: {local} · cost: ${cost:.2f} · total time: {secs / 60:.1f} min", ""]
    for r in results:
        lines.append(f"## {r['id']} (run {r.get('run', 1)}) · {r.get('status', '?').upper()}")
        lines.append(f"{r['title']} · {r.get('seconds', 0)}s" + (f" · {r['note']}" if r.get("note") else ""))
        for c in r.get("checks", []):
            mark = {True: "✓", False: "✗", None: "–"}[c["passed"]]
            lines.append(f"- {mark} {c['type']}: {c['detail']}")
        if r.get("answer"):
            lines += ["", "~~~~", r["answer"][:1500], "~~~~"]  # answers may contain ``` themselves
        lines.append("")
    return "\n".join(lines)
