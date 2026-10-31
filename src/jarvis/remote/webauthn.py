"""Minimal WebAuthn (passkeys) relying-party verification for JARVIS's iPhone companion.

Supports exactly what we need: ES256 (P-256) credentials, "none" attestation (we trust the passkey
because you created it during pairing on a one-time code, not because of a vendor certificate), and
user verification required (Face ID / Touch ID / device passcode on every ceremony).

Checks performed (W3C WebAuthn Level 2 §7.1 / §7.2):
- clientDataJSON: type, challenge (exact, single-use), origin (exact)
- authenticatorData: RP ID hash == SHA-256(rp_id), User Present and User Verified flags
- registration: credential public key is EC2/P-256/ES256
- assertion: signature over authenticatorData || SHA-256(clientDataJSON) with the stored key;
  signature counter must increase when the authenticator uses one (clone detection)
"""

from __future__ import annotations

import base64
import hashlib
import json
import struct
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

FLAG_UP = 0x01
FLAG_UV = 0x04
FLAG_AT = 0x40


class WebAuthnError(ValueError):
    pass


def b64url_decode(text: str) -> bytes:
    if not isinstance(text, str):
        raise WebAuthnError("expected base64url text")
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (ValueError, TypeError):
        raise WebAuthnError("invalid base64url") from None


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


# ---- a small, strict CBOR decoder (only what WebAuthn uses) ----------------------------------
def cbor_decode(data: bytes) -> Any:
    value, end = _cbor(data, 0, depth=0)
    if end != len(data):
        raise WebAuthnError("trailing bytes after CBOR value")
    return value


def cbor_decode_prefix(data: bytes) -> tuple[Any, int]:
    """Decode one CBOR item from the start of ``data``; return (value, bytes consumed)."""
    return _cbor(data, 0, depth=0)


def _cbor(data: bytes, pos: int, depth: int) -> tuple[Any, int]:
    if depth > 16:
        raise WebAuthnError("CBOR nested too deeply")
    if pos >= len(data):
        raise WebAuthnError("truncated CBOR")
    initial = data[pos]
    major, info = initial >> 5, initial & 0x1F
    pos += 1
    if info < 24:
        arg = info
    elif info in (24, 25, 26, 27):
        size = 1 << (info - 24)
        if pos + size > len(data):
            raise WebAuthnError("truncated CBOR")
        arg = int.from_bytes(data[pos:pos + size], "big")
        pos += size
    else:
        raise WebAuthnError("unsupported CBOR encoding")
    if major == 0:
        return arg, pos
    if major == 1:
        return -1 - arg, pos
    if major in (2, 3):
        if pos + arg > len(data):
            raise WebAuthnError("truncated CBOR")
        raw = data[pos:pos + arg]
        return (raw if major == 2 else raw.decode("utf-8")), pos + arg
    if major == 4:
        if arg > 1024:
            raise WebAuthnError("CBOR array too long")
        items = []
        for _ in range(arg):
            item, pos = _cbor(data, pos, depth + 1)
            items.append(item)
        return items, pos
    if major == 5:
        if arg > 1024:
            raise WebAuthnError("CBOR map too long")
        out = {}
        for _ in range(arg):
            key, pos = _cbor(data, pos, depth + 1)
            val, pos = _cbor(data, pos, depth + 1)
            out[key] = val
        return out, pos
    if major == 7 and info in (20, 21, 22):
        return {20: False, 21: True, 22: None}[info], pos
    raise WebAuthnError("unsupported CBOR type")


# ---- authenticator data ------------------------------------------------------------------------
@dataclass(frozen=True)
class AuthData:
    rp_id_hash: bytes
    flags: int
    sign_count: int
    credential_id: bytes | None = None
    public_key: dict | None = None


def parse_auth_data(raw: bytes) -> AuthData:
    if len(raw) < 37:
        raise WebAuthnError("authenticator data too short")
    rp_hash, flags, count = raw[:32], raw[32], struct.unpack(">I", raw[33:37])[0]
    if not flags & FLAG_AT:
        return AuthData(rp_hash, flags, count)
    if len(raw) < 37 + 16 + 2:
        raise WebAuthnError("attested credential data truncated")
    pos = 37 + 16  # skip AAGUID
    cred_len = struct.unpack(">H", raw[pos:pos + 2])[0]
    pos += 2
    if cred_len > 1023 or pos + cred_len > len(raw):
        raise WebAuthnError("bad credential id length")
    cred_id = raw[pos:pos + cred_len]
    key, _ = cbor_decode_prefix(raw[pos + cred_len:])
    if not isinstance(key, dict):
        raise WebAuthnError("credential public key is not a COSE map")
    return AuthData(rp_hash, flags, count, cred_id, key)


def cose_to_public_key(cose: dict) -> ec.EllipticCurvePublicKey:
    # kty 2 = EC2, alg -7 = ES256, crv 1 = P-256, x = -2, y = -3
    if cose.get(1) != 2 or cose.get(3) != -7 or cose.get(-1) != 1:
        raise WebAuthnError("only ES256 (P-256) passkeys are supported")
    x, y = cose.get(-2), cose.get(-3)
    if not (isinstance(x, bytes) and isinstance(y, bytes) and len(x) == 32 and len(y) == 32):
        raise WebAuthnError("malformed EC public key")
    try:
        return ec.EllipticCurvePublicNumbers(int.from_bytes(x, "big"), int.from_bytes(y, "big"),
                                             ec.SECP256R1()).public_key()
    except ValueError:
        raise WebAuthnError("public key is not on the curve") from None


def public_key_pem(key: ec.EllipticCurvePublicKey) -> str:
    return key.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()


def load_public_key(pem: str) -> ec.EllipticCurvePublicKey:
    key = serialization.load_pem_public_key(pem.encode())
    if not isinstance(key, ec.EllipticCurvePublicKey):
        raise WebAuthnError("stored key is not an EC key")
    return key


# ---- ceremonies ----------------------------------------------------------------------------
def _client_data(raw_b64: str, *, expected_type: str, challenge: bytes, origin: str) -> bytes:
    raw = b64url_decode(raw_b64)
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise WebAuthnError("clientDataJSON is not JSON") from None
    if data.get("type") != expected_type:
        raise WebAuthnError(f"expected a {expected_type} ceremony")
    if data.get("challenge") != b64url_encode(challenge):
        raise WebAuthnError("challenge mismatch (stale or replayed request)")
    if data.get("origin") != origin:
        raise WebAuthnError("origin mismatch")
    if data.get("crossOrigin") is True:
        raise WebAuthnError("cross-origin ceremonies are not allowed")
    return raw


def _check_flags(auth: AuthData, rp_id: str) -> None:
    if auth.rp_id_hash != hashlib.sha256(rp_id.encode()).digest():
        raise WebAuthnError("passkey belongs to a different site")
    if not auth.flags & FLAG_UP:
        raise WebAuthnError("user presence missing")
    if not auth.flags & FLAG_UV:
        raise WebAuthnError("Face ID / device unlock was not performed")


@dataclass(frozen=True)
class Registration:
    credential_id: str  # base64url
    public_key_pem: str
    sign_count: int


def verify_registration(credential: dict, *, challenge: bytes, origin: str, rp_id: str) -> Registration:
    try:
        response = credential["response"]
        _client_data(response["clientDataJSON"], expected_type="webauthn.create", challenge=challenge, origin=origin)
        att = cbor_decode(b64url_decode(response["attestationObject"]))
    except (KeyError, TypeError):
        raise WebAuthnError("malformed registration response") from None
    if not isinstance(att, dict) or not isinstance(att.get("authData"), bytes):
        raise WebAuthnError("malformed attestation object")
    if att.get("fmt") != "none":
        # Other formats are fine to accept without checking certificates, but only if attStmt is ignored
        # consciously; we only ever request "none".
        if att.get("fmt") not in ("packed", "apple"):
            raise WebAuthnError(f"unsupported attestation format {att.get('fmt')!r}")
    auth = parse_auth_data(att["authData"])
    _check_flags(auth, rp_id)
    if auth.credential_id is None or auth.public_key is None:
        raise WebAuthnError("no credential in registration")
    if b64url_decode(credential.get("rawId", "")) != auth.credential_id:
        raise WebAuthnError("credential id mismatch")
    key = cose_to_public_key(auth.public_key)
    return Registration(b64url_encode(auth.credential_id), public_key_pem(key), auth.sign_count)


def verify_assertion(credential: dict, *, challenge: bytes, origin: str, rp_id: str, public_key_pem_text: str,
                     stored_sign_count: int) -> int:
    """Return the new signature counter. Raises WebAuthnError on any failure."""
    try:
        response = credential["response"]
        client_raw = _client_data(response["clientDataJSON"], expected_type="webauthn.get", challenge=challenge,
                                  origin=origin)
        auth_raw = b64url_decode(response["authenticatorData"])
        signature = b64url_decode(response["signature"])
    except (KeyError, TypeError):
        raise WebAuthnError("malformed assertion") from None
    auth = parse_auth_data(auth_raw)
    _check_flags(auth, rp_id)
    key = load_public_key(public_key_pem_text)
    try:
        key.verify(signature, auth_raw + hashlib.sha256(client_raw).digest(), ec.ECDSA(hashes.SHA256()))
    except InvalidSignature:
        raise WebAuthnError("signature is not valid") from None
    if (auth.sign_count or stored_sign_count) and auth.sign_count <= stored_sign_count:
        raise WebAuthnError("signature counter went backwards (possible cloned passkey)")
    return auth.sign_count
