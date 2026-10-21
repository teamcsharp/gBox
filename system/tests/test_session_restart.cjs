// Restart session / Reconnect stream (operator 2026-10-21) and triple-click picture-in-picture: the shared restart flow
// (clients/web/viz/session-restart.js), the PiP gesture decision (clients/desktop/pip-gesture.js), the PiP window
// following a restarted game (compact-game.js follow) and the menu / message wiring in both shells.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const R = require('../clients/web/viz/session-restart.js');
const G = require('../clients/desktop/pip-gesture.js');
const C = require('../clients/desktop/compact-game.js');
const read = p => fs.readFileSync(path.join(__dirname, p), 'utf8').replace(/\r\n/g, '\n');   // a Windows checkout has CRLF
const web = read('../clients/web/index.html');
const desktop = read('../clients/desktop/index.html');
const pickWhip = read('../clients/web/viz/pick-whip.js');

// a fake control plane: the reset job runs `steps` polls, then ends as `end`
function plane({ end = { state: 'succeeded', output: { session_id: 'spark-new', notes: [] } }, steps = 2, autoplay = null, autoplayStartError = null } = {}) {
  const calls = [], log = [];
  let polls = 0;
  const io = {
    api: async (p, body) => {
      calls.push([p, body]);
      if (p.endsWith('/reset')) return { id: 'job1', state: 'running', progress: { pct: 10, msg: 'Starting the copy' } };
      if (p === '/api/jobs/job1') return ++polls < steps ? { id: 'job1', state: 'running', progress: { pct: 50, msg: 'Booting' } } : { id: 'job1', ...end };
      throw new Error('unexpected ' + p);
    },
    autoplay: async (sid, input) => {
      log.push(['autoplay', sid, input.op, input.mode]);
      if (input.op === 'status') return autoplay || { running: false };
      if (input.op === 'start' && autoplayStartError) throw new Error(autoplayStartError);
      return input.op === 'start' ? { objective: 'RE5 Mercenaries playbook' } : { stopped: true };
    },
    progress: (p, m) => log.push(['progress', Math.round(p), m]),
    show: t => log.push(['show', t]),
    fail: m => log.push(['fail', m]),
    follow: (a, b) => log.push(['follow', a, b]),
    reconnect: sid => log.push(['reconnect', sid]),
    delay: async () => {},
  };
  return { io, calls, log };
}

test('Restart relaunches through the reset endpoint (mode restart), never session_op reset, then follows and re-attaches', async () => {
  const x = plane();
  const r = await R.restart(x.io, { sid: 'spark-old', title: 'Demon\'s Souls' });
  assert.deepEqual(x.calls[0], ['/api/sessions/spark-old/reset', { mode: 'restart', intent: 'restart' }]);
  assert.ok(!x.calls.some(([p, b]) => p === '/api/jobs' || (b && b.tool === 'session_op')), 'no session_op reset (RPCS3 has none)');
  assert.equal(r.session_id, 'spark-new'); assert.equal(r.from, 'spark-old'); assert.equal(r.autoplay, null);
  const order = x.log.filter(e => e[0] === 'follow' || e[0] === 'reconnect');
  assert.deepEqual(order, [['follow', 'spark-old', 'spark-new'], ['reconnect', 'spark-new']], 'follow first, then the new stream');
  assert.ok(x.log.some(e => e[0] === 'progress' && e[2] === 'Booting'), 'the job progress is shown');
  assert.deepEqual(x.log.filter(e => e[0] === 'autoplay').map(e => e[2]), ['status'], 'no autoplay: only asked');
  assert.equal(x.log.at(-1)[0], 'progress'); assert.equal(x.log.at(-1)[1], 100);
});

test('a running autoplay is stopped for the relaunch and started again on the new session', async () => {
  const x = plane({ autoplay: { running: true, mode: 'playbook', mission: 'merc' } });
  const r = await R.restart(x.io, { sid: 'spark-old' });
  assert.deepEqual(x.log.filter(e => e[0] === 'autoplay'),
    [['autoplay', 'spark-old', 'status', undefined], ['autoplay', 'spark-old', 'stop', undefined], ['autoplay', 'spark-new', 'start', 'playbook']]);
  assert.deepEqual(r.autoplay, { ok: true, objective: 'RE5 Mercenaries playbook' });
  const i = x.log.findIndex(e => e[0] === 'reconnect'), j = x.log.findIndex(e => e[2] === 'start');
  assert.ok(i >= 0 && j > i, 'the autoplay starts after the stream is back');
});

test('a replay autoplay restarts as auto (a replay would reset the game again)', () => {
  assert.deepEqual(R.autoplayInput({ mode: 'replay' }), { op: 'start', mode: 'auto' });
  assert.deepEqual(R.autoplayInput({ mode: 'vision' }), { op: 'start', mode: 'vision' });
  assert.deepEqual(R.autoplayInput(null), { op: 'start', mode: 'auto' });
});

test('an autoplay that does not come back is a note, not a failed restart', async () => {
  const x = plane({ autoplay: { running: true, mode: 'auto' }, autoplayStartError: 'no playbook here' });
  const r = await R.restart(x.io, { sid: 'spark-old' });
  assert.equal(r.ok, true); assert.deepEqual(r.autoplay, { ok: false, error: 'no playbook here' });
  assert.match(r.notes.join(' '), /autoplay did not start again \(no playbook here\); press F3/);
});

test('a failed relaunch says why, does not follow, and gives the autoplay back to the old copy', async () => {
  const x = plane({ end: { state: 'failed', error: 'That game is the operator\'s live session; automated tasks can\'t reset or restart it.' },
    autoplay: { running: true, mode: 'learned' } });
  await assert.rejects(R.restart(x.io, { sid: 'spark-old' }), /^Error: Restart failed: That game is the operator's live session/);
  assert.ok(x.log.some(e => e[0] === 'fail' && /^Restart failed: /.test(e[1])), 'the progress view shows the reason');
  assert.ok(!x.log.some(e => e[0] === 'follow' || e[0] === 'reconnect'));
  assert.deepEqual(x.log.filter(e => e[0] === 'autoplay').at(-1), ['autoplay', 'spark-old', 'start', 'learned']);
});

test('an HTTP refusal (409 already resetting) is a clear failure too', async () => {
  const x = plane();
  x.io.api = async () => { throw new Error('This game is already being reset or swapped. Wait for that to finish.'); };
  await assert.rejects(R.restart(x.io, { sid: 'spark-old' }), /Restart failed: This game is already being reset/);
  await assert.rejects(R.restart(x.io, {}), /No session to restart/);
});

test('reconnectImages re-attaches only that session\'s MJPEG pictures and keeps their token', () => {
  const imgs = ['/api/sessions/spark-a/mjpeg?token=T', '/api/sessions/spark-b/mjpeg?token=T', '/api/sessions/spark-a/frame.jpg?t=1', 'http://h/api/sessions/spark-a/mjpeg?token=T&reconnect=3']
    .map(src => ({ src, getAttribute() { return this.src; }, setAttribute(k, v) { this.src = v; } }));
  const doc = { querySelectorAll: () => imgs };
  assert.equal(R.reconnectImages(doc, 'spark-a', 99), 2);
  assert.deepEqual(imgs.map(i => i.src), ['/api/sessions/spark-a/mjpeg?token=T&reconnect=99', '/api/sessions/spark-b/mjpeg?token=T',
    '/api/sessions/spark-a/frame.jpg?t=1', 'http://h/api/sessions/spark-a/mjpeg?token=T&reconnect=99']);
  assert.equal(R.sessionOf('/api/sessions/w%2Dx/mjpeg?token=1'), 'w-x');
  assert.match(R.confirmText({ session_id: 'spark-1', title: 'RE5', owner: 'agent' }), /^Restart the agent's test session RE5 on spark\?/);
  assert.deepEqual(R.menuItems().map(i => i.text), ['Restart session', 'Reconnect stream']);
});

test('triple click: enter PiP from the game, leave it from the PiP window; single, double and modified clicks do nothing', () => {
  let t = 1000; const g = G.create({ now: () => t });
  assert.equal(g.decide({ clicks: 1, compact: false, onGame: true }), null);
  assert.equal(g.decide({ clicks: 2, compact: false, onGame: true }), null);
  assert.equal(g.decide({ clicks: 3, compact: false, onGame: false }), null, 'only the game picture');
  assert.equal(g.decide({ clicks: 3, compact: false, onGame: true, modifiers: true }), null, 'Ctrl/Alt clicks belong to the pickers');
  assert.equal(g.decide({ clicks: 3, compact: false, onGame: true }), 'enter');
  g.changed(true);
  t += 300; assert.equal(g.decide({ clicks: 3, compact: true, onGame: true }), null, 'the click run that opened it');
  t += 1000; assert.equal(g.decide({ clicks: 3, compact: true, onGame: true }), 'exit');
  assert.equal(g.decide({ clicks: 4, compact: true, onGame: true }), null);
});

test('triple click in PiP: the double click already restored it, so the third click does not reopen it', () => {
  let t = 1000; const g = G.create({ now: () => t });
  g.changed(true); t += 5000;
  g.changed(false);                       // dblclick restore (clicks 1 and 2)
  t += 200; assert.equal(g.decide({ clicks: 3, compact: false, onGame: true }), null);
  t += G.COOLDOWN_MS; assert.equal(g.decide({ clicks: 3, compact: false, onGame: true }), 'enter', 'a new triple click later works');
});

test('the PiP window follows a restarted game: same window, new session, pad follows', async () => {
  const seen = { render: [], pad: [], present: 0, modes: [] };
  const ctl = C.create({ mode: () => 'auto', resolve: async r => ({ sid: r.sid, local: false }), windowMode: async v => { seen.modes.push(v.on); return { ...v }; },
    render: s => seen.render.push(s.sid), present: () => seen.present++, pad: sid => seen.pad.push(sid) });
  await ctl.enter({ sid: 'spark-old' });
  assert.equal(await ctl.follow('other', { sid: 'spark-new', local: false }), false, 'another game: untouched');
  assert.equal(await ctl.follow('spark-old', { sid: 'spark-new', local: false }), true);
  assert.equal(ctl.state.sid, 'spark-new'); assert.equal(ctl.state.on, true);
  assert.equal(seen.pad.at(-1), 'spark-new'); assert.equal(seen.render.at(-1), 'spark-new');
  assert.deepEqual(seen.modes, [true], 'the window was not closed and reopened');
  assert.equal(await ctl.follow('spark-new', { sid: 'pc-local', local: true }), false, 'a local window cannot share the stream window');
  assert.equal(ctl.state.on, false); assert.deepEqual(seen.modes, [true, false]);
});

test('web shell wiring: session icon, PiP picture and game picture menus; triple-click message', () => {
  assert.match(web, /<script src="\/viz\/session-restart\.js"><\/script>/);
  const chip = web.slice(web.indexOf('function sessionChipMenu(sid, x)'), web.indexOf('document.addEventListener("click", async e => {', web.indexOf('function sessionChipMenu')));
  assert.match(chip, /GBoxSessionRestart\.menuItems\(\)\.map/);
  assert.match(web, /const c = e\.target\.closest\("\.tchip, #pipimg"\)/, 'the PiP picture opens the same menu');
  assert.match(web, /else if \(a === "restart" \|\| a === "reconnect"\) \{[^\n]*\n\s*a === "restart" \? sessionRestart\(sid\) : streamReconnect\(sid\); return; \}/);
  assert.match(web, /sessionExtra: sid => sid \? \["-", \.\.\.GBoxSessionRestart\.menuItems\(\)\] : \[\]/);
  assert.match(web, /onSessionExtra: \(id, sid\) => id === "restart" \? sessionRestart\(sid\) : id === "reconnect" \? streamReconnect\(sid\) : null/);
  assert.match(pickWhip, /extra: \(io\.sessionExtra && io\.sessionExtra\(sid\)\) \|\| \[\], onExtra: id => io\.onSessionExtra && io\.onSessionExtra\(id, sid\)/);
  const flow = web.slice(web.indexOf('async function sessionRestart(sid)'), web.indexOf('// Relaunch a game that shows no picture (#2858)'));
  assert.match(flow, /confirm\(GBoxSessionRestart\.confirmText\(info\)\)/, 'an explicit operator confirmation');
  assert.match(flow, /tool: "autoplay", input: \{ \.\.\.input, session_id: id \}, require_worker: id\.split\("-"\)\[0\]/);
  assert.match(flow, /follow: \(from, to\) => \{ followSession\(from, to\); gboxTell\(\{ ev: "sessionreplaced", from, to \}\); \}/);
  const triple = web.slice(web.indexOf('// Triple-click the game picture'));
  assert.match(triple, /if \(e\.detail !== 3 \|\| e\.button !== 0 \|\| e\.ctrlKey \|\| e\.altKey \|\| e\.shiftKey \|\| e\.metaKey \|\| !gboxEmbedded\(\)\) return;/);
  assert.match(triple, /gboxTell\(\{ ev: "gametriple", sid \}\);/);
  assert.doesNotMatch(triple.slice(0, triple.indexOf('});')), /preventDefault/, 'the clicks still reach the game');
});

test('desktop wiring: guest and native triple clicks, PiP follow / keep, PiP menu and the game menu entry', () => {
  for (const s of ['<script src="pip-gesture.js"></script>', '<script src="../web/viz/session-restart.js"></script>']) assert.ok(desktop.includes(s), s);
  assert.match(desktop, /else if \(m\.ev === "gametriple"\) pipTriple\(m\.sid \|\| EMB\.sid\);/);
  assert.match(desktop, /else if \(m\.ev === "sessionreplaced"\) compactFollow\(m\.from, m\.to\)/);
  assert.match(desktop, /else if \(m\.ev === "streamreconnect"\) compactReconnect\(m\.sid\)/);
  assert.match(desktop, /if \(ev\.event === "piptriple"\) return pipTriple\(EMB\.sid\);/);
  assert.match(desktop, /&& !\(await compactKeep\(COMPACT\.sid\)\)\) await compactRestore\(\);/, 'PiP waits for / follows a restarted game');
  assert.match(desktop, /render: state => \{\n?\s*pipGesture\.changed\(state\.on\);/);
  assert.match(desktop, /pipGesture\.changed\(false\); compactRestore\(\)/, 'the double-click restore starts the cooldown at once');
  assert.match(desktop, /\["restart", "↻ Restart session \(relaunch it with its mod\)"\]/);
  assert.match(desktop, /else if \(a === "restart"\) await desktopRestart\(EMB\.sid\);/);
  assert.match(desktop, /if \(!COMPACT\.on \|\| e\.target\.id !== 'compact-stream'\) return;\n\s*e\.preventDefault\(\); e\.stopPropagation\(\); compactMenu\(e\.clientX, e\.clientY\);/);
  assert.match(desktop, /:not\(#compact-menu\):not\(#compact-status\)/, 'the PiP window shows its menu and status');
});
