import json
import time
import urllib.error
import urllib.request

import pytest


from jarvis.server import Dashboard

from conftest import CFG  # noqa: E402,F401  (re-exported for other test modules)


def call(d, path, body=None, *, cookie=True, host=None, headers=None, origin=None):
    url = f"http://127.0.0.1:{d.port}{path}"
    h = {"Host": host or f"localhost:{d.port}"}
    if cookie:
        h["Cookie"] = "jarvis_session=test-token"
    if body is not None:
        h.update({"Content-Type": "application/json", "X-Requested-By": "jarvis"})
    if origin:
        h["Origin"] = origin
    h.update(headers or {})
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, headers=h,
                                 method="POST" if body is not None else "GET")
    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(req, timeout=10) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None


def wait_for(fn, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.05)
    raise AssertionError("condition not met in time")


def state(d):
    return json.loads(call(d, "/api/state")[2])


# ---- security ------------------------------------------------------------------------------
def test_requires_session(dash):
    d, *_ = dash
    assert call(d, "/api/state", cookie=False)[0] == 401
    assert call(d, "/static/app.js", cookie=False)[0] == 401
    status, _, body = call(d, "/", cookie=False)
    assert status == 401 and b"jarvis dashboard" in body


def test_token_link_sets_strict_httponly_cookie(dash):
    d, *_ = dash
    status, headers, _ = call(d, "/?token=test-token", cookie=False)
    assert status == 303 and headers["Location"] == "/"
    assert "HttpOnly" in headers["Set-Cookie"] and "SameSite=Strict" in headers["Set-Cookie"]
    assert call(d, "/?token=wrong", cookie=False)[0] == 401


def test_ip_address_redirects_to_localhost(dash):
    d, *_ = dash
    status, headers, _ = call(d, "/?token=test-token", cookie=False, host=f"127.0.0.1:{d.port}")
    assert status == 303 and headers["Location"] == f"http://localhost:{d.port}/?token=test-token"
    assert d.url.startswith(f"http://localhost:{d.port}/")
    assert call(d, "/api/state", host=f"127.0.0.1:{d.port}")[0] == 200  # the API still answers on the IP


def test_dns_rebinding_host_refused(dash):
    d, *_ = dash
    assert call(d, "/api/state", host=f"evil.example:{d.port}")[0] == 403


def test_csrf_defences(dash):
    d, *_ = dash
    assert call(d, "/api/stop", {"reason": "x"}, origin="https://evil.example")[0] == 403
    assert call(d, "/api/stop", {"reason": "x"}, headers={"X-Requested-By": "other"})[0] == 403
    assert d.kernel.killswitch.engaged() is False


def test_security_headers_and_static(dash):
    d, *_ = dash
    status, headers, body = call(d, "/")
    assert status == 200 and b"J.A.R.V.I.S." in body
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    assert headers["X-Frame-Options"] == "DENY"
    assert call(d, "/static/app.js")[0] == 200
    assert call(d, "/static/../app.py")[0] == 404


def test_only_loopback():
    with pytest.raises(ValueError):
        Dashboard.__init__(object.__new__(Dashboard), None, host="0.0.0.0")


# ---- real state & actions ------------------------------------------------------------------
def test_state_reflects_real_kernel(dash):
    d, *_ = dash
    s = state(d)
    assert s["tasks"] == [] and s["approvals"] == [] and s["emergency_stop"] is None
    assert s["models"]["providers"][0]["available"] == ["planner:7b"]
    assert s["audit_chain"]["ok"] is True


def test_chat(dash):
    d, *_ = dash
    status, _, body = call(d, "/api/chat", {"message": "hi", "history": [{"role": "user", "content": "x"}]})
    r = json.loads(body)
    assert status == 200 and r["text"] == "Hello, I am JARVIS." and r["model"] == "ollama/planner:7b"


def test_plan_run_approve_complete(dash):
    d, script, root = dash
    (root / "src.txt").write_text("source")
    script["plan"] = {"goal": "Copy", "question": None, "cannot": None, "steps": [
        {"description": "Read", "tool": "fs", "action": "read", "args": {"path": f"{root}/src.txt"}, "depends_on": []},
        {"description": "Save", "tool": "fs", "action": "write",
         "args": {"path": f"{root}/copy.md", "content": "copy of {{steps.0.content}}"}, "depends_on": [0]}]}
    job = json.loads(call(d, "/api/plan", {"request": "copy src"})[2])["job_id"]
    j = wait_for(lambda: next((x for x in state(d)["jobs"] if x["id"] == job and x["state"] == "ready"), None))
    assert j["kind"] == "plan" and len(j["steps"]) == 2 and not (root / "copy.md").exists()

    tid = json.loads(call(d, f"/api/plan/{job}/run", {})[2])["task_id"]
    appr = wait_for(lambda: state(d)["approvals"])[0]
    assert appr["preview"] == "copy of source" and appr["task_id"] == tid
    assert call(d, f"/api/approvals/{appr['id']}", {"approve": True})[0] == 200
    t = wait_for(lambda: next((t for t in state(d)["tasks"] if t["id"] == tid and t["state"] == "completed"), None))
    assert (root / "copy.md").read_text() == "copy of source"
    assert t["evidence"]["files"][0]["content_matches"] is True
    assert t["runner"] == "dashboard"
    # decisions are attributed to the dashboard user in the audit log
    assert any(e["actor"] == "user:dashboard" and e["event"] == "approval.approved" for e in d.kernel.audit.entries())
    assert call(d, f"/api/plan/{job}/run", {})[0] == 409  # a plan runs once


def test_dashboard_never_drives_cli_tasks(dash):
    d, _, root = dash
    from jarvis.core import StepSpec
    tid = d.kernel.tasks.create("cli task", steps=[StepSpec("r", "fs", "list", {"path": str(root)})],
                                context={"runner": "cli"})
    time.sleep(0.4)
    assert d.kernel.tasks.get(tid)["state"] == "queued"


def test_emergency_stop_and_release(dash):
    d, *_ = dash
    assert call(d, "/api/stop", {"reason": "test"})[0] == 200
    assert state(d)["emergency_stop"]["by"] == "user:dashboard"
    assert call(d, "/api/release", {})[0] == 409            # needs explicit confirm
    assert call(d, "/api/release", {"confirm": True})[0] == 200
    assert state(d)["emergency_stop"] is None


def test_bad_input_rejected(dash):
    d, *_ = dash
    assert call(d, "/api/chat", {"message": ""})[0] == 400
    assert call(d, "/api/approvals/nope", {"approve": "yes"})[0] == 400
    assert call(d, "/api/approvals/nope", {"approve": True})[0] == 409
    assert call(d, "/api/nothing", {})[0] == 404


def test_bad_content_length_refused_quickly(dash):
    import socket
    d, *_ = dash
    for value in ("-5", "abc"):
        with socket.create_connection(("127.0.0.1", d.port), timeout=5) as sock:
            sock.sendall((f"POST /api/stop HTTP/1.1\r\nHost: localhost:{d.port}\r\nCookie: jarvis_session=test-token\r\n"
                          f"X-Requested-By: jarvis\r\nContent-Length: {value}\r\n\r\n").encode())
            assert sock.recv(64).startswith(b"HTTP/1.0 400")  # answered at once, not left waiting
    assert d.kernel.killswitch.engaged() is False


def test_capabilities_drive_the_help_examples(dash):
    d, *_ = dash
    caps = state(d)["capabilities"]
    assert caps == {"mac_apps": False, "research": False, "voice": False}  # this test JARVIS has none of them
