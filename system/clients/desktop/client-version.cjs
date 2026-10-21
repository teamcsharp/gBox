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
function create({ desktop, web, runtimeFiles, apiUrl, fetch = globalThis.fetch }) {
  // The main process keeps this identity across renderer F5 reloads. It never applies or restarts an update.
  const runtimeStart = fingerprint(runtimeFiles).catch(() => null);
  let pending = null;
  async function read() {
    if (pending) return pending;
    pending = (async () => {
      const [desktopFiles, webFiles, started] = await Promise.all([filesUnder(desktop), filesUnder(web), runtimeStart]);
      const [renderer, runtime] = await Promise.all([fingerprint([...desktopFiles, ...webFiles].filter(p => !runtimeFiles.includes(p))), fingerprint(runtimeFiles)]);
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
module.exports = { create, fingerprint, filesUnder };
