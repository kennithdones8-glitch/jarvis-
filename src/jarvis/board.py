"""The project board: projects JARVIS opens and plans on the dashboard, instead of leaving files in your Notes.

How it works (the owner's choices):
- A project has a title, a short summary and a state (planning, active, done, archived). JARVIS opens one when you ask
  it to start or plan a project, or you open one yourself on the Projects page.
- What JARVIS makes for a project is kept with it: plans, notes, code and pages (HTML, e.g. an animation). It lives in
  JARVIS's own database (so it's in your encrypted backups), never in a folder or in Apple Notes, unless you
  ask for a file by name.
- Saving goes through the usual plan -> approve flow: the planner's `projects.save` step is a routine change, so
  JARVIS asks first, exactly as it does for writing a file. Opening, reading and listing are read-only or routine.
- Pages can be played on the Projects page only after you switch "Play animations" on (Mac only; Touch ID when set
  up). A page always plays in a sealed frame: its own empty origin, no network, no access to the dashboard, your data
  or your sign-in. Off by default; turning it off stops every page at once.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from .core.permissions import Tier
from .core.tools import ActionSpec, CallContext, ToolError, ToolSpec
from .core.util import new_id, now_iso

STATES = ("planning", "active", "done", "archived")
KINDS = ("plan", "note", "code", "page")
KIND_LABELS = {"plan": "Plan", "note": "Note", "code": "Code", "page": "Page"}
MAX_TITLE = 120
MAX_SUMMARY = 600
MAX_CONTENT = 1_000_000
MAX_PROJECTS = 200
MAX_ITEMS = 200
PLAY_ON = "board.play.on"

_FENCE = re.compile(r"```[ \t]*([\w+-]*)[ \t]*\n(.*?)```", re.S)
_HTML_START = re.compile(r"^\s*(<!doctype\s+html|<html[\s>])", re.I)
_HTML_BITS = re.compile(r"<(canvas|svg|script|style|body)[\s>]", re.I)
_CODE_HINT = re.compile(r"^\s*(def |class |import |from \w+ import |function |const |let |#include|<\?php)", re.M)


class BoardError(ValueError):
    pass


def key(title: str) -> str:
    return " ".join(title.split()).lower()


def _title(value: Any, what: str = "title") -> str:
    if not isinstance(value, str) or not value.strip():
        raise BoardError(f"'{what}' must be non-empty text")
    t = " ".join(value.split())
    if len(t) > MAX_TITLE:
        raise BoardError(f"'{what}' must be at most {MAX_TITLE} characters")
    return t


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def is_html(text: str) -> bool:
    return bool(_HTML_START.match(text)) or (text.lstrip().startswith("<") and bool(_HTML_BITS.search(text)))


def shape(content: str, title: str, kind: str | None) -> tuple[str, str]:
    """(kind, content) for what JARVIS saved. A page is the HTML on its own, even when the model wrapped it in a
    code fence with a sentence around it (small models do), so it can be played as it is."""
    if kind is not None and kind not in KINDS:
        raise BoardError(f"'kind' must be one of {', '.join(KINDS)}")
    text = content.strip()
    fenced = [(lang.lower(), body.strip()) for lang, body in _FENCE.findall(text)]
    page = next((body for lang, body in fenced if lang in ("html", "htm") or is_html(body)), None)
    if kind == "page" or (kind is None and (is_html(text) or page is not None)):
        html = text if is_html(text) else page
        if html is None:
            raise BoardError("a page must be HTML")
        return "page", html
    if kind:
        return kind, text
    if fenced or _CODE_HINT.search(text):
        return "code", text
    return ("plan" if "plan" in title.lower() else "note"), text


class Board:
    def __init__(self, db, audit):
        self.db = db
        self.audit = audit

    # ---- projects ---------------------------------------------------------------------------------------------
    def _project(self, ref: str) -> dict[str, Any] | None:
        row = self.db.one("SELECT * FROM board_projects WHERE id = ? OR title_key = ?", (ref, key(ref)))
        return dict(row) if row else None

    def open(self, title: Any, summary: Any = "", *, by: str) -> dict[str, Any]:
        """Open a project (or return the one with that name). Opening an archived one brings it back to planning."""
        t = _title(title)
        s = " ".join(summary.split())[:MAX_SUMMARY] if isinstance(summary, str) else ""
        existing = self._project(t)
        now = now_iso()
        if existing:
            if existing["state"] == "archived" or (s and not existing["summary"]):
                with self.db.tx() as c:
                    c.execute("UPDATE board_projects SET state = CASE WHEN state = 'archived' THEN 'planning' ELSE state END,"
                              " summary = CASE WHEN summary = '' THEN ? ELSE summary END, updated_at = ? WHERE id = ?",
                              (s, now, existing["id"]))
            return {**self._project(existing["id"]), "opened": False}
        if self.db.one("SELECT COUNT(*) FROM board_projects WHERE state != 'archived'")[0] >= MAX_PROJECTS:
            raise BoardError(f"there are already {MAX_PROJECTS} projects: archive some first")
        pid = new_id("proj")
        with self.db.tx() as c:
            c.execute("INSERT INTO board_projects (id, title_key, title, summary, state, created_by, created_at, updated_at)"
                      " VALUES (?, ?, ?, ?, 'planning', ?, ?, ?)", (pid, key(t), t, s, by, now, now))
        self.audit.record("board.project_opened", actor=by, project=pid, title=t)
        return {**self._project(pid), "opened": True}

    def set_state(self, pid: str, state: str, *, by: str) -> dict[str, Any]:
        if state not in STATES:
            raise BoardError(f"state must be one of {', '.join(STATES)}")
        p = self._project(pid)
        if p is None or p["id"] != pid:
            raise KeyError("no such project")
        with self.db.tx() as c:
            c.execute("UPDATE board_projects SET state = ?, updated_at = ? WHERE id = ?", (state, now_iso(), pid))
        self.audit.record("board.project_state", actor=by, project=pid, state=state)
        return self._project(pid)

    # ---- items ------------------------------------------------------------------------------------------------
    def save(self, project: Any, title: Any, content: Any, kind: Any = None, *, by: str,
             task_id: str | None = None, summary: Any = "") -> dict[str, Any]:
        """Save (or replace) one thing in a project; the project is opened if it isn't yet. Saving the same thing
        twice changes nothing (safe to retry)."""
        if not isinstance(content, str) or not content.strip():
            raise BoardError("'content' must be non-empty text")
        if len(content) > MAX_CONTENT:
            raise BoardError("content too large")
        t = _title(title)
        kind, body = shape(content, t, kind if isinstance(kind, str) and kind else None)
        p = self.open(project, summary, by=by)
        digest = sha(body)
        old = self.db.one("SELECT id, sha256 FROM board_items WHERE project_id = ? AND title_key = ?", (p["id"], key(t)))
        now = now_iso()
        if old and old["sha256"] == digest:
            return self._saved(p, old["id"], t, kind, body, changed=False)
        if not old and self.db.one("SELECT COUNT(*) FROM board_items WHERE project_id = ?", (p["id"],))[0] >= MAX_ITEMS:
            raise BoardError(f"this project already holds {MAX_ITEMS} things")
        iid = old["id"] if old else new_id("item")
        with self.db.tx() as c:
            if old:
                c.execute("UPDATE board_items SET title = ?, kind = ?, content = ?, sha256 = ?, task_id = ?, updated_at = ?"
                          " WHERE id = ?", (t, kind, body, digest, task_id, now, iid))
            else:
                c.execute("INSERT INTO board_items (id, project_id, title_key, title, kind, content, sha256, task_id,"
                          " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                          (iid, p["id"], key(t), t, kind, body, digest, task_id, now, now))
            c.execute("UPDATE board_projects SET updated_at = ?, state = CASE WHEN state = 'archived' THEN 'planning'"
                      " ELSE state END WHERE id = ?", (now, p["id"]))
        self.audit.record("board.saved", actor=by, task_id=task_id, project=p["id"], item=iid, kind=kind,
                          bytes=len(body.encode()), replaced=bool(old))
        return self._saved(p, iid, t, kind, body, changed=True)

    @staticmethod
    def _saved(p: dict, iid: str, title: str, kind: str, body: str, *, changed: bool) -> dict[str, Any]:
        return {"project_id": p["id"], "project": p["title"], "item_id": iid, "title": title, "kind": kind,
                "sha256": sha(body), "bytes": len(body.encode()), "changed": changed,
                "where": f"the Projects page on the dashboard (project “{p['title']}”)"}

    def item(self, iid: str) -> dict[str, Any]:
        row = self.db.one("SELECT i.*, p.title AS project FROM board_items i JOIN board_projects p ON p.id = i.project_id"
                          " WHERE i.id = ?", (iid,))
        if row is None:
            raise KeyError("no such item")
        return dict(row)

    def find(self, project: str, title: str) -> dict[str, Any] | None:
        p = self._project(project)
        if p is None:
            return None
        row = self.db.one("SELECT id FROM board_items WHERE project_id = ? AND title_key = ?", (p["id"], key(title)))
        return self.item(row["id"]) if row else None

    def delete_item(self, iid: str, *, by: str) -> None:
        it = self.item(iid)
        with self.db.tx() as c:
            c.execute("DELETE FROM board_items WHERE id = ?", (iid,))
        self.audit.record("board.item_deleted", actor=by, project=it["project_id"], item=iid, title=it["title"])

    def overview(self, *, include_archived: bool = False) -> list[dict[str, Any]]:
        where = "" if include_archived else "WHERE state != 'archived'"
        projects = [dict(r) for r in self.db.query(f"SELECT * FROM board_projects {where} ORDER BY updated_at DESC")]
        for p in projects:
            p["items"] = [dict(r) for r in self.db.query(
                "SELECT id, title, kind, length(content) AS chars, task_id, created_at, updated_at FROM board_items"
                " WHERE project_id = ? ORDER BY created_at", (p["id"],))]
            p.pop("title_key", None)
        return projects

    # ---- the planner's tool -----------------------------------------------------------------------------------
    def spec(self) -> ToolSpec:
        return ToolSpec("projects", "Projects on the dashboard: open one, save plans, notes, code or pages to it", {
            "list": ActionSpec(Tier.READ, timeout_s=10),
            "read": ActionSpec(Tier.READ, timeout_s=10),
            "open": ActionSpec(Tier.ROUTINE, timeout_s=10),
            "save": ActionSpec(Tier.ROUTINE, idempotent=True, timeout_s=15),
        }, self.handle)

    def handle(self, action: str, args: dict[str, Any], ctx: CallContext) -> Any:
        by = "jarvis"
        try:
            if action == "list":
                return {"projects": [{"title": p["title"], "state": p["state"], "summary": p["summary"],
                                      "items": [i["title"] for i in p["items"]]} for p in self.overview()]}
            if action == "read":
                p = self._project(_title(args.get("project"), "project"))
                if p is None:
                    raise ToolError(f"there's no project called “{args.get('project')}” on the dashboard")
                if args.get("title"):
                    it = self.find(p["id"], _title(args["title"]))
                    if it is None:
                        raise ToolError(f"project “{p['title']}” has nothing called “{args['title']}”")
                    return {"project": p["title"], "title": it["title"], "kind": it["kind"], "content": it["content"]}
                items = self.overview(include_archived=True)
                mine = next(x for x in items if x["id"] == p["id"])
                return {"project": p["title"], "summary": p["summary"], "state": p["state"],
                        "items": [{"title": i["title"], "kind": i["kind"]} for i in mine["items"]]}
            if action == "open":
                p = self.open(args.get("title"), args.get("summary", ""), by=by)
                return {"project_id": p["id"], "project": p["title"], "opened": p["opened"],
                        "where": f"the Projects page on the dashboard (project “{p['title']}”)"}
            if action == "save":
                return self.save(args.get("project"), args.get("title"), args.get("content"), args.get("kind"),
                                 by=by, task_id=ctx.task_id, summary=args.get("summary", ""))
        except BoardError as exc:
            raise ToolError(str(exc)) from None
        raise ToolError(f"unknown action {action}")


# ---- "Play animations" (off until you turn it on) ------------------------------------------------------------------
def play_enabled(kernel) -> bool:
    row = kernel.db.one("SELECT value FROM meta WHERE key = ?", (PLAY_ON,))
    return bool(row) and row["value"] == "1"


def set_play(kernel, on: bool, *, by: str) -> dict[str, Any]:
    if not by.startswith("user"):
        raise PermissionError("only you can turn playing animations on or off")
    with kernel.db.tx() as c:
        c.execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                  (PLAY_ON, "1" if on else "0"))
    kernel.audit.record("board.play", actor=by, on=on)
    return {"play": on}


# What a played page may do: run its own scripts and styles and show inline images. Nothing else: no network, no
# forms, no popups, no navigating the dashboard, no camera/microphone, and (sandbox without allow-same-origin) an
# empty origin of its own, so it can't read the dashboard, its cookies or your data even if opened on its own.
PLAY_HEADERS = {
    "Content-Security-Policy": "sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; "
                               "style-src 'unsafe-inline'; img-src data: blob:; media-src data: blob:; font-src data:; "
                               "connect-src 'none'; form-action 'none'; base-uri 'none'; frame-ancestors 'self'",
    "X-Frame-Options": "SAMEORIGIN",
    "Permissions-Policy": "microphone=(), camera=(), geolocation=(), payment=(), usb=(), fullscreen=()",
    "Cross-Origin-Resource-Policy": "same-origin",
}


__all__ = ["Board", "BoardError", "KINDS", "KIND_LABELS", "PLAY_HEADERS", "STATES", "play_enabled", "set_play", "shape"]
