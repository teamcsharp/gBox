'use strict';
const fs = require('node:fs/promises'), path = require('node:path'), crypto = require('node:crypto');
const digest = value => crypto.createHash('sha256').update(value).digest('hex');
async function filesUnder(root) {
  const files = [];
  async function walk(dir) {
    for (const e of await fs.readdir(dir, { withFileTypes: true })) {
      if (['node_modules', '.git', '__pycache__'].includes(e.name) || e.isSymbolicLink()) continue;
      const p = path.join(dir, e.name);
      if (e.isDirectory()) await walk(p);
      else if (/\.(?:js|cjs|html|css)$/.test(e.name)) files.push(p);
    }
  }
  await walk(root); return files.sort();
}
async function fingerprint(files) {
  const hash = crypto.createHash('sha256');
  for (const file of [...files].sort()) { hash.update(file); hash.update('\0'); hash.update(await fs.readFile(file)); }
  return hash.digest('hex');
}
function sourceStamp(root, { now = Date.now, interval = 20000, io = fs } = {}) {
  // The local authority imports Python in its own process. Keep its source
  // identity beside the desktop identity without rehashing the package on the
  // renderer's two-second version poll. Only changed source files are read.
  let cache = new Map(), checked = -Infinity, saved = null, pending = null;
  async function scan() {
    const next = new Map(), hash = crypto.createHash('sha256'); let bytes = 0, visited = 0;
    async function walk(dir) {
      const entries = await io.readdir(dir, { withFileTypes: true });
      for (const entry of entries.sort((a, b) => a.name.localeCompare(b.name))) {
        if (++visited > 16384) throw Error('Local backend source identity exceeds its bounded scan.');
        if (['__pycache__', '.git', 'node_modules'].includes(entry.name) || entry.isSymbolicLink()) continue;
        const file = path.join(dir, entry.name);
        if (entry.isDirectory()) { await walk(file); continue; }
        if (!entry.isFile() || !entry.name.endsWith('.py')) continue;
        const stat = await io.stat(file);
        bytes += stat.size;
        if (next.size >= 4096 || stat.size > 8 * 1024 * 1024 || bytes > 128 * 1024 * 1024)
          throw Error('Local backend source identity exceeds its bounded scan.');
        const stamp = `${stat.size}:${stat.mtimeMs}:${stat.ctimeMs}`, previous = cache.get(file);
        let content = previous?.stamp === stamp ? previous.content : digest(await io.readFile(file));
        const after = await io.stat(file);
        if (`${after.size}:${after.mtimeMs}:${after.ctimeMs}` !== stamp)
          throw Error('Local backend source changed during its identity check.');
        next.set(file, { stamp, content }); hash.update(path.relative(root, file)); hash.update('\0'); hash.update(content);
      }
    }
    const directory = await io.lstat(root);
    if (!directory.isDirectory() || directory.isSymbolicLink()) throw Error('Local backend source directory is unavailable.');
    await walk(root);
    if (!next.size) throw Error('Local backend source identity is unavailable.');
    cache = next; saved = hash.digest('hex'); checked = now(); return saved;
  }
  async function read({ fresh = false } = {}) {
    if (pending) { const value = await pending; return fresh ? read({ fresh: true }) : value; }
    if (!fresh && saved && now() - checked < interval) return saved;
    pending = scan().finally(() => { pending = null; }); return pending;
  }
  return { read };
}
function create({ desktop, web, runtimeFiles, backendRoot, apiUrl, fetch = globalThis.fetch, now = Date.now }) {
  // The main process keeps this identity across renderer F5 reloads. It never applies or restarts an update.
  const backend = backendRoot ? sourceStamp(backendRoot, { now }) : null;
  const backendStart = backend?.read() || Promise.resolve(null);
  const identity = async fresh => digest(JSON.stringify([
    await fingerprint(runtimeFiles), backend ? await backend.read({ fresh }) : null]));
  const runtimeStart = backendStart.then(() => identity(false)).catch(() => null);
  let pending = null;
  async function read({ freshBackend = false } = {}) {
    if (pending) { const value = await pending; return freshBackend ? read({ freshBackend: true }) : value; }
    pending = (async () => {
      const [desktopFiles, webFiles, started] = await Promise.all([filesUnder(desktop), filesUnder(web), runtimeStart]);
      const [renderer, runtime] = await Promise.all([fingerprint([...desktopFiles, ...webFiles].filter(p => !runtimeFiles.includes(p))), identity(freshBackend)]);
      let remote = null;
      try {
        const identities = await Promise.all(['/', '/viz/stream-watchdog.js', '/viz/session-refresh.js', '/viz/autoplay-coach.js', '/viz/re5-modifiers.js'].map(async part => {
          // FastAPI's explicit GET routes do not implement HEAD. Read headers, then cancel the static body.
          const r = await fetch(new URL(part, apiUrl()), { method: 'GET', cache: 'no-store', signal: AbortSignal.timeout(3000) });
          await r.body?.cancel();
          if (!r.ok) throw Error('Remote client identity unavailable');
          const tag = r.headers.get('etag'); if (!tag) throw Error('No remote client version');
          return part + ':' + tag;
        }));
        remote = digest(identities.join('\n'));
      } catch { /* offline is a connection state, not proof of an update */ }
      return { renderer, runtime, remote, restart: !!started && runtime !== started };
    })().finally(() => { pending = null; });
    return pending;
  }
  return { read };
}
module.exports = { create, fingerprint, filesUnder, sourceStamp };
