const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { spawnSync } = require('node:child_process');

const html = fs.readFileSync(path.join(__dirname, '../clients/desktop/index.html'), 'utf8');
function between(start, end) {
  const a = html.indexOf(start), b = html.indexOf(end, a + start.length);
  assert.ok(a >= 0 && b > a, `missing desktop source boundary: ${start}`);
  return html.slice(a, b);
}
const helpers = between('function singleFlightPoll(work)', 'const fmtDur');
const inbox = between('function refreshInbox(explicit', '$("#reqlist").addEventListener("change"');
const audit = between('function auditPoll(explicit', 'function auGroup(rows)');
const status = between('function statusRight(explicit', 'statusRight(false).catch');
const shared = between('const LIVE_SESSIONS', 'document.querySelectorAll("aside button[data-s]").forEach');
const GBoxLivePoll = require('../clients/desktop/live-poll.js');
const tick = () => new Promise(resolve => setImmediate(resolve));
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function setup(visible = false) {
  const nodes = new Map(), calls = [], active = new Map(), maximum = new Map();
  let renders = 0, tokens = 0, auditRenders = 0;
  function node(id) {
    if (!nodes.has(id)) nodes.set(id, { id, innerHTML: '', textContent: '', style: {}, dataset: {},
      classes: new Set(), attrs: {}, setAttribute(k, v) { this.attrs[k] = v; },
      contains(el) { return el?.host === this; },
      classList: { contains(k) { return nodes.get(id).classes.has(k); } } });
    return nodes.get(id);
  }
  if (visible) node('#requests').classes.add('on');
  node('#d-svc').classes.add('ok');
  const filters = ['all', 'pending', 'completed'].map(mode => ({ dataset: { requestFilter: mode },
    style: {}, setAttribute() {} }));
  const context = vm.createContext({ console, Date, Set, Map, Promise, GBoxLivePoll,
    $: node, esc: value => String(value ?? ''),
    document: { activeElement: null, querySelectorAll: () => filters },
    gbox: { api(url) {
      const d = deferred(), count = (active.get(url) || 0) + 1;
      active.set(url, count); maximum.set(url, Math.max(maximum.get(url) || 0, count));
      calls.push({ url, ...d });
      return d.promise.finally(() => active.set(url, active.get(url) - 1));
    }, token: async () => { tokens++; return 'fixture-token'; } },
    requestFilter: 'all', inboxSolverRequests: [], openThreads: new Set(), replyAtt: {},
    S: { apiUrl: 'https://fixture.invalid' }, REG: { tools: {} }, MODS: { list: [] },
    GBoxRequestSolvers: { badge: () => '' }, GBoxReportStory: { disclosureHtml: () => '', reattach() {} }, fmtDur: String, fmtTok: String,
    updateInboxView(host, key, render) { renders++; host.innerHTML = render(); host.key = key; },
    AUD: { rows: [], after: 0 }, activity: { remote() {} }, processPopupSync() {},
    AU_ACTION: [], AU_ACTOR: [], auIcon: () => '*', auBadge: () => '',
    auGroup: rows => rows.map(row => [row]), auditRender: () => { auditRenders++; }, EMU_ICON: {}
  });
  vm.runInContext(shared + '\n' + helpers + '\n' + inbox + '\n' + audit + '\n' + status, context);
  return { context, node, calls, active, maximum,
    run: code => vm.runInContext(code, context),
    count: url => calls.filter(call => call.url === url).length,
    request: (url, n = 0) => calls.filter(call => call.url === url)[n],
    renders: () => renders, tokens: () => tokens, auditRenders: () => auditRenders };
}
function request(status = 'open') {
  return { id: 'request-1', number: 1, title: 'Actual request', status, source: 'app', kind: 'text',
    created: 1, automated: false, messages: [], metrics: { tokens_in: 0, tokens_out: 0, tools: {}, files_changed: [] } };
}

test('every inline desktop and web script still parses', () => {
  const web = fs.readFileSync(path.join(__dirname, '../clients/web/index.html'), 'utf8');
  const blocks = [...(html + '\n' + web).matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g)];
  assert.ok(blocks.length);
  for (const [, attributes, source] of blocks) {
    if (attributes.includes('src=')) continue;
    if (/type=["']importmap["']/.test(attributes)) JSON.parse(source);
    else if (/type=["']module["']/.test(attributes)) {
      const result = spawnSync(process.execPath, ['--input-type=module', '--check'], { input: source, encoding: 'utf8' });
      assert.equal(result.status, 0, result.stderr);
    } else new vm.Script(source);
  }
});

test('automatic ticks share pending work without queuing extra fetches', async () => {
  const x = setup();
  const p = x.run('refreshInbox(false)'); await tick();
  for (let i = 0; i < 50; i++) assert.equal(x.run('refreshInbox(false)'), p);
  assert.equal(x.count('/api/requests'), 1);
  x.request('/api/requests').resolve({ ok: true, data: [request()] });
  await p; await tick();
  assert.equal(x.count('/api/requests'), 1);
  assert.equal(x.node('#tb-count').textContent, 1);
  assert.equal(x.tokens(), 0); assert.equal(x.count('/api/mods'), 0);
});

test('many explicit refreshes retain one latest pass after a mutation', async () => {
  const x = setup();
  const p = x.run('refreshInbox(false)'); await tick();
  for (let i = 0; i < 10; i++) assert.equal(x.run('refreshInbox()'), p);
  x.request('/api/requests').resolve({ ok: true, data: [request()] }); await tick();
  assert.equal(x.count('/api/requests'), 2);
  x.request('/api/requests', 1).resolve({ ok: true, data: [request('done')] });
  await p; await tick();
  assert.equal(x.node('#tb-count').textContent, 0);
  assert.equal(x.context.inboxSolverRequests[0].status, 'done');
  assert.equal(x.count('/api/requests'), 2); assert.equal(x.maximum.get('/api/requests'), 1);
});

test('an explicit refresh in the settlement microtask tail is never lost', async () => {
  for (const depth of [2, 3]) {
    const x = setup(), fetched = deferred(); let calls = 0, explicit;
    x.context.fixtureWork = async () => {
      calls++; if (calls === 1) await fetched.promise;
      return calls;
    };
    const poll = x.run('singleFlightPoll(fixtureWork)'), first = poll(false);
    await tick();
    fetched.promise.then(() => {
      let callback = () => { explicit = poll(true); };
      for (let i = 0; i < depth; i++) {
        const next = callback;
        callback = () => queueMicrotask(next);
      }
      callback();
    });
    fetched.resolve(); await tick();
    await first; assert.ok(explicit);
    assert.equal(await explicit, 2, `refresh after ${depth} microtasks`);
    assert.equal(calls, 2);
  }
});

test('visible inbox renders mod cards and the latest filter without overlapping calls', async () => {
  const x = setup(true), p = x.run('refreshInbox(false)'); await tick();
  x.context.requestFilter = 'completed';
  x.run('refreshInbox()');
  x.request('/api/requests').resolve({ ok: true, data: [] }); await tick();
  assert.equal(x.count('/api/mods'), 1);
  x.request('/api/mods').resolve({ ok: true, data: [] }); await tick();
  x.request('/api/requests', 1).resolve({ ok: true, data: [request('done')] }); await tick();
  x.request('/api/mods', 1).resolve({ ok: true, data: [] }); await p;
  assert.equal(x.renders(), 2);
  assert.equal(JSON.parse(x.node('#reqlist').key)[0], 'completed');
  assert.match(x.node('#reqlist').innerHTML, /Actual request/);
  assert.equal(x.maximum.get('/api/mods'), 1);
});

test('a rejected fetch resets the gate and permits a later retry', async () => {
  const x = setup(), p = x.run('refreshInbox(false)');
  const rejected = assert.rejects(p, /network refused/); await tick();
  x.request('/api/requests').reject(new Error('network refused')); await rejected;
  const retry = x.run('refreshInbox(false)'); await tick();
  x.request('/api/requests', 1).resolve({ ok: true, data: [] }); await retry;
  assert.equal(x.count('/api/requests'), 2);
});

test('an explicit refresh survives failure of the pending pass', async () => {
  const x = setup(), p = x.run('refreshInbox(false)'); await tick();
  x.run('refreshInbox()');
  x.request('/api/requests').reject(new Error('temporary failure')); await tick();
  x.request('/api/requests', 1).resolve({ ok: true, data: [request()] }); await p;
  assert.equal(x.node('#tb-count').textContent, 1);
});

test('audit waits for a pending sibling after rejection and never reopens a closed overlay', async () => {
  const x = setup(); x.node('#auditpanel').classes.add('on');
  const p = x.run('auditPoll(false)'), rejected = assert.rejects(p, /audit unavailable/); await tick();
  x.request('/api/audit?tail=500').reject(new Error('audit unavailable')); await tick();
  assert.equal(x.run('auditPoll(false)'), p);
  assert.equal(x.count('/api/jobs?state=queued,running&limit=100'), 1);
  x.request('/api/jobs?state=queued,running&limit=100').resolve({ ok: true, data: [] }); await rejected;
  const retry = x.run('auditPoll(false)'); await tick();
  x.node('#auditpanel').classes.delete('on');
  x.request('/api/audit?tail=500', 1).resolve({ ok: true, data: [{ seq: 1, action: 'job.succeeded', actor: 'worker', subject: 'finished', ts: 1 }] });
  x.request('/api/jobs?state=queued,running&limit=100', 1).resolve({ ok: true, data: [] }); await retry;
  assert.equal(x.auditRenders(), 0); assert.equal(x.node('#auditpanel').classes.has('on'), false);
  assert.equal(x.context.AUD.after, 1);
  assert.equal(x.maximum.get('/api/jobs?state=queued,running&limit=100'), 1);
});

test('desktop popup receives the shared jobs result without introducing a second poller', async () => {
  const x = setup(), received = [];
  x.context.processPopupSync = jobs => received.push(jobs);
  const p = x.run('auditPoll(false)'); await tick();
  for (let i = 0; i < 30; i++) x.run('auditPoll(false)');
  const jobs = [{ id: 'model', state: 'running', tool: 'characters' }];
  x.request('/api/jobs?state=queued,running&limit=100').resolve({ ok: true, data: jobs });
  x.request('/api/audit?tail=500').resolve({ ok: true, data: [] }); await p;
  assert.deepEqual(received, [jobs]);
  assert.equal(x.count('/api/jobs?state=queued,running&limit=100'), 1);
});

test('desktop waits for its API credentials before creating the donor preview URL', async () => {
  const ready = deferred(), received = []; let options, mounts = 0;
  const context = vm.createContext({ SBX_READY: ready.promise, SBX: { api: '', tok: '' }, encodeURIComponent,
    window: { GBoxProcessPopup: { mount(opts) { mounts++; options = opts; return { sync: jobs => received.push(jobs) }; } } } });
  vm.runInContext(between('let PROCESS_POPUP = null;', 'function auditPoll(explicit'), context);
  const pending = vm.runInContext('processPopupSync([{id:"model"}])', context); await tick();
  assert.equal(mounts, 0, 'first job cannot load before credentials resolve');
  context.SBX.api = 'https://fixture.invalid'; context.SBX.tok = 'fixture token'; ready.resolve(); await pending;
  assert.equal(mounts, 1);
  assert.equal(options.assetUrl('/api/characters/amy/model'), 'https://fixture.invalid/api/characters/amy/model?token=fixture%20token');
  assert.equal(received[0][0].id, 'model');
});

test('status ticks cannot duplicate an unsettled workers or sessions fetch', async () => {
  const x = setup(), p = x.run('statusRight(false)'); await tick();
  for (let i = 0; i < 30; i++) assert.equal(x.run('statusRight(false)'), p);
  x.request('/api/workers').resolve({ ok: true, data: [] }); await tick();
  assert.equal(x.run('statusRight(false)'), p);
  x.request(LIVE).resolve({ ok: true, data: [] }); await p;
  assert.match(x.node('#sb-right').innerHTML, /Spark API/);
  assert.equal(x.count('/api/workers'), 1); assert.equal(x.count(LIVE), 1);
  assert.equal(x.count('/api/sessions'), 0, 'the status bar never downloads the whole session history');
});

const LIVE = '/api/sessions?include_ended=false';
test('#712: status bar, chat context and the docked-game loop share one running-sessions read', async () => {
  const x = setup();
  const a = x.run('liveSessions()'), b = x.run('liveSessions()'), c = x.run('statusRight(false)'); await tick();
  assert.equal(x.count(LIVE), 1);
  x.request(LIVE).resolve({ ok: true, data: [{ session_id: 's1', state: 'running' }] });
  x.request('/api/workers').resolve({ ok: true, data: [] });
  await Promise.all([a, b, c]);
  assert.equal(x.run('LIVE_SESSIONS.peek().data[0].session_id'), 's1');
  await x.run('liveSessions()');                               // still fresh: no new request
  assert.equal(x.count(LIVE), 1);
});

test('#712: an ended session is looked up in the cached history, once', async () => {
  const x = setup();
  const one = x.run('sessionById("old")'); await tick();
  x.request(LIVE).resolve({ ok: true, data: [] }); await tick();
  x.request('/api/sessions').resolve({ ok: true, data: [{ session_id: 'old', state: 'ended', game_id: 'g' }] });
  assert.equal((await one).game_id, 'g');
  x.run('LIVE_SESSIONS.invalidate()');
  const two = x.run('sessionById("old")'); await tick();
  x.request(LIVE, 1).resolve({ ok: true, data: [] });
  assert.equal((await two).game_id, 'g');
  assert.equal(x.count('/api/sessions'), 1, 'history is reused for 30 s');
});

test('closing Requests during a slow mods fetch does not redraw or reopen it', async () => {
  const x = setup(true), p = x.run('refreshInbox(false)'); await tick();
  x.request('/api/requests').resolve({ ok: true, data: [request()] }); await tick();
  x.node('#requests').classes.delete('on');
  x.request('/api/mods').resolve({ ok: true, data: [] }); await p;
  assert.equal(x.renders(), 0); assert.equal(x.node('#requests').classes.has('on'), false);
  assert.equal(x.node('#tb-count').textContent, 1);
});

test('reply focus acquired during a slow mods fetch preserves the edit', async () => {
  const x = setup(true), p = x.run('refreshInbox(false)'); await tick();
  x.request('/api/requests').resolve({ ok: true, data: [] }); await tick();
  x.context.document.activeElement = { host: x.node('#reqlist'), closest: selector => selector.startsWith('input') ? {} : null };
  x.request('/api/mods').resolve({ ok: true, data: [] }); await p;
  assert.equal(x.renders(), 0);
});

test('opening Requests triggers an explicit refresh rather than waiting for a timer', () => {
  const requests = { dataset: { s: 'requests' }, classList: { toggle() {} } };
  const sections = [{ id: 'requests', classList: { toggle() {} } }]; let calls = 0;
  const context = vm.createContext({ document: { querySelectorAll: selector => selector === 'section' ? sections : [requests] },
    refreshInbox: () => { calls++; }, refresh() {} });
  vm.runInContext(between('document.querySelectorAll("aside button[data-s]").forEach', '$("#chat-home").onclick'), context);
  requests.onclick(); assert.equal(calls, 1);
});

test('timer wiring always uses automatic mode and consumes timer rejections', () => {
  for (const [name, interval] of [['auditPoll', 3000], ['statusRight', 5000]])
    assert.ok(html.includes(`setInterval(() => ${name}(false).catch(() => {}), ${interval})`));
  assert.ok(html.includes('refreshInbox(false).catch(() => {});'));
});

test('#712: an unchanged request history (same ETag) is neither copied into the page nor keyed by its contents', async () => {
  const x = setup(true), seen = [];
  x.context.gbox.apiTagged = async (p, etag) => { seen.push([p, etag]);
    return etag === 'A' ? { ok: true, etag: 'A', unchanged: true } : { ok: true, etag: 'A', data: [request()] }; };
  const first = x.run('refreshInbox(false)'); await tick(); await tick();
  x.request('/api/mods').resolve({ ok: true, data: [] }); await first;
  const key = x.node('#reqlist').key;
  assert.ok(key.includes('"A"') && !key.includes('Actual request'), 'the re-render key is the tag, not 8 MB of JSON');
  const second = x.run('refreshInbox(false)'); await tick(); await tick();
  x.request('/api/mods', 1).resolve({ ok: true, data: [] }); await second;
  assert.deepEqual(seen, [['/api/requests', null], ['/api/requests', 'A']]);
  assert.equal(x.node('#reqlist').key, key, 'same answer, same key: updateInboxView keeps the DOM');
  assert.equal(x.count('/api/requests'), 0, 'the tagged path replaces the plain one');
  assert.equal(x.node('#tb-count').textContent, 1);
});

test('#712: the 8 MB request history is polled every 5 s only while Requests is on screen', () => {
  const timer = between('var inboxAt = 0;', 'function popups()');
  let tickFn = null, polls = 0, now = 1000000;
  const on = new Set();
  const context = vm.createContext({ GBoxLivePoll: { due: (at, vis, fast, slow) => GBoxLivePoll.due(at, vis, fast, slow, now) },
    $: () => ({ classList: { contains: k => on.has(k) } }),
    setInterval: fn => { tickFn = fn; }, refreshInbox: () => { polls++; context.inboxAt = now; return Promise.resolve(); } });
  vm.runInContext(timer, context);
  context.inboxAt = now;
  for (let i = 0; i < 11; i++) { now += 5000; tickFn(); }    // 55 s hidden: no poll
  assert.equal(polls, 0);
  now += 5000; tickFn(); assert.equal(polls, 1);             // a minute: the badge refreshes
  on.add('on');
  for (let i = 0; i < 4; i++) { now += 5000; tickFn(); }
  assert.equal(polls, 5);                                    // visible: every 5 s
});
