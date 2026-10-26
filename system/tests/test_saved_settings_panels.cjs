// The game menus show what the game keeps across reloads (operator 2026-10-26: "when i set the settings in the right
// click menu for the mods / bot systems, retain those settings across reloads"; gbox/game_prefs.py keeps them).
const { test } = require('node:test');
const assert = require('node:assert/strict');
const RE5 = require('../clients/web/viz/re5-modifiers.js');
const RE4 = require('../clients/web/viz/re4-modifiers.js');

const RE5_SESSION = { session_id: 'spark-re5', game_id: RE5.GAME, state: 'running', adapter: 'rpcs3' };
const RE5_STATUS = { unlimited_health: false, infinite_ammo: true, infinite_spray: false, fire_rate_x: 120, turn_speed_x: 1,
  bullet_damage_x: 1, kill_time_on: false, kill_time_range: '10', qte_assist: { enabled: false },
  all_weapons: [{ item: 15, weapon: 'Longbow' }],
  capabilities: Object.fromEntries(RE5.DEFINITIONS.map(row => [row.op, { available: true }])) };
const RE4_SESSION = { session_id: 'nuc-re4', game_id: '78ab9efa2e310db4', state: 'running', adapter: 'dolphin' };
const RE4_STATUS = { infinite_ammo: 'on', combo_freeze: 'on', merc_timer_freeze: 'off', unlimited_health: 'off', grenade_safe: 'off',
  merc_time_bonus_x: 3, merc_combo_window_x: 3, hp: 1200 };

function api(session, status, team) {
  return async (path, body) => {
    if (path.startsWith('/api/sessions')) return [session];
    if (path.startsWith('/api/jobs?')) return [];
    if (body?.tool === 'mercs_team') return { id: 't', state: 'succeeded', output: { result: { status: team } } };
    return { id: 'j', state: 'succeeded', output: { result: { status: structuredClone(status) } } };
  };
}

test('RE5 shows the saved settings, which ones are on this session yet, and the saved value beside a different live one', async () => {
  const saved = { game_id: RE5.GAME, panels: { re5_mods: { fire_rate: { on: true, multiplier: 120 }, unlimited_health: { on: true },
    weapon_override: { on: true, weapon: 15, only: true } } },
    applied: { re5_mods: { fire_rate: { state: 'applied' }, unlimited_health: { state: 'failed', reason: 'game still booting' },
      weapon_override: { state: 'applied' } } }, receives: { re5_mods: true } };
  let painted;
  const ctl = RE5.create({ session: RE5_SESSION, api: api(RE5_SESSION, RE5_STATUS), render: s => { painted = s; },
    savedPrefs: async () => saved, delay: async () => {}, now: () => 0 });
  await ctl.refresh();
  const html = RE5.html(painted);
  assert.match(html, /Saved for this game: Fire rate ×120 · Unlimited life on · Next-round weapon: Longbow \(only weapon\)\./);
  assert.match(html, /Not on this session yet: Unlimited life on \(game still booting\)\./);
  assert.match(html, /Saved: Unlimited life on \(not on this session yet: game still booting\)/, 'live off, saved on');
  assert.doesNotMatch(html, /Saved: Fire rate/, 'live matches saved: no extra note');
  assert.match(painted.message, /kept for this game across reloads and relaunches/);
});

test('the saved settings show as soon as the menu opens, before the game itself has answered', async () => {
  let release, painted = [];
  const slow = async (path, body) => {
    if (path.startsWith('/api/sessions')) return [RE4_SESSION];
    if (path.startsWith('/api/jobs?')) return [];
    await new Promise(resolve => { release = resolve; });              // the worker is still reading the game
    return { id: 'j', state: 'succeeded', output: { result: { status: structuredClone(RE4_STATUS) } } };
  };
  const ctl = RE4.create({ session: RE4_SESSION, api: slow, render: s => painted.push(s), delay: async () => {}, now: () => 0,
    savedPrefs: async () => ({ panels: { re_mods: { grenade_safe: { on: true } } }, applied: {}, receives: { re_mods: true } }) });
  const done = ctl.refresh();
  for (let i = 0; i < 20 && !release; i++) await new Promise(resolve => setImmediate(resolve));
  const early = painted.at(-1);
  assert.equal(early.busy, true);
  assert.match(RE4.html(early), /Saved for this game: Hand grenades never hurt Leon on\./);
  release(); await done;
  assert.equal(painted.at(-1).busy, false);
});

test('RE5 without the saved-settings reader (or with it failing) shows the live values as before', async () => {
  for (const savedPrefs of [undefined, async () => { throw Error('offline'); }, async () => [RE5_SESSION]]) {
    let painted;
    const ctl = RE5.create({ session: RE5_SESSION, api: api(RE5_SESSION, RE5_STATUS), render: s => { painted = s; }, savedPrefs,
      delay: async () => {}, now: () => 0 });
    await ctl.refresh();
    assert.equal(painted.saved, null);
    assert.doesNotMatch(RE5.html(painted), /Saved for this game/);
  }
});

test('RE5 team choices kept for the game say where they apply; nothing saved yet says changes will be kept', async () => {
  const team = { config: { role: 'teammate_p2', training_profile: 'assisted', auto_reduce_mods: false }, phase: 'waiting_p2',
    capabilities: {} };
  let painted;
  const ctl = RE5.create({ session: RE5_SESSION, api: api(RE5_SESSION, RE5_STATUS, team), render: s => { painted = s; },
    teamControls: true, delay: async () => {}, now: () => 0,
    savedPrefs: async () => ({ panels: { mercs_team: { team: { role: 'teammate_p2', training_profile: 'assisted', auto_reduce_mods: true } } },
      applied: {}, receives: { mercs_team: false } }) });
  await ctl.refresh();
  const html = RE5.html(painted);
  assert.match(html, /Saved for this game: Player 2: follow and protect human Player 1 · assisted training · gradual reduction allowed\. Used on your own sessions; MercMode and bot demos always play solo\./);
  assert.match(html, /Changes confirmed here are kept for this game/);
});

test('RE5 saved values read as the operator chose them', () => {
  assert.equal(RE5.savedText('mines', { on: true, multiplier: 30 }), 'Mines every 30 s');
  assert.equal(RE5.savedText('mines', { on: true, multiplier: 'only' }), 'Mines only');
  assert.equal(RE5.savedText('rotten_egg_only', { on: false, multiplier: 20 }), 'Rotten eggs off');
  assert.equal(RE5.savedText('kill_time', { on: true, multiplier: 7 }), 'Time added per kill: 7 s');
  assert.equal(RE5.savedText('bullet_damage', { on: true }), 'Bullet damage ×10');
  assert.equal(RE5.savedText('weapon_override', { on: false }), "Next-round weapon: the game's loadout");
  assert.equal(RE5.savedText('weapon_override', { on: true, weapon: 99, only: false }), 'Next-round weapon: weapon 99');
});

test('RE4 shows the saved settings and the saved value beside a different live one', async () => {
  let painted;
  const ctl = RE4.create({ session: RE4_SESSION, api: api(RE4_SESSION, RE4_STATUS), render: s => { painted = s; },
    delay: async () => {}, now: () => 0,
    savedPrefs: async () => ({ panels: { re_mods: { combo_freeze: { on: false }, combo_time: { on: true, multiplier: 3 },
      loadout: { mode: 'default', character: 'leon' } } },
      applied: { re_mods: { combo_freeze: { state: 'pending' }, combo_time: { state: 'applied' }, loadout: { state: 'applied' } } },
      receives: { re_mods: true } }) });
  await ctl.refresh();
  const html = RE4.html(painted);
  assert.match(html, /Saved for this game: Combo never ends off · Combo window ×3 · The game&#39;s own weapons\. Being applied to this session…/);
  assert.match(html, /Saved: Combo never ends off \(being applied to this session\)/);
  assert.doesNotMatch(html, /Saved: Combo window/);
  assert.equal(RE4.savedText('spawn_multiplier', { on: true, count: 3 }), 'Enemies ×3');
  assert.equal(RE4.savedText('loadout', { mode: 'random' }), 'Random weapon (99.9× damage)');
  assert.equal(RE4.savedText('aim_turn_speed', { on: false }), "Aim turn speed: the game's own");
});

test('RE4 on an agent test session says saved settings are not applied there', async () => {
  let painted;
  const ctl = RE4.create({ session: RE4_SESSION, api: api(RE4_SESSION, RE4_STATUS), render: s => { painted = s; },
    delay: async () => {}, now: () => 0,
    savedPrefs: async () => ({ panels: { re_mods: { grenade_safe: { on: true } } }, applied: {}, receives: { re_mods: false } }) });
  await ctl.refresh();
  assert.match(RE4.html(painted), /Agent test sessions and paused games keep their own setup\./);
});
