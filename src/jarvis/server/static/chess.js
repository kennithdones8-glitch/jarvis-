"use strict";
// JARVIS chess: the full rules and a small engine, written for JARVIS (no library, nothing downloaded, no model, no
// network). It runs in the browser (a Web Worker thinks, so the page never freezes) and in Node for the tests.
//
// Board: 64 squares, 0 = a8 … 63 = h1. Pieces: "PNBRQK" white, "pnbrqk" black, "" empty.
// The engine is alpha-beta search with iterative deepening, a capture search at the leaves, piece-square tables and
// a time limit. Levels change its depth and how often it picks a slightly worse move on purpose.
(function (root) {
  const FILES = "abcdefgh";
  const sqName = (s) => FILES[s & 7] + (8 - (s >> 3));
  const sqOf = (n) => (8 - Number(n[1])) * 8 + FILES.indexOf(n[0]);
  const white = (p) => p !== "" && p === p.toUpperCase();
  const colorOf = (p) => (p === "" ? null : white(p) ? "w" : "b");
  const START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";

  function parseFEN(fen) {
    const [rows, turn, castling, ep, half, full] = fen.trim().split(/\s+/);
    const board = [];
    for (const ch of rows.replace(/\//g, "")) {
      if (/\d/.test(ch)) for (let i = 0; i < Number(ch); i++) board.push("");
      else board.push(ch);
    }
    if (board.length !== 64) throw new Error("bad FEN");
    return { board, turn: turn || "w", castling: castling && castling !== "-" ? castling : "",
             ep: ep && ep !== "-" ? sqOf(ep) : -1, half: Number(half || 0), full: Number(full || 1) };
  }
  function toFEN(s) {
    let out = "";
    for (let r = 0; r < 8; r++) {
      let empty = 0;
      for (let c = 0; c < 8; c++) {
        const p = s.board[r * 8 + c];
        if (p === "") { empty++; continue; }
        if (empty) { out += empty; empty = 0; }
        out += p;
      }
      if (empty) out += empty;
      if (r < 7) out += "/";
    }
    return `${out} ${s.turn} ${s.castling || "-"} ${s.ep >= 0 ? sqName(s.ep) : "-"} ${s.half} ${s.full}`;
  }
  // the part of the FEN that decides repetition: pieces, side to move, castling rights, en passant
  const positionKey = (s) => toFEN(s).split(" ").slice(0, 4).join(" ");

  const KNIGHT = [[-2, -1], [-2, 1], [-1, -2], [-1, 2], [1, -2], [1, 2], [2, -1], [2, 1]];
  const KING = [[-1, -1], [-1, 0], [-1, 1], [0, -1], [0, 1], [1, -1], [1, 0], [1, 1]];
  const ROOK = [[-1, 0], [1, 0], [0, -1], [0, 1]];
  const BISHOP = [[-1, -1], [-1, 1], [1, -1], [1, 1]];
  const on = (r, c) => r >= 0 && r < 8 && c >= 0 && c < 8;

  // is square sq attacked by colour `by`?
  function attacked(board, sq, by) {
    const r = sq >> 3, c = sq & 7, w = by === "w";
    const pr = w ? r + 1 : r - 1;   // a white pawn attacks upwards (towards row 0)
    for (const dc of [-1, 1]) if (on(pr, c + dc) && board[pr * 8 + c + dc] === (w ? "P" : "p")) return true;
    for (const [dr, dc] of KNIGHT) if (on(r + dr, c + dc) && board[(r + dr) * 8 + c + dc] === (w ? "N" : "n")) return true;
    for (const [dr, dc] of KING) if (on(r + dr, c + dc) && board[(r + dr) * 8 + c + dc] === (w ? "K" : "k")) return true;
    const slide = (dirs, pieces) => {
      for (const [dr, dc] of dirs) {
        let rr = r + dr, cc = c + dc;
        while (on(rr, cc)) {
          const p = board[rr * 8 + cc];
          if (p !== "") { if (colorOf(p) === by && pieces.includes(p.toUpperCase())) return true; break; }
          rr += dr; cc += dc;
        }
      }
      return false;
    };
    return slide(ROOK, "RQ") || slide(BISHOP, "BQ");
  }
  const kingSq = (board, color) => board.indexOf(color === "w" ? "K" : "k");
  const inCheck = (s, color = s.turn) => attacked(s.board, kingSq(s.board, color), color === "w" ? "b" : "w");

  function pseudoMoves(s) {
    const out = [], b = s.board, me = s.turn, them = me === "w" ? "b" : "w";
    const add = (from, to, extra = {}) => out.push({ from, to, piece: b[from], captured: b[to], ...extra });
    for (let sq = 0; sq < 64; sq++) {
      const p = b[sq];
      if (p === "" || colorOf(p) !== me) continue;
      const r = sq >> 3, c = sq & 7, t = p.toUpperCase();
      if (t === "P") {
        const dir = me === "w" ? -1 : 1, startRow = me === "w" ? 6 : 1, lastRow = me === "w" ? 0 : 7;
        const push = (from, to, extra) => {
          if ((to >> 3) === lastRow) for (const q of "QRBN") add(from, to, { ...extra, promo: me === "w" ? q : q.toLowerCase() });
          else add(from, to, extra);
        };
        if (on(r + dir, c) && b[(r + dir) * 8 + c] === "") {
          push(sq, (r + dir) * 8 + c);
          if (r === startRow && b[(r + 2 * dir) * 8 + c] === "") add(sq, (r + 2 * dir) * 8 + c, { double: true });
        }
        for (const dc of [-1, 1]) {
          if (!on(r + dir, c + dc)) continue;
          const to = (r + dir) * 8 + c + dc;
          if (b[to] !== "" && colorOf(b[to]) === them) push(sq, to);
          else if (to === s.ep) add(sq, to, { ep: true, captured: me === "w" ? "p" : "P" });
        }
      } else if (t === "N" || t === "K") {
        for (const [dr, dc] of t === "N" ? KNIGHT : KING) {
          if (!on(r + dr, c + dc)) continue;
          const to = (r + dr) * 8 + c + dc;
          if (b[to] === "" || colorOf(b[to]) === them) add(sq, to);
        }
        if (t === "K") {   // castling: rights, empty squares, and not out of, through or into check
          const home = me === "w" ? 60 : 4, [kc, qc] = me === "w" ? ["K", "Q"] : ["k", "q"];
          if (sq === home && !attacked(b, home, them)) {
            if (s.castling.includes(kc) && b[home + 1] === "" && b[home + 2] === "" && b[home + 3] === (me === "w" ? "R" : "r")
                && !attacked(b, home + 1, them) && !attacked(b, home + 2, them)) add(sq, home + 2, { castle: "K" });
            if (s.castling.includes(qc) && b[home - 1] === "" && b[home - 2] === "" && b[home - 3] === "" && b[home - 4] === (me === "w" ? "R" : "r")
                && !attacked(b, home - 1, them) && !attacked(b, home - 2, them)) add(sq, home - 2, { castle: "Q" });
          }
        }
      } else {
        const dirs = t === "R" ? ROOK : t === "B" ? BISHOP : ROOK.concat(BISHOP);
        for (const [dr, dc] of dirs) {
          let rr = r + dr, cc = c + dc;
          while (on(rr, cc)) {
            const to = rr * 8 + cc;
            if (b[to] === "") add(sq, to);
            else { if (colorOf(b[to]) === them) add(sq, to); break; }
            rr += dr; cc += dc;
          }
        }
      }
    }
    return out;
  }

  const CASTLE_SQ = { 0: "q", 7: "k", 56: "Q", 63: "K" };
  function make(s, m) {
    const b = s.board.slice();
    b[m.to] = m.promo || m.piece;
    b[m.from] = "";
    if (m.ep) b[m.to + (s.turn === "w" ? 8 : -8)] = "";
    if (m.castle) {
      const home = s.turn === "w" ? 60 : 4;
      if (m.castle === "K") { b[home + 1] = b[home + 3]; b[home + 3] = ""; }
      else { b[home - 1] = b[home - 4]; b[home - 4] = ""; }
    }
    let castling = s.castling;
    if (m.piece === "K") castling = castling.replace(/[KQ]/g, "");
    if (m.piece === "k") castling = castling.replace(/[kq]/g, "");
    for (const sq of [m.from, m.to]) if (CASTLE_SQ[sq]) castling = castling.replace(CASTLE_SQ[sq], "");
    const pawn = m.piece === "P" || m.piece === "p";
    return { board: b, turn: s.turn === "w" ? "b" : "w", castling,
             ep: m.double ? (m.from + m.to) / 2 : -1,
             half: pawn || m.captured ? 0 : s.half + 1, full: s.full + (s.turn === "b" ? 1 : 0) };
  }

  const legalMoves = (s) => pseudoMoves(s).filter((m) => !inCheck(make(s, m), s.turn));

  function perft(s, depth) {
    if (depth === 0) return 1;
    let n = 0;
    for (const m of legalMoves(s)) n += depth === 1 ? 1 : perft(make(s, m), depth - 1);
    return n;
  }

  function insufficient(b) {
    const rest = b.filter((p) => p !== "" && p.toUpperCase() !== "K");
    if (rest.length === 0) return true;
    return rest.length === 1 && "BN".includes(rest[0].toUpperCase());
  }
  // the game's state, from the position and the keys of earlier positions (for repetition)
  function status(s, history = []) {
    const moves = legalMoves(s);
    if (!moves.length) return inCheck(s) ? { over: true, result: s.turn === "w" ? "0-1" : "1-0", why: "checkmate" }
                                          : { over: true, result: "½-½", why: "stalemate" };
    if (insufficient(s.board)) return { over: true, result: "½-½", why: "insufficient material" };
    if (s.half >= 100) return { over: true, result: "½-½", why: "the 50-move rule" };
    const key = positionKey(s);
    if (history.filter((k) => k === key).length >= 3) return { over: true, result: "½-½", why: "threefold repetition" };
    return { over: false, check: inCheck(s) };
  }

  function san(s, m) {
    if (m.castle) return m.castle === "K" ? "O-O" : "O-O-O";
    const t = m.piece.toUpperCase();
    let out = "";
    if (t === "P") {
      if (m.captured) out += FILES[m.from & 7] + "x";
      out += sqName(m.to);
      if (m.promo) out += "=" + m.promo.toUpperCase();
    } else {
      out += t;
      const rivals = legalMoves(s).filter((x) => x.piece === m.piece && x.to === m.to && x.from !== m.from);
      if (rivals.length) {
        if (rivals.every((x) => (x.from & 7) !== (m.from & 7))) out += FILES[m.from & 7];
        else if (rivals.every((x) => x.from >> 3 !== m.from >> 3)) out += 8 - (m.from >> 3);
        else out += sqName(m.from);
      }
      if (m.captured) out += "x";
      out += sqName(m.to);
    }
    const after = make(s, m);
    if (inCheck(after)) out += legalMoves(after).length ? "+" : "#";
    return out;
  }

  // ---- the engine --------------------------------------------------------------------------------------------------
  const VALUE = { P: 100, N: 320, B: 330, R: 500, Q: 900, K: 0 };
  // piece-square tables from White's side, rank 8 first (row 0)
  const PST = {
    P: [0, 0, 0, 0, 0, 0, 0, 0, 50, 50, 50, 50, 50, 50, 50, 50, 10, 10, 20, 30, 30, 20, 10, 10, 5, 5, 10, 25, 25, 10, 5, 5,
        0, 0, 0, 20, 20, 0, 0, 0, 5, -5, -10, 0, 0, -10, -5, 5, 5, 10, 10, -20, -20, 10, 10, 5, 0, 0, 0, 0, 0, 0, 0, 0],
    N: [-50, -40, -30, -30, -30, -30, -40, -50, -40, -20, 0, 0, 0, 0, -20, -40, -30, 0, 10, 15, 15, 10, 0, -30, -30, 5, 15, 20, 20, 15, 5, -30,
        -30, 0, 15, 20, 20, 15, 0, -30, -30, 5, 10, 15, 15, 10, 5, -30, -40, -20, 0, 5, 5, 0, -20, -40, -50, -40, -30, -30, -30, -30, -40, -50],
    B: [-20, -10, -10, -10, -10, -10, -10, -20, -10, 0, 0, 0, 0, 0, 0, -10, -10, 0, 5, 10, 10, 5, 0, -10, -10, 5, 5, 10, 10, 5, 5, -10,
        -10, 0, 10, 10, 10, 10, 0, -10, -10, 10, 10, 10, 10, 10, 10, -10, -10, 5, 0, 0, 0, 0, 5, -10, -20, -10, -10, -10, -10, -10, -10, -20],
    R: [0, 0, 0, 0, 0, 0, 0, 0, 5, 10, 10, 10, 10, 10, 10, 5, -5, 0, 0, 0, 0, 0, 0, -5, -5, 0, 0, 0, 0, 0, 0, -5,
        -5, 0, 0, 0, 0, 0, 0, -5, -5, 0, 0, 0, 0, 0, 0, -5, -5, 0, 0, 0, 0, 0, 0, -5, 0, 0, 0, 5, 5, 0, 0, 0],
    Q: [-20, -10, -10, -5, -5, -10, -10, -20, -10, 0, 0, 0, 0, 0, 0, -10, -10, 0, 5, 5, 5, 5, 0, -10, -5, 0, 5, 5, 5, 5, 0, -5,
        0, 0, 5, 5, 5, 5, 0, -5, -10, 5, 5, 5, 5, 5, 0, -10, -10, 0, 5, 0, 0, 0, 0, -10, -20, -10, -10, -5, -5, -10, -10, -20],
    K: [-30, -40, -40, -50, -50, -40, -40, -30, -30, -40, -40, -50, -50, -40, -40, -30, -30, -40, -40, -50, -50, -40, -40, -30,
        -30, -40, -40, -50, -50, -40, -40, -30, -20, -30, -30, -40, -40, -30, -30, -20, -10, -20, -20, -20, -20, -20, -20, -10,
        20, 20, 0, 0, 0, 0, 20, 20, 20, 30, 10, 0, 0, 10, 30, 20],
  };
  // score from the side to move's point of view
  function evaluate(s) {
    let score = 0;
    for (let sq = 0; sq < 64; sq++) {
      const p = s.board[sq];
      if (p === "") continue;
      const t = p.toUpperCase(), w = p === t;
      const v = VALUE[t] + PST[t][w ? sq : (7 - (sq >> 3)) * 8 + (sq & 7)];
      score += w ? v : -v;
    }
    return s.turn === "w" ? score : -score;
  }
  const order = (moves) => moves.sort((a, b) =>
    ((b.captured ? 10 * VALUE[b.captured.toUpperCase()] - VALUE[b.piece.toUpperCase()] : 0) + (b.promo ? 800 : 0))
    - ((a.captured ? 10 * VALUE[a.captured.toUpperCase()] - VALUE[a.piece.toUpperCase()] : 0) + (a.promo ? 800 : 0)));

  const MATE = 100000;
  function search(s, opts = {}) {
    const deadline = Date.now() + (opts.timeMs || 1500), maxDepth = opts.depth || 4;
    let nodes = 0, stopped = false;
    const timeUp = () => (++nodes & 1023) === 0 && Date.now() > deadline && (stopped = true);
    function quiesce(st, alpha, beta, ply) {
      if (stopped || timeUp()) return 0;
      const stand = evaluate(st);
      if (stand >= beta) return beta;
      if (stand > alpha) alpha = stand;
      if (ply > 6) return alpha;
      for (const m of order(legalMoves(st).filter((x) => x.captured || x.promo))) {
        const v = -quiesce(make(st, m), -beta, -alpha, ply + 1);
        if (v >= beta) return beta;
        if (v > alpha) alpha = v;
      }
      return alpha;
    }
    function negamax(st, depth, alpha, beta, ply) {
      if (stopped || timeUp()) return 0;
      const moves = legalMoves(st);
      if (!moves.length) return inCheck(st) ? -MATE + ply : 0;
      if (st.half >= 100) return 0;
      if (depth === 0) return quiesce(st, alpha, beta, 0);
      for (const m of order(moves)) {
        const v = -negamax(make(st, m), depth - 1, -beta, -alpha, ply + 1);
        if (v >= beta) return beta;
        if (v > alpha) alpha = v;
      }
      return alpha;
    }
    const root = order(legalMoves(s));
    if (!root.length) return null;
    let best = root[0], scores = [];
    for (let depth = 1; depth <= maxDepth && !stopped; depth++) {
      const done = [];
      let alpha = -Infinity;
      for (const m of root) {
        // Levels that may pick a near-best move need every root move's real score (a full window); otherwise a move
        // that isn't better than the best so far only gets a bound back, so it is marked as strictly worse.
        const prev = alpha;
        let v = -negamax(make(s, m), depth - 1, -Infinity, opts.slack ? Infinity : -alpha, 1);
        if (!opts.slack && done.length && v <= prev) v = prev - 1;
        if (stopped) break;
        done.push({ m, v });
        if (v > alpha) alpha = v;
      }
      if (stopped && done.length < root.length) break;   // keep the last full depth
      done.sort((a, b) => b.v - a.v);
      scores = done;
      best = done[0].m;
      root.sort((a, b) => done.findIndex((x) => x.m === a) - done.findIndex((x) => x.m === b));   // best first next time
      if (done[0].v > MATE - 100) break;   // a forced mate: no need to look further
    }
    // weaker levels sometimes play a near-best move instead (within `slack` centipawns)
    const rnd = opts.random || Math.random;
    if (opts.slack && scores.length > 1 && rnd() < (opts.wander || 0)) {
      const near = scores.filter((x) => x.v >= scores[0].v - opts.slack);
      best = near[Math.floor(rnd() * near.length)].m;
    }
    return { move: best, score: scores.length ? scores[0].v : 0, nodes, all: scores };
  }
  const LEVELS = {
    easy: { label: "Easy", depth: 1, timeMs: 400, slack: 250, wander: 0.6 },
    medium: { label: "Medium", depth: 3, timeMs: 1200, slack: 60, wander: 0.25 },
    hard: { label: "Hard", depth: 5, timeMs: 3000, slack: 0, wander: 0 },
  };

  // Coach: replay a game and grade each of your moves by how much it gave away compared with the engine's best move
  // (centipawns, from your side). Labels: inaccuracy ≥ 60, mistake ≥ 150, blunder ≥ 300; a missed mate is a blunder.
  function review(moves, you, opts = {}, onProgress) {
    const think = { depth: opts.depth || 3, timeMs: opts.timeMs || 4000 };
    let s = parseFEN(START);
    const out = [];
    const total = moves.filter((_, i) => (i % 2 === 0 ? "w" : "b") === you).length;
    let done = 0;
    moves.forEach((u, i) => {
      const m = legalMoves(s).find((x) => x.from === u.from && x.to === u.to && (x.promo || null) === (u.promo || null));
      if (!m) return;
      if (s.turn === you) {
        // one search scores every move at the same depth (full window), so yours and the best are comparable
        const best = search(s, { ...think, slack: 1, wander: 0 });
        const mine = best && best.all.find((x) => x.m.from === m.from && x.m.to === m.to && (x.m.promo || null) === (m.promo || null));
        const played = mine ? mine.v : best ? best.score : 0;
        const loss = Math.max(0, (best ? best.score : 0) - played);
        const label = loss >= 300 || (best && best.score > MATE - 100 && played < MATE - 100) ? "blunder"
          : loss >= 150 ? "mistake" : loss >= 60 ? "inaccuracy" : "good";
        out.push({ ply: i, move: Math.floor(i / 2) + 1, san: san(s, m), label, loss: Math.min(loss, 9999),
                   best: best && label !== "good" ? san(s, best.move) : null });
        done += 1;
        if (onProgress) onProgress(done, total);
      }
      s = make(s, m);
    });
    return out;
  }

  const api = { START, parseFEN, toFEN, positionKey, legalMoves, make, perft, status, san, inCheck, search, evaluate,
                LEVELS, sqName, sqOf, colorOf, review };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.JarvisChess = api;
})(typeof self !== "undefined" ? self : globalThis);
