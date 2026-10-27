// Run with node system/tests/test_pad_takeover.cjs. The pad takeover badge (clients/web/viz/pad-takeover.js,
// gbox/pad_takeover.py): "You have control - put the pad down to give it back (3 s)" while the operator's pad drives a
// session whose bot runs, counting down once the pad is idle; the web view's controller loop feeds it, the desktop PiP
// mirrors it.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const T = require('../clients/web/viz/pad-takeover.js');

const plain = x => JSON.parse(JSON.stringify(x));   // values from the view's VM realm
const clock = (t = 0) => { const c = { t, now: () => c.t }; return c; };
const WORDS = 'You have control - put the pad down to give it back';

test('a press on a session whose bot runs shows the badge; held it stays full; put down it counts down to the bot', () => {
  const c = clock(), t = T.create({ now: c.now });
  t.bot('w-s1', true, 3000);
  assert.equal(t.observe('w-s1', []).show, false);
  let st = t.observe('w-s1', ['b']);
  assert.equal(st.show, true);
  assert.equal(st.text, `${WORDS} (3 s)`);
  c.t = 5000; st = t.observe('w-s1', ['b']);                // held 5 s: still the full idle time
  assert.deepEqual([st.show, st.held, st.seconds], [true, true, 3]);
  c.t = 5100; st = t.observe('w-s1', []);                   // put down
  assert.deepEqual([st.show, st.held, st.seconds], [true, false, 3]);
  c.t = 6200; assert.equal(t.state().text, `${WORDS} (2 s)`);
  c.t = 7200; assert.equal(t.state().text, `${WORDS} (1 s)`);
  c.t = 8100; assert.equal(t.state().show, false);           // the bot has taken back over: the badge goes
  assert.equal(t.observe('w-s1', []).show, false);           // and nothing but a new press brings it back
});

test('a key held longer than the idle time keeps the pad even when only its press and release are seen', () => {
  const c = clock(), t = T.create({ now: c.now });
  t.bot('w-s1', true, 3000);
  t.observe('w-s1', ['lup']);
  c.t = 4000;
  assert.equal(t.observe('w-s1', []).text, `${WORDS} (3 s)`);   // let go after 4 s: the countdown starts now
  c.t = 6000; assert.equal(t.state().seconds, 1);
});

test('every input renews the countdown; the bot report sets the idle time', () => {
  const c = clock(), t = T.create({ now: c.now });
  t.bot('w-s1', true, 5000);                                 // gbox.toml takeover_idle_s = 5
  t.observe('w-s1', ['a']); c.t = 100; t.observe('w-s1', []);
  c.t = 4000; t.observe('w-s1', ['x']); c.t = 4100; t.observe('w-s1', []);
  c.t = 8000; assert.equal(t.state().seconds, 2);            // 3.9 s after the last input of a 5 s idle time
  c.t = 9100; assert.equal(t.state().show, false);
});

test('no badge without a running bot, for a release, or for another session; a late bot report counts', () => {
  const c = clock(), t = T.create({ now: c.now });
  assert.equal(t.observe('w-s1', ['a']).show, false);        // the bot's report has not come yet
  t.bot('w-s1', true, 3000);
  assert.equal(t.state().show, true);                        // it came while the pad is in use: the badge shows
  t.observe('w-s2', ['a']);                                  // another session's pad: its own rule, its bot unknown
  assert.equal(t.state().show, false);
  t.bot('w-s2', false, 0);
  c.t = 100; assert.equal(t.observe('w-s2', ['a', 'b']).show, false);   // its bot is not running: you just play
  const r = T.create({ now: c.now }); r.bot('w-s3', true, 3000);
  r.observe('w-s3', []); assert.equal(r.observe('w-s3', []).show, false);
  assert.equal(r.known('w-s3', 6000), true); c.t = 7000; assert.equal(r.known('w-s3', 6000), false);
});

test('the desktop PiP counts down from the view\'s message on its own clock', () => {
  const held = T.countdown({ sid: 'w-s1', show: true, held: true, remaining_ms: 3000, idle_ms: 3000 }, 1000, 9000);
  assert.deepEqual([held.show, held.seconds], [true, 3]);
  const idle = { sid: 'w-s1', show: true, held: false, remaining_ms: 2900, idle_ms: 3000 };
  assert.equal(T.countdown(idle, 1000, 1000).text, `${WORDS} (3 s)`);
  assert.equal(T.countdown(idle, 1000, 2500).seconds, 2);
  assert.equal(T.countdown(idle, 1000, 4000).show, false);
  assert.equal(T.countdown({ sid: 'w-s1', show: false }, 0, 0).show, false);
  assert.equal(T.countdown({ sid: 'w-s1', show: true, held: true, idle_ms: 3000 }, 0, 13000).show, false,
    'a held badge the view stopped repeating is over');
});

test('the badge element renders the words once and only the seconds change', () => {
  const nodes = [];
  const el = () => ({ hidden: false, dataset: {}, attrs: {}, children: [], textContent: '', innerHTML: '',
    setAttribute(k, v) { this.attrs[k] = v; }, append(n) { this.children.push(n); nodes.push(n); },
    querySelector(sel) { return this.parts?.[sel]; } });
  const doc = { body: el(), head: el(), getElementById: id => nodes.find(n => n.id === id) || null,
    createElement: () => { const n = el(); n.parts = { '.pt-secs': el() }; return n; } };
  const ui = T.mount(doc);
  assert.equal(ui.el.hidden, true);
  assert.equal(ui.render({ show: true, held: false, seconds: 2, sid: 'w-s1', text: `${WORDS} (2 s)` }), true);
  assert.equal(ui.el.hidden, false);
  assert.match(ui.el.innerHTML, /You have control - put the pad down to give it back/);
  assert.equal(ui.el.querySelector('.pt-secs').textContent, '(2 s)');
  assert.equal(ui.el.attrs.role, 'status');
  assert.equal(ui.render({ show: false }), false);
  assert.equal(ui.el.hidden, true);
  assert.equal(T.mount(doc).el, ui.el);                      // one badge per document
});

// The web view's real controller loop (index.html), with the badge code beside it: the operator's pad is forwarded to the
// session the view shows (#1532) and, when that session's bot runs, the badge says they have control.
function client() {
  const html = fs.readFileSync(path.join(__dirname, '../clients/web/index.html'), 'utf8');
  const pads = html.slice(html.indexOf('const RETRO ='), html.indexOf('async function snap(sid)'));
  const badge = html.slice(html.indexOf('// ---------------- pad takeover badge'), html.indexOf('// ---------------- end pad takeover badge'));
  assert.ok(pads.includes('padTakeoverTick(sid, sources)') && badge.includes('function padTakeoverTick'));
  const sent = [], renders = [], logs = [], telemetry = {}, c = clock(1000);
  const ctx = vm.createContext({
    navigator: { getGamepads: () => [] }, console: { log: s => logs.push(String(s)), warn() {} },
    localStorage: { getItem: () => null, setItem() {} },
    api: async (url, body) => {
      if (url.startsWith('/api/autoplay/telemetry/')) return telemetry[decodeURIComponent(url.split('/').pop())] || {};
      sent.push({ url, ...body }); return {};
    },
    requestAnimationFrame() {}, addEventListener() {}, setInterval() {}, $: () => null, cur: 'Sessions', playing: null,
    show() {}, esc: String, document: {}, Date, Promise, JSON, Math, Number, Set, Map, Object, String, encodeURIComponent,
    decodeURIComponent,
  });
  ctx.window = ctx;
  ctx.GBoxPadTakeover = { ...T, create: o => T.create({ ...o, now: c.now }), mount: () => ({ render: st => renders.push(st) }) };
  vm.runInContext(pads + '\n' + badge, ctx);
  const run = code => vm.runInContext(code, ctx);
  const flush = async () => { await run('Promise.all([...padQueues.values()])'); await new Promise(r => setImmediate(r)); };
  const push = pads => run(`window.gboxNativePad(${JSON.stringify(pads)})`);
  return { run, sent, renders, logs, telemetry, clock: c, flush, push };
}
const xi = (buttons = 0) => [{ slot: 0, buttons, lt: 0, rt: 0, lx: 0, ly: 0, rx: 0, ry: 0 }];
const A = 0x1000;

test('the view forwards the pad to the session it shows and badges the takeover while that session\'s bot runs', async () => {
  const v = client(), SID = '13e9fba6ff024e99-re4live';
  v.run(`active = ${JSON.stringify({ sid: SID, title: 'Resident Evil 4', local: false })}`);
  v.telemetry[SID] = { running: true, age_s: 2, stats: { operator_idle_s: 3 } };
  v.push(xi(A)); await v.flush();
  assert.deepEqual(plain(v.sent.map(s => [s.url, s.events])), [[`/api/sessions/${SID}/input`, [{ key: 'b', down: true, player: 1 }]]]);
  let st = v.renders.at(-1);
  assert.equal(st.show, true, 'the bot report came back: you have control');
  assert.equal(st.text, `${WORDS} (3 s)`);
  const msg = JSON.parse(v.logs.filter(l => l.startsWith('GBOX:')).at(-1).slice(5));
  assert.deepEqual([msg.ev, msg.sid, msg.show, msg.held, msg.idle_ms], ['padtakeover', SID, true, true, 3000]);
  v.clock.t = 1500; v.push(xi(0)); await v.flush();          // the pad put down
  assert.deepEqual(plain(v.sent.at(-1).events), [{ key: 'b', down: false, player: 1 }]);
  v.clock.t = 3000; v.run('padTakeoverRender()');
  assert.equal(v.renders.at(-1).seconds, 2);
  v.clock.t = 4600; v.run('padTakeoverRender()');
  assert.equal(v.renders.at(-1).show, false, 'the bot takes back over and the badge goes');
  assert.equal(JSON.parse(v.logs.filter(l => l.startsWith('GBOX:')).at(-1).slice(5)).show, false);
});

test('no badge when the shown session has no running bot; a game on this PC follows this PC\'s pad without forwarding', async () => {
  const v = client(), SID = 'aa-own-game', LOCAL = 'w9-native-re5';
  v.run(`active = ${JSON.stringify({ sid: SID, title: 'Own game', local: false })}`);
  v.telemetry[SID] = { running: false, age_s: 1 };
  v.push(xi(A)); await v.flush();
  assert.equal(v.sent.length, 1);                            // your input reaches your game as always
  assert.equal(v.renders.at(-1).show, false);                // nobody to take over from
  v.push(xi(0)); await v.flush();
  v.run(`active = ${JSON.stringify({ sid: LOCAL, title: 'RE5 here', local: true })}`);
  v.telemetry[LOCAL] = { running: true, age_s: 1, stats: {} };
  const before = v.sent.length;
  v.clock.t = 2000; v.push(xi(A)); await v.flush();
  assert.equal(v.sent.length, before, 'a native game here reads the pad itself: nothing is forwarded');
  assert.equal(v.renders.at(-1).show, true, 'its worker watches the same pad: the badge follows it');
  assert.equal(v.renders.at(-1).sid, LOCAL);
});
