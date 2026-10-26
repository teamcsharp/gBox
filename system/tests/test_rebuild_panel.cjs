const test = require('node:test'), assert = require('node:assert/strict');
const P = require('../clients/web/viz/rebuild-panel.js');

const LINES = ['Rebuilding JAYBUILT (windows, Python 3.12.13) from D:/gBox/system', '== 1/5 Code ==',
  'Code: runs from the share, nothing to pull on this PC.', '== 2/5 Python packages ==',
  '$ C:/venv/python.exe -m pip install -q --disable-pip-version-check --upgrade pip', '[ok]',
  '$ C:/venv/python.exe -m pip install -q --disable-pip-version-check "fastapi>=0.110"'];

test('the spinner is npx\'s braille cycle and wraps', () => {
  assert.equal(P.SPINNER.length, 10);
  assert.equal(P.spinnerFrame(0), '⠋'); assert.equal(P.spinnerFrame(1), '⠙'); assert.equal(P.spinnerFrame(10), '⠋'); assert.equal(P.spinnerFrame(-1), '⠏');
  assert.equal(P.statusText({ status: 'running', activity: 'Installing Python packages', tick: 3, name: 'X' }), '⠸ Installing Python packages…');
});

test('phase and activity come from the worker\'s headers and command lines', () => {
  assert.deepEqual(P.phaseOf(LINES), { n: 2, of: 5, title: 'Python packages' });
  assert.equal(P.phaseOf([]), null);
  assert.equal(P.activityOf(LINES), 'Installing Python packages');
  assert.equal(P.activityOf(LINES.slice(0, 6)), 'Upgrading pip');
  assert.equal(P.activityOf(LINES.slice(0, 3)), 'Updating code');
  assert.equal(P.activityOf(['== 5/5 Restart ==', 'Waiting for 2 game session(s) to be saved and closed and 0 other job(s) to finish (88 s left)...']), 'Waiting for games to close');
  assert.equal(P.activityOf(['$ /venv/bin/python -m gbox.hermes_activation --check-idle /home/x/gBox/system']), 'Checking that the Spark is idle');
  assert.equal(P.activityOf([]), 'Starting');
  assert.deepEqual(['$ git pull', '== 1/5 Code ==', '! pip could not upgrade', '[exit 1]', '[ok]', 'Done: code ok', 'plain'].map(P.lineClass),
    ['cmd', 'head', 'warn', 'bad', 'ok', 'ok', '']);
});

test('the console merges only the lines beyond what it has, by the job\'s running count, and keeps the last 200', () => {
  assert.deepEqual(P.mergeConsole(['a', 'b'], 2, ['c', 'd'], 4), ['a', 'b', 'c', 'd']);
  assert.deepEqual(P.mergeConsole(['a', 'b'], 2, ['a', 'b', 'c', 'd'], 4), ['a', 'b', 'c', 'd'], 'an over-fetch is trimmed');
  assert.deepEqual(P.mergeConsole(['a', 'b'], 2, ['x'], 2), ['a', 'b'], 'nothing new');
  assert.deepEqual(P.mergeConsole([], 0, [], 0), []);
  const many = Array.from({ length: 250 }, (_, i) => 'l' + i);
  const merged = P.mergeConsole(['old'], 1, many, 251);
  assert.equal(merged.length, P.KEEP); assert.equal(merged[0], 'l50'); assert.equal(merged.at(-1), 'l249');
});

test('a console answer moves the state: lines, pct, phase, then the outcome of the job', () => {
  const t0 = 1000;
  let s = P.initial({ name: 'JAYBUILT', workerId: 'w1', jobId: 'j1', now: t0 });
  s = P.applyJob(s, { state: 'running', seq: 3, pct: 12.5, lines: LINES.slice(0, 3) }, t0 + 1);
  assert.equal(s.status, 'running'); assert.equal(s.pct, 12.5); assert.deepEqual(s.phase, { n: 1, of: 5, title: 'Code' }); assert.equal(s.lines.length, 3);
  s = P.applyJob(s, { state: 'running', seq: 7, pct: 9, lines: LINES.slice(3) }, t0 + 2);
  assert.equal(s.pct, 12.5, 'the bar never moves backwards'); assert.equal(s.lines.length, 7); assert.equal(s.activity, 'Installing Python packages');
  const scheduled = P.applyJob(s, { state: 'succeeded', seq: 9, pct: 100, lines: ['== 5/5 Restart ==', 'Done'], restart: 'scheduled', steps: [{ step: 'restart', status: 'ok' }], failed: [] }, t0 + 3);
  assert.equal(scheduled.status, 'restarting'); assert.ok(scheduled.pct >= 92 && scheduled.pct < 100); assert.equal(scheduled.finishedAt, t0 + 3); assert.equal(scheduled.restart, 'scheduled');
  const deferred = P.applyJob(s, { state: 'succeeded', seq: 9, pct: 100, lines: ['Done'], restart: 'deferred' }, t0 + 3);
  assert.equal(deferred.status, 'done'); assert.equal(deferred.pct, 100);
  assert.match(P.statusText(deferred), /^⏸ JAYBUILT rebuilt; restart deferred$/);
  const invalid = P.applyJob(s, { state: 'invalid', seq: 9, lines: [], restart: 'blocked', failed: ['check'] }, t0 + 3);
  assert.equal(invalid.status, 'done'); assert.match(P.statusText(invalid), /^✗ JAYBUILT rebuilt; restart blocked \(failed: check\)$/);
  const failed = P.applyJob(s, { state: 'failed', seq: 9, lines: [], error: 'TimeoutError: boom' }, t0 + 3);
  assert.equal(failed.status, 'failed'); assert.equal(P.statusText(failed), '✗ Rebuild of JAYBUILT failed: TimeoutError: boom');
});

test('back online means the worker went away and returned, or came back under a new id; else a timeout', () => {
  const base = { ...P.initial({ name: 'JAYBUILT', workerId: 'w1', jobId: 'j1', now: 0 }), status: 'restarting', finishedAt: 1000 };
  const same = [{ name: 'JAYBUILT', id: 'w1', online: true }], other = [{ name: 'i9-NUC', id: 'w2', online: true }];
  let s = P.applyWorkers(base, same, 2000);
  assert.equal(s.status, 'restarting'); assert.equal(s.offlineSeen, false);
  assert.equal(P.statusText({ ...s, tick: 0 }), '⠋ Restarting JAYBUILT… its worker is shutting down');
  s = P.applyWorkers(s, null, 3000);
  assert.equal(s.status, 'restarting', 'no answer from the control plane proves nothing');
  s = P.applyWorkers(s, other, 4000);
  assert.equal(s.offlineSeen, true); assert.equal(s.status, 'restarting');
  assert.equal(P.statusText({ ...s, tick: 1 }), '⠙ Restarting JAYBUILT… waiting for it to come back');
  s = P.applyWorkers(s, [{ name: 'JAYBUILT', id: 'w1', online: false }], 5000);
  assert.equal(s.status, 'restarting');
  s = P.applyWorkers(s, [{ name: 'JAYBUILT', id: 'w7', online: true }], 6000);
  assert.equal(s.status, 'online'); assert.equal(s.pct, 100); assert.equal(s.newWorkerId, 'w7'); assert.equal(s.onlineAt, 6000);
  assert.equal(P.statusText(s), '✓ JAYBUILT is back online');
  const fresh = P.applyWorkers(base, [{ name: 'JAYBUILT', id: 'w9', online: true }], 2000);
  assert.equal(fresh.status, 'online', 'a new worker id for the name is the restarted worker');
  const late = P.applyWorkers(base, same, 1000 + P.TIMEOUT_MS + 1);
  assert.equal(late.status, 'timeout'); assert.equal(P.statusText(late), '✗ JAYBUILT did not come back within 5 min');
  assert.equal(P.applyWorkers(base, same, 1000 + P.TIMEOUT_MS).status, 'restarting');
});

test('render shows the PC, the phase, every console line escaped, the status and the loading bar', () => {
  let s = P.initial({ name: 'i9-NUC', workerId: 'w2', jobId: 'j', now: 0 });
  s = P.applyJob(s, { state: 'running', seq: 2, pct: 37.5, lines: ['== 2/5 Python packages ==', '$ pip install "a<b>"'] }, 1);
  const html = P.render({ ...s, tick: 2 });
  assert.match(html, /Rebuild &amp; relaunch · i9-NUC/);
  assert.match(html, /data-rbp-phase>2\/5 Python packages</);
  assert.match(html, /class="rbp-l head">== 2\/5 Python packages ==</);
  assert.match(html, /class="rbp-l cmd">\$ pip install &#34;a&#60;b&#62;&#34;</);
  assert.match(html, /data-rbp-status>⠹ Installing Python packages…</);
  assert.match(html, /aria-valuenow="37.5"/); assert.match(html, /width:37.5%/);
  assert.match(html, /data-rbp-close/);
  assert.match(P.CSS, /#rebuild-panel\.rbp-pip\{inset:0/); assert.match(P.CSS, /\.rbp-con\{.*monospace/);
});

test('the controller polls the console with after=, then the workers, and tells once when the PC is back', async () => {
  const calls = [], online = [], ended = [];
  let now = 10000;
  const answers = {
    '/api/jobs/j1/console?after=0': { state: 'running', seq: 2, pct: 10, lines: ['== 1/5 Code ==', '$ git pull'] },
    '/api/jobs/j1/console?after=2': { state: 'running', seq: 3, pct: 50, lines: ['[ok]'] },
    '/api/jobs/j1/console?after=3': { state: 'succeeded', seq: 4, pct: 100, lines: ['Done'], restart: 'scheduled', steps: [], failed: [] },
  };
  let workers = [{ name: 'JAYBUILT', id: 'w1', online: true }];
  const api = async (path, body, method) => { calls.push([path, body, method]); if (path === '/api/workers') return workers; if (!(path in answers)) throw Error('offline'); return answers[path]; };
  const rendered = [];
  const ctl = P.create({ api, name: 'JAYBUILT', workerId: 'w1', jobId: 'j1', now: () => now, render: s => rendered.push(s), onOnline: s => online.push(s), onEnd: s => ended.push(s) });
  await ctl.poll(); await ctl.poll();
  assert.deepEqual(calls.map(c => c[0]), ['/api/jobs/j1/console?after=0', '/api/jobs/j1/console?after=2']);
  assert.equal(calls[0][2], 'GET');
  assert.equal(ctl.state().status, 'running'); assert.deepEqual(ctl.state().lines, ['== 1/5 Code ==', '$ git pull', '[ok]']); assert.equal(ctl.state().pct, 50);
  await ctl.poll();
  assert.equal(ctl.state().status, 'restarting'); assert.equal(ctl.state().finishedAt, now);
  assert.equal(ended.length, 0);
  await ctl.poll();                                    // the old worker still heartbeats under its id
  assert.equal(calls.at(-1)[0], '/api/workers'); assert.equal(ctl.state().status, 'restarting');
  workers = null; await ctl.poll();                     // the control plane itself answers nothing for a moment
  assert.equal(ctl.state().status, 'restarting');
  workers = [{ name: 'JAYBUILT', id: 'w5', online: true }]; await ctl.poll();
  assert.equal(ctl.state().status, 'online'); assert.equal(online.length, 1); assert.equal(ended.length, 1);
  await ctl.poll(); await ctl.poll();
  assert.equal(online.length, 1, 'told once'); assert.equal(calls.filter(c => c[0] === '/api/workers').length, 3, 'no polling after the end');
  ctl.tick(); assert.equal(rendered.at(-1).tick, 1); assert.match(rendered.at(-1).text, /back online/);
  ctl.stop(); const before = rendered.length; ctl.tick(); assert.equal(rendered.length, before);
});

test('a failed console read keeps polling and says so; a rebuild that ends without a restart ends the follow', async () => {
  let fail = true, now = 0;
  const api = async path => { if (fail) throw Error('502 Bad Gateway'); return { state: 'succeeded', seq: 1, pct: 100, lines: ['Done'], restart: 'skipped' }; };
  const ended = [];
  const ctl = P.create({ api, name: 'lilspark', workerId: 'w0', jobId: 'j', now: () => now, onEnd: s => ended.push(s) });
  await ctl.poll();
  assert.equal(ctl.state().status, 'running'); assert.match(ctl.state().apiError, /502/);
  assert.match(P.statusText(ctl.state()), /Starting… \(502 Bad Gateway\)$/);
  fail = false; await ctl.poll();
  assert.equal(ctl.state().status, 'done'); assert.equal(ended.length, 1); assert.equal(ctl.state().apiError, '');
  assert.equal(P.statusText(ctl.state()), '✓ lilspark rebuilt; restart skipped');
});

test('menu items list online PCs only, the PiP\'s PC first, then this PC, the Spark and the rest', () => {
  const ws = [{ name: 'i9-NUC', id: 'a', os: 'windows', online: true }, { name: 'lilspark', id: 'b', os: 'linux', online: true },
    { name: 'JAYBUILT', id: 'c', os: 'windows', online: true }, { name: 'OLD', id: 'd', os: 'windows', online: false }, { name: 'JAYBUILT', id: 'c2', os: 'windows', online: true }];
  const items = P.pcs(ws, 'JAYBUILT', 'i9-NUC');
  assert.deepEqual(items.map(p => p.name), ['i9-NUC', 'JAYBUILT', 'lilspark']);
  assert.deepEqual(items.map(p => p.label), ['⟳ Rebuild & relaunch i9-NUC', '⟳ Rebuild & relaunch JAYBUILT (this PC)', '⟳ Rebuild & relaunch lilspark (the Spark)']);
  assert.equal(items[0].current, true); assert.equal(items[1].here, true);
  assert.deepEqual(P.pcs(null), []); assert.deepEqual(P.pcs([{ online: true }]), []);
});

test('mount draws once, patches the console and bar, closes on its button and hides after the PC is back', async () => {
  // a small DOM stand-in: enough of querySelector / innerHTML / dataset / classList for mount()
  function el(tag) {
    const node = { tag, children: [], attrs: {}, dataset: {}, style: {}, classes: new Set(), listeners: {}, _html: '', removed: false, scrollTop: 0, scrollHeight: 999, textContent: '',
      classList: { toggle: (c, on) => { on ? node.classes.add(c) : node.classes.delete(c); } },
      addEventListener: (type, fn) => { node.listeners[type] = fn; }, remove: () => { node.removed = true; },
      setAttribute: (k, v) => { node.attrs[k] = v; },
      querySelector: sel => {
        const key = sel.replace(/[\[\]]/g, '').replace(/^\./, '');
        if (node._html.includes(sel.startsWith('.') ? `class="${key}` : key)) { node.parts ||= {}; return node.parts[sel] ||= Object.assign(el('part'), { querySelector: () => node.parts[sel + ' i'] ||= el('i') }); }
        return null;
      },
      get innerHTML() { return node._html; }, set innerHTML(v) { node._html = v; node.childElementCount = (v.match(/class="rbp-l/g) || []).length; } };
    return node;
  }
  const host = el('div');
  let now = 0, workers = [{ name: 'PC', id: 'w1', online: true }];
  const answers = [{ state: 'running', seq: 1, pct: 20, lines: ['== 1/5 Code =='] }, { state: 'succeeded', seq: 2, pct: 100, lines: ['Done'], restart: 'scheduled' }];
  const api = async path => path === '/api/workers' ? workers : answers.shift() || { state: 'succeeded', seq: 2, pct: 100, lines: [], restart: 'scheduled' };
  const timers = [];
  const realSetInterval = globalThis.setInterval, realClear = globalThis.clearInterval, realTimeout = globalThis.setTimeout;
  globalThis.setInterval = (fn, ms) => { timers.push({ fn, ms }); return timers.length; }; globalThis.clearInterval = id => { timers[id - 1].cleared = true; };
  const hides = []; globalThis.setTimeout = (fn, ms) => { hides.push({ fn, ms }); return 1; };
  let closed = 0;
  try {
    const panel = P.mount(host, { api, name: 'PC', workerId: 'w1', jobId: 'j', now: () => now, pip: () => true, onClose: () => closed++ });
    assert.equal(host.id, 'rebuild-panel'); assert.ok(host.classes.has('rbp-pip')); assert.equal(host.dataset.status, 'running');
    assert.match(host.innerHTML, /Rebuild &amp; relaunch · PC/);
    await new Promise(r => setImmediate(r));                    // the first poll inside mount
    assert.equal(panel.state().lines.length, 1);
    const con = host.querySelector('[data-rbp-con]'); assert.match(con.innerHTML, /== 1\/5 Code ==/); assert.equal(con.scrollTop, 999, 'autoscroll');
    assert.equal(host.querySelector('.rbp-bar').attrs['aria-valuenow'], '20');
    assert.deepEqual(timers.map(t => t.ms), [1500, 90]);
    await panel.poll(); assert.equal(host.dataset.status, 'restarting');
    workers = [{ name: 'PC', id: 'w2', online: true }]; await panel.poll();
    assert.equal(host.dataset.status, 'online'); assert.equal(hides.length, 1); assert.equal(hides[0].ms, 8000);
    assert.match(host.querySelector('[data-rbp-status]').textContent, /PC is back online/);
    hides[0].fn();                                               // the auto-hide
    assert.equal(host.removed, true); assert.equal(closed, 1); assert.ok(timers.every(t => t.cleared));
    panel.close(); assert.equal(closed, 1, 'closing twice is one close');
    const again = el('div');
    const p2 = P.mount(again, { api: async () => ({ state: 'running', seq: 0, pct: 0, lines: [] }), name: 'PC', workerId: 'w1', jobId: 'j', pip: () => false });
    assert.ok(again.classes.has('rbp-float'));
    again.listeners.click({ target: { closest: sel => sel === '[data-rbp-close]' ? {} : null } });
    assert.equal(again.removed, true); assert.equal(p2.state().status, 'running');
  } finally { globalThis.setInterval = realSetInterval; globalThis.clearInterval = realClear; globalThis.setTimeout = realTimeout; }
});
