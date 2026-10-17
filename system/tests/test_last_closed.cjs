const { test } = require('node:test');
const assert = require('node:assert/strict');
const { lastClosedSession } = require('../clients/desktop/last-closed.js');

test('picks the most recently ended session for this worker, ignoring other PCs', () => {
  const all = { ok: true, data: [
    { session_id: 'a', state: 'running', game_id: 'x', title: 'Running', detail: { worker_name: 'PC' } },
    { session_id: 'b', state: 'ended', game_id: 'sc2', title: 'Soul Calibur II', ended: 100, started: 50, detail: { worker_name: 'PC' } },
    { session_id: 'c', state: 'ended', game_id: 'other', title: 'Other PC game', ended: 200, started: 150, detail: { worker_name: 'OtherPC' } },
    { session_id: 'd', state: 'ended', game_id: 'sc2b', title: 'Soul Calibur II (later)', ended: 300, started: 250, detail: { worker_name: 'PC' } },
  ]};
  assert.equal(lastClosedSession(all, 'PC').session_id, 'd');
  assert.equal(lastClosedSession(all, 'OtherPC').session_id, 'c');
});

test('ignores live sessions and ended sessions without a game', () => {
  const all = { ok: true, data: [
    { session_id: 'live', state: 'running', game_id: 'x', title: 'Live', detail: { worker_name: 'PC' } },
    { session_id: 'nogame', state: 'ended', game_id: null, detail: { worker_name: 'PC' } },
  ]};
  assert.equal(lastClosedSession(all, 'PC'), null);
});

test('tolerates a failed or empty listing and an empty worker filter', () => {
  assert.equal(lastClosedSession({ ok: false }, 'PC'), null);
  assert.equal(lastClosedSession(null, 'PC'), null);
  assert.equal(lastClosedSession({ ok: true, data: [] }, 'PC'), null);
  const all = { ok: true, data: [
    { session_id: 'e', state: 'ended', game_id: 'g', ended: 10, started: 1, detail: { worker_name: 'A' } },
    { session_id: 'f', state: 'ended', game_id: 'g2', ended: 20, started: 2, detail: { worker_name: 'B' } },
  ]};
  assert.equal(lastClosedSession(all, '').session_id, 'f', 'an empty worker filter returns the newest ended session');
});
