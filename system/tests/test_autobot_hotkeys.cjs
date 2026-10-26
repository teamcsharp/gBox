// F3 starts the autobot on the game a window shows from any PC; F5 brings a bot game back with its autobot driving
// (operator 2026-10-26). The desktop shell's handlers, run against stubs: no Electron, no server.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const PIP = require('../clients/desktop/pip-media.js');

const html = fs.readFileSync(path.join(__dirname, '../clients/desktop/index.html'), 'utf8');
const main = fs.readFileSync(path.join(__dirname, '../clients/desktop/main.js'), 'utf8');
const plain = value => JSON.parse(JSON.stringify(value));     // objects made inside the vm context
const BLOCK = html.slice(html.indexOf('async function recoverAndRefresh()'), html.indexOf('// ---- reconnect flow: whatever it takes'));

function shell(over = {}) {
  const r = { toasts: [], calls: [], order: [], timers: [], storage: new Map(), autoplay: [], ...over };
  const ctx = {
    console, JSON, Map, Date, Promise, Error, encodeURIComponent,
    setTimeout: (fn, ms) => { r.timers.push({ fn, ms }); return r.timers.length; },
    toast: (text, ms) => r.toasts.push(String(text)),
    GBoxPipMedia: PIP,
    COMPACT: { on: false, sid: null, ...(over.COMPACT || {}) },
    EMB: { sid: null, authority: null, ...(over.EMB || {}) },
    S: { apiUrl: 'http://spark:8765' },
    GM: { auto: false, slot: 0 },
    $: () => ({ getAttribute: () => r.streamSrc || '' }),
    globalThis: { gboxStreamWatchdog: { sessionOf: src => (/sessions\/([^/]+)\//.exec(src) || [])[1] || null } },
    gboxState: async () => r.guest || {},
    chatContext: async () => r.chat || {},
    compactCurrentSid: () => r.compactSid || null,
    compactMedia: over.compactMedia || null,
    sessionStorage: { getItem: k => r.storage.has(k) ? r.storage.get(k) : null, setItem: (k, v) => r.storage.set(k, String(v)),
      removeItem: k => r.storage.delete(k) },
    compactApi: async (url, body, method) => {
      r.calls.push({ url, body, method }); r.order.push('api ' + url);
      if (r.api) return r.api(url, body, method);
      throw Error('unexpected ' + url);
    },
    recoverStreams: async () => { r.order.push('recoverStreams'); },
    reconnectFlow: { state: () => ({ done: r.flowDone !== false }) },
    reconnectRun: async options => { r.order.push('reconnectRun'); },
    clientRefresh: { refresh: async () => { r.order.push('refresh'); } },
  };
  vm.createContext(ctx);
  vm.runInContext(BLOCK, ctx);
  r.ctx = ctx;
  r.flush = () => new Promise(resolve => setImmediate(resolve));
  return r;
}

test('F3 in the PiP toggles the autobot of the shown stream through the control plane and toasts its answer', async () => {
  const media = { calls: 0, toggleAutobot: async () => { media.calls++; return { ok: true, running: true,
    message: 'Autobot started on Resident Evil 5 (lilspark): playbook: mercs_bot.' }; } };
  const r = shell({ COMPACT: { on: true, sid: 'w1-stale' }, compactMedia: media });
  r.streamSrc = 'http://spark:8765/api/sessions/w1-live/mjpeg'; r.compactSid = 'w1-live';
  await r.ctx.f3Autobot();
  assert.equal(media.calls, 1);
  assert.deepEqual(r.toasts, ['🤖 F3: asking the PC that runs this game…',
    '🤖 Autobot started on Resident Evil 5 (lilspark): playbook: mercs_bot.']);
  assert.equal(r.ctx.GM.auto, true);
});

test('F3 on a remote game shown in the gBox view asks that game\'s session, from this PC', async () => {
  const r = shell({ guest: { tab: 'Sessions', session: 'nuc-re4' },
    api: url => ({ id: 't1', state: 'succeeded', output: { action: 'started', running: true,
      message: 'Autobot started on Resident Evil 4 (i9-NUC).' } }) });
  await r.ctx.f3Autobot();
  assert.deepEqual(plain(r.calls[0]), { url: '/api/sessions/nuc-re4/autoplay', body: { op: 'toggle', source: 'F3' }, method: 'POST' });
  assert.equal(r.toasts.at(-1), '🤖 Autobot started on Resident Evil 4 (i9-NUC).');
});

test('F3 skips a docked game of another connection and says so when nothing is shown', async () => {
  const r = shell({ EMB: { sid: 'w9-local', authority: 'http://127.0.0.1:18765' }, guest: { session: 'w1-spark' },
    api: () => ({ id: 't', state: 'succeeded', output: { action: 'stopped', running: false, message: 'Autobot stopped: you have control.' } }) });
  await r.ctx.f3Autobot();
  assert.equal(r.calls[0].url, '/api/sessions/w1-spark/autoplay');
  const none = shell({});
  await none.ctx.f3Autobot();
  assert.equal(none.calls.length, 0);
  assert.match(none.toasts.at(-1), /^⚠ F3: no game is shown in this window/);
  const watching = shell({ EMB: { sid: 'pc2-mine', authority: null }, guest: { tab: 'Sessions', session: 'nuc-re4' },
    api: () => ({ id: 't', state: 'succeeded', output: { action: 'started', running: true, message: 'Autobot started on RE4 (i9-NUC).' } }) });
  await watching.ctx.f3Autobot();
  assert.equal(watching.calls[0].url, '/api/sessions/nuc-re4/autoplay', 'the session page open here, not the docked game');
  const docked = shell({ EMB: { sid: 'pc2-mine', authority: null }, guest: { tab: 'Home' },
    api: () => ({ id: 't', state: 'succeeded', output: { action: 'started', running: true, message: 'ok' } }) });
  await docked.ctx.f3Autobot();
  assert.equal(docked.calls[0].url, '/api/sessions/pc2-mine/autoplay');
});

test('F3 failures are toasted in the control plane\'s words and a second press waits for the first', async () => {
  let finish;
  const r = shell({ guest: { session: 'w1-x' }, api: () => new Promise((_, reject) => { finish = reject; }) });
  const first = r.ctx.f3Autobot();
  await r.flush();
  await r.ctx.f3Autobot();
  assert.match(r.toasts.at(-1), /still on its way/);
  finish(Error('409 {"detail":"lilspark (running Resident Evil 5) is offline, so the autobot can\'t be reached there right now."}'));
  await first;
  assert.equal(r.toasts.at(-1), "⚠ Autobot: lilspark (running Resident Evil 5) is offline, so the autobot can't be reached there right now.");
  assert.equal(r.calls.length, 1);
});

test('F5 asks the control plane to keep the bot driving before the client reload, then toasts what it did', async () => {
  const r = shell({ COMPACT: { on: true, sid: 'w1-merc' },
    api: url => ({ id: 'e1', state: 'succeeded', output: { action: 'started', kind: 'mercmode',
      message: 'Autobot back in control of Resident Evil 5 (lilspark).' } }) });
  r.streamSrc = 'http://spark:8765/api/sessions/w1-merc/mjpeg';
  await r.ctx.recoverAndRefresh();
  await r.flush();
  assert.deepEqual(r.order, ['api /api/sessions/w1-merc/autoplay/ensure', 'recoverStreams', 'refresh']);
  assert.deepEqual(plain(r.calls[0].body), { reason: 'F5' });
  assert.ok(r.toasts.includes('🤖 Autobot back in control of Resident Evil 5 (lilspark).'));
  assert.equal(r.storage.has('gbox.f5.bot'), false, 'the kept request id is cleared once its answer was shown');
});

test('F5 on the operator\'s own game says nothing about bots and still refreshes; a failed check is said', async () => {
  const own = shell({ COMPACT: { on: true, sid: 'w1-mine' },
    api: () => ({ id: 'e2', state: 'succeeded', output: { action: 'none', reason: 'No autobot was driving this game.' } }) });
  await own.ctx.recoverAndRefresh();
  await own.flush();
  assert.deepEqual(own.toasts, ['F5: reconnecting the stream…']);
  assert.equal(own.order.at(-1), 'refresh');
  const down = shell({ COMPACT: { on: true, sid: 'w1-mine' }, api: () => { throw Error('502 {"detail":"control plane restarting"}'); } });
  await down.ctx.recoverAndRefresh();
  assert.ok(down.toasts.includes('⚠ F5: the autobot could not be checked: control plane restarting'));
  assert.equal(down.order.at(-1), 'refresh');
});

test('the answer of an F5 check reaches the operator after the reload, once', async () => {
  const r = shell({ api: url => url === '/api/jobs/e3'
    ? { id: 'e3', state: 'succeeded', output: { action: 'restarted', message: 'The autobot on Resident Evil 4 (i9-NUC) had stopped reporting: restarted it.' } }
    : Error('unexpected') });
  r.storage.set('gbox.f5.bot', JSON.stringify({ id: 'e3', at: Date.now() }));
  const later = r.timers.find(t => t.ms === 2500);
  later.fn();
  for (let i = 0; i < 30 && r.storage.has('gbox.f5.bot'); i++) await new Promise(resolve => setTimeout(resolve, 100));
  assert.deepEqual(r.toasts, ['🤖 The autobot on Resident Evil 4 (i9-NUC) had stopped reporting: restarted it.']);
  assert.equal(r.storage.has('gbox.f5.bot'), false);
});

test('F5 and its reconnect flow send one check per game', async () => {
  const r = shell({ api: () => ({ id: 'e4', state: 'succeeded', output: { action: 'driving', message: 'The autobot is driving X.' } }) });
  await r.ctx.botEnsure('w1-merc');
  assert.equal(await r.ctx.botEnsure('w1-merc'), null);
  assert.equal(r.calls.filter(c => c.url.endsWith('/ensure')).length, 1);
  assert.equal(await r.ctx.botEnsure(null), null);
});

test('the F3 key reaches the autobot handler; the game keys still reach the game menu', () => {
  const start = html.indexOf('gbox.onHotkey?.(k => {');
  const code = html.slice(start, html.indexOf('});', start) + 3);
  const seen = [];
  const ctx = { gbox: { onHotkey: fn => { ctx.handler = fn; } }, f3Autobot: () => seen.push('f3'), recoverAndRefresh: () => seen.push('f5'),
    gameAction: a => seen.push('game:' + a), eyeStart: () => seen.push('eye'), viewAction: () => seen.push('view'), isFull: () => false };
  vm.runInNewContext(code, ctx);
  for (const k of ['autoplay', 'client-refresh', 'save', 'slot+', 'eyedropper']) ctx.handler(k);
  assert.deepEqual(seen, ['f3', 'f5', 'game:save', 'game:slot+', 'eye']);
  assert.match(main, /const GAME_KEYS = \{ F1: "replay", F2: "save", F3: "autoplay", F4: "load", F5: "client-refresh" \}/);
  assert.match(html, /if \(a === "autoplay"\) return await f3Autobot\(\);/, 'the menu\'s Take control is the same request');
});
