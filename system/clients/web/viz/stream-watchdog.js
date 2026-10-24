/* Native MJPEG recovery. Server health alone cannot prove that an <img> is still receiving pictures.
   Compare a tiny rendered thumbnail with the latest cached server frame before declaring a client stall.
   Recovery changes only this image connection; it never restarts or pauses the game. */
(function (root) {
  const MJPEG = /\/api\/sessions\/([^/?#]+)\/mjpeg(?:\?|$)/;
  const isStream = el => !!el && el.tagName === 'IMG' && MJPEG.test(el.getAttribute('src') || '');
  const sessionOf = src => (MJPEG.exec(String(src || '')) || [])[1] || '';
  function reconnectUrl(src, attempt) {
    const [path, query = ''] = String(src).split('?'), params = new URLSearchParams(query);
    params.set('reconnect', String(attempt));
    return path + '?' + params.toString();
  }
  function sideUrl(src, tail, extra) {
    const [path, query = ''] = String(src).split('?'), params = new URLSearchParams(query);
    params.delete('reconnect'); params.delete('t');
    for (const [k, v] of Object.entries(extra || {})) params.set(k, String(v));
    const q = params.toString();
    return path.replace(/\/mjpeg$/, tail) + (q ? '?' + q : '');
  }
  const frameUrl = (src, t) => sideUrl(src, '/frame.jpg', { t });
  const healthUrl = src => sideUrl(src, '/stream/health');
  function defaultPreload(env) {
    return (url, { signal } = {}) => new Promise((resolve, reject) => {
      if (!env || typeof env.Image !== 'function') return reject(new Error('no Image'));
      const im = new env.Image(); let done = false;
      const finish = (error) => {
        if (done) return; done = true;
        im.onload = im.onerror = null; signal?.removeEventListener('abort', abort);
        if (error) { im.src = ''; reject(error); } else resolve({ url, image: im });
      };
      const abort = () => finish(new Error('frame cancelled'));
      im.onload = () => finish(); im.onerror = () => finish(new Error('frame unavailable'));
      if (signal?.aborted) return abort();
      signal?.addEventListener('abort', abort, { once: true }); im.src = url;
    });
  }
  function defaultHealth(env) {
    return async (src, { signal } = {}) => {
      if (!env || typeof env.fetch !== 'function') return null;
      const r = await env.fetch(healthUrl(src), { cache: 'no-store', signal });
      if (!r.ok) throw new Error('health ' + r.status);
      return r.json();
    };
  }
  function pictureReader(doc) {
    let canvas;
    return image => {
      if (!image?.naturalWidth) return null;
      try {
        canvas ||= doc.createElement('canvas'); canvas.width = 16; canvas.height = 9;
        const ctx = canvas.getContext('2d', { willReadFrequently: true });
        ctx.drawImage(image, 0, 0, 16, 9);
        const bytes = ctx.getImageData(0, 0, 16, 9).data; let hash = 2166136261;
        for (let i = 0; i < bytes.length; i++) if (i % 4 !== 3) hash = Math.imul(hash ^ (bytes[i] >> 3), 16777619);
        return hash >>> 0;
      } catch { return null; } // cross-origin mini player: bounded connection renewal instead
    };
  }
  function picturePoster(doc) {
    return image => {
      if (!image?.naturalWidth) return null;
      try {
        const canvas = doc.createElement('canvas');
        canvas.width = Math.min(960,image.naturalWidth);
        canvas.height = Math.round(canvas.width*image.naturalHeight/image.naturalWidth);
        canvas.getContext('2d').drawImage(image,0,0,canvas.width,canvas.height);
        return canvas.toDataURL('image/jpeg',.85);
      } catch { return null; }
    };
  }
  // Used by browser input forwarding: releases are always allowed, new presses wait for the viewed stream.
  function inputAllowed(el, sid) {
    if (!isStream(el) || sessionOf(el.getAttribute('src')) !== sid) return true;
    return el.getAttribute('data-stream-state') === 'connected';
  }
  function createStreamWatchdog({ doc, setTimer = setTimeout, clearTimer = clearTimeout, now = Date.now,
    interval = 4000, blankAfter = 8000, maxDelay = 10000, stallAfter = 3000, reattachAfterStall = 20000,
    requestTimeout = 5000, renewAfter = 60000, posterEvery = 15000, carryFor = 5000, log = () => {},
    env = typeof window !== 'undefined' ? window : null, preload = defaultPreload(env),
    fetchHealth = defaultHealth(env), readPicture = pictureReader(doc),
    captureFrame = env?.GBOX_STREAM_CAPTURE_FRAME || picturePoster(doc) } = {}) {
    const state = new WeakMap(), tracked = new Set();
    let carry = null, stopped = false, started = false, loop, observer;
    const keyOf = el => isStream(el) ? healthUrl(el.getAttribute('src')) : '';
    const current = (el, s) => !stopped && el.isConnected && state.get(el) === s && keyOf(el) === s.key;
    function cancelRetry(s) { clearTimer(s.retryTimer); s.pending = false; s.retryGeneration = (s.retryGeneration || 0) + 1; }
    function cancel(s) {
      if (!s) return;
      cancelRetry(s); for (const task of [...s.tasks]) task.cancel();
      s.badge?.remove?.(); s.badge = null;
    }
    function info(el) {
      let s = state.get(el), key = keyOf(el);
      if (!s || s.key !== key) {
        cancel(s);
        s = { key, attempt: 0, since: now(), pending: false, trouble: null, stale: false, posterAt: -Infinity,
          poster: null, ended: false, badge: null, checking: false, healthAt: -Infinity, probing: false, tasks: new Set(),
          hash: null, renderAt: now(), status: null, posterVersion:0, alt: el.getAttribute('alt') };
        state.set(el, s); tracked.add(el);
        status(el, 'connecting');
      }
      return s;
    }
    function bounded(s, operation) {
      return new Promise((resolve, reject) => {
        const controller = typeof AbortController === 'function' ? new AbortController() : null;
        let done = false, timer;
        const finish = (error, value) => {
          if (done) return; done = true; clearTimer(timer); s.tasks.delete(task);
          if (error) { controller?.abort(); reject(error); } else resolve(value);
        };
        const task = { cancel: () => finish(new Error('stream request cancelled')) }; s.tasks.add(task);
        timer = setTimer(() => finish(new Error('stream request timed out')), requestTimeout);
        Promise.resolve().then(() => operation({ signal: controller?.signal })).then(v => finish(null, v), e => finish(e));
      });
    }
    function status(el, value) {
      const s = state.get(el); if (!s) return;
      const changed = s.status !== value; s.status = value;
      if (!s.badge && doc.createElement && doc.body) {
        const b = doc.createElement('div'); b.className = 'gbox-stream-badge'; b.setAttribute?.('role', 'status');
        Object.assign(b.style || {}, { position: 'fixed', zIndex: '40', pointerEvents: 'none', font: '11px system-ui, sans-serif',
          color: '#fff', background: 'rgba(0,0,0,.65)', padding: '2px 8px', borderRadius: '10px' });
        doc.body.append(b); s.badge = b;
      }
      if (s.badge) {
        const text = ({ connecting: 'Connecting...', connected: 'Connected', reconnecting: 'Reconnecting...', ended: 'Session ended' })[value];
        if (s.badge.textContent !== text) s.badge.textContent = text;
        const r = el.getBoundingClientRect?.();
        if (r && s.badge.style) Object.assign(s.badge.style, { left: Math.round(r.left + 8) + 'px', top: Math.round(r.top + 8) + 'px', display: r.width > 0 ? 'block' : 'none' });
      }
      if (changed) {
        el.setAttribute('data-stream-state', value);
        if (env?.CustomEvent) el.dispatchEvent?.(new env.CustomEvent('gbox-stream-state', {
          detail: { session: sessionOf(el.getAttribute('src')), state: value, connected: value === 'connected' }
        }));
      }
    }
    function setPoster(el, url) {
      const s = info(el); s.poster = url; s.posterVersion++;
      if (el.style) Object.assign(el.style, { backgroundImage: `url("${url}")`, backgroundSize: 'contain',
        backgroundPosition: 'center', backgroundRepeat: 'no-repeat' });
    }
    function trouble(el, reason) {
      const s = info(el); s.trouble = reason;
      if (s.alt != null) el.setAttribute('alt', '');
      status(el, 'reconnecting');
    }
    function calm(el) {
      const s = info(el);
      if (s.trouble || s.stale) log(`game stream recovered (${s.trouble || 'stale source'})`);
      cancelRetry(s); s.trouble = null; s.stale = false; s.attempt = 0;
      if (s.alt != null) el.setAttribute('alt', s.alt);
      status(el, 'connected');
    }
    function reconnect(el, reason) {
      const s = info(el);
      if (s.pending || s.ended || !current(el, s)) return false;
      s.pending = true; trouble(el, reason);
      const generation = s.retryGeneration;
      const delay = Math.min(maxDelay, 1000 * 2 ** Math.min(s.attempt, 4));
      s.retryTimer = setTimer(() => {
        if (!current(el, s) || s.ended) return;
        const replace = poster => {
          if (!current(el,s) || s.ended || !s.pending || s.retryGeneration !== generation) return;
          if (typeof poster === 'string' && /^data:image\/(jpeg|png);base64,/.test(poster)) setPoster(el,poster);
          s.pending = false; s.attempt += 1; s.since = now();
          log(`game stream reconnect #${s.attempt} (${reason})`);
          el.setAttribute('src', reconnectUrl(el.getAttribute('src'), s.attempt));
        };
        try {
          const held = captureFrame(el);
          if (held?.then) bounded(s,() => held).then(replace,() => replace(null));
          else replace(held);
        } catch { replace(null); }
      }, delay);
      return true;
    }
    async function refreshPoster(el, compare = false) {
      const s = info(el); if (s.probing || s.ended) return;
      s.probing = true; s.posterAt = now();
      const url = frameUrl(el.getAttribute('src'), s.posterAt), oldHash = s.hash, posterVersion=s.posterVersion;
      try {
        const frame = await bounded(s, opts => preload(url, opts));
        if (!current(el, s) || s.ended) return;
        if (s.posterVersion === posterVersion) setPoster(el, url);
        if (compare && !s.stale) {
          const latest = readPicture(frame?.image), shown = readPicture(el);
          if (latest !== null && shown !== null && latest === shown) { s.hash = shown; s.renderAt = now(); calm(el); }
          else if (latest !== null && shown !== null && shown === oldHash && now() - s.renderAt >= blankAfter)
            reconnect(el, 'picture stopped updating');
        }
      } catch {
        // Keep the poster; a failed probe must not keep a silent image attached forever either.
        if (compare && current(el, s) && now() - s.renderAt >= renewAfter) reconnect(el, 'picture probe unavailable');
      }
      finally { s.probing = false; }
    }
    function seed(el) {
      const s = info(el); if (s.poster || s.probing) return;
      const worker = sessionOf(el.getAttribute('src')).split('-')[0];
      if (carry && carry.worker === worker && now() - carry.at <= carryFor) setPoster(el, carry.url);
      refreshPoster(el);
    }
    async function checkHealth(el) {
      const s = info(el); if (s.checking || !fetchHealth || s.ended || !current(el, s)) return;
      s.checking = true; s.healthAt = now(); const src = el.getAttribute('src');
      try {
        const h = await bounded(s, opts => fetchHealth(src, opts));
        if (!current(el, s) || !h) return;
        if (h.state === 'ended') {
          s.ended = true; cancelRetry(s);
          status(el, el.getAttribute('data-stream-follow') === 'game' ? 'reconnecting' : 'ended');
          return; // the continuity poll supplies the successor URL; keep this frame meanwhile
        }
        const age = h.age_s == null ? null : h.age_s * 1000;
        if (h.worker_online === false || age === null || !Number.isFinite(age) || age >= stallAfter) {
          s.stale = true; trouble(el, 'source stalled');
          if (h.worker_online === false || age === null || !Number.isFinite(age) || age >= reattachAfterStall) reconnect(el, 'source stalled');
          return;
        }
        s.stale = false;
        const shown = readPicture(el);
        if (shown !== null && shown !== s.hash) { s.hash = shown; s.renderAt = now(); calm(el); }
        else if (shown !== null && (s.trouble || now() - s.renderAt >= blankAfter)) await refreshPoster(el, true);
        else if (shown === null && el.naturalWidth > 0) {
          // file:// players can use authenticated IPC health even though canvas pixel reads are forbidden.
          // A healthy source and decoded picture do not need a periodic connection reset (it interrupts playback).
          // Errors, missing first pictures and stale source health still reconnect this opaque image.
          if (!s.pending) calm(el);
        }
        if (!el.naturalWidth && now() - s.since >= blankAfter) reconnect(el, 'no picture');
      } catch { if (current(el, s) && !s.ended) reconnect(el, 'server unreachable'); }
      finally { s.checking = false; }
    }
    function onError(event) { if (isStream(event.target)) reconnect(event.target, 'error'); }
    function onLoad(event) {
      const el = event.target; if (!isStream(el)) return;
      const s = info(el); if (!s.ended && !fetchHealth && el.naturalWidth > 0) calm(el);
    }
    function sweep() {
      if (stopped) return;
      for (const el of tracked) if (!el.isConnected || !isStream(el)) { cancel(state.get(el)); tracked.delete(el); state.delete(el); }
      for (const el of doc.querySelectorAll('img')) {
        if (!isStream(el)) continue;
        const s = info(el); if (s.ended) continue;
        if (!s.poster && s.posterAt === -Infinity) seed(el);
        if (!el.naturalWidth && now() - s.since >= blankAfter) reconnect(el, 'no picture');
        if (!fetchHealth && el.naturalWidth > 0) {
          if (now() - s.since >= renewAfter) reconnect(el, 'connection renewal');
          else if (!s.trouble) calm(el);
        }
        if (!s.trouble && now() - s.posterAt >= posterEvery) refreshPoster(el);
        status(el, s.status); if (now() - s.healthAt >= interval) checkHealth(el);
      }
    }
    function wake() { if (!doc.hidden) sweep(); }
    function start() {
      if (started) return; started = true; stopped = false;
      doc.addEventListener('error', onError, true); doc.addEventListener('load', onLoad, true);
      doc.addEventListener('visibilitychange', wake); env?.addEventListener?.('online', wake);
      if (env?.MutationObserver && doc.documentElement) {
        observer = new env.MutationObserver(records => {
          for (const r of records) for (const n of r.removedNodes || []) {
            const imgs = n.tagName === 'IMG' ? [n] : (n.querySelectorAll ? [...n.querySelectorAll('img')] : []);
            for (const el of imgs) {
              const s = state.get(el);
              if (s?.poster && isStream(el)) carry = { url: s.poster, worker: sessionOf(el.getAttribute('src')).split('-')[0], at: now() };
            }
          }
          sweep();
        });
        observer.observe(doc.documentElement, { childList: true, subtree: true, attributes: true, attributeFilter: ['src'] });
      }
      const tick = () => { if (stopped) return; sweep(); loop = setTimer(tick, interval); };
      tick();
    }
    function stop() {
      stopped = true; started = false; clearTimer(loop); observer?.disconnect();
      doc.removeEventListener?.('error', onError, true); doc.removeEventListener?.('load', onLoad, true);
      doc.removeEventListener?.('visibilitychange', wake); env?.removeEventListener?.('online', wake);
      for (const el of tracked) { cancel(state.get(el)); state.delete(el); } tracked.clear();
    }
    return { start, stop, sweep, reconnect, onError, onLoad, checkHealth, seed, state: el => info(el) };
  }
  const api = { createStreamWatchdog, reconnectUrl, isStream, frameUrl, healthUrl, sessionOf, inputAllowed };
  if (typeof module === 'object' && module.exports) module.exports = api;
  else {
    root.gboxStreamWatchdog = api;
    if (root.document) createStreamWatchdog({ doc: root.document, log: m => console.info(m),
      fetchHealth: root.GBOX_STREAM_FETCH_HEALTH || (root.GBOX_STREAM_HEALTH === false ? null : undefined) }).start();
  }
})(typeof window !== 'undefined' ? window : globalThis);
