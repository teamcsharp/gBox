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
    innerWidth: 1500, innerHeight: 950, $: () => menu, esc: String,
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
