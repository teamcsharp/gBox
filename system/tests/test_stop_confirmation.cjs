const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
// #1504: Stop answers at once (the game leaves the screen before the worker's kill is confirmed); a stop the worker
// cannot confirm brings the session back with the reason, and the client never marks the session ended itself.
test('web Stop leaves at once and brings the session back when the kill is not confirmed', async () => {
  const source = fs.readFileSync(path.join(__dirname, '../clients/web/index.html'), 'utf8');
  const events = [], button = {}, status = {textContent: ''};
  let finish;
  const context = {active: {sid: 'w-s'}, encodeURIComponent,
    runJob: () => { events.push('stop'); return new Promise(r => { finish = r; }); },
    pip: () => events.push('pip'), show: async (...a) => events.push('show ' + a.join(' ')),
    api: () => {throw new Error('Stop must not preemptively mark ended');},
    $: () => status};
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('async function hardStop('), source.indexOf('async function resetGame(')), context);
  const pending = context.hardStop('w-s', button);
  // before the worker answers, the game is already gone from the screen
  assert.equal(context.active, null);
  assert.deepEqual(events, ['pip', 'show Library', 'stop']);
  assert.equal(button.disabled, true);
  finish({state: 'failed', error: 'worker unavailable'});
  await pending;
  assert.deepEqual(events, ['pip', 'show Library', 'stop', 'show Sessions w-s']);
  assert.equal(button.disabled, false);
  assert.match(button.title, /worker unavailable/);
  assert.match(status.textContent, /worker unavailable/);
  events.length = 0; context.active = {sid: 'w-s'};
  context.runJob = async () => { events.push('stop'); return {state: 'succeeded', output: {ended: true}}; };
  await context.hardStop('w-s', button);
  assert.equal(context.active, null);
  assert.deepEqual(events, ['pip', 'show Library', 'stop']);
});
test('desktop Close hides the game at once, docks it again when the stop fails, never announces a false close', async () => {
  const source = fs.readFileSync(path.join(__dirname, '../clients/desktop/index.html'), 'utf8');
  const events = [];
  let fail;
  const context = { EMB: {sid: 'w-s', closed: new Set(), pid: 7}, pipHandle() {},
    gbox: {embedSync: async st => events.push('hide ' + st), api: () => {throw new Error('no ended shortcut');}},
    gameJob: () => new Promise((_, reject) => { fail = reject; }), toast: text => events.push(text)};
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('async function gameClose()'), source.indexOf('// ---------------- game menu actions')), context);
  const pending = context.gameClose();
  await new Promise(r => setImmediate(r));
  assert.equal(context.EMB.sid, null);                    // gone before the worker answered
  assert.ok(context.EMB.closed.has('w-s'));
  assert.deepEqual(events.slice(0, 2), ['hide null', 'Stopping…']);
  fail(new Error('stop failed'));
  await pending;
  assert.equal(context.EMB.closed.size, 0);                // the embed tick docks the still-running game again
  assert.ok(events.some(s => s.includes('stop failed')));
  assert.ok(!events.includes('Closed'));
  events.length = 0;
  context.EMB.sid = 'w-s';
  context.gameJob = async () => ({returncode: 1});
  await context.gameClose();
  assert.ok(context.EMB.closed.has('w-s'));
  assert.equal(events.at(-1), 'Closed');
});
