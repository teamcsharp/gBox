// The web client's Reset / Restart / Hard reset (clients/web/index.html): one server operation, never "stop, then hope
// the relaunch comes". 2026-10-13: Reset on Dolphin ran session_op stop_game and the relaunch never followed. The
// functions are taken from the page and run against stubs (no browser, no game).
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const web = fs.readFileSync(path.join(__dirname, '../clients/web/index.html'), 'utf8');
const desktop = fs.readFileSync(path.join(__dirname, '../clients/desktop/index.html'), 'utf8');
function fn(name) {                                       // one top-level function of the page, by brace matching
  const start = web.search(new RegExp(`^(async )?function ${name}\\(`, 'm'));
  assert.ok(start >= 0, name);
  let depth = 0, i = web.indexOf('{', start);
  for (; i < web.length; i++) { if (web[i] === '{') depth++; else if (web[i] === '}' && --depth === 0) break; }
  return web.slice(start, i + 1);
}

function page({ jobs, rpcOk = false, sessions }) {
  const calls = [], body = { html: '' }, followed = [], played = [];
  const elements = {};
  const el = id => elements[id] ||= { textContent: '', onclick: null, remove() { delete elements[id]; body.html = ''; } };
  const ctx = {
    calls, followed, played, body, elements, playing: 'w-live', tok: 't', console,
    setTimeout: (f, ms) => (ms > 1000 ? 0 : f()), Promise,                // the hard reset's 5 s disarm timer never fires here
    esc: s => String(s ?? ''), modReapply: () => calls.push(['modReapply']),
    followSession: (a, b) => followed.push([a, b]), play: (...a) => played.push(a),
    $: sel => (sel.startsWith('#') ? (sel === '#resetfail' && !body.html ? null : el(sel.slice(1))) : null),
    document: { getElementById: id => (id === 'resetfail' && body.html ? el(id) : null),
                body: { insertAdjacentHTML: (_w, h) => { body.html = h; } } },
    fetch: async (url, init) => { calls.push(['fetch', url, JSON.parse(init.body)]); return { ok: rpcOk }; },
    api: async (url, b) => {
      calls.push(['api', url, b]);
      if (url === '/api/sessions') return sessions;
      if (url.endsWith('/reset')) return jobs.shift();
      if (url.startsWith('/api/jobs/')) return jobs.shift();
      throw new Error('unexpected ' + url);
    },
    runJob: async b => { calls.push(['runJob', b]); return { state: 'succeeded' }; },
    bootSet: () => {}, localStorage: { removeItem() {} },
  };
  vm.createContext(ctx);
  const arming = web.match(/^const HARD_RESET_ARM_MS = .*\r?\nlet hardResetArmed = .*$/m)[0];   // #301: Ctrl+click twice
  vm.runInContext([arming, ...['hardResetArm', 'resetJob', 'resetFailed', 'hardReset', 'restartGame', 'resetGame'].map(fn)].join('\n'), ctx);
  return ctx;
}
const LIVE = { session_id: 'w-live', game_id: 'ts', state: 'running', mod: 'tts_sonic_full_cast', detail: { worker_name: 'JAYBUILTFINALE' } };
const plain = x => JSON.parse(JSON.stringify(x));            // objects made inside the vm context
const btn = () => ({ disabled: false, style: {}, title: '', querySelector: () => null });

test('Reset with no live-channel reset: one /reset job, the view follows the relaunched copy; no stop_game', async () => {
  const p = page({ sessions: [LIVE], jobs: [{ id: 'j1', state: 'running' },
    { id: 'j1', state: 'succeeded', output: { session_id: 'w-new', mode: 'relaunch' } }] });
  const b = btn();
  await p.resetGame('w-live', b, false);
  assert.deepEqual(plain(p.calls.filter(c => c[0] === 'api' && c[1].endsWith('/reset'))), [['api', '/api/sessions/w-live/reset', { mode: 'reset', intent: 'reset' }]]);
  assert.ok(!JSON.stringify(p.calls).includes('stop_game'), 'never stops the game itself');
  assert.deepEqual(plain(p.followed), [['w-live', 'w-new']]);
  assert.match(b.title, /Reset ✓ \(relaunched: same game and mod\)/);
});

test('Reset over the live channel stays instant and in place', async () => {
  const p = page({ sessions: [LIVE], jobs: [], rpcOk: true });
  await p.resetGame('w-live', btn(), false);
  assert.deepEqual(p.calls.map(c => c[0]), ['api', 'fetch', 'modReapply']);
});

test('a failed reset says so loudly and offers Play again with the same game, mod and PC', async () => {
  const p = page({ sessions: [LIVE], jobs: [{ id: 'j1', state: 'failed', error: 'MGS could not be relaunched (Dolphin exited 1). Your game is still running as it was.' }] });
  const b = btn();
  await p.resetGame('w-live', b, false);
  assert.match(b.title, /^Reset failed: .*still running as it was/);
  assert.match(p.body.html, /role="alert"/); assert.match(p.body.html, /Reset failed\.<\/b> <span>MGS could not be relaunched/);
  assert.match(p.body.html, /id="rf_play"[^>]*>Play again</);
  p.elements.rf_play.onclick();
  assert.deepEqual(plain(p.played), [['ts', 'JAYBUILTFINALE', false, { disc: 'tts_sonic_full_cast', slot: '' }]]);
});

test('Hard reset and Restart go through the same server operation (hard reset with its intent)', async () => {
  let p = page({ sessions: [LIVE], jobs: [{ id: 'h', state: 'succeeded', output: { session_id: 'w-orig', mode: 'hard' } }] });
  const hb = btn();
  await p.hardReset('w-live', hb);                                   // the first Ctrl+click only arms it (#301)
  assert.equal(p.calls.length, 0); assert.match(hb.title, /armed/);
  await p.hardReset('w-live', hb);                                   // the second one, within 5 s, runs it
  assert.deepEqual(plain(p.calls.find(c => c[1]?.endsWith?.('/reset'))), ['api', '/api/sessions/w-live/reset', { mode: 'hard', intent: 'hard_reset' }]);
  assert.deepEqual(plain(p.followed), [['w-live', 'w-orig']]);
  p = page({ sessions: [LIVE], jobs: [{ id: 'r', state: 'succeeded', output: { session_id: 'w-r', mode: 'relaunch' } }] });
  await p.restartGame('w-live');
  assert.deepEqual(plain(p.calls.find(c => c[1]?.endsWith?.('/reset'))), ['api', '/api/sessions/w-live/reset', { mode: 'restart', intent: 'restart' }]);
});

test('no "stop, then relaunch" path is left in the clients', () => {
  for (const name of ['resetGame', 'hardReset', 'restartGame', 'examineRelaunch'])
    assert.ok(!fn(name).includes('stop_game'), name + ' must not stop the game itself');
  assert.match(web, /await restartGame\(el\.dataset\.sid\); done\("Restarted with the new settings ✓"\)/, 'graphics: Save & restart');
  assert.match(fn('examineRelaunch'), /\/swap`, \{ mod: [^}]*keep_state: true \}/, 'Examine 3D relaunch = one state-keeping swap');
  // the debugger copy is launched first; this copy is stopped only after it runs
  const dbg = web.slice(web.indexOf('rl.onclick = async'), web.indexOf('const act = async (op, args)'));
  assert.ok(dbg.indexOf('/launch?node=linux&debug=true') < dbg.indexOf('stop_game'));
  assert.match(desktop, /q: "Restart the game", act: \(\) => EMB\.sid && document\.querySelector\("#wv"\)\?\.executeJavaScript\(\s*`restartGame\(/);
  assert.ok(!/[^\r]\n/.test(web) && !/[^\r]\n/.test(desktop), 'CRLF line endings kept');
});
