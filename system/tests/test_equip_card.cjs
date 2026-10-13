// Zelda equip screen (#212): the card rendered from a fake item table, the chat event that carries it, and the button
// dispatch onto the existing zelda ops (give / equip <button> / unrestrict / all_items / catalog refresh).
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../clients/desktop/index.html'), 'utf8');
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);

const catalog = {
  game: 'Ocarina of Time', groups: ['inventory', 'equipment', 'upgrades'], buttons: ['b', 'c-left', 'c-down', 'c-right'], default_button: 'c-left',
  unrestrict: true, all_items: true, hearts: true, rupees: true,
  items: [{ name: 'bow', group: 'inventory', equip: 'button', count: 30 }, { name: 'bottle', group: 'inventory', equip: 'button', count: null },
          { name: 'master sword', group: 'equipment', equip: 'worn', count: null }, { name: 'goron tunic', group: 'equipment', equip: 'worn', count: null },
          { name: 'giants wallet', group: 'upgrades', equip: null, count: null }, { name: '<odd>', group: 'upgrades', equip: null, count: null }],
};
const state = { game: 'Ocarina of Time', items: ['bow', 'master sword'], buttons: { b: 'master sword', 'c-left': 'bow', 'c-down': null, 'c-right': null }, hearts: 3.5, max_hearts: 5, rupees: 42 };

function fixture() {
  const jobs = [], results = {}, toasts = [];
  const ctx = { esc, EMB: { last: '' }, toast: t => toasts.push(t), chatContext: async () => ({}), floating() {}, $: () => null,
    document: { addEventListener() {} },
    gameJob: async (tool, input) => { jobs.push({ tool, ...input }); if (results.error) throw new Error(results.error);
      return input.op === 'catalog' ? { catalog, state: results.state || state } : { op: input.op, item: input.item, button: input.button || undefined, verified: true, ...(results[input.op] || {}) }; } };
  vm.createContext(ctx);
  vm.runInContext(source.slice(source.indexOf('// ---------------- Zelda equip screen (#212)'), source.indexOf('// ---------------- controller settings icon (#622)')), ctx);
  ctx.EQ = vm.runInContext('EQ', ctx);                      // a const binding: lives in the script scope, not on the global
  return { ctx, jobs, results, toasts };
}
const card = (f, id) => { const msg = { textContent: '' }, c = { dataset: { eq: id }, innerHTML: '', querySelector: s => s === '.eqb' ? { value: 'c-down' } : msg }; c.msg = msg; return c; };
const button = (op, item) => ({ dataset: { op }, closest: () => item ? { dataset: { item } } : null });

test('the card lists the chosen group with Give / Equip / Let me use and marks what Link has', () => {
  const f = fixture(), html = f.ctx.equipCardHtml(catalog, state);
  assert.match(html, /Inventory <small>2<\/small>/); assert.match(html, /Equipment <small>2<\/small>/); assert.match(html, /Upgrades <small>2<\/small>/);
  assert.match(html, /class="eqtab on" data-tab="inventory"/);
  assert.match(html, /class="eqit have" data-item="bow"><div class="eqn"><b>bow<\/b><span class="mut">on C-LEFT · ×30<\/span>/);
  assert.match(html, /class="eqit" data-item="bottle"/);
  assert.equal((html.match(/data-op="give"/g) || []).length, 2); assert.equal((html.match(/data-op="equip"/g) || []).length, 2);
  assert.equal((html.match(/data-op="use"/g) || []).length, 2);
  assert.match(html, /<select class="eqb"[^>]*>.*<option value="c-left" selected>C-LEFT<\/option>/s);
  assert.match(html, /♥ 3\.5 \/ 5 · ◆ 42/); assert.match(html, /data-op="all_items"/); assert.match(html, /data-op="unrestrict"/); assert.match(html, /data-op="refresh"/);
  assert.ok(!html.includes('master sword'), 'other groups stay on their own tab');
});

test('equipment wears instead of equipping, upgrades only give, names are escaped and the search filters', () => {
  const f = fixture();
  const gear = f.ctx.equipCardHtml(catalog, state, { tab: 'equipment' });
  assert.match(gear, /data-item="master sword"[^]*?data-op="equip"[^>]*>Wear</); assert.match(gear, /class="eqit have" data-item="master sword"/);
  assert.match(gear, /on B/);
  const up = f.ctx.equipCardHtml(catalog, null, { tab: 'upgrades', note: 'live values unavailable' });
  assert.ok(!up.includes('data-op="equip"')); assert.match(up, /&#60;odd&#62;/); assert.ok(!up.includes('<odd>')); assert.match(up, /live values unavailable/);
  assert.match(f.ctx.equipCardHtml(catalog, null), /no save loaded yet/);
  const q = f.ctx.equipCardHtml(catalog, state, { q: 'BOT' });
  assert.match(q, /data-item="bottle"/); assert.ok(!q.includes('data-item="bow"'));
  assert.match(f.ctx.equipCardHtml(catalog, state, { q: 'zzz' }), /nothing matches/);
  assert.ok(!f.ctx.equipCardHtml({ ...catalog, buttons: ['y'] }, state).includes('<select'), 'one button needs no chooser');
  assert.ok(!f.ctx.equipCardHtml({ ...catalog, unrestrict: false, all_items: false }, state).includes('data-op="unrestrict"'));
});

test('the chat event from zelda op=catalog renders the same card and remembers its session', () => {
  const f = fixture();
  const html = f.ctx.equipCardEvent({ type: 'cards', kind: 'equip', session_id: 'pc-1', game: 'Ocarina of Time', catalog, state, items: catalog.items });
  const id = /data-eq="(eq\d+)"/.exec(html)[1];
  assert.match(html, /^<div class="cm equip eqcard" data-eq="eq\d+">/); assert.match(html, /data-item="bow"/);
  assert.equal(f.ctx.EQ.cards[id].sid, 'pc-1'); assert.equal(f.ctx.EQ.cards[id].tab, 'inventory');
  const bare = f.ctx.equipCardEvent({ type: 'cards', kind: 'equip', session_id: 'pc-2', items: catalog.items });
  assert.match(bare, /data-item="bow"/);
  // the conversation renderer hands the equip kind to it
  const r = { esc, S: {}, SBX: {}, equipCardEvent: e => `<div class="cm equip">${e.session_id}</div>`, encodeURIComponent };
  vm.createContext(r); vm.runInContext(source.slice(source.indexOf('function choicesHtml('), source.indexOf('async function chatLoad(')), r);
  assert.equal(r.renderEvent({ type: 'cards', kind: 'equip', session_id: 'pc-9', items: [{ name: 'x' }] }), '<div class="cm equip">pc-9</div>');
});

test('buttons dispatch the zelda ops on the session and refresh the live values', async () => {
  const f = fixture();
  const id = f.ctx.equipRegister({ cat: catalog, state, sid: 'pc-1' }), c = card(f, id);
  await f.ctx.equipAction(c, button('equip', 'bow'));
  assert.deepEqual(f.jobs.map(j => [j.tool, j.session_id, j.op, j.item, j.button]), [['zelda', 'pc-1', 'equip', 'bow', 'c-down'], ['zelda', 'pc-1', 'catalog', undefined, undefined]]);
  assert.equal(f.ctx.EQ.cards[id].msg, '✓ equip bow · on c-down'); assert.match(c.innerHTML, /✓ equip bow · on c-down/);
  f.jobs.length = 0; await f.ctx.equipAction(c, button('give', 'bottle'));
  assert.deepEqual(f.jobs.map(j => [j.op, j.item, j.button]), [['give', 'bottle', ''], ['catalog', undefined, undefined]]);
  f.jobs.length = 0; await f.ctx.equipAction(c, button('use', 'bottle'));
  assert.deepEqual(f.jobs.map(j => [j.op, j.item]), [['give', 'bottle'], ['unrestrict', ''], ['catalog', undefined]]);
  assert.match(f.ctx.EQ.cards[id].msg, /^✓ usable: bottle/);
  f.jobs.length = 0; await f.ctx.equipAction(c, button('all_items'));
  assert.deepEqual(f.jobs.map(j => j.op), ['all_items', 'catalog']); assert.match(f.ctx.EQ.cards[id].msg, /everything given/);
  f.jobs.length = 0; await f.ctx.equipAction(c, button('refresh'));
  assert.deepEqual(f.jobs.map(j => j.op), ['catalog']); assert.equal(f.ctx.EQ.cards[id].msg, '');
  f.results.state = { ...state, items: ['bow', 'bottle'] }; await f.ctx.equipAction(c, button('refresh'));
  assert.match(c.innerHTML, /class="eqit have" data-item="bottle"/, 'the read-back marks the new item');
});

test('tabs re-render without a job, notes from the tool are shown and failures are reported in place', async () => {
  const f = fixture();
  const id = f.ctx.equipRegister({ cat: catalog, state, sid: 'pc-1' }), c = card(f, id);
  await f.ctx.equipAction(c, { dataset: { tab: 'equipment' }, closest: () => null });
  assert.equal(f.jobs.length, 0); assert.equal(f.ctx.EQ.cards[id].tab, 'equipment'); assert.match(c.innerHTML, /data-item="goron tunic"/);
  f.results.equip = { note: 'the C-button icon is drawn on the next area load', verified: false };
  await f.ctx.equipAction(c, button('equip', 'bow'));
  assert.equal(f.ctx.EQ.cards[id].msg, '✓ equip bow · on c-down · not verified · the C-button icon is drawn on the next area load');
  f.results.error = 'not in gameplay yet';
  await f.ctx.equipAction(c, button('give', 'bow'));
  assert.equal(c.msg.textContent, '⚠ not in gameplay yet');
  await f.ctx.equipAction({ dataset: { eq: 'nope' } }, button('give', 'bow'));
  assert.equal(f.jobs.filter(j => j.op === 'give').length, 1, 'an unknown card dispatches nothing');
});

test('the game menu offers the Equip screen on Zelda titles and routes it to the panel', () => {
  assert.match(source, /\/zelda\/i\.test\(EMB\.title \|\| ""\) \? \[\["equip", "🗡 Equip screen/);
  assert.match(source, /else if \(a === "equip"\) equipShow\(\);/);
  assert.match(source, /\["#equip", "#pipmenu"\]/);
});
