// docs/stream-stability.md: the operator's streamed game must never go black on a stall, reconnect or rebuild.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');
const w = require('../clients/web/viz/stream-watchdog.js');

function harness({ health = async () => ({ state: 'running', age_s: 0.1 }), preloadOk = true } = {}) {
  let t = 0; const timers = []; const logs = []; const preloaded = [];
  const setTimer = (fn, ms) => timers.push([t + ms, fn]);
  const run = until => { for (;;) { timers.sort((a, b) => a[0] - b[0]); if (!timers.length || timers[0][0] > until) break;
    const [at, fn] = timers.shift(); t = at; fn(); } t = until; };
  const body = { kids: [], append(el) { this.kids.push(el); el.parent = this; } };
  const doc = { body, imgs: [], addEventListener() {}, querySelectorAll() { return this.imgs; },
    createElement: () => ({ style: {}, attrs: {}, setAttribute(k, v) { this.attrs[k] = v; }, remove() { body.kids.splice(body.kids.indexOf(this), 1); } }) };
  const img = src => ({ tagName: 'IMG', isConnected: true, naturalWidth: 640, style: {}, a: { src, alt: 'Live game view' },
    getAttribute(k) { return this.a[k]; }, setAttribute(k, v) { this.a[k] = v; },
    getBoundingClientRect: () => ({ left: 10, top: 20, width: 640, height: 480 }) });
  const state = { health };
  const dog = w.createStreamWatchdog({ doc, setTimer, now: () => t, log: m => logs.push(m), env: null,
    preload: url => { preloaded.push(url); return preloadOk ? Promise.resolve(url) : Promise.reject(new Error('x')); },
    fetchHealth: src => state.health(src) });
  const flush = () => new Promise(r => setImmediate(r));
  return { dog, doc, img, run, logs, preloaded, body, state, flush, now: () => t };
}

test('side URLs keep the session and auth query', () => {
  assert.equal(w.frameUrl('/api/sessions/a-b/mjpeg?token=t&reconnect=3', 5), '/api/sessions/a-b/frame.jpg?token=t&t=5');
  assert.equal(w.healthUrl('http://spark:8765/api/sessions/a-b/mjpeg?token=t'), 'http://spark:8765/api/sessions/a-b/stream/health?token=t');
  assert.equal(w.sessionOf('/api/sessions/w1-j9/mjpeg?x=1'), 'w1-j9');
});

test('an errored stream keeps the last good frame behind it and shows only a small badge', async () => {
  const h = harness(); const el = h.img('/api/sessions/w-s/mjpeg?token=x'); h.doc.imgs.push(el);
  h.dog.sweep(); await h.flush();                       // first sight: the poster is the server's newest frame
  assert.match(el.style.backgroundImage, /frame\.jpg\?token=x&t=0/);
  el.naturalWidth = 0;                                  // the response errored: the <img> itself is broken now
  h.dog.onError({ target: el }); await h.flush();
  assert.equal(el.a.alt, '');                           // no alt text painted over the held picture
  assert.match(el.style.backgroundImage, /frame\.jpg/); // never cleared
  assert.equal(h.body.kids.length, 1); assert.equal(h.body.kids[0].textContent, 'reconnecting…');
  h.run(1500);
  assert.equal(el.a.src, '/api/sessions/w-s/mjpeg?token=x&reconnect=1');
  el.naturalWidth = 640;                                // the new response delivers
  h.dog.onLoad({ target: el });
  assert.equal(el.a.alt, 'Live game view'); assert.equal(h.body.kids.length, 0);
});

test('a failed poster refresh never replaces the held picture', async () => {
  const h = harness({ preloadOk: false }); const el = h.img('/api/sessions/w-s/mjpeg?token=x'); h.doc.imgs.push(el);
  el.style.backgroundImage = 'url("held")';
  h.dog.sweep(); await h.flush();
  assert.equal(el.style.backgroundImage, 'url("held")');
});

test('a stale source shows the badge; a short stall clears without reconnecting', async () => {
  const h = harness(); const el = h.img('/api/sessions/w-s/mjpeg?token=x'); h.doc.imgs.push(el);
  h.state.health = async () => ({ state: 'running', age_s: 5 });
  await h.dog.checkHealth(el);
  assert.equal(h.body.kids[0].textContent, 'reconnecting…');
  h.state.health = async () => ({ state: 'running', age_s: 0.2 });
  await h.dog.checkHealth(el);
  assert.equal(h.body.kids.length, 0);
  h.run(20000);
  assert.equal(el.a.src, '/api/sessions/w-s/mjpeg?token=x');   // untouched
});

test('after a long stall the stream is reattached once, transparently', async () => {
  const h = harness(); const el = h.img('/api/sessions/w-s/mjpeg?token=x'); h.doc.imgs.push(el);
  for (const age of [5, 12, 25]) { h.state.health = async () => ({ state: 'running', age_s: age }); await h.dog.checkHealth(el); }
  h.state.health = async () => ({ state: 'running', age_s: 0.1 });
  await h.dog.checkHealth(el);
  h.run(1100);
  assert.equal(el.a.src, '/api/sessions/w-s/mjpeg?token=x&reconnect=1');
  await h.dog.checkHealth(el);                          // fresh frames + a picture: badge gone, no second reattach
  assert.equal(h.body.kids.length, 0);
  h.run(30000);
  assert.equal(el.a.src, '/api/sessions/w-s/mjpeg?token=x&reconnect=1');
});

test('an unreachable server badges the view and reattaches when it is back', async () => {
  const h = harness(); const el = h.img('/api/sessions/w-s/mjpeg?token=x'); h.doc.imgs.push(el);
  h.state.health = async () => { throw new Error('offline'); };
  await h.dog.checkHealth(el);
  assert.equal(h.body.kids[0].textContent, 'reconnecting…');
  assert.equal(el.a.src, '/api/sessions/w-s/mjpeg?token=x');
  h.state.health = async () => ({ state: 'running', age_s: 0.1 });
  await h.dog.checkHealth(el); h.run(1100);
  assert.match(el.a.src, /reconnect=1$/);
});

test('only a session the server reports ended is left alone', async () => {
  const h = harness(); const el = h.img('/api/sessions/w-s/mjpeg?token=x'); h.doc.imgs.push(el);
  h.state.health = async () => ({ state: 'ended', age_s: 50 });
  await h.dog.checkHealth(el);
  el.naturalWidth = 0;
  h.dog.onError({ target: el }); h.run(60000);
  assert.equal(el.a.src, '/api/sessions/w-s/mjpeg?token=x');
  assert.equal(h.body.kids.length, 0);
});

test('mini player loads the watchdog without the cross-origin health poll', () => {
  const html = fs.readFileSync(path.join(__dirname, '../clients/desktop/mini.html'), 'utf8');
  assert.match(html, /window\.GBOX_STREAM_HEALTH = false;[\s\S]*<script src="\.\.\/web\/viz\/stream-watchdog\.js"><\/script>/);
});

test('hard reset needs a second Ctrl+click within 5 s and sends an explicit intent', () => {
  const html = fs.readFileSync(path.join(__dirname, '../clients/web/index.html'), 'utf8');
  const src = html.match(/const HARD_RESET_ARM_MS[\s\S]*?\r?\n}\r?\n/)[0];   // the checkout may be CRLF
  const ctx = { setTimeout: () => 0, Date };
  vm.runInNewContext(src + '; this.arm = hardResetArm;', ctx);
  const btn = { title: 'Reset', style: {} };
  assert.equal(ctx.arm('w-s', btn, 1000), false);       // the stray Ctrl+click only arms it
  assert.match(btn.title, /armed/);
  assert.equal(ctx.arm('w-other', btn, 2000), false);   // another game: re-armed, not fired
  assert.equal(ctx.arm('w-other', btn, 9000), false);   // too late
  assert.equal(ctx.arm('w-other', btn, 10000), true);   // deliberate double Ctrl+click
  // the hard reset goes through POST /api/sessions/{sid}/reset with intent hard_reset (reset-keeps-game); a reset of a
  // hot-swapped model is relaunched server-side; any keep_state=false swap left in the page still names its intent
  assert.match(html, /\/reset`, \{ mode, intent: mode === "hard" \? "hard_reset" : mode \}/);
  assert.match(html, /await resetJob\(sid, "hard", btn\)/);
  for (const m of html.matchAll(/keep_state: false[^}]*\}/g)) assert.match(m[0], /intent: "(hard_reset|reset_model)"/);
});
