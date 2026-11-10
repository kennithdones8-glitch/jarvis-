"use strict";
// JARVIS's side of a chess game: the engine thinks here, off the page's thread, so the board never freezes.
importScripts("/static/chess.js");
self.onmessage = (e) => {
  const { id, fen, level, type, moves, you } = e.data || {};
  if (type === "review") {   // the coach: grade your moves in a finished (or ongoing) game
    try {
      const out = self.JarvisChess.review(moves || [], you, {}, (done, total) => self.postMessage({ id, progress: [done, total] }));
      self.postMessage({ id, review: out });
    } catch (err) {
      self.postMessage({ id, error: String(err) });
    }
    return;
  }
  try {
    const C = self.JarvisChess;
    const r = C.search(C.parseFEN(fen), C.LEVELS[level] || C.LEVELS.medium);
    self.postMessage({ id, move: r && r.move ? { from: r.move.from, to: r.move.to, promo: r.move.promo || null } : null });
  } catch (err) {
    self.postMessage({ id, error: String(err) });
  }
};
