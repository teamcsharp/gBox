const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function setup(failure) {
  let now = 100000, calls = 0, disposals = 0;
  const state = { success: false }, commands = [];
  const video = { stats: () => ({ ready: false }),
    sync: async () => { calls++; if (!state.success) throw failure; return { ready: true }; },
    dispose() { disposals++; }, snapshot: () => null };
  const source = fs.readFileSync(path.join(__dirname, '../clients/desktop/game-surface.js'), 'utf8');
  const api = vm.runInNewContext(source.slice(0, source.indexOf('let gpuOverlaySending')) + '\n({GPU_GAME, gpuGamePresent});', {
    window: { GBoxGPUVideo: video }, document: { querySelector: () => null },
    Date: { now: () => now }, EMB: { last: 'before' }, VIEW: { mode: 'windowed' }, ovlRect() {},
    console: { warn() {} }, gbox: { embedSync: async command => {
      commands.push(command); return { ok: true, sourceId: `window:${command.pid}:0` };
    } }
  });
  return { api, commands, state, calls: () => calls, disposals: () => disposals,
    advance(ms) { now += ms; }, present(pid = 123) { return api.gpuGamePresent({ adapter: 'retroarch',
      detail: { pid }, session_id: 's1' }, { x: 20, y: 20, w: 640, h: 480 }, false, false, null, true); } };
}

test('an unreadable game falls back once and does not reparent again after its retry delay', async () => {
  const x = setup(Object.assign(new Error('Could not start video source'), { name: 'NotReadableError' }));
  assert.equal(await x.present(), false); assert.equal(x.api.GPU_GAME.blockedPid, 123);
  const count = x.commands.length; x.advance(40000);
  assert.equal(await x.present(), false); x.advance(40000); assert.equal(await x.present(), false);
  assert.equal(x.commands.length, count); assert.equal(x.calls(), 1); assert.equal(x.disposals(), 1);
});

test('a transient timeout still retries after the delay', async () => {
  const x = setup(new Error('Game capture timed out (source)'));
  assert.equal(await x.present(), false); assert.equal(x.api.GPU_GAME.blockedPid, null);
  x.advance(20000); assert.equal(await x.present(), false); assert.equal(x.calls(), 1);
  x.advance(10001); assert.equal(await x.present(), false); assert.equal(x.calls(), 2);
});

test('a new PID can capture successfully after the old source was unreadable', async () => {
  const x = setup(Object.assign(new Error('Could not start video source'), { name: 'NotReadableError' }));
  assert.equal(await x.present(), false); x.state.success = true;
  assert.equal(await x.present(124), true); assert.equal(x.calls(), 2);
  assert.equal(x.api.GPU_GAME.blockedPid, null); assert.equal(x.api.GPU_GAME.failedPid, null);
  assert.ok(x.commands.some(command => command.pid === 124 && command.surface === 'gpu-ready'));
});
