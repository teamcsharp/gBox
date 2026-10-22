const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const M = require('../clients/web/viz/re4-spawn.js');
const S = { session_id: 'w-1', state: 'running', adapter: 'dolphin', title: 'Resident Evil 4 (GameCube)' };

test('value to op mapping: 1 reverts, 2-4 set count', () => {
  assert.deepEqual(M.input(1), { op: 'spawn_multiplier', on: false });
  for (const n of [2, 3, 4]) assert.deepEqual(M.input(n), { op: 'spawn_multiplier', count: n, on: true });
});
test('clamps to 1..4', () => {
  assert.equal(M.clamp(0), 1); assert.equal(M.clamp(-5), 1); assert.equal(M.clamp(9), 4);
  assert.equal(M.clamp('abc'), 1); assert.equal(M.clamp(2.6), 3);
  assert.deepEqual(M.input(8), { op: 'spawn_multiplier', count: 4, on: true });
});
test('only a running RE4 GameCube Dolphin session is eligible', () => {
  assert.equal(M.eligible(S), true);
  for (const c of [{ state: 'ended' }, { adapter: 'rpcs3' }, { title: 'Resident Evil 4 (2023)' },
    { title: 'Resident Evil 4: Wii Edition' }, { title: 'Resident Evil 5' }, { stopping: true }, { session_id: 'x' }])
    assert.equal(M.eligible({ ...S, ...c }), false);
});
test('job is sent to the exact worker/session as operator job', async () => {
  const calls = [];
  const api = async (path, body) => { calls.push({ path, body }); return { id: 'j', state: 'succeeded' }; };
  const c = M.create({ session: S, api });
  await c.set(3); await c.set(1);
  assert.deepEqual(calls[0].body, { tool: 're_mods', agent_use: false, require_worker: 'w',
    input: { session_id: 'w-1', op: 'spawn_multiplier', count: 3, on: true } });
  assert.deepEqual(calls[1].body.input, { session_id: 'w-1', op: 'spawn_multiplier', on: false });
  assert.equal(c.state().value, 1); assert.equal(c.state().error, false);
});
test('failed job keeps old value and reports error', async () => {
  const c = M.create({ session: S, api: async () => ({ id: 'j', state: 'failed', error: 'boom' }) });
  await c.set(4);
  assert.equal(c.state().value, 1); assert.equal(c.state().error, true); assert.match(c.state().message, /boom/);
});
test('html slider has 1..4 bounds and shell loads the script', () => {
  assert.match(M.html({ value: 7 }), /min="1" max="4" step="1" value="4"/);
  assert.match(fs.readFileSync(require.resolve('../clients/web/index.html'), 'utf8'), /\/viz\/re4-spawn\.js/);
});
