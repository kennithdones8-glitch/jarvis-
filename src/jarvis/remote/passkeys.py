"""Passkey ceremonies shared by the iPhone companion (Face ID) and the Mac dashboard (Touch ID).

Challenges are random, single use, short-lived, kept in memory, and bound to a purpose. For step-up the
purpose includes a digest of the exact request (path + body), so a Face ID / Touch ID confirmation can't be
replayed or reused for a different action.
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
from .webauthn import b64url_encode, verify_assertion, verify_registration

CHALLENGE_TTL = 120
MAX_OUTSTANDING = 256  # sign-in challenges can be requested before sign-in; keep memory bounded

# Requests to these need a fresh passkey assertion bound to the exact request (path + body).
STEP_UP = (
    r"/api/approvals/[\w-]+",
    r"/api/release",
    r"/api/plan/\w+/run",
    r"/api/memory/[\w-]+/(delete|edit)",
    r"/api/memory/forget",
    r"/api/devices/[\w-]+/revoke",
)


class PasskeyRP:
    """A WebAuthn relying party for one origin and one kind of key ("phone" or "mac")."""

    kind = "phone"

    def __init__(self, kernel, origin: str):
        self.kernel = kernel
        self.origin = origin
        self.rp_id = urlsplit(origin).hostname
        self.devices = DeviceStore(kernel.db, kernel.audit)
        self._challenges: dict[str, tuple[bytes, float, tuple]] = {}
        self._lock = threading.Lock()

    # ---- challenges ------------------------------------------------------------------------
    def _issue(self, binding: tuple) -> tuple[str, bytes]:
        cid, challenge = secrets.token_urlsafe(16), secrets.token_bytes(32)
        now = time.time()
        with self._lock:
            self._challenges = {k: v for k, v in self._challenges.items() if v[1] > now}
            while len(self._challenges) >= MAX_OUTSTANDING:  # drop the oldest
                self._challenges.pop(next(iter(self._challenges)))
            self._challenges[cid] = (challenge, now + CHALLENGE_TTL, binding)
        return cid, challenge

    def _take(self, cid: Any, binding: tuple) -> bytes:
        with self._lock:
            entry = self._challenges.pop(str(cid), None)
        if entry is None or entry[1] < time.time() or entry[2] != binding:
            raise DeviceError("this confirmation expired or doesn't match — try again")
        return entry[0]

    # ---- ceremonies ------------------------------------------------------------------------
    def _register(self, credential: dict, challenge: bytes):
        return verify_registration(credential, challenge=challenge, origin=self.origin, rp_id=self.rp_id)

    def _assert(self, credential: dict, challenge: bytes, device: dict | None = None) -> dict:
        if not isinstance(credential, dict) or not isinstance(credential.get("id"), str):
            raise DeviceError("malformed passkey response")
        stored = self.devices.by_credential(credential["id"], kind=self.kind)
        if device is not None and stored["id"] != device["id"]:
            raise DeviceError("that passkey belongs to a different device")
        count = verify_assertion(credential, challenge=challenge, origin=self.origin, rp_id=self.rp_id,
                                 public_key_pem_text=stored["public_key"], stored_sign_count=stored["sign_count"])
        self.devices.record_use(stored["id"], count)
        return stored

    def _request_options(self, cid: str, challenge: bytes, credentials: list[str]) -> dict[str, Any]:
        return {"challengeId": cid, "challenge": b64url_encode(challenge), "rpId": self.rp_id, "timeout": 60000,
                "userVerification": "required",
                "allowCredentials": [{"type": "public-key", "id": c} for c in credentials]}

    def _creation_options(self, challenge: bytes, user_id: bytes, name: str, display: str) -> dict[str, Any]:
        return {"challenge": b64url_encode(challenge),
                "rp": {"id": self.rp_id, "name": "JARVIS"},
                "user": {"id": b64url_encode(user_id), "name": name, "displayName": display},
                "pubKeyCredParams": [{"type": "public-key", "alg": -7}],
                "authenticatorSelection": {"userVerification": "required", "residentKey": "preferred"},
                "excludeCredentials": [{"type": "public-key", "id": c}
                                       for c in self.devices.active_credentials(self.kind)],
                "attestation": "none", "timeout": 120000}

    # ---- step-up -----------------------------------------------------------------------------
    @staticmethod
    def request_digest(path: str, body: dict[str, Any]) -> str:
        clean = {k: v for k, v in body.items() if k not in ("assertion", "challengeId")}
        return hashlib.sha256(canonical_json({"path": path, "body": clean}).encode()).hexdigest()

    def _stepup_scope(self, device: dict | None) -> tuple[str, list[str]]:
        raise NotImplementedError

    def stepup_options(self, device: dict | None, path: str, body: dict[str, Any]) -> dict[str, Any]:
        scope, credentials = self._stepup_scope(device)
        cid, challenge = self._issue(("stepup", scope, self.request_digest(path, body)))
        return self._request_options(cid, challenge, credentials)

    def verify_stepup(self, device: dict | None, path: str, body: dict[str, Any], *, actor: str) -> None:
        """Raise unless ``body`` carries a fresh passkey assertion for exactly this path and body."""
        if not isinstance(body.get("assertion"), dict) or "challengeId" not in body:
            raise DeviceError(f"{self.biometric} is required for this action")
        scope, _ = self._stepup_scope(device)
        binding = ("stepup", scope, self.request_digest(path, body))
        stored = self._assert(body["assertion"], self._take(body["challengeId"], binding), device=device)
        self.kernel.audit.record("device.step_up", actor=actor, device_id=stored["id"], path=path)

    biometric = "Face ID"
