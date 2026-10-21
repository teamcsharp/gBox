// The detailed report's saved moment (desktop evidence viewer): a Dolphin / RetroArch report keeps its moment through
// gBox's own save slot (one state_transfer op=snapshot job, also its state_export_job_id): no emulator slot holds it,
// so Restore imports its file instead of loading a slot. Other emulators' reports still load their slot.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../clients/desktop/index.html'), 'utf8');
function between(start, end) {
  const a = html.indexOf(start), b = html.indexOf(end, a + start.length);
  assert.ok(a >= 0 && b > a, `missing desktop boundary ${start}`);
  return html.slice(a, b);
}
const page = vm.createContext({});
vm.runInContext(between('function evMoment(context, job)', 'async function evRequest('), page);

const snapshot = (state, result = {}, error) => ({ tool: 'state_transfer', state, error,
  input: { session_id: 'w1-re4', op: 'snapshot' }, output: { result } });

test('a snapshot moment restores by importing its file, never by loading a slot', () => {
  const moment = page.evMoment({ session_id: 'w1-re4' }, snapshot('succeeded',
    { artifact: 'a'.repeat(64), file: 'G4BE08.s10', bytes: 4096, slot: 10, operator_slot: 1 }));
  assert.equal(moment.snap, true);
  assert.deepEqual({ ...moment.state }, { sessionId: 'w1-re4', artifact: 'a'.repeat(64) });
  assert.match(moment.text, /gBox's own save slot/);
  assert.match(moment.text, /G4BE08\.s10 \(4096 bytes\)/);
  assert.doesNotMatch(moment.text, /in slot 10/);
  assert.deepEqual(JSON.parse(JSON.stringify(page.evRestoreJob(moment.state))), {
    tool: 'state_transfer', input: { session_id: 'w1-re4', op: 'import', artifact: 'a'.repeat(64) }, require_worker: 'w1' });
});

test('a failed or file-less snapshot offers no restore', () => {
  const failed = page.evMoment({ session_id: 'w1-re4' }, snapshot('failed', {}, 'ValueError: op: export | export_saved | import'));
  assert.equal(failed.state, null);
  assert.match(failed.text, /export_saved/);
  assert.equal(page.evMoment({ session_id: 'w1-re4' }, snapshot('succeeded', {})).state, null);
  assert.equal(page.evMoment({ session_id: 'w1-re4' }, snapshot('queued')).text, 'Save state is being prepared.');
});

test("another emulator's saved slot still restores by loading that slot", () => {
  const job = { tool: 'session_op', state: 'succeeded', input: { session_id: 'w2-psx', op: 'save_state', args: { slot: 60 } },
    output: { result: { slot: 1 } } };
  const moment = page.evMoment({ session_id: 'w2-psx' }, job);
  assert.equal(moment.snap, false);
  assert.equal(moment.text, 'Save state ready in slot 1.');
  assert.deepEqual(JSON.parse(JSON.stringify(page.evRestoreJob(moment.state))), {
    tool: 'session_op', input: { session_id: 'w2-psx', op: 'load_state', args: { slot: 1 } }, require_worker: 'w2' });
});

test('the report shows a snapshot once: it is its own portable export', () => {
  const source = between('async function evRequest(', 'function tkTokenSummary');
  assert.match(source, /state_export_job_id && x\.context\.state_export_job_id !== x\.context\.state_job_id/);
  assert.match(source, /moment = evMoment\(x\.context, job\)/);
  assert.match(between('$("#task-evidence").addEventListener("click"', 'addEventListener("keydown"'),
    /gbox\.api\("\/api\/jobs", evRestoreJob\(EV\.state\)\)/);
});
