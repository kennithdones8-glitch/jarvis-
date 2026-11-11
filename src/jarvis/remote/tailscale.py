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


def checklist() -> list[dict[str, object]]:
    """Where iPhone access stands, step by step (nothing is changed). Each step: name, ok, and what to do if not."""
    steps: list[dict[str, object]] = []
    try:
        cli()
        steps.append({"name": "Tailscale installed on this Mac", "ok": True, "fix": ""})
    except TailscaleError:
        steps.append({"name": "Tailscale installed on this Mac", "ok": False,
                      "fix": "Install Tailscale from the Mac App Store (free) and sign in."})
        return steps
    try:
        status = json.loads(_run("status", "--json"))
    except (TailscaleError, ValueError) as exc:
        steps.append({"name": "Tailscale running", "ok": False, "fix": f"Open the Tailscale app and sign in ({exc})."})
        return steps
    running = status.get("BackendState") == "Running"
    steps.append({"name": "Tailscale signed in and connected", "ok": running,
                  "fix": "" if running else "Open the Tailscale app (menu bar) and sign in."})
    if not running:
        return steps
    name = str((status.get("Self") or {}).get("DNSName") or "").rstrip(".")
    magic = name.endswith(".ts.net")
    steps.append({"name": "MagicDNS and HTTPS on", "ok": magic, "fix": "" if magic else
                  "In the Tailscale admin console (login.tailscale.com → DNS), turn on MagicDNS and HTTPS Certificates."})
    phones = [p for p in (status.get("Peer") or {}).values()
              if str(p.get("OS", "")).lower() in ("ios", "iphone") or "iphone" in str(p.get("HostName", "")).lower()]
    steps.append({"name": "An iPhone in the same Tailscale account", "ok": bool(phones), "fix": "" if phones else
                  "Install Tailscale on your iPhone (App Store, free) and sign in with the same account."})
    return steps
