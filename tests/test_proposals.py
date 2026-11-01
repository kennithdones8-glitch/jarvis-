"""Improvement proposals: found in JARVIS's own record; deciding records your answer and changes nothing else."""

import json

import pytest
from test_bench import _run
from test_dashboard import call

from jarvis.core.util import new_id, now_iso
from jarvis.proposals import Proposals, detect


def _approval(k, tool, action, resource, state, tier=1):
    with k.db.tx() as c:
        c.execute("INSERT INTO approvals (id, task_id, step_id, tool, action, resource, args_hash, tier, reason, summary, "
                  "state, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                  (new_id("appr"), None, None, tool, action, resource, "h", tier, "r", "s", state, now_iso()))


def _bench(k):
    out = k.home / "bench-results"
    d = _run(out, "20261101-013114-local", {"coding-dedupe": "fff", "coding-roman": "ppp", "reasoning-flour": "fpf"},
             started="2026-11-01T01:31:14-05:00")
    data = json.loads((d / "results.json").read_text())
    for r in data["results"]:
        r["category"] = r["id"].split("-")[0]
    (d / "results.json").write_text(json.dumps(data))


def test_benchmark_failures_become_proposals(make_kernel):
    k = make_kernel()
    _bench(k)
    found = {p.key: p for p in detect(k)}
    assert set(found) == {"bench:coding", "bench:reasoning"}
    assert "coding-dedupe (0/3)" in found["bench:coding"].evidence and "coding-roman" not in str(found["bench:coding"].evidence)


def test_always_approved_routine_actions_suggest_a_rule_you_add_yourself(make_kernel, root):
    k = make_kernel()
    for _ in range(10):
        _approval(k, "fs", "write", f"{root}/notes/a.md", "consumed")
    for _ in range(12):
        _approval(k, "fs", "delete", f"{root}/notes/a.md", "consumed", tier=4)  # never suggested: deletes always ask
    p = {x.key: x for x in detect(k)}
    rule = p[f"allow:fs.write:{root}/notes"]
    assert rule.kind == "rule" and f'resources = ["{root}/notes/**"]' in rule.suggestion
    assert not any(key.startswith("allow:fs.delete") for key in p)
    _approval(k, "fs", "write", f"{root}/notes/b.md", "rejected")  # one rejection: no longer "always"
    assert not any(key.startswith("allow:fs.write") for key in (x.key for x in detect(k)))


def test_repeated_rejections_and_timeouts(make_kernel):
    k = make_kernel()
    for _ in range(3):
        _approval(k, "apps", "open", None, "rejected")
    for i in range(3):
        k.audit.record("tool.start", op_id=f"op{i}", tool="calendar", action="events", args={})
        k.audit.record("tool.timeout", op_id=f"op{i}", timeout_s=85)
    keys = {x.key for x in detect(k)}
    assert "rejected:apps.open:None" in keys and "timeout:calendar.events" in keys


def test_deciding_records_your_answer_and_changes_nothing_else(make_kernel, root):
    k = make_kernel()
    for _ in range(10):
        _approval(k, "fs", "write", f"{root}/notes/a.md", "consumed")
    policy_before = k.policy_path.read_text()
    props = Proposals(k)
    assert props.refresh() == {"added": 1, "updated": 0}
    pid = props.list()[0]["id"]
    with pytest.raises(PermissionError):
        props.decide(pid, "approved", by="system")
    with pytest.raises(PermissionError):
        props.brief(pid)  # only approved proposals get a brief
    props.decide(pid, "approved", by="user:test")
    assert k.policy_path.read_text() == policy_before  # never edits its own policy
    brief = props.brief(pid)
    assert "Stage A first" in brief and "new branch" in brief and pid in brief
    assert props.refresh() == {"added": 0, "updated": 0}  # an approved one isn't re-proposed
    ev = [e for e in k.audit.entries() if e["event"] == "proposals.decided"][-1]["payload"]
    assert ev["state"] == "approved"


def test_a_rejected_idea_returns_only_if_the_evidence_doubles(make_kernel):
    k = make_kernel()
    for _ in range(3):
        _approval(k, "apps", "open", None, "rejected")
    props = Proposals(k)
    props.refresh()
    pid = props.list()[0]["id"]
    props.decide(pid, "rejected", by="user:test")
    _approval(k, "apps", "open", None, "rejected")
    props.refresh()
    assert props.get(pid)["state"] == "rejected"  # 4 isn't double 3
    for _ in range(2):
        _approval(k, "apps", "open", None, "rejected")
    props.refresh()
    assert props.get(pid)["state"] == "open" and props.get(pid)["size"] == 6


def test_evidence_holds_no_private_text(make_kernel):
    k = make_kernel()
    k.memory.remember("My locker code is zebra-quartz", origin="explicit", by="user:test")  # text that can't occur by chance
    k.audit.record("chat.grounding", ok=False, unsupported_times=1, retried=True)
    for _ in range(3):
        k.audit.record("chat.grounding", ok=False, unsupported_times=1, retried=True)
    props = Proposals(k)
    props.refresh()
    assert "zebra-quartz" not in json.dumps(props.list()).lower()


def test_dashboard_page_and_decisions(dash):
    d, _, root = dash
    for _ in range(3):
        _approval(d.kernel, "apps", "open", None, "rejected")
    status, _, body = call(d, "/api/proposals")
    items = json.loads(body)["proposals"]
    assert status == 200 and items[0]["title"] == "You keep rejecting apps.open"
    pid = items[0]["id"]
    assert call(d, f"/api/proposals/{pid}/approve", {}, headers={"X-Requested-By": "nope"})[0] == 403  # CSRF check
    status, _, body = call(d, f"/api/proposals/{pid}/approve", {})
    assert status == 200 and json.loads(body)["state"] == "approved"
    assert call(d, "/api/proposals/nope/approve", {})[0] == 404
    assert call(d, "/api/proposals", cookie=False)[0] in (401, 403)
    status, _, body = call(d, "/proposals")
    assert status == 200 and b"/static/proposals.js" in body and b"style=" not in body
    assert "innerHTML" not in call(d, "/static/proposals.js")[2].decode()
    # reachable from the dashboard: sidebar / More → Briefing & ideas → "Open Ideas to decide"
    assert b'href="#/intelligence"' in call(d, "/")[2]
    assert 'h("a", { class: "btn btn-sm", href: "/proposals" }, "Open Ideas to decide")' in call(d, "/static/app.js")[2].decode()


def test_cli(tmp_path, capsys):
    from jarvis.cli import main as cli_main
    home = tmp_path / "h"
    assert cli_main(["--home", str(home), "init"]) == 0
    capsys.readouterr()
    assert cli_main(["--home", str(home), "proposals"]) == 0
    assert "No proposals" in capsys.readouterr().out
    assert cli_main(["--home", str(home), "proposals", "approve"]) == 1
    assert cli_main(["--home", str(home), "proposals", "show", "prop_nope"]) == 1
