const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
test('web Stop keeps the session visible until native termination succeeds', async () => {
  const source = fs.readFileSync(path.join(__dirname, '../clients/web/index.html'), 'utf8');
  const events = [], button = {};
  const context = {active: {sid: 'w-s'}, encodeURIComponent,
    runJob: async () => { events.push('stop'); return {state: 'failed', error: 'worker unavailable'}; },
    pip: () => events.push('pip'), show: () => events.push('navigate'),
    api: () => {throw new Error('Stop must not preemptively mark ended');},
    $: () => ({textContent: ''})};
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('async function hardStop('), source.indexOf('async function resetGame(')), context);
  await context.hardStop('w-s', button);
  assert.equal(context.active.sid, 'w-s');
  assert.deepEqual(events, ['stop']);
  assert.equal(button.disabled, false);
  assert.match(button.title, /worker unavailable/);
  context.runJob = async () => ({state: 'succeeded', output: {ended: true}});
  await context.hardStop('w-s', button);
  assert.equal(context.active, null);
  assert.deepEqual(events, ['stop', 'pip', 'navigate']);
});
test('desktop Close retains the session on stop failure and never announces a false close', async () => {
  const source = fs.readFileSync(path.join(__dirname, '../clients/desktop/index.html'), 'utf8');
  const events = [];
  const context = { EMB: {sid: 'w-s', closed: new Set()}, pipHandle() {},
    gbox: {embedSync: async () => {}, api: () => {throw new Error('no ended shortcut');}},
    gameJob: async () => {throw new Error('stop failed');}, toast: text => events.push(text)};
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('async function gameClose()'), source.indexOf('// ---------------- game menu actions')), context);
  await context.gameClose();
  assert.equal(context.EMB.sid, 'w-s');
  assert.equal(context.EMB.closed.size, 0);
  assert.ok(events.some(s => s.includes('stop failed')));
  assert.ok(!events.includes('Closed'));
});
