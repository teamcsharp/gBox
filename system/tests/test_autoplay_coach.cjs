// clients/web/viz/autoplay-coach.js: the Sessions header's "Coach the autoplay" box (send / clear / status), and the watch
// panel's Coach line (clients/web/viz/watch-analytics.js). Server side: tests/test_autoplay_coach.py.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const C = require('../clients/web/viz/autoplay-coach.js');
const W = require('../clients/web/viz/watch-analytics.js');

const tick = () => new Promise(r => setImmediate(r));
async function until(cond, n = 200) { for (let i = 0; i < n && !cond(); i++) await tick(); assert.ok(cond(), 'condition never became true'); }

// a fake server: POST answers `sent`, each status read answers the next of `polls` (the last one repeats)
function fakeApi(sent, polls = [], fail = null) {
  const calls = [];
  let i = 0;
  const api = async (path, body) => {
    calls.push({ path, body });
    if (body) { if (fail) throw new Error(fail); return sent; }
    return polls[Math.min(i++, polls.length - 1)];
  };
  return { api, calls };
}

const SENT = { request_id: 'r1', number: 812, message_id: 'm1', note: 3,
  captures: { frame: { state: 'pending' }, state: { state: 'skipped', detail: 'no slot of gBox own' }, ram: { state: 'pending' } } };
const POLLS = [
  { note: 3, number: 812, captures: { frame: { state: 'done', detail: '640x480' }, state: { state: 'skipped' }, ram: { state: 'pending' } }, done: false },
  { note: 3, number: 812, captures: { frame: { state: 'done' }, state: { state: 'skipped' }, ram: { state: 'done', detail: '24.0 MiB at 0x80000000' } },
    summary: '[RE4 Mercenaries at this note: room r400]', done: true }];

test('the status line marks each capture', () => {
  assert.equal(C.statusText(3, { frame: { state: 'done' }, state: { state: 'pending' }, ram: { state: 'failed' } }),
    'Note #3 sent · frame ✓ · state … · RAM ✗');
  assert.equal(C.statusText(1, { frame: { state: 'skipped' } }), 'Note #1 sent · frame – · state … · RAM …');
  const tip = C.detailText(POLLS[1]);
  assert.match(tip, /Coaching ticket #812, note 3/);
  assert.match(tip, /RAM: done - 24\.0 MiB at 0x80000000/);
  assert.match(tip, /room r400/);
  // settled, the line folds so the box keeps its room in a full header
  const all = s => ({ frame: { state: s }, state: { state: s }, ram: { state: s } });
  assert.equal(C.compactText(3, all('done')), 'Note #3 ✓');
  assert.equal(C.compactText(3, { ...all('done'), state: { state: 'skipped' } }), 'Note #3 ✓ · state –');
  assert.equal(C.compactText(3, { ...all('done'), ram: { state: 'failed' } }), 'Note #3 · RAM ✗');
});

test('send posts the trimmed note and follows its captures until they settle', async () => {
  const { api, calls } = fakeApi(SENT, POLLS), views = [];
  const ctl = C.create({ sid: 'w1-send', api, render: v => views.push(v), sleep: tick, timeout: 5000 });
  const out = await ctl.send('  stop walking into walls  ');
  assert.equal(out.message_id, 'm1');
  assert.deepEqual(calls[0], { path: '/api/sessions/w1-send/coach', body: { text: 'stop walking into walls' } });
  assert.equal(views[0].text, 'Sending note…');
  assert.equal(views[1].text, 'Note #3 sent · frame … · state – · RAM …');
  await until(() => views.at(-1).compact);
  assert.deepEqual(views.slice(2).map(v => v.text), ['Note #3 sent · frame ✓ · state – · RAM …',
    'Note #3 sent · frame ✓ · state – · RAM ✓', 'Note #3 ✓ · state –']);   // the spec line, then folded after HOLD_MS
  assert.ok(calls.slice(1).every(c => c.path === '/api/sessions/w1-send/coach/m1' && c.body === undefined));
  assert.match(views.at(-1).title, /room r400/);
});

test('an empty note sends nothing; a failed send says so and keeps polling quiet', async () => {
  const { api, calls } = fakeApi(SENT, POLLS, '409 This session has no game to coach'), views = [];
  const ctl = C.create({ sid: 'w1-empty', api, render: v => views.push(v), sleep: tick, timeout: 5000 });
  assert.equal(await ctl.send('   '), null);
  assert.equal(calls.length, 0);
  await assert.rejects(ctl.send('aim at him'), /no game to coach/);
  assert.equal(views.at(-1).state, 'error');
  assert.match(views.at(-1).text, /^✗ Note not sent: 409 This session has no game to coach/);
  assert.equal(calls.length, 1);
});

test('only the newest note paints the status', async () => {
  let release;
  const gate = new Promise(r => { release = r; });
  const views = [];                             // each note's status answers for its own note number
  const api = async (path, body) => body ? { ...SENT, note: body.text === 'second' ? 4 : 3, message_id: body.text }
    : (await gate, { ...POLLS[1], note: path.endsWith('/second') ? 4 : 3 });
  const ctl = C.create({ sid: 'w1-two', api, render: v => views.push(v), sleep: tick, timeout: 5000 });
  await ctl.send('first');
  await ctl.send('second');
  const after = views.length;
  release();
  await until(() => views.at(-1).compact);
  assert.ok(views.slice(after).every(v => v.text.startsWith('Note #4')));   // the first note's late answer stays quiet
  assert.deepEqual(views.slice(after).map(v => v.text), ['Note #4 sent · frame ✓ · state – · RAM ✓', 'Note #4 ✓ · state –']);
});

// --- the box in the header -----------------------------------------------------------------------------------------------
function fakeBox() {
  const listen = () => { const on = {}; return { on, addEventListener(t, fn) { (on[t] = on[t] || []).push(fn); } }; };
  const input = { value: '', blurred: false, blur() { this.blurred = true; }, ...listen() };
  const status = { textContent: '', title: '', dataset: {} };
  const box = { matches: s => s === '[data-coach]', querySelector: s => (s === 'input' ? input : s === '[data-coach-status]' ? status : null) };
  const host = { matches: () => false, querySelector: s => (s === '[data-coach]' ? box : null) };
  const fire = (type, ev) => (input.on[type] || []).forEach(fn => fn(ev));
  const key = (k, extra = {}) => {
    const ev = { key: k, isComposing: false, shiftKey: false, prevented: false, stopped: false, ...extra,
      preventDefault() { this.prevented = true; }, stopPropagation() { this.stopped = true; } };
    fire('keydown', ev);
    return ev;
  };
  const type = text => { input.value = text; fire('input', {}); };
  return { host, input, status, key, type };
}

test('Enter sends the note, clears the box and shows the status beside it', async () => {
  const { api, calls } = fakeApi(SENT, POLLS), b = fakeBox();
  const ctl = C.mount(b.host, { sid: 'w1-box', api, sleep: tick, timeout: 5000 });
  assert.ok(ctl);
  b.type('stop walking into walls');
  const letter = b.key('a');
  assert.ok(letter.stopped && !letter.prevented);              // typing is never a page shortcut or game input
  const enter = b.key('Enter');
  assert.ok(enter.prevented);
  assert.equal(b.input.value, '');                             // cleared at once: the next note can be typed
  assert.deepEqual(calls[0].body, { text: 'stop walking into walls' });
  await until(() => b.status.textContent === 'Note #3 sent · frame ✓ · state – · RAM ✓');
  await until(() => b.status.textContent === 'Note #3 ✓ · state –');
  assert.equal(b.status.dataset.state, 'done');
  assert.match(b.status.title, /Coaching ticket #812/);
  b.key('Enter');                                              // an empty box sends nothing
  assert.equal(calls.filter(c => c.body).length, 1);
  b.key('Escape');
  assert.ok(b.input.blurred);
});

test('a note that could not be sent comes back into the box', async () => {
  const { api } = fakeApi(SENT, POLLS, 'gBox server unreachable'), b = fakeBox();
  C.mount(b.host, { sid: 'w1-fail', api, sleep: tick, timeout: 5000 });
  b.type("that's not an enemy");
  b.key('Enter');
  await until(() => b.status.dataset.state === 'error');
  assert.equal(b.input.value, "that's not an enemy");
  assert.match(b.status.textContent, /✗ Note not sent: gBox server unreachable/);
});

test('a header drawn again keeps the draft and the last note status', async () => {
  const { api } = fakeApi(SENT, POLLS), first = fakeBox();
  const ctl = C.mount(first.host, { sid: 'w1-again', api, sleep: tick, timeout: 5000 });
  first.type('go after the');
  const again = fakeBox();
  C.mount(again.host, { sid: 'w1-again', api, sleep: tick, timeout: 5000 });
  assert.equal(again.input.value, 'go after the');            // the unsent draft
  again.type('go after the enemy');
  again.key('Enter');
  await until(() => again.status.textContent === 'Note #3 ✓ · state –');
  ctl.dispose();
  const third = fakeBox();
  C.mount(third.host, { sid: 'w1-again', api, sleep: tick, timeout: 5000 });
  assert.equal(third.input.value, '');                         // sent: no draft left
  assert.equal(third.status.textContent, 'Note #3 ✓ · state –');   // the settled note, folded; nothing polled again
  assert.match(third.status.title, /room r400/);
});

test('a header drawn again while the note still captures picks its polling back up', async () => {
  const pending = { ...SENT, message_id: 'm9', note: 9 };
  const { api, calls } = fakeApi(pending, [{ ...POLLS[1], note: 9 }]);
  let release;
  const gate = new Promise(r => { release = r; });
  const slow = async (path, body) => (body ? api(path, body) : (await gate, api(path, body)));
  const first = fakeBox();
  const ctl = C.mount(first.host, { sid: 'w1-resume', api: slow, sleep: tick, timeout: 5000 });
  first.type('aim at the enemy'); first.key('Enter');
  await until(() => first.status.textContent.startsWith('Note #9 sent · frame …'));
  ctl.dispose();                                               // the view changes while frame / RAM still capture
  const again = fakeBox();
  C.mount(again.host, { sid: 'w1-resume', api: slow, sleep: tick, timeout: 5000 });
  assert.equal(again.status.textContent, 'Note #9 sent · frame … · state – · RAM …');
  release();
  await until(() => again.status.textContent === 'Note #9 ✓ · state –');
  assert.ok(calls.some(c => c.path === '/api/sessions/w1-resume/coach/m9'));
});

test('the markup is the box the header shows', () => {
  const h = C.html('w1-<x>');
  assert.match(h, /data-coach data-sid="w1-&#60;x&#62;"/);
  assert.match(h, /<input type="text" class="coach-in" maxlength="2000"/);
  assert.ok(h.includes('placeholder="Coach the autoplay: stop walking into walls, aim at him…"'));
  assert.match(h, /data-coach-status role="status" aria-live="polite"/);
  assert.equal(C.mount({ matches: () => false, querySelector: () => null }, { sid: 's', api: async () => ({}) }), null);
});

// --- the watch panel's Coach line ----------------------------------------------------------------------------------------
test('the watch panel shows the newest note and how long ago', () => {
  const coach = { number: 812, count: 4, latest: { note: 3, text: 'stop walking into walls', age_s: 125, summary: '[RE4 Mercenaries at this note: room r400]' } };
  const m = W.model({ running: true }, null, coach);
  assert.deepEqual(m.coach, { line: 'Coach: stop walking into walls · 2 min ago', detail: 'note 3 · ticket #812 · 4 notes kept',
    summary: '[RE4 Mercenaries at this note: room r400]' });
  const h = W.html(m, 'RE4');
  assert.ok(h.indexOf('<h4>Coach</h4>') < h.indexOf('<h4>Bot</h4>'));
  assert.ok(h.includes('Coach: stop walking into walls · 2 min ago'));
  assert.ok(W.html(W.model({}, null, { latest: { text: '<b>x</b>', age_s: 3 } }), 't').includes('Coach: &#60;b&#62;x&#60;/b&#62; · just now'));
  assert.deepEqual(W.model({}, null, { latest: null, count: 0 }), { bot: [], analysis: [], jobs: [], runs: [], results: [] });
  assert.equal(W.ago(45), '45 s ago');
  assert.equal(W.ago(7200), '2 h ago');
});

test('the chat has an instant-command dropdown that posts the exact command for this session', async () => {
  const C = require('../clients/web/viz/autoplay-coach.js');
  assert.match(C.html('w-1'), /data-coach-cmds/);
  assert.deepEqual(C.COMMANDS.map(c => c[0]), ['fight', 'next_area', 'explore', 'hunt', 'score', 'repetitive', 'mine', 'mine_trail', 'missing']);
  const calls = [], states = [];
  const host = { ownerDocument: undefined, matches: () => true, querySelector: sel => sel === 'input' ? input : sel === '[data-coach-status]' ? status : sel === '[data-coach-cmds]' ? button : null };
  const input = { addEventListener() {}, value: '', setAttribute() {} }, status = { dataset: {} }, button = { addEventListener() {}, setAttribute() {}, getBoundingClientRect: () => ({}) };
  const ctl = C.mount(host, { sid: 'w-1', api: async (path, body) => { calls.push([path, body]); return { directive: { label: 'x' } }; }, onState: v => states.push(v) });
  await ctl.command('fight');
  assert.deepEqual(calls[0], ['/api/sessions/w-1/directive', { command: 'fight' }]);
  assert.equal(states.at(-1).state, 'done'); assert.match(states.at(-1).text, /Fight them!.*sent/);
});

test('the command dropdown closes when the pointer goes elsewhere, when the window loses focus, and never survives a re-mount', async () => {
  // operator 2026-10-26 (PiP, the menu stuck open over the game): "close dropdowns when i click away. I cant close this now"
  const C = require('../clients/web/viz/autoplay-coach.js');
  const listeners = { doc: {}, win: {} };
  const on = store => (type, fn) => { (store[type] ||= []).push(fn); };
  const off = store => (type, fn) => { store[type] = (store[type] || []).filter(f => f !== fn); };
  const win = { addEventListener: on(listeners.win), removeEventListener: off(listeners.win) };
  const stale = { className: 'coach-menu', removed: false, remove() { this.removed = true; } };
  const made = [];
  const doc = {
    defaultView: win, addEventListener: on(listeners.doc), removeEventListener: off(listeners.doc),
    querySelectorAll: sel => sel === '.coach-menu' ? [stale] : [],
    createElement() {
      const el = { className: '', style: {}, innerHTML: '', removed: false, handlers: {},
        setAttribute() {}, addEventListener(t, fn) { this.handlers[t] = fn; }, remove() { this.removed = true; },
        contains: node => node && node.inside === true, querySelector: () => null };
      made.push(el); return el;
    },
    body: { append() {} },
  };
  let clicks = null;
  const button = { addEventListener(t, fn) { if (t === 'click') clicks = fn; }, setAttribute() {}, getBoundingClientRect: () => ({ left: 10, bottom: 20 }), focus() {} };
  const input = { addEventListener() {}, value: '', setAttribute() {} }, status = { dataset: {} };
  const host = { ownerDocument: doc, matches: () => true, querySelector: sel => sel === 'input' ? input : sel === '[data-coach-status]' ? status : sel === '[data-coach-cmds]' ? button : null };
  C.mount(host, { sid: 'w-1', api: async () => ({}) });
  clicks({ preventDefault() {}, stopPropagation() {} });
  assert.ok(stale.removed, 'a menu left by an earlier mount is removed when a new one opens');
  assert.equal(made.length, 1);
  assert.ok(listeners.doc.pointerdown?.length && listeners.doc.mousedown?.length && listeners.win.blur?.length);
  listeners.doc.pointerdown[0]({ target: { inside: false } });          // a click on the game, the stream, anywhere else
  assert.ok(made[0].removed, 'the menu closes on a pointer-down outside it');
  assert.deepEqual([listeners.doc.pointerdown, listeners.doc.mousedown, listeners.win.blur].map(l => l.length), [0, 0, 0]);
  clicks({ preventDefault() {}, stopPropagation() {} });                 // open again
  assert.equal(made.length, 2);
  listeners.win.blur[0]();                                              // the native game surface took the click
  assert.ok(made[1].removed, 'the menu closes when the window loses focus');
  clicks({ preventDefault() {}, stopPropagation() {} });
  listeners.doc.pointerdown[0]({ target: { inside: true } });            // inside the menu: stays
  assert.ok(!made[2].removed);
});
