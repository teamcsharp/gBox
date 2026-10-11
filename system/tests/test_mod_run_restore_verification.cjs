const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../clients/desktop/index.html'), 'utf8');
const start = html.indexOf('async function modRun(c, sid) {');
const end = html.indexOf('async function modSession(m, launch)', start);
assert.ok(start >= 0 && end > start, 'exercise the actual desktop modRun function');
const source = html.slice(start, end);
const message = 'The mod opened, but restoration of the saved game moment was not verified. This replacement still needs verification.';

function harness(responses) {
  const calls = [], delays = [];
  const context = vm.createContext({
    gbox: { api: async (...args) => {
      calls.push(JSON.parse(JSON.stringify(args)));
      assert.ok(responses.length, 'unexpected extra API request');
      return responses.shift();
    } },
    setTimeout: (callback, delay) => { delays.push(delay); callback(); },
  });
  vm.runInContext(source, context);
  return { run: context.modRun, calls, delays };
}

const swap = { tool: '@launch', input: { mod: 'reviewed-native-mod' } };

for (const [name, flags] of [
  ['missing verification flags', {}],
  ['explicit false verification', { load_requested: true, load_verified: false }],
  ['unknown verification', { load_requested: null, load_verified: null }],
  ['verified but not loaded', { load_requested: true, load_verified: true }],
]) {
  test(`state_loaded=false with ${name} retains the reporting error and job ID`, async () => {
    const h = harness([
      { ok: true, data: { id: 'swap-job-17', state: 'queued' } },
      { ok: true, data: { id: 'swap-job-17', state: 'running' } },
      { ok: true, data: { id: 'swap-job-17', state: 'succeeded', output: { state_loaded: false, ...flags } } },
    ]);
    await assert.rejects(h.run(swap, 'JAYBUILTFINALE-session/17'), err => {
      assert.equal(err.message, message);
      assert.equal(err.jobId, 'swap-job-17');
      return true;
    });
    assert.deepEqual(h.calls, [
      ['/api/sessions/JAYBUILTFINALE-session%2F17/swap', { mod: 'reviewed-native-mod', keep_state: true }],
      ['/api/jobs/swap-job-17'], ['/api/jobs/swap-job-17'],
    ]);
    assert.deepEqual(h.delays, [500, 500]);
  });
}

test('a verified loaded swap continues with its exact job output', async () => {
  const job = { id: 'verified-swap', state: 'succeeded', output: { state_loaded: true, load_requested: true, load_verified: true } };
  const h = harness([{ ok: true, data: job }]);
  assert.equal(await h.run(swap, 'worker-session'), job);
  assert.equal(h.calls.length, 1);
  assert.deepEqual(h.delays, []);
});

test('legacy output without state_loaded keeps the existing guard semantics', async () => {
  const job = { id: 'legacy-swap', state: 'succeeded', output: {} };
  const h = harness([{ ok: true, data: job }]);
  assert.equal(await h.run(swap, 'worker-session'), job);
});

test('non-launch mod tools keep their own success semantics', async () => {
  const job = { id: 'ordinary-job', state: 'succeeded', output: { state_loaded: false } };
  const h = harness([{ ok: true, data: job }]);
  assert.equal(await h.run({ tool: 'character_swap', input: { character: 'amy' } }, 'JAYBUILTFINALE-session'), job);
  assert.deepEqual(h.calls, [['/api/jobs', {
    tool: 'character_swap', input: { character: 'amy', session_id: 'JAYBUILTFINALE-session' }, require_worker: 'JAYBUILTFINALE',
  }]]);
});

test('actual job failure retains the original native error and job ID', async () => {
  const h = harness([{ ok: true, data: { id: 'failed-swap', state: 'failed', error: 'native load rejected' } }]);
  await assert.rejects(h.run(swap, 'worker-session'), err => {
    assert.equal(err.message, '@launch: native load rejected');
    assert.equal(err.jobId, 'failed-swap');
    return true;
  });
});
