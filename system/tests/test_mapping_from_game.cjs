// "Fix this character's mapping" from gameplay: the pick whip's menu item (clients/web/viz/pick-whip.js) resolves the
// donor standing in the picked slot of the session's build and opens the Retarget editor straight in the Goals view
// (flagged, game kept paused), else the donor browser; the editor's flips (clients/web/viz/retarget-editor.js +
// retarget-handles.js): Swap left <-> right (role overrides) and Turn around (profile.turn), the overlay and captions.
const assert = require('node:assert/strict');
const { test } = require('node:test');
const PW = require('../clients/web/viz/pick-whip.js');
const E = require('../clients/web/viz/retarget-editor.js');
const H = require('../clients/web/viz/retarget-handles.js');

// ---- retarget-handles: the flips' maths ----------------------------------------------------------------------------
test('Turn around: a profile flag, not identity, turning the fit frame 180 degrees about up', () => {
  assert.equal(H.normalize({ turn: true }).turn, true);
  assert.equal(H.normalize({ turn: 'yes' }).turn, undefined);           // only a real true, like the server
  assert.equal(H.isIdentity({ turn: true }), false);
  const R = H.facing(H.standardSkeleton(1.7));
  assert.deepEqual(H.turnFrame(R, {}), R);
  assert.deepEqual(H.turnFrame(R, { turn: true }).map(r => r.map(x => x + 0)), [[-1, 0, 0], [0, 1, 0], [0, 0, -1]]);
});

test('Swap left <-> right: every l_ role takes its r_ twin\'s bone; the overrides carry it to the build', () => {
  const base = { hip: 'pelvis', head: 'head', l_upper: 'armL', r_upper: 'armR', l_fore: 'foreL', r_fore: 'foreR', l_hand: 'handL' };
  const swapped = H.swapSides(base);
  assert.deepEqual(swapped, { hip: 'pelvis', head: 'head', r_upper: 'armL', l_upper: 'armR', r_fore: 'foreL', l_fore: 'foreR', r_hand: 'handL' });
  assert.deepEqual(H.swapSides(swapped), base);                          // twice is the original
  const over = H.roleOverrides(base, swapped);
  assert.deepEqual(over, { l_upper: 'armR', l_fore: 'foreR', l_hand: '', r_upper: 'armL', r_fore: 'foreL', r_hand: 'handL' });
  assert.deepEqual(H.applyOverrides(base, over), swapped);                // what apply_to_meta does on the server
  // a rig named from the viewer's side faces backwards; swapping its sides turns its facing around
  const P = H.standardSkeleton(1.7), named = {};
  for (const [r, p] of Object.entries(P)) named[r.replace(/^l_/, 'R_').replace(/^r_/, 'l_').replace(/^R_/, 'r_')] = p;
  const back = H.facing(named), fixed = H.facing(Object.fromEntries(Object.entries(H.swapSides(Object.fromEntries(Object.keys(named).map(r => [r, r]))))
    .map(([role, bone]) => [role, named[bone]])));
  assert.deepEqual(back[2].map(x => x + 0), [0, 0, -1]); assert.deepEqual(fixed[2].map(x => x + 0), [0, 0, 1]);
});

test('Swap left <-> right: joint moves follow their bone (x, z flip with the frame), shoe tops keep their side', () => {
  const p = H.swapProfileSides({ joints: { l_fore: [0.02, -0.03, 0.01], head: [0, 0.01, 0] }, shoe_tops: { l: 0.2 },
    lattice: { offsets: { 0: [0.01, 0.02, 0.03] } }, adjust: { l_fore: { length: 1.2 } }, turn: true });
  assert.deepEqual(p.joints, { r_fore: [-0.02, -0.03, -0.01], head: [0, 0.01, 0] });
  assert.deepEqual(p.shoe_tops, { r: 0.2 });
  assert.deepEqual(p.lattice.offsets, { 20: [-0.01, 0.02, -0.03] });   // (0,0,0) -> (2,0,2)
  assert.equal(p.adjust.l_fore.length, 1.2); assert.equal(p.turn, true); // target-space edits stay with their role
});

// ---- the editor controller: flips, flags, captions ----------------------------------------------------------------
const VIEW = { slug: 'luigi', name: 'Luigi', rig_roles: { hip: 'pelvis', head: 'head', l_upper: 'armL', r_upper: 'armR' },
  model_url: '/m.glb', profile: null, game_wide: null, resolved: { roles: {} },
  flagged: [{ at: 1760000000, session_id: 'w1-s1', note: 'Luigi looked mapped wrong in fighter:KAS' }] };
function fakeIo() {
  const parts = {}, statuses = [], calls = [];
  const io = { api: async (p, body) => {
    calls.push([p, body]);
    if (p.startsWith('/api/characters/luigi/retarget_profile')) return body ? Object.assign({}, VIEW, { profile: body.profile, flagged: [] }) : VIEW;
    if (p.startsWith('/api/cast_swap/sources')) return { slots: [{ slot: 'fighter:KAS', name: 'Kasumi' }] };
    return null;
  }, render: (part, html) => { parts[part] = html; }, status: t => statuses.push(t) };
  return { io, parts, statuses, calls };
}

test('editor: flagged from gameplay until saved; Swap and Turn save as role overrides and profile.turn', async () => {
  const x = fakeIo(), c = E.controller(x.io, { slug: 'luigi', gid: '0123456789abcdef', title: 'DOA2', slot: 'fighter:KAS', flagged: true });
  await c.load();
  assert.match(x.parts.header, /⚑ Flagged from gameplay: Luigi looked mapped wrong in fighter:KAS/);
  assert.match(x.parts.tabs, /data-rt-go="swap-lr" title="[^"]*fixes a body that faces backwards or arms that bend the wrong way"/);
  assert.match(x.parts.tabs, /data-rt-go="turn"/); assert.match(x.parts.tabs, /data-rt-overlay/);
  c.swapSides();
  assert.deepEqual(c.state.roles, { hip: 'pelvis', head: 'head', l_upper: 'armR', r_upper: 'armL' });
  c.setTurn(true);
  assert.match(x.parts.tabs, /aria-pressed="true"[^>]*>↻ Turn around · on/);
  const body = c.payload('slot');
  assert.deepEqual(body.profile.roles, { l_upper: 'armR', r_upper: 'armL' }); assert.equal(body.profile.turn, true);
  await c.save('slot');
  assert.doesNotMatch(x.parts.header, /Flagged from gameplay/);         // the server cleared it with the save
  c.setOverlay(0.02); assert.equal(c.state.overlay, 0.1); c.setOverlay(0.5); assert.equal(c.state.overlay, 0.5);
});

test('editor: a flag post that failed still says it was opened from gameplay; captions name both sides', async () => {
  const x = fakeIo(); VIEW.flagged = [];
  const c = E.controller(x.io, { slug: 'luigi', gid: 'g', title: 'DOA2', slot: 'fighter:KAS', flagged: true });
  await c.load();
  assert.match(x.parts.header, /Flagged from gameplay/);
  const cap = E.captionsFor(c.state);
  assert.equal(cap.donor[0], 'Donor: Luigi'); assert.match(cap.donor[1], /drag the circles/);
  assert.equal(cap.target[0], 'In game: Kasumi with Luigi fitted over it');
  c.setTpose(false); assert.match(E.captionsFor(c.state).target[1], /over the original/);
  c.setMode('fit'); assert.equal(E.captionsFor(c.state).target[0], 'In game: Kasumi with Luigi fitted over it');
});

// ---- the pick whip: "Fix this character's mapping" ----------------------------------------------------------------
test('menu: Fix this character\'s mapping sits right under Report…', () => {
  const ids = PW.menuItems().map(i => i.id);
  assert.deepEqual(ids.slice(0, 2), ['report', 'fixmap']);
  const it = PW.menuItems()[1];
  assert.equal(it.icon, '✎'); assert.equal(it.text, 'Fix this character\'s mapping…'); assert.equal(it.hint, 'mapped wrong? adjust it');
});

const ROWS = [{ slot: 'fighter:KAS', slot_name: 'Kasumi', donor: 'luigi', donor_name: 'Luigi' },
  { slot: 'fighter:RYU', slot_name: 'Ryu Hayabusa', donor: 'wario', donor_name: 'Wario' }];
test('castMatch: the picked slot, else the pick named as a donor or a slot, else the only replaced slot', () => {
  assert.equal(PW.castMatch(ROWS, { slot: 'fighter:KAS:all' }).donor, 'luigi');
  assert.equal(PW.castMatch(ROWS, { slot: 'RYU' }).donor, 'wario');
  assert.equal(PW.castMatch(ROWS, { slot: '', name: 'Wario', known: true }).slot, 'fighter:RYU');
  assert.equal(PW.castMatch(ROWS, { slot: '', model: 'luigi' }).slot, 'fighter:KAS');
  assert.equal(PW.castMatch(ROWS, { slot: '', name: 'something' }, { collection: { slug: 'wario' } }).donor, 'wario');
  assert.equal(PW.castMatch(ROWS, { slot: '', name: 'Kasumi', known: true }).donor, 'luigi');
  assert.equal(PW.castMatch(ROWS, { slot: 'fighter:AYA' }), null);       // a stock slot: ask
  assert.equal(PW.castMatch(ROWS, { slot: '' }), null);                  // two slots, nothing to tell them apart
  assert.equal(PW.castMatch([ROWS[0]], { slot: '' }).via, 'the build\'s only replaced slot');
  assert.equal(PW.castMatch([ROWS[0]], { slot: 'player' }), null);
  assert.equal(PW.castMatch([], { slot: 'fighter:KAS' }), null); assert.equal(PW.castMatch(null, {}), null);
});

// a fake DOM + control plane, just enough for the menu and the browser
class El {
  constructor(tag, doc) { this.tagName = tag; this.doc = doc; this.style = {}; this.dataset = {}; this.children = []; this.kids = {};
    this.className = ''; this._html = ''; this.textContent = ''; this.attrs = {};
    this.classList = { add() {}, remove() {}, toggle() {}, contains: () => false }; }
  set id(v) { this._id = v; this.doc.ids[v] = this; } get id() { return this._id; }
  set innerHTML(v) { this._html = v; this.kids = {}; } get innerHTML() { return this._html; }
  append(...c) { for (const x of c) { this.children.push(x); if (x._id) this.doc.ids[x._id] = x; } }
  remove() { if (this._id && this.doc.ids[this._id] === this) delete this.doc.ids[this._id]; }
  setAttribute(k, v) { this.attrs[k] = v; } getAttribute(k) { return this.attrs[k] ?? null; } addEventListener(t, f) { (this.on ||= {})[t] = f; } focus() {}
  querySelector(sel) { return this.kids[sel] || (this.kids[sel] = new El(sel, this.doc)); }
  contains(x) { return x === this; } getBoundingClientRect() { return { left: 0, top: 0, width: 100, height: 100 }; }
}
function fakeDoc() {
  const doc = { ids: {}, listeners: {} };
  doc.createElement = t => new El(t, doc); doc.getElementById = id => doc.ids[id] || null;
  doc.head = new El('head', doc); doc.body = new El('body', doc);
  doc.addEventListener = (t, f) => (doc.listeners[t] ||= []).push(f);
  doc.removeEventListener = (t, f) => { doc.listeners[t] = (doc.listeners[t] || []).filter(x => x !== f); };
  doc.defaultView = { innerWidth: 1600, innerHeight: 900, requestAnimationFrame: () => 0, cancelAnimationFrame() {}, addEventListener() {} };
  return doc;
}
const tick = async (n = 8) => { for (let i = 0; i < n; i++) await new Promise(r => setTimeout(r, 0)); };
function menu(preview, routes) {
  const doc = fakeDoc(), calls = [], seen = { retarget: [], closed: [] };
  const api = async (path, body) => {
    calls.push({ path, body });
    if (path === '/api/jobs') return { id: 'j1', state: 'succeeded', output: { result: preview } };
    if (path.startsWith('/api/jobs/')) return { id: 'j1', state: 'succeeded', output: { result: preview } };
    const r = routes[path]; if (r === undefined) throw new Error('404 not found ' + path);
    return typeof r === 'function' ? r(body) : r;
  };
  const store = new Map();
  globalThis.localStorage = { getItem: k => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) };
  const io = { api, sleep: async () => {}, img: c => '/p/' + c.slug, toast() {}, place() {},
    retarget: async o => { seen.retarget.push(o); seen.order = calls.length; return { el: {}, dispose() {} }; } };
  const m = PW.characterMenu(doc, io, { sid: 'w1-s1', at: [0.5, 0.25], aspect: 4 / 3, x: 100, y: 100, gid: '0123456789abcdef',
    anchor: [10, 10], onClose: why => seen.closed.push(why) });
  return { doc, calls, seen, menu: m };
}

test('fix mapping: the donor in the picked slot opens straight in the Goals view, flagged, the game held paused', async () => {
  const held = [];
  const fx = menu({ picked: { class: 'fighter', kind: 'player', slot: 'fighter:KAS' } }, {
    '/api/sessions/w1-s1/cast': { session_id: 'w1-s1', game_id: '0123456789abcdef', mod: 'doa2_sonic_cast', rows: ROWS },
    '/api/characters/luigi/retarget_profile/flag': b => ({ flagged: [b] }),
    '/api/pickwhip/w1-s1/hold': b => { held.push(b.op); return { owned: true, paused: true }; } });
  await tick();
  await fx.menu.onPick('fixmap'); await tick();
  const o = fx.seen.retarget[0];
  assert.deepEqual({ slug: o.slug, name: o.name, gid: o.gid, slot: o.slot, view: o.view, flagged: o.flagged, build_name: o.build_name },
    { slug: 'luigi', name: 'Luigi', gid: '0123456789abcdef', slot: 'fighter:KAS', view: 'goals', flagged: true, build_name: 'doa2_sonic_cast' });
  assert.ok(!fx.calls.some(c => c.path.startsWith('/api/characters?')), 'no donor browser');
  const flag = fx.calls.find(c => c.path === '/api/characters/luigi/retarget_profile/flag').body;
  assert.equal(flag.game_id, '0123456789abcdef'); assert.equal(flag.slot, 'fighter:KAS'); assert.equal(flag.session_id, 'w1-s1');
  assert.match(flag.note, /looked mapped wrong in fighter:KAS \(picked at 50% across, 25% down\)/);
  assert.deepEqual(fx.seen.closed, ['mapping']);
  assert.deepEqual(held, ['pause']);                                      // paused before the menu let go of its own hold
  o.onClose(); await tick();                                             // the editor closed: the game resumes
  assert.deepEqual(held, ['pause', 'release']);
});

test('fix mapping: a slot the build did not replace asks for the donor first, then opens flagged', async () => {
  const fx = menu({ picked: { class: 'fighter', kind: 'player', slot: 'fighter:AYA' } }, {
    '/api/sessions/w1-s1/cast': { game_id: '0123456789abcdef', mod: 'doa2_sonic_cast', rows: ROWS },
    '/api/characters?game_id=0123456789abcdef': [{ slug: 'peach', name: 'Peach', model: 'p', kind: 'character' }],
    '/api/characters/peach/retarget_profile/flag': {} });
  await tick();
  await fx.menu.onPick('fixmap'); await tick();
  const m = fx.doc.getElementById('pwmenu');
  assert.match(m.querySelector('.pw-grid').innerHTML, /Peach/);
  assert.equal(fx.seen.retarget.length, 0);
  m.onclick({ target: { closest: () => ({ dataset: { slug: 'peach' }, disabled: false }) } }); await tick();
  const o = fx.seen.retarget[0];
  assert.equal(o.slug, 'peach'); assert.equal(o.slot, 'fighter:AYA'); assert.equal(o.flagged, true); assert.equal(o.view, 'goals');
  assert.deepEqual(fx.seen.closed, ['mapping']);
});

test('fix mapping: the original game (no build, no cast route) falls back to the donor browser', async () => {
  const fx = menu({ picked: { class: 'pl0000', kind: 'player' } }, { '/api/characters?game_id=0123456789abcdef': [] });
  await tick();
  await fx.menu.onPick('fixmap'); await tick();
  assert.match(fx.doc.getElementById('pwmenu').innerHTML, /Fix the mapping in this slot: which donor\?/);
  assert.equal(fx.seen.retarget.length, 0);
});

test('fix mapping and the web / desktop shells: both route io.retarget into the shared editor with the options', () => {
  const fs = require('node:fs'), path = require('node:path');
  const read = f => fs.readFileSync(path.join(__dirname, '..', 'clients', f), 'utf8');
  assert.match(read('web/index.html'), /retarget: o => \/\^\[0-9a-f\]\{16\}\$\/\.test\(o\.gid \|\| ""\) \? retargetOpen\(\{ \.\.\.o, title/);
  assert.match(read('desktop/index.html'), /retarget: o => \/\^\[0-9a-f\]\{16\}\$\/\.test\(o\.gid \|\| ""\) \? retargetOpen\(\{ \.\.\.o, title/);
  assert.match(read('web/index.html'), /GBoxRetargetEditor\.open\(document, \{[\s\S]{0,400}\}, o\)/);   // opts (onClose, view, flagged) pass through
  assert.match(read('desktop/index.html'), /GBoxRetargetEditor\.open\(document, \{[\s\S]{0,600}\}, o\)/);
});

test('castMatch: a costume slot is its fighter; a slot two donors share needs the donor named', () => {
  const sc2 = [{ slot: 'fighter:taki', slot_name: 'Taki', donor: 'luigi', donor_name: 'Luigi' },
    { slot: 'fighter:taki', slot_name: 'Taki', donor: 'wario', donor_name: 'Wario' },
    { slot: 'fighter:maxi', slot_name: 'Maxi', donor: 'wario', donor_name: 'Wario' }];
  assert.equal(PW.castMatch(sc2, { slot: 'fighter:maxi:2' }).donor, 'wario');
  assert.equal(PW.castMatch(sc2, { slot: 'fighter:taki:1' }), null);                      // Luigi or Wario?
  assert.deepEqual(PW.castCandidates(sc2, { slot: 'fighter:taki:1' }).map(r => r.donor), ['luigi', 'wario']);
  assert.equal(PW.castMatch(sc2, { slot: 'taki', name: 'Wario', known: true }).via, 'slot and donor');
  assert.equal(PW.castMatch(sc2, { slot: '', name: 'Wario', known: true }), null);        // Wario stands in two slots
  assert.equal(PW.castMatch(sc2, { slot: '', name: 'Luigi', known: true }).slot, 'fighter:taki');
});

test('fix mapping: a slot several donors share lists them first in the browser and opens the canonical slot', async () => {
  const rows = [{ slot: 'fighter:taki', slot_name: 'Taki', donor: 'luigi', donor_name: 'Luigi' },
    { slot: 'fighter:taki', slot_name: 'Taki', donor: 'wario', donor_name: 'Wario' }];
  const fx = menu({ picked: { class: 'fighter', kind: 'player', slot: 'fighter:taki:2' } }, {
    '/api/sessions/w1-s1/cast': { game_id: '0123456789abcdef', mod: 'sc2_random', rows },
    '/api/characters?game_id=0123456789abcdef': [{ slug: 'amy', name: 'Amy', model: 'a', kind: 'character', ready: [{ mod: 'x' }] },
      { slug: 'wario', name: 'Wario', model: 'w', kind: 'character' }, { slug: 'luigi', name: 'Luigi', model: 'l', kind: 'character' }],
    '/api/characters/wario/retarget_profile/flag': {} });
  await tick();
  await fx.menu.onPick('fixmap'); await tick();
  const grid = fx.doc.getElementById('pwmenu').querySelector('.pw-grid').innerHTML;
  assert.ok(grid.indexOf('Luigi') < grid.indexOf('Amy') && grid.indexOf('Wario') < grid.indexOf('Amy'), grid);
  assert.match(grid, /in this slot of the build/);
  fx.doc.getElementById('pwmenu').onclick({ target: { closest: () => ({ dataset: { slug: 'wario' }, disabled: false }) } }); await tick();
  assert.equal(fx.seen.retarget[0].slot, 'fighter:taki');                  // where the SC2 writer reads its profile
  assert.equal(fx.seen.retarget[0].build_name, 'sc2_random');
});
