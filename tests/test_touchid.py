"""Touch ID on the Mac dashboard: once set up you sign in with it (per browser session, at most 12 hours); after that
ordinary approvals are one tap, and the dangerous few need a fresh Touch ID for that exact request."""

import json
import re

from soft_passkey import SoftPasskey
from test_dashboard import call, state


class MacBrowser:
    """The Mac dashboard in a browser with a Touch ID passkey (software stand-in, real signatures). It keeps the
    Touch ID sign-in cookie like a real browser does."""

    def __init__(self, d, passkey=None):
        self.d, self.origin = d, f"http://localhost:{d.port}"
        self.passkey = passkey or SoftPasskey("localhost")
        self.session = None

    def _cookie(self):
        return {"Cookie": "jarvis_session=test-token" + (f"; jarvis_touchid={self.session}" if self.session else "")}

    def _keep(self, headers):
        m = re.search(r"jarvis_touchid=([^;]+)", headers.get("Set-Cookie", ""))
        if m:
            self.session = m.group(1)

    def post(self, path, body):
        status, headers, raw = call(self.d, path, body, origin=self.origin, headers=self._cookie())
        self._keep(headers)
        return status, json.loads(raw)

    def get(self, path):
        status, _, raw = call(self.d, path, headers=self._cookie())
        return status, raw

    def state(self):
        status, raw = self.get("/api/state")
        assert status == 200, raw
        return json.loads(raw)

    def enroll(self, name="This Mac", passkey=None, extra=None):
        passkey = passkey or self.passkey
        status, opts = self.post("/api/touchid/enroll/options", {"name": name, **(extra or {})})
        assert status == 200, opts
        cred = passkey.create(opts["publicKey"]["challenge"], self.origin)
        return self.post("/api/touchid/enroll/finish", {"name": name, "challengeId": opts["challengeId"],
                                                       "credential": cred})

    def sign_in(self, passkey=None, **kw):
        status, opts = self.post("/api/touchid/signin/options", {})
        assert status == 200, opts
        return self.post("/api/touchid/signin", {"challengeId": opts["challengeId"],
                                                 "credential": (passkey or self.passkey).get(opts["challenge"], self.origin, **kw)})

    def touch_id(self, path, body, passkey=None, **kw):
        status, opts = self.post("/api/stepup/options", {"path": path, "body": body})
        assert status == 200, opts
        return {**body, "challengeId": opts["challengeId"],
                "assertion": (passkey or self.passkey).get(opts["challenge"], self.origin, **kw)}


def _pending(k, tier):
    from jarvis.core.permissions import Decision, Effect, Tier
    return k.approvals.request(task_id=None, step_id=None, tool="fs", action="write", digest=__import__("secrets").token_hex(32),
                               decision=Decision(Effect.CONFIRM, Tier(tier), "test", resource="/x"), summary=f"tier {tier}")


def test_off_by_default(dash):
    d, *_ = dash
    assert state(d)["touch_id"] == {"enabled": False, "keys": []}
    d.kernel.engine.emergency_stop(by="t", reason="t")
    assert call(d, "/api/release", {"confirm": True})[0] == 200  # unchanged until you set it up


def test_setting_up_signs_this_browser_in_and_others_must_sign_in(dash):
    d, *_ = dash
    mac = MacBrowser(d)
    status, _ = mac.enroll()
    assert status == 200 and mac.session and mac.state()["touch_id"]["enabled"] is True  # setting up = signed in
    # the dashboard link alone no longer opens the dashboard's data or actions...
    for path in ("/api/state", "/api/memory", "/api/projects"):
        status, _, raw = call(d, path)
        assert status == 401 and json.loads(raw)["error"] == "Touch ID sign-in required", path
    assert call(d, "/api/chat", {"message": "hi"})[0] == 401
    # ...but the page itself, its files and the emergency stop always work
    assert call(d, "/")[0] == 200 and call(d, "/static/app.js")[0] == 200
    assert call(d, "/api/stop", {"reason": "x"})[0] == 200 and d.kernel.killswitch.engaged() is True


def test_sign_in_flow(dash):
    d, *_ = dash
    key = SoftPasskey("localhost")
    MacBrowser(d, key).enroll()
    browser = MacBrowser(d, key)                                   # another browser: not signed in yet
    assert browser.get("/api/state")[0] == 401
    assert browser.sign_in(uv=False)[0] == 403                     # presence without user verification: no
    assert browser.sign_in(passkey=SoftPasskey("localhost"))[0] == 403   # an unknown key: no
    status, opts = browser.post("/api/touchid/signin/options", {})
    cred = key.get(opts["challenge"], browser.origin)
    assert browser.post("/api/touchid/signin", {"challengeId": opts["challengeId"], "credential": cred})[0] == 200
    assert browser.post("/api/touchid/signin", {"challengeId": opts["challengeId"], "credential": cred})[0] == 403  # single use
    assert browser.state()["touch_id"]["enabled"] is True
    assert any(e["event"] == "touchid.signin" for e in d.kernel.audit.entries())
    # sessions end: after 12 hours (simulated) the browser has to sign in again
    d.mac._sessions = {k: 0.0 for k in d.mac._sessions}
    assert browser.get("/api/state")[0] == 401


def test_signed_in_ordinary_approvals_are_one_tap_but_high_risk_needs_touch_id(dash):
    d, *_ = dash
    mac = MacBrowser(d)
    mac.enroll()
    low, high, other = _pending(d.kernel, 1), _pending(d.kernel, 4), _pending(d.kernel, 4)
    assert mac.post(f"/api/approvals/{low}", {"approve": True})[0] == 200          # one tap
    assert mac.post(f"/api/approvals/{high}", {"approve": True})[0] == 403         # high-risk: Touch ID again
    assert mac.post(f"/api/approvals/{high}", mac.touch_id(f"/api/approvals/{other}", {"approve": True}))[0] == 403
    assert d.kernel.approvals.get(high)["state"] == "pending"
    assert mac.post(f"/api/approvals/{high}", mac.touch_id(f"/api/approvals/{high}", {"approve": True}))[0] == 200
    assert mac.post(f"/api/approvals/{other}", {"approve": False})[0] == 200       # saying no is always one tap


def test_releasing_the_stop_needs_touch_id_bound_to_the_request(dash):
    d, *_ = dash
    mac = MacBrowser(d)
    mac.enroll()
    d.kernel.engine.emergency_stop(by="t", reason="t")
    assert mac.post("/api/release", {"confirm": True})[0] == 403                   # signed in isn't enough
    assert mac.post("/api/release", mac.touch_id("/api/release", {"confirm": True}, uv=False))[0] == 403
    signed = mac.touch_id("/api/release", {"confirm": False})
    assert mac.post("/api/release", {**signed, "confirm": True})[0] == 403             # body changed afterwards
    assert d.kernel.killswitch.engaged() is True
    signed = mac.touch_id("/api/release", {"confirm": True})
    assert mac.post("/api/release", signed)[0] == 200
    assert mac.post("/api/release", signed)[0] == 403                                  # single use
    events = [(e["actor"], e["event"]) for e in d.kernel.audit.entries()]
    assert ("user:dashboard", "touchid.added") in events and ("user:dashboard", "device.step_up") in events


def test_adding_and_removing_keys_need_touch_id(dash):
    d, *_ = dash
    mac = MacBrowser(d)
    mac.enroll()
    other = SoftPasskey("localhost")
    assert mac.post("/api/touchid/enroll/options", {"name": "Intruder"})[0] == 403
    status, _ = mac.enroll("Backup key", passkey=other,
                           extra={k: v for k, v in mac.touch_id("/api/touchid/enroll/options", {"name": "Backup key"})
                                  .items() if k in ("challengeId", "assertion")})
    assert status == 200 and len(mac.state()["touch_id"]["keys"]) == 2
    key = next(k["id"] for k in mac.state()["touch_id"]["keys"] if k["name"] == "Backup key")
    assert mac.post(f"/api/touchid/{key}/remove", {})[0] == 403
    assert mac.post(f"/api/touchid/{key}/remove", mac.touch_id(f"/api/touchid/{key}/remove", {}))[0] == 200
    assert [k["name"] for k in mac.state()["touch_id"]["keys"]] == ["This Mac"]


def test_enroll_challenge_bound_to_name_and_origin(dash):
    d, *_ = dash
    mac = MacBrowser(d)
    status, opts = mac.post("/api/touchid/enroll/options", {"name": "A"})
    cred = mac.passkey.create(opts["publicKey"]["challenge"], mac.origin)
    assert mac.post("/api/touchid/enroll/finish", {"name": "B", "challengeId": opts["challengeId"],
                                                   "credential": cred})[0] == 403
    status, opts = mac.post("/api/touchid/enroll/options", {"name": "A"})
    cred = mac.passkey.create(opts["publicKey"]["challenge"], "http://127.0.0.1:1")
    assert mac.post("/api/touchid/enroll/finish", {"name": "A", "challengeId": opts["challengeId"],
                                                   "credential": cred})[0] == 403
    assert state(d)["touch_id"]["enabled"] is False


def test_pairing_a_phone_needs_touch_id_when_on(dash):
    d, *_ = dash
    from jarvis.remote import RemoteAccess
    d.remote = RemoteAccess(d.kernel, "mac.tail1234.ts.net")
    mac = MacBrowser(d)
    mac.enroll()
    assert mac.post("/api/devices/pair", {})[0] == 403
    status, r = mac.post("/api/devices/pair", mac.touch_id("/api/devices/pair", {}))
    assert status == 200 and "pair=" in r["url"]


def test_phone_keys_and_mac_keys_dont_mix(dash):
    d, *_ = dash
    from jarvis.remote.devices import DeviceStore
    mac = MacBrowser(d)
    mac.enroll()
    # a phone passkey (registered for localhost, to isolate the "kind" check) can't confirm Mac actions
    store = DeviceStore(d.kernel.db, d.kernel.audit)
    phone = SoftPasskey("localhost")
    from jarvis.remote.webauthn import b64url_encode, public_key_pem
    store.finish_pairing(store.create_pairing(by="t"), name="p", credential_id=b64url_encode(phone.cred_id),
                         public_key_pem=public_key_pem(phone.key.public_key()), sign_count=0)
    d.kernel.engine.emergency_stop(by="t", reason="t")
    assert mac.post("/api/release", mac.touch_id("/api/release", {"confirm": True}, passkey=phone))[0] == 403
    assert d.kernel.killswitch.engaged() is True


def test_cli_list_and_reset(dash, capsys):
    d, *_ = dash
    from jarvis.cli import main as cli_main
    mac = MacBrowser(d)
    mac.enroll()
    home = str(d.kernel.home)
    assert cli_main(["--home", home, "touchid"]) == 0 and "This Mac" in capsys.readouterr().out
    assert cli_main(["--home", home, "touchid", "reset"]) == 1  # needs --yes
    assert mac.state()["touch_id"]["enabled"] is True and call(d, "/api/state")[0] == 401
    assert cli_main(["--home", home, "touchid", "reset", "--yes"]) == 0
    assert state(d)["touch_id"]["enabled"] is False
    assert any(e["event"] == "touchid.reset" for e in d.kernel.audit.entries())
