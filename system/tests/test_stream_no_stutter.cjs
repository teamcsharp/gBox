// The PiP followers (desktop compact view, mini window, idle-screen corner) poll every 2-4 s. Reading the 660 KB
// session history each time made the server hold every game stream ~0.1 s per read (2026-10-26 stutter report):
// they read the few-KB running list while the watched game runs, and the history only to find its replacement.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const C = require('../clients/web/viz/session-continuity');

const live = { session_id: 'spark-a', state: 'running', game_id: 're5', mod: '', started: 5, last_frame_age: .1,
  detail: { worker_name: 'lilspark' } };

function reads(running, history) {
  const calls = [];
  return { calls, running: async () => { calls.push('running'); return running; },
    history: async () => { calls.push('history'); return history; } };
}

test('a running watched game is followed from the running list without reading the history', async () => {
  const r = reads([live], []);
  assert.deepEqual(await C.rowsFor(live.session_id, r.running, r.history), [live]);
  assert.deepEqual(r.calls, ['running']);
});

test('a MercMode turn resolves from the running list alone', async () => {
  const next = { ...live, session_id: 'spark-b', game_id: 're4' };
  const parked = { ...live, warm: true, replaced_by: next.session_id, mercmode_display_successor: true };
  const r = reads([parked, next], []);
  const rows = await C.rowsFor(live.session_id, r.running, r.history);
  assert.equal(C.resolve(live.session_id, rows), next);
  assert.deepEqual(r.calls, ['running']);
});

test('a replaced game (gone from the running list) is followed through the history', async () => {
  const fresh = { ...live, session_id: 'spark-new', started: 9 };
  const ended = { ...live, state: 'ended', replaced_by: fresh.session_id };
  const r = reads([fresh], [ended, fresh]);
  let selected = { session_id: live.session_id };
  const followed = [];
  const ctl = C.create({ current: () => selected, read: id => C.rowsFor(id, r.running, r.history),
    follow: async next => { followed.push(next.session_id); selected = next; } });
  await ctl.poll();
  assert.deepEqual(r.calls, ['running', 'history']);
  assert.deepEqual(followed, [fresh.session_id]);
  r.calls.length = 0;
  await ctl.poll();                                   // following the new game: back to the running list only
  assert.deepEqual(r.calls, ['running']);
});

test('a failed read keeps the watched game (the next poll retries)', async () => {
  await assert.rejects(C.rowsFor('x', async () => { throw Error('offline'); }, async () => []), /offline/);
});

test('the desktop compact PiP reads the shared running list, the history only for a replacement', async () => {
  const html = fs.readFileSync(require.resolve('../clients/desktop/index.html'), 'utf8');
  const start = html.indexOf('const compactRows =');
  assert.ok(start > 0 && start < html.indexOf('const compactContinuity ='));
  const calls = [];
  let running = [live];
  const context = vm.createContext({
    GBoxSessionContinuity: C, COMPACT: { on: true, local: false, sid: live.session_id }, compactSession: live,
    pipSelection:{preference:null},
    liveSessions: async () => { calls.push('running'); return { ok: true, data: running }; },
    gbox: { api: async path => { calls.push(path); return { ok: true, data: [{ ...live, state: 'ended' }] }; } },
    Error });
  vm.runInContext(html.slice(start, html.indexOf('async function pipFollowSelected()', start)), context);
  await vm.runInContext('compactContinuity.poll()', context);
  assert.deepEqual(calls, ['running'], 'a running game never reads the 660 KB history');
  running = [];
  calls.length = 0;
  await vm.runInContext('compactContinuity.poll()', context);
  assert.deepEqual(calls, ['running', '/api/sessions?limit=200']);
});

test('the mini window and the idle-screen corner poll the running list', () => {
  const mini = fs.readFileSync(require.resolve('../clients/desktop/mini.html'), 'utf8');
  const follower = mini.slice(mini.indexOf('const continuity = GBoxSessionContinuity.create('), mini.indexOf('const followTimer'));
  assert.match(follower, /GBoxSessionContinuity\.rowsFor\(id, \(\) => rows\('\/api\/sessions\?include_ended=false'\), \(\) => rows\('\/api\/sessions\?limit=200'\)\)/);
  assert.match(mini, /<script src="\.\.\/web\/viz\/session-continuity\.js"><\/script>/);
  const corner = fs.readFileSync(require.resolve('../clients/web/viz/background-operations.js'), 'utf8');
  const pip = corner.slice(corner.indexOf('async function sparkPip()'), corner.indexOf('async function tick()'));
  assert.match(pip, /api\('\/api\/sessions\?include_ended=false'\)/);
  assert.doesNotMatch(pip, /api\('\/api\/sessions'\)/);
});
