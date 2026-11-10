"use strict";
// JARVIS's side of a chess game: the engine thinks here, off the page's thread, so the board never freezes.
importScripts("/static/chess.js");
self.onmessage = (e) => {
  const { id, fen, level } = e.data || {};
  try {
    const C = self.JarvisChess;
    const r = C.search(C.parseFEN(fen), C.LEVELS[level] || C.LEVELS.medium);
    self.postMessage({ id, move: r && r.move ? { from: r.move.from, to: r.move.to, promo: r.move.promo || null } : null });
  } catch (err) {
    self.postMessage({ id, error: String(err) });
  }
};
