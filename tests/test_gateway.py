import pytest

from helpers import build_registry

from jarvis.core.approvals import ApprovalStateError
from jarvis.core.killswitch import EmergencyStop
from jarvis.core.tools import ApprovalRequired, PermissionDenied, ToolError, ToolTimeout


def test_unknown_tool_denied(make_kernel):
    k = make_kernel()
    with pytest.raises(PermissionDenied):
        k.gateway.invoke("shell", "run", {"cmd": "rm -rf /"})
    with pytest.raises(PermissionDenied):
        k.gateway.invoke("fs", "chmod", {"path": "x"})


def test_allowed_write_executes_for_real(make_kernel, root):
    k = make_kernel()
    k.gateway.invoke("fs", "write", {"path": f"{root}/notes/a.md", "content": "hello"})
    assert (root / "notes" / "a.md").read_text() == "hello"


def test_confirm_flow_is_bound_to_exact_args_and_single_use(make_kernel, root):
    k = make_kernel()
    args = {"path": f"{root}/plan.md", "content": "v1"}
    with pytest.raises(ApprovalRequired) as ei:
        k.gateway.invoke("fs", "write", args, task_id="t1")
    assert not (root / "plan.md").exists()
    k.approvals.decide(ei.value.approval_id, approve=True, by="user:test")

    # Different content is NOT covered by the approval.
    with pytest.raises(ApprovalRequired):
        k.gateway.invoke("fs", "write", {**args, "content": "v2-malicious"}, task_id="t1")
    k.gateway.invoke("fs", "write", args, task_id="t1")
    assert (root / "plan.md").read_text() == "v1"
    # Single use: a second identical write needs approval again.
    with pytest.raises(ApprovalRequired):
        k.gateway.invoke("fs", "write", args, task_id="t1")


def test_only_user_can_decide_approvals(make_kernel, root):
    k = make_kernel()
    with pytest.raises(ApprovalRequired) as ei:
        k.gateway.invoke("fs", "write", {"path": f"{root}/x", "content": "c"}, task_id="t1")
    with pytest.raises(PermissionError):
        k.approvals.decide(ei.value.approval_id, approve=True, by="model")
    k.approvals.decide(ei.value.approval_id, approve=False, by="user:test")
    with pytest.raises(ApprovalStateError):
        k.approvals.decide(ei.value.approval_id, approve=True, by="user:test")


def test_rejection_cannot_be_bypassed_with_another_tool(make_kernel, root):
    k = make_kernel()
    target = f"{root}/report.md"
    with pytest.raises(ApprovalRequired) as ei:
        k.gateway.invoke("fs", "write", {"path": target, "content": "x"}, task_id="t1")
    k.approvals.decide(ei.value.approval_id, approve=False, by="user:test")
    with pytest.raises(PermissionDenied, match="rejected"):
        k.gateway.invoke("fs", "write", {"path": target, "content": "different"}, task_id="t1")
    with pytest.raises(PermissionDenied, match="rejected"):
        k.gateway.invoke("fs", "append", {"path": target, "line": "sneaky"}, task_id="t1")
    assert not (root / "report.md").exists()


def test_external_action_always_confirms_despite_allow_rule(make_kernel):
    calls = []
    k = make_kernel(registry=build_registry(calls))
    with pytest.raises(ApprovalRequired):
        k.gateway.invoke("net", "post", {"url": "https://example.org/hook", "body": "hi"}, task_id="t1")
    assert calls == []


def test_emergency_stop_blocks_everything(make_kernel, root):
    k = make_kernel()
    k.killswitch.engage(by="user:test", reason="test")
    with pytest.raises(EmergencyStop):
        k.gateway.invoke("fs", "read", {"path": f"{root}/x"})
    with pytest.raises(ValueError):
        k.killswitch.release(by="user:test", confirm=False)
    with pytest.raises(PermissionError):
        k.killswitch.release(by="model", confirm=True)
    k.killswitch.release(by="user:test", confirm=True)
    (root / "x").write_text("ok")
    assert k.gateway.invoke("fs", "read", {"path": f"{root}/x"}) == {"content": "ok"}


def test_timeout_and_output_limit(make_kernel):
    k = make_kernel(registry=build_registry(timeout_s=0.2))
    with pytest.raises(ToolTimeout):
        k.gateway.invoke("test", "slow", {"seconds": 1})
    with pytest.raises(ToolError, match="output exceeded"):
        k.gateway.invoke("test", "big", {})


def test_unexpected_exception_is_wrapped_as_outcome_unknown(make_kernel):
    k = make_kernel()
    with pytest.raises(ToolError) as ei:
        k.gateway.invoke("test", "boom", {})
    assert ei.value.outcome_unknown and not ei.value.retryable


def test_audit_records_checks_without_bulk_content_or_secrets(make_kernel, root):
    k = make_kernel()
    body = "private text " * 100
    k.gateway.invoke("fs", "write", {"path": f"{root}/notes/n.md", "content": body, "api_key": "sk-" + "z" * 30})
    events = [e["event"] for e in k.audit.entries()]
    assert events[-3:] == ["permission.check", "tool.start", "tool.result"]
    start = next(e for e in k.audit.entries() if e["event"] == "tool.start")
    assert start["payload"]["args"]["content"]["chars"] == len(body)
    assert start["payload"]["args"]["api_key"] == "[REDACTED]"
    assert k.audit.verify().ok
