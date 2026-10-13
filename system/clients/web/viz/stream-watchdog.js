/* Keeps every live MJPEG game view (<img src=".../mjpeg?...">) connected and never lets it go black on a hiccup.
   An MJPEG <img> whose response errors or never delivers a picture stays black/frozen until the view is rebuilt, while
   the emulator keeps running. This reattaches the stream with backoff instead of leaving the operator a dead view.

   Stream stability (docs/stream-stability.md):
   - last good frame: each stream <img> carries the newest server frame (/frame.jpg) as its CSS background, refreshed
     while healthy and on trouble, so an errored, reconnecting or freshly rebuilt view shows the game, not black. A
     view rebuilt for the same machine within a few seconds (a swap's new session) starts from the previous picture.
   - stalls: /stream/health tells a frozen source (worker/encoder stall) from a quiet scene; a small "reconnecting…"
     badge shows while the source is stale or the stream is reattaching, and nothing else changes.
   - reconnect: errors, a view that never got a picture and a long stall reattach the stream with backoff; the old
     picture stays up until the new response delivers. Only a session the server reports ended is left alone. */
(function (root) {
  const MJPEG = /\/api\/sessions\/([^/?#]+)\/mjpeg(?:\?|$)/;
  const isStream = el => !!el && el.tagName === 'IMG' && MJPEG.test(el.getAttribute('src') || '');
  const sessionOf = src => (MJPEG.exec(String(src || '')) || [])[1] || '';

  function reconnectUrl(src, attempt) {
    const [path, query = ''] = String(src).split('?');
    const params = new URLSearchParams(query);
    params.set('reconnect', String(attempt));
    return path + '?' + params.toString();
  }
  function sideUrl(src, tail, extra) {                 // the same session + auth query, another endpoint
    const [path, query = ''] = String(src).split('?');
    const params = new URLSearchParams(query);
    params.delete('reconnect'); params.delete('t');
    for (const [k, v] of Object.entries(extra || {})) params.set(k, String(v));
    const q = params.toString();
    return path.replace(/\/mjpeg$/, tail) + (q ? '?' + q : '');
  }
  const frameUrl = (src, t) => sideUrl(src, '/frame.jpg', { t });
  const healthUrl = src => sideUrl(src, '/stream/health');

  function defaultPreload(env) {
    return url => new Promise((resolve, reject) => {
      if (!env || typeof env.Image !== 'function') return reject(new Error('no Image'));
      const im = new env.Image();
      im.onload = () => resolve(url); im.onerror = () => reject(new Error('frame unavailable'));
      im.src = url;
    });
  }
  function defaultHealth(env) {
    return async src => {
      if (!env || typeof env.fetch !== 'function') return null;
      const r = await env.fetch(healthUrl(src), { cache: 'no-store' });
      if (!r.ok) throw new Error('health ' + r.status);
      return r.json();
    };
  }

  function createStreamWatchdog({ doc, setTimer = setTimeout, now = Date.now, interval = 4000, blankAfter = 8000,
                                  maxDelay = 10000, stallAfter = 3000, reattachAfterStall = 20000,
                                  posterEvery = 15000, carryFor = 5000, log = () => {},
                                  env = typeof window !== 'undefined' ? window : null,
                                  preload = defaultPreload(env), fetchHealth = defaultHealth(env) } = {}) {
    const state = new WeakMap();
    let carry = null;                                  // { url, worker, at }: the picture of a view just removed
    const info = el => {
      let s = state.get(el);
      if (!s) {
        s = { attempt: 0, since: now(), pending: false, trouble: null, stale: false, posterAt: -Infinity,
              poster: null, maxAge: 0, ended: false, badge: null, alt: null, checking: false };
        state.set(el, s);
      }
      return s;
    };

    // --- last good frame ------------------------------------------------------------------------------------
    function setPoster(el, url) {
      const s = info(el); s.poster = url;
      if (!el.style) return;
      el.style.backgroundImage = `url("${url}")`;
      el.style.backgroundSize = 'contain'; el.style.backgroundPosition = 'center'; el.style.backgroundRepeat = 'no-repeat';
    }
    function refreshPoster(el) {
      const s = info(el), src = el.getAttribute('src');
      s.posterAt = now();
      const url = frameUrl(src, s.posterAt);
      // Preload first: a failed background URL would itself paint black over the previous picture.
      return Promise.resolve(preload(url)).then(() => { if (el.isConnected && isStream(el)) setPoster(el, url); },
                                                () => {});
    }
    function seed(el) {                                  // a new stream view: never start from black
      const s = info(el);
      if (s.poster) return;
      const worker = sessionOf(el.getAttribute('src')).split('-')[0];
      if (carry && carry.worker === worker && now() - carry.at <= carryFor) setPoster(el, carry.url);
      refreshPoster(el);
    }

    // --- badge + trouble state --------------------------------------------------------------------------------
    function badge(el, text) {
      const s = info(el);
      if (!text) { if (s.badge) { s.badge.remove?.(); s.badge = null; } return; }
      if (!s.badge && doc.createElement && doc.body) {
        const b = doc.createElement('div');
        b.className = 'gbox-stream-badge'; b.setAttribute?.('role', 'status');
        Object.assign(b.style || {}, { position: 'fixed', zIndex: '40', pointerEvents: 'none', font: '11px system-ui, sans-serif',
          color: '#fff', background: 'rgba(0,0,0,.55)', padding: '2px 8px', borderRadius: '10px', opacity: '.85' });
        doc.body.append(b); s.badge = b;
      }
      if (!s.badge) return;
      s.badge.textContent = text;
      const r = el.getBoundingClientRect?.();
      if (r && s.badge.style) { s.badge.style.left = Math.round(r.left + 8) + 'px'; s.badge.style.top = Math.round(r.top + 8) + 'px';
        s.badge.style.display = r.width > 0 ? 'block' : 'none'; }
    }
    function trouble(el, reason) {
      const s = info(el);
      if (!s.trouble) {
        s.trouble = reason;
        if (s.alt === null && el.getAttribute('alt') != null) { s.alt = el.getAttribute('alt'); el.setAttribute('alt', ''); }
        if (!s.poster) refreshPoster(el);
      }
      badge(el, 'reconnecting…');
    }
    function calm(el) {
      const s = info(el);
      if (s.trouble || s.stale) log(`game stream recovered (${s.trouble || 'stale source'})`);
      s.trouble = null; s.stale = false;
      if (s.alt !== null) { el.setAttribute('alt', s.alt); s.alt = null; }
      badge(el, null);
    }

    function reconnect(el, reason) {
      const s = info(el);
      if (s.pending || s.ended || !el.isConnected || !isStream(el)) return false;
      s.pending = true;
      trouble(el, reason);
      const delay = Math.min(maxDelay, 1000 * 2 ** Math.min(s.attempt, 4));
      setTimer(() => {
        s.pending = false;
        if (!el.isConnected || !isStream(el) || s.ended) return;
        s.attempt += 1; s.since = now();
        log(`game stream reconnect #${s.attempt} (${reason})`);
        // The old picture (or the poster behind a broken one) stays up until the new response delivers.
        el.setAttribute('src', reconnectUrl(el.getAttribute('src'), s.attempt));
      }, delay);
      return true;
    }
    function onError(event) { if (isStream(event.target)) reconnect(event.target, 'error'); }
    function onLoad(event) {
      if (!isStream(event.target)) return;
      const s = info(event.target); s.attempt = 0;
      if (s.trouble === 'error' || s.trouble === 'no picture') calm(event.target);
    }

    async function checkHealth(el) {
      const s = info(el);
      if (s.checking || !fetchHealth) return;
      s.checking = true;
      let h = null, failed = false;
      try { h = await fetchHealth(el.getAttribute('src')); } catch { failed = true; } finally { s.checking = false; }
      if (!el.isConnected || !isStream(el)) return;
      if (failed) { trouble(el, 'server unreachable'); return; }
      if (!h) return;
      if (h.state === 'ended') {                       // the session truly ended: the app shows that, not the watchdog
        s.ended = true; badge(el, null); return;
      }
      const age = h.age_s == null ? null : h.age_s * 1000;
      if (age != null && age >= stallAfter) {
        s.stale = true; s.maxAge = Math.max(s.maxAge, age); badge(el, 'reconnecting…');
        return;
      }
      if (s.trouble === 'server unreachable' || (s.stale && s.maxAge >= reattachAfterStall)) {
        // Frames flow again after the server was unreachable or a long stall: that response may have ended or be
        // wedged, so reattach once (the current picture stays until the new response delivers).
        const why = s.trouble === 'server unreachable' ? 'server back' : `stall of ${Math.round(s.maxAge / 1000)} s`;
        s.maxAge = 0; s.stale = false; s.trouble = null;
        reconnect(el, why);
        return;
      }
      s.maxAge = 0;
      // Fresh source and a picture on screen: whatever was wrong is over (a broken view keeps its badge until its
      // reattached response delivers; the sweep's no-picture rule handles one that never does).
      if (!s.pending && (s.stale || s.trouble) && el.naturalWidth > 0) calm(el);
      else if (!s.pending && !s.trouble && !s.stale) badge(el, null);
    }

    function sweep() {
      for (const el of doc.querySelectorAll('img')) {
        if (!isStream(el)) continue;
        const s = info(el);
        if (s.ended) continue;
        if (!s.poster && s.posterAt === -Infinity) seed(el);
        if (el.naturalWidth > 0) {
          s.attempt = 0;
          if (!s.trouble && !s.stale && now() - s.posterAt >= posterEvery) refreshPoster(el);
        } else if (now() - s.since >= blankAfter) reconnect(el, 'no picture');
        if (s.badge) badge(el, s.badge.textContent);  // follow layout changes
        checkHealth(el);
      }
    }
    function watchDom() {
      const MO = env && env.MutationObserver;
      if (!MO || !doc.documentElement) return;
      new MO(records => {
        for (const r of records) {
          for (const n of r.removedNodes || []) {
            const imgs = n.tagName === 'IMG' ? [n] : (n.querySelectorAll ? [...n.querySelectorAll('img')] : []);
            for (const el of imgs) {
              const s = state.get(el);
              if (s && s.badge) badge(el, null);
              if (s && s.poster && isStream(el)) carry = { url: s.poster, worker: sessionOf(el.getAttribute('src')).split('-')[0], at: now() };
            }
          }
          for (const n of r.addedNodes || []) {
            const imgs = n.tagName === 'IMG' ? [n] : (n.querySelectorAll ? [...n.querySelectorAll('img')] : []);
            for (const el of imgs) if (isStream(el)) seed(el);
          }
        }
      }).observe(doc.documentElement, { childList: true, subtree: true });
    }
    function start() {
      doc.addEventListener('error', onError, true);   // <img> error events do not bubble: capture them
      doc.addEventListener('load', onLoad, true);
      watchDom();
      const tick = () => { try { sweep(); } finally { setTimer(tick, interval); } };
      setTimer(tick, interval);
    }
    return { start, sweep, reconnect, onError, onLoad, checkHealth, seed, state: el => info(el) };
  }

  const api = { createStreamWatchdog, reconnectUrl, isStream, frameUrl, healthUrl, sessionOf };
  if (typeof module === 'object' && module.exports) module.exports = api;
  else {
    root.gboxStreamWatchdog = api;
    if (root.document) createStreamWatchdog({ doc: root.document, log: m => console.info(m),
      fetchHealth: root.GBOX_STREAM_HEALTH === false ? null : undefined }).start();
  }
})(typeof window !== 'undefined' ? window : globalThis);
