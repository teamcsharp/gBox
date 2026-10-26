const test = require('node:test'), assert = require('node:assert/strict');
const F = require('../clients/desktop/reconnect-flow.js');

function rig(over = {}) {
  let clock = 0;
  const calls = [], renders = [], memory = new Map();
  const r = { calls, renders, memory, mode: 'remote', remoteReady: true, pip: null, restarts: 0, reloads: 0, healthBy: {},
    mercmode: { hosts: [{ name: 'lilspark', online: true, settings: { enabled: true },
      current_run: { phase: 'playing', session_id: 'w1-s1', title: 'Resident Evil 5' } }] },
    health: { state: 'running', age_s: 0.1 }, ...over };
  r.io = {
    status: async () => ({ mode: r.mode, remote: { ready: r.remoteReady } }),
    restartSpark: async () => { r.restarts++; r.restartAt = clock; if (r.recoverOnRestart) r.remoteReady = true; },
    select: async mode => { calls.push(['select', mode]); r.mode = mode; },
    reload: async () => { r.reloads++; },
    remember: (k, v) => memory.set(k, v), forget: k => memory.delete(k), recall: k => memory.get(k),
    api: async (path, body) => {
      calls.push([path, body]);
      if (path === '/api/mercmode' && body) { r.mercmode.hosts[0].settings.enabled = body.enabled; if (r.startOnEnable)
        r.mercmode.hosts[0].current_run = { phase: 'playing', session_id: 'w1-new', title: 'Resident Evil 4' }; return r.mercmode; }
      if (path === '/api/mercmode') return JSON.parse(JSON.stringify(r.mercmode));
      if (path.endsWith('/stream/health')) return r.healthBy[decodeURIComponent(path.split('/')[3])] || r.health;
      if (path === '/api/jobs') { r.health = { state: 'running', age_s: 0.2 }; r.healthBy = {}; return { id: 'j' }; }
      throw Error('unexpected ' + path);
    },
    pickHost: data => F.pickHost(data, 'JAYBUILTFINALE'),
    pipSession: () => r.pip, pipEnter: async sid => { r.pip = sid; }, pipRestore: async () => { r.pip = null; },
    health: sid => r.io.api(`/api/sessions/${encodeURIComponent(sid)}/stream/health`),
    session: async sid => (r.sessions || {})[sid] || null,
    show: () => {},
  };
  r.ctl = F.create({ io: r.io, render: s => renders.push(s), sleep: async ms => { clock += ms; }, now: () => clock });
  r.elapsed = () => clock; r.advance = ms => { clock += ms; };
  return r;
}

test('a healthy Spark with MercMode playing goes straight to picture-in-picture', async () => {
  const r = rig();
  const out = await r.ctl.run();
  assert.equal(out.done, true); assert.equal(r.pip, 'w1-s1'); assert.equal(r.restarts, 0);
  assert.deepEqual(out.steps.map(s => s.status), ['ok', 'ok', 'ok', 'ok', 'ok']);
});

test('a window on This PC switches to the Spark and reloads, remembering to resume', async () => {
  const r = rig({ mode: 'local' });
  const out = await r.ctl.run();
  assert.deepEqual(r.calls[0], ['select', 'remote']); assert.equal(r.reloads, 1);
  assert.equal(r.memory.get(F.RESUME_KEY), '1'); assert.equal(out.done, false); assert.equal(r.pip, null);
  const again = await r.ctl.run();                                  // after the reload
  assert.equal(again.done, true); assert.equal(r.memory.has(F.RESUME_KEY), false);
});

test('a silent Spark is restarted once, then the flow continues', async () => {
  const r = rig({ remoteReady: false, recoverOnRestart: true });
  const out = await r.ctl.run();
  assert.equal(r.restarts, 1); assert.equal(out.done, true);
  assert.equal(r.restartAt, 60000);
  const s = rig({ remoteReady: false });
  const failed = await s.ctl.run();
  assert.equal(failed.done, false); assert.match(failed.error, /not answering/); assert.equal(failed.steps[0].status, 'err');
  assert.equal(s.restarts, 1); assert.equal(s.restartAt, 60000);
});

test('a planned service restart that recovers after 20-30 seconds never triggers another restart', async () => {
  for (const automatic of [false, true]) for (const recoveredAt of [20000, 30000]) {
    const r = rig({ remoteReady: false });
    r.io.status = async () => ({ mode: 'remote', remote: { ready: r.elapsed() >= recoveredAt } });
    const out = await r.ctl.run({ automatic });
    assert.equal(out.done, true); assert.equal(r.restarts, 0); assert.equal(r.pip, 'w1-s1');
    assert.equal(r.elapsed(), recoveredAt);
  }
});

test('automatic reconnect never restarts a shared service during a persistent outage', async () => {
  const r = rig({ remoteReady: false });
  for (const quiet of [true, false]) {
    const out = await r.ctl.run({ automatic: true, quiet });
    assert.equal(out.done, false); assert.match(out.error, /Automatic reconnect/);
    assert.equal(r.restarts, 0); assert.equal(r.calls.length, 0);
  }
  r.recoverOnRestart = true;
  const manual = await r.ctl.run({ quiet: true }); // quiet controls display, never operator intent
  assert.equal(manual.done, true); assert.equal(r.restarts, 1); assert.equal(r.restartAt, 180000);
});

test('launch and PiP polling mark automatic intent while manual retry and F5 retain operator intent', () => {
  const html = require('node:fs').readFileSync(require('node:path').join(__dirname, '../clients/desktop/index.html'), 'utf8');
  assert.match(html, /reconnectRun\(\{ quiet: !resume, automatic: true \}\)/);
  assert.match(html, /!st\.remote\.ready && COMPACT\.on\) \{\r?\n\s*const out = await reconnectRun\(\{ quiet: false, automatic: true \}\);/);
  assert.match(html, /\[data-rc-retry\]'\)\.onclick = \(\) => reconnectRun\(\{ quiet: false \}\)/);
  assert.match(html, /!reconnectFlow\.state\(\)\.done\) return reconnectRun\(\{ quiet: false \}\)/);
});

test('no running MercMode game: the flow only reconnects, never turns MercMode on or waits', async () => {
  const r = rig();
  r.mercmode.hosts[0].settings.enabled = false; r.mercmode.hosts[0].current_run = null;
  const out = await r.ctl.run();
  assert.equal(out.done, true); assert.equal(r.pip, null);
  assert.deepEqual(out.steps.map(s => s.id), ['spark', 'library']);
  assert.ok(!r.calls.some(([p, b]) => p === '/api/mercmode' && b));
});

test('a stale picture of a running MercMode game gets a new encoder', async () => {
  const r = rig({ health: { state: 'running', age_s: 40 } });
  const out = await r.ctl.run();
  assert.ok(r.calls.some(([p, b]) => p === '/api/jobs' && b.input.op === 'restart_stream'));
  assert.equal(out.done, true); assert.equal(r.pip, 'w1-s1');
});

test('the shown PC prefers this PC playing, then any PC playing, then the Spark', () => {
  const play = name => ({ name, online: true, current_run: { phase: 'playing', session_id: name + '-s' } });
  assert.equal(F.pickHost({ hosts: [play('i9-NUC'), play('JAYBUILTFINALE')] }, 'JAYBUILTFINALE').name, 'JAYBUILTFINALE');
  assert.equal(F.pickHost({ hosts: [{ name: 'lilspark', online: true }, play('i9-NUC')] }, 'x').name, 'i9-NUC');
  assert.equal(F.pickHost({ hosts: [{ name: 'lilspark', online: true }] }, 'x').name, 'lilspark');
  assert.equal(F.pickHost({ hosts: [] }, 'x'), null);
});

test('a MercMode status that times out is asked again instead of failing the flow', async () => {
  const r = rig(); let fails = 2; const api = r.io.api;
  r.io.api = async (path, body) => { if (path === '/api/mercmode' && !body && fails-- > 0) throw Error('The operation was aborted due to timeout'); return api(path, body); };
  const out = await r.ctl.run();
  assert.equal(out.done, true); assert.equal(r.pip, 'w1-s1');
});

test('an operator reconnect brings the MercMode game back with its autobot; automatic ones and failures never block', async () => {
  for (const automatic of [false, true]) {
    const r = rig(); const asked = [];
    r.io.ensureBot = async sid => { asked.push(sid); };
    const out = await r.ctl.run({ automatic });
    assert.equal(out.done, true); assert.equal(r.pip, 'w1-s1');
    assert.deepEqual(asked, automatic ? [] : ['w1-s1'], 'F5 / Try again only (operator 2026-10-26)');
  }
  const r = rig(); r.io.ensureBot = async () => { throw Error('control plane restarting'); };
  assert.equal((await r.ctl.run()).done, true);
  const idle = rig(); idle.mercmode.hosts[0].current_run = null; const asked = [];
  idle.io.ensureBot = async sid => { asked.push(sid); };
  await idle.ctl.run();
  assert.deepEqual(asked, [], 'no MercMode game: nothing to keep driving');
});

// operator 2026-10-26 (i9-NUC): the app watching the Spark's MercMode game in PiP was pulled into this PC's own "running"
// Mercenaries 3D session, whose worker had been offline for 43 h, and reloaded over and over without showing anything.
const html = require('node:fs').readFileSync(require('node:path').join(__dirname, '../clients/desktop/index.html'), 'utf8');
test('a PiP already showing a game is kept: the flow repairs that picture and never opens another host\'s run', async () => {
  for (const automatic of [false, true]) {
    const r = rig({ pip: 'spark-live' });
    r.healthBy = { 'spark-live': { state: 'running', age_s: 40 } };                                // its picture is stale
    r.mercmode.hosts.unshift({ name: 'JAYBUILTFINALE', online: true, settings: { enabled: true },   // this PC's own run: ignored
      current_run: { phase: 'playing', session_id: 'jay-own', title: 'Resident Evil 4' } });
    const out = await r.ctl.run({ automatic });
    assert.equal(out.done, true); assert.equal(r.pip, 'spark-live', 'the picture on screen is never replaced');
    assert.ok(r.calls.some(([p, b]) => p === '/api/jobs' && b.input.session_id === 'spark-live' && b.input.op === 'restart_stream'), 'the shown game gets the new encoder');
    assert.ok(!r.calls.some(([p]) => p === '/api/mercmode'), 'no other host is asked for');
    assert.equal(out.steps.find(s => s.id === 'mercmode').detail, 'Keeping the game already on screen');
    assert.equal(out.steps.find(s => s.id === 'pip').detail, 'Showing');
  }
});

test('only a PiP whose session ended gives way to the running MercMode game; an offline PC or no answer keeps it', async () => {
  const ended = rig({ pip: 'spark-old' }); ended.healthBy = { 'spark-old': { state: 'ended' } };
  assert.equal((await ended.ctl.run()).done, true); assert.equal(ended.pip, 'w1-s1');
  const offline = rig({ pip: 'nuc-game' }); offline.healthBy = { 'nuc-game': { state: 'running', worker_online: false, age_s: null } };
  assert.equal((await offline.ctl.run({ automatic: true })).done, true); assert.equal(offline.pip, 'nuc-game', 'a PC going offline never closes the PiP');
  const silent = rig({ pip: 'spark-live' }); const api = silent.io.api;
  silent.io.api = async (path, body) => { if (path.endsWith('/stream/health')) throw Error('timeout'); return api(path, body); };
  assert.equal((await silent.ctl.run()).done, true); assert.equal(silent.pip, 'spark-live');
});

test('a PiP MercMode parked for its next title (warm) gives way to that title on the same PC, never another PC\'s game', async () => {
  const r = rig({ pip: 'w1-old' });
  r.sessions = { 'w1-old': { session_id: 'w1-old', state: 'running', warm: true } };            // paused in the warm pool
  r.healthBy = { 'w1-old': { state: 'running', age_s: 0.1 } };
  r.mercmode.hosts = [
    { name: 'JAYBUILTFINALE', id: 'jay', online: true, settings: { enabled: true }, current_run: { phase: 'playing', session_id: 'jay-re4', title: 'Resident Evil 4' } },
    { name: 'lilspark', id: 'w1', online: true, settings: { enabled: true },
      current_run: { phase: 'playing', session_id: 'w1-s1', title: 'Resident Evil 5', mercmode_predecessor: { session_id: 'w1-old' } } }];
  r.io.pickHost = data => F.pickHost(data, 'i9-NUC');                                           // would pick the first PC playing: JAY
  const out = await r.ctl.run();
  assert.equal(out.done, true); assert.equal(r.pip, 'w1-s1', 'the same PC\'s next title, not JAYBUILTFINALE\'s game');
  assert.match(out.steps.find(s => s.id === 'mercmode').detail, /Resident Evil 5 on lilspark/);
  const playing = rig({ pip: 'w1-live' });                                                      // a playing (not parked) PiP stays
  playing.sessions = { 'w1-live': { session_id: 'w1-live', state: 'running' } };
  assert.equal((await playing.ctl.run()).done, true); assert.equal(playing.pip, 'w1-live');
  assert.match(html, /session: sid => sessionById\(sid\),/);
});

test('a MercMode run on a PC that is offline is never put on screen (i9-NUC\'s dead Mercenaries 3D)', async () => {
  const dead = { name: 'i9-NUC', online: false, settings: { enabled: true },
    current_run: { phase: 'playing', session_id: 'nuc-merc3d', title: 'Resident Evil: The Mercenaries 3D (USA)' } };
  assert.equal(F.pickHost({ hosts: [dead, { name: 'lilspark', online: true }] }, 'i9-NUC').name, 'lilspark', 'an offline host is never this PC\'s own');
  // the host row looks online (this PC's own local gBox) but the session's health says its worker is offline (#2870)
  const r = rig({ mercmode: { hosts: [{ ...dead, online: true }] } });
  r.io.pickHost = data => F.pickHost(data, 'i9-NUC');
  r.healthBy = { 'nuc-merc3d': { state: 'running', worker_online: false, age_s: null } };
  const out = await r.ctl.run();
  assert.equal(out.done, true); assert.equal(r.pip, null, 'nothing is opened');
  assert.ok(!r.calls.some(([p]) => p === '/api/jobs'), 'no encoder restart is sent to an offline PC');
  const note = out.steps.find(s => s.id === 'mercmode');
  assert.equal(note.status, 'err'); assert.match(note.detail, /on i9-NUC: that PC is offline, so there is nothing to show yet/);
});

test('the library switch never reloads a window with a PiP on it, and reloads at most once per failure', async () => {
  const shown = rig({ mode: 'local', pip: 'spark-live' });
  const out = await shown.ctl.run();
  assert.equal(shown.reloads, 0); assert.equal(out.done, true); assert.equal(shown.pip, 'spark-live');
  assert.ok(!shown.calls.some(([p]) => p === 'select'));
  assert.match(out.steps.find(s => s.id === 'library').detail, /Keeping the game on screen/);
  // no PiP: one reload; a window still on This PC's library right after it is not reloaded again
  const r = rig({ mode: 'local' });
  r.io.select = async mode => { r.calls.push(['select', mode]); };                    // the switch does not stick
  const first = await r.ctl.run(); assert.equal(r.reloads, 1); assert.equal(first.done, false);
  assert.equal(r.memory.get(F.RELOAD_KEY), '1'); assert.equal(r.memory.get(F.RESUME_KEY), '1');
  const again = await r.ctl.run();
  assert.equal(r.reloads, 1, 'no second reload for the same failure'); assert.equal(again.done, false);
  assert.equal(again.steps.find(s => s.id === 'library').status, 'err'); assert.match(again.error, /still on This PC's library/);
  r.advance(F.RELOAD_ONCE_MS + 1);                                                     // a new failure much later may reload once more
  await r.ctl.run(); assert.equal(r.reloads, 2);
  r.mode = 'remote'; const fixed = await r.ctl.run();                                  // on the Spark library: the stamps are gone
  assert.equal(fixed.done, true); assert.equal(r.memory.has(F.RELOAD_KEY), false); assert.equal(r.memory.has(F.RESUME_KEY), false);
  const refused = rig({ mode: 'local' });
  refused.io.select = async () => { throw Error('Keep the current game in its own connection.'); };
  const held = await refused.ctl.run();
  assert.equal(refused.reloads, 0); assert.equal(held.steps.find(s => s.id === 'library').status, 'err'); assert.match(held.error, /Keep the current game/);
});

test('the automatic poll backs off from 5 s to a minute, resets on success, and never reloads the client', () => {
  assert.deepEqual([0, 1, 2, 3, 4, 9, -1, NaN, undefined].map(F.backoff), [5000, 10000, 20000, 40000, 60000, 60000, 5000, 5000, 5000]);
  const watch = html.slice(html.indexOf('const RECONNECT_WATCH ='), html.indexOf('setTimeout(reconnectWatch, RECONNECT_WATCH.every);'));
  assert.match(watch, /RECONNECT_WATCH\.failures = out\?\.done \? 0 : RECONNECT_WATCH\.failures \+ 1/);
  assert.match(watch, /GBoxReconnectFlow\.backoff\(RECONNECT_WATCH\.failures - 1\)/);
  assert.doesNotMatch(watch, /location\.reload|clientRefresh\.refresh|clientReload/);
  assert.doesNotMatch(html, /setInterval\(async \(\) => \{\r?\n\s*const st = await gbox\.connectionStatus/);   // the old 15 s interval is gone
  // the shell gives the flow the session health it keeps or skips a game by, and the reload stamp
  assert.match(html, /health: sid => compactApi\(`\/api\/sessions\/\$\{encodeURIComponent\(sid\)\}\/stream\/health`, undefined, 'GET'\)/);
  assert.match(html, /recall: k => \{ try \{ return sessionStorage\.getItem\(k\); \} catch \{ return null; \} \}/);
});
