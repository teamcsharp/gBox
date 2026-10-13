// gBox's global game hotkeys are held only while a game is docked AND gBox is the foreground window (hotkey-scope.js):
// Blender (F2 rename, F3 search, Ctrl+I invert, F11...) or any other app in front gets every key.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const hotkeyScope = require('../clients/desktop/hotkey-scope');

const KEYS = { F2: 'save', F3: 'autoplay', F4: 'load', F5: 'reset', 'Shift+F2': 'slot+', 'CommandOrControl+F2': 'slot-',
  'CommandOrControl+I': 'eyedropper', 'Alt+Enter': 'fullscreen', F11: 'fullscreen' };

function fakeShortcuts() {
  const held = new Map(), log = [];
  return { held, log,
    register(k, fn) { log.push(['+', k]); held.set(k, fn); return true; },
    unregister(k) { log.push(['-', k]); held.delete(k); },
    isRegistered: k => held.has(k) };
}

test('shouldHold: only docked AND in front', () => {
  assert.equal(hotkeyScope.shouldHold({ docked: true, front: true }), true);
  assert.equal(hotkeyScope.shouldHold({ docked: true, front: false }), false);
  assert.equal(hotkeyScope.shouldHold({ docked: false, front: true }), false);
  assert.equal(hotkeyScope.shouldHold({ docked: false, front: false }), false);
});

test('a docked game with gBox in front holds every game key; another app in front holds none', () => {
  const gs = fakeShortcuts(), sent = [];
  const hk = hotkeyScope({ globalShortcut: gs, keys: KEYS, onKey: a => sent.push(a) });
  hk.setDocked(true);
  assert.equal(gs.held.size, 0, 'docked but foreground unknown: nothing registered');
  hk.setFront(true);
  assert.deepEqual([...gs.held.keys()].sort(), Object.keys(KEYS).sort());
  gs.held.get('F3')();
  assert.deepEqual(sent, ['autoplay']);
  hk.setFront(false);                                            // Blender comes to the front
  assert.equal(gs.held.size, 0, 'Blender keeps F2 / F3 / Ctrl+I / F11');
  hk.setFront(true);
  assert.equal(gs.held.size, Object.keys(KEYS).length, 'back in gBox: held again');
});

test('undocking, minimizing (front=false) and quitting release everything; repeats are no-ops', () => {
  const gs = fakeShortcuts();
  const hk = hotkeyScope({ globalShortcut: gs, keys: KEYS, onKey() {} });
  hk.setFront(true);
  assert.equal(gs.held.size, 0, 'gBox in front without a docked game: in-app keys come through before-input-event');
  hk.setDocked(true); hk.setDocked(true);
  const registrations = gs.log.filter(([op]) => op === '+').length;
  assert.equal(registrations, Object.keys(KEYS).length, 'repeated syncs register once');
  hk.setDocked(false);
  assert.equal(gs.held.size, 0);
  hk.setDocked(true); assert.ok(hk.held);
  hk.release();
  assert.equal(gs.held.size, 0); assert.equal(hk.held, false);
});

test('a key another app already owns does not break the rest', () => {
  const gs = fakeShortcuts();
  gs.register = (k, fn) => { if (k === 'F4') throw new Error('taken'); gs.held.set(k, fn); return true; };
  const hk = hotkeyScope({ globalShortcut: gs, keys: KEYS, onKey() {} });
  hk.setDocked(true); hk.setFront(true);
  assert.equal(gs.held.size, Object.keys(KEYS).length - 1);
  hk.setFront(false);
  assert.equal(gs.held.size, 0);
});

test('main.js registers global shortcuts only through the foreground-scoped module', () => {
  const dir = path.join(__dirname, '..', 'clients', 'desktop');
  for (const f of fs.readdirSync(dir).filter(f => f.endsWith('.js') && f !== 'hotkey-scope.js')) {
    const src = fs.readFileSync(path.join(dir, f), 'utf8');
    assert.doesNotMatch(src, /globalShortcut\.register\(/, `${f} registers a global shortcut outside hotkey-scope.js`);
  }
  const main = fs.readFileSync(path.join(dir, 'main.js'), 'utf8');
  assert.match(main, /m\.event === "foreground"\) \{ hotkeys\.setFront\(!!m\.front\)/, 'winembed foreground events drive the scope');
  assert.match(main, /win\.on\("blur", \(\) => \{ hotkeys\.setFront\(false\)/, 'blur releases at once');
  assert.match(main, /win\.on\("minimize", \(\) => hotkeys\.setFront\(false\)\)/);
  assert.match(main, /app\.on\("will-quit", \(\) => \{ hotkeys\.release\(\); try \{ globalShortcut\.unregisterAll\(\)/);
  assert.match(main, /function f3\(on\) \{\r?\n  hotkeys\.setDocked\(on\);/);
});
