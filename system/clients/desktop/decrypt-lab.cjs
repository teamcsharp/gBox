'use strict';
// The decryption lab window: owned by this app, holds no credential, and only relays allowlisted lab routes.
const path = require('node:path'), fs = require('node:fs');
const { pathToFileURL } = require('node:url');

const TITLE_RE = /^[A-Za-z0-9_.-]{1,64}$/;
const SCAN_ID_RE = /^[0-9a-f]{16}$/;
const STATUS = new Set(['confirmed', 'candidate', 'rejected']);
const FIELD_RE = /^[A-Za-z0-9_.-]{1,64}$/;

function originOf(value) {
  try {
    const u = new URL(value);
    return /^https?:$/.test(u.protocol) && !u.username && !u.password ? u.origin : null;
  } catch { return null; }
}

function scopeOf(value) {
  const server = originOf(value?.origin);
  if (!server) throw Error('Choose a connected gBox server first.');
  return { origin: server };
}

function placement(value, displays = []) {
  const w = Math.round(Math.max(760, Math.min(2600, Number(value?.width) || 1380)));
  const h = Math.round(Math.max(520, Math.min(1700, Number(value?.height) || 900)));
  let x = Math.round(Number(value?.x) || 120), y = Math.round(Number(value?.y) || 90);
  const areas = displays.map((d) => d.workArea || d.bounds || d)
    .filter((a) => [a.x, a.y, a.width, a.height].every(Number.isFinite));
  if (areas.length && !areas.some((a) => Math.min(x + w, a.x + a.width) - Math.max(x, a.x) >= 120
      && Math.min(y + h, a.y + a.height) - Math.max(y, a.y) >= 100)) {
    x = areas[0].x + 40; y = areas[0].y + 40;
  }
  return { x, y, width: w, height: h };
}

// The lab page may only ask for these shapes.
function request(value) {
  if (!value || typeof value.path !== 'string' || value.path.length > 4096 || !value.path.startsWith('/api/')
      || value.path.includes('\\') || /[\u0000-\u001f]/.test(value.path)) throw Error('Unsupported lab request.');
  const u = new URL(value.path, 'http://viewer.invalid');
  if (u.origin !== 'http://viewer.invalid' || u.hash) throw Error('Unsupported lab request.');
  const method = String(value.method || (value.body === undefined ? 'GET' : 'POST')).toUpperCase();
  const p = u.pathname;
  if (method === 'GET' && value.body === undefined
      && (p === '/api/decrypt-lab/state' || p === '/api/decrypt-lab/events' || p === '/api/decrypt-lab/assets'
          || p === '/api/decrypt-lab/asset' || p === '/api/decrypt-lab/preview'
          || /^\/api\/decrypt-lab\/scan\/[0-9a-f]{16}$/.test(p))) {
    // the asset routes take a RomFS path in the query: it must stay relative, with no traversal
    if (p === '/api/decrypt-lab/asset' || p === '/api/decrypt-lab/preview') {
      const inner = u.searchParams.get('path') || '';
      if (!inner || inner.length > 400 || inner.startsWith('/') || inner.split('/').includes('..')) {
        throw Error('Unsupported asset path.');
      }
    }
    return { path: u.pathname + u.search, method };
  }
  if (method === 'POST' && p === '/api/decrypt-lab/stage') {
    const b = value.body;
    if (!b || typeof b !== 'object') throw Error('Invalid stage request.');
    if (!TITLE_RE.test(b.title || '') || typeof b.path !== 'string' || !b.path || b.path.length > 400
        || b.path.startsWith('/') || b.path.split('/').includes('..') || typeof b.data_b64 !== 'string'
        || b.data_b64.length > 90 * 1024 * 1024 || !/^[A-Za-z0-9_.-]{1,64}$/.test(b.build || 'gbox-lab')) {
      throw Error('Invalid stage request.');
    }
    return { path: p, method, body: { title: b.title, path: b.path, data_b64: b.data_b64, build: b.build || 'gbox-lab' } };
  }
  if (method === 'POST' && p === '/api/decrypt-lab/swap') {
    const b = value.body;
    const rel = (s) => typeof s === 'string' && s && s.length <= 400 && !s.startsWith('/') && !s.split('/').includes('..');
    if (!b || typeof b !== 'object' || !TITLE_RE.test(b.title || '') || !rel(b.from_path) || !rel(b.to_path)
        || !/^[A-Za-z0-9_.-]{1,64}$/.test(b.build || 'gbox-lab')) {
      throw Error('Invalid swap request.');
    }
    return { path: p, method, body: { title: b.title, from_path: b.from_path, to_path: b.to_path, build: b.build || 'gbox-lab' } };
  }
  if (method === 'POST' && p === '/api/decrypt-lab/scan') {
    const b = value.body;
    if (!b || typeof b !== 'object' || JSON.stringify(b).length > 512) throw Error('Invalid scan request.');
    if (!TITLE_RE.test(b.title || '') || !Number.isSafeInteger(b.offset) || !Number.isSafeInteger(b.length)
        || b.length < 16 || b.length > 4096 || !['module', 'absolute'].includes(b.mode)) {
      throw Error('Invalid scan request.');
    }
    return { path: p, method, body: { title: b.title, offset: b.offset, length: b.length, mode: b.mode } };
  }
  if (method === 'POST' && p === '/api/decrypt-lab/field') {
    const b = value.body;
    if (!b || typeof b !== 'object' || JSON.stringify(b).length > 1024) throw Error('Invalid field request.');
    if (!TITLE_RE.test(b.title || '') || !FIELD_RE.test(b.name || '') || !STATUS.has(b.status)) {
      throw Error('Invalid field request.');
    }
    const note = typeof b.note === 'string' ? b.note.slice(0, 400) : '';
    return { path: p, method, body: { title: b.title, name: b.name, status: b.status, note } };
  }
  throw Error('Unsupported lab request.');
}

module.exports = function ({ BrowserWindow, ipcMain, getOpeningScope, getToken, fetch: fetcher = globalThis.fetch,
                             userData, screen, folder = __dirname, setTimer = setTimeout, clearTimer = clearTimeout }) {
  const windows = new Map();
  const stateFile = path.join(userData, 'decrypt-lab-window.json');
  const file = path.join(folder, 'decrypt-lab.html');
  const fileURL = pathToFileURL(file).href;
  let saved = {};
  try {
    if (fs.statSync(stateFile).size < 16384) {
      const value = JSON.parse(fs.readFileSync(stateFile, 'utf8'));
      if (value && typeof value === 'object' && !Array.isArray(value)) saved = value;
    }
  } catch { /* first run */ }

  function rowOf(event) {
    const row = [...windows.values()].find((r) => !r.win.isDestroyed() && event.sender === r.win.webContents);
    if (!row || (event.senderFrame && event.senderFrame !== row.win.webContents.mainFrame)
        || event.sender.getURL() !== fileURL) throw Error('Only the owned lab window can make this request.');
    return row;
  }

  function persist(row) {
    if (row.win.isDestroyed()) return;
    const b = row.win.getNormalBounds?.() || row.win.getBounds();
    saved[row.scope.origin] = { bounds: placement(b, screen?.getAllDisplays?.() || []), top: row.win.isAlwaysOnTop() };
    const tmp = stateFile + '.tmp';
    try {
      fs.mkdirSync(userData, { recursive: true });
      fs.writeFileSync(tmp, JSON.stringify(saved), { mode: 0o600 });
      fs.renameSync(tmp, stateFile);
    } catch { try { fs.unlinkSync(tmp); } catch { /* ignore */ } }
  }

  function notify(row) { row.win.webContents.send('decrypt-lab:scope', { ...row.scope, top: row.win.isAlwaysOnTop() }); }

  async function open(value) {
    const target = scopeOf(value);
    let row = windows.get(target.origin);
    if (row && !row.win.isDestroyed()) { row.win.show(); row.win.focus(); return { opened: true, ...target }; }
    const prefs = saved[target.origin] || {};
    const bounds = placement(prefs.bounds, screen?.getAllDisplays?.() || []);
    const win = new BrowserWindow({
      ...bounds, minWidth: 760, minHeight: 520, show: false, title: 'gBox · Decryption lab',
      backgroundColor: '#0b0f14', alwaysOnTop: prefs.top === true,
      webPreferences: {
        preload: path.join(folder, 'decrypt-lab-preload.js'), contextIsolation: true, sandbox: true,
        nodeIntegration: false, webviewTag: false, backgroundThrottling: false, partition: 'decrypt-lab-window',
      },
    });
    row = { win, scope: target, timer: null };
    windows.set(target.origin, row);
    win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
    win.webContents.on('will-navigate', (event, url) => { if (url !== fileURL) event.preventDefault(); });
    win.webContents.on('will-attach-webview', (event) => event.preventDefault());
    win.webContents.session?.setPermissionRequestHandler?.((_wc, _p, reply) => reply(false));
    for (const event of ['move', 'resize']) {
      win.on(event, () => { if (row.timer) clearTimer(row.timer); row.timer = setTimer(() => { row.timer = null; persist(row); }, 250); });
    }
    win.on('close', () => persist(row));
    win.on('closed', () => { if (row.timer) clearTimer(row.timer); if (windows.get(target.origin) === row) windows.delete(target.origin); });
    await win.loadFile(file);
    if (!win.isDestroyed()) { notify(row); win.show(); }
    return { opened: true, ...target };
  }

  async function api(row, input) {
    const q = request(input), server = row.scope.origin, credential = await getToken(server);
    if (!credential) throw Error('This server is reconnecting. Nothing was read.');
    const r = await fetcher(server + q.path, {
      method: q.method, redirect: 'error',
      headers: { authorization: 'Bearer ' + credential, 'content-type': 'application/json' },
      ...(q.body !== undefined ? { body: JSON.stringify(q.body) } : {}),
      signal: AbortSignal.timeout(20000),
    });
    if (!r.ok) {
      let detail = '';
      try { const v = await r.json(); if (typeof v.detail === 'string') detail = ': ' + v.detail.slice(0, 240); } catch { /* ignore */ }
      throw Error('Lab request failed (' + r.status + ')' + detail);
    }
    return r.json();
  }

  ipcMain.handle('decrypt-lab:open', (event, value) => open(getOpeningScope(event, value)));
  ipcMain.handle('decrypt-lab:info', (event) => { const r = rowOf(event); return { ...r.scope, top: r.win.isAlwaysOnTop() }; });
  ipcMain.handle('decrypt-lab:api', (event, value) => api(rowOf(event), value));
  // A preview is an image, not JSON: the renderer cannot fetch a URL itself (connect-src 'none'), so the main
  // process fetches it with the credential and hands back a data URL the page can put in an <img>.
  ipcMain.handle('decrypt-lab:preview', async (event, value) => {
    const row = rowOf(event);
    const title = String(value?.title || ''), path = String(value?.path || '');
    if (!TITLE_RE.test(title) || !path || path.length > 400 || path.startsWith('/') || path.split('/').includes('..')) {
      throw Error('Invalid preview request.');
    }
    const q = request({ path: `/api/decrypt-lab/preview?title=${encodeURIComponent(title)}&path=${encodeURIComponent(path)}`,
                        method: 'GET' });
    const server = row.scope.origin, credential = await getToken(server);
    if (!credential) throw Error('This server is reconnecting. Nothing was read.');
    const r = await fetcher(server + q.path, {
      method: 'GET', redirect: 'error',
      headers: { authorization: 'Bearer ' + credential },
      signal: AbortSignal.timeout(60000),
    });
    if (!r.ok) {
      let detail = '';
      try { const v = await r.json(); if (typeof v.detail === 'string') detail = ': ' + v.detail.slice(0, 200); } catch { /* not JSON */ }
      throw Error('Preview unavailable (' + r.status + ')' + detail);
    }
    const type = (r.headers.get('content-type') || 'image/png').split(';')[0];
    const buf = Buffer.from(await r.arrayBuffer());
    if (buf.length > 4 * 1024 * 1024) throw Error('Preview is larger than 4 MiB');
    return { dataUrl: `data:${type};base64,${buf.toString('base64')}`, bytes: buf.length, type };
  });
  ipcMain.handle('decrypt-lab:top', (event, top) => { const r = rowOf(event); r.win.setAlwaysOnTop(top === true); persist(r); return r.win.isAlwaysOnTop(); });

  return {
    open,
    owns(wc) { return [...windows.values()].some((r) => !r.win.isDestroyed() && r.win.webContents === wc); },
    close() { for (const r of windows.values()) if (!r.win.isDestroyed()) r.win.close(); },
    windows,
  };
};
module.exports.scope = scopeOf;
module.exports.placement = placement;
module.exports.request = request;
