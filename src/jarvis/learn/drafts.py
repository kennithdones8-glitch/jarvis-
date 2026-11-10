"""JARVIS drafts a fix (tier 6): a patch for a problem you describe, tested before you see it. You decide what happens.

Flow, as one Lab experiment ("draft"):
1. Which files: the model sees the list of JARVIS's own source and test files and the problem, and names up to three.
2. The patch: it reads those files and writes a unified diff. Only files under src/ and tests/ may change; a patch that
   touches anything else (settings, the lockfile, CI, the gate's own list) is refused before it is tested.
3. The test: the patch is applied to a throwaway copy and the full suite and linter run in the hardened sandbox
   (see trial.py), compared with your current code.
4. A second opinion on the diff from a different local model.
5. The result: the patch (saved in JARVIS's data folder), what the tests and the reviewer found, and the command to
   apply it yourself. JARVIS never applies, commits, merges or pushes a draft.

Models: the best one you've allowed (Claude through Claude Code if it's on; it may ask in Decisions before JARVIS's
source is sent), else local. Patches that touch security-sensitive files are labelled as such.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path
from typing import Any

from ..models import ChatRequest, Message, Need
from ..models.types import Category
from .trial import REPO, TrialError

MAX_FILES = 3
MAX_FILE_CHARS = 60_000
ALLOWED = ("src/", "tests/")
SENSITIVE = ("src/jarvis/core/permissions.py", "src/jarvis/core/approvals.py", "src/jarvis/core/killswitch.py",
             "src/jarvis/core/audit.py", "src/jarvis/core/redact.py", "src/jarvis/models/egress.py",
             "src/jarvis/learn/trial.py", "src/jarvis/learn/__init__.py", "src/jarvis/gate.py", "src/jarvis/remote/",
             "src/jarvis/server/app.py", "src/jarvis/codecheck.py", "src/jarvis/update.py")

PICK_PROMPT = """You help fix JARVIS, a Python project. Given a PROBLEM and the list of FILES, name the files that most
likely need changing (at most 3, from the list only). Reply with JSON only: {"files": ["path", ...]}"""

PATCH_PROMPT = """You fix JARVIS, a Python project. Write the smallest change that fixes the PROBLEM, as a unified diff
(git format, paths a/... and b/..., correct @@ hunk headers, enough context lines), touching only the files shown, and
add or adjust a test when you can. Reply with the diff only, inside one ```diff block. No explanation."""

DIFF = re.compile(r"```(?:diff|patch)?\s*\n(.*?)```", re.S)


class DraftError(ValueError):
    pass


def _files(repo: Path) -> list[str]:
    out = subprocess.run(["git", "ls-files", "src", "tests"], cwd=repo, capture_output=True, text=True, timeout=60)
    return [f for f in out.stdout.splitlines() if f.endswith((".py", ".js", ".css", ".html", ".toml"))]


def touched(patch: str) -> list[str]:
    paths = set()
    for line in patch.splitlines():
        if line.startswith(("--- a/", "+++ b/")):
            paths.add(line[6:].strip())
    return sorted(paths)


def check_scope(patch: str) -> dict[str, Any]:
    files = touched(patch)
    if not files:
        raise DraftError("the draft isn't a patch JARVIS can read")
    outside = [f for f in files if not f.startswith(ALLOWED) or ".." in f]
    if outside:
        raise DraftError(f"the draft changes files outside src/ and tests/ ({', '.join(outside[:3])}); refused untested")
    return {"files": files, "sensitive": [f for f in files if any(f.startswith(s) for s in SENSITIVE)]}


def _complete(models, system: str, content: str, *, json_mode: bool, purpose: str):
    req = ChatRequest((Message("system", system, Category.SYSTEM_PROMPT),
                       Message("user", content, Category.PROJECT)), max_tokens=4000 if not json_mode else 300,
                      temperature=0.0, json_mode=json_mode)
    try:
        return models.complete(Need("chat", prefer="quality"), req, purpose=purpose)
    except Exception:  # noqa: BLE001 - no cloud, a consent question, a limit: draft on this Mac instead
        return models.complete(Need("chat", prefer="quality", local_only=True), req, purpose=purpose + " (local)")


def draft(models, problem: str, *, repo: Path = REPO) -> dict[str, Any]:
    from ..orchestrator.lookup import lenient_json
    problem = " ".join(str(problem).split())[:2000]
    if len(problem) < 10:
        raise DraftError("describe the problem in a sentence or two")
    listing = _files(repo)
    r = _complete(models, PICK_PROMPT, f"PROBLEM:\n{problem}\n\nFILES:\n" + "\n".join(listing), json_mode=True,
                  purpose="draft a fix: choose files")
    try:
        picked = [f for f in (lenient_json(r.text) or {}).get("files", []) if f in listing][:MAX_FILES]
    except Exception:  # noqa: BLE001
        picked = []
    if not picked:
        raise DraftError("couldn't tell which files to change; describe the problem more specifically")
    shown = "\n\n".join(f"FILE {f}:\n" + (repo / f).read_text(errors="replace")[:MAX_FILE_CHARS] for f in picked)
    r = _complete(models, PATCH_PROMPT, f"PROBLEM:\n{problem}\n\n{shown}", json_mode=False, purpose="draft a fix: patch")
    m = DIFF.search(r.text)
    patch = (m.group(1) if m else r.text).strip() + "\n"
    scope = check_scope(patch)
    return {"problem": problem, "picked": picked, "patch": patch, "model": f"{r.provider}/{r.model}",
            "sha256": hashlib.sha256(patch.encode()).hexdigest()[:16], **scope}


def save(home: Path, eid: str, patch: str) -> Path:
    d = Path(home) / "drafts"
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    p = d / f"{eid}.patch"
    p.write_text(patch)
    p.chmod(0o600)
    return p


def recommendation(trial_result: dict[str, Any] | None, review: dict[str, Any], scope: dict[str, Any], path: Path,
                   error: str | None = None) -> str:
    apply = f"To use it, review the patch, then in the JARVIS folder: git apply \"{path}\""
    if error:
        return f"The draft couldn't be tested: {error}. Nothing was changed."
    r = trial_result or {}
    head = ("The tests didn't run, so this proves nothing." if not r.get("ran") else
            f"Don't use it yet: {len(r['newly_failing'])} test(s) newly fail ({', '.join(r['newly_failing'][:3])})."
            if r.get("newly_failing") else
            f"Tests hold: no new failures ({r['candidate']['tests']['passed']} pass)"
            + (f", and it fixes {len(r['newly_passing'])} failing test(s)" if r.get("newly_passing") else "") + ".")
    if r.get("ran") and not r.get("newly_failing") and r.get("candidate", {}).get("lint") not in (None, "clean"):
        head += f" The linter reports: {r['candidate']['lint']}."
    rev = {"agree": " A second model agrees with the change.", "disagree": " A second model disagrees: "
           + "; ".join(review.get("problems", [])[:2]) + ".", "unsure": " A second model is unsure.",
           "unavailable": " Not reviewed by a second model (none installed)."}.get(review.get("verdict"), "")
    sens = f" It touches security-sensitive files ({', '.join(scope['sensitive'])}): read it with extra care." \
        if scope.get("sensitive") else ""
    return head + rev + sens + " " + apply + ". JARVIS never applies, commits or pushes it."


def code_review(models, problem: str, patch: str, *, author: str | None) -> dict[str, Any]:
    from ..orchestrator.review import _ask
    prompt = ("You are checking a patch for JARVIS, a Python project, before its owner applies it. Read the PROBLEM and "
              "the DIFF. Say whether the diff fixes the problem without breaking anything else, and name concrete "
              "issues only (a bug, a missed case, a security weakening, a change beyond what was asked). Reply with "
              'JSON only: {"verdict": "agree" | "disagree" | "unsure", "problems": ["...", ...]}')
    return _ask(models, prompt, f"PROBLEM:\n{problem}\n\nDIFF:\n{patch[:10000]}", author=author,
                purpose="second opinion (patch)").as_dict()


__all__ = ["DraftError", "TrialError", "check_scope", "code_review", "draft", "recommendation", "save", "touched"]
