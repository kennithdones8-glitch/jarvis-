"""Missions and decisions on the dashboard: real step counts, honest pause/cancel, decisions that scale with risk."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "src" / "jarvis" / "server" / "static"
JS = (STATIC / "app.js").read_text()


def _fn(name):
    return re.search(rf"function {name}\(.*?\n\}}\n", JS, re.S).group(0)


def _node(body, tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    (tmp_path / "h.js").write_text(body)
    return json.loads(subprocess.run([node, str(tmp_path / "h.js")], capture_output=True, text=True, check=True).stdout)


def test_progress_is_real_step_counts_never_percent(tmp_path):
    got = _node(_fn("stepText") + r"""
const t = (state, steps) => ({ state, steps: steps.map((s) => ({ state: s })) });
console.log(JSON.stringify({
  running: stepText(t("running", ["done", "started", "pending"])),
  queued: stepText(t("queued", ["pending", "pending"])),
  done: stepText(t("completed", ["done", "skipped"])),
  failed: stepText(t("failed", ["done", "failed", "pending"])),
  none: stepText(t("planning", [])),
}));""", tmp_path)
    assert got == {"running": "Step 2 of 3", "queued": "Step 1 of 2", "done": "2 of 2 steps done",
                   "failed": "1 of 3 steps done", "none": "No steps yet"}
    assert "%" not in _fn("stepText") and "%" not in _fn("missionRow")


def test_decision_detail_grows_with_risk_and_cloud_consent_shows_why(tmp_path):
    got = _node("const h = (t, p, ...k) => ({ t, k: k.flat().filter(Boolean).map((x) => x.k ? x.k.join('') : x) });\n"
                + _fn("riskOf") + _fn("egressLines") + r"""
const summary = "purpose: dashboard chat. Provider data use: Claude via your Claude Pro plan; consumer terms apply.";
console.log(JSON.stringify({
  write: riskOf({ tool: "fs", action: "write", tier: 1 }).level, move: riskOf({ tool: "fs", action: "move", tier: 2 }).level,
  external: riskOf({ tool: "x", action: "y", tier: 3 }).label, del: riskOf({ tool: "fs", action: "delete", tier: 4 }).level,
  cloud: riskOf({ tool: "egress", action: "claude", tier: 3 }).label, facts: egressLines(summary).k,
}));""", tmp_path)
    assert got["write"] == "routine" and got["move"] == "review" and got["del"] == "high"
    assert got["external"] == "External action" and got["cloud"] == "Data leaves this Mac"
    assert got["facts"] == ["Why: dashboard chat", "Provider's data use: Claude via your Claude Pro plan; consumer terms apply"]


def test_egress_summary_format_matches_what_the_card_parses():
    """The card reads the consent summary the egress gate writes; keep the two in step."""
    src = (Path(__file__).resolve().parents[1] / "src/jarvis/models/egress.py").read_text()
    assert '— purpose: {purpose}. Provider data use: {p.data_use_note}.' in src


def test_approve_and_reject_requests_are_unchanged():
    assert JS.count("act(`/api/approvals/${a.id}`, { approve: true })") == 1
    assert JS.count("act(`/api/approvals/${a.id}`, { approve: false })") == 1
    assert "/^\\/api\\/approvals\\/[\\w-]+$/" in JS  # still in the Face ID / Touch ID list


def test_pause_and_cancel_say_what_they_do_and_uncertain_steps_block_resume():
    card = _fn("missionCard")
    assert "Pause: stops after the current step. Nothing is undone; resume any time." in card
    assert "is not undone." in card and 'ok: "Cancel mission", danger: true' in card
    assert '["paused", "blocked"].includes(t.state) && !uncertain.length' in card  # no Resume the engine would refuse
    assert "JARVIS never repeats this automatically." in card
