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
  const msgs = [], fails = [], shown = [], hidden = [];
  const el = { style: {}, onclick: null };
  const ctx = vm.createContext({ console, encodeURIComponent, addEventListener() {},
    Date: { now: () => (clock += 1000) }, setTimeout: f => setImmediate(f), api,
    runJob: async () => ({}), $: () => el, bootGet: () => ({}),
    show: (...args) => shown.push(args), WHERE: 'local', window: { GBOX_LOCAL: { worker: 'i9-NUC' } },
    loader: { show() {}, hide() { hidden.push(true); }, progress: (p, m) => msgs.push(m), fail: m => fails.push(m) } });
  vm.runInContext(source + '\nthis.play = play; this.cancelLoad = cancelLoad; this.state = () => ({ LOADING, LAST_LAUNCH });', ctx);
  return { ctx, msgs, fails, shown, hidden };
}
const catalog = () => ({ title: 'Dead or Alive', core: 'pcsx_rearmed', platform: 'psx' });

test('failed switch dismisses its loader and returns to the game kept running on that PC', async () => {
  const h = launchHarness(async url => {
    if (url.startsWith('/api/catalog/')) return catalog();
    if (url.startsWith('/api/games/')) return { id: 'switch', require_worker: 'local' };
    if (url === '/api/jobs/switch') return { state: 'failed', error: 'previous game could not be saved' };
    if (url === '/api/sessions') return [
      { session_id: 'other-test', state: 'running', started: 200, detail: { worker_name: 'other' } },
      { session_id: 'local-game', state: 'running', started: 100, detail: { worker_name: 'i9-NUC' } }];
    throw new Error('unexpected ' + url);
  });
  await h.ctx.play('game');
  assert.equal(h.ctx.state().LOADING, null);
  assert.equal(h.hidden.length, 1);
  assert.deepEqual(h.shown.at(-1), ['Sessions', 'local-game']);
  assert.match(h.ctx.state().LAST_LAUNCH.error, /previous game could not be saved/);
});

test('failed switch session lookup cannot navigate over a newer launch', async () => {
  const sessions = deferred(), lookup = deferred(), poll = deferred(), started = deferred();
  const h = launchHarness(async url => {
    if (url.startsWith('/api/catalog/')) return catalog();
    if (url.startsWith('/api/games/first')) return { id: 'old' };
    if (url.startsWith('/api/games/second')) return { id: 'new' };
    if (url === '/api/jobs/old') return { state: 'failed', error: 'failed switch' };
    if (url === '/api/sessions') { lookup.resolve(); return sessions.promise; }
    if (url === '/api/jobs/new') { started.resolve(); return poll.promise; }
    throw new Error('unexpected ' + url);
  });
  const old = h.ctx.play('first'); await lookup.promise;
  const next = h.ctx.play('second'); await started.promise;
  sessions.resolve([]); await old;
  assert.equal(h.shown.length, 0);
  poll.resolve({ state: 'succeeded', output: { session_id: 'new-game' } }); await next;
});

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

test('an unexplained running launch timeout retains its exact job for later Cancel', async () => {
  let reads = 0; const cancellations = [];
  const h = launchHarness(async url => {
    if (url.startsWith('/api/catalog/')) return catalog();
    if (url.startsWith('/api/games/')) return { id: 'slow-running' };
    if (url.endsWith('/cancel')) { cancellations.push(url); return {}; }
    if (url === '/api/jobs/slow-running') { reads++; return { state: 'running' }; }
    throw new Error('unexpected ' + url);
  });
  await h.ctx.play('game');
  assert.equal(reads, 750);
  assert.match(h.fails.at(-1), /has not finished.*Esc to cancel/);
  assert.equal(h.ctx.state().LOADING?.job, 'slow-running');
  await h.ctx.cancelLoad();
  assert.deepEqual(cancellations, ['/api/jobs/slow-running/cancel']);
});

test('the real loader delayed cancel animation cannot hide a newly started Play', async () => {
  const loaderStart = html.indexOf('const loader = {');
  const loaderEnd = html.indexOf('// ---- microphone device:', loaderStart);
  assert.ok(loaderStart >= 0 && loaderEnd > loaderStart);
  const loaderSource = html.slice(loaderStart, loaderEnd);
  const nodes = new Map(), timers = [], oldPoll = deferred(), oldBegan = deferred(), newPoll = deferred(), began = deferred();
  let oldReads = 0;
  const $ = selector => {
    if (!nodes.has(selector)) {
      const names = new Set();
      nodes.set(selector, { style: {}, firstChild: null,
        classList: { add: (...x) => x.forEach(y => names.add(y)), remove: (...x) => x.forEach(y => names.delete(y)), contains: x => names.has(x) } });
    }
    return nodes.get(selector);
  };
  const ctx = vm.createContext({ console, encodeURIComponent, addEventListener() {}, $,
    Date: { now: () => NOW }, setTimeout: (f, ms) => timers.push({ f, ms }),
    api: async url => {
      if (url.startsWith('/api/catalog/')) return catalog();
      if (url.startsWith('/api/games/old/')) return { id: 'old' };
      if (url.startsWith('/api/games/new/')) return { id: 'new' };
      if (url.endsWith('/cancel')) return {};
      if (url === '/api/jobs/old') {
        if (++oldReads === 1) { oldBegan.resolve(); return oldPoll.promise; }
        return { state: 'queued' };
      }
      if (url === '/api/jobs/new') { began.resolve(); return newPoll.promise; }
      throw new Error('unexpected ' + url);
    },
    runJob: async () => ({}), bootGet: () => ({}), esc: x => String(x),
    show() {}, WHERE: 'local', window: { GBOX_LOCAL: { worker: 'JAYBUILTFINALE' } } });
  vm.runInContext(loaderSource + source + '\nloader.scene=async()=>({});this.realLoader=loader;this.play=play;this.cancelLoad=cancelLoad;', ctx);
  // Cancel the real visible old loader, then start a new launch during its600ms exit animation.
  const old = ctx.play('old'); await oldBegan.promise;
  await ctx.cancelLoad();
  const work = ctx.play('new'); await began.promise;
  assert.equal($('#loader').classList.contains('on'), true);
  const cancelAnimation = timers.find(t => t.ms === 600);
  assert.ok(cancelAnimation);
  cancelAnimation.f();
  assert.equal($('#loader').classList.contains('on'), true, 'new launch must remain visible after the old hide animation fires');
  oldPoll.resolve({ state: 'queued' }); await old;
  newPoll.resolve({ state: 'succeeded', output: { session_id: 'new-session' } }); await work;
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

test('#1294: slots held with nothing running on the Spark are reported as a stuck worker, not busy', () => {
  const f = helpers();
  const stuck = nuc({ online: true, last_seen: NOW / 1000 - 4, active_jobs: 4, running_jobs: 0 });
  const note = f(queued({ require_worker: nuc().id, created: NOW / 1000 - 480 }), [stuck, jay()], 'i9-NUC', NOW);
  assert.match(note, /^i9-NUC is online but stuck: it reports 4 job slots in use while the Spark has no job running there/);
  assert.match(note, /Restart gBox on i9-NUC/);
  assert.doesNotMatch(note, /busy with/);
  // under a minute it may just be a result in flight: keep the plain busy note
  assert.match(f(queued({ require_worker: nuc().id, created: NOW / 1000 - 30 }), [stuck], 'i9-NUC', NOW), /still busy with 4 other jobs/);
  // genuinely busy (the Spark has jobs running there), or an older server without the field: busy note
  assert.match(f(queued({ require_worker: nuc().id, created: NOW / 1000 - 480 }), [{ ...stuck, running_jobs: 2 }], 'i9-NUC', NOW),
    /still busy with 4 other jobs/);
  const { running_jobs, ...old } = stuck;
  assert.match(f(queued({ require_worker: nuc().id, created: NOW / 1000 - 480 }), [old], 'i9-NUC', NOW), /still busy with 4 other jobs/);
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


// "This PC" is a host choice, independent of a libretro core or adapter.
for (const platform of ['xbox', 'xbox360', 'windows_native', 'switch', 'ps2', 'ps3', 'gamecube']) {
  test(`This PC pins ${platform} without a core to i9-NUC`, async () => {
    let request;
    const h = launchHarness(async url => {
      if (url.startsWith('/api/catalog/')) return { title: 'Standalone game', platform, core: null };
      if (url.startsWith('/api/games/')) { request=url; throw Error('stop after routing'); }
      throw Error('unexpected '+url);
    });
    await h.ctx.play('game', undefined, false, { disc: 'custom build', label: 'My build' });
    const params = new URL(request, 'http://test').searchParams;
    assert.equal(params.get('node'), 'i9-NUC');
    assert.equal(params.get('mod'), 'custom build');
    assert.equal(h.ctx.state().LAST_LAUNCH.node, 'i9-NUC');
  });
}
test('catalog lookup failure still pins This PC instead of delegating automatically', async () => {
  let request;
  const h = launchHarness(async url => {
    if (url.startsWith('/api/catalog/')) throw Error('catalog unavailable');
    request=url;throw Error('stop after routing');
  });
  await h.ctx.play('game');
  assert.equal(new URL(request,'http://test').searchParams.get('node'),'i9-NUC');
});
for (const [where, explicit, debug, expected] of [
  ['local','JAYBUILTFINALE',false,'JAYBUILTFINALE'],
  ['spark',undefined,false,'linux'], ['local',undefined,true,'linux']
]) {
  test(`explicit launch selection remains ${expected}: ${where}/${explicit}/${debug}`, async () => {
    let request;
    const h = launchHarness(async url => {
      if (url.startsWith('/api/catalog/')) return {title:'Standalone game',platform:'xbox',core:null};
      request=url;throw Error('stop after routing');
    });
    h.ctx.WHERE=where;
    await h.ctx.play('game',explicit,debug);
    assert.equal(new URL(request,'http://test').searchParams.get('node'),expected);
  });
}
