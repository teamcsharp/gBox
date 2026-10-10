const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync(require.resolve('../clients/desktop/index.html'), 'utf8');
const start = source.indexOf('let playLoadPromise = null;');
const code = source.slice(start, source.indexOf('// settings', start));

function setup(token = async () => 'test-token') {
  const nodes = new Map(), scripts = [], navigations = [], timers = new Map();
  let n = 0;
  function element(id) {
    return { id, dataset: {}, hidden: false, isConnected: true, events: {},
      setAttribute() {}, remove() { this.isConnected = false; nodes.delete(this.id); },
      addEventListener(name, fn) { this.events[name] = fn; },
      executeJavaScript: async script => { scripts.push(script); },
      set src(value) { this.url = value; navigations.push(value); }
    };
  }
  for (const id of ['play', 'playhost', 'playmessage', 'playretry']) nodes.set(id, element(id));
  nodes.get('play').prepend = el => nodes.set(el.id, el);
  const context = vm.createContext({
    $: selector => nodes.get(selector.slice(1)),
    document: { createElement: () => element('wv') },
    gbox: { token }, S: { apiUrl: 'http://localhost:8765/', workerName: 'Test PC' },
    EMB: { sid: 'test-session' }, playLoaded: false,
    URL, URLSearchParams, Promise, console: { error() {} },
    setTimeout: fn => { timers.set(++n, fn); return n; }, clearTimeout: id => timers.delete(id)
  });
  vm.runInContext(code, context);
  return { context, nodes, scripts, navigations, timers, load: () => context.loadPlay() };
}

test('overlapping status callbacks share one authentication and one page navigation', async () => {
  let resolve, calls = 0;
  const x = setup(() => { calls++; return new Promise(r => { resolve = r; }); });
  const a = x.load(), b = x.load();
  assert.equal(a, b);
  await Promise.resolve(); resolve('test-token'); await a;
  assert.equal(calls, 1); assert.equal(x.navigations.length, 1);
  await x.load(); assert.equal(x.navigations.length, 1);
});

test('first navigation already carries authentication, local worker and current session', async () => {
  const x = setup(); await x.load();
  const url = new URL(x.navigations[0]), hash = new URLSearchParams(url.hash.slice(1));
  assert.equal(url.searchParams.get('embedded'), '1');
  assert.equal(url.searchParams.has('token'), false);
  assert.equal(hash.get('token'), 'test-token'); assert.equal(hash.get('worker'), 'Test PC');
  assert.equal(hash.get('session'), 'test-session');
});

test('DOM readiness reveals the initialized page without a reload', async () => {
  const x = setup(); await x.load(); const w = x.nodes.get('wv');
  assert.equal(w.dataset.ready, 'false'); assert.equal(x.nodes.get('playhost').hidden, false);
  await w.events['dom-ready'](); await w.events['dom-ready']();
  assert.equal(w.dataset.ready, 'true'); assert.equal(x.nodes.get('playhost').hidden, true);
  assert.equal(x.timers.size, 0); assert.equal(x.navigations.length, 1);
  assert.equal(x.scripts.some(s => /reload|localStorage/.test(s)), false);
});

test('renderer failures show retry and cannot be hidden by an earlier ready response', async () => {
  const x = setup(); await x.load(); const w = x.nodes.get('wv');
  let resolve; w.executeJavaScript = () => new Promise(r => { resolve = r; });
  const ready = w.events['dom-ready']();
  w.events['render-process-gone']({ reason: 'crashed' }); resolve(); await ready;
  assert.equal(w.dataset.ready, 'false'); assert.equal(x.nodes.get('playhost').hidden, false);
  assert.equal(x.nodes.get('playretry').hidden, false);
  assert.match(x.nodes.get('playmessage').textContent, /stopped displaying/);
});

test('failed initialization, navigation and timeout all offer recovery instead of blanking', async () => {
  for (const failure of ['init', 'navigation', 'timeout']) {
    const x = setup(); await x.load(); const w = x.nodes.get('wv');
    if (failure === 'init') {
      w.executeJavaScript = async () => { throw new Error('gone'); }; await w.events['dom-ready']();
    } else if (failure === 'navigation') w.events['did-fail-load']({ errorCode: -102, isMainFrame: true });
    else [...x.timers.values()][0]();
    assert.equal(w.dataset.ready, 'false'); assert.equal(x.nodes.get('playretry').hidden, false);
    assert.equal(x.nodes.get('playhost').hidden, false);
  }
});

test('canceled navigation and iframe failures do not hide a working page', async () => {
  const x = setup(); await x.load(); const w = x.nodes.get('wv'); await w.events['dom-ready']();
  w.events['did-fail-load']({ errorCode: -3, isMainFrame: true });
  w.events['did-fail-load']({ errorCode: -102, isMainFrame: false });
  assert.equal(w.dataset.ready, 'true'); assert.equal(x.nodes.get('playhost').hidden, true);
});

test('an old view failure cannot cover its replacement with an error', async () => {
  const x = setup(); await x.load(); const old = x.nodes.get('wv');
  x.nodes.get('playretry').onclick(); await x.load();
  await x.nodes.get('wv').events['dom-ready']();
  old.events['render-process-gone']({ reason: 'crashed' });
  assert.equal(x.nodes.get('playhost').hidden, true);
});

test('missing credentials remain retryable and retry replaces only the embedded view', async () => {
  let tok = '';
  const x = setup(async () => tok); await x.load();
  assert.equal(x.navigations.length, 0); assert.equal(x.nodes.get('playretry').hidden, false);
  tok = 'test-token'; x.nodes.get('playretry').onclick(); await x.load();
  const old = x.nodes.get('wv');
  old.events['render-process-gone']({ reason: 'crashed' });
  x.nodes.get('playretry').onclick(); await x.load();
  assert.equal(old.isConnected, false); assert.equal(x.navigations.length, 2);
  assert.equal(x.context.EMB.sid, 'test-session');
});
