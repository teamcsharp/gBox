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
  const cal = x.elements.find(e => e.className === 'pp-cal');           // #1385 calibration play-by-play caption
  assert.equal(cal.textContent, 'Calibrating Sonic → Ryu: size ×0.9');
  const later = JSON.parse(JSON.stringify(FITTING));
  later.models['fighter:RYU'].state = 'done'; later.models['fighter:RYU'].current = 'write';
  later.models['fighter:RYU'].stages.write = { state: 'done', data: { mod: 'm' } };
  later.current = 'fighter:TIN'; later.models['fighter:TIN'].current = 'scale'; later.models['fighter:TIN'].state = 'running';
  later.models['fighter:TIN'].stages.scale = { state: 'running' };
  x.win.sync([job({ fitting: later })]);
  assert.match(fit.innerHTML, /<b>Fitting<\/b> 2\/3 models/);
  assert.equal(op.textContent, 'scale · 3/3');
  assert.equal(cal.textContent, '');                                     // Tina's scale has no numbers yet
  x.win.dispose();
});

test('desktop and web load the extended popup script (no second copy)', () => {
  const fs = require('node:fs'), path = require('node:path');
  const web = fs.readFileSync(path.join(__dirname, '..', 'clients', 'web', 'index.html'), 'utf8');
  const desk = fs.readFileSync(path.join(__dirname, '..', 'clients', 'desktop', 'index.html'), 'utf8');
  assert.equal(web.split('/viz/process-popup.js').length - 1, 1);
  assert.equal(desk.split('../web/viz/process-popup.js').length - 1, 1);
});

test('the cast writers numbers: donor height, rigid ride, per-limb counts, growth and the new VROM range', () => {
  const N = popup.stageNumbers;
  assert.equal(N('scale', { scale: 100, donor_height: 7.9, fitted_height: 790 }), '×100 · 7.9 → 790 tall');
  assert.equal(N('scale', { donor_height: 1.75, donor_triangles: 1200 }), '1.75 tall · 1,200 tris');
  assert.equal(N('retarget', { mode: 'rigid ride', vertices: 168 }), 'rigid ride · 168 verts');
  assert.equal(N('weights', { limbs: 14, vertices: 168, per_limb: { 'head (limb 14)': 12 } }), '14 limbs · 168 verts');
  assert.equal(N('weights', { nodes: 9, vertices: 1200 }), '9 limbs · 1,200 verts');
  assert.equal(N('encode', { bytes: 4768, grew: 1104, relocates: true }), '4.66 KB · +1.08 KB · moved');
  assert.equal(N('encode', { bytes: 2048, relocated: false }), '2 KB');
  assert.equal(N('write', { mod: 'cast_oot', relocated: ['object_sa'], vrom: '0x120000-0x12b600 (was 0xf8a30)' }),
    'cast_oot · 0x120000-0x12b600 (was 0xf8a30)');
  // a sprite writer's preview image shows when the model has no mesh snapshot; a mesh snapshot wins
  const sprite = { order: ['fighter:taffy'], current: 'fighter:taffy', models: { 'fighter:taffy': { label: 'Donor → Taffy',
    stages: {}, preview: '/api/jobs/j1/fitting/files/fitted_frames-1.png', preview_ts: 5 } } };
  assert.equal(popup.previewOf({ fitting: sprite }), '/api/jobs/j1/fitting/files/fitted_frames-1.png');
  sprite.models['fighter:taffy'].snapshot = '/api/jobs/j1/fitting/files/x.glb'; sprite.models['fighter:taffy'].snapshot_ts = 9;
  assert.equal(popup.previewOf({ fitting: sprite }), null);
  assert.equal(popup.previewOf(job()), null);
});

test('a collect job lists the roster as Collecting k/N with extract / preview chips and the extracted mesh', () => {
  const f = { kind: 'collect', order: ['sa1_sonic', 'sa1_tikal'], current: 'sa1_tikal', updated: 3, models: {
    sa1_sonic: { label: 'Sonic', state: 'done', current: 'preview', updated: 2,
      snapshot: '/api/jobs/j2/fitting/files/sa1_sonic-extract-0.glb', snapshot_stage: 'extract',
      stages: { extract: { state: 'done', data: { triangles: 1800, roles: 15 } }, preview: { state: 'done', data: { roles: 15 } } } },
    sa1_tikal: { label: 'Tikal', state: 'running', current: 'extract', updated: 3,
      snapshot: '/api/jobs/j2/fitting/files/sa1_tikal-extract-1.glb', snapshot_stage: 'extract',
      stages: { extract: { state: 'done', data: { triangles: 1500 } } } } } };
  const j = { id: 'j2', tool: 'characters', input: { op: 'collect' }, state: 'running', fitting: f };
  const html = popup.fittingHTML(j);
  assert.ok(html.includes('<b>Collecting</b> 1/2 characters'), html);
  assert.ok(html.includes('title="extract: 1,800 tris · 15 roles">E</i>') && !html.includes('>S</i>'), html);
  assert.equal(popup.modelPath(j), '/api/jobs/j2/fitting/files/sa1_tikal-extract-1.glb');   // not the placeholder
  assert.equal(popup.previewOf(j), null);                                                   // the mesh wins over a PNG
  assert.equal(popup.stageNumbers('extract', { kind: 'sprites' }), 'sprite sheet');
});

// ---- "R": the Retarget editor on the model being fitted (fit events name the donor, game and slot) ----------------
const GAME = '0123456789abcdef';
function withWho() {
  const f = JSON.parse(JSON.stringify(FITTING));
  Object.assign(f.models['fighter:KAS'], { donor: 'amy', game: GAME, slot: 'fighter:KAS' });
  Object.assign(f.models['fighter:RYU'], { donor: 'sonic', game: GAME, slot: 'fighter:RYU' });
  return f;                                                     // fighter:TIN: no donor named (an older writer)
}
const castJob = (extra = {}) => job({ input: { op: 'cast_swap', target_game: 'Dead or Alive 2', source: 'SA2', slots: 'all' },
  fitting: withWho(), ...extra });

test('a row opens the editor on its donor, game and slot (the job\'s call rides along for the rebuild)', () => {
  const o = popup.retargetOf(castJob(), 'fighter:KAS');
  assert.deepEqual(o, { slug: 'amy', gid: GAME, slot: 'fighter:KAS', name: 'Amy', view: 'goals', key: 'fighter:KAS', job: 'j1',
    recipe: { tool: 'characters', input: { op: 'cast_swap', target_game: 'Dead or Alive 2', source: 'SA2', slots: 'all' } } });
  assert.equal(popup.retargetOf(castJob()).slug, 'sonic');                         // no key: the model being fitted
  assert.equal(popup.retargetOf(castJob(), 'fighter:TIN'), null);                  // no donor named: no R
  assert.equal(popup.retargetOf(job(), 'fighter:KAS'), null);
  const use = { id: 'j3', tool: 'characters', state: 'running', input: { op: 'use', character: 'amy', game_id: GAME, slot: 'player' },
    fitting: { order: ['player'], current: 'player', models: { player: { label: 'Amy -> RE4 (player)', stages: {} } } } };
  assert.equal(popup.retargetOf(use).slot, 'player'); assert.equal(popup.retargetOf(use).slug, 'amy');
  const collect = { input: { op: 'collect' }, fitting: { kind: 'collect', order: ['amy'], current: 'amy',
    models: { amy: { label: 'Amy', donor: 'amy', game: GAME, stages: {} } } } };
  assert.equal(popup.retargetOf(collect, 'amy'), null);                           // a reader's roster: nothing to fit
  assert.equal(popup.shownKey(castJob()), 'fighter:RYU');                          // the model whose snapshot is shown
});

test('every fitting row with a donor gets its own small R', () => {
  const html = popup.fittingHTML(castJob());
  assert.match(html, /<i class="done" title="write: cast_doa2_x">W<\/i><button type="button" class="pp-rr" data-pp-r="fighter:KAS" title="Retarget goals: Amy → Kasumi[^"]*">R<\/button>/);
  assert.match(html, /data-pp-r="fighter:RYU"/);
  assert.ok(!html.includes('data-pp-r="fighter:TIN"'));
  assert.ok(!popup.fittingHTML(castJob(), { retarget: false }).includes('pp-rr'));   // a shell without the editor
});

function mountWith(opts) {
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
  return { win: createPopup(env).mount(Object.assign({ now: () => 0 }, opts)), elements };
}

test('the R in the 3D view\'s corner opens the editor on the model shown; a row\'s R on that row\'s model', () => {
  const opened = [];
  const x = mountWith({ retarget: o => opened.push(o) });
  x.win.sync([castJob()]);
  const r = x.elements.find(e => e.className === 'pp-rbtn'), stage = x.elements.find(e => e.className === 'pp-stage');
  assert.ok(stage.children.includes(r)); assert.equal(r.textContent, 'R'); assert.equal(r.style.display, '');
  assert.match(r.title, /Sonic → fighter:RYU/);
  r.onclick({ stopPropagation() {} });
  assert.deepEqual([opened[0].slug, opened[0].gid, opened[0].slot, opened[0].view], ['sonic', GAME, 'fighter:RYU', 'goals']);
  const fit = x.elements.find(e => e.className === 'pp-fit');
  assert.match(fit.innerHTML, /data-pp-r="fighter:KAS"/);
  fit.onclick({ target: { closest: sel => (sel === '[data-pp-r]' ? { dataset: { ppR: 'fighter:KAS' } } : null) } });
  assert.deepEqual([opened[1].slug, opened[1].slot], ['amy', 'fighter:KAS']);
  fit.onclick({ target: { closest: () => null } });                                 // anywhere else on the list: nothing
  assert.equal(opened.length, 2);
  x.win.sync([job()]);                                                              // no donor named: the corner R hides
  assert.equal(r.style.display, 'none');
  x.win.dispose();
  const plain = mountWith({});                                                      // a shell without the editor: no R
  plain.win.sync([castJob()]);
  assert.equal(plain.elements.find(e => e.className === 'pp-rbtn').style.display, 'none');
  assert.ok(!plain.elements.find(e => e.className === 'pp-fit').innerHTML.includes('pp-rr'));
  plain.win.dispose();
});

test('follow(jobId): the rebuild the editor queued takes the window once it is live', () => {
  const x = mountWith({ retarget: () => {} });
  const older = castJob({ id: 'j1', progress: { pct: 10, msg: 'x', ts: 50 } });
  const rebuild = { id: 'j2', tool: 'characters', state: 'queued', created: 10, input: { op: 'cast_swap', slots: 'fighter:KAS' } };
  x.win.sync([older, rebuild]);
  const chip = x.elements.find(e => e.className === 'pp-chip');                    // the state chip
  assert.equal(chip.textContent, 'processing');                                     // running beats queued...
  x.win.follow('j2'); x.win.sync([older, rebuild]);
  assert.equal(chip.textContent, 'queued');                                         // ...unless the editor queued it
  assert.ok(x.elements.some(e => e.className === 'pp-chip' && e.textContent === '+1 more'));
  assert.equal(x.win.openRetarget('fighter:KAS'), null);                            // the rebuild has no rows yet
  x.win.dispose();
});
