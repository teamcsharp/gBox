const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const M = require('../clients/web/viz/re5-modifiers.js');
const BD = require('../clients/web/viz/bot-demo.js');
const SESSION = { session_id: 'worker-launch', game_id: M.GAME, state: 'running', adapter: 'rpcs3' };
const BASE = { unlimited_health: false, infinite_ammo: true, fire_rate_x: 1, turn_speed_x: 1,
  bullet_damage_x: 1, in_hand: { weapon: 'M500' }, capabilities: Object.fromEntries(
    [...M.DEFINITIONS.map(row => row.op), 'random_weapon'].map(op => [op, { available: true }])) };
function rig() {
  const out = { status: structuredClone(BASE), calls: [], paints: [], sessions: [SESSION], active: [], clock: 0 };
  out.api = async (path, body, method) => {
    out.calls.push({ path, body, method });
    if (path.startsWith('/api/sessions')) return out.sessions;
    if (path.startsWith('/api/jobs?')) return out.active;
    if (path.startsWith('/api/jobs/')) return out.poll ? out.poll(path) : { id: 'job', state: 'succeeded', output: { result: { verified: true } } };
    assert.equal(path, '/api/jobs');
    const { op, on, multiplier } = body.input;
    let result;
    if (op === 'status') {
      if (out.onStatus) out.onStatus();
      result = { status: structuredClone(out.status) };
    } else if (out.command) result = await out.command(body.input);
    else {
      const definition = M.DEFINITIONS.find(d => d.op === op);
      out.status[definition.field] = definition.multiplier ? on ? multiplier : 1 : on;
      result = { verified: true };
    }
    return { id: 'job', state: 'succeeded', output: { result } };
  };
  out.control = M.create({ session: SESSION, api: out.api, render: s => out.paints.push(s),
    delay: async ms => { out.clock += ms; }, now: () => out.clock });
  out.commands = () => out.calls.filter(c => c.body && c.body.input.op !== 'status');
  return out;
}

test('only the exact running RE5 RPCS3 session gets controls', () => {
  assert.equal(M.eligible(SESSION), true);
  for (const change of [{ state: 'ended' }, { game_id: 'other' }, { adapter: 'retroarch' }, { stopping: true }, { session_id: '' }])
    assert.equal(M.eligible({ ...SESSION, ...change }), false);
});

test('toggle uses exact session and worker, operator job, verified status and explicit off', async () => {
  const r = rig(); await r.control.refresh();
  await r.control.change('fire_rate', true);
  assert.deepEqual(r.commands()[0].body, { tool: 're5_mods', agent_use: false, require_worker: 'worker',
    input: { session_id: 'worker-launch', op: 'fire_rate', on: true, multiplier: 80 } });
  assert.equal(r.control.state().status.fire_rate_x, 80);
  await r.control.change('fire_rate', false);
  assert.deepEqual(r.commands()[1].body.input, { session_id: 'worker-launch', op: 'fire_rate', on: false });
  assert.equal(r.control.state().status.fire_rate_x, 1);
  assert.equal(r.control.state().error, false);
});

test('all existing supported modifiers use fixed verified operations and presets', async () => {
  for (const op of ['unlimited_health', 'infinite_ammo', 'turn_speed', 'bullet_damage']) {
    const r = rig(); await r.control.refresh(); await r.control.change(op, true);
    assert.equal(r.commands()[0].body.input.op, op);
    assert.equal(r.control.state().error, false);
    await r.control.change(op, false);
    assert.equal(r.commands()[1].body.input.on, false);
  }
});

test('pending operation disables every modifier and does not optimistically flip state', async () => {
  const r = rig(); await r.control.refresh();
  let finish;
  r.command = () => new Promise(resolve => { finish = () => { r.status.unlimited_health = true; resolve({ verified: true }); }; });
  const first = r.control.change('unlimited_health', true);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(r.control.state().status.unlimited_health, false);
  assert.ok(M.rows(r.control.state()).every(row => row.disabled));
  await r.control.change('bullet_damage', true);
  assert.equal(r.commands().length, 1);
  finish(); await first;
  assert.equal(r.control.state().status.unlimited_health, true);
  assert.equal(r.control.state().busy, false);
});

test('fresh status wins over optimistic command result and failed verification is reported', async () => {
  for (const verified of [true, false]) {
    const r = rig(); await r.control.refresh();
    r.command = async () => ({ verified, reason: 'Readback did not match' });
    await r.control.change('unlimited_health', true);
    assert.equal(r.control.state().status.unlimited_health, false);
    assert.equal(r.control.state().error, true);
    assert.equal(r.control.state().stale, true);
  }
});

test('ended or replaced sessions never receive a mutation', async () => {
  for (const sessions of [[], [{ ...SESSION, state: 'ended' }], [{ ...SESSION, game_id: 'other' }]]) {
    const r = rig(); await r.control.refresh(); r.sessions = sessions;
    await r.control.change('bullet_damage', true);
    assert.equal(r.commands().length, 0);
    assert.match(r.control.state().message, /ended or changed/);
  }
});

test('server capability blocks a supported control; unimplemented hooks never send jobs', async () => {
  const r = rig();
  r.status.capabilities.unlimited_health = { available: false, reason: 'Signature unavailable' };
  await r.control.refresh();
  for (const op of ['unlimited_health', 'aimbot', 'instant_qte', 'auto_parry', 'knife_knockback', 'write_memory'])
    await r.control.change(op, true);
  assert.equal(r.commands().length, 0);
  assert.match(M.html(r.control.state()), /Signature unavailable/);
  assert.match(M.html(r.control.state()), /Aimbot/);
  assert.match(M.html(r.control.state()), /Unavailable: no verified live control/);
  assert.doesNotMatch(M.html(r.control.state()), /data-re5-mod="aimbot"/);
});

test('unknown state and escaped server reasons cannot become checked working controls', () => {
  const html = M.html({ status: { capabilities: { random_weapon: { available: false, reason: '<script>bad</script>' } } }, stale: false });
  assert.equal((html.match(/aria-checked="mixed"/g) || []).length, 6);
  assert.match(html, /&#60;script&#62;bad&#60;\/script&#62;/);
  assert.doesNotMatch(html, /<script>bad/);
});

test('old worker status fields never enable mutations or claim retained session overrides', async () => {
  const r = rig(); delete r.status.capabilities;
  await r.control.refresh();
  assert.ok(M.rows(r.control.state()).every(row => row.disabled && !row.available));
  assert.match(M.html(r.control.state()), /Worker update pending/);
  assert.doesNotMatch(r.control.state().message, /Choices are kept/);
  for (const op of [...M.DEFINITIONS.map(row => row.op), 'random_weapon']) await r.control.change(op, true);
  assert.equal(r.commands().length, 0);
});

test('random weapon waits for the matching confirmed request, never queue acceptance', async () => {
  const r = rig(); await r.control.refresh(); let reads = 0;
  r.command = async () => {
    r.status.random_weapon_request = { id: 'switch-1', state: 'pending', weapon: 'L. Hawk' };
    return { queued: true, verified: false, request: r.status.random_weapon_request };
  };
  r.onStatus = () => {
    if (++reads === 3) {
      r.status.random_weapon_request.state = 'confirmed'; r.status.in_hand.weapon = 'L. Hawk';
    }
  };
  await r.control.change('random_weapon');
  assert.equal(reads, 3);
  assert.equal(r.commands().length, 1);
  assert.deepEqual(r.commands()[0].body.input, { session_id: 'worker-launch', op: 'random_weapon' });
  assert.equal(r.control.state().message, 'Equipped L. Hawk.');
  assert.equal(r.control.state().weaponPending, null);
});

test('random weapon rejects a failed selection and times out without claiming success', async () => {
  for (const state of ['rejected', 'pending']) {
    const r = rig(); await r.control.refresh();
    r.command = async () => {
      r.status.random_weapon_request = { id: 'switch-1', state, reason: 'No eligible weapon' };
      return { queued: true, verified: false, request: { id: 'switch-1' } };
    };
    await r.control.change('random_weapon');
    assert.equal(r.control.state().error, true);
    assert.doesNotMatch(r.control.state().message, /Equipped/);
    assert.equal(r.commands().length, 1);
    if (state === 'pending') {
      assert.ok(M.rows(r.control.state()).every(row => row.disabled));
      await r.control.change('random_weapon');
      assert.equal(r.commands().length, 1);
      r.status.random_weapon_request.state = 'confirmed';
      await r.control.refresh();
      assert.equal(r.control.state().weaponPending, null);
    }
  }
});

test('another request confirmation cannot complete this weapon request', async () => {
  const r = rig(); await r.control.refresh();
  r.command = async () => {
    r.status.random_weapon_request = { id: 'other', state: 'confirmed' };
    return { queued: true, verified: false, request: { id: 'ours' } };
  };
  await r.control.change('random_weapon');
  assert.equal(r.control.state().error, true);
  assert.match(r.control.state().message, /not confirmed/);
});

test('an active server job prevents repeated mutation after reopening the panel', async () => {
  const r = rig(); await r.control.refresh();
  r.active = [{ id: 'existing', tool: 're5_mods', input: { session_id: SESSION.session_id } }];
  await r.control.change('infinite_ammo', false);
  assert.equal(r.commands().length, 0);
  assert.equal(r.control.state().pending, 'existing');
  r.active = [];
  await r.control.refresh();
  assert.equal(r.control.state().pending, null);
});

test('job polling failure leaves controls blocked until refresh resolves it', async () => {
  const r = rig(); await r.control.refresh();
  const api = r.api;
  let queued = true;
  r.control = M.create({ session: SESSION, api: async (...args) => {
    if (args[1]?.input?.op === 'status' && queued) return { id: 'queued', state: 'running' };
    if (args[0] === '/api/jobs/queued') return queued ? { id: 'queued', state: 'running' }
      : { id: 'queued', state: 'succeeded', output: { result: { status: r.status } } };
    return api(...args);
  }, delay: async ms => { r.clock += 30000; }, now: () => r.clock });
  await r.control.refresh();
  assert.equal(r.control.state().pending, 'queued');
  assert.equal(r.control.state().error, true);
  queued = false; await r.control.refresh();
  assert.equal(r.control.state().pending, null);
  assert.equal(r.control.state().error, false);
});

test('closing the panel suppresses late renders and further commands', async () => {
  const r = rig(); await r.control.refresh(); const count = r.paints.length;
  r.control.stop(); await r.control.change('fire_rate', true); await r.control.refresh();
  assert.equal(r.paints.length, count);
  assert.equal(r.commands().length, 0);
});

test('transport and terminal job failures report errors and keep controls unconfirmed', async () => {
  for (const transport of [true, false]) {
    const r = rig(); await r.control.refresh();
    r.command = async () => { if (transport) throw new Error('Worker unreachable'); return { verified: false, reason: 'Build mismatch' }; };
    await r.control.change('unlimited_health', true);
    assert.equal(r.control.state().error, true);
    assert.equal(r.control.state().status.unlimited_health, false);
    assert.match(r.control.state().message, transport ? /Worker unreachable/ : /Build mismatch/);
  }
  const control = M.create({ session: SESSION, api: async (path) => path.startsWith('/api/sessions') ? [SESSION]
    : path.startsWith('/api/jobs?') ? [] : { state: 'failed', error: { message: 'Memory unavailable' } } });
  await control.refresh();
  assert.match(control.state().message, /Memory unavailable/);
  assert.ok(M.rows(control.state()).every(row => row.disabled));
});

test('bot dropdown mounts modifiers inline and stops their controller when closed', () => {
  let stopped = false; const host = {};
  const el = { style: {}, contains: () => true, setAttribute() {}, querySelector: () => host };
  const doc = { getElementById: () => null, createElement: () => el, body: { append() {} }, addEventListener() {}, removeEventListener() {} };
  const menu = BD.open(doc, { modifiers: { html: '<section>Modifiers</section>', mount: target => {
    assert.equal(target, host); return { stop: () => { stopped = true; } };
  } } });
  assert.match(el.innerHTML, /Modifiers/);
  menu.close(); assert.equal(stopped, true);
});

test('shell binds controls to the exact currently opened session and authenticated operator API', () => {
  const shell = fs.readFileSync(require('node:path').join(__dirname, '../clients/web/index.html'), 'utf8');
  assert.match(shell, /<script src="\/viz\/re5-modifiers\.js"><\/script>/);
  assert.match(shell, /viewed\?\.session_id === anchor\?\.closest\?\.\("#session-head"\)\?\.dataset.sid/);
  assert.match(shell, /GBoxRE5Modifiers\.mount\(host, \{ session: current, api \}\)/);
  assert.doesNotMatch(fs.readFileSync(require.resolve('../clients/web/viz/re5-modifiers.js'), 'utf8'), /write_memory|read_memory|Bearer|x-gbox-actor/);
});
