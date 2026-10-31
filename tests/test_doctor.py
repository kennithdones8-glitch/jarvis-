"""`jarvis doctor`: every check runs (none crash), problems come with a fix, and the phone path check
really distinguishes "reaches JARVIS as the phone" from "reaches JARVIS but the Host was rewritten"."""

import json
import ssl

import pytest

from model_servers import start_whisper
from test_dashboard import dash  # noqa: F401  (fixture)

from jarvis.doctor import FAIL, OK, SKIP, WARN, Doctor, report

HOST = "mac.tail1234.ts.net"


def by_name(results):
    return {c.name: c for c in results}


def test_runs_every_check_without_crashing(make_kernel):
    results = Doctor(make_kernel(), port=1, voice_test=False).run()
    assert not [c for c in results if "crashed" in c.detail]
    r = by_name(results)
    assert r["Database"].status == OK and r["Audit log"].status == OK and r["HTTPS trust"].status == OK
    assert r["Dashboard"].status == WARN and "jarvis service install" in r["Dashboard"].fix
    assert r["Morning briefing"].status == OK and "08:00" in r["Morning briefing"].detail
    assert r["iPhone access"].status == SKIP and r["Voice"].status == SKIP
    text = report(results)
    assert "→ Start it" in text and "problem(s)" in text


def test_dashboard_check_against_a_running_dashboard(dash):
    d, *_ = dash
    r = by_name(Doctor(d.kernel, port=d.port, voice_test=False).run())
    assert r["Dashboard"].status == OK


def _fake_tailscale(tmp_path, monkeypatch, name=HOST):
    fake = tmp_path / "bin" / "tailscale"
    fake.parent.mkdir()
    fake.write_text(f"""#!/bin/sh
[ "$1" = status ] && echo '{{"BackendState": "Running", "Self": {{"DNSName": "{name}."}}}}'
""")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake.parent}:/usr/bin:/bin")


def _remote_kernel(make_kernel, tmp_path):
    (tmp_path / "jarvis.toml").write_text(f'[remote]\nenabled = true\nhostname = "{HOST}"\n')
    return make_kernel(config_path=tmp_path / "jarvis.toml")


def test_phone_path_proves_host_header_survives(make_kernel, tmp_path, monkeypatch):
    _fake_tailscale(tmp_path, monkeypatch)
    k = _remote_kernel(make_kernel, tmp_path)
    seen = []

    def fetch(url, timeout=5, context=None):
        seen.append(url)
        if url.startswith("https://"):
            return 200, b'{"name": "JARVIS"}'
        raise OSError("not running")
    r = by_name(Doctor(k, fetch=fetch, voice_test=False).run())
    assert r["Tailscale"].status == OK and r["Phone address"].status == OK
    assert f"https://{HOST}/manifest.webmanifest" in seen
    assert r["Paired phones"].status == WARN

    # if tailscale serve rewrote Host to 127.0.0.1, JARVIS would treat it as local and answer 401
    r = by_name(Doctor(k, fetch=lambda url, timeout=5, context=None: (401, b"{}"), voice_test=False).run())
    assert r["Phone address"].status == FAIL and "HTTP 401" in r["Phone address"].detail


def test_tailscale_name_changed(make_kernel, tmp_path, monkeypatch):
    _fake_tailscale(tmp_path, monkeypatch, name="other-mac.tail1234.ts.net")
    k = _remote_kernel(make_kernel, tmp_path)
    r = by_name(Doctor(k, fetch=lambda *a, **kw: (200, b"JARVIS"), voice_test=False).run())
    assert r["Tailscale"].status == FAIL and "remote enable" in r["Tailscale"].fix


def test_voice_check(make_kernel, tmp_path):
    server = start_whisper()
    try:
        (tmp_path / "jarvis.toml").write_text(f'[voice]\nenabled = true\nserver = "{server.url}"\n')
        r = by_name(Doctor(make_kernel(config_path=tmp_path / "jarvis.toml"), port=1, voice_test=False).run())
        assert r["Voice"].status == OK
    finally:
        server.stop()
    (tmp_path / "j2.toml").write_text('[voice]\nenabled = true\nwhisper_binary = "/nope/whisper-server"\n'
                                      'model = "/nope/ggml-base.en.bin"\n')
    r = by_name(Doctor(make_kernel(config_path=tmp_path / "j2.toml"), port=1, voice_test=False).run())
    assert r["Voice"].status == FAIL and "not found" in r["Voice"].detail


def test_cli_doctor_json_and_exit_code(tmp_path, capsys):
    from jarvis.cli import main as cli_main
    code = cli_main(["--home", str(tmp_path / "home"), "doctor", "--json", "--port", "1", "--no-voice-test"])
    results = json.loads(capsys.readouterr().out)
    assert {c["name"] for c in results} >= {"Database", "Audit log", "Backups", "HTTPS trust"}
    assert code == (1 if any(c["status"] == FAIL for c in results) else 0)


def test_tls_falls_back_to_a_system_bundle_when_python_has_none(monkeypatch, tmp_path):
    import jarvis.core.tls as tls
    bundle = ssl.get_default_verify_paths().cafile or ssl.get_default_verify_paths().openssl_cafile
    if not bundle:
        pytest.skip("no CA bundle on this machine to stand in for /etc/ssl/cert.pem")
    monkeypatch.setattr(tls.ssl, "create_default_context", lambda: ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT))
    monkeypatch.setattr(tls, "FALLBACK_BUNDLES", (str(tmp_path / "missing.pem"), bundle))
    ctx = tls.client_context()
    assert ctx.cert_store_stats()["x509_ca"] > 0 and ctx.verify_mode == ssl.CERT_REQUIRED
    assert tls.trust_summary()["fallback"] is True
