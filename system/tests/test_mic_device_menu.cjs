const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

// The microphone-device helper is duplicated verbatim in the desktop app and the
// web UI.  Extract it from each file and exercise its logic in a stubbed context.
function extract(source) {
  const start = source.indexOf('// ---- microphone device');
  assert.ok(start >= 0, 'helper block not found');
  const anchor = 'window.addEventListener("resize", close);';
  const ai = source.indexOf(anchor, start);
  assert.ok(ai >= 0, 'helper tail not found');
  const end = source.indexOf('})();', ai) + '})();'.length;
  return source.slice(start, end);
}

// Values produced inside the vm context live in a different realm, so normalize
// across the realm boundary before comparing.
const plain = o => JSON.parse(JSON.stringify(o));

function setup({ devices = [], firstEmpty = false } = {}) {
  const store = new Map();
  const localStorage = {
    getItem: k => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
  };

  let getUserMediaCalls = 0;
  const navigator = {
    mediaDevices: {
      getUserMedia: async () => {
        getUserMediaCalls++;
        return { getTracks: () => [{ stop() {} }] };
      },
      enumerateDevices: async () => {
        const out = devices.slice();
        if (firstEmpty) {
          devices = [
            { kind: 'audioinput', deviceId: 'dev1', label: 'Mic One' },
            { kind: 'audioinput', deviceId: 'dev2', label: 'Mic Two' },
          ];
        }
        return out;
      },
    },
  };

  function element(tag) {
    const el = {
      tagName: tag.toUpperCase(), className: '', innerHTML: '', textContent: '',
      children: [], style: {}, offsetWidth: 230, offsetHeight: 120,
      append(...c) { this.children.push(...c); return this; },
      remove() { this.removed = true; },
      contains(node) { return this === node || this.children.some(ch => ch.contains && ch.contains(node)); },
      getBoundingClientRect: () => ({ left: 0, top: 0, right: 100, bottom: 20, width: 100, height: 20 }),
      addEventListener() {},
    };
    return el;
  }
  const document = {
    head: element('head'), body: element('body'),
    createElement: t => element(t), addEventListener() {},
  };
  const window = { addEventListener() {} };

  const context = vm.createContext({
    window, document, navigator, localStorage,
    innerHeight: 800, innerWidth: 1200, console: { error() {} },
    String, Promise,
  });
  vm.runInContext(extract(code), context);
  return { context, window, document, store, getUserMediaCalls: () => getUserMediaCalls };
}

const desktop = fs.readFileSync(require.resolve('../clients/desktop/index.html'), 'utf8');
const web = fs.readFileSync(require.resolve('../clients/web/index.html'), 'utf8');
const code = desktop; // both files carry the same block; the first test cross-checks web

test('desktop and web carry an identical microphone-device helper', () => {
  assert.equal(extract(desktop), extract(web));
});

test('gboxMicAudio returns the plain default when no device is chosen', () => {
  const x = setup();
  assert.deepEqual(plain(x.window.gboxMicAudio()), { audio: true });
  assert.deepEqual(plain(x.window.gboxMicAudio({ echoCancellation: true })), { audio: { echoCancellation: true } });
});

test('gboxMicAudio pins the exact chosen device and merges extra constraints', () => {
  const x = setup();
  x.store.set('gbox_mic_device', 'dev2');
  assert.deepEqual(plain(x.window.gboxMicAudio()), { audio: { deviceId: { exact: 'dev2' } } });
  assert.deepEqual(
    plain(x.window.gboxMicAudio({ echoCancellation: true, noiseSuppression: true })),
    { audio: { deviceId: { exact: 'dev2' }, echoCancellation: true, noiseSuppression: true } },
  );
});

test('right-click menu lists System default and every input, and choosing one persists it', async () => {
  const x = setup({ devices: [
    { kind: 'audioinput', deviceId: 'dev1', label: 'Mic One' },
    { kind: 'audioinput', deviceId: 'dev2', label: 'Mic Two' },
  ] });
  const anchor = x.document.createElement('button');
  await x.window.gboxMicMenu(anchor, { preventDefault() {}, stopPropagation() {} });

  const menu = x.document.body.children.find(c => c.className === 'micmenu');
  assert.ok(menu, 'menu appended to body');
  const text = menu.children.map(c => c.innerHTML).join('\n');
  assert.match(text, /System default/);
  assert.match(text, /Mic One/);
  assert.match(text, /Mic Two/);

  const item = menu.children.find(c => c.innerHTML.includes('Mic Two'));
  assert.ok(item, 'device item present');
  item.onclick();
  assert.equal(x.store.get('gbox_mic_device'), 'dev2');
  assert.deepEqual(plain(x.window.gboxMicAudio()), { audio: { deviceId: { exact: 'dev2' } } });
});

test('first use requests mic permission once so device labels become available', async () => {
  const x = setup({ devices: [{ kind: 'audioinput', deviceId: 'default', label: '' }], firstEmpty: true });
  await x.window.gboxMicMenu(x.document.createElement('button'), { preventDefault() {}, stopPropagation() {} });
  assert.equal(x.getUserMediaCalls(), 1);
  const menu = x.document.body.children.find(c => c.className === 'micmenu');
  const text = menu.children.map(c => c.innerHTML).join('\n');
  assert.match(text, /Mic One/);
});
