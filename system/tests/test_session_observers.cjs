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
  const calls = [], toggle = {}, look = {};
  const element = { isConnected: true, innerHTML: '', querySelector: s => s.includes('look') ? look : toggle };
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

function panel(response) {
  const calls = [], buttons = {};
  const element = { isConnected: true, innerHTML: '',
    querySelector: s => (buttons[s] ??= { onclick: null }) };
  const context = { document: { getElementById: () => element },
    clearTimeout() {}, setTimeout() {}, encodeURIComponent, Date,
    esc: text => String(text).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;'),
    tq: () => '',
    api: async (path, body) => { calls.push({ path, body }); return response; } };
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('const observerWatch ='), source.indexOf('async function wbInit()')), context);
  return { context, element, calls, buttons };
}
const goals = {
  ask: { agent: 'hermes', name: 'Hermes (engineering agent)',
         text: 'Get characters on screen up close (character select, a cutscene, or stand facing an enemy for a few seconds), then press "Done, look now"' },
  agents: [
    { agent: 'gameplay', name: 'Gameplay observer', state: 'waiting_for_frame',
      goal: 'Look at 007 Agent Under Fire every 30 seconds and note who is on screen',
      doing: 'Waiting for a fresh frame from your game window (a capture is on its way).',
      seeking: 'a frame with characters clearly visible: close up, not a menu, loading or death screen',
      you_can_help: 'Stand still facing a character for a few seconds', blocked_by: '' },
    { agent: 'models', name: 'Model collector', state: 'unsupported', goal: 'Read every character model',
      doing: 'Waiting for a model reader.', seeking: 'a native model reader for this exact game build',
      you_can_help: 'Nothing in-game', blocked_by: 'no native model reader for 007 Agent Under Fire yet <b>' },
    { agent: 'hermes', name: 'Hermes (engineering agent)', state: 'queued', stage: 'reader', stages_verified: ['inventory', 'analysis'],
      goal: 'Write and test a reader', doing: 'Its run for this stage is queued.', seeking: 'extracted models',
      you_can_help: 'Get characters on screen', blocked_by: '',
      requests: [{ id: 'r1', number: 41, title: 'Put Bond into AUF', goal: 'put Bond into 007 Agent Under Fire' }] }],
  look_requested: null };

test('session agents panel puts each goal, what it seeks, how to help and its blocker on top', async () => {
  const { context, element } = panel({ service_online: true, enabled: true, gameplay_state: 'waiting_for_frame',
    latest: { summary: 'Bond in a corridor', captured: 100 }, models: { state: 'unsupported' }, samples: 3, history: [], goals });
  context.sessionObserverWatch('w-1');
  await new Promise(resolve => setImmediate(resolve));
  const html = element.innerHTML;
  for (const text of ['You can help the Hermes (engineering agent):', 'Goal:', 'Now:', 'Looking for:', 'You can help:',
                      'Blocked by:', 'stage: reader', 'verified: inventory, analysis', '#41 Put Bond into AUF',
                      'a frame with characters clearly visible', 'Done, look now', 'Pause observers'])
    assert.ok(html.includes(text), text);
  assert.ok(html.indexOf('Gameplay observer') < html.indexOf('Bond in a corridor'), 'goals render above the observation');
  assert.ok(html.includes('&lt;b&gt;') && !html.includes('yet <b>'), 'server text is escaped');
  assert.equal((html.match(/class="obs-agent"/g) || []).length, 3);
});

test('"Done, look now" posts the look request and keeps the observer toggle', async () => {
  const { context, calls, buttons } = panel({ service_online: true, enabled: true, gameplay_state: 'watching',
    models: {}, samples: 0, history: [], goals });
  context.sessionObserverWatch('w-1');
  await new Promise(resolve => setImmediate(resolve));
  const target = {};
  await buttons['[data-observer-look]'].onclick({ currentTarget: target });
  assert.equal(target.textContent, 'Looking...');
  const posts = calls.filter(c => c.body);
  assert.equal(posts.length, 1);
  assert.equal(posts[0].path, '/api/sessions/w-1/observers/look');
  assert.ok(typeof buttons['[data-observer-toggle]'].onclick === 'function');
});

test('a pending look shows as Looking... and an older server without goals still renders', async () => {
  let { context, element } = panel({ service_online: true, enabled: true, gameplay_state: 'watching',
    models: {}, history: [], goals: { ...goals, look_requested: 1000 } });
  context.sessionObserverWatch('w-1');
  await new Promise(resolve => setImmediate(resolve));
  assert.ok(element.innerHTML.includes('disabled>Looking...'));
  ({ context, element } = panel({ service_online: true, enabled: true, gameplay_state: 'watching', models: {}, history: [] }));
  context.sessionObserverWatch('w-1');
  await new Promise(resolve => setImmediate(resolve));
  assert.ok(!element.innerHTML.includes('obs-goals') && element.innerHTML.includes('Done, look now'));
});
