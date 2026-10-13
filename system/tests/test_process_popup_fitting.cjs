const { test } = require('node:test');
const assert = require('node:assert/strict');
const createPopup = require('../clients/web/viz/process-popup.js');

const popup = createPopup({ document: undefined, Math });

// job.fitting as the server folds it from gbox/fit_events.py events
const FITTING = {
  order: ['fighter:KAS', 'fighter:RYU', 'fighter:TIN'], current: 'fighter:RYU', updated: 30,
  models: {
    'fighter:KAS': { label: 'Amy → Kasumi', state: 'done', current: 'write', updated: 20,
      snapshot: '/api/jobs/j1/fitting/files/kas-decimate-3.glb', snapshot_stage: 'decimate',
      stages: { scale: { state: 'done', data: { scale: 1.23456, head_scale: 1.1 } },
        retarget: { state: 'done', data: { roles: 15, vertices: 12000 } },
        proportion: { state: 'done', data: { applied: true, height: 1.1, head: 1.3, torso_width: 1, roles_adjusted: ['l_fore'] } },
        weights: { state: 'done', data: { vertices_reduced: 312, max_influences: 2 } },
        decimate: { state: 'done', data: { from: 12000, triangles: 8000 } },
        encode: { state: 'done', data: { chr_bytes: 40960, bin_bytes: 8192 } },
        write: { state: 'done', data: { mod: 'cast_doa2_x' } } } },
    'fighter:RYU': { label: 'Sonic → Ryu', state: 'running', current: 'proportion', updated: 30,
      snapshot: '/api/jobs/j1/fitting/files/ryu-retarget-5.glb', snapshot_stage: 'retarget',
      stages: { scale: { state: 'done', data: { scale: 0.9 } }, retarget: { state: 'done', data: { roles: 12 } },
        proportion: { state: 'skipped', data: { profile: 'none' } } } },
    'fighter:TIN': { label: 'Knuckles → Tina', state: 'pending', stages: {} },
  },
};
const job = (extra = {}) => ({ id: 'j1', state: 'running', tool: 'characters', input: { op: 'cast_swap' },
  progress: { pct: 40, msg: 'RYU: Sonic → Ryu: proportion (skipped)' }, fitting: FITTING, ...extra });

test('every planned model is a row with its stages in pipeline order and short numbers', () => {
  const rows = popup.fittingRows(job());
  assert.deepEqual(rows.map(r => r.key), ['fighter:KAS', 'fighter:RYU', 'fighter:TIN']);
  assert.deepEqual(rows[0].stages.map(s => s.name), popup.STAGES);
  const t = Object.fromEntries(rows[0].stages.map(s => [s.name, s.text]));
  assert.equal(t.scale, '×1.23 · head ×1.1');
  assert.equal(t.retarget, '15 roles · 12,000 verts');
  assert.equal(t.proportion, 'height ×1.1 · head ×1.3 · 1 parts');
  assert.equal(t.weights, '312 verts → 2 bones');
  assert.equal(t.decimate, '12,000 → 8,000 tris');
  assert.equal(t.encode, '48 KB');
  assert.equal(t.write, 'cast_doa2_x');
  assert.equal(rows[1].stages.find(s => s.name === 'proportion').text, 'no profile');
  assert.equal(rows[2].stages.length, 0);
  assert.deepEqual(popup.fittingRows({}), []);
});

test('the summary counts finished models and names the one being fitted', () => {
  const s = popup.fittingSummary(job());
  assert.equal(s.total, 3); assert.equal(s.done, 1); assert.equal(s.failed, 0); assert.equal(s.current.key, 'fighter:RYU');
});

test('the preview follows the current model\'s snapshot, else the newest one, else the donor GLB', () => {
  assert.equal(popup.snapshotOf(job()), '/api/jobs/j1/fitting/files/ryu-retarget-5.glb');
  assert.equal(popup.modelPath(job()), '/api/jobs/j1/fitting/files/ryu-retarget-5.glb');
  const noCur = JSON.parse(JSON.stringify(FITTING)); noCur.current = 'fighter:TIN';
  assert.equal(popup.snapshotOf(job({ fitting: noCur })), '/api/jobs/j1/fitting/files/ryu-retarget-5.glb');
  assert.equal(popup.modelPath({ tool: 'characters', input: { character: 'amy' } }), '/api/characters/amy/model');
});

test('a job that is fitting models always opens the window, whatever its tool', () => {
  assert.equal(popup.classify(job({ tool: 'some_tool', input: { op: 'list' } })), true);
  assert.equal(popup.classify(job({ state: 'succeeded' })), false);
});

test('the list escapes labels and marks stage states', () => {
  const evil = JSON.parse(JSON.stringify(FITTING)); evil.models['fighter:TIN'].label = '<img src=x onerror=alert(1)>';
  const html = popup.fittingHTML(job({ fitting: evil }));
  assert.ok(!html.includes('<img'));
  assert.match(html, /<b>Fitting<\/b> 1\/3 models/);
  assert.match(html, /pp-fr running cur" title="fighter:RYU"/);
  assert.match(html, /<i class="skipped" title="proportion: no profile">P<\/i>/);
  assert.match(html, /<i class="todo" title="weights">W<\/i>/);
  assert.match(html, /<span class="pp-fn">proportion · no profile<\/span>/);
  assert.equal(popup.fittingHTML({}), '');
});

function setup() {
  const elements = [];
  function element(tag) {
    const el = { tagName: tag.toUpperCase(), className: '', textContent: '', innerHTML: '', style: {}, children: [], attributes: {},
      setAttribute(k, v) { this.attributes[k] = String(v); },
      classList: { add() {}, remove() {}, contains() { return false; } },
      append(...c) { for (const ch of c) { this.children.push(ch); ch.parent = this; } this.firstChild = this.children[0] || null; },
      insertBefore(n) { this.children.unshift(n); n.parent = this; this.firstChild = this.children[0]; },
      remove() { this.removed = true; }, getContext: () => new Proxy({}, { get: () => () => {} }) };
    elements.push(el); return el;
  }
  const env = { document: { createElement: element, head: element('head'), body: element('body') },
    setTimeout: () => 1, clearTimeout: () => {}, setInterval: () => 1, clearInterval: () => {},
    requestAnimationFrame: () => 1, cancelAnimationFrame: () => {}, Math };
  const win = createPopup(env).mount({ now: () => 0 });
  return { env, win, elements };
}

test('the window shows the fitting list and labels the current stage over the 3D view', () => {
  const x = setup();
  x.win.sync([job()]);
  const fit = x.elements.find(e => e.className === 'pp-fit'), op = x.elements.find(e => e.className === 'pp-op');
  assert.match(fit.innerHTML, /Sonic → Ryu/);
  assert.equal(op.textContent, 'proportion · 2/3');
  const later = JSON.parse(JSON.stringify(FITTING));
  later.models['fighter:RYU'].state = 'done'; later.models['fighter:RYU'].current = 'write';
  later.models['fighter:RYU'].stages.write = { state: 'done', data: { mod: 'm' } };
  later.current = 'fighter:TIN'; later.models['fighter:TIN'].current = 'scale'; later.models['fighter:TIN'].state = 'running';
  later.models['fighter:TIN'].stages.scale = { state: 'running' };
  x.win.sync([job({ fitting: later })]);
  assert.match(fit.innerHTML, /<b>Fitting<\/b> 2\/3 models/);
  assert.equal(op.textContent, 'scale · 3/3');
  x.win.dispose();
});

test('desktop and web load the extended popup script (no second copy)', () => {
  const fs = require('node:fs'), path = require('node:path');
  const web = fs.readFileSync(path.join(__dirname, '..', 'clients', 'web', 'index.html'), 'utf8');
  const desk = fs.readFileSync(path.join(__dirname, '..', 'clients', 'desktop', 'index.html'), 'utf8');
  assert.equal(web.split('/viz/process-popup.js').length - 1, 1);
  assert.equal(desk.split('../web/viz/process-popup.js').length - 1, 1);
});
