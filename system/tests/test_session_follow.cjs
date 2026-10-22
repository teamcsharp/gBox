// The Sessions view always shows a game that plays (clients/web/viz/session-follow.js; operator 2026-10-20: "Every time
// I look over at gBox, the window looks like this. There's not even a game playing... I need it playing games always").
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const F = require('../clients/web/viz/session-follow.js');
const L = require('../clients/web/viz/session-live.js');

const NOW = 1_000_000;
const WORKERS = [{ id: 'nuc', name: 'i9-NUC', online: true, features: [] }, { id: 'spark', name: 'lilspark', online: true, features: [] }];
const RE4 = { session_id: 'spark-re4', title: 'Resident Evil 4', state: 'ended', ended: NOW - 5, agent_owned: true, detail: { worker_name: 'lilspark' } };
const DOA3 = { session_id: 'nuc-doa3', title: 'Dead or Alive 3', state: 'running', started: NOW - 600, last_frame_age: 0.4, agent_owned: true, detail: { worker_name: 'i9-NUC' } };
const NEW_DARK = { session_id: 'spark-sc2', title: 'SoulCalibur II', state: 'running', started: NOW - 20, last_frame_age: null, detail: { worker_name: 'lilspark' } };

test('the next game: the broadcast program, else the newest with a picture, else the newest', () => {
  const ss = [RE4, DOA3, NEW_DARK];
  assert.deepEqual(F.pick(ss, { session_id: 'spark-sc2' }), { session: NEW_DARK, via: 'broadcast' });
  // the program shows the ended game (or nothing): the newest game with a picture, even if a newer one has none yet
  assert.equal(F.pick(ss, { session_id: 'spark-re4' }, { except: 'spark-re4', workers: WORKERS, now: NOW, judge: L.judge }).session, DOA3);
  assert.equal(F.pick(ss, null).session, DOA3);
  assert.equal(F.pick([RE4, NEW_DARK], null).via, 'newest');
  assert.equal(F.pick([RE4, { ...DOA3, stopping: true }], null), null);              // stopping or ended: nothing to show
  assert.equal(F.pick(null, null), null);
});

test('it leaves an ended demo at once, the operator\'s own game after a minute, and never a playing or pinned one', () => {
  assert.equal(F.decide(null).follow, true);                                         // nothing selected
  assert.equal(F.decide(DOA3).follow, false);                                        // it plays: never switched away from
  assert.deepEqual(F.decide(RE4, { now: NOW }), { follow: true, why: 'ended' });     // an agent's / bot demo's session
  assert.equal(F.decide({ ...RE4, agent_owned: false, bot_demo: true }, { now: NOW }).follow, true);
  const own = { ...RE4, agent_owned: false };
  assert.deepEqual(F.decide(own, { now: NOW }), { follow: false, why: 'your game ended', wait_s: F.OWN_GRACE_S - 5 });
  assert.equal(F.decide(own, { now: NOW + F.OWN_GRACE_S }).follow, true);            // time to Reopen it is over
  assert.equal(F.decide(RE4, { now: NOW, pinned: 'spark-re4' }).why, 'pinned');      // "Stay here"
  assert.equal(F.decide(RE4, { now: NOW, program: { mode: 'session', target: 'spark-re4' } }).follow, false);   // On air pin
});

test('the line says what it shows now and why', () => {
  assert.equal(F.note(RE4, DOA3), 'Now showing Dead or Alive 3 on i9-NUC: the Resident Evil 4 session ended');
  assert.equal(F.note(null, DOA3), 'Now showing Dead or Alive 3 on i9-NUC: no game was selected');
  const wait = F.waitHTML(DOA3, { why: 'your game ended', wait_s: 42 });
  assert.match(wait, /Showing <b>Dead or Alive 3<\/b> on i9-NUC in 42 s/);
  assert.match(wait, /data-follow-stay="1">Stay here/);
  assert.match(wait, /data-follow-go="nuc-doa3">Watch it now/);
  assert.match(F.waitHTML(DOA3, { why: 'pinned' }), /Pinned here\. <b>Dead or Alive 3<\/b> on i9-NUC is playing\./);
});

test('nothing playing: when the screensaver starts a game, and why not yet on each PC', () => {
  const st = { settings: { enabled: true, idle_minutes: 10 }, pcs: [
    { name: 'JAYBUILTFINALE', online: true, reason: 'waiting for 10 minutes without operator input', starts_in_s: 360 },
    { name: 'lilspark', online: true, reason: 'CPU is at 93%; background admission budget is 70%.', starts_in_s: null },
    { name: 'i9-NUC', online: false, reason: 'offline', starts_in_s: null }] };
  const html = F.idleHTML(st);
  assert.match(html, /Nothing is playing; the screensaver starts on JAYBUILTFINALE after 10 min idle \(6 min to go\)/);
  assert.match(html, /<li><b>lilspark<\/b>: CPU is at 93%; background admission budget is 70%\.<\/li>/);
  assert.match(html, /<li><b>i9-NUC<\/b>: offline<\/li>/);
  const ready = F.idleHTML({ settings: { enabled: true }, pcs: [{ name: 'lilspark', online: true, reason: null }] });
  assert.match(ready, /starts a game on lilspark at its next check/);
  assert.match(ready, /lilspark<\/b>: can start a game now/);
  assert.match(F.idleHTML({ settings: { enabled: false }, pcs: [] }), /the autoplay screensaver is off/);
  assert.match(F.idleHTML({ settings: { enabled: true }, pcs: [{ name: 'x', online: true, reason: 'busy with jobs' }] }),
               /can&#39;t start a game on any PC now/);
  assert.match(F.idleHTML(null), /Nothing is playing\./);
  assert.match(F.idleHTML({ settings: {}, pcs: [{ name: '<b>', online: true, reason: '<i>' }] }), /&#60;b&#62;/);   // escaped
});

test('web shell: an ended or empty Sessions view follows the live game; the list stays when chosen', () => {
  const web = fs.readFileSync(path.join(__dirname, '..', 'clients', 'web', 'index.html'), 'utf8');
  assert.match(web, /<script src="\/viz\/session-follow\.js"><\/script>/);
  // the ended view looks for a game (and says why nothing plays), the list too unless the operator chose it
  assert.match(web, /Reopen game<\/button>` : ''}<div id="follow-idle">/);
  assert.match(web, /if \(!sid\) \{ if \(!FOLLOW\.list\) followWatch\(null\); return; \}/);
  assert.match(web, /head\.dataset\.state !== "running"\) \{ playing = null;[^\n]*followWatch\(sid\); return; \}/);
  assert.match(web, /\$\("#tabs"\)\.onclick = e => e\.target\.dataset\.t && \(e\.target\.dataset\.t === "Sessions" \? showList\(\)/);
  assert.match(web, /<button class="act" onclick="showList\(\)">All sessions<\/button>/);
  assert.match(web, /if \(!\(t === "Sessions" && !args\[0\]\)\) FOLLOW\.list = false;/);
  // the program first (GET /api/broadcast), the screensaver's reasons when nothing runs, the line after a move
  assert.match(web, /api\("\/api\/broadcast"\)/);
  assert.match(web, /F\.idleHTML\(await api\("\/api\/autoplay-screensaver"\)/);
  assert.match(web, /followNote\(sid, head\);/);
});

test('a running session on an offline PC is never followed (#2870)', () => {
  const ghost = { ...DOA3, session_id: 'jay-x', worker_online: false };
  assert.equal(F.pick([ghost], { session_id: 'jay-x' }), null);
  assert.equal(F.pick([ghost, NEW_DARK], null).session, NEW_DARK);
});
