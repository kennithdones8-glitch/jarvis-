"""ANALYZE, EXPERIMENT and the read-only views: the intelligence tournament, the simulation lab, capability
discovery, self-inspection and the knowledge graph. None of it changes JARVIS; it produces evidence, experiment
records and proposals.
"""

from __future__ import annotations

import ast
import json
import re
import threading
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any

from ..core.util import new_id, now_iso
from . import WINDOW_DAYS, Autonomy

PKG = Path(__file__).resolve().parents[1]          # src/jarvis
STATIC = PKG / "server" / "static"


# ---- the intelligence tournament ------------------------------------------------------------------------------------
def tournament(kernel) -> dict[str, Any]:
    """Evidence-based profiles per model: benchmark pass rates by category (isolated runs) and real chat outcomes
    (answer checks, latency, your ratings). The recommendation is only a suggestion; routing never changes by itself.
    A bigger or paid model is not assumed better: it has to win on the evidence."""
    from ..bench import history

    db = kernel.db
    since = (datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)).isoformat()
    profiles: dict[str, dict[str, Any]] = defaultdict(lambda: {"replies": 0, "verified": 0, "seconds": [], "helpful": 0,
                                                                "not_helpful": 0, "bench": {}})
    for r in db.query("SELECT model, verdict, seconds FROM outcomes WHERE kind = 'reply' AND model IS NOT NULL AND created_at >= ?", (since,)):
        p = profiles[r["model"]]
        p["replies"] += 1
        p["verified"] += r["verdict"] == "verified"
        if r["seconds"] is not None:
            p["seconds"].append(r["seconds"])
    for r in db.query("SELECT model, rating FROM feedback WHERE model IS NOT NULL AND created_at >= ?", (since,)):
        profiles[r["model"]]["helpful" if r["rating"] == 1 else "not_helpful"] += 1
    runs = []
    try:
        runs = history.runs(Path(kernel.home) / "bench-results")
    except Exception:  # noqa: BLE001 - no runs yet, or an unreadable folder: profiles without benchmark data
        runs = []
    for run in runs[:10]:
        label = "bench:" + ",".join(run.get("models") or ["?"]) if isinstance(run.get("models"), list) else f"bench:{run.get('models')}"
        p = profiles[label]
        for cat, v in run["categories"].items():
            b = p["bench"].setdefault(cat, {"passed": 0, "scored": 0, "runs": 0})
            b["passed"] += v["passed"]
            b["scored"] += v["scored"]
            b["runs"] += 1
    out = []
    for model, p in profiles.items():
        secs = p.pop("seconds")
        out.append({"model": model, **p, "median_s": round(median(secs), 2) if secs else None,
                    "check_rate": round(p["verified"] / p["replies"], 3) if p["replies"] else None})
    rec = None
    contenders = [x for x in out if x["replies"] >= 5 and x["check_rate"] is not None]
    if len(contenders) >= 2:
        best = max(contenders, key=lambda x: (x["check_rate"], -(x["median_s"] or 99)))
        worst = min(contenders, key=lambda x: x["check_rate"])
        if best["model"] != worst["model"] and best["check_rate"] - worst["check_rate"] >= 0.2:
            rec = {"text": f"{best['model']} passed the answer check {best['check_rate']:.0%} of the time against "
                           f"{worst['check_rate']:.0%} for {worst['model']}. Consider routing more chat to it.",
                   "evidence": {best["model"]: best["replies"], worst["model"]: worst["replies"]}}
    return {"window_days": WINDOW_DAYS, "profiles": sorted(out, key=lambda x: -(x["replies"] + sum(b["scored"] for b in x["bench"].values()))),
            "recommendation": rec, "bench_runs": len(runs)}


# ---- the simulation lab ---------------------------------------------------------------------------------------------
KINDS = {
    "replay": "Routing replay: on your recorded answers, how a routing choice would have scored (recorded data only; "
              "no model is called, nothing leaves the Mac).",
    "drill": "Recovery drills: break a throwaway JARVIS on purpose and check it recovers (a temporary folder; your "
             "data is never touched).",
    "bench_compare": "Benchmark comparison: compare your two latest benchmark runs (results already on disk).",
    "trial": "Change trial (tier 6): run the full test suite and linter on a branch or commit in a throwaway copy of "
             "JARVIS and compare with your current code. Never merges or pushes.",
}


class LabError(ValueError):
    pass


class Lab:
    """Every experiment has an objective, a baseline, a hypothesis, an environment, criteria, results, a comparison
    and a recommendation. Only the kinds above exist, and each runs in isolation from your real JARVIS."""

    _running: set[str] = set()

    def __init__(self, kernel):
        self.kernel = kernel
        self.db = kernel.db

    def list(self) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM experiments ORDER BY created_at DESC LIMIT 50")
        return [{**dict(r), "results": json.loads(r["results"]) if r["results"] else None} for r in rows]

    def start(self, kind: str, *, by: str, background: bool = True, ref: str | None = None, baseline: str = "HEAD") -> str:
        if kind not in KINDS:
            raise LabError("unknown experiment kind")
        if not Autonomy(self.kernel).can("experiment"):
            raise LabError("experiments are paused or not allowed (autonomy settings or the emergency stop)")
        if kind == "trial":
            from . import trial
            if not Autonomy(self.kernel).can("execute"):
                raise LabError("change trials need autonomy tier 6, which can only be switched on from the Mac's terminal "
                               "(`jarvis autonomy enable 6`)")
            if why := trial.available():
                raise LabError(why)
            try:
                trial.resolve(ref or "")
                trial.resolve(baseline)
            except trial.TrialError as exc:
                raise LabError(str(exc)) from None
            self._args = (ref, baseline)
        if self.db.one("SELECT COUNT(*) FROM experiments WHERE state = 'running'")[0]:
            raise LabError("one experiment at a time: another one is running")
        spec = self._spec(kind, getattr(self, "_args", None))
        eid = new_id("exp")
        now = now_iso()
        with self.db.tx() as c:
            c.execute("INSERT INTO experiments (id, kind, objective, hypothesis, baseline, criteria, environment, state, created_at, updated_at) "
                      "VALUES (?,?,?,?,?,?,?, 'running', ?, ?)", (eid, kind, spec["objective"], spec["hypothesis"], spec["baseline"],
                                                                   spec["criteria"], spec["environment"], now, now))
        self.kernel.audit.record("lab.started", actor=by, experiment=eid, kind=kind)
        if background:
            threading.Thread(target=self._run, args=(eid, kind, getattr(self, "_args", None)), name=f"jarvis-lab-{eid}", daemon=True).start()
        else:
            self._run(eid, kind, getattr(self, "_args", None))
        return eid

    def _spec(self, kind: str, args: tuple | None = None) -> dict[str, str]:
        if kind == "trial":
            ref, base = args
            return {"objective": f"Find out whether {ref} is safe to merge.",
                    "hypothesis": f"{ref} passes every test that passes on {base}, and the linter stays clean.",
                    "baseline": f"{base} (committed code; uncommitted edits are not included)",
                    "criteria": "No test newly failing, no errors, linter clean.",
                    "environment": "Two throwaway git worktrees under JARVIS's data folder, removed afterwards."}
        if kind == "replay":
            return {"objective": "Find which model gives the most reliable chat answers on your own recorded questions.",
                    "hypothesis": "One available model passes the answer check clearly more often than the others.",
                    "baseline": "Your current routing, as recorded.", "criteria": "Answer-check pass rate; at least 5 answers per model.",
                    "environment": "Recorded outcomes only (no model calls)."}
        if kind == "drill":
            return {"objective": "Confirm JARVIS still recovers safely from crashes, a tampered log and a lost database.",
                    "hypothesis": "Every recovery drill passes on the current code.", "baseline": "The last drill run.",
                    "criteria": "All drills pass.", "environment": "Throwaway JARVIS folders in a temporary directory."}
        return {"objective": "Measure whether the latest change helped or hurt the benchmark.",
                "hypothesis": "The newest run scores at least as well as the one before.", "baseline": "The previous benchmark run.",
                "criteria": "Pass rate per category; no category drops.", "environment": "Benchmark results already on disk."}

    def _finish(self, eid: str, state: str, results: dict[str, Any], recommendation: str) -> None:
        with self.db.tx() as c:
            c.execute("UPDATE experiments SET state = ?, results = ?, recommendation = ?, updated_at = ? WHERE id = ?",
                      (state, json.dumps(results, default=str)[:20000], recommendation, now_iso(), eid))
        self.kernel.audit.record("lab.finished", experiment=eid, state=state)

    def _run(self, eid: str, kind: str, args: tuple | None = None) -> None:
        try:
            if kind == "trial":
                from . import trial
                r = trial.run(args[0], args[1], work=Path(self.kernel.home) / "trials", data=Path(self.kernel.home))
                return self._finish(eid, "done" if r["ok"] else "failed", r, trial.recommendation(r))
            if kind == "replay":
                from . import Pipeline
                Pipeline(self.kernel).ingest()   # bring outcomes up to date with the audit log first
                t = tournament(self.kernel)
                rows = [p for p in t["profiles"] if p["replies"]]
                enough = [p for p in rows if p["replies"] >= 5]
                if len(enough) < 2:
                    return self._finish(eid, "done", {"models": rows, "comparison": "not enough data"},
                                        "Not enough recorded answers yet (5 per model, from 2 models) to compare. Nothing to change.")
                return self._finish(eid, "done", {"models": rows, "comparison": t["recommendation"]},
                                    (t["recommendation"] or {}).get("text") or "No model is clearly better on your answers. Keep the current routing.")
            if kind == "drill":
                from .. import drill
                res = drill.run()
                rows = [{"name": r.name, "ok": r.passed, "detail": r.detail[:300], "seconds": round(r.seconds, 1)} for r in res]
                bad = [r["name"] for r in rows if not r["ok"]]
                return self._finish(eid, "done" if not bad else "failed", {"drills": rows, "passed": len(rows) - len(bad), "total": len(rows)},
                                    "All recovery drills pass. Nothing to change." if not bad else
                                    f"Investigate: {', '.join(bad)} failed. A proposal with the details is worth opening.")
            from ..bench import history
            out = Path(self.kernel.home) / "bench-results"
            runs = history.runs(out) if out.is_dir() else []
            if len(runs) < 2:
                return self._finish(eid, "done", {"runs": len(runs)}, "Fewer than two benchmark runs on disk: run `jarvis bench` twice to compare.")
            new, old = runs[0], runs[1]
            drops = [c for c, v in new["categories"].items() if c in old["categories"] and old["categories"][c]["scored"]
                     and v["scored"] and v["passed"] / v["scored"] < old["categories"][c]["passed"] / old["categories"][c]["scored"]]
            return self._finish(eid, "done", {"before": old, "after": new, "dropped": drops},
                                "No category dropped." if not drops else f"These categories dropped: {', '.join(drops)}. Look at them before keeping the change.")
        except Exception as exc:  # noqa: BLE001 - an experiment that crashes is a failed experiment, with the reason
            self._finish(eid, "failed", {"error": f"{type(exc).__name__}: {exc}"[:500]}, "The experiment itself failed; nothing was changed.")


# ---- capability discovery -------------------------------------------------------------------------------------------
def discover(kernel, facts: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """What JARVIS could already do here but doesn't use. Recommendations only: nothing is installed or switched on."""
    cfg = kernel.model_config
    out = []
    def add(key: str, title: str, why: str, cost: str, privacy: str, how: str, on: bool) -> None:
        out.append({"key": key, "title": title, "why": why, "cost": cost, "privacy": privacy, "how": how, "available": on})
    available = facts.get("models_available", []) if facts else []
    add("local-models", "A second local model", "A second local model makes the tournament and routing replay meaningful and keeps answers on the Mac.",
        "$0", "stays on the Mac", "Install with `ollama pull <model>` and list it under [providers.ollama] in jarvis.toml.", len(available) >= 2)
    add("voice", "Voice input", "Talk to JARVIS from the dashboard; speech is transcribed on the Mac by whisper.cpp.",
        "$0", "stays on the Mac", "`uv run jarvis voice setup` prints the steps.", bool(facts and facts.get("voice")))
    add("backups", "Automatic encrypted backups", "Versioned backups make every change reversible.", "$0", "stays on the Mac",
        "`uv run jarvis backup now`, then backups run on their own.", bool(facts and facts.get("backups")))
    add("touch-id", "Touch ID for approvals", "Each approval asks for your fingerprint, not just the browser's sign-in.", "$0",
        "stays on the Mac", "Systems → Set up Touch ID.", bool(facts and facts.get("touch_id")))
    add("coding-self-test", "Run code before answering", "Code answers are tested in a sandbox before you see them.", "$0",
        "stays on the Mac", "`[coding] self_test = true` in jarvis.toml.", bool((getattr(cfg, "coding", None) or {}).get("self_test", False)))
    add("iphone", "iPhone companion", "Approve and ask from your phone over your private network.", "$0", "your tailnet only",
        "`uv run jarvis remote enable`.", bool(facts and facts.get("iphone")))
    return out


# ---- self-inspection -------------------------------------------------------------------------------------------------
_ROUTE = re.compile(r'"(/api/[a-z_/{}()\\w+-]+)"')


def architecture() -> dict[str, Any]:
    """JARVIS's real structure, read from its own source (read-only): Python modules and their imports, the
    dashboard's scripts and their imports, the API routes and the database tables."""
    nodes, edges = [], []
    for f in sorted(PKG.rglob("*.py")):
        if "__pycache__" in f.parts:
            continue
        rel = f.relative_to(PKG.parent).with_suffix("")
        name = ".".join(rel.parts).removesuffix(".__init__")
        group = rel.parts[1] if len(rel.parts) > 2 else "core"
        text = f.read_text(encoding="utf-8", errors="replace")
        nodes.append({"id": name, "kind": "python", "group": group, "lines": text.count("\n") + 1})
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        pkg = name.rsplit(".", 1)[0] if not f.name == "__init__.py" else name
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and n.level:
                base = pkg.split(".")
                base = base[: len(base) - (n.level - 1)] if n.level > 1 else base
                target = ".".join(base + ([n.module] if n.module else []))
                edges.append({"from": name, "to": target, "rel": "imports"})
            elif isinstance(n, ast.ImportFrom) and n.module and n.module.startswith("jarvis"):
                edges.append({"from": name, "to": n.module, "rel": "imports"})
    ids = {n["id"] for n in nodes}
    edges = [e for e in edges if e["to"] in ids and e["from"] != e["to"]]
    for f in sorted(STATIC.glob("*.js")):
        text = f.read_text(encoding="utf-8", errors="replace")
        nodes.append({"id": f"static/{f.name}", "kind": "frontend", "group": "dashboard", "lines": text.count("\n") + 1})
        for m in re.findall(r'from "/static/([\w.-]+)"', text):
            edges.append({"from": f"static/{f.name}", "to": f"static/{m}", "rel": "imports"})
    app = (PKG / "server" / "app.py").read_text()
    routes = sorted({r for r in _ROUTE.findall(app)})
    from ..core.db import MIGRATIONS
    tables = sorted({t for m in MIGRATIONS for t in re.findall(r"CREATE (?:VIRTUAL )?TABLE (\w+)", m)})
    nodes += [{"id": f"api{r}", "kind": "api", "group": "api", "lines": 0} for r in routes]
    nodes += [{"id": f"db.{t}", "kind": "table", "group": "database", "lines": 0} for t in tables]
    edges += [{"from": "jarvis.server.app", "to": f"api{r}", "rel": "serves"} for r in routes]
    edges += [{"from": "jarvis.core.db", "to": f"db.{t}", "rel": "stores"} for t in tables]
    edges += [{"from": "static/app.js", "to": "jarvis.server.app", "rel": "calls"}]
    largest = sorted((n for n in nodes if n["lines"]), key=lambda n: -n["lines"])[:5]
    fan_in = Counter(e["to"] for e in edges if e["rel"] == "imports")
    return {"nodes": nodes, "edges": edges, "routes": len(routes), "tables": len(tables),
            "largest": [{"id": n["id"], "lines": n["lines"]} for n in largest],
            "most_depended_on": [{"id": k, "importers": v} for k, v in fan_in.most_common(5)]}


# ---- the knowledge graph ---------------------------------------------------------------------------------------------
def _norm(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2}


def knowledge_graph(kernel, *, limit: int = 120) -> dict[str, Any]:
    """Memories, lessons, models, missions and proposals as one graph. Every node says what kind of knowledge it is
    (stated by you, inferred, hypothesis, outdated, confirmed) and where it came from. Near-duplicate memories are
    linked as such; lessons with opposite conclusions about the same subject are linked as a contradiction."""
    db = kernel.db
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    mems = db.query("SELECT id, text, kind, origin, confidence, created_at, verified_at FROM memories ORDER BY created_at DESC LIMIT ?", (limit // 2,))
    words = {}
    for m in mems:
        nodes[f"memory:{m['id']}"] = {"id": f"memory:{m['id']}", "kind": "memory", "label": m["text"][:80],
                                      "status": "user" if m["origin"] == "explicit" else ("confirmed" if m["verified_at"] else "inferred"),
                                      "confidence": m["confidence"], "since": m["created_at"]}
        words[m["id"]] = _norm(m["text"])
    ids = list(words)
    for i, a in enumerate(ids):           # near-duplicates (shared words), a cheap local check
        for b in ids[i + 1:]:
            wa, wb = words[a], words[b]
            if wa and wb and len(wa & wb) / len(wa | wb) >= 0.6:
                edges.append({"from": f"memory:{a}", "to": f"memory:{b}", "rel": "possible duplicate"})
    subjects: dict[str, list] = defaultdict(list)
    for les in db.query("SELECT * FROM lessons WHERE state = 'active' ORDER BY last_seen DESC LIMIT ?", (limit // 3,)):
        nid = f"lesson:{les['key']}"
        nodes[nid] = {"id": nid, "kind": "lesson", "label": les["statement"][:120], "status": les["kind"],
                      "confidence": les["confidence"], "since": les["first_seen"], "polarity": les["polarity"]}
        sid = f"subject:{les['subject']}"
        nodes.setdefault(sid, {"id": sid, "kind": "subject", "label": les["subject"], "status": "fact"})
        edges.append({"from": nid, "to": sid, "rel": "about"})
        subjects[les["subject"]].append((nid, les["polarity"]))
    for subj, ls in subjects.items():
        pos = [n for n, p in ls if p > 0]
        neg = [n for n, p in ls if p < 0]
        edges += [{"from": a, "to": b, "rel": "contradicts"} for a in pos for b in neg]
    for t in db.query("SELECT id, goal, state FROM tasks ORDER BY created_at DESC LIMIT 20"):
        nodes[f"task:{t['id']}"] = {"id": f"task:{t['id']}", "kind": "mission", "label": t["goal"][:80], "status": t["state"]}
    for o in db.query("SELECT ref, model FROM outcomes WHERE kind = 'task' AND model IS NOT NULL ORDER BY created_at DESC LIMIT 40"):
        if f"task:{o['ref']}" in nodes:
            sid = f"subject:{o['model']}"
            nodes.setdefault(sid, {"id": sid, "kind": "subject", "label": o["model"], "status": "fact"})
            edges.append({"from": f"task:{o['ref']}", "to": sid, "rel": "answered by"})
    for p in db.query("SELECT id, title, state FROM proposals ORDER BY updated_at DESC LIMIT 15"):
        nodes[f"proposal:{p['id']}"] = {"id": f"proposal:{p['id']}", "kind": "proposal", "label": p["title"][:80], "status": p["state"]}
    for p in db.query("SELECT id, title, state FROM project_ideas ORDER BY updated_at DESC LIMIT 15"):
        nodes[f"project:{p['id']}"] = {"id": f"project:{p['id']}", "kind": "project", "label": p["title"][:80], "status": p["state"]}
    return {"nodes": list(nodes.values()), "edges": edges,
            "legend": {"user": "you told JARVIS", "confirmed": "confirmed by you", "inferred": "inferred from evidence",
                       "hypothesis": "contested: evidence points both ways", "outdated": "evidence stopped arriving"}}
