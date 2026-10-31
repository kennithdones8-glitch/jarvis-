"""HTTPS trust for JARVIS's own connections (Web Push to Apple, web fetch, `jarvis doctor`).

Some Python builds (including ones uv installs) don't find the operating system's CA certificates, which
makes every HTTPS connection fail certificate checks. macOS ships a CA bundle at /etc/ssl/cert.pem, so if
the default store is empty we load that. Verification is never turned off.
"""

from __future__ import annotations

import ssl
from pathlib import Path

FALLBACK_BUNDLES = ("/etc/ssl/cert.pem", "/private/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt")


def client_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if not ctx.cert_store_stats().get("x509_ca"):
        for bundle in FALLBACK_BUNDLES:
            if Path(bundle).is_file():
                ctx.load_verify_locations(cafile=bundle)
                break
    return ctx


def trust_summary() -> dict:
    ctx = ssl.create_default_context()
    default = ctx.cert_store_stats().get("x509_ca", 0)
    used = client_context().cert_store_stats().get("x509_ca", 0)
    return {"default_store": default, "in_use": used, "fallback": default == 0 and used > 0}
