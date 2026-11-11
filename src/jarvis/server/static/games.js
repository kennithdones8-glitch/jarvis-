"use strict";
// JARVIS games besides chess: Connect Four and Checkers (American rules). Rules and opponents written for JARVIS:
// alpha-beta search with simple, honest evaluations. No library, no model, no network. Runs in a Web Worker
// (games-worker.js) and in Node for the tests.
(function (root) {
  // ---------------------------------------------------------------- Connect Four: 7 columns × 6 rows
  // board: 42 cells, index = row * 7 + col, row 0 = top. 0 empty, 1 you-or-first, 2 second.
  const C4 = { COLS: 7, ROWS: 6 };
  C4.empty = () => ({ board: new Array(42).fill(0), turn: 1, moves: 0 });
  C4.legal = (s) => [3, 2, 4, 1, 5, 0, 6].filter((c) => s.board[c] === 0);   // centre first: better pruning
  C4.drop = (s, col) => {
    for (let r = 5; r >= 0; r--) {
      if (s.board[r * 7 + col] === 0) {
        const b = s.board.slice();
        b[r * 7 + col] = s.turn;
        return { board: b, turn: 3 - s.turn, moves: s.moves + 1, last: r * 7 + col };
      }
    }
    return null;
  };
  const LINES = [];
  for (let r = 0; r < 6; r++) for (let c = 0; c < 7; c++)
    for (const [dr, dc] of [[0, 1], [1, 0], [1, 1], [1, -1]]) {
      const cells = [0, 1, 2, 3].map((i) => [r + dr * i, c + dc * i]);
      if (cells.every(([rr, cc]) => rr >= 0 && rr < 6 && cc >= 0 && cc < 7)) LINES.push(cells.map(([rr, cc]) => rr * 7 + cc));
    }
  C4.winner = (s) => {
    for (const l of LINES) { const v = s.board[l[0]]; if (v && l.every((i) => s.board[i] === v)) return { who: v, line: l }; }
    return s.moves >= 42 ? { who: 0, line: [] } : null;   // 0 = draw
  };
  function c4Eval(s, me) {
    let score = 0;
    for (const l of LINES) {
      let mine = 0, theirs = 0;
      for (const i of l) { if (s.board[i] === me) mine++; else if (s.board[i]) theirs++; }
      if (mine && theirs) continue;
      score += [0, 1, 6, 40, 0][mine] - [0, 1, 6, 50, 0][theirs];
    }
    for (let r = 0; r < 6; r++) score += (s.board[r * 7 + 3] === me ? 3 : s.board[r * 7 + 3] ? -3 : 0);
    return score;
  }
  C4.best = (s, depth) => {
    function nm(st, d, a, b) {
      const w = C4.winner(st);
      if (w) return w.who === 0 ? 0 : -100000 - d;   // the side to move has just been beaten (sooner = worse)
      if (d === 0) return c4Eval(st, st.turn);
      for (const c of C4.legal(st)) {
        const v = -nm(C4.drop(st, c), d - 1, -b, -a);
        if (v >= b) return b;
        if (v > a) a = v;
      }
      return a;
    }
    let bestCol = C4.legal(s)[0], bestV = -Infinity;
    for (const c of C4.legal(s)) {
      const v = -nm(C4.drop(s, c), depth - 1, -Infinity, -bestV);
      if (v > bestV) { bestV = v; bestCol = c; }
    }
    return bestCol;
  };
  C4.LEVELS = { easy: { label: "Easy", depth: 2 }, medium: { label: "Medium", depth: 5 }, hard: { label: "Hard", depth: 9 } };

  // ---------------------------------------------------------------- Checkers (American / English draughts)
  // board: 32 dark squares? Simpler: 64 cells, only dark squares used. "b"/"w" men, "B"/"W" kings. Black moves first,
  // from the top (row 0) downward; White from the bottom upward. Captures are compulsory; multi-jumps continue;
  // a man reaching the far row becomes a king and the move ends there.
  const CK = {};
  CK.start = () => {
    const board = new Array(64).fill("");
    for (let r = 0; r < 8; r++) for (let c = 0; c < 8; c++) {
      if ((r + c) % 2 === 1) { if (r < 3) board[r * 8 + c] = "b"; else if (r > 4) board[r * 8 + c] = "w"; }
    }
    return { board, turn: "b", quiet: 0 };
  };
  const side = (p) => (p ? p.toLowerCase() : "");
  const dirs = (p) => (p === "b" ? [[1, -1], [1, 1]] : p === "w" ? [[-1, -1], [-1, 1]] : [[1, -1], [1, 1], [-1, -1], [-1, 1]]);
  const inB = (r, c) => r >= 0 && r < 8 && c >= 0 && c < 8;
  function jumps(board, sq, p, path, taken, out) {
    const r = sq >> 3, c = sq & 7;
    let extended = false;
    for (const [dr, dc] of dirs(p)) {
      const mr = r + dr, mc = c + dc, lr = r + 2 * dr, lc = c + 2 * dc;
      if (!inB(lr, lc)) continue;
      const mid = mr * 8 + mc, land = lr * 8 + lc;
      if (board[mid] && side(board[mid]) !== side(p) && !taken.includes(mid) && board[land] === "") {
        extended = true;
        const crowned = (p === "b" && lr === 7) || (p === "w" && lr === 0);
        const b2 = board.slice(); b2[land] = p; b2[sq] = "";
        if (crowned) out.push({ path: [...path, land], taken: [...taken, mid] });   // crowning ends the move
        else jumps(b2, land, p, [...path, land], [...taken, mid], out);
      }
    }
    if (!extended && taken.length) out.push({ path, taken });
  }
  CK.legal = (s) => {
    const caps = [], steps = [];
    for (let sq = 0; sq < 64; sq++) {
      const p = s.board[sq];
      if (!p || side(p) !== s.turn) continue;
      jumps(s.board, sq, p, [sq], [], caps);
      const r = sq >> 3, c = sq & 7;
      for (const [dr, dc] of dirs(p)) if (inB(r + dr, c + dc) && s.board[(r + dr) * 8 + c + dc] === "") steps.push({ path: [sq, (r + dr) * 8 + c + dc], taken: [] });
    }
    return caps.length ? caps : steps;   // a capture, if any, is compulsory
  };
  CK.play = (s, m) => {
    const b = s.board.slice();
    const from = m.path[0], to = m.path[m.path.length - 1];
    let p = b[from];
    b[from] = "";
    for (const t of m.taken) b[t] = "";
    if ((p === "b" && to >> 3 === 7) || (p === "w" && to >> 3 === 0)) p = p.toUpperCase();
    b[to] = p;
    return { board: b, turn: s.turn === "b" ? "w" : "b", quiet: m.taken.length || p !== s.board[from] ? 0 : s.quiet + 1 };
  };
  CK.status = (s) => {
    if (!CK.legal(s).length) return { over: true, winner: s.turn === "b" ? "w" : "b", why: "no moves left" };
    if (s.quiet >= 80) return { over: true, winner: null, why: "40 moves each without a capture" };
    return { over: false };
  };
  function ckEval(s) {
    let v = 0;
    for (let sq = 0; sq < 64; sq++) {
      const p = s.board[sq];
      if (!p) continue;
      const king = p === p.toUpperCase(), adv = side(p) === "b" ? sq >> 3 : 7 - (sq >> 3);
      const val = (king ? 160 : 100 + adv * 3) + ((sq & 7) > 1 && (sq & 7) < 6 ? 2 : 0);
      v += side(p) === s.turn ? val : -val;
    }
    return v;
  }
  CK.best = (s, depth) => {
    function nm(st, d, a, b) {
      const moves = CK.legal(st);
      if (!moves.length) return -100000 - d;
      if (d === 0) return ckEval(st);
      for (const m of moves) {
        const v = -nm(CK.play(st, m), d - 1, -b, -a);
        if (v >= b) return b;
        if (v > a) a = v;
      }
      return a;
    }
    const moves = CK.legal(s);
    let best = moves[0], bestV = -Infinity;
    for (const m of moves) {
      const v = -nm(CK.play(s, m), depth - 1, -Infinity, -bestV);
      if (v > bestV) { bestV = v; best = m; }
    }
    return best;
  };
  CK.LEVELS = { easy: { label: "Easy", depth: 2 }, medium: { label: "Medium", depth: 5 }, hard: { label: "Hard", depth: 9 } };

  const api = { C4, CK };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.JarvisGames = api;
})(typeof self !== "undefined" ? self : globalThis);
