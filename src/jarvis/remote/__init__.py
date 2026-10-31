"""iPhone companion: reaching JARVIS from your phone over your private Tailscale network.

The dashboard still listens only on 127.0.0.1; `tailscale serve` forwards your tailnet's HTTPS
traffic to it. Requests arriving under the Tailscale hostname are "remote" and are handled here:
- pairing: a one-time code made on the Mac → a passkey (Face ID) created on the phone
- sign-in: passkey assertion → a device session cookie (Secure, HttpOnly, SameSite=Strict)
- step-up: sensitive actions need a fresh Face ID bound to exactly that request
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from .devices import DeviceError
from .mac import MacKeys
from .passkeys import STEP_UP, PasskeyRP
from .push import PUSH_HOSTS, Notifier, PushService
from .webauthn import WebAuthnError

# Never allowed from the phone (a stolen phone session must not be able to add devices).
LOCAL_ONLY = (r"/api/devices/pair", r"/api/touchid/.*")


class RemoteAccess(PasskeyRP):
    kind = "phone"
    biometric = "Face ID"

    def __init__(self, kernel, hostname: str, *, origin: str | None = None, push_hosts: tuple[str, ...] = PUSH_HOSTS,
                 push_opener=None):
        if not hostname:
            raise ValueError("remote access needs the Mac's Tailscale hostname")
        self.hostname = hostname.rstrip(".")
        super().__init__(kernel, origin or f"https://{self.hostname}")
        self.push = PushService(kernel.db, kernel.audit, kernel.home / "push-vapid.pem", hosts=push_hosts,
                                opener=push_opener)

    @property
    def hosts(self) -> set[str]:
        netloc = urlsplit(self.origin).netloc
        return {self.hostname, f"{self.hostname}:443", netloc}

    # ---- pairing --------------------------------------------------------------------------
    def pair_url(self, code: str) -> str:
        return f"{self.origin}/?pair={code}"

    def pairing_options(self, code: str, name: str) -> dict[str, Any]:
        challenge, user_id = self.devices.begin_pairing(code)
        return self._creation_options(challenge, user_id, "jarvis-owner", name[:60] or "iPhone")

    def pairing_finish(self, code: str, name: str, credential: dict) -> str:
        reg = self._register(credential, self.devices.pairing_challenge(code))
        device_id = self.devices.finish_pairing(code, name=name, credential_id=reg.credential_id,
                                                public_key_pem=reg.public_key_pem, sign_count=reg.sign_count)
        return self.devices.create_session(device_id)

    # ---- sign-in --------------------------------------------------------------------------
    def login_options(self) -> dict[str, Any]:
        creds = self.devices.active_credentials()
        if not creds:
            raise DeviceError("no phone is paired yet — pair it from the dashboard on your Mac")
        cid, challenge = self._issue(("login",))
        return self._request_options(cid, challenge, creds)

    def login_finish(self, challenge_id: str, credential: dict) -> str:
        stored = self._assert(credential, self._take(challenge_id, ("login",)))
        return self.devices.create_session(stored["id"])

    # ---- step-up: bound to the signed-in phone ------------------------------------------------
    def _stepup_scope(self, device: dict | None) -> tuple[str, list[str]]:
        if device is None:
            raise DeviceError("not signed in")
        return device["id"], [self.devices.get(device["id"])["credential_id"]]


__all__ = ["DeviceError", "LOCAL_ONLY", "MacKeys", "Notifier", "RemoteAccess", "STEP_UP", "WebAuthnError"]
