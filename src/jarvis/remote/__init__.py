"""iPhone companion: reaching JARVIS from your phone over your private Tailscale network.

The dashboard still listens only on 127.0.0.1; `tailscale serve` forwards your tailnet's HTTPS
traffic to it. Requests arriving under the Tailscale hostname are "remote" and are handled here:
- pairing: a one-time code made on the Mac → a passkey (Face ID) created on the phone
- sign-in: passkey assertion → a device session cookie (Secure, HttpOnly, SameSite=Strict)
- step-up: sensitive actions need a fresh Face ID bound to exactly that request
"""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
from typing import Any
from urllib.parse import urlsplit

from ..core.util import canonical_json
from .devices import DeviceError, DeviceStore
from .push import PUSH_HOSTS, Notifier, PushService
from .webauthn import WebAuthnError, b64url_encode, verify_assertion, verify_registration

CHALLENGE_TTL = 120

# Remote requests to these need a fresh Face ID bound to the exact request (path + body).
STEP_UP = (
    r"/api/approvals/[\w-]+",
    r"/api/release",
    r"/api/plan/\w+/run",
    r"/api/memory/[\w-]+/(delete|edit)",
    r"/api/memory/forget",
    r"/api/devices/[\w-]+/revoke",
)
# Never allowed from the phone (a stolen phone session must not be able to add devices).
LOCAL_ONLY = (r"/api/devices/pair",)


class RemoteAccess:
    def __init__(self, kernel, hostname: str, *, origin: str | None = None, push_hosts: tuple[str, ...] = PUSH_HOSTS,
                 push_opener=None):
        if not hostname:
            raise ValueError("remote access needs the Mac's Tailscale hostname")
        self.kernel = kernel
        self.hostname = hostname.rstrip(".")
        self.origin = origin or f"https://{self.hostname}"
        self.rp_id = urlsplit(self.origin).hostname
        self.devices = DeviceStore(kernel.db, kernel.audit)
        self.push = PushService(kernel.db, kernel.audit, kernel.home / "push-vapid.pem", hosts=push_hosts,
                                opener=push_opener)
        self._challenges: dict[str, tuple[bytes, float, tuple]] = {}
        self._lock = threading.Lock()

    @property
    def hosts(self) -> set[str]:
        netloc = urlsplit(self.origin).netloc
        return {self.hostname, f"{self.hostname}:443", netloc}

    # ---- challenges (single use, short-lived, bound to a purpose) ---------------------------
    def _issue(self, binding: tuple) -> tuple[str, bytes]:
        cid, challenge = secrets.token_urlsafe(16), secrets.token_bytes(32)
        now = time.time()
        with self._lock:
            self._challenges = {k: v for k, v in self._challenges.items() if v[1] > now}
            self._challenges[cid] = (challenge, now + CHALLENGE_TTL, binding)
        return cid, challenge

    def _take(self, cid: Any, binding: tuple) -> bytes:
        with self._lock:
            entry = self._challenges.pop(str(cid), None)
        if entry is None or entry[1] < time.time() or entry[2] != binding:
            raise DeviceError("this Face ID request expired or doesn't match — try again")
        return entry[0]

    # ---- pairing --------------------------------------------------------------------------
    def pair_url(self, code: str) -> str:
        return f"{self.origin}/?pair={code}"

    def pairing_options(self, code: str, name: str) -> dict[str, Any]:
        challenge, user_id = self.devices.begin_pairing(code)
        return {"challenge": b64url_encode(challenge),
                "rp": {"id": self.rp_id, "name": "JARVIS"},
                "user": {"id": b64url_encode(user_id), "name": "jarvis-owner", "displayName": name[:60] or "iPhone"},
                "pubKeyCredParams": [{"type": "public-key", "alg": -7}],
                "authenticatorSelection": {"userVerification": "required", "residentKey": "preferred"},
                "excludeCredentials": [{"type": "public-key", "id": c} for c in self.devices.active_credentials()],
                "attestation": "none", "timeout": 120000}

    def pairing_finish(self, code: str, name: str, credential: dict) -> str:
        reg = verify_registration(credential, challenge=self.devices.pairing_challenge(code), origin=self.origin,
                                  rp_id=self.rp_id)
        device_id = self.devices.finish_pairing(code, name=name, credential_id=reg.credential_id,
                                                public_key_pem=reg.public_key_pem, sign_count=reg.sign_count)
        return self.devices.create_session(device_id)

    # ---- sign-in --------------------------------------------------------------------------
    def login_options(self) -> dict[str, Any]:
        creds = self.devices.active_credentials()
        if not creds:
            raise DeviceError("no phone is paired yet — pair it from the dashboard on your Mac")
        cid, challenge = self._issue(("login",))
        return {"challengeId": cid, "challenge": b64url_encode(challenge), "rpId": self.rp_id, "timeout": 60000,
                "userVerification": "required", "allowCredentials": [{"type": "public-key", "id": c} for c in creds]}

    def _assert(self, credential: dict, challenge: bytes, device: dict | None = None) -> dict:
        if not isinstance(credential, dict) or not isinstance(credential.get("id"), str):
            raise DeviceError("malformed Face ID response")
        stored = self.devices.by_credential(credential["id"])
        if device is not None and stored["id"] != device["id"]:
            raise DeviceError("that passkey belongs to a different device")
        count = verify_assertion(credential, challenge=challenge, origin=self.origin, rp_id=self.rp_id,
                                 public_key_pem_text=stored["public_key"], stored_sign_count=stored["sign_count"])
        self.devices.record_use(stored["id"], count)
        return stored

    def login_finish(self, challenge_id: str, credential: dict) -> str:
        stored = self._assert(credential, self._take(challenge_id, ("login",)))
        return self.devices.create_session(stored["id"])

    # ---- step-up for sensitive actions --------------------------------------------------------
    @staticmethod
    def _request_digest(path: str, body: dict[str, Any]) -> str:
        clean = {k: v for k, v in body.items() if k not in ("assertion", "challengeId")}
        return hashlib.sha256(canonical_json({"path": path, "body": clean}).encode()).hexdigest()

    def stepup_options(self, device: dict, path: str, body: dict[str, Any]) -> dict[str, Any]:
        stored = self.devices.get(device["id"])
        cid, challenge = self._issue(("stepup", device["id"], self._request_digest(path, body)))
        return {"challengeId": cid, "challenge": b64url_encode(challenge), "rpId": self.rp_id, "timeout": 60000,
                "userVerification": "required",
                "allowCredentials": [{"type": "public-key", "id": stored["credential_id"]}]}

    def verify_stepup(self, device: dict, path: str, body: dict[str, Any]) -> None:
        """Raise unless ``body`` carries a fresh Face ID assertion for exactly this path and body."""
        if not isinstance(body.get("assertion"), dict) or "challengeId" not in body:
            raise DeviceError("Face ID is required for this action")
        binding = ("stepup", device["id"], self._request_digest(path, body))
        self._assert(body["assertion"], self._take(body["challengeId"], binding), device=device)
        self.kernel.audit.record("device.step_up", actor=f"user:phone:{device['name']}", device_id=device["id"],
                                 path=path)


__all__ = ["DeviceError", "LOCAL_ONLY", "Notifier", "RemoteAccess", "STEP_UP", "WebAuthnError"]
