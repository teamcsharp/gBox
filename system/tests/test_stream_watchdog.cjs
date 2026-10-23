const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');
const w = require('../clients/web/viz/stream-watchdog.js');

function harness({ health = async () => ({ state: 'running', age_s: 0.1 }), preloadOk = true, pixels = true, mini = false } = {}) {
  let t = 0, nextTimer = 0; const timers = new Map(); const logs = [], preloaded = [], changes = [];
  const setTimer = (fn, ms) => { const id = ++nextTimer; timers.set(id, [t + ms, fn]); return id; };
  const clearTimer = id => timers.delete(id);
  const run = until => { for (;;) { const entry = [...timers].sort((a, b) => a[1][0] - b[1][0])[0];
    if (!entry || entry[1][0] > until) break;
    const [id, [at, fn]] = entry; timers.delete(id); t = at; fn(); } t = until; };
  const body = { kids: [], append(el) { this.kids.push(el); el.parent = this; } };
  const doc = { body, imgs: [], addEventListener() {}, removeEventListener() {}, querySelectorAll() { return this.imgs; },
    createElement: () => ({ style: {}, attrs: {}, setAttribute(k, v) { this.attrs[k] = v; },
      remove() { const i = body.kids.indexOf(this); if (i >= 0) body.kids.splice(i, 1); } }) };
  const img = src => ({ tagName: 'IMG', isConnected: true, naturalWidth: 640, picture: 'first', style: {}, a: { src, alt: 'Live game view' },
    getAttribute(k) { return this.a[k]; }, setAttribute(k, v) { this.a[k] = v; },
    dispatchEvent(event) { changes.push(event.detail); },
    getBoundingClientRect: () => ({ left: 10, top: 20, width: 640, height: 480 }) });
  const state = { health, picture: 'first', preload: null };
  const dog = w.createStreamWatchdog({ doc, setTimer, clearTimer, now: () => t, log: m => logs.push(m),
    env: { CustomEvent: class { constructor(type, data) { this.type = type; this.detail = data.detail; } } },
    readPicture: im => pixels && im?.naturalWidth ? im.picture : null,
    preload: (url, opts) => { preloaded.push(url); return state.preload ? state.preload(url, opts) : preloadOk
      ? Promise.resolve({ url, image: { naturalWidth: 640, picture: state.picture } }) : Promise.reject(new Error('x')); },
    fetchHealth: mini ? null : (src, opts) => state.health(src, opts) });
  const flush = () => new Promise(r => setImmediate(r));
  return { dog, doc, img, run, logs, preloaded, body, state, flush, changes, timers, now: () => t };
}

test('side URLs keep the session and auth query', () => {
  assert.equal(w.frameUrl('/api/sessions/a-b/mjpeg?token=t&reconnect=3', 5), '/api/sessions/a-b/frame.jpg?token=t&t=5');
  assert.equal(w.healthUrl('http://spark:8765/api/sessions/a-b/mjpeg?token=t'), 'http://spark:8765/api/sessions/a-b/stream/health?token=t');
  assert.equal(w.sessionOf('/api/sessions/w1-j9/mjpeg?x=1'), 'w1-j9');
});

test('an errored stream retains the last good frame and shows recovery then connected status', async () => {
  const h = harness(), el = h.img('/api/sessions/w-s/mjpeg?token=x'); h.doc.imgs.push(el);
  h.dog.sweep(); await h.flush(); assert.match(el.style.backgroundImage, /frame\.jpg\?token=x&t=0/);
  el.naturalWidth = 0; h.dog.onError({ target: el }); await h.flush();
  assert.equal(el.a.alt, ''); assert.match(el.style.backgroundImage, /frame\.jpg/);
  assert.equal(h.body.kids.length, 1); assert.equal(h.body.kids[0].textContent, 'Reconnecting...');
  h.run(1500); assert.equal(el.a.src, '/api/sessions/w-s/mjpeg?token=x&reconnect=1');
  el.naturalWidth = 640; el.picture = 'second'; h.dog.onLoad({ target: el }); await h.dog.checkHealth(el);
  assert.equal(el.a.alt, 'Live game view'); assert.equal(h.body.kids[0].textContent, 'Connected');
  assert.deepEqual(h.changes.map(x => x.state), ['connecting', 'connected', 'reconnecting', 'connected']);
});

test('a failed poster refresh never replaces the held picture', async () => {
  const h = harness({ preloadOk: false }), el = h.img('/api/sessions/w-s/mjpeg?token=x'); h.doc.imgs.push(el);
  el.style.backgroundImage = 'url("held")'; h.dog.sweep(); await h.flush(); assert.equal(el.style.backgroundImage, 'url("held")');
});

test('a followed game keeps its poster during replacement and connects the new stream',async()=>{
  const h=harness({health:async()=>({state:'ended'})}),el=h.img('/api/sessions/old/mjpeg');
  el.setAttribute('data-stream-follow','game');el.style.backgroundImage='url("last-game-frame")';
  await h.dog.checkHealth(el);
  assert.equal(el.a['data-stream-state'],'reconnecting');
  assert.equal(el.style.backgroundImage,'url("last-game-frame")');
  el.setAttribute('src','/api/sessions/new/mjpeg');h.state.health=async()=>({state:'running',age_s:.1});
  await h.dog.checkHealth(el);assert.equal(el.a['data-stream-state'],'connected');
});

test('a short source stall shows status and recovers without reconnecting a working view', async () => {
  const h = harness(), el = h.img('/api/sessions/w-s/mjpeg');
  await h.dog.checkHealth(el); h.state.health = async () => ({ state: 'running', age_s: 5 });
  await h.dog.checkHealth(el); assert.equal(el.a['data-stream-state'], 'reconnecting');
  h.state.health = async () => ({ state: 'running', age_s: .2 }); await h.dog.checkHealth(el);
  assert.equal(el.a['data-stream-state'], 'connected'); h.run(20000); assert.equal(el.a.src, '/api/sessions/w-s/mjpeg');
});

test('a long source stall reattaches and verifies fresh rendered pictures', async () => {
  const h = harness(), el = h.img('/api/sessions/w-s/mjpeg'); await h.dog.checkHealth(el);
  for (const age of [5, 12, 25]) { h.state.health = async () => ({ state: 'running', age_s: age }); await h.dog.checkHealth(el); }
  h.run(1100); assert.equal(el.a.src, '/api/sessions/w-s/mjpeg?reconnect=1');
  h.state.health = async () => ({ state: 'running', age_s: .1 }); el.picture = 'resumed'; await h.dog.checkHealth(el);
  assert.equal(el.a['data-stream-state'], 'connected'); h.run(30000); assert.equal(el.a.src, '/api/sessions/w-s/mjpeg?reconnect=1');
});

test('unreachable server retries without waiting for a successful health response', async () => {
  const h = harness({ health: async () => { throw new Error('offline'); } }), el = h.img('/api/sessions/w-s/mjpeg');
  await h.dog.checkHealth(el); assert.equal(el.a['data-stream-state'], 'reconnecting');
  h.run(1100); assert.match(el.a.src, /reconnect=1$/);
});

test('fresh server frames reconnect a frozen image, but identical quiet pictures stay connected', async () => {
  const h = harness(), el = h.img('/api/sessions/w-s/mjpeg'); h.doc.imgs.push(el); await h.dog.checkHealth(el);
  h.run(8000); await h.dog.checkHealth(el);
  assert.equal(h.dog.state(el).pending, false); assert.equal(el.a['data-stream-state'], 'connected');
  h.state.picture = 'server moved'; h.run(16000); await h.dog.checkHealth(el);
  assert.equal(el.a['data-stream-state'], 'reconnecting'); h.run(17000); assert.match(el.a.src, /reconnect=1/);
  el.picture = 'server moved'; await h.dog.checkHealth(el); assert.equal(el.a['data-stream-state'], 'connected');
});

test('hanging health times out and aborts, permits another poll, and ignores late results', async () => {
  const h = harness(), el = h.img('/api/sessions/w-s/mjpeg'); let resolve, signal, calls = 0;
  h.state.health = (src, opts) => { calls++; signal = opts.signal; return new Promise(r => { resolve = r; }); };
  const checking = h.dog.checkHealth(el); await h.flush(); await h.dog.checkHealth(el); assert.equal(calls, 1);
  h.run(5000); await checking;
  assert.equal(signal.aborted, true); assert.equal(h.dog.state(el).checking, false); assert.equal(el.a['data-stream-state'], 'reconnecting');
  h.state.health = async () => ({ state: 'running', age_s: .1 }); await h.dog.checkHealth(el);
  resolve({ state: 'ended' }); await h.flush();
  assert.equal(h.dog.state(el).ended, false); assert.equal(el.a['data-stream-state'], 'connected');
});

test('old session health, poster and retry cannot affect an image reused for another session', async () => {
  const h = harness(), el = h.img('/api/sessions/w-old/mjpeg?token=a'); h.doc.imgs.push(el); let oldHealth, oldPoster;
  h.state.health = () => new Promise(r => { oldHealth = r; }); h.state.preload = () => new Promise(r => { oldPoster = r; });
  h.dog.sweep(); await h.flush(); h.dog.onError({ target: el });
  el.a.src = '/api/sessions/w-new/mjpeg?token=b'; h.state.health = async () => ({ state: 'running', age_s: .1 }); h.state.preload = null;
  h.dog.sweep(); await h.flush(); oldHealth({ state: 'ended' }); oldPoster('old URL'); await h.flush(); h.run(3000);
  assert.equal(el.a.src, '/api/sessions/w-new/mjpeg?token=b'); assert.equal(h.dog.state(el).ended, false);
  assert.match(el.style.backgroundImage, /w-new/); assert.equal(h.body.kids.length, 1);
});

test('auth changes invalidate old requests even for the same session', async () => {
  const h = harness(), el = h.img('/api/sessions/w-s/mjpeg?token=old'); let resolve;
  h.state.health = () => new Promise(r => { resolve = r; }); const checking = h.dog.checkHealth(el); await h.flush();
  el.a.src = '/api/sessions/w-s/mjpeg?token=new'; resolve({ state: 'ended' }); await checking;
  assert.equal(h.dog.state(el).ended, false); assert.equal(el.a['data-stream-state'], 'connecting');
});

test('a retained decoded image does not reset retry backoff', async () => {
  const h = harness({ health: async () => { throw new Error('offline'); } }), el = h.img('/api/sessions/w-s/mjpeg'); h.doc.imgs.push(el);
  await h.dog.checkHealth(el); h.run(1000); h.dog.sweep(); await h.dog.checkHealth(el); await h.flush();
  h.run(2999); assert.match(el.a.src, /reconnect=1$/); h.run(3000); assert.match(el.a.src, /reconnect=2$/);
  h.dog.sweep(); await h.dog.checkHealth(el); await h.flush(); h.run(6999); assert.match(el.a.src, /reconnect=2$/); h.run(7000); assert.match(el.a.src, /reconnect=3$/);
});

test('no first frame or offline worker retries with visible status', async () => {
  for (const health of [{ state: 'running', age_s: null }, { state: 'running', age_s: 0, worker_online: false }]) {
    const h = harness({ health: async () => health }), el = h.img('/api/sessions/w-s/mjpeg'); el.naturalWidth = 0;
    await h.dog.checkHealth(el); assert.equal(el.a['data-stream-state'], 'reconnecting'); h.run(1000); assert.match(el.a.src, /reconnect=1$/);
  }
});

test('ended sessions cancel pending retries; stop aborts pending work and all timers', async () => {
  const h = harness(), el = h.img('/api/sessions/w-s/mjpeg'); h.dog.onError({ target: el });
  h.state.health = async () => ({ state: 'ended' }); await h.dog.checkHealth(el); h.run(10000);
  assert.equal(el.a.src, '/api/sessions/w-s/mjpeg'); assert.equal(el.a['data-stream-state'], 'ended');
  const h2 = harness(), el2 = h2.img('/api/sessions/w-s/mjpeg'); h2.doc.imgs.push(el2); let signal, resolve;
  h2.state.health = (src, opts) => { signal = opts.signal; return new Promise(r => { resolve = r; }); };
  h2.dog.start(); await h2.flush(); h2.dog.onError({ target: el2 }); h2.dog.stop(); await h2.flush();
  assert.equal(signal.aborted, true); assert.equal(h2.timers.size, 0); assert.equal(h2.body.kids.length, 0);
  resolve({ state: 'ended' }); await h2.flush(); h2.run(60000); assert.equal(el2.a.src, '/api/sessions/w-s/mjpeg'); assert.equal(h2.body.kids.length, 0);
});

test('a hanging poster cannot suppress future frame probes', async () => {
  const h = harness(), el = h.img('/api/sessions/w-s/mjpeg'); let signal;
  h.state.preload = (url, opts) => { signal = opts.signal; return new Promise(() => {}); };
  h.dog.seed(el); await h.flush(); h.run(5000); await h.flush(); assert.equal(signal.aborted, true); assert.equal(h.dog.state(el).probing, false);
  h.state.preload = null; h.dog.seed(el); await h.flush(); assert.match(el.style.backgroundImage, /frame.jpg/);
});

test('cross-origin mini renews after 60 seconds and recovers on load', async () => {
  const h = harness({ mini: true, pixels: false }), el = h.img('http://spark/api/sessions/w-s/mjpeg'); h.doc.imgs.push(el);
  h.dog.sweep(); await h.flush(); assert.equal(el.a['data-stream-state'], 'connected');
  h.run(59999); h.dog.sweep(); assert.equal(h.dog.state(el).pending, false);
  h.run(60000); h.dog.sweep(); assert.equal(el.a['data-stream-state'], 'reconnecting'); h.run(61000); assert.match(el.a.src, /reconnect=1/);
  h.dog.onLoad({ target: el }); assert.equal(el.a['data-stream-state'], 'connected');
});

test('stream input gate blocks new presses only for the viewed session until connected', () => {
  const h = harness(), el = h.img('/api/sessions/w-s/mjpeg?token=x'); assert.equal(w.inputAllowed(el, 'w-s'), false);
  for (const state of ['connecting', 'reconnecting', 'ended']) { el.a['data-stream-state'] = state; assert.equal(w.inputAllowed(el, 'w-s'), false); }
  el.a['data-stream-state'] = 'connected'; assert.equal(w.inputAllowed(el, 'w-s'), true);
  el.a['data-stream-state'] = 'reconnecting'; assert.equal(w.inputAllowed(el, 'w-other'), true); assert.equal(w.inputAllowed(null, 'w-s'), true);
});

test('mini player reads authenticated health through IPC and rejects a different server', async () => {
  const html = fs.readFileSync(path.join(__dirname, '../clients/desktop/mini.html'), 'utf8');
  const script = html.match(/window\.GBOX_STREAM_FETCH_HEALTH = async src => \{[\s\S]*?\n  \};/)[0];
  const calls = [], context = { window: {}, URL, gbox: {
    settings: async () => ({apiUrl: 'http://spark:8765'}),
    api: async path => { calls.push(path); return {ok: true, data: {state:'running',age_s:.01,seq:10}}; }
  }};
  vm.runInNewContext(script, context);
  const health = await context.window.GBOX_STREAM_FETCH_HEALTH('http://spark:8765/api/sessions/worker-new/mjpeg?token=x');
  assert.equal(health.seq, 10); assert.deepEqual(calls, ['/api/sessions/worker-new/stream/health']);
  await assert.rejects(context.window.GBOX_STREAM_FETCH_HEALTH('http://other:8765/api/sessions/x/mjpeg'), /Different server/);
  assert.equal(calls.length, 1);
  context.gbox.api = async () => ({ok:false,error:'offline'});
  await assert.rejects(context.window.GBOX_STREAM_FETCH_HEALTH('http://spark:8765/api/sessions/x/mjpeg'), /offline/);
});

test('DOM churn does not accelerate health polls and healthy opaque desktop pictures keep their connection', async () => {
  let calls = 0; const h = harness({ pixels: false, health: async () => { calls++; return { state: 'running', age_s: .1 }; } });
  const el = h.img('/api/sessions/w-s/mjpeg'); h.doc.imgs.push(el);
  h.dog.sweep(); await h.flush();
  for (let n = 0; n < 30; n++) { h.dog.sweep(); await h.flush(); }
  assert.equal(calls, 1);
  for (const time of [60000, 120000, 180000]) { h.run(time); h.dog.sweep(); await h.flush(); }
  assert.equal(el.a['data-stream-state'], 'connected'); assert.equal(el.a.src, '/api/sessions/w-s/mjpeg');
  assert.equal(h.dog.state(el).pending, false);
  h.state.health = async () => ({state:'running',age_s:25}); await h.dog.checkHealth(el); h.run(181000);
  assert.match(el.a.src, /reconnect=1$/);
});

test('actual keyboard and glyph handlers release held input to its original session when video disconnects', () => {
  const html = fs.readFileSync(path.join(__dirname, '../clients/web/index.html'), 'utf8');
  const start = html.indexOf('  const send = (key, down) => api(`/api/sessions/');
  const end = html.indexOf('  scr.focus();', start) + '  scr.focus();'.length;
  const sent = [], events = {}, winEvents = {}; let connected = true;
  const scr = { addEventListener: (name, fn) => { events[name] = fn; }, focus() {} }, pg = {};
  const ctx = vm.createContext({ sid: 'original-session', api: (url, body) => sent.push({ url, ...body.events[0] }),
    $: () => scr, pg, keysym: e => e.key, streamInputAllowed: () => connected, sop() {},
    addEventListener: (name, fn) => { winEvents[name] = fn; }, removeEventListener() {} });
  vm.runInContext(html.slice(start, end), ctx);
  const key = { key: 'a', preventDefault() {} }; scr.onkeydown(key); assert.equal(sent.at(-1).down, true);
  connected = false; events['gbox-stream-state']({ detail: { connected: false } });
  assert.deepEqual(sent.at(-1), { url: '/api/sessions/original-session/input', key: 'a', down: false });
  const count = sent.length; scr.onkeydown(key); assert.equal(sent.length, count);
  connected = true; pg.onpointerdown({ button: 0, target: { closest: () => ({ dataset: { k: 'b' } }) }, preventDefault() {} });
  events['gbox-stream-state']({ detail: { connected: false } }); assert.equal(sent.at(-1).key, 'b'); assert.equal(sent.at(-1).down, false);
});

test('hard reset needs a second Ctrl+click within 5 s and sends an explicit intent', () => {
  const html = fs.readFileSync(path.join(__dirname, '../clients/web/index.html'), 'utf8');
  const src = html.match(/const HARD_RESET_ARM_MS[\s\S]*?\r?\n}\r?\n/)[0];
  const ctx = { setTimeout: () => 0, Date }; vm.runInNewContext(src + '; this.arm = hardResetArm;', ctx);
  const btn = { title: 'Reset', style: {} };
  assert.equal(ctx.arm('w-s', btn, 1000), false); assert.match(btn.title, /armed/);
  assert.equal(ctx.arm('w-other', btn, 2000), false); assert.equal(ctx.arm('w-other', btn, 9000), false);
  assert.equal(ctx.arm('w-other', btn, 10000), true);
  assert.match(html, /\/reset`, \{ mode, intent: mode === "hard" \? "hard_reset" : mode \}/);
  assert.match(html, /await resetJob\(sid, "hard", btn\)/);
  for (const m of html.matchAll(/keep_state: false[^}]*\}/g)) assert.match(m[0], /intent: "(hard_reset|reset_model)"/);
});
