// Pick whip shared UI logic (clients/web/viz/pick-whip.js): outline geometry, hover scheduling, the pause hold,
// tool fallbacks (pick_identify -> pick_preview, pick_replace -> live_use -> rebuild request, pick_name -> evidence),
// the mini console and the character menu flows, against a fake DOM and a fake control plane.
const assert = require('node:assert/strict');
const { test } = require('node:test');
const PW = require('../clients/web/viz/pick-whip.js');

// ---- a fake DOM: just enough for the menu, the browser and the console -------------------------------------------
class El {
  constructor(tag, doc) { this.tagName = tag; this.doc = doc; this.style = {}; this.dataset = {}; this.children = []; this.kids = {};
    this.className = ''; this._html = ''; this.textContent = ''; this.attrs = {}; this.classList = { set: new Set(),
      add: c => this.classList.set.add(c), remove: c => this.classList.set.delete(c), toggle: (c, on) => (on ?? !this.classList.set.has(c)) ? this.classList.set.add(c) : this.classList.set.delete(c),
      contains: c => this.classList.set.has(c) }; }
  set id(v) { this._id = v; this.doc.ids[v] = this; } get id() { return this._id; }
  set innerHTML(v) { this._html = v; this.kids = {}; } get innerHTML() { return this._html; }
  append(...c) { for (const x of c) { this.children.push(x); x.parent = this; if (x._id) this.doc.ids[x._id] = x; } }
  remove() { if (this._id && this.doc.ids[this._id] === this) delete this.doc.ids[this._id]; this.removed = true; }
  setAttribute(k, v) { this.attrs[k] = v; } getAttribute(k) { return this.attrs[k] ?? null; } addEventListener(t, f) { (this.on ||= {})[t] = f; } focus() {}
  getContext() { return new Proxy({}, { get: () => () => ({ data: new Uint8ClampedArray(4) }) }); }
  toDataURL() { return 'data:image/png;base64,RlJBTUU='; }
  querySelector(sel) { return this.kids[sel] || (this.kids[sel] = new El(sel, this.doc)); }
  contains(x) { return x === this; } getBoundingClientRect() { return { left: 0, top: 0, width: 100, height: 100 }; }
}
function fakeDoc() {
  const doc = { ids: {}, listeners: {} };
  doc.createElement = t => new El(t, doc);
  doc.getElementById = id => doc.ids[id] || null;
  doc.head = new El('head', doc); doc.body = new El('body', doc);
  doc.addEventListener = (t, f) => (doc.listeners[t] ||= []).push(f);
  doc.removeEventListener = (t, f) => { doc.listeners[t] = (doc.listeners[t] || []).filter(x => x !== f); };
  doc.defaultView = { innerWidth: 1600, innerHeight: 900, requestAnimationFrame: () => 0, cancelAnimationFrame() {}, addEventListener() {} };
  doc.contains = () => true;
  return doc;
}
const tick = async (n = 6) => { for (let i = 0; i < n; i++) await new Promise(r => setTimeout(r, 0)); };

// ---- a fake control plane ------------------------------------------------------------------------------------------
function fakeApi(tools, extra = {}) {
  const calls = [], jobs = {};
  let n = 0;
  const api = async (path, body) => {
    calls.push({ path, body });
    if (path === '/api/jobs') {
      const t = tools[body.tool];
      if (!t) throw new Error(`404 {"detail":"unknown tool ${body.tool}"}`);
      const out = typeof t === 'function' ? t(body.input, body) : t;
      const j = { id: 'j' + (++n), tool: body.tool, input: body.input, state: out.state || 'succeeded', error: out.error,
        output: { result: out.result ?? out }, progress_log: out.log || [] };
      jobs[j.id] = j; return j;
    }
    if (path.startsWith('/api/jobs/')) return jobs[path.split('/').pop()];
    if (extra[path]) return typeof extra[path] === 'function' ? extra[path](body) : extra[path];
    throw new Error('404 not found ' + path);
  };
  return { api, calls, jobs, sleep: async () => {} };
}

// ---- geometry ----------------------------------------------------------------------------------------------------------
test('window <-> 4:3 picture mapping round-trips with letterboxing', () => {
  for (const aspect of [16 / 9, 4 / 3, 1]) for (const p of [[0.1, 0.2], [0.5, 0.5], [0.9, 0.75]]) {
    const back = PW.pictureToWindow(PW.windowToPicture(p, aspect), aspect);
    assert.ok(Math.abs(back[0] - p[0]) < 1e-9 && Math.abs(back[1] - p[1]) < 1e-9);
  }
  assert.deepEqual(PW.pictureToWindow([0, 0.5], 16 / 9), [0.125, 0.5]);            // 4:3 centred in 16:9: pillarbox
});

test('mask edges trace a silhouette and clip to the entity box', () => {
  const W = 4, H = 4, mask = new Uint8Array(16); for (const i of [5, 6, 9, 10]) mask[i] = 1;   // a 2x2 square in the middle
  const segs = PW.maskEdges(mask, W, H);
  const len = segs.reduce((s, [x0, y0, x1, y1]) => s + Math.abs(x1 - x0) + Math.abs(y1 - y0), 0);
  assert.equal(segs.length, 4); assert.equal(len, 8);
  const clipped = PW.maskEdges(mask, W, H, [0, 0, 0.5, 1]);                       // only the left column of the square
  const lenc = clipped.reduce((s, [x0, y0, x1, y1]) => s + Math.abs(x1 - x0) + Math.abs(y1 - y0), 0);
  assert.equal(lenc, 6);
});

test('flood region finds the colour blob under the cursor', () => {
  const W = 10, H = 10, d = new Uint8ClampedArray(W * H * 4);
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) { const i = (y * W + x) * 4; const red = x >= 3 && x < 6 && y >= 2 && y < 8; d[i] = red ? 220 : 10; d[i + 3] = 255; }
  const g = PW.floodRegion({ data: d }, W, H, [0.45, 0.5]);
  assert.deepEqual(g.box, [0.3, 0.2, 0.6, 0.8]); assert.equal(g.n, 18);
});

test('outline: best evidence wins (polygon > mask > bounds > region at the entity > point)', () => {
  const region = { box: [0.4, 0.3, 0.6, 0.8], mask: new Uint8Array(4), W: 2, H: 2 };
  const poly = PW.outlineOf({ outline: [[0.4, 0.2], [0.6, 0.2], [0.5, 0.9]], space: 'window' }, region, 4 / 3);
  assert.equal(poly.kind, 'polygon'); assert.deepEqual(poly.box, [0.4, 0.2, 0.6, 0.9]);
  const b64 = Buffer.from([0, 1, 1, 0]).toString('base64');
  const mask = PW.outlineOf({ mask: { w: 2, h: 2, b64 }, space: 'window' }, null, 4 / 3);
  assert.equal(mask.kind, 'mask'); assert.deepEqual(mask.box, [0, 0, 1, 1]);
  // entity probe pick: screen_box in pixels of a 640x480 picture (click/click_px tell the frame)
  const probe = PW.outlineOf({ picked: { class: 'bot', screen_box: [256, 96, 384, 384], screen: [320, 240] }, click: [0.5, 0.5], click_px: [320, 240] }, region, 4 / 3);
  assert.equal(probe.kind, 'bounds'); assert.deepEqual(probe.box.map(v => +v.toFixed(3)), [0.4, 0.2, 0.6, 0.8]); assert.equal(probe.region, region);
  const atRegion = PW.outlineOf({ picked: { class: 'Soldier' }, screen: [0.5, 0.5] }, region, 4 / 3);
  assert.equal(atRegion.kind, 'region');
  const point = PW.outlineOf({ picked: { class: 'Soldier' }, screen: [0.1, 0.5] }, region, 4 / 3);
  assert.equal(point.kind, 'point'); assert.ok(point.box[0] < 0.1 && point.box[2] > 0.1);
  assert.equal(PW.outlineOf({ picked: null }, null), null);
});

test('the outline eases toward its target instead of jumping', () => {
  const a = PW.easeBox([0, 0, 0, 0], [1, 1, 1, 1], 16);
  assert.ok(a[0] > 0.1 && a[0] < 0.4);
  assert.deepEqual(PW.easeBox(null, [0.2, 0.2, 0.4, 0.4], 16), [0.2, 0.2, 0.4, 0.4]);
});

test('label: local model name > pick_identify > pick_preview', () => {
  const preview = { picked: { class: 'pl0000', kind: 'player', entity_id: 3, ptr: '0x80123' }, model: ['pl', 'pl00.mdl'] };
  let l = PW.labelOf(preview);
  assert.equal(l.name, 'pl0000'); assert.equal(l.model, 'pl / pl00.mdl'); assert.equal(l.via, 'pick_preview'); assert.equal(l.ram, '0x80123');
  l = PW.labelOf(preview, { entity: { name: 'Leon' }, slot: 'player', model: { name: 'pl00' } });
  assert.equal(l.name, 'Leon'); assert.equal(l.slot, 'player'); assert.equal(l.model, 'pl00'); assert.equal(l.via, 'pick_identify');
  l = PW.labelOf(preview, null, { name: 'Leon Kennedy', route: 'local', llm_model: 'gemma4:e4b' });
  assert.equal(l.name, 'Leon Kennedy'); assert.equal(l.via, 'gemma4:e4b (local)');
});

// ---- hover scheduling ------------------------------------------------------------------------------------------------
test('hover: one request in flight, the latest point wins, stale answers are dropped', async () => {
  const pending = [], applied = [];
  const h = PW.createHover({ minMs: 0, request: at => new Promise(r => pending.push({ at, r })), apply: (res, at) => applied.push(at[0]) });
  h.move([1]); h.move([2]); h.move([3]);
  assert.equal(pending.length, 1);                                               // [1] in flight; [2] superseded by [3]
  pending[0].r('a'); await tick();
  assert.deepEqual(applied, []);                                                  // [1]'s answer is stale: the cursor moved on
  assert.equal(pending.length, 2); assert.deepEqual(pending[1].at, [3]);
  pending[1].r('b'); await tick();
  assert.deepEqual(applied, [3]);
  h.stop(); h.move([4]); assert.equal(pending.length, 2);
});

// ---- pause hold --------------------------------------------------------------------------------------------------------
test('hold: pauses once, renews while held, resumes on the last release', async () => {
  const f = fakeApi({}, { '/api/pickwhip/w1-s1/hold': b => b.op === 'pause' ? { paused: true, owned: true, via: 'rpc' } : b.op === 'release' ? { resumed: true } : { ok: true } });
  const timers = [];
  const hold = PW.createHold({ api: f.api, holder: 'desk', every: (fn, ms) => { timers.push(fn); return timers.length; }, stop: () => timers.splice(0) });
  assert.equal((await hold.acquire('w1-s1')).owned, true);
  assert.equal((await hold.acquire('w1-s1')).shared, true);                        // the menu inside the eyedropper
  timers[0](); await tick();
  assert.deepEqual(f.calls.map(c => c.body.op), ['pause', 'renew']);
  assert.equal((await hold.release('w1-s1')).shared, true);
  assert.equal((await hold.release('w1-s1')).resumed, true);
  assert.deepEqual(f.calls.map(c => c.body.op), ['pause', 'renew', 'release']);
  assert.equal(timers.length, 0); assert.equal(hold.held('w1-s1'), false);
});

test('hold: disabled setting skips; an older control plane falls back to session_op', async () => {
  const off = PW.createHold({ api: async () => { throw new Error('x'); }, holder: 'a', enabled: () => false });
  assert.equal((await off.acquire('s')).skipped, true);
  const ops = [];
  const old = PW.createHold({ api: async () => { throw new Error('404 Not Found'); }, holder: 'a', sessionOp: async (sid, op) => ops.push(op) });
  assert.equal((await old.acquire('w1-s1')).via, 'session_op');
  await old.release('w1-s1');
  assert.deepEqual(ops, ['pause', 'resume']);
});

test('hold: a release while the pause is on its way undoes it on arrival; a leaked hold stops at maxMs', async () => {
  let answer; const ops = [];
  const api = async (p, b) => { ops.push(b.op); if (b.op === 'pause') return new Promise(r => { answer = r; }); return { resumed: true }; };
  const hold = PW.createHold({ api, holder: 'd', every: () => 1, stop() {} });
  const pending = hold.acquire('w1-s1');
  assert.equal((await hold.release('w1-s1')).pending, true);
  answer({ paused: true, owned: true });
  assert.equal((await pending).released, true);
  assert.deepEqual(ops, ['pause', 'release']);
  let t = 0, tickFn; ops.length = 0;
  const api2 = async (p, b) => { ops.push(b.op); return b.op === 'pause' ? { owned: true } : { ok: true, resumed: true }; };
  const leak = PW.createHold({ api: api2, holder: 'd', maxMs: 1000, now: () => t, every: f => { tickFn = f; return 1; }, stop() {} });
  await leak.acquire('w1-s1'); await leak.acquire('w1-s1');                         // two references, only one released below
  await leak.release('w1-s1');
  t = 500; tickFn(); await tick();
  t = 1500; tickFn(); await tick();
  assert.deepEqual(ops, ['pause', 'renew', 'release']); assert.equal(leak.held('w1-s1'), false);
});

test('web viewer: shared module, ⌖ in the session bar, right-click on the picture opens the menu', () => {
  const web = require('node:fs').readFileSync(require('node:path').join(__dirname, '../clients/web/index.html'), 'utf8');
  assert.match(web, /<script src="\/viz\/pick-whip\.js"><\/script>/);
  assert.match(web, /id="pwbtn"[\s\S]{0,400}PWW\.toggle\(\)/);
  assert.match(web, /window\.PWW = GBoxPickWhip\.mountOverlay\(document, \{/);
  assert.match(web, /closest\("\.tchip, \.card\[data-gid\], input, textarea, select, #scr, img\.screen, img\[src\*='\/mjpeg'\], #pwcanvas, #pwmenu, #pwreport"\)/);   // the issue menu stays off the picture
  assert.match(web, /const PW_GAME_VIEW = "#scr, img\.screen, img\[src\*='\/mjpeg'\]";/);
  assert.match(web, /closest\?\.\(PW_GAME_VIEW\)[\s\S]{0,120}PWW\.menuAt\(e\.clientX, e\.clientY, v\)/);
});

// ---- Report… ---------------------------------------------------------------------------------------------------------------
test('report body: a problem at this spot, prefilled; no pick needed', () => {
  const b = PW.reportBody({ sid: 'spark-s7', at: [0.5, 0.4], aspect: 16 / 9, session: { game: 'Dead or Alive 2', game_id: 'g1', mod: 'doa2_amy', worker: 'spark' }, view: 'web Sessions · play' });
  assert.equal(b.session_id, 'spark-s7'); assert.equal(b.save_state, true);
  assert.equal(b.what, 'Problem at this spot (50% across, 40% down)');
  assert.equal(b.detail, 'No character was identified at this spot.');
  assert.equal(b.title, 'Dead or Alive 2: Problem at this spot (50% across, 40% down)');
  assert.deepEqual(b.element, { kind: 'game-point', view: 'web Sessions · play', tag: 'GAME', text: b.what, x: 0.5, y: 0.4, window_aspect: 1.7778 });
  assert.deepEqual(b.context.click, { x: 0.5, y: 0.4 });
  assert.equal(b.context.mod, 'doa2_amy'); assert.equal(b.context.worker, 'spark'); assert.equal(b.context.pick, null);
  assert.deepEqual(b.attachments, []); assert.equal(b.image_b64, null);
  assert.equal(PW.reportBody({ sid: 'w1-s1' }).context.worker, 'w1');                 // worker from the session id
  assert.equal(PW.reportBody({}).save_state, false);                                  // no game: a plain request, no state save
});

test('report body: the pick goes along (summary + pick-result.json)', () => {
  const pick = { preview: { picked: { class: 'kasumi', kind: 'player', ptr: '0x8c0f1000' }, model: 'KASUMI.BIN' }, named: { name: 'Kasumi', route: 'local', llm_model: 'gemma4:e4b' } };
  const b = PW.reportBody({ sid: 'spark-s7', at: [0.3, 0.6], pick, note: 'her hair is missing', image: 'PNG' });
  assert.equal(b.what, 'Problem at this spot (30% across, 60% down) on Kasumi');
  assert.match(b.detail, /Picked: Kasumi \(player\) · model KASUMI\.BIN · RAM 0x8c0f1000 · via gemma4:e4b \(local\)/);
  assert.match(b.title, /— her hair is missing$/); assert.equal(b.image_b64, 'PNG');
  const att = JSON.parse(Buffer.from(b.attachments[0].b64, 'base64').toString('utf8'));
  assert.equal(b.attachments[0].name, 'pick-result.json'); assert.equal(att.preview.picked.class, 'kasumi'); assert.equal(att.named.name, 'Kasumi');
  assert.equal(b.context.pick.name, 'Kasumi');
});

test('character menu: Report… is first, opens the report pop-up and files it with a marked frame', async () => {
  const fx = menuFixture({ pick_preview: { picked: { class: 'kasumi', kind: 'player' } } }, { '/api/requests/issue': b => ({ number: 12, id: 'r12', body: b }) });
  fx.io.frame = at => 'FRAME@' + at.join(',');
  fx.io.session = sid => ({ game: 'Dead or Alive 2', game_id: 'g1', mod: 'doa2_amy', worker: 'spark' });
  let reported = null; fx.io.onReported = r => { reported = r; };
  await tick(10);
  assert.equal(PW.menuItems()[0].id, 'report');
  assert.match(fx.doc.getElementById('pwmenu').innerHTML, /^<div class="pw-head">[\s\S]*?<button role="menuitem" data-pw="report"/);
  const pop = await fx.menu.onPick('report');
  assert.deepEqual(fx.seen.closed, ['report']);
  const m = fx.doc.getElementById('pwreport');
  assert.match(m.innerHTML, /⚑ Report: Problem at this spot \(50% across, 50% down\) on kasumi/);
  assert.match(m.innerHTML, /What did you expect\? \(optional\)/);
  m.querySelector('input').value = 'should not freeze';
  const r = await pop.send();
  const body = fx.f.calls.find(c => c.path === '/api/requests/issue').body;
  assert.equal(r.number, 12); assert.equal(reported.number, 12);
  assert.equal(body.session_id, 'w1-s1'); assert.equal(body.save_state, true); assert.equal(body.note, 'should not freeze');
  assert.equal(body.image_b64, 'FRAME@0.5,0.5'); assert.equal(body.context.game, 'Dead or Alive 2'); assert.equal(body.context.mod, 'doa2_amy');
  assert.equal(body.attachments[0].name, 'pick-result.json');
  assert.match(m.querySelector('.mut').textContent, /Report #12 is in the inbox/);
});

test('Report works where identification fails (no picker tools at all)', async () => {
  const fx = menuFixture({}, { '/api/requests/issue': () => ({ number: 13 }) });
  await tick(10);
  const pop = await fx.menu.onPick('report');
  await pop.send();
  const body = fx.f.calls.find(c => c.path === '/api/requests/issue').body;
  assert.equal(body.what, 'Problem at this spot (50% across, 50% down)'); assert.deepEqual(body.attachments, []);
  assert.equal(body.detail, 'No character was identified at this spot.');
});

test('web viewer: right-click on a Sessions stream opens the menu (paused), Report… is there, and reportAt files directly', async () => {
  const doc = fakeDoc(), f = fakeApi({}, { '/api/pickwhip/spark-s7/hold': b => ({ paused: true, owned: true }), '/api/requests/issue': () => ({ number: 14 }) });
  const img = new El('img', doc); img.id = 'scr'; img.attrs.src = '/api/sessions/spark-s7/mjpeg?token=x';
  img.getBoundingClientRect = () => ({ left: 100, top: 100, width: 640, height: 480 }); img.naturalWidth = 640; img.naturalHeight = 480;
  const store = new Map(); globalThis.localStorage = { getItem: k => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) };
  const ow = PW.mountOverlay(doc, { api: f.api, sleep: f.sleep, toast() {}, view: () => 'web Sessions · play' });
  await ow.menuAt(420, 340, img); await tick(10);
  assert.ok(f.calls.some(c => c.path === '/api/pickwhip/spark-s7/hold' && c.body.op === 'pause'));
  const menu = doc.getElementById('pwmenu');
  assert.equal(menu.style.display, 'block'); assert.match(menu.innerHTML, /data-pw="report"/);
  const pop = ow.reportAt(420, 340, img);
  assert.match(pop.el.innerHTML, /Problem at this spot \(50% across, 50% down\)/);
  await pop.send();
  const body = f.calls.find(c => c.path === '/api/requests/issue').body;
  assert.equal(body.session_id, 'spark-s7'); assert.equal(body.context.worker, 'spark'); assert.equal(body.element.view, 'web Sessions · play');
  assert.equal(body.image_b64, 'RlJBTUU=');                                          // the stream frame with the spot marked
  ow.stop(); await tick();                                                            // closing resumes (and stops the renewals)
  assert.ok(f.calls.some(c => c.path === '/api/pickwhip/spark-s7/hold' && c.body.op === 'release'));
});

// ---- tool fallbacks ------------------------------------------------------------------------------------------------------
test('identify: pick_identify when registered, else pick_preview', async () => {
  let f = fakeApi({ pick_preview: { picked: { class: 'Soldier' } } });
  const logs = [];
  let r = await PW.identify(f, { sid: 'w1-s1', x: 0.5, y: 0.5, log: t => logs.push(t) });
  assert.equal(r.source, 'pick_preview'); assert.match(logs[0], /not on this gBox yet/);
  assert.equal(f.calls.find(c => c.body?.tool === 'pick_preview').body.require_worker, 'w1');
  f = fakeApi({ pick_identify: { entity: { name: 'Leon' }, slot: 'player' } });
  r = await PW.identify(f, { sid: 'w1-s1', x: 0.5, y: 0.5 });
  assert.equal(r.source, 'pick_identify'); assert.equal(r.result.slot, 'player');
});

test('replace: pick_replace live, then build when live does not take', async () => {
  let f = fakeApi({ pick_replace: i => ({ status: i.mode === 'live' ? 'live' : 'built' }) });
  let r = await PW.replace(f, { sid: 'w1-s1', character: 'amy', x: 0.5, y: 0.5 });
  assert.equal(r.mode, 'live'); assert.equal(r.ok, true);
  f = fakeApi({ pick_replace: i => i.mode === 'live' ? { status: 'unsupported: no hot path' } : { status: 'built mod re4_amy' } });
  const logs = [];
  r = await PW.replace(f, { sid: 'w1-s1', character: 'amy', x: 0.5, y: 0.5, log: t => logs.push(t) });
  assert.equal(r.mode, 'build'); assert.equal(r.ok, true);
  assert.deepEqual(f.calls.filter(c => c.path === '/api/jobs' && c.body.tool === 'pick_replace').map(c => c.body.input.mode), ['live', 'build']);
  assert.ok(logs.some(t => /building instead/.test(t)));
});

// ---- the real backend (gbox/pick_tool.py): pick_identify's answer is the pick, the backend's own build fallback ----------
const IDENT = { entity: { class: 'En_Wolf', kind: 'enemy', ptr: '0x80123400' }, game_id: 'g1', slot: 'enemy:wolf', model: 'wolf',
  ram: { entity_struct: '0x80123400', model: '0x80400000', skeleton: '0x80401000', model_detail: { kind: 'ninja' }, structures: [{ at: '0x80400000' }] },
  evidence: [], confidence: 0.8, replaceable: { live: true, build: true }, backend: 'profile' };

test('replace: a bare point is identified first and pick_replace gets the pick_identify result', async () => {
  const f = fakeApi({ pick_identify: IDENT, pick_replace: i => ({ status: 'live', mode_used: 'live', message: 'Amy replaces enemy:wolf' }) });
  let seen = null;
  const r = await PW.replace(f, { sid: 'w1-s1', character: 'amy', x: 0.25, y: 0.5, aspect: 16 / 9, onIdentified: p => { seen = p; } });
  assert.equal(r.ok, true); assert.equal(r.mode, 'live'); assert.equal(seen.slot, 'enemy:wolf');
  const ident = f.calls.find(c => c.body && c.body.tool === 'pick_identify').body.input;
  assert.equal(ident.window_aspect, +(16 / 9).toFixed(4));
  const rep = f.calls.find(c => c.body && c.body.tool === 'pick_replace').body.input;
  assert.equal(rep.pick.slot, 'enemy:wolf'); assert.equal(rep.pick.ram.model, '0x80400000'); assert.equal(rep.mode, 'live');
  assert.match(PW.replaceText(r, 'Amy'), /replaced live/);
});

test('replace: a pick_identify result is passed as is (no second identify)', async () => {
  const f = fakeApi({ pick_identify: () => { throw new Error('should not identify again'); }, pick_replace: { status: 'live' } });
  const r = await PW.replace(f, { sid: 'w1-s1', character: 'amy', x: 0.5, y: 0.5, pick: Object.assign({}, IDENT, { x: 0.5, y: 0.5 }) });
  assert.equal(r.ok, true);
  assert.equal(f.calls.filter(c => c.body && c.body.tool === 'pick_identify').length, 0);
});

test('replace: the backend fell back to build itself: no second build job, both steps shown', async () => {
  const f = fakeApi({ pick_identify: IDENT, pick_replace: { status: 'swapped', mode_used: 'build', fell_back: true, fallback_reason: 'no RAM image', message: 'Amy is in mod_x' } });
  const r = await PW.replace(f, { sid: 'w1-s1', character: 'amy', x: 0.5, y: 0.5 });
  assert.equal(r.ok, true); assert.equal(r.mode, 'build');
  assert.equal(f.calls.filter(c => c.body && c.body.tool === 'pick_replace').length, 1);
  assert.deepEqual(r.steps.map(s => [s.mode, s.ok]), [['live', false], ['build', true]]);
  assert.match(PW.replaceText(r, 'Amy'), /built and swapped in/);
});

test('replace: not_replaceable -> characters live_use, then the rebuild request', async () => {
  const f = fakeApi({ pick_identify: Object.assign({}, IDENT, { slot: null }), pick_replace: { status: 'not_replaceable', message: 'no writer slot' } });
  let r = await PW.replace(f, { sid: 'w1-s1', character: 'amy', x: 0.5, y: 0.5, fallbackLive: async () => ({ status: 'live_swapped' }) });
  assert.equal(r.ok, true); assert.equal(r.via, 'characters live_use');
  assert.equal(f.calls.filter(c => c.body && c.body.tool === 'pick_replace').length, 1);   // no build attempt: it has no slot either
  let steps = null;
  r = await PW.replace(f, { sid: 'w1-s1', character: 'amy', x: 0.5, y: 0.5, fallbackLive: async () => ({ status: 'unsupported' }),
    fallbackBuild: async s => { steps = s.slice(); return { number: 9 }; } });
  assert.equal(r.ok, true); assert.equal(r.via, 'rebuild request');
  assert.deepEqual(steps.map(s => s.via), ['pick_replace', 'characters live_use']);
});

test('replace: liveFirst runs the game-specific live_use before pick_replace', async () => {
  const f = fakeApi({ pick_identify: IDENT, pick_replace: { status: 'live' } });
  const r = await PW.replace(f, { sid: 'w1-s1', character: 'amy', x: 0.5, y: 0.5, liveFirst: true, fallbackLive: async () => ({ status: 'live_swapped', message: 'Snake is Amy' }) });
  assert.equal(r.via, 'characters live_use'); assert.equal(f.calls.filter(c => c.path === '/api/jobs').length, 0);
});

test('labels: pick_identify ram (an object) shows its keys and addresses, never [object Object]', () => {
  const l = PW.labelOf(null, IDENT);
  assert.doesNotMatch(l.ram, /object Object/);
  assert.equal(l.ram, 'entity 0x80123400 · model 0x80400000 · skeleton 0x80401000');
  assert.equal(PW.ramText({ model_images: [{ name: 'chr', base: '0x80500000' }] }), 'model image 0x80500000');
  assert.equal(PW.ramText([{ address: '0x80001000' }]), '0x80001000');
  assert.equal(PW.ramText('0x80002000'), '0x80002000');
  assert.equal(PW.labelOf({ picked: { class: 'Soldier', ptr: '0x8000F000' } }).ram, '0x8000F000');
});

test('replace: before pick_replace exists, live_use then the rebuild request', async () => {
  const f = fakeApi({});
  let r = await PW.replace(f, { sid: 'w1-s1', character: 'amy', x: 0.5, y: 0.5, fallbackLive: async () => ({ status: 'swapped' }) });
  assert.equal(r.via, 'characters live_use'); assert.equal(r.ok, true);
  let steps = null;
  r = await PW.replace(f, { sid: 'w1-s1', character: 'amy', x: 0.5, y: 0.5,
    fallbackLive: async () => ({ status: 'unsupported' }), fallbackBuild: async s => { steps = s.slice(); return { number: 7 }; } });
  assert.equal(r.mode, 'build'); assert.equal(r.ok, true); assert.equal(r.result.number, 7);
  assert.equal(steps[0].via, 'characters live_use'); assert.equal(steps[0].ok, false);
});

test('pick_name runs next to the model (linux) and degrades to null when missing', async () => {
  let f = fakeApi({ pick_name: { name: 'Leon', route: 'local', llm_model: 'gemma4:e4b' } });
  const r = await PW.nameLocal(f, { sid: 'w1-s1', x: 0.5, y: 0.5, model: 'gemma4:e4b', evidence: { picked: {} } });
  assert.equal(r.name, 'Leon');
  const body = f.calls[0].body;
  assert.equal(body.require_os, 'linux'); assert.equal(body.input.target_session, 'w1-s1'); assert.equal(body.input.allow_cloud, false);
  assert.equal(body.input.session_id, undefined);                                  // never routed to the gaming PC
  f = fakeApi({});
  assert.equal(await PW.nameLocal(f, { sid: 'w1-s1', x: 0.5, y: 0.5 }), null);
});

test('characters: compatible first, vehicles only for vehicles', () => {
  const chars = [{ slug: 'b', name: 'Bob', model: 'm.glb' }, { slug: 'a', name: 'Amy', model: 'm.glb', ready: [{ mod: 'x' }] },
    { slug: 'c', name: 'Car', kind: 'vehicle', model: 'c.glb' }, { slug: 'd', name: 'Dee', targets: { g1: [{ mod: 'y', needs_rebuild: true }] }, model: 'm' },
    { slug: 'e', name: 'Eve' }];
  assert.deepEqual(PW.rankCharacters(chars, { gid: 'g1', kind: 'enemy' }).map(r => r.c.slug), ['a', 'd', 'b', 'e']);
  assert.deepEqual(PW.rankCharacters(chars, { kind: 'vehicle' }).map(r => r.c.slug), ['c']);
});

test('console lines: progress log, fit events, the end', () => {
  const job = { state: 'succeeded', progress_log: ['extracting', 'retargeting'], progress: { msg: 'writing' }, output: { result: { status: 'live', message: 'Amy is in' } },
    fitting: { order: ['amy'], models: { amy: { label: 'Amy → Leon', current: 'retarget', stages: { scale: { state: 'done' }, retarget: { state: 'running' } } } } } };
  const lines = PW.consoleLines(job);
  assert.deepEqual(lines, ['extracting', 'retargeting', 'writing', '◆ Amy → Leon: retarget running', '✓ Amy is in']);
  assert.equal(PW.consoleLines({ state: 'failed', error: 'boom' }).at(-1), '✗ boom');
});

// ---- the character menu, end to end on fakes ---------------------------------------------------------------------
function menuFixture(tools, extra = {}) {
  const doc = fakeDoc(), f = fakeApi(tools, extra), seen = { blender: [], clip: [], retarget: [], closed: [], assets: [], live: [] };
  const io = { api: f.api, sleep: f.sleep, img: c => '/p/' + c.slug, toast() {}, place() {},
    blenderCopy: async input => { seen.blender.push(input); return { host: 'PC' }; }, clipboard: async t => seen.clip.push(t),
    retarget: o => seen.retarget.push(o), assets: q => seen.assets.push(q), chatModel: () => ({ name: 'gemma4:e4b', vision: false }),
    fallbackLive: async o => { seen.live.push(o); return { status: 'swapped' }; } };
  const store = new Map();
  globalThis.localStorage = { getItem: k => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) };
  const menu = PW.characterMenu(doc, io, { sid: 'w1-s1', at: [0.5, 0.5], aspect: 4 / 3, x: 100, y: 100, gid: 'g1', anchor: [10, 10],
    onClose: why => seen.closed.push(why) });
  return { doc, f, seen, menu, io };
}

test('menu: first look, then the local model names it (tool calling on the Spark)', async () => {
  const fx = menuFixture({ pick_preview: { picked: { class: 'pl0000', kind: 'player' } }, pick_name: { name: 'Leon', kind: 'player', route: 'local', llm_model: 'gemma4:e4b' } });
  await tick(10);
  const tools = fx.f.calls.filter(c => c.path === '/api/jobs').map(c => c.body.tool);
  assert.deepEqual(tools, ['pick_preview', 'pick_name']);
  assert.equal(fx.f.calls[1].body.input.model, 'gemma4:e4b');
  assert.match(fx.doc.getElementById('pwmenu').querySelector('.pw-head').innerHTML, /Leon/);
  assert.match(fx.doc.getElementById('pwcon').children[0].querySelector('pre').textContent, /Leon \(gemma4:e4b, local\)/);
});

test('menu: Copy to Blender extracts the model, puts it on the clipboard and writes Blender\'s clipboard', async () => {
  const fx = menuFixture({ pick_preview: { picked: { class: 'bot' } }, pick: { picked: { class: 'bot' }, package: 'auf_bot' } },
    { '/api/uap/auf_bot/clipboard': { sha256: 'abc', name: 'auf_bot' } });
  await tick(10);
  await fx.menu.onPick('blender'); await tick();
  assert.deepEqual(fx.seen.blender, [{ artifact: 'abc' }]);
  assert.deepEqual(fx.seen.closed, ['blender']);
  assert.equal(fx.doc.getElementById('pwmenu').style.display, 'none');
});

test('menu: Export to Blender tags the clipboard for the round trip', async () => {
  const fx = menuFixture({ pick_preview: { picked: { class: 'bot', kind: 'npc' } }, pick: { package: 'auf_bot' } },
    { '/api/uap/auf_bot/clipboard': { sha256: 'abc', name: 'auf_bot' }, '/api/clipboard': b => b });
  await tick(10);
  await fx.menu.onPick('export'); await tick();
  const clip = fx.f.calls.find(c => c.path === '/api/clipboard').body;
  assert.equal(clip.artifact, 'abc'); assert.equal(clip.meta.round_trip, true); assert.equal(clip.meta.session_id, 'w1-s1'); assert.equal(clip.meta.game_id, 'g1');
});

test('menu: Replace with… browses compatible characters and falls back to the live swap', async () => {
  const fx = menuFixture({ pick_preview: { picked: { class: 'Soldier', kind: 'enemy' } } },
    { '/api/characters?game_id=g1': [{ slug: 'amy', name: 'Amy', model: 'm', ready: [{ mod: 'x' }] }, { slug: 'car', name: 'Car', kind: 'vehicle', model: 'c' }] });
  await tick(10);
  await fx.menu.onPick('replace');
  const m = fx.doc.getElementById('pwmenu');
  assert.match(m.querySelector('.pw-grid').innerHTML, /Amy/); assert.doesNotMatch(m.querySelector('.pw-grid').innerHTML, /Car/);
  m.onclick({ target: { closest: () => ({ dataset: { slug: 'amy' }, disabled: false }) } }); await tick(10);
  assert.equal(fx.seen.live[0].character, 'amy');
  assert.deepEqual(fx.seen.closed, ['picked']);
  const pre = fx.doc.getElementById('pwcon').children.at(-1).querySelector('pre').textContent;
  assert.match(pre, /pick_replace is not on this gBox yet/); assert.match(pre, /replaced live \(characters live_use\)/);
});

test('menu: Identify streams into the console; settings toggle; outside click closes once', async () => {
  const fx = menuFixture({ pick_preview: { picked: { class: 'Soldier', ptr: '0x80001' }, evidence: { Soldier: { struct_size: '0x200' } } } });
  await tick(10);
  await fx.menu.onPick('identify'); await tick();
  const pre = fx.doc.getElementById('pwcon').children.at(-1).querySelector('pre').textContent;
  assert.match(pre, /Soldier .*RAM 0x80001 \(pick_preview\)/); assert.match(pre, /struct_size/);
  const fx2 = menuFixture({ pick_preview: { picked: null } });
  await fx2.menu.onPick('pause');
  assert.equal(PW.settings().pause, false);
  fx2.doc.listeners.mousedown[0]({ target: {} }); fx2.doc.listeners.mousedown[0]?.({ target: {} });
  assert.deepEqual(fx2.seen.closed, ['dismiss']);
});
