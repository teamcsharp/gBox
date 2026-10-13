// #1562 "right click menu never comes up": the library's game menu (clients/web/viz/game-menu.js) opens in the frame of
// the right-click from what the client already has, whatever the server does (hangs, rejects, throws, answers late);
// a section that throws can't keep it closed; an older right-click's answer can't overwrite a newer menu; it is placed
// inside the window. Plus the wiring in both clients.
const { test, beforeEach } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const GM = require('../clients/web/viz/game-menu.js');

const GID = 'zelda-oot';
// a #gmenu stand-in: innerHTML as a string, sections addressable by [data-gm="name"] (the controller swaps one in place)
function fakeMenu() {
  const el = { html: '', writes: 0, classes: new Set(), style: {},
    get innerHTML() { return this.html; }, set innerHTML(v) { this.html = v; this.writes++; },
    classList: { add: c => el.classes.add(c), remove: c => el.classes.delete(c), contains: c => el.classes.has(c) },
    querySelector(sel) {
      const m = /^\[data-gm="(\w+)"\]$/.exec(sel); if (!m) return null;
      const start = el.html.indexOf(`<div data-gm="${m[1]}">`); if (start < 0) return null;
      const next = el.html.indexOf('<div data-gm="', start + 1), end = next < 0 ? el.html.length : next;
      return { set outerHTML(v) { el.html = el.html.slice(0, start) + v + el.html.slice(end); el.writes++; } };
    },
    querySelectorAll: () => [] };
  return el;
}
function fakeIo(api, extra = {}) {
  const calls = { api: [], place: [], play: [], cast: [], models: [], refit: 0 };
  const boots = {};
  const io = { el: fakeMenu(), img: u => u + '?token=t', worker: 'i9-NUC',
    api: (p, body) => { calls.api.push(p); return api(p, body); },
    boot: { get: gid => ({ disc: '', slot: '', character: '', ...(boots[gid] || {}) }), set: (gid, b) => { boots[gid] = b; } },
    keep: { get: () => [], set() {} }, badge() {},
    place: (el, x, y) => calls.place.push([x, y, el.classes.has('on')]), refit: () => { calls.refit++; },
    models: (...a) => calls.models.push(a), cover() {}, cast: (...a) => calls.cast.push(a), play: (...a) => calls.play.push(a), ...extra };
  return { io, calls, boots };
}
const visible = el => el.classes.has('on') && /data-go=""/.test(el.html);
const hang = () => new Promise(() => {});
const CHARS = [
  { slug: 'link_adult', name: 'Adult Link', preview_url: '/api/characters/link_adult/preview', targets: { [GID]: [{ mod: 'cm_link', slot: 'player' }] } },
  { slug: 'kane', name: 'Kane', source: { game_title: 'SmackDown! 2' }, targets: {} },
  { slug: 'kane_alt', name: 'Kane (alt)', variant_of: 'kane', targets: {} },
  { slug: 'stale', name: 'Stale', targets: { [GID]: [{ mod: 'old', needs_rebuild: true }] } },
];
const MODS = [{ id: 'm1', title: 'Moon Jump', calls: [{ tool: 'poke' }] }, { id: 'm2', title: 'Hard Mode disc', calls: [{ tool: '@launch', input: { mod: 'hard_disc' } }] }];
const answer = p => p.startsWith('/api/characters') ? CHARS : p.startsWith('/api/mods') ? MODS : {};

beforeEach(() => GM._reset());

test('right-click shows the whole menu synchronously while every fetch hangs (< 50 ms), placed at the pointer', () => {
  const { io, calls } = fakeIo(hang);
  const t0 = performance.now();
  const m = GM.open(io, { gid: GID, title: 'Legend of Zelda, The: Ocarina of Time (USA)', x: 700, y: 820 });
  const ms = performance.now() - t0;
  assert.ok(visible(io.el), 'menu on with its Play button in the same call');
  assert.ok(ms < 50, `opened in ${ms.toFixed(2)} ms`);
  for (const k of ['data-models', 'data-cover', 'data-cast', 'id="gmcollect"', 'id="gmslot"', 'data-go="plain"', 'data-go="linux"'])
    assert.ok(io.el.html.includes(k), k);
  assert.match(io.el.html, /data-gm-loading="chars"[^>]*>loading characters…/);
  assert.match(io.el.html, /data-gm-loading="mods">loading mods…/);
  assert.deepEqual(calls.place, [[700, 820, true]], 'placed once, after it is on (so it can be measured)');
  assert.ok(m.state.errors.length === 0);
});

test('fetches that reject (Spark restarting) or throw synchronously: the menu is already up, the sections say why + Retry', async () => {
  for (const api of [() => Promise.reject(new Error('gBox server unreachable: Failed to fetch')), () => { throw new Error('boom'); }]) {
    GM._reset();
    const { io } = fakeIo(api);
    const m = GM.open(io, { gid: GID, title: 'Zelda', x: 10, y: 10 });
    assert.ok(visible(io.el));
    await m.settled;
    assert.match(io.el.html, /Characters didn&#39;t load: [^<]*(unreachable|boom)[^<]*<button class="act" type="button" data-gm-retry="chars"/);
    assert.match(io.el.html, /Mods didn&#39;t load: [^<]*(unreachable|boom)[^<]*<button class="act" type="button" data-gm-retry="mods"/);
    assert.ok(visible(io.el), 'Play still there');
  }
});

test('a read that never answers turns into "did not answer" instead of "loading…" forever', async () => {
  const { io } = fakeIo(hang, { charsTimeout: 15, modsTimeout: 15 });
  const m = GM.open(io, { gid: GID, title: 'Zelda' });
  await m.settled;
  assert.match(io.el.html, /The character library did not answer in 0 s/);
  assert.match(io.el.html, /This game&#39;s mods did not answer in 0 s/);
  assert.ok(!io.el.html.includes('loading characters…'));
});

test('answers fill the sections in place: ready characters, the build list (no variants), boot mods, switches', async () => {
  const { io, calls } = fakeIo(async p => answer(p));
  const m = GM.open(io, { gid: GID, title: 'Zelda' });
  const writes = io.el.writes;
  await m.settled;
  assert.ok(io.el.writes > writes, 'sections repainted');
  assert.match(io.el.html, /value="link_adult" data-disc="cm_link" data-character-slot="player" >.*src="\/api\/characters\/link_adult\/preview\?token=t"/);
  assert.match(io.el.html, /<option value="kane">Kane · SmackDown! 2<\/option>/);
  assert.ok(!io.el.html.includes('value="kane_alt"') && !io.el.html.includes('value="stale" data-disc'), 'variants / needs_rebuild targets left out');
  assert.match(io.el.html, /name="gmd" value="hard_disc" > Hard Mode disc/);
  assert.match(io.el.html, /data-keep="m1" > Moon Jump/);
  assert.ok(!/loading (characters|mods)/.test(io.el.html));
  assert.ok(calls.refit > 0, 'refit after the content grew');
  assert.deepEqual(calls.api.sort(), ['/api/characters', `/api/mods?game_id=${GID}`]);
});

test('the next right-click renders the cached library and mods at once (no "loading"), revalidating only when stale', async () => {
  const first = fakeIo(async p => answer(p));
  await GM.open(first.io, { gid: GID, title: 'Zelda' }).settled;
  const { io, calls } = fakeIo(hang);
  GM.open(io, { gid: GID, title: 'Zelda' });
  assert.match(io.el.html, /Adult Link/); assert.match(io.el.html, /Hard Mode disc/);
  assert.ok(!/loading (characters|mods)/.test(io.el.html));
  assert.deepEqual(calls.api, [], 'fresh cache: nothing fetched');
});

test('the library prefetch warms the cache the menu reads', async () => {
  const { io } = fakeIo(async p => answer(p));
  await GM.prefetch(io);
  const second = fakeIo(hang);
  GM.open(second.io, { gid: GID, title: 'Zelda' });
  assert.match(second.io.el.html, /Adult Link/);
});

test('a section builder that throws (or bad data) never blocks the menu: that section says so, Play still opens', async () => {
  const orig = GM.SECTIONS.chars;
  GM.SECTIONS.chars = () => { throw new Error('preview_url of undefined'); };
  try {
    const { io } = fakeIo(hang);
    const m = GM.open(io, { gid: GID, title: 'Zelda' });
    assert.ok(visible(io.el));
    assert.match(io.el.html, /data-gm-broken="chars"[^>]*>Play as could not be shown: preview_url of undefined/);
    assert.deepEqual(m.state.errors.map(e => e.section), ['chars']);
  } finally { GM.SECTIONS.chars = orig; }
  GM._reset();
  const { io } = fakeIo(async p => p.startsWith('/api/characters') ? [null, { slug: 'x' }] : [{ calls: null }, 7]);
  const m = GM.open(io, { gid: GID, title: 'Zelda' });
  await m.settled;
  assert.ok(visible(io.el), 'malformed answers: the menu stays usable');
});

test('a boot or keep store that throws still opens the menu', () => {
  const { io } = fakeIo(hang, { boot: { get() { throw new Error('localStorage blocked'); }, set() {} }, keep: { get() { throw new Error('x'); }, set() {} } });
  GM.open(io, { gid: GID, title: 'Zelda' });
  assert.ok(visible(io.el));
});

test('an older right-click answering late cannot overwrite the newer menu (no stale closures)', async () => {
  let resolveA;
  const { io } = fakeIo(p => p.includes('game_id=A') ? new Promise(r => { resolveA = r; }) : hang());
  const a = GM.open(io, { gid: 'A', title: 'Game A' });
  GM.open(io, { gid: 'B', title: 'Game B' });
  resolveA([{ id: 'ma', title: 'A only mod', calls: [{ tool: '@launch', input: { mod: 'a_disc' } }] }]);
  for (let i = 0; i < 3; i++) await new Promise(r => setTimeout(r, 0));
  assert.equal(a.state.mods.length, 1, 'A got its answer');
  assert.match(io.el.html, /<h4>Game B<\/h4>/);
  assert.ok(!io.el.html.includes('A only mod'));
  // and its click handlers act on B
  io.el.onclick({ target: { closest: s => s === '[data-go]' ? { dataset: { go: '' } } : null } });
});

test('Play / Play original / Play on Spark / cast work before anything loaded', () => {
  const { io, calls } = fakeIo(hang);
  GM.open(io, { gid: GID, title: 'Zelda' });
  const click = sel => io.el.onclick({ target: { closest: s => s === sel ? { dataset: sel === '[data-go]' ? { go: 'plain' } : {} } : null } });
  click('[data-go]');
  assert.deepEqual(calls.play, [[GID, 'plain']]); assert.ok(!io.el.classes.has('on'), 'closes');
  GM.open(io, { gid: GID, title: 'Zelda' }); click('[data-cast]');
  assert.deepEqual(calls.cast, [[GID, 'Zelda']]);
});

test('Retry refetches the section that failed', async () => {
  let fail = true;
  const { io } = fakeIo(async p => { if (fail) throw new Error('503'); return answer(p); });
  const m = GM.open(io, { gid: GID, title: 'Zelda' });
  await m.settled; fail = false;
  assert.match(io.el.html, /data-gm-retry="chars"/);
  await io.el.onclick({ target: { closest: s => s === '[data-gm-retry]' ? { dataset: { gmRetry: 'chars' } } : null } });
  await new Promise(r => setTimeout(r, 0)); await new Promise(r => setTimeout(r, 0));
  assert.match(io.el.html, /Adult Link/);
});

test('placement keeps the menu inside the window: flips above the pointer, clamps to the edges, scrolls when too tall', () => {
  const inside = (f, w, h, vw, vh) => f.left >= 0 && f.top >= 0 && f.left + w <= vw && f.top + Math.min(h, f.maxHeight ?? h) <= vh;
  const vw = 1500, vh = 950;
  for (const [x, y, w, h] of [[10, 10, 340, 600], [1490, 940, 340, 600], [700, 820, 340, 760], [1400, 100, 340, 200], [0, 949, 340, 2000], [-50, -50, 340, 300]]) {
    const f = GM.fit(x, y, w, h, vw, vh, 8, 8);
    assert.ok(inside(f, w, h, vw, vh), JSON.stringify({ x, y, w, h, f }));
  }
  assert.deepEqual(GM.fit(700, 820, 340, 600, vw, vh), { left: 700, top: 220, maxHeight: null }, 'bottom row: opens above the pointer');
  assert.equal(GM.fit(0, 949, 340, 2000, vw, vh).maxHeight, 934, 'taller than the window: scrolls inside');
  assert.ok(GM.fit(0, 0, 340, 300, 1500, 30, 8, 40).maxHeight >= 40, 'a tiny window never gets a negative max-height');
});

test('wiring: both clients load the module; the card handler opens it without awaiting anything; re-fit works for fixed menus', () => {
  const read = f => fs.readFileSync(path.join(__dirname, '..', 'clients', f), 'utf8');
  const web = read('web/index.html'), desk = read('desktop/index.html');
  assert.match(web, /<script src="\/viz\/game-menu.js"><\/script>/);
  assert.match(desk, /<script src="\.\.\/web\/viz\/game-menu.js"><\/script>/);
  const handler = web.match(/document\.addEventListener\("contextmenu", (async )?e => \{\s*const c = e\.target\.closest\("\.card\[data-gid\]"\)[\s\S]*?\n\}\);/);
  assert.ok(handler, 'card handler found');
  assert.ok(!handler[1] && !/await|api\(/.test(handler[0]), 'synchronous: no fetch before the menu shows');
  assert.match(handler[0], /e\.preventDefault\(\);\s*GBoxGameMenu\.open\(gameMenuIO\(\)/);
  assert.match(web, /library\.after = \(\) => \{\s*GBoxGameMenu\.prefetch\(gameMenuIO\(\)\)/);
  for (const src of [web, desk]) {
    assert.ok(!/offsetParent !== null\) refitMenu/.test(src), 'offsetParent is null for position:fixed: the re-fit never ran');
    assert.match(src, /el\._fitXY && el\.getClientRects\(\)\.length\) refitMenu\(el\)/);
    assert.match(src, /function refitMenu\(el\) \{[\s\S]{0,200}GBoxGameMenu\.fit\(/);
  }
  assert.match(web, /m\.id = "issuemenu"; m\.setAttribute\("role", "menu"\)/, '"Request about…" is cut out of a docked game like the other guest menus');
  assert.match(desk, /EMB_GUEST_MENUS = "#gmenu, [^"]*\[role=menu\]/);
});
