const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const M = require('../clients/web/viz/re6-modifiers.js');
const RE5 = require('../clients/web/viz/re5-modifiers.js');
const SESSION = { session_id: 'spark-re6', game_id: '115f9cdbba115432', state: 'running', adapter: 'citron' };
const WEAPONS = [
  { id: 4, type: 0x104, name: 'Shotgun', kind: 'shotgun', loaded: true, wheel_index: 3 },
  { id: 8, type: 0x108, name: 'Elephant Killer', kind: 'magnum', loaded: true, wheel_index: 4 },
  { id: 11, type: 0x10B, name: 'Anti-Materiel Rifle', kind: 'sniper', loaded: false, wheel_index: null },
  { id: 25, type: 0x119, name: 'Combat Knife', kind: 'melee', loaded: false, wheel_index: null },
];
const STATUS = { infinite_ammo: true, infinite_tablets: true, infinite_stamina: false, infinite_grenades: true, auto_qte: true,
  kill_time_on: true, fire_rate_x: 4, magnum_speed_x: 3, throw_speed_x: 20, quick_attack_x: 10, down_fire_x: 3, next_weapon: null,
  bot: { aim_lock: true, nades: true, flash: true, bomb_drop: true, want_weapon: 3 } };

function rig(result = input => ({ verified: true })) {
  const out = { calls: [], status: structuredClone(STATUS), paints: [] };
  out.api = async (p, body, method) => {
    out.calls.push({ path: p, body, method });
    assert.equal(p, '/api/jobs'); assert.equal(method, 'POST'); assert.equal(body.tool, 're5_mods');
    const input = body.input;
    if (input.op === 'status') return { id: 'j', state: 'succeeded', output: { result: structuredClone(out.status) } };
    if (input.op === 'weapons') return { id: 'j', state: 'succeeded', output: { result: { verified: true, weapons: WEAPONS } } };
    return { id: 'j', state: 'succeeded', output: { result: result(input, out.status) } };
  };
  out.ctl = M.create({ session: SESSION, api: out.api, render: s => out.paints.push(M.html(s)), delay: async () => {}, now: () => 0 });
  out.commands = () => out.calls.filter(c => !['status', 'weapons'].includes(c.body.input.op)).map(c => c.body.input);
  return out;
}

test('only a running RE6 Switch session on Citron or Eden gets the RE6 panel', () => {
  assert.equal(M.eligible(SESSION), true);
  assert.equal(M.eligible({ ...SESSION, adapter: 'eden' }), true);
  for (const change of [{ state: 'ended' }, { stopping: true }, { game_id: RE5.SWITCH }, { adapter: 'xenia' }, { session_id: 'nodash' }])
    assert.equal(M.eligible({ ...SESSION, ...change }), false);
  assert.equal(M.eligible(null), false);
  assert.equal(RE5.panelEligible(SESSION), true, 'the team controls still mount inside it');
});

test('the weapon dropdown lists every weapon, loaded or next round, and the gun in hand is selected', async () => {
  const r = rig();
  await r.ctl.refresh();
  const page = r.paints.at(-1);
  assert.match(page, /<option value="4" selected>Shotgun \(shotgun\) - loaded<\/option>/);
  assert.match(page, /Anti-Materiel Rifle \(sniper\) - next round/);
  assert.doesNotMatch(page, /Combat Knife/, 'a melee weapon not carried is not offered');
  assert.match(page, /data-re6-mod="infinite_ammo" checked/);
  assert.match(page, /data-re6-x="throw_speed"[^>]*value="20"/);
  assert.match(page, /data-re6-bot="aim_lock" checked/);
});

test('use now sends live_weapon with the id and says whether it is now or next round', async () => {
  const r = rig(input => input.op === 'live_weapon'
    ? { verified: true, weapon: input.weapon === 11 ? 'Anti-Materiel Rifle' : 'Shotgun', loaded: input.weapon !== 11, next_round: input.weapon === 11 }
    : { verified: true });
  await r.ctl.useWeapon('4');
  assert.deepEqual(r.commands().at(-1), { session_id: SESSION.session_id, op: 'live_weapon', weapon: 4 });
  assert.match(r.paints.at(-1), /Shotgun: switching to it now/);
  await r.ctl.useWeapon(11);
  assert.match(r.paints.at(-1), /Anti-Materiel Rifle: not loaded this round - it comes in the next round/);
});

test('toggles, multipliers and the bot switches each go out as their own op', async () => {
  const r = rig();
  await r.ctl.toggle('infinite_stamina', true);
  await r.ctl.multiplier('magnum_speed', '4');
  await r.ctl.multiplier('throw_speed', '1');
  await r.ctl.bot('flash', false);
  const ops = r.commands().map(({ session_id, ...rest }) => rest);
  assert.deepEqual(ops, [{ op: 'infinite_stamina', on: true }, { op: 'magnum_speed', multiplier: 4, on: true },
    { op: 'throw_speed', multiplier: 1, on: false }, { op: 'bot_options', flash: false }]);
});

test('a failed job shows its message and the panel stays usable', async () => {
  const r = rig(() => { throw new Error('the weapon table is not this build\'s'); });
  await r.ctl.toggle('infinite_ammo', false);
  assert.match(r.paints.at(-1), /data-re6-message>the weapon table is not this build/);
  assert.equal(r.ctl.state().busy, false);
});

test('the desktop pip and the web bot demo pick the RE6 panel for an RE6 Switch session', () => {
  const desktop = fs.readFileSync(path.join(__dirname, '../clients/desktop/index.html'), 'utf8');
  const web = fs.readFileSync(path.join(__dirname, '../clients/web/index.html'), 'utf8');
  const demo = fs.readFileSync(path.join(__dirname, '../clients/web/viz/bot-demo.js'), 'utf8');
  assert.match(desktop, /<script src="\.\.\/web\/viz\/re6-modifiers\.js"><\/script>/);
  assert.match(desktop, /GBoxRE6Modifiers\?\.eligible\(session\)\) return \{ module: GBoxRE6Modifiers, selector: '\.re6-modifiers' \}/);
  assert.match(web, /<script src="\/viz\/re6-modifiers\.js"><\/script>/);
  assert.match(web, /GBoxRE6Modifiers\?\.eligible\(current\)/);
  assert.match(demo, /querySelector\("\.re6-modifiers, \.re5-modifiers, \.re4-spawn"\)/);
  assert.match(M.sectionHTML(), /class="re6-modifiers"[\s\S]*data-re6-mods[\s\S]*class="re5-modifiers" data-re6-team/);
});
