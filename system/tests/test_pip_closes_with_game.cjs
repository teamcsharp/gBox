// #1934: quitting a game left its picture-in-picture window behind; the PiP now closes when its session ends.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const html = fs.readFileSync(path.join(__dirname, '../clients/web/index.html'), 'utf8');

test('the session follow poll hides the PiP of a game that ended', () => {
  const a = html.indexOf('setInterval(async () => {                                  // a session replaced elsewhere');
  assert.ok(a >= 0, 'follow poll present');
  const poll = html.slice(a, html.indexOf('}, 3000);', a));
  assert.match(poll, /else if \(s && s\.state !== "running" && active\?\.sid === sid && cur !== "Sessions"\) \{ active = null; pip\(\); \}/);
  assert.match(poll, /if \(s\?\.state === "ended" && s\.replaced_by\) followSession\(sid, s\.replaced_by\);/, 'a replaced session is still followed first');
});

test('Stop hides the PiP before the stop job and returns to the Library', () => {
  const a = html.indexOf('async function hardStop(sid, btn)');
  const fn = html.slice(a, html.indexOf('async function resetGame', a));
  assert.match(fn, /if \(wasActive\) \{ active = null; pip\(\); \}/);
  assert.match(fn, /show\("Library"\);/);
});
