"""Tier 6 — change trials: try a proposed change in isolation and report the evidence. Never applies it.

A trial checks a git branch or commit out into a throwaway **worktree** of JARVIS's own repository (a separate folder
under the data directory), runs the full test suite and the linter there, and does the same for the baseline (your
current code, or another ref you name). The result is an experiment record: tests that newly fail, tests that newly
pass, lint, the commits and how long it took. The worktrees are removed afterwards.

What it never does: switch, merge, commit, push or modify the code JARVIS is running, install anything, or call a
model. It needs autonomy tier 6, which can only be switched on from the Mac's terminal (`jarvis autonomy enable 6`),
and it can only be started from the Mac (never from a paired iPhone).

Isolation (the branch's tests are code you haven't vetted yet, so they run as if they were hostile):
- a bare environment: no API keys, tokens, SSH agent or JARVIS settings; a throwaway HOME and TMPDIR inside the
  trial's own folder; no bytecode written anywhere else;
- on macOS, inside the system sandbox (``sandbox-exec``): no network except this Mac itself (the tests' own stand-in
  servers); no writes outside the trial folder; no reading anything in any user folder or external drive except the
  trial, the Python installation and the repository's history (so not your Documents, Mail, Messages, browser data,
  SSH keys, cloud credentials or Keychains, and never JARVIS's data folder); no Keychain, no remote control of other
  apps (Apple events), no clipboard; no starting osascript, open, security, screencapture, pbcopy/pbpaste,
  automator or shortcuts; no local socket into a home folder or to Docker. If the sandbox can't start, the suite
  doesn't run and the trial reports that it proves nothing; it never falls back to running unsandboxed on a Mac;
- limits on everything it starts: 2 GB per file, 2,048 open files, 30 minutes of CPU, and the trial folder at most
  6 GB; on the time limit or a full folder its whole process group is stopped.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]          # the checkout JARVIS runs from (…/src/jarvis/learn → repo)
REF = re.compile(r"^(?!-)[\w./@^~-]{1,120}$")       # branch, tag, commit, HEAD~1 … never an option or a path trick
TIMEOUT = 1800


class TrialError(ValueError):
    pass


def available(repo: Path = REPO) -> str | None:
    """None if trials can run here, else why not."""
    if not (repo / ".git").exists():
        return "JARVIS isn't running from a git checkout, so there is nothing to try changes against"
    if shutil.which("git") is None:
        return "git isn't installed"
    return None


def _git(*args: str, cwd: Path = REPO, timeout: int = 120) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise TrialError(f"git {args[0]} failed: {(r.stderr or r.stdout).strip()[:300]}")
    return r.stdout.strip()


def resolve(ref: str, repo: Path = REPO) -> str:
    if not REF.fullmatch(ref or ""):
        raise TrialError("a branch, tag or commit name is required (letters, digits, . / _ - only)")
    return _git("rev-parse", "--verify", f"{ref}^{{commit}}", cwd=repo)


# Only these pass through from JARVIS's own environment; everything else (keys, tokens, agents, settings) is dropped.
PASS_ENV = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ")
# Never readable from inside the sandbox (besides JARVIS's data folder), relative to your home folder.
PRIVATE = (".ssh", ".aws", ".gnupg", ".config/gcloud", ".kube", ".docker", ".netrc", "Library/Keychains")


def trial_env(tree: Path, home: Path, tmp: Path) -> dict[str, str]:
    env = {k: os.environ[k] for k in PASS_ENV if k in os.environ}
    env.update(HOME=str(home), TMPDIR=str(tmp), PYTHONPATH=str(tree / "src"), PYTHONDONTWRITEBYTECODE="1",
               JARVIS_HOME=str(home / "jarvis-data"))
    return env


def _q(path: Path | str) -> str:
    return '"' + str(path).replace("\\", "\\\\").replace('"', '\\"') + '"'


# Programs a trial may not start (they reach your apps, clipboard, screen or Keychain through other processes).
NO_EXEC = ("/usr/bin/osascript", "/usr/bin/open", "/usr/bin/security", "/usr/bin/pbcopy", "/usr/bin/pbpaste",
           "/usr/sbin/screencapture", "/usr/bin/automator", "/usr/bin/shortcuts")
# Limits for everything a trial starts: biggest single file, open files, CPU seconds, and the whole trial folder.
MAX_FILE = 2 * 1024 ** 3
MAX_FILES_OPEN = 2048
MAX_DISK = 6 * 1024 ** 3


def _python_reads() -> list[Path]:
    """The Python installation and the environment the tests run in (they may live under your home folder)."""
    exe = Path(os.path.realpath(sys.executable))
    return sorted({Path(os.path.realpath(p)) for p in (sys.prefix, sys.base_prefix, exe.parent)})


def sandbox_profile(root: Path, data: Path | None, real_home: Path, *, extra_reads: list[Path] | None = None) -> str:
    """The macOS sandbox rules for one trial (later rules win). Reads are denied for every user folder and external
    drive, then allowed back only for the trial itself, the Python installation and the repository's history
    (`extra_reads`); private folders and JARVIS's data folder are denied again on top, except the trial."""
    root, home = Path(os.path.realpath(root)), Path(os.path.realpath(real_home))
    private = [home / p for p in PRIVATE] + ([Path(os.path.realpath(data))] if data else [])
    reads = [*_python_reads(), *[Path(os.path.realpath(p)) for p in (extra_reads or [])]]
    return "\n".join([
        "(version 1)",
        "(allow default)",
        "(deny network*)",
        '(allow network* (local ip "localhost:*"))',
        '(allow network* (remote ip "localhost:*"))',
        "(allow network* (remote unix-socket))",
        '(deny network* (remote unix-socket (path-regex #"^/(private/)?var/run/docker")))',
        f'(deny network* (remote unix-socket (path-regex #"^{_rx(home)}/")))',
        f"(allow network* (remote unix-socket (subpath {_q(root)})))",
        '(deny mach-lookup (global-name "com.apple.SecurityServer") (global-name "com.apple.securityd")'
        ' (global-name "com.apple.coreservices.appleevents") (global-name "com.apple.pasteboard.1"))',
        "(deny appleevent-send)",
        "(deny process-exec " + " ".join(f"(literal {_q(x)})" for x in NO_EXEC) + ")",
        "(deny file-write*)",
        f'(allow file-write* (subpath {_q(root)}) (literal "/dev/null") (literal "/dev/zero") (literal "/dev/tty") (subpath "/dev/fd"))',
        '(deny file-read-data (subpath "/Users") (subpath "/Volumes") ' + f"(subpath {_q(home)}))",
        "(allow file-read-data " + " ".join(f"(subpath {_q(r)})" for r in reads) + ")",
        "(deny file-read* " + " ".join(f"(subpath {_q(p)})" for p in private) + ")",
        f"(allow file-read* (subpath {_q(root)}))",
    ])


def _rx(path: Path) -> str:
    import re as _re
    return _re.escape(str(path)).replace('"', '\\"')


def _limits() -> None:  # pragma: no cover - runs in the child, before it starts
    import resource
    for what, value in ((resource.RLIMIT_FSIZE, MAX_FILE), (resource.RLIMIT_NOFILE, MAX_FILES_OPEN),
                        (resource.RLIMIT_CPU, TIMEOUT)):
        try:
            soft, hard = resource.getrlimit(what)
            cap = value if hard == resource.RLIM_INFINITY else min(value, hard)
            resource.setrlimit(what, (cap if soft == resource.RLIM_INFINITY else min(soft, cap), hard))
        except (ValueError, OSError):
            pass


def _size(folder: Path) -> int:
    total = 0
    for dirpath, _dirs, files in os.walk(folder):
        for f in files:
            try:
                total += os.lstat(os.path.join(dirpath, f)).st_size
            except OSError:
                pass
    return total


def contained_run(argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int, watch: Path,
                  max_disk: int = MAX_DISK) -> tuple[int, str, str]:
    """Run with the resource limits, in its own process group: on a timeout or a full trial folder the whole group
    (everything it started) is stopped. Output goes to files, so a chatty suite can't fill a pipe and hang."""
    import signal
    out, err = watch / ".trial-stdout.txt", watch / ".trial-stderr.txt"
    with open(out, "w") as o, open(err, "w") as e:
        proc = subprocess.Popen(argv, cwd=cwd, env=env, stdout=o, stderr=e, stdin=subprocess.DEVNULL,
                                start_new_session=True, preexec_fn=_limits)
        deadline, reason = time.monotonic() + timeout, ""
        while proc.poll() is None:
            if time.monotonic() > deadline:
                reason = f"stopped: over the {timeout // 60}-minute limit"
            elif _size(watch) > max_disk:
                reason = f"stopped: the trial folder passed {max_disk // 1024 ** 3} GB"
            if reason:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait()
                break
            time.sleep(2)
    text = out.read_text(errors="replace"), err.read_text(errors="replace")
    return (proc.returncode if not reason else -9), text[0], (text[1] + ("\n" + reason if reason else ""))


def isolation() -> str:
    """How trials are isolated on this machine: "macOS sandbox" or "environment only" (not macOS; development)."""
    if sys.platform != "darwin":
        return "environment only"
    if not Path("/usr/bin/sandbox-exec").exists():
        raise TrialError("the macOS sandbox (sandbox-exec) isn't available, so trials can't run safely here")
    return "macOS sandbox"


def _isolated(argv: list[str], root: Path, data: Path | None, *, reads: list[Path] | None = None) -> list[str]:
    if isolation() == "macOS sandbox":
        return ["/usr/bin/sandbox-exec", "-p", sandbox_profile(root, data, Path.home(), extra_reads=reads), *argv]
    return argv


def _run_suite(tree: Path, root: Path | None = None, data: Path | None = None, repo: Path = REPO) -> dict[str, Any]:
    """The tests and the linter inside one worktree, isolated (see the module notes), with that worktree's own code
    first on the path."""
    box = root or tree.parent / f"{tree.name}-box"   # this side's throwaway HOME and TMPDIR
    root = tree.parent                                # the whole trial folder: the only place the tests may write
    box.mkdir(exist_ok=True)
    home, tmp = box / "home", box / "tmp"
    home.mkdir(exist_ok=True)
    tmp.mkdir(exist_ok=True)
    env = trial_env(tree, home, tmp)
    started = time.monotonic()
    report = tree / ".trial-junit.xml"   # machine-readable results: independent of the project's pytest output settings
    reads = [Path(repo) / ".git"]   # a worktree's history lives in the repository's .git
    code, _out, err_text = contained_run(_isolated([sys.executable, "-m", "pytest", "-q", "--no-header", "-p",
                                                    "no:cacheprovider", f"--junitxml={report}", "tests"], root, data,
                                                   reads=reads), cwd=tree, env=env, timeout=TIMEOUT, watch=root)
    counts, failing = {"passed": 0, "failed": 0, "error": 0, "skipped": 0}, []
    try:
        import xml.etree.ElementTree as ET
        for case in ET.parse(report).getroot().iter("testcase"):
            name = f"{case.get('classname', '').replace('.', '/')}.py::{case.get('name')}"
            if case.find("failure") is not None:
                counts["failed"] += 1
                failing.append(name)
            elif case.find("error") is not None:
                counts["error"] += 1
                failing.append(name)
            elif case.find("skipped") is not None:
                counts["skipped"] += 1
            else:
                counts["passed"] += 1
    except Exception:  # noqa: BLE001 - no report: the suite didn't run; counted below as a failure
        counts["error"] += 1
    lint = None
    if shutil.which("ruff") or (Path(sys.executable).parent / "ruff").exists():
        ruff = shutil.which("ruff") or str(Path(sys.executable).parent / "ruff")
        lcode, lout, _ = contained_run(_isolated([ruff, "check", "--no-cache", "src", "tests"], root, data, reads=reads),
                                       cwd=tree, env=env, timeout=300, watch=root)
        lint = "clean" if lcode == 0 else (lout.strip().splitlines() or ["problems"])[-1][:200]
    stopped = next((line for line in err_text.splitlines() if line.startswith("stopped:")), None)
    return {"tests": counts, "failing": sorted(set(failing)), "lint": lint,
            "seconds": round(time.monotonic() - started, 1), "exit": code, **({"stopped": stopped} if stopped else {})}


def run(candidate: str, baseline: str = "HEAD", *, work: Path, repo: Path = REPO, data: Path | None = None) -> dict[str, Any]:
    """Run both sides in their own worktrees and compare. ``work`` is a folder JARVIS owns (under its data dir);
    ``data`` is JARVIS's data folder, which the sandboxed tests may not read."""
    if why := available(repo):
        raise TrialError(why)
    how = isolation()   # refuses on a Mac without the sandbox, before anything is checked out
    cand, base = resolve(candidate, repo), resolve(baseline, repo)
    work.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="trial-", dir=work))
    trees = {}
    try:
        for side, sha in (("baseline", base), ("candidate", cand)):
            trees[side] = root / side
            _git("worktree", "add", "--detach", str(trees[side]), sha, cwd=repo)
        res = {}
        for side, tree in trees.items():
            box = root / f"{side}-box"
            box.mkdir()
            res[side] = _run_suite(tree, box, data, repo)
    finally:
        for tree in trees.values():
            subprocess.run(["git", "worktree", "remove", "--force", str(tree)], cwd=repo, capture_output=True, timeout=120)
        subprocess.run(["git", "worktree", "prune"], cwd=repo, capture_output=True, timeout=60)
        shutil.rmtree(root, ignore_errors=True)   # only the trial's own temporary folder
    newly_failing = sorted(set(res["candidate"]["failing"]) - set(res["baseline"]["failing"]))
    newly_passing = sorted(set(res["baseline"]["failing"]) - set(res["candidate"]["failing"]))
    commits = _git("log", "--oneline", f"{base}..{cand}", cwd=repo).splitlines()[:30]
    ran = res["candidate"]["tests"]["passed"] > 0 and res["baseline"]["tests"]["passed"] > 0   # a suite that didn't run proves nothing
    ok = ran and not newly_failing and res["candidate"]["tests"]["error"] == 0 and res["candidate"]["lint"] in (None, "clean")
    return {"candidate": {"ref": candidate, "sha": cand[:12], **res["candidate"]}, "baseline": {"ref": baseline, "sha": base[:12], **res["baseline"]},
            "newly_failing": newly_failing, "newly_passing": newly_passing, "commits": commits, "ran": ran, "ok": ok,
            "isolation": how}


def recommendation(r: dict[str, Any]) -> str:
    c = r["candidate"]
    if not r.get("ran"):
        return "The tests didn't run in one of the copies, so this trial proves nothing. Check that the branch has its tests."
    if r["newly_failing"]:
        return (f"Don't merge yet: {len(r['newly_failing'])} test(s) pass on {r['baseline']['ref']} but fail on {c['ref']} "
                f"({', '.join(r['newly_failing'][:3])}{'…' if len(r['newly_failing']) > 3 else ''}).")
    if c["lint"] not in (None, "clean"):
        return f"Tests hold, but the linter reports: {c['lint']}. Fix that before merging."
    gained = f" It also fixes {len(r['newly_passing'])} failing test(s)." if r["newly_passing"] else ""
    return (f"No regressions: {c['tests']['passed']} tests pass on {c['ref']} ({len(r['commits'])} commit(s) ahead).{gained} "
            "Merging is still your decision (JARVIS never merges or pushes).")
