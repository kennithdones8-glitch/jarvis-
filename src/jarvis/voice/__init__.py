"""Voice: local speech recognition with whisper.cpp, on your Mac.

- Audio is recorded in the browser (Mac or iPhone) and sent to JARVIS as a 16 kHz mono WAV, at most 60 s.
  JARVIS passes it in memory to a whisper.cpp server on 127.0.0.1 and never writes it to disk.
- The whisper server is refused unless it's on a loopback address, like Ollama: audio never leaves the Mac
  (phone audio reaches the Mac over your Tailscale network, encrypted).
- The transcript is ordinary chat text: it goes through the same routing and privacy gate as typing, and it
  can't approve anything. Voice identity is not authentication.
- Spoken replies use the browser's on-device voices only (see app.js); nothing is synthesised on a server.
"""

from __future__ import annotations

import io
import json
import os
import re
import secrets
import signal
import subprocess
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path
from urllib.parse import urlsplit

from ..models.providers import is_loopback_url

SAMPLE_RATE = 16000
MAX_SECONDS = 60
MAX_BYTES = SAMPLE_RATE * 2 * MAX_SECONDS + 4096
DEFAULT_URL = "http://127.0.0.1:8178"
# whisper.cpp marks non-speech like this; on silence it can also invent a polite phrase
NOISE = re.compile(r"\[[^\]]*\]|\([^)]*\)|\*[^*]*\*")
SILENCE_PHRASES = {"", "you", "thank you.", "thanks for watching!", "thank you for watching."}


class VoiceError(RuntimeError):
    pass


def check_wav(data: bytes) -> float:
    """Validate a recording and return its length in seconds."""
    if len(data) > MAX_BYTES:
        raise VoiceError(f"recordings are limited to {MAX_SECONDS} seconds")
    try:
        with wave.open(io.BytesIO(data)) as w:
            channels, width, rate, frames = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
    except (wave.Error, EOFError):
        raise VoiceError("not a WAV recording") from None
    if (channels, width, rate) != (1, 2, SAMPLE_RATE):
        raise VoiceError("expected 16 kHz mono 16-bit audio")
    seconds = frames / SAMPLE_RATE
    if seconds < 0.3:
        raise VoiceError("that was too short — hold to talk a little longer")
    if seconds > MAX_SECONDS + 0.5:
        raise VoiceError(f"recordings are limited to {MAX_SECONDS} seconds")
    return seconds


def clean_transcript(text: str) -> str:
    text = " ".join(NOISE.sub(" ", text or "").split())
    return "" if text.lower() in SILENCE_PHRASES else text


def _multipart(fields: dict[str, str], file_bytes: bytes) -> tuple[bytes, str]:
    boundary = "jarvis" + secrets.token_hex(12)
    out = io.BytesIO()
    for name, value in fields.items():
        out.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    out.write(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="speech.wav"\r\n'
              "Content-Type: audio/wav\r\n\r\n".encode())
    out.write(file_bytes)
    out.write(f"\r\n--{boundary}--\r\n".encode())
    return out.getvalue(), f"multipart/form-data; boundary={boundary}"


class WhisperClient:
    """Talks to whisper.cpp's `whisper-server` (POST /inference). Loopback only."""

    def __init__(self, url: str = DEFAULT_URL, *, language: str = "en", timeout: float = 90.0):
        if not is_loopback_url(url):
            raise ValueError(f"the speech recogniser must run on this Mac (loopback), got {url!r}")
        self.url = url.rstrip("/")
        self.language = language
        self.timeout = timeout
        # never use a system HTTP proxy for local audio
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def available(self) -> bool:
        """Ready to transcribe: whisper-server's /health says ok (it answers 503 while the model loads)."""
        try:
            with self._opener.open(self.url + "/health", timeout=2) as resp:
                return resp.status == 200
        except (urllib.error.URLError, OSError):
            return False

    def transcribe(self, wav: bytes) -> str:
        check_wav(wav)
        body, ctype = _multipart({"response_format": "json", "temperature": "0.0", "language": self.language}, wav)
        req = urllib.request.Request(self.url + "/inference", data=body, method="POST",
                                     headers={"Content-Type": ctype})
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                raw = resp.read(1024 * 1024)
        except urllib.error.HTTPError as exc:
            raise VoiceError(f"speech recogniser error (HTTP {exc.code})") from None
        except (urllib.error.URLError, OSError):
            raise VoiceError("the speech recogniser isn't running — see `jarvis voice status`") from None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            raise VoiceError("the speech recogniser returned something unexpected") from None
        if not isinstance(data, dict) or "error" in data or not isinstance(data.get("text", ""), str):
            raise VoiceError("the speech recogniser couldn't read that recording")
        text = data.get("text", "")
        return clean_transcript(str(text))


class WhisperProcess:
    """Runs whisper-server as a child of JARVIS (same lifetime, no extra background service)."""

    def __init__(self, binary: str, model: str, url: str, *, language: str = "en", threads: int = 4,
                 log_path: Path | None = None):
        if not is_loopback_url(url):
            raise ValueError("whisper-server must listen on loopback")
        self.binary, self.model, self.url = binary, model, url
        self.language, self.threads, self.log_path = language, threads, log_path
        self.proc: subprocess.Popen | None = None

    def problems(self) -> list[str]:
        out = []
        if not (Path(self.binary).is_file() and os.access(self.binary, os.X_OK)):
            out.append(f"whisper-server not found at {self.binary}")
        if not Path(self.model).is_file():
            out.append(f"model not found at {self.model}")
        return out

    def start(self) -> bool:
        if self.problems() or (self.proc and self.proc.poll() is None):
            return False
        parts = urlsplit(self.url)
        log = open(self.log_path, "ab") if self.log_path else subprocess.DEVNULL  # noqa: SIM115
        try:
            self.proc = subprocess.Popen(
                [self.binary, "-m", self.model, "--host", parts.hostname or "127.0.0.1", "--port", str(parts.port or 8178),
                 "-t", str(self.threads), "-l", self.language],
                stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
        finally:
            if log is not subprocess.DEVNULL:
                log.close()
        return True

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stop(self) -> None:
        if not self.running():
            return
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(self.proc.pid, sig)
                self.proc.wait(timeout=3)
                return
            except (ProcessLookupError, PermissionError):
                return
            except subprocess.TimeoutExpired:
                continue


class Voice:
    """What the dashboard uses: config → client (+ optional managed whisper-server)."""

    def __init__(self, cfg: dict, home: Path):
        self.enabled = bool(cfg.get("enabled"))
        url = cfg.get("server") or DEFAULT_URL
        self.client = WhisperClient(url, language=cfg.get("language", "en"))
        self.process = None
        if cfg.get("whisper_binary") and cfg.get("model"):
            self.process = WhisperProcess(os.path.expanduser(cfg["whisper_binary"]), os.path.expanduser(cfg["model"]),
                                          url, language=cfg.get("language", "en"), threads=int(cfg.get("threads", 4)),
                                          log_path=home / "whisper.log")
        self._avail: tuple[float, bool] = (0.0, False)

    def start(self) -> None:
        if self.enabled and self.process is not None and not self.client.available():
            self.process.start()

    def stop(self) -> None:
        if self.process is not None:
            self.process.stop()

    def available(self) -> bool:
        if time.monotonic() - self._avail[0] > 10:
            self._avail = (time.monotonic(), self.enabled and self.client.available())
        return self._avail[1]

    def status(self) -> dict:
        return {"enabled": self.enabled, "available": self.available() if self.enabled else False,
                "managed": self.process is not None,
                "problems": self.process.problems() if self.process else []}
