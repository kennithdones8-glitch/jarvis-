"""Voice: local speech recognition (whisper.cpp protocol stand-in), audio checks, endpoints, process lifecycle."""

import io
import json
import math
import os
import struct
import sys
import time
import urllib.request
import wave

import pytest

from model_servers import start_whisper
from test_dashboard import call, state
from test_remote import HOST, ORIGIN, Phone, paired  # noqa: F401

from jarvis.models.config import ConfigError, parse_model_config
from jarvis.remote import RemoteAccess
from jarvis.server import Dashboard
from jarvis.voice import VoiceError, WhisperClient, WhisperProcess, check_wav, clean_transcript


def wav(seconds=1.0, rate=16000, channels=1):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        n = int(seconds * rate)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(i / 10))) * channels for i in range(n)))
    return buf.getvalue()


def post_audio(d, data, *, host=None, headers=None, origin=None, cookie=True):
    h = {"Host": host or f"localhost:{d.port}", "Content-Type": "audio/wav", "X-Requested-By": "jarvis"}
    if cookie:
        h["Cookie"] = "jarvis_session=test-token"
    if origin:
        h["Origin"] = origin
    h.update(headers or {})
    req = urllib.request.Request(f"http://127.0.0.1:{d.port}/api/voice/transcribe", data=data, headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


# ---- audio checks -------------------------------------------------------------------------
def test_check_wav():
    assert abs(check_wav(wav(2.0)) - 2.0) < 0.01
    for bad, why in ((wav(1, rate=44100), "16 kHz"), (wav(1, channels=2), "16 kHz"), (wav(0.1), "too short"),
                     (b"RIFFnotreally", "not a WAV"), (wav(61), "60 seconds")):
        with pytest.raises(VoiceError, match=why):
            check_wav(bad)


def test_clean_transcript():
    assert clean_transcript(" [BLANK_AUDIO]\n") == ""
    assert clean_transcript(" Thank you.") == ""          # whisper's habit on silence
    assert clean_transcript("(music) What's on today? ") == "What's on today?"


# ---- client ---------------------------------------------------------------------------------
def test_client_loopback_only():
    for bad in ("http://10.0.0.5:8178", "https://whisper.example.com", "http://mac.tail1234.ts.net:8178"):
        with pytest.raises(ValueError):
            WhisperClient(bad)
    with pytest.raises(ConfigError):
        parse_model_config({"voice": {"enabled": True, "server": "http://192.168.1.2:8178"}})


def test_client_sends_exact_audio_and_ignores_proxies(monkeypatch):
    server = start_whisper(" What's the weather? [BLANK_AUDIO]")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")  # a proxy would break this; local audio must not use one
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:9")
    try:
        client = WhisperClient(server.url)
        audio = wav(1.5)
        assert client.available() is True
        assert client.transcribe(audio) == "What's the weather?"
        got = server.received[0]
        assert got["path"] == "/inference" and got["file"] == audio
        assert got["fields"]["response_format"] == b"json" and got["fields"]["language"] == b"en"
        server.fail_status = 500
        with pytest.raises(VoiceError, match="HTTP 500"):
            client.transcribe(audio)
    finally:
        server.stop()
    with pytest.raises(VoiceError, match="isn't running"):
        client.transcribe(wav(1))
    assert client.available() is False


# ---- dashboard endpoint -----------------------------------------------------------------------
@pytest.fixture
def voice_dash(make_kernel, tmp_path):
    server = start_whisper(" Remind me what I asked yesterday.")
    (tmp_path / "jarvis.toml").write_text(f'[voice]\nenabled = true\nserver = "{server.url}"\n')
    k = make_kernel(config_path=tmp_path / "jarvis.toml")
    d = Dashboard(k, port=0, token="test-token", poll_s=0.05)
    d.start()
    yield d, server
    d.shutdown()
    server.stop()


def test_transcribe_endpoint(voice_dash):
    d, server = voice_dash
    assert state(d)["voice"]["enabled"] is True and state(d)["voice"]["available"] is True
    status, r = post_audio(d, wav(1.2))
    assert status == 200 and r["text"] == "Remind me what I asked yesterday."
    entry = next(e for e in d.kernel.audit.entries() if e["event"] == "voice.transcribed")
    assert entry["payload"]["chars"] == len(r["text"]) and "yesterday" not in json.dumps(entry["payload"])
    assert not list(d.kernel.home.rglob("*.wav"))  # audio is never written to disk


def test_transcribe_endpoint_defences(voice_dash):
    d, server = voice_dash
    assert post_audio(d, wav(1), cookie=False)[0] == 401
    assert post_audio(d, wav(1), headers={"X-Requested-By": "x"})[0] == 403
    assert post_audio(d, wav(1), origin="https://evil.example")[0] == 403
    assert post_audio(d, wav(1), headers={"Content-Type": "application/json"})[0] == 415
    assert post_audio(d, wav(61))[0] == 413
    assert post_audio(d, wav(1, rate=48000))[0] == 422
    assert server.received == []  # nothing invalid reached the recogniser


def test_voice_off_by_default(make_kernel):
    d = Dashboard(make_kernel(), port=0, token="test-token")
    d.start()
    try:
        assert state(d)["voice"]["enabled"] is False
        assert post_audio(d, wav(1))[0] == 409
    finally:
        d.shutdown()


def test_phone_can_talk_when_signed_in(voice_dash):
    d, server = voice_dash
    d.remote = RemoteAccess(d.kernel, HOST)
    assert post_audio(d, wav(1), host=HOST, cookie=False, origin=ORIGIN)[0] == 401
    phone, _ = paired(d)
    status, r = post_audio(d, wav(1), host=HOST, cookie=False, origin=ORIGIN,
                           headers={"Cookie": f"jarvis_device={phone.cookie}"})
    assert status == 200 and r["text"].startswith("Remind me")
    assert any(e["actor"] == "user:phone:Test iPhone" and e["event"] == "voice.transcribed"
               for e in d.kernel.audit.entries())


def test_permissions_policy_allows_only_microphone(voice_dash):
    d, _ = voice_dash
    headers = call(d, "/")[1]
    assert "microphone=(self)" in headers["Permissions-Policy"] and "camera=()" in headers["Permissions-Policy"]


# ---- managed whisper-server process --------------------------------------------------------------
def test_process_lifecycle(tmp_path):
    fake = tmp_path / "whisper-server"
    args_file = tmp_path / "args.txt"
    fake.write_text(f"#!{sys.executable}\nimport sys, time\nopen({str(args_file)!r}, 'w').write(' '.join(sys.argv[1:]))\n"
                    "time.sleep(60)\n")
    fake.chmod(0o755)
    model = tmp_path / "ggml-base.en.bin"
    p = WhisperProcess(str(fake), str(model), "http://127.0.0.1:8178", log_path=tmp_path / "whisper.log")
    assert p.problems() == [f"model not found at {model}"] and p.start() is False
    model.write_bytes(b"x")
    assert p.start() is True and p.running()
    for _ in range(50):
        if args_file.exists():
            break
        time.sleep(0.1)
    assert args_file.read_text() == f"-m {model} --host 127.0.0.1 --port 8178 -t 4 -l en"
    p.stop()
    assert not p.running()
    with pytest.raises(ValueError):
        WhisperProcess(str(fake), str(model), "http://0.0.0.0:8178")


def test_cli_enable_status_disable(tmp_path, capsys):
    from jarvis.cli import main as cli_main
    from jarvis.core import Kernel
    home, wdir = tmp_path / "home", tmp_path / "whisper.cpp"
    assert cli_main(["--home", str(home), "voice", "enable", "--whisper-dir", str(wdir)]) == 1
    assert "voice setup" in capsys.readouterr().err
    (wdir / "build" / "bin").mkdir(parents=True)
    (wdir / "models").mkdir()
    (wdir / "build" / "bin" / "whisper-server").write_text("#!/bin/sh\n")
    (wdir / "build" / "bin" / "whisper-server").chmod(0o755)
    (wdir / "models" / "ggml-base.en.bin").write_bytes(b"x")
    assert cli_main(["--home", str(home), "voice", "enable", "--whisper-dir", str(wdir)]) == 0
    k = Kernel(home)
    try:
        v = k.model_config.voice
        assert v["enabled"] is True and v["model"].endswith("ggml-base.en.bin") and v["language"] == "en"
        assert v["server"] == "http://127.0.0.1:8178"
    finally:
        k.close()
    assert cli_main(["--home", str(home), "voice", "enable", "--whisper-dir", str(wdir)]) == 0
    assert (home / "jarvis.toml").read_text().count("[voice]") == 1
    assert cli_main(["--home", str(home), "voice", "setup"]) == 0
    assert "v1.9.4" in capsys.readouterr().out
    assert cli_main(["--home", str(home), "voice", "disable"]) == 0
    k = Kernel(home)
    try:
        assert k.model_config.voice["enabled"] is False
    finally:
        k.close()
