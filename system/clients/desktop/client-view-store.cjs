'use strict';
// Reopen presentation only. These records never carry worker/relaunch authority.
const fs = require('node:fs'), path = require('node:path'), crypto = require('node:crypto');
const handoff = require('./client-handoff.cjs');
const { origin } = require('./client-refresh.js');
const { wideBounds } = require('./compact-window.cjs');
function matches(value, server) { const key = origin(server); return !!key && origin(value?.state?.origin) === key; }
function mini(value, server) { const key = origin(server); return key && origin(value?.origin) === key ? value : null; }
function startupWindow(value) {
  return value?.state?.compact && value.compactBounds
    ? {bounds:wideBounds(value.compactBounds),top:true,maximized:false,fullscreen:false} : value?.window || null;
}
function view(value, at) {
  const { startWorker, ...saved } = handoff.view(value, at);
  return saved;
}
function create(directory, { now = Date.now, io = fs } = {}) {
  const file = server => path.join(directory, 'client-view-' + crypto.createHash('sha256').update(server).digest('hex').slice(0, 24) + '.json');
  function load(server) {
    const key = origin(server); if (!key) return null;
    try {
      const target = file(key); if (io.statSync(target).size > 16384) return null;
      const record = JSON.parse(io.readFileSync(target, 'utf8'));
      if (record.v !== 1 || record.origin !== key || !Number.isFinite(record.at) || record.at < 0) return null;
      // Earlier disk records are safely migratable because the enclosing record
      // already proves its server. Unbound sessionStorage/handoff records do not.
      return view({ ...record, state: { ...record.state, origin: key } }, now());
    } catch { return null; }
  }
  function save(server, value) {
    const key = origin(server); if (!key) throw Error('The saved view server is unavailable.');
    if (origin(value?.state?.origin) && !matches(value, key)) throw Error('The saved view belongs to a different server.');
    const at = now(), record = { v: 1, origin: key, at, ...view({ ...value, state: { ...value.state, origin: key } }, at) };
    const data = JSON.stringify(record), target = file(key), tmp = target + '.' + crypto.randomBytes(12).toString('hex');
    if (Buffer.byteLength(data) > 16384) throw Error('The saved view is too large.');
    let fd;
    try {
      fd = io.openSync(tmp, 'wx', 0o600); io.writeFileSync(fd, data); io.fsyncSync(fd); io.closeSync(fd); fd = undefined;
      io.renameSync(tmp, target);
    } catch (error) {
      if (fd !== undefined) try { io.closeSync(fd); } catch {}
      try { io.unlinkSync(tmp); } catch {}
      throw error; // atomic replacement preserves the previous complete checkpoint
    }
    return record;
  }
  return { load, save };
}
module.exports = { create, origin, matches, mini, view, startupWindow };
