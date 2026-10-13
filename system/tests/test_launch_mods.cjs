// Launch screen mods (clients/web/viz/launch-mods.js, mounted on the web shell's #loader, which the desktop app shows):
// a modded launch shows what it replaces (marquee + slides) and what is on; a stock launch shows nothing.
// Fixture data: tests/fixtures/ui_evidence/launch_mods.json (the same data the PR screenshots render).
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const factory = require('../clients/web/viz/launch-mods.js');

const NOW = 1_800_000_000;
const withNow = v => typeof v === 'string' && /^\$now([+-]\d+)?$/.test(v) ? NOW + Number(v.slice(4) || 0)
  : Array.isArray(v) ? v.map(withNow) : v && typeof v === 'object' ? Object.fromEntries(Object.entries(v).map(([k, x]) => [k, withNow(x)])) : v;
const FX = withNow(JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'ui_evidence', 'launch_mods.json'), 'utf8')).routes);
const DETAILS = FX['/api/builds/doa2/doa2_sonic_cast/details'];
const BUILT = FX['/api/mods/built'];
const CARDS = FX['/api/mods'];
const LM = factory({});

// ---------- a small DOM: the loader host, the layer and its two slide slots ----------
function fakeDom() {
  const made = [];
  class El {
    constructor(tag) { this.tagName = tag.toUpperCase(); this.children = []; this.parentNode = null; this.dataset = {}; this.attrs = {};
      this._html = ''; this.slots = {}; this.hidden = false; this.className = ''; made.push(this); }
    setAttribute(k, v) { this.attrs[k] = String(v); }
    appendChild(c) { c.parentNode = this; this.children.push(c); return c; }
    insertBefore(c, ref) { c.parentNode = this; const i = ref ? this.children.indexOf(ref) : -1; i < 0 ? this.children.push(c) : this.children.splice(i, 0, c); return c; }
    get nextSibling() { const sib = this.parentNode ? this.parentNode.children : []; return sib[sib.indexOf(this) + 1] || null; }
    get innerHTML() { return this._html; }
    set innerHTML(v) { this._html = String(v); this.slots = {}; }
    querySelector(sel) {
      if (sel === 'canvas') return this.children.find(c => c.tagName === 'CANVAS') || null;
      const m = /^\.lm-(l|r)$/.exec(sel);
      if (m && this._html.includes(`lm-slot lm-${m[1]}`)) return this.slots[m[1]] ||= { innerHTML: '' };
      return null;
    }
  }
  const byId = new Map();
  const doc = { createElement: t => new El(t), getElementById: id => byId.get(id) || null, head: new El('head') };
  const origAppend = doc.head.appendChild.bind(doc.head);
  doc.head.appendChild = c => { if (c.id) byId.set(c.id, c); return origAppend(c); };
  const host = new El('div'); host.appendChild(new El('canvas')); host.appendChild(new El('div'));
  return { doc, host };
}
function harness({ reduced = false, fetchJson, budgetMs } = {}) {
  const { doc, host } = fakeDom(), timers = [], images = [];
  const env = { document: doc, matchMedia: q => ({ matches: reduced && /reduced-motion/.test(q) }),
    Image: class { constructor() { images.push(this); } } };
  let id = 0;
  const ctl = factory(env).mount(host, { url: u => u + '?token=t', fetchJson, budgetMs, now: () => NOW * 1000,
    setTimeout: (fn, ms) => { timers.push({ fn, ms, id: ++id }); return id; }, clearTimeout: tid => { const i = timers.findIndex(t => t.id === tid); if (i >= 0) timers.splice(i, 1); } });
  const fire = ms => { const t = timers.find(x => x.ms === ms); assert.ok(t, `a timer of ${ms} ms`); timers.splice(timers.indexOf(t), 1); t.fn(); };
  return { ctl, host, doc, timers, images, fire, layer: ctl.el };
}
const answers = (over = {}) => async p => {
  if (p in over) { const v = over[p]; if (v instanceof Error) throw v; return v; }
  if (p.startsWith('/api/builds/doa2/doa2_sonic_cast/details')) return DETAILS;
  if (p.startsWith('/api/mods/built?')) return BUILT;
  throw new Error('404 ' + p);
};
const sessionMods = async () => LM.sessionModsFrom(CARDS, ['m_unlock', 'm_link']);

// ---------------------------------------------------------------- the model
test('the model: display name, slot <- donor pairs with the game\'s own character and the fit preview, counts', () => {
  const m = LM.modelFrom({ gameId: 'doa2', mod: 'doa2_sonic_cast', details: DETAILS, built: BUILT.items[0], now: NOW,
    session: LM.sessionModsFrom(CARDS, ['m_unlock', 'm_link']) });
  assert.equal(m.label, 'Sonic crew in DOA2');
  assert.equal(m.originalTitle, 'doa2 roster: sonic cast');
  assert.equal(m.writer, 'doa2_swap');
  assert.deepEqual(m.kinds, ['cast swap', 'cheats']);
  assert.equal(m.pairs.length, 6);
  const kas = m.pairs[0];
  assert.deepEqual(kas.original, { name: 'Kasumi', img: '/api/characters/doa2_kasumi/preview' });
  assert.deepEqual(kas.donor, { name: 'Amy Rose', img: '/api/jobs/jdoa2/fitting/files/amy-2.png' }, 'the fit preview wins');
  assert.equal(m.pairs[1].donor.img, '/api/characters/sonic/preview', 'else the donor\'s collection preview');
  const ten = m.pairs.find(p => p.slot === 'TEN');
  assert.equal(ten.original, null, 'no original in the library: the slot name stands in');
  assert.deepEqual(m.codes, { cheat: 1, unlock: 1 });
  assert.equal(m.filesCount, 3, 'the built image row is not a changed asset');
  assert.deepEqual(m.files.map(f => f.name), ['KAS_C1.BIN', 'HAY_C1.BIN', 'SELECT.PVR']);
  assert.equal(m.age, 'built 2 h ago');
  assert.equal(m.verified, false);
  assert.equal(m.verifiedText, 'unverified in game until launched');
  assert.equal(m.buildCall, 'characters cast_swap');
  assert.deepEqual(m.session, [{ title: 'Unlock all costumes', kind: 'cheats' }, { title: 'Bullet-cam link', kind: 'game link' }]);
  assert.equal(m.namesOnly, false);
});

test('without the details (index only): pairs from the changes with the donor previews, originals as slot names', () => {
  const m = LM.modelFrom({ gameId: 'doa2', mod: 'doa2_sonic_cast', built: BUILT.items[0], now: NOW });
  assert.equal(m.label, 'Sonic crew in DOA2');
  assert.deepEqual(m.pairs.map(p => `${p.slotName} ← ${p.donor.name}`),
    ['KAS ← Amy Rose', 'HAY ← Sonic', 'RYU ← Shadow', 'BAS ← Knuckles', 'TIN ← Rouge', 'TEN ← Big The Cat']);
  assert.ok(m.pairs.every(p => p.original === null && p.donor.img.startsWith('/api/characters/')));
  assert.equal(m.verifiedText, 'not verified in game yet');
});

test('slot labels: a raw key reads as a name, a short code stays', () => {
  assert.equal(LM.slotLabel('fighter:kasumi'), 'Kasumi');
  assert.equal(LM.slotLabel('KAS', 'KAS'), 'KAS');
  assert.equal(LM.slotLabel('enemy:hildebear', 'Hildebear'), 'Hildebear');
});

test('which launch carries a mod: launch_game and session_swap input.mod; "" is the original game', () => {
  assert.deepEqual(LM.modOfJob({ tool: 'launch_game', input: { game: { game_id: 'doa2' }, mod: 'doa2_sonic_cast' } }), { gameId: 'doa2', mod: 'doa2_sonic_cast' });
  assert.deepEqual(LM.modOfJob({ tool: 'session_swap', input: { game_id: 'doa2', mod: 'x' } }), { gameId: 'doa2', mod: 'x' });
  assert.equal(LM.modOfJob({ tool: 'session_swap', input: { game_id: 'doa2', mod: '' } }), null);
  assert.equal(LM.modOfJob({ tool: 'cheats', input: { mod: 'x' } }), null);
});

// ---------------------------------------------------------------- rendering
test('marquee: [original] -> [replacement] tiles labelled "KAS ← Amy Rose", the original first, text escaped', () => {
  const m = LM.modelFrom({ gameId: 'doa2', mod: 'doa2_sonic_cast', details: DETAILS, built: BUILT.items[0], now: NOW });
  const html = LM.marqueeHTML(m, { mapUrl: u => u + '?token=t' });
  assert.match(html, /KAS ← Amy Rose/);
  assert.match(html, /HAY ← Sonic/);
  const tile = html.slice(html.indexOf('<span class="lm-pair"'), html.indexOf('KAS ← Amy Rose'));
  assert.ok(tile.indexOf('lm-orig') < tile.indexOf('lm-new'), 'original before replacement');
  assert.ok(tile.indexOf('doa2_kasumi/preview?token=t') < tile.indexOf('amy-2.png?token=t'));
  assert.match(html, /KAS_C1\.BIN<\/i><\/span><b class="lm-arrow"[^>]*>→<\/b><span class="lm-th lm-new lm-txt"><i>replaced/, 'changed files follow as text tiles');
  const evil = LM.modelFrom({ mod: 'x', built: { changes: [{ donor: '<img src=x onerror=alert(1)>', slot: 'A"B' }] } });
  assert.ok(!LM.marqueeHTML(evil).includes('<img src=x'));
  assert.ok(!LM.infoHTML(LM.modelFrom({ mod: '<b>m</b>' })).includes('<b>m</b>'));
});

test('direction: the track moves left to right (-50% -> 0) and holds its tiles twice for a seamless loop', () => {
  const m = LM.modelFrom({ mod: 'doa2_sonic_cast', details: DETAILS, now: NOW });
  const html = LM.marqueeHTML(m);
  assert.match(html, /class="lm-track lm-ltr"/);
  assert.match(LM.CSS, /\.lm-track\.lm-ltr \{ animation:lm-ltr /);
  assert.match(LM.CSS, /@keyframes lm-ltr \{ from \{ transform:translateX\(-50%\); \} to \{ transform:translateX\(0\); \} \}/);
  const copy = html.indexOf('<span class="lm-copy" aria-hidden="true">');
  assert.ok(copy > 0);
  assert.equal(html.slice(html.indexOf('lm-ltr') + 1, copy).split('KAS ← Amy Rose').length - 1,
    html.slice(copy).split('KAS ← Amy Rose').length - 1, 'both halves hold the same tiles');
  assert.doesNotMatch(LM.CSS, /\.lm-track \{[^}]*gap:/, 'per-tile margins, no flex gap: the halves are exactly equal');
  const one = LM.marqueeHTML(LM.modelFrom({ mod: 'm', built: { changes: [{ donor: 'amy_rose', slot: 'KAS' }] } }));
  assert.ok(one.split('KAS ← Amy Rose').length - 1 >= 24, 'a short list repeats so a wide band is full');
  assert.match(LM.CSS, /@keyframes lm-fly \{ 0% \{ opacity:0; transform:translateX\(-90px\)[^}]*\}.*100% \{ opacity:0; transform:translateX\(110px\)/s,
    'slides fly in from the left and out to the right, like the marquee');
});

test('the list: name, writer and kind, slots / cheats / unlocks / files, age + verification, build call, session mods', () => {
  const m = LM.modelFrom({ gameId: 'doa2', mod: 'doa2_sonic_cast', details: DETAILS, built: BUILT.items[0], now: NOW,
    session: LM.sessionModsFrom(CARDS, ['m_unlock', 'm_link']) });
  const text = LM.infoLines(m).map(l => l.html.replace(/<[^>]+>/g, ''));
  assert.deepEqual(text, [
    'Sonic crew in DOA2 (doa2 roster: sonic cast) by doa2_swap · cast swap, cheats',
    '6 slots replaced · 1 cheat active · 1 unlock active · 3 files changed',
    'built 2 h ago · unverified in game until launched',
    'built with characters cast_swap',
    'Also on: Unlock all costumes (cheats), Bullet-cam link (game link)']);
  assert.match(LM.infoHTML(m), /MODDED BUILD/);
  assert.deepEqual(LM.sessionModsFrom(CARDS, ['m_unlock']).map(s => s.title), ['Unlock all costumes'], 'only the kept ones');
});

// ---------------------------------------------------------------- the controller
test('a modded launch: fetches details + index in one budget, renders marquee, slides and list, preloads thumbnails', async () => {
  const asked = [];
  const h = harness({ fetchJson: (p, signal) => { asked.push(p); return answers()(p, signal); } });
  assert.equal(h.host.children[1], h.layer, 'the layer sits right above the visualizer canvas, under the logo and buttons');
  const m = await h.ctl.start({ gameId: 'doa2', mod: 'doa2_sonic_cast', sessionMods });
  assert.deepEqual(asked, ['/api/builds/doa2/doa2_sonic_cast/details', '/api/mods/built?game_id=doa2&q=doa2_sonic_cast&limit=20']);
  assert.equal(m.pairs.length, 6);
  assert.equal(h.layer.hidden, false);
  assert.equal(h.layer.dataset.motion, 'full');
  assert.match(h.layer.innerHTML, /lm-band/);
  assert.match(h.layer.innerHTML, /lm-stage/);
  assert.match(h.layer.innerHTML, /Also on: Unlock all costumes/);
  assert.ok(h.doc.getElementById('lm-style'), 'styles injected once');
  const urls = h.images.map(i => i.src);
  assert.ok(urls.includes('/api/characters/doa2_kasumi/preview?token=t') && urls.includes('/api/jobs/jdoa2/fitting/files/amy-2.png?token=t'));
  assert.equal(new Set(urls).size, urls.length, 'each thumbnail preloaded once');
  // slides: a card every SLIDE_MS, alternating sides, cycling the pairs; nothing else is scheduled (no polling)
  assert.match(h.layer.querySelector('.lm-l').innerHTML, /lm-card lm-fly[\s\S]*Amy Rose[\s\S]*replaces Kasumi · KAS/);
  assert.deepEqual(h.timers.map(t => t.ms), [LM.SLIDE_MS]);
  h.fire(LM.SLIDE_MS);
  assert.match(h.layer.querySelector('.lm-r').innerHTML, /Sonic[\s\S]*replaces Ryu Hayabusa · HAY/);
  for (let i = 0; i < 5; i++) h.fire(LM.SLIDE_MS);
  h.fire(LM.SLIDE_MS);
  assert.match(h.layer.querySelector('.lm-l').innerHTML, /Amy Rose/, 'back to the first pair');
  h.ctl.clear();
  assert.equal(h.timers.length, 0, 'clear stops the slideshow');
  assert.equal(h.layer.hidden, true);
  assert.equal(h.layer.innerHTML, '');
});

test('reduced motion: the marquee stands still (no animation, one copy), slides swap in place slowly', async () => {
  const h = harness({ reduced: true, fetchJson: answers() });
  await h.ctl.start({ gameId: 'doa2', mod: 'doa2_sonic_cast' });
  assert.equal(h.layer.dataset.motion, 'reduced');
  assert.match(h.layer.innerHTML, /class="lm-band lm-still"/);
  assert.doesNotMatch(h.layer.innerHTML, /lm-ltr|lm-copy|lm-fly/);
  assert.match(h.layer.querySelector('.lm-l').innerHTML, /class="lm-card lm-still"/);
  assert.deepEqual(h.timers.map(t => t.ms), [5000]);
  h.fire(5000);
  assert.match(h.layer.querySelector('.lm-l').innerHTML, /lm-card lm-still[\s\S]*Sonic/, 'same place, next pair');
  assert.equal(h.layer.querySelector('.lm-r').innerHTML, '', 'never flies to the other side');
  assert.match(LM.CSS, /@media \(prefers-reduced-motion: reduce\) \{ \.lm-track\.lm-ltr, \.lm-card\.lm-fly \{ animation:none; \}/);
});

test('no mod: nothing is fetched and nothing is shown (a stock launch is unchanged)', async () => {
  let asked = 0;
  const h = harness({ fetchJson: async () => { asked++; return {}; } });
  assert.equal(await h.ctl.start({ gameId: 'taxi', mod: '' }), null);
  assert.equal(asked, 0);
  assert.equal(h.layer.hidden, true);
  assert.equal(h.layer.innerHTML, '');
  assert.equal(h.timers.length, 0);
  assert.equal(h.images.length, 0);
  // kept session mods that turn out empty: still nothing
  await h.ctl.start({ gameId: 'taxi', mod: '', sessionMods: async () => [] });
  assert.equal(h.layer.hidden, true);
});

test('a fetch failure fails silently: only the names show', async () => {
  const h = harness({ fetchJson: answers({ '/api/builds/doa2/doa2_broken/details': new Error('500'),
    '/api/mods/built?game_id=doa2&q=doa2_broken&limit=20': new Error('500') }) });
  const m = await h.ctl.start({ gameId: 'doa2', mod: 'doa2_broken', sessionMods });
  assert.equal(m.namesOnly, true);
  assert.doesNotMatch(h.layer.innerHTML, /lm-band|lm-stage|500|error/i);
  assert.match(h.layer.innerHTML, /<b>doa2_broken<\/b>/);
  assert.match(h.layer.innerHTML, /Also on: Unlock all costumes/);
  assert.equal(h.timers.length, 0);
});

test('the 1.5 s budget: answers still out at the deadline are dropped (requests aborted), names only', async () => {
  let signal = null;
  const h = harness({ fetchJson: (p, s) => { signal = s; return new Promise(() => {}); } });
  const pending = h.ctl.start({ gameId: 'doa2', mod: 'doa2_sonic_cast' });
  await new Promise(r => setImmediate(r));
  assert.deepEqual(h.timers.map(t => t.ms), [LM.BUDGET_MS]);
  h.fire(LM.BUDGET_MS);
  const m = await pending;
  assert.equal(m.namesOnly, true);
  assert.equal(signal.aborted, true);
  assert.match(h.layer.innerHTML, /<b>doa2_sonic_cast<\/b>/);
  // the index alone in time: the pairs come from it
  const h2 = harness({ fetchJson: p => p.startsWith('/api/mods/built') ? Promise.resolve(BUILT) : new Promise(() => {}) });
  const p2 = h2.ctl.start({ gameId: 'doa2', mod: 'doa2_sonic_cast' });
  await new Promise(r => setImmediate(r));
  h2.fire(LM.BUDGET_MS);
  assert.equal((await p2).pairs.length, 6);
  assert.match(h2.layer.innerHTML, /KAS ← Amy Rose/);
});

test('a newer launch (or the loader closing) drops the older answer', async () => {
  const held = [];
  const h = harness({ fetchJson: p => new Promise(r => held.push(() => r(p.includes('details') ? DETAILS : BUILT))) });
  const first = h.ctl.start({ gameId: 'doa2', mod: 'doa2_sonic_cast' });
  await new Promise(r => setImmediate(r));
  h.ctl.clear();                                             // loader.show for a stock launch / loader.hide
  held.forEach(release => release());
  assert.equal(await first, null);
  assert.equal(h.layer.innerHTML, '');
});

// ---------------------------------------------------------------- the web shell wiring
test('the web shell loads the module and starts it from play() with the launch\'s mod; show/hide clear it', () => {
  const html = fs.readFileSync(path.join(__dirname, '..', 'clients', 'web', 'index.html'), 'utf8');
  assert.match(html, /<script src="\/viz\/launch-mods\.js"><\/script>/);
  // (#1656: the title names a renamed build launched from Mods / Builds / Special builds: "<game> · <build name>")
  assert.match(html, /loader\.show\(boot\.label \? `\$\{g\.title\} · \$\{boot\.label\}` : g\.title, [^\n]*\);\r?\n  loader\.modsFor\?\.\(id, boot\.disc\);/);
  assert.match(html, /this\.generation\+\+; this\.mods\?\.clear\(\);/);
  assert.match(html, /this\.three\?\.viz\?\.stop\(\); this\.mods\?\.clear\(\);/);
  assert.match(html, /modsFor\(gid, mod\) \{[\s\S]*?GBoxLaunchMods\.mount\(\$\("#loader"\)[\s\S]*?modKeepGet\(gid\)/);
});
