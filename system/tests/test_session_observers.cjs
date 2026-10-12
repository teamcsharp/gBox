const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { test } = require('node:test');
const source = fs.readFileSync(require('node:path').join(__dirname, '../clients/web/index.html'), 'utf8');
test('web inline scripts parse', () => {
  for (const match of source.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)) {
    if (match[1].trim()) new vm.Script(match[1]);
  }
});
test('session panel escapes model output and only changes observer setting', async () => {
  const calls = [], toggle = {};
  const element = { isConnected: true, innerHTML: '', querySelector: () => toggle };
  const context = { document: { getElementById: () => element },
    clearTimeout() {}, setTimeout() {}, encodeURIComponent, Date,
    esc: text => String(text).replaceAll('<', '&lt;').replaceAll('>', '&gt;'), tq: () => '',
    api: async (path, body) => { calls.push({ path, body }); return {
      service_online: true, enabled: body?.enabled ?? true, gameplay_state: 'watching',
      latest: { summary: '<script>unsafe</script>', captured: 100, actors: ['<img>'] },
      models: { state: 'unsupported' }, samples: 1, history: [] }; } };
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('const observerWatch ='), source.indexOf('async function wbInit()')), context);
  context.sessionObserverWatch('worker-session');
  await new Promise(resolve => setImmediate(resolve));
  assert.ok(element.innerHTML.includes('&lt;script&gt;'));
  assert.ok(!element.innerHTML.includes('<script>'));
  await toggle.onclick({ currentTarget: {} });
  const posts = calls.filter(c => c.body);
  assert.equal(posts.length, 1);
  assert.equal(posts[0].path, '/api/sessions/worker-session/observers');
  assert.equal(posts[0].body.enabled, false);
});
