/* Triple-click the game display: picture-in-picture; triple-click the picture-in-picture window: the full app again
   (operator 2026-10-21). One decision for every surface that reports a triple click: the desktop page's own game
   pictures (click event.detail === 3), the embedded web shell's stream ("gametriple" message) and a docked native game
   window (winembed.py "piptriple"). Single and double clicks never reach it, so the game keeps its input and the PiP
   window keeps its double-click restore. A double click already restores PiP, so the third click of that run lands
   on the full app: the cooldown after every PiP change keeps it from entering PiP again at once. */
(function (root) {
  'use strict';
  const COOLDOWN_MS = 900;
  function create({ now = Date.now, cooldownMs = COOLDOWN_MS } = {}) {
    let changedAt = -Infinity, lastOn = null;
    // every PiP on/off change (any gesture, button or menu) starts the cooldown
    function changed(on) { if (lastOn === null || !!on !== lastOn) { lastOn = !!on; changedAt = now(); } }
    // clicks: the click count of this click; compact: PiP is on; onGame: the click was on the game picture
    function decide({ clicks, compact, onGame, modifiers = false }) {
      if (clicks !== 3 || !onGame || modifiers) return null;
      if (now() - changedAt < cooldownMs) return null;
      changedAt = now();
      return compact ? 'exit' : 'enter';
    }
    return { changed, decide };
  }
  const api = { create, COOLDOWN_MS };
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.GBoxPipGesture = api;
})(globalThis);
