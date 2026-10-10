const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const createVideo = require('../clients/web/viz/gpu-game-surface');
const createMain = require('../clients/desktop/game-surface-main');

function setup(open) {
  const videos = [], frames = [], streams = [], sent = [], timers = new Map(); let id = 0, calls = 0;
  function makeStream() {
    const track = { readyState: 'live', events: {}, stop() { this.readyState = 'ended'; }, addEventListener(n, f) { this.events[n] = f; } };
    const s = { getTracks: () => [track], getVideoTracks: () => [track] }; streams.push(s); return s;
  }
  const body = { append(v) { v.parentElement = this; } }, slot = { dataset: { sid: 's1' }, style: {}, append: body.append };
  const env = { document: { body, getElementById: () => slot, createElement: tag => {
    if (tag === 'iframe') {
      const frame = { style: {}, events: {}, messages: [], setAttribute() {}, addEventListener(n, f) { this.events[n] = f; },
        remove() { this.parentElement = null; } };
      frame.contentWindow = { postMessage: (message, origin) => frame.messages.push({ message, origin }) };
      frames.push(frame); return frame;
    }
    const v = { style: {}, events: {}, videoWidth: 640, videoHeight: 480, clientWidth: 640, clientHeight: 480, currentTime: 1,
      setAttribute() {}, addEventListener(n, f) { this.events[n] = f; },
      paused: false, play: async function () { this.paused = false; }, remove() { this.parentElement = null; this.paused = true; }, focus() {},
      getVideoPlaybackQuality: () => ({ totalVideoFrames: 30 }) }; videos.push(v); return v;
  } }, navigator: { mediaDevices: { getUserMedia: () => { calls++; return open ? open(makeStream) : Promise.resolve(makeStream()); } } },
    addEventListener() {}, setTimeout(fn) { timers.set(++id, fn); return id; }, clearTimeout(n) { timers.delete(n); },
    api: async (url, body) => { sent.push({ url, events: body.events }); } };
  return { api: createVideo(env), env, videos, frames, streams, sent, timers, calls: () => calls };
}
const st = { pid: 123, sid: 's1', sourceId: 'window:456:0', visible: true };

test('re-rendering and resizing keep one live capture and mount in the latest slot', async () => {
  const x = setup(); await x.api.sync(st); await x.api.sync(st);
  assert.equal(x.calls(), 1); assert.equal(x.streams[0].getTracks()[0].readyState, 'live');
  assert.equal(x.videos[0].parentElement, x.env.document.getElementById());
  assert.equal(x.env.document.getElementById().dataset.surface, 'gpu'); assert.equal(x.timers.size, 0);
});
test('concurrent mounts share the pending source and wait for its first frame', async () => {
  let finish; const x = setup(make => new Promise(r => { finish = () => r(make()); }));
  const a = x.api.sync(st), b = x.api.sync(st); assert.equal(x.calls(), 1);
  finish(); assert.equal((await a).ready, true); assert.equal((await b).ready, true);
});
test('a remounted video resumes the existing stream after Chromium pauses it', async () => {
  const x = setup(); await x.api.sync(st); x.videos[0].remove();
  assert.equal(x.videos[0].paused, true); await x.api.sync(st);
  assert.equal(x.videos[0].paused, false); assert.equal(x.calls(), 1);
  assert.equal(x.streams[0].getVideoTracks()[0].readyState, 'live');
});
test('disposing an opening capture stops its late stream and never resurrects the view', async () => {
  let finish; const x = setup(make => new Promise(r => { finish = () => r(make()); }));
  const opening = x.api.sync(st); x.api.dispose(); finish();
  await assert.rejects(opening, /view changed/);
  assert.equal(x.streams[0].getTracks()[0].readyState, 'ended'); assert.equal(x.api.stats().ready, false);
});
test('capture timeout does not hang integration and releases a late stream', async () => {
  let finish; const x = setup(make => new Promise(r => { finish = () => r(make()); }));
  const opening = x.api.sync(st); [...x.timers.values()][0]();
  await assert.rejects(opening, /timed out/); finish(); await Promise.resolve();
  assert.equal(x.streams[0].getTracks()[0].readyState, 'ended');
});
test('source changes release held buttons to the original session before stopping its tracks', async () => {
  const x = setup(); await x.api.sync(st);
  x.videos[0].events.keydown({ code: 'KeyX', preventDefault() {}, stopPropagation() {} });
  await x.api.sync({ ...st, pid: 124, sid: 's2', sourceId: 'window:789:0' });
  await new Promise(r => setImmediate(r));
  assert.equal(x.streams[0].getTracks()[0].readyState, 'ended');
  assert.deepEqual(x.sent.map(s => s.events), [[{ key: 'a', down: true }], [{ key: 'a', down: false }]]);
  assert.ok(x.sent.every(s => s.url.includes('/s1/')));
});
test('an ended source is reported and is replaced on the next mount', async () => {
  const x = setup(); await x.api.sync(st); const t = x.streams[0].getTracks()[0];
  t.readyState = 'ended'; t.events.ended(); assert.equal(x.api.stats().ready, false);
  assert.equal((await x.api.sync(st)).ready, true); assert.equal(x.calls(), 2);
});
test('host video uses DOM stacking and never creates native cut-outs', async () => {
  const x = setup(); await x.api.sync({ ...st, host: 'root', rect: { x: 40, y: 60, w: 480, h: 360 } });
  assert.equal(x.videos[0].style.position, 'fixed'); assert.equal(x.videos[0].style.left, '40px');
  assert.equal(x.videos[0].style.zIndex, '35'); assert.equal(x.videos[0].style.clipPath, undefined);
});

test('model picking and overlays align with the game picture inside letterboxing', async () => {
  const x = setup(), picks = []; x.env.gbox = { overlay: (op, args) => picks.push({ op, args }) };
  await x.api.sync({ ...st, host: 'root', rect: { x: 40, y: 60, w: 600, h: 600 } });
  x.videos[0].getBoundingClientRect = () => ({ left: 40, top: 60, width: 600, height: 600 });
  const click = (clientX, clientY) => x.videos[0].events.click({ altKey: true, clientX, clientY, preventDefault() {} });
  click(340, 70); assert.equal(picks.length, 0);
  click(340, 360); assert.deepEqual(picks, [{ op: 'pick', args: { sid: 's1', point: [.5, .5] } }]);
  x.api.overlay({ type: 'banner', text: 'pick' }, 'https://gbox.test/viz/swap-overlay.html');
  assert.equal(x.frames[0].style.top, '135px'); assert.equal(x.frames[0].style.height, '450px');
});

test('voice overlay waits for navigation and replays the latest level once loaded', async () => {
  const x = setup(); await x.api.sync(st);
  x.api.voice({ on: true, level: .2, beat: false }, 'https://gbox.test/viz/overlay.html');
  x.api.voice({ on: true, level: .8, beat: true }, 'https://gbox.test/viz/overlay.html');
  assert.equal(x.frames[0].messages.length, 0); x.frames[0].events.load();
  assert.deepEqual(x.frames[0].messages, [{ message: { gboxVoice: { level: .8, beat: true } }, origin: 'https://gbox.test' }]);
  x.api.voice({ on: false }); x.frames[0].events.load();
  assert.equal(x.frames[0].messages.length, 1);
});
test('main process serializes window transitions and rejects stale/invalid cached frames', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'gbox-surface-')), commands = [], native = [];
  const sync = createMain({ getWin: () => ({ isDestroyed: () => false, getNativeWindowHandle: () => Buffer.from([1,0,0,0,0,0,0,0]) }),
    f3() {}, frameDir: dir, embedCmd: async m => { commands.push(m); return { ok: true, sourceId: 'window:456:0' }; },
    nativeSync: async st => { native.push(st); return { ok: true }; } });
  try {
    await sync({ ...st, surface: 'gpu' }); assert.equal(commands[0].op, 'capture');
    assert.equal((await sync({ ...st, pid: 999, surface: 'gpu-frame', frame: 'invalid' })).ok, false);
    assert.equal((await sync({ ...st, surface: 'gpu-frame', frame: 'invalid' })).ok, false);
    const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=', 'base64');
    const frame = 'data:image/png;base64,' + png.toString('base64');
    assert.equal((await sync({ ...st, surface: 'gpu-frame', frame })).ok, true);
    assert.deepEqual(fs.readFileSync(path.join(dir, '123.png')), png);
    assert.equal((await sync({ ...st, surface: 'gpu-ready' })).ok, true);
    assert.equal(commands.at(-1).op, 'captured');
    await sync(null); assert.equal(native.length, 1);
    assert.equal((await sync({ ...st, surface: 'gpu-frame', frame })).ok, false);
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
});

test('slow monitoring cannot block display changes and retains only the latest pending frame', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'gbox-publish-')), sent = []; let release;
  const sync = createMain({ getWin: () => ({ isDestroyed: () => false, getNativeWindowHandle: () => Buffer.alloc(8) }),
    f3() {}, frameDir: dir, embedCmd: async () => ({ ok: true, sourceId: st.sourceId }), nativeSync: async () => ({ ok: true }),
    publishFrame: async sid => { sent.push(sid); if (sent.length === 1) await new Promise(r => { release = r; }); } });
  try {
    await sync({ ...st, surface: 'gpu', warm: true });
    const frame = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=';
    await sync({ ...st, surface: 'gpu-frame', frame });
    await sync({ ...st, sid: 'older', surface: 'gpu-frame', frame });
    await sync({ ...st, sid: 'latest', surface: 'gpu-frame', frame });
    assert.equal((await sync({ ...st, surface: 'gpu-ready' })).ok, true);
    assert.deepEqual(sent, ['s1']); release(); await new Promise(r => setImmediate(r));
    assert.deepEqual(sent, ['s1', 'latest']);
  } finally { release?.(); fs.rmSync(dir, { recursive: true, force: true }); }
});
