/* One game-only presentation, shared by the game menu and the title-bar PiP action. */
(function (root) {
  'use strict';
  const validAspect = n => Number.isFinite(n) && n >= 0.2 && n <= 8;
  function fit(width, height, aspect) {
    aspect = validAspect(aspect) ? aspect : 4 / 3;
    const w = Math.min(width, height * aspect), h = w / aspect;
    return { x: (width - w) / 2, y: (height - h) / 2, w, h };
  }
  function create(io) {
    const state = { on: false, sid: null, local: false, aspect: 4 / 3, returnMode: 'auto' };
    let queue = Promise.resolve();
    const serial = fn => { const next = queue.then(fn); queue = next.catch(() => {}); return next; };
    function clear() {
      if (!state.on) return;
      state.on = false; state.sid = null; state.local = false;
      io.render(state); io.pad(null); io.present();
    }
    function changed(value) {
      if (!value.on) { clear(); return; }
      if (validAspect(value.aspect)) state.aspect = value.aspect;
      if (state.on) { io.render(state); io.present(); }
    }
    function enter() {
      return serial(async () => {
        if (state.on) return state;
        const session = await io.resolve();
        if (!session || !session.sid) throw Error('Start or select an emulation session first.');
        Object.assign(state, { on: true, sid: session.sid, local: !!session.local,
          aspect: validAspect(session.aspect) ? session.aspect : 4 / 3, returnMode: io.mode() });
        try {
          io.render(state); io.pad(state.local ? null : state.sid);
          const result = await io.windowMode({ on: true, ...(validAspect(session.aspect) ? { aspect: session.aspect } : {}) });
          if (!result?.on) throw Error('Picture-in-picture could not open.');
          changed(result); return state;
        } catch (error) {
          await io.windowMode({ on: false }).catch(() => {});
          clear(); throw error;
        }
      });
    }
    function restore() {
      return serial(async () => { const result = await io.windowMode({ on: false }); clear(); return result; });
    }
    function picture(width, height) {
      return serial(async () => {
        if (!state.on || !width || !height || !validAspect(width / height) || Math.abs(width / height - state.aspect) < 0.002) return;
        state.aspect = width / height; io.render(state); io.present();
        return io.windowMode({ on: true, aspect: state.aspect });
      });
    }
    return { state, enter, restore, changed, picture };
  }
  const api = { fit, create };
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.GBoxCompactGame = api;
})(globalThis);
