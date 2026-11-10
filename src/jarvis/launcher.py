"""JARVIS.app: a double-click launcher that opens the dashboard (macOS).

The app is a tiny AppleScript applet made on your own Mac with Apple's `osacompile`, so nothing is downloaded
and macOS doesn't flag it as coming from an unidentified developer. It runs exactly what `jarvis open` runs,
with the same `uv`, repository and data folder as the background service:

- no secret is stored in the app: the dashboard link is read from JARVIS's data folder each time it's opened;
- if JARVIS isn't running it says so and offers a "Start JARVIS" button, which (only when you click it) sets up the
  background service again, `jarvis service install`, then opens the dashboard once it answers;
- otherwise it never starts, stops, updates or changes JARVIS.

`jarvis app install` also puts a small `jarvis` command in ~/.local/bin, so `jarvis doctor` works in Terminal
without `uv run` (it runs this same repository with the same uv).

`jarvis app install` creates or replaces it; `jarvis app uninstall` removes it. Both only touch an app that
carries this launcher's marker file, never anything else with the same name.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .service import DEFAULT_PORT, REPO

APP_NAME = "JARVIS.app"
MARKER = "jarvis-launcher.txt"


class LauncherError(RuntimeError):
    pass


def default_dir() -> Path:
    return Path.home() / "Applications"


def _as_text(value: str) -> str:
    """An AppleScript string literal."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _shell(args: list[str]) -> str:
    return " & \" \" & ".join(f"quoted form of {_as_text(a)}" for a in args)


def applescript(*, uv: str, repo: Path, home: Path, custom_home: bool, port: int = DEFAULT_PORT) -> str:
    base = [uv, "run", "--project", str(repo), "--quiet", "jarvis"] + (["--home", str(home)] if custom_home else [])
    # `jarvis open` explains problems on stdout; send it to stderr so AppleScript's error message carries it
    command = _shell(base + ["open", "--port", str(port)]) + ' & " 1>&2"'
    start = _shell(base + ["service", "install", "--port", str(port)]) + ' & " 1>&2"'
    return f"""-- JARVIS launcher: opens the dashboard. Made by `jarvis app install`. It starts JARVIS only when you click
-- "Start JARVIS"; otherwise it changes nothing.
on run
\ttry
\t\tdo shell script {command}
\ton error errMsg number errNum
\t\tif errMsg contains "isn't running" then
\t\t\tset choice to button returned of (display dialog "JARVIS isn't running right now." & return & return & "It normally starts by itself when you log in. Start it now?" buttons {{"Cancel", "Start JARVIS"}} default button "Start JARVIS" cancel button "Cancel" with title "JARVIS" with icon caution)
\t\t\tif choice is "Start JARVIS" then
\t\t\t\ttry
\t\t\t\t\tdo shell script {start}
\t\t\t\ton error startMsg
\t\t\t\t\tdisplay dialog "JARVIS couldn't start:" & return & return & startMsg buttons {{"OK"}} default button "OK" with title "JARVIS" with icon caution
\t\t\t\t\treturn
\t\t\t\tend try
\t\t\t\trepeat 30 times
\t\t\t\t\tdelay 2
\t\t\t\t\ttry
\t\t\t\t\t\tdo shell script {command}
\t\t\t\t\t\treturn
\t\t\t\t\tend try
\t\t\t\tend repeat
\t\t\t\tdisplay dialog "JARVIS was started but isn't answering yet. Give it a minute and open JARVIS again. If it still doesn't open, the log is in JARVIS's data folder (logs/dashboard.log)." buttons {{"OK"}} default button "OK" with title "JARVIS" with icon caution
\t\t\tend if
\t\telse
\t\t\tdisplay dialog "JARVIS couldn't open the dashboard:" & return & return & errMsg buttons {{"OK"}} default button "OK" with title "JARVIS" with icon caution
\t\tend if
\tend try
end run
"""


COMMAND_MARK = "# Made by `jarvis app install`"


def command_dir() -> Path:
    return Path.home() / ".local" / "bin"


def command_script(*, uv: str, repo: Path, home: Path, custom_home: bool) -> str:
    import shlex
    extra = f" --home {shlex.quote(str(home))}" if custom_home else ""
    return (f"#!/bin/sh\n{COMMAND_MARK}: runs JARVIS from {repo} (`jarvis app uninstall` removes it).\n"
            f"exec {shlex.quote(uv)} run --project {shlex.quote(str(repo))} --quiet jarvis{extra} \"$@\"\n")


def install_command(home: Path, *, custom_home: bool, dest_dir: Path | None = None, repo: Path = REPO) -> Path:
    """A `jarvis` command for Terminal (no `uv run` needed). Never replaces a `jarvis` file it didn't make."""
    uv = shutil.which("uv")
    if not uv:
        raise LauncherError("couldn't find `uv` on your PATH")
    dest_dir = Path(dest_dir) if dest_dir else command_dir()
    target = dest_dir / "jarvis"
    if target.exists() and COMMAND_MARK not in target.read_text(errors="ignore"):
        raise LauncherError(f"{target} already exists and wasn't made by JARVIS; not touching it")
    dest_dir.mkdir(parents=True, exist_ok=True)
    target.write_text(command_script(uv=uv, repo=repo, home=home, custom_home=custom_home))
    target.chmod(0o755)
    return target


def uninstall_command(dest_dir: Path | None = None) -> bool:
    target = (Path(dest_dir) if dest_dir else command_dir()) / "jarvis"
    if not target.exists() or COMMAND_MARK not in target.read_text(errors="ignore"):
        return False
    target.unlink()
    return True


def is_ours(app: Path) -> bool:
    return (app / "Contents" / "Resources" / MARKER).is_file()


def install(home: Path, *, custom_home: bool, dest_dir: Path | None = None, port: int = DEFAULT_PORT,
            repo: Path = REPO) -> Path:
    if sys.platform != "darwin":
        raise LauncherError("the JARVIS app is only available on macOS")
    osacompile = shutil.which("osacompile")
    uv = shutil.which("uv")
    if not osacompile:
        raise LauncherError("couldn't find Apple's `osacompile`")
    if not uv:
        raise LauncherError("couldn't find `uv` on your PATH")
    dest_dir = Path(dest_dir) if dest_dir else default_dir()
    target = dest_dir / APP_NAME
    if target.exists() and not is_ours(target):
        raise LauncherError(f"{target} already exists and wasn't made by JARVIS; not touching it")
    dest_dir.mkdir(parents=True, exist_ok=True)
    script = applescript(uv=uv, repo=repo, home=home, custom_home=custom_home, port=port)
    with tempfile.TemporaryDirectory() as tmp:
        built = Path(tmp) / APP_NAME
        src = Path(tmp) / "launcher.applescript"
        src.write_text(script)
        r = subprocess.run([osacompile, "-o", str(built), str(src)], capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise LauncherError(f"osacompile failed: {(r.stderr or r.stdout).strip()[:300]}")
        (built / "Contents" / "Resources" / MARKER).write_text(
            "Made by `jarvis app install`. Opens the JARVIS dashboard; changes nothing.\n"
            f"repository: {repo}\n")
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(built), str(target))
    return target


def uninstall(dest_dir: Path | None = None) -> bool:
    target = (Path(dest_dir) if dest_dir else default_dir()) / APP_NAME
    if not target.exists():
        return False
    if not is_ours(target):
        raise LauncherError(f"{target} wasn't made by JARVIS; not removing it")
    shutil.rmtree(target)
    return True
