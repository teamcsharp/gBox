// "Special builds ▸/▾" in the game right-click menu (clients/web/viz/game-menu.js over GET /api/games/{id}/special_builds,
// gbox/special_builds.py): drawn at once with placeholder rows while the read hangs, filled from the answer; open /
// closed remembered per user; each build's Quick launch + options submenu (PCs, saved moment, debugger, Mods page,
// request, Rebuild); "Rebuild all confirmation builds" queues Spark jobs and hands them to the process pop-up; the same
// section mounted into the desktop app's game chip menu. Plus the wiring in both clients.
const { test, beforeEach } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const GM = require('../clients/web/viz/game-menu.js');

const GID = 'g1';
const opt = (id, label, node, extra = {}) => ({ id, label, node, target: extra.target || node, moment: false, debug: false, default: false, ...extra,
  call: { method: 'POST', path: `/api/games/${GID}/launch?node=${node}&mod=x` } });
const OPTS = slot => [opt('here', 'This PC', 'auto', { target: 'here', default: true }), opt('pc:i9-NUC', 'Play on i9-NUC (windows)', 'i9-NUC'),
  opt('pc:spark', 'Play on spark (linux)', 'spark'),
  ...(slot != null ? [opt('moment', `Play from saved moment (slot ${slot})`, 'auto', { target: 'here', moment: true, state_slot: slot })] : []),
  opt('debug', 'Play with the debugger (Spark)', 'linux', { debug: true })];
const KANE = { key: 'g1/g1_kane_req', name: 'g1_kane_req', mod_title: 'Kane as Neo', kind: 'character', summary: 'kane → neo',
  tickets: [{ number: 9, id: 'r9', title: 'Kane as the hero', status: 'in_progress' }], launch_options: OPTS(null),
  rebuild_recipe: { tool: 'characters', input: { op: 'use', character: 'kane', game_id: GID, slot: 'neo', launch: false, rebuild: true } } };
const HUCAST = { key: 'g1/g1_hucast', name: 'g1_hucast', mod_title: 'HUcast in G1', kind: 'character', state_slot: 3, card_id: 'card1',
  tickets: [{ number: 5, id: 'r5', title: 'Put HUcast in G1', status: 'done' }], launch_options: OPTS(3),
  rebuild_recipe: { tool: 'characters', input: { op: 'use', character: 'hucast', game_id: GID, slot: 'player', launch: false, rebuild: true } } };
const CAST = { key: 'g1/cast_g1', name: 'cast_g1', mod_title: 'G1: cast as Wrestlers', kind: 'cast', tickets: [], launch_options: OPTS(null),
  summary: 'Wrestlers (No Mercy, WCW, SmackDown! 2, Def Jam) · 1/2 slots built, 1 failed',
  cast: { source: 'Wrestlers', summary: '1/2 slots built, 1 failed', rows: [] },
  rebuild_recipe: { tool: 'characters', input: { op: 'cast_swap', target_game: GID, source: 'wrestlers' } } };
const PATCH = { key: 'g1/g1_patch', name: 'g1_patch', kind: 'other', tickets: [], launch_options: OPTS(null), rebuild_recipe: null,
  recipe_missing: 'the marker records no character or cast plan to build it from', summary: 'built by g1' };
const SPECIAL = { game_id: GID, total: 4, groups: [
  { key: 'confirmation', label: 'Confirmation builds', count: 2, builds: [KANE, HUCAST] },
  { key: 'cast', label: 'Cast swaps', count: 1, builds: [CAST] },
  { key: 'character', label: 'Character swaps', count: 0, builds: [] },
  { key: 'other', label: 'Other', count: 1, builds: [PATCH] }] };

function fakeMenu() {
  const el = { html: '', classes: new Set(), style: {},
    get innerHTML() { return this.html; }, set innerHTML(v) { this.html = v; },
    classList: { add: c => el.classes.add(c), remove: c => el.classes.delete(c), contains: c => el.classes.has(c) },
    querySelector(sel) {
      const m = /^\[data-gm="(\w+)"\]$/.exec(sel); if (!m) return null;
      const start = el.html.indexOf(`<div data-gm="${m[1]}">`); if (start < 0) return null;
      const next = el.html.indexOf('<div data-gm="', start + 1), end = next < 0 ? el.html.length : next;
      return { set outerHTML(v) { el.html = el.html.slice(0, start) + v + el.html.slice(end); } };
    },
    querySelectorAll: () => [] };
  return el;
}
function fakeStorage(init = {}) {
  const m = new Map(Object.entries(init));
  return { getItem: k => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), map: m };
}
function fakeIo(api, extra = {}) {
  const calls = { api: [], launch: [], mods: [], request: [], progress: [] };
  const io = { el: fakeMenu(), img: u => u, worker: 'i9-NUC', storage: fakeStorage(),
    api: (p, body) => { calls.api.push([p, body]); return api(p, body); },
    boot: { get: () => ({ disc: '', slot: '', character: '' }), set() {} }, keep: { get: () => [], set() {} }, badge() {},
    place() {}, refit() {}, models() {}, cover() {}, cast() {}, play() {},
    launch: (gid, x) => calls.launch.push([gid, x]), openMods: (gid, b) => calls.mods.push([gid, b && b.key]),
    openRequest: (t, b) => calls.request.push([t.number, t.title, b && b.key]), progress: jobs => calls.progress.push(jobs), ...extra };
  return { io, calls };
}
const hang = () => new Promise(() => {});
const answer = (p, body) => {
  if (p.endsWith('/special_builds/rebuild')) return Promise.resolve({ game_id: GID, queued: 2, job_ids: ['j1', 'j2'], skipped: [],
    jobs: [{ key: KANE.key, label: KANE.mod_title, job_id: 'j1', state: 'queued', tool: 'characters', input: KANE.rebuild_recipe.input },
           { key: HUCAST.key, label: HUCAST.mod_title, job_id: 'j2', state: 'queued', tool: 'characters', input: HUCAST.rebuild_recipe.input }] });
  if (p.endsWith('/special_builds')) return Promise.resolve(SPECIAL);
  if (p.startsWith('/api/characters')) return Promise.resolve([]);
  return Promise.resolve([]);
};
// a click on an element matching `sel` with these data attributes
const target = (sel, dataset) => ({ closest: s => (s === sel || (sel === '[data-gm-sb]' && s === '[data-gm-sb]')) ? { dataset } : null });
const sb = (act, extra = {}) => target('[data-gm-sb]', { gmSb: act, ...extra });
const tick = async (n = 4) => { for (let i = 0; i < n; i++) await new Promise(r => setTimeout(r, 0)); };
const openState = io => { io.storage.setItem(GM.SPECIAL_KEY, '1'); return io; };

beforeEach(() => GM._reset());

test('the section is in the menu at once: collapsed by default, a count placeholder while the read hangs', () => {
  const { io } = fakeIo(hang);
  const t0 = performance.now();
  GM.open(io, { gid: GID, title: 'G1' });
  assert.ok(performance.now() - t0 < 50);
  assert.match(io.el.html, /data-gm-sb="toggle" aria-expanded="false"[^>]*>Special builds ▸ <span class="mut" data-gm-loading="special-count">…/);
  assert.ok(!io.el.html.includes('data-gm-sbg='), 'collapsed: no group rows');
  assert.ok(GM.ORDER.indexOf('special') > GM.ORDER.indexOf('mods') && GM.ORDER.indexOf('special') < GM.ORDER.indexOf('play'));
});

test('expanded (remembered): placeholder rows for every group instantly, then filled from the endpoint', async () => {
  let resolve;
  const { io, calls } = fakeIo(p => p.endsWith('/special_builds') ? new Promise(r => { resolve = r; }) : hang());
  openState(io);
  const m = GM.open(io, { gid: GID, title: 'G1' });
  assert.match(io.el.html, /Special builds ▾/);
  for (const label of ['Confirmation builds', 'Cast swaps', 'Character swaps', 'Other'])
    assert.match(io.el.html, new RegExp(`<b style="font-size:12px">${label}</b>\\s*<div class="mut gm-sbph" data-gm-loading="special"`));
  assert.match(io.el.html, /data-gm-sb="rebuild-all"[^>]*disabled/, 'nothing to rebuild before the answer');
  assert.deepEqual(calls.api.map(c => c[0]).filter(p => p.includes('special')), [`/api/games/${GID}/special_builds`]);
  resolve(SPECIAL); await tick();
  const html = io.el.html;
  assert.ok(!html.includes('data-gm-loading="special"'));
  assert.match(html, /Special builds ▾ <span class="mut">\(4\)<\/span>/);
  assert.match(html, /Rebuild all confirmation builds \(2\)/);
  assert.ok(!/data-gm-sb="rebuild-all"[^>]*disabled/.test(html));
  assert.ok(html.indexOf('Kane as Neo') < html.indexOf('HUcast in G1') && html.indexOf('HUcast in G1') < html.indexOf('G1: cast as Wrestlers'),
    'groups in order, confirmation builds newest first as served');
  assert.match(html, /#9 Kane as the hero/);
  assert.match(html, /1\/2 slots built, 1 failed/);
  assert.match(html, /data-gm-sbg="character"><b style="font-size:12px">Character swaps<\/b> <span class="mut">0<\/span>\s*<div class="mut" style="font-size:11px">none<\/div>/);
  assert.match(html, /data-gm-sb="quick" data-key="g1\/g1_kane_req" title="Quick launch: Play on this PC \(i9-NUC\)"/);
  assert.deepEqual(m.state.errors, []);
});

test('collapse state: toggling repaints and is remembered per user (localStorage key per io.user, or the host store)', async () => {
  const { io } = fakeIo(answer, { user: 'mx' });
  const m = GM.open(io, { gid: GID, title: 'G1' });
  await m.settled;
  assert.match(io.el.html, /Special builds ▸ <span class="mut">\(4\)/);
  io.el.onclick({ target: sb('toggle') });
  assert.match(io.el.html, /Special builds ▾/); assert.match(io.el.html, /Kane as Neo/);
  assert.equal(io.storage.map.get(`${GM.SPECIAL_KEY}:mx`), '1');
  GM.open(io, { gid: GID, title: 'G1' });                    // the next right-click opens it expanded, from the cache
  assert.match(io.el.html, /Special builds ▾/); assert.match(io.el.html, /Kane as Neo/);
  io.el.onclick({ target: sb('toggle') });
  assert.equal(io.storage.map.get(`${GM.SPECIAL_KEY}:mx`), '0');
  assert.ok(!io.el.html.includes('Kane as Neo'));
  let kept = true;
  const host = fakeIo(answer, { special: { get: () => kept, set: v => { kept = v; } } });
  GM.open(host.io, { gid: GID, title: 'G1' });
  assert.match(host.io.el.html, /Special builds ▾/);
  host.io.el.onclick({ target: sb('toggle') });
  assert.equal(kept, false);
  const broken = fakeIo(hang, { storage: { getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); } } });
  GM.open(broken.io, { gid: GID, title: 'G1' });
  assert.match(broken.io.el.html, /Special builds ▸/, 'blocked storage: collapsed, still opens');
  broken.io.el.onclick({ target: sb('toggle') });
  assert.match(broken.io.el.html, /Special builds ▾/);
});

test('options submenu: PCs, saved moment, debugger, Mods page, request, Rebuild; launches go to the host', async () => {
  const { io, calls } = fakeIo(answer);
  openState(io);
  const m = GM.open(io, { gid: GID, title: 'G1' });
  await m.settled;
  io.el.onclick({ target: sb('opts', { key: HUCAST.key }) });
  const sub = io.el.html.slice(io.el.html.indexOf('data-gm-sbo="g1/g1_hucast"'));
  for (const s of ['▶ Play on this PC (i9-NUC)', '▶ Play on i9-NUC (windows)', '▶ Play on spark (linux)', '▶ Play from saved moment (slot 3)',
                   '▶ Play with the debugger (Spark)', 'Open in Mods page', 'Open request #5 · Put HUcast in G1', '⟳ Rebuild'])
    assert.ok(sub.includes(s), s);
  assert.match(io.el.html, /data-gm-sb="opts" data-key="g1\/g1_hucast" aria-haspopup="menu" aria-expanded="true"/);
  // quick launch: the default (this PC = io.worker)
  io.el.classes.add('on');
  io.el.onclick({ target: sb('quick', { key: KANE.key }) });
  assert.deepEqual(calls.launch.at(-1)[0], GID);
  assert.deepEqual({ ...calls.launch.at(-1)[1], option: undefined, build: undefined },
                   { mod: 'g1_kane_req', node: 'i9-NUC', debug: false, slot: '', option: undefined, build: undefined });
  assert.ok(!io.el.classes.has('on'), 'the menu closes on launch');
  io.el.onclick({ target: sb('launch', { key: HUCAST.key, opt: 'moment' }) });
  assert.equal(calls.launch.at(-1)[1].slot, 3); assert.equal(calls.launch.at(-1)[1].node, 'i9-NUC');
  io.el.onclick({ target: sb('launch', { key: HUCAST.key, opt: 'pc:spark' }) });
  assert.equal(calls.launch.at(-1)[1].node, 'spark');
  io.el.onclick({ target: sb('launch', { key: HUCAST.key, opt: 'debug' }) });
  assert.equal(calls.launch.at(-1)[1].debug, true); assert.equal(calls.launch.at(-1)[1].node, 'linux');
  io.el.onclick({ target: sb('mods', { key: HUCAST.key }) });
  assert.deepEqual(calls.mods, [[GID, HUCAST.key]]);
  io.el.onclick({ target: sb('request', { key: HUCAST.key, n: '5' }) });
  assert.deepEqual(calls.request, [[5, 'Put HUcast in G1', HUCAST.key]]);
  // a build without a recipe says why instead of offering Rebuild
  io.el.onclick({ target: sb('opts', { key: PATCH.key }) });
  assert.match(io.el.html, /No rebuild recipe: the marker records no character/);
  // no launch hook: the server's launch call, with this PC's name for node=auto
  const bare = fakeIo(answer, { launch: undefined });
  openState(bare.io);
  await GM.open(bare.io, { gid: GID, title: 'G1' }).settled;
  bare.io.el.onclick({ target: sb('quick', { key: KANE.key }) });
  assert.deepEqual(bare.calls.api.at(-1), [`/api/games/${GID}/launch?node=i9-NUC&mod=x`, {}]);
});

test('Rebuild all confirmation builds: one POST, job ids in the status line, the jobs handed to the process pop-up', async () => {
  const { io, calls } = fakeIo(answer);
  openState(io);
  const m = GM.open(io, { gid: GID, title: 'G1' });
  await m.settled;
  io.el.onclick({ target: sb('rebuild-all') });
  assert.match(io.el.html, /queueing every confirmation build on the Spark…/);
  assert.match(io.el.html, /data-gm-sb="rebuild-all"[^>]*disabled/, 'no double submit while queueing');
  await tick();
  assert.deepEqual(calls.api.filter(c => c[0].endsWith('/rebuild')), [[`/api/games/${GID}/special_builds/rebuild`, { recipes: 'all', group: 'confirmation' }]]);
  assert.match(io.el.html, /✓ 2 rebuilds queued on the Spark \(j1, j2\): progress in the pop-up/);
  assert.equal(calls.progress.length, 1);
  assert.deepEqual(calls.progress[0].map(j => [j.id, j.tool, j.state, j.input.op]), [['j1', 'characters', 'queued', 'use'], ['j2', 'characters', 'queued', 'use']]);
  // one build's Rebuild posts its own recipe
  io.el.onclick({ target: sb('rebuild', { key: CAST.key }) });
  await tick();
  assert.deepEqual(calls.api.filter(c => c[0].endsWith('/rebuild')).at(-1)[1], { recipes: [CAST.rebuild_recipe] });
  // a failing POST says why, the button comes back
  const bad = fakeIo((p, b) => p.endsWith('/rebuild') ? Promise.reject(new Error('503 Spark restarting')) : answer(p, b));
  openState(bad.io);
  await GM.open(bad.io, { gid: GID, title: 'G1' }).settled;
  bad.io.el.onclick({ target: sb('rebuild-all') }); await tick();
  assert.match(bad.io.el.html, /✗ 503 Spark restarting/);
  assert.ok(!/data-gm-sb="rebuild-all"[^>]*disabled/.test(bad.io.el.html));
});

test('a failed read says why with a Retry; Retry refetches', async () => {
  let fail = true;
  const { io } = fakeIo((p, b) => p.endsWith('/special_builds') && fail ? Promise.reject(new Error('gBox server unreachable')) : answer(p, b));
  openState(io);
  const m = GM.open(io, { gid: GID, title: 'G1' });
  await m.settled;
  assert.match(io.el.html, /Special builds didn&#39;t load: gBox server unreachable<button class="act" type="button" data-gm-retry="special"/);
  fail = false;
  io.el.onclick({ target: target('[data-gm-retry]', { gmRetry: 'special' }) });
  await tick();
  assert.match(io.el.html, /Kane as Neo/);
});

test('mountSpecial: the same section in another menu (the desktop chip menu), its own clicks, close on launch', async () => {
  let closed = 0;
  const { io, calls } = fakeIo(answer, { close: () => { closed++; } });
  openState(io);
  const host = { innerHTML: '' };
  const s = GM.mountSpecial(io, host, { gid: GID, title: 'G1' });
  assert.match(host.innerHTML, /Special builds ▾/); assert.match(host.innerHTML, /data-gm-loading="special"/);
  await s.settled;
  assert.match(host.innerHTML, /Kane as Neo/);
  let stopped = false;
  host.onclick({ target: sb('quick', { key: KANE.key }), stopPropagation: () => { stopped = true; } });
  assert.equal(calls.launch.length, 1); assert.equal(closed, 1); assert.ok(stopped, 'the chip menu does not also act on it');
  host.onclick({ target: sb('toggle'), stopPropagation() {} });
  assert.match(host.innerHTML, /Special builds ▸/);
});

// ------------------------------------------------------------------ #1656: Favorites group, ✎ Rename…, ★ in the options
const FAVED = { game_id: GID, total: 4, groups: [
  { key: 'favorites', label: 'Favorites', count: 1, builds: [{ ...HUCAST, favorite: true, home: 'confirmation', display_name: 'Sonic Full Cast',
                                                              mod_title: 'Sonic Full Cast', original_title: 'HUcast in G1' }] },
  { key: 'confirmation', label: 'Confirmation builds', count: 1, builds: [{ ...KANE, home: 'confirmation' }] },
  { key: 'cast', label: 'Cast swaps', count: 1, builds: [{ ...CAST, home: 'cast' }] },
  { key: 'character', label: 'Character swaps', count: 0, builds: [] },
  { key: 'other', label: 'Other', count: 1, builds: [{ ...PATCH, home: 'other' }] }] };

const clone = x => JSON.parse(JSON.stringify(x));          // the controller updates the rows it shows
function buildsIo(state) {
  const sent = [];
  const api = (p, body, method) => {
    if (p.startsWith('/api/builds/')) {
      sent.push([method, p, body]);
      if (p.endsWith('/favorite')) return Promise.resolve({ key: 'x', favorite: body.favorite });
      return Promise.resolve({ key: 'x', display_name: body.display_name, label: body.display_name || 'HUcast in G1' });
    }
    if (p.endsWith('/special_builds')) return Promise.resolve(state.special);
    return answer(p, body);
  };
  const r = fakeIo(api);
  r.io.api = (p, body, method) => { r.calls.api.push([p, body, method]); return api(p, body, method); };
  return { ...r, sent };
}

test('Favorites group at the top: ★ on the row, its name as the operator named it; Rebuild all still counts a favorited confirmation build', async () => {
  const { io } = buildsIo({ special: clone(FAVED) });
  openState(io);
  await GM.open(io, { gid: GID, title: 'G1' }).settled;
  const html = io.el.html;
  assert.ok(html.indexOf('data-gm-sbg="favorites"') < html.indexOf('data-gm-sbg="confirmation"'), 'Favorites first');
  assert.match(html, /<b style="font-size:12px">Favorites<\/b> <span class="mut">1<\/span>/);
  assert.match(html, /<span class="gm-fav" title="Favorite">★<\/span> Sonic Full Cast<\/span>/);
  assert.match(html, /title="Sonic Full Cast \(was “HUcast in G1”, folder g1_hucast\)"/);
  assert.match(html, /⟳ Rebuild all confirmation builds \(2\)/, 'the favorited confirmation build is still one of them');
});

test('✎ Rename… in a build\'s options: an inline field, Enter saves (PATCH), Esc cancels, empty restores; the menu refetches', async () => {
  const state = { special: clone(SPECIAL) };
  const { io, sent } = buildsIo(state);
  openState(io);
  const m = GM.open(io, { gid: GID, title: 'G1' });
  await m.settled;
  io.el.onclick({ target: sb('opts', { key: HUCAST.key }) });
  assert.match(io.el.html, /data-gm-sb="rename" data-key="g1\/g1_hucast"[^>]*>✎ Rename…</);
  assert.match(io.el.html, /data-gm-sb="fav" data-key="g1\/g1_hucast"[^>]*>★ Add to favorites</);
  io.el.onclick({ target: sb('rename', { key: HUCAST.key }) });
  assert.equal(m.state.sbRenaming, HUCAST.key);
  assert.match(io.el.html, /<input data-gm-sbrename="g1\/g1_hucast" value="HUcast in G1" maxlength="120"[^>]* data-nomic>/);
  assert.ok(!io.el.html.includes('data-gm-sbo='), 'the options close while renaming');
  const field = (value, key = HUCAST.key) => ({ closest: s => s === '[data-gm-sbrename]' ? { dataset: { gmSbrename: key }, value } : null });
  // a click inside the field stays in it; Esc cancels
  assert.equal(m.special.click(field('x')), true);
  io.el.onkeydown({ key: 'Escape', target: field('typed'), preventDefault() {}, stopPropagation() {} });
  assert.equal(m.state.sbRenaming, null); assert.equal(sent.length, 0);
  // Enter saves through PATCH /api/builds/{game}/{name}; the menu refetches its groups
  io.el.onclick({ target: sb('rename', { key: HUCAST.key }) });
  state.special = clone(FAVED);
  io.el.onkeydown({ key: 'Enter', target: field('  Sonic Full Cast  '), preventDefault() {} });
  await tick(6);
  assert.deepEqual(sent[0], ['PATCH', '/api/builds/g1/g1_hucast', { display_name: 'Sonic Full Cast' }]);
  assert.match(io.el.html, /✓ renamed “Sonic Full Cast” \(the folder stays g1_hucast\)/);
  assert.match(io.el.html, /Sonic Full Cast<\/span>/);
  // empty restores the original
  io.el.onclick({ target: sb('rename', { key: HUCAST.key }) });
  io.el.onkeydown({ key: 'Enter', target: field(''), preventDefault() {} });
  await tick(6);
  assert.deepEqual(sent[1], ['PATCH', '/api/builds/g1/g1_hucast', { display_name: '' }]);
});

test('★ Add to favorites from a build\'s options: PUT, the menu refetches with the Favorites group on top; mountSpecial gets keys too', async () => {
  const state = { special: clone(SPECIAL) };
  const { io, sent } = buildsIo(state);
  openState(io);
  const m = GM.open(io, { gid: GID, title: 'G1' });
  await m.settled;
  io.el.onclick({ target: sb('opts', { key: HUCAST.key }) });
  state.special = clone(FAVED);
  io.el.onclick({ target: sb('fav', { key: HUCAST.key }) });
  await tick(6);
  assert.deepEqual(sent[0], ['PUT', '/api/builds/g1/g1_hucast/favorite', { favorite: true }]);
  assert.match(io.el.html, /data-gm-sbg="favorites"/);
  assert.match(io.el.html, /★ HUcast in G1 is a favorite/);
  // un-star from the Favorites row
  io.el.onclick({ target: sb('opts', { key: HUCAST.key }) });
  assert.match(io.el.html, /☆ Remove from favorites/);
  // the desktop chip menu's mount has the same keys
  const host = { innerHTML: '' };
  const s = GM.mountSpecial(io, host, { gid: GID, title: 'G1' });
  await s.settled;
  host.onclick({ target: sb('rename', { key: HUCAST.key }), stopPropagation() {} });
  assert.match(host.innerHTML, /data-gm-sbrename="g1\/g1_hucast"/);
  host.onkeydown({ key: 'Escape', target: { closest: q => q === '[data-gm-sbrename]' ? { dataset: { gmSbrename: HUCAST.key }, value: '' } : null }, preventDefault() {}, stopPropagation() {} });
  assert.ok(!host.innerHTML.includes('data-gm-sbrename'));
});

test('Boot with a mod: a card of a renamed build shows its display name, ★ builds first', () => {
  const st = { gid: GID, title: 'G1', boot: { disc: '', slot: '', character: '' }, kept: [], chars: [], special: null, specialOpen: false,
               mods: [{ id: 'a', title: 'Plain card', calls: [{ tool: '@launch', input: { mod: 'plain' } }] },
                      { id: 'b', title: 'Patch card', display_name: 'Sonic Full Cast', favorite: true, calls: [{ tool: '@launch', input: { mod: 'g1_patch' } }] }] };
  const html = GM.SECTIONS.mods(st, GM.derive(st));
  assert.ok(html.indexOf('★ Sonic Full Cast') > 0 && html.indexOf('★ Sonic Full Cast') < html.indexOf('Plain card'));
  assert.ok(!html.includes('Patch card'));
});

test('wiring: the web game menu io and the desktop chip menu', () => {
  const read = f => fs.readFileSync(path.join(__dirname, '..', 'clients', f), 'utf8');
  const web = read('web/index.html'), desk = read('desktop/index.html'), gallery = read('web/viz/mods-gallery.js');
  const io = web.match(/const gameMenuIO = \(\) => \(\{[\s\S]*?\}\);\r?\n/);
  assert.ok(io, 'gameMenuIO found');
  assert.match(io[0], /launch: \(gid, x\) => play\(gid, x\.node === "auto" \? undefined : x\.node, !!x\.debug, \{ disc: x\.mod, slot:/);
  assert.match(io[0], /openMods: \(gid, b\) => \{ MODSG\.focus = \{ q: b\?\.name/);
  assert.match(io[0], /openRequest: t => \{ MODSG\.focus = \{ q: "#" \+ t\.number/);
  assert.match(io[0], /progress: jobs => window\.GBOX_PROCESS_POPUP\?\.sync\(jobs\)/);
  assert.match(web, /q: focus\.q, game: focus\.game/);
  assert.match(desk, /GBoxGameMenu\.mountSpecial\(chipSpecialIO\(m\), m\.querySelector\("\[data-chip-special\]"\), \{ gid: chip\.dataset\.g/);
  assert.match(desk, /m\.onclick = ev => \{ if \(ev\.target\.closest\("\[data-chip-special\]"\)\) return;/);
  assert.match(desk, /function chipSpecialIO\(m\) \{[\s\S]{0,900}progress: jobs => \{ Promise\.resolve\(processPopupSync\(jobs\)\)/);
  assert.match(desk, /async function specialBuildLaunch\(gid, x\) \{[\s\S]{0,400}modsGalleryPlay\(m,/);
  assert.match(gallery, /function focus\(\{ q, game \} = \{\}\)/);
});

test('#1656 wiring: the launch screen and the Mini window name a renamed build; the chip menu passes PATCH / PUT', () => {
  const read = f => fs.readFileSync(path.join(__dirname, '..', 'clients', f), 'utf8');
  const web = read('web/index.html'), desk = read('desktop/index.html');
  assert.match(web, /label: x\.build\?\.mod_title \|\| x\.build\?\.label \|\| "" \}\)/, 'Special builds / Builds launches carry the build name');
  assert.match(web, /loader\.show\(boot\.label \? `\$\{g\.title\} · \$\{boot\.label\}` : g\.title,/);
  assert.match(desk, /const sessionTitle = s => s \? \(s\.mod_title \? `\$\{s\.title \|\| s\.game_id \|\| "game"\} · \$\{s\.mod_title\}`/);
  assert.match(desk, /sid = s\.session_id; title = sessionTitle\(s\);/);
  assert.match(desk, /title = s \? sessionTitle\(s\) : "";\r?\n\s*\}\r?\n\s*miniPadTarget\(sid\);\r?\n\s*gbox\.miniOpen\(sid, title\);/);
  assert.match(desk, /function chipSpecialIO\(m\) \{\r?\n\s*const api = async \(path, body, method\) => \{ const r = await gbox\.api\(path, body, method\);/);
  for (const f of [web, desk]) assert.ok(!/[^\r]\n/.test(f), 'CRLF line endings kept');
});
