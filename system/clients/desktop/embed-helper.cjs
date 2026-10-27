'use strict';
// The game-window helper (winembed.py): one child process, one JSON line per command, answered in order.
//
// A helper that starts slowly or stops answering must never leave the app inert (operator 2026-10-27, JAYBUILTFINALE:
// F5 ended on "Game-window helper timed out; the current dock was preserved"). After a relaunch the helper's interpreter
// started 3 s after it was spawned, while gBox's local services were booting, so its first command (picture-in-picture's
// window controls) timed out before Python had even run; and a helper stuck in a call into another window would time out
// every command after it. Here:
//   - the first answer after a start gets coldStartMs more than its command's deadline;
//   - a helper that has answered nothing for its oldest command's allowance is stuck (commands run one at a time): its
//     process tree is ended and the next command starts a fresh helper; its unanswered commands resolve at once;
//   - every command the helper did not answer says so (unavailable: true), so a caller can fall back instead of failing;
//   - an answer that comes after its deadline still reaches the command's late() callback (main keeps the caption bits).
const COLD_START_MS = 12000, HUNG_MS = 10000, ATTACH_HUNG_MS = 20000, QUEUE_LIMIT = 64;

function create({ start, kill = proc => proc.kill(), onEvent = () => {}, onExit = () => {}, log = () => {}, now = Date.now,
                  setTimer = setTimeout, clearTimer = clearTimeout, coldStartMs = COLD_START_MS, hungMs = HUNG_MS,
                  attachHungMs = ATTACH_HUNG_MS }) {
  let child = null, queue = [], buffer = '', startedAt = 0, answered = false, answeredAt = 0, checkTimer = null;
  const missing = error => ({ ok: false, unavailable: true, error });
  function launch() {
    const proc = start();
    child = proc; queue = []; buffer = ''; startedAt = now(); answered = false; answeredAt = 0;
    clearTimer(checkTimer); checkTimer = null;
    proc.stdout.on('data', data => {
      if (child !== proc) return;                    // a replaced helper's late output answers nothing here
      buffer += data; let i;
      while ((i = buffer.indexOf('\n')) >= 0) {
        const line = buffer.slice(0, i); buffer = buffer.slice(i + 1);
        let m;
        try { m = JSON.parse(line); } catch { log('Ignored malformed helper output'); continue; }
        if (m && m.event) { try { onEvent(m); } catch (error) { log(String(error?.message || error)); } continue; }
        answered = true; answeredAt = now();
        // Keep a timed-out reply's FIFO slot until it arrives; do not let it be
        // mistaken for the next command or detach a different game's surface.
        const entry = queue.shift();
        if (!entry) continue;
        if (entry.settled) { try { entry.late?.(m); } catch {} } else entry.finish(m);
      }
    });
    proc.stdin?.on?.('error', error => log('Game-window helper input closed: ' + error.message));
    proc.on('error', error => log('Game-window helper failed: ' + error.message));
    proc.on('close', () => {
      if (child !== proc) return;
      child = null; clearTimer(checkTimer); checkTimer = null;
      queue.splice(0).forEach(entry => entry.finish(missing('Game-window helper exited; the current dock was preserved')));
      onExit({ restarted: false });
    });
    return proc;
  }
  function restart(reason) {
    const proc = child;
    if (!proc) return;
    log(`Game-window helper stopped answering (${reason}); a new one starts with the next command`);
    child = null; clearTimer(checkTimer); checkTimer = null;
    queue.splice(0).forEach(entry => entry.finish(missing('Game-window helper restarted; the current dock was preserved')));
    try { proc.stdin?.end?.(); } catch {}
    try { kill(proc); } catch (error) { log('Game-window helper could not be stopped: ' + error.message); }
    onExit({ restarted: true });
  }
  // From a missed deadline on: the oldest unanswered command (they run one at a time) is watched until the helper answers
  // or its allowance runs out.
  function check() {
    clearTimer(checkTimer); checkTimer = null;
    const head = queue[0];
    if (!child || !head) return;
    const since = Math.max(head.at, answeredAt, answered ? 0 : startedAt + coldStartMs);
    const left = since + (['attach', 'kill'].includes(head.op) ? attachHungMs : hungMs) - now();   // these may wait on purpose
    if (left <= 0) restart(`no answer to ${head.op || 'a command'}`);
    else checkTimer = setTimer(check, left);
  }
  function send(cmd, deadlineMs = 3000, { late } = {}) {
    if (!child) {
      try { launch(); }
      catch (error) { child = null; return Promise.resolve(missing('Game-window helper could not start: ' + error.message)); }
    }
    if (queue.length >= QUEUE_LIMIT) { check(); return Promise.resolve(missing('Game-window helper is busy; the current dock was preserved')); }
    const proc = child;
    return new Promise(resolve => {
      const entry = { op: cmd?.op, at: now(), settled: false, late, timer: null,
        finish: value => { if (entry.settled) return; entry.settled = true; clearTimer(entry.timer); resolve(value); } };
      queue.push(entry);
      // a new helper's first answer also waits for its interpreter to start
      const grace = answered ? 0 : Math.max(0, startedAt + coldStartMs - now());
      entry.timer = setTimer(() => {
        entry.finish(missing('Game-window helper timed out; the current dock was preserved'));
        check();
      }, deadlineMs + grace);
      try { proc.stdin.write(JSON.stringify(cmd) + '\n'); }
      catch (error) { const at = queue.indexOf(entry); if (at >= 0) queue.splice(at, 1); entry.finish(missing(error.message)); }
    });
  }
  // a fire-and-forget line for a helper that already runs (the detach at shutdown); never starts one
  function notify(cmd) { try { child?.stdin.write(JSON.stringify(cmd) + '\n'); } catch {} }
  return { send, notify, restart, running: () => !!child, kill: () => { try { child?.kill(); } catch {} } };
}

module.exports = { create, COLD_START_MS, HUNG_MS, ATTACH_HUNG_MS, QUEUE_LIMIT };
