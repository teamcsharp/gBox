// Texture pop-up (#186): the desktop shell's #texpop (zoom at the cursor, fit / 1:1, ‹ › siblings, brightness / contrast,
// checkerboard, channels, save, Esc / click-outside) and the web client's #lbox mirror, driven on a tiny fake DOM.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const desktop = fs.readFileSync(path.join(__dirname, '../clients/desktop/index.html'), 'utf8');
const web = fs.readFileSync(path.join(__dirname, '../clients/web/index.html'), 'utf8');

function node(tag, extra = {}) {
  const n = { tagName: tag.toUpperCase(), children: [], parent: null, style: {}, dataset: {}, listeners: {}, classes: new Set(), textContent: '',
    hidden: false, disabled: false, clicks: 0, ...extra };
  n.classList = { add: (...c) => c.forEach(x => n.classes.add(x)), remove: (...c) => c.forEach(x => n.classes.delete(x)),
    toggle: (c, f) => { (f === undefined ? !n.classes.has(c) : f) ? n.classes.add(c) : n.classes.delete(c); }, contains: c => n.classes.has(c) };
  n.append = (...k) => k.forEach(x => { x.parent = n; n.children.push(x); });
  n.addEventListener = (t, fn) => (n.listeners[t] ||= []).push(fn);
  n.fire = (t, ev = {}) => (n.listeners[t] || []).forEach(fn => fn({ preventDefault() {}, stopPropagation() {}, target: n, ...ev }));
  n.contains = x => { for (; x; x = x.parent) if (x === n) return true; return false; };
  n.closest = () => null; n.matches = () => false; n.click = () => { n.clicks++; };
  n.removeAttribute = k => { delete n[k]; }; n.setPointerCapture = () => {}; n.querySelector = () => null; n.querySelectorAll = () => [];
  n.getBoundingClientRect = () => ({ left: 0, top: 0, width: n.clientWidth || 0, height: n.clientHeight || 0 });
  return n;
}

function desktopFixture({ canvas = false } = {}) {
  const created = [], fits = [], toasts = [], opened = [], doc = {}, win = {}; let fills = 0, fetchOk = false, found = [];
  const ctx2d = { drawImage() {}, putImageData() {}, fillRect() { fills++; },
    getImageData: () => ({ data: Uint8ClampedArray.of(10, 20, 30, 255, 40, 50, 60, 128) }), createImageData: (w, h) => ({ data: new Uint8ClampedArray(w * h * 4) }) };
  const ctx = {
    document: { body: node('body'), createElement: tag => { const n = node(tag); if (tag === 'canvas' && canvas) { n.getContext = () => ctx2d; n.toDataURL = () => 'data:chan'; } created.push(n); return n; },
      addEventListener: (t, fn) => (doc[t] ||= []).push(fn), querySelectorAll: () => found },
    addEventListener: (t, fn) => (win[t] ||= []).push(fn), innerWidth: 1600, innerHeight: 900,
    fitMenu: (el, x, y) => { fits.push([x, y]); el._fitXY = [x, y]; }, dragAnywhere: el => { el._dragAny = true; },
    EMB: { last: 'stale' }, gbox: { openExternal: u => opened.push(u) }, toast: t => toasts.push(t), esc: String,
    URL: { createObjectURL: () => 'blob:one', revokeObjectURL() {} }, setTimeout: () => 0,
    fetch: async () => { if (!fetchOk) throw new Error('blocked'); return { ok: true, blob: async () => ({}) }; },
  };
  ctx.window = ctx;
  vm.createContext(ctx);
  vm.runInContext(desktop.slice(desktop.indexOf('// ---------------- texture pop-up (#186)'), desktop.indexOf('// ---------------- Zelda equip screen (#212)')), ctx);
  Object.assign(ctx, vm.runInContext('({ TP, tpZoomAt, tpFitState, tpWrap, tpStage })', ctx));   // const bindings live in the script scope
  return { ctx, created, fits, toasts, opened, doc, win, fills: () => fills, allowFetch: () => { fetchOk = true; }, setFound: f => { found = f; },
    load: (w, h) => { const img = ctx.TP.img; img.naturalWidth = w; img.naturalHeight = h; img.complete = true; ctx.TP.stage.clientWidth = 740; ctx.TP.stage.clientHeight = 500; img.onload(); } };
}
const list = [{ src: 'data:image/png;base64,AAAA', name: 'skin.png' }, { src: 'http://spark:8080/api/artifacts/abc?token=t', name: 'scene_capture: extracted' }];
const plain = x => JSON.parse(JSON.stringify(x));           // values built inside the vm realm compare by structure

test('zoom keeps the point under the cursor still and stays within 5%..3200%', () => {
  const f = desktopFixture(), z = f.ctx.tpZoomAt;
  const st = z({ k: 1, x: 0, y: 0 }, 2, 100, 50);
  assert.deepEqual(plain(st), { k: 2, x: -100, y: -50 });
  assert.equal((100 - st.x) / st.k, 100); assert.equal((50 - st.y) / st.k, 50);         // image point under (100, 50) unchanged
  const again = z(st, 0.5, 100, 50);
  assert.deepEqual(plain(again), { k: 1, x: 0, y: 0 });
  assert.equal(z({ k: 30, x: 0, y: 0 }, 4, 0, 0).k, 32); assert.equal(z({ k: 0.06, x: 0, y: 0 }, 0.1, 0, 0).k, 0.05);
});

test('fit centres the whole picture in the stage and the sibling index wraps', () => {
  const f = desktopFixture();
  const st = f.ctx.tpFitState(200, 100, 740, 500);
  assert.ok(Math.abs(st.k - 716 / 200) < 1e-9);
  assert.ok(Math.abs(st.x + 200 * st.k / 2 - 370) < 1e-9); assert.ok(Math.abs(st.y + 100 * st.k / 2 - 250) < 1e-9);
  assert.equal(f.ctx.tpFitState(0, 0, 100, 100).k, 76);
  assert.equal(f.ctx.tpWrap(0, -1, 3), 2); assert.equal(f.ctx.tpWrap(2, 1, 3), 0); assert.equal(f.ctx.tpWrap(5, 1, 0), 0);
});

test('opens next to the click, walks the siblings, zooms with the buttons and fits on load', () => {
  const f = desktopFixture(), TP = f.ctx.TP;
  const el = f.ctx.texPopOpen(list, 1, [300, 200]);
  assert.ok(el.classes.has('on')); assert.deepEqual(f.fits, [[316, 160]]); assert.equal(f.ctx.EMB.last, '');
  assert.equal(TP.i, 1); assert.equal(TP.name.textContent, 'scene_capture: extracted'); assert.equal(TP.img.src, list[1].src);
  f.load(256, 128);
  assert.equal(TP.info.textContent, '256×128'); assert.ok(Math.abs(TP.k - 716 / 256) < 1e-9, 'fit: the width is the tighter side');
  assert.equal(TP.chans.hidden, true, 'no readable pixels without a canvas: channel buttons hidden');
  f.ctx.texPopAction('next'); assert.equal(TP.i, 0); assert.equal(TP.img.src, list[0].src);
  f.ctx.texPopAction('prev'); assert.equal(TP.i, 1);
  assert.match(TP.foot.textContent, /2 \/ 2/);
  const k = TP.k; f.ctx.texPopAction('plus'); assert.ok(Math.abs(TP.k - k * 1.25) < 1e-5, 'zoom steps are rounded to a millionth');
  f.ctx.texPopAction('one'); assert.equal(TP.k, 1); assert.match(TP.img.style.transform, /scale\(1\)/);
  f.ctx.texPopAction('minus'); assert.equal(TP.k, 0.8); f.ctx.texPopAction('plus'); assert.equal(TP.k, 1, '0.8 × 1.25 lands on 1 exactly');
  f.ctx.texPopAction('fit'); assert.ok(Math.abs(TP.k - k) < 1e-9);
  const r = f.ctx.tpStage(); f.ctx.TP.stage.fire('wheel', { deltaY: -100, clientX: r[0] / 2, clientY: r[1] / 2 });
  assert.ok(Math.abs(TP.k - k * 1.15) < 1e-5);
});

test('brightness / contrast, checkerboard and pan by drag change the picture, not the window', () => {
  const f = desktopFixture(), TP = f.ctx.TP;
  f.ctx.texPopOpen(list, 0); f.load(64, 64);
  assert.equal(TP.img.style.filter, '');
  TP.inB.value = '150'; TP.inB.oninput(); TP.inC.value = '80'; TP.inC.oninput();
  assert.equal(TP.img.style.filter, 'brightness(150%) contrast(80%)');
  f.ctx.texPopAction('checker'); assert.ok(TP.stage.classes.has('checker')); assert.ok(TP.btn.checker.classes.has('on'));
  f.ctx.texPopAction('checker'); assert.ok(!TP.stage.classes.has('checker'));
  const x0 = TP.x, y0 = TP.y; let stopped = false;
  TP.stage.fire('pointerdown', { button: 0, clientX: 10, clientY: 10, pointerId: 1, stopPropagation() { stopped = true; } });
  assert.ok(stopped, 'the drag never bubbles to dragAnywhere on the window');
  TP.stage.fire('pointermove', { clientX: 40, clientY: 25 }); TP.stage.fire('pointerup', {});
  assert.equal(TP.x, x0 + 30); assert.equal(TP.y, y0 + 15); assert.equal(TP.drag, null);
  f.ctx.texPopOpen(list, 1);
  assert.equal(TP.bright, 100); assert.equal(TP.img.style.filter, '', 'adjustments reset per opening');
});

test('Esc and a click outside close it; keys and clicks inside do not', () => {
  const f = desktopFixture(), TP = f.ctx.TP, key = (k, target = { closest: () => null }) => f.win.keydown.forEach(fn => fn({ key: k, target, preventDefault() {}, stopPropagation() {} }));
  const el = f.ctx.texPopOpen(list, 0); f.load(8, 8);
  key('ArrowRight'); assert.equal(TP.i, 1); key('ArrowLeft'); assert.equal(TP.i, 0);
  key('+'); assert.ok(TP.k > 1); key('0'); key('Escape', { closest: () => ({}) }); assert.ok(el.classes.has('on'), 'typing in a field keeps it open');
  key('Escape'); assert.ok(!el.classes.has('on')); assert.equal(TP.list.length, 0);
  f.ctx.texPopOpen(list, 0);
  const down = target => f.doc.mousedown.forEach(fn => fn({ target }));
  down(TP.stage); assert.ok(el.classes.has('on'));
  down(node('div', { closest: () => null })); assert.ok(!el.classes.has('on'));
  f.ctx.texPopOpen(list, 0); assert.equal(f.fits.length, 3, 'placed on every opening while it was never dragged');
  el._fitXY = null;                                            // dragAnywhere clears the fit once the operator moved it
  f.ctx.texPopOpen(list, 1); assert.equal(f.fits.length, 3, 'stays where it was dropped');
});

test('Save downloads data URLs directly and hands blocked cross-origin pictures to the browser', async () => {
  const f = desktopFixture();
  f.ctx.texPopOpen(list, 0); await f.ctx.texPopSave();
  const a = f.created.filter(n => n.tagName === 'A').at(-1);
  assert.equal(a.href, list[0].src); assert.equal(a.download, 'skin.png'); assert.equal(a.clicks, 1); assert.match(f.toasts.at(-1), /skin\.png/);
  f.ctx.texPopAction('next'); await f.ctx.texPopSave();
  assert.deepEqual(f.opened, [list[1].src]); assert.match(f.toasts.at(-1), /browser/);
  f.allowFetch(); await f.ctx.texPopSave();
  const b = f.created.filter(n => n.tagName === 'A').at(-1);
  assert.equal(b.href, 'blob:one'); assert.equal(b.download, 'scene_capture_extracted.png'); assert.equal(b.clicks, 1);
});

test('readable pixels enable the channel views and the histogram', () => {
  const f = desktopFixture({ canvas: true }), TP = f.ctx.TP;
  f.ctx.texPopOpen(list, 0); f.load(2, 1);
  assert.equal(TP.chans.hidden, false); assert.equal(TP.data.length, 8); assert.ok(f.fills() > 0, 'histogram drawn');
  f.ctx.texPopAction('ch:R'); assert.equal(TP.ch, 'R'); assert.equal(TP.img.src, 'data:chan');
  assert.ok(TP.chBtns.find(b => b.dataset.a === 'ch:R').classes.has('on'));
  f.ctx.texPopAction('ch:RGB'); assert.equal(TP.img.src, list[0].src);
  TP.stage.fire('pointermove', { clientX: TP.x + TP.k * 1.5, clientY: TP.y + TP.k * 0.5 });
  assert.match(TP.foot.textContent, /x 1 y 0 · R 40 G 50 B 60 A 128/);
});

test('a click on a thumbnail opens it with every sibling of its kind', () => {
  const f = desktopFixture(), TP = f.ctx.TP;
  const a = node('img', { src: 'data:a', alt: 'a.png' }), b = node('img', { src: 'data:thumb', tpSrc: 'data:full', dataset: { name: 'wall' } });
  for (const im of [a, b]) { im.matches = s => s === '.tpable'; im.closest = s => s.includes('.tpable') ? im : null; }
  f.setFound([a, b]);
  f.doc.click.forEach(fn => fn({ target: b, clientX: 50, clientY: 60, preventDefault() {}, stopPropagation() {} }));
  assert.equal(TP.i, 1); assert.deepEqual(plain(TP.list), [{ src: 'data:a', name: 'a.png' }, { src: 'data:full', name: 'wall' }]);
  assert.deepEqual(plain(f.fits.at(-1)), [66, 40]);
});

// ---------- web client: the same controls on its #lbox lightbox ----------
function webFixture() {
  const img = node('img'), nameEl = node('b'), lbox = node('div'), inputs = [node('input'), node('input')], nav = [node('button'), node('button')], win = {}, doc = {};
  lbox.style.display = 'none'; let found = [];
  lbox.querySelector = () => img; lbox.querySelectorAll = sel => sel.includes('data-adj') ? inputs : nav;
  const ctx = { document: { body: { insertAdjacentHTML() {} }, addEventListener: (t, fn) => (doc[t] ||= []).push(fn), querySelectorAll: () => found, createElement: tag => node(tag) },
    $: s => s === '#lbox' ? lbox : s === '#lbox-name' ? nameEl : null, addEventListener: (t, fn) => (win[t] ||= []).push(fn),
    innerWidth: 1000, innerHeight: 800, URL: { createObjectURL: () => 'blob:x' }, fetch: async () => ({ blob: async () => ({}) }), open() {} };
  vm.createContext(ctx);
  vm.runInContext(web.slice(web.indexOf('// click a mod thumbnail or any texture (img.tpable)'), web.indexOf('// right-click any option: with a game open')), ctx);
  ctx.LB = vm.runInContext('LB', ctx);
  return { ctx, img, nameEl, lbox, inputs, nav, win, doc, setFound: f => { found = f; },
    click: z => lbox.fire('click', { target: { closest: () => ({ dataset: { z } }) } }) };
}

test('web lightbox walks siblings, adjusts, toggles the checkerboard and saves', async () => {
  const w = webFixture(), LB = w.ctx.LB, items = [{ src: 'a.png', name: 'A' }, { src: 'b.png?w=96', name: 'B' }];
  w.ctx.lbOpen(null, items, 1);
  assert.equal(w.lbox.style.display, 'block'); assert.equal(w.img.src, 'b.png?w=96'); assert.equal(w.nameEl.textContent, 'B · 2 / 2');
  assert.equal(w.nav[0].disabled, false);
  w.click('next'); assert.equal(LB.i, 0); w.click('prev'); assert.equal(LB.i, 1);
  w.win.keydown.forEach(fn => fn({ key: 'ArrowRight', target: { closest: () => null } })); assert.equal(LB.i, 0);
  w.click('checker'); assert.match(w.lbox.style.background, /conic-gradient/); w.click('checker'); assert.equal(w.lbox.style.background, '#000d');
  w.lbox.fire('input', { target: { dataset: { adj: 'bright' }, value: '200' } }); assert.equal(w.img.style.filter, 'brightness(200%) contrast(100%)');
  w.click('1.25'); assert.equal(LB.k, 1.25); w.click('1:1'); assert.equal(LB.k, 1);
  await w.ctx.lbSave();
  w.click('x'); assert.equal(w.lbox.style.display, 'none'); assert.equal(LB.list.length, 0);
  w.ctx.lbOpen('single.png'); assert.equal(w.img.src, 'single.png'); assert.equal(w.nav[0].disabled, true); assert.equal(LB.bright, 100);
  const im = node('img', { src: 'x.png?w=96', alt: 'X' }); im.matches = s => s.startsWith('.wbm'); im.closest = s => s.includes('.wbm') ? im : null;
  w.setFound([im]); w.doc.click.forEach(fn => fn({ target: im, preventDefault() {}, stopPropagation() {} }));
  assert.deepEqual(plain(LB.list), [{ src: 'x.png?', name: 'X' }]);
});
