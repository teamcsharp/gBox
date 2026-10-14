// Blender paste pop-up (#1393): after blender_copy the desktop shell shows a movable window with the copied model rotating,
// the caption "Copied to Blender's clipboard: hover a 3D viewport and press Ctrl+V" and the clipboard files the worker
// wrote; the embedded library page reports the result over the GBOX: console bridge. Driven on a tiny fake DOM.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const desktop = fs.readFileSync(path.join(__dirname, '../clients/desktop/index.html'), 'utf8');
const web = fs.readFileSync(path.join(__dirname, '../clients/web/index.html'), 'utf8');

function node(tag) {
  const n = { tagName: tag.toUpperCase(), id: '', style: {}, classes: new Set(), listeners: {}, children: [], html: '', inserted: [] };
  n.classList = { add: (...c) => c.forEach(x => n.classes.add(x)), remove: (...c) => c.forEach(x => n.classes.delete(x)), contains: c => n.classes.has(c) };
  Object.defineProperty(n, 'innerHTML', { get: () => n.html, set: v => { n.html = v; n.av = v.includes('class="av"') ? { inserted: [], insertAdjacentHTML: (w, h) => n.av.inserted.push(h) } : null; } });
  n.append = (...k) => k.forEach(x => { x.parent = n; n.children.push(x); });
  n.addEventListener = (t, fn) => (n.listeners[t] ||= []).push(fn);
  n.fire = (t, ev = {}) => (n.listeners[t] || []).forEach(fn => fn({ preventDefault() {}, ...ev }));
  n.querySelector = sel => sel === '.av' ? n.av : null;
  return n;
}

function fixture({ viewer = 'ok', tok = 't k' } = {}) {
  const created = [], fits = [], drags = [], views = [], doc = {}, tokens = [];
  const ctx = {
    document: { body: node('body'), createElement: tag => { const n = node(tag); created.push(n); return n; }, addEventListener: (t, fn) => (doc[t] ||= []).push(fn) },
    $: sel => created.find(n => '#' + n.id === sel) || null,
    esc: s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]),
    fitMenu: (el, x, y, pad, minTop) => fits.push([x, y, pad, minTop]), dragAnywhere: el => drags.push(el),
    innerWidth: 1600, innerHeight: 900, S: { tok, apiUrl: 'http://spark:8080' },
    gbox: { token: async () => { tokens.push(1); return 'fresh'; } },
  };
  ctx.window = ctx;
  if (viewer === 'ok') ctx.assetView = async (box, url) => { views.push([box, url]); return { triangles: 12 }; };
  else if (viewer === 'fail') ctx.assetView = async (box, url) => { views.push([box, url]); throw new Error('WebGL unavailable'); };
  vm.createContext(ctx);
  const a = desktop.indexOf('// ---------------- Blender paste pop-up (#1393)'), b = desktop.indexOf('// ---------------- texture pop-up (#186)');
  assert.ok(a > 0 && b > a, 'the pop-up section exists before the texture pop-up');
  vm.runInContext(desktop.slice(a, b), ctx);
  Object.assign(ctx, vm.runInContext('({ BLENDER_PASTE_CAPTION, blenderPasteFiles })', ctx));
  return { ctx, created, fits, drags, views, doc, tokens, pop: () => ctx.$('#blpop') };
}
const R = { objects: 3, triangles: 1200, packed: 2, blender_version: '4.2.3', host: 'JAYBUILTFINALE', running: ['C:/B/blender.exe'],
  source: '/api/characters/mario/model', copybuffer: 'C:/Users/jay/AppData/Local/Temp/copybuffer.blend',
  copybuffers: ['C:/Users/jay/AppData/Local/Temp/copybuffer.blend', 'C:/Windows/Temp/copybuffer.blend'],
  skipped: { 'C:/Users/other/AppData/Local/Temp': 'PermissionError: denied' } };
const plain = x => JSON.parse(JSON.stringify(x));

test('the preview URL is the GLB the worker imported, with the token; a worker-local file has no preview', () => {
  const f = fixture(), g = f.ctx.blenderPasteGlb;
  assert.equal(g('/api/characters/mario/model', 'http://spark:8080', 't k'), 'http://spark:8080/api/characters/mario/model?token=t%20k');
  assert.equal(g('/api/artifacts/ab12?x=1', 'http://spark:8080', 'tok'), 'http://spark:8080/api/artifacts/ab12?x=1&token=tok');
  assert.equal(g('C:/rips/asset.glb', 'http://spark:8080', 'tok'), '');
  assert.equal(g(undefined, 'http://spark:8080', 'tok'), '');
  assert.deepEqual(plain(f.ctx.blenderPasteFiles(R)), R.copybuffers);
  assert.deepEqual(plain(f.ctx.blenderPasteFiles({ copybuffer: 'C:/t/copybuffer.blend' })), ['C:/t/copybuffer.blend']);
  assert.deepEqual(plain(f.ctx.blenderPasteFiles({})), []);
});

test('the window text: caption, facts, every file written, the ones skipped, and a note when Blender was not open', () => {
  const f = fixture(), h = f.ctx.blenderPasteHtml(R);
  assert.equal(f.ctx.BLENDER_PASTE_CAPTION, "Copied to Blender's clipboard: hover a 3D viewport and press Ctrl+V");
  assert.ok(h.includes('Copied to Blender&#39;s clipboard: hover a 3D viewport and press Ctrl+V'));
  assert.ok(h.includes('1200 triangles · 2 textures · Blender 4.2.3 · on JAYBUILTFINALE'));
  assert.ok(h.includes('2 clipboard files written') && h.includes('<li>C:/Windows/Temp/copybuffer.blend</li>') && h.includes('<li>C:/Users/jay/AppData/Local/Temp/copybuffer.blend</li>'));
  assert.ok(h.includes('1 not written') && h.includes('C:/Users/other/AppData/Local/Temp: PermissionError: denied'));
  assert.ok(h.includes('<canvas></canvas>') && h.includes('data-close'));
  assert.ok(!h.includes('was not open'));
  const one = f.ctx.blenderPasteHtml({ ...R, copybuffers: undefined, skipped: {}, running: [] });
  assert.ok(one.includes('1 clipboard file written') && !one.includes('not written') && one.includes('Blender was not open on JAYBUILTFINALE'));
  assert.ok(f.ctx.blenderPasteHtml({ copybuffers: ['C:/<x>/copybuffer.blend'] }).includes('C:/&lt;x&gt;/copybuffer.blend'));   // escaped
  assert.ok(f.ctx.blenderPasteHtml({}).includes('0 clipboard files written'));                                                   // no crash on an empty result
});

test('the pop-up is built once, movable, placed top-right, and starts the rotating model on the same GLB', async () => {
  const f = fixture(), url = 'http://spark:8080/api/characters/mario/model?token=t';
  const m = f.ctx.blenderPastePopup(R, url);
  assert.equal(m.id, 'blpop'); assert.ok(m.classes.has('on'));
  assert.deepEqual(f.drags, [m]); assert.deepEqual(f.fits, [[1600 - 372, 56, 8, 40]]);
  assert.equal(f.ctx.document.body.children[0], m);
  await new Promise(r => setImmediate(r));
  assert.equal(f.views.length, 1); assert.equal(f.views[0][0], m.av); assert.equal(f.views[0][1], url);
  assert.deepEqual(m.av.inserted, []);
  const again = f.ctx.blenderPastePopup({ ...R, triangles: 7 }, url, [10, 20]);        // a second copy reuses the window
  assert.equal(again, m); assert.equal(f.drags.length, 1); assert.deepEqual(f.fits[1], [10, 20, 8, 40]);
  assert.ok(m.html.includes('7 triangles'));
});

test('no preview when there is nothing to fetch, when the viewer is missing, or when it fails: the files still show', async () => {
  const none = fixture(); const m1 = none.ctx.blenderPastePopup(R, '');
  assert.equal(none.views.length, 0); assert.ok(m1.av.inserted[0].includes('no preview')); assert.ok(m1.html.includes('2 clipboard files written'));
  const missing = fixture({ viewer: 'none' }); const m2 = missing.ctx.blenderPastePopup(R, 'http://x/glb');
  assert.ok(m2.av.inserted[0].includes('3D viewer not loaded'));
  const failing = fixture({ viewer: 'fail' }); const m3 = failing.ctx.blenderPastePopup(R, 'http://x/glb');
  await new Promise(r => setImmediate(r));
  assert.ok(m3.av.inserted[0].includes('WebGL unavailable')); assert.ok(m3.classes.has('on'));
});

test('the bridge message fetches a token only when a preview needs one, then opens the window', async () => {
  const f = fixture({ tok: '' });
  await f.ctx.blenderCopiedMsg({ ev: 'blendercopied', result: R, input: { character: 'mario' }, worker: 'JAYBUILTFINALE' });
  assert.deepEqual(f.tokens, [1]); assert.equal(f.ctx.S.tok, 'fresh');
  assert.equal(f.views[0][1], 'http://spark:8080/api/characters/mario/model?token=fresh');
  const local = fixture({ tok: '' });
  await local.ctx.blenderCopiedMsg({ ev: 'blendercopied', result: { ...R, source: 'C:/rips/a.glb' } });
  assert.deepEqual(local.tokens, []); assert.equal(local.views.length, 0); assert.ok(local.pop().av.inserted[0].includes('no preview'));
  const empty = fixture();
  await empty.ctx.blenderCopiedMsg({ ev: 'blendercopied' });                                   // a bare message never throws
  assert.ok(empty.pop().classes.has('on'));
});

test('the ✕ button and Esc close it and stop the model (the stage leaves the DOM)', () => {
  const f = fixture(); const m = f.ctx.blenderPastePopup(R, 'http://x/glb');
  m.fire('click', { target: { closest: sel => sel === '[data-close]' ? {} : null } });
  assert.ok(!m.classes.has('on')); assert.equal(m.html, ''); assert.equal(m.av, null);
  f.ctx.blenderPastePopup(R, 'http://x/glb'); assert.ok(m.classes.has('on'));
  f.doc.keydown.forEach(fn => fn({ key: 'Escape' }));
  assert.ok(!m.classes.has('on'));
  f.doc.keydown.forEach(fn => fn({ key: 'Escape' }));                                           // closed already: harmless
});

// ---- the library page (embedded in the shell): the status line names the PC and the files, and the shell is told
function webFixture({ worker = 'JAYBUILTFINALE', job, workers } = {}) {
  const logs = [], jobs = [];
  const ctx = {
    api: async p => p === '/api/workers' ? (workers || [{ id: 'w1', name: 'JAYBUILTFINALE', online: true, os: 'windows' }, { id: 'w2', name: 'i9-NUC', online: true, os: 'windows' }]) : null,
    runJob: async body => { jobs.push(body); return job; },
    console: { log: s => logs.push(s) },
  };
  ctx.window = ctx; if (worker) ctx.GBOX_LOCAL = { worker };
  vm.createContext(ctx);
  const a = web.indexOf('async function blenderCopy(input, sid) {'), b = web.indexOf('async function modShot(');
  assert.ok(a > 0 && b > a);
  vm.runInContext(web.slice(a, b), ctx);
  Object.assign(ctx, vm.runInContext('({ blenderCopyNote, blenderCopyFiles })', ctx));
  return { ctx, logs, jobs };
}

test('blenderCopy runs on this PC, returns the result, tells the shell, and words the status with PC and file count', async () => {
  const f = webFixture({ job: { state: 'succeeded', output: { result: R } } });
  const r = await f.ctx.blenderCopy({ character: 'mario' }, 'sid');
  assert.equal(plain(r).host, 'JAYBUILTFINALE'); assert.equal(f.jobs[0].require_worker, 'w1'); assert.equal(f.jobs[0].tool, 'blender_copy');
  assert.equal(f.logs.length, 1); assert.ok(f.logs[0].startsWith('GBOX:'));
  const m = JSON.parse(f.logs[0].slice(5));
  assert.equal(m.ev, 'blendercopied'); assert.deepEqual(m.result, R); assert.deepEqual(m.input, { character: 'mario' }); assert.equal(m.worker, 'JAYBUILTFINALE');
  assert.equal(f.ctx.blenderCopyNote(R), "on Blender's clipboard on JAYBUILTFINALE: 1200 triangles, 2 textures · hover a 3D viewport there and press Ctrl+V (2 files written)");
  assert.equal(f.ctx.blenderCopyNote({ triangles: 1, packed: 0, copybuffer: 'C:/t/copybuffer.blend' }), "on Blender's clipboard: 1 triangles, 0 textures · hover a 3D viewport there and press Ctrl+V (1 file written)");
});

test('unidentified or offline local workers never send a clipboard job to another PC; failures are readable', async () => {
  const f = webFixture({ worker: '', job: { state: 'succeeded', output: { result: R } } });
  await assert.rejects(f.ctx.blenderCopy({ character: 'mario' }, 'sid'), /no gBox worker on this PC/);
  assert.deepEqual(f.logs, []); assert.deepEqual(f.jobs, []);
  const offline = webFixture({workers:[{id:'remote',name:'i9-NUC',online:true,os:'windows'}]});
  await assert.rejects(offline.ctx.blenderCopy({character:'mario'}), /no gBox worker on this PC/);
  assert.deepEqual(offline.jobs, []);
  const none = webFixture({ job: { state: 'succeeded', output: { result: { triangles: 1 } } } });
  await assert.rejects(none.ctx.blenderCopy({ character: 'mario' }, 'sid'), /ran on JAYBUILTFINALE but no clipboard file was written/);
  const failed = webFixture({ job: { state: 'failed', error: 'no Blender found on this machine' } });
  await assert.rejects(failed.ctx.blenderCopy({ character: 'mario' }, 'sid'), /no Blender found on this machine/);
  const nowhere = webFixture({ workers: [{ id: 'l', name: 'spark', online: true, os: 'linux' }] });
  await assert.rejects(nowhere.ctx.blenderCopy({ character: 'mario' }, 'sid'), /no gBox worker on this PC/);
});

test('image copies do not repeat the PNG payload in the desktop popup bridge',async()=>{
 const f=webFixture({job:{state:'succeeded',output:{result:R}}});
 await f.ctx.blenderCopy({image_b64:'large-image-payload',paste_as:'image_empty'});
 const message=JSON.parse(f.logs[0].slice(5));
 assert.deepEqual(message.input,{paste_as:'image_empty'});
 assert.equal(message.result.host,'JAYBUILTFINALE');
});
