/* Keeps every live MJPEG game view (<img src=".../mjpeg?...">) connected.
   An MJPEG <img> whose response errors or never delivers a picture stays black/frozen until the view is rebuilt, while
   the emulator keeps running. This reattaches the stream with backoff instead of leaving the operator a dead view. */
(function (root) {
  const MJPEG = /\/api\/sessions\/[^/?#]+\/mjpeg(?:\?|$)/;
  const isStream = el => !!el && el.tagName === 'IMG' && MJPEG.test(el.getAttribute('src') || '');

  function reconnectUrl(src, attempt) {
    const [path, query = ''] = String(src).split('?');
    const params = new URLSearchParams(query);
    params.set('reconnect', String(attempt));
    return path + '?' + params.toString();
  }

  function createStreamWatchdog({ doc, setTimer = setTimeout, now = Date.now, interval = 4000, blankAfter = 8000,
                                  maxDelay = 10000, log = () => {} } = {}) {
    const state = new WeakMap();
    const info = el => {
      let s = state.get(el);
      if (!s) { s = { attempt: 0, since: now(), pending: false }; state.set(el, s); }
      return s;
    };
    function reconnect(el, reason) {
      const s = info(el);
      if (s.pending || !el.isConnected || !isStream(el)) return false;
      s.pending = true;
      const delay = Math.min(maxDelay, 1000 * 2 ** Math.min(s.attempt, 4));
      setTimer(() => {
        s.pending = false;
        if (!el.isConnected || !isStream(el)) return;
        s.attempt += 1; s.since = now();
        log(`game stream reconnect #${s.attempt} (${reason})`);
        el.setAttribute('src', reconnectUrl(el.getAttribute('src'), s.attempt));
      }, delay);
      return true;
    }
    function onError(event) { if (isStream(event.target)) reconnect(event.target, 'error'); }
    function onLoad(event) { if (isStream(event.target)) { const s = info(event.target); s.attempt = 0; } }
    function sweep() {
      for (const el of doc.querySelectorAll('img')) {
        if (!isStream(el)) continue;
        const s = info(el);
        if (el.naturalWidth > 0) { s.attempt = 0; continue; }
        if (now() - s.since >= blankAfter) reconnect(el, 'no picture');
      }
    }
    function start() {
      doc.addEventListener('error', onError, true);   // <img> error events do not bubble: capture them
      doc.addEventListener('load', onLoad, true);
      const tick = () => { try { sweep(); } finally { setTimer(tick, interval); } };
      setTimer(tick, interval);
    }
    return { start, sweep, reconnect, onError, onLoad };
  }

  const api = { createStreamWatchdog, reconnectUrl, isStream };
  if (typeof module === 'object' && module.exports) module.exports = api;
  else {
    root.gboxStreamWatchdog = api;
    if (root.document) createStreamWatchdog({ doc: root.document, log: m => console.info(m) }).start();
  }
})(typeof window !== 'undefined' ? window : globalThis);
