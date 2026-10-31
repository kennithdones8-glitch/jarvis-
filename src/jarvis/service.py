"""Run the JARVIS dashboard as a per-user macOS LaunchAgent (starts at login, restarts after a crash).

Nothing runs as root. The agent is a plain plist in ~/Library/LaunchAgents that runs
`uv run jarvis dashboard --no-open` from the JARVIS folder; `jarvis service uninstall` removes it.
"""

from __future__ import annotations

import os
import plistlib
import secrets
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any

LABEL = "com.jarvis.dashboard"
DEFAULT_PORT = 8765
REPO = Path(__file__).resolve().parents[2]


class ServiceError(RuntimeError):
    pass


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def token_path(home: Path) -> Path:
    return home / "dashboard.token"


def dashboard_token(home: Path, *, rotate: bool = False) -> str:
    """A stable secret for the dashboard link (so a bookmark keeps working across restarts)."""
    path = token_path(home)
    if path.exists() and not rotate:
        token = path.read_text().strip()
        if len(token) >= 32:
            return token
    token = secrets.token_urlsafe(32)
    path.write_text(token)
    path.chmod(0o600)
    return token


def dashboard_url(home: Path, port: int = DEFAULT_PORT) -> str:
    return f"http://127.0.0.1:{port}/?token={dashboard_token(home)}"


def build_plist(*, home: Path, uv: str, port: int = DEFAULT_PORT, repo: Path = REPO,
                path_env: str | None = None, custom_home: bool = False) -> bytes:
    args = [uv, "run", "--project", str(repo), "--quiet", "jarvis"]
    if custom_home:
        args += ["--home", str(home)]
    args += ["dashboard", "--no-open", "--port", str(port)]
    logs = home / "logs"
    env = {"PATH": path_env or os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"), "JARVIS_SERVICE": "1"}
    if custom_home:
        env["JARVIS_HOME"] = str(home)
    return plistlib.dumps({
        "Label": LABEL,
        "ProgramArguments": args,
        "WorkingDirectory": str(repo),
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},  # restart after a crash, not after a clean stop
        "ThrottleInterval": 30,
        "ProcessType": "Background",
        "EnvironmentVariables": env,
        "StandardOutPath": str(logs / "dashboard.log"),
        "StandardErrorPath": str(logs / "dashboard.log"),
    })


def _launchctl(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    if not shutil.which("launchctl"):
        raise ServiceError("launchctl not found — the background service is macOS-only")
    proc = subprocess.run(["launchctl", *args], capture_output=True, text=True, timeout=30)
    if check and proc.returncode != 0:
        raise ServiceError(f"launchctl {' '.join(args)} failed: {(proc.stderr or proc.stdout).strip()[:300]}")
    return proc


def _domain() -> str:
    return f"gui/{os.getuid()}"


def install(home: Path, *, port: int = DEFAULT_PORT, custom_home: bool = False) -> Path:
    if sys.platform != "darwin":
        raise ServiceError("the background service is only available on macOS")
    uv = shutil.which("uv")
    if not uv:
        raise ServiceError("couldn't find `uv` on your PATH")
    (home / "logs").mkdir(parents=True, exist_ok=True)
    dashboard_token(home)
    target = plist_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    if is_loaded():
        _launchctl("bootout", f"{_domain()}/{LABEL}", check=False)
    target.write_bytes(build_plist(home=home, uv=uv, port=port, custom_home=custom_home))
    _launchctl("bootstrap", _domain(), str(target))
    return target


def uninstall() -> bool:
    was = plist_path().exists()
    if is_loaded():
        _launchctl("bootout", f"{_domain()}/{LABEL}", check=False)
    plist_path().unlink(missing_ok=True)
    return was


def restart() -> None:
    _launchctl("kickstart", "-k", f"{_domain()}/{LABEL}")


def is_loaded() -> bool:
    if not shutil.which("launchctl"):
        return False
    return _launchctl("print", f"{_domain()}/{LABEL}", check=False).returncode == 0


def responding(port: int = DEFAULT_PORT) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2):
            return True
    except urllib.error.HTTPError as exc:
        return exc.code == 401  # the dashboard answers (asks for the link) → it's up
    except OSError:
        return False


def status(port: int = DEFAULT_PORT) -> dict[str, Any]:
    info: dict[str, Any] = {"installed": plist_path().exists(), "loaded": False, "pid": None,
                            "responding": responding(port)}
    if shutil.which("launchctl"):
        proc = _launchctl("print", f"{_domain()}/{LABEL}", check=False)
        if proc.returncode == 0:
            info["loaded"] = True
            for line in proc.stdout.splitlines():
                line = line.strip()
                if line.startswith("pid = "):
                    info["pid"] = int(line.split("=")[1])
                if line.startswith("state = "):
                    info["state"] = line.split("=")[1].strip()
    return info
