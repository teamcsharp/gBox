// #712 / #1081: shared control-plane reads and coalesced pop-up syncs of the desktop shell (clients/desktop/live-poll.js)
const { test } = require('node:test');
const assert = require('node:assert/strict');
const P = require('../clients/desktop/live-poll.js');

const tick = () => new Promise(resolve => setImmediate(resolve));
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

test('concurrent callers share one request and a fresh answer is reused', async () => {
  let now = 0, calls = [];
  const read = P.cachedRead(() => { const d = deferred(); calls.push(d); return d.promise; }, { ttl: 1000, now: () => now });
  const a = read.get(), b = read.get(), c = read.get(); await tick();
  assert.equal(calls.length, 1);
  calls[0].resolve({ ok: true, data: [1] });
  assert.deepEqual(await Promise.all([a, b, c]).then(r => r.map(x => x.data[0])), [1, 1, 1]);
  now = 999; assert.equal((await read.get()).data[0], 1); assert.equal(calls.length, 1);
  now = 1000; const d = read.get(); await tick(); assert.equal(calls.length, 2, 'an answer as old as the ttl is refetched');
  calls[1].resolve({ ok: true, data: [2] }); assert.equal((await d).data[0], 2);
  const e = read.get(0); await tick(); assert.equal(calls.length, 3, 'maxAge 0 always fetches');
  calls[2].resolve({ ok: true, data: [3] }); await e;
});

test('a failed answer is shared briefly; a rejection is not cached and reaches the caller', async () => {
  let now = 0, n = 0, fail = 'answer';
  const read = P.cachedRead(async () => { n++; if (fail === 'throw') throw new Error('ipc gone'); return fail === 'answer' ? { ok: false, error: '502' } : { ok: true, data: n }; },
    { ttl: 1000, now: () => now });
  assert.equal((await read.get()).ok, false);
  assert.equal((await read.get()).ok, false); assert.equal(n, 1, 'a down API is not hammered by every caller');
  now = 2000; fail = 'throw';
  await assert.rejects(read.get(), /ipc gone/);
  fail = 'ok'; assert.equal((await read.get()).data, 3, 'the next call retries at once after a rejection');
});

test('peek never waits: it returns the last good answer and refreshes it in the background', async () => {
  let now = 0, calls = [];
  const read = P.cachedRead(() => { const d = deferred(); calls.push(d); return d.promise; }, { ttl: 1000, now: () => now });
  assert.equal(read.peek(), null); await tick();
  assert.equal(calls.length, 1, 'the first peek starts the first read');
  calls[0].resolve({ ok: true, data: 'a' }); await tick(); await tick();
  assert.equal(read.peek().data, 'a'); assert.equal(calls.length, 1);
  now = 1500; assert.equal(read.peek().data, 'a', 'stale but immediate'); await tick();
  assert.equal(calls.length, 2);
  assert.equal(read.peek().data, 'a'); await tick(); assert.equal(calls.length, 2, 'one background refresh at a time');
  calls[1].resolve({ ok: false, error: 'down' }); await tick(); await tick();
  assert.equal(read.peek().data, 'a', 'a failed refresh keeps the last good answer');
  now = 4000; read.peek(); await tick();
  calls[2].reject(new Error('gone')); await tick(); await tick();   // a background rejection is swallowed
  assert.equal(read.peek().data, 'a');
});

test('view cadence: fast while visible, slow otherwise', () => {
  assert.equal(P.due(0, true, 5000, 60000, 4999), false);
  assert.equal(P.due(0, true, 5000, 60000, 5000), true);
  assert.equal(P.due(0, false, 5000, 60000, 59999), false);
  assert.equal(P.due(0, false, 5000, 60000, 60000), true);
});

test('coalesce: a burst of DOM changes runs one sync, and a change during a sync runs exactly one more', async () => {
  const timers = []; let now = 0, runs = 0, gate = null;
  const trigger = P.coalesce(async () => { runs++; if (gate) await gate.promise; },
    { minMs: 32, now: () => now, schedule: (cb, ms) => timers.push({ cb, ms }) });
  for (let i = 0; i < 20; i++) trigger();
  assert.equal(timers.length, 1); assert.equal(timers[0].ms, 0, 'the first change is followed in the next frame');
  gate = deferred(); timers.shift().cb(); assert.equal(runs, 1);
  for (let i = 0; i < 5; i++) trigger();                       // pop-up opened while the first sync is still running
  assert.equal(timers.length, 0);
  now = 10; gate.resolve(); await tick();
  assert.equal(timers.length, 1); assert.equal(timers[0].ms, 22, 'at most one sync per 32 ms');
  gate = null; timers.shift().cb(); await tick();
  assert.equal(runs, 2); assert.equal(timers.length, 0, 'nothing left queued');
  now = 100; trigger(); assert.equal(timers[0].ms, 0);
});

test('the desktop shell loads the module before the scripts that use it', () => {
  const html = require('node:fs').readFileSync(require('node:path').join(__dirname, '../clients/desktop/index.html'), 'utf8');
  const load = html.indexOf('<script src="live-poll.js"></script>'), use = html.indexOf('GBoxLivePoll.cachedRead');
  assert.ok(load > 0 && use > load);
  assert.ok(!/gbox\.api\("\/api\/sessions"\)\.then|await gbox\.api\("\/api\/sessions"\)/.test(html), 'no caller downloads the whole session history directly');
});
