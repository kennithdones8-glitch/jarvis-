"""Chess with JARVIS: the rules are exact (perft on the standard test positions), the engine finds mates and never
plays an illegal move, draws are recognised, and the page loads it from this Mac only (no inline code, CSP intact)."""

import json
import shutil
import subprocess

import pytest
from test_dashboard import call

from jarvis.server.app import STATIC

NODE = shutil.which("node")
CHESS = str(STATIC / "chess.js")


def js(code: str):
    if not NODE:
        pytest.skip("node not installed")
    out = subprocess.run([NODE, "-e", f"const C = require({json.dumps(CHESS)});\n{code}"], capture_output=True, text=True,
                         timeout=120, check=True)
    return json.loads(out.stdout)


@pytest.mark.parametrize("fen,depth,nodes", [
    ("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", 3, 8902),
    ("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1", 2, 2039),        # castling, pins, ep
    ("8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1", 3, 2812),                                   # en passant edge cases
    ("r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1", 2, 264),              # promotions
    ("rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8", 2, 1486),
])
def test_perft_matches_the_published_counts(fen, depth, nodes):
    assert js(f"console.log(JSON.stringify(C.perft(C.parseFEN({json.dumps(fen)}), {depth})))") == nodes


def test_engine_finds_mate_in_one_at_every_level_every_time():
    # Easy and Medium sometimes pick a near-best move on purpose; a mate is never "near" anything else (regression:
    # a fail-hard bound once made other root moves tie with the mate, and Medium missed it ~1 time in 3).
    r = js("""
const mv = (fen, lv) => { const m = C.search(C.parseFEN(fen), C.LEVELS[lv]).move; return C.sqName(m.from) + C.sqName(m.to); };
const out = { back: new Set(), queen: new Set() };
for (let i = 0; i < 20; i++) for (const lv of ["easy", "medium", "hard"]) {
  out.back.add(mv("6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1", lv));
  out.queen.add(mv("k7/8/1K6/8/8/8/8/7Q w - - 0 1", lv));
}
console.log(JSON.stringify({ back: [...out.back], queen: [...out.queen] }));""")
    assert r["back"] == ["a1a8"]
    assert set(r["queen"]) <= {"h1h8", "h1b7"}      # both are mate (Qb7 is guarded by the king on b6)


def test_engine_moves_are_always_legal_and_games_end():
    r = js("""
let s = C.parseFEN(C.START), keys = [C.positionKey(s)], plies = 0, st = C.status(s, keys), illegal = 0;
let seed = 7; const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
while (!st.over && plies < 160) {
  const r = C.search(s, { ...C.LEVELS.easy, random: rnd });
  if (!C.legalMoves(s).some((m) => m.from === r.move.from && m.to === r.move.to)) illegal++;
  s = C.make(s, r.move); keys.push(C.positionKey(s)); st = C.status(s, keys); plies++;
}
console.log(JSON.stringify({ illegal, plies }));""")
    assert r["illegal"] == 0 and r["plies"] > 10


def test_draws_and_mates_are_recognised():
    r = js("""
const st = (fen, keys) => C.status(C.parseFEN(fen), keys || []);
const rep = C.positionKey(C.parseFEN("4k3/8/8/8/8/8/8/4K2R w K - 0 1"));
console.log(JSON.stringify({
  stalemate: st("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1"),
  mate: st("6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1"),
  mated: st("R5k1/5ppp/8/8/8/8/5PPP/6K1 b - - 0 1"),
  bare: st("4k3/8/8/8/8/8/8/4KN2 w - - 0 1"),
  fifty: st("4k3/8/8/8/8/8/8/4K2R w K - 100 80"),
  threefold: st("4k3/8/8/8/8/8/8/4K2R w K - 4 10", [rep, "x", rep, "y", rep]),
  noCastleThroughCheck: C.legalMoves(C.parseFEN("4k3/8/8/8/8/8/5r2/4K2R w K - 0 1")).some((m) => m.castle),
  san: C.san(C.parseFEN(C.START), C.legalMoves(C.parseFEN(C.START)).find((m) => C.sqName(m.from) === "g1" && C.sqName(m.to) === "f3")),
}));""")
    assert r["stalemate"] == {"over": True, "result": "½-½", "why": "stalemate"}
    assert r["mate"]["over"] is False
    assert r["mated"] == {"over": True, "result": "1-0", "why": "checkmate"}
    assert r["bare"]["why"] == "insufficient material"
    assert r["fifty"]["why"] == "the 50-move rule"
    assert r["threefold"]["why"] == "threefold repetition"
    assert r["noCastleThroughCheck"] is False and r["san"] == "Nf3"


def test_page_serves_the_engine_and_keeps_the_csp(dash):
    d, *_ = dash
    for path in ("/static/chess.js", "/static/chess-worker.js"):
        status, headers, body = call(d, path)
        assert status == 200 and b"JarvisChess" in body
    status, headers, body = call(d, "/")
    html = body.decode()
    assert '<script src="/static/chess.js" defer></script>' in html and 'data-view="games"' in html
    assert "script-src 'self'" in headers.get("Content-Security-Policy", "")
    assert "<script>" not in html   # no inline code
    worker = (STATIC / "chess-worker.js").read_text()
    assert 'importScripts("/static/chess.js")' in worker and "fetch(" not in worker and "XMLHttpRequest" not in worker
    engine = (STATIC / "chess.js").read_text()
    assert "fetch(" not in engine and "XMLHttpRequest" not in engine and "WebSocket" not in engine
