"""v0.12 F2: private text is fingerprinted in the audit log, and `forget` removes it everywhere JARVIS
keeps it — including the raw database files — while the audit chain stays verifiable."""

import pytest

from jarvis.core import StepSpec, TaskState
from jarvis.core.audit import fingerprint, minimise
from jarvis.core.tasks import InvalidTransition

SECRET = "Jane Roe custody hearing"


def run_private_task(k, root):
    tid = k.tasks.create(f"Draft a note about {SECRET}", steps=[
        StepSpec(f"Save note about {SECRET}", "fs", "write", {"path": f"{root}/notes/n.md", "content": f"Call {SECRET}"})])
    assert k.engine.run(tid) is TaskState.COMPLETED
    return tid


def raw_files_contain(k, needle: bytes) -> bool:
    return any(needle in p.read_bytes() for p in k.home.glob("jarvis.db*"))


def test_audit_fingerprints_free_text_but_keeps_paths_and_structure(make_kernel, root):
    k = make_kernel(registry="default")
    tid = run_private_task(k, root)
    entries = k.audit.entries(task_id=tid, limit=200)
    assert SECRET not in str(entries)
    start = next(e for e in entries if e["event"] == "tool.start")
    assert start["payload"]["args"]["path"] == f"{root}/notes/n.md"            # paths stay readable
    assert start["payload"]["args"]["content"] == fingerprint(f"Call {SECRET}")  # text provable, not readable
    assert start["payload"]["tool"] == "fs" and k.audit.verify().ok


def test_forget_removes_text_from_every_table_and_the_raw_files(make_kernel, root):
    k = make_kernel(registry="default")
    k.memory.remember(f"Lawyer is {SECRET}", by="user:test")
    tid = run_private_task(k, root)
    preview = k.forget("Jane Roe", by="user:test")
    assert len(preview["memories"]) == 1 and [t["id"] for t in preview["tasks"]] == [tid]
    assert raw_files_contain(k, b"Jane Roe")                                   # still there before forgetting
    k.forget("Jane Roe", by="user:test", dry_run=False)
    dump = "\n".join(k.db._conn.iterdump())
    assert "Jane Roe" not in dump
    assert not raw_files_contain(k, b"Jane Roe")                               # not lingering on disk, while running
    events = [e["event"] for e in k.audit.entries(limit=50)]
    assert k.audit.verify().ok and "memory.forget" in events and "task.deleted" in events
    assert (root / "notes" / "n.md").exists()                                  # your own files are never touched


def test_active_tasks_are_listed_not_deleted(make_kernel, root):
    k = make_kernel(registry="default")
    tid = k.tasks.create(f"About {SECRET}", steps=[StepSpec("x", "fs", "list", {"path": str(root)})])
    res = k.forget("Jane Roe", by="user:test", dry_run=False)
    assert res["tasks"][0]["deletable"] is False and k.tasks.get(tid)
    with pytest.raises(InvalidTransition):
        k.tasks.delete(tid, by="user:test")


def test_minimise_rules():
    out = minimise({"args": {"path": "~/x.md", "url": "https://a.org/p", "content": "hello", "n": 3, "flag": True,
                             "api_key": "[REDACTED]"}, "tool": "fs", "reason": "matched rule notes"})
    assert out["args"]["path"] == "~/x.md" and out["args"]["url"] == "https://a.org/p"
    assert out["args"]["content"] == fingerprint("hello") and out["args"]["n"] == 3 and out["args"]["flag"] is True
    assert out["args"]["api_key"] == "[REDACTED]" and out["tool"] == "fs" and out["reason"] == "matched rule notes"
    text = "/etc/passwd\nroot:x"
    assert minimise({"content": text})["content"] == fingerprint(text)            # multi-line isn't a "path"
