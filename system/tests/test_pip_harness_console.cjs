/* The PiP harness console: the watched tools, the dismissible controls, and the scrolling feed contract. */
const test = require('node:test'), assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path');
const SRC = fs.readFileSync(path.join(__dirname, '../clients/web/viz/pip-harness-console.js'), 'utf8');
const SHELL = fs.readFileSync(path.join(__dirname, '../clients/web/index.html'), 'utf8');

test('the shell loads the console', () => {
  assert.match(SHELL, /<script src="\/viz\/pip-harness-console\.js"><\/script>/);
});

test('it watches the harness, Ghidra, ROM and runtime tools', () => {
  assert.match(SRC, /switch_mods\|re5_mods\|re6_mods/);
  assert.match(SRC, /ghidra/);
  assert.match(SRC, /launch_game\|session_op/);
  assert.match(SRC, /build\|disc\|rom\|iso\|patch/);
});

test('it reads the streaming job console, not just the final job record', () => {
  assert.match(SRC, /\/api\/jobs\/\$\{encodeURIComponent\(id\)\}\/console\?after=/);
  assert.match(SRC, /seqByJob/);
  assert.match(SRC, /progress_log/);
});

test('the panel can be collapsed and dismissed, and a pill brings it back', () => {
  assert.match(SRC, /data-phc-toggle/);
  assert.match(SRC, /data-phc-hide/);
  assert.match(SRC, /pip-harness-pill/);
  assert.match(SRC, /function show\(\)/);
  assert.match(SRC, /function hide\(\)/);
});

test('it animates new lines, a scanline and a spinner with reduced-motion support', () => {
  assert.match(SRC, /@keyframes phc-in/);
  assert.match(SRC, /@keyframes phc-scan/);
  assert.match(SRC, /@keyframes phc-blink/);
  assert.match(SRC, /prefers-reduced-motion/);
  assert.match(SRC, /SPIN/);
});

test('the feed is bounded and de-duplicates repeated poll tails', () => {
  assert.match(SRC, /const KEEP = 220/);
  assert.match(SRC, /state\.seen/);
  assert.match(SRC, /splice\(0, state\.lines\.length - KEEP\)/);
});
