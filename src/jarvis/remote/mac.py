"""Touch ID for the Mac dashboard.

Once a Touch ID passkey is set up, every sensitive dashboard action (the same list as the phone, plus
pairing a phone and adding or removing Touch ID keys) needs a fresh Touch ID bound to that exact request.
The dashboard cookie alone is no longer enough to approve anything.

The passkey's site is ``localhost`` (passkeys can't belong to a bare IP address), so the dashboard is
served at http://localhost:PORT. Recovery if Touch ID stops working: ``jarvis touchid reset --yes`` in
Terminal (audited).
"""

from __future__ import annotations

import secrets
from typing import Any

from .devices import DeviceError
from .passkeys import STEP_UP, PasskeyRP

MAC_STEP_UP = STEP_UP + (r"/api/devices/pair", r"/api/touchid/enroll/options", r"/api/touchid/[\w-]+/remove")


class MacKeys(PasskeyRP):
    kind = "mac"
    biometric = "Touch ID"

    def __init__(self, kernel, port: int):
        super().__init__(kernel, f"http://localhost:{port}")

    def enabled(self) -> bool:
        return bool(self.devices.active_credentials(self.kind))

    def keys(self) -> list[dict[str, Any]]:
        return [k for k in self.devices.list(self.kind) if not k["revoked_at"]]

    def enroll_options(self, name: str) -> dict[str, Any]:
        """Creation options for a new Touch ID key. The caller must already have required Touch ID if any
        key exists (the dashboard does this through MAC_STEP_UP)."""
        user_id = secrets.token_bytes(16)
        cid, challenge = self._issue(("enroll", name))
        return {"challengeId": cid,
                "publicKey": self._creation_options(challenge, user_id, "jarvis-mac", name[:60] or "This Mac")}

    def enroll_finish(self, challenge_id: str, name: str, credential: dict, *, by: str) -> str:
        reg = self._register(credential, self._take(challenge_id, ("enroll", name)))
        return self.devices.add_mac_key(name=name, credential_id=reg.credential_id,
                                        public_key_pem=reg.public_key_pem, sign_count=reg.sign_count, by=by)

    def remove(self, key_id: str, *, by: str) -> None:
        if key_id not in {k["id"] for k in self.keys()}:
            raise KeyError(key_id)
        self.devices.revoke(key_id, by=by)

    def _stepup_scope(self, device: dict | None) -> tuple[str, list[str]]:
        creds = self.devices.active_credentials(self.kind)
        if not creds:
            raise DeviceError("Touch ID isn't set up")
        return "mac", creds
