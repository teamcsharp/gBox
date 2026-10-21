const { test } = require('node:test'), assert = require('node:assert/strict');
const D = require('../clients/desktop/player-damage-view');
const path = '/api/sessions/worker-session/damage/runs/run_123456';
const artifact = sha => 'https://gbox.invalid/api/artifacts/' + sha + '?token=local';

test('damage button only opens a same-service event ledger, never an arbitrary URL', () => {
  assert.match(D.button({ ledger: path, events: 120 }), /120 events/);
  for (const ledger of ['https://evil.test/', path + '?token=secret', path + '/../../jobs', 'javascript:alert(1)']) {
    assert.equal(D.button({ ledger }), '');
    assert.throws(() => D.pager(ledger, () => {}), /Invalid damage batch/);
  }
});

test('large batches are requested one bounded page at a time and concurrent clicks share the request', async () => {
  const calls = []; let resolve;
  const p = D.pager(path, url => { calls.push(url); return new Promise(r => { resolve = r; }); });
  const first = p.load(75), repeated = p.load(100);
  assert.equal(first, repeated); assert.deepEqual(calls, [path + '?offset=75&limit=25']);
  resolve({ ok: true, data: { total: 10000, events: [{ event_id: 'event-76' }], next_offset: 100 } });
  const page = await first;
  assert.equal(page.previous, 50); assert.equal(page.next_offset, 100); assert.equal(page.offset, 75);
  assert.equal(page.events.length, 1);
});

test('closing a viewer discards a late answer and starts no further reads', async () => {
  let resolve, reads = 0;
  const p = D.pager(path, () => { reads++; return new Promise(r => { resolve = r; }); });
  const pending = p.load(); p.close();
  resolve({ ok: true, data: { total: 1, events: [{ event_id: 'hit' }] } });
  assert.equal(await pending, null); assert.equal(await p.load(25), null); assert.equal(reads, 1);
});

test('failed reads remain retryable and malformed oversized pages never render as a complete result', async () => {
  let n = 0;
  const p = D.pager(path, async () => ++n === 1 ? { ok: false, error: 'Offline' }
    : n === 2 ? { ok: true, data: { total: 100, events: Array(26).fill({}) } }
      : { ok: true, data: { total: 0, events: [], next_offset: -5 } });
  await assert.rejects(p.load(), /Offline/); await assert.rejects(p.load(), /incomplete/);
  assert.equal((await p.load()).next_offset, null); assert.equal(n, 3);
});

test('event evidence distinguishes unavailable state and delayed screenshot without fabricating images', () => {
  const html = D.eventHTML({ observed_at: 100, event_id: 'event-one', round_id: 'round-one', hp_before: 30000,
    hp_after: 29950, state: 'done', save_state: { state: 'skipped_disruptive', detail: 'Would reload this game.' },
    evidence: { stream: { state: 'done', source_at: 100.5 }, map: { state: 'failed', detail: 'No geometry' } },
    receipt: 'a'.repeat(64), attachments: [] }, artifact);
  assert.match(html, /500 ms from detected HP loss/); assert.match(html, /skipped_disruptive/);
  assert.match(html, /Self-damage: unknown/); assert.match(html, /Original event and capture receipt/);
  assert.doesNotMatch(html, /<img/);
});

test('report data and artifact metadata are escaped; unvalidated artifact paths are omitted', () => {
  const html = D.eventHTML({ event_id: '<script>bad</script>', save_state: { state: 'failed', detail: '<img onerror=bad>' },
    attachments: [{ sha256: 'b'.repeat(64), type: 'image/svg+xml', name: '<danger>' },
      { sha256: '../secret', type: 'image/png', name: 'bad-path' }] }, artifact);
  assert.doesNotMatch(html, /<script>|<danger>|bad-path|<img onerror/);
  assert.match(html, /&#60;danger&#62;/); assert.match(html, /loading="lazy"/);
});
