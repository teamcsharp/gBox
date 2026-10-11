const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

// Exercise the actual helper in both clients without requesting a real microphone.
const desktop = fs.readFileSync(require.resolve('../clients/desktop/index.html'), 'utf8');
const web = fs.readFileSync(require.resolve('../clients/web/index.html'), 'utf8');
function extract(source) {
  const start = source.indexOf('// ---- microphone device');
  assert.ok(start >= 0, 'helper block not found');
  const tail = source.indexOf('window.addEventListener("resize", close);', start);
  assert.ok(tail >= 0, 'helper tail not found');
  return source.slice(start, source.indexOf('})();', tail) + 5);
}
const plain = value => JSON.parse(JSON.stringify(value));
const event = () => ({ preventDefault() {}, stopPropagation() {} });
function setup({ devices = [], enumerate, mediaMissing = false, denied = false, width = 1200, height = 800, gameRect, anchorRect } = {}) {
  const store = new Map(), listeners = {}, windowListeners = {}, mediaListeners = {};
  let captures = 0, stopped = 0;
  const media = {
    enumerateDevices: enumerate || (async () => devices),
    getUserMedia: async () => {
      captures++; if (denied) throw new Error('Permission denied');
      devices = [{ kind: 'audioinput', deviceId: 'allowed', label: 'Allowed microphone' }];
      return { getTracks: () => [{ stop() { stopped++; } }] };
    },
    addEventListener: (name, fn) => { mediaListeners[name] = fn; },
  };
  function element(tag) {
    return {
      tagName: tag.toUpperCase(), className: '', innerHTML: '', textContent: '',
      children: [], style: {}, attributes: {}, offsetWidth: Math.min(300, width - 16), offsetHeight: Math.min(180, height - 16),
      append(...children) { this.children.push(...children); },
      setAttribute(k, v) { this.attributes[k] = String(v); },
      remove() { this.removed = true; },
      contains(node) { return this === node || this.children.some(child => child.contains?.(node)); },
      querySelectorAll() { return this.children.filter(child => child.tagName === 'BUTTON' && !child.disabled); },
      focus() { document.activeElement = this; },
      getBoundingClientRect: () => anchorRect || ({ left: width - 35, right: width - 5, top: height - 25, bottom: height - 5 }),
    };
  }
  const document = {
    head: element('head'), body: element('body'), activeElement: null,
    createElement: element, addEventListener: (name, fn) => { listeners[name] = fn; },
    getElementById: id => id === 'nativeslot' && gameRect ? { getBoundingClientRect: () => gameRect } : null,
  };
  const window = { addEventListener: (name, fn) => { windowListeners[name] = fn; } };
  const localStorage = { getItem: key => store.get(key) ?? null, setItem: (key, value) => store.set(key, String(value)) };
  vm.runInNewContext(extract(desktop), { window, document, navigator: mediaMissing ? {} : { mediaDevices: media }, localStorage, innerHeight: height, innerWidth: width });
  const menu = () => document.body.children.filter(child => child.className === 'micmenu' && !child.removed).at(-1);
  return { window, document, store, listeners, windowListeners, mediaListeners, menu, captures: () => captures, stopped: () => stopped,
    open: () => window.gboxMicMenu(element('button'), event()) };
}
const text = menu => menu.children.map(child => child.innerHTML + child.textContent).join('\n');

test('both clients carry the same helper and every recording path uses the saved input', () => {
  assert.equal(extract(desktop), extract(web));
  for (const source of [desktop, web]) {
    const recording = source.replace(extract(source), '');
    const calls = [...recording.matchAll(/navigator\.mediaDevices\.getUserMedia\(([^;]+)\);/g)];
    assert.equal(calls.length, source === desktop ? 3 : 1);
    calls.forEach(call => assert.match(call[1], /^window\.gboxMicAudio\(/));
  }
});
test('system default retains processing options; a chosen microphone is exact', () => {
  const x = setup();
  assert.deepEqual(plain(x.window.gboxMicAudio()), { audio: true });
  assert.deepEqual(plain(x.window.gboxMicAudio({ echoCancellation: true })), { audio: { echoCancellation: true } });
  x.store.set('gbox_mic_device', 'dev2');
  assert.deepEqual(plain(x.window.gboxMicAudio({ noiseSuppression: true, deviceId: 'wrong' })),
    { audio: { noiseSuppression: true, deviceId: { exact: 'dev2' } } });
});
test('menu filters output and default aliases, escapes labels, persists choice and restores default', async () => {
  const x = setup({ devices: [
    { kind: 'audiooutput', deviceId: 'speaker', label: 'Speaker' },
    { kind: 'audioinput', deviceId: 'default', label: 'Default duplicate' },
    { kind: 'audioinput', deviceId: 'dev1', label: '<script>Mic</script>' },
    { kind: 'audioinput', deviceId: 'dev2', label: 'Mic Two' },
  ] });
  await x.open();
  assert.equal(x.menu().attributes.role, 'menu'); // native embed popup cutout recognizes this
  assert.match(text(x.menu()), /&lt;script&gt;Mic/);
  assert.equal(x.menu().children.find(child => child.innerHTML.includes('&lt;script&gt;')).title, '<script>Mic</script>');
  assert.doesNotMatch(text(x.menu()), /Speaker|Default duplicate/);
  x.menu().children.find(child => child.innerHTML.includes('Mic Two')).onclick();
  assert.equal(x.store.get('gbox_mic_device'), 'dev2');
  await x.open();
  assert.equal(x.menu().children.find(child => child.innerHTML.includes('Mic Two')).attributes['aria-checked'], 'true');
  x.menu().children.find(child => child.innerHTML.includes('System default')).onclick();
  assert.deepEqual(plain(x.window.gboxMicAudio()), { audio: true });
  assert.equal(x.captures(), 0);
});
test('opening an unlabeled menu never requests capture; explicit access stops its temporary stream', async () => {
  const x = setup({ devices: [{ kind: 'audioinput', deviceId: 'unknown', label: '' }] });
  await x.open();
  assert.equal(x.captures(), 0);
  assert.match(text(x.menu()), /Microphone 1/);
  await x.menu().children.find(child => child.textContent.startsWith('Allow microphone')).onclick();
  assert.equal(x.captures(), 1); assert.equal(x.stopped(), 1);
  assert.match(text(x.menu()), /Allowed microphone/);
});
test('denied access keeps usable default menu and reports the failure', async () => {
  const x = setup({ denied: true }); await x.open();
  await x.menu().children.find(child => child.textContent.startsWith('Allow microphone')).onclick();
  assert.match(text(x.menu()), /Permission denied/);
  assert.match(text(x.menu()), /System default/);
});
test('insecure or unavailable browser capture does not break menu opening', async () => {
  const x = setup({ mediaMissing: true }); await x.open();
  assert.match(text(x.menu()), /unavailable in this browser context/);
  assert.match(text(x.menu()), /System default/);
});
test('missing saved device is visible and can be reset rather than silently using a different mic', async () => {
  const x = setup(); x.store.set('gbox_mic_device', 'unplugged'); await x.open();
  assert.match(text(x.menu()), /selected microphone is unavailable/);
  x.menu().children.find(child => child.innerHTML.includes('System default')).onclick();
  assert.equal(x.window.gboxMicDevice(), '');
});
test('enumeration errors become a usable status instead of an unhandled rejection', async () => {
  const x = setup({ enumerate: async () => { throw new Error('Device service offline'); } }); await x.open();
  assert.match(text(x.menu()), /Device service offline/);
  assert.equal(x.captures(), 0);
});
test('Escape during enumeration prevents a late dropdown from appearing', async () => {
  let resolve; const x = setup({ enumerate: () => new Promise(r => { resolve = r; }) });
  const pending = x.open(); x.listeners.keydown({ key: 'Escape' }); resolve([]); await pending;
  assert.equal(x.menu(), undefined);
});
test('only the newest async menu survives; outside, resize and device change dismiss it', async () => {
  const waits = []; const x = setup({ enumerate: () => new Promise(resolve => waits.push(resolve)) });
  const old = x.open(), fresh = x.open(); waits[1]([]); await fresh; waits[0]([]); await old;
  assert.equal(x.document.body.children.filter(child => !child.removed).length, 1);
  x.listeners.pointerdown({ target: x.document.body }); assert.equal(x.menu(), undefined);
  const third = x.open(); waits[2]([]); await third; x.windowListeners.resize(); assert.equal(x.menu(), undefined);
  const fourth = x.open(); waits[3]([]); await fourth; x.mediaListeners.devicechange(); assert.equal(x.menu(), undefined);
});
test('menu is bounded on small windows and arrow keys move among device choices', async () => {
  const x = setup({ width: 220, height: 160 }); await x.open(); const m = x.menu();
  assert.ok(parseFloat(m.style.left) >= 8); assert.ok(parseFloat(m.style.left) + m.offsetWidth <= 212);
  assert.ok(parseFloat(m.style.top) >= 8); assert.ok(parseFloat(m.style.top) + m.offsetHeight <= 152);
  m.onkeydown({ key: 'Home', preventDefault() {} }); assert.equal(x.document.activeElement, m.children[1]);
});
test('right-click on desktop dictation does not start or stop an active recording', () => {
  const start = desktop.indexOf('  function bindMic(b, el) {');
  const end = desktop.indexOf('\n  const skip =', start);
  assert.ok(start > 0 && end > start);
  let starts = 0, stops = 0, menus = 0;
  const context = { rec: { stop() { stops++; } }, toggle() { starts++; }, window: { gboxMicMenu() { menus++; } } };
  vm.runInNewContext(desktop.slice(start, end) + '\nthis.bindMic = bindMic;', context);
  const button = {}; context.bindMic(button, {});
  button.onpointerdown({ button: 2 }); button.oncontextmenu(event());
  assert.equal(starts, 0); assert.equal(stops, 0); assert.equal(menus, 1);
});
test('a menu crossing the native game moves fully into the available right sidebar', async () => {
  const game = { left: 16, top: 160, right: 870, bottom: 760 };
  const x = setup({ gameRect: game, anchorRect: { right: 820, top: 100, bottom: 122 } }); await x.open();
  const m = x.menu();
  assert.equal(parseFloat(m.style.left), 878);
  assert.ok(parseFloat(m.style.left) >= game.right && parseFloat(m.style.left) + m.offsetWidth <= 1192);
});
test('left sidebar is used when the right side has no room; nonintersecting menus stay anchored', async () => {
  const x = setup({ width: 900, gameRect: { left: 360, top: 160, right: 884, bottom: 760 },
    anchorRect: { right: 700, top: 100, bottom: 122 } }); await x.open();
  assert.equal(parseFloat(x.menu().style.left), 52);
  const clear = setup({ gameRect: { left: 16, top: 160, right: 500, bottom: 760 },
    anchorRect: { right: 820, top: 100, bottom: 122 } }); await clear.open();
  assert.equal(parseFloat(clear.menu().style.left), 520);
  assert.equal(parseFloat(clear.menu().style.top), 128);
});
