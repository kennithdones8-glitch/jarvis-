"""Paired devices (your iPhone), their sign-in sessions, and one-time pairing codes.

- Pairing codes are random, valid for 10 minutes, single use, and only their hash is stored.
- A paired device is a passkey (public key only; the private key never leaves the phone).
- Mac Touch ID keys (kind "mac") are stored here too; they never sign in a phone and have no sessions.
- Sessions are random tokens (stored hashed), expire after 12 hours idle or 30 days total, and are
  deleted the moment the device is revoked.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from typing import Any

from ..core.audit import AuditLog
from ..core.db import Database
from ..core.util import new_id, now_iso

PAIRING_TTL = 600
SESSION_IDLE = 12 * 3600
SESSION_MAX = 30 * 86400


class DeviceError(PermissionError):
    pass


def _h(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class DeviceStore:
    def __init__(self, db: Database, audit: AuditLog):
        self.db = db
        self.audit = audit

    # ---- pairing -------------------------------------------------------------------------
    def create_pairing(self, *, by: str) -> str:
        code = secrets.token_urlsafe(24)
        now = time.time()
        with self.db.tx() as c:
            c.execute("DELETE FROM pairings WHERE expires_at < ?", (now,))
            c.execute("INSERT INTO pairings (code_hash, created_at, expires_at) VALUES (?,?,?)",
                      (_h(code), now, now + PAIRING_TTL))
            self.audit.record("device.pairing_created", actor=by, expires_in_s=PAIRING_TTL)
        return code

    def _pairing(self, code: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM pairings WHERE code_hash = ?", (_h(str(code)),))
        if row is None or row["used_at"] is not None or row["expires_at"] < time.time():
            raise DeviceError("this pairing code is invalid, expired or already used — make a new one on the Mac")
        return dict(row)

    def begin_pairing(self, code: str) -> tuple[bytes, bytes]:
        """Return (challenge, user_id) for the passkey creation ceremony, remembered with the code."""
        self._pairing(code)
        challenge, user_id = secrets.token_bytes(32), secrets.token_bytes(16)
        with self.db.tx() as c:
            c.execute("UPDATE pairings SET challenge = ?, user_id = ? WHERE code_hash = ?",
                      (challenge.hex(), user_id.hex(), _h(code)))
        return challenge, user_id

    def pairing_challenge(self, code: str) -> bytes:
        p = self._pairing(code)
        if not p["challenge"]:
            raise DeviceError("pairing not started")
        return bytes.fromhex(p["challenge"])

    def finish_pairing(self, code: str, *, name: str, credential_id: str, public_key_pem: str, sign_count: int) -> str:
        with self.db.tx() as c:
            # single use, atomically: a second finish with the same code fails
            cur = c.execute("UPDATE pairings SET used_at = ? WHERE code_hash = ? AND used_at IS NULL AND expires_at >= ?",
                            (time.time(), _h(code), time.time()))
            if cur.rowcount != 1:
                raise DeviceError("this pairing code is invalid, expired or already used")
            did = new_id("dev")
            c.execute("INSERT INTO devices (id, name, credential_id, public_key, sign_count, created_at) VALUES (?,?,?,?,?,?)",
                      (did, name[:60] or "iPhone", credential_id, public_key_pem, sign_count, now_iso()))
            self.audit.record("device.paired", actor="user:phone", device_id=did)
        return did

    # ---- devices -------------------------------------------------------------------------
    def list(self, kind: str = "phone") -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.query(
            "SELECT id, name, kind, created_at, last_seen, revoked_at FROM devices WHERE kind = ? "
            "ORDER BY created_at DESC", (kind,))]

    def active_credentials(self, kind: str = "phone") -> list[str]:
        return [r["credential_id"] for r in self.db.query(
            "SELECT credential_id FROM devices WHERE revoked_at IS NULL AND kind = ?", (kind,))]

    def by_credential(self, credential_id: str, kind: str = "phone") -> dict[str, Any]:
        row = self.db.one("SELECT * FROM devices WHERE credential_id = ? AND revoked_at IS NULL AND kind = ?",
                          (credential_id, kind))
        if row is None:
            raise DeviceError("unknown or revoked device")
        return dict(row)

    def add_mac_key(self, *, name: str, credential_id: str, public_key_pem: str, sign_count: int, by: str) -> str:
        did = new_id("key")
        with self.db.tx() as c:
            c.execute("INSERT INTO devices (id, name, kind, credential_id, public_key, sign_count, created_at) "
                      "VALUES (?,?,?,?,?,?,?)",
                      (did, name[:60] or "This Mac", "mac", credential_id, public_key_pem, sign_count, now_iso()))
            self.audit.record("touchid.added", actor=by, key_id=did)
        return did

    def get(self, device_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM devices WHERE id = ?", (device_id,))
        if row is None:
            raise KeyError(device_id)
        return dict(row)

    def record_use(self, device_id: str, sign_count: int) -> None:
        with self.db.tx() as c:
            c.execute("UPDATE devices SET sign_count = ?, last_seen = ? WHERE id = ?", (sign_count, now_iso(), device_id))

    def revoke(self, device_id: str, *, by: str) -> None:
        with self.db.tx() as c:
            if c.execute("UPDATE devices SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
                         (now_iso(), device_id)).rowcount != 1:
                raise KeyError(device_id)
            c.execute("DELETE FROM device_sessions WHERE device_id = ?", (device_id,))
            c.execute("DELETE FROM push_subscriptions WHERE device_id = ?", (device_id,))
            self.audit.record("device.revoked", actor=by, device_id=device_id)

    def revoke_all(self, kind: str, *, by: str) -> int:
        ids = [r["id"] for r in self.db.query("SELECT id FROM devices WHERE kind = ? AND revoked_at IS NULL", (kind,))]
        for did in ids:
            self.revoke(did, by=by)
        return len(ids)

    # ---- sessions ------------------------------------------------------------------------
    def create_session(self, device_id: str) -> str:
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self.db.tx() as c:
            c.execute("DELETE FROM device_sessions WHERE expires_at < ?", (now,))
            c.execute("INSERT INTO device_sessions (token_hash, device_id, created_at, expires_at, last_seen) "
                      "VALUES (?,?,?,?,?)", (_h(token), device_id, now, now + SESSION_MAX, now))
            self.audit.record("device.signed_in", actor="user:phone", device_id=device_id)
        return token

    def session_device(self, token: str | None) -> dict[str, Any] | None:
        """The (non-revoked) device behind a session token, refreshing its idle timer; None if invalid."""
        if not token:
            return None
        now = time.time()
        row = self.db.one(
            "SELECT s.*, d.name, d.revoked_at FROM device_sessions s JOIN devices d ON d.id = s.device_id "
            "WHERE s.token_hash = ?", (_h(token),))
        if row is None or row["revoked_at"] or row["expires_at"] < now or now - row["last_seen"] > SESSION_IDLE:
            return None
        with self.db.tx() as c:
            c.execute("UPDATE device_sessions SET last_seen = ? WHERE token_hash = ?", (now, _h(token)))
        return {"id": row["device_id"], "name": row["name"]}

    def end_session(self, token: str) -> None:
        with self.db.tx() as c:
            c.execute("DELETE FROM device_sessions WHERE token_hash = ?", (_h(token),))
