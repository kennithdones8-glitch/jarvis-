"""Phase 2 backend: live system telemetry (never invented) and the evolving core (only verified milestones)."""

import json
import subprocess

import pytest

from test_dashboard import call

from jarvis import evolution, telemetry

VM_STAT = """Mach Virtual Memory Statistics: (page size of 4096 bytes)
Pages free:                               12345.
Pages active:                            800000.
Pages inactive:                          700000.
Pages speculative:                        30000.
Pages throttled:                              0.
Pages wired down:                        400000.
Pages purgeable:                          10000.
"Translation faults":                 123456789.
Pages copy-on-write:                    4567890.
Pages zero filled:                     98765432.
Pages reactivated:                        12345.
Pages purged:                              6789.
File-backed pages:                       300000.
Anonymous pages:                        1200000.
Pages stored in compressor:              900000.
Pages occupied by compressor:            300000.
Decompressions:                           12345.
Compressions:                             67890.
"""


def test_vm_stat_is_parsed_like_activity_monitor(monkeypatch):
    vm = telemetry.parse_vm_stat(VM_STAT)
    assert vm["page_size"] == 4096 and vm["pages active"] == 800000 and vm["pages occupied by compressor"] == 300000
    monkeypatch.setattr(telemetry.sys, "platform", "darwin")
    outputs = {"/usr/sbin/sysctl": "34359738368\n", "/usr/bin/vm_stat": VM_STAT}
    monkeypatch.setattr(telemetry, "_run", lambda args: outputs[args[0]])
    m = telemetry.memory()
    assert m["available"] and m["total_bytes"] == 32 * 1024**3
    assert m["used_bytes"] == (800000 + 400000 + 300000) * 4096 and 0 < m["used_pct"] < 100
    assert "vm_stat" in m["source"]


def test_unreadable_figures_are_reported_unavailable_not_guessed(monkeypatch):
    monkeypatch.setattr(telemetry.sys, "platform", "darwin")

    def fail(args):
        raise subprocess.TimeoutExpired(args, 2)
    monkeypatch.setattr(telemetry, "_run", fail)
    m = telemetry.memory()
    assert m == {"available": False, "reason": "couldn't read memory use (TimeoutExpired)"}
    monkeypatch.setattr(telemetry.os, "getloadavg", lambda: (_ for _ in ()).throw(OSError("no")))
    assert telemetry.cpu()["available"] is False


def test_commands_run_with_a_fixed_path_and_deadline(monkeypatch):
    seen = {}

    def fake(args, **kw):
        seen.update(kw, args=args)
        return subprocess.CompletedProcess(args, 0, "1\n", "")
    monkeypatch.setattr(telemetry.subprocess, "run", fake)
    telemetry._run(["/usr/sbin/sysctl", "-n", "hw.memsize"])
    assert seen["timeout"] == telemetry.TIMEOUT_S and seen["env"]["PATH"] == "/usr/bin:/bin:/usr/sbin:/sbin"
    assert seen["args"][0].startswith("/")  # absolute: never whatever `sysctl` is first on PATH


def test_network_check_returns_no_address():
    n = telemetry.network()
    assert set(n) == {"available", "route", "source"} and isinstance(n["route"], bool)


def test_snapshot_is_cached(tmp_path, monkeypatch):
    t = telemetry.Telemetry(tmp_path, ttl_s=60)
    calls = []
    monkeypatch.setattr(telemetry, "cpu", lambda: calls.append(1) or {"available": True})
    t.snapshot()
    t.snapshot()
    assert len(calls) == 1


# ---- evolution -------------------------------------------------------------------------------------------------
def facts(**over):
    base = {"db_ok": True, "audit_ok": True, "providers": [], "confirmed_memories": 0, "completed_tasks": 0,
            "capabilities": {}, "voice_ready": False, "paired_phones": 0, "touch_id": False, "bench_runs": False,
            "health": None}
    return {**base, **over}


LOCAL = [{"location": "local", "available": ["m"]}]


def test_tiers_follow_verified_milestones_only(make_kernel):
    k = make_kernel()
    r = evolution.evaluate(k, facts())
    assert (r["tier"], r["name"], r["verified"]) == (1, "Foundational Projection", 1)  # only "Core online"
    assert r["next"] == {"tier": 2, "name": "Advanced Projection", "needs": 4}
    r = evolution.evaluate(k, facts(providers=LOCAL, confirmed_memories=1, completed_tasks=1, touch_id=True))
    assert (r["tier"], r["name"], r["verified"]) == (2, "Advanced Projection", 5)
    assert r["version"] == evolution.DEFINITION_VERSION and r["stages"][3] == "Evolved Projection" and r["stages"][4] == "Signature Projection"
    assert {m["id"] for m in r["milestones"] if m["verified"]} == {"core_online", "local_mind", "memory", "first_mission", "touch_id"}


def test_first_verification_is_recorded_once_with_no_content(make_kernel):
    k = make_kernel()
    evolution.evaluate(k, facts(providers=LOCAL))
    evolution.evaluate(k, facts(providers=LOCAL))
    events = [e for e in k.audit.entries(limit=100) if e["event"] == "evolution.milestone"]
    assert sorted(e["payload"]["milestone"] for e in events) == ["core_online", "local_mind"]
    assert all(set(e["payload"]) == {"milestone"} for e in events)


def test_a_lost_capability_holds_for_seven_days_then_stops_counting(make_kernel):
    from datetime import datetime, timedelta, timezone
    k = make_kernel()
    t0 = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    gone = [{"location": "local", "available": []}]
    first = evolution.evaluate(k, facts(providers=LOCAL), now=t0)
    day3 = evolution.evaluate(k, facts(providers=gone), now=t0 + timedelta(days=3))
    lm = {m["id"]: m for m in day3["milestones"]}["local_mind"]
    assert lm["verified"] is False and lm["held"] is True and lm["counts"] is True
    assert lm["held_until"].startswith("2026-11-08") and day3["verified"] == first["verified"]  # stage holds
    day8 = evolution.evaluate(k, facts(providers=gone), now=t0 + timedelta(days=8))
    lm = {m["id"]: m for m in day8["milestones"]}["local_mind"]
    assert lm["held"] is False and lm["counts"] is False and day8["verified"] == first["verified"] - 1   # reversible
    assert lm["first_verified"] == {m["id"]: m for m in first["milestones"]}["local_mind"]["first_verified"]  # record kept


def test_stage_changes_and_definition_versions_are_audited(make_kernel):
    from datetime import datetime, timedelta, timezone
    k = make_kernel()
    t0 = datetime(2026, 11, 1, tzinfo=timezone.utc)
    evolution.evaluate(k, facts(), now=t0)
    evolution.evaluate(k, facts(providers=LOCAL, confirmed_memories=1, completed_tasks=1, touch_id=True), now=t0 + timedelta(minutes=1))
    tiers = [e["payload"] for e in k.audit.entries(limit=100) if e["event"] == "evolution.tier"]
    assert tiers == [{"frm": 1, "to": 2, "verified": 5}]
    with k.db.tx() as c:
        c.execute("UPDATE meta SET value = '1' WHERE key = ?", (evolution.VERSION_KEY,))
    evolution.evaluate(k, facts(), now=t0 + timedelta(minutes=2))
    assert [e["payload"] for e in k.audit.entries(limit=100) if e["event"] == "evolution.definitions"] == [{"frm": "1", "to": str(evolution.DEFINITION_VERSION)}]


def test_last_verified_is_not_rewritten_every_minute(make_kernel):
    from datetime import datetime, timedelta, timezone
    k = make_kernel()
    t0 = datetime(2026, 11, 1, tzinfo=timezone.utc)
    evolution.evaluate(k, facts(providers=LOCAL), now=t0)
    before = k.db.one("SELECT value FROM meta WHERE key = ?", (evolution.META_KEY,))[0]
    evolution.evaluate(k, facts(providers=LOCAL), now=t0 + timedelta(minutes=5))
    assert k.db.one("SELECT value FROM meta WHERE key = ?", (evolution.META_KEY,))[0] == before
    evolution.evaluate(k, facts(providers=LOCAL), now=t0 + timedelta(hours=2))
    assert k.db.one("SELECT value FROM meta WHERE key = ?", (evolution.META_KEY,))[0] != before


def test_activity_alone_earns_nothing(make_kernel):
    k = make_kernel()
    k.memory.remember("the owner probably likes tea", origin="observed")  # a guess is not a confirmed memory
    f = evolution.facts_from(k, health=None, providers=[], capabilities={}, voice_ready=False, paired_phones=0,
                             touch_id=False)
    assert f["confirmed_memories"] == 0 and f["completed_tasks"] == 0 and f["bench_runs"] is False
    k.memory.remember("my name is Sam")
    assert evolution.facts_from(k, health=None, providers=[], capabilities={}, voice_ready=False, paired_phones=0,
                                touch_id=False)["confirmed_memories"] == 1


@pytest.mark.parametrize("count,tier", [(0, 1), (4, 1), (5, 2), (9, 2), (10, 3), (14, 3), (15, 4), (18, 4), (19, 5)])
def test_tier_thresholds(count, tier):
    assert evolution.tier_for(count)[0] == tier


def test_dashboard_state_carries_real_telemetry_evolution_and_model_timings(dash):
    d, _, _ = dash
    d._evolution = d.evolution()
    json.loads(call(d, "/api/chat", {"message": "hi", "history": []})[2])
    d._intel_cache = (0.0, {})
    state = json.loads(call(d, "/api/state")[2])
    assert state["telemetry"]["storage"]["available"] and "source" in state["telemetry"]["cpu"]
    assert state["evolution"]["tier"] >= 1 and len(state["evolution"]["milestones"]) == len(evolution.MILESTONES)
    last = state["intelligence"]["last"]
    assert last["model"] == "ollama/planner:7b" and last["location"] == "local" and last["latency_s"] is not None
    assert "hi" not in json.dumps(state["intelligence"])  # timings and counts only


def test_evolution_events_are_worded(dash):
    from jarvis.server.app import describe_event
    assert describe_event("evolution.milestone", {"milestone": "local_mind"}) == \
        "Core evolution: verified “Local intelligence”"
    assert "tier 1 → 2" in describe_event("evolution.tier", {"frm": 1, "to": 2, "verified": 4})


# ---- milestones from real runs (definitions v3) ----------------------------------------------------------------------
def _kernel_facts(k, **over):
    f = evolution.facts_from(k, health=over.pop("health", {"ok": True, "items": []}), providers=[], capabilities={},
                             voice_ready=False, paired_phones=0, touch_id=False)
    f.update(over)
    return f


def _ids(r, key="verified"):
    return {m["id"] for m in r["milestones"] if m[key]}


def test_missions_count_only_completed_verified_tasks(make_kernel):
    k = make_kernel()
    r = evolution.evaluate(k, facts(completed_tasks=24))
    assert {"missions_5"} <= _ids(r) and "missions_25" not in _ids(r) and "missions_100" not in _ids(r)
    assert {"missions_5", "missions_25"} <= _ids(evolution.evaluate(k, facts(completed_tasks=25)))


def test_benchmark_milestone_needs_a_real_passing_run(make_kernel):
    k = make_kernel()
    assert "bench_pass" not in _ids(evolution.evaluate(k, _kernel_facts(k)))   # no run, nothing earned
    run = k.home / "bench-results" / "20261101-120000-local"
    run.mkdir(parents=True)

    def save(passed, total):
        results = [{"id": f"t{i}", "status": "pass" if i < passed else "fail"} for i in range(total)]
        (run / "results.json").write_text(json.dumps({"meta": {"run_id": run.name, "started": "2026-11-01T12:00:00"}, "results": results}))
    save(17, 22)
    assert "bench_pass" not in _ids(evolution.evaluate(k, _kernel_facts(k)))   # 77% is below the bar
    save(18, 22)
    assert "bench_pass" in _ids(evolution.evaluate(k, _kernel_facts(k)))


def test_doctor_and_mac_check_count_only_when_they_passed_recently(make_kernel):
    from datetime import datetime, timedelta, timezone
    k = make_kernel()
    assert not {"doctor_green", "mac_check"} & _ids(evolution.evaluate(k, _kernel_facts(k)))
    evolution.record_check(k, "doctor", True)
    evolution.record_check(k, "mac_check", False)
    r = evolution.evaluate(k, _kernel_facts(k))
    assert "doctor_green" in _ids(r) and "mac_check" not in _ids(r)
    evolution.record_check(k, "doctor", True, now=datetime.now(timezone.utc) - timedelta(days=31))   # stale run
    assert "doctor_green" not in _ids(evolution.evaluate(k, _kernel_facts(k)))
    assert [e["payload"] for e in k.audit.entries(limit=50) if e["event"] == "evolution.check"][:2] == [
        {"check": "doctor", "ok": True}, {"check": "mac_check", "ok": False}]


def test_reliability_needs_thirty_quiet_days(make_kernel):
    from datetime import datetime, timedelta, timezone
    k = make_kernel()
    now = datetime.now(timezone.utc)
    assert evolution._reliable(k, {"ok": True}, now + timedelta(days=40)) is False   # no history at all: can't be reliable
    k.audit.record("dashboard.started")                                               # the installation's first record
    assert evolution._reliable(k, {"ok": True}, now) is False                         # too young
    later = now + timedelta(days=31)
    assert evolution._reliable(k, {"ok": True}, later) is True
    assert evolution._reliable(k, {"ok": False}, later) is False                      # unhealthy now
    evolution.record_check(k, "drill", False, now=later - timedelta(days=2))
    assert evolution._reliable(k, {"ok": True}, later) is False                       # a recent failed drill
    k.audit.record("health.changed", ok=False, problems=["Backups"])
    assert evolution._reliable(k, {"ok": True}, now + timedelta(days=20)) is False


def test_cli_records_real_doctor_runs(tmp_path, monkeypatch):
    from jarvis.cli import main
    from jarvis.core import Kernel
    home = tmp_path / "h"
    assert main(["--home", str(home), "init"]) == 0
    main(["--home", str(home), "doctor", "--no-voice-test"])
    k = Kernel(home)
    try:
        assert evolution._check(k, "doctor") is not None   # recorded (pass or fail, whichever was true)
    finally:
        k.close()
