"""Live system awareness: CPU load, memory, storage, network route, and JARVIS's own memory use.

Standard library and macOS's built-in commands only (`sysctl`, `vm_stat`); no new dependency. Every figure says
where it came from, and anything that can't be read is reported as unavailable with the reason, never estimated.
Nothing here sends anything: the network check asks the operating system for a route without sending a packet,
and no address is returned.
"""

from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

TIMEOUT_S = 2.0


def _unavailable(reason: str) -> dict[str, Any]:
    return {"available": False, "reason": reason}


def cpu() -> dict[str, Any]:
    cores = os.cpu_count() or 0
    try:
        one, five, fifteen = os.getloadavg()
    except (OSError, AttributeError):
        return _unavailable("load average not available on this system")
    return {"available": True, "cores": cores, "load": [round(one, 2), round(five, 2), round(fifteen, 2)],
            "load_per_core": round(one / cores, 2) if cores else None, "source": "load average (1, 5, 15 min)"}


def _run(args: list[str]) -> str:
    return subprocess.run(args, capture_output=True, text=True, timeout=TIMEOUT_S, check=True, env={"LC_ALL": "C",
                          "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"}).stdout


def parse_vm_stat(text: str) -> dict[str, int]:
    """Pages per category from `vm_stat`, plus the page size in bytes."""
    out: dict[str, int] = {}
    if m := re.search(r"page size of (\d+) bytes", text):
        out["page_size"] = int(m.group(1))
    for name, value in re.findall(r'^"?([A-Za-z][^:"]*?)"?:\s+(\d+)\.?\s*$', text, re.M):
        out[name.strip().lower()] = int(value)
    return out


def memory() -> dict[str, Any]:
    try:
        if sys.platform == "darwin":
            total = int(_run(["/usr/sbin/sysctl", "-n", "hw.memsize"]).strip())
            vm = parse_vm_stat(_run(["/usr/bin/vm_stat"]))
            page = vm.get("page_size", 4096)
            # Like Activity Monitor's "Memory Used": app memory (active) + wired + compressed.
            used = (vm.get("pages active", 0) + vm.get("pages wired down", 0)
                    + vm.get("pages occupied by compressor", 0)) * page
            source = "vm_stat (active + wired + compressed)"
        else:
            info = {k: int(v) * 1024 for k, v in re.findall(r"^(\w+):\s+(\d+) kB", Path("/proc/meminfo").read_text(), re.M)}
            total = info["MemTotal"]
            used = total - info.get("MemAvailable", info.get("MemFree", 0))
            source = "/proc/meminfo (total − available)"
    except (OSError, subprocess.SubprocessError, ValueError, KeyError) as exc:
        return _unavailable(f"couldn't read memory use ({type(exc).__name__})")
    if total <= 0:
        return _unavailable("memory size not reported")
    return {"available": True, "total_bytes": total, "used_bytes": max(0, min(used, total)),
            "used_pct": round(100 * max(0, min(used, total)) / total, 1), "source": source}


def storage(path: Path) -> dict[str, Any]:
    try:
        u = shutil.disk_usage(path)
    except OSError as exc:
        return _unavailable(f"couldn't read disk usage ({type(exc).__name__})")
    return {"available": True, "total_bytes": u.total, "free_bytes": u.free,
            "used_pct": round(100 * (u.total - u.free) / u.total, 1) if u.total else None,
            "source": "the disk holding JARVIS's data"}


def network() -> dict[str, Any]:
    """Whether the system has a route to the internet. A UDP "connect" only asks the kernel for a route to a
    documentation-only address (TEST-NET-1); no packet is sent and no address is kept."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 9))
        local = s.getsockname()[0]
    except OSError:
        return {"available": True, "route": False, "source": "routing table (no packet sent)"}
    finally:
        s.close()
    return {"available": True, "route": not local.startswith("127."), "source": "routing table (no packet sent)"}


def process() -> dict[str, Any]:
    try:
        import resource
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except (ImportError, OSError):
        return _unavailable("not available on this system")
    # macOS reports bytes, Linux kilobytes.
    peak_bytes = peak if sys.platform == "darwin" else peak * 1024
    return {"available": True, "peak_bytes": peak_bytes, "pid": os.getpid(), "source": "getrusage (peak since start)"}


class Telemetry:
    """Cached snapshot (a few seconds), so the dashboard's polling never runs commands more often than that."""

    def __init__(self, home: Path, *, ttl_s: float = 5.0):
        self.home = home
        self.ttl_s = ttl_s
        self._cache: tuple[float, dict[str, Any]] = (0.0, {})

    def snapshot(self) -> dict[str, Any]:
        now = time.monotonic()
        if now - self._cache[0] > self.ttl_s or not self._cache[1]:
            self._cache = (now, {"cpu": cpu(), "memory": memory(), "storage": storage(self.home),
                                 "network": network(), "process": process(), "platform": sys.platform,
                                 "at": time.time()})
        return self._cache[1]
