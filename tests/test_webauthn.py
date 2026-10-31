import os

import pytest

from soft_passkey import SoftPasskey

from jarvis.remote.webauthn import WebAuthnError, b64url_encode, cbor_decode, verify_assertion, verify_registration

RP = "kenniths-mbp.tail1234.ts.net"
ORIGIN = f"https://{RP}"


def challenge():
    raw = os.urandom(32)
    return raw, b64url_encode(raw)


def registered():
    pk = SoftPasskey(RP)
    raw, b64 = challenge()
    reg = verify_registration(pk.create(b64, ORIGIN), challenge=raw, origin=ORIGIN, rp_id=RP)
    return pk, reg


def test_registration_and_assertion_round_trip():
    pk, reg = registered()
    raw, b64 = challenge()
    count = verify_assertion(pk.get(b64, ORIGIN), challenge=raw, origin=ORIGIN, rp_id=RP,
                             public_key_pem_text=reg.public_key_pem, stored_sign_count=reg.sign_count)
    assert count == reg.sign_count + 1 and reg.public_key_pem.startswith("-----BEGIN PUBLIC KEY")


@pytest.mark.parametrize("mutate,match", [
    (lambda pk, b64: pk.create(b64, "https://evil.example"), "origin"),
    (lambda pk, b64: pk.create(b64, ORIGIN, rp_id="evil.example"), "different site"),
    (lambda pk, b64: pk.create(b64, ORIGIN, uv=False), "Face ID"),
    (lambda pk, b64: pk.create(b64_other(), ORIGIN), "challenge"),
])
def test_registration_rejections(mutate, match):
    pk = SoftPasskey(RP)
    raw, b64 = challenge()
    with pytest.raises(WebAuthnError, match=match):
        verify_registration(mutate(pk, b64), challenge=raw, origin=ORIGIN, rp_id=RP)


def b64_other():
    return challenge()[1]


def test_assertion_rejections():
    pk, reg = registered()
    raw, b64 = challenge()
    kw = dict(challenge=raw, origin=ORIGIN, rp_id=RP, public_key_pem_text=reg.public_key_pem, stored_sign_count=5)
    with pytest.raises(WebAuthnError, match="Face ID"):
        verify_assertion(pk.get(b64, ORIGIN, uv=False, counter=10), **kw)
    with pytest.raises(WebAuthnError, match="origin"):
        verify_assertion(pk.get(b64, "https://evil.example", counter=11), **kw)
    with pytest.raises(WebAuthnError, match="challenge"):
        verify_assertion(pk.get(b64_other(), ORIGIN, counter=12), **kw)
    with pytest.raises(WebAuthnError, match="backwards"):
        verify_assertion(pk.get(b64, ORIGIN, counter=5), **kw)               # replayed / cloned counter
    other = SoftPasskey(RP)                                                    # someone else's passkey
    with pytest.raises(WebAuthnError, match="signature"):
        verify_assertion(other.get(b64, ORIGIN, counter=20), **kw)
    tampered = pk.get(b64, ORIGIN, counter=30)
    tampered["response"]["clientDataJSON"] = b64url_encode(b'{"type":"webauthn.get","challenge":"' + b64.encode()
                                                           + b'","origin":"' + ORIGIN.encode() + b'","x":1}')
    with pytest.raises(WebAuthnError, match="signature"):
        verify_assertion(tampered, **kw)
    assert verify_assertion(pk.get(b64, ORIGIN, counter=40), **kw) == 40       # a genuine one still works


def test_cbor_rejects_garbage():
    for bad in (b"", b"\xa1", b"\x5f", b"\xa1\x01"):
        with pytest.raises(WebAuthnError):
            cbor_decode(bad)
    assert cbor_decode(b"\xa2\x01\x02\x20\x43abc") == {1: 2, -1: b"abc"}
