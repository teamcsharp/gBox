// PiP retains its watched game across restarts; explicit Stop still closes it.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const html = fs.readFileSync(path.join(__dirname, '../clients/web/index.html'), 'utf8');

test('the session follow poll retains PiP and follows both watched roles through replacement', () => {
  const a = html.indexOf('setInterval(async () => {                                  // a session replaced elsewhere');
  assert.ok(a >= 0, 'follow poll present');
  const poll = html.slice(a, html.indexOf('}, 3000);', a));
  assert.doesNotMatch(poll, /active = null/);
  assert.match(poll, /\[playing, active\?\.sid\]/);
  assert.match(poll, /GBoxSessionContinuity.resolve/);
  assert.match(poll, /followSession\(sid, next.session_id\)/);
});

test('Stop hides the PiP before the stop job and returns to the Library', () => {
  const a = html.indexOf('async function hardStop(sid, btn)');
  const fn = html.slice(a, html.indexOf('async function resetGame', a));
  assert.match(fn, /if \(wasActive\) \{ active = null; pip\(\); \}/);
  assert.match(fn, /show\("Library"\);/);
});
