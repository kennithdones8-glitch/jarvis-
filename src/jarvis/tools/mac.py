"""Mac apps: Calendar, Reminders, Notes, Mail drafts and opening apps, through macOS's own scripting
(`osascript -l JavaScript`). No extra software; macOS asks you once per app ("… wants to control Calendar").

- Every call goes through the ToolGateway: reading is tier 0, anything that adds or changes something is tier 1
  and asks you first. Nothing here sends mail or messages, deletes anything or changes system settings.
- Arguments reach the script as one JSON string (osascript's argv), never pasted into script text, so names and
  titles can't inject code.
- Output from your apps is private: when it's passed to a model it is sent as `file_content`, so the privacy gate
  asks before any of it goes to Claude.
- Calendar scripting doesn't list the individual dates of repeating events; JARVIS expands their repeat rules
  itself (python-dateutil) so a weekly meeting shows up on every week it happens.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from ..core.permissions import Tier
from ..core.tools import ActionSpec, CallContext, ToolError, ToolSpec

MAX_RANGE_DAYS = 62
READS = {"calendar.events", "reminders.list", "notes.search", "notes.read", "calendar.find", "reminders.find", "notes.find"}
# Seconds for osascript, a little under the gateway's limit for the action, so our clearer message wins.
TIMEOUTS = {"calendar.events": 85, "reminders.list": 85, "notes.search": 85, "apps.open": 25}
MAX_ITEMS = 200
MAX_NOTE_CHARS = 20_000
EMAIL = re.compile(r"^[^@\s<>\"',;]+@[^@\s<>\"',;]+\.[^@\s<>\"',;]+$")

# JXA scripts. Each receives one JSON argument and returns JSON. Bulk property reads (`sel.name()`) are one
# Apple event per property instead of one per item, which matters with hundreds of reminders or events.
PRELUDE = "function run(argv) { const a = JSON.parse(argv[0]); return JSON.stringify(main(a)); }\n"
SCRIPTS: dict[str, str] = {
    "calendar.events": """
function main(a) {
  // Never ask for all events before a date: a calendar's whole history (and subscribed holiday/birthday calendars)
  // can be thousands of events and take minutes. Two bounded questions per calendar instead:
  //  1) events that overlap the window;  2) repeating events that began before it (their later dates may fall in it).
  const Cal = Application("Calendar");
  const from = new Date(a.from), to = new Date(a.to);
  const cals = a.calendar ? [Cal.calendars.byName(a.calendar)] : Cal.calendars();
  const out = [], timing = [];
  const take = (sel, cname, withExcluded) => {
    const n = sel.summary(), s = sel.startDate(), e = sel.endDate(), ad = sel.alldayEvent(), loc = sel.location(),
          rec = sel.recurrence();
    let ex = [];
    if (withExcluded) { try { ex = sel.excludedDates(); } catch (err) { ex = []; } }
    for (let i = 0; i < n.length; i++) {
      const recurring = !!rec[i];
      out.push({title: n[i] || "", start: s[i].toISOString(), end: e[i].toISOString(), all_day: !!ad[i],
                location: loc[i] || "", calendar: cname, recurrence: recurring ? rec[i] : null,
                excluded: recurring && ex[i] ? ex[i].map((d) => d.toISOString()) : []});
    }
    return n.length;
  };
  for (const c of cals) {
    const t0 = Date.now(), cname = c.name(), row = {calendar: cname};
    try {
      row.overlapping = take(c.events.whose({_and: [{startDate: {_lessThan: to}}, {endDate: {_greaterThan: from}}]}),
                             cname, true);
    } catch (err) { row.error = "overlap: " + String(err).slice(0, 120); }
    try {
      row.repeating = take(c.events.whose({_and: [{startDate: {_lessThan: from}}, {recurrence: {_beginsWith: "FREQ"}}]}),
                           cname, true);
    } catch (err) { row.error = (row.error ? row.error + "; " : "") + "repeating: " + String(err).slice(0, 120); }
    row.seconds = (Date.now() - t0) / 1000;
    timing.push(row);
  }
  return {events: out, timing: timing};
}""",
    "calendar.add": """
function main(a) {
  const Cal = Application("Calendar");
  let cal = null;
  if (a.calendar) cal = Cal.calendars.byName(a.calendar);
  else { for (const c of Cal.calendars()) { if (c.writable()) { cal = c; break; } } }
  if (!cal) throw new Error("no calendar you can add events to");
  const ev = Cal.Event({summary: a.title, startDate: new Date(a.start), endDate: new Date(a.end),
                        location: a.location || "", description: a.notes || ""});
  cal.events.push(ev);
  return {title: a.title, start: a.start, end: a.end, calendar: cal.name()};
}""",
    "calendar.find": """
function main(a) {
  const Cal = Application("Calendar");
  const at = new Date(a.start);
  for (const c of Cal.calendars()) {
    const hits = c.events.whose({_and: [{summary: a.title}, {startDate: at}]})();
    if (hits.length) return {found: true};
  }
  return {found: false};
}""",
    "reminders.list": """
function main(a) {
  const R = Application("Reminders");
  const lists = a.list ? [R.lists.byName(a.list)] : R.lists();
  const out = [];
  for (const l of lists) {
    const sel = a.include_completed ? l.reminders : l.reminders.whose({completed: false});
    const n = sel.name(), d = sel.dueDate(), c = sel.completed(), b = sel.body();
    const lname = l.name();
    for (let i = 0; i < n.length; i++) {
      out.push({title: n[i] || "", due: d[i] ? d[i].toISOString() : null, completed: !!c[i], notes: b[i] || "",
                list: lname});
    }
  }
  return out;
}""",
    "reminders.add": """
function main(a) {
  const R = Application("Reminders");
  const list = a.list ? R.lists.byName(a.list) : R.defaultList();
  const r = R.Reminder({name: a.title, body: a.notes || ""});
  list.reminders.push(r);
  if (a.due) r.dueDate = new Date(a.due);
  return {title: a.title, list: list.name(), due: a.due || null};
}""",
    "reminders.complete": """
function main(a) {
  const R = Application("Reminders");
  const lists = a.list ? [R.lists.byName(a.list)] : R.lists();
  const hits = [];
  for (const l of lists) for (const r of l.reminders.whose({_and: [{name: a.title}, {completed: false}]})()) hits.push([r, l.name()]);
  if (hits.length === 0) return {error: "not_found"};
  if (hits.length > 1) return {error: "ambiguous", lists: hits.map((h) => h[1])};
  hits[0][0].completed = true;
  return {title: a.title, list: hits[0][1]};
}""",
    "reminders.find": """
function main(a) {
  const R = Application("Reminders");
  const lists = a.list ? [R.lists.byName(a.list)] : R.lists();
  for (const l of lists) if (l.reminders.whose({name: a.title})().length) return {found: true};
  return {found: false};
}""",
    "notes.search": """
function main(a) {
  const N = Application("Notes");
  const sel = N.notes.whose({_or: [{name: {_contains: a.query}}, {plaintext: {_contains: a.query}}]});
  const names = sel.name(), mod = sel.modificationDate();
  const out = [];
  for (let i = 0; i < names.length && i < a.limit; i++) {
    let text = "";
    try { text = sel[i].plaintext().slice(0, 240); } catch (e) { text = ""; }
    out.push({title: names[i] || "", modified: mod[i] ? mod[i].toISOString() : null, snippet: text});
  }
  return {total: names.length, results: out};
}""",
    "notes.read": """
function main(a) {
  const N = Application("Notes");
  const hits = N.notes.whose({name: a.title})();
  if (hits.length === 0) return {error: "not_found"};
  if (hits.length > 1) return {error: "ambiguous", count: hits.length};
  const n = hits[0];
  return {title: n.name(), modified: n.modificationDate().toISOString(), content: n.plaintext()};
}""",
    "notes.create": """
function main(a) {
  const N = Application("Notes");
  const folder = a.folder ? N.folders.byName(a.folder) : N.defaultAccount().defaultFolder();
  const note = N.Note({name: a.title, body: a.html});
  folder.notes.push(note);
  return {title: a.title, folder: folder.name()};
}""",
    "notes.find": """
function main(a) { return {found: Application("Notes").notes.whose({name: a.title})().length > 0}; }""",
    "mail.draft": """
function main(a) {
  const M = Application("Mail");
  const msg = M.OutgoingMessage({subject: a.subject, content: a.body, visible: true});
  M.outgoingMessages.push(msg);
  for (const addr of a.to) msg.toRecipients.push(M.Recipient({address: addr}));
  msg.save();
  return {subject: a.subject, to: a.to, saved_as: "draft"};
}""",
    "apps.open": """
function main(a) {
  const app = Application(a.name);
  app.activate();
  return {opened: app.name()};
}""",
}


class MacError(ToolError):
    pass


def osascript(name: str, args: dict[str, Any], timeout: float) -> Any:
    """Run one of SCRIPTS with JSON arguments and return its parsed JSON result."""
    reading = name in READS
    try:
        r = subprocess.run(["osascript", "-l", "JavaScript", "-e", PRELUDE + SCRIPTS[name], json.dumps(args)],
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        # A change that timed out may still have happened: never retry it blindly (that could duplicate it).
        raise MacError(f"{name.split('.')[0].capitalize()} didn't answer in time. If macOS is showing a permission "
                       "question, answer it and try again.", retryable=reading, outcome_unknown=not reading) from None
    except FileNotFoundError:
        raise MacError("osascript isn't available (Mac apps work only on macOS)") from None
    if r.returncode != 0:
        raise _explain(name, r.stderr)
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        raise MacError(f"unexpected reply from {name.split('.')[0]}") from None


def _explain(name: str, stderr: str) -> MacError:
    app = {"calendar": "Calendar", "reminders": "Reminders", "notes": "Notes", "mail": "Mail", "apps": "that app"}[
        name.split(".")[0]]
    if "-1743" in stderr or "Not authorized" in stderr or "not allowed" in stderr.lower():
        return MacError(f"macOS hasn't allowed JARVIS to use {app}. Open System Settings → Privacy & Security → "
                        f"Automation and turn on {app} under the app that runs JARVIS (Terminal, or python/uv for the "
                        "background service), then try again.")
    if "-1728" in stderr or "Can't get" in stderr or "Can’t get" in stderr:
        return MacError(f"{app} doesn't have that (check the name of the list, calendar, folder or app)")
    if "-600" in stderr or "isn't running" in stderr:
        return MacError(f"{app} isn't running and couldn't be started", retryable=True)
    tail = stderr.strip().splitlines()[-1][:200] if stderr.strip() else "unknown error"
    return MacError(f"{app} reported an error: {tail}")


# ---- argument checks ------------------------------------------------------------------------------------
def _text(args: dict, name: str, limit: int, *, required: bool = True) -> str:
    v = args.get(name)
    if v is None and not required:
        return ""
    if not isinstance(v, str) or (required and not v.strip()) or len(v) > limit:
        raise MacError(f"'{name}' must be text under {limit} characters")
    return v.strip()


def _when(args: dict, name: str, *, required: bool = True) -> datetime | None:
    v = args.get(name)
    if v is None and not required:
        return None
    if not isinstance(v, str):
        raise MacError(f"'{name}' must be a date/time like 2026-11-05T14:00")
    try:
        dt = datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
    except ValueError:
        raise MacError(f"'{name}' must be a date/time like 2026-11-05T14:00, got {v!r}") from None
    return dt if dt.tzinfo else dt.astimezone()  # no zone given: the Mac's local time


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _html(text: str) -> str:
    """Notes stores HTML; turn plain text into safe HTML (no markup from the input survives)."""
    esc = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return "".join(f"<div>{line or '<br>'}</div>" for line in esc.split("\n"))


def expand(events: list[dict], start: datetime, end: datetime) -> list[dict]:
    """Turn Calendar's raw events (repeating ones as one master with an RRULE) into the occurrences that overlap
    [start, end), sorted by start."""
    from dateutil.rrule import rrulestr

    out = []
    for ev in events:
        s, e = datetime.fromisoformat(ev["start"].replace("Z", "+00:00")), datetime.fromisoformat(ev["end"].replace("Z", "+00:00"))
        duration = e - s
        base = {k: ev[k] for k in ("title", "all_day", "location", "calendar")}
        if not ev.get("recurrence"):
            if s < end and e > start:
                out.append({**base, "start": _iso(s), "end": _iso(e)})
            continue
        try:
            rule = rrulestr(ev["recurrence"], dtstart=s)
        except (ValueError, TypeError):
            if s < end and e > start:  # unreadable rule: at least show the first occurrence
                out.append({**base, "start": _iso(s), "end": _iso(e), "repeats": True})
            continue
        excluded = {datetime.fromisoformat(x.replace("Z", "+00:00")) for x in ev.get("excluded", [])}
        for occ in rule.between(start - duration, end, inc=True):
            if occ in excluded or occ + duration <= start or occ >= end:
                continue
            out.append({**base, "start": _iso(occ), "end": _iso(occ + duration), "repeats": True})
            if len(out) > MAX_ITEMS * 2:
                break
    out.sort(key=lambda x: x["start"])
    return out[:MAX_ITEMS]


class MacTool:
    """Registered as five small tools (calendar, reminders, notes, mail, apps) so permissions and plans can name
    each app separately. ``runner(script_name, args, timeout)`` is osascript on a Mac; tests pass a stand-in."""

    def __init__(self, runner: Callable[[str, dict, float], Any] = osascript):
        self.runner = runner

    def run(self, name: str, args: dict) -> Any:
        return self.runner(name, args, TIMEOUTS.get(name, 55))

    def specs(self) -> list[ToolSpec]:
        read, change = Tier.READ, Tier.ROUTINE
        return [
            ToolSpec("calendar", "Your Mac's Calendar: see events, add an event", {
                "events": ActionSpec(read, timeout_s=90),
                "add": ActionSpec(change, idempotent=False, timeout_s=60, reconcile=self._reconcile("calendar")),
            }, self.handle_calendar),
            ToolSpec("reminders", "Your Mac's Reminders: list, add, complete", {
                "list": ActionSpec(read, timeout_s=90),
                "add": ActionSpec(change, idempotent=False, timeout_s=60, reconcile=self._reconcile("reminders")),
                "complete": ActionSpec(change, timeout_s=60),
            }, self.handle_reminders),
            ToolSpec("notes", "Your Mac's Notes: search, read, create", {
                "search": ActionSpec(read, timeout_s=90),
                "read": ActionSpec(read, timeout_s=60),
                "create": ActionSpec(change, idempotent=False, timeout_s=60, reconcile=self._reconcile("notes")),
            }, self.handle_notes),
            ToolSpec("mail", "Mail: create a draft for you to review and send yourself (never sends)", {
                "draft": ActionSpec(change, idempotent=False, timeout_s=60),
            }, self.handle_mail),
            ToolSpec("apps", "Open an app on your Mac", {
                "open": ActionSpec(change, timeout_s=30),
            }, self.handle_apps),
        ]

    # ---- handlers --------------------------------------------------------------------------------------
    def handle_calendar(self, action: str, args: dict, ctx: CallContext) -> Any:
        cal = _text(args, "calendar", 100, required=False) or None
        if action == "events":
            start = _when(args, "from")
            end = _when(args, "to")
            if end <= start or end - start > timedelta(days=MAX_RANGE_DAYS):
                raise MacError(f"the date range must be forward and at most {MAX_RANGE_DAYS} days")
            raw = self.run("calendar.events", {"from": _iso(start), "to": _iso(end), "calendar": cal})
            timing = raw.get("timing", []) if isinstance(raw, dict) else []
            raw = raw["events"] if isinstance(raw, dict) else raw
            seen, unique = set(), []
            for ev in raw:  # an event can come back from both questions; keep it once
                key = (ev["title"], ev["start"], ev["calendar"])
                if key not in seen:
                    seen.add(key)
                    unique.append(ev)
            events = expand(unique, start, end)
            out = {"from": _iso(start), "to": _iso(end), "count": len(events), "events": events}
            problems = [f"{t['calendar']}: {t['error']}" for t in timing if t.get("error")]
            if problems:
                out["incomplete"] = problems  # say so instead of silently missing events
            out["timing"] = timing
            return out
        title = _text(args, "title", 200)
        start, end = _when(args, "start"), _when(args, "end")
        if end <= start or end - start > timedelta(days=14):
            raise MacError("an event must end after it starts (and last at most 14 days)")
        return self.run("calendar.add", {"title": title, "start": _iso(start), "end": _iso(end), "calendar": cal,
                                         "location": _text(args, "location", 200, required=False),
                                         "notes": _text(args, "notes", 2000, required=False)})

    def handle_reminders(self, action: str, args: dict, ctx: CallContext) -> Any:
        lst = _text(args, "list", 100, required=False) or None
        if action == "list":
            items = self.run("reminders.list", {"list": lst, "include_completed": args.get("include_completed") is True})
            items.sort(key=lambda r: (r["due"] is None, r["due"] or "", r["title"]))
            return {"count": len(items), "reminders": items[:MAX_ITEMS]}
        title = _text(args, "title", 200)
        if action == "add":
            due = _when(args, "due", required=False)
            return self.run("reminders.add", {"title": title, "list": lst, "due": _iso(due) if due else None,
                                              "notes": _text(args, "notes", 2000, required=False)})
        r = self.run("reminders.complete", {"title": title, "list": lst})
        if r.get("error") == "not_found":
            raise MacError(f"no open reminder is called exactly “{title}”")
        if r.get("error") == "ambiguous":
            raise MacError(f"more than one open reminder is called “{title}” (in {', '.join(r['lists'])}): name the list")
        return r

    def handle_notes(self, action: str, args: dict, ctx: CallContext) -> Any:
        if action == "search":
            limit = args.get("limit", 20)
            if not isinstance(limit, int) or not 1 <= limit <= 50:
                raise MacError("'limit' must be 1–50")
            return self.run("notes.search", {"query": _text(args, "query", 200), "limit": limit})
        title = _text(args, "title", 200)
        if action == "read":
            r = self.run("notes.read", {"title": title})
            if r.get("error") == "not_found":
                raise MacError(f"no note is called exactly “{title}” (search for it first)")
            if r.get("error") == "ambiguous":
                raise MacError(f"{r['count']} notes are called “{title}”: rename one or be more specific")
            r["truncated"] = len(r["content"]) > MAX_NOTE_CHARS
            r["content"] = r["content"][:MAX_NOTE_CHARS]
            return r
        body = _text(args, "body", MAX_NOTE_CHARS)
        return self.run("notes.create", {"title": title, "html": _html(f"{title}\n{body}"),
                                         "folder": _text(args, "folder", 100, required=False) or None})

    def handle_mail(self, action: str, args: dict, ctx: CallContext) -> Any:
        to = args.get("to")
        if isinstance(to, str):
            to = [to]
        if not isinstance(to, list) or not 1 <= len(to) <= 20 or not all(isinstance(x, str) and EMAIL.match(x.strip()) for x in to):
            raise MacError("'to' must be 1–20 email addresses")
        return self.run("mail.draft", {"to": [x.strip() for x in to], "subject": _text(args, "subject", 300),
                                       "body": _text(args, "body", 50_000)})

    def handle_apps(self, action: str, args: dict, ctx: CallContext) -> Any:
        name = _text(args, "name", 80)
        if not re.fullmatch(r"[\w .&+'()-]+", name):
            raise MacError("'name' must be an app name like Safari or Music")
        return self.run("apps.open", {"name": name})

    # ---- after a crash: did the add happen? -------------------------------------------------------------
    def _reconcile(self, app: str):
        from ..core.tools import RECONCILE_DONE, RECONCILE_NOT_DONE

        def check(args: dict, op_id: str) -> str:
            try:
                if app == "calendar":
                    q = {"title": args["title"], "start": _iso(_when(args, "start"))}
                elif app == "reminders":
                    q = {"title": args["title"], "list": args.get("list")}
                else:
                    q = {"title": args["title"]}
                found = self.run(f"{app}.find", q)["found"]
            except Exception:
                return "unknown"
            return RECONCILE_DONE if found else RECONCILE_NOT_DONE
        return check


def available() -> bool:
    return sys.platform == "darwin"
