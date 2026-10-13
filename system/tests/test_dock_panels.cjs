// Dock (#262): a panel dragged by its header onto the sidebar becomes a collapsible dock item (the game takes the freed
// room), its header opens / collapses it through the panel's own opener, dragging the header out or its arrow floats it
// again, and the layout survives a restart (localStorage.gbox_dock), including panels that are created later. Driven on
// clients/desktop/dock.js with a tiny fake DOM; the desktop shell's hooks are checked as text.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../clients/desktop/dock.js'), 'utf8');
const desktop = fs.readFileSync(path.join(__dirname, '../clients/desktop/index.html'), 'utf8');

function node(tag, sel = '') {
  const n = { tagName: tag.toUpperCase(), sel, id: '', children: [], parent: null, style: {}, dataset: {}, listeners: {}, classes: new Set(), textContent: '', hidden: false, attrs: {}, clicks: 0 };
  n.style.removeProperty = k => { delete n.style[k]; };
  Object.defineProperty(n, 'className', { get: () => [...n.classes].join(' '), set: v => { n.classes = new Set(String(v).split(/\s+/).filter(Boolean)); } });
  n.classList = { add: (...c) => c.forEach(x => n.classes.add(x)), remove: (...c) => c.forEach(x => n.classes.delete(x)), contains: c => n.classes.has(c),
    toggle: (c, f) => { const on = f === undefined ? !n.classes.has(c) : !!f; on ? n.classes.add(c) : n.classes.delete(c); return on; } };
  const detach = x => { if (x.parent) { x.parent.children.splice(x.parent.children.indexOf(x), 1); x.parent = null; } };
  n.append = (...k) => k.forEach(x => { detach(x); x.parent = n; n.children.push(x); });
  n.before = x => { const p = n.parent; detach(x); x.parent = p; p.children.splice(p.children.indexOf(n), 0, x); };
  n.remove = () => detach(n);
  n.addEventListener = (t, fn) => (n.listeners[t] ||= []).push(fn);
  n.fire = (t, ev = {}) => (n.listeners[t] || []).forEach(fn => fn({ preventDefault() {}, stopPropagation() {}, target: n, button: 0, ...ev }));
  n.click = () => { n.clicks++; n.fire('click'); };
  n.setAttribute = (k, v) => { n.attrs[k] = v; };
  n.querySelector = s => n.children.map(c => c.sel === s ? c : c.querySelector(s)).find(Boolean) || null;
  const matches = (x, s) => s.split(',').map(z => z.trim()).some(part => x.sel === part || x.tagName.toLowerCase() === part || (part.startsWith('.') && x.classes.has(part.slice(1))));
  n.closest = s => { for (let x = n; x; x = x.parent) if (matches(x, s)) return x; return null; };
  n.getBoundingClientRect = () => n.rect || { left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0 };
  return n;
}

function fixture({ stored = null, navc = false } = {}) {
  const reg = {}, created = [], timers = [], store = new Map(), floats = [], layouts = [], docListeners = {}, winListeners = {};
  if (stored) store.set('gbox_dock', JSON.stringify(stored));
  const body = node('body'), head = node('head'), aside = node('aside', '.app > aside'), st = node('div', '.st');
  aside.rect = { left: 0, top: 36, right: 200, bottom: 900, width: 200, height: 864 }; aside.append(node('button'), st);
  if (navc) body.classes.add('navc');
  const panel = (sel, handleSel, { on = true, opener = null } = {}) => {
    const el = node('div', sel), handle = node('div', handleSel); el.id = sel.slice(1);
    const btn = node('button'); handle.append(btn); el.append(handle); body.append(el);
    if (on) el.classes.add('on');
    Object.assign(el.style, { position: 'fixed', left: '40px', top: '90px', width: '600px', height: '400px' });
    el.__floatingDestroy = () => { el.destroyed = (el.destroyed || 0) + 1; delete el.__floatingDestroy; };
    reg[sel] = el; reg[handleSel] = handle;
    if (opener) { const o = node('button', opener); o.addEventListener('click', () => el.classList.toggle('on')); reg[opener] = o; }
    return { el, handle, btn };
  };
  const chat = panel('#chatpanel', '#chathead', { opener: '#sb-chat' });
  const remote = panel('#remote-pip', '#remote-pip .rp-head');
  const ctx = {
    document: { body, head, querySelector: s => reg[s] || null, createElement: tag => { const n = node(tag); created.push(n); return n; },
      addEventListener: (t, fn) => (docListeners[t] ||= []).push(fn) },
    localStorage: null, setTimeout: fn => { timers.push(fn); return 1; },
  };
  ctx.window = { addEventListener: (t, fn) => (winListeners[t] ||= []).push(fn), floating: (el, handle, key) => floats.push([el, handle, key]) };
  vm.createContext(ctx);
  vm.runInContext(source, ctx);
  const Dock = ctx.window.GBoxDock;
  const storage = { getItem: k => store.has(k) ? store.get(k) : null, setItem: (k, v) => store.set(k, v) };
  Dock.mount({ document: ctx.document, window: ctx.window, storage, aside, onLayout: wide => layouts.push(wide) });
  const docFire = (t, ev) => (docListeners[t] || []).forEach(fn => fn({ preventDefault() {}, button: 0, ...ev }));
  const winFire = (t, ev) => (winListeners[t] || []).forEach(fn => fn({ preventDefault() {}, ...ev }));
  const flush = () => { timers.splice(0).forEach(fn => fn()); };
  return { Dock, reg, aside, body, st, chat, remote, store, floats, layouts, created, docFire, winFire, flush, dock: () => aside.querySelector('#dock') || aside.children.find(c => c.id === 'dock') };
}
const saved = f => JSON.parse(f.store.get('gbox_dock'));
const plain = x => JSON.parse(JSON.stringify(x));           // values built inside the vm realm compare by structure

test('a point counts as a drop only inside a visible sidebar', () => {
  const f = fixture(), r = { left: 0, top: 36, right: 200, bottom: 900, width: 200, height: 864 };
  assert.equal(f.Dock.hit(r, 100, 300), true); assert.equal(f.Dock.hit(r, 240, 300), false); assert.equal(f.Dock.hit(r, 100, 20), false);
  assert.equal(f.Dock.hit({ ...r, width: 0, right: 0 }, 0, 300), false, 'a folded sidebar is no target'); assert.equal(f.Dock.hit(null, 1, 1), false);
});

test('docking moves the panel into a dock item before the status block, widens the sidebar and remembers the layout', () => {
  const f = fixture(), item = () => f.chat.el.parent;
  assert.equal(f.Dock.dock('#chatpanel'), true);
  assert.equal(item().classes.has('dock-item'), true); assert.equal(item().dataset.dock, '#chatpanel');
  assert.equal(item().parent.id, 'dock'); assert.equal(item().parent.parent, f.aside);
  assert.ok(f.aside.children.indexOf(item().parent) < f.aside.children.indexOf(f.st), 'the dock sits above the status dots');
  assert.equal(f.chat.el.destroyed, 1, 'the floating geometry handler is released'); assert.equal(f.chat.el.style.left, undefined, 'inline geometry is cleared');
  assert.equal(f.chat.el.classes.has('docked'), true); assert.equal(f.chat.el.classes.has('on'), true);
  assert.equal(item().classes.has('collapsed'), false); assert.equal(f.body.classes.has('dockwide'), true); assert.deepEqual(f.layouts, [true]);
  assert.deepEqual(saved(f), { items: ['#chatpanel'], on: { '#chatpanel': true } });
  assert.equal(f.Dock.dock('#chatpanel'), false, 'already docked'); assert.equal(f.Dock.dock('#nothing'), false);
  const head = item().children[0];
  assert.equal(head.classes.has('dock-head'), true); assert.equal(head.children[1].textContent, 'Chat'); assert.equal(head.children[2].attrs['aria-label'], 'Undock Chat');
});

test('the item header opens and collapses through the panel opener; a panel without one toggles itself', () => {
  const f = fixture(); f.Dock.dock('#chatpanel'); f.Dock.dock('#remote-pip', false);
  const chatItem = f.chat.el.parent, remoteItem = f.remote.el.parent, head = chatItem.children[0];
  assert.equal(remoteItem.classes.has('collapsed'), true); assert.equal(f.remote.el.classes.has('on'), false);
  head.fire('click', { target: head });
  assert.equal(f.reg['#sb-chat'].clicks, 1, 'the status-bar Chat button does the opening work');
  assert.equal(f.chat.el.classes.has('on'), false); assert.equal(chatItem.classes.has('collapsed'), true);
  assert.equal(f.body.classes.has('dockwide'), false, 'all collapsed: the game gets the room back'); assert.deepEqual(f.layouts, [true, false]);
  assert.deepEqual(saved(f).on, { '#chatpanel': false, '#remote-pip': false });
  assert.equal(f.Dock.toggle('#remote-pip'), true); assert.equal(remoteItem.classes.has('collapsed'), false); assert.equal(f.body.classes.has('dockwide'), true);
  assert.equal(f.Dock.toggle('#missing'), false);
});

test('undocking floats the panel again: the arrow puts it back where it floated, a drag lands it under the pointer', () => {
  const f = fixture(); f.store.set('gbox_float_chat', JSON.stringify({ x: 500, y: 200, w: 700, h: 420 }));
  f.Dock.dock('#chatpanel'); f.Dock.dock('#remote-pip');
  const out = f.chat.el.parent.children[0].children[2];
  out.fire('click', { target: out });
  assert.equal(f.chat.el.parent, f.body); assert.equal(f.chat.el.classes.has('docked'), false); assert.equal(f.Dock.isDocked('#chatpanel'), false);
  assert.deepEqual(f.floats.at(-1), [f.chat.el, f.chat.handle, 'chat'], 'floating is re-armed with its own key');
  assert.deepEqual(JSON.parse(f.store.get('gbox_float_chat')), { x: 500, y: 200, w: 700, h: 420 }, 'no pointer: the old spot stays');
  assert.deepEqual(saved(f), { items: ['#remote-pip'], on: { '#remote-pip': true } });
  f.Dock.dock('#chatpanel');
  assert.equal(f.Dock.undock('#chatpanel', { x: 640, y: 300 }), true);
  assert.deepEqual(JSON.parse(f.store.get('gbox_float_chat')), { x: 560, y: 286, w: 700, h: 420 }, 'at the pointer, same size as before');
  assert.equal(f.Dock.undock('#remote-pip', { x: 900, y: 400 }), true);
  assert.equal(f.remote.el.style.left, '820px'); assert.equal(f.remote.el.style.top, '386px'); assert.equal(f.remote.el.style.right, 'auto');
  assert.equal(f.floats.filter(x => x[0] === f.remote.el).length, 0, 'Other PC has its own drag, not floating()');
  assert.equal(f.body.classes.has('dockwide'), false); assert.equal(f.dock().hidden, true);
  assert.equal(f.Dock.undock('#chatpanel'), false, 'not docked');
});

test('dragging a panel header onto the sidebar docks it; controls, tiny moves and a folded sidebar do not', () => {
  const f = fixture();
  f.docFire('pointerdown', { target: f.chat.btn, pointerId: 1, clientX: 100, clientY: 100 });
  f.winFire('pointermove', { pointerId: 1, clientX: 100, clientY: 300 }); f.winFire('pointerup', { pointerId: 1, clientX: 100, clientY: 300 });
  assert.equal(f.Dock.isDocked('#chatpanel'), false, 'a button in the header is a click, not a drag');
  f.docFire('pointerdown', { target: f.chat.handle, pointerId: 2, clientX: 400, clientY: 100 });
  f.winFire('pointermove', { pointerId: 2, clientX: 403, clientY: 101 });
  assert.equal(f.aside.classes.has('dock-target'), false, 'not moved yet');
  f.winFire('pointermove', { pointerId: 2, clientX: 120, clientY: 300 });
  assert.equal(f.aside.classes.has('dock-target'), true, 'over the sidebar: the drop target lights up');
  f.winFire('pointermove', { pointerId: 2, clientX: 420, clientY: 300 });
  assert.equal(f.aside.classes.has('dock-target'), false);
  f.winFire('pointermove', { pointerId: 2, clientX: 110, clientY: 500 });
  f.winFire('pointermove', { pointerId: 9, clientX: 900, clientY: 500 });
  f.winFire('pointerup', { pointerId: 2, clientX: 110, clientY: 500 });
  assert.equal(f.Dock.isDocked('#chatpanel'), true); assert.equal(f.aside.classes.has('dock-target'), false);
  const g = fixture({ navc: true });
  g.docFire('pointerdown', { target: g.chat.handle, pointerId: 3, clientX: 400, clientY: 100 });
  g.winFire('pointermove', { pointerId: 3, clientX: 100, clientY: 300 }); g.winFire('pointerup', { pointerId: 3, clientX: 100, clientY: 300 });
  assert.equal(g.Dock.isDocked('#chatpanel'), false, 'a hidden sidebar cannot take a drop');
  const h = fixture();
  h.docFire('pointerdown', { target: h.chat.handle, pointerId: 4, clientX: 100, clientY: 200, button: 2 });
  h.winFire('pointermove', { pointerId: 4, clientX: 120, clientY: 400 }); h.winFire('pointerup', { pointerId: 4, clientX: 120, clientY: 400 });
  assert.equal(h.Dock.isDocked('#chatpanel'), false, 'only the primary button drags');
});

test('dragging a dock item header out of the sidebar floats the panel at the pointer, and that drag is not a click', () => {
  const f = fixture(); f.Dock.dock('#chatpanel');
  const head = f.chat.el.parent.children[0];
  head.fire('pointerdown', { target: head, pointerId: 5, clientX: 80, clientY: 120 });
  f.winFire('pointermove', { pointerId: 5, clientX: 84, clientY: 122 });
  assert.equal(f.Dock.isDocked('#chatpanel'), true, 'a nudge inside the sidebar does nothing');
  f.winFire('pointermove', { pointerId: 5, clientX: 260, clientY: 140 });
  assert.equal(f.Dock.isDocked('#chatpanel'), false, 'past the sidebar edge it pops out');
  assert.deepEqual(JSON.parse(f.store.get('gbox_float_chat')), { x: 180, y: 126 });
  f.winFire('pointerup', { pointerId: 5, clientX: 260, clientY: 140 }); head.fire('click', { target: head }); f.flush();
  assert.equal(f.reg['#sb-chat'].clicks, 0, 'the release after a drag does not toggle the panel');
  f.Dock.dock('#chatpanel'); const head2 = f.chat.el.parent.children[0];
  head2.fire('pointerdown', { target: head2, pointerId: 6, clientX: 80, clientY: 120 });
  f.winFire('pointermove', { pointerId: 6, clientX: 90, clientY: 160 });
  f.winFire('pointerup', { pointerId: 6, clientX: 90, clientY: 160 }); head2.fire('click', { target: head2 });
  assert.equal(f.reg['#sb-chat'].clicks, 0, 'a drag that stayed inside is not a click either'); f.flush();
  head2.fire('pointerdown', { target: head2, pointerId: 7, clientX: 80, clientY: 120 }); f.winFire('pointerup', { pointerId: 7, clientX: 80, clientY: 120 });
  head2.fire('click', { target: head2 }); assert.equal(f.reg['#sb-chat'].clicks, 1, 'a plain click toggles');
});

test('the remembered layout comes back at start, and a panel created later docks itself when it appears', () => {
  const f = fixture({ stored: { items: ['#chatpanel', '#items', '#bogus'], on: { '#chatpanel': false, '#items': true } } });
  assert.equal(f.Dock.isDocked('#chatpanel'), true); assert.equal(f.chat.el.classes.has('on'), false); assert.equal(f.chat.el.parent.classes.has('collapsed'), true);
  assert.deepEqual(plain(f.Dock.docked()), ['#chatpanel']); assert.equal(f.body.classes.has('dockwide'), false);
  const items = node('div', '#items'), ah = node('div', '#items .ah'); items.id = 'items'; items.append(ah); f.body.append(items); f.reg['#items'] = items; f.reg['#items .ah'] = ah;
  f.Dock.appeared();
  assert.deepEqual(plain(f.Dock.docked()), ['#chatpanel', '#items']); assert.equal(items.classes.has('on'), true); assert.equal(f.body.classes.has('dockwide'), true);
  assert.deepEqual(saved(f), { items: ['#chatpanel', '#items'], on: { '#chatpanel': false, '#items': true } }, 'an unknown panel is dropped from the layout');
});

test('the desktop shell loads the dock after its panels, keeps docked panels on click-away and out of the game geometry', () => {
  assert.match(desktop, /<script src="dock\.js"><\/script>/);
  assert.match(desktop, /GBoxDock\.mount\(\{ floating, onLayout: \(\) => \{ EMB\.last = ""; setTimeout\(\(\) => dispatchEvent\(new Event\("resize"\)\), 200\); \} \}\);/);
  assert.ok(desktop.indexOf('GBoxDock.mount(') > desktop.indexOf('floating($("#svcpanel")'), 'mounted once every panel exists and floats');
  assert.match(desktop, /if \(!el \|\| el\.closest\("#dock"\) \|\| \(target &&/, 'closePops leaves docked panels alone');
  assert.match(desktop, /\$\("#live"\)\.classList\.contains\("on"\) && !\$\("#live"\)\.closest\("#dock"\)/, 'a docked talk sidebar takes no room from the game');
  assert.match(desktop, /aside > button \{ text-align:left;/, 'the nav button style no longer reaches into docked panels');
  assert.ok(!/\n\s*aside button \{/.test(desktop));
  assert.match(source, /body\.dockwide:not\(\.navc\) \.app\.has-assets \{ grid-template-columns:var\(--dock-w,370px\) minmax\(0,1fr\) var\(--assets-width,280px\); \}/);
});
