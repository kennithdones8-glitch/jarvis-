"""The few Tailscale commands `jarvis remote` needs. JARVIS never installs or signs in to Tailscale itself.

`tailscale serve` (not `funnel`) publishes the dashboard only inside your tailnet: devices signed in to
your Tailscale account. Nothing is exposed to the internet.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

APP_CLI = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"


class TailscaleError(RuntimeError):
    pass


def cli() -> str:
    found = shutil.which("tailscale")
    if found:
        return found
    if Path(APP_CLI).exists():
        return APP_CLI
    raise TailscaleError("Tailscale isn't installed. Install it from the Mac App Store (free), sign in, then try again.")


def _run(*args: str, timeout: float = 20) -> str:
    try:
        r = subprocess.run([cli(), *args], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise TailscaleError("Tailscale didn't respond — is the Tailscale app running?") from None
    if r.returncode != 0:
        raise TailscaleError((r.stderr or r.stdout).strip()[:400] or f"tailscale {args[0]} failed")
    return r.stdout


def hostname() -> str:
    """This Mac's MagicDNS name, e.g. ``my-mac.tail1234.ts.net``."""
    status = json.loads(_run("status", "--json"))
    if status.get("BackendState") != "Running":
        raise TailscaleError("Tailscale is not connected. Open the Tailscale app and sign in.")
    name = str((status.get("Self") or {}).get("DNSName") or "").rstrip(".")
    if not name.endswith(".ts.net"):
        raise TailscaleError("MagicDNS isn't on. Turn on MagicDNS and HTTPS certificates in the Tailscale admin "
                             "console (DNS page), then try again.")
    return name


def serve_command(port: int) -> list[str]:
    return [cli(), "serve", "--bg", "--https=443", f"http://127.0.0.1:{port}"]


def serve(port: int) -> None:
    _run(*serve_command(port)[1:], timeout=60)


def unserve() -> None:
    _run("serve", "--https=443", "off")
