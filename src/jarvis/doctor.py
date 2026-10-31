"""`jarvis doctor`: checks the whole installation on this Mac and says plainly what works and what to fix.

Read-only apart from temporary files: it never changes settings, sends nothing private anywhere and doesn't
use Claude (which would count against your plan). The voice check speaks a fixed test sentence with macOS's
`say` and transcribes it locally.
"""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

OK, WARN, FAIL, SKIP = "ok", "warn", "fail", "skip"
MARK = {OK: "✓", WARN: "!", FAIL: "✗", SKIP: "–"}
VOICE_SENTENCE = "Jarvis voice check. One, two, three."


@dataclass
class Check:
    name: str
    status: str
    detail: str
    fix: str = ""


def _is_mac() -> bool:
    return sys.platform == "darwin"


def _get(url: str, *, timeout: float = 5, context=None) -> tuple[int, bytes]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                         *([urllib.request.HTTPSHandler(context=context)] if context else []))
    try:
        with opener.open(url, timeout=timeout) as r:
            return r.status, r.read(65536)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(65536)


class Doctor:
    def __init__(self, kernel, *, port: int = 8765, fetch: Callable = _get, voice_test: bool = True):
        self.k = kernel
        self.port = port
        self.fetch = fetch
        self.voice_test = voice_test
        self.results: list[Check] = []

    def add(self, name: str, status: str, detail: str, fix: str = "") -> None:
        self.results.append(Check(name, status, detail, fix))

    def run(self) -> list[Check]:
        for check in (self.system, self.storage, self.models, self.dashboard, self.service, self.backups,
                      self.tls, self.touch_id, self.phone, self.voice, self.briefing):
            try:
                check()
            except Exception as exc:  # a broken check must not hide the others
                self.add(check.__name__.replace("_", " ").capitalize(), FAIL, f"check crashed: {type(exc).__name__}: {exc}")
        return self.results

    # ---- checks -------------------------------------------------------------------------
    def system(self) -> None:
        mac = platform.mac_ver()[0]
        self.add("System", OK if _is_mac() else WARN,
                 f"macOS {mac} · {platform.machine()}" if mac else f"{platform.system()} (Mac-only checks skipped)")
        ok = sys.version_info >= (3, 12)
        self.add("Python", OK if ok else FAIL, platform.python_version(), "" if ok else "JARVIS needs Python 3.12+")

    def storage(self) -> None:
        from .core.db import MIGRATIONS

        k = self.k
        integrity = k.db.one("PRAGMA quick_check")[0]
        version = k.db.schema_version
        good = integrity == "ok" and version == len(MIGRATIONS)
        self.add("Database", OK if good else FAIL, f"integrity {integrity} · schema v{version}",
                 "" if good else "Restore the latest backup: `jarvis backup list`, then `jarvis backup restore FILE --yes`")
        chain = k.audit.verify()
        self.add("Audit log", OK if chain.ok else FAIL,
                 f"intact · {chain.checked} entries" if chain.ok else f"broken at entry {chain.first_bad_seq}")
        free = shutil.disk_usage(k.home).free / 1e9
        self.add("Disk space", OK if free > 5 else WARN if free > 2 else FAIL, f"{free:.0f} GB free")

    def models(self) -> None:
        from .status import models_status

        status = models_status(self.k)
        local = [p for p in status["providers"] if p["location"] == "local"]
        avail = sorted({m for p in local for m in p["available"]})
        self.add("Local models", OK if avail else FAIL, ", ".join(avail) or "Ollama isn't answering",
                 "" if avail else "Open the Ollama app; then `ollama pull llama3.2:3b`")
        cloud = [p for p in status["providers"] if p["location"] == "cloud"]
        if not cloud:
            self.add("Claude", SKIP, "off (local models only)", "`jarvis use-claude on` to use your Pro plan")
        for p in cloud:
            self.add(p["name"].capitalize(), OK if p["available"] else WARN,
                     "ready (not called: doctor never uses your plan)" if p["available"] else (p["error"] or "unavailable"),
                     "" if p["available"] else "Run `claude` once in Terminal and sign in")

    def dashboard(self) -> None:
        try:
            status, _ = self.fetch(f"http://localhost:{self.port}/", timeout=3)
        except (urllib.error.URLError, OSError) as exc:
            self.add("Dashboard", WARN, f"not running on port {self.port} ({getattr(exc, 'reason', exc)})",
                     "Start it: `jarvis service install` (always on) or `jarvis dashboard`")
            return
        ok = status in (200, 401)
        self.add("Dashboard", OK if ok else FAIL, f"answering at http://localhost:{self.port}" if ok else f"HTTP {status}")

    def service(self) -> None:
        if not _is_mac():
            self.add("Background service", SKIP, "macOS only")
            return
        from . import service as svc

        loaded = svc.is_loaded()
        self.add("Background service", OK if loaded else WARN, "starts at login" if loaded else "not installed",
                 "" if loaded else "`jarvis service install` so JARVIS (briefing, phone) runs without Terminal")

    def backups(self) -> None:
        from .backup import BackupError, get_passphrase, last_backup, verify_backup

        cfg = self.k.model_config.backup
        folder = Path(cfg["dir"]).expanduser() if cfg.get("dir") else self.k.home / "backups"
        if not get_passphrase():
            self.add("Backups", WARN, "not set up", "`jarvis backup now` once (save the passphrase it prints)")
            return
        last = last_backup(folder)
        if not last:
            self.add("Backups", WARN, "passphrase set, no backups yet", "`jarvis backup now`")
            return
        try:
            verify_backup(Path(last["path"]))
            verified = "newest one decrypts and checks out"
        except BackupError as exc:
            self.add("Backups", FAIL, f"newest backup failed verification: {exc}")
            return
        fresh = last["age_hours"] < 48
        self.add("Backups", OK if fresh else WARN, f"{last['count']} kept · newest {last['age_hours']:.0f}h old · {verified}",
                 "" if fresh else "Is JARVIS running? Automatic backups run daily while it is")

    def tls(self) -> None:
        from .core.tls import trust_summary

        t = trust_summary()
        if not t["in_use"]:
            self.add("HTTPS trust", FAIL, "no trusted certificates found: notifications and web fetch will fail",
                     "Tell Claude: `jarvis doctor` says HTTPS trust failed")
        else:
            self.add("HTTPS trust", OK, f"{t['in_use']} root certificates" + (" (macOS bundle fallback)" if t["fallback"] else ""))

    def touch_id(self) -> None:
        from .remote.devices import DeviceStore

        keys = [d for d in DeviceStore(self.k.db, self.k.audit).list("mac") if not d["revoked_at"]]
        self.add("Touch ID", OK if keys else SKIP, f"on · {len(keys)} key(s)" if keys else "off",
                 "" if keys else "Optional: dashboard → Systems → Touch ID")

    def phone(self) -> None:
        cfg = self.k.model_config.remote
        if not cfg.get("enabled"):
            self.add("iPhone access", SKIP, "off", "Optional: install Tailscale, then `jarvis remote enable`")
            return
        from .remote import tailscale as ts
        from .remote.devices import DeviceStore

        host = cfg["hostname"]
        try:
            actual = ts.hostname()
            same = actual == host
            self.add("Tailscale", OK if same else FAIL, f"connected as {actual}",
                     "" if same else "This Mac's Tailscale name changed: run `jarvis remote enable` again")
        except ts.TailscaleError as exc:
            self.add("Tailscale", FAIL, str(exc))
            return
        from .core.tls import client_context

        try:
            # Served to signed-out phones, so 200 here proves the whole path: tailnet HTTPS → tailscale serve →
            # JARVIS, with the Tailscale name kept in the Host header (otherwise JARVIS would answer 401).
            status, body = self.fetch(f"https://{host}/manifest.webmanifest", timeout=10, context=client_context())
            ok = status == 200 and b"JARVIS" in body
            self.add("Phone address", OK if ok else FAIL, f"https://{host} reaches JARVIS" if ok else f"HTTP {status} from https://{host}",
                     "" if ok else "Run `jarvis remote enable` again; check HTTPS certificates are on in the Tailscale admin console")
        except (urllib.error.URLError, OSError) as exc:
            self.add("Phone address", FAIL, f"https://{host} unreachable: {getattr(exc, 'reason', exc)}",
                     "Is JARVIS running? Run `jarvis remote enable` again")
        store = DeviceStore(self.k.db, self.k.audit)
        phones = [d for d in store.list() if not d["revoked_at"]]
        subs = len(self.k.db.query("SELECT 1 FROM push_subscriptions"))
        self.add("Paired phones", OK if phones else WARN, f"{len(phones)} paired · {subs} with notifications on",
                 "" if phones else "Dashboard → Systems → Phone → Pair a phone")

    def voice(self) -> None:
        from .voice import Voice, VoiceError

        cfg = self.k.model_config.voice
        if not cfg.get("enabled"):
            self.add("Voice", SKIP, "off", "Optional: `jarvis voice setup`")
            return
        v = Voice(cfg, self.k.home)
        problems = v.process.problems() if v.process else []
        if problems:
            self.add("Voice", FAIL, "; ".join(problems), "`jarvis voice setup` shows the build steps")
            return
        if not (self.voice_test and _is_mac() and shutil.which("say") and shutil.which("afconvert")):
            self.add("Voice", OK if v.client.available() else WARN,
                     "recogniser answering" if v.client.available() else "recogniser not running (starts with JARVIS)")
            return
        started = False
        try:
            if not v.client.available() and v.process:
                started = v.process.start()
                for _ in range(120):
                    if v.client.available():
                        break
                    time.sleep(0.5)
            with tempfile.TemporaryDirectory() as tmp:
                aiff, wav = Path(tmp) / "t.aiff", Path(tmp) / "t.wav"
                subprocess.run(["say", "-o", str(aiff), VOICE_SENTENCE], check=True, timeout=30)
                subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", str(aiff), str(wav)],
                               check=True, timeout=30)
                t0 = time.monotonic()
                heard = v.client.transcribe(wav.read_bytes())
                secs = time.monotonic() - t0
            words = {w.strip(".,!?").lower() for w in heard.split()}
            ok = {"voice", "check"} <= words or {"one", "two", "three"} <= words
            self.add("Voice", OK if ok else WARN, f'heard "{heard}" in {secs:.1f}s',
                     "" if ok else "Recognition is off: try the larger model (`jarvis voice enable --model small.en`)")
        except (VoiceError, subprocess.SubprocessError, OSError) as exc:
            self.add("Voice", FAIL, str(exc))
        finally:
            if started:
                v.process.stop()

    def briefing(self) -> None:
        from .proactive import Schedule

        s = Schedule.from_config(self.k.model_config.proactive)  # fills in the defaults
        if not s.enabled:
            self.add("Morning briefing", SKIP, "off")
            return
        self.add("Morning briefing", OK, f"daily at {s.briefing_time} · quiet hours {s.quiet_hours or 'none'}"
                 + ("" if _is_mac() else " (needs JARVIS running at that time)"))


def report(results: list[Check]) -> str:
    width = max(len(c.name) for c in results) + 2
    lines = []
    for c in results:
        lines.append(f"{MARK[c.status]} {c.name:<{width}}{c.detail}")
        if c.fix and c.status in (FAIL, WARN):
            lines.append(f"  {'':<{width}}→ {c.fix}")
    fails = sum(c.status == FAIL for c in results)
    warns = sum(c.status == WARN for c in results)
    lines.append("")
    lines.append("All good." if not fails and not warns else f"{fails} problem(s), {warns} warning(s).")
    return "\n".join(lines)


def as_json(results: list[Check]) -> str:
    return json.dumps([asdict(c) for c in results], indent=2)
