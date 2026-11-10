// 2026-11-10: a critique typed in the PiP never reached the bot's ticket and nothing said so. The coach box now queues a
// note that could not be delivered (autoplay-coach.js outbox), says so where the hidden PiP bar can be seen
// (compact-coach.js), sends with a visible button, keeps words carried across MercMode's title change for the game they
// were typed for, and shows what the bot made of a quick command.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const C = require('../clients/desktop/compact-coach');
const A = require('../clients/web/viz/autoplay-coach');

const settled = { message_id: 'note', note: 1, change_id: 'c', dispatch_state: 'queued', implementation_number: 9,
  captures: { frame: { state: 'done' }, state: { state: 'skipped' }, ram: { state: 'done' } } };
const tick = () => new Promise(r => setImmediate(r));

function box(extra = {}) {
  const listeners = {}, input = { value: '', addEventListener(t, fn) { (listeners[t] ||= []).push(fn); }, setAttribute() {} };
  const status = { textContent: '', title: '', dataset: {} };
  const host = { matches: s => s === '[data-coach]',
    querySelector: s => s === 'input' ? input : s === '[data-coach-status]' ? status : extra[s] || null };
  const fire = (type, ev = {}) => (listeners[type] || []).forEach(f => f(ev));
  const type = text => { input.value = text; fire('input'); };
  const enter = () => fire('keydown', { key: 'Enter', isComposing: false, shiftKey: false, preventDefault() {}, stopPropagation() {} });
  return { host, input, status, fire, type, enter };
}

test('a note that never left this PC waits in the outbox and is filed once with its own ID', async () => {
  const calls = [], views = [];
  let reachable = false;
  const ctl = A.create({ sid: 'outbox-offline', idempotent: true, makeId: () => 'offline-id', render: x => views.push(x),
    sleep: async () => {}, api: async (path, body) => {
      calls.push({ path, body });
      if (!reachable) throw Object.assign(Error("Remote gBox is offline. This PC's local library remains available."), { notSent: true });
      return settled;
    } });
  await assert.rejects(ctl.send('aim the grenades at the ground, not into the lava'), e => e.queued === true);
  assert.equal(calls.length, 1, 'no receipt lookup for a request that never left');
  assert.equal(views.at(-1).state, 'queued');
  assert.match(views.at(-1).text, /not sent yet - retrying in \d+ s/);
  assert.match(views.at(-1).title, /lava/);
  assert.equal(ctl.waiting(), 1);
  reachable = true;
  await A.outboxFlush('outbox-offline');
  const posts = calls.filter(c => c.body);
  assert.equal(posts.length, 2);
  assert.equal(posts[1].body.client_id, 'offline-id');
  assert.equal(ctl.waiting(), 0);
  assert.match(views.at(-1).text, /^Note #1/);
  ctl.dispose();
});

test('an old app saying "no request was sent" in words queues too, and the same words again retry the waiting note', async () => {
  assert.ok(A.notSent(Error("Waiting for this connection's API credential. No request was sent.")));
  assert.ok(!A.notSent(Error('The operation was aborted due to timeout')));
  const calls = [];
  let up = false;
  const ctl = A.create({ sid: 'outbox-same', idempotent: true, makeId: () => `same-${calls.length}`, render() {},
    sleep: async () => {}, api: async (path, body) => {
      calls.push({ path, body });
      if (!up) throw Error("This PC's gBox is starting or reconnecting. Your game was not changed.");
      return settled;
    } });
  await assert.rejects(ctl.send('stop throwing into the void'), e => e.queued);
  up = true;
  const out = await ctl.send('stop throwing into the void');           // the operator presses Enter again
  assert.equal(out.message_id, 'note');
  const posts = calls.filter(c => c.body);
  assert.equal(posts.length, 2); assert.equal(posts[0].body.client_id, posts[1].body.client_id);
  ctl.dispose();
});

test('a lost answer whose receipt did not get through asks for it before any second POST', async () => {
  const calls = [];
  let network = false;
  const ctl = A.create({ sid: 'outbox-lost', idempotent: true, makeId: () => 'lost-id', render() {}, sleep: async () => {},
    api: async (path, body) => {
      calls.push({ path, body });
      if (body) throw Error('The operation was aborted due to timeout');
      if (!network) throw Error('fetch failed');                          // the receipt lookup does not get through
      return { state: 'saved', session_id: 'outbox-lost', client_id: 'lost-id', result: settled };
    } });
  await assert.rejects(ctl.send('shoot the ones on the ledge'), e => e.queued);
  network = true;
  await A.outboxFlush('outbox-lost');
  assert.equal(calls.filter(c => c.body).length, 1, 'the server had filed it: never posted twice');
  assert.equal(ctl.waiting(), 0); ctl.dispose();
});

test('a refused note comes back into the box and is never queued; the visible send button sends like Enter', async () => {
  let clicks = null;
  const button = { addEventListener(t, fn) { if (t === 'click') clicks = fn; } };
  const b = box({ '[data-coach-send]': button }), calls = [];
  const ctl = A.mount(b.host, { sid: 'outbox-422', idempotent: true, sleep: async () => {}, makeId: () => 'refused-id',
    api: async (path, body) => { calls.push(body); throw Error('422 Say what is wrong or what to change'); } });
  b.type('xx');
  clicks({ preventDefault() {}, stopPropagation() {} });
  await tick(); await tick();
  assert.equal(calls.length, 1);
  assert.equal(b.input.value, 'xx');
  assert.equal(b.status.dataset.state, 'error');
  assert.ok(![...A._outbox.values()].some(x => x.sid === 'outbox-422'));
  b.fire('blur');                                                       // the failure stays said, not a draft hint
  assert.equal(b.status.dataset.state, 'error');
  ctl.dispose();
});

test('an unsent critique says so when the box loses focus; one carried from the previous game is filed there', async () => {
  const b = box(), calls = [];
  const ctl = A.mount(b.host, { sid: 'carry-new', idempotent: true, sleep: async () => {}, makeId: () => `carry-${calls.length}`,
    api: async (path, body) => { calls.push(path); return settled; } });
  b.type('grenades at the ground');
  b.fire('blur');
  assert.equal(b.status.dataset.state, 'draft'); assert.match(b.status.textContent, /Not sent/);
  b.type('');
  assert.equal(ctl.carry('carry-old', 'aim the grenades at the ground, not the lava'), true);
  assert.equal(b.input.value, 'aim the grenades at the ground, not the lava');
  assert.match(b.status.textContent, /previous game/);
  b.enter();
  await tick();
  assert.equal(calls[0], '/api/sessions/carry-old/coach');             // the game it was typed for
  assert.equal(b.input.value, '');
  assert.equal(ctl.carry('carry-new', 'x'), false);                   // never "carried" into its own session
  ctl.dispose();
});

test('the compact bar stays up while a note waits or sits unsent and for a while after a failure, and toasts once', () => {
  let t = 1000, options = null;
  const toasts = [], shown = [], later = [];
  const coach = { html: () => '', mount(host, o) { options = o; return { input: { value: '', setAttribute() {} }, dispose() {} }; } };
  const host = { innerHTML: '', contains: () => false };
  const ctl = C.create({ coach, api() {}, show: x => shown.push(x), notify: text => toasts.push(text), now: () => t,
    schedule: (fn, ms) => later.push([fn, ms]) });
  ctl.update({ on: true, sid: 's' }, host);
  options.onState({ state: 'queued', text: '⟳ Note not sent yet - retrying in 4 s' });
  options.onState({ state: 'queued', text: '⟳ Note not sent yet - retrying in 3 s' });
  assert.equal(ctl.pinned(), true); assert.equal(toasts.length, 1);
  options.onState({ state: 'draft', text: '✎ Not sent - Enter or ➤' }); assert.equal(ctl.pinned(), true);
  options.onState({ state: 'error', text: '✗ Note not sent: 422 bad' });
  assert.equal(ctl.pinned(), true); assert.equal(toasts.length, 2);
  t += C.ERROR_PIN_MS + 1; assert.equal(ctl.pinned(), false);
  assert.ok(later[0][1] > C.ERROR_PIN_MS);
  later[0][0](); assert.equal(shown.at(-1), false);
  options.delivered('aim'); assert.match(toasts.at(-1), /delivered/);
});

test('words left in the box when MercMode moves the PiP to the next game are carried into the new box', () => {
  const mounts = [];
  const coach = { html: () => '', mount(host, o) {
    const control = { input: { value: '', setAttribute() {} }, carried: null, dispose() {},
      carry(sid, text) { this.carried = [sid, text]; return true; } };
    mounts.push(control); return control;
  } };
  const host = { innerHTML: '', contains: () => false };
  const ctl = C.create({ coach, api() {}, show() {} });
  ctl.update({ on: true, sid: 're6-session' }, host);
  mounts[0].input.value = 'aim the grenades at the ground';
  ctl.update({ on: true, sid: 're4-session' }, host);
  assert.deepEqual(mounts[1].carried, ['re6-session', 'aim the grenades at the ground']);
  assert.equal(ctl.report('x'), null);                                  // no report hook on this fake box
});

test('a quick command shows what the bot made of it, from its telemetry', async () => {
  const states = [], input = { addEventListener() {}, value: '', setAttribute() {} }, status = { dataset: {} };
  const host = { matches: () => true, querySelector: sel => sel === 'input' ? input : sel === '[data-coach-status]' ? status : null };
  let reads = 0;
  const ctl = A.mount(host, { sid: 'cmd-ack', onState: v => states.push(v), api: async (path, body) => {
    if (body) return { directive: { seq: 41, command: 'hunt', label: 'Go after the enemies' } };
    reads++;
    return { stats: reads < 2 ? { directive_seq: 40 } : { directive_seq: 41, directive_status: 'acting: hunt' } };
  } });
  await ctl.command('hunt');
  assert.match(states.at(-1).text, /Go after the enemies · sent/);
  for (let i = 0; i < 60 && !/bot:/.test(states.at(-1).text); i++) await new Promise(r => setTimeout(r, 100));
  assert.match(states.at(-1).text, /bot: acting: hunt/);
  ctl.dispose();
});
