"""A software passkey (real P-256 keys, real signatures) that produces WebAuthn responses exactly as a
browser/iPhone would, so the relying-party code is exercised for real. Used only by tests."""

import hashlib
import json
import os
import struct

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from jarvis.remote.webauthn import FLAG_AT, FLAG_UP, FLAG_UV, b64url_encode


def _cbor(value) -> bytes:
    def head(major, n):
        if n < 24:
            return bytes([major << 5 | n])
        for size, code in ((1, 24), (2, 25), (4, 26), (8, 27)):
            if n < 1 << (8 * size):
                return bytes([major << 5 | code]) + n.to_bytes(size, "big")
    if isinstance(value, bool) or value is None:
        return bytes([0xF5 if value is True else 0xF4 if value is False else 0xF6])
    if isinstance(value, int):
        return head(0, value) if value >= 0 else head(1, -1 - value)
    if isinstance(value, bytes):
        return head(2, len(value)) + value
    if isinstance(value, str):
        b = value.encode()
        return head(3, len(b)) + b
    if isinstance(value, list):
        return head(4, len(value)) + b"".join(_cbor(v) for v in value)
    if isinstance(value, dict):
        return head(5, len(value)) + b"".join(_cbor(k) + _cbor(v) for k, v in value.items())
    raise TypeError(value)


class SoftPasskey:
    def __init__(self, rp_id: str):
        self.rp_id = rp_id
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.cred_id = os.urandom(16)
        self.counter = 0

    def _auth_data(self, flags, attested=False, rp_id=None):
        self.counter += 1
        data = hashlib.sha256((rp_id or self.rp_id).encode()).digest() + bytes([flags]) + struct.pack(">I", self.counter)
        if attested:
            nums = self.key.public_key().public_numbers()
            cose = {1: 2, 3: -7, -1: 1, -2: nums.x.to_bytes(32, "big"), -3: nums.y.to_bytes(32, "big")}
            data += b"\0" * 16 + struct.pack(">H", len(self.cred_id)) + self.cred_id + _cbor(cose)
        return data

    @staticmethod
    def _client(kind, challenge_b64, origin):
        return json.dumps({"type": kind, "challenge": challenge_b64, "origin": origin, "crossOrigin": False}).encode()

    def create(self, challenge_b64: str, origin: str, *, uv=True, rp_id=None):
        flags = FLAG_UP | FLAG_AT | (FLAG_UV if uv else 0)
        att = _cbor({"fmt": "none", "attStmt": {}, "authData": self._auth_data(flags, True, rp_id)})
        return {"id": b64url_encode(self.cred_id), "rawId": b64url_encode(self.cred_id), "type": "public-key",
                "response": {"clientDataJSON": b64url_encode(self._client("webauthn.create", challenge_b64, origin)),
                             "attestationObject": b64url_encode(att)}}

    def get(self, challenge_b64: str, origin: str, *, uv=True, rp_id=None, counter=None):
        if counter is not None:
            self.counter = counter - 1
        auth = self._auth_data(FLAG_UP | (FLAG_UV if uv else 0), rp_id=rp_id)
        client = self._client("webauthn.get", challenge_b64, origin)
        sig = self.key.sign(auth + hashlib.sha256(client).digest(), ec.ECDSA(hashes.SHA256()))
        return {"id": b64url_encode(self.cred_id), "rawId": b64url_encode(self.cred_id), "type": "public-key",
                "response": {"clientDataJSON": b64url_encode(client), "authenticatorData": b64url_encode(auth),
                             "signature": b64url_encode(sig), "userHandle": None}}
