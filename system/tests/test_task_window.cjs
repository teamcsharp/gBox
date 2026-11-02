'use strict';
// Unit tests for the Spark2 task dashboard popup (clients/desktop/task-window.cjs): the read-only
// whitelist, the main-process token injection (no credential ever reaches the renderer), the bounded
// correspondence-image fetch, and the wiring that puts "Spark2 tasks" on the PiP right-click menu.
const { test } = require('node:test'), assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), os = require('node:os');
const { EventEmitter } = require('node:events'), { pathToFileURL } = require('node:url');
const create = require('../clients/desktop/task-window.cjs');
const FOLDER = path.resolve(__dirname, '../clients/desktop');
const RUN = 'a'.repeat(32), REQ = 'b'.repeat(16), SHA = 'c'.repeat(64);

function fixture(t) {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'gbox-task-window-'));
  t.after(() => fs.rmSync(temp, { recursive: true, force: true }));
  const handlers = {}, windows = [], calls = [], tokens = [], shell = {};
  let data = { runs: [] }, imageBytes = Buffer.from('PNGDATA'), imageType = 'image/png';
  class Window extends EventEmitter {
    constructor(opts) {
      super(); this.opts = opts; this.bounds = { x: opts.x, y: opts.y, width: opts.width, height: opts.height }; this.top = opts.alwaysOnTop;
      const wc = this.webContents = new EventEmitter(); wc.mainFrame = {}; wc.getURL = () => this.url; wc.send = (...v) => { this.last = v; };
      wc.setWindowOpenHandler = f => this.popups = f; wc.session = { setPermissionRequestHandler: f => this.permissions = f }; windows.push(this);
    }
    isDestroyed() { return !!this.dead; }
    async loadFile(file) { this.file = file; this.url = pathToFileURL(file).href; }
    getBounds() { return this.bounds; } getNormalBounds() { return this.bounds; }
    isAlwaysOnTop() { return this.top; } setAlwaysOnTop(v) { this.top = v; }
    show() { this.shown = true; } focus() { this.focused = true; }
    close() { this.emit('close'); this.dead = true; this.emit('closed'); }
  }
  const manager = create({
    BrowserWindow: Window, ipcMain: { handle: (k, f) => handlers[k] = f }, userData: temp, folder: FOLDER,
    screen: { getAllDisplays: () => [{ workArea: { x: 0, y: 0, width: 1920, height: 1080 } }] },
    getOpeningScope: (event, v) => { if (event.sender !== shell) throw Error('Untrusted shell'); return v; },
    getToken: async origin => { tokens.push(origin); return origin.includes('spark') ? 'spark-secret' : 'local-secret'; },
    fetch: async (url, opts) => {
      calls.push({ url, opts });
      if (url.includes('/api/artifacts/'))
        return { ok: true, status: 200, headers: { get: k => k.toLowerCase() === 'content-type' ? imageType : '' }, arrayBuffer: async () => imageBytes };
      return { ok: true, status: 200, json: async () => typeof data === 'function' ? data(url, opts) : data };
    }
  });
  t.after(() => manager.close());
  const event = w => ({ sender: w.webContents, senderFrame: w.webContents.mainFrame });
  return { manager, handlers, windows, calls, tokens, shell, temp, event,
    setData: v => data = v, setImage: (bytes, type) => { imageBytes = bytes; imageType = type; } };
}

test('read-only whitelist accepts the dashboard feeds and refuses tricks, writes and foreign routes', () => {
  const allow = ['/api/hermes/dashboard', '/api/hermes/dashboard?limit=24', '/api/tasks', '/api/tasks?hermes_limit=24',
    '/api/hermes/providers', '/api/hermes/local', '/api/hermes/queue/priority', '/api/grunt',
    '/api/tasks/hermes/' + RUN, '/api/tasks/resolutions/' + REQ, '/api/tasks/resolutions/' + RUN, '/api/requests/' + REQ];
  for (const p of allow) assert.equal(create.request({ path: p }).method, 'GET', p);
  for (const p of ['https://attacker/api/tasks', '//attacker/api/tasks', '/api/settings', '/api/../settings',
    '/api/tasks?token=x', '/api/tasks#x', '/api/tasks\\x', '/api/artifacts/' + SHA, '/api/tasks/hermes/nothex',
    '/api/tasks/hermes/' + 'a'.repeat(31), '/api/requests/' + 'b'.repeat(15), '/api/sessions/' + REQ + '/input'])
    assert.throws(() => create.request({ path: p }), /Unsupported/, p);
  assert.throws(() => create.request({ path: '/api/tasks', method: 'POST', body: {} }), /read-only/);
  assert.throws(() => create.request({ path: '/api/tasks', body: { x: 1 } }), /read-only/);
});

test('popup is sandboxed, parentless, obtains no credential on open and denies navigation/popups', async t => {
  const f = fixture(t);
  await f.handlers['task-window:open']({ sender: f.shell }, { origin: 'http://spark:8765' });
  const w = f.windows[0];
  assert.equal(w.opts.parent, undefined);
  assert.equal(w.opts.webPreferences.sandbox, true);
  assert.equal(w.opts.webPreferences.contextIsolation, true);
  assert.equal(w.opts.webPreferences.nodeIntegration, false);
  assert.equal(w.opts.webPreferences.webviewTag, false);
  assert.match(w.file, /task-window\.html$/);
  assert.ok(!w.url.includes('?'));
  assert.equal(w.popups({ url: 'https://attacker/' }).action, 'deny');
  let denied = false; w.webContents.emit('will-navigate', { preventDefault() { denied = true; } }, 'https://attacker/');
  assert.equal(denied, true);
  let allowed = null; w.permissions(null, 'media', v => allowed = v); assert.equal(allowed, false);
  assert.deepEqual(f.handlers['task-window:info'](f.event(w)), { origin: 'http://spark:8765', top: false });
  assert.equal(f.tokens.length, 0, 'opening the window never obtains or exposes a credential');
  assert.equal(f.manager.owns(w.webContents), true);
  assert.equal(f.manager.owns({}), false);
});

test('API injects the Bearer token server-side and never shares credentials across origins', async t => {
  const f = fixture(t);
  await f.manager.open({ origin: 'http://spark:8765' });
  await f.manager.open({ origin: 'http://127.0.0.1:18765' });
  f.setData({ runs: [{ id: RUN, state: 'running' }] });
  const a = await f.handlers['task-window:api'](f.event(f.windows[0]), { path: '/api/hermes/dashboard?limit=24', method: 'GET' });
  await f.handlers['task-window:api'](f.event(f.windows[1]), { path: '/api/tasks', method: 'GET' });
  assert.equal(a.runs[0].id, RUN);
  assert.equal(f.calls[0].url, 'http://spark:8765/api/hermes/dashboard?limit=24');
  assert.equal(f.calls[0].opts.headers.authorization, 'Bearer spark-secret');
  assert.equal(f.calls[0].opts.redirect, 'error');
  assert.equal(f.calls[1].opts.headers.authorization, 'Bearer local-secret');
  assert.equal(JSON.stringify(f.handlers['task-window:info'](f.event(f.windows[0]))).includes('secret'), false);
  await assert.rejects(f.handlers['task-window:api'](f.event(f.windows[0]), { path: '/api/jobs', method: 'POST', body: {} }), /read-only/);
});

test('correspondence image returns a bounded data URL and rejects non-images, oversize and bad digests', async t => {
  const f = fixture(t);
  await f.manager.open({ origin: 'http://spark:8765' });
  const ev = f.event(f.windows[0]);
  const url = await f.handlers['task-window:image'](ev, SHA);
  assert.match(url, /^data:image\/png;base64,/);
  assert.equal(Buffer.from(url.split(',')[1], 'base64').toString(), 'PNGDATA');
  assert.equal(f.calls.at(-1).url, 'http://spark:8765/api/artifacts/' + SHA);
  await assert.rejects(f.handlers['task-window:image'](ev, 'nothex'), /Unknown image/);
  f.setImage(Buffer.from('x'), 'text/html');
  await assert.rejects(f.handlers['task-window:image'](ev, SHA), /Not an image/);
  f.setImage(Buffer.alloc(9 * 1024 * 1024), 'image/png');
  await assert.rejects(f.handlers['task-window:image'](ev, SHA), /too large/);
});

test('foreign, child-frame and navigated renderers cannot reach the transport', async t => {
  const f = fixture(t);
  await f.manager.open({ origin: 'http://spark:8765' });
  const w = f.windows[0];
  assert.throws(() => f.handlers['task-window:info']({ sender: { getURL: () => w.url } }), /Only the Spark2 task window/);
  assert.throws(() => f.handlers['task-window:info']({ sender: w.webContents, senderFrame: {} }), /Only the Spark2 task window/);
  w.url = 'https://attacker/'; assert.throws(() => f.handlers['task-window:info'](f.event(w)), /Only the Spark2 task window/);
  assert.throws(() => f.handlers['task-window:open']({ sender: {} }, { origin: 'http://spark' }), /Untrusted shell/);
});

test('always-on-top and a bounded position persist without any credential on disk', async t => {
  const f = fixture(t);
  await f.manager.open({ origin: 'http://spark:8765' });
  const w = f.windows[0];
  w.bounds = { x: 99999, y: 99999, width: 99999, height: 99999 };
  f.handlers['task-window:top'](f.event(w), true); w.close();
  const saved = JSON.parse(fs.readFileSync(path.join(f.temp, 'task-window.json'), 'utf8'))['http://spark:8765'];
  assert.equal(saved.top, true);
  assert.ok(saved.bounds.width <= 2600 && saved.bounds.x >= 0, 'bounds are clamped onto a real display');
  assert.equal(JSON.stringify(saved).includes('secret'), false);
  await f.manager.open({ origin: 'http://spark:8765' });
  assert.equal(f.windows[1].opts.alwaysOnTop, true);
});

test('narrow preload exposes no credential/general IPC, the page is CSP-locked, and the PiP menu opens it', () => {
  const preload = fs.readFileSync(path.join(FOLDER, 'task-window-preload.js'), 'utf8');
  const html = fs.readFileSync(path.join(FOLDER, 'task-window.html'), 'utf8');
  assert.match(preload, /exposeInMainWorld\('taskWindow'/);
  assert.doesNotMatch(preload, /\.token\(|"token"|'token'|\.settings\(|\.send\(/);
  assert.match(html, /connect-src 'none'/);
  assert.doesNotMatch(html, /https?:\/\/|[?&](?:token|key)=/);
  const mini = fs.readFileSync(path.join(FOLDER, 'mini.html'), 'utf8');
  assert.match(mini, /Spark2 tasks/);
  assert.match(mini, /gbox\.tasksOpen/);
  const mainPreload = fs.readFileSync(path.join(FOLDER, 'preload.js'), 'utf8');
  assert.match(mainPreload, /tasksOpen:/);
  assert.match(mainPreload, /task-window:open/);
  const main = fs.readFileSync(path.join(FOLDER, 'main.js'), 'utf8');
  assert.match(main, /require\('\.\/task-window\.cjs'\)/);
  assert.match(main, /taskWindows\?\.owns\(wc\)/);
  assert.match(main, /CmdOrCtrl\+Shift\+T/);
  assert.ok(fs.existsSync(path.join(FOLDER, 'vendor', 'three.min.js')), 'Three.js is vendored for the offline, CSP-locked popup');
  const page = fs.readFileSync(path.join(FOLDER, 'task-window.js'), 'utf8');
  assert.doesNotMatch(page, /\bimport\s/, 'the popup page uses a classic script, not an ES-module import (blocked over file://)');
  assert.match(html, /vendor\/three\.min\.js/);
});
