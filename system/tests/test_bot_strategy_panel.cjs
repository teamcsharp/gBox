// The PiP's bot strategy panel: checkbox + intensity slider per strategy, drag reorder; every change POSTs /api/mercs/strategy.
const test = require('node:test');
const assert = require('node:assert');
const S = require('../clients/desktop/bot-strategy-panel.js');
const mk = names => ({ title: 're5', strategies: names.map((n, i) => ({ name: n, label: n.toUpperCase(), help: 'h ' + n, enabled: i !== 1, intensity: 0.5 })) });
const VIEW = mk(['survive', 'combo', 'score']);

test('renders ordered rows with a checkbox and an intensity slider', () => {
  const h = S.html(VIEW);
  assert.match(h, /data-bs-on="survive" checked/);
  assert.doesNotMatch(h, /data-bs-on="combo" checked/);
  assert.match(h, /type="range" data-bs-int="score" min="0" max="1" step="0.05" value="0.5"/);
  assert.ok(h.indexOf('data-bs-name="survive"') < h.indexOf('data-bs-name="combo"'));
  assert.match(h, /draggable="true"/);
});

test('reorder drops a row before the target', () => {
  assert.deepEqual(S.reorder(['a', 'b', 'c'], 'c', 'a'), ['c', 'a', 'b']);
  assert.deepEqual(S.reorder(['a', 'b', 'c'], 'a', 'c'), ['b', 'a', 'c']);
  assert.deepEqual(S.reorder(['a', 'b'], 'a', 'a'), ['a', 'b']);
  assert.deepEqual(S.reorder(['a', 'b'], 'x', 'a'), ['a', 'b']);
});

test('open reads, set/move/reset POST and show the server reply', async () => {
  const calls = [];
  const api = async (path, body, method) => { calls.push([path, body, method]); return method === 'POST' && body.reorder ? mk(body.reorder) : VIEW; };
  const p = S.create({ api, doc: null });
  await p.open('re5');
  assert.equal(calls[0][0], '/api/mercs/strategy?title=re5');
  assert.equal(calls[0][2], 'GET');
  await p.set('combo', { enabled: true });
  assert.deepEqual(calls[1], ['/api/mercs/strategy', { title: 're5', values: { combo: { enabled: true } } }, 'POST']);
  await p.move('score', 'survive');
  assert.deepEqual(calls[2][1].reorder, ['score', 'survive', 'combo']);
  assert.deepEqual(p.state().view.strategies.map(s => s.name), ['score', 'survive', 'combo']);
  await p.reset();
  assert.deepEqual(calls[3][1], { title: 're5', reset: true });
});

test('a failed request shows the error and keeps the last view', async () => {
  let fail = false;
  const api = async () => { if (fail) throw new Error('boom'); return VIEW; };
  const p = S.create({ api, doc: null });
  await p.open('re5'); fail = true; await p.set('combo', { intensity: 1 });
  assert.equal(p.state().message, 'boom');
  assert.equal(p.state().view, VIEW);
});

test('titleFor maps game names', () => {
  assert.equal(S.titleFor('Resident Evil 6'), 're6');
  assert.equal(S.titleFor('BIOHAZARD 5 Mercenaries'), 're5');
  assert.equal(S.titleFor('Doom'), null);
});
