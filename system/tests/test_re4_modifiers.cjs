const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const M = require('../clients/web/viz/re4-modifiers.js');
const RE5 = require('../clients/web/viz/re5-modifiers.js');
const CONTINUITY = require('../clients/web/viz/session-continuity.js');
const SESSION = { session_id: 'spark-launch', game_id: '78ab9efa2e310db4', state: 'running', adapter: 'dolphin' };
// what RE4.status() reports on the GameCube build: patch states are "on" / "off" strings, numeric factors are read back
const BASE = { game: 'Resident Evil 4 (GameCube NTSC-U, G4BE08)', room: 'r400', money: 0, hp: 1200, unlock_flags: 'ff000000', hooked: true,
  infinite_ammo: 'off', combo_freeze: 'off', merc_timer_freeze: 'off', unlimited_health: 'off',
  merc_time_bonus_x: 1, merc_combo_window_x: 1, grenade_safe: 'off', merc_seconds_left: 95.5, merc_combo: 12 };
const WII_UNSUPPORTED = 're_mods: COMBO_WINDOW is not located in Resident Evil 4: Wii Edition (PAL RB4P08) yet (works on the GameCube release; see docs/mercenaries.md)';

function worker(status, input) {              // the tool's result shapes, applied to the fake game's status
  const def = M.DEFINITIONS.find(d => d.op === input.op);
  if (def?.kind === 'toggle') { status[def.field] = input.on ? 'on' : 'off'; return { verified: true, effect: 'patched' }; }
  if (input.op === 'merc_time_bonus') { status.merc_time_bonus_x = input.on ? input.multiplier : 1; return { verified: true, multiplier: status.merc_time_bonus_x }; }
  if (input.op === 'combo_time') { status.merc_combo_window_x = input.on ? input.multiplier : 1; return { verified: true, combo_window_x: status.merc_combo_window_x }; }
  if (input.op === 'aim_turn_speed') return { verified: true, aim_turn_speed_x: input.on ? input.multiplier : 1 };
  if (input.op === 'spawn_multiplier') return { verified: true, factor: input.on ? input.count : 1, enemies_alive: 3 };
  if (input.op === 'random_loadout') return { verified: true, picked: ['Striker'], equipped: 'Striker', weapon_mod: [true] };
  if (input.op === 'merc_loadout') return { verified: true, loadout: 'game default', records: 0 };
  if (input.op === 'mercenaries_unlock') return { verified: true, unlocked: { characters: ['Leon', 'Ada', 'HUNK', 'Krauser', 'Wesker'],
    stages: ['Village', 'Castle', 'Island', 'Waterworld'] } };
  throw new Error('unexpected op ' + input.op);
}
function rig() {
  const out = { status: structuredClone(BASE), calls: [], paints: [], sessions: [SESSION], active: [], clock: 0 };
  out.api = async (path, body, method) => {
    out.calls.push({ path, body, method });
    if (path.startsWith('/api/sessions')) return out.sessions;
    if (path.startsWith('/api/jobs?')) return out.active;
    if (path.startsWith('/api/jobs/')) return out.poll ? out.poll(path) : { id: 'job', state: 'succeeded', output: { result: { verified: true } } };
    assert.equal(path, '/api/jobs'); assert.equal(method, 'POST');
    const input = body.input;
    if (input.op === 'status') return { id: 'job', state: 'succeeded', output: { result: { op: 'status', status: structuredClone(out.status) } } };
    if (out.command) {
      const result = await out.command(input);
      return result.state ? result : { id: 'job', state: 'succeeded', output: { result } };       // a command may answer with a whole job
    }
    return { id: 'job', state: 'succeeded', output: { result: worker(out.status, input) } };
  };
  out.control = M.create({ session: SESSION, api: out.api, render: s => out.paints.push(s),
    delay: async ms => { out.clock += ms; }, now: () => out.clock });
  out.commands = () => out.calls.filter(c => c.body && c.body.input.op !== 'status');
  out.reads = () => out.calls.filter(c => c.body && c.body.input.op === 'status').length;
  return out;
}

test('only a running RE4 GameCube Dolphin session (either disc) gets controls', () => {
  assert.equal(M.eligible(SESSION), true);
  assert.equal(M.eligible({ ...SESSION, game_id: 'e42c9b780c07c437' }), true);
  for (const change of [{ state: 'ended' }, { game_id: RE5.GAME }, { game_id: 'other' }, { adapter: 'retroarch' }, { adapter: 'rpcs3' },
    { stopping: true }, { session_id: 'nodash' }, { session_id: '' }])
    assert.equal(M.eligible({ ...SESSION, ...change }), false);
  assert.equal(M.eligible(null), false);
  assert.equal(RE5.panelEligible(SESSION), false, 'the RE5 panel never claims an RE4 session');
});

test('status maps to rows: string patch states, read-back factors, local values and the vitals line', async () => {
  const r = rig(); r.status.unlimited_health = 'on'; r.status.merc_time_bonus_x = 2.5;
  await r.control.refresh();
  const rows = Object.fromEntries(M.rows(r.control.state()).map(row => [row.op, row]));
  assert.equal(rows.unlimited_health.on, true); assert.equal(rows.infinite_ammo.on, false); assert.equal(rows.grenade_safe.on, false);
  assert.equal(rows.merc_time_bonus.value, 2.5); assert.equal(rows.combo_time.value, 1);
  assert.equal(rows.aim_turn_speed.value, null); assert.equal(rows.aim_turn_speed.available, true);
  assert.equal(rows.spawn_multiplier.value, null); assert.equal(rows.spawn_multiplier.available, true);
  assert.ok(M.rows(r.control.state()).every(row => !row.disabled), 'every GameCube control is live after a read');
  const html = M.html(r.control.state());
  assert.match(html, /HP 1200 · room r400 · 95\.5 s left · combo 12/);
  assert.match(html, /data-re4-mod="unlimited_health"[^>]*aria-checked="true" checked/);
  assert.match(html, /data-re4-mod="infinite_ammo"[^>]*aria-checked="false" >/);
  assert.match(html, /data-re4-range="merc_time_bonus"[^>]*min="1" max="10" step="0.5" value="2.5"/);
  assert.match(html, /data-re4-range="spawn_multiplier"[^>]*min="1" max="4" step="1" value="1"/);
  assert.match(html, /data-re4-range="aim_turn_speed"[^>]*min="0.5" max="5" step="0.25"/);
  assert.match(html, /Not read back from the game/);
  for (const id of ['random', 'reset', 'unlock']) assert.match(html, new RegExp(`data-re4-action="${id}"[^>]*>(?!.*disabled)`));
  assert.equal(r.control.state().error, false);
});

test('a missing status field or an unknown patch word disables that control alone', async () => {
  const r = rig(); delete r.status.merc_combo_window_x; r.status.combo_freeze = 'unknown (deadbeef)'; r.status.grenade_safe = 'mixed';
  await r.control.refresh();
  const rows = Object.fromEntries(M.rows(r.control.state()).map(row => [row.op, row]));
  assert.equal(rows.combo_time.disabled, true); assert.match(rows.combo_time.reason, /does not report merc_combo_window_x/);
  assert.equal(rows.combo_freeze.disabled, true); assert.equal(rows.combo_freeze.on, null); assert.match(rows.combo_freeze.reason, /deadbeef/);
  assert.equal(rows.grenade_safe.disabled, true); assert.equal(rows.grenade_safe.on, null);
  assert.equal(rows.unlimited_health.disabled, false); assert.equal(rows.merc_time_bonus.disabled, false);
  const html = M.html(r.control.state());
  assert.equal((html.match(/aria-checked="mixed"/g) || []).length, 2);
  assert.match(html, /data-re4-range="combo_time"[^>]*disabled/);
  await r.control.change('combo_freeze', true); await r.control.setValue('combo_time', 3);
  assert.equal(r.commands().length, 0, 'unavailable controls never send jobs');
});

test('a toggle sends the exact operator job to the session worker and the fresh status wins', async () => {
  const r = rig(); await r.control.refresh(); const reads = r.reads();
  await r.control.change('unlimited_health', true);
  assert.deepEqual(r.commands()[0].body, { tool: 're_mods', agent_use: false, require_worker: 'spark',
    input: { session_id: 'spark-launch', op: 'unlimited_health', on: true } });
  assert.equal(r.reads(), reads + 1, 'a status read follows the change');
  assert.equal(r.control.state().status.unlimited_health, 'on');
  assert.equal(M.rows(r.control.state()).find(row => row.op === 'unlimited_health').on, true);
  assert.equal(r.control.state().message, 'Unlimited life enabled.');
  await r.control.change('unlimited_health', false);
  assert.deepEqual(r.commands()[1].body.input, { session_id: 'spark-launch', op: 'unlimited_health', on: false });
  assert.equal(r.control.state().status.unlimited_health, 'off');
  for (const op of ['infinite_ammo', 'combo_freeze', 'merc_timer_freeze', 'grenade_safe']) {
    await r.control.change(op, true);
    assert.equal(r.commands().at(-1).body.input.op, op); assert.equal(r.control.state().error, false);
  }
  await r.control.change('merc_time_bonus', true); await r.control.change('unlimited_health', 'yes'); await r.control.change('warp', true);
  assert.equal(r.commands().length, 6, 'numeric ops, non-boolean wishes and unknown ops are not toggles');
});

test('toggles are never flipped optimistically: unverified or unconfirmed results report an error', async () => {
  for (const command of [async () => ({ verified: false, reason: 'unexpected code at 0x800CEC10' }), async () => ({ verified: true })]) {
    const r = rig(); await r.control.refresh(); r.command = command;
    await r.control.change('unlimited_health', true);
    assert.equal(r.control.state().status.unlimited_health, 'off');
    assert.equal(r.control.state().error, true); assert.equal(r.control.state().stale, true);
    assert.ok(M.rows(r.control.state()).every(row => row.disabled));
    assert.deepEqual(r.control.state().unsupported, {}, 'a failed verification does not retire the control');
  }
});

test('a multiplier slider submits multiplier and confirms it from the fresh status or the verified result', async () => {
  const r = rig(); await r.control.refresh();
  await r.control.setValue('merc_time_bonus', '2.5');
  assert.deepEqual(r.commands()[0].body, { tool: 're_mods', agent_use: false, require_worker: 'spark',
    input: { session_id: 'spark-launch', op: 'merc_time_bonus', on: true, multiplier: 2.5 } });
  assert.equal(r.control.state().status.merc_time_bonus_x, 2.5); assert.equal(r.control.state().message, 'Time per pickup: ×2.5.');
  await r.control.setValue('combo_time', 3);
  assert.deepEqual(r.commands()[1].body.input, { session_id: 'spark-launch', op: 'combo_time', on: true, multiplier: 3 });
  await r.control.setValue('aim_turn_speed', 2);
  assert.deepEqual(r.commands()[2].body.input, { session_id: 'spark-launch', op: 'aim_turn_speed', on: true, multiplier: 2 });
  assert.equal(r.control.state().applied.aim_turn_speed_x, 2);
  assert.match(M.html(r.control.state()), /data-re4-range="aim_turn_speed"[^>]*value="2"/);
  assert.match(M.html(r.control.state()), /Last value set here/);
  assert.equal(r.control.state().error, false); assert.equal(r.control.state().stale, false);
  for (const [op, bad] of [['merc_time_bonus', 0.5], ['merc_time_bonus', 11], ['combo_time', NaN], ['combo_time', ''], ['aim_turn_speed', 0.25],
    ['aim_turn_speed', 6], ['aim_turn_speed', Infinity], ['unlimited_health', 2], ['warp', 1]])
    await r.control.setValue(op, bad);
  assert.equal(r.commands().length, 3, 'out-of-range, non-numeric, toggle and unknown ops send nothing');
});

test('the enemies slider submits count: 1 turns the multiplier off, 2-4 clone every spawn', async () => {
  const r = rig(); await r.control.refresh();
  await r.control.setValue('spawn_multiplier', 3);
  assert.deepEqual(r.commands()[0].body.input, { session_id: 'spark-launch', op: 'spawn_multiplier', on: true, count: 3 });
  assert.equal(r.control.state().applied.spawn_x, 3); assert.match(r.control.state().message, /Enemies ×3: every spawn gets 2 extra copies/);
  await r.control.setValue('spawn_multiplier', '1');
  assert.deepEqual(r.commands()[1].body.input, { session_id: 'spark-launch', op: 'spawn_multiplier', on: false, count: 1 });
  assert.match(r.control.state().message, /Normal enemy spawns restored/);
  for (const bad of [2.5, 5, 0, '3 enemies']) await r.control.setValue('spawn_multiplier', bad);
  assert.equal(r.commands().length, 2);
  r.command = async () => ({ verified: true, factor: 2 });
  await r.control.setValue('spawn_multiplier', 4);
  assert.equal(r.control.state().error, true); assert.equal(r.control.state().applied.spawn_x, 1, 'a mismatching factor is not kept');
});

test('an unsupported op is disabled with the tool message and stays retired across refreshes', async () => {
  const r = rig(); await r.control.refresh();
  r.command = async input => input.op === 'combo_time' ? { id: 'job', state: 'failed', error: { message: WII_UNSUPPORTED } } : worker(r.status, input);
  await r.control.setValue('combo_time', 3);
  assert.equal(r.control.state().error, true); assert.equal(r.control.state().message, WII_UNSUPPORTED);
  assert.ok(M.rows(r.control.state()).every(row => row.disabled), 'a failure blocks every control until Refresh');
  await r.control.refresh();
  const rows = Object.fromEntries(M.rows(r.control.state()).map(row => [row.op, row]));
  assert.equal(rows.combo_time.disabled, true); assert.equal(rows.combo_time.available, false); assert.equal(rows.combo_time.reason, WII_UNSUPPORTED);
  assert.equal(rows.merc_time_bonus.disabled, false); assert.equal(rows.unlimited_health.disabled, false);
  const html = M.html(r.control.state());
  assert.match(html, /data-re4-range="combo_time"[^>]*disabled/);
  assert.match(html, /COMBO_WINDOW is not located in Resident Evil 4: Wii Edition/);
  assert.match(r.control.state().message, /cannot do stay disabled/);
  const sent = r.commands().length;
  await r.control.setValue('combo_time', 3);
  assert.equal(r.commands().length, sent, 'a retired control sends no further jobs');
  await r.control.setValue('merc_time_bonus', 2);
  assert.equal(r.control.state().error, false);
});

test('an unsupported action button is disabled with the message; a transient failure is not retired', async () => {
  const r = rig(); await r.control.refresh();
  r.command = async input => input.op === 'mercenaries_unlock'
    ? { id: 'job', state: 'failed', error: 're_mods: Resident Evil 4 on GameCube / Wii (Dolphin) so far; Resident Evil 4 (ps2): see docs/mercenaries.md' }
    : input.op === 'unlimited_health' ? { id: 'job', state: 'failed', error: 'the game did not run the request (paused, loading or in a menu?) - try again in play' }
    : worker(r.status, input);
  await r.control.action('unlock');
  assert.match(r.control.state().message, /GameCube \/ Wii \(Dolphin\) so far/);
  await r.control.refresh();
  const unlock = M.actions(r.control.state()).find(act => act.id === 'unlock');
  assert.equal(unlock.disabled, true); assert.match(unlock.reason, /so far/);
  assert.match(M.html(r.control.state()), /data-re4-action="unlock"[^>]*disabled/);
  assert.match(M.html(r.control.state()), /Unlock Mercenaries: re_mods: Resident Evil 4 on GameCube/);
  assert.equal(M.actions(r.control.state()).find(act => act.id === 'random').disabled, false);
  const sent = r.commands().length;
  await r.control.action('unlock'); assert.equal(r.commands().length, sent);
  await r.control.change('unlimited_health', true);
  assert.equal(r.control.state().error, true); assert.match(r.control.state().message, /try again in play/);
  await r.control.refresh();
  assert.equal(M.rows(r.control.state()).find(row => row.op === 'unlimited_health').disabled, false, 'a transient failure re-enables after Refresh');
});

test('weapon and unlock buttons send the documented re_mods inputs and report the verified result', async () => {
  const r = rig(); await r.control.refresh();
  await r.control.action('random');
  assert.deepEqual(r.commands()[0].body.input, { session_id: 'spark-launch', op: 'random_loadout', character: 'leon', damage: 99.9, on: true });
  assert.match(r.control.state().message, /Striker at 99\.9× damage/);
  await r.control.action('reset');
  assert.deepEqual(r.commands()[1].body.input, { session_id: 'spark-launch', op: 'merc_loadout', character: 'leon', reset: true });
  assert.match(r.control.state().message, /game's own again/);
  await r.control.action('unlock');
  assert.deepEqual(r.commands()[2].body.input, { session_id: 'spark-launch', op: 'mercenaries_unlock', on: true });
  assert.match(r.control.state().message, /Leon, Ada, HUNK, Krauser, Wesker; Village, Castle, Island, Waterworld/);
  assert.equal(r.reads(), 4, 'every action is followed by a status read');
  await r.control.action('nuke'); assert.equal(r.commands().length, 3);
  r.command = async () => ({ verified: false });
  await r.control.action('random');
  assert.equal(r.control.state().error, true); assert.match(r.control.state().message, /did not verify/);
});

test('ended, replaced or busy sessions never receive a mutation', async () => {
  for (const sessions of [[], [{ ...SESSION, state: 'ended' }], [{ ...SESSION, game_id: RE5.GAME }], [{ ...SESSION, session_id: 'spark-new' }]]) {
    const r = rig(); await r.control.refresh(); r.sessions = sessions;
    await r.control.change('infinite_ammo', true); await r.control.setValue('spawn_multiplier', 2); await r.control.action('random');
    assert.equal(r.commands().length, 0); assert.match(r.control.state().message, /ended or changed/);
  }
  const busy = rig(); await busy.control.refresh();
  busy.active = [{ id: 'existing', tool: 're_mods', input: { session_id: SESSION.session_id } }];
  await busy.control.change('infinite_ammo', true);
  assert.equal(busy.commands().length, 0); assert.equal(busy.control.state().pending, 'existing');
  busy.active = []; await busy.control.refresh(); assert.equal(busy.control.state().pending, null);
  const cold = rig(); await cold.control.change('infinite_ammo', true); await cold.control.setValue('combo_time', 2);
  assert.equal(cold.commands().length, 0, 'no mutation before the first status read');
  const closed = rig(); await closed.control.refresh(); const paints = closed.paints.length; closed.control.stop();
  await closed.control.change('infinite_ammo', true); await closed.control.refresh();
  assert.equal(closed.commands().length, 0); assert.equal(closed.paints.length, paints);
});

test('queued jobs are polled to completion and a terminal failure keeps the panel blocked until refresh', async () => {
  const r = rig(); await r.control.refresh();
  let polls = 0;
  r.command = async () => ({ id: 'slow', state: 'queued' });
  r.poll = () => ++polls < 3 ? { id: 'slow', state: 'running' } : { id: 'slow', state: 'succeeded', output: { result: worker(r.status, { op: 'infinite_ammo', on: true }) } };
  await r.control.change('infinite_ammo', true);
  assert.equal(polls, 3); assert.equal(r.control.state().status.infinite_ammo, 'on'); assert.equal(r.control.state().pending, null);
  const control = M.create({ session: SESSION, api: async p => p.startsWith('/api/sessions') ? [SESSION]
    : p.startsWith('/api/jobs?') ? [] : { state: 'failed', error: { message: 'Memory unavailable' } } });
  await control.refresh();
  assert.match(control.state().message, /Memory unavailable/);
  assert.ok(M.rows(control.state()).every(row => row.disabled));
  assert.ok(M.actions(control.state()).every(act => act.disabled));
});

test('server strings are escaped and never become markup or checked controls', () => {
  const html = M.html({ status: { ...BASE, room: '<script>bad</script>', unlimited_health: '<b>' }, stale: false,
    unsupported: { combo_time: '<img src=x onerror=1>' } });
  assert.match(html, /&#60;script&#62;bad&#60;\/script&#62;/);
  assert.doesNotMatch(html, /<script>bad|<img src/);
  assert.match(html, /data-re4-mod="unlimited_health"[^>]*aria-checked="mixed"/);
  assert.match(html, /data-re4-range="combo_time"[^>]*disabled/);
  assert.match(M.html({}), /Waiting for the game&#39;s status/);
});

test('mounted controls preview without mutating, revert optimistic checks and send the chosen values', async () => {
  const r = rig(), output = { textContent: '' };
  const host = { innerHTML: '', querySelector: selector => { assert.match(selector, /data-re4-value=/); return output; } };
  const control = M.mount(host, { session: SESSION, api: r.api });
  await new Promise(resolve => setImmediate(resolve));
  assert.match(host.innerHTML, /RE4 modifiers/);
  const range = { dataset: { re4Range: 'merc_time_bonus' }, value: '3', matches: selector => selector === '[data-re4-range]' };
  host.oninput({ target: range });
  assert.equal(output.textContent, '×3'); assert.equal(r.commands().length, 0);
  host.onchange({ target: range }); await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(r.commands()[0].body.input, { session_id: 'spark-launch', op: 'merc_time_bonus', on: true, multiplier: 3 });
  const box = { checked: true, disabled: false, dataset: { re4Mod: 'infinite_ammo' }, matches: () => false };
  box.closest = selector => selector === '[data-re4-mod]' ? box : null;
  host.onchange({ target: box });
  assert.equal(box.checked, false, 'the box shows the game state until the fresh status confirms');
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(r.commands()[1].body.input, { session_id: 'spark-launch', op: 'infinite_ammo', on: true });
  const button = { disabled: false, dataset: { re4Action: 'reset' } };
  host.onclick({ target: { closest: selector => selector === '[data-re4-action]' ? button : null } });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(r.commands()[2].body.input.op, 'merc_loadout');
  assert.equal(control.state().error, false); control.stop();
  assert.equal(M.mount(null, { session: SESSION, api: r.api }), null);
});

function desktopPipRig({ session = SESSION, re4 = true, history = [] } = {}) {
  const source = fs.readFileSync(path.join(__dirname, '../clients/desktop/index.html'), 'utf8');
  const hosts = {}, selectors = [], panel = { innerHTML: '', textContent: '' }, mounts = [], calls = [];
  const menu = { opening: {}, style: {}, querySelector: selector => { selectors.push(selector);
    return selector === '[data-pip-modifiers]' ? panel : (hosts[selector] ||= { selector }); } };
  const stream = { src: '', getAttribute(name) { return name === 'src' ? this.src : null; } };
  const fake = module => ({ ...module, mount: (target, options) => { mounts.push({ module, target, options }); return { stop() {} }; } });
  const context = vm.createContext({
    $: selector => selector === '#compact-stream' ? stream : menu,
    gboxStreamWatchdog: { sessionOf: () => null },
    COMPACT: { on: true, sid: session.session_id }, EMB: { sid: session.session_id, last: '' },
    GM: { menu: true }, compactSession: session, sessionById: async () => session,
    GBoxSessionContinuity: CONTINUITY, GBoxRE5Modifiers: fake(RE5), ...(re4 ? { GBoxRE4Modifiers: fake(M) } : {}),
    gbox: { api: async (...args) => { calls.push(args); return { ok: true, data: args[0].startsWith('/api/sessions?') ? history : { confirmed: true } }; } },
  });
  vm.runInContext(source.slice(source.indexOf('function closePipMenu()'), source.indexOf('function pipMenu(x, y)')), context);
  return { context, menu, panel, hosts, selectors, mounts, calls, source };
}

test('desktop PiP mounts the RE4 panel for an RE4 GameCube session through the authenticated IPC wrapper', async () => {
  const r = desktopPipRig(); await r.context.pipModifiers(r.menu, r.menu.opening);
  assert.equal(r.mounts.length, 1);
  assert.equal(r.mounts[0].module, M);
  assert.equal(r.mounts[0].target, r.hosts['.re4-modifiers']);
  assert.equal(r.mounts[0].options.session, SESSION);
  assert.match(r.panel.innerHTML, /class="re4-modifiers"/);
  assert.deepEqual(await r.mounts[0].options.api('/api/jobs', { input: { op: 'status' } }, 'POST'), { confirmed: true });
  assert.deepEqual(r.calls.at(-1), ['/api/jobs', { input: { op: 'status' } }, 'POST']);
  assert.equal(r.calls.length, 1, 'an eligible RE4 session needs no history lookup');
});

test('desktop PiP keeps the RE5 panel first and shows nothing for RE4 without the module or when the session ended', async () => {
  const re5 = { session_id: 'spark-launch', game_id: RE5.GAME, state: 'running', adapter: 'rpcs3' };
  const r = desktopPipRig({ session: re5 }); await r.context.pipModifiers(r.menu, r.menu.opening);
  assert.equal(r.mounts.length, 1); assert.equal(r.mounts[0].module, RE5); assert.equal(r.mounts[0].target, r.hosts['.re5-modifiers']);
  const absent = desktopPipRig({ re4: false }); await absent.context.pipModifiers(absent.menu, absent.menu.opening);
  assert.equal(absent.mounts.length, 0); assert.equal(absent.panel.textContent, '');
  const ended = desktopPipRig({ session: { ...SESSION, state: 'ended' } }); await ended.context.pipModifiers(ended.menu, ended.menu.opening);
  assert.equal(ended.mounts.length, 0); assert.equal(ended.panel.textContent, '');
  assert.equal(ended.calls[0][0], '/api/sessions?limit=200', 'an ineligible session still consults history for an RE5 replacement');
});

test('both shells load the RE4 modifier script next to the RE5 one and the module stays operator-scoped', () => {
  const desktop = fs.readFileSync(path.join(__dirname, '../clients/desktop/index.html'), 'utf8');
  const web = fs.readFileSync(path.join(__dirname, '../clients/web/index.html'), 'utf8');
  assert.match(desktop, /<script src="\.\.\/web\/viz\/re5-modifiers\.js"><\/script>\s*<script src="\.\.\/web\/viz\/re4-modifiers\.js"><\/script>/);
  assert.match(web, /<script src="\/viz\/re5-modifiers\.js"><\/script>\s*<script src="\/viz\/re4-modifiers\.js"><\/script>/);
  const source = fs.readFileSync(require.resolve('../clients/web/viz/re4-modifiers.js'), 'utf8');
  assert.doesNotMatch(source, /write_memory|read_memory|Bearer|x-gbox-actor/);
  assert.match(source, /agent_use: false/);
});

// --- the Mercenaries clock control and "Send a wave" (operator 2026-10-26: stalemates) ---
test('the clock control uses re_mods add_time / set_time on the vitals clock; a Mercenaries stage is required', async () => {
  const r = rig(); await r.control.refresh();                       // BASE: 95.5 s left in r400
  r.command = async input => {
    const before = r.status.merc_seconds_left, after = input.op === 'set_time' ? input.seconds : Math.max(1, before + input.seconds);
    r.status.merc_seconds_left = after;
    return { verified: true, clock_before: before, clock_after: after, seconds: after };
  };
  assert.equal(M.clockState(r.control.state()).disabled, false);
  assert.match(M.html(r.control.state()), /<fieldset class="mercs-clock" >/); assert.match(M.html(r.control.state()), /96 s left on the clock/);
  await r.control.addTime(-30);
  assert.deepEqual(r.commands()[0].body, { tool: 're_mods', agent_use: false, require_worker: 'spark',
    input: { session_id: 'spark-launch', op: 'add_time', seconds: -30 } });
  assert.equal(r.control.state().message, 'Clock 96 → 66 s.'); assert.equal(r.control.state().error, false);
  await r.control.setTime(5);
  assert.deepEqual(r.commands()[1].body.input, { session_id: 'spark-launch', op: 'set_time', seconds: 5 });
  assert.equal(r.control.state().status.merc_seconds_left, 5); assert.equal(r.control.state().message, 'Clock 66 → 5 s.');
  for (const bad of [0, 31, 'x']) await r.control.addTime(bad);
  for (const bad of [0, 61]) await r.control.setTime(bad);
  assert.equal(r.commands().length, 2, 'out-of-range values never send a job');
  const story = rig(); delete story.status.merc_seconds_left; story.status.room = 'r102'; await story.control.refresh();
  assert.equal(M.clockState(story.control.state()).disabled, true); assert.match(M.html(story.control.state()), /no Mercenaries round is up/);
  await story.control.addTime(-30); await story.control.setTime(5); assert.equal(story.commands().length, 0);
  r.command = async () => { throw new Error(WII_UNSUPPORTED.replace('COMBO_WINDOW', 'MERC_TIMER')); };
  await r.control.addTime(-5);
  assert.match(M.clockState(r.control.state()).reason, /not located in/);
  await r.control.refresh();
  assert.equal(M.clockState(r.control.state()).disabled, true, 'a build without the clock word keeps the control retired');
  assert.match(M.html(r.control.state()), /<fieldset class="mercs-clock" disabled>/);
});

test('Send a wave re-arms the spawn multiplier through spawn_wave and reports the clones honestly', async () => {
  const r = rig(); await r.control.refresh();
  r.command = async input => { assert.equal(input.op, 'spawn_wave'); return { verified: true, wave: true, factor: 3, enemies_alive: 7 }; };
  const html = M.html(r.control.state());
  assert.match(html, /data-re4-action="wave"[^>]*title="[^"]*clones only/); assert.match(html, />Send a wave</);
  await r.control.action('wave');
  assert.deepEqual(r.commands()[0].body.input, { session_id: 'spark-launch', op: 'spawn_wave' });
  assert.match(r.control.state().message, /Wave sent: 7 enemies alive after the clone pass \(×3\)\. Clones only: nothing appears from zero\./);
  assert.equal(r.control.state().error, false);
  r.command = async () => ({ verified: false, reason: '0x80002800-0x800029E0 is in use' });
  await r.control.action('wave');
  assert.equal(r.control.state().error, true); assert.match(r.control.state().message, /in use/);
});
