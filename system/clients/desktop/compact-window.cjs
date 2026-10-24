'use strict';

// Keep the existing app, game child, GPU surface and controller route alive while
// the desktop window becomes a small game-only player. No second stream/window.
const DEFAULT_ASPECT = 4 / 3;
const WINDOW_ASPECT = 16 / 9;
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

function create({ getWin, screen, nativeChrome = async () => ({ ok: true }), emit = () => {} }) {
  let saved = null, aspect = DEFAULT_ASPECT, queue = Promise.resolve(), compactBounds = null, restoreSeed = null;
  const state = () => ({ on: !!saved, aspect });
  const window = () => { const w = getWin(); if (!w || w.isDestroyed()) throw Error('The gBox window is unavailable.'); return w; };
  const publish = () => { const value = state(); emit(value); return value; };
  const workArea = w => screen.getDisplayMatching(w.getBounds()).workArea;
  const enqueue = run => { const next = queue.then(run); queue = next.catch(() => {}); return next; };

  async function restoreNow() {
    if (!saved) return state();
    const w = window(), before = saved;
    compactBounds = w.getBounds();
    // A failed native restore must leave the mode recoverable for a second try.
    const result = await nativeChrome(false);
    if (!result?.ok) throw Error(result?.error || 'Could not restore the gBox window controls.');
    w.setAspectRatio(0);
    w.setMinimumSize(...before.minimum);
    w.setMaximumSize(...before.maximum);
    w.setAlwaysOnTop(before.top);
    w.setTitleBarOverlay?.({ color: '#111114', symbolColor: '#e8e8ee', height: 36 });
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
      const result = await nativeChrome(true);
      if (!result?.ok) throw Error(result?.error || 'Could not hide the gBox window controls.');
      aspect = validAspect(request.aspect) ? +request.aspect : validAspect(result.aspect) ? +result.aspect : DEFAULT_ASPECT;
      w.setMinimumSize(160, 90); w.setMaximumSize(0, 0);
      const windowAspect = WINDOW_ASPECT;
      w.setAlwaysOnTop(true); w.setAspectRatio(windowAspect);
      // Electron exposes overlay styling, rather than a runtime visibility API.
      // The native helper removes caption controls; transparent overlay styling
      // also avoids a flash while Chromium processes that style change.
      w.setTitleBarOverlay?.({ color: '#00000000', symbolColor: '#00000000', height: 0 });
      const work = workArea(w), width = Number.isFinite(+request.width) ? +request.width : compactBounds?.width || 480;
      const candidate = compactBounds || { x: work.x + work.width - width - 24, y: work.y + work.height - width / windowAspect - 24, width };
      w.setBounds(fitBounds(candidate, windowAspect, work, width));
      saved = before; restoreSeed = null;
      return publish();
    } catch (error) {
      // Roll back the same live window; this never touches the emulator process.
      await nativeChrome(false).catch(() => {});
      w.setAspectRatio(0); w.setMinimumSize(...before.minimum); w.setMaximumSize(...before.maximum);
      w.setAlwaysOnTop(before.top); w.setTitleBarOverlay?.({ color: '#111114', symbolColor: '#e8e8ee', height: 36 });
      w.setBounds(before.bounds);
      if (before.maximized) w.maximize();
      if (before.fullscreen) w.setFullScreen(true);
      throw error;
    }
  }

  return { state, update: request => enqueue(() => updateNow(request)), restore: () => enqueue(restoreNow),
    handoff: () => {
      const w = window();
      return { window: saved || { bounds: w.getNormalBounds(), maximized: w.isMaximized(), fullscreen: w.isFullScreen(), top: w.isAlwaysOnTop() },
        compactBounds: saved ? w.getBounds() : compactBounds };
    },
    seedBounds: (value, restore) => { compactBounds = wideBounds(value) || null; restoreSeed = restore || null; }
  };
}

module.exports = { create, fitBounds, validAspect, wideBounds };
