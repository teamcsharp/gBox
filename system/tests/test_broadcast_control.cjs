// The broadcast controls in the clients (clients/web/viz/broadcast.js, docs/broadcast.md): the On air button's state and
// click, the watching heartbeat that makes the program follow what the operator watches, and the Sessions list's bar.
const { test } = require('node:test');
const assert = require('node:assert/strict');

function fakeTimers() {
  const timers = [];
  globalThis.setInterval = (fn, ms) => { timers.push({ fn, ms }); return timers.length; };
  globalThis.clearInterval = id => { if (timers[id - 1]) timers[id - 1].fn = () => {}; };
  return timers;
}
const timers = fakeTimers();
const BC = require('../clients/web/viz/broadcast.js');
const tick = () => new Promise(r => setImmediate(r));

function el(id) {
  const attrs = {};
  const classes = new Set();
  return {
    id, attrs, hidden: false, disabled: false, textContent: '', innerHTML: '', title: '', src: '', dataset: {}, onclick: null,
    setAttribute(k, v) { attrs[k] = String(v); }, getAttribute(k) { return attrs[k]; },
    classList: { toggle(c, on) { if (on) classes.add(c); else classes.delete(c); }, contains: c => classes.has(c) },
    querySelectorAll() { return []; }, insertAdjacentHTML() {},
  };
}
function doc(ids) {
  const map = Object.fromEntries(ids.map(i => [i, el(i)]));
  const d = { head: { append() {} }, hidden: false, getElementById: id => map[id] || null, createElement: () => el('style') };
  for (const e of Object.values(map)) e.ownerDocument = d;
  return d;
}

test('the On air button: pinned, on air by auto, or off air with what is on', () => {
  const pinned = BC.state({ mode: 'session', target: 's1', session_id: 's1' }, 's1');
  assert.deepEqual([pinned.pressed, pinned.label, pinned.next], [true, 'On air (pinned)', { session_id: 'auto' }]);
  const auto = BC.state({ mode: 'auto', session_id: 's1', why: 'following what you watch' }, 's1');
  assert.deepEqual([auto.pressed, auto.label, auto.next], [true, 'On air', { session_id: 's1' }]);
  assert.match(auto.title, /following what you watch/);
  const off = BC.state({ mode: 'auto', session_id: 's2', title: 'RE4', pc: 'lilspark' }, 's1');
  assert.deepEqual([off.pressed, off.label, off.next], [false, 'Put on air', { session_id: 's1' }]);
  assert.match(off.title, /On air now: RE4 on lilspark/);
  assert.equal(BC.state(null, 's1').pressed, false);
  assert.match(BC.button('s"1'), /id="onairbtn" data-sid="s&#34;1"/);
});

test('the Broadcast bar says what is on air, why, and how it holds', () => {
  assert.equal(BC.line({ mode: 'auto', session_id: null, why: 'no game is running' }), 'Nothing on air · no game is running · auto');
  assert.equal(BC.line({ mode: 'auto', session_id: 's', title: 'DOA2', pc: 'lilspark', state: 'live', why: 'following what you watch' }),
    'On air: DOA2 on lilspark · following what you watch');
  assert.equal(BC.line({ mode: 'session', session_id: 's', title: 'DOA2', state: 'slate' }), 'On air: DOA2 · waiting for its picture · pinned');
  assert.equal(BC.line({ mode: 'pc', target: 'i9nuc', session_id: 's', title: 'SC2', state: 'hold' }),
    'On air: SC2 · holding the last picture · pinned to i9nuc');
  assert.equal(BC.line({ mode: 'pc', target: 'jaybuilt', session_id: null, why: 'jaybuilt is not running a game' }),
    'Nothing on air · jaybuilt is not running a game · pinned to jaybuilt');
});

test('a new link lists its program URLs per network, the token shown once', () => {
  const made = { name: 'Pine Box', program: { lan: { mjpeg: 'http://l/p.mjpg?token=gbb_x', ts: 'http://l/p.ts?token=gbb_x', hls: 'h', jpeg: 'j' },
    tailnet: { mjpeg: 'http://t/p.mjpg?token=gbb_x' } }, feeds: { lan: 'http://l/api/broadcast/feeds?token=gbb_x' } };
  const rows = BC.links(made);
  assert.deepEqual(rows.map(r => `${r.where}/${r.format}`), ['lan/mjpeg', 'lan/ts', 'lan/hls', 'lan/jpeg', 'tailnet/mjpeg', 'lan/feeds']);
  assert.deepEqual(BC.links(null), []);
});

test('watching: reported on every change, then once a minute while the app is visible', async () => {
  const sent = [];
  const api = (path, body) => { sent.push([path, body]); return Promise.resolve({}); };
  const d = { hidden: false };
  BC.watching('s1', { api, doc: d });
  BC.watching('s1', { api, doc: d });
  BC.watching('s2', { api, doc: d });
  BC.watching(null, { api, doc: d });
  assert.deepEqual(sent, [['/api/broadcast/watching', { session_id: 's1' }], ['/api/broadcast/watching', { session_id: 's2' }],
    ['/api/broadcast/watching', { session_id: null }]]);
  const beat = timers.find(t => t.ms === BC.HEARTBEAT_MS);
  assert.ok(beat, 'one heartbeat timer');
  beat.fn();
  assert.equal(sent.length, 3, 'nothing watched: no heartbeat');
  BC.watching('s3', { api, doc: d });
  BC._W.sent = 0;
  d.hidden = true; beat.fn();
  assert.equal(sent.length, 4, 'a hidden app is not watching');
  d.hidden = false; beat.fn();
  assert.deepEqual(sent.at(-1), ['/api/broadcast/watching', { session_id: 's3' }]);
  assert.equal(timers.filter(t => t.ms === BC.HEARTBEAT_MS).length, 1);
  const failing = () => Promise.reject(new Error('404 Not Found'));
  BC.watching('s4', { api: failing, doc: d });                      // an older server: nothing breaks
  await tick();
});

test('mount: the button shows the program and a click switches it', async () => {
  const d = doc(['onairbtn']);
  const calls = [];
  let program = { mode: 'auto', session_id: 'other', title: 'RE4' };
  const api = async (path, body) => {
    calls.push([path, body]);
    if (path === '/api/broadcast') return { program };
    program = body.session_id === 'auto' ? { mode: 'auto', session_id: 'other' } : { mode: 'session', target: body.session_id, session_id: body.session_id };
    return { program };
  };
  const ctl = BC.mount({ ownerDocument: d }, { sid: 's1', api });
  await tick();
  const btn = d.getElementById('onairbtn');
  assert.equal(btn.attrs['aria-pressed'], 'false');
  await btn.onclick();
  assert.deepEqual(calls.at(-1), ['/api/broadcast/program', { session_id: 's1' }]);
  assert.deepEqual([btn.attrs['aria-pressed'], btn.attrs['aria-label']], ['true', 'On air (pinned)']);
  await btn.onclick();
  assert.deepEqual(calls.at(-1), ['/api/broadcast/program', { session_id: 'auto' }]);
  assert.equal(btn.attrs['aria-pressed'], 'false');
  const err = async () => { throw new Error('403 automation never switches the program'); };
  const ctl2 = BC.mount({ ownerDocument: d }, { sid: 's1', api: err });
  await tick();
  await btn.onclick();
  assert.match(btn.title, /Could not switch the broadcast: 403/);
  assert.equal(btn.disabled, false);
  ctl.stop(); ctl2.stop();
  assert.equal(BC.mount({ ownerDocument: doc([]) }, { sid: 's1', api }), null, 'no button (an ended session): nothing mounts');
});

test('the Broadcast bar: program line, Auto, links made and revoked', async () => {
  const ids = ['broadcast-panel', 'bc-line', 'bc-dot', 'bc-auto', 'bc-links', 'bc-tokens', 'bc-pic', 'bc-name', 'bc-control', 'bc-new'];
  const d = doc(ids);
  const calls = [];
  const api = async (path, body, method) => {
    calls.push([path, body, method]);
    if (path === '/api/broadcast') return { program: { mode: 'session', target: 's', session_id: 's', title: 'DOA2', pc: 'lilspark', state: 'live', why: 'pinned' } };
    if (path === '/api/broadcast/tokens' && body) return { name: body.name, token: 'gbb_x', program: { lan: { mjpeg: 'http://l/p.mjpg?token=gbb_x' } } };
    if (path === '/api/broadcast/tokens') return [{ id: 't1', name: 'Pine Box', scope: 'view', last_used: null }];
    return {};
  };
  const ctl = BC.mountPanel(d.getElementById('broadcast-panel'), { api });
  await tick(); await tick();
  assert.equal(d.getElementById('bc-line').textContent, 'On air: DOA2 on lilspark · pinned');
  assert.ok(d.getElementById('bc-dot').classList.contains('live'));
  assert.equal(d.getElementById('bc-auto').disabled, false);
  await d.getElementById('bc-auto').onclick();
  assert.ok(calls.some(c => c[0] === '/api/broadcast/program' && c[1].session_id === 'auto'));
  d.getElementById('bc-tokens').hidden = true;
  d.getElementById('bc-links').onclick();
  await tick(); await tick();
  assert.equal(d.getElementById('bc-links').attrs['aria-expanded'], 'true');
  assert.match(d.getElementById('bc-tokens').innerHTML, /Pine Box/);
  d.getElementById('bc-name').value = 'OBS';
  d.getElementById('bc-control').checked = true;
  await d.getElementById('bc-new').onclick();
  await tick();
  assert.ok(calls.some(c => c[0] === '/api/broadcast/tokens' && c[1] && c[1].name === 'OBS' && c[1].scope === 'control'));
  assert.match(d.getElementById('bc-tokens').innerHTML, /copy these now/);
  assert.match(d.getElementById('bc-tokens').innerHTML, /http:\/\/l\/p\.mjpg\?token=gbb_x/);
  ctl.stop();
});
