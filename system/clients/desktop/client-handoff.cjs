'use strict';
// A desktop-only restart: no control-plane requests, process killing, or token persistence.
const fs = require('node:fs'), crypto = require('node:crypto');
const refresh = require('./client-refresh');
const ARG = '--gbox-client-handoff=', PREFIX = 'GBOX_CLIENT_CONTROL:';
const nonce = () => crypto.randomBytes(32).toString('hex');
const validNonce = v => typeof v === 'string' && /^[a-f0-9]{64}$/.test(v);
function bounds(v) {
  if (!v || !['x', 'y', 'width', 'height'].every(k => Number.isFinite(v[k]))) return null;
  if (Math.abs(v.x) > 100000 || Math.abs(v.y) > 100000 || v.width < 160 || v.height < 90 || v.width > 32000 || v.height > 32000) return null;
  return Object.fromEntries(['x', 'y', 'width', 'height'].map(k => [k, Math.round(v[k])]));
}
function view(value, at) {
  const state = refresh.snapshot(value?.state, at), normal = bounds(value?.window?.bounds);
  if (!normal) throw Error('The desktop window state is unavailable.');
  const sid = refresh.guestState({ active: value?.mini?.sid }).active;
  return { state, window: { bounds: normal, maximized: !!value.window.maximized,
    fullscreen: !!value.window.fullscreen, top: !!value.window.top }, compactBounds: bounds(value.compactBounds),
    mini: sid ? { sid, title: String(value.mini.title || '').slice(0, 160), bounds: bounds(value.mini.bounds) } : null,
    startWorker: value.startWorker === true };
}
function save(file, value, { now = Date.now, owner = process.pid } = {}) {
  const id = nonce(), at = now(), record = { v: 1, id, owner, at, ...view(value, at) };
  const tmp = file + '.' + id;
  let fd;
  try { fd = fs.openSync(tmp, 'wx', 0o600); fs.writeFileSync(fd, JSON.stringify(record)); fs.fsyncSync(fd); }
  finally { if (fd !== undefined) fs.closeSync(fd); }
  try { fs.renameSync(tmp, file); } catch (error) { fs.unlinkSync(tmp); throw error; }
  return id;
}
function consume(file, args, { now = Date.now } = {}) {
  const markers = args.filter(a => a.startsWith(ARG));
  if (!markers.length) return { requested: false, value: null };
  try {
    if (markers.length !== 1 || !validNonce(markers[0].slice(ARG.length))) throw Error('Invalid desktop refresh handoff.');
    if (fs.statSync(file).size > 16384) throw Error('Oversized desktop refresh handoff.');
    const data = JSON.parse(fs.readFileSync(file, 'utf8')), id = markers[0].slice(ARG.length);
    if (data.v !== 1 || data.id !== id || !Number.isSafeInteger(data.owner) || data.owner <= 0 ||
        !Number.isFinite(data.at) || now() < data.at || now() - data.at > 120000) throw Error('Expired or mismatched desktop refresh handoff.');
    const value = view(data, now());
    fs.unlinkSync(file); // consumed once, before any new worker starts
    return { requested: true, value };
  } catch (error) { return { requested: true, value: null, error: error.message }; }
}

function workerChannel(child, secret, { now = Date.now, setTimer = setTimeout, clearTimer = clearTimeout } = {}) {
  let ready = false, buffer = '', pending = null, closed = false;
  function finish(error) {
    const p = pending; pending = null;
    if (p) { clearTimer(p.timer); error ? p.reject(Error(error)) : p.resolve(); }
  }
  child.on('close', code => {
    closed = true;
    if (pending) finish(pending.accepted && code === 0 ? null : 'The local worker did not confirm a clean idle shutdown.');
  });
  function feed(chunk) {
    buffer += String(chunk); let output = '', i;
    while ((i = buffer.indexOf('\n')) !== -1) {
      const line = buffer.slice(0, i); buffer = buffer.slice(i + 1);
      if (!line.startsWith(PREFIX)) { output += line + '\n'; continue; }
      let v; try { v = JSON.parse(line.slice(PREFIX.length)); } catch { continue; }
      if (v.v !== 1 || v.pid !== child.pid || v.secret !== secret) continue;
      if (v.event === 'ready') ready = true;
      if (!pending || v.id !== pending.id) continue;
      if (v.event === 'stopping') pending.accepted = true;
      if (v.event === 'refused') finish(String(v.reason || 'The local worker is busy.').slice(0, 240));
    }
    if (buffer.length > 65536) { output += buffer.startsWith(PREFIX) ? '' : buffer; buffer = ''; }
    return output;
  }
  function stop() {
    if (!ready || closed || !child.stdin?.writable) return Promise.reject(Error('The running local worker does not support safe desktop refresh yet.'));
    if (pending) return Promise.reject(Error('The local worker is already checking an idle shutdown.'));
    return new Promise((resolve, reject) => {
      const id = crypto.randomBytes(16).toString('hex');
      pending = { id, resolve, reject, accepted: false, timer: setTimer(() => finish('The local worker did not finish an idle shutdown in time; it was not killed.'), 30000) };
      try { child.stdin.write(JSON.stringify({ v: 1, secret, op: 'stop_if_idle', id, expires: now() / 1000 + 10 }) + '\n', error => { if (error) finish('The local worker control pipe is unavailable.'); }); }
      catch { finish('The local worker control pipe is unavailable.'); }
    });
  }
  return { feed, stop, ready: () => ready };
}

async function perform(io, state) {
  // Lock new desktop-owned work before checking. The worker makes its own
  // atomic idle decision BETWEEN claims, then must actually exit normally.
  io.lock(true);
  let launched = false;
  try {
    const before = await io.inspect(); if (before) throw Error(before);
    await io.stopWorker();
    const after = await io.inspect(); if (after) throw Error(after);
    const id = io.save(state);
    io.launch(id); launched = true;
    return { state: 'relaunching', reason: 'Reloading desktop code; remote sessions remain running.' };
  } catch (error) {
    return { state: 'pending', reason: String(error.message || error).slice(0, 300) };
  } finally {
    if (!launched) { io.lock(false); await io.resumeWorker(); }
  }
}
module.exports = { ARG, PREFIX, nonce, bounds, view, save, consume, workerChannel, perform };
