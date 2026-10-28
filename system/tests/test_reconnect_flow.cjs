const test = require('node:test'), assert = require('node:assert/strict'), vm = require('node:vm');
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
  assert.match(html, /\[data-rc-retry\]'\)\.onclick = \(\) => recoverAndRefresh\(\);/, 'Try again is the F5 recovery');
  assert.match(html, /async function recoverAndRefresh\(\) \{ return f5Recover\(null\); \}/);
  assert.match(html, /const out = await reconnectRun\(\{ quiet: false, f5: true, resumed \}\);/);
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

test('a run whose picture never comes back is asked again and the new session is shown (right after a restart)', async () => {
  // operator 2026-10-26: "gbox reloaded to this" - the status still named Resident Evil 5's dead session; RE4 already played
  const r = rig({ healthBy: { 'w1-s1': { state: 'running', age_s: 99 } } });
  r.io.api = (inner => async (path, body) => {
    if (path === '/api/jobs') { r.calls.push([path, body]); return { id: 'j' }; }          // a new encoder: still no picture
    const out = await inner(path, body);
    if (path === '/api/mercmode' && r.calls.filter(c => c[0] === '/api/mercmode').length > 1)
      out.hosts[0].current_run = { phase: 'playing', session_id: 'w2-re4', title: 'Resident Evil 4' };
    return out;
  })(r.io.api);
  const out = await r.ctl.run();
  assert.equal(r.pip, 'w2-re4');
  assert.equal(out.steps.find(s => s.id === 'mercmode').detail, 'Resident Evil 4 on lilspark');
  assert.equal(out.steps.find(s => s.id === 'stream').status, 'ok');
});

// ---- F5: one deterministic recovery (operator 2026-10-26: "when i encounter issues. I just want to press F5 reconnect it
// to the source and reboot the stream and build and update the gbox app and get the pip stream back autoplaying seamlessly")
function f5rig(over = {}) {
  const r = rig(over);
  Object.assign(r, { asked: [], switched: [], views: [], applied: [], marks: [], shows: [], updates: 0, reconnected: 0,
    plan: { reload: false, status: 'ok', detail: 'Up to date with GitHub main (a5cbf58)' } });
  r.mercmode.hosts[0].id = 'w1';
  Object.assign(r.io, {
    show: on => r.shows.push(on),
    workerName: () => 'JAYBUILTFINALE',
    update: async () => { r.updates++; return r.plan; },
    applyUpdate: async info => { r.applied.push(info); return r.applyResult; },
    f5Mark: info => r.marks.push(info),
    ownGame: async () => r.own || null,
    shownSession: async () => (r.shown === undefined ? r.pip : r.shown),
    repairTarget: async sid => sid,
    pipSwitch: async (from, sid) => { r.switched.push([from, sid]); r.pip = sid; return true; },
    reconnectPicture: () => { r.reconnected++; },
    ensureBot: async sid => { r.asked.push(sid); return r.botJob || { id: 'e1', state: 'succeeded',
      output: { action: 'driving', message: 'The autobot is driving Resident Evil 5 (lilspark).' } }; },
    jobResult: async (job, ms) => (r.botDone ? r.botDone(job, ms) : job),
    mainFollow: async sid => { r.views.push(sid); return 'shown'; },
    settleView: async () => { r.settled = (r.settled || 0) + 1; },
  });
  return r;
}
const detail = (out, id) => out.steps.find(s => s.id === id)?.detail;

test('F5 runs every step in order well within 45 s: update, Spark, library, MercMode\'s game, live picture, PiP, autobot, main window', async () => {
  const r = f5rig();
  const out = await r.ctl.run({ f5: true });
  assert.equal(out.done, true); assert.equal(out.f5, true);
  assert.deepEqual(out.steps.map(s => s.id), ['update', 'spark', 'library', 'mercmode', 'stream', 'pip', 'bot', 'view']);
  assert.ok(out.steps.every(s => s.status === 'ok'), JSON.stringify(out.steps));
  assert.equal(r.pip, 'w1-s1'); assert.deepEqual(r.asked, ['w1-s1']); assert.deepEqual(r.views, ['w1-s1']);
  assert.equal(detail(out, 'update'), 'Up to date with GitHub main (a5cbf58)');
  assert.equal(detail(out, 'mercmode'), 'Resident Evil 5 on lilspark');
  assert.equal(detail(out, 'bot'), 'The autobot is driving Resident Evil 5 (lilspark).');
  assert.equal(detail(out, 'view'), 'Showing it in Sessions');
  assert.deepEqual(r.shows, [true, false], 'the dialog shows every step, then leaves');
  assert.ok(r.elapsed() < 45000, `${r.elapsed()} ms`);
  assert.equal(r.restarts, 0); assert.equal(r.settled, 1, 'a saved view being restored never undoes the F5');
  assert.equal(F.summary(out), 'Resident Evil 5 on lilspark · Live · The autobot is driving Resident Evil 5 (lilspark).');
});

test('F5 with an update reloads once, then goes on from the Spark without asking for the update again', async () => {
  const r = f5rig(); r.advance(1000);
  r.plan = { reload: true, status: 'ok', detail: 'Pulled 3 new commits from GitHub main (a5cbf58 → 1234567)' };
  const first = await r.ctl.run({ f5: true });
  assert.equal(first.done, false); assert.equal(r.applied.length, 1);
  assert.deepEqual(r.applied[0], { started: 1000, update: { status: 'ok', detail: 'Pulled 3 new commits from GitHub main (a5cbf58 → 1234567)' } });
  assert.match(first.steps[0].detail, /: reloading gBox…$/);
  assert.equal(r.pip, null); assert.deepEqual(r.asked, []); assert.equal(r.calls.length, 0, 'nothing else ran before the reload');
  r.advance(5000);                                                       // the window reloaded: F5_KEY carries this F5
  const after = await r.ctl.run({ f5: true, resumed: JSON.parse(JSON.stringify(r.applied[0])) });
  assert.equal(after.done, true); assert.equal(r.updates, 1, 'the update is not checked twice');
  assert.equal(after.steps[0].detail, 'Pulled 3 new commits from GitHub main (a5cbf58 → 1234567); gBox reloaded');
  assert.equal(r.pip, 'w1-s1'); assert.deepEqual(r.asked, ['w1-s1']);
  // a reload that never came: the F5 goes on with the current version and says so
  const stuck = f5rig(); stuck.plan = r.plan; stuck.applyResult = false;
  const out = await stuck.ctl.run({ f5: true });
  assert.equal(out.done, true); assert.equal(stuck.pip, 'w1-s1');
  assert.equal(out.steps[0].status, 'warn'); assert.match(out.steps[0].detail, /the reload did not happen/);
  // a failed update check never stops the recovery
  const broken = f5rig(); broken.io.update = async () => { throw Error('git is not installed'); };
  const went = await broken.ctl.run({ f5: true });
  assert.equal(went.done, true); assert.equal(went.steps[0].status, 'warn'); assert.match(went.steps[0].detail, /git is not installed/);
});

test('F5 moves a PiP showing another game to MercMode\'s current game in place; an automatic reconnect keeps it', async () => {
  for (const [pip, sessions, why] of [
    ['w1-dead', { 'w1-dead': { session_id: 'w1-dead', state: 'ended' } }, 'the session a service restart ended'],
    ['w1-parked', { 'w1-parked': { session_id: 'w1-parked', state: 'running', warm: true } }, 'a paused warm-pool game'],
    ['nuc-re4', { 'nuc-re4': { session_id: 'nuc-re4', state: 'running' } }, 'another PC\'s game']]) {
    const r = f5rig({ pip }); r.sessions = sessions;
    const out = await r.ctl.run({ f5: true });
    assert.equal(out.done, true, why); assert.equal(r.pip, 'w1-s1', why);
    assert.deepEqual(r.switched, [[pip, 'w1-s1']], why);
    assert.equal(detail(out, 'pip'), 'Switched the PiP to it'); assert.deepEqual(r.views, ['w1-s1'], why);
  }
  const auto = rig({ pip: 'nuc-re4' }); auto.sessions = { 'nuc-re4': { session_id: 'nuc-re4', state: 'running' } };
  assert.equal((await auto.ctl.run({ automatic: true })).done, true); assert.equal(auto.pip, 'nuc-re4');
});

// operator 2026-10-27: F5 ended inert on "Error invoking remote method 'compact:view': Error: Game-window helper timed out":
// the in-place move lost a race with the PiP's own follower, and closing and reopening the PiP needed the slow helper
test('F5 moves the PiP again from where its own follower put it, and never closes it for that', async () => {
  const r = f5rig({ pip: 'w1-dead' }); r.sessions = { 'w1-dead': { session_id: 'w1-dead', state: 'ended' } };
  let restores = 0; r.io.pipRestore = async () => { restores++; r.pip = null; };
  r.io.pipSwitch = async (from, sid) => {
    r.switched.push([from, sid]);
    if (r.switched.length === 1) { r.pip = 'w1-warm'; return false; }       // the continuity poll moved it meanwhile
    r.pip = sid; return true;
  };
  const out = await r.ctl.run({ f5: true });
  assert.equal(out.done, true); assert.equal(r.pip, 'w1-s1'); assert.equal(restores, 0);
  assert.deepEqual(r.switched, [['w1-dead', 'w1-s1'], ['w1-warm', 'w1-s1']]);
  assert.equal(detail(out, 'pip'), 'Switched the PiP to it');
  // the follower got there first: nothing more to move
  const first = f5rig({ pip: 'w1-dead' }); first.sessions = r.sessions;
  first.io.pipSwitch = async (from, sid) => { first.switched.push([from, sid]); first.pip = sid; return false; };
  assert.equal((await first.ctl.run({ f5: true })).done, true); assert.equal(first.pip, 'w1-s1');
  assert.deepEqual(first.switched, [['w1-dead', 'w1-s1']]);
  // a PiP that could not be moved or closed says so on its step, with what to do
  const stuck = f5rig({ pip: 'w1-dead' }); stuck.sessions = r.sessions;
  stuck.io.pipSwitch = async (from, sid) => { stuck.switched.push([from, sid]); return false; };
  stuck.io.pipRestore = async () => { throw Error("Error invoking remote method 'compact:view': Error: Game-window helper timed out; the current dock was preserved"); };
  const failed = await stuck.ctl.run({ f5: true });
  assert.equal(stuck.switched.length, 3); assert.equal(failed.done, false);
  assert.equal(failed.steps.find(s => s.id === 'pip').status, 'err');
  assert.match(failed.error, /^The picture-in-picture could not move to it \(.*helper timed out.*\)\. Press F5 again\.$/);
});

test('F5 keeps the operator\'s own game on this PC: no other game, the main window untouched, its stream still repaired', async () => {
  const r = f5rig({ pip: 'jay-mine' }); r.own = { sid: 'jay-mine', native: false };
  r.healthBy = { 'jay-mine': { state: 'running', age_s: 30 } };
  const out = await r.ctl.run({ f5: true });
  assert.equal(out.done, true); assert.equal(r.pip, 'jay-mine'); assert.deepEqual(r.switched, []); assert.deepEqual(r.views, []);
  assert.equal(detail(out, 'mercmode'), 'Your own game on this PC stays on screen');
  assert.ok(r.calls.some(([p, b]) => p === '/api/jobs' && b.input.session_id === 'jay-mine' && b.input.op === 'restart_stream'));
  assert.equal(detail(out, 'pip'), 'Keeping your game on screen'); assert.equal(r.reconnected, 1);
  assert.deepEqual(r.asked, ['jay-mine']); assert.ok(!out.steps.some(s => s.id === 'view'));
  // a native window (docked here, or a local PiP): no stream to reboot, the window stays as it is
  const n = f5rig(); n.own = { sid: 'jay-native', native: true };
  const docked = await n.ctl.run({ f5: true });
  assert.equal(docked.done, true); assert.ok(!n.calls.some(([p]) => p === '/api/jobs')); assert.equal(n.pip, null);
  assert.equal(detail(docked, 'stream'), 'Shown from this PC directly (no stream)');
  assert.equal(detail(docked, 'pip'), 'Your game stays where it is');
  // a MercMode game running on this PC is not the operator's own: F5 shows MercMode's current game
  const m = f5rig({ pip: 'w1-old' }); m.own = { sid: 'w1-old' };
  m.mercmode.hosts[0].current_run.mercmode_predecessor = { session_id: 'w1-old' };
  await m.ctl.run({ f5: true });
  assert.equal(m.pip, 'w1-s1');
});

test('F5 shows MercMode\'s current game only: never a game of the warm pool, an ended session or an offline PC\'s', async () => {
  // the status still names a parked (warm) game, then one that just ended, then the live game: F5 waits for the live one
  const r = f5rig();
  const stages = [
    { warm: [{ title: 're4', session_id: 'w1-s1', state: 'ready' }], run: { phase: 'playing', session_id: 'w1-s1', title: 'Resident Evil 4' } },
    { warm: [], run: { phase: 'playing', session_id: 'w1-gone', title: 'Resident Evil 5' } },
    { warm: [], run: { phase: 'playing', session_id: 'w1-live', title: 'Resident Evil 5' } }];
  r.sessions = { 'w1-gone': { session_id: 'w1-gone', state: 'ended' } };
  let reads = 0;
  r.io.api = (inner => async (path, body) => {
    if (path === '/api/mercmode') { const s = stages[Math.min(reads++, stages.length - 1)]; Object.assign(r.mercmode.hosts[0], { warm: s.warm, current_run: s.run }); }
    return inner(path, body);
  })(r.io.api);
  const out = await r.ctl.run({ f5: true });
  assert.equal(out.done, true); assert.equal(r.pip, 'w1-live'); assert.equal(detail(out, 'mercmode'), 'Resident Evil 5 on lilspark');
  assert.ok(r.renders.some(s => /^MercMode is switching titles: loading Resident Evil/.test(s.steps.find(x => x.id === 'mercmode')?.detail || '')));
  // the run of a PC that is offline: nothing is shown, and the step says what to do
  const off = f5rig(); off.sessions = { 'w1-s1': { session_id: 'w1-s1', state: 'running', worker_online: false } };
  const dead = await off.ctl.run({ f5: true });
  assert.equal(off.pip, null); assert.ok(!off.calls.some(([p]) => p === '/api/jobs'));
  assert.equal(dead.done, false); assert.match(dead.error, /that PC is offline.*Relaunch its worker, then press F5/);
  assert.equal(off.shows.at(-1), true, 'the dialog stays up with what to do');
  // an offline PC's row is passed over for an online PC's game
  const two = f5rig();
  two.mercmode.hosts.unshift({ name: 'i9-NUC', id: 'nuc', online: false, settings: { enabled: true },
    current_run: { phase: 'playing', session_id: 'nuc-merc', title: 'Resident Evil 4' } });
  await two.ctl.run({ f5: true }); assert.equal(two.pip, 'w1-s1');
});

test('F5 between titles waits for the next title and follows it; a long boot is left to the PiP\'s own transition', async () => {
  const r = f5rig({ pip: 'w1-old' });
  r.mercmode.hosts[0].current_run = { phase: 'launching', title: 'Resident Evil 4', mercmode: { title: 're4' }, mercmode_predecessor: { session_id: 'w1-old' } };
  r.io.api = (inner => async (path, body) => {
    if (path === '/api/mercmode' && r.elapsed() >= 10000)
      r.mercmode.hosts[0].current_run = { phase: 'starting', session_id: 'w1-re4', title: 'Resident Evil 4', mercmode: { title: 're4' } };
    return inner(path, body);
  })(r.io.api);
  const out = await r.ctl.run({ f5: true });
  assert.equal(out.done, true); assert.equal(r.pip, 'w1-re4'); assert.deepEqual(r.switched, [['w1-old', 'w1-re4']]);
  assert.ok(r.elapsed() < 45000, `${r.elapsed()} ms`);
  const slow = f5rig({ pip: 'w1-old' });
  slow.mercmode.hosts[0].current_run = { phase: 'launching', title: 'Resident Evil 5', mercmode: { title: 're5' } };
  const late = await slow.ctl.run({ f5: true });
  assert.equal(late.done, true); assert.equal(slow.pip, 'w1-old', 'the PiP keeps its game; its transition follows the boot');
  assert.equal(late.steps.find(s => s.id === 'mercmode').status, 'warn');
  assert.match(detail(late, 'mercmode'), /^Resident Evil 5 is still loading on lilspark: the PiP follows it when it plays/);
  assert.deepEqual(slow.asked, []); assert.ok(slow.elapsed() >= F.TITLE_WAIT_MS);
});

test('F5: a picture not fresh within 3 s gets a new encoder and a new connection, then a fresh frame', async () => {
  const r = f5rig({ pip: 'w1-s1', health: { state: 'running', age_s: 40 } });
  r.io.api = (inner => async (path, body) => { if (path === '/api/jobs') r.encoderAt = r.elapsed(); return inner(path, body); })(r.io.api);
  const out = await r.ctl.run({ f5: true });
  assert.equal(out.done, true);
  assert.deepEqual(r.calls.find(([p]) => p === '/api/jobs')[1], { tool: 'session_op', agent_use: false, require_worker: 'w1',
    input: { session_id: 'w1-s1', op: 'restart_stream', args: {} } });
  assert.equal(r.encoderAt, 3000, 'after a 3 s look');
  assert.equal(detail(out, 'stream'), 'Live again (stream rebooted)'); assert.equal(r.reconnected, 1);
  const live = f5rig({ pip: 'w1-s1' }); await live.ctl.run({ f5: true });
  assert.ok(!live.calls.some(([p]) => p === '/api/jobs'), 'a fresh picture keeps its encoder'); assert.equal(live.reconnected, 0);
});

test('a failed F5 step keeps the dialog up with what to do; the F5 still brings the game, its autobot and the main window', async () => {
  const r = f5rig({ health: { state: 'running', age_s: 99 } });
  r.io.api = (inner => async (path, body) => { if (path === '/api/jobs') { r.calls.push([path, body]); return { id: 'j' }; } return inner(path, body); })(r.io.api);
  const out = await r.ctl.run({ f5: true });
  assert.equal(out.done, false); assert.equal(r.shows.at(-1), true);
  assert.match(out.error, /^Still no fresh picture after a new encoder.*Press F5 again; if it stays frozen, use Report & fix/);
  assert.equal(r.pip, 'w1-s1'); assert.deepEqual(r.asked, ['w1-s1']); assert.deepEqual(r.views, ['w1-s1']);
  assert.ok(r.elapsed() < 45000, `${r.elapsed()} ms`);
});

test('F5 takes over an automatic reconnect in progress; the older run never writes into the F5 dialog', async () => {
  const r = f5rig(); let ready = false;
  r.io.status = async () => ({ mode: 'remote', remote: { ready } });
  const auto = r.ctl.run({ automatic: true, quiet: true });
  ready = true;
  const out = await r.ctl.run({ f5: true });
  assert.equal(out.done, true); assert.equal(r.pip, 'w1-s1'); assert.deepEqual(r.asked, ['w1-s1']);
  assert.equal((await auto).superseded, true);
  assert.equal(r.renders.at(-1).f5, true); assert.ok(r.renders.filter(s => !s.f5).every(s => s.steps.length === 5));
  // a second F5, or an automatic reconnect, during an F5 joins it
  const s = f5rig(); const a = s.ctl.run({ f5: true }), b = s.ctl.run({ f5: true }), c = s.ctl.run({ automatic: true });
  assert.equal(a, b); assert.equal(a, c); await a; assert.equal(s.updates, 1);
});

test('F5 with no MercMode game repairs the game on screen and never mentions MercMode', async () => {
  const r = f5rig({ pip: 'w9-other' });
  r.mercmode.hosts[0].current_run = null; r.mercmode.hosts[0].settings.enabled = false;
  r.healthBy = { 'w9-other': { state: 'running', age_s: 50 } };
  const out = await r.ctl.run({ f5: true });
  assert.equal(out.done, true);
  assert.deepEqual(out.steps.map(s => s.id), ['update', 'spark', 'library', 'stream', 'pip', 'bot']);
  assert.ok(r.calls.some(([p, b]) => p === '/api/jobs' && b.input.session_id === 'w9-other'));
  assert.equal(r.pip, 'w9-other'); assert.deepEqual(r.switched, []); assert.deepEqual(r.asked, ['w9-other']); assert.deepEqual(r.views, []);
  const idle = f5rig(); idle.mercmode.hosts[0].current_run = null;
  const quiet = await idle.ctl.run({ f5: true });
  assert.equal(quiet.done, true); assert.deepEqual(quiet.steps.map(s => s.id), ['update', 'spark', 'library']);
});

test('an F5 that switches this window to the Spark library goes on after that reload as the F5', async () => {
  const r = f5rig({ mode: 'local' });
  const out = await r.ctl.run({ f5: true });
  assert.equal(out.done, false); assert.equal(r.reloads, 1);
  assert.deepEqual(r.marks, [{ started: 0, update: { status: 'ok', detail: 'Up to date with GitHub main (a5cbf58)' } }]);
});

test('F5 shows the autobot\'s answer; a slow check is left to its toast, a MercMode game left without its bot is flagged', async () => {
  const slow = f5rig(); slow.botJob = { id: 'e9', state: 'running', progress: { msg: 'Asking lilspark whether the autobot runs' } };
  slow.botDone = async (job, ms) => { assert.equal(ms, 15000); throw Error('The autobot check is still running; check the task list.'); };
  const a = await slow.ctl.run({ f5: true });
  assert.equal(a.done, true); assert.equal(detail(a, 'bot'), 'Still checking; its answer pops up when it is done');
  assert.ok(slow.renders.some(s => s.steps.find(x => x.id === 'bot')?.detail === 'Asking lilspark whether the autobot runs'));
  const off = f5rig(); off.botJob = { id: 'e8', state: 'succeeded', output: { action: 'none',
    reason: 'You took over with the controller, so the autobot stays off. Press F3 to hand it back.' } };
  const b = await off.ctl.run({ f5: true });
  assert.equal(b.done, true); assert.equal(b.steps.find(s => s.id === 'bot').status, 'warn'); assert.match(detail(b, 'bot'), /^You took over/);
  const down = f5rig(); down.io.ensureBot = async () => { throw Error('control plane restarting'); };
  const c = await down.ctl.run({ f5: true });
  assert.equal(c.done, false); assert.match(detail(c, 'bot'), /could not be checked \(control plane restarting\)\. Press F3/);
  assert.deepEqual(down.views, ['w1-s1'], 'the main window still follows');
});

test('the update plan reloads once for anything new and says why it did not', () => {
  const base = { renderer: 'r1', remote: 'm1', runtime: 'x1', restart: false };
  const pulled = { state: 'updated', detail: 'Pulled 2 new commits from GitHub main (aaaaaaa → bbbbbbb)', restart: false };
  assert.deepEqual(F.updatePlan({ pull: pulled, baseline: base, latest: { ...base, renderer: 'r2' } }),
    { reload: true, status: 'ok', detail: 'Pulled 2 new commits from GitHub main (aaaaaaa → bbbbbbb)' });
  const current = { state: 'current', detail: 'Up to date with GitHub main (aaaaaaa)' };
  assert.deepEqual(F.updatePlan({ pull: current, baseline: base, latest: base }), { reload: false, status: 'ok', detail: 'Up to date with GitHub main (aaaaaaa)' });
  let p = F.updatePlan({ pull: current, baseline: base, latest: { ...base, remote: 'm2' } });      // the Spark's client changed
  assert.equal(p.reload, true); assert.equal(p.detail, 'Up to date with GitHub main (aaaaaaa); the Spark serves a newer gBox client');
  p = F.updatePlan({ pull: current, baseline: base, latest: { ...base, renderer: 'r2' } });         // files changed on disk
  assert.equal(p.reload, true); assert.match(p.detail, /newer app files are on this PC/);
  p = F.updatePlan({ pull: { state: 'skipped', detail: 'This PC\'s copy is on branch re4-fire-80x, not main: nothing was pulled (switch it to main to let F5 update it)' },
    baseline: base, latest: base });
  assert.equal(p.reload, false); assert.equal(p.status, 'warn'); assert.match(p.detail, /on branch re4-fire-80x/);
  // gBox's own code: a relaunch through the reload only while this PC is idle; a refused one is not retried on every F5
  p = F.updatePlan({ pull: { ...pulled, restart: true, busy: null }, baseline: base, latest: { ...base, restart: true } });
  assert.equal(p.reload, true); assert.match(p.detail, /; gBox restarts to load its new code$/);
  p = F.updatePlan({ pull: { ...current, restart: true, busy: 'A native game still belongs to this desktop.' }, baseline: base, latest: { ...base, restart: true } });
  assert.equal(p.reload, false); assert.equal(p.status, 'warn'); assert.match(p.detail, /once this PC is idle \(A native game still belongs to this desktop\.\)/);
  p = F.updatePlan({ pull: { ...current, restart: true, busy: null, activation: { state: 'pending', reason: 'An owned local game is active.' } },
    baseline: { ...base, restart: true }, latest: { ...base, restart: true } });
  assert.equal(p.reload, false); assert.match(p.detail, /\(An owned local game is active\.\)/);
  // an older main process (no client:update): the Spark's client still reloads; the note says how to enable updates
  p = F.updatePlan({ pull: null, baseline: base, latest: { ...base, remote: 'm2' } });
  assert.equal(p.reload, true); assert.equal(p.status, 'warn'); assert.match(p.detail, /close and reopen it once/);
  p = F.updatePlan({ pull: { ...pulled, packages: true }, baseline: base, latest: base });
  assert.equal(p.status, 'warn'); assert.match(p.detail, /Rebuild & relaunch/);
});

test('F5 moves the PiP at once (no wait for a first frame); the continuity follower still waits for a real one', async () => {
  const src = html.slice(html.indexOf('// force (F5): the PiP moves at once'), html.indexOf('async function pipFollowSelected()'));
  const follows = [], image = { style: { backgroundImage: 'url("old")' } };
  let health = { state: 'running', age_s: 12 };
  const ctx = vm.createContext({ S: { apiUrl: 'http://spark:8765' }, COMPACT: { on: true, sid: 'w1-old' }, JSON, encodeURIComponent,
    pipSelection:{revision:0,allows:()=>true},
    gbox: { token: async () => 't' }, $: () => image, sessionTitle: s => s.title, closePipMenu: () => {}, setTimeout, clearTimeout,
    compactApi: async () => health,
    document: { querySelector: () => ({ dataset: { ready: 'false' }, executeJavaScript: async () => null }) },
    compactController: { follow: async (from, s, options) => { if(!options.current())return false;options.prepare();follows.push([from, s.sid]);return true; } } });
  vm.runInContext(src, ctx);
  await ctx.compactFollow({ session_id: 'w1-next', title: 'RE4' }, 'w1-old');   // no view to look, no live picture yet: it waits
  assert.deepEqual(follows, []); assert.equal(image.style.backgroundImage, 'url("old")');
  health = { state: 'running', age_s: 0.2 };                                     // the stream is live: the view is not needed
  await ctx.compactFollow({ session_id: 'w1-next', title: 'RE4' }, 'w1-old');
  assert.deepEqual(follows, [['w1-old', 'w1-next']]); follows.length = 0; image.style.backgroundImage = 'url("old")';
  await ctx.compactFollow({ session_id: 'w1-s1', title: 'RE5' }, 'w1-old', { force: true });
  assert.deepEqual(follows, [['w1-old', 'w1-s1']]); assert.equal(image.style.backgroundImage, '');
  // at most 30 fps (gbox/live_stream.py max_fps): half a 57 fps source's bitrate on this PC's Wi-Fi (operator 2026-10-27)
  assert.match(vm.runInContext('compactStreamUrl', ctx), /\/api\/sessions\/w1-s1\/mjpeg\?token=t&fps=30$/);
});

test('the shell wires the F5 steps: update through main.js, the F5 key carried over a reload, the main window following', () => {
  const main = require('node:fs').readFileSync(require('node:path').join(__dirname, '../clients/desktop/main.js'), 'utf8');
  const preload = require('node:fs').readFileSync(require('node:path').join(__dirname, '../clients/desktop/preload.js'), 'utf8');
  assert.match(preload, /clientUpdate: \(\) => ipcRenderer\.invoke\('client:update'\)/);
  assert.match(main, /ipcMain\.handle\('client:update', async event => \{\r?\n\s*assertClientSender\(event\);/);
  assert.match(html, /return GBoxReconnectFlow\.updatePlan\(\{ pull, baseline: await clientVersionAtLoad, latest \}\);/);
  assert.match(html, /localStorage\.setItem\(key, JSON\.stringify\(\{ \.\.\.info, at: Date\.now\(\) \}\)\); \} catch \{\}\r?\n\s*try \{ await clientRefresh\.refresh\(\); \}/);
  assert.match(html, /if \(F5_RESUME\) setTimeout\(\(\) => f5Recover\(F5_RESUME\), 1500\);/);
  assert.match(html, /if \(F5_RESUME\) return;\s+\/\/ the F5 going on does the reconnecting/);
  assert.match(html, /show\("Sessions", \$\{JSON\.stringify\(sid\)\}\); return "shown";/);
  assert.match(html, /await compactFollow\(session, COMPACT\.sid, \{ force: true \}\);/);
  assert.match(html, /ensureBot: sid => botEnsure\(sid, 'F5', \{ raise: true \}\),/);
  assert.match(html, /clientViewNavigation\+\+; restoreClientView\.retryAt = 0; clientRefresh\.done\(\);/);
  // the PiP hides every other element: an F5's dialog (only an F5's) stays visible over it
  assert.match(html, /body\.gbox-compact > :not\(#gpu-game\)[^{]*:not\(#reconnect\.f5\)[^{]*\{ display:none !important; \}/);
  assert.match(html, /el\.classList\.toggle\('f5', !!state\.f5\);/);
});
