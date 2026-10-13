// Controller icon (#622): the desktop game bar / toolbar icon and the web session bar icon open the running emulator's own
// controller settings over the game (session rpc op=menu) and fall back to gBox's controller mapping when the emulator has none.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const desktop = fs.readFileSync(path.join(__dirname, '../clients/desktop/index.html'), 'utf8');
const web = fs.readFileSync(path.join(__dirname, '../clients/web/index.html'), 'utf8');

function desktopFixture(reply, sid = 'pc1-abc') {
  const calls = [], toasts = [], actions = [], pad = {};
  const ctx = { EMB: { sid }, chatContext: async () => ({ session_id: sid ? sid : undefined }), encodeURIComponent,
    gbox: { api: async (url, body) => { calls.push({ url, body }); return reply; } }, toast: t => toasts.push(t), gameAction: async a => actions.push(a),
    $: () => pad };
  vm.createContext(ctx);
  vm.runInContext(desktop.slice(desktop.indexOf('// ---------------- controller settings icon (#622)'), desktop.indexOf('// ---------------- PSO item sidebar')), ctx);
  return { ctx, calls, toasts, actions, pad };
}

test('desktop icon toggles the emulator menu over the docked game', async () => {
  const f = desktopFixture({ ok: true, data: { menu: 'toggled' } });
  assert.equal(await f.ctx.padSettings(), true);
  assert.deepEqual(JSON.parse(JSON.stringify(f.calls)), [{ url: '/api/sessions/pc1-abc/rpc', body: { op: 'menu', args: {} } }]);
  assert.match(f.toasts[0], /Controls/); assert.match(f.toasts[0], /again to close/); assert.deepEqual(f.actions, []);
  assert.equal(typeof f.pad.onclick, 'function'); f.pad.onclick();                 // the toolbar button is wired to it
  assert.equal(f.calls.length, 2);
});

test('an emulator without the menu falls back to gBox controller mapping and says so', async () => {
  const f = desktopFixture({ ok: false, error: 'dolphin: open its controller settings from its own window' });
  assert.equal(await f.ctx.padSettings(), false);
  assert.deepEqual(f.actions, ['mapping']);
  assert.match(f.toasts[0], /dolphin: open its controller settings from its own window/); assert.match(f.toasts[0], /controller mapping/);
});

test('without a running game the mapping page opens and nothing is sent', async () => {
  const f = desktopFixture({ ok: true }, null);
  assert.equal(await f.ctx.padSettings(), false);
  assert.deepEqual(f.calls, []); assert.deepEqual(f.actions, ['mapping']); assert.match(f.toasts[0], /No game running/);
});

test('the icon sits on the toolbar, the PiP bar and the game menu', () => {
  assert.match(desktop, /<button id="tb-pad" hidden title="Controller settings of the running emulator/);
  assert.match(desktop, /\$\("#tb-mini"\)\.hidden = \$\("#tb-pad"\)\.hidden = /);                  // shown while a game runs
  assert.match(desktop, /<button data-a="pad" title="Controller settings/);                           // PiP bar
  assert.match(desktop, /a === "pad" \? gameAction\("pad"\)/);
  assert.match(desktop, /\["pad", "🎮 Controller settings \(emulator menu\)"\]/);                      // right-click menu
  assert.match(desktop, /else if \(a === "pad"\) await padSettings\(\);/);
});

function webFixture(api) {
  const shows = [], sopres = { textContent: '' }, btn = { attrs: { 'aria-pressed': 'false' }, getAttribute(k) { return this.attrs[k]; }, setAttribute(k, v) { this.attrs[k] = v; } };
  const ctx = { $: s => s === '#sopres' ? sopres : null, api, show: t => shows.push(t), encodeURIComponent };
  vm.createContext(ctx);
  vm.runInContext(web.slice(web.indexOf('async function padSettings(sid, btn)'), web.indexOf('async function sop(sid, op)')), ctx);
  return { ctx, shows, sopres, btn };
}

test('web session bar icon opens and closes the emulator menu in place', async () => {
  const calls = [], w = webFixture(async (url, body) => { calls.push({ url, body }); return { menu: 'toggled' }; });
  assert.equal(await w.ctx.padSettings('w-1', w.btn), true);
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [{ url: '/api/sessions/w-1/rpc', body: { op: 'menu', args: {} } }]);
  assert.equal(w.btn.attrs['aria-pressed'], 'true'); assert.match(w.sopres.textContent, /open over the game/); assert.deepEqual(w.shows, []);
  await w.ctx.padSettings('w-1', w.btn);
  assert.equal(w.btn.attrs['aria-pressed'], 'false'); assert.match(w.sopres.textContent, /closed/);
});

test('web icon shows the Controllers page when the emulator keeps its settings in its own window', async () => {
  const w = webFixture(async () => { throw new Error('422 xenia: open its controller settings from its own window'); });
  assert.equal(await w.ctx.padSettings('w-2', w.btn), false);
  assert.deepEqual(w.shows, ['Controllers']); assert.match(w.sopres.textContent, /xenia: open its controller settings from its own window/);
  assert.match(w.sopres.textContent, /controller mapping instead/);
  assert.match(web, /<button class="act" id="padbtn"[^>]*onclick='padSettings\(\$\{JSON\.stringify\(sid\)\}, this\)'/);
});
