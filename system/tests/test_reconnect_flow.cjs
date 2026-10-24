const test = require('node:test'), assert = require('node:assert/strict');
const F = require('../clients/desktop/reconnect-flow.js');

function rig(over = {}) {
  let clock = 0;
  const calls = [], renders = [], memory = new Map();
  const r = { calls, renders, memory, mode: 'remote', remoteReady: true, pip: null, restarts: 0, reloads: 0,
    mercmode: { hosts: [{ name: 'lilspark', online: true, settings: { enabled: true },
      current_run: { phase: 'playing', session_id: 'w1-s1', title: 'Resident Evil 5' } }] },
    health: { state: 'running', age_s: 0.1 }, ...over };
  r.io = {
    status: async () => ({ mode: r.mode, remote: { ready: r.remoteReady } }),
    restartSpark: async () => { r.restarts++; if (r.recoverOnRestart) r.remoteReady = true; },
    select: async mode => { calls.push(['select', mode]); r.mode = mode; },
    reload: async () => { r.reloads++; },
    remember: (k, v) => memory.set(k, v), forget: k => memory.delete(k),
    api: async (path, body) => {
      calls.push([path, body]);
      if (path === '/api/mercmode' && body) { r.mercmode.hosts[0].settings.enabled = body.enabled; if (r.startOnEnable)
        r.mercmode.hosts[0].current_run = { phase: 'playing', session_id: 'w1-new', title: 'Resident Evil 4' }; return r.mercmode; }
      if (path === '/api/mercmode') return JSON.parse(JSON.stringify(r.mercmode));
      if (path.endsWith('/stream/health')) return r.health;
      if (path === '/api/jobs') { r.health = { state: 'running', age_s: 0.2 }; return { id: 'j' }; }
      throw Error('unexpected ' + path);
    },
    pickHost: data => F.pickHost(data, 'JAYBUILTFINALE'),
    pipSession: () => r.pip, pipEnter: async sid => { r.pip = sid; }, pipRestore: async () => { r.pip = null; },
    show: () => {},
  };
  r.ctl = F.create({ io: r.io, render: s => renders.push(s), sleep: async ms => { clock += ms; }, now: () => clock });
  return r;
}

test('a healthy Spark with MercMode playing goes straight to picture-in-picture', async () => {
  const r = rig();
  const out = await r.ctl.run();
  assert.equal(out.done, true); assert.equal(r.pip, 'w1-s1'); assert.equal(r.restarts, 0);
  assert.deepEqual(out.steps.map(s => s.status), ['ok', 'ok', 'ok', 'ok', 'ok']);
});

test('a window on This PC switches to the Spark and reloads, remembering to resume', async () => {
  const r = rig({ mode: 'local' });
  const out = await r.ctl.run();
  assert.deepEqual(r.calls[0], ['select', 'remote']); assert.equal(r.reloads, 1);
  assert.equal(r.memory.get(F.RESUME_KEY), '1'); assert.equal(out.done, false); assert.equal(r.pip, null);
  const again = await r.ctl.run();                                  // after the reload
  assert.equal(again.done, true); assert.equal(r.memory.has(F.RESUME_KEY), false);
});

test('a silent Spark is restarted once, then the flow continues', async () => {
  const r = rig({ remoteReady: false, recoverOnRestart: true });
  const out = await r.ctl.run();
  assert.equal(r.restarts, 1); assert.equal(out.done, true);
  const s = rig({ remoteReady: false });
  const failed = await s.ctl.run();
  assert.equal(failed.done, false); assert.match(failed.error, /not answering/); assert.equal(failed.steps[0].status, 'err');
});

test('MercMode is turned on when off, and a stale picture gets a new encoder', async () => {
  const r = rig({ startOnEnable: true, health: { state: 'running', age_s: 40 } });
  r.mercmode.hosts[0].settings.enabled = false; r.mercmode.hosts[0].current_run = null;
  const out = await r.ctl.run();
  assert.ok(r.calls.some(([p, b]) => p === '/api/mercmode' && b?.enabled === true));
  assert.ok(r.calls.some(([p, b]) => p === '/api/jobs' && b.input.op === 'restart_stream'));
  assert.equal(out.done, true); assert.equal(r.pip, 'w1-new');
});

test('the shown PC prefers this PC playing, then any PC playing, then the Spark', () => {
  const play = name => ({ name, online: true, current_run: { phase: 'playing', session_id: name + '-s' } });
  assert.equal(F.pickHost({ hosts: [play('i9-NUC'), play('JAYBUILTFINALE')] }, 'JAYBUILTFINALE').name, 'JAYBUILTFINALE');
  assert.equal(F.pickHost({ hosts: [{ name: 'lilspark', online: true }, play('i9-NUC')] }, 'x').name, 'i9-NUC');
  assert.equal(F.pickHost({ hosts: [{ name: 'lilspark', online: true }] }, 'x').name, 'lilspark');
  assert.equal(F.pickHost({ hosts: [] }, 'x'), null);
});

test('a MercMode status that times out is asked again instead of failing the flow', async () => {
  const r = rig(); let fails = 2; const api = r.io.api;
  r.io.api = async (path, body) => { if (path === '/api/mercmode' && !body && fails-- > 0) throw Error('The operation was aborted due to timeout'); return api(path, body); };
  const out = await r.ctl.run();
  assert.equal(out.done, true); assert.equal(r.pip, 'w1-s1');
});
