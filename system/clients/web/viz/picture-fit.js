/* Fit the game picture (not the frame) to the picture-in-picture window.
   The server measures the frame's black bars (GET /api/sessions/<sid>/picture, gbox/picture_bounds.py); this
   scales the streamed <img> so the picture inside those bars fills the window's height (or width), 1:1 aspect,
   and recentres it. Operator 2026-10-24: RE4's 16:9 picture sits letterboxed in its 4:3 frame, so a 16:9 PiP
   showed bars on every side. Three agreeing measurements change the fit; a black frame (a load) keeps the last. */
(function (root) {
  'use strict';
  const AGREE = 3, MIN_BAR = 0.025;
  function fit(win, frame, content) {
    if (!(win?.w > 0 && win?.h > 0 && frame?.w > 0 && frame?.h > 0)) return null;
    const c = content && content.w > 0 && content.h > 0 ? content : { x: 0, y: 0, w: frame.w, h: frame.h };
    const s = Math.min(win.w / c.w, win.h / c.h);
    return { left: (win.w - c.w * s) / 2 - c.x * s, top: (win.h - c.h * s) / 2 - c.y * s, width: frame.w * s, height: frame.h * s };
  }
  function bars(measurement) {
    const b = measurement?.bars; if (!b || !measurement.content) return null;
    return { top: b.top, bottom: b.bottom, left: b.left, right: b.right };
  }
  function cropped(measurement) {
    const b = bars(measurement); if (!b) return false;
    return b.top + b.bottom >= MIN_BAR * 2 || b.left + b.right >= MIN_BAR * 2;
  }
  function create({ api, current, window: win, apply, delay = ms => new Promise(r => setTimeout(r, ms)) }) {
    let stopped = false, polling = false, sid = null;
    const recent = [];
    async function poll() {
      if (stopped || polling) return;
      const id = current();
      if (id !== sid) { sid = id; recent.length = 0; apply(null); }
      if (!id) return;
      polling = true;
      try {
        const m = await api('/api/sessions/' + encodeURIComponent(id) + '/picture', undefined, 'GET');
        if (stopped || current() !== id) return;
        if (!m?.content) return;                                  // a black frame: keep what is applied
        recent.push(m); if (recent.length > AGREE) recent.shift();
        if (recent.length < AGREE) return;
        const crops = recent.map(cropped);
        if (crops.every(Boolean)) {
          // the smallest bars of the agreeing measurements: never crop more than every frame showed
          const last = recent[recent.length - 1], w = last.w, h = last.h;
          const top = Math.min(...recent.map(r => r.bars.top)), bottom = Math.min(...recent.map(r => r.bars.bottom));
          const left = Math.min(...recent.map(r => r.bars.left)), right = Math.min(...recent.map(r => r.bars.right));
          const content = { x: Math.round(left * w), y: Math.round(top * h), w: Math.round((1 - left - right) * w), h: Math.round((1 - top - bottom) * h) };
          apply(fit(win(), { w, h }, content));
        } else if (crops.every(x => !x)) apply(null);
      } catch { /* the next poll tries again; the applied fit stays */ }
      finally { polling = false; }
    }
    return { poll, refit: () => { if (recent.length >= AGREE) { const r = recent[recent.length - 1]; if (recent.every(cropped)) apply(fit(win(), { w: r.w, h: r.h }, r.content)); } }, stop: () => { stopped = true; } };
  }
  const api = { fit, cropped, create, AGREE, MIN_BAR };
  if (typeof module === 'object' && module.exports) module.exports = api; else root.GBoxPictureFit = api;
})(globalThis);
