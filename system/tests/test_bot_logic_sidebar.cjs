const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const S = require('../clients/desktop/bot-logic-sidebar.js');
const SESSION = { session_id: 'w123-re6', worker_id: 'worker-123', game_id: '115f9cdbba115432',
  adapter: 'citron', state: 'running', detail: { worker_name: 'lilspark' } };
const RE5 = { ...SESSION, session_id: 'w123-re5', game_id: '52d15709be0fda1a' };
const VIEW = { verified: true, title: 're6', knobs: [
  { name: 'FLASH', label: 'Flash and fight', group: 'Crowd control', kind: 'bool', value: true, set: false, min: 0, max: 1, step: 1 },
  { name: 'FLASH_GAP_S', label: 'Seconds between flashes', group: 'Crowd control', kind: 'float', value: 5, set: true,
    min: 0.5, max: 15, step: 0.5, help: 'fight window' },
  { name: 'FLASH_N', label: 'Crowd size', group: 'Crowd control', kind: 'int', value: 3, min: 2, max: 8, step: 1 }] };
const STATUS = { fire_rate_x: 4, infinite_ammo: true, infinite_tablets: true, infinite_stamina: false,
  infinite_grenades: true, auto_qte: true, kill_time_on: true, quick_attack_x: 10, down_fire_x: 3,
  unlimited_health: true, infinite_spray: true, qte_assist: { enabled: true } };
const ok = result => ({ id: 'j1', state: 'succeeded', output: { result } });
const defer = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };
function rig(session = SESSION) {
  const r = { calls: [], rows: [structuredClone(session)], shown: session.session_id, session, hook: null,
    status: structuredClone(STATUS), view: { ...structuredClone(VIEW), title: session.game_id === RE5.game_id ? 're5' : 're6' } };
  r.status.capabilities = Object.fromEntries(S.definitions('re5').map(d => [d.op, { available: true }]));
  r.api = async (url, body, method) => {
    r.calls.push({ url, body, method });
    const handled = r.hook && await r.hook(url, body, method);
    if (handled !== undefined && handled !== null) return handled;
    if (url === '/api/sessions?include_ended=false') return structuredClone(r.rows);
    assert.equal(url, '/api/jobs');
    assert.equal(method, 'POST');
    assert.equal(body.tool, 're5_mods');
    assert.equal(body.agent_use, false);
    const input = body.input;
    if (input.op === 'bot_logic') {
      for (const [name, value] of Object.entries(input.values || {})) r.view.knobs.find(k => k.name === name).value = value;
      return ok(structuredClone(r.view));
    }
    if (input.op === 'status') return ok(session.game_id === RE5.game_id ? { status: structuredClone(r.status) } : structuredClone(r.status));
    const d = S.definitions(r.view.title).find(d => d.op === input.op);
    if (d) r.status[d.field] = d.kind === 'bool' ? input.on : input.multiplier;
    return ok({ verified: true });
  };
  r.sb = S.create({ api: r.api, doc: null, delay: async () => {}, current: () => r.shown });
  r.select = session => {
    r.shown = session.session_id; r.rows = [session]; r.view.title = session.game_id === RE5.game_id ? 're5' : 're6';
    r.sb.update({ on: true, sid: session.session_id, session });
  };
  r.jobs = () => r.calls.filter(c => c.url === '/api/jobs');
  r.changes = () => r.jobs().filter(c => !['status', 'bot_logic'].includes(c.body.input.op) || c.body.input.values || c.body.input.reset);
  r.select(session);
  return r;
}

test('behavior knobs remain grouped and current mod controls show bounded fire rate and the selected PC', () => {
  const h = S.html(VIEW, '', { status: STATUS, title: 're6', pc: 'lilspark', scope: '3' });
  assert.match(h, /<h4>Crowd control<\/h4>/);
  assert.match(h, /type="checkbox" data-bl="FLASH" checked/);
  assert.match(h, /type="range" data-bl="FLASH_GAP_S" min="0.5" max="15" step="0.5" value="5"/);
  assert.match(h, /data-bl-mod="fire_rate" min="1" max="80"[^>]*value="4"/);
  assert.match(h, /data-bl-mod="infinite_grenades" checked/);
  assert.match(h, /lilspark.*game shown in this PiP/);
  assert.match(h, /bl-set/);
  assert.match(h, /data-bl-scope="3"/);
});

test('only current running RE5 and RE6 Switch sessions are eligible, never warmed or offline rows', () => {
  assert.equal(S.eligible(SESSION), true);
  assert.equal(S.eligible({ ...RE5, adapter: 'eden' }), true);
  for (const changed of [{ warm: true }, { stopping: true }, { worker_online: false }, { state: 'ended' },
    { game_id: 'other' }, { adapter: 'rpcs3' }, { session_id: 'bad' }]) assert.equal(S.eligible({ ...SESSION, ...changed }), false);
  const r = rig();
  r.sb.update({ on: true, sid: SESSION.session_id, session: RE5 });
  assert.equal(r.sb.state().sid, undefined);
});

for (const session of [RE5, SESSION]) test(`${session.session_id}: fire rate dispatches to the bound worker and reads verified live status`, async () => {
  const r = rig(session);
  assert.equal(await r.sb.refresh(), true);
  assert.equal(await r.sb.setMod('fire_rate', '30'), true);
  const change = r.changes().at(-1);
  assert.deepEqual(change.body.input, { session_id: session.session_id, op: 'fire_rate', multiplier: 30, on: true });
  assert.equal(change.body.require_worker, 'worker-123');
  assert.equal(r.sb.state().status.fire_rate_x, 30);
  assert.equal(r.jobs().at(-1).body.input.op, 'status');
  await r.sb.setMod('fire_rate', 1);
  assert.deepEqual(r.changes().at(-1).body.input, { session_id: session.session_id, op: 'fire_rate', multiplier: 1, on: false });
});

test('behavior changes and reset keep their existing schema; mod toggles are separate operations', async () => {
  const r = rig(); await r.sb.refresh();
  await r.sb.set('FLASH_GAP_S', 3);
  assert.deepEqual(r.changes().at(-1).body.input, { session_id: SESSION.session_id, op: 'bot_logic', values: { FLASH_GAP_S: 3 } });
  assert.equal(r.sb.state().view.knobs[1].value, 3);
  await r.sb.setMod('infinite_stamina', true);
  assert.deepEqual(r.changes().at(-1).body.input, { session_id: SESSION.session_id, op: 'infinite_stamina', on: true });
  await r.sb.reset();
  assert.deepEqual(r.changes().at(-1).body.input, { session_id: SESSION.session_id, op: 'bot_logic', reset: true });
});

test('invalid numeric and boolean inputs never dispatch a mutation', async () => {
  for (const value of [0, 0.9, 81, NaN, Infinity, '', 'not a number', null, true]) {
    const r = rig(); await r.sb.refresh();
    assert.equal(await r.sb.setMod('fire_rate', value), false);
    assert.equal(r.changes().length, 0);
    assert.match(r.sb.state().message, /must be 1/);
  }
  for (const [name, value] of [['FLASH_N', 2.5], ['FLASH_GAP_S', 20], ['FLASH', 'false'], ['UNKNOWN', 1]]) {
    const r = rig(); await r.sb.refresh();
    assert.equal(await r.sb.set(name, value), false);
    assert.equal(r.changes().length, 0);
  }
});

test('unavailable RE5 capabilities are disabled and cannot dispatch', async () => {
  const r = rig(RE5); r.status.capabilities.fire_rate = { available: false, reason: 'Update the worker first.' };
  await r.sb.refresh();
  assert.match(S.html(r.sb.state().view, '', r.sb.state()), /data-bl-mod="fire_rate"[^>]* disabled/);
  assert.equal(await r.sb.setMod('fire_rate', 30), false);
  assert.equal(r.changes().length, 0);
});

test('fresh session checks reject warmed predecessors, changed PCs, changed games and ended sessions', async () => {
  for (const changed of [{ warm: true }, { state: 'ended' }, { worker_online: false }, { worker_id: 'worker-other' },
    { detail: { worker_name: 'other-PC' } }, { game_id: RE5.game_id }]) {
    const r = rig(); await r.sb.refresh();
    r.rows = [{ ...SESSION, ...changed }, { ...SESSION, session_id: 'other-active' }];
    assert.equal(await r.sb.setMod('fire_rate', 30), false);
    assert.equal(r.changes().length, 0);
    assert.match(r.sb.state().message, /session ended, paused or moved/);
    assert.equal(r.sb.state().stale, true);
  }
});

test('a display change during preflight prevents the old control from being posted', async () => {
  const r = rig(); await r.sb.refresh();
  const gate = defer();
  r.hook = url => url.startsWith('/api/sessions?') ? gate.promise : undefined;
  const pending = r.sb.setMod('fire_rate', 30);
  r.select(RE5); gate.resolve([SESSION]);
  assert.equal(await pending, false);
  assert.equal(r.changes().length, 0);
  assert.equal(r.sb.state().sid, RE5.session_id);
});

test('an old job response cannot replace settings or clear a new session request', async () => {
  const r = rig(); await r.sb.refresh();
  const gate = defer(), posted = defer(), nextGate = defer(), nextPosted = defer();
  r.hook = (_url, body) => {
    if (body?.input?.values) { posted.resolve(); return gate.promise; }
    if (body?.input?.session_id === RE5.session_id && body.input.op === 'bot_logic') { nextPosted.resolve(); return nextGate.promise; }
  };
  const old = r.sb.set('FLASH_GAP_S', 3);
  await posted.promise;
  r.select(RE5);
  const fresh = r.sb.refresh(); await nextPosted.promise;
  gate.resolve(ok({ ...VIEW, title: 're6' }));
  assert.equal(await old, false);
  assert.equal(r.sb.state().busy, true, 'the old finally cannot release the new request');
  assert.equal(r.sb.state().view, null);
  nextGate.resolve(ok({ ...VIEW, title: 're5' }));
  assert.equal(await fresh, true);
  assert.equal(r.sb.state().view.title, 're5');
  assert.equal(r.sb.state().busy, false);
  assert.equal(r.sb.state().message, '');
});

test('detached controls and a changed actual stream cannot send to the new selection', async () => {
  const r = rig(); await r.sb.refresh();
  const scope = r.sb.state().scope;
  r.select(RE5); await r.sb.refresh();
  const count = r.calls.length;
  assert.equal(await r.sb.setMod('fire_rate', 30, scope), false);
  assert.equal(r.calls.length, count);
  r.shown = 'different-stream';
  assert.equal(await r.sb.setMod('fire_rate', 30), false);
  assert.equal(r.changes().length, 0);
});

test('unverified and failed jobs show errors without optimistic values; refresh recovers', async () => {
  for (const failure of [ok({ verified: false, reason: 'The weapon table signature changed.' }),
    { id: 'j2', state: 'failed', error: { message: 'Worker disconnected.' } }]) {
    const r = rig(); await r.sb.refresh();
    r.hook = (_url, body) => body?.input?.op === 'fire_rate' ? failure : undefined;
    assert.equal(await r.sb.setMod('fire_rate', 30), false);
    assert.equal(r.sb.state().status.fire_rate_x, 4);
    assert.match(r.sb.state().message, /signature changed|Worker disconnected/);
    assert.equal(r.sb.state().busy, false);
    assert.equal(r.sb.state().stale, true);
    r.hook = null; assert.equal(await r.sb.refresh(), true);
    assert.equal(r.sb.state().stale, false);
  }
});

test('verified job acceptance cannot substitute for matching current readback', async () => {
  const r = rig(); await r.sb.refresh();
  r.hook = (_url, body) => body?.input?.op === 'fire_rate' ? ok({ verified: true, fire_rate_x: 30 }) : undefined;
  assert.equal(await r.sb.setMod('fire_rate', 30), false);
  assert.equal(r.sb.state().status.fire_rate_x, 4);
  assert.match(r.sb.state().message, /not confirmed/);
  await r.sb.refresh();
  r.hook = (_url, body) => body?.input?.values ? ok(VIEW) : undefined;
  assert.equal(await r.sb.set('FLASH_GAP_S', 3), false);
  assert.match(r.sb.state().message, /not confirmed/);
});

test('pending jobs are bounded, prevent duplicate changes and can be checked with Refresh', async () => {
  const r = rig(); await r.sb.refresh();
  r.hook = (url, body) => url === '/api/jobs/jq' || body?.input?.op === 'fire_rate' ? { id: 'jq', state: 'running' } : undefined;
  assert.equal(await r.sb.setMod('fire_rate', 30), false);
  assert.equal(r.calls.filter(c => c.url === '/api/jobs/jq').length, 200);
  assert.equal(r.sb.state().pending, 'jq');
  assert.equal(await r.sb.setMod('fire_rate', 15), false);
  assert.equal(r.changes().length, 1);
  r.hook = url => url === '/api/jobs/jq' ? ok({ verified: true }) : undefined;
  assert.equal(await r.sb.refresh(), true);
  assert.equal(r.sb.state().pending, null);
});

test('closing PiP invalidates outstanding jobs and clears controls', async () => {
  const r = rig(); await r.sb.refresh();
  const gate = defer(), posted = defer();
  r.hook = (_url, body) => {
    if (body?.input?.op === 'fire_rate') { posted.resolve(); return gate.promise; }
  };
  const old = r.sb.setMod('fire_rate', 30);
  await posted.promise;
  r.sb.update({ on: false }); gate.resolve(ok({ verified: true }));
  assert.equal(await old, false);
  assert.equal(r.sb.state().sid, undefined);
  assert.equal(r.sb.state().view, null);
});

test('desktop supplies session identity after updating the displayed stream; labels and errors are escaped', () => {
  const desktop = fs.readFileSync(path.join(__dirname, '../clients/desktop/index.html'), 'utf8');
  assert.match(desktop, /GBoxBotLogicSidebar.create\(\{ current: \(\) => compactCurrentSid\(\)/);
  assert.match(desktop, /stream.src = compactStreamUrl;[\s\S]*botLogicSidebar.update\(\{ \.\.\.state, session: compactSession \}\)/);
  const h = S.html(VIEW, '<script>bad</script>', { pc: '<img src=x>', title: 're6', busy: true, status: STATUS });
  assert.doesNotMatch(h, /<script>|<img/);
  assert.match(h, /<fieldset disabled>/);
  assert.match(h, /data-bl-mod="fire_rate"[^>]* disabled/);
});
