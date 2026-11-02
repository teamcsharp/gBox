'use strict';
// The Spark2 task dashboard popup (PiP → "Spark2 tasks"). Like the Mercenaries window it owns no
// emulator and never receives an API credential: the renderer asks over IPC and the main process
// injects the Bearer token, so only a tight whitelist of read-only Hermes/task routes can be called.
// Images in a task's correspondence are fetched here and handed back as a data: URL (the renderer's
// CSP is default-src 'none', so it cannot fetch or load a remote image itself).
const path = require('node:path'), fs = require('node:fs');
const { pathToFileURL } = require('node:url');

const HEX32 = /^[0-9a-f]{32}$/, HEX16 = /^[0-9a-f]{16}$/, SHA256 = /^[0-9a-f]{64}$/;

function origin(value) {
  try { const u = new URL(value); return /^https?:$/.test(u.protocol) && !u.username && !u.password ? u.origin : null; }
  catch { return null; }
}

// Every dashboard request is GET and read-only. Returns the exact path+query to call, or throws.
function request(value) {
  if (!value || typeof value.path !== 'string' || value.path.length > 2048
      || !value.path.startsWith('/api/') || value.path.includes('\\'))
    throw Error('Unsupported dashboard request.');
  const u = new URL(value.path, 'http://viewer.invalid');
  if (u.origin !== 'http://viewer.invalid' || u.hash || u.pathname !== value.path.split('?')[0]
      || /[\u0000-\u001f]/.test(value.path)
      || [...u.searchParams.keys()].some(k => /token|authorization/i.test(k)))
    throw Error('Unsupported dashboard request.');
  if (String(value.method || 'GET').toUpperCase() !== 'GET' || value.body !== undefined)
    throw Error('The dashboard is read-only.');
  const p = u.pathname;
  const run = /^\/api\/tasks\/hermes\/([0-9a-f]{32})$/.exec(p);
  const resolution = /^\/api\/tasks\/resolutions\/([0-9a-f]{16}|[0-9a-f]{32})$/.exec(p);
  const req = /^\/api\/requests\/([0-9a-f]{16}|[0-9a-f]{32})$/.exec(p);
  const ok = p === '/api/hermes/dashboard' || p === '/api/tasks'
    || p === '/api/hermes/providers' || p === '/api/hermes/local'
    || p === '/api/hermes/queue/priority' || p === '/api/grunt'
    || (run && HEX32.test(run[1])) || (resolution && (HEX16.test(resolution[1]) || HEX32.test(resolution[1])))
    || (req && (HEX16.test(req[1]) || HEX32.test(req[1])));
  if (!ok) throw Error('Unsupported dashboard request.');
  return { path: u.pathname + u.search, method: 'GET' };
}

module.exports = function ({ BrowserWindow, ipcMain, getOpeningScope, getToken, fetch: fetcher = globalThis.fetch,
                             userData, screen, folder = __dirname, setTimer = setTimeout, clearTimer = clearTimeout }) {
  const windows = new Map();
  const stateFile = path.join(userData, 'task-window.json');
  const file = path.join(folder, 'task-window.html');
  const fileURL = pathToFileURL(file).href;
  let saved = {};
  try {
    if (fs.statSync(stateFile).size < 16384) {
      const value = JSON.parse(fs.readFileSync(stateFile, 'utf8'));
      if (value && typeof value === 'object' && !Array.isArray(value)) saved = value;
    }
  } catch {}

  function placement(prefs) {
    const b = prefs && prefs.bounds || {};
    const w = Math.round(Math.max(760, Math.min(2600, Number(b.width) || 1180)));
    const h = Math.round(Math.max(520, Math.min(1700, Number(b.height) || 820)));
    let x = Math.round(Number(b.x)), y = Math.round(Number(b.y));
    const displays = screen && screen.getAllDisplays ? screen.getAllDisplays() : [];
    const areas = displays.map(d => d.workArea || d.bounds || d).filter(a => [a.x, a.y, a.width, a.height].every(Number.isFinite));
    if (!Number.isFinite(x) || !Number.isFinite(y) || Math.abs(x) > 100000 || Math.abs(y) > 100000
        || (areas.length && !areas.some(a => Math.min(x + w, a.x + a.width) - Math.max(x, a.x) >= 100
                                          && Math.min(y + h, a.y + a.height) - Math.max(y, a.y) >= 80))) {
      if (areas.length) { x = areas[0].x + 40; y = areas[0].y + 40; } else { x = 120; y = 120; }
    }
    return { x, y, width: w, height: h };
  }

  function persist(row) {
    if (row.win.isDestroyed()) return;
    const b = row.win.getNormalBounds ? row.win.getNormalBounds() : row.win.getBounds();
    saved[row.scope.origin] = { bounds: placement({ bounds: b }), top: row.win.isAlwaysOnTop() };
    const tmp = stateFile + '.tmp';
    try { fs.mkdirSync(userData, { recursive: true }); fs.writeFileSync(tmp, JSON.stringify(saved), { mode: 0o600 }); fs.renameSync(tmp, stateFile); }
    catch { try { fs.unlinkSync(tmp); } catch {} }
  }

  function notify(row) { row.win.webContents.send('task-window:scope', { origin: row.scope.origin, top: row.win.isAlwaysOnTop() }); }

  function rowOf(event) {
    const row = [...windows.values()].find(r => !r.win.isDestroyed() && event.sender === r.win.webContents);
    if (!row || (event.senderFrame && event.senderFrame !== row.win.webContents.mainFrame) || event.sender.getURL() !== fileURL)
      throw Error('Only the Spark2 task window can make this request.');
    return row;
  }

  async function open(value) {
    const server = origin(value && value.origin);
    if (!server) throw Error('Connect to a gBox server first.');
    let row = windows.get(server);
    if (row && !row.win.isDestroyed()) { row.win.show(); row.win.focus(); return { opened: true, origin: server }; }
    const prefs = saved[server] || {}, bounds = placement(prefs);
    const win = new BrowserWindow({
      ...bounds, minWidth: 760, minHeight: 520, show: false, title: 'gBox · Spark2 tasks', backgroundColor: '#0d0d0d',
      alwaysOnTop: prefs.top === true,
      webPreferences: { preload: path.join(folder, 'task-window-preload.js'), contextIsolation: true, sandbox: true,
        nodeIntegration: false, webviewTag: false, backgroundThrottling: false, partition: 'task-window' }
    });
    row = { win, scope: { origin: server }, timer: null };
    windows.set(server, row);
    win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
    win.webContents.on('will-navigate', (event, url) => { if (url !== fileURL) event.preventDefault(); });
    win.webContents.on('will-attach-webview', event => event.preventDefault());
    if (win.webContents.session && win.webContents.session.setPermissionRequestHandler)
      win.webContents.session.setPermissionRequestHandler((_wc, _permission, reply) => reply(false));
    for (const ev of ['move', 'resize'])
      win.on(ev, () => { if (row.timer) clearTimer(row.timer); row.timer = setTimer(() => { row.timer = null; persist(row); }, 250); });
    win.on('close', () => persist(row));
    win.on('closed', () => { if (row.timer) clearTimer(row.timer); if (windows.get(server) === row) windows.delete(server); });
    await win.loadFile(file);
    if (!win.isDestroyed()) { notify(row); win.show(); }
    return { opened: true, origin: server };
  }

  async function call(server, path, method = 'GET') {
    const credential = await getToken(server);
    if (!credential) throw Error('This server is reconnecting.');
    const r = await fetcher(server + path, { method, redirect: 'error',
      headers: { authorization: 'Bearer ' + credential }, signal: AbortSignal.timeout(15000) });
    if (!r.ok) {
      let detail = '';
      try { const v = await r.json(); if (typeof v.detail === 'string') detail = ': ' + v.detail.slice(0, 240); } catch {}
      const err = Error('Dashboard request failed (' + r.status + ')' + detail);
      err.status = r.status;
      throw err;
    }
    return r;
  }

  async function api(row, input) {
    const q = request(input);
    const r = await call(row.scope.origin, q.path, q.method);
    return r.json();
  }

  // A correspondence image: fetched here (CSP blocks the renderer) and returned as a bounded data: URL.
  async function image(row, digest) {
    if (!SHA256.test(String(digest || ''))) throw Error('Unknown image.');
    const r = await call(row.scope.origin, '/api/artifacts/' + digest, 'GET');
    const type = (r.headers.get('content-type') || '').split(';')[0].trim();
    if (!/^image\//.test(type)) throw Error('Not an image.');
    const buf = Buffer.from(await r.arrayBuffer());
    if (buf.length > 8 * 1024 * 1024) throw Error('Image too large to preview.');
    return 'data:' + type + ';base64,' + buf.toString('base64');
  }

  ipcMain.handle('task-window:open', (event, value) => open(getOpeningScope(event, value)));
  ipcMain.handle('task-window:info', event => { const r = rowOf(event); return { origin: r.scope.origin, top: r.win.isAlwaysOnTop() }; });
  ipcMain.handle('task-window:api', (event, value) => api(rowOf(event), value));
  ipcMain.handle('task-window:image', (event, digest) => image(rowOf(event), digest));
  ipcMain.handle('task-window:top', (event, top) => { const r = rowOf(event); r.win.setAlwaysOnTop(top === true); persist(r); return r.win.isAlwaysOnTop(); });

  return {
    open,
    owns(wc) { return [...windows.values()].some(r => !r.win.isDestroyed() && r.win.webContents === wc); },
    close() { for (const r of windows.values()) if (!r.win.isDestroyed()) r.win.close(); },
    windows
  };
};
module.exports.origin = origin;
module.exports.request = request;
