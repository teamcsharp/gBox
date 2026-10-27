// The game-window helper process (clients/desktop/embed-helper.cjs, winembed.py) and main.js's use of it.
// operator 2026-10-27, JAYBUILTFINALE: F5 ended inert on "Error invoking remote method 'compact:view': Error: Game-window
// helper timed out; the current dock was preserved" - after a relaunch the helper's interpreter started 3 s after it was
// spawned (venv launcher 01:03:06, interpreter 01:03:09), so its first command could not be answered within its 3 s.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const fs = require('node:fs');
const path = require('node:path');
const H = require('../clients/desktop/embed-helper.cjs');

function rig(options = {}) {
  let clock = 1000, id = 0;
  const timers = new Map(), procs = [], killed = [], exits = [], events = [], logs = [];
  const advance = ms => {
    const until = clock + ms;
    for (;;) {
      const due = [...timers.entries()].filter(([, t]) => t.at <= until).sort((a, b) => a[1].at - b[1].at)[0];
      if (!due) break;
      timers.delete(due[0]); clock = Math.max(clock, due[1].at); due[1].fn();
    }
    clock = until;
  };
  const helper = H.create({
    start: () => {
      if (options.fail) throw Error('python.exe was not found');
      const proc = new EventEmitter(); proc.pid = 100 + procs.length; proc.lines = [];
      proc.stdout = new EventEmitter();
      proc.stdin = { write: line => { proc.lines.push(JSON.parse(line)); }, end: () => { proc.ended = true; }, on() {} };
      proc.kill = () => { proc.plainKill = true; };
      proc.reply = value => proc.stdout.emit('data', JSON.stringify(value) + '\n');
      procs.push(proc); return proc;
    },
    kill: proc => killed.push(proc.pid),
    onEvent: m => events.push(m), onExit: info => exits.push(info), log: text => logs.push(text),
    now: () => clock,
    setTimer: (fn, ms) => { timers.set(++id, { fn, at: clock + ms }); return id; },
    clearTimer: key => timers.delete(key),
  });
  return { helper, procs, killed, exits, events, logs, advance, now: () => clock };
}
const settle = () => new Promise(resolve => setImmediate(resolve));

test('a slow first start is waited for; once the helper answers, each command has its own deadline', async () => {
  const r = rig();
  const watch = r.helper.send({ op: 'watch', app: 7 });
  r.advance(5000); await settle();                                   // 3 s deadline passed: still starting, still waiting
  r.procs[0].reply({ ok: true, front: true });
  assert.deepEqual(await watch, { ok: true, front: true });
  const chrome = r.helper.send({ op: 'appchrome', on: true });
  r.advance(3000);
  assert.deepEqual(await chrome, { ok: false, unavailable: true, error: 'Game-window helper timed out; the current dock was preserved' });
  assert.equal(r.procs.length, 1); assert.deepEqual(r.killed, []);
  // a start that never answers at all times out after the deadline plus the start allowance
  const cold = rig(); const first = cold.helper.send({ op: 'watch' });
  let done = false; first.then(() => { done = true; });
  cold.advance(H.COLD_START_MS + 2999); await settle(); assert.equal(done, false);
  cold.advance(1); assert.equal((await first).unavailable, true);
});

test('a reply after its deadline keeps its FIFO slot and still reaches late(); the next command gets its own reply', async () => {
  const r = rig(), late = [];
  const warm = r.helper.send({ op: 'status' }); r.procs[0].reply({ ok: true }); await warm;
  const a = r.helper.send({ op: 'appchrome', on: true }, 3000, { late: value => late.push(value) });
  r.advance(3000); assert.equal((await a).unavailable, true);
  const b = r.helper.send({ op: 'watch' });
  r.procs[0].reply({ ok: true, bits: 0xcb0000 });                    // a's answer, late
  r.procs[0].reply({ ok: true, front: false });                      // b's answer
  assert.deepEqual(late, [{ ok: true, bits: 0xcb0000 }]);
  assert.deepEqual(await b, { ok: true, front: false });
});

test('a helper that stops answering is replaced: its commands resolve, its process tree ends, the next command starts anew', async () => {
  const r = rig();
  const warm = r.helper.send({ op: 'watch' }); r.procs[0].reply({ ok: true }); await warm;
  const stuck = r.helper.send({ op: 'appchrome', on: true });         // the helper never answers again
  r.advance(3000); assert.equal((await stuck).unavailable, true);
  assert.deepEqual(r.killed, [], 'one missed deadline is not yet a stuck helper');
  const again = r.helper.send({ op: 'watch' });
  r.advance(H.HUNG_MS);
  assert.deepEqual(await again, { ok: false, unavailable: true, error: 'Game-window helper timed out; the current dock was preserved' });
  assert.deepEqual(r.killed, [100], 'the whole helper tree (venv launcher + interpreter) is ended');
  assert.equal(r.procs[0].ended, true); assert.deepEqual(r.exits, [{ restarted: true }]);
  assert.match(r.logs.join('\n'), /stopped answering \(no answer to appchrome\)/);
  r.procs[0].reply({ ok: true, bits: 1 });                           // the old helper's late output answers nothing
  const fresh = r.helper.send({ op: 'watch', app: 7 });
  assert.equal(r.procs.length, 2); assert.deepEqual(r.procs[1].lines, [{ op: 'watch', app: 7 }]);
  r.procs[1].reply({ ok: true, front: true });
  assert.deepEqual(await fresh, { ok: true, front: true });
  r.procs[0].emit('close');                                          // the replaced helper's exit changes nothing now
  assert.deepEqual(r.exits, [{ restarted: true }]); assert.equal(r.helper.running(), true);
});

test('an attach may wait for its emulator window; a cold start is not mistaken for a stuck helper', async () => {
  const r = rig();
  const warm = r.helper.send({ op: 'watch' }); r.procs[0].reply({ ok: true }); await warm;
  const attach = r.helper.send({ op: 'attach', pid: 4, parent: 7 });
  r.advance(3000); await attach;
  const probe = r.helper.send({ op: 'status', pid: 4 }, 1200);
  r.advance(H.HUNG_MS + 1000); await probe;
  assert.deepEqual(r.killed, [], 'attach waits up to 15 s for a window by design');
  const late = r.helper.send({ op: 'status', pid: 4 }, 1200);
  r.advance(H.ATTACH_HUNG_MS); await late;
  assert.deepEqual(r.killed, [100]);
  const cold = rig(); const first = cold.helper.send({ op: 'watch' });
  cold.advance(H.COLD_START_MS + 3000); await first;
  assert.deepEqual(cold.killed, [], 'the first answer of a new helper is allowed its start');
});

test('events never take a reply slot; malformed lines are skipped; a helper that exits resolves its commands', async () => {
  const r = rig();
  const watch = r.helper.send({ op: 'watch' });
  r.procs[0].stdout.emit('data', '{"event":"foreground","front":true}\nnot json\n{"ok":tr');
  r.procs[0].stdout.emit('data', 'ue,"front":true}\n');
  assert.deepEqual(await watch, { ok: true, front: true });
  assert.deepEqual(r.events, [{ event: 'foreground', front: true }]); assert.match(r.logs.join(), /malformed/);
  const pending = r.helper.send({ op: 'move', x: 0, y: 0, w: 1, h: 1 });
  r.procs[0].emit('close');
  assert.deepEqual(await pending, { ok: false, unavailable: true, error: 'Game-window helper exited; the current dock was preserved' });
  assert.deepEqual(r.exits, [{ restarted: false }]);
  r.helper.notify({ op: 'detach' }); assert.equal(r.procs.length, 1, 'notify never starts a helper');
  r.helper.send({ op: 'watch' }); assert.equal(r.procs.length, 2);
});

test('a helper that cannot start, or a full queue, answers unavailable at once', async () => {
  const r = rig({ fail: true });
  const out = await r.helper.send({ op: 'watch' });
  assert.equal(out.ok, false); assert.equal(out.unavailable, true); assert.match(out.error, /could not start: python\.exe was not found/);
  const q = rig(); const sent = [];
  for (let i = 0; i < H.QUEUE_LIMIT; i++) sent.push(q.helper.send({ op: 'status' }));
  assert.match((await q.helper.send({ op: 'status' })).error, /busy/);
});

test('main.js uses the helper module: a replaced helper keeps the PiP and main keeps the caption bits, late answers too', () => {
  const main = fs.readFileSync(path.join(__dirname, '../clients/desktop/main.js'), 'utf8');
  assert.match(main, /const embedHelper = require\('\.\/embed-helper\.cjs'\)\.create\(\{/);
  assert.match(main, /return embedHelper\.send\(cmd, deadlineMs, options\);/);
  assert.match(main, /execFile\('taskkill', \['\/T', '\/F', '\/PID', String\(proc\.pid\)\]/);
  const exit = main.slice(main.indexOf('onExit: ({ restarted }) => {'), main.indexOf('function embedCmd('));
  assert.match(exit, /if \(restarted\) \{ if \(!quitting && compactWindow\.state\(\)\.on\) compactWindow\.rechrome\(\)/);
  assert.match(exit, /compactRecoveryPending = true;\s+compactWindow\.restore\(\)/, 'an exited helper still restores the window controls');
  assert.match(main, /const keep = result => \{ if \(result\?\.ok\) \{ compactChromeBits = on \? result\.bits : null;/);
  assert.match(main, /\.\.\.\(compactChromeBits !== null \? \{ bits: compactChromeBits \} : \{\}\) \}, 3000, \{ late: keep \}\);/);
  assert.doesNotMatch(main, /\bembedder\b/);
});
