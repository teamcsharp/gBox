const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const M = require('../clients/web/viz/re5-modifiers.js');
const BD = require('../clients/web/viz/bot-demo.js');
const CONTINUITY = require('../clients/web/viz/session-continuity.js');
const SESSION = { session_id: 'worker-launch', game_id: M.GAME, state: 'running', adapter: 'rpcs3' };
const BASE = { unlimited_health: false, infinite_ammo: true, fire_rate_x: 1, turn_speed_x: 1,
  bullet_damage_x: 1, kill_time_on: false, kill_time_range: '3', qte_assist: { enabled: false }, in_hand: { weapon: 'M500' }, capabilities: Object.fromEntries(
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
      if (op === 'instant_qte') out.status.qte_assist = { enabled: on, phase: 'waiting', completed: false };
      else out.status[definition.field] = definition.multiplier ? on ? multiplier : 1 : on;
      if (op === 'kill_time' && multiplier !== undefined) out.status.kill_time_range = String(multiplier);
      result = { verified: true };
    }
    return { id: 'job', state: 'succeeded', output: { result } };
  };
  out.control = M.create({ session: SESSION, api: out.api, render: s => out.paints.push(s),
    delay: async ms => { out.clock += ms; }, now: () => out.clock });
  out.commands = () => out.calls.filter(c => c.body && c.body.input.op !== 'status');
  return out;
}

test('mine cadence and mines-only settings use verified scoped jobs', async () => {
  const r = rig();
  r.status.capabilities.mines = { available: true };
  r.status.mine_settings = { enabled: true, interval_s: 60, only: false };
  r.command = async input => {
    r.status.mine_settings = { enabled: input.on, interval_s: input.multiplier === 'only' ? 2 : input.multiplier,
      only: input.multiplier === 'only' };
    return { verified: true };
  };
  await r.control.refresh();
  await r.control.setMines(30, true, false);
  assert.deepEqual(r.commands()[0].body.input, { session_id: 'worker-launch', op: 'mines', on: true, multiplier: 30 });
  await r.control.setMines(2, true, true);
  assert.equal(r.commands()[1].body.input.multiplier, 'only');
  assert.equal(r.control.state().status.mine_settings.only, true);
  await r.control.setMines(0, true, false);
  assert.equal(r.commands().length, 2);
});

test('egg mode uses scoped jobs and accurately retains native supply pending', async () => {
  const r=rig();r.status.capabilities.rotten_egg_only={available:true};
  r.status.rotten_egg_only=false;r.status.egg_rate_x=20;
  r.command=async input=>{
    r.status.rotten_egg_only=input.on;r.status.egg_rate_x=input.multiplier;
    r.status.egg_native_equipped=false;return {verified:true};
  };
  await r.control.refresh();await r.control.setEggs(true,20);
  assert.deepEqual(r.commands()[0].body.input,{session_id:'worker-launch',op:'rotten_egg_only',on:true,multiplier:20});
  assert.match(r.control.state().message,/Waiting for native pickup/);
  assert.match(M.html(r.control.state()),/Requested animation speed/);
  assert.match(M.html(r.control.state()),/actual throw cadence and ballistic aim are not yet verified/);
  assert.match(M.html(r.control.state()),/data-re5-mines[^>]*disabled|fieldset[^>]*disabled/);
  await r.control.setEggs(false,5);
  assert.equal(r.commands()[1].body.input.on,false);
  assert.match(r.control.state().message,/Returning to an existing gun/);
});

test('egg mode rejects nonfinite or excessive rates and unavailable native capability',async()=>{
  const r=rig();r.status.capabilities.rotten_egg_only={available:true};await r.control.refresh();
  for(const rate of [0,20.01,Infinity,NaN]) await r.control.setEggs(true,rate);
  assert.equal(r.commands().length,0);
  r.status.capabilities.rotten_egg_only={available:false};await r.control.refresh();
  await r.control.setEggs(true,20);assert.equal(r.commands().length,0);
});

test('live longbow queue stays pending until fresh native equip confirmation', async () => {
  const r = rig(); r.status.capabilities.live_weapon = { available: true };
  r.command = async input => {
    assert.equal(input.op, 'live_weapon');
    r.status.live_weapon = { phase: 'pending', verified: false, reason: 'Waiting for a safe pickup.' };
    return { queued: true, verified: true }; // queue receipt cannot override native readback
  };
  await r.control.refresh(); await r.control.setLiveWeapon(true);
  assert.deepEqual(r.commands()[0].body.input, { session_id: SESSION.session_id, op: 'live_weapon', on: true, weapon: 15 });
  assert.equal(r.commands()[0].body.require_worker, 'worker');
  assert.equal(r.commands()[0].body.agent_use, false);
  assert.match(r.control.state().message, /Waiting for a safe pickup/);
  assert.doesNotMatch(r.control.state().message, /equipped and confirmed/);
  assert.match(M.html(r.control.state()), /data-re5-live-bow disabled/);
  r.status.live_weapon = { phase: 'equipped', verified: false };
  await r.control.refresh();
  assert.doesNotMatch(M.html(r.control.state()), /Longbow equipped and confirmed/);
  r.status.live_weapon.verified = true;
  await r.control.refresh();
  assert.match(M.html(r.control.state()), /Longbow equipped and confirmed in this round/);
});

test('live longbow cancellation requires current cancellation readback', async () => {
  const r = rig(); r.status.capabilities.live_weapon = { available: true };
  r.status.live_weapon = { phase: 'donor', verified: false };
  r.command = async () => ({ verified: true });
  await r.control.refresh(); await r.control.setLiveWeapon(false);
  assert.equal(r.control.state().error, true);
  assert.match(r.control.state().message, /Cancellation is pending/);
  r.command = async () => {
    r.status.live_weapon = { phase: 'cancelled', restoration_pending: true, verified: false };
    return { verified: false };
  };
  await r.control.setLiveWeapon(false);
  assert.equal(r.control.state().error, true);
  assert.match(M.html(r.control.state()), /Cancellation pending: restoring/);
  r.status.capabilities.live_weapon = { available: false, reason: 'Bot stopped.' };
  await r.control.refresh();
  assert.doesNotMatch(M.html(r.control.state()), /data-re5-live-cancel disabled/);
  r.command = async () => { r.status.live_weapon = { phase: 'cancelled', verified: false }; return { queued: false }; };
  await r.control.setLiveWeapon(false);
  assert.equal(r.control.state().error, false);
  assert.match(r.control.state().message, /request cancelled/);
});

test('active equipped requests refresh verification and can be cancelled after the controller stops', async () => {
  const r = rig();
  r.status.capabilities.live_weapon = { available: true };
  r.status.live_weapon = { phase: 'equipped', active: true, verified: true };
  let tick, cleared = false;
  const context = vm.createContext({ module: { exports: {} }, setTimeout,
    setInterval(fn) { tick = fn; return { unref() {} }; }, clearInterval() { cleared = true; } });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../clients/web/viz/re5-modifiers.js'), 'utf8'), context);
  const host = { innerHTML: '' };
  const ctl = context.module.exports.mount(host, { session: SESSION, api: r.api });
  await new Promise(resolve => setImmediate(resolve));
  assert.match(host.innerHTML, /Longbow equipped and confirmed/);
  r.status.capabilities.live_weapon.available = false;
  r.status.live_weapon.verified = false;
  r.status.live_weapon.reason = 'Waiting for a fresh native observation.';
  tick(); await new Promise(resolve => setImmediate(resolve));
  assert.doesNotMatch(host.innerHTML, /Longbow equipped and confirmed/);
  assert.doesNotMatch(host.innerHTML, /data-re5-live-cancel disabled/);
  r.command = async () => { r.status.live_weapon = { phase: 'cancelled', active: false }; return { cancelled: true }; };
  await ctl.setLiveWeapon(false);
  assert.equal(r.commands().length, 1);
  assert.equal(ctl.state().error, false);
  const stale = { ...ctl.state(), stale: true, status: { ...r.status,
    live_weapon: { phase: 'equipped', active: true, verified: true } } };
  assert.doesNotMatch(M.html(stale), /Longbow equipped and confirmed/);
  ctl.stop(); assert.equal(cleared, true);
});

test('old workers cannot receive a live weapon command and reasons are escaped', async () => {
  const r = rig(); await r.control.refresh(); await r.control.setLiveWeapon(true);
  assert.equal(r.commands().length, 0);
  assert.match(M.html(r.control.state()), /Worker update pending/);
  r.status.capabilities.live_weapon = { available: true };
  r.status.live_weapon = { phase: 'pending', reason: '<img onerror=bad>' };
  await r.control.refresh();
  assert.doesNotMatch(M.html(r.control.state()), /<img onerror=bad>/);
  assert.match(M.html(r.control.state()), /&#60;img onerror=bad&#62;/);
});

test('native QTE setting requires capability and never reports a pending event as passed', async () => {
  const r = rig();
  r.command = async input => {
    assert.equal(input.op, 'instant_qte');
    r.status.qte_assist = { enabled: input.on, phase: 'pending', completed: false,
      reason: 'Waiting for the native event outcome.' };
    return { verified: true, qte_assist: structuredClone(r.status.qte_assist) };
  };
  await r.control.refresh(); await r.control.change('instant_qte', true);
  assert.equal(r.control.state().error, false);
  assert.equal(r.commands()[0].body.input.session_id, SESSION.session_id);
  assert.match(M.html(r.control.state()), /Wiggle and accumulation events/);
  assert.match(M.html(r.control.state()), /Waiting for the native event outcome/);
  assert.doesNotMatch(r.control.state().message, /QTE (passed|completed)/i);
  r.status.qte_assist = undefined;
  r.status.capabilities.instant_qte = { available: false, reason: 'Worker update pending.' };
  await r.control.refresh(); await r.control.change('instant_qte', true);
  assert.equal(r.commands().length, 1);
});

test('next Mercenaries selection retains actual mode costume and stage', async () => {
  const r = rig();
  r.status.capabilities.mercs_select = { available: true };
  r.command = async input => { r.status.mercs_rotation = { next: input }; return { verified: true }; };
  await r.control.refresh();
  await r.control.selectMercs('mercenaries', 'Jill (Battle Suit)', 7);
  assert.deepEqual(r.commands()[0].body.input, { session_id: 'worker-launch', op: 'mercs_select',
    mode: 'mercenaries', character: 'Jill (Battle Suit)', stage: 7 });
  assert.match(r.control.state().message, /Queued.*current round continues/);
  r.sessions = [];
  await r.control.selectMercs('reunion', 'Barry', 0);
  assert.equal(r.commands().length, 1);
});

test('queued exact Mercenaries selection stays visibly pending until native start acknowledgment', async () => {
  const r=rig();r.status.capabilities.mercs_select={available:true};
  r.status.mercs_catalog={rosters:{mercenaries:['Sheva (Tribal)'],reunion:['Excella']},stages:['Public Assembly']};
  const selection={mode:'mercenaries',character:'Sheva (Tribal)',stage:0};
  r.command=async()=>{
    r.status.mercs_rotation={next:selection,selection_request:{id:'request',state:'queued',selection}};
    return {verified:true,queued:true,native_start_verified:false,request_id:'request'};
  };
  await r.control.refresh();await r.control.selectMercs(selection.mode,selection.character,selection.stage);
  assert.match(M.html(r.control.state()),/Queued: The Mercenaries \/ Sheva \(Tribal\) \/ Public Assembly/);
  assert.doesNotMatch(M.html(r.control.state()),/Started and confirmed in game/);
  r.status.mercs_rotation.selection_request.state='started';
  r.status.mercs_rotation.selection_request.confirmation='native_round_start';
  r.status.mercs_rotation.next={mode:'reunion',character:'Excella',stage:0};
  await r.control.refresh();
  assert.match(M.html(r.control.state()),/Started and confirmed in game: The Mercenaries \/ Sheva \(Tribal\) \/ Public Assembly/);
});

test('next selection cannot claim queue success when fresh readback has another costume',async()=>{
  const r=rig();r.status.capabilities.mercs_select={available:true};
  r.command=async()=>{r.status.mercs_rotation={next:{mode:'reunion',character:'Excella',stage:0}};return {verified:true};};
  await r.control.refresh();await r.control.selectMercs('mercenaries','Sheva (Tribal)',0);
  assert.equal(r.control.state().error,true);
  assert.match(r.control.state().message,/Fresh readback did not confirm/);
});

test('an exact native start between queue completion and readback is acknowledged by request ID',async()=>{
  const r=rig();r.status.capabilities.mercs_select={available:true};
  const selection={mode:'mercenaries',character:'Sheva (Tribal)',stage:0};
  r.command=async()=>{
    r.status.mercs_rotation={next:{mode:'reunion',character:'Excella',stage:6},
      selection_request:{id:'request',state:'started',selection,confirmation:'native_round_start'}};
    return {verified:true,queued:true,request_id:'request'};
  };
  await r.control.refresh();await r.control.selectMercs(selection.mode,selection.character,selection.stage);
  assert.equal(r.control.state().error,false);
  assert.match(r.control.state().message,/requested round has started.*confirmed in game/);
  r.command=async()=>({verified:true,queued:true,request_id:'different-request'});
  await r.control.selectMercs(selection.mode,selection.character,selection.stage);
  assert.equal(r.control.state().error,true);
});

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
  r.status.capabilities.instant_qte = { available: false, reason: 'Build not verified.' };
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
  assert.equal((html.match(/aria-checked="mixed"/g) || []).length, 8);   // existing modifiers plus native QTE assistance
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

test('explicit available gun selection is scoped and waits for native confirmation',async()=>{
  const r=rig();r.status.capabilities.select_weapon={available:true};
  r.status.available_weapons=[{item:27,weapon:'S&W M500',rounds:5}];
  await r.control.refresh();let reads=0;
  r.command=async input=>{
    assert.equal(input.weapon,27);
    r.status.preferred_weapon={item:27,weapon:'S&W M500',available:true,equipped:false,persistent:true};
    r.status.random_weapon_request={id:'selected-gun',state:'pending'};
    return {queued:true,verified:false,preference_saved:true,request:r.status.random_weapon_request};
  };
  r.onStatus=()=>{if(++reads===2){r.status.random_weapon_request.state='confirmed';
    r.status.preferred_weapon.equipped=true;r.status.in_hand.weapon='S&W M500';}};
  await r.control.change('select_weapon',27);
  assert.deepEqual(r.commands()[0].body.input,{session_id:'worker-launch',op:'select_weapon',weapon:27});
  assert.equal(reads,2);assert.equal(r.control.state().message,'Equipped S&W M500.');
  assert.match(M.html(r.control.state()),/Kept for this session and restored after mines or egg mode/);
  assert.equal(r.control.state().status.unlimited_health,false);
});

test('deferred preference is saved honestly until gunplay resumes and unavailable choice stays visible',async()=>{
  const r=rig();r.status.capabilities.select_weapon={available:true};
  r.status.available_weapons=[{item:27,weapon:'S&W M500',rounds:5}];await r.control.refresh();
  r.command=async()=>{
    r.status.preferred_weapon={item:27,weapon:'S&W M500',available:true,equipped:false,persistent:true};
    r.status.random_weapon_request={id:'deferred',state:'deferred',weapon:'S&W M500'};
    return {queued:true,verified:false,preference_saved:true,deferred:true,request:r.status.random_weapon_request};
  };
  await r.control.change('select_weapon',27);
  assert.match(r.control.state().message,/Preferred gun saved.*gunplay resumes/);
  assert.doesNotMatch(r.control.state().message,/Equipped/);
  assert.equal(r.control.state().weaponPending,null);
  r.status.available_weapons=[];r.status.preferred_weapon.available=false;await r.control.refresh();
  assert.match(M.html(r.control.state()),/S&#38;W M500 — unavailable in this loadout/);
});

test('Auto clears the preference without changing any modifier or inventing an equip',async()=>{
  const r=rig();r.status.capabilities.select_weapon={available:true};
  r.status.available_weapons=[{item:27,weapon:'S&W M500',rounds:5}];
  r.status.preferred_weapon={item:27,weapon:'S&W M500',available:true,equipped:true};await r.control.refresh();
  r.command=async()=>{r.status.preferred_weapon=null;return {verified:true,automatic:true,preference_saved:true};};
  await r.control.change('select_weapon',null);
  assert.deepEqual(r.commands()[0].body.input,{session_id:'worker-launch',op:'select_weapon',on:false});
  assert.match(r.control.state().message,/Automatic gun selection enabled/);
  assert.equal(r.commands().length,1);assert.equal(r.control.state().status.unlimited_health,false);
  await r.control.change('select_weapon',999);assert.equal(r.commands().length,1);
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
  assert.match(shell, /GBoxRE5Modifiers\.mount\(host, \{ session: current, api,/);
  assert.doesNotMatch(fs.readFileSync(require.resolve('../clients/web/viz/re5-modifiers.js'), 'utf8'), /write_memory|read_memory|Bearer|x-gbox-actor/);
});

test('time per kill defaults to ten seconds and preserves explicit historical settings', async () => {
  const row = M.DEFINITIONS.find(d => d.op === 'kill_time');
  assert.equal(row.multiplier, undefined);                     // a toggle never sends seconds, so the range is kept
  assert.match(M.html({ status: { ...BASE, kill_time_on: true } }), /3 s per kill/);
  assert.match(M.html({ status: BASE }), /data-re5-range="kill_time"[^>]*value="3"/);
  assert.match(M.html({status:{...BASE,kill_time_range:undefined}}), /data-re5-range="kill_time"[^>]*value="10"/);
  const status = { ...structuredClone(BASE), kill_time_on: true, kill_time_range: '10' };
  const on = M.html({ status });
  assert.match(on, /10 s per kill/);
  assert.doesNotMatch(on, /Random 10/);
  assert.match(on, /data-re5-mod="kill_time"[^>]*aria-checked="true" checked/);
  const off = M.html({ status: { ...status, kill_time_on: false } });
  assert.match(off, /data-re5-mod="kill_time"[^>]*aria-checked="false" >/);
  const r = rig(); r.status.kill_time_range = '10'; await r.control.refresh();
  await r.control.change('kill_time', true);
  assert.deepEqual(r.commands()[0].body.input, { session_id: SESSION.session_id, op: 'kill_time', on: true });
  assert.equal(r.control.state().status.kill_time_range, '10');
});

test('numeric sliders send exact values as scoped operator jobs and confirm three seconds per kill', async () => {
  for (const [op, number] of [['kill_time', 3], ['fire_rate', 12.5], ['bullet_damage', 2.5], ['turn_speed', 1.5]]) {
    const r = rig(); await r.control.refresh(); await r.control.setMultiplier(op, String(number));
    assert.deepEqual(r.commands()[0].body, { tool: 're5_mods', agent_use: false, require_worker: 'worker',
      input: { session_id: SESSION.session_id, op, on: true, multiplier: number } });
    assert.equal(r.control.state().error, false);
    assert.equal(r.control.state().stale, false);
    assert.match(r.control.state().message, op === 'kill_time' ? /3 seconds per kill/ : new RegExp(number + ' times'));
  }
});

test('numeric slider bounds match each verified operation and reject invalid values without jobs', async () => {
  for (const op of ['fire_rate', 'bullet_damage', 'turn_speed', 'kill_time']) {
    const def = M.DEFINITIONS.find(row => row.op === op);
    for (const number of [def.min, def.max]) {
      const r = rig(); await r.control.refresh(); await r.control.setMultiplier(op, number);
      assert.equal(r.commands().length, 1, `${op} accepts ${number}`);
      assert.equal(r.control.state().error, false);
    }
    const r = rig(); await r.control.refresh();
    for (const bad of [def.min - .01, def.max + .01, NaN, Infinity, -Infinity, '', '3 seconds', '1-10'])
      await r.control.setMultiplier(op, bad);
    assert.equal(r.commands().length, 0, `${op} rejects out-of-range/non-numeric values`);
  }
});

test('requesting multiplier one confirms the actual default value', async () => {
  for (const op of ['fire_rate', 'bullet_damage', 'turn_speed']) {
    const r = rig(); await r.control.refresh(); await r.control.setMultiplier(op, 1);
    assert.equal(r.control.state().error, false);
    assert.equal(r.commands()[0].body.input.multiplier, 1);
  }
});

test('numeric controls require verified actual readback rather than queue success or a fallback value', async () => {
  for (const [op, number, change] of [
    ['kill_time', 3, status => { status.kill_time_on = true; delete status.kill_time_range; }],
    ['kill_time', 3, status => { status.kill_time_on = true; status.kill_time_range = 'not a number'; }],
    ['kill_time', 3, status => { status.kill_time_on = false; status.kill_time_range = '3'; }],
    ['kill_time', 3, status => { status.kill_time_on = true; status.kill_time_range = '10'; }],
    ['fire_rate', 80, status => { delete status.fire_rate_x; }],
    ['bullet_damage', 10, status => { status.bullet_damage_x = null; }],
    ['turn_speed', 3, status => { status.turn_speed_x = 1; }],
  ]) {
    const r = rig(); await r.control.refresh();
    r.command = async () => { change(r.status); return { verified: true }; };
    await r.control.setMultiplier(op, number);
    assert.equal(r.control.state().error, true, `${op} rejects missing, disabled or mismatching readback`);
    assert.equal(r.control.state().stale, true);
    assert.doesNotMatch(r.control.state().message, /seconds per kill\.|times\.$/);
  }
  const r = rig(); await r.control.refresh();
  r.command = async () => { r.status.kill_time_on = true; r.status.kill_time_range = '3'; return { verified: false }; };
  await r.control.setMultiplier('kill_time', 3);
  assert.equal(r.control.state().error, true);
});

test('a pending numeric mutation keeps sliders disabled, preserves readback and blocks duplicate jobs', async () => {
  const r = rig(); await r.control.refresh();
  let finish;
  r.command = () => new Promise(resolve => { finish = () => {
    r.status.kill_time_on = true; r.status.kill_time_range = '3'; resolve({ verified: true });
  }; });
  const pending = r.control.setMultiplier('kill_time', 3);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(r.control.state().status.kill_time_on, false);
  assert.match(M.html(r.control.state()), /data-re5-range="kill_time"[^>]*disabled/);
  await r.control.setMultiplier('fire_rate', 20);
  await r.control.change('unlimited_health', true);
  assert.equal(r.commands().length, 1);
  finish(); await pending;
  assert.equal(r.control.state().busy, false);
  assert.equal(r.control.state().status.kill_time_on, true);
});

test('numeric sliders cannot mutate ended, replaced, stale, unavailable or closed sessions', async () => {
  for (const sessions of [[], [{ ...SESSION, state: 'ended' }], [{ ...SESSION, session_id: 'worker-new' }]]) {
    const r = rig(); await r.control.refresh(); r.sessions = sessions;
    await r.control.setMultiplier('kill_time', 3);
    assert.equal(r.commands().length, 0);
    assert.equal(r.control.state().error, true);
  }
  const r = rig(); await r.control.setMultiplier('kill_time', 3); // no initial status
  assert.equal(r.commands().length, 0);
  await r.control.refresh(); r.control.stop(); await r.control.setMultiplier('kill_time', 3);
  assert.equal(r.commands().length, 0);
  const denied = rig(); denied.status.capabilities.kill_time.available = false;
  await denied.control.refresh(); await denied.control.setMultiplier('kill_time', 3);
  assert.equal(denied.commands().length, 0);
  const busy = rig(); await busy.control.refresh();
  busy.active = [{ id: 'existing', tool: 're5_mods', input: { session_id: SESSION.session_id } }];
  await busy.control.setMultiplier('kill_time', 3);
  assert.equal(busy.commands().length, 0); assert.equal(busy.control.state().pending, 'existing');
});

test('mounted slider previews do not mutate gameplay and change uses the requested numeric value', async () => {
  const r = rig(), output = { textContent: '' };
  const host = { innerHTML: '', querySelector: selector => {
    assert.equal(selector, '[data-re5-value="kill_time"]'); return output;
  } };
  const control = M.mount(host, { session: SESSION, api: r.api });
  await new Promise(resolve => setImmediate(resolve));
  const target = { dataset: { re5Range: 'kill_time' }, value: '3', matches: selector => selector === '[data-re5-range]' };
  host.oninput({ target });
  assert.equal(output.textContent, '3 seconds'); assert.equal(r.commands().length, 0);
  host.onchange({ target }); await new Promise(resolve => setImmediate(resolve));
  assert.equal(r.commands()[0].body.input.multiplier, 3);
  assert.equal(control.state().error, false); control.stop();
});

function desktopPipRig({ compact = true, lookup = async () => SESSION, history = [] } = {}) {
  const source = fs.readFileSync(path.join(__dirname, '../clients/desktop/index.html'), 'utf8');
  const host = {}, menu = { opening: {}, style: {}, querySelector: () => host }, mounts = [], calls = [];
  const stream = { src: '', getAttribute(name) { return name === 'src' ? this.src : null; } };
  let stops = 0;
  const context = vm.createContext({
    $: selector => selector === '#compact-stream' ? stream : menu,
    gboxStreamWatchdog: { sessionOf: src => /\/api\/sessions\/([^/]+)\/mjpeg/.exec(src)?.[1] },
    COMPACT: { on: compact, sid: SESSION.session_id }, EMB: { sid: SESSION.session_id, last: '' },
    GM: { menu: true }, compactSession: compact ? SESSION : null, sessionById: lookup,
    GBoxSessionContinuity: CONTINUITY,
    GBoxRE5Modifiers: { eligible: M.eligible, panelEligible: M.panelEligible, replacementSession: M.replacementSession, sectionHTML: M.sectionHTML,
      mount: (target, options) => { mounts.push({ target, options }); return { stop: () => { stops++; } }; } },
    gbox: { api: async (...args) => { calls.push(args); return { ok: true,
      data: args[0].startsWith('/api/sessions?') ? history : { confirmed: true } }; } },
  });
  vm.runInContext(source.slice(source.indexOf('function closePipMenu()'), source.indexOf('function pipMenu(x, y)')), context);
  return { context, host, menu, stream, mounts, calls, source, stops: () => stops };
}

test('desktop PiP mounts the exact compact session and unwraps authenticated IPC responses', async () => {
  const r = desktopPipRig(); await r.context.pipModifiers(r.menu, r.menu.opening);
  assert.equal(r.mounts.length, 1);
  assert.equal(r.mounts[0].target, r.host);
  assert.equal(r.mounts[0].options.session, SESSION);
  const result = await r.mounts[0].options.api('/api/jobs', { input: { op: 'kill_time' } }, 'POST');
  assert.deepEqual(result, { confirmed: true });
  assert.deepEqual(r.calls.at(-1), ['/api/jobs', { input: { op: 'kill_time' } }, 'POST']);
  r.context.closePipMenu(); assert.equal(r.stops(), 1);
  assert.equal(r.menu.style.display, 'none'); assert.equal(r.menu.opening, null);
});

test('desktop PiP closure during a session lookup prevents a late modifier panel', async () => {
  let finish;
  const r = desktopPipRig({ compact: false, lookup: () => new Promise(resolve => { finish = resolve; }) });
  const pending = r.context.pipModifiers(r.menu, r.menu.opening);
  r.context.closePipMenu(); finish(SESSION); await pending;
  assert.equal(r.mounts.length, 0);
  const ended = desktopPipRig({ compact: false, lookup: async () => ({ ...SESSION, state: 'ended' }) });
  await ended.context.pipModifiers(ended.menu, ended.menu.opening);
  assert.equal(ended.mounts.length, 0);
});

test('desktop PiP recovers modifier scope from its displayed stream after runtime metadata is absent', async () => {
  const lookedUp = [];
  const r = desktopPipRig({ lookup: async sid => { lookedUp.push(sid); return SESSION; } });
  r.context.COMPACT.sid = ''; r.context.EMB.sid = ''; r.context.compactSession = null;
  r.stream.src = `http://spark:8765/api/sessions/${SESSION.session_id}/mjpeg?token=test`;
  await r.context.pipModifiers(r.menu, r.menu.opening);
  assert.deepEqual(lookedUp, [SESSION.session_id]);
  assert.equal(r.mounts.length, 1); assert.equal(r.mounts[0].options.session, SESSION);
});

test('the actual PiP stream takes precedence over an older still-running metadata session', async () => {
  const r = desktopPipRig({ lookup: async sid => sid === SESSION.session_id ? SESSION : null });
  r.context.COMPACT.sid = r.context.EMB.sid = 'worker-old';
  r.context.compactSession = { ...SESSION, session_id: 'worker-old' };
  r.stream.src = `http://spark:8765/api/sessions/${SESSION.session_id}/mjpeg`;
  await r.context.pipModifiers(r.menu, r.menu.opening);
  assert.equal(r.mounts.length, 1); assert.equal(r.mounts[0].options.session, SESSION);
  const unrelated = desktopPipRig({ lookup: async () => null });
  unrelated.stream.src = 'http://spark:8765/api/sessions/unknown-launch/mjpeg';
  await unrelated.context.pipModifiers(unrelated.menu, unrelated.menu.opening);
  assert.equal(unrelated.mounts.length, 0, 'unknown displayed stream cannot fall back to another session');
});

function replacedSessions() {
  const old = { ...SESSION, state: 'ended', started: 1, detail: { worker_name: 'spark' }, replaced_by: 'worker-new' };
  const fresh = { ...SESSION, session_id: 'worker-new', started: 2, detail: { worker_name: 'spark' } };
  return { old, fresh };
}

test('modifier replacement follows the exact historical chain and refuses unrelated targets and cycles', () => {
  const { old, fresh } = replacedSessions();
  assert.equal(M.replacementSession(old.session_id, [old, fresh], old, CONTINUITY.resolve), fresh);
  const middle = { ...old, session_id: 'worker-middle', replaced_by: fresh.session_id };
  assert.equal(M.replacementSession(old.session_id, [{ ...old, replaced_by: middle.session_id }, middle, fresh], old, CONTINUITY.resolve), fresh);
  for (const change of [{ game_id: 'another-game' }, { adapter: 'retroarch' },
    { detail: { worker_name: 'foreign-pc' } }, { collection_mod: 'other-build' }])
    assert.equal(M.replacementSession(old.session_id, [old, { ...fresh, ...change }], old, CONTINUITY.resolve), null);
  const foreignMiddle = { ...middle, detail: { worker_name: 'foreign-pc' } };
  assert.equal(M.replacementSession(old.session_id, [{ ...old, replaced_by: middle.session_id }, foreignMiddle, fresh], old, CONTINUITY.resolve), null);
  assert.equal(M.replacementSession(old.session_id, [old, { ...fresh, replaced_by: old.session_id }], old, CONTINUITY.resolve), null);
  assert.equal(M.replacementSession('missing-launch', [fresh], null, CONTINUITY.resolve), null);
});

test('desktop PiP refreshes its anchor and binds only a verified historical replacement', async () => {
  const { old, fresh } = replacedSessions(), seen = [];
  const r = desktopPipRig({ lookup: async sid => { seen.push(sid); return old; }, history: [old, fresh] });
  r.context.compactSession = { ...old, state: 'running' }; // stale cached metadata must not win
  r.stream.src = `http://spark:8765/api/sessions/${old.session_id}/mjpeg`;
  await r.context.pipModifiers(r.menu, r.menu.opening);
  assert.deepEqual(seen, [old.session_id]);
  assert.equal(r.mounts.length, 1); assert.equal(r.mounts[0].options.session, fresh);
  assert.equal(r.calls[0][0], '/api/sessions?limit=200');
  const foreign = desktopPipRig({ lookup: async () => old, history: [old, { ...fresh, detail: { worker_name: 'other' } }] });
  await foreign.context.pipModifiers(foreign.menu, foreign.menu.opening);
  assert.equal(foreign.mounts.length, 0);
});

function miniPipRig(readSessions = async () => ({ ok: true, data: [{ ...SESSION, session_id: 'other-launch' }, SESSION] })) {
  const source = fs.readFileSync(path.join(__dirname, '../clients/desktop/mini.html'), 'utf8');
  const listeners = {}, mounts = [], menus = [], calls = [], viewerCalls = [];
  let stops = 0, restored = 0;
  const host = {}, context = vm.createContext({
    v: { src: 'http://spark:8765/api/sessions/worker-launch/mjpeg?token=test' }, innerWidth: 1280, innerHeight: 720,
    addEventListener: (name, fn, options) => { listeners[name] = { fn, options }; },
    gboxStreamWatchdog: { sessionOf: src => /\/api\/sessions\/([^/]+)\/mjpeg/.exec(src)?.[1] },
    document: { body: { append: menu => menus.push(menu) }, createElement: () => ({ style: {}, offsetWidth: 300,
      offsetHeight: 400, children:[], append(...children){this.children.push(...children);}, querySelector: () => host, remove() { this.removed = true; } }) },
    GBoxSessionContinuity: CONTINUITY,
    GBoxRE5Modifiers: { eligible: M.eligible, panelEligible: M.panelEligible, replacementSession: M.replacementSession, sectionHTML: M.sectionHTML,
      mount: (target, options) => { mounts.push({ target, options }); return { stop: () => { stops++; } }; } },
    gbox: { api: async (...args) => { calls.push(args); return args[0].startsWith('/api/sessions')
      ? readSessions(args[0]) : { ok: true, data: { confirmed: true } }; }, miniRestore: () => { restored++; },
      mercsOpen:async options=>{viewerCalls.push(options);return {opened:true};} }, URL,
    console: { warn() {} },
  });
  vm.runInContext(source.slice(source.indexOf('let modifierMenu ='), source.indexOf('// file:// cannot fetch health')), context);
  const event = { clientX: 1200, clientY: 700, preventDefault() {}, stopPropagation() {} };
  return { context, listeners, mounts, menus, calls, viewerCalls, event, source, stops: () => stops, restored: () => restored };
}

test('detached PiP opens its map or reviewer separately even with no eligible mod panel',async()=>{
  for(const [index,mode] of [[0,'map'],[1,'reviewer']]){
    const r=miniPipRig(async()=>({ok:true,data:[]}));await r.listeners.contextmenu.fn(r.event);
    assert.equal(r.mounts.length,0);r.menus[0].children[index].onclick();
    assert.equal(r.viewerCalls.length,1);assert.equal(r.viewerCalls[0].origin,'http://spark:8765');
    assert.equal(r.viewerCalls[0].sid,'worker-launch');assert.equal(r.viewerCalls[0].mode,mode);
    assert.equal(r.restored(),0,'opening the reviewer never restores or closes gameplay');
  }
});

test('detached PiP right-click binds the displayed session and uses the authenticated modifier API', async () => {
  const r = miniPipRig(); await r.listeners.contextmenu.fn(r.event);
  assert.equal(r.mounts.length, 1);
  assert.equal(r.mounts[0].options.session, SESSION);
  assert.equal(r.mounts[0].target, r.menus[0].querySelector('.re5-modifiers'));
  assert.deepEqual(await r.mounts[0].options.api('/api/jobs', { op: 'status' }, 'POST'), { confirmed: true });
  assert.deepEqual(r.calls.at(-1), ['/api/jobs', { op: 'status' }, 'POST']);
  assert.equal(r.menus[0].style.left, '972px');
  assert.equal(r.menus[0].style.top, '312px');
  r.listeners.pagehide.fn(); assert.equal(r.stops(), 1); assert.equal(r.menus[0].removed, true);
});

test('detached PiP discards late lookups after closure and refuses ended or unrelated sessions', async () => {
  let finish;
  const r = miniPipRig(() => new Promise(resolve => { finish = resolve; }));
  const opening = r.listeners.contextmenu.fn(r.event);
  r.listeners.pagehide.fn(); finish({ ok: true, data: [SESSION] }); await opening;
  assert.equal(r.mounts.length, 0);
  for (const rows of [[{ ...SESSION, state: 'ended' }], [{ ...SESSION, session_id: 'other-launch' }]]) {
    const other = miniPipRig(async () => ({ ok: true, data: rows }));
    await other.listeners.contextmenu.fn(other.event); assert.equal(other.mounts.length, 0);
  }
});

test('detached PiP resolves a retired displayed SID through strict history and refuses foreign replacements', async () => {
  const { old, fresh } = replacedSessions();
  for (const candidate of [fresh, { ...fresh, game_id: 'another-game' }, { ...fresh, detail: { worker_name: 'foreign' } }]) {
    const r = miniPipRig(async url => ({ ok: true, data: url.includes('limit=200') ? [old, candidate] : [] }));
    await r.listeners.contextmenu.fn(r.event);
    assert.equal(r.mounts.length, candidate === fresh ? 1 : 0);
    if (candidate === fresh) assert.equal(r.mounts[0].options.session, fresh);
    assert.deepEqual(r.calls.map(args => args[0]), ['/api/sessions?include_ended=false', '/api/sessions?limit=200']);
  }
});

test('detached PiP editing keeps the menu open and Escape closes it before restoring the full app', async () => {
  const r = miniPipRig(); await r.listeners.contextmenu.fn(r.event);
  const inside = { target: { closest: () => r.menus[0] } };
  r.listeners.mousedown.fn(inside); r.listeners.dblclick.fn(inside);
  assert.equal(r.stops(), 0); assert.equal(r.restored(), 0);
  r.listeners.keydown.fn({ key: 'Escape' });
  assert.equal(r.stops(), 1); assert.equal(r.restored(), 0);
  r.listeners.keydown.fn({ key: 'Escape' }); assert.equal(r.restored(), 1);
});

test('both PiP shells load modifier UI and compact right-click owns the gameplay context menu', () => {
  const desktop = desktopPipRig().source, mini = miniPipRig().source;
  for (const source of [desktop, mini])
    assert.match(source, /<script src="\.\.\/web\/viz\/re5-modifiers\.js"><\/script>/);
  assert.match(desktop, /if \(!COMPACT\.on \|\| event\.target\.closest\?\.\('#pipmenu'\)\) return/);
  assert.match(desktop, /event\.preventDefault\(\);\s*event\.stopPropagation\(\);\s*pipMenu\(event\.clientX, event\.clientY\)/);
  const follow = desktop.slice(desktop.indexOf('const compactContinuity ='), desktop.indexOf('setInterval(() => compactContinuity.poll()'));
  assert.match(follow, /closePipMenu\(\)/);
  assert.match(mini, /follow: async session => \{\s*closeModifiers\(\)/);
});

// --- the Mercenaries clock control (operator 2026-10-26: stalemates) ---
function clockRig(left = 95) {
  const r = rig();
  r.status.merc_seconds_left = left;
  r.status.capabilities.add_time = { available: true }; r.status.capabilities.set_time = { available: true };
  r.command = async input => {
    const before = r.status.merc_seconds_left, wanted = input.op === 'set_time' ? input.seconds : before + input.seconds;
    const after = Math.max(1, wanted); r.status.merc_seconds_left = after;
    return { verified: true, clock_before: before, clock_after: after, clamped: after !== wanted };
  };
  return r;
}
const flush = async () => { for (let i = 0; i < 12; i++) await new Promise(resolve => setImmediate(resolve)); };

test('the Mercenaries clock control sends add_time / set_time with the exact seconds and confirms from the verified result', async () => {
  const r = clockRig(); await r.control.refresh();
  const html = M.html(r.control.state());
  assert.match(html, /<fieldset class="mercs-clock" >/); assert.match(html, /95 s left on the clock/);
  assert.match(html, /data-clock-delta[^>]*value="-30"/); assert.match(html, /Set clock to 5 s/);
  assert.equal(M.clockState(r.control.state()).disabled, false);
  await r.control.addTime('-30');
  assert.deepEqual(r.commands()[0].body, { tool: 're5_mods', agent_use: false, require_worker: 'worker',
    input: { session_id: 'worker-launch', op: 'add_time', seconds: -30 } });
  assert.equal(r.control.state().message, 'Clock 95 → 65 s.'); assert.equal(r.control.state().error, false);
  await r.control.setTime(5);
  assert.deepEqual(r.commands()[1].body.input, { session_id: 'worker-launch', op: 'set_time', seconds: 5 });
  assert.equal(r.control.state().message, 'Clock 65 → 5 s.'); assert.equal(r.control.state().status.merc_seconds_left, 5);
  await r.control.addTime(30);
  assert.equal(r.control.state().message, 'Clock 5 → 35 s.');
  await r.control.addTime(-3600 + 3570);                 // -30 again: the game stops at 1 s and says so
  assert.equal(r.control.state().message, 'Clock 35 → 5 s.');
  await r.control.addTime(-30);
  assert.equal(r.control.state().message, 'Clock 5 → 1 s (stopped at 1 s).');
  const sent = r.commands().length;
  for (const bad of [0, 31, -31, 'x']) await r.control.addTime(bad);
  for (const bad of [0, 61, 2.5]) await r.control.setTime(bad);
  assert.equal(r.commands().length, sent, 'out-of-range values never send a job');
  r.command = async () => ({ verified: false, reason: 'authoritative countdown write not confirmed' });
  await r.control.addTime(10);
  assert.equal(r.control.state().error, true); assert.match(r.control.state().message, /not confirmed/); assert.equal(r.control.state().stale, true);
});

test('the clock control is disabled without a round or on a worker without the ops, and keeps its drafts across repaints', async () => {
  const r = clockRig(null); await r.control.refresh();
  assert.equal(M.clockState(r.control.state()).disabled, true); assert.match(M.html(r.control.state()), /no Mercenaries round is up/);
  await r.control.addTime(-30); await r.control.setTime(5); assert.equal(r.commands().length, 0);
  const old = rig(); old.status.merc_seconds_left = 90; await old.control.refresh();      // no add_time capability: an older worker
  const st = M.clockState(old.control.state()); assert.equal(st.disabled, true); assert.match(st.reason, /Worker update pending/);
  assert.match(M.html(old.control.state()), /<fieldset class="mercs-clock" disabled>/);
  await old.control.setTime(5); assert.equal(old.commands().length, 0);
  r.control.clockDraft({ delta: 12, set: 20 });
  assert.match(M.html(r.control.state()), /data-clock-delta[^>]*value="12"/); assert.match(M.html(r.control.state()), /Set clock to 20 s/);
  assert.equal(M.html({ ...r.control.state(), teamOnly: true }).includes('mercs-clock'), false, 'the RE6 team-only panel has no clock');
});

test('mounted clock inputs preview without a job and the buttons send the chosen seconds through the panel', async () => {
  const r = clockRig();
  const nodes = { '[data-clock-delta-out]': { textContent: '' }, '[data-clock-set-apply]': { textContent: '' },
    '[data-clock-delta]': { value: '-12' }, '[data-clock-set]': { value: '9' } };
  const host = { innerHTML: '', querySelector: selector => nodes[selector] || null };
  const control = M.mount(host, { session: SESSION, api: r.api });
  await flush();
  host.oninput({ target: { value: '-12', matches: s => s === '[data-clock-delta]' } });
  assert.equal(nodes['[data-clock-delta-out]'].textContent, '−12 s'); assert.equal(r.commands().length, 0);
  host.oninput({ target: { value: '9', matches: s => s === '[data-clock-set]' } });
  assert.equal(nodes['[data-clock-set-apply]'].textContent, 'Set clock to 9 s');
  assert.deepEqual(control.state().clock, { delta: -12, set: 9 });
  host.onclick({ target: { closest: s => s === '[data-clock-apply]' ? { disabled: false } : null } }); await flush();
  assert.deepEqual(r.commands()[0].body.input, { session_id: 'worker-launch', op: 'add_time', seconds: -12 });
  host.onclick({ target: { closest: s => s === '[data-clock-set-apply]' ? { disabled: false } : null } }); await flush();
  assert.deepEqual(r.commands()[1].body.input, { session_id: 'worker-launch', op: 'set_time', seconds: 9 });
  assert.equal(control.state().message, 'Clock 83 → 9 s.');
  assert.match(host.innerHTML, /data-clock-delta[^>]*value="-12"/, 'the repaint keeps the slider where the operator left it');
  control.stop();
});

test('RE5 on Switch gets the same panel: eligible on Citron / Eden, split-screen team controls, not-yet ops disabled with their reason', async () => {
  const sw = { session_id: 'lilspark-re5sw', game_id: M.SWITCH, state: 'running', adapter: 'citron' };
  assert.equal(M.eligible(sw), true);
  assert.equal(M.eligible({ ...sw, adapter: 'eden' }), true);
  assert.equal(M.panelEligible(sw), true);
  for (const change of [{ adapter: 'rpcs3' }, { adapter: 'retroarch' }, { state: 'ended' }, { stopping: true }, { session_id: 'x' }])
    assert.equal(M.eligible({ ...sw, ...change }), false);
  assert.equal(M.eligible({ ...SESSION, adapter: 'citron' }), false);          // the PS3 game on a Switch emulator: no
  const status = { ...structuredClone(BASE), edition: 'switch', turn_speed_x: null,
    capabilities: { ...structuredClone(BASE.capabilities),
      turn_speed: { available: false, reason: 'not yet on Switch: sParameter’s turn rates are not mapped' } } };
  const calls = [];
  const api = async (path, body) => {
    calls.push({ path, body });
    if (path.startsWith('/api/sessions')) return [sw];
    if (path.startsWith('/api/jobs?')) return [];
    return { id: 'job', state: 'succeeded', output: { result: { status: structuredClone(status) } } };
  };
  let painted;
  const control = M.create({ session: sw, api, render: s => { painted = s; }, delay: async () => {}, teamControls: true });
  await control.refresh();
  assert.equal(control.state().error, false);
  assert.ok(calls.some(c => c.body?.tool === 'mercs_team' && c.body.input.op === 'status'), 'the team read for split screen');
  assert.equal(calls.find(c => c.body?.tool)?.body.input.session_id, 'lilspark-re5sw');
  const html = M.html(painted);
  assert.match(html, /RE5 modifiers \(Switch\)/);
  assert.match(html, /Team and training/);                                     // split screen (gbox/switch_coop.py)
  const turn = M.rows(painted).find(r => r.op === 'turn_speed');
  assert.equal(turn.disabled, true);
  assert.match(html, /not yet on Switch: sParameter/);
  const fire = M.rows(painted).find(r => r.op === 'fire_rate');
  assert.equal(fire.disabled, false);
  // the next-round weapon (a loadout template change) stays usable where the live gun choice is not yet
  const live = { ...painted, status: { ...painted.status, capabilities: { ...painted.status.capabilities,
    select_weapon: { available: false, reason: 'not yet on Switch: the Switch bot’s weapon choice is not wired yet' },
    weapon_override: { available: true } } } };
  const page = M.html(live);
  assert.match(page, /<fieldset class="re5-mine-controls" ><legend>Next-round weapon<\/legend>/);
  assert.match(page, /<fieldset class="re5-mine-controls" disabled><legend>Preferred gun<\/legend>/);
});

test('Switch split screen: bots on both players, Player 2 connected by an in-place restart, RE6 Switch team-only', async () => {
  const sw = { session_id: 'lilspark-re5sw', game_id: M.SWITCH, state: 'running', adapter: 'citron' };
  const re6 = { session_id: 'lilspark-re6sw', game_id: M.RE6_SWITCH, state: 'running', adapter: 'citron' };
  assert.equal(M.panelEligible(re6), true);
  assert.equal(M.eligible(re6), false);                                         // no re5_mods on RE6
  assert.equal(M.panelEligible({ ...re6, adapter: 'xenia' }), false);
  const team = { config: { role: 'solo_p1', training_profile: 'assisted', auto_reduce_mods: false, selected_route_id: null },
    phase: 'active', control_player: 1, split_screen: true,
    capabilities: { teammate_p2: { available: false, reason: 'Player 2 has not joined the round' },
      bots_p1_p2: { available: true }, prepare_player2: { available: true, restart_available: true } } };
  const calls = [];
  const api = async (path, body) => {
    calls.push({ path, body });
    if (path.startsWith('/api/sessions')) return [re6];
    if (path.startsWith('/api/jobs?')) return [];
    if (body?.input?.op === 'prepare_player2') team.player2_preparation = { player: 2, prepared: true, verified: false, reason: 'restarting' };
    return { id: 'job', state: 'succeeded', output: { result: { status: structuredClone(team), configuration_verified: true } } };
  };
  let painted;
  const control = M.create({ session: re6, api, render: s => { painted = s; }, delay: async () => {}, teamControls: true });
  await control.refresh();
  assert.ok(!calls.some(c => c.body?.tool === 're5_mods'), 'RE6 Switch never asks for RE5 modifiers');
  const html = M.html(painted);
  assert.match(html, /RE6 team and training \(Switch\)/);
  assert.match(html, /<option value="bots_p1_p2" >Bots on Player 1 and Player 2 \(split screen\)<\/option>/);
  assert.match(html, /data-re5-team-prepare data-restart="1" >Connect Player 2 and restart this title now/);
  await control.preparePlayer2({ restart: true });
  const prep = calls.find(c => c.body?.input?.op === 'prepare_player2');
  assert.deepEqual(prep.body.input, { session_id: 'lilspark-re6sw', op: 'prepare_player2', restart: true });
  await control.setTeam({ role: 'bots_p1_p2' });
  assert.ok(calls.some(c => c.body?.input?.op === 'configure' && c.body.input.role === 'bots_p1_p2'));
  // the PS3 panel keeps its own wording and never offers bots on both players
  const ps3 = M.html({ team: { ...structuredClone(team), split_screen: false }, teamOnly: true });
  assert.doesNotMatch(ps3, /bots_p1_p2/);
  assert.match(ps3, /Prepare Player 2 controller for next launch/);
});
