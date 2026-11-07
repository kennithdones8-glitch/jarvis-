"""Mac checkup: how this Mac is doing, in plain words, with what you could do about it (owner's choice, 0.19.1).

Look-only. Every check runs a fixed macOS command (no shell, no arguments from anywhere else) with a short time
limit, reads its output, and reports. Nothing is installed, deleted, changed or restarted: the advice is for you to
act on, yourself. Process names and sizes are shown to you only; the audit log records counts, never details.

`jarvis checkup` runs it. `--updates` also asks Apple's Software Update which macOS updates exist; that is the
only check that uses the network, and it's macOS doing it (JARVIS sends nothing).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

OK, WARN, INFO, SKIP = "ok", "warn", "info", "skip"
PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
Runner = Callable[[list[str], float], str]


@dataclass
class Finding:
    name: str
    status: str
    detail: str
    advice: str = ""


def run_command(args: list[str], timeout: float) -> str:
    """A fixed system command, no shell, a clean environment, and a time limit. Raises on any failure."""
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=True,
                          env={"PATH": PATH, "LC_ALL": "C", "HOME": str(Path.home())}).stdout


def _gb(n: float) -> str:
    return f"{n / 1e9:.0f} GB" if n >= 10e9 else f"{n / 1e9:.1f} GB"


class Checkup:
    def __init__(self, *, run: Runner = run_command, home: Path | None = None, platform: str = sys.platform,
                 now: float | None = None):
        self.run = run
        self.home = home or Path.home()
        self.mac = platform == "darwin"
        self.now = now or time.time()

    def all(self, *, updates: bool = False) -> list[Finding]:
        checks = [self.macos, self.disk, self.clutter, self.cpu, self.memory, self.battery, self.uptime,
                  self.startup_items, self.time_machine]
        if updates:
            checks.insert(1, self.software_updates)
        out = []
        for check in checks:
            try:
                out.append(check())
            except Exception as exc:  # one check failing must never hide the others
                out.append(Finding(check.__name__.replace("_", " ").capitalize(), SKIP,
                                   f"couldn't check ({type(exc).__name__})"))
        return out

    # ---- checks ------------------------------------------------------------------------------------------------
    def macos(self) -> Finding:
        if not self.mac:
            return Finding("macOS", SKIP, "not a Mac")
        version = self.run(["/usr/bin/sw_vers", "-productVersion"], 5).strip()
        major = int(version.split(".")[0])
        if major < 15:
            return Finding("macOS", WARN, f"macOS {version}",
                           "Check System Settings → General → Software Update. Newer releases carry security fixes. "
                           "Back up first (Time Machine, and `jarvis backup now`).")
        return Finding("macOS", OK, f"macOS {version}")

    def software_updates(self) -> Finding:
        if not self.mac:
            return Finding("Software updates", SKIP, "not a Mac")
        text = self.run(["/usr/sbin/softwareupdate", "--list"], 90)
        titles = re.findall(r"^\s*\*\s*Label:\s*(.+)$", text, re.M)
        if not titles:
            return Finding("Software updates", OK, "none waiting")
        return Finding("Software updates", WARN, f"{len(titles)} waiting: " + "; ".join(t.strip() for t in titles[:4]),
                       "Install from System Settings → General → Software Update (after a backup). JARVIS never "
                       "installs anything itself.")

    def disk(self) -> Finding:
        u = shutil.disk_usage("/")
        pct = 100 * u.free / u.total
        detail = f"{_gb(u.free)} free of {_gb(u.total)} ({pct:.0f}%)"
        if pct < 10:
            return Finding("Disk space", WARN, detail, "Below 10% free, macOS slows down. See the clutter line below.")
        return Finding("Disk space", OK, detail)

    def clutter(self) -> Finding:
        """Sizes of the usual space-eaters you can safely tidy yourself (read with `du`, which only reads)."""
        places = {"Downloads": self.home / "Downloads", "Trash": self.home / ".Trash",
                  "app caches": self.home / "Library" / "Caches"}
        sizes = {}
        for label, path in places.items():
            if not path.is_dir():
                continue
            try:
                kb = int(self.run(["/usr/bin/du", "-sk", str(path)], 20).split()[0])
            except Exception:
                continue
            sizes[label] = kb * 1024
        if not sizes:
            return Finding("Clutter", SKIP, "couldn't read the usual folders")
        detail = ", ".join(f"{label} {_gb(n)}" for label, n in sizes.items())
        big = [label for label, n in sizes.items() if n > 5e9]
        if big:
            return Finding("Clutter", INFO, detail,
                           f"{' and '.join(big)} hold over 5 GB. Look through Downloads and empty the Trash when you "
                           "are sure; app caches rebuild themselves but are best left to the apps.")
        return Finding("Clutter", OK, detail)

    def cpu(self) -> Finding:
        load = os.getloadavg()[0]
        cores = os.cpu_count() or 1
        top = []
        try:
            text = self.run(["/bin/ps", "-Aceo", "pcpu,comm", "-r"], 5)
            for line in text.splitlines()[1:]:
                pct, _, name = line.strip().partition(" ")
                if float(pct) >= 10:
                    top.append(f"{name.strip()} {float(pct):.0f}%")
                if len(top) == 3:
                    break
        except Exception:
            pass
        detail = f"load {load:.1f} on {cores} cores" + (f" · busiest: {', '.join(top)}" if top else "")
        if load / cores > 0.5:
            return Finding("CPU", WARN, detail,
                           "The Mac is busy even before you ask JARVIS anything, and local models share the CPU. "
                           "Activity Monitor → % CPU shows what; quitting it makes answers faster.")
        return Finding("CPU", OK, detail)

    def memory(self) -> Finding:
        if not self.mac:
            return Finding("Memory", SKIP, "not a Mac")
        total = int(self.run(["/usr/sbin/sysctl", "-n", "hw.memsize"], 5))
        swap = self.run(["/usr/sbin/sysctl", "-n", "vm.swapusage"], 5)
        m = re.search(r"used = ([\d.]+)M", swap)
        used_mb = float(m.group(1)) if m else 0.0
        detail = f"{_gb(total)} installed · swap in use {used_mb / 1024:.1f} GB"
        if used_mb > 4096:
            return Finding("Memory", WARN, detail,
                           "Heavy swapping slows everything down. Close apps you aren't using, or restart.")
        return Finding("Memory", OK, detail)

    def battery(self) -> Finding:
        if not self.mac:
            return Finding("Battery", SKIP, "not a Mac")
        text = self.run(["/usr/sbin/system_profiler", "SPPowerDataType"], 20)
        cycles = re.search(r"Cycle Count:\s*(\d+)", text)
        condition = re.search(r"Condition:\s*(.+)", text)
        if not cycles and not condition:
            return Finding("Battery", SKIP, "no battery (desktop Mac)")
        state = condition.group(1).strip() if condition else "unknown"
        detail = f"condition {state}" + (f" · {cycles.group(1)} cycles" if cycles else "")
        if state.lower() not in ("normal", "unknown"):
            return Finding("Battery", WARN, detail, "macOS recommends service: see System Settings → Battery.")
        return Finding("Battery", OK, detail)

    def uptime(self) -> Finding:
        if not self.mac:
            return Finding("Last restart", SKIP, "not a Mac")
        text = self.run(["/usr/sbin/sysctl", "-n", "kern.boottime"], 5)
        m = re.search(r"sec = (\d+)", text)
        if not m:
            return Finding("Last restart", SKIP, "couldn't read the boot time")
        days = (self.now - int(m.group(1))) / 86400
        detail = f"{days:.0f} day(s) ago"
        if days > 14:
            return Finding("Last restart", INFO, detail,
                           "A restart now and then clears out memory leaks and applies pending updates. "
                           "JARVIS starts again by itself at login.")
        return Finding("Last restart", OK, detail)

    def startup_items(self) -> Finding:
        """Background helpers that start at login (files in the LaunchAgents folders; only the names are read)."""
        folders = [self.home / "Library" / "LaunchAgents", Path("/Library/LaunchAgents"), Path("/Library/LaunchDaemons")]
        names = sorted({p.stem for f in folders if f.is_dir() for p in f.glob("*.plist")})
        others = [n for n in names if n != "com.jarvis.dashboard"]
        detail = f"{len(others)} background helper(s) besides JARVIS"
        if len(others) > 15:
            return Finding("Startup helpers", INFO, detail,
                           "Many apps add helpers that run all the time. System Settings → General → Login Items "
                           "lets you turn off the ones you don't need.")
        return Finding("Startup helpers", OK, detail)

    def time_machine(self) -> Finding:
        if not self.mac:
            return Finding("Time Machine", SKIP, "not a Mac")
        try:
            latest = self.run(["/usr/bin/tmutil", "latestbackup"], 10).strip()
        except subprocess.CalledProcessError:
            return Finding("Time Machine", WARN, "no backup found (or not set up)",
                           "Time Machine with an external disk protects everything on this Mac, not just JARVIS. "
                           "System Settings → General → Time Machine.")
        m = re.search(r"(\d{4})-(\d{2})-(\d{2})-(\d{2})(\d{2})(\d{2})", latest)
        when = time.mktime(time.strptime("-".join(m.groups()), "%Y-%m-%d-%H-%M-%S")) if m else self._tm_settings_date()
        if when is None:
            # On the owner's Mac (14.1.1) tmutil answered without a date (backup disk not connected, or Terminal
            # without Full Disk Access). Say what it said rather than guess.
            said = " ".join(latest.split())[:80]
            return Finding("Time Machine", INFO, "set up; last backup date not readable"
                           + (f" (tmutil said: {said})" if said else " (backup disk not connected?)"),
                           "Check the date in System Settings → General → Time Machine.")
        days = (self.now - when) / 86400
        detail = f"last backup {days:.0f} day(s) ago"
        if days > 7:
            return Finding("Time Machine", WARN, detail, "Connect the backup disk so Time Machine can catch up.")
        return Finding("Time Machine", OK, detail)


    def _tm_settings_date(self) -> float | None:
        """The newest backup date in Time Machine's own settings (readable without the backup disk connected)."""
        try:
            out = self.run(["/usr/bin/defaults", "read", "/Library/Preferences/com.apple.TimeMachine"], 10)
        except (subprocess.SubprocessError, OSError):
            return None
        dates = re.findall(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} [+-]\d{4})", out)
        if not dates:
            return None
        from datetime import datetime
        return max(datetime.strptime(d, "%Y-%m-%d %H:%M:%S %z").timestamp() for d in dates)


def report(findings: list[Finding]) -> str:
    mark = {OK: "✓", WARN: "!", INFO: "i", SKIP: "–"}
    lines = ["Mac checkup (look only: nothing was changed)", ""]
    for f in findings:
        lines.append(f"{mark[f.status]} {f.name:<17} {f.detail}")
        if f.advice:
            lines.append(f"  {'':<17} → {f.advice}")
    warns = sum(f.status == WARN for f in findings)
    lines += ["", "All good." if not warns else f"{warns} thing(s) worth a look."]
    return "\n".join(lines)
