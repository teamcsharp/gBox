// Builds view (clients/web/viz/builds.js over /api/builds): rows (thumbnail, name, game, kinds, date, size, where, launch),
// inline rename (double-click -> PATCH display_name), launch options, details (modifications, characters with the 360°
// turntable placeholders, codes, compile, recipe, jobs, verification), the turntables' lazy GLB load on a stub three.js
// (only after the details open AND the viewer is on screen; disposed on collapse), the scheduled jobs (Cancel, Edit =
// cancel + resubmit, Investigate) and the job flowchart (flowOf + the three.js flow on the stub), and the web shell's tab.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const BV = require('../clients/web/viz/builds.js');

// ------------------------------------------------------------------ fixtures
const opt = (id, label, extra = {}) => ({ id, label, node: 'auto', target: id === 'here' ? 'here' : 'auto', moment: false, debug: false,
  default: id === 'here', call: { method: 'POST', path: `/api/games/g1/launch?node=auto&mod=cast_g1` }, ...extra });
const CAST = {
  key: 'g1/cast_g1', name: 'cast_g1', game_id: 'g1', game_title: 'Game <One>', label: 'G1: cast as <Wrestlers>', display_name: '',
  original_title: 'G1: cast as <Wrestlers>', kind: 'cast', kinds: ['cast', 'test'], writer: 'etm_swap', built: 3000, size: 3 * 2 ** 30,
  own_size: 2 ** 20, verified: false, image: '/api/characters/kane/preview', summary: 'kane → neo; rock → agent:smith',
  changes: [{ donor: 'kane', slot: 'neo' }, { donor: 'rock', slot: 'agent:smith' }], slots: 2, local_only: false,
  where: [{ where: 'spark', label: 'Spark collection' }, { where: 'pc', node: 'i9-NUC', online: true, label: 'i9-NUC (staged copy)' }],
  tickets: [{ number: 7 }], launch_options: [opt('here', 'This PC'), opt('pc:i9-NUC', 'Play on i9-NUC (windows)', { node: 'i9-NUC', target: 'i9-NUC',
    call: { method: 'POST', path: '/api/games/g1/launch?node=i9-NUC&mod=cast_g1' } }), opt('debug', 'Play with the debugger (Spark)', { node: 'linux', target: 'linux', debug: true })],
};
const PATCH = { ...CAST, key: 'g1/g1_patch', name: 'g1_patch', label: 'Patch', original_title: 'Patch', kind: 'romhack', kinds: ['romhack'],
  built: 1000, size: null, image: '', changes: [], summary: 'built by file_mod', tickets: [], where: [{ where: 'spark', label: 'Spark collection' }] };
const HACK = { ...PATCH, key: 'g2/g2_hack', name: 'g2_hack', game_id: 'g2', game_title: 'Game Two', label: 'Hack', kinds: ['cheats'], kind: 'cheats', built: 2000 };
const DETAILS = {
  key: 'g1/cast_g1', name: 'cast_g1', game_id: 'g1', label: 'G1: cast as <Wrestlers>', writer: 'etm_swap', built: 3000,
  built_on: { host: 'spark', os: 'linux' }, where: [{ label: 'Spark collection' }, { label: 'i9-NUC (staged copy)' }],
  modifications: { files: [{ path: 'game.iso', change: 'image', size: 2048, what: 'the built image the launch boots' },
                           { path: 'EBOOT.BIN', change: 'patched', size: 10, base_size: 10, patches: [{ offset: 16, length: 2 }] },
                           { path: 'data/new.bin', change: 'new' }], derived: true, note: 'base sizes were not recorded' },
  characters: [
    { slot: 'neo', slot_name: 'Neo', status: 'built', donors: ['kane'], donor: { slug: 'kane', name: 'Kane', preview_url: '/api/characters/kane/preview', model_url: '/api/characters/kane/file/kane.glb' },
      donor_source: 'No Mercy', fitted_url: '/api/characters/kane/file/targets/g1_neo.glb', fitted_from: 'fitted model kept in the collection',
      original: { slug: 'g1_neo', name: 'Neo', source: 'G1', preview_url: '/api/characters/g1_neo/preview', model_url: '/api/characters/g1_neo/file/g1_neo.glb' } },
    { slot: 'agent:smith', slot_name: 'Agent Smith', status: 'failed', reason: 'too many bones', donors: ['rock'],
      donor: { slug: 'rock', name: 'The Rock', preview_url: '/api/characters/rock/preview', model_url: '' }, fitted_url: '', fitted_from: '',
      original: null, original_note: 'no character of this game named like Agent Smith' }],
  cast: { source: 'Wrestlers', mapping: 'by_role', seed: '' },
  codes: [{ type: 'cheat', label: 'inf health', codes: ['ABCD-1234'], source: 'mod card' }, { type: 'ram_write', tool: 'write_memory', label: 'write_memory', address: '0x8001234', value: 99, source: 'mod card' }],
  compile: { compiler_flags: '-O2 -g' }, recipe: { tool: 'characters', input: { op: 'cast_swap', target_game: 'g1' } }, recipe_recorded: true,
  build_call: { tool: 'characters', input: { op: 'cast_swap' } }, job_id: 'jcast',
  jobs: [{ id: 'jcast', tool: 'characters', op: 'cast_swap', state: 'succeeded', finished: 3000 }],
  receipts: [{ id: 'rc1', validation_ok: true, problems: [], artifacts: [{ sha256: 'a'.repeat(64), name: 'preview.png', url: '/api/artifacts/' + 'a'.repeat(64) }] }],
  tickets: [{ number: 7, title: 'Cast it' }], verification: { verified: false, text: 'unverified in game until launched', launches: [] },
};
const now = Date.now() / 1000;
const QUEUED = { id: 'q1', tool: 'characters', op: 'cast_swap', category: 'cast', category_label: 'cast swap', label: 'Cast swap: G1 as wrestlers',
  state: 'queued', phase: 'queued', worker: '', require_os: 'linux', created: now - 30, editable: true, progress: null, eta_s: null,
  input: { op: 'cast_swap', target_game: 'g1', source: 'wrestlers', slots: 'all', seed: 3, assignments: [{ slot: 'neo', character: 'kane' }] }, stages: [], steps: [] };
const RUNNING = { id: 'r1', tool: 'characters', op: 'use', category: 'character', category_label: 'character swap', label: 'Character swap: kane → G1 player',
  state: 'running', phase: 'running', worker: 'spark', created: now - 200, started: now - 100, editable: false, eta_s: 300,
  progress: { pct: 25, msg: 'retarget' }, input: { op: 'use' },
  stages: [{ name: 'scale', state: 'done', done: 1, total: 1 }, { name: 'retarget', state: 'running', done: 0, total: 1 }], steps: [] };
const FAILED = { id: 'f1', tool: 'file_mod', op: 'build', category: 'file', category_label: 'file mod', label: 'File mod: x', state: 'failed', phase: 'failed',
  worker: 'i9-NUC', created: now - 900, started: now - 800, finished: now - 60, error: 'boom', editable: false, input: {}, stages: [],
  steps: ['Copying the base', 'Patching EBOOT.BIN'] };

// ------------------------------------------------------------------ a small fake DOM
const unesc = s => String(s).replace(/&#(\d+);/g, (_, n) => String.fromCharCode(+n));
const camel = s => s.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
function fakeEl(tag = 'div') {
  const el = {
    tagName: tag.toUpperCase(), dataset: {}, style: {}, children: [], className: '', value: '', _html: '', removed: false, focused: false,
    clientWidth: 600, clientHeight: 220, width: 0, height: 0, listeners: {},
    appendChild(c) { if (c.parentNode) c.parentNode.children = c.parentNode.children.filter(x => x !== c); this.children.push(c); c.parentNode = this; return c; },
    remove() { this.removed = true; if (this.parentNode) this.parentNode.children = this.parentNode.children.filter(x => x !== this); this.parentNode = null; },
    get innerHTML() { return this._html; },
    set innerHTML(v) { this._html = String(v); this._cache = null; this.children = []; },
    set textContent(v) { this._text = String(v); }, get textContent() { return this._text ?? this._html; },
    focus() { this.focused = true; }, select() {},
    addEventListener(t, fn) { this.listeners[t] = fn; }, removeEventListener(t) { delete this.listeners[t]; },
    getContext() { return { draws: 0, clearRect() {}, drawImage() { this.draws++; } }; },
    querySelectorAll(sel) {
      if (!this._cache) this._cache = { tags: parseTags(this._html), els: new Map() };
      const alts = sel.split(',').map(s => [...s.trim().matchAll(/\[([\w-]+)(?:="([^"]*)")?\]/g)].map(m => [m[1], m[2]]));
      const out = [];
      this._cache.tags.forEach((t, i) => {
        if (!alts.some(conds => conds.every(([a, v]) => a in t.attrs && (v === undefined || t.attrs[a] === v)))) return;
        let e = this._cache.els.get(i);
        if (!e) {
          e = fakeEl(t.tag);
          for (const [k, v] of Object.entries(t.attrs)) if (k.startsWith('data-')) e.dataset[camel(k.slice(5))] = v;
          e.value = t.tag === 'textarea' ? t.text : (t.attrs.value ?? '');
          e.attrs = t.attrs; e.isConnected = true;
          this._cache.els.set(i, e);
        }
        out.push(e);
      });
      return out;
    },
    querySelector(sel) { return this.querySelectorAll(sel)[0] || null; },
  };
  return el;
}
function parseTags(html) {
  const out = [];
  for (const m of html.matchAll(/<(\w+)((?:\s+[\w-]+(?:="[^"]*")?)*)\s*\/?>/g)) {
    const attrs = {};
    for (const a of m[2].matchAll(/([\w-]+)(?:="([^"]*)")?/g)) attrs[a[1]] = a[2] === undefined ? '' : unesc(a[2]);
    const text = m[1] === 'textarea' ? unesc(html.slice(m.index + m[0].length, html.indexOf('</textarea>', m.index))) : '';
    out.push({ tag: m[1], attrs, text });
  }
  return out;
}
// an event target inside a row / job: closest() answers the delegated selectors the controller asks for
function target({ bv, key, jid, dataset = {}, rename, value } = {}) {
  return {
    dataset, value,
    closest(sel) {
      if (sel === '[data-bv]' && bv) return { dataset: { bv, ...dataset } };
      if (sel === '[data-bv="name"]' && bv === 'name') return { dataset: { bv } };
      if (sel === '[data-bv-key]' && key) return { dataset: { bvKey: key } };
      if (sel === '[data-bv-jid]' && jid) return { dataset: { bvJid: jid } };
      if (sel === '[data-bv-rename]' && rename) return { dataset: { bvRename: rename }, value };
      return null;
    },
  };
}

// ------------------------------------------------------------------ a three.js stub
function threeStub() {
  const made = { renderers: [], geometries: [], loads: [], disposedGeo: 0, renders: 0, managers: [] };
  class V3 { constructor(x = 0, y = 0, z = 0) { this.x = x; this.y = y; this.z = z; }
    set(x, y, z) { this.x = x; this.y = y; this.z = z; return this; } length() { return Math.hypot(this.x, this.y, this.z); }
    sub(v) { this.x -= v.x; this.y -= v.y; this.z -= v.z; return this; } clone() { return new V3(this.x, this.y, this.z); }
    copy(v) { return this.set(v.x, v.y, v.z); } lerp(v, k) { return this.set(this.x + (v.x - this.x) * k, this.y + (v.y - this.y) * k, this.z + (v.z - this.z) * k); }
    project() { return new V3(this.x / 10, this.y / 10, 0.5); } setScalar(s) { return this.set(s, s, s); } }
  class O3 { constructor() { this.children = []; this.position = new V3(); this.rotation = new V3(); this.scale = new V3(1, 1, 1); }
    add(...o) { this.children.push(...o); return this; } clear() { this.children = []; }
    traverse(fn) { fn(this); for (const c of this.children) c.traverse ? c.traverse(fn) : fn(c); } lookAt() {} updateProjectionMatrix() {} }
  class Geo { constructor() { made.geometries.push(this); } dispose() { this.disposed = true; made.disposedGeo++; } setFromPoints() { return this; } }
  class Mat { constructor(o) { this.o = o; } dispose() { this.disposed = true; } }
  class Mesh extends O3 { constructor(g, m) { super(); this.geometry = g; this.material = m; } }
  const THREE = {
    Vector3: V3, Scene: O3, Group: O3, Mesh, Line: Mesh, PerspectiveCamera: class extends O3 { constructor() { super(); this.aspect = 1; } },
    HemisphereLight: O3, DirectionalLight: O3, AmbientLight: O3, PointLight: O3,
    SphereGeometry: Geo, OctahedronGeometry: Geo, TorusGeometry: Geo, BufferGeometry: Geo,
    MeshStandardMaterial: Mat, MeshBasicMaterial: Mat, LineBasicMaterial: Mat,
    Box3: class { setFromObject() { return this; } getCenter(v) { return v.set(0, 1, 0); } getSize(v) { return v.set(1, 2, 1); } },
    LoadingManager: class { constructor() { made.managers.push(this); } setURLModifier(f) { this.modify = f; } },
    WebGLRenderer: class { constructor(o) { this.o = o; this.domElement = o?.canvas || fakeEl('canvas'); made.renderers.push(this); }
      setPixelRatio() {} setSize(w, h) { this.size = [w, h]; } render() { made.renders++; } dispose() { this.disposed = true; } },
  };
  class GLTFLoader {
    constructor(manager) { this.manager = manager; }
    load(url, onLoad, _p, onError) {
      made.loads.push(url);
      if (/broken/.test(url)) return Promise.resolve().then(() => onError(new Error('404')));
      const scene = new O3(); scene.add(new Mesh(new Geo(), new Mat()));
      return Promise.resolve().then(() => onLoad({ scene }));
    }
  }
  return { mods: { THREE, GLTFLoader }, made };
}
class FakeIO {
  constructor(cb) { this.cb = cb; this.targets = new Set(); FakeIO.last = this; }
  observe(el) { this.targets.add(el); } unobserve(el) { this.targets.delete(el); } disconnect() { this.targets.clear(); this.off = true; }
  fire(el, on = true) { this.cb([{ target: el, isIntersecting: on }]); }
}
const flush = async (n = 6) => { for (let i = 0; i < n; i++) await new Promise(r => setImmediate(r)); };

function fakeEnv(extra = {}) {
  const calls = [], stub = threeStub(), frames = [];
  const routes = {
    'GET /api/builds': () => ({ items: [CAST, PATCH, HACK], indexing: false, sizing: 0 }),
    'GET /api/builds/scheduled': () => ({ jobs: [RUNNING, QUEUED], recent: [FAILED], queued: 1, running: 1 }),
    'GET /api/builds/g1/cast_g1/details': () => DETAILS,
    'PATCH /api/builds/g1/cast_g1': b => ({ key: 'g1/cast_g1', display_name: b.display_name, label: b.display_name || CAST.original_title }),
    'POST /api/jobs/q1/cancel': () => ({ id: 'q1', state: 'failed', cancel_requested: false }),
    'POST /api/builds/scheduled/q1/edit': b => ({ cancelled: 'q1', job: { ...QUEUED, id: 'q2', input: { ...QUEUED.input, ...b.input }, edited_from: 'q1' } }),
    'GET /api/builds/scheduled/f1': () => ({ ...FAILED, log_tail: 'line1\nboom happened\n', progress_log: [], receipt: { id: 'rc9', validation_ok: false, problems: ['no image'] },
      artifacts: [{ sha256: 'b'.repeat(64), name: 'mod.json', size: 9, url: '/api/artifacts/' + 'b'.repeat(64) }],
      fitting_events: { models: { player: { label: 'Kane -> player', state: 'failed', stages: { scale: { state: 'done' }, write: { state: 'failed' } } } } },
      result: { status: 'failed', mod: 'x', message: 'nope' } }),
    'POST /api/games/g1/launch': () => ({ id: 'L1', state: 'queued' }),
    ...extra.routes,
  };
  const env = {
    calls, stub, frames, here: 'MYPC', tick: 3600000, document: { createElement: t => fakeEl(t) }, IntersectionObserver: FakeIO,
    loadThree: async () => stub.mods, raf: f => { frames.push(f); return frames.length; }, caf() {},
    url: u => u + (u.includes('?') ? '&' : '?') + 'token=t', confirm: () => true,
    api: async (p, body, method) => {
      const m = method || (body ? 'POST' : 'GET');
      calls.push([m, p, body]);
      const key = `${m} ${p.split('?')[0]}`;
      if (!routes[key]) throw new Error('404 ' + key);
      return routes[key](body);
    },
    ...extra,
  };
  return env;
}
const host = () => { const h = fakeEl('div'); h.addEventListener = (t, fn) => { h.listeners[t] = fn; }; return h; };

// ------------------------------------------------------------------ pure rendering
test('all six build columns sort their displayed values in both directions', () => {
  const low = { ...CAST, key: 'low', label: 'Build 2', game_title: 'Game 2', kinds: ['cast'], built: 9, size: 10000, own_size: 9, where: [{ label: 'Alpha PC' }] };
  const high = { ...CAST, key: 'high', label: 'Build 10', game_title: 'Game 10', kinds: ['character'], built: 100, size: 100, own_size: 100, where: [{ label: 'Zulu PC' }], favorite: true };
  for (const sort of ['name', 'game', 'kind', 'built', 'size', 'where']) {
    assert.deepEqual(BV.filterBuilds([high, low], { sort, direction: 'asc' }).map(b => b.key), ['low', 'high'], sort);
    assert.deepEqual(BV.filterBuilds([low, high], { sort, direction: 'desc' }).map(b => b.key), ['high', 'low'], sort);
  }
  const missing = { ...low, key: 'missing', built: 0, size: null };
  for (const sort of ['built', 'size']) for (const direction of ['asc', 'desc']) {
    assert.equal(BV.filterBuilds([missing, high, low], { sort, direction }).at(-1).key, 'missing');
  }
  assert.equal(BV.filterBuilds([{ ...high, local_only: true }, low], { sort: 'size' }).at(-1).key, 'high');
  assert.deepEqual(BV.filterBuilds([low, high], { fav: true, sort: 'name' }).map(b => b.key), ['high']);
});

test('column clicks toggle direction, reset pagination and retain sorting through filters and refresh', async () => {
  const items = Array.from({ length: 65 }, (_, i) => ({ ...CAST, key: 'g1/build' + i, name: 'build' + i, label: 'Build ' + i, built: i + 1 }));
  const env = fakeEnv({ routes: { 'GET /api/builds': () => ({ items }) } }), h = host();
  const ctl = BV.mount(h, env); await ctl.ready;
  const click = sort => ctl.onClick({ target: target({ bv: 'sort', dataset: { sort } }) });
  const first = () => h.querySelector('[data-bv-list]').innerHTML.match(/data-bv-key="([^"]+)"/)[1];
  try {
    await ctl.onClick({ target: target({ bv: 'more' }) });
    assert.equal(ctl.st.page, 2);
    await click('name');
    assert.equal(first(), 'g1/build0'); assert.equal(ctl.st.page, 1);
    assert.match(h.querySelector('[data-bv-head]').innerHTML, /Name, sorted ascending/);
    await click('name'); assert.equal(first(), 'g1/build64');
    assert.match(h.querySelector('[data-bv-head]').innerHTML, /Name, sorted descending/);
    await click('built'); assert.equal(ctl.st.direction, 'desc');
    await click('built'); assert.equal(first(), 'g1/build0');
    ctl.st.q = 'Build 6'; ctl.drawList(); assert.equal(first(), 'g1/build6');
    await ctl.loadList(true); assert.equal(first(), 'g1/build6');
    assert.equal(ctl.st.sort, 'built'); assert.equal(ctl.st.direction, 'asc');
    await click('size'); assert.equal(ctl.st.direction, 'desc');
  } finally { ctl.stop(); }
});

test('launch and return restores filters, sorting, expanded rows, options, pagination and scroll without stale launch messages', async () => {
  const values = new Map(), storage = { getItem: k => values.get(k), setItem: (k, v) => values.set(k, v) };
  const scrollElement = { scrollTop: 0 };
  let finishLaunch;
  const first = BV.mount(host(), fakeEnv({ storage, scrollElement, launch: () => new Promise(r => { finishLaunch = r; }) }));
  await first.ready;
  first.onInput({ target: { dataset: { bvF: 'game' }, value: 'g1' } });
  first.onInput({ target: { dataset: { bvF: 'q' }, value: 'cast' } });
  await first.onClick({ target: target({ bv: 'sort', dataset: { sort: 'size' } }) });
  await first.onClick({ target: target({ bv: 'more' }) });
  await first.toggle(CAST);
  await first.onClick({ target: target({ bv: 'opts', key: CAST.key }) });
  scrollElement.scrollTop = 735;
  const pending = first.launch(CAST, CAST.launch_options[0]);
  first.stop(); scrollElement.scrollTop = 0;
  const h = host(), second = BV.mount(h, fakeEnv({ storage, scrollElement }));
  await second.ready;
  try {
    assert.equal(second.st.game, 'g1'); assert.equal(second.st.q, 'cast');
    assert.equal(second.st.sort, 'size'); assert.equal(second.st.direction, 'desc');
    assert.equal(second.st.page, 2); assert.ok(second.st.open.has(CAST.key));
    assert.ok(second.st.details.get(CAST.key)?.data, 'expanded details are loaded again');
    assert.equal(second.st.opts, CAST.key); assert.equal(second.st.lastLaunch, CAST.key);
    assert.equal(scrollElement.scrollTop, 735);
    assert.match(h.querySelector('[data-bv-list]').innerHTML, /Last launched/);
    assert.equal(second.st.msg.size, 0);
    second.onInput({ target: { dataset: { bvF: 'q' }, value: 'updated' } });
    finishLaunch(); await pending;
    assert.equal(JSON.parse([...values.values()][0]).q, 'updated', 'late launch response cannot overwrite the returned view');
  } finally { second.stop(); }
  const directed = BV.mount(host(), fakeEnv({ storage, scrollElement, q: '', game: 'g2' }));
  await directed.ready;
  try { assert.equal(directed.st.game, 'g2'); assert.equal(directed.st.q, ''); assert.equal(directed.st.page, 1); assert.equal(scrollElement.scrollTop, 0); }
  finally { directed.stop(); }
});

test('unavailable storage and deleted remembered builds do not prevent returning to Builds', async () => {
  const storage = { getItem: () => JSON.stringify({ open: ['missing'], lastLaunch: 'missing', opts: 'missing' }), setItem() { throw new Error('blocked'); } };
  const ctl = BV.mount(host(), fakeEnv({ storage })); await ctl.ready;
  try { assert.equal(ctl.st.data.items.length, 3); assert.equal(ctl.st.details.size, 0); }
  finally { ctl.stop(); }
});

test('filters and facets: words over name / game / donor / kind / #ticket, game and kind filters, newest first', () => {
  const all = [PATCH, CAST, HACK];
  assert.deepEqual(BV.filterBuilds(all).map(b => b.name), ['cast_g1', 'g2_hack', 'g1_patch']);
  assert.deepEqual(BV.filterBuilds(all, { q: 'rock' }).map(b => b.name), ['cast_g1']);
  assert.deepEqual(BV.filterBuilds(all, { q: 'rom hack' }).map(b => b.name), ['g1_patch']);
  assert.deepEqual(BV.filterBuilds(all, { q: '#7' }).map(b => b.name), ['cast_g1']);
  assert.deepEqual(BV.filterBuilds(all, { kind: 'test' }).map(b => b.name), ['cast_g1']);
  assert.deepEqual(BV.filterBuilds(all, { game: 'g2' }).map(b => b.name), ['g2_hack']);
  const f = BV.facets(all);
  assert.deepEqual(f.games.map(g => [g.game_id, g.count]), [['g1', 2], ['g2', 1]]);
  assert.deepEqual(f.kinds.map(k => k.kind), ['cast', 'cheats', 'romhack', 'test']);
});

test('row: thumbnail, escaped name, game, kind chips, date, size, where, launch + options', () => {
  const html = BV.rowHTML(CAST, { open: new Set() }, { url: u => u + '?token=t', here: 'MYPC', now: 3030 });
  assert.match(html, /data-bv-key="g1\/cast_g1"/);
  assert.match(html, /<img class="bv-thumb"[^>]*src="\/api\/characters\/kane\/preview\?token=t"/);
  assert.ok(html.includes('G1: cast as &#60;Wrestlers&#62;') && !html.includes('<Wrestlers>'));
  assert.match(html, /data-bv="name" title="Double-click \(or ✎\) to rename · folder cast_g1"/);
  assert.match(html, /Game &#60;One&#62;/);
  assert.match(html, /<span class="bv-chip bv-k1">cast swap<\/span><span class="bv-chip">test<\/span>/);
  assert.match(html, /just now/); assert.match(html, /1\.0 MB/);
  assert.match(html, /Spark collection<\/span><span class="bv-where-i"[^>]*>i9-NUC \(staged copy\)/);
  assert.match(html, /data-bv="launch"[^>]*title="This PC \(MYPC\)">▶ Launch/);
  assert.match(html, /data-bv="toggle" aria-expanded="false"[^>]*>▸/);
  assert.ok(!html.includes('bv-det'), 'details closed');
  assert.match(BV.rowHTML(PATCH, {}, {}), /sizing…/);
  assert.match(BV.rowHTML(PATCH, {}, {}), /bv-nothumb/);
  const renaming = BV.rowHTML(CAST, { renaming: 'g1/cast_g1' }, {});
  assert.match(renaming, /<input class="bv-rename" data-bv-rename="g1\/cast_g1" value="G1: cast as &#60;Wrestlers&#62;"/);
  const opts = BV.rowHTML(CAST, { opts: 'g1/cast_g1' }, { here: 'MYPC' });
  assert.match(opts, /data-opt="here">▶ This PC \(MYPC\)/);
  assert.match(opts, /data-opt="pc:i9-NUC">▶ Play on i9-NUC \(windows\)/);
  assert.match(opts, /data-opt="debug">▶ Play with the debugger \(Spark\)/);
  const named = BV.rowHTML({ ...CAST, label: 'Best cast', display_name: 'Best cast' }, {}, {});
  assert.match(named, />Best cast</); assert.match(named, /was “G1: cast as &#60;Wrestlers&#62;”/);
  // the launch call: "here" options go to this PC's worker, others keep their node
  const c = BV.launchCall(CAST, CAST.launch_options[0], 'MYPC');
  assert.equal(c.path, '/api/games/g1/launch?node=MYPC&mod=cast_g1'); assert.equal(c.x.mod, 'cast_g1');
  assert.equal(BV.launchCall(CAST, CAST.launch_options[1], 'MYPC').path, '/api/games/g1/launch?node=i9-NUC&mod=cast_g1');
});

test('details: modifications, characters with two 360° viewers each, codes, compile, recipe, jobs, verification', () => {
  const html = BV.detailsHTML(DETAILS, { url: u => u + '?token=t' });
  assert.match(html, /<h4>Modifications <span class="mut">3<\/span>/);
  assert.match(html, /<td class="bv-path">EBOOT\.BIN<\/td><td><span class="bv-chip bv-ch-patched">patched<\/span><\/td><td>10 B<\/td><td>10 B<\/td>/);
  assert.match(html, /1 byte patch: 0x10 \(\+2\)/);
  assert.match(html, /base sizes were not recorded/);
  assert.match(html, /<b>Neo<\/b> ← <b>Kane<\/b> <span class="bv-chip bv-s-built">built<\/span> <span class="mut">from No Mercy/);
  assert.match(html, /data-bv-tt="g1\/cast_g1\|0\|donor" data-glb="\/api\/characters\/kane\/file\/targets\/g1_neo\.glb" data-img="\/api\/characters\/kane\/preview" data-state="idle"/);
  assert.match(html, /<small>Who they are<\/small><b>Kane<\/b><span class="mut">fitted model kept in the collection/);
  assert.match(html, /data-bv-tt="g1\/cast_g1\|0\|orig" data-glb="\/api\/characters\/g1_neo\/file\/g1_neo\.glb"/);
  assert.match(html, /<small>Who they&#39;re replacing<\/small><b>Neo<\/b>/);
  assert.match(html, /data-bv-tt="g1\/cast_g1\|1\|donor" data-glb="" data-img="\/api\/characters\/rock\/preview" data-state="image"/);
  assert.match(html, /no character of this game named like Agent Smith/);
  assert.match(html, /src="\/api\/characters\/kane\/preview\?token=t"/);
  assert.match(html, /<span class="bv-chip">cheat<\/span> <b>inf health<\/b> <code>ABCD-1234<\/code>/);
  assert.match(html, /<code>0x8001234 = 99<\/code>/);
  assert.match(html, /&#34;compiler_flags&#34;: &#34;-O2 -g&#34;/);
  assert.match(html, /data-bv="rebuild" data-key="g1\/cast_g1"/);
  assert.match(html, /The exact call recorded at build time/);
  assert.match(html, /data-bv="jobopen" data-jid="jcast">job jcast/);
  assert.match(html, /<a class="bv-art"[^>]*href="\/api\/artifacts\/a{64}">preview\.png/);
  assert.match(html, /unverified in game until launched/); assert.match(html, /Never launched/);
  assert.match(html, /built [^·]* on spark · lives on Spark collection, i9-NUC \(staged copy\)/);
  const bare = BV.detailsHTML({ key: 'g/x', name: 'x', modifications: { files: [] }, characters: [], codes: [], codes_note: 'no cheat codes',
    compile: null, compile_note: 'not a decomp / recompile build', recipe: null, recipe_note: 'no recipe recorded', jobs: [], receipts: [], verification: {} });
  assert.match(bare, /No changed files recorded/); assert.match(bare, /No characters inserted/); assert.match(bare, /no cheat codes/);
  assert.match(bare, /not a decomp \/ recompile build/); assert.match(bare, /no recipe recorded/); assert.match(bare, /No job recorded/);
  assert.match(BV.detailsHTML({ local_only: true, note: 'only on i9-NUC' }), /only on i9-NUC/);
});

test('flowOf: queued, claimed, stages, steps, failure in red where it stopped, done', () => {
  const lab = f => f.nodes.map(n => `${n.label}:${n.state}`);
  assert.deepEqual(lab(BV.flowOf(QUEUED)), ['queued:running', 'claimed:pending', 'cast swap:pending', 'write:pending', 'verify:pending', 'done:pending']);
  const run = BV.flowOf(RUNNING);
  assert.deepEqual(lab(run), ['queued:done', 'claimed · spark:done', 'scale:done', 'retarget:running', 'write:pending', 'verify:pending', 'done:pending']);
  assert.equal(run.current, 3); assert.deepEqual(run.edges[0], ['queued', 'claimed']); assert.equal(run.edges.length, 6);
  assert.deepEqual(lab(BV.flowOf({ ...RUNNING, phase: 'claimed', progress: null, stages: [] })),
    ['queued:done', 'claimed · spark:running', 'character swap:pending', 'write:pending', 'verify:pending', 'done:pending']);
  assert.deepEqual(lab(BV.flowOf(FAILED)), ['queued:done', 'claimed · i9-NUC:done', 'Copying the base:done', 'Patching EBOOT.BIN:failed',
    'write:pending', 'verify:pending', 'failed:failed']);
  assert.deepEqual(lab(BV.flowOf({ ...FAILED, steps: [], phase: 'cancelled' })).slice(-4), ['file mod:failed', 'write:pending', 'verify:pending', 'cancelled:failed']);
  assert.deepEqual(lab(BV.flowOf({ ...RUNNING, state: 'invalid', stages: [{ name: 'scale', state: 'done', done: 1, total: 1 }, { name: 'write', state: 'done', done: 1, total: 1 }] })).slice(-3),
    ['write:done', 'verify:failed', 'failed:failed']);
  assert.ok(BV.flowOf({ ...RUNNING, state: 'succeeded', phase: 'succeeded' }).nodes.every(n => n.state === 'done'));
  assert.match(BV.flowTextHTML(run), /<li class="bv-fn bv-fn-running">retarget <span class="mut">0\/1<\/span>/);
});

test('scheduled rows: phase, worker, progress + ETA, Edit only when queued; editor fields and parsed edits', () => {
  const html = BV.scheduledHTML({ jobs: [RUNNING, QUEUED], recent: [FAILED] }, { jobOpen: new Set(['r1']) }, { now });
  assert.match(html, /data-bv-jid="r1"[\s\S]*bv-ph-running">running[\s\S]*Character swap: kane → G1 player[\s\S]*spark · job r1/);
  assert.match(html, /25% · retarget · ~5 min left/);
  assert.match(html, /data-bv="jedit" disabled title="Only a queued job can be edited">Edit/);
  assert.match(html, /data-bv-flow="r1"/); assert.ok(!html.includes('data-bv-flow="q1"'));
  assert.match(html, /data-bv-jid="q1"[\s\S]*any linux worker[\s\S]*waiting for a worker[\s\S]*data-bv="jedit" >Edit/);
  assert.match(html, /Recently finished[\s\S]*data-bv-jid="f1"[\s\S]*boom/);
  assert.ok(!/data-bv-jid="f1"[\s\S]*data-bv="jcancel"/.test(html), 'a finished job has no Cancel');
  const ed = BV.editorHTML(QUEUED);
  assert.match(ed, /data-bv-ef="source" data-jid="q1" data-type="string" value="wrestlers"/);
  assert.match(ed, /data-bv-ef="seed" data-jid="q1" data-type="number" value="3"/);
  assert.match(ed, /<textarea data-bv-ej="assignments" data-jid="q1"/);
  assert.ok(!ed.includes('data-bv-ef="op"'), 'the op is not editable');
  const el = (k, v, extra = {}) => ({ dataset: { bvEf: k, ...extra }, value: v });
  assert.deepEqual(BV.readEdits(QUEUED, [el('source', 'fighters', { type: 'string' }), el('seed', '3', { type: 'number' }),
    { dataset: { bvEj: 'assignments' }, value: '[{"slot":"neo","character":"rock"}]' }]),
    { source: 'fighters', assignments: [{ slot: 'neo', character: 'rock' }] });
  assert.throws(() => BV.readEdits(QUEUED, [{ dataset: { bvEj: 'assignments' }, value: '[oops' }]), /assignments: not valid JSON/);
  assert.throws(() => BV.readEdits(QUEUED, [el('seed', 'x', { type: 'number' })]), /seed: a number/);
});

// ------------------------------------------------------------------ the controller
test('controller: list, rename by double-click (PATCH display_name), launch on this PC and from the options', async () => {
  const env = fakeEnv(), h = host();
  const ctl = BV.mount(h, env); await ctl.ready;
  try {
    const list = h.querySelector('[data-bv-list]');
    assert.match(list.innerHTML, /data-bv-key="g1\/cast_g1"[\s\S]*data-bv-key="g2\/g2_hack"[\s\S]*data-bv-key="g1\/g1_patch"/);
    assert.match(h.innerHTML, /<option value="cast">cast swap \(1\)<\/option>/);
    assert.equal(h.querySelector('[data-bv-count]').textContent, '3 of 3');
    // double-click the name -> an input, focused; Enter saves through PATCH
    h.listeners.dblclick({ target: target({ bv: 'name', key: 'g1/cast_g1' }) });
    const inp = h.querySelector('[data-bv-list]').querySelector('[data-bv-rename]');
    assert.ok(inp && inp.dataset.bvRename === 'g1/cast_g1' && inp.focused);
    await ctl.onKey({ key: 'Enter', target: target({ rename: 'g1/cast_g1', value: '  Wrestlemania  ' }) });
    await flush();
    assert.deepEqual(env.calls.find(c => c[0] === 'PATCH'), ['PATCH', '/api/builds/g1/cast_g1', { display_name: 'Wrestlemania' }]);
    assert.match(h.querySelector('[data-bv-list]').innerHTML, /data-bv="name"[^>]*>Wrestlemania</);
    assert.match(h.querySelector('[data-bv-list]').innerHTML, /Renamed \(the folder stays cast_g1\)/);
    assert.equal(ctl.st.renaming, null);
    // Escape cancels; the same name is not saved again
    h.listeners.dblclick({ target: target({ bv: 'name', key: 'g1/cast_g1' }) });
    ctl.onKey({ key: 'Escape', target: target({ rename: 'g1/cast_g1', value: 'x' }) });
    assert.equal(ctl.st.renaming, null); assert.equal(env.calls.filter(c => c[0] === 'PATCH').length, 1);
    // ▶ Launch: the default option (this PC's worker); ▾ -> another PC
    await ctl.onClick({ target: target({ bv: 'launch', key: 'g1/cast_g1' }) });
    assert.deepEqual(env.calls.at(-1), ['POST', '/api/games/g1/launch?node=MYPC&mod=cast_g1', {}]);
    await ctl.onClick({ target: target({ bv: 'opts', key: 'g1/cast_g1' }) });
    assert.match(h.querySelector('[data-bv-list]').innerHTML, /data-bv-opts="g1\/cast_g1"/);
    await ctl.onClick({ target: target({ bv: 'launchopt', dataset: { key: 'g1/cast_g1', opt: 'pc:i9-NUC' } }) });
    assert.deepEqual(env.calls.at(-1), ['POST', '/api/games/g1/launch?node=i9-NUC&mod=cast_g1', {}]);
    // the shell's launch path (loader) when the host gives one
    const seen = [];
    const env2 = fakeEnv({ launch: async (gid, x) => seen.push([gid, x.mod, x.node, x.debug]) }), h2 = host();
    const ctl2 = BV.mount(h2, env2); await ctl2.ready;
    await ctl2.onClick({ target: target({ bv: 'launchopt', dataset: { key: 'g1/cast_g1', opt: 'debug' } }) });
    assert.deepEqual(seen, [['g1', 'cast_g1', 'linux', true]]); ctl2.stop();
    // filters
    ctl.onInput({ target: { dataset: { bvF: 'kind' }, value: 'cheats' } });
    assert.match(h.querySelector('[data-bv-list]').innerHTML, /g2_hack/); assert.doesNotMatch(h.querySelector('[data-bv-list]').innerHTML, /cast_g1/);
  } finally { ctl.stop(); }
});

test('#1656 rows: ☆/★ and ✎ next to the name; ▾ options carry Rename…, favorite, restore; favorites first + ★ filter', () => {
  const html = BV.rowHTML(CAST, {}, {});
  assert.match(html, /<div class="bv-nm"><button class="bv-ico bv-star" type="button" data-bv="fav" aria-pressed="false"[^>]*>☆<\/button><span class="bv-name"/);
  assert.match(html, /data-bv="rename" title="Rename this build \(the folder keeps its name\)" aria-label="Rename">✎</);
  const fav = BV.rowHTML({ ...CAST, favorite: true, display_name: 'Best', label: 'Best' }, { opts: 'g1/cast_g1' }, { here: 'MYPC' });
  assert.match(fav, /class="bv-row bv-fav" data-bv-key="g1\/cast_g1"/);
  assert.match(fav, /data-bv="fav" aria-pressed="true"[^>]*>★</);
  assert.match(fav, /data-bv="rename" data-key="g1\/cast_g1"[^>]*>✎ Rename…</);
  assert.match(fav, /data-bv="fav" data-key="g1\/cast_g1">☆ Remove from favorites</);
  assert.match(fav, /data-bv="unname" data-key="g1\/cast_g1">↺ Restore “G1: cast as &#60;Wrestlers&#62;”</);
  const unnamed = { ...CAST, display_name: '', label: CAST.original_title };       // (earlier tests rename the shared CAST)
  assert.match(BV.optionsHTML(unnamed, 'MYPC'), /★ Add to favorites/);
  assert.match(BV.rowHTML(unnamed, { renaming: 'g1/cast_g1' }, {}), /<input class="bv-rename"[^>]* data-nomic>/,
               'no dictation wrapper: moving the field would blur (so close) it in the web shell');
  assert.ok(!BV.optionsHTML(unnamed, 'MYPC').includes('unname'), 'no display name: nothing to restore');
  const all = [CAST, { ...PATCH, favorite: true }, HACK];
  const plain = BV.filterBuilds([CAST, PATCH, HACK]).map(b => b.name);
  assert.deepEqual(BV.filterBuilds(all).map(b => b.name), ['g1_patch', ...plain.filter(n => n !== 'g1_patch')], 'the favorite first, then newest');
  assert.deepEqual(BV.filterBuilds(all, { fav: true }).map(b => b.name), ['g1_patch']);
  assert.equal(BV.facets(all).favorites, 1);
});

test('#1656 controller: ☆ stars (PUT), the row moves first, ★ Favorites filters; right-click opens the options; Rename… / restore', async () => {
  const env = fakeEnv({ routes: {
    // copies: the controller updates the rows it shows, the shared fixtures stay as they are for the other tests
    'GET /api/builds': () => ({ items: [{ ...CAST, display_name: '', label: CAST.original_title }, { ...PATCH }, { ...HACK }], indexing: false, sizing: 0 }),
    'PUT /api/builds/g2/g2_hack/favorite': b => ({ key: 'g2/g2_hack', favorite: b.favorite }),
    'PATCH /api/builds/g1/cast_g1': b => ({ key: 'g1/cast_g1', display_name: b.display_name, label: b.display_name || CAST.original_title }),
  } }), h = host();
  const ctl = BV.mount(h, env); await ctl.ready;
  const list = () => h.querySelector('[data-bv-list]').innerHTML;
  try {
    assert.ok(list().indexOf('g1/cast_g1') < list().indexOf('g2/g2_hack'));
    await ctl.onClick({ target: target({ bv: 'fav', key: 'g2/g2_hack' }) });
    assert.deepEqual(env.calls.find(c => c[0] === 'PUT'), ['PUT', '/api/builds/g2/g2_hack/favorite', { favorite: true }]);
    assert.ok(list().indexOf('g2/g2_hack') < list().indexOf('g1/cast_g1'), 'the favorite moves first');
    assert.match(list(), /★ Favorite: listed first and kept/);
    assert.match(h.innerHTML, /★ Favorites \(1\)/);
    ctl.onInput({ target: { dataset: { bvF: 'fav' }, type: 'checkbox', checked: true } });
    assert.match(list(), /g2_hack/); assert.doesNotMatch(list(), /cast_g1/);
    ctl.onInput({ target: { dataset: { bvF: 'fav' }, type: 'checkbox', checked: false } });
    // right-click a row: the options under it; Rename… from there opens the field
    ctl.onContext({ target: target({ key: 'g1/cast_g1' }), preventDefault() {}, stopPropagation() {} });
    assert.equal(ctl.st.opts, 'g1/cast_g1'); assert.match(list(), /data-bv-opts="g1\/cast_g1"/);
    await ctl.onClick({ target: target({ bv: 'rename', dataset: { key: 'g1/cast_g1' } }) });
    assert.equal(ctl.st.opts, null); assert.equal(ctl.st.renaming, 'g1/cast_g1');
    await ctl.onKey({ key: 'Enter', target: target({ rename: 'g1/cast_g1', value: 'Sonic Full Cast' }) });
    await flush();
    assert.match(list(), /data-bv="name"[^>]*>Sonic Full Cast</);
    // ✎ next to the name opens the field too; ↺ restores the original name ("")
    await ctl.onClick({ target: target({ bv: 'rename', key: 'g1/cast_g1' }) });
    assert.equal(ctl.st.renaming, 'g1/cast_g1');
    ctl.onKey({ key: 'Escape', target: target({ rename: 'g1/cast_g1', value: '' }) });
    await ctl.onClick({ target: target({ bv: 'unname', dataset: { key: 'g1/cast_g1' } }) });
    await flush();
    assert.deepEqual(env.calls.filter(c => c[0] === 'PATCH').map(c => c[2]), [{ display_name: 'Sonic Full Cast' }, { display_name: '' }]);
    assert.match(list(), /Original name restored: G1: cast as &#60;Wrestlers&#62;/);
  } finally { ctl.stop(); }
});

test('details ▸: fetched on open; 360° viewers load their GLB only when on screen; disposed on collapse', async () => {
  const env = fakeEnv(), h = host();
  const ctl = BV.mount(h, env); await ctl.ready;
  try {
    await ctl.onClick({ target: target({ bv: 'toggle', key: 'g1/cast_g1' }) });
    await flush();
    assert.ok(env.calls.some(c => c[1] === '/api/builds/g1/cast_g1/details'));
    const list = h.querySelector('[data-bv-list]');
    assert.match(list.innerHTML, /data-bv-det="g1\/cast_g1"[\s\S]*Characters inserted/);
    const tts = list.querySelectorAll('[data-bv-tt]');
    assert.equal(tts.length, 3, 'two viewers for Neo, one (preview only) for Agent Smith');
    assert.equal(env.stub.made.loads.length, 0, 'nothing loads before a viewer is on screen');
    const io = FakeIO.last;
    assert.equal(io.targets.size, 2, 'only viewers with a GLB are observed');
    io.fire(tts[0], true); await flush();
    assert.deepEqual(env.stub.made.loads, ['/api/characters/kane/file/targets/g1_neo.glb?token=t']);
    assert.equal(tts[0].dataset.state, 'loaded'); assert.equal(tts[0].children[0].tagName, 'CANVAS');
    assert.equal(env.stub.made.managers[0].modify('/api/characters/kane/file/targets/g1_neo.bin'), '/api/characters/kane/file/targets/g1_neo.bin?token=t',
      'a glTF\'s own buffers carry the token too');
    // the shared renderer draws the visible viewer (one WebGL context for every turntable), spinning it
    assert.equal(env.frames.length, 1); env.frames.shift()(1000);
    assert.equal(env.stub.made.renderers.length, 1); assert.equal(env.stub.made.renders, 1);
    const v = ctl.tts.views.get('g1/cast_g1|0|donor');
    assert.ok(Math.abs(v.pivot.rotation.y - 1000 * BV.SPIN) < 1e-9);
    io.fire(tts[0], false); env.frames.length = 0; ctl.tts.draw(2000);
    assert.equal(env.stub.made.renders, 1, 'off screen: not drawn');
    io.fire(tts[1], true); await flush();
    assert.equal(env.stub.made.loads[1], '/api/characters/g1_neo/file/g1_neo.glb?token=t');
    // a list redraw (poll, another row) keeps the loaded viewers: no second download
    ctl.drawList(); await flush();
    assert.equal(env.stub.made.loads.length, 2);
    assert.equal(h.querySelector('[data-bv-list]').querySelectorAll('[data-bv-tt]')[0].dataset.state, 'loaded');
    // collapse: every viewer of the build disposed (geometry freed, unobserved, renderer released)
    await ctl.onClick({ target: target({ bv: 'toggle', key: 'g1/cast_g1' }) });
    assert.equal(ctl.tts.views.size, 0);
    assert.ok(env.stub.made.disposedGeo >= 2, 'the loaded models\' geometry is disposed');
    assert.equal(io.targets.size, 0);
    assert.ok(env.stub.made.renderers[0].disposed);
    assert.doesNotMatch(h.querySelector('[data-bv-list]').innerHTML, /bv-det/);
  } finally { ctl.stop(); }
});

test('a GLB that fails to load keeps the preview picture', async () => {
  const env = fakeEnv({ routes: { 'GET /api/builds/g1/cast_g1/details': () => ({ ...DETAILS, characters: [{ ...DETAILS.characters[0], fitted_url: '/broken.glb', original: null }] }) } });
  const h = host(), ctl = BV.mount(h, env); await ctl.ready;
  try {
    await ctl.onClick({ target: target({ bv: 'toggle', key: 'g1/cast_g1' }) }); await flush();
    const tt = h.querySelector('[data-bv-list]').querySelector('[data-bv-tt]');
    FakeIO.last.fire(tt, true); await flush();
    assert.equal(tt.dataset.state, 'failed'); assert.equal(tt.children.length, 0, 'no canvas: the <img> preview stays');
  } finally { ctl.stop(); }
});

test('scheduled: flowchart on ▸ (three.js stub), Cancel, Edit = cancel + resubmit, Investigate', async () => {
  const env = fakeEnv(), h = host();
  const ctl = BV.mount(h, env); await ctl.ready;
  try {
    const sched = () => h.querySelector('[data-bv-sched]');
    assert.match(sched().innerHTML, /data-bv-jid="r1"[\s\S]*data-bv-jid="q1"[\s\S]*Recently finished[\s\S]*data-bv-jid="f1"/);
    assert.equal(h.querySelector('[data-bv-scount]').textContent, '1 running · 1 queued');
    // ▸ -> the flowchart: a canvas + labels under the job, nodes built on the stub once three.js is in
    await ctl.onClick({ target: target({ bv: 'jtoggle', jid: 'r1' }) }); await flush();
    const holder = sched().querySelector('[data-bv-flow]');
    assert.equal(holder.dataset.bvFlow, 'r1'); assert.equal(holder.children[0].tagName, 'CANVAS');
    ctl.drawSched(); await flush();                                     // three.js arrived: the graph is (re)built
    const f = ctl.flows.flows.get('r1');
    assert.ok(f.renderer && f.renderer.o.canvas === f.canvas, 'renders into the job\'s own canvas');
    assert.deepEqual(f.nodes.map(n => n.node.state), ['done', 'done', 'done', 'running', 'pending', 'pending', 'pending']);
    assert.deepEqual([...f.labels.children].map(l => l.textContent), ['queued', 'claimed · spark', 'scale · 1/1', 'retarget · 0/1', 'write', 'verify', 'done']);
    assert.equal(f.sparks.length, 1, 'a spark runs into the current node');
    assert.match(sched().innerHTML, /bv-fn-running">retarget/);
    // collapse disposes it
    await ctl.onClick({ target: target({ bv: 'jtoggle', jid: 'r1' }) });
    assert.equal(ctl.flows.flows.size, 0); assert.ok(f.renderer.disposed);
    // Cancel (confirmed) -> the existing cancel API
    await ctl.onClick({ target: target({ bv: 'jcancel', jid: 'q1' }) });
    assert.ok(env.calls.some(c => c[0] === 'POST' && c[1] === '/api/jobs/q1/cancel'));
    // Edit: the form, then Save & requeue -> POST .../edit with only what changed
    await ctl.onClick({ target: target({ bv: 'jedit', jid: 'q1' }) });
    assert.match(sched().innerHTML, /data-bv-edit="q1"/);
    const fields = sched().querySelectorAll('[data-bv-ef][data-jid="q1"], [data-bv-ej][data-jid="q1"]');
    fields.find(x => x.dataset.bvEf === 'slots').value = 'main';
    await ctl.onClick({ target: target({ bv: 'jsave', jid: 'q1' }) });
    assert.deepEqual(env.calls.find(c => c[1] === '/api/builds/scheduled/q1/edit'), ['POST', '/api/builds/scheduled/q1/edit', { input: { slots: 'main' } }]);
    assert.equal(ctl.st.editing, null);
    assert.equal(ctl.st.jmsg.get('q2'), 'Edited: replaces job q1 (slots)');
    // the running job can't be edited
    await ctl.onClick({ target: target({ bv: 'jedit', jid: 'r1' }) });
    assert.equal(ctl.st.editing, null);
    // Investigate: log tail, receipt, artifacts, fitting events, result
    await ctl.onClick({ target: target({ bv: 'jinv', jid: 'f1' }) }); await flush();
    const inv = sched().innerHTML;
    assert.match(inv, /Investigate job f1/); assert.match(inv, /boom happened/);
    assert.match(inv, /validation failed[\s\S]*no image/);
    assert.match(inv, /href="\/api\/artifacts\/b{64}">mod\.json/);
    assert.match(inv, /Kane -&#62; player[\s\S]*bv-fn-failed">write/);
    assert.match(inv, /<span class="bv-chip">failed<\/span> nope · mod <code>x<\/code>/);
    await ctl.onClick({ target: target({ bv: 'jinvclose', jid: 'f1' }) });
    assert.doesNotMatch(sched().innerHTML, /Investigate job f1/);
  } finally { ctl.stop(); }
});

test('a build\'s job opened from its details is investigated under Scheduled & running', async () => {
  const env = fakeEnv({ routes: { 'GET /api/builds/scheduled/jcast': () => ({ id: 'jcast', tool: 'characters', op: 'cast_swap', state: 'succeeded',
    log_tail: 'cast built', receipt: { id: 'rc1', validation_ok: true, problems: [] }, artifacts: [], result: { status: 'built', mod: 'cast_g1' } }) } });
  const h = host(), ctl = BV.mount(h, env); await ctl.ready;
  try {
    await ctl.onClick({ target: target({ bv: 'toggle', key: 'g1/cast_g1' }) }); await flush();
    await ctl.onClick({ target: target({ bv: 'jobopen', key: 'g1/cast_g1', dataset: { jid: 'jcast' } }) }); await flush();
    const sched = h.querySelector('[data-bv-sched]').innerHTML;
    assert.match(sched, /Investigating[\s\S]*data-bv-jid="jcast"[\s\S]*Investigate job jcast[\s\S]*cast built/);
    await ctl.onClick({ target: target({ bv: 'jinvclose', jid: 'jcast' }) });
    assert.doesNotMatch(h.querySelector('[data-bv-sched]').innerHTML, /jcast/);
  } finally { ctl.stop(); }
});

test('leaving the view stops the polls and frees every viewer', async () => {
  let visible = true;
  const env = fakeEnv({ visible: () => visible }), h = host();
  const ctl = BV.mount(h, env); await ctl.ready;
  try {
    await ctl.onClick({ target: target({ bv: 'toggle', key: 'g1/cast_g1' }) }); await flush();
    FakeIO.last.fire(h.querySelector('[data-bv-list]').querySelector('[data-bv-tt]'), true); await flush();
    assert.equal(ctl.tts.views.size, 3);
    visible = false; await ctl.tick();
    assert.equal(ctl.tts.views.size, 0); assert.equal(h.listeners.click, undefined);
  } finally { ctl.stop(); }
});

test('the web shell (and so the desktop app, which embeds it) has the Builds tab wired to the view', () => {
  const web = fs.readFileSync(path.join(__dirname, '../clients/web/index.html'), 'utf8');
  assert.match(web, /const tabs = \{ Library: library, Mods: modsView, Builds: buildsView, Sessions:/);
  assert.match(web, /<script src="\/viz\/mods-gallery\.js"><\/script>\r?\n<script src="\/viz\/builds\.js"><\/script>/);
  assert.match(web, /GBoxBuilds\.mount\(\$\("#buildsview"\), \{ api, here: window\.GBOX_LOCAL\?\.worker \|\| "auto"/);
  assert.match(web, /visible: \(\) => cur === "Builds" && !!\$\("#buildsview"\), launch: \(gid, x\) => gameMenuIO\(\)\.launch\(gid, x\)/);
  assert.ok(!/[^\r]\n/.test(web), 'CRLF line endings kept');
  const desktop = fs.readFileSync(path.join(__dirname, '../clients/desktop/index.html'), 'utf8');
  assert.match(desktop, /url\.searchParams\.set\("embedded", "1"\)/, 'the desktop app shows the web shell (top bar included)');
});

// 📷 Screenshot in the Builds tab follows the Mods gallery's rules (clients/web/viz/build-shot.js): another build of the
// same game running = the row asks, and nothing is launched, swapped or captured before the operator's second click.
test('📷 Screenshot: this build running = a frame now; another build running = a choice, never a silent swap', async () => {
  const CARDED = { ...CAST, card_id: 'c-cast' }, OTHER = { ...PATCH, card_id: 'c-patch' };
  let sessions = [{ session_id: 'w1-op', state: 'running', game_id: 'g1', mod: 'g1_patch~a1b2', collection_mod: 'g1_patch', started: 5 }];
  const env = fakeEnv({ wait: async () => {}, routes: {
    'GET /api/builds': () => ({ items: [CARDED, OTHER, HACK], indexing: false, sizing: 0 }),
    'GET /api/sessions': () => sessions,
    'POST /api/mods/c-patch/thumb': () => ({ id: 'c-patch' }), 'POST /api/mods/c-cast/thumb': () => ({ id: 'c-cast' }) } });
  const h = host(), ctl = BV.mount(h, env); await ctl.ready;
  const list = () => h.querySelector('[data-bv-list]').innerHTML;
  const acted = () => env.calls.filter(c => /\/thumb|\/swap$|^\/api\/jobs$/.test(c[1])).map(c => c[1]);
  try {
    assert.match(list(), /data-bv="shot" [^>]*aria-label="Screenshot">📷/);
    assert.match(BV.rowHTML(HACK, {}, {}), /data-bv="shot" disabled/, 'no mod card: nothing to add a picture to');
    await ctl.onClick({ target: target({ bv: 'shot', key: 'g1/cast_g1' }) });
    assert.deepEqual(acted(), [], 'first click: nothing launched, swapped or captured');
    assert.match(list(), /class="bv-shot" data-bv-key="g1\/cast_g1"[\s\S]*is running <b>Patch<\/b>, not this build/);
    assert.match(list(), /data-bv="shot-running"[^>]*>Capture from the running build instead \(adds to that build's card\)/);
    assert.match(list(), /data-bv="shot-switch"[^>]*>Switch to this build/);
    await ctl.onClick({ target: target({ bv: 'shot-running', key: 'g1/cast_g1' }) });
    assert.deepEqual(acted(), ['/api/mods/c-patch/thumb?append=true&session_id=w1-op']);
    assert.doesNotMatch(list(), /bv-shot"/);
    // the build that runs (a staged copy of it) is captured at once
    sessions = [{ session_id: 'w1-op', state: 'running', game_id: 'g1', mod: 'cast_g1~ff00', started: 6 }];
    await ctl.onClick({ target: target({ bv: 'shot', key: 'g1/cast_g1' }) });
    assert.deepEqual(acted().slice(1), ['/api/mods/c-cast/thumb?append=true&session_id=w1-op']);
  } finally { ctl.stop(); }
});

test('build-shot.js plan: exact build (staged / collection / live model), another build, nothing; ended sessions ignored', () => {
  const BS = require('../clients/web/viz/build-shot.js');
  const b = { game_id: 'g', name: 'm' };
  assert.equal(BS.plan(b, [{ state: 'running', game_id: 'g', mod: 'm~x', session_id: 'a' }]).kind, 'exact');
  assert.equal(BS.plan(b, [{ state: 'running', game_id: 'g', mod: 'z', live_mod: 'm', session_id: 'a' }]).kind, 'exact');
  assert.equal(BS.plan(b, [{ state: 'running', game_id: 'g', mod: 'm', live_mod: 'z', session_id: 'a' }]).kind, 'other');
  assert.equal(BS.plan(b, [{ state: 'ended', game_id: 'g', mod: 'm' }, { state: 'running', game_id: 'h', mod: 'm' }]).kind, 'none');
  assert.equal(BS.plan(b, [{ state: 'running', game_id: 'g', mod: 'm', stopping: true }]).kind, 'none');
  const p = BS.plan(b, [{ state: 'running', game_id: 'g', mod: 'old', started: 1, session_id: 'o' }, { state: 'running', game_id: 'g', mod: 'new', started: 2, session_id: 'n' }]);
  assert.deepEqual([p.kind, p.session.session_id, p.build], ['other', 'n', 'new'], 'the newest session of the game');
});
