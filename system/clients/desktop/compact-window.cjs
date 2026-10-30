'use strict';

// Keep the existing app, game child, GPU surface and controller route alive while
// the desktop window becomes a small game-only player. No second stream/window.
const DEFAULT_ASPECT = 4 / 3;
const WINDOW_ASPECT = 16 / 9;
const CHROME_RETRY_MS = 2000, CHROME_RETRY_MAX_MS = 30000;
const OVERLAY = { color: '#111114', symbolColor: '#e8e8ee', height: 36 };
const OVERLAY_HIDDEN = { color: '#00000000', symbolColor: '#00000000', height: 0 };
const validAspect = value => Number.isFinite(+value) && +value >= .1 && +value <= 10;
const clamp = (value, lo, hi) => Math.max(lo, Math.min(hi, value));

function wideBounds(bounds) {
  if (!bounds || Math.abs(bounds.width / bounds.height - WINDOW_ASPECT) < .002) return bounds;
  const width = Math.round(bounds.height * WINDOW_ASPECT);
  return { ...bounds, x: bounds.x + bounds.width - width, width };
}

function fitBounds(bounds, aspect, work, width) {
  const w0 = Number.isFinite(+width) ? +width : bounds.width;
  let w = clamp(w0, Math.max(160, Math.ceil(90 * aspect)), Math.max(160, work.width - 16));
  let h = Math.round(w / aspect);
  if (h > work.height - 16) { h = Math.max(90, work.height - 16); w = Math.round(h * aspect); }
  return { x: Math.round(clamp(bounds.x, work.x, work.x + work.width - w)),
    y: Math.round(clamp(bounds.y, work.y, work.y + work.height - h)), width: Math.round(w), height: h };
}

function create({ getWin, screen, nativeChrome = async () => ({ ok: true }), emit = () => {}, schedule = setTimeout, cancel = clearTimeout }) {
  let saved = null, aspect = DEFAULT_ASPECT, queue = Promise.resolve(), compactBounds = null, restoreSeed = null;
  // chrome: the native helper hid the caption controls. A PiP opened while the helper did not answer keeps them in view
  // (chrome false) and asks again, backing off, until it does.
  let chrome = false, retryTimer = null, retryMs = CHROME_RETRY_MS;
  const state = () => ({ on: !!saved, aspect });
  const window = () => { const w = getWin(); if (!w || w.isDestroyed()) throw Error('The gBox window is unavailable.'); return w; };
  const publish = () => { const value = state(); emit(value); return value; };
  const workArea = w => screen.getDisplayMatching(w.getBounds()).workArea;
  const enqueue = run => { const next = queue.then(run); queue = next.catch(() => {}); return next; };
  const later = () => { cancel(retryTimer); retryTimer = saved && !chrome ? schedule(() => { retryTimer = null; rechrome().catch(() => {}); }, retryMs) : null; };
  // Hide (or hide again, for a helper started while the window was already compact) the native caption controls.
  function rechrome() {
    return enqueue(async () => {
      if (!saved) return state();
      const result = await nativeChrome(true).catch(error => ({ ok: false, error: error.message }));
      if (result?.ok) {
        if (!chrome) window().setTitleBarOverlay?.(OVERLAY_HIDDEN);
        chrome = true; retryMs = CHROME_RETRY_MS;
      } else if (!chrome) { retryMs = Math.min(CHROME_RETRY_MAX_MS, retryMs * 2); later(); }
      return state();
    });
  }

  async function restoreNow() {
    if (!saved) return state();
    const w = window(), before = saved;
    compactBounds = w.getBounds();
    // A failed native restore must leave the mode recoverable for a second try. Controls the helper never hid (it did
    // not answer when the PiP opened) need no answer to come back.
    const result = await nativeChrome(false);
    if (!result?.ok && chrome) throw Error(result?.error || 'Could not restore the gBox window controls.');
    cancel(retryTimer); retryTimer = null; chrome = false; retryMs = CHROME_RETRY_MS;
    w.setAspectRatio(0);
    w.setMinimumSize(...before.minimum);
    w.setMaximumSize(...before.maximum);
    w.setAlwaysOnTop(before.top);
    w.setTitleBarOverlay?.(OVERLAY);
    w.setBounds(before.bounds);
    if (before.maximized) w.maximize();
    if (before.fullscreen) w.setFullScreen(true);
    saved = null;
    return publish();
  }

  async function updateNow(request = {}) {
    if (!request || typeof request !== 'object') throw Error('Invalid picture-in-picture request.');
    if (!request.on) return restoreNow();
    const w = window();
    if (saved) {
      const nextAspect = validAspect(request.aspect) ? +request.aspect : aspect;
      // Source aspect describes the picture, not the operator's window. A
      // MercMode title switch must only change letterboxing inside these bounds.
      aspect = nextAspect;
      if (Number.isFinite(+request.width)) {
        const bounds = w.getBounds(), windowAspect = bounds.width / bounds.height;
        w.setAspectRatio(windowAspect);
        w.setBounds(fitBounds(bounds, windowAspect, workArea(w), request.width));
      }
      return publish();
    }
    const before = { bounds: w.getNormalBounds(), maximized: w.isMaximized(), fullscreen: w.isFullScreen(),
      top: w.isAlwaysOnTop(), ...restoreSeed, minimum: w.getMinimumSize(), maximum: w.getMaximumSize() };
    try {
      if (before.fullscreen) w.setFullScreen(false);
      if (before.maximized) w.unmaximize();
      // Geometry and the existing game surface do not depend on Python starting
      // or Windows answering the caption helper. Show PiP before that wait.
      chrome = false;
      aspect = validAspect(request.aspect) ? +request.aspect : DEFAULT_ASPECT;
      w.setMinimumSize(160, 90); w.setMaximumSize(0, 0);
      const windowAspect = WINDOW_ASPECT;
      w.setAlwaysOnTop(true); w.setAspectRatio(windowAspect);
      // Electron exposes overlay styling, rather than a runtime visibility API.
      // The native helper removes caption controls; transparent overlay styling
      // also avoids a flash while Chromium processes that style change.
      // Controls the helper could not remove stay visible (never invisible but clickable).
      const work = workArea(w), width = Number.isFinite(+request.width) ? +request.width : compactBounds?.width || 480;
      const candidate = compactBounds || { x: work.x + work.width - width - 24, y: work.y + work.height - width / windowAspect - 24, width };
      w.setBounds(fitBounds(candidate, windowAspect, work, width));
      saved = before; restoreSeed = null; retryMs = CHROME_RETRY_MS;
      publish();
      const result = await nativeChrome(true);
      if (!result?.ok && !result?.unavailable) throw Error(result?.error || 'Could not hide the gBox window controls.');
      chrome = !!result?.ok;
      if (chrome) w.setTitleBarOverlay?.(OVERLAY_HIDDEN);
      if (!validAspect(request.aspect) && validAspect(result?.aspect)) aspect = +result.aspect;
      if (!chrome) later();
      return state();
    } catch (error) {
      // Roll back the same live window; this never touches the emulator process.
      await nativeChrome(false).catch(() => {});
      w.setAspectRatio(0); w.setMinimumSize(...before.minimum); w.setMaximumSize(...before.maximum);
      w.setAlwaysOnTop(before.top); w.setTitleBarOverlay?.(OVERLAY);
      w.setBounds(before.bounds);
      if (before.maximized) w.maximize();
      if (before.fullscreen) w.setFullScreen(true);
      saved = null; chrome = false;
      publish();
      throw error;
    }
  }

  return { state, update: request => enqueue(() => updateNow(request)), restore: () => enqueue(restoreNow), rechrome,
    handoff: () => {
      const w = window();
      return { window: saved || { bounds: w.getNormalBounds(), maximized: w.isMaximized(), fullscreen: w.isFullScreen(), top: w.isAlwaysOnTop() },
        compactBounds: saved ? w.getBounds() : compactBounds };
    },
    seedBounds: (value, restore) => { compactBounds = wideBounds(value) || null; restoreSeed = restore || null; }
  };
}

module.exports = { create, fitBounds, validAspect, wideBounds, CHROME_RETRY_MS, CHROME_RETRY_MAX_MS };
