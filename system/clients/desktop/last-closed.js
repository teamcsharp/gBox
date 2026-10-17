// Anchor an issue report to the most recently ended game on this PC when nothing is live (#1982).
//
// The operator may close a frozen game before reporting it (it did not crash, they quit because
// it failed), so the report must still name the game and build it was about instead of falling
// back to "no game running" with a null game_id. This is a pure helper so both the desktop shell
// and a node:test can exercise the same selection rule.
(function (root) {
  "use strict";
  function lastClosedSession(all, workerName) {
    const rows = all && all.ok && Array.isArray(all.data) ? all.data : [];
    return rows.filter(s => s && s.state === "ended" && s.game_id &&
        (!workerName || ((s.detail && s.detail.worker_name) || "") === workerName))
      .sort((a, b) => (b.ended || b.started || 0) - (a.ended || a.started || 0))[0] || null;
  }
  const api = { lastClosedSession };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.GBoxLastClosed = api;
})(typeof window !== "undefined" ? window : globalThis);
