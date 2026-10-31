"""Web Push notifications to the paired iPhone (iOS 16.4+, JARVIS added to the Home Screen).

- Payloads are encrypted for the phone alone (RFC 8291, aes128gcm) and signed with JARVIS's VAPID key
  (RFC 8292). The push service (Apple) can't read them.
- Payloads never contain your content — only generic wording ("JARVIS needs a decision"). Details
  appear after you open the app and sign in with Face ID. Lock-screen previews stay private.
- Only https endpoints on known push services are ever contacted (no arbitrary URLs).
"""

from __future__ import annotations

import json
import os
import struct
import time
import urllib.error
from datetime import datetime
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from ..core.audit import AuditLog
from ..core.db import Database
from ..core.tls import client_context
from ..core.util import new_id, now_iso
from .webauthn import b64url_decode, b64url_encode

PUSH_HOSTS = ("web.push.apple.com", ".push.apple.com", "fcm.googleapis.com", "updates.push.services.mozilla.com",
              ".notify.windows.com")
RECORD_SIZE = 4096


class PushError(RuntimeError):
    pass


def _hkdf(salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(ikm)


def _raw_public(key: ec.EllipticCurvePublicKey) -> bytes:
    return key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def encrypt(payload: bytes, ua_public_b64: str, auth_secret_b64: str, *, salt: bytes | None = None,
            as_private: ec.EllipticCurvePrivateKey | None = None) -> bytes:
    """RFC 8291 message encryption (single aes128gcm record)."""
    ua_raw = b64url_decode(ua_public_b64)
    auth = b64url_decode(auth_secret_b64)
    if len(ua_raw) != 65 or len(auth) != 16:
        raise PushError("malformed subscription keys")
    ua_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_raw)
    as_private = as_private or ec.generate_private_key(ec.SECP256R1())
    as_raw = _raw_public(as_private.public_key())
    salt = salt or os.urandom(16)
    shared = as_private.exchange(ec.ECDH(), ua_key)
    ikm = _hkdf(auth, shared, b"WebPush: info\x00" + ua_raw + as_raw, 32)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    if len(payload) > RECORD_SIZE - 17 - 86:
        raise PushError("payload too large")
    body = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)
    return salt + struct.pack(">I", RECORD_SIZE) + bytes([len(as_raw)]) + as_raw + body


def load_or_create_vapid(path: Path) -> ec.EllipticCurvePrivateKey:
    if path.exists():
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
        if isinstance(key, ec.EllipticCurvePrivateKey):
            return key
    key = ec.generate_private_key(ec.SECP256R1())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
    path.chmod(0o600)
    return key


def vapid_subject(subject: str) -> str:
    """Apple's push service rejects (BadJwtToken) a subject that isn't a mailto: or https: URL with a real
    domain; localhost / .local / bare names fail. JARVIS uses its own Tailscale address, never your email."""
    parts = urlsplit(subject)
    host = (parts.hostname or subject.partition("@")[2]).lower()
    if parts.scheme not in ("https", "mailto") or not host or "." not in host or host == "localhost" \
            or host.endswith((".local", ".localhost")):
        raise PushError(f"push subject {subject!r} would be rejected by Apple's push service")
    return subject


def vapid_header(endpoint: str, key: ec.EllipticCurvePrivateKey, *, subject: str,
                 now: float | None = None) -> str:
    parts = urlsplit(endpoint)
    claims = {"aud": f"{parts.scheme}://{parts.netloc}", "exp": int((now or time.time()) + 12 * 3600),
              "sub": vapid_subject(subject)}
    signing_input = (b64url_encode(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode()) + "."
                     + b64url_encode(json.dumps(claims, separators=(",", ":")).encode()))
    r, s = decode_dss_signature(key.sign(signing_input.encode(), ec.ECDSA(hashes.SHA256())))
    jwt = signing_input + "." + b64url_encode(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
    return f"vapid t={jwt}, k={b64url_encode(_raw_public(key.public_key()))}"


def allowed_endpoint(endpoint: str, hosts: tuple[str, ...] = PUSH_HOSTS) -> bool:
    parts = urlsplit(endpoint)
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and any(host == h or (h.startswith(".") and host.endswith(h)) for h in hosts)


class PushService:
    def __init__(self, db: Database, audit: AuditLog, key_path: Path, *, hosts: tuple[str, ...] = PUSH_HOSTS,
                 opener=None, subject: str = "https://jarvis.invalid"):
        self.db = db
        self.audit = audit
        self.key = load_or_create_vapid(key_path)
        self.hosts = hosts
        self.subject = subject
        self.opener = opener or urllib.request.build_opener(urllib.request.HTTPSHandler(context=client_context()))

    @property
    def public_key(self) -> str:
        """The applicationServerKey the phone subscribes with."""
        return b64url_encode(_raw_public(self.key.public_key()))

    def subscribe(self, device_id: str, sub: dict[str, Any]) -> str:
        endpoint = sub.get("endpoint")
        keys = sub.get("keys") or {}
        if not isinstance(endpoint, str) or not allowed_endpoint(endpoint, self.hosts):
            raise PushError("not a recognised push service")
        encrypt(b"probe", keys.get("p256dh", ""), keys.get("auth", ""))  # validates the keys
        sid = new_id("push")
        with self.db.tx() as c:
            c.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))
            c.execute("INSERT INTO push_subscriptions (id, device_id, endpoint, p256dh, auth, created_at) "
                      "VALUES (?,?,?,?,?,?)", (sid, device_id, endpoint, keys["p256dh"], keys["auth"], now_iso()))
            self.audit.record("push.subscribed", device_id=device_id)
        return sid

    def subscriptions(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.query(
            "SELECT p.* FROM push_subscriptions p JOIN devices d ON d.id = p.device_id WHERE d.revoked_at IS NULL")]

    def send(self, title: str, body: str, *, tag: str = "jarvis", url: str = "/") -> int:
        """Send a generic notification to every paired, non-revoked device. Returns how many accepted."""
        if not url.startswith("/") or url.startswith("//"):
            raise PushError("notifications only open JARVIS's own pages")
        payload = json.dumps({"title": title, "body": body, "tag": tag, "url": url}).encode()
        delivered, errors = 0, []
        for sub in self.subscriptions():
            if not allowed_endpoint(sub["endpoint"], self.hosts):
                continue
            data = encrypt(payload, sub["p256dh"], sub["auth"])
            req = urllib.request.Request(sub["endpoint"], data=data, method="POST", headers={
                "Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream", "TTL": "86400",
                "Urgency": "high", "Authorization": vapid_header(sub["endpoint"], self.key, subject=self.subject)})
            try:
                with self.opener.open(req, timeout=10) as resp:
                    delivered += resp.status in (200, 201, 202)
            except urllib.error.HTTPError as exc:
                if exc.code in (404, 410):  # the phone unsubscribed or reinstalled the app
                    with self.db.tx() as c:
                        c.execute("DELETE FROM push_subscriptions WHERE id = ?", (sub["id"],))
                else:
                    errors.append(f"HTTP {exc.code}")
            except OSError as exc:  # e.g. offline, or HTTPS certificate problems
                reason = getattr(exc, "reason", exc)
                errors.append(type(reason).__name__ if not isinstance(reason, str) else reason[:60])
        self.audit.record("push.sent", tag=tag, devices=delivered, **({"errors": errors[:3]} if errors else {}))
        return delivered


class Notifier:
    """Turns JARVIS state changes into a few generic notifications (batched, never content).

    Quiet hours hold everything back except the morning briefing; what happened overnight is in the briefing.
    """

    def __init__(self, kernel, push: PushService, *, min_interval_s: float = 20.0, schedule=None):
        from ..proactive import Schedule

        self.kernel = kernel
        self.push = push
        self.min_interval_s = min_interval_s
        self.schedule = schedule or Schedule.from_config(kernel.model_config.proactive)
        self._last_sent: dict[str, float] = {}
        self._seen_approvals = {a["id"] for a in kernel.approvals.pending()}
        self._reminded: set[str] = set(self._seen_approvals)  # don't nag about ones from before a restart
        self._task_states = {t["id"]: t["state"] for t in kernel.tasks.list(limit=100)}

    def _quiet(self, now: datetime | None) -> bool:
        return self.schedule.quiet(now or datetime.now().astimezone())

    def poll(self, now: datetime | None = None) -> list[str]:
        sent: list[str] = []
        quiet = self._quiet(now)
        approvals = self.kernel.approvals.pending()
        pending = {a["id"] for a in approvals}
        new = pending - self._seen_approvals
        self._seen_approvals |= pending
        if new and not quiet and self._may_send("approval"):
            n = len(pending)
            self.push.send("JARVIS", "JARVIS needs a decision" if n == 1 else f"JARVIS needs {n} decisions",
                           tag="approval")
            sent.append("approval")
        cutoff = (now or datetime.now().astimezone()).timestamp() - self.schedule.approval_reminder_min * 60
        waiting = [a["id"] for a in approvals if a["id"] not in self._reminded and _ts(a["created_at"]) < cutoff]
        if waiting and not quiet and self._may_send("reminder"):
            self._reminded |= set(waiting)
            self.push.send("JARVIS", "A decision is still waiting for you", tag="approval")
            sent.append("reminder")
        finished = attention = 0
        for t in self.kernel.tasks.list(limit=100):
            before = self._task_states.get(t["id"])
            if before != t["state"]:
                if t["state"] == "completed":
                    finished += 1
                elif t["state"] in ("failed", "blocked"):
                    attention += 1
            self._task_states[t["id"]] = t["state"]
        if quiet:
            return sent
        if attention and self._may_send("attention"):
            self.push.send("JARVIS", "A task needs your attention", tag="attention")
            sent.append("attention")
        elif finished and self._may_send("finished"):
            self.push.send("JARVIS", "A task finished" if finished == 1 else f"{finished} tasks finished", tag="finished")
            sent.append("finished")
        return sent

    def health_changed(self, ok: bool, now: datetime | None = None) -> bool:
        if ok or self._quiet(now) or not self._may_send("health"):
            return False
        self.push.send("JARVIS", "Something on your Mac needs attention", tag="health")
        return True

    def briefing_ready(self) -> None:
        self.push.send("JARVIS", "Your morning briefing is ready", tag="briefing", url="/#briefing")

    def _may_send(self, kind: str) -> bool:
        now = time.monotonic()
        if now - self._last_sent.get(kind, -1e9) < self.min_interval_s:
            return False
        self._last_sent[kind] = now
        return True


def _ts(iso: str) -> float:
    try:
        return datetime.fromisoformat(iso).timestamp()
    except (TypeError, ValueError):
        return time.time()
