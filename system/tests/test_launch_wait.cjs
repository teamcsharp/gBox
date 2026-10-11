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
