"""Flight Recorder: one readable timeline per task, built from what JARVIS already records.

It reads the hash-chained audit log, the task, its steps and its approvals, and puts them in order: the request,
the plan, each permission decision, each approval and who gave it, which model did what (on the Mac or Claude),
what each tool did, the verification and the outcome. Read-only: it changes nothing, and it shows only what the
audit log already holds (which by design has fingerprints, not your private text).
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

# How each audit event appears in the timeline: (phase, include?). Phases group the story for display.
PHASES = {
    "task.created": "request", "orchestrator.planned": "plan", "task.state": "state", "task.control": "state",
    "task.verified": "verify", "task.deleted": "state",
    "permission.check": "permission", "permission.denied": "permission",
    "approval.requested": "approval", "approval.approved": "approval", "approval.rejected": "approval",
    "approval.consumed": "approval", "approval.restored": "approval", "approval.expired": "approval",
    "tool.start": "tool", "tool.result": "tool", "tool.error": "tool", "tool.uncertain": "tool",
    "model.route": "model", "model.local_call": "model", "model.fallback": "model", "model.triage": "model",
    "model.no_route": "model", "model.attempt_failed": "model",
    "egress.send": "cloud", "egress.denied": "cloud",
    "emergency_stop.engaged": "stop", "emergency_stop.released": "stop",
}
SUMMARY_TEXT = {
    "approval.consumed": "Your approval was used for this step",
    "approval.restored": "Approval kept for later (the step didn't run)",
}


def timeline(kernel, task_id: str) -> dict[str, Any]:
    """Everything recorded about one task, in order. Raises KeyError for an unknown task."""
    from .server.app import describe_event, tilde

    task = kernel.tasks.get(task_id)
    steps = kernel.tasks.steps(task_id)
    approvals = [dict(r) for r in kernel.db.query(
        "SELECT id, tool, action, resource, tier, state, summary, decided_by, created_at FROM approvals "
        "WHERE task_id = ? ORDER BY created_at", (task_id,))]
    entries = kernel.audit.entries(task_id=task_id, limit=5000)
    ids = {a["id"] for a in approvals}
    if ids:  # "used" and "restored" are recorded by approval id only
        for row in kernel.db.query("SELECT * FROM audit WHERE event IN ('approval.consumed', 'approval.restored') "
                                   "ORDER BY seq"):
            payload = json.loads(row["payload"])
            if payload.get("approval_id") in ids:
                entries.append({**dict(row), "payload": payload})
    entries.sort(key=lambda e: e["seq"])

    goals = {task_id: task["goal"]}
    calls: dict[str, str] = {}  # op_id → "tool.action": "finished" entries don't repeat which action it was
    events, seen = [], set()
    for e in entries:
        if e["seq"] in seen:
            continue
        seen.add(e["seq"])
        phase = PHASES.get(e["event"], "other")
        text = SUMMARY_TEXT.get(e["event"]) or describe_event(e["event"], e["payload"], task_id=e["task_id"], goals=goals)
        op = e["payload"].get("op_id")
        if e["event"] == "tool.start" and op:
            calls[op] = f"{e['payload'].get('tool')}.{e['payload'].get('action')}"
        elif e["event"] == "tool.result" and op in calls:
            text = f"Finished {calls[op]}"
        events.append({"seq": e["seq"], "ts": e["ts"], "phase": phase, "event": e["event"], "actor": e["actor"],
                       "text": tilde(text) if isinstance(text, str) else text,
                       "problem": e["event"] in ("tool.error", "tool.uncertain", "permission.denied", "egress.denied",
                                                  "model.no_route", "model.attempt_failed")
                       or (e["event"] == "task.verified" and not e["payload"].get("ok"))
                       or (e["event"] == "task.state" and e["payload"].get("to") in ("failed", "blocked"))})

    def count(event: str) -> int:
        return sum(1 for e in entries if e["event"] == event)
    verified = next((e["payload"].get("ok") for e in reversed(entries) if e["event"] == "task.verified"), None)
    started, last = (entries[0]["ts"], entries[-1]["ts"]) if entries else (task["created_at"], task["updated_at"])
    try:
        duration = round((datetime.fromisoformat(last) - datetime.fromisoformat(started)).total_seconds(), 1)
    except ValueError:
        duration = None
    chain = kernel.audit.verify()
    return {
        "task": {"id": task_id, "goal": task["goal"], "state": task["state"], "created_at": task["created_at"],
                 "updated_at": task["updated_at"], "runner": task["context"].get("runner"),
                 "planner": task["context"].get("planner"), "error": task["error"]},
        "steps": [{"n": s["idx"], "description": s["description"], "call": f"{s['tool']}.{s['action']}",
                   "state": s["state"], "attempts": s["attempts"], "error": s["error"]} for s in steps],
        "approvals": [{"tool": a["tool"], "action": a["action"], "tier": a["tier"], "state": a["state"],
                       "summary": tilde(a["summary"]), "decided_by": a["decided_by"]} for a in approvals],
        "events": events,
        "summary": {
            "duration_s": duration, "steps": len(steps), "steps_done": sum(s["state"] == "done" for s in steps),
            "tools_run": count("tool.start"), "local_model_calls": count("model.local_call"),
            "claude_calls": count("egress.send"), "approvals_requested": count("approval.requested"),
            "approved": count("approval.approved"), "rejected": count("approval.rejected"),
            "permission_denials": count("permission.denied"), "verified": verified,
            "problems": sum(ev["problem"] for ev in events),
        },
        "integrity": {"audit_chain_ok": chain.ok, "entries_checked": chain.checked,
                      "first_bad_seq": chain.first_bad_seq},
    }


def as_text(t: dict[str, Any]) -> str:
    task, s = t["task"], t["summary"]
    verified = {True: "passed", False: "FAILED", None: "not run"}[s["verified"]]
    lines = [f"Task {task['id']} · {task['state'].replace('_', ' ')}", f"Goal: {task['goal']}",
             f"{s['steps_done']}/{s['steps']} steps · {s['tools_run']} tool runs · models: {s['local_model_calls']} on the Mac, "
             f"{s['claude_calls']} Claude · approvals: {s['approvals_requested']} asked, {s['approved']} approved, "
             f"{s['rejected']} rejected · verification {verified}"
             + (f" · {s['duration_s']}s" if s["duration_s"] is not None else ""),
             "Audit log: " + ("intact" if t["integrity"]["audit_chain_ok"] else
                              f"BROKEN at entry {t['integrity']['first_bad_seq']} — this timeline may be incomplete"), ""]
    for e in t["events"]:
        when = e["ts"][11:19] if len(e["ts"]) > 19 else e["ts"]
        who = "" if e["actor"] in ("system", None) else f" [{e['actor']}]"
        lines.append(f"{'!' if e['problem'] else ' '} {when} {e['phase']:<10} {e['text']}{who}")
    return "\n".join(lines)
