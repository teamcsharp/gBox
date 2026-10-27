// The game keys (operator 2026-10-26: "when i press F3, I intend to start the autobot, not save a replay. I dont want that
// saying that when I press F3. I want to save replays with F1. F2 saves state and F4 loads it"): F1 replay, F2 save state,
// F3 autobot on/off for the shown game (any PC), F4 load state, F5 client refresh. The routing in main.js (keys -> actions),
// the desktop shell and the mini window (actions -> handlers), against stubs: no Electron, no server.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const PIP = require('../clients/desktop/pip-media.js');

const DESKTOP = path.join(__dirname, '../clients/desktop');
const html = fs.readFileSync(path.join(DESKTOP, 'index.html'), 'utf8');
const main = fs.readFileSync(path.join(DESKTOP, 'main.js'), 'utf8');
const mini = fs.readFileSync(path.join(DESKTOP, 'mini.html'), 'utf8');
const plain = value => JSON.parse(JSON.stringify(value));

function mainKeys() {
  return plain(vm.runInNewContext(main.slice(main.indexOf('const GAME_KEYS = {'), main.indexOf('ipcMain.handle("win:fullscreen"')) + '\nGAME_KEYS'));
}

test('main.js maps F1 replay, F2 save, F3 autobot, F4 load, F5 client refresh, and nothing else to a game key', () => {
  assert.deepEqual(mainKeys(), { F1: 'replay', F2: 'save', F3: 'autoplay', F4: 'load', F5: 'client-refresh' });
  assert.match(main, /keys: \{ \.\.\.GAME_KEYS, "Shift\+F2": "slot\+", "CommandOrControl\+F2": "slot-"/, 'the same keys while a docked game owns the keyboard');
});

test('keys pressed inside gBox reach the shell as actions; the mini window gets F3 (autobot) and F1 (replay) itself', () => {
  const hook = main.slice(main.indexOf('app.on("web-contents-created", (_e, wc) => wc.on("before-input-event"'), main.indexOf('// Universal game hotkeys'));
  const sent = [], miniSent = [], handlers = {};
  const page = { on(_event, fn) { handlers.page = fn; } };
  const miniWc = { on(_event, fn) { handlers.mini = fn; }, send: (channel, action) => miniSent.push([channel, action]) };
  const ctx = { app: { on(_event, fn) { fn({}, page); fn({}, miniWc); } }, mercsWindows: { owns: () => false }, GAME_KEYS: mainKeys(),
    win: { webContents: { send: (channel, action) => sent.push([channel, action]) }, isFullScreen: () => false },
    mini: { webContents: miniWc }, compactWindow: { state: () => ({ on: false }) } };
  vm.runInNewContext(hook, ctx);
  const press = (wc, key, extra = {}) => handlers[wc]({ preventDefault() {} }, { key, type: 'keyDown', ...extra });
  for (const key of ['F1', 'F2', 'F3', 'F4', 'F5']) press('page', key);
  assert.deepEqual(plain(sent), [['hotkey', 'replay'], ['hotkey', 'save'], ['hotkey', 'autoplay'], ['hotkey', 'load'], ['hotkey', 'client-refresh']]);
  press('page', 'F3', { control: true });
  handlers.page({ preventDefault() {} }, { key: 'F1', type: 'keyUp' });
  assert.equal(sent.length, 5, 'modified keys and key-ups are not game keys');
  // the same keys from the mini window: F3 and F1 act on the game it shows; F2 / F4 still reach the shell
  const before = sent.length;
  for (const key of ['F3', 'F1', 'F2', 'F4']) press('mini', key);
  assert.deepEqual(plain(miniSent), [['hotkey', 'autoplay'], ['hotkey', 'replay']]);
  assert.deepEqual(plain(sent.slice(before)), [['hotkey', 'save'], ['hotkey', 'load']]);
});

test('the desktop shell routes replay to F1\'s handler, autobot to F3\'s, save / load to the game menu; nothing crosses over', () => {
  const start = html.indexOf('gbox.onHotkey?.(k => {');
  const code = html.slice(start, html.indexOf('});', start) + 3);
  const seen = [];
  const ctx = { gbox: { onHotkey: fn => { ctx.handler = fn; } }, f3Autobot: () => seen.push('autobot'), f1Replay: () => seen.push('replay'),
    recoverAndRefresh: () => seen.push('refresh'), gameAction: a => seen.push('game:' + a), eyeStart: () => seen.push('eye'),
    viewAction: () => seen.push('view'), isFull: () => false };
  vm.runInNewContext(code, ctx);
  for (const action of ['replay', 'save', 'autoplay', 'load', 'client-refresh', 'slot+', 'fullscreen']) ctx.handler(action);
  assert.deepEqual(seen, ['replay', 'game:save', 'autobot', 'game:load', 'refresh', 'game:slot+', 'view']);
  assert.doesNotMatch(code, /exportLast|toggleAutobot/, 'the key handler delegates; F3 never touches the replay export');
});

test('the mini window: F3 toggles the autobot of its stream, F1 saves its last 3 minutes, nothing else', () => {
  const line = mini.split('\n').find(l => l.includes('gbox.onHotkey?.('));
  const calls = [];
  vm.runInNewContext(line, { gbox: { onHotkey: fn => { for (const k of ['autoplay', 'replay', 'save', 'load']) fn(k); } },
    media: { toggleAutobot: () => calls.push('autobot'), exportLast: () => calls.push('replay') } });
  assert.deepEqual(calls, ['autobot', 'replay']);
});

function shell(over = {}) {
  const r = { toasts: [], calls: [], ...over };
  const ctx = { console, JSON, Map, Date, Promise, Error, encodeURIComponent, setTimeout: (fn, ms) => 0,
    toast: (text, ms, o) => r.toasts.push(String(text)), GBoxPipMedia: PIP,
    COMPACT: { on: false, sid: null, ...(over.COMPACT || {}) }, EMB: { sid: null, authority: null, ...(over.EMB || {}) },
    S: { apiUrl: 'http://spark:8765' }, GM: { auto: false, slot: 0 }, $: () => ({ getAttribute: () => r.streamSrc || '' }),
    globalThis: { gboxStreamWatchdog: { sessionOf: src => (/sessions\/([^/]+)\//.exec(src) || [])[1] || null } },
    gboxState: async () => r.guest || {}, chatContext: async () => r.chat || {}, compactCurrentSid: () => r.compactSid || null,
    compactMedia: over.compactMedia || null, sessionStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    gbox: { recPreferences: async () => ({ targetMB: 20 }), recSaveClip: async clip => { r.saved = clip; return { file: 'replay.mp4', folderOpened: true }; } },
    compactApi: async (url, body, method) => { r.calls.push({ url, body, method }); return r.api(url, body, method); },
    recoverStreams: async () => {}, reconnectFlow: { state: () => ({ done: true }) }, reconnectRun: async () => {}, clientRefresh: { refresh: async () => {} } };
  vm.createContext(ctx);
  vm.runInContext(html.slice(html.indexOf('async function recoverAndRefresh()'), html.indexOf('// ---- reconnect flow: whatever it takes')), ctx);
  const f1 = html.indexOf('const F1 = { ctl: null');
  vm.runInContext(html.slice(f1, html.indexOf('addEventListener("keydown", e => {', f1)), ctx);
  r.ctx = ctx;
  return r;
}

test('F1 in the PiP saves the last 3 minutes through the PiP media controls', async () => {
  const media = { exports: 0, exportLast: async () => { media.exports++; } };
  const r = shell({ COMPACT: { on: true, sid: 'w1-live' }, compactMedia: media });
  await r.ctx.f1Replay();
  assert.equal(media.exports, 1);
  assert.deepEqual(r.toasts, ['🎬 F1: saving the last 3 minutes…']);
});

test('F1 outside the PiP exports the shown game\'s replay with the recording tool and toasts progress and result', async () => {
  const r = shell({ guest: { tab: 'Sessions', session: 'nuc-re4' },
    api: (url, body) => {
      if (body?.input?.op === 'status') return { state: 'succeeded', output: { result: { status: { av_span_s: 180 } } } };
      return { state: 'succeeded', output: { result: { clip: { audio: true, seconds: 180, bytes: 10, sha256: 'a'.repeat(64), name: 'replay.mp4' } } } };
    } });
  await r.ctx.f1Replay();
  const jobs = r.calls.filter(c => c.url === '/api/jobs').map(c => plain(c.body));
  assert.deepEqual(jobs.map(j => [j.tool, j.require_worker, j.input.session_id, j.input.op]),
    [['recording', 'nuc', 'nuc-re4', 'status'], ['recording', 'nuc', 'nuc-re4', 'export']]);
  assert.equal(r.saved.openFolder, true);
  assert.ok(r.toasts.some(t => /Replay saved/.test(t)), r.toasts.join(' | '));
  assert.ok(!r.toasts.some(t => /autobot/i.test(t)), 'F1 says nothing about the autobot');
  const none = shell({});
  await none.ctx.f1Replay();
  assert.match(none.toasts.at(-1), /^⚠ F1: no game is shown in this window/);
});

test('F3 never shows the replay\'s "Preparing" text and F1 never touches the autobot', async () => {
  let message = '';
  const c = PIP.create({ current: () => 'w1-game', api: async (url, body) => {
    if (url.startsWith('/api/autoplay/')) return { running: false, age_s: 0 };
    if (url.endsWith('/autoplay')) return { id: 't1', state: 'running' };
    if (url === '/api/jobs/t1') return { id: 't1', state: 'succeeded', output: { action: 'started', running: true, message: 'Autobot started on X.' } };
    if (body?.input?.op === 'status') return { state: 'succeeded', output: { result: { status: { av_span_s: 180 } } } };
    return { state: 'succeeded', output: { result: { clip: { audio: true, seconds: 180, bytes: 1, sha256: 'a'.repeat(64), name: 'r.mp4' } } } };
  }, save: async () => ({ file: 'r.mp4' }), render: s => { message += '|' + s.message; }, delay: async () => {}, fade: () => {} });
  await c.toggleAutobot();
  assert.doesNotMatch(message, /[Rr]eplay|Preparing/);
  const requests = [];
  const d = PIP.create({ current: () => 'w1-game', api: async (url, body) => { requests.push(url + ' ' + (body?.tool || body?.input?.op || ''));
    if (body?.input?.op === 'status') return { state: 'succeeded', output: { result: { status: { av_span_s: 180 } } } };
    return { state: 'succeeded', output: { result: { clip: { audio: true, seconds: 180, bytes: 1, sha256: 'a'.repeat(64), name: 'r.mp4' } } } }; },
    save: async () => ({ file: 'r.mp4' }), delay: async () => {}, fade: () => {} });
  await d.exportLast();
  assert.ok(requests.every(r => !/autoplay/.test(r)), requests.join(', '));
});

test('the on-screen hints name the keys the operator asked for', () => {
  assert.match(html, /F1 save the last 3 minutes \(replay\) · F2 save state · F3 autobot on\/off for the game shown \(whichever PC runs it\) · F4 load state · F5 recover \(update gBox, reconnect, MercMode back in the PiP with its autobot\)/);
  assert.match(html, /\["replay", "🎬 Save the last 3 minutes \(replay\)  F1"\]/);
  assert.match(html, /\["save", "💾 Save state  F2", noStates\], \["load", "📂 Load state  F4", noStates\]/);
  assert.match(html, /"🤖 Take control \(autoplay\)  F3/);
  assert.match(PIP.CSS.length ? fs.readFileSync(path.join(DESKTOP, 'pip-media.js'), 'utf8') : '', /open the export folder \(F1\)/);
  assert.match(fs.readFileSync(path.join(DESKTOP, 'hotkey-scope.js'), 'utf8'), /F1 save replay, F2 save state, F3 autobot on\/off,\s*\/\/ F4 load state, F5 client refresh/);
});
