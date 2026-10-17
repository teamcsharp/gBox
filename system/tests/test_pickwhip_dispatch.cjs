const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');
const source = fs.readFileSync(path.join(__dirname, '../clients/desktop/index.html'), 'utf8');
function fixture() {
  const calls = [], toasts = [], input = { value: 'Claude' };
  const menu = { style: {}, classList: { add() {}, remove() {} }, insertAdjacentHTML() {},
    querySelector: () => input, contains: () => true };
  const ctx = { EMB: { sid: 'worker-game', title: 'GTA III', rect: { x: 100, y: 100, w: 800, h: 600 } },
    innerWidth: 1500, innerHeight: 950, $: () => menu, esc: String, fitMenu() {}, dragAnywhere() {},   // layout helpers: no-ops on the fake menu
    toast: text => toasts.push(text), refreshInbox() {},
    gbox: { api: async (url, body) => { calls.push({ url, body });
      return url === '/api/whip/identify' ? { ok: true, data: { b: { name: 'Claude', kind: 'player' } } } :
        { ok: true, data: { number: 42, context: { resolution_dispatch: 'hermes_queue' } } }; } } };
  vm.createContext(ctx);
  vm.runInContext(source.slice(source.indexOf('async function autoWhipFailure('),
                              source.indexOf('async function whipMenuGame(')), ctx);
  return { ctx, menu, calls, toasts, click: action => menu.onclick({ target: {
    closest: () => ({ dataset: { w: action } }) } }) };
}
for (const action of ['swap', 'rebuild']) test(`${action} persists donor and frozen target without a chat`, async () => {
  const f = fixture();
  await f.ctx.whipCardMenu({ name: 'Amy Rose', slug: 'sa2_amy_rose' }, [500, 400], { shot: 'data:image/png;base64,frame' });
  assert.equal(f.calls.length, 0); // displaying the menu does not wait for inference
  await f.click(action);
  assert.equal(f.calls.length, 1);
  const { url, body } = f.calls[0];
  assert.equal(url, '/api/requests/auto-mod-failure');
  assert.equal(body.session_id, 'worker-game');
  assert.equal(body.character, 'sa2_amy_rose');
  assert.equal(body.target, 'Claude');
  assert.equal(body.x, .5); assert.equal(body.y, .5);
  assert.equal(body.image_b64, 'frame');
  assert.equal(body.replacement_requested, true);
  assert.equal(body.needs_rebuild, action === 'rebuild');
  assert.match(f.toasts[0], /queued for Hermes/);
});
test('changed game refuses the old drop and identification uses screenshot coordinates', async () => {
  const f = fixture();
  await f.ctx.whipCardMenu({ name: 'Amy', slug: 'amy' }, [500, 400], { shot: 'data:image/png;base64,frame' });
  await f.click('identify');
  assert.equal(f.calls[0].body.b[0], 500 / 1500);
  f.ctx.EMB.sid = 'different-game';
  await f.click('swap');
  assert.equal(f.calls.length, 1);
  assert.match(f.toasts.at(-1), /selected game changed/);
});
// the whip's live swap runs the shared replace chain (clients/web/viz/pick-whip.js): pwApi answers the control plane's
// /api/jobs; tools = {} is an older control plane without pick_identify / pick_replace (404 unknown tool)
function vrFixture(game, tools = {}) {
  const jobs = [], toasts = [], input = { value: '' }, live = { innerHTML: 'live' }, api = [];
  const menu = { style: {}, classList: { add() {}, remove() {} }, insertAdjacentHTML() {}, contains: () => true,
    querySelector: sel => sel.includes('live') ? live : input };
  const ctx = { EMB: { sid: 'pc-vr', game, title: 'Metal Gear Solid - VR Missions', rect: { x: 0, y: 0, w: 640, h: 480 } },
    innerWidth: 1000, innerHeight: 800, $: () => menu, esc: String, fitMenu() {}, dragAnywhere() {},
    toast: t => toasts.push(t), refreshInbox() {}, gbox: { api: async () => ({ ok: true, data: {} }) },
    PW: require('../clients/web/viz/pick-whip.js'),
    pwCon: () => ({ anchor() {}, open: () => ({ update() {}, log() {}, done() {} }) }),
    pwApi: async (p, body) => { api.push(JSON.parse(JSON.stringify({ p, body })));
      if (p !== '/api/jobs' || !tools[body.tool]) throw new Error(`404 unknown tool ${body && body.tool}`);
      return { id: 'j' + api.length, state: 'succeeded', output: { result: tools[body.tool] } }; },
    gameJob: async (tool, inp) => { jobs.push(JSON.parse(JSON.stringify({ tool, inp })));
      return inp.op === 'resolve_slot' ? { slot: 'enemy:soldier', name: 'Genome soldiers (every VR soldier)', kind: 'enemy' }
                                       : { status: 'live_swapped', message: 'Sonic replaces the soldiers' }; } };
  vm.createContext(ctx);
  vm.runInContext(source.slice(source.indexOf('async function autoWhipFailure('),
                              source.indexOf('async function whipMenuGame(')), ctx);
  return { ctx, menu, jobs, toasts, input, live, api };
}
test('VR Missions drop names the slot under it and the live swap targets that slot', async () => {
  const f = vrFixture('afd2fc507bb69843');
  await f.ctx.whipCardMenu({ name: 'Sonic', slug: 'sonic' }, [320, 240], {});
  await new Promise(r => setTimeout(r, 0));
  assert.deepEqual(f.jobs[0], { tool: 'characters', inp: { op: 'resolve_slot', session_id: 'pc-vr', x: .5, y: .5,
                                                           window_aspect: 1.3333 } });
  assert.match(f.live.innerHTML, /Put Sonic in place of Genome soldiers/);
  assert.equal(f.input.value, 'Genome soldiers (every VR soldier)');
  await f.menu.onclick({ target: { closest: () => ({ dataset: { w: 'live' } }) } });
  assert.deepEqual(f.jobs[1], { tool: 'characters', inp: { op: 'live_use', character: 'sonic', session_id: 'pc-vr',
                                                           slot: 'enemy:soldier' } });
  assert.match(f.toasts.at(-1), /Sonic replaces the soldiers/);
});
test('a game without a slot resolver is not asked and the live swap sends the point', async () => {
  const f = vrFixture('0123456789abcdef');
  await f.ctx.whipCardMenu({ name: 'Sonic', slug: 'sonic' }, [320, 240], {});
  assert.equal(f.jobs.length, 0);
  await f.menu.onclick({ target: { closest: () => ({ dataset: { w: 'live' } }) } });
  assert.deepEqual(f.jobs[0].inp, { op: 'live_use', character: 'sonic', session_id: 'pc-vr', x: .5, y: .5,
                                    window_aspect: 1.3333, target: 'the character at this point' });
});
test('with pick_identify / pick_replace on the control plane the whip replaces the identified pick', async () => {
  const pick = { entity: { class: 'Genome' }, slot: 'enemy:soldier', ram: { model: '0x80100000' }, replaceable: { live: true }, backend: 'profile' };
  const f = vrFixture('0123456789abcdef', { pick_identify: pick, pick_replace: { status: 'live', mode_used: 'live', message: 'Sonic is in' } });
  await f.ctx.whipCardMenu({ name: 'Sonic', slug: 'sonic' }, [320, 240], {});
  await f.menu.onclick({ target: { closest: () => ({ dataset: { w: 'live' } }) } });
  assert.equal(f.jobs.length, 0);                                                    // no live_use: pick_replace took
  const rep = f.api.find(c => c.body && c.body.tool === 'pick_replace').body;
  assert.equal(rep.input.pick.slot, 'enemy:soldier'); assert.equal(rep.input.mode, 'live'); assert.equal(rep.require_worker, 'pc');
  assert.equal(f.api.find(c => c.body && c.body.tool === 'pick_identify').body.input.window_aspect, 1.3333);
  assert.match(f.toasts.at(-1), /Sonic: replaced live .*Sonic is in/);
});
