"""Data for the eight holographic projections. Each module reads real records only (read-only) and says when it
has nothing; every payload carries a ``basis`` line that the projection shows ("from your task store", "simulation:
recorded data, not real-world outcomes", "estimate").
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

MODULES = ("workflow", "architecture", "neural", "globe", "data", "timeline", "security", "simulation")

# A small built-in gazetteer (country and city names, approximate centre coordinates) for the globe. Places are
# matched in your own conversations and research on this Mac; nothing is looked up online.
PLACES: dict[str, tuple[float, float]] = {
    "united states": (39.8, -98.6), "usa": (39.8, -98.6), "canada": (56.1, -106.3), "mexico": (23.6, -102.5), "brazil": (-14.2, -51.9),
    "argentina": (-38.4, -63.6), "chile": (-35.7, -71.5), "peru": (-9.2, -75.0), "colombia": (4.6, -74.3), "venezuela": (6.4, -66.6),
    "united kingdom": (55.4, -3.4), "uk": (55.4, -3.4), "england": (52.4, -1.5), "scotland": (56.5, -4.2), "wales": (52.1, -3.8),
    "ireland": (53.4, -8.2), "france": (46.2, 2.2), "germany": (51.2, 10.5), "spain": (40.5, -3.7), "portugal": (39.4, -8.2),
    "italy": (41.9, 12.6), "netherlands": (52.1, 5.3), "belgium": (50.5, 4.5), "switzerland": (46.8, 8.2), "austria": (47.5, 14.6),
    "poland": (51.9, 19.1), "sweden": (60.1, 18.6), "norway": (60.5, 8.5), "finland": (61.9, 25.7), "denmark": (56.3, 9.5),
    "greece": (39.1, 21.8), "turkey": (39.0, 35.2), "ukraine": (48.4, 31.2), "russia": (61.5, 105.3), "egypt": (26.8, 30.8),
    "nigeria": (9.1, 8.7), "kenya": (-0.0, 37.9), "south africa": (-30.6, 22.9), "ethiopia": (9.1, 40.5), "morocco": (31.8, -7.1),
    "saudi arabia": (23.9, 45.1), "israel": (31.0, 34.9), "iran": (32.4, 53.7), "iraq": (33.2, 43.7), "united arab emirates": (23.4, 53.8),
    "india": (20.6, 79.0), "pakistan": (30.4, 69.3), "bangladesh": (23.7, 90.4), "china": (35.9, 104.2), "japan": (36.2, 138.3),
    "south korea": (35.9, 127.8), "north korea": (40.3, 127.5), "taiwan": (23.7, 121.0), "vietnam": (14.1, 108.3), "thailand": (15.9, 101.0),
    "indonesia": (-0.8, 113.9), "philippines": (12.9, 121.8), "malaysia": (4.2, 102.0), "singapore": (1.35, 103.8), "australia": (-25.3, 133.8),
    "new zealand": (-40.9, 174.9), "antarctica": (-82.9, 135.0), "mars": None,  # not on Earth: ignored on purpose
    "london": (51.5, -0.13), "paris": (48.86, 2.35), "berlin": (52.52, 13.4), "madrid": (40.42, -3.7), "rome": (41.9, 12.5),
    "amsterdam": (52.37, 4.9), "brussels": (50.85, 4.35), "vienna": (48.2, 16.37), "zurich": (47.37, 8.54), "stockholm": (59.33, 18.07),
    "oslo": (59.91, 10.75), "copenhagen": (55.68, 12.57), "dublin": (53.35, -6.26), "lisbon": (38.72, -9.14), "athens": (37.98, 23.73),
    "istanbul": (41.0, 28.98), "moscow": (55.76, 37.62), "kyiv": (50.45, 30.52), "warsaw": (52.23, 21.01), "prague": (50.08, 14.44),
    "new york": (40.71, -74.0), "los angeles": (34.05, -118.24), "san francisco": (37.77, -122.42), "chicago": (41.88, -87.63),
    "seattle": (47.61, -122.33), "boston": (42.36, -71.06), "washington": (38.9, -77.04), "miami": (25.76, -80.19), "toronto": (43.65, -79.38),
    "vancouver": (49.28, -123.12), "mexico city": (19.43, -99.13), "sao paulo": (-23.55, -46.63), "rio de janeiro": (-22.91, -43.17),
    "buenos aires": (-34.6, -58.38), "cairo": (30.04, 31.24), "lagos": (6.52, 3.38), "nairobi": (-1.29, 36.82), "cape town": (-33.92, 18.42),
    "dubai": (25.2, 55.27), "tel aviv": (32.08, 34.78), "delhi": (28.7, 77.1), "mumbai": (19.08, 72.88), "bangalore": (12.97, 77.59),
    "beijing": (39.9, 116.4), "shanghai": (31.23, 121.47), "hong kong": (22.32, 114.17), "tokyo": (35.68, 139.69), "seoul": (37.57, 126.98),
    "singapore city": (1.29, 103.85), "sydney": (-33.87, 151.21), "melbourne": (-37.81, 144.96), "auckland": (-36.85, 174.76),
    "leeds": (53.8, -1.55), "manchester": (53.48, -2.24), "birmingham": (52.49, -1.89), "edinburgh": (55.95, -3.19), "glasgow": (55.86, -4.25),
}


def _since(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def workflow(dash) -> dict[str, Any]:
    db = dash.kernel.db
    tasks = db.query("SELECT id, goal, state, created_at, updated_at FROM tasks WHERE state NOT IN ('cancelled') "
                     "ORDER BY updated_at DESC LIMIT 12")
    nodes, edges = [], []
    for t in tasks:
        steps = db.query("SELECT id, idx, description, tool, action, state, depends_on FROM steps WHERE task_id = ? ORDER BY idx", (t["id"],))
        verified = db.one("SELECT verdict FROM outcomes WHERE kind = 'task' AND ref = ?", (t["id"],))
        nodes.append({"id": t["id"], "kind": "mission", "label": t["goal"][:70], "state": t["state"],
                      "verified": verified["verdict"] if verified else None})
        for s in steps:
            nodes.append({"id": s["id"], "kind": "step", "label": s["description"][:60], "state": s["state"], "tool": f"{s['tool']}.{s['action']}"})
            edges.append({"from": t["id"], "to": s["id"], "rel": "step"})
            for dep in json.loads(s["depends_on"] or "[]"):
                dep_id = next((x["id"] for x in steps if x["idx"] == dep), None)
                if dep_id:
                    edges.append({"from": dep_id, "to": s["id"], "rel": "needs"})
        for a in db.query("SELECT id, state, tool, action FROM approvals WHERE task_id = ? ORDER BY created_at DESC LIMIT 4", (t["id"],)):
            nodes.append({"id": a["id"], "kind": "approval", "label": f"{a['tool']}.{a['action']}", "state": a["state"]})
            edges.append({"from": t["id"], "to": a["id"], "rel": "checkpoint"})
    return {"nodes": nodes, "edges": edges, "basis": "From the task store: missions, their steps, dependencies and approvals."}


def neural(dash) -> dict[str, Any]:
    from .analysis import knowledge_graph
    g = knowledge_graph(dash.kernel, limit=90)
    routes = Counter()
    for r in dash.kernel.db.query("SELECT model FROM outcomes WHERE model IS NOT NULL AND created_at >= ?", (_since(30),)):
        routes[r["model"]] += 1
    return {**g, "routing": [{"model": m, "answers": n} for m, n in routes.most_common(6)],
            "basis": "Knowledge graph from memories, lessons, missions and proposals. The glow between nodes is "
                     "illustrative; it is not the model's internal computation."}


def globe(dash) -> dict[str, Any]:
    rows = dash.kernel.db.query("SELECT content, created_at FROM records WHERE created_at >= ? "
                                "ORDER BY created_at DESC LIMIT 200", (_since(90),))
    hits: Counter = Counter()
    for r in rows:
        low = r["content"].lower()
        for name, at in PLACES.items():
            if at and re.search(rf"\b{re.escape(name)}\b", low):
                hits[name] += 1
    seen, points = set(), []
    for name, n in hits.most_common(24):
        at = PLACES[name]
        if at in seen:
            continue
        seen.add(at)
        points.append({"name": name.title() if len(name) > 3 else name.upper(), "lat": at[0], "lon": at[1], "mentions": n})
    return {"points": points, "researched": len(rows),
            "basis": "Places named in your conversations and research on this Mac (last 90 days), matched to a built-in list; nothing is looked up online."}


def analytics(dash) -> dict[str, Any]:
    from .analysis import tournament
    t = tournament(dash.kernel)
    series = []
    for p in t["profiles"]:
        if p["replies"]:
            series.append({"label": p["model"], "check_rate": p["check_rate"], "median_s": p["median_s"], "n": p["replies"]})
    bench = []
    for p in t["profiles"]:
        for cat, b in p["bench"].items():
            if b["scored"]:
                bench.append({"label": cat, "rate": round(b["passed"] / b["scored"], 3), "n": b["scored"], "models": p["model"]})
    days = []
    for d in range(13, -1, -1):
        day = (datetime.now(timezone.utc) - timedelta(days=d)).date().isoformat()
        n = dash.kernel.db.one("SELECT COUNT(*) FROM outcomes WHERE substr(created_at, 1, 10) = ?", (day,))[0]
        ok = dash.kernel.db.one("SELECT COUNT(*) FROM outcomes WHERE substr(created_at, 1, 10) = ? AND verdict = 'verified'", (day,))[0]
        days.append({"day": day, "total": n, "verified": ok})
    return {"models": series, "bench": bench, "days": days,
            "basis": "Answer checks and timings per model, benchmark pass rates and verified outcomes per day (UTC)."}


def timeline(dash) -> dict[str, Any]:
    db = dash.kernel.db
    events = []
    for m in (dash._evolution or {}).get("milestones", []):
        if m.get("first_verified"):
            events.append({"at": m["first_verified"], "kind": "milestone", "label": m["title"]})
    for t in db.query("SELECT goal, state, created_at, updated_at FROM tasks ORDER BY created_at DESC LIMIT 30"):
        events.append({"at": t["created_at"], "kind": "mission", "label": t["goal"][:60], "state": t["state"]})
        if t["state"] in ("completed", "failed"):
            events.append({"at": t["updated_at"], "kind": t["state"], "label": t["goal"][:60]})
    for p in db.query("SELECT title, state, created_at, decided_at FROM project_ideas ORDER BY created_at DESC LIMIT 20"):
        events.append({"at": p["created_at"], "kind": "project", "label": p["title"][:60], "state": p["state"]})
    events.sort(key=lambda e: e["at"])
    evo = dash._evolution or {}
    upcoming = []
    if evo.get("next"):
        upcoming.append({"label": f"Stage {evo['next']['tier']} · {evo['next']['name']}", "needs": evo["next"]["needs"],
                         "estimate": None, "note": "No date: stages advance only when milestones verify, so no forecast is made."})
    for t in db.query("SELECT goal FROM tasks WHERE state IN ('queued', 'running', 'planning', 'awaiting_approval', 'blocked', 'paused')"):
        upcoming.append({"label": t["goal"][:60], "needs": None, "estimate": None, "note": "Open mission"})
    return {"events": events[-60:], "upcoming": upcoming,
            "basis": "Milestones, missions and projects with their real dates. Upcoming items have no invented dates."}


def security(dash) -> dict[str, Any]:
    from ..trust import contract
    k = dash.kernel
    c = contract(k).as_dict()
    pending = k.db.query("SELECT id, tool, action, tier, created_at FROM approvals WHERE state = 'pending' ORDER BY created_at DESC LIMIT 10")
    denied = k.db.one("SELECT COUNT(*) FROM audit WHERE event IN ('permission.denied', 'egress.denied', 'device.denied') AND ts >= ?", (_since(7),))[0]
    return {"stop": k.killswitch.state(), "pending": [dict(p) for p in pending], "denied_7d": denied,
            "rings": {"on_its_own": len(c["on_its_own"]), "asks_first": len(c["asks_first"]), "never": len(c["never"])},
            "never": [line["text"] for line in c["never"]][:8], "touch_id": dash.mac.enabled(),
            "audit_ok": next((i["ok"] for i in (dash._health or {}).get("items", []) if i["name"] == "Audit log"), None),
            "basis": "Live from the permission engine, pending approvals and the audit log. Pending means NOT authorized."}


def simulation(dash) -> dict[str, Any]:
    from .analysis import Lab
    exps = Lab(dash.kernel).list()
    return {"experiments": [{"id": e["id"], "kind": e["kind"], "state": e["state"], "objective": e["objective"],
                             "recommendation": e["recommendation"], "results": e["results"], "at": e["created_at"]} for e in exps[:12]],
            "basis": "Simulation and sandbox experiments: recorded data and throwaway copies, not real-world outcomes."}


def architecture(dash) -> dict[str, Any]:
    from .analysis import architecture as arch
    return {**arch(), "basis": "Read from JARVIS's own source code on this Mac (modules, imports, API routes, tables)."}


def data(dash, module: str) -> dict[str, Any]:
    fn = {"workflow": workflow, "architecture": architecture, "neural": neural, "globe": globe, "data": analytics,
          "timeline": timeline, "security": security, "simulation": simulation}.get(module)
    if fn is None:
        raise KeyError(module)
    return {"module": module, **fn(dash)}
