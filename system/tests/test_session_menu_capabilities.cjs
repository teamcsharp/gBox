// #2518 / #2519: an emulator without save states (Cxbx-Reloaded) gets no Save / Load job that can only fail:
// the game menu says what is missing, the actions and the typed one-liners answer in words.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../clients/desktop/index.html'), 'utf8');
function between(start, end) {
  const a = html.indexOf(start), b = html.indexOf(end, a + start.length);
  assert.ok(a >= 0 && b > a, `missing desktop source boundary: ${start}`);
  return html.slice(a, b);
}

function capMissingFor(EMB) {
  const src = between('const CAP_WORDS = {', 'function pipMenu(x, y) {');
  const ctx = { EMB };
  vm.createContext(ctx);
  vm.runInContext(src + '\nthis.capMissing = capMissing;', ctx);
  return ctx.capMissing;
}

test('the docked session keeps its adapter and capabilities for the menu', () => {
  assert.match(html, /EMB\.adapter = mine\.adapter \|\| ""; EMB\.caps = mine\.capabilities \|\| \{\};/);
});

test('a Cxbx session says it has no save states; a Dolphin session says nothing', () => {
  const cxbx = capMissingFor({ adapter: 'cxbx', caps: { save_state: 'unsupported', load_state: 'unsupported', pause: 'unsupported', get_frame: 'supported' } });
  assert.equal(cxbx('save_state'), 'The cxbx emulator has no save states in gBox');
  assert.equal(cxbx('pause'), 'The cxbx emulator cannot pause in gBox');
  assert.equal(cxbx('get_frame'), '', 'a supported op has no reason');
  const dolphin = capMissingFor({ adapter: 'dolphin', caps: { save_state: 'supported' } });
  assert.equal(dolphin('save_state'), '');
  assert.equal(capMissingFor({})('save_state'), '', 'no capabilities known: nothing is disabled');
});

test('the game menu shows Save, Load, the slots and the film strip as unavailable with the reason', () => {
  const menu = between('function pipMenu(x, y) {', 'async function gameAction(a) {');
  assert.match(menu, /const noStates = capMissing\("save_state"\);/);
  assert.match(menu, /\["save", "💾 Save state", noStates\], \["load", "📂 Load state", noStates\]/);
  assert.match(menu, /\["slot-", "Save slot ◂ previous", noStates\]/);
  assert.match(menu, /\["strip", "⏪ Rewind \/ save-state film strip", noStates\]/);
  assert.match(menu, /disabled title="\$\{esc\(off\)\}"/, 'an unavailable entry is a disabled button that says why');
});

test('Save, Load and the strip answer in words instead of posting a job the emulator cannot run', () => {
  const act = between('async function gameAction(a) {', 'async function updateCheck()');
  const guard = act.indexOf('(a === "save" || a === "load" || a === "strip") && capMissing("save_state")) toast(capMissing("save_state"))');
  const save = act.indexOf('else if (a === "save") { toast("💾 Saving…")');
  assert.ok(guard >= 0 && save > guard, 'the guard comes before the Save job');
});

test('the typed or spoken "save state" / "pause" one-liners answer in words for that emulator', () => {
  const cmd = between('async function sessionCommand(text, context = null) {', 'async function instantCommand(');
  assert.match(cmd, /if \(ctx\.session_id === EMB\.sid && capMissing\(hit\[1\]\)\) return \{ say: capMissing\(hit\[1\]\) \+ "\." \};/);
  const post = cmd.indexOf('gbox.api("/api/jobs"');
  assert.ok(cmd.indexOf('capMissing(hit[1])') < post, 'the answer comes before any job is posted');
});
