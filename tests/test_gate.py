"""The release gate itself: security items are pass/fail gates that nothing can outweigh, and the gate fails closed
(a failing, skipped, renamed or deleted covering test fails it). Runs on synthetic results; the real end-to-end
run is `jarvis gate`, which can't run inside the suite it runs."""

import re
from pathlib import Path

from jarvis import gate

TESTS = Path(__file__).parent


def junit(cases):
    rows = []
    for key, status in cases.items():
        module, name = key.split("::")
        inner = {"failed": "<failure message='x'/>", "skipped": "<skipped message='x'/>", "passed": ""}[status]
        rows.append(f'<testcase classname="tests.{module}" name="test_{name}">{inner}</testcase>')
    return f"<testsuites><testsuite>{''.join(rows)}</testsuite></testsuites>"


def all_passing():
    every = {t for _, tests in gate.SECURITY.values() for t in tests}
    return {t: "passed" for t in every} | {s: "skipped" for s in gate.ALLOWED_SKIPS} | {"test_extra::unrelated": "passed"}


def test_everything_green_passes():
    r = gate.evaluate(gate.parse_junit(junit(all_passing())), lint_ok=True)
    assert r.passed and all(i.passed for i in r.items)


def test_one_failing_security_test_fails_its_item_and_the_gate():
    cases = all_passing() | {"test_permissions::path_traversal_denied": "failed"}
    r = gate.evaluate(gate.parse_junit(junit(cases)), lint_ok=True)
    bad = [i for i in r.items if not i.passed]
    assert not r.passed and [i.name for i in bad] == ["Permission bypass"]
    assert "path_traversal_denied" in bad[0].detail


def test_skipped_or_missing_security_tests_fail_closed():
    skipped = all_passing() | {"test_stop::stop_kills_running_claude_and_its_children": "skipped"}
    assert not gate.evaluate(gate.parse_junit(junit(skipped)), lint_ok=True).passed
    missing = dict(all_passing())
    missing.pop("test_models::budget_guard_blocks_and_records")
    r = gate.evaluate(gate.parse_junit(junit(missing)), lint_ok=True)
    assert not r.passed and "no longer exist" in next(i for i in r.items if i.name == "Budget guard (protected)").detail


def test_security_failures_cant_be_outweighed_and_other_failures_count_too():
    other = all_passing() | {"test_extra::unrelated": "failed"}
    r = gate.evaluate(gate.parse_junit(junit(other)), lint_ok=True)
    assert not r.passed and all(i.passed for i in r.items) and r.suite["failed"] == ["test_extra::unrelated"]
    assert not gate.evaluate(gate.parse_junit(junit(all_passing())), lint_ok=False).passed
    stray_skip = all_passing() | {"test_extra::quietly_skipped": "skipped"}
    assert not gate.evaluate(gate.parse_junit(junit(stray_skip)), lint_ok=True).passed
    assert not gate.evaluate({}, lint_ok=True).passed  # no results at all is a failure, not a pass


def test_parametrized_case_failing_fails_the_function():
    xml = ('<testsuites><testsuite><testcase classname="tests.test_mac" name="test_x[a]"/>'
           '<testcase classname="tests.test_mac" name="test_x[b]"><failure/></testcase></testsuite></testsuites>')
    assert gate.parse_junit(xml) == {"test_mac::x": "failed"}


def test_every_listed_test_really_exists():
    """Renaming a test without updating the gate would otherwise fail every run; catch it here, by name."""
    defined = {f"{p.stem}::{m}" for p in TESTS.glob("test_*.py")
               for m in re.findall(r"^def test_(\w+)", p.read_text(), re.M)}
    listed = {t for _, tests in gate.SECURITY.values() for t in tests} | gate.ALLOWED_SKIPS
    assert listed - defined == set()


def test_refuses_outside_a_repository(tmp_path):
    import pytest
    with pytest.raises(RuntimeError, match="from the JARVIS repository"):
        gate.run(root=tmp_path)
