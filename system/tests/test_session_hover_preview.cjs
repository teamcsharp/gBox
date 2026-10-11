const { test } = require('node:test');
const assert = require('node:assert/strict');
const { placement, controller, mount } = require('../clients/web/viz/session-hover-preview.js');
const flush = () => new Promise(resolve => setImmediate(resolve));
function setup(fetchFrame) {
  let id = 0;
  const timers = new Map(), frames = [], statuses = [];
  const view = controller({ fetchFrame, showFrame: (frame, key) => frames.push({ frame, key }),
    showStatus: text => statuses.push(text),
    setTimer(fn, ms) { timers.set(++id, { fn, ms }); return id; }, clearTimer: n => timers.delete(n) });
  return { view, timers, frames, statuses, tick(ms) {
    for (const [key, timer] of [...timers]) if (timer.ms === ms) { timers.delete(key); timer.fn(); }
  } };
}
test('preview flips above a low anchor and stays inside a small viewport', () => {
  const p = placement({ right: 800, top: 680, bottom: 720 }, { width: 900, height: 740 });
  assert.ok(p.y + p.height < 680);
  const small = placement({ right: 220, top: 155, bottom: 175 }, { width: 240, height: 170 });
  assert.ok(small.x >= 8 && small.y >= 8 && small.x + small.width <= 232 && small.y + small.height <= 162);
});
test('actual guest native bounds leave the whole preview in its free sidebar', () => {
  const p = placement({ right: 600, top: 10, bottom: 42 }, { width: 1220, height: 842 },
    { x: 16, y: 120, width: 854, height: 650 });
  assert.ok(p.x >= 878 && p.x + p.width <= 1212 && p.y + p.height <= 834);
});
test('left sidebar is usable when the game occupies the right side', () => {
  const p = placement({ right: 500, top: 70, bottom: 110 }, { width: 1000, height: 700 },
    { x: 370, y: 120, width: 622, height: 572 });
  assert.ok(p.x + p.width <= 362);
});
test('closing during a delayed frame aborts and discards that response', async () => {
  let resolve, signal;
  const s = setup((key, abort) => { signal = abort; return new Promise(done => resolve = done); });
  s.view.open('one'); s.view.close(); resolve('old'); await flush();
  assert.ok(signal.aborted); assert.equal(s.frames.length, 0); assert.equal(s.timers.size, 0);
});
test('switching chips prevents an old response from replacing the new session', async () => {
  const replies = {};
  const s = setup(key => new Promise(resolve => replies[key] = resolve));
  s.view.open('one'); s.view.open('two'); replies.two('new'); await flush(); replies.one('stale'); await flush();
  assert.deepEqual(s.frames, [{ frame: 'new', key: 'two' }]); s.view.close();
});
test('polling waits for completion and exists only while preview is open', async () => {
  let calls = 0, resolve;
  const s = setup(() => { calls++; return new Promise(done => resolve = done); });
  s.view.open('one'); assert.equal(calls, 1); assert.equal([...s.timers.values()].filter(t => t.ms === 3000).length, 0);
  resolve('frame'); await flush(); assert.equal([...s.timers.values()].filter(t => t.ms === 3000).length, 1);
  s.tick(3000); assert.equal(calls, 2); s.view.close(); assert.equal(s.timers.size, 0);
});
test('missing frames are stated honestly and a later failed refresh labels the retained screenshot', async () => {
  let fail = true;
  const s = setup(async () => { if (fail) throw Error('404'); return 'frame'; });
  s.view.open('one'); await flush(); assert.match(s.statuses.at(-1), /not available/);
  fail = false; s.tick(3000); await flush(); assert.equal(s.frames.length, 1);
  fail = true; s.tick(3000); await flush(); assert.equal(s.statuses.at(-1), 'Frame unavailable; last screenshot shown');
  s.view.close();
});
test('a slow request is aborted after five seconds and may retry without parallel polling', async () => {
  let signal;
  const s = setup((key, abort) => { signal = abort; return new Promise((resolve, reject) => abort.addEventListener('abort', () => reject(Error('timeout')))); });
  s.view.open('one'); s.tick(5000); await flush(); assert.ok(signal.aborted);
  assert.match(s.statuses.at(-1), /not available/); assert.equal([...s.timers.values()].filter(t => t.ms === 3000).length, 1);
  s.view.close(); assert.equal(s.timers.size, 0);
});
test('a normal tray redraw transfers the open preview without new fetches, while true removal closes it', () => {
  const listeners = {}, panels = [], requests = [];
  let observer, chips = [];
  const element = () => ({ style: {}, attributes: {}, textContent: '', isConnected: true,
    setAttribute(k, v) { this.attributes[k] = v; }, getAttribute(k) { return this.attributes[k] ?? null; },
    removeAttribute(k) { delete this.attributes[k]; }, contains(target) { return target === this; },
    addEventListener() {}, getBoundingClientRect() { return { x: 100, y: 20, width: 100, height: 30, right: 200, top: 20, bottom: 50 }; } });
  const children = Object.fromEntries(['.preview-title', 'img', '.preview-status', 'button'].map(selector => [selector, element()]));
  const tray = element();
  const doc = { head: { append() {} }, body: { append(panel) { panels.push(panel); } },
    getElementById(id) { return id === 'tray' ? tray : panels.find(panel => panel.id === id) || null; },
    createElement() { const e = element(); e.querySelector = selector => children[selector]; return e; },
    querySelectorAll() { return chips; }, addEventListener(name, fn) { listeners[name] = fn; } };
  const win = { innerWidth: 1000, innerHeight: 700, setTimeout, clearTimeout, addEventListener() {},
    URL: { revokeObjectURL() {}, createObjectURL() { return 'blob:test'; } },
    fetch(url, options) { requests.push({ url, signal: options.signal }); return new Promise(() => {}); },
    MutationObserver: class { constructor(fn) { observer = fn; } observe() {} } };
  const chip = (description) => { const e = element(); e.dataset = { sid: 'full-session-id' };
    e.closest = () => e; e.querySelector = () => ({ textContent: 'Same game' });
    if (description) e.setAttribute('aria-describedby', description); return e; };
  const old = chip('old-description'); chips = [old];
  const result = mount({ document: doc, window: win, url: path => path });
  try {
    listeners.focusin({ target: old }); assert.equal(requests.length, 1);
    const replacement = chip('new-description'); old.isConnected = false; chips = [replacement]; observer();
    assert.equal(result.panel.style.display, 'grid');
    assert.equal(requests.length, 1); assert.equal(requests[0].signal.aborted, false);
    assert.equal(old.getAttribute('aria-describedby'), 'old-description');
    assert.equal(replacement.getAttribute('aria-describedby'), 'new-description session-hover-preview');
    replacement.isConnected = false; chips = []; observer();
    assert.equal(result.panel.style.display, 'none'); assert.equal(requests[0].signal.aborted, true);
    assert.equal(replacement.getAttribute('aria-describedby'), 'new-description');
  } finally { result.close(); }
});
