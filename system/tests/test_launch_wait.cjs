const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// #1293: a launch queued for an offline worker must say so instead of spinning on "queued".
const html = fs.readFileSync(path.join(__dirname, '../clients/web/index.html'), 'utf8');
const start = html.indexOf('let LOADING = null, LAST_LAUNCH = null;');
const end = html.indexOf('async function details(id)', start);
assert.ok(start >= 0 && end > start, 'launch helpers must be present');
const source = html.slice(start, end);
const NOW = 1791748430000;
const nuc = (o = {}) => ({ id: 'e82335a1adfd4e14', name: 'i9-NUC', os: 'windows', last_seen: NOW / 1000 - 946,
  active_jobs: 4, online: false, ...o });
const jay = (o = {}) => ({ id: '097f09a8149141ed', name: 'JAYBUILTFINALE', os: 'windows', last_seen: NOW / 1000 - 3,
  active_jobs: 0, online: true, ...o });
const spark = { id: '6874781e7b494d5b', name: 'lilspark', os: 'linux', last_seen: NOW / 1000, active_jobs: 0, online: true };

function helpers() {
  const ctx = vm.createContext({ addEventListener() {}, console });
  vm.runInContext(source + '\nthis.launchWaitNote = launchWaitNote;', ctx);
  return ctx.launchWaitNote;
}
const queued = (o = {}) => ({ id: 'e4dc01d6ac784fdc', state: 'queued', created: NOW / 1000 - 30, require_worker: null,
  require_os: null, ...o });

test('offline target worker is named with how long ago it checked in', () => {
  const note = helpers()(queued({ require_worker: 'e82335a1adfd4e14' }), [nuc(), jay(), spark], 'i9-NUC', NOW);
  assert.match(note, /^i9-NUC's gBox worker is offline: it last checked in 16 min ago\./);
  assert.match(note, /starts by itself when it reconnects/);
  assert.match(note, /restart gBox on i9-NUC/);
});

test('a different launch node cannot stand in for the job\'s authoritative worker', () => {
  const note = helpers()(queued({ require_worker: 'missing-authoritative-id' }), [jay()], 'JAYBUILTFINALE', NOW);
  assert.match(note, /worker named missing-authoritative-id/);
});

function deferred() {
  let resolve, reject;
  const promise = new Promise((r, j) => { resolve = r; reject = j; });
  return { promise, resolve, reject };
}
function launchHarness(api) {
  let clock = NOW;
  const msgs = [], fails = [], shown = [];
  const el = { style: {}, onclick: null };
  const ctx = vm.createContext({ console, encodeURIComponent, addEventListener() {},
    Date: { now: () => (clock += 1000) }, setTimeout: f => setImmediate(f), api,
    runJob: async () => ({}), $: () => el, bootGet: () => ({}),
    show: (...args) => shown.push(args), WHERE: 'local', window: { GBOX_LOCAL: { worker: 'i9-NUC' } },
    loader: { show() {}, hide() {}, progress: (p, m) => msgs.push(m), fail: m => fails.push(m) } });
  vm.runInContext(source + '\nthis.play = play; this.cancelLoad = cancelLoad; this.state = () => ({ LOADING, LAST_LAUNCH });', ctx);
  return { ctx, msgs, fails, shown };
}
const catalog = () => ({ title: 'Dead or Alive', core: 'pcsx_rearmed', platform: 'psx' });

test('late success after Esc cannot reopen the cancelled game', async () => {
  const polling = deferred(), started = deferred();
  let reads = 0;
  const h = launchHarness(async url => {
    if (url.startsWith('/api/catalog/')) return catalog();
    if (url.startsWith('/api/games/')) return { id: 'old' };
    if (url.endsWith('/cancel')) return {};
    if (url === '/api/jobs/old') {
      if (++reads === 1) { started.resolve(); return polling.promise; }
      return { state: 'queued' };
    }
    throw new Error('unexpected ' + url);
  });
  const running = h.ctx.play('game');
  await started.promise;
  await h.ctx.cancelLoad();
  polling.resolve({ state: 'succeeded', output: { session_id: 'old-session' } });
  await running;
  assert.equal(h.shown.some(args => args[0] === 'Sessions'), false);
});

test('poll failure remains cancellable so a queued launch cannot start later unnoticed', async () => {
  let cancelled = 0;
  const h = launchHarness(async url => {
    if (url.startsWith('/api/catalog/')) return catalog();
    if (url.startsWith('/api/games/')) return { id: 'old' };
    if (url.endsWith('/cancel')) { cancelled++; return {}; }
    if (url === '/api/jobs/old') throw new Error('connection lost');
    throw new Error('unexpected ' + url);
  });
  await h.ctx.play('game');
  assert.match(h.fails[0], /connection lost/);
  await h.ctx.cancelLoad();
  assert.equal(cancelled, 1);
});

test('an old launch response cannot overwrite the newer launch waiting on its own job', async () => {
  const firstPost = deferred(), firstStarted = deferred(), secondPoll = deferred(), secondStarted = deferred();
  let cancelledOld = 0;
  const h = launchHarness(async url => {
    if (url.startsWith('/api/catalog/')) return catalog();
    if (url.startsWith('/api/games/first/')) { firstStarted.resolve(); return firstPost.promise; }
    if (url.startsWith('/api/games/second/')) return { id: 'new' };
    if (url.endsWith('/old/cancel')) { cancelledOld++; return {}; }
    if (url === '/api/jobs/new') { secondStarted.resolve(); return secondPoll.promise; }
    if (url === '/api/jobs/old') return { state: 'failed', error: 'old finished' };
    throw new Error('unexpected ' + url);
  });
  const first = h.ctx.play('first');
  await firstStarted.promise;
  const second = h.ctx.play('second');
  await secondStarted.promise;
  firstPost.resolve({ id: 'old' });
  await first;
  assert.equal(h.ctx.state().LOADING?.job, 'new');
  assert.equal(cancelledOld, 1);
  secondPoll.resolve({ state: 'succeeded', output: { session_id: 'new-session' } });
  await second;
  assert.deepEqual(h.shown.at(-1), ['Sessions', 'new-session']);
});

test('queued progress text cannot hide the current offline-worker explanation', async () => {
  let reads = 0;
  const h = launchHarness(async url => {
    if (url.startsWith('/api/catalog/')) return catalog();
    if (url.startsWith('/api/games/')) return { id: 'old' };
    if (url === '/api/workers') return [nuc()];
    if (url === '/api/jobs/old') return ++reads === 1
      ? queued({ id: 'old', require_worker: nuc().id, progress: { pct: 1, msg: 'queued' } })
      : { state: 'failed', error: 'test ended' };
    throw new Error('unexpected ' + url);
  });
  await h.ctx.play('game');
  assert.match(h.msgs.at(-1), /worker is offline/);
});

test('a late catalog response cannot start the obsolete launch or replace a newer loader', async () => {
  const oldCatalog = deferred(), oldStarted = deferred(), newPoll = deferred(), newStarted = deferred();
  const posts = [];
  const h = launchHarness(async url => {
    if (url === '/api/catalog/first') { oldStarted.resolve(); return oldCatalog.promise; }
    if (url === '/api/catalog/second') return catalog();
    if (url.startsWith('/api/games/')) { posts.push(url); return { id: 'new' }; }
    if (url === '/api/jobs/new') { newStarted.resolve(); return newPoll.promise; }
    throw new Error('unexpected ' + url);
  });
  const old = h.ctx.play('first'); await oldStarted.promise;
  const current = h.ctx.play('second'); await newStarted.promise;
  oldCatalog.resolve({ ...catalog(), title: 'Obsolete title' }); await old;
  assert.equal(posts.length, 1);
  assert.match(posts[0], /games\/second\//);
  assert.equal(h.ctx.state().LOADING.job, 'new');
  assert.equal(h.ctx.state().LOADING.title, catalog().title);
  newPoll.resolve({ state: 'succeeded', output: { session_id: 'new-session' } }); await current;
});

test('Esc during the catalog await leaves no launch POST when the catalog eventually arrives', async () => {
  const pending = deferred(), began = deferred(); let posts = 0;
  const h = launchHarness(async url => {
    if (url.startsWith('/api/catalog/')) { began.resolve(); return pending.promise; }
    if (url.startsWith('/api/games/')) { posts++; return { id: 'obsolete' }; }
    throw new Error('unexpected ' + url);
  });
  const work = h.ctx.play('game'); await began.promise;
  await h.ctx.cancelLoad(); pending.resolve(catalog()); await work;
  assert.equal(posts, 0);
  assert.equal(h.ctx.state().LOADING, null);
});

test('late rejection from an old poll cannot fail the newer launch', async () => {
  const oldPoll = deferred(), oldStarted = deferred(), newPoll = deferred(), newStarted = deferred();
  let oldReads = 0;
  const h = launchHarness(async url => {
    if (url.startsWith('/api/catalog/')) return catalog();
    if (url.startsWith('/api/games/first/')) return { id: 'old' };
    if (url.startsWith('/api/games/second/')) return { id: 'new' };
    if (url.endsWith('/cancel')) return {};
    if (url === '/api/jobs/old') {
      if (++oldReads === 1) { oldStarted.resolve(); return oldPoll.promise; }
      return { state: 'queued' };
    }
    if (url === '/api/jobs/new') { newStarted.resolve(); return newPoll.promise; }
    throw new Error('unexpected ' + url);
  });
  const old = h.ctx.play('first'); await oldStarted.promise;
  const current = h.ctx.play('second'); await newStarted.promise;
  oldPoll.reject(new Error('old connection failed')); await old;
  assert.equal(h.fails.length, 0);
  assert.equal(h.ctx.state().LOADING.job, 'new');
  newPoll.resolve({ state: 'succeeded', output: { session_id: 'new-session' } }); await current;
});

test('late worker inventory after Esc cannot repaint the cancelled loader', async () => {
  const workers = deferred(), workerRead = deferred(); let reads = 0;
  const h = launchHarness(async url => {
    if (url.startsWith('/api/catalog/')) return catalog();
    if (url.startsWith('/api/games/')) return { id: 'old' };
    if (url.endsWith('/cancel')) return {};
    if (url === '/api/jobs/old') { reads++; return queued({ id: 'old', require_worker: nuc().id }); }
    if (url === '/api/workers') { workerRead.resolve(); return workers.promise; }
    throw new Error('unexpected ' + url);
  });
  const work = h.ctx.play('game'); await workerRead.promise;
  await h.ctx.cancelLoad(); const count = h.msgs.length;
  workers.resolve([nuc()]); await work;
  assert.equal(h.msgs.length, count);
  assert.equal(h.shown.some(a => a[0] === 'Sessions'), false);
  assert.equal(h.ctx.state().LOADING, null);
});

test('explained offline wait beyond the ordinary deadline remains cancellable by exact job', async () => {
  const reached = deferred(), finalPoll = deferred(); let polls = 0; const cancelled = [];
  const h = launchHarness(async url => {
    if (url.startsWith('/api/catalog/')) return catalog();
    if (url.startsWith('/api/games/')) return { id: 'offline-job' };
    if (url.endsWith('/cancel')) { cancelled.push(url); return {}; }
    if (url === '/api/workers') return [nuc()];
    if (url === '/api/jobs/offline-job') {
      if (++polls === 850) { reached.resolve(); return finalPoll.promise; }
      return queued({ id: 'offline-job', require_worker: nuc().id });
    }
    throw new Error('unexpected ' + url);
  });
  const work = h.ctx.play('game'); await reached.promise;
  assert.equal(h.fails.length, 0);
  assert.match(h.msgs.at(-1), /worker is offline.*Esc to cancel/);
  await h.ctx.cancelLoad(); finalPoll.resolve(queued({ id: 'offline-job' })); await work;
  assert.deepEqual(cancelled, ['/api/jobs/offline-job/cancel']);
  assert.equal(h.ctx.state().LOADING, null);
});

test('a prior successful launch hide timer cannot hide a newer pending launch', async () => {
  const newPoll = deferred(), began = deferred(); let hide = 0; const delayed = [];
  const h = launchHarness(async url => {
    if (url.startsWith('/api/catalog/')) return catalog();
    if (url.startsWith('/api/games/first/')) return { id: 'old' };
    if (url.startsWith('/api/games/second/')) return { id: 'new' };
    if (url === '/api/jobs/old') return { state: 'succeeded', output: { session_id: 'old-session' } };
    if (url === '/api/jobs/new') { began.resolve(); return newPoll.promise; }
    throw new Error('unexpected ' + url);
  });
  h.ctx.loader.hide = () => hide++;
  h.ctx.setTimeout = (f, ms) => ms === 500 ? delayed.push(f) : setImmediate(f);
  await h.ctx.play('first');
  const current = h.ctx.play('second'); await began.promise;
  delayed[0](); assert.equal(hide, 0);
  assert.equal(h.ctx.state().LOADING.job, 'new');
  newPoll.resolve({ state: 'succeeded', output: { session_id: 'new-session' } }); await current;
});

test('malformed successful result is diagnosed without discarding known-job cancellation', async () => {
  let cancelled = 0;
  const h = launchHarness(async url => {
    if (url.startsWith('/api/catalog/')) return catalog();
    if (url.startsWith('/api/games/')) return { id: 'bad-result' };
    if (url.endsWith('/cancel')) { cancelled++; return {}; }
    if (url === '/api/jobs/bad-result') return { state: 'succeeded', output: {} };
    throw new Error('unexpected ' + url);
  });
  await h.ctx.play('game');
  assert.equal(h.shown.some(a => a[0] === 'Sessions'), false);
  assert.equal(h.ctx.state().LOADING?.job, 'bad-result');
  assert.match(h.fails.at(-1), /session|result/i);
  await h.ctx.cancelLoad(); assert.equal(cancelled, 1);
});

test('a job queued by worker name (launched while it was down) resolves the same worker', () => {
  const note = helpers()(queued({ require_worker: 'i9-NUC' }), [jay(), nuc()], 'i9-NUC', NOW);
  assert.match(note, /^i9-NUC's gBox worker is offline/);
});

test('unknown worker and no worker of the required OS are both explained', () => {
  const f = helpers();
  assert.match(f(queued({ require_worker: 'ghost-pc' }), [jay(), spark], 'ghost-pc', NOW),
    /worker named ghost-pc, which isn't connected/);
  const none = f(queued({ require_os: 'windows' }), [nuc(), jay({ online: false, last_seen: NOW / 1000 - 120 }), spark], 'auto', NOW);
  assert.match(none, /^No Windows gBox worker is online \(JAYBUILTFINALE last checked in 2 min ago\)/);
});

test('online workers: idle says nothing, busy says it is next once the wait is noticeable', () => {
  const f = helpers();
  assert.equal(f(queued({ require_worker: jay().id }), [jay(), nuc()], 'JAYBUILTFINALE', NOW), '');
  assert.equal(f(queued({ require_worker: jay().id, created: NOW / 1000 - 3 }), [jay({ active_jobs: 2 })], 'x', NOW), '');
  assert.match(f(queued({ require_worker: jay().id }), [jay({ active_jobs: 1 })], 'x', NOW),
    /^JAYBUILTFINALE is online but still busy with 1 other job;/);
  assert.equal(f(queued({ require_os: 'windows' }), [nuc(), jay()], 'auto', NOW), '');
  assert.equal(f({ ...queued({ require_worker: nuc().id }), state: 'running' }, [nuc()], 'i9-NUC', NOW), '');
  assert.equal(f(queued(), null, 'auto', NOW), '');
});

// The real play() loop: an offline worker is shown on the loader, the launch keeps waiting
// (no five-minute failure), and it opens the session once the worker reconnects and runs it.
test('play() shows the offline worker, keeps waiting, then opens the game when it reconnects', async () => {
  let clock = NOW, polls = 0, cancelled = 0;
  const msgs = [], fails = [], shown = [];
  let worker = nuc();
  const job = { id: 'e4dc01d6ac784fdc', state: 'queued', created: NOW / 1000, require_worker: worker.id };
  const api = async (url, body, method) => {
    if (url.startsWith('/api/catalog/')) return { title: 'Dead or Alive (USA)', core: 'pcsx_rearmed', platform: 'psx' };
    if (url.startsWith('/api/games/')) return { id: job.id };
    if (url === '/api/workers') return [worker, jay(), spark];
    if (url.endsWith('/cancel')) { cancelled++; return {}; }
    if (url === '/api/jobs/' + job.id) {
      polls++;
      if (polls === 900) worker = nuc({ online: true, last_seen: clock / 1000, active_jobs: 0 });  // past 750 polls: no timeout
      if (polls === 903) Object.assign(job, { state: 'running' });
      if (polls === 905) Object.assign(job, { state: 'succeeded', output: { session_id: 'e82335a1adfd4e14-abc' } });
      return { ...job };
    }
    throw new Error('unexpected ' + url);
  };
  const el = { style: {}, onclick: null };
  const ctx = vm.createContext({ console, encodeURIComponent, addEventListener() {},
    Date: { now: () => (clock += 1000) },
    setTimeout: f => setImmediate(f), api, runJob: async () => ({}),
    $: () => el, bootGet: () => ({}), show: (...a) => { shown.push(a); },
    WHERE: 'local', window: { GBOX_LOCAL: { worker: 'i9-NUC' } },
    loader: { show() {}, hide() {}, progress: (p, m) => msgs.push(m), fail: m => fails.push(m) } });
  vm.runInContext(source.replace(/^let WHERE[^\n]*\n/m, '') + '\nthis.play = play; this.state = () => ({ LOADING, LAST_LAUNCH });', ctx);
  await ctx.play('deabd11481aa5a0c');
  assert.deepEqual(fails, [], 'an offline worker must not turn into a five-minute failure');
  const offline = msgs.filter(m => /i9-NUC's gBox worker is offline/.test(m || ''));
  assert.ok(offline.length >= 1, 'loader must name the offline worker: ' + JSON.stringify(msgs.slice(0, 4)));
  assert.ok(msgs.indexOf(offline[0]) <= 2, 'the explanation appears on the first worker check');
  assert.ok(msgs.includes('Worker picked up the launch'));
  assert.equal(msgs.at(-1), 'Running — opening the stream');
  assert.deepEqual(shown.at(-1), ['Sessions', 'e82335a1adfd4e14-abc']);
  assert.equal(cancelled, 0);
  assert.equal(ctx.state().LOADING, null);
});
