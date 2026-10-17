// Toasts and floating panels stay inside the window, below the app's header bar (clients/web/viz/toast-stack.js).
// Operator report: a build notification ("Collecting characters failed: Pokémon Shield") showed half off the top of the
// Library page in the desktop app: the toast sat at a fixed 52 px top, but the page's header wraps to two rows (~99 px)
// in the desktop app's narrower view, so the toast started inside the header and its title's first line was cut. Here a
// small fake DOM places toasts in small and large viewports, under short and tall headers, and checks they are clamped,
// stacked newest first, capped so the stack scrolls inside itself, and laid out again on resize / a header that wraps.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const TS = require('../clients/web/viz/toast-stack.js');

// ---- a fake DOM: enough layout for the stack (fixed top/right/width/max-height) and for fixed panels -----------------
const CARD_H = 130, GAP = 8;
function fakeWorld({ vw = 1500, vh = 950, header = 55, footer = 0 } = {}) {
  let clock = 0; const timers = [];
  const resize = [], observers = [];
  const view = {
    innerWidth: vw, innerHeight: vh,
    addEventListener: (ev, fn) => { if (ev === 'resize') resize.push(fn); },
    removeEventListener: (ev, fn) => { const i = resize.indexOf(fn); if (i >= 0) resize.splice(i, 1); },
    getComputedStyle: el => ({ display: el.hidden || el.style.display === 'none' ? 'none' : 'block', visibility: 'visible' }),
    setTimeout: (fn, ms) => { const t = { fn, at: clock + ms, on: true }; timers.push(t); return t; },
    clearTimeout: t => { if (t) t.on = false; },
    ResizeObserver: class { constructor(cb) { this.cb = cb; this.els = []; observers.push(this); } observe(el) { this.els.push(el); } disconnect() { this.els = []; } },
  };
  class El {
    constructor(tag) { this.tagName = tag.toUpperCase(); this.id = ''; this.className = ''; this.style = {}; this.children = []; this.parentNode = null;
      this.attrs = {}; this.hidden = false; this.listeners = {}; this.scrollTop = 0; this._html = ''; this.rect = null; }
    set innerHTML(h) { this._html = h; } get innerHTML() { return this._html; }
    get firstChild() { return this.children[0] || null; }
    appendChild(c) { c.parentNode = this; this.children.push(c); return c; }
    insertBefore(c, ref) { c.parentNode = this; const i = this.children.indexOf(ref); this.children.splice(i < 0 ? this.children.length : i, 0, c); return c; }
    removeChild(c) { const i = this.children.indexOf(c); if (i >= 0) this.children.splice(i, 1); c.parentNode = null; return c; }
    setAttribute(k, v) { this.attrs[k] = String(v); if (k === 'id') this.id = String(v); } getAttribute(k) { return this.attrs[k] ?? null; }
    addEventListener(ev, fn) { (this.listeners[ev] ||= []).push(fn); } removeEventListener() {}
    closest(sel) { const a = /^\[([\w-]+)\]$/.exec(sel); for (let e = this; e; e = e.parentNode) if (a && e.attrs && a[1] in e.attrs) return e; return null; }
    get ownerDocument() { return doc; }
    getBoundingClientRect() {
      if (this.rect) return this.rect();
      const s = this.style, px = v => parseFloat(v) || 0;
      if (this.id === 'gbox-toasts') {                       // the stack: its cards' heights, capped by max-height
        if (this.hidden) return { left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0 };
        const content = this.children.length * CARD_H + Math.max(0, this.children.length - 1) * GAP + 8;
        const h = Math.min(content, s.maxHeight ? px(s.maxHeight) : Infinity), w = px(s.width), right = view.innerWidth - px(s.right);
        return { left: right - w, top: px(s.top), right, bottom: px(s.top) + h, width: w, height: h };
      }
      return { left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0 };
    }
  }
  const all = [];
  const doc = {
    defaultView: view,
    createElement: tag => { const e = new El(tag); all.push(e); return e; },
    getElementById: id => all.find(e => e.id === id && (e.parentNode || e === doc.body || e === doc.head)) || null,
    querySelectorAll: sel => sel.split(',').map(s => s.trim()).flatMap(s => all.filter(e => e.parentNode &&
      (s.startsWith('#') ? e.id === s.slice(1).split('.')[0] && (!s.includes('.') || e.className.split(' ').includes(s.split('.')[1]))
        : e.tagName === s.toUpperCase()))),
  };
  doc.head = new El('head'); doc.body = new El('body'); doc.documentElement = doc.body;
  const bar = (tag, id, top, h) => { const e = doc.createElement(tag); if (id) e.id = id; doc.body.appendChild(e);
    e.rect = () => ({ left: 0, top: top(), right: view.innerWidth, bottom: top() + h(), width: view.innerWidth, height: h() }); return e; };
  const W = { view, doc, timers, observers, headerH: header, footerH: footer };
  W.header = bar('header', '', () => 0, () => W.headerH);
  if (footer) W.footer = bar('div', 'statusbar', () => view.innerHeight - W.footerH, () => W.footerH);
  W.tick = ms => { clock += ms; for (const t of timers.slice()) if (t.on && t.at <= clock) { t.on = false; t.fn(); } };
  W.resize = (w, h) => { view.innerWidth = w; view.innerHeight = h; resize.forEach(fn => fn()); };
  W.observe = () => observers.forEach(o => o.cb([]));
  return W;
}
const inside = (r, W, top) => {
  assert.ok(r.top >= top, `top ${r.top} below the header (${top})`);
  assert.ok(r.bottom <= W.view.innerHeight, `bottom ${r.bottom} inside the window (${W.view.innerHeight})`);
  assert.ok(r.left >= 0, `left ${r.left} inside`); assert.ok(r.right <= W.view.innerWidth, `right ${r.right} inside`);
};
const LONG = n => ({ id: 'n' + n, title: `Collecting characters failed: Pokémon Shield (${n}) with a very long title that wraps`,
  text: 'No native model reader for this game; no unrigged capture was substituted.', ms: 12000 });

test('limits: below the measured header (one row or two), above a footer, inside the window; never hard-coded', () => {
  const one = fakeWorld({ vw: 1500, vh: 950, header: 55 });
  assert.deepEqual(TS.limits(one.doc, { header: 'header' }), { top: 63, bottom: 942, left: 8, right: 1492, vw: 1500, vh: 950 });
  const two = fakeWorld({ vw: 1300, vh: 842, header: 99 });      // the desktop app's webview: the header wraps
  assert.equal(TS.limits(two.doc, { header: 'header' }).top, 107, 'a 99 px header puts the top at 107, not 52');
  const desk = fakeWorld({ vw: 1280, vh: 720, header: 80, footer: 28 });
  assert.deepEqual(TS.limits(desk.doc, { header: 'header', footer: '#statusbar' }), { top: 88, bottom: 684, left: 8, right: 1272, vw: 1280, vh: 720 });
  assert.equal(TS.limits(desk.doc, { header: 'header', footer: '#statusbar', top: () => 135 }).top, 143, 'an embedded page header further down wins');
  const tiny = fakeWorld({ vw: 320, vh: 160, header: 140 });     // no room under the header: inside the window wins
  const L = TS.limits(tiny.doc, { header: 'header' });
  assert.ok(L.bottom <= 160 && L.top >= 0 && L.bottom - L.top >= 96 - 0.5, JSON.stringify(L));
});

test('a large window: the stack sits right under the header in the top-right corner, fully inside', () => {
  const W = fakeWorld({ vw: 1500, vh: 950, header: 55 });
  const s = TS.mount(W.doc, { header: 'header' });
  assert.equal(s.el.hidden, true, 'empty: hidden, so no hole is cut in a docked game');
  s.push(LONG(1));
  assert.equal(s.el.hidden, false);
  assert.equal(s.el.style.top, '63px'); assert.equal(s.el.style.right, '8px'); assert.equal(s.el.style.width, '360px');
  assert.equal(s.el.style.maxHeight, '879px');
  inside(s.el.getBoundingClientRect(), W, 55);
});

test('a small window and a two-row header: still under the header, narrower, capped and scrolling inside', () => {
  const W = fakeWorld({ vw: 720, vh: 520, header: 100 });
  const s = TS.mount(W.doc, { header: 'header' });
  for (let i = 1; i <= 6; i++) s.push(LONG(i));
  const r = s.el.getBoundingClientRect();
  inside(r, W, 100);
  assert.equal(s.el.style.maxHeight, '404px', '520 - 108 top - 8 margin');
  assert.ok(6 * CARD_H > r.height, 'more toasts than room: the stack is capped and scrolls');
  assert.match(TS.CSS, /#gbox-toasts\{[^}]*overflow-y:auto/);
  assert.match(TS.CSS, /\.gts-card\{[^}]*overflow-wrap:anywhere[^}]*white-space:normal/, 'long titles and text wrap');
  const narrow = fakeWorld({ vw: 300, vh: 400, header: 60 });
  const n = TS.mount(narrow.doc, { header: 'header' }); n.push(LONG(1));
  assert.equal(n.el.style.width, '284px'); inside(n.el.getBoundingClientRect(), narrow, 60);
});

test('stacking: newest first, the same id replaces and comes to the top, at most max cards (oldest go)', () => {
  const W = fakeWorld();
  const s = TS.mount(W.doc, { header: 'header', max: 4 });
  ['a', 'b', 'c'].forEach(id => s.push({ id, text: id }));
  assert.deepEqual(s.ids(), ['c', 'b', 'a']);
  s.push({ id: 'a', text: 'a again' });
  assert.deepEqual(s.ids(), ['a', 'c', 'b']);
  s.push({ id: 'd', text: 'd' }); s.push({ id: 'e', text: 'e' });
  assert.deepEqual(s.ids(), ['e', 'd', 'a', 'c'], 'b (the oldest) dropped');
  assert.equal(s.el.scrollTop, 0, 'the newest is in view');
  s.remove('d'); assert.deepEqual(s.ids(), ['e', 'a', 'c']);
  s.clear(); assert.equal(s.size, 0); assert.equal(s.el.hidden, true);
});

test('cards expire after their time, not while hovered; close and action buttons work', () => {
  const W = fakeWorld();
  const s = TS.mount(W.doc, { header: 'header' });
  let shown = 0;
  s.push({ id: 'x', title: 'Build failed', text: 'reason', ms: 3000, actions: [['Show', () => shown++]] });
  s.push({ id: 'y', text: 'stays', ms: 0 });
  W.tick(2999); assert.ok(s.has('x'));
  s.el.listeners.mouseenter[0](); W.tick(5000); assert.ok(s.has('x'), 'hovered: kept');
  s.el.listeners.mouseleave[0](); W.tick(1600); assert.ok(!s.has('x'), 'gone once the pointer left');
  assert.ok(s.has('y'), 'ms 0: until dismissed');
  const html = TS.textHTML({ title: 'T <b>', text: 'x & y', actions: [['Show', () => {}]] });
  assert.match(html, /<b class="gts-t">T &#60;b&#62;<\/b>/); assert.match(html, /data-gts-act="0">Show/); assert.match(html, /data-gts-close/);
  s.push({ id: 'z', text: 'act', actions: [['Show', () => shown++]] });
  const card = s.el.children[0];
  const btn = { closest: sel => sel === '[data-gts]' ? card : sel === '[data-gts-act]' ? { getAttribute: () => '0' } : null };
  s.el.listeners.click[0]({ target: btn });
  assert.equal(shown, 1); assert.ok(!s.has('z'), 'an action closes its card');
  const y = s.el.children.find(c => c.getAttribute('data-gts') === 'y');
  s.el.listeners.click[0]({ target: { closest: sel => sel === '[data-gts]' ? y : sel === '[data-gts-close]' ? {} : null } });
  assert.ok(!s.has('y'));
});

test('resize and a header that wraps to a second row lay the stack out again', () => {
  const W = fakeWorld({ vw: 1500, vh: 950, header: 55 });
  const s = TS.mount(W.doc, { header: 'header' });
  s.push(LONG(1)); s.push(LONG(2));
  assert.equal(s.el.style.top, '63px');
  W.headerH = 99; W.observe();                               // tray chips arrive: the header wraps (ResizeObserver)
  assert.equal(s.el.style.top, '107px');
  W.resize(1280, 720);
  assert.equal(s.el.style.maxHeight, '605px'); inside(s.el.getBoundingClientRect(), W, 99);
  W.resize(640, 360);
  inside(s.el.getBoundingClientRect(), W, 99);
  assert.equal(s.el.style.width, '360px');
  W.resize(300, 360);
  assert.equal(s.el.style.width, '284px'); inside(s.el.getBoundingClientRect(), W, 99);
  s.dispose(); W.resize(1500, 950);
});

test('clampBox: off the top / bottom / right moves back inside; taller than the room is capped', () => {
  const L = { top: 88, bottom: 684, left: 8, right: 1272, vw: 1280, vh: 720 };
  assert.deepEqual(TS.clampBox({ left: 900, top: -40, width: 340, height: 124 }, L),
    { left: 900, top: 88, width: 340, height: 124, maxWidth: 1264, maxHeight: 596, moved: true });
  const tall = TS.clampBox({ left: 876, top: 30, width: 390, height: 640 }, L);
  assert.equal(tall.height, 596); assert.equal(tall.top, 88); assert.equal(tall.maxHeight, 596);
  const right = TS.clampBox({ left: 1200, top: 300, width: 300, height: 100 }, L);
  assert.equal(right.left, 972); assert.equal(right.moved, true);
  assert.equal(TS.clampBox({ left: 100, top: 100, width: 100, height: 100 }, L).moved, false);
});

test('fit(): a bottom-anchored panel (the process pop-up) taller than the room is capped and kept below the header', () => {
  const W = fakeWorld({ vw: 1280, vh: 720, header: 80, footer: 28 });
  const el = W.doc.createElement('div'); W.doc.body.appendChild(el);
  el.style.bottom = '46px'; el.style.right = '14px';
  const natural = 640;
  el.rect = () => { const px = v => parseFloat(v) || 0, h = Math.min(natural, el.style.maxHeight ? px(el.style.maxHeight) : Infinity);
    const top = el.style.top && el.style.top !== 'auto' ? px(el.style.top) : W.view.innerHeight - px(el.style.bottom) - h;
    return { left: 876, top, right: 1266, bottom: top + h, width: 390, height: h }; };
  const f = TS.fit(el, { header: 'header', footer: '#statusbar' });
  assert.equal(el.style.maxHeight, '596px'); assert.equal(el.style.overflowY, 'auto');
  const r = el.getBoundingClientRect();
  inside(r, W, 80); assert.ok(r.bottom <= 720 - 28, 'above the status strip');
  assert.equal(f.moved, true); assert.equal(el.style.bottom, 'auto');
  const pin = W.doc.createElement('div'); W.doc.body.appendChild(pin);       // the bell tray: pinned under the header
  pin.rect = () => ({ left: 1172, top: parseFloat(pin.style.top) || 48, right: 1272, bottom: (parseFloat(pin.style.top) || 48) + 200, width: 100, height: 200 });
  TS.fit(pin, { header: 'header', margin: 4, pinTop: true, maxHeight: 504 });
  assert.equal(pin.style.top, '84px'); assert.equal(pin.style.maxHeight, '504px');
});

test('the last-played pop-up sits below the shell header and scrolls inside the window', () => {
  const LP = require('../clients/web/viz/last-played.js');
  assert.match(LP.CSS, /\.lp-box\{[^}]*max-height:100%;overflow:auto/);
  const html = [];
  let back = null;
  const host = { insertAdjacentHTML: (_, h) => { html.push(h); if (h.includes('lp-back')) back = { style: {}, remove() { back = null; } }; },
    querySelector: s => (s === '.lp-back' ? back : s === '#lp-css' ? (html.length ? {} : null) : null), addEventListener() {}, removeEventListener() {} };
  const lp = LP.mount({ api: async () => ({ entry: null }), host, top: () => 99, poll: 1e9 });
  lp.st.entry = { session_id: 's1', title: 'Pokémon Shield', node: 'JAYBUILTFINALE', node_online: true, reason: { text: 'The game ended.' } };
  lp.draw();
  assert.equal(back.style.paddingTop, '115px', 'header bottom 99 + 16');
  lp.stop();
});

test('wiring: both shells put every toast in the stack, clamp their floating panels and cut the stack out of a docked game', () => {
  const web = fs.readFileSync(path.join(__dirname, '..', 'clients', 'web', 'index.html'), 'utf8');
  const desk = fs.readFileSync(path.join(__dirname, '..', 'clients', 'desktop', 'index.html'), 'utf8');
  const bn = fs.readFileSync(path.join(__dirname, '..', 'clients', 'web', 'viz', 'build-notes.js'), 'utf8');
  const pp = fs.readFileSync(path.join(__dirname, '..', 'clients', 'web', 'viz', 'process-popup.js'), 'utf8');
  const pw = fs.readFileSync(path.join(__dirname, '..', 'clients', 'web', 'viz', 'pick-whip.js'), 'utf8');
  const lb = fs.readFileSync(path.join(__dirname, '..', 'clients', 'web', 'viz', 'launch-bar.js'), 'utf8');
  // the cause: a toast fixed at 52 px from the top, whatever the header's height
  assert.doesNotMatch(bn, /bn-toast\{[^}]*position:fixed/);
  assert.doesNotMatch(bn, /top:52px/);
  // web shell: the stack under the measured header; build notes (several, newest on top) and the Builds / Mods toast
  assert.match(web, /<script src="\/viz\/toast-stack.js"><\/script>\s*<script src="\/viz\/build-notes.js">/);
  assert.match(web, /const TOASTS = GBoxToastStack\.mount\(document, \{ header: "header"/);
  assert.match(web, /TOASTS\.push\(\{ id: "bn:" \+ n\.id, html: GBoxBuildNotes\.toastHTML\(n/);
  assert.match(web, /GBoxBuildNotes\.fresh\(notes, TRAY\.seen\)\.slice\(0, 4\)\.reverse\(\)\.forEach\(bnAnnounce\)/);
  assert.match(web, /function blToast\(t\) \{[^\n]*\n\s+TOASTS\.push\(/);
  assert.doesNotMatch(web, /id="bltoast"|id="bntoast"/);
  // web floating panels: the bell tray, the process pop-up, the mini console, the last-played pop-up
  assert.match(web, /function trayFit\(\) \{[^\n]*GBoxToastStack\.fit\(el, \{ header: "header"[^\n]*pinTop: true/);
  assert.match(web, /addEventListener\("resize", trayFit\)/);
  assert.match(web, /fit: el => GBoxToastStack\.fit\(el, \{ header: 'header' \}\)/);
  assert.match(web, /fit: el => GBoxToastStack\.fit\(el, \{ header: "header" \}\),\s+\/\/ the mini console/);
  assert.match(web, /GBoxLastPlayed\.mount\(\{ api, host: document\.body, top: \(\) => GBoxToastStack\.limits\(document, \{ header: "header"/);
  // desktop shell: toast() and build notes are cards in the stack below the title bar + chat bar (+ the page's header)
  assert.match(desk, /<script src="\.\.\/web\/viz\/toast-stack.js"><\/script>/);
  assert.match(desk, /function toastBounds\(\) \{ return \{ header: "#titlebar, #chatbar", footer: "#statusbar, #launchbar\.on"/);
  assert.match(desk, /function toast\(t, ms = 3500, o = \{\}\) \{\s+const s = toastStack\(\)/);
  assert.match(desk, /function buildNoteMsg\(m\) \{[\s\S]{0,400}actions: \[\["Show", openBuildNotes\]\]/);
  assert.match(desk, /const EMB_HOLES = "[^"]*#gbox-toasts/, 'a docked game window cuts the shell stack out');
  assert.match(desk, /const EMB_GUEST_MENUS = "[^"]*#gbox-toasts/, 'and the embedded page\'s stack');
  assert.match(desk, /fit: el => GBoxToastStack\.fit\(el, toastBounds\(\)\),\s+\/\/ inside the window/);
  assert.match(desk, /PW\.createConsole\(document, \{ drag: dragAnywhere, fit: el => GBoxToastStack\.fit\(el, toastBounds\(\)\) \}\)/);
  // the shared panels take the shell's fit and re-clamp on resize
  assert.match(pp, /opts\.fit\(root\)/); assert.match(pp, /view\.addEventListener\("resize", fitIn\)/);
  assert.match(pw, /function createConsole\(doc, \{ drag, fit \} = \{\}\)/); assert.match(pw, /W\.addEventListener\("resize"/);
  assert.match(pw, /#pwcon \{[^}]*overflow-y:auto/);
  // the launch bar's failure line wraps (a few lines at most, growing up from the bottom edge) instead of cutting off
  assert.match(lb, /#launchbar\.err \{ height:auto;[^}]*max-height:min\(30vh, 76px\)/);
  assert.match(lb, /#launchbar\.err \.lb-static \{ white-space:normal/);
});
