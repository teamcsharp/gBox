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
function setup() {
  const timers = [];
  let id = 0;
  const elements = [];
  function element(tag) {
    const el = {
      tagName: tag.toUpperCase(), className: '', textContent: '', innerHTML: '', style: {},
      children: [], width: 0, height: 0, firstChild: null,
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
    clearTimeout: () => {}, setInterval: () => 0, clearInterval: () => {},
    requestAnimationFrame: fn => { timers.push({ fn, ms: 33 }); return ++id; },
    cancelAnimationFrame: () => {},
    Math, now: () => t,
  };
  // headless: pass a fake clock so the module skips the dynamic-import viewer and
  // uses the dependency-free 2D orbit fallback; the env supplies document/timers.
  const win = createPopup(env).mount({ now: () => t });
  const runTimers = n => { for (let i = 0; i < n; i++) { const tm = timers.shift(); if (!tm) break; t += tm.ms || 33; tm.fn(); } };
  return { env, body, elements, timers, win, element, advance: ms => { t += ms; }, runTimers };
}

test('popup opens for a 3D job, follows its progress and closes via the VCR effect', async () => {
  const x = setup();
  const j = job('characters', { op: 'use', character: 'amy' }, {
    id: 'a1', state: 'running', progress: { pct: 12, msg: 'decimating…' }, progress_log: ['import glb', 'decimating…'],
  });
  x.win.sync([j]);
  const root = x.body.children.find(c => c.className === 'gbox-pp');
  assert.ok(root, 'window mounted in the page');
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
