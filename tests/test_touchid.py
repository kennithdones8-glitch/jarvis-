"""Touch ID on the Mac dashboard: once set up, sensitive actions need a fresh Touch ID for that exact request."""

import json


from soft_passkey import SoftPasskey
from test_dashboard import call, state


class MacBrowser:
    """The Mac dashboard in a browser with a Touch ID passkey (software stand-in, real signatures)."""

    def __init__(self, d):
        self.d, self.origin = d, f"http://localhost:{d.port}"
        self.passkey = SoftPasskey("localhost")

    def post(self, path, body):
        status, _, raw = call(self.d, path, body, origin=self.origin)
        return status, json.loads(raw)

    def enroll(self, name="This Mac", passkey=None, extra=None):
        passkey = passkey or self.passkey
        status, opts = self.post("/api/touchid/enroll/options", {"name": name, **(extra or {})})
        assert status == 200, opts
        cred = passkey.create(opts["publicKey"]["challenge"], self.origin)
        return self.post("/api/touchid/enroll/finish", {"name": name, "challengeId": opts["challengeId"],
                                                       "credential": cred})

    def touch_id(self, path, body, passkey=None, **kw):
        status, opts = self.post("/api/stepup/options", {"path": path, "body": body})
        assert status == 200, opts
        return {**body, "challengeId": opts["challengeId"],
                "assertion": (passkey or self.passkey).get(opts["challenge"], self.origin, **kw)}


def test_off_by_default(dash):
    d, *_ = dash
    assert state(d)["touch_id"] == {"enabled": False, "keys": []}
    d.kernel.engine.emergency_stop(by="t", reason="t")
    assert call(d, "/api/release", {"confirm": True})[0] == 200  # unchanged until you set it up


def test_setup_then_actions_need_touch_id(dash):
    d, *_ = dash
    mac = MacBrowser(d)
    status, r = mac.enroll()
    assert status == 200 and state(d)["touch_id"]["enabled"] is True
    d.kernel.engine.emergency_stop(by="t", reason="t")
    assert call(d, "/api/release", {"confirm": True})[0] == 403                       # cookie alone: no
    assert mac.post("/api/release", mac.touch_id("/api/release", {"confirm": True}, uv=False))[0] == 403
    signed = mac.touch_id("/api/release", {"confirm": False})
    assert mac.post("/api/release", {**signed, "confirm": True})[0] == 403             # body changed afterwards
    assert d.kernel.killswitch.engaged() is True
    signed = mac.touch_id("/api/release", {"confirm": True})
    assert mac.post("/api/release", signed)[0] == 200
    assert mac.post("/api/release", signed)[0] == 403                                  # single use
    assert call(d, "/api/stop", {"reason": "x"})[0] == 200                             # stopping never needs it
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
    assert status == 200 and len(state(d)["touch_id"]["keys"]) == 2
    key = next(k["id"] for k in state(d)["touch_id"]["keys"] if k["name"] == "Backup key")
    assert mac.post(f"/api/touchid/{key}/remove", {})[0] == 403
    assert mac.post(f"/api/touchid/{key}/remove", mac.touch_id(f"/api/touchid/{key}/remove", {}))[0] == 200
    assert [k["name"] for k in state(d)["touch_id"]["keys"]] == ["This Mac"]


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
    MacBrowser(d).enroll()
    home = str(d.kernel.home)
    assert cli_main(["--home", home, "touchid"]) == 0 and "This Mac" in capsys.readouterr().out
    assert cli_main(["--home", home, "touchid", "reset"]) == 1  # needs --yes
    assert state(d)["touch_id"]["enabled"] is True
    assert cli_main(["--home", home, "touchid", "reset", "--yes"]) == 0
    assert state(d)["touch_id"]["enabled"] is False
    assert any(e["event"] == "touchid.reset" for e in d.kernel.audit.entries())
