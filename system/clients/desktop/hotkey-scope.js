// gBox's game hotkeys while a native game window docked in gBox has the keyboard (F2 save, F3 autoplay, F4 load, F5 reset,
// Shift/Ctrl+F2 slot, Ctrl+I eyedropper, Alt+Enter / F11 full screen). The docked game owns the keyboard focus, so the keys
// never reach gBox's pages and have to be Electron global shortcuts, which Windows delivers system-wide. They are held ONLY
// while a game is docked AND gBox (or the game docked inside it) is the foreground window: the moment another application
// (Blender, a browser, ...) comes to the front they are released, so that application gets every key as if gBox weren't
// running. The foreground state comes from winembed.py (EVENT_SYSTEM_FOREGROUND + a 100 ms recheck) and the window's
// blur / minimize events; with no report at all the keys stay released (unknown = another app is in front).
const shouldHold = ({ docked, front }) => !!(docked && front);

module.exports = function hotkeyScope({ globalShortcut, keys, onKey }) {
  let docked = false, front = false, held = false;
  function apply() {
    const want = shouldHold({ docked, front });
    if (want === held) return held;
    held = want;
    for (const [k, a] of Object.entries(keys)) {
      try { if (want) globalShortcut.register(k, () => onKey(a)); else globalShortcut.unregister(k); } catch {}
    }
    return held;
  }
  return {
    setDocked(on) { docked = !!on; return apply(); },          // a native game is docked in gBox (or captured into it)
    setFront(on) { front = !!on; return apply(); },            // gBox / its docked game is the foreground window
    release() { docked = false; front = false; return apply(); },   // quit: nothing stays registered
    get held() { return held; },
    get docked() { return docked; },
  };
};
module.exports.shouldHold = shouldHold;
