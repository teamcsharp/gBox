// Shared, cached reads of the control plane for the desktop shell (#712).
//
// The shell used to fetch the same endpoints independently from many timers: /api/sessions (every session ever played,
// ~950 KB and 0.25-1.3 s per answer) roughly twice a second from the docked-game loop alone, plus the inbox, status bar,
// chat hints and Resident Evil helper. A cachedRead gives every caller one in-flight request and reuses an answer younger
// than its time-to-live, and peek() hands the last good answer to a loop that must not wait on the network (the native
// game's geometry/pop-up sync), refreshing it in the background.
(function (root) {
  "use strict";
  function cachedRead(fetcher, { ttl = 1000, now = () => Date.now() } = {}) {
    let last = null, lastAt = -Infinity, good = null, goodAt = -Infinity, pending = null;
    function refresh() {
      if (pending) return pending;
      pending = Promise.resolve()
        .then(fetcher)
        .then(result => {                       // a rejection is not cached: it reaches every waiting caller once
          last = result; lastAt = now();
          if (result && result.ok) { good = result; goodAt = lastAt; }
          return result;
        })
        .finally(() => { pending = null; });
      return pending;
    }
    // an answer younger than maxAge (an {ok:false} one too, so a down API is not hammered by every caller); 0 = fetch now
    function get(maxAge = ttl) {
      return last && now() - lastAt < maxAge ? Promise.resolve(last) : refresh();
    }
    // the last good answer right away (null before the first one); starts a refresh when it is older than maxAge
    function peek(maxAge = ttl) {
      if (now() - lastAt >= maxAge) refresh().catch(() => {});
      return good;
    }
    function invalidate() { lastAt = -Infinity; goodAt = -Infinity; }
    return { get, peek, refresh, invalidate, age: () => now() - goodAt };
  }
  // poll cadence for a view: fast while it is on screen, slow (badges, counters) while it is not
  function due(lastAt, visible, fastMs, slowMs, now = Date.now()) {
    return now - lastAt >= (visible ? fastMs : slowMs);
  }
  // run fn at most once per frame-ish interval; calls arriving while it runs schedule exactly one more run
  function coalesce(fn, { minMs = 50, schedule = (cb, ms) => setTimeout(cb, ms), now = () => Date.now() } = {}) {
    let queued = false, running = false, again = false, lastRun = -Infinity;
    async function run() {
      queued = false;
      if (running) { again = true; return; }
      running = true; lastRun = now();
      try { await fn(); } catch {} finally {
        running = false;
        if (again) { again = false; trigger(); }
      }
    }
    function trigger() {
      if (queued) return;
      if (running) { again = true; return; }
      queued = true;
      schedule(run, Math.max(0, minMs - (now() - lastRun)));
    }
    return trigger;
  }
  const api = { cachedRead, due, coalesce };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.GBoxLivePoll = api;
})(typeof window !== "undefined" ? window : globalThis);
