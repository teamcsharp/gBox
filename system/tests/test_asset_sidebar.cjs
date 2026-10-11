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
