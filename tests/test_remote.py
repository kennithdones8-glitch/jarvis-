"""iPhone companion: pairing, device sessions, Face ID step-up, remote routing and push."""

import io
import json
import re
import struct
import time
import urllib.error

import pytest

from model_servers import start_ollama
from soft_passkey import SoftPasskey
from test_dashboard import CFG, call, wait_for

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from jarvis.remote import RemoteAccess
from jarvis.remote.devices import DeviceError, DeviceStore
from jarvis.remote.push import Notifier, PushService, allowed_endpoint, encrypt
from jarvis.remote.webauthn import b64url_decode, b64url_encode
from jarvis.server import Dashboard
from jarvis.tools import default_registry

HOST = "mac.tail1234.ts.net"
ORIGIN = f"https://{HOST}"
PUSH_URL = "https://web.push.apple.com/QGdevice-token"


class FakePushService:
    """Stands in for Apple's push service: records what JARVIS sends, never touches the network."""

    def __init__(self):
        self.sent, self.status = [], 201

    def open(self, req, timeout=None):
        self.sent.append(req)
        if self.status >= 400:
            raise urllib.error.HTTPError(req.full_url, self.status, "gone", {}, io.BytesIO())

        class R:
            status = self.status

            def __enter__(s):
                return s

            def __exit__(s, *a):
                return False
        return R()


class Phone:
    """A paired iPhone talking to JARVIS over the tailnet (Host = the Tailscale name)."""

    def __init__(self, d):
        self.d, self.passkey, self.cookie = d, SoftPasskey(HOST), None

    def req(self, path, body=None, *, cookie=None, origin=ORIGIN):
        headers = {}
        token = self.cookie if cookie is None else cookie
        if token:
            headers["Cookie"] = f"jarvis_device={token}"
        status, h, raw = call(self.d, path, body, cookie=False, host=HOST, headers=headers,
                              origin=origin if body is not None else None)
        if m := re.match(r"jarvis_device=([^;]*)", h.get("Set-Cookie", "")):
            self.cookie = m.group(1) or None
        return status, h, (json.loads(raw) if h.get("Content-Type", "").startswith("application/json") else raw)

    def pair(self, url):
        code = url.split("pair=")[1]
        status, _, opts = self.req("/api/pair/options", {"code": code, "name": "Test iPhone"})
        assert status == 200, opts
        cred = self.passkey.create(opts["challenge"], ORIGIN)
        return self.req("/api/pair/finish", {"code": code, "name": "Test iPhone", "credential": cred})

    def login(self):
        _, _, opts = self.req("/api/login/options", {})
        return self.req("/api/login/finish", {"challengeId": opts["challengeId"],
                                              "credential": self.passkey.get(opts["challenge"], ORIGIN)})

    def face_id(self, path, body, **kw):
        status, _, opts = self.req("/api/stepup/options", {"path": path, "body": body})
        assert status == 200, opts
        return {**body, "challengeId": opts["challengeId"],
                "assertion": self.passkey.get(opts["challenge"], ORIGIN, **kw)}


@pytest.fixture
def remote_dash(make_kernel, tmp_path, root):
    server = start_ollama(installed=["planner:7b"])
    script = {"plan": None}
    server.reply = lambda body: (json.dumps(script["plan"]) if "planning component" in body["messages"][0]["content"]
                                 else "Hello, I am JARVIS.")
    (tmp_path / "jarvis.toml").write_text(CFG.format(url=server.url))
    k = make_kernel(registry=default_registry(tmp_path / "home"), config_path=tmp_path / "jarvis.toml")
    push = FakePushService()
    remote = RemoteAccess(k, HOST, push_opener=push)
    d = Dashboard(k, port=0, token="test-token", poll_s=0.05, remote=remote)
    d.notifier.min_interval_s = 0
    d.notifier.schedule.quiet_hours = ""  # tests must not depend on the time of day
    d.start()
    yield d, script, root, push
    d.shutdown()
    server.stop()


def paired(d):
    url = json.loads(call(d, "/api/devices/pair", {})[2])["url"]
    phone = Phone(d)
    status, headers, _ = phone.pair(url)
    assert status == 200
    return phone, headers


# ---- device store ---------------------------------------------------------------------------
def test_pairing_code_single_use_and_hashed(make_kernel):
    k = make_kernel()
    store = DeviceStore(k.db, k.audit)
    code = store.create_pairing(by="user:cli")
    assert k.db.one("SELECT COUNT(*) AS n FROM pairings WHERE code_hash = ?", (code,))["n"] == 0  # never stored raw
    store.begin_pairing(code)
    did = store.finish_pairing(code, name="iPhone", credential_id="cred", public_key_pem="pem", sign_count=0)
    with pytest.raises(DeviceError):
        store.finish_pairing(code, name="again", credential_id="cred2", public_key_pem="pem", sign_count=0)
    with pytest.raises(DeviceError):
        store.begin_pairing("not-a-code")
    assert [d["id"] for d in store.list()] == [did]


def test_pairing_code_expires(make_kernel):
    k = make_kernel()
    store = DeviceStore(k.db, k.audit)
    code = store.create_pairing(by="user:cli")
    with k.db.tx() as c:
        c.execute("UPDATE pairings SET expires_at = ?", (time.time() - 1,))
    with pytest.raises(DeviceError):
        store.begin_pairing(code)


def test_sessions_expire_and_die_with_revoke(make_kernel):
    k = make_kernel()
    store = DeviceStore(k.db, k.audit)
    code = store.create_pairing(by="user:cli")
    did = store.finish_pairing(code, name="iPhone", credential_id="cred", public_key_pem="pem", sign_count=0)
    token = store.create_session(did)
    assert store.session_device(token)["id"] == did
    assert store.session_device("forged") is None and store.session_device(None) is None
    assert k.db.one("SELECT COUNT(*) AS n FROM device_sessions WHERE token_hash = ?", (token,))["n"] == 0
    with k.db.tx() as c:  # idle too long
        c.execute("UPDATE device_sessions SET last_seen = ?", (time.time() - 13 * 3600,))
    assert store.session_device(token) is None
    token = store.create_session(did)
    store.revoke(did, by="user:cli")
    assert store.session_device(token) is None
    assert store.active_credentials() == []
    with pytest.raises(KeyError):
        store.revoke(did, by="user:cli")


# ---- remote routing -------------------------------------------------------------------------
def test_remote_disabled_rejects_tailnet_host(make_kernel, tmp_path):
    k = make_kernel()
    d = Dashboard(k, port=0, token="t")
    d.start()
    try:
        assert call(d, "/", host=HOST, cookie=False)[0] == 403
    finally:
        d.shutdown()


def test_remote_unpaired_sees_only_sign_in(remote_dash):
    d, *_ = remote_dash
    phone = Phone(d)
    status, _, body = phone.req("/")
    assert status == 200 and b"phone.js" in body and b"app.js" not in body
    assert phone.req("/api/state")[0] == 401
    assert phone.req("/static/app.js")[0] == 401
    assert phone.req("/api/stop", {"reason": "x"})[0] == 401
    assert phone.req("/manifest.webmanifest")[0] == 200 and phone.req("/sw.js")[0] == 200
    assert phone.req("/api/login/options", {})[0] == 403  # nothing paired yet


def test_dashboard_token_is_not_accepted_remotely(remote_dash):
    d, *_ = remote_dash
    status, _, _ = call(d, "/api/state", host=HOST)  # sends the Mac's dashboard cookie
    assert status == 401


def test_pair_sign_in_and_cookie(remote_dash):
    d, *_ = remote_dash
    phone, headers = paired(d)
    cookie = headers["Set-Cookie"]
    assert all(flag in cookie for flag in ("HttpOnly", "Secure", "SameSite=Strict"))
    status, _, body = phone.req("/")
    assert status == 200 and b"app.js" in body
    s = phone.req("/api/state")[2]
    assert s["remote"]["this_device"]["name"] == "Test iPhone" and len(s["remote"]["devices"]) == 1
    # sign out, then back in with Face ID
    assert phone.req("/api/logout", {})[0] == 200 and phone.cookie is None
    assert phone.req("/api/state")[0] == 401
    assert phone.login()[0] == 200
    assert phone.req("/api/state")[0] == 200
    events = [e["event"] for e in d.kernel.audit.entries()]
    assert "device.paired" in events and events.count("device.signed_in") == 2


def test_pairing_is_mac_only_and_code_single_use(remote_dash):
    d, *_ = remote_dash
    url = json.loads(call(d, "/api/devices/pair", {})[2])["url"]
    assert url.startswith(f"{ORIGIN}/?pair=")
    phone = Phone(d)
    assert phone.pair(url)[0] == 200
    assert phone.req("/api/devices/pair", {})[0] == 403  # a phone can't add more phones
    assert phone.req("/api/touchid/enroll/options", {"name": "x"})[0] == 403  # nor touch the Mac's Touch ID keys
    thief = Phone(d)
    assert thief.req("/api/pair/options", {"code": url.split("pair=")[1], "name": "x"})[0] == 403


def test_remote_csrf_and_wrong_origin(remote_dash):
    d, *_ = remote_dash
    phone, _ = paired(d)
    assert phone.req("/api/stop", {"reason": "x"}, origin="https://evil.example")[0] == 403
    assert phone.req("/api/stop", {"reason": "x"}, origin=f"http://127.0.0.1:{d.port}")[0] == 403
    assert d.kernel.killswitch.engaged() is False
    assert phone.req("/api/stop", {"reason": "from phone"})[0] == 200  # stopping never needs Face ID
    assert d.kernel.killswitch.engaged() is True


def test_passkey_from_wrong_site_rejected(remote_dash):
    d, *_ = remote_dash
    url = json.loads(call(d, "/api/devices/pair", {})[2])["url"]
    phone = Phone(d)
    code = url.split("pair=")[1]
    opts = phone.req("/api/pair/options", {"code": code, "name": "x"})[2]
    bad = phone.passkey.create(opts["challenge"], "https://evil.example")
    assert phone.req("/api/pair/finish", {"code": code, "name": "x", "credential": bad})[0] == 403
    assert any(e["event"] == "device.denied" for e in d.kernel.audit.entries())


# ---- Face ID step-up ------------------------------------------------------------------------
def test_release_needs_face_id_bound_to_exact_request(remote_dash):
    d, *_ = remote_dash
    phone, _ = paired(d)
    d.kernel.engine.emergency_stop(by="user:cli", reason="t")
    assert phone.req("/api/release", {"confirm": True})[0] == 403  # no Face ID
    signed = phone.face_id("/api/release", {"confirm": True}, uv=False)
    assert phone.req("/api/release", signed)[0] == 403  # passcode-less presence isn't enough
    signed = phone.face_id("/api/release", {"confirm": False})
    assert phone.req("/api/release", {**signed, "confirm": True})[0] == 403  # body swapped after Face ID
    signed = phone.face_id("/api/stop", {"confirm": True})
    assert phone.req("/api/release", signed)[0] == 403  # signed for a different path
    assert d.kernel.killswitch.engaged() is True
    signed = phone.face_id("/api/release", {"confirm": True})
    assert phone.req("/api/release", signed)[0] == 200
    assert phone.req("/api/release", signed)[0] == 403  # a Face ID approval is single use
    assert d.kernel.killswitch.engaged() is False
    assert any(e["event"] == "device.step_up" for e in d.kernel.audit.entries())


def test_approve_from_phone_with_face_id(remote_dash):
    d, script, root, push = remote_dash
    phone, _ = paired(d)
    keys = _browser_subscription()
    assert phone.req("/api/push/subscribe", {"subscription": keys["sub"]})[0] == 200
    (root / "src.txt").write_text("source")
    script["plan"] = {"goal": "Copy", "question": None, "cannot": None, "steps": [
        {"description": "Read", "tool": "fs", "action": "read", "args": {"path": f"{root}/src.txt"}, "depends_on": []},
        {"description": "Save", "tool": "fs", "action": "write",
         "args": {"path": f"{root}/copy.md", "content": "copy of {{steps.0.content}}"}, "depends_on": [0]}]}
    job = phone.req("/api/plan", {"request": "copy src"})[2]["job_id"]
    wait_for(lambda: next((x for x in phone.req("/api/state")[2]["jobs"] if x["state"] == "ready"), None))
    assert phone.req(f"/api/plan/{job}/run", {})[0] == 403
    tid = phone.req(f"/api/plan/{job}/run", phone.face_id(f"/api/plan/{job}/run", {}))[2]["task_id"]
    appr = wait_for(lambda: phone.req("/api/state")[2]["approvals"])[0]
    # the notification arrives, with generic wording only
    msg = wait_for(lambda: [_decrypt(r, keys) for r in push.sent if b"decision" in _decrypt(r, keys)])[0]
    assert json.loads(msg) == {"title": "JARVIS", "body": "JARVIS needs a decision", "tag": "approval",
                               "url": "/"}
    path = f"/api/approvals/{appr['id']}"
    assert phone.req(path, {"approve": True})[0] == 403
    assert phone.req(path, phone.face_id(path, {"approve": True}))[0] == 200
    wait_for(lambda: d.kernel.tasks.get(tid)["state"] == "completed")
    assert (root / "copy.md").read_text() == "copy of source"
    assert any(e["actor"] == "user:phone:Test iPhone" and e["event"] == "approval.approved"
               for e in d.kernel.audit.entries())


def test_revoke_from_mac_ends_phone_session(remote_dash):
    d, *_ = remote_dash
    phone, _ = paired(d)
    did = phone.req("/api/state")[2]["remote"]["this_device"]["id"]
    assert call(d, f"/api/devices/{did}/revoke", {})[0] == 200
    assert phone.req("/api/state")[0] == 401
    assert phone.req("/api/login/options", {})[0] == 403  # its passkey no longer opens JARVIS


# ---- push ---------------------------------------------------------------------------------
def _browser_subscription():
    ua = ec.generate_private_key(ec.SECP256R1())
    raw = ua.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    auth = b"0123456789abcdef"
    return {"ua": ua, "auth": auth,
            "sub": {"endpoint": PUSH_URL, "keys": {"p256dh": b64url_encode(raw), "auth": b64url_encode(auth)}}}


def _decrypt(req, keys) -> bytes:
    """What the iPhone does on receipt (RFC 8291) — proves only the phone can read the payload."""
    data = req.data
    salt, rs, idlen = data[:16], struct.unpack(">I", data[16:20])[0], data[20]
    as_raw, body = data[21:21 + idlen], data[21 + idlen:]
    assert rs == 4096
    ua_raw = b64url_decode(keys["sub"]["keys"]["p256dh"])
    shared = keys["ua"].exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_raw))

    def hkdf(s, ikm, info, n):
        return HKDF(algorithm=hashes.SHA256(), length=n, salt=s, info=info).derive(ikm)
    ikm = hkdf(keys["auth"], shared, b"WebPush: info\x00" + ua_raw + as_raw, 32)
    plain = AESGCM(hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)).decrypt(
        hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12), body, None)
    return plain.rstrip(b"\x00")[:-1]


def test_rfc8291_vector():
    # RFC 8291 §5
    ua_priv = ec.derive_private_key(int.from_bytes(b64url_decode("q1dXpw3UpT5VOmu_cf_v6ih07Aems3njxI-JWgLcM94"), "big"),
                                    ec.SECP256R1())
    as_priv = ec.derive_private_key(int.from_bytes(b64url_decode("yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"), "big"),
                                    ec.SECP256R1())
    ua_pub = b64url_encode(ua_priv.public_key().public_bytes(serialization.Encoding.X962,
                                                            serialization.PublicFormat.UncompressedPoint))
    out = encrypt(b"When I grow up, I want to be a watermelon", ua_pub, "BTBZMqHH6r4Tts7J_aSIgg",
                  salt=b64url_decode("DGv6ra1nlYgDCS1FRnbzlw"), as_private=as_priv)
    assert b64url_encode(out) == (
        "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A_"
        "yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN")


def test_push_endpoint_allowlist(make_kernel, tmp_path):
    k = make_kernel()
    push = PushService(k.db, k.audit, tmp_path / "vapid.pem", opener=FakePushService())
    keys = _browser_subscription()["sub"]["keys"]
    for bad in ("http://web.push.apple.com/x", "https://evil.example/x", "https://web.push.apple.com.evil.example/x",
                "https://127.0.0.1/x"):
        assert not allowed_endpoint(bad)
        with pytest.raises(Exception):
            push.subscribe("dev", {"endpoint": bad, "keys": keys})
    assert allowed_endpoint(PUSH_URL) and allowed_endpoint("https://api.push.apple.com/x")
    with pytest.raises(Exception):
        push.subscribe("dev", {"endpoint": PUSH_URL, "keys": {"p256dh": "short", "auth": "x"}})
    assert (tmp_path / "vapid.pem").stat().st_mode & 0o777 == 0o600


def test_push_send_signs_and_drops_gone_subscriptions(make_kernel, tmp_path):
    k = make_kernel()
    store = DeviceStore(k.db, k.audit)
    did = store.finish_pairing(store.create_pairing(by="t"), name="p", credential_id="c", public_key_pem="x",
                               sign_count=0)
    fake = FakePushService()
    push = PushService(k.db, k.audit, tmp_path / "vapid.pem", opener=fake)
    keys = _browser_subscription()
    push.subscribe(did, keys["sub"])
    assert push.send("JARVIS", "A task finished", tag="finished") == 1
    req = fake.sent[0]
    assert req.headers["Content-encoding"] == "aes128gcm"
    assert req.headers["Authorization"].startswith("vapid t=") and push.public_key in req.headers["Authorization"]
    assert json.loads(_decrypt(req, keys))["body"] == "A task finished"
    fake.status = 410
    assert push.send("JARVIS", "x") == 0
    assert push.subscriptions() == []


def test_notifier_batches_and_seeds(make_kernel, root):
    k = make_kernel()
    sent = []

    class P:
        def send(self, title, body, *, tag):
            sent.append((tag, body))
    from jarvis.core import StepSpec
    (root / "input.txt").write_text("x")
    k.tasks.create("old", steps=[StepSpec("r", "fs", "read", {"path": f"{root}/input.txt"})])
    from jarvis.proactive import Schedule
    n = Notifier(k, P(), min_interval_s=3600, schedule=Schedule(quiet_hours=""))
    assert n.poll() == [] and sent == []  # existing state isn't announced after a restart
    t1 = k.tasks.create("a", steps=[StepSpec("r", "fs", "read", {"path": f"{root}/input.txt"})])
    k.engine.run(t1)
    assert n.poll() == ["finished"]
    t2 = k.tasks.create("b", steps=[StepSpec("r", "fs", "read", {"path": f"{root}/input.txt"})])
    k.engine.run(t2)
    assert n.poll() == []  # rate-limited
    assert sent == [("finished", "A task finished")]


# ---- CLI ----------------------------------------------------------------------------------
def test_cli_remote_enable_status_disable(tmp_path, monkeypatch, capsys):
    from jarvis.cli import main as cli_main
    from jarvis.core import Kernel
    calls = tmp_path / "calls.txt"
    fake = tmp_path / "bin" / "tailscale"
    fake.parent.mkdir()
    fake.write_text(f"""#!/bin/sh
echo "$@" >> {calls}
if [ "$1" = status ]; then
  echo '{{"BackendState": "Running", "Self": {{"DNSName": "{HOST}."}}}}'
fi
""")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake.parent}:/usr/bin:/bin")
    home = tmp_path / "home"
    assert cli_main(["--home", str(home), "init"]) == 0
    assert cli_main(["--home", str(home), "remote", "enable"]) == 0
    assert "serve --bg --https=443 http://127.0.0.1:8765" in calls.read_text()
    assert "funnel" not in calls.read_text()  # never published to the internet
    k = Kernel(home)
    try:
        assert k.model_config.remote == {"enabled": True, "hostname": HOST}
    finally:
        k.close()
    capsys.readouterr()
    assert cli_main(["--home", str(home), "remote", "status"]) == 0
    assert f"https://{HOST}" in capsys.readouterr().out
    assert cli_main(["--home", str(home), "remote", "enable"]) == 0  # idempotent: one [remote] section
    assert (home / "jarvis.toml").read_text().count("[remote]") == 1
    assert cli_main(["--home", str(home), "remote", "disable"]) == 0
    assert "serve --https=443 off" in calls.read_text()
    k = Kernel(home)
    try:
        assert k.model_config.remote["enabled"] is False
        store = DeviceStore(k.db, k.audit)
        did = store.finish_pairing(store.create_pairing(by="t"), name="p", credential_id="c", public_key_pem="x",
                                   sign_count=0)
    finally:
        k.close()
    assert cli_main(["--home", str(home), "devices"]) == 0
    assert did in capsys.readouterr().out
    assert cli_main(["--home", str(home), "devices", "revoke", did]) == 0


def test_cli_remote_without_tailscale(tmp_path, monkeypatch, capsys):
    from jarvis.cli import main as cli_main
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr("jarvis.remote.tailscale.APP_CLI", str(tmp_path / "nope"))
    assert cli_main(["--home", str(tmp_path / "home"), "remote", "enable"]) == 1
    assert "isn't installed" in capsys.readouterr().err


def test_push_failures_are_recorded_not_silent(make_kernel, tmp_path):
    k = make_kernel()
    store = DeviceStore(k.db, k.audit)
    did = store.finish_pairing(store.create_pairing(by="t"), name="p", credential_id="c", public_key_pem="x",
                               sign_count=0)

    class Broken:
        def open(self, req, timeout=None):
            raise urllib.error.URLError(ssl_error())

    def ssl_error():
        import ssl
        return ssl.SSLCertVerificationError("certificate verify failed")
    push = PushService(k.db, k.audit, tmp_path / "vapid.pem", opener=Broken())
    push.subscribe(did, _browser_subscription()["sub"])
    assert push.send("JARVIS", "x") == 0
    entry = [e for e in k.audit.entries() if e["event"] == "push.sent"][-1]
    assert entry["payload"]["errors"] == ["SSLCertVerificationError"]
    assert push.subscriptions()  # a temporary failure keeps the subscription


def test_vapid_subject_is_one_apple_accepts(make_kernel):
    from jarvis.remote.push import PushError, vapid_header, vapid_subject
    for bad in ("mailto:jarvis@localhost", "https://localhost", "mailto:me@mac.local", "jarvis", "http://example.com"):
        with pytest.raises(PushError):
            vapid_subject(bad)
    k = make_kernel()
    remote = RemoteAccess(k, HOST)
    assert remote.push.subject == f"https://{HOST}"  # JARVIS's own address, never the owner's email
    header = vapid_header(PUSH_URL, remote.push.key, subject=remote.push.subject)
    claims = json.loads(b64url_decode(header.split("t=")[1].split(".")[1]))
    assert claims["sub"] == f"https://{HOST}" and claims["aud"] == "https://web.push.apple.com"


def test_device_names_cleaned(make_kernel):
    k = make_kernel()
    store = DeviceStore(k.db, k.audit)
    did = store.finish_pairing(store.create_pairing(by="t"), name="Ken's\niPhone\x1b[31m  " + "x" * 80,
                               credential_id="c", public_key_pem="x", sign_count=0)
    name = store.get(did)["name"]
    assert "\n" not in name and "\x1b" not in name and len(name) == 60 and name.startswith("Ken's iPhone [31m")


def test_unauthenticated_challenges_are_bounded(make_kernel):
    from jarvis.remote.passkeys import MAX_OUTSTANDING
    k = make_kernel()
    remote = RemoteAccess(k, HOST)
    store = remote.devices
    store.finish_pairing(store.create_pairing(by="t"), name="p", credential_id="c", public_key_pem="x", sign_count=0)
    first = remote.login_options()["challengeId"]
    for _ in range(MAX_OUTSTANDING + 50):
        remote.login_options()
    assert len(remote._challenges) == MAX_OUTSTANDING
    with pytest.raises(DeviceError):  # the oldest was dropped
        remote._take(first, ("login",))
