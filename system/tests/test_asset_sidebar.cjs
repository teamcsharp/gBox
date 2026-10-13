const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require.resolve('../clients/web/viz/asset-sidebar.js'), 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function setup() {
  const state = { textures: new Map(), revision: 1, disposed: false, busy: false, polling: false, signature: 'old', items: [] };
  const controls = new Map([['.as-sort', { value: 'name' }], ['.as-game', { value: 'DOA2' }],
    ['.as-list', { scrollTop: 0 }], ['.as-changed', { hidden: true }]]);
  const requests = []; let interval, loads = 0, closed = false;
  const context = vm.createContext({ state, URLSearchParams, Date, Map,
    esc: value => String(value ?? '').replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`),
    $: selector => controls.get(selector),
    options: { url: path => path, api(url) { const d = deferred(); requests.push({ url, ...d }); return d.promise; } },
    root: { classList: { contains: () => closed } }, document: { hidden: false },
    setInterval(fn) { interval = fn; return 1; }, load() { loads++; }, query: () => '/api/asset-groups', signature: page => page.signature,
  });
  const start = source.indexOf('const url = path => options.url(path);'), end = source.indexOf('function query(', start);
  assert.ok(start >= 0 && end > start);
  vm.runInContext(source.slice(start, end), context);
  const pollStart = source.indexOf('const interval = setInterval('), pollEnd = source.indexOf('// Apply saved filters', pollStart);
  vm.runInContext(source.slice(pollStart, pollEnd), context);
  const rows = { innerHTML: '' }, element = { dataset: { owner: 'owner-id' }, isConnected: true, querySelector: () => rows };
  return { context, state, requests, rows, element, interval, controls,
    run: code => vm.runInContext(code, context), loads: () => loads, close: () => { closed = true; } };
}

test('both companion categories are counted and labels escape the owner id', () => {
  const x = setup();
  x.context.item = { id: '<unsafe>', texture_count: 2, file_count: 3 };
  assert.match(x.run('textureTree(item)'), /Textures \(2\) \/ Files \(3\)/);
  assert.ok(!x.run('textureTree(item)').includes('<unsafe>'));
  x.context.item = { id: 'files', file_count: 4 };
  assert.match(x.run('textureTree(item)'), /Files \(4\)/);
  assert.ok(!x.run('textureTree(item)').includes('Textures'));
});

test('expanded model fetches all companions without inheriting a model-name search', async () => {
  const x = setup(); x.context.element = x.element;
  const loading = x.run('loadTextures(element)'); await tick();
  const params = new URL('https://fixture.invalid' + x.requests[0].url).searchParams;
  assert.equal(params.get('owner'), 'owner-id'); assert.equal(params.get('limit'), '200');
  assert.equal(params.get('q'), null); assert.equal(params.get('kind'), null);
  const item = (id, kind) => ({ id, kind, name: id, format: 'BIN', game: 'DOA2', size: 20, preview_url: '/preview', added: 1 });
  x.requests[0].resolve({ items: [item('mesh', 'data')], has_more: true }); await tick();
  assert.equal(new URL('https://fixture.invalid' + x.requests[1].url).searchParams.get('offset'), '200');
  x.requests[1].resolve({ items: [item('voice', 'audio')], has_more: false }); await loading;
  assert.equal(x.state.textures.size, 2);
  assert.match(x.rows.innerHTML, /mesh/); assert.match(x.rows.innerHTML, /voice/);
  await x.run('loadTextures(element)'); assert.equal(x.requests.length, 2, 'already-expanded tree stays cached');
});

test('detached, disposed and newer-query trees ignore old results and failures', async () => {
  for (const stale of ['detached', 'disposed', 'revision']) {
    for (const failed of [false, true]) {
      const x = setup(); x.context.element = x.element;
      const loading = x.run('loadTextures(element)'); await tick();
      const before = x.rows.innerHTML;
      if (stale === 'detached') x.element.isConnected = false;
      if (stale === 'disposed') x.state.disposed = true;
      if (stale === 'revision') x.state.revision++;
      if (failed) x.requests[0].reject(new Error('late failure'));
      else x.requests[0].resolve({ items: [], has_more: false });
      await loading;
      assert.equal(x.rows.innerHTML, before, `${stale} ${failed}`); assert.equal(x.state.textures.size, 0);
    }
  }
});

test('failed tree expansion can retry and reports an escaped error', async () => {
  const x = setup(); x.context.element = x.element;
  const first = x.run('loadTextures(element)'); await tick();
  x.requests[0].reject(new Error('<failure>')); await first;
  assert.equal(x.element.dataset.loaded, undefined); assert.match(x.rows.innerHTML, /&#60;failure&#62;/);
  const retry = x.run('loadTextures(element)'); await tick();
  x.requests[1].resolve({ items: [], has_more: false }); await retry;
  assert.match(x.rows.innerHTML, /No companion files/);
});

test('asset change poll is singleflight, retries failure and ignores late close/dispose', async () => {
  const x = setup(), first = x.interval(); await tick();
  for (let i = 0; i < 40; i++) await x.interval();
  assert.equal(x.requests.length, 1);
  x.requests[0].reject(new Error('offline')); await first;
  assert.equal(x.state.polling, false);
  const retry = x.interval(); await tick(); x.close();
  x.requests[1].resolve({ signature: 'changed' }); await retry;
  assert.equal(x.loads(), 0); assert.equal(x.controls.get('.as-changed').hidden, true);
  const y = setup(), last = y.interval(); await tick(); y.state.disposed = true;
  y.requests[0].resolve({ signature: 'changed' }); await last;
  assert.equal(y.loads(), 0);
});
function loadSetup(responses) {
  const text = () => ({ textContent: '', innerHTML: '', hidden: true, scrollTop: 0, value: '' });
  const controls = new Map(['.as-count', '.as-message', '.as-rows', '.as-list', '.as-changed'].map(s => [s, text()]));
  const state = { textures: new Map(), groups: new Map(), revision: 0, disposed: false, busy: false, polling: false, signature: '', items: [], retryTimer: 0, retryDelay: 0 };
  const timers = [], requests = [];
  const context = vm.createContext({ state, Map, Set, Promise, String, Math, JSON,
    esc: value => String(value ?? ''), url: path => path, $: selector => controls.get(selector), expanded: new Set(), prefs: {},
    facets() {}, save() {}, loadGroup: async () => {}, signature: page => JSON.stringify(page.groups),
    query: (game, offset, fresh) => '/api/asset-groups?' + (fresh ? 'fresh=1' : ''),
    options: { api: async url => { requests.push(url); const next = responses.shift(); if (next instanceof Error) throw next; return next; } },
    root: { classList: { contains: () => false } },
    setTimeout(fn, ms) { timers.push({ fn, ms }); return timers.length; }, clearTimeout() {},
  });
  const start = source.indexOf('const slow = e =>'), end = source.indexOf('const refresh = () =>', start);
  assert.ok(start >= 0 && end > start);
  vm.runInContext(source.slice(start, end), context);
  return { context, state, controls, timers, requests, run: code => vm.runInContext(code, context) };
}

const settle = async () => { for (let i = 0; i < 5; i++) await tick(); };
const timeout = () => Object.assign(new Error('The operation was aborted due to timeout'), { name: 'TimeoutError' });
const ready = { indexing: false, total: 1, total_all: 1, nested: 0, hidden_assets: 0, kinds: ['character'], games: ['DOA2'],
  groups: [{ title: 'DOA2', count: 1, preview_url: '/p', added: 1, copied: 0 }] };

test('a first load while the server is still indexing says so and retries with backoff', async () => {
  const x = loadSetup([{ indexing: true, groups: [] }, timeout(), ready]);
  await x.run('load()');
  assert.equal(x.controls.get('.as-count').textContent, 'Indexing assets…');
  assert.equal(x.controls.get('.as-message').textContent, '');
  assert.equal(x.timers.length, 1); assert.equal(x.timers[0].ms, 2000);
  x.timers[0].fn(); await settle();                // the slow control plane times the next request out: no error, longer wait
  assert.equal(x.controls.get('.as-count').textContent, 'Indexing assets…');
  assert.equal(x.controls.get('.as-message').textContent, '');
  assert.equal(x.timers.length, 2); assert.equal(x.timers[1].ms, 4000);
  x.timers[1].fn(); await settle();
  assert.match(x.controls.get('.as-count').textContent, /^1 assets · 1 titles/);
  assert.match(x.controls.get('.as-rows').innerHTML, /DOA2/);
  assert.equal(x.requests.length, 3); assert.equal(x.state.retryDelay, 0); assert.equal(x.timers.length, 2);
});

test('other load failures are reported, and a superseded retry does nothing', async () => {
  const x = loadSetup([new Error('500 boom')]);
  await x.run('load()');
  assert.equal(x.controls.get('.as-message').textContent, 'Could not load assets: 500 boom');
  assert.equal(x.timers.length, 0);
  const y = loadSetup([{ indexing: true, groups: [] }, ready]);
  await y.run('load()'); y.state.revision++;       // the operator changed a filter meanwhile
  y.timers[0].fn(); await settle();
  assert.equal(y.requests.length, 1);
  await y.run('load(true)');
  assert.equal(y.requests[1], '/api/asset-groups?fresh=1');
});
