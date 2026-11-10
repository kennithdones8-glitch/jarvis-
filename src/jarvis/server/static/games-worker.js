"use strict";
// JARVIS's side of Connect Four and Checkers: thinks here, off the page's thread.
importScripts("/static/games.js");
self.onmessage = (e) => {
  const { id, game, state, level } = e.data || {};
  try {
    const G = self.JarvisGames[game === "c4" ? "C4" : "CK"];
    const move = G.best(state, (G.LEVELS[level] || G.LEVELS.medium).depth);
    self.postMessage({ id, game, move });
  } catch (err) {
    self.postMessage({ id, error: String(err) });
  }
};
