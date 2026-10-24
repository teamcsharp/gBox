const { test } = require('node:test'), assert = require('node:assert/strict');
const fs = require('node:fs'), os = require('node:os'), path = require('node:path'), vm = require('node:vm');
const V = require('../clients/desktop/client-view-store.cjs'), R = require('../clients/desktop/client-refresh.js');
const S = require('../clients/web/viz/session-refresh.js');
const value = () => ({ state: { v: 1, sid: 'pip-B', compact: true, returnMode: 'full',
  guest: { tab: 'Sessions', playing: 'main-A', active: 'pip-B', pip: 'pip-B' }, token: 'SECRET' },
  window: { bounds: { x: 50, y: 60, width: 1200, height: 900 }, maximized: true, fullscreen: false, top: false },
  compactBounds: { x: 800, y: 500, width: 480, height: 360 },
  mini: { sid: 'legacy-C', title: 'Game', bounds: { x: 90, y: 100, width: 480, height: 360 }, url: '?token=SECRET' },
  startWorker: true, owner: 123, id: 'authority' });
function disk(t) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'gbox-view-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true })); return dir;
}
test('ordinary reopen days later restores exact streams and PiP origin without a handoff token', async t => {
  const dir = disk(t); V.create(dir, { now: () => 1000 }).save('http://server:8765', value());
  const reopened = V.create(dir, { now: () => 86400000 }).load('http://server:8765');
  assert.deepEqual(reopened.state.guest, value().state.guest); assert.equal(reopened.state.sid, 'pip-B');
  assert.equal(reopened.state.returnMode, 'full'); assert.deepEqual(reopened.window, value().window);
  assert.deepEqual(reopened.compactBounds, value().compactBounds); assert.equal(reopened.mini.sid, 'legacy-C');
  const calls = [], resolver = S.create({ sessions: async () => ['main-A', 'pip-B', 'other'].map(session_id => ({ session_id, state: 'running' })),
    tabs: ['Home', 'Sessions'], show: async (...args) => calls.push(args), active: s => calls.push(s.session_id), pip: () => calls.push('pip') });
  assert.deepEqual((await resolver.restore(reopened.state.guest)).missing, []);
  assert.deepEqual(calls, [['Sessions', 'main-A'], 'pip-B', 'pip']);
});
test('server origins are isolated and saved records contain no credentials or process authority', t => {
  const dir = disk(t), store = V.create(dir);
  store.save('http://user:SECRET@server:8765/?token=SECRET#SECRET', value());
  assert.equal(store.load('https://server:8765'), null); assert.equal(store.load('http://other:8765'), null);
  assert.ok(store.load('http://server:8765'));
  const raw = fs.readFileSync(path.join(dir, fs.readdirSync(dir)[0]), 'utf8');
  assert.doesNotMatch(raw, /SECRET|token|startWorker|owner|authority|"url"/);
  assert.equal(V.origin('file:///foo'), null); assert.equal(V.origin('invalid'), null);
  assert.equal(store.load('http://server:8765').state.origin, 'http://server:8765');
  assert.equal(V.matches({ state: { origin: 'http://server:8765' } }, 'http://server:8765'), true);
  assert.equal(V.matches({ state: {} }, 'http://server:8765'), false, 'unbound handoff cannot select streams');
  assert.equal(V.matches({ state: { origin: 'http://old:8765' } }, 'http://server:8765'), false);
  assert.equal(V.mini({ sid: 'old', origin: 'http://old' }, 'http://server'), null);
  assert.equal(V.mini({ sid: 'unbound' }, 'http://server'), null);
});
test('legacy origin-scoped disk view migrates safely, unlike an unbound reload record', t => {
  const dir = disk(t), store = V.create(dir); store.save('http://server', value());
  const file = path.join(dir, fs.readdirSync(dir)[0]), old = JSON.parse(fs.readFileSync(file, 'utf8'));
  delete old.state.origin; fs.writeFileSync(file, JSON.stringify(old));
  assert.equal(store.load('http://server').state.origin, 'http://server');
  const data = new Map(), storage = { getItem: k => data.get(k), setItem: (k, v) => data.set(k, v), removeItem: k => data.delete(k) };
  const ctl = R.create({ storage, context: () => ({ origin: 'http://server' }), now: () => 1000 });
  for (const bound of [undefined, 'http://other']) {
    storage.setItem('gbox.client.refresh.v1', JSON.stringify({ ...value().state, at: 1000, origin: bound }));
    assert.equal(ctl.pending(), null); assert.equal(data.size, 0);
    assert.equal(ctl.adopt({ ...value().state, origin: bound }), null);
  }
  assert.equal(ctl.adopt({ ...value().state, origin: 'http://user:SECRET@server/?token=SECRET' }).origin, 'http://server');
  assert.doesNotMatch([...data.values()].join(''), /SECRET|token/);
});
test('API switch discards partial old-server intent and cannot relabel an old guest as the new server', async () => {
  let server = 'http://old', guest = { tab: 'Sessions', playing: 'old-A', active: 'old-B', pip: 'old-B', origin: 'http://old', revision: 4 };
  const data = new Map(), ctl = R.create({
    storage: { getItem: k => data.get(k), setItem: (k, v) => data.set(k, v), removeItem: k => data.delete(k) },
    context: () => ({ origin: server, sid: 'old-B', compact: true, section: 'play' }),
    readState: async () => guest, reload: async () => {} });
  ctl.remember(guest); ctl.retain({ ...value().state, origin: server }, guest);
  server = 'http://new'; assert.equal(ctl.pending(), null); assert.equal(ctl.observe(guest), null);
  const next = await ctl.refresh(); assert.equal(next.origin, 'http://new'); assert.equal(next.sid, null);
  assert.equal(next.compact, false); assert.equal(next.guest.playing, null); assert.equal(next.guest.pip, null);
  ctl.done(); guest = { tab: 'Sessions', playing: 'new-A', active: 'new-A', origin: server };
  const confirmed = ctl.observe(guest);
  assert.equal(confirmed.guest.playing, 'new-A'); assert.equal(confirmed.sid, 'new-A');
  assert.equal(confirmed.compact, false, 'an old native compact target cannot be rebound to a new server');
});
test('corruption, oversized and invalid records cannot restore a view', t => {
  const dir = disk(t), store = V.create(dir); store.save('http://server', value());
  const file = path.join(dir, fs.readdirSync(dir)[0]);
  for (const data of ['{', ' '.repeat(16385), JSON.stringify({ v: 1, origin: 'http://server', at: 1, window: { bounds: {} } })]) {
    fs.writeFileSync(file, data); assert.equal(store.load('http://server'), null);
  }
});
test('failed replacement leaves last complete checkpoint intact and removes its temporary file', t => {
  const dir = disk(t), store = V.create(dir); store.save('http://server', value());
  const bad = V.create(dir, { io: { ...fs, renameSync() { throw Error('disk failure'); } } });
  assert.throws(() => bad.save('http://server', { ...value(), state: { guest: { playing: 'wrong' } } }), /disk failure/);
  assert.equal(store.load('http://server').state.guest.playing, 'main-A'); assert.equal(fs.readdirSync(dir).length, 1);
});
function tracker() {
  let time = 1000, context = { sid: 'pip-B', compact: true, section: 'play' }; const data = new Map();
  const storage = { getItem: k => data.get(k), setItem: (k, v) => data.set(k, v), removeItem: k => data.delete(k) };
  const ctl = R.create({ storage, now: () => time, context: () => context, readState: async () => ({}), reload: async () => {} });
  return { ctl, data, later: () => { time += 86400000; }, context: v => { context = v; } };
}
test('periodic checkpoints do not arm a reload or erase a good view on guest read failure', () => {
  const x = tracker(), g = { tab: 'Sessions', playing: 'main-A', active: 'pip-B', pip: 'pip-B', token: 'SECRET' };
  const observed = x.ctl.observe(g); assert.equal(observed.guest.playing, 'main-A'); assert.equal(x.ctl.pending(), null);
  assert.equal(x.data.size, 0); assert.equal(x.ctl.observe({}), null); assert.equal(x.ctl.current().guest.pip, 'pip-B');
});
test('explicit empty foreground and PiP clear an old fallback session identity', () => {
  const x = tracker(); x.context({ sid: 'stale', compact: false, section: 'play' });
  assert.equal(x.ctl.observe({ tab: 'Home', playing: null, active: null, pip: null }).sid, null);
});
test('immediate F5 after operator navigation does not revive retained missing streams', async () => {
  const saved = new Map(), latest = { tab: 'Library', playing: null, active: null, pip: null, revision: 5 };
  const ctl = R.create({ storage: { getItem: k => saved.get(k), setItem: (k, v) => saved.set(k, v), removeItem: k => saved.delete(k) },
    context: () => ({ section: 'play', compact: false }), readState: async () => latest, reload: async () => {} });
  ctl.retain(value().state, { tab: 'Sessions', playing: 'main-A', active: 'main-A', pip: null, revision: 4 });
  const state = await ctl.refresh(); assert.equal(state.guest.tab, 'Library'); assert.equal(state.guest.pip, null);
});
test('missing stream intent survives long offline periods then explicit navigation replaces it', () => {
  const x = tracker(), partial = { tab: 'Sessions', playing: 'main-A', active: 'main-A', pip: null, revision: 4 };
  x.ctl.retain(value().state, partial); x.later();
  assert.equal(x.ctl.observe(partial).guest.pip, 'pip-B'); assert.equal(x.ctl.pending().guest.pip, 'pip-B');
  const next = x.ctl.observe({ tab: 'Library', playing: null, active: 'main-A', pip: 'main-A', revision: 5 });
  assert.equal(x.ctl.pending(), null); assert.equal(next.guest.tab, 'Library'); assert.equal(next.guest.pip, 'main-A');
});
test('explicit PiP close and shell section navigation replace a retained partial view', () => {
  for (const action of ['close', 'section']) {
    const x = tracker(), partial = { tab: 'Sessions', playing: null, active: 'pip-B', pip: 'pip-B', revision: 4 };
    x.ctl.retain(value().state, partial);
    if (action === 'section') x.context({ sid: 'pip-B', compact: true, section: 'requests' });
    const next = x.ctl.observe(action === 'close' ? { ...partial, active: null, pip: null } : partial);
    assert.equal(x.ctl.pending(), null); assert.equal(next.guest.playing, null);
  }
});
test('main checkpoint authenticates shell sender and actual guest origin, and skips unchanged writes', () => {
  const source = fs.readFileSync(require.resolve('../clients/desktop/main.js'), 'utf8');
  const code = source.slice(source.indexOf('function saveClientView('), source.indexOf('let embedded ='));
  const wc = {}, writes = [], handlers = {}, x = value(); x.state.origin = 'http://server';
  const ctx = vm.createContext({ savedClientState: null, savedClientOrigin: null, savedClientKey: null, clientViewTimer: null,
    win: { isDestroyed: () => false, webContents: wc }, clientViews: V, settings: () => ({ apiUrl: 'http://server' }),
    compactWindow: { handoff: () => ({ window: x.window, compactBounds: x.compactBounds }) }, mini: null, pendingMini: null,
    clientViewStore: { save: (...args) => writes.push(args), load: () => x },
    assertClientSender: e => { if (e.sender !== wc) throw Error('wrong sender'); },
    ipcMain: { handle: (name, fn) => { handlers[name] = fn; } }, setTimeout, clearTimeout });
  vm.runInContext(code, ctx);
  assert.throws(() => handlers['client:view-save']({}, x.state, 'http://server'), /wrong sender/);
  assert.equal(handlers['client:view-save']({ sender: wc }, x.state, 'http://other'), false); assert.equal(writes.length, 0);
  assert.equal(handlers['client:view-save']({ sender: wc }, x.state, 'http://server'), true);
  handlers['client:view-save']({ sender: wc }, { ...x.state, at: Date.now() }, 'http://server'); assert.equal(writes.length, 1);
  assert.equal(writes[0][1].startWorker, undefined);
  ctx.pendingMini = { sid: 'old-mini', origin: 'http://old' };
  handlers['client:view-save']({ sender: wc }, x.state, 'http://server'); assert.equal(writes.length, 1);
  ctx.pendingMini = { sid: 'same-server-mini', origin: 'http://server' };
  handlers['client:view-save']({ sender: wc }, x.state, 'http://server'); assert.equal(writes.length, 2);
  assert.equal(writes[1][1].mini.sid, 'same-server-mini');
});
test('delayed mini reopen refuses an API switch after token lookup without creating a window', async () => {
  const source = fs.readFileSync(require.resolve('../clients/desktop/main.js'), 'utf8');
  const code = source.slice(source.indexOf('async function openMini('), source.indexOf('ipcMain.handle("mini:open"'));
  let server = 'http://old', finish;
  const ctx = vm.createContext({ clientViews: V, settings: () => ({ apiUrl: server }), token: () => new Promise(resolve => { finish = resolve; }),
    clientHandoffBusy: false, BrowserWindow: class { constructor() { assert.fail('must not create a cross-server PiP'); } } });
  vm.runInContext(code, ctx);
  const job = ctx.openMini('old-session', 'Game', undefined, 'http://old');
  server = 'http://new'; finish('fixture-token'); await assert.rejects(job, /different server/);
});
test('cold view startup preserves presentation without sweeping legacy or unrelated processes', () => {
  const source = fs.readFileSync(require.resolve('../clients/desktop/main.js'), 'utf8');
  const start = source.slice(source.indexOf('startupHandoff = clientHandoff.consume'), source.indexOf('  appMenu();', source.indexOf('startupHandoff = clientHandoff.consume')));
  assert.match(start, /const startupView = handoffMatches \? startupHandoff.value : \(!startupHandoff.requested && clientViewStore.load/);
  assert.match(start, /const handoffMatches = clientViews.matches\(startupHandoff.value, settings\(\).apiUrl\)/);
  assert.doesNotMatch(start, /startupHandoff\s*=\s*clientViewStore|startWorker\(/);
  const launch = source.slice(source.indexOf('if (startupHandoff.requested) {'),
    source.indexOf('startAudioVolumeHelper();', source.indexOf('if (startupHandoff.requested) {')));
  assert.match(launch, /startupHandoff.value\?\.startWorker/);
  assert.match(launch, /settings\(\).autoStartWorker/);
  assert.doesNotMatch(launch, /cleanupSessions|taskkill|Stop-Process|Get-CimInstance|execFile/);
  assert.doesNotMatch(source, /CLEANUP_PS|cleanupSessions\(|Stop-Process/);
  const shutdown = source.slice(source.indexOf('function shutdownSessions()'), source.indexOf('app.on("window-all-closed"'));
  assert.match(shutdown, /String\(worker.pid\)/);
  assert.match(shutdown, /String\(localControlProcess.pid\)/);
  assert.doesNotMatch(shutdown, /Get-CimInstance|Where-Object|runtime\\/);
});
test('cold renderer reopen waits for guest readiness and restores both roles before native compact', async () => {
  const html = fs.readFileSync(require.resolve('../clients/desktop/index.html'), 'utf8');
  const code = html.slice(html.indexOf('async function restoreClientView()'), html.indexOf('// Native desktop PiP has no browser gesture restriction.'));
  let pending = null, ready; const calls = [], state = value().state;
  const guest = { gboxReady: new Promise(resolve => { ready = resolve; }), executeJavaScript: async script => {
    assert.match(script, /main-A/); assert.match(script, /pip-B/); calls.push('guest'); return { missing: [], view: state.guest };
  } };
  const ctx = vm.createContext({ clientViewNavigation: 0, clientViewRestoring: true, EMB: {},
    clientRefresh: { pending: () => pending, adopt: s => { pending = s; }, done: () => { pending = null; }, retain() {},
      remember: guest => { assert.equal(guest.playing, 'main-A'); assert.equal(guest.pip, 'pip-B'); calls.push('remember'); } },
    gbox: { clientView: async () => state }, document: { querySelector: q => q === '#wv' ? guest : { click() {} } },
    loadPlay: async () => { calls.push('load'); }, compactController: { enter: async s => { assert.equal(s.sid, 'pip-B'); assert.equal(s.preserveGuest, true); calls.push('compact'); } } });
  vm.runInContext(code, ctx); const job = ctx.restoreClientView(); await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(calls, ['load']); ready(); await job;
  assert.deepEqual(calls, ['load', 'guest', 'remember', 'compact']); assert.equal(ctx.EMB.sid, 'main-A'); assert.equal(ctx.clientViewRestoring, false);
});
test('operator shell navigation while saved view loads cancels cold restoration', async () => {
  const html = fs.readFileSync(require.resolve('../clients/desktop/index.html'), 'utf8');
  const code = html.slice(html.indexOf('async function restoreClientView()'), html.indexOf('// Native desktop PiP has no browser gesture restriction.'));
  let pending = null, finish; const ctx = vm.createContext({ clientViewNavigation: 0, clientViewRestoring: true,
    clientRefresh: { pending: () => pending, adopt: s => { pending = s; }, done: () => { pending = null; }, retain() {} },
    gbox: { clientView: () => new Promise(resolve => { finish = resolve; }) },
    loadPlay: () => { throw Error('must not select a view'); } });
  vm.runInContext(code, ctx); const job = ctx.restoreClientView(); ctx.clientViewNavigation++; finish(value().state); await job;
  assert.equal(pending, null); assert.equal(ctx.clientViewRestoring, false);
});
