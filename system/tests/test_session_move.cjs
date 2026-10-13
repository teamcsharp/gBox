const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { targets, run } = require('../clients/web/viz/session-move.js');

const W = [
  { id: 'spark', name: 'spark-dgx', os: 'linux', online: true },
  { id: 'jay', name: 'JAYBUILTFINALE', os: 'windows', online: true },
  { id: 'nuc', name: 'i9-NUC', os: 'windows', online: true },
  { id: 'old', name: 'OLDPC', os: 'windows', online: false },
];

test('a Spark game offers this PC first, then the other online PCs, never its own machine', () => {
  const t = targets('spark-abc', W, 'JAYBUILTFINALE');
  assert.deepEqual(t.map(x => [x.kind, x.to]), [['here', 'JAYBUILTFINALE'], ['pc', 'i9-NUC']]);
  assert.equal(t[0].label, 'Bring to this PC');
});

test('a game on another PC offers bringing it here and loading it on the main computer', () => {
  const t = targets('nuc-1', W, 'JAYBUILTFINALE');
  assert.deepEqual(t.map(x => [x.kind, x.to]), [['here', 'JAYBUILTFINALE'], ['main', 'spark-dgx']]);
  assert.equal(t[1].label, 'Load on the main computer');
});

test('a game already on this PC can go to the main computer or another PC; offline workers are hidden', () => {
  const t = targets('jay-9', W, 'JAYBUILTFINALE');
  assert.deepEqual(t.map(x => x.to), ['spark-dgx', 'i9-NUC']);
  assert.ok(!t.some(x => x.to === 'OLDPC'));
});

test('a plain browser keeps a Windows target for Spark games', () => {
  assert.deepEqual(targets('spark-1', W, '').map(x => x.to), ['JAYBUILTFINALE', 'i9-NUC']);
});

function fakeIo(jobs) {
  const calls = [], shown = [], steps = [], failed = [], opened = [];
  return {
    calls, shown, steps, failed, opened,
    io: {
      api: async (p, body) => { calls.push([p, body]); return jobs.shift(); },
      show: (t, sub, shot) => shown.push({ t, sub, shot }),
      progress: (pct, msg) => steps.push([pct, msg]),
      fail: m => failed.push(m), done: async sid => opened.push(sid),
      frame: sid => `/frame/${sid}`, delay: async () => {},
    },
  };
}

test('the move runs the swap job behind the loading screen and opens the new session', async () => {
  const f = fakeIo([{ id: 'j1', state: 'running', progress: { pct: 30, msg: 'Saving state' } },
                    { id: 'j1', state: 'running', progress: { pct: 70, msg: 'Loading state on JAYBUILTFINALE' } },
                    { id: 'j1', state: 'succeeded', output: { session_id: 'jay-new' } }]);
  const r = await run(f.io, { sid: 'spark-abc', to: 'JAYBUILTFINALE', label: 'Bring to this PC', title: 'PSO', mod: 'm1' });
  assert.deepEqual(f.calls[0], ['/api/sessions/spark-abc/swap', { mod: 'm1', to: 'JAYBUILTFINALE', keep_state: true }]);
  assert.equal(f.calls[1][0], '/api/jobs/j1');
  assert.equal(f.shown[0].shot, '/frame/spark-abc');
  assert.match(f.shown[0].t, /PSO → Bring to this PC/);
  assert.deepEqual(f.steps.map(s => s[1]).slice(1, 3), ['Saving state', 'Loading state on JAYBUILTFINALE']);
  assert.equal(f.steps.at(-1)[0], 100);
  assert.deepEqual(f.opened, ['jay-new']);
  assert.equal(r.ok, true);
});

test('a refused or failed move stays on the loading screen with the reason and opens nothing', async () => {
  const f = fakeIo([{ id: 'j2', state: 'failed', error: "i9-NUC has no Dolphin" }]);
  const r = await run(f.io, { sid: 'jay-1', to: 'i9-NUC' });
  assert.equal(r.ok, false);
  assert.match(f.failed[0], /i9-NUC has no Dolphin.*keeps running/);
  assert.deepEqual(f.opened, []);
});

test('the session chip menu is wired to the move targets and the loader shows the frame', () => {
  const html = fs.readFileSync(path.join(__dirname, '../clients/web/index.html'), 'utf8');
  assert.match(html, /<script src="\/viz\/session-move.js"><\/script>/);
  assert.match(html, /GBoxSessionMove\.targets\(sid, TRAY\.ws/);
  assert.match(html, /data-a="move" data-to=/);
  assert.match(html, /moveSession\(sid, mb\.dataset\.to, mb\.dataset\.label\)/);
  assert.match(html, /id="ldshot"/);
  assert.match(html, /show\(title, sub, shot\)/);
  assert.match(html, /\$\("#ldcancel"\)\.style\.display = \$\("#ldlocal"\)\.style\.display = "none"/);   // no Cancel mid-move
});
