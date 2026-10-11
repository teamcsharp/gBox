const { test } = require('node:test');
const assert = require('node:assert/strict');
const createPopup = require('../clients/web/viz/process-popup.js');

// The UMD wrapper hands Node the factory; give it the same browser-shaped env the
// shells provide (window). One instance backs the pure-function tests below.
const popup = createPopup({ document: undefined, Math });
// The classifier and friends must survive a document-less env (pure functions only).

// ---------- classifier: which background jobs open the 3D process window ----------
const job = (tool, input = {}, extra = {}) => ({ id: 'j1', state: 'running', tool, input, ...extra });

test('Blender/GLB/model-prep tools open the popup', () => {
  for (const t of ['characters', 'session_swap', 'asset_convert', 'open_in_blender', 'blender_copy',
    'export_asset', 'extract_pso_model', 'extract_pso_area', 'bevy_scene', 'oot_models', 'rom_export', 'file_mod'])
    assert.equal(popup.classify(job(t)), true, t);
});

test('cheap read-only ops on those tools do not open the popup', () => {
  for (const op of ['list', 'get', 'coverage', 'environments', 'plan', 'status', 'search', 'summary'])
    assert.equal(popup.classify(job('characters', { op })), false, op);
  assert.equal(popup.classify(job('export_asset', { op: 'plan' })), false);
});

test('memory/cheat/analysis/runtime jobs never open the popup', () => {
  for (const t of ['session_op', 'graphics', 'launch_game', 'zelda', 'cheats', 'read_memory',
    'memory_search', 'analyze_binary', 'scan_library', 'get_frame', 'llm_complete', 'autoplay'])
    assert.equal(popup.classify(job(t, { op: 'anything' })), false, t);
});

test('an unclassified tool still opens when its live progress mentions mesh work', () => {
  assert.equal(popup.classify(job('some_future_tool', {}, { progress: { msg: 'decimating to 3000 triangles' } })), true);
  assert.equal(popup.classify(job('some_future_tool', {}, { progress_log: ['step', 'retarget skeleton onto mesh'] })), true);
  assert.equal(popup.classify(job('some_future_tool', {}, { progress: { msg: 'scanning library' } })), false);
});

test('finished or queued-away jobs are ignored', () => {
  assert.equal(popup.classify(job('characters', {}, { state: 'succeeded' })), false);
  assert.equal(popup.classify(job('characters', {}, { state: 'failed' })), false);
  assert.equal(popup.classify(job('characters', {}, { state: 'cancelled' })), false);
  assert.equal(popup.classify(null), false);
});

// ---------- picking which live job the window follows ----------
test('a running job wins over a queued one, newest activity breaks ties', () => {
  const queued = job('characters', {}, { id: 'q', state: 'queued', created: 500 });
  const running = job('characters', {}, { id: 'r', state: 'running', progress: { ts: 100 } });
  const newer = job('asset_convert', {}, { id: 'n', state: 'running', progress: { ts: 900 } });
  const { job: first, others } = popup.pick([queued, running, newer]);
  assert.equal(first.id, 'n');                       // running beats queued, then most recent progress
  assert.equal(others, 2);
  assert.equal(popup.pick([]).job, null);
});

test('the window title names the tool, op and model', () => {
  assert.equal(popup.title(job('characters', { op: 'use', character: 'sa2_amy_rose' })),
    'characters · use · sa2_amy_rose');
  assert.equal(popup.title(job('asset_convert')), 'asset_convert');
});

test('the characters op=use job links to the collection GLB being processed', () => {
  assert.equal(popup.modelPath(job('characters', { op: 'use', character: 'sa2_amy_rose' })),
    '/api/characters/sa2_amy_rose/model');
  assert.equal(popup.modelPath(job('asset_convert', { path: 'x.glb' })), null);
  // a session swap / other model tool naming a collection character follows that GLB too
  assert.equal(popup.modelPath(job('session_swap', { character: 'sa2_amy_rose' })), '/api/characters/sa2_amy_rose/model');
  assert.equal(popup.modelPath(job('read_memory', { character: 'sa2_amy_rose' })), null);
});

// ---------- live mesh-change view: the worker's own stage lines drive what the model shows ----------
test('decimation lines with both counts give the kept share and a label', () => {
  const fx = popup.stageEffect('Amy: decimating 12000 -> 8000 triangles');
  assert.equal(fx.kind, 'decimate'); assert.equal(fx.from, 12000); assert.equal(fx.to, 8000);
  assert.ok(Math.abs(fx.ratio - 8000 / 12000) < 1e-9);
  assert.equal(fx.label, 'decimate 12,000 → 8,000 tris');
  assert.ok(Math.abs(popup.decimateRatio(fx, 999) - 2 / 3) < 1e-9);
});

test('decimation to a target count is scaled against the loaded mesh', () => {
  const fx = popup.stageEffect("Too big (90000 > 60000 bytes): decimating to ~4000 triangles");
  assert.equal(fx.kind, 'decimate'); assert.equal(fx.to, 4000); assert.equal(fx.ratio, null);
  assert.equal(popup.decimateRatio(fx, 16000), 0.25);
  assert.equal(popup.decimateRatio(fx, 0), 0.5);                         // mesh not loaded yet
  assert.equal(popup.decimateRatio(popup.stageEffect("Writing Leon's packs (textures 256px, decimated)"), 100), 0.5);
  assert.equal(popup.decimateRatio(popup.stageEffect('decimating 100 -> 1 triangles'), 1e6), 0.02);  // never empty
});

test('retarget and rescale stages are recognised; unrelated stages are not', () => {
  assert.deepEqual(popup.stageEffect("Retargeting Amy Rose onto Leon's skeleton"), { kind: 'retarget', label: "retarget → Leon's skeleton" });
  assert.deepEqual(popup.stageEffect('Retargeting Amy onto the wrestler skeleton'), { kind: 'retarget', label: 'retarget → the wrestler skeleton' });
  assert.equal(popup.stageEffect('Retargeting onto x (52 bones)').label, 'retarget → x');
  assert.equal(popup.stageEffect('Rescaling to the slot height').kind, 'rescale');
  for (const m of ['Building the disc image x.iso', 'Vanilla disc image from a.gcz', '', null, undefined])
    assert.equal(popup.stageEffect(m), null, String(m));
  assert.equal(popup.decimateRatio(null, 10), 1);
});

test('every writer wording of decimate / simplify / fit / retarget drives a stage', () => {
  const D = (m) => popup.stageEffect(m);
  // oot_swap / sm64_swap / ninja_swap name the model, then give only the target
  let fx = D('Decimating Amy Rose -> 4000 triangles (Blender)');
  assert.equal(fx.kind, 'decimate'); assert.equal(fx.to, 4000); assert.equal(fx.ratio, null);
  assert.equal(fx.label, 'decimate → 4,000 tris'); assert.equal(popup.decimateRatio(fx, 16000), 0.25);
  assert.equal(D('Decimating the body -> 3000 triangles (Blender)').to, 3000);
  assert.equal(D('Decimating Amy to 1500 triangles (Blender)').to, 1500);
  fx = D('Simplifying the props 300 -> 200 triangles (Blender)');
  assert.equal(fx.kind, 'decimate'); assert.equal(fx.from, 300); assert.equal(fx.to, 200);
  // budget fitting is a decimation; fitting onto a skeleton / body / nodes is a retarget
  assert.deepEqual(D("Fitting 3 parts into the game's vertex/face budget (Blender, pass 1)"),
    { kind: 'decimate', ratio: 0.5, label: 'fit to budget' });
  assert.equal(D("Fitting textures and triangles into Mario's data (64x32 RGBA16 max)").kind, 'decimate');
  assert.deepEqual(D("Fitting Amy onto Cloud's field skeleton"), { kind: 'retarget', label: "retarget → Cloud's field skeleton" });
  assert.deepEqual(D("Fitting Amy to Sonic's 22 nodes"), { kind: 'retarget', label: "retarget → Sonic's 22 nodes" });
  assert.equal(D('Fitting Amy to the HUmar body (40 nodes)').label, 'retarget → the HUmar body');
  assert.equal(D('Fitting Amy onto Aya (casual dress)').label, 'retarget → Aya');
  assert.equal(D('Fitting the character onto torso, legs').label, 'retarget → torso, legs');
  // '4000 to the slot' is not a triangle count; still a plain rescale
  assert.equal(D('Rescaling 4000 to the slot height').kind, 'rescale');
});

test("the stage parser covers every progress line gBox's writers actually emit", () => {
  const fs = require('node:fs'), path = require('node:path');
  const dir = path.join(__dirname, '..', 'gbox');
  const NUMERIC = /tris|target|budget|len\(|count|^n$|^k$|rnd|btarget|PROP|attempt/i;
  const seen = [];
  for (const f of fs.readdirSync(dir).filter((n) => n.endsWith('.py'))) {
    const src = fs.readFileSync(path.join(dir, f), 'utf8');
    for (const m of src.matchAll(/progress\([^"\n]*?f?"([^"\n]*)"/g)) {
      const line = m[1].replace(/\{([^{}]*)\}/g, (_, e) => (NUMERIC.test(e.trim()) ? '1200' : 'Amy'));
      let want = null;
      if (/decimat|simplif/i.test(line) || /\bfitting\b.*\binto\b/i.test(line)) want = 'decimate';
      else if (/retarget/i.test(line) || /\bfitting\b.*\b(onto|to)\b/i.test(line)) want = 'retarget';
      if (!want) continue;
      seen.push(`${f}: ${line}`);
      const fx = popup.stageEffect(line);
      assert.ok(fx, `${f}: no stage for "${line}"`);
      assert.equal(fx.kind, want, `${f}: "${line}"`);
      if (want === 'retarget') assert.notEqual(fx.label, 'retarget', `${f}: no target named in "${line}"`);
      if (want === 'decimate' && /\d+\s*tri/i.test(line)) assert.ok(fx.to > 0, `${f}: lost the triangle target in "${line}"`);
    }
  }
  assert.ok(seen.length >= 15, `expected the writers' progress lines, found ${seen.length}`);
});

// ---------- VCR close effect timeline ----------
test('VCR effect runs tracking static, collapse to a line, then finishes', () => {
  let t = 1000;
  const now = () => t;
  const vcr = popup.createVcr(now);
  vcr.start();
  assert.equal(vcr.step().phase, 'tracking');
  t += 350; assert.equal(vcr.step().phase, 'tracking'); assert.ok(vcr.step().p > 0.4);
  t += 400; assert.equal(vcr.step().phase, 'collapse');
  t += 260; assert.equal(vcr.step().phase, 'hold');
  t += 61; const end = vcr.step();
  assert.equal(end.phase, 'done'); assert.equal(end.done, true);
});

// ---------- the popup window lifecycle: open on a job, live updates, VCR close, reopen ----------
function setup(options = {}) {
  const timers = [];
  const intervals = [];
  let id = 0;
  const elements = [];
  function element(tag) {
    const el = {
      tagName: tag.toUpperCase(), className: '', textContent: '', innerHTML: '', style: {},
      children: [], width: 0, height: 0, firstChild: null, attributes: {},
      setAttribute(k, v) { this.attributes[k] = String(v); },
      classList: {
        add(...cs) { const s = new Set(el.className.split(/\s+/).filter(Boolean)); cs.forEach(c => s.add(c)); el.className = [...s].join(' '); },
        remove(...cs) { const s = new Set(el.className.split(/\s+/).filter(Boolean)); cs.forEach(c => s.delete(c)); el.className = [...s].join(' '); },
        contains(c) { return el.className.split(/\s+/).includes(c); },
      },
      append(...c) { for (const ch of c) { this.children.push(ch); ch.parent = this; } this.firstChild = this.children[0] || null; },
      insertBefore(n, ref) { this.children.unshift(n); n.parent = this; this.firstChild = this.children[0] || null; },
      remove() { this.removed = true; if (this.parent) this.parent.children = this.parent.children.filter(c => c !== this); },
      onclick: null, getContext: null,
    };
    elements.push(el);
    return el;
  }
  const head = element('head'), body = element('body');
  // minimal 2D-context stub so the VCR overlay effect actually animates and finishes
  const ctxStub = new Proxy({}, { get: (t, k) => (k === 'fillStyle' || k === 'font' || k === 'globalAlpha' ? t[k] : () => {}), set: (t, k, v) => (t[k] = v, true) });
  const origCreate = element;
  const createElement = tag => { const el = origCreate(tag); el.getContext = () => ctxStub; return el; };
  let t = 0;
  const env = {
    document: { createElement, head, body },
    setTimeout: (fn, ms) => { timers.push({ fn, ms }); return ++id; },
    clearTimeout: () => {}, setInterval: fn => { intervals.push(fn); return ++id; }, clearInterval: () => {},
    requestAnimationFrame: fn => { timers.push({ fn, ms: 33 }); return ++id; },
    cancelAnimationFrame: () => {},
    Math, now: () => t,
  };
  // headless: pass a fake clock so the module skips the dynamic-import viewer and
  // uses the dependency-free 2D orbit fallback; the env supplies document/timers.
  const win = createPopup(env).mount({ now: () => t, ...options });
  const runTimers = n => { for (let i = 0; i < n; i++) { const tm = timers.shift(); if (!tm) break; t += tm.ms || 33; tm.fn(); } };
  return { env, body, elements, timers, intervals, win, element, advance: ms => { t += ms; }, runTimers };
}

test('popup opens for a 3D job, follows its progress and closes via the VCR effect', async () => {
  const x = setup();
  const j = job('characters', { op: 'use', character: 'amy' }, {
    id: 'a1', state: 'running', progress: { pct: 12, msg: 'decimating…' }, progress_log: ['import glb', 'decimating…'],
  });
  x.win.sync([j]);
  const root = x.body.children.find(c => c.className === 'gbox-pp');
  assert.ok(root, 'window mounted in the page');
  assert.equal(root.attributes.role, 'dialog', 'native surface cutouts can discover the popup');
  const deep = (el) => [el, ...el.children.flatMap(deep)];               // all descendants
  const title = deep(root).find(c => c.tagName === 'B');
  assert.equal(title.textContent, 'characters · use · amy');
  assert.ok(deep(root).some(c => c.className === 'pp-stage'), '3D stage present');

  // progress updates flow into the bar and the ticker without remounting
  const before = root;
  x.win.sync([job('characters', { op: 'use', character: 'amy' }, {
    id: 'a1', state: 'running', progress: { pct: 80, msg: 'retargeting…' }, progress_log: ['import glb', 'decimating…', 'retargeting…'],
  })]);
  assert.equal(x.body.children.find(c => c.className === 'gbox-pp'), before, 'same window instance');
  const msg = deep(root).find(c => c.className === 'pp-msg');
  assert.equal(msg.textContent, 'retargeting…');

  // job ends: the window plays the VCR close (animated by timers) and removes itself
  x.win.sync([]);
  assert.equal(root.className, 'gbox-pp pp-closing', 'VCR close started');
  x.runTimers(40);                                                                 // run the animation loop to completion
  assert.equal(root.removed, true, 'window removed after the effect');

  // a later 3D job reopens the window
  x.win.sync([job('asset_convert', {}, { id: 'b2', state: 'running', progress: { pct: 5, msg: 'converting' } })]);
  assert.ok(x.body.children.some(c => c.className === 'gbox-pp' && !c.removed), 'window reopened');
  x.win.dispose();
  assert.equal(x.body.children.filter(c => c.className === 'gbox-pp' && !c.removed).length, 0, 'dispose removes the window');
});

test('the ✕ button hides this task instantly and it stays hidden while it runs', async () => {
  const x = setup();
  const j = job('characters', { op: 'use', character: 'amy' }, { id: 'a1', state: 'running', progress: { pct: 10, msg: 'rigging' } });
  x.win.sync([j]);
  const root = x.body.children.find(c => c.className === 'gbox-pp');
  const deep = (el) => [el, ...el.children.flatMap(deep)];
  const close = deep(root).find(c => c.tagName === 'BUTTON');
  close.onclick();
  assert.equal(root.removed, true, 'closed without the VCR animation');
  x.win.sync([job('characters', { op: 'use', character: 'amy' }, { id: 'a1', state: 'running', progress: { pct: 20, msg: 'still rigging' } })]);
  assert.ok(!x.body.children.some(c => c.className === 'gbox-pp' && !c.removed), 'suppressed task does not reopen');
  x.win.sync([job('asset_convert', {}, { id: 'c3', state: 'queued' })]);
  assert.ok(x.body.children.some(c => c.className === 'gbox-pp' && !c.removed), 'a different task still opens');
  x.win.dispose();
});

test('the popup labels the mesh operation running now and clears it on other stages', () => {
  const x = setup();
  const deep = (el) => [el, ...el.children.flatMap(deep)];
  const j = (msg) => job('characters', { op: 'use', character: 'amy' }, { id: 'op1', progress: { pct: 30, msg } });
  x.win.sync([j('Amy: decimating 12000 -> 8000 triangles')]);
  const root = x.body.children.find(c => c.className === 'gbox-pp');
  const op = deep(root).find(c => c.className === 'pp-op');
  assert.ok(op, 'stage label element exists');
  assert.equal(op.textContent, 'decimate 12,000 → 8,000 tris');
  x.win.sync([j("Retargeting Amy onto Leon's skeleton")]);
  assert.equal(op.textContent, "retarget → Leon's skeleton");
  x.win.sync([j('Building the disc image x.iso')]);
  assert.equal(op.textContent, '');
});

test('the same job updates its queued/running chip and changing companion count', () => {
  const x = setup();
  const queued = job('characters', { character: 'A' }, { id: 'same', state: 'queued' });
  x.win.sync([queued]);
  const root = x.body.children.find(c => c.className === 'gbox-pp');
  const deep = el => [el, ...el.children.flatMap(deep)];
  const [state, more] = deep(root).filter(c => c.className === 'pp-chip');
  assert.equal(state.textContent, 'queued'); assert.equal(more.style.display, 'none');
  x.win.sync([{ ...queued, state: 'running' }, job('asset_convert', {}, { id: 'other', state: 'queued' })]);
  assert.equal(x.body.children.find(c => c.className === 'gbox-pp'), root, 'no remount on state transition');
  assert.equal(state.textContent, 'processing'); assert.ok(state.classList.contains('run'));
  assert.equal(more.textContent, '+1 more'); assert.equal(more.style.display, '');
  x.win.sync([queued]);
  assert.equal(state.textContent, 'queued'); assert.ok(!state.classList.contains('run'));
  assert.equal(more.textContent, '+0 more'); assert.equal(more.style.display, 'none');
  x.win.dispose();
});

test('non-3D jobs never mount anything', () => {
  const x = setup();
  x.win.sync([job('session_op', { op: 'save_state' }, { state: 'running' }), job('graphics', { op: 'get' }, { state: 'running' })]);
  assert.equal(x.body.children.filter(c => c.className === 'gbox-pp').length, 0);
  x.win.dispose();
});

// ---------- both shells include the shared module and feed it ----------
const fs = require('node:fs');
test('desktop and web both include process-popup.js', () => {
  const desktop = fs.readFileSync(require.resolve('../clients/desktop/index.html'), 'utf8');
  const web = fs.readFileSync(require.resolve('../clients/web/index.html'), 'utf8');
  assert.ok(desktop.includes('../web/viz/process-popup.js'), 'desktop script tag');
  assert.ok(web.includes('/viz/process-popup.js'), 'web script tag');
  assert.ok(desktop.includes('processPopupSync'), 'desktop feeds the popup from its existing jobs poll');
  assert.ok(web.includes('GBoxProcessPopup.mount'), 'web mounts the popup');
});

const tick = () => new Promise(resolve => setImmediate(resolve));
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

test('the shared jobs poll coalesces slow ticks, retries rejection and ignores disposed results', async () => {
  const requests = [];
  const x = setup({ fetchJobs: () => { const d = deferred(); requests.push(d); return d.promise; } });
  await tick();
  for (let i = 0; i < 30; i++) x.intervals[0]();
  assert.equal(requests.length, 1);
  requests[0].reject(new Error('offline')); await tick();
  x.intervals[0](); await tick();
  assert.equal(requests.length, 2, 'failed fetch released the gate');
  x.win.dispose();
  requests[1].resolve([job('characters', { character: 'late' })]); await tick();
  assert.equal(x.body.children.length, 0, 'late result did not reopen a disposed popup');
  assert.ok(x.env.document.head.children.every(e => e.removed), 'dispose removes its stylesheet');
});

// Browser-shaped Three.js fixture; tests use the real asynchronous viewer and GLTF callbacks.
function viewerFixture() {
  const loads = [], rendered = [], scenes = [];
  class Vector {
    constructor() { this.x = 1; }
    set() { return this; } setScalar(v) { this.x = v; return this; }
    copy() { return this; } multiplyScalar() { return this; } length() { return 2; }
  }
  class Object3D {
    constructor() { this.children = []; this.userData = {}; this.position = new Vector(); this.scale = new Vector(); this.rotation = { x: 0, y: 0 }; }
    add(o) { if (o.parent) o.parent.remove(o); o.parent = this; this.children.push(o); }
    remove(o) { this.children = this.children.filter(c => c !== o); o.parent = null; }
    traverse(fn) { fn(this); for (const c of this.children) c.traverse(fn); }
    updateMatrixWorld() {}
  }
  class Scene extends Object3D { constructor() { super(); scenes.push(this); } }
  class Box {
    union() { return this; } copy() { return this; } applyMatrix4() { return this; }
    isEmpty() { return false; } getCenter(v) { return v; } getSize(v) { return v; }
  }
  class Geometry {
    constructor() { this.attributes = { position: { count: 12 } }; this.disposals = 0; this.boundingBox = {}; }
    dispose() { this.disposals++; } setDrawRange() {} computeBoundingBox() {}
  }
  class Material {
    constructor() { this.disposals = 0; this.opacity = 1; this.transparent = false; this.depthWrite = true; this.color = { set() {} }; }
    dispose() { this.disposals++; }
  }
  class Line extends Object3D { constructor(g, m) { super(); this.geometry = g; this.material = m; this.isLineSegments = true; } }
  class Camera extends Object3D { lookAt() {} }
  const THREE = {
    Scene, Group: Object3D, HemisphereLight: Object3D, DirectionalLight: Object3D,
    PerspectiveCamera: Camera, Box3: Box, Vector3: Vector,
    EdgesGeometry: Geometry, IcosahedronGeometry: Geometry, WireframeGeometry: Geometry,
    LineBasicMaterial: Material, LineSegments: Line,
    WebGLRenderer: class {
      constructor() { this.domElement = { style: {}, remove() { this.removed = true; } }; }
      setPixelRatio() {} setSize() {} dispose() {}
      render(scene) { rendered.push(scene); }
    },
  };
  class GLTFLoader { load(path, callback) { loads.push({ path, callback }); } }
  function model(name) {
    const scene = new Object3D(), mesh = new Object3D();
    const geometry = new Geometry(), material = new Material();
    const texture = { isTexture: true, disposals: 0, dispose() { this.disposals++; } };
    material.map = texture; material.normalMap = texture;
    mesh.isMesh = true; mesh.geometry = geometry; mesh.material = [material, material];
    scene.name = name; scene.add(mesh);
    return { scene, mesh, geometry, material, texture };
  }
  return { modules: { THREE, GLTFLoader }, loads, rendered, scenes, model,
    current: () => scenes.at(-1)?.children.find(c => c.userData.model)?.userData.model || null };
}

test('module imports use the latest same-job model and stage; closed imports never mount', async () => {
  const v = viewerFixture(), modules = deferred();
  const x = setup({ loadModules: () => modules.promise });
  x.win.sync([job('characters', { character: 'old' }, { id: 'same' })]);
  x.win.sync([job('characters', { character: 'new' }, { id: 'same', progress: { msg: 'Rescaling the model' } })]);
  modules.resolve(v.modules); await tick();
  assert.deepEqual(v.loads.map(l => l.path), ['/api/characters/new/model']);
  assert.equal(x.win.viewer().fx.kind, 'rescale');
  x.win.dispose();

  const late = deferred(), y = setup({ loadModules: () => late.promise });
  y.win.sync([job('characters', { character: 'closed' })]); y.win.dispose();
  late.resolve(v.modules); await tick();
  assert.equal(v.loads.length, 1, 'closed import never constructs another viewer');
});

test('out-of-order models, replacements and close dispose real resources without stale presentation', async () => {
  const v = viewerFixture(), x = setup({ loadModules: async () => v.modules });
  const j = (name, msg = '') => job('characters', { character: name }, { progress: { msg } });
  x.win.sync([j('A')]); await tick();
  x.win.sync([j('B', 'Decimating 12 -> 6 triangles')]);
  const A = v.model('A'), B = v.model('B');
  v.loads[1].callback(B); v.loads[0].callback(A);
  assert.equal(v.current(), B.scene, 'latest B remains displayed after A finishes');
  assert.equal(A.geometry.disposals, 1); assert.equal(A.material.disposals, 1); assert.equal(A.texture.disposals, 1);
  assert.equal(B.material.opacity, 0.22, 'live decimation preview applied');
  const footer = x.elements.find(e => e.className === 'pp-f');
  assert.equal(footer.textContent, 'Donor model preview · stage effects illustrate reported progress');
  x.win.sync([j('C')]);
  assert.equal(B.material.opacity, 1, 'preview material restored before disposal');
  assert.equal(B.geometry.disposals, 1); assert.equal(B.material.disposals, 1); assert.equal(B.texture.disposals, 1);
  const C = v.model('C'); x.win.dispose(); v.loads[2].callback(C);
  assert.equal(C.geometry.disposals, 1); assert.equal(C.material.disposals, 1); assert.equal(C.texture.disposals, 1);
  assert.equal(x.body.children.length, 0, 'late callback cannot reopen a closed window');
});

test('a job with no model clears its predecessor instead of mislabelling the old model', async () => {
  const v = viewerFixture(), x = setup({ loadModules: async () => v.modules });
  x.win.sync([job('characters', { character: 'A' })]); await tick();
  const A = v.model('A'); v.loads[0].callback(A);
  x.win.sync([job('asset_convert', {}, { id: 'unknown-model' })]);
  assert.equal(x.win.viewer().path, null); assert.equal(v.current(), null);
  assert.match(x.elements.find(e => e.className === 'pp-f').textContent, /^Progress illustration/);
  assert.equal(A.geometry.disposals, 1);
  x.win.dispose();
});

test('decimation restores a shared material once across meshes and repeated preview/replacement', async () => {
  const v = viewerFixture(), x = setup({ loadModules: async () => v.modules });
  const j = (character, msg) => job('characters', { character }, { progress: { msg } });
  const decimating = j('A', 'Decimating 12 -> 6 triangles');
  x.win.sync([decimating]); await tick();
  const A = v.model('A'), shared = v.model('another');
  shared.mesh.material = A.mesh.material; A.scene.add(shared.mesh);
  A.material.opacity = 0.65;
  const original = () => {
    assert.equal(A.material.opacity, 0.65);
    assert.equal(A.material.transparent, false);
    assert.equal(A.material.depthWrite, true);
  };
  v.loads[0].callback(A); assert.equal(A.material.opacity, 0.22);
  x.win.sync([j('A', 'Building the disc image')]); original();
  x.win.sync([decimating]); assert.equal(A.material.opacity, 0.22);
  x.win.sync([j('B', 'Loading the donor')]); original();
  assert.equal(A.material.disposals, 1, 'shared material disposed once on replacement');
  assert.equal(A.texture.disposals, 1);
  x.win.dispose();
});

test('web owns one authenticated popup poller and embedded pages leave ownership to desktop', () => {
  const vm = require('node:vm');
  const web = fs.readFileSync(require.resolve('../clients/web/index.html'), 'utf8');
  const start = web.indexOf('<script>', web.indexOf('<script src="/viz/process-popup.js"></script>')) + '<script>'.length;
  const script = web.slice(start, web.indexOf('</script>', start));
  for (const embedded of [false, true]) {
    let mounts = 0, disposed = 0, options, pagehide;
    const ctx = { location: { search: embedded ? '?embedded=1' : '' }, URLSearchParams,
      window: { addEventListener(name, fn) { assert.equal(name, 'pagehide'); pagehide = fn; } },
      GBoxProcessPopup: { mount(opts) { mounts++; options = opts; return { dispose() { disposed++; } }; } },
      api: path => path, tq: () => 'token=fixture-token' };
    vm.runInNewContext(script, ctx);
    assert.equal(mounts, embedded ? 0 : 1);
    if (!embedded) {
      assert.equal(options.fetchJobs(), '/api/jobs?state=queued,running&limit=100');
      assert.equal(options.assetUrl('/api/characters/amy/model'), '/api/characters/amy/model?token=fixture-token');
      assert.equal(options.assetUrl('/model?x=1'), '/model?x=1&token=fixture-token');
      pagehide(); assert.equal(disposed, 1);
    }
  }
});
