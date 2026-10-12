const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// #1118: during an OoT session the desktop logged "One-time callback was called more than once" at the
// display-media handler and the recording aborted twice. Electron's callback is one-time: the handler must answer
// exactly once, even when that first answer throws, and must keep the first refusal visible.
const main = fs.readFileSync(path.join(__dirname, '../clients/desktop/main.js'), 'utf8');
const start = main.indexOf('// <display-media-handler>');
const end = main.indexOf('// </display-media-handler>', start);
assert.ok(start >= 0 && end > start, 'display-media handler markers must be present');
const source = main.slice(start, end);

function handlerFactory() {
  const ctx = vm.createContext({ console, String });
  vm.runInContext(source + '\nthis.displayMediaHandler = displayMediaHandler;', ctx);
  return ctx.displayMediaHandler;
}

// Electron's one-time callback: the first call consumes it, even when it then throws for a refused answer.
function oneTime(refuse) {
  const calls = [];
  const cb = streams => {
    calls.push(streams);
    if (calls.length > 1) throw new TypeError('One-time callback was called more than once');
    if (refuse) throw new TypeError(refuse);
  };
  return { cb, calls };
}

const frame = { id: 'main-frame' };
const win = { webContents: { mainFrame: frame } };
const rec = { display: { id: 7 } };
const screen = { id: 'screen:7:0', display_id: '7' };
const capturer = (sources, fail) => ({ getSources: async () => { if (fail) throw new Error(fail); return sources; } });

test('a refused first answer is logged once and never answered twice', async () => {
  const logs = [];
  const handler = handlerFactory()(() => rec, () => win, capturer([screen]), (...a) => logs.push(a.join(' ')));
  const { cb, calls } = oneTime('Video was requested, but no video stream was provided');
  await assert.doesNotReject(handler({ frame, audioRequested: true, videoRequested: true }, cb));
  assert.equal(calls.length, 1);
  assert.equal(calls[0].video, screen);
  assert.equal(calls[0].audio, 'loopback');
  assert.equal(logs.length, 1);
  assert.match(logs[0], /answer refused: Video was requested, but no video stream was provided/);
  assert.doesNotMatch(logs.join('\n'), /more than once/);
});

test('a failed source lookup answers with no streams exactly once', async () => {
  const logs = [];
  const handler = handlerFactory()(() => rec, () => win, capturer(null, 'capturer gone'), (...a) => logs.push(a.join(' ')));
  const { cb, calls } = oneTime();
  await assert.doesNotReject(handler({ frame, audioRequested: true }, cb));
  assert.equal(calls.length, 1);
  assert.equal(Object.keys(calls[0]).length, 0);
  assert.match(logs.join('\n'), /screen sources unavailable: capturer gone/);
});

test('no recording, another frame, or a missing display answers empty once', async () => {
  const make = handlerFactory();
  for (const [getRec, req, sources] of [[() => null, { frame }, [screen]],
                                         [() => rec, { frame: { id: 'webview' } }, [screen]],
                                         [() => rec, { frame }, [{ id: 'screen:2:0', display_id: '2' }]]]) {
    const { cb, calls } = oneTime();
    await make(getRec, () => win, capturer(sources), () => {})(req, cb);
    assert.equal(calls.length, 1);
    assert.equal(Object.keys(calls[0]).length, 0);
  }
});

test('a recording stopped during the source lookup answers empty', async () => {
  let current = rec;
  const slow = { getSources: async () => { current = null; return [screen]; } };
  const { cb, calls } = oneTime();
  await handlerFactory()(() => current, () => win, slow, () => {})({ frame, audioRequested: true }, cb);
  assert.equal(calls.length, 1);
  assert.equal(Object.keys(calls[0]).length, 0);
});

test('loopback audio is offered only when the request asked for audio', async () => {
  const make = handlerFactory();
  const video = oneTime();
  await make(() => rec, () => win, capturer([screen]), () => {})({ frame, audioRequested: false, videoRequested: true }, video.cb);
  assert.deepEqual(Object.keys(video.calls[0]), ['video']);
  const both = oneTime();
  await make(() => rec, () => win, capturer([screen]), () => {})({ frame, audioRequested: true, videoRequested: true }, both.cb);
  assert.equal(both.calls[0].audio, 'loopback');
});

test('main.js registers the guarded handler and no longer re-answers from a catch', () => {
  assert.match(main, /setDisplayMediaRequestHandler\(displayMediaHandler\(\(\) => rec, \(\) => win, desktopCapturer\)\)/);
  assert.doesNotMatch(main, /catch \{ callback\(\{\}\); \}/);
});
