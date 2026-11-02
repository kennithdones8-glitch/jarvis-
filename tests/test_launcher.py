"""JARVIS.app launcher: opens the dashboard exactly like `jarvis open`, stores no secret, and only ever
replaces or removes an app it made itself. (The real osacompile is exercised in test_macos_only.)"""

import shutil
import sys
from pathlib import Path

import pytest

from jarvis import launcher

FAKE_OSACOMPILE = r'''#!{python}
import pathlib, shutil, sys
args = sys.argv[1:]
out = pathlib.Path(args[args.index("-o") + 1])
res = out / "Contents" / "Resources"
res.mkdir(parents=True)
shutil.copy(args[-1], res / "source.applescript")
(out / "Contents" / "Info.plist").write_text("<plist/>")
'''


@pytest.fixture
def mac(monkeypatch, tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name, body in (("osacompile", FAKE_OSACOMPILE.format(python=sys.executable)), ("uv", "#!/bin/sh\n")):
        (bindir / name).write_text(body)
        (bindir / name).chmod(0o755)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("PATH", f"{bindir}:/usr/bin:/bin")
    return bindir


def source(app: Path) -> str:
    return (app / "Contents" / "Resources" / "source.applescript").read_text()


def test_script_runs_jarvis_open_like_the_service(tmp_path):
    repo, home = Path("/Users/k/my \"jarvis\" repo's"), tmp_path / "home"
    s = launcher.applescript(uv="/usr/local/bin/uv", repo=repo, home=home, custom_home=False, port=8765)
    for part in ("/usr/local/bin/uv", "run", "--project", "--quiet", "jarvis", "open", "--port", "8765"):
        assert f'quoted form of "{part}"' in s
    assert 'quoted form of "/Users/k/my \\"jarvis\\" repo\'s"' in s  # quotes escaped; the shell quoting is AppleScript's
    assert "--home" not in s  # default data folder: same as the service
    assert '" 1>&2"' in s and 'contains "isn\'t running"' in s
    custom = launcher.applescript(uv="/u/uv", repo=repo, home=home, custom_home=True)
    assert f'quoted form of "--home" & " " & quoted form of "{home}"' in custom


def test_install_replace_and_uninstall_only_touch_our_app(mac, tmp_path):
    from jarvis.service import dashboard_token
    home, apps = tmp_path / "home", tmp_path / "Apps"
    home.mkdir()
    token = dashboard_token(home)
    app = launcher.install(home, custom_home=False, dest_dir=apps)
    assert app == apps / "JARVIS.app" and launcher.is_ours(app)
    assert f'quoted form of "{mac / "uv"}"' in source(app)
    assert not any(token in p.read_text(errors="ignore") for p in app.rglob("*") if p.is_file())  # no link inside
    launcher.install(home, custom_home=False, dest_dir=apps)  # replacing our own app is fine
    assert launcher.uninstall(apps) is True and not app.exists()
    assert launcher.uninstall(apps) is False

    foreign = apps / "JARVIS.app"
    (foreign / "Contents").mkdir(parents=True)
    with pytest.raises(launcher.LauncherError, match="wasn't made by JARVIS"):
        launcher.install(home, custom_home=False, dest_dir=apps)
    with pytest.raises(launcher.LauncherError, match="wasn't made by JARVIS"):
        launcher.uninstall(apps)
    assert foreign.exists()


def test_refuses_off_macos_and_without_tools(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(launcher.LauncherError, match="only available on macOS"):
        launcher.install(tmp_path, custom_home=False, dest_dir=tmp_path / "Apps")
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(launcher.LauncherError, match="osacompile"):
        launcher.install(tmp_path, custom_home=False, dest_dir=tmp_path / "Apps")
    assert not (tmp_path / "Apps").exists()


def test_cli(mac, tmp_path, capsys):
    from jarvis.cli import main
    home, apps = tmp_path / "home", tmp_path / "Apps"
    assert main(["--home", str(home), "app", "install", "--dir", str(apps)]) == 0
    assert "Double-click it" in capsys.readouterr().out
    assert f'quoted form of "--home" & " " & quoted form of "{home}"' in source(apps / "JARVIS.app")
    assert main(["--home", str(home), "app", "uninstall", "--dir", str(apps)]) == 0
    assert "Removed JARVIS.app" in capsys.readouterr().out
