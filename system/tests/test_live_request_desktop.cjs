const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../clients/desktop/index.html'), 'utf8');
function between(start, end) {
  const a = html.indexOf(start), b = html.indexOf(end, a + start.length);
  assert.ok(a >= 0 && b > a, `missing desktop boundary ${start}`);
  return html.slice(a, b);
}
const contextSource = between('async function chatContext()', 'const LIVE_REQUEST_PHASES');
const liveSource = between('const LIVE_REQUEST_PHASES', 'function choicesHtml');
const eventSource = between('function renderEvent(e)', 'async function chatLoad');
const progressSource = between('const BUSY =', 'document.body.insertAdjacentHTML("beforeend", \'<div id="busysteps">');
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);

test('the visible session header preserves an ended selection ahead of another attached game', async () => {
  const page = vm.createContext({ cur: 'Sessions', active: { sid: 'other-running' }, playing: null,
    location: { hash: '' }, document: { getElementById: () => ({ dataset: { sid: 'selected-ended' } }) } });
  const shell = vm.createContext({ document: { querySelector: () => ({ executeJavaScript: async source => vm.runInContext(source, page) }) } });
  vm.runInContext(between('async function gboxState()', 'function appContext'), shell);
  assert.equal((await shell.gboxState()).session, 'selected-ended');
  vm.runInContext('cur = "Home"', page);
  assert.equal((await shell.gboxState()).session, 'other-running');
});

function contextHarness({ selected, record, sessions = [], workers = [], local = 'PLAY-PC' } = {}) {
  const calls = { live: 0, workers: 0, exact: [] };
  const context = vm.createContext({
    S: { workerName: local },
    gboxState: async () => ({ tab: 'Sessions', session: selected }),
    liveSessions: async () => { calls.live++; return { ok: true, data: sessions }; },
    WORKERS: { get: async () => { calls.workers++; return { ok: true, data: workers }; } },
    sessionById: async sid => { calls.exact.push(sid); return record; }
  });
  vm.runInContext(contextSource, context);
  return { calls, get: () => context.chatContext() };
}

test('selected running session carries the exact build and worker without exposing its ROM', async () => {
  const record = { session_id: 'remote-one', game_id: 'soul', title: 'SoulCalibur', worker_id: 'remote',
    mod: 'sonic-v4~stage', collection_mod: 'sonic-v4', platform: 'dreamcast', core: 'flycast', state: 'running',
    detail: { local_window: true, rom: 'D:/private/owned/game.gdi' } };
  const h = contextHarness({ selected: record.session_id, record });
  const actual = await h.get();
  assert.equal(actual.session_id, 'remote-one');
  assert.equal(actual.worker_id, 'remote');
  assert.equal(actual.game_id, 'soul');
  assert.equal(actual.mod, 'sonic-v4~stage');
  assert.equal(actual.collection_mod, 'sonic-v4');
  assert.equal(actual.platform, 'dreamcast');
  assert.equal(actual.core, 'flycast');
  assert.equal(actual.live_edit, true);
  assert.equal(actual.native_window, true);
  assert.equal(JSON.stringify(actual).includes('private'), false);
  assert.deepEqual(h.calls, { live: 0, workers: 0, exact: ['remote-one'] });
});

test('ended or missing selected targets are preserved instead of selecting another running game', async () => {
  for (const record of [null, { session_id: 'old-one', state: 'ended', game_id: 'soul' }]) {
    const h = contextHarness({ selected: 'old-one', record,
      workers: [{ id: 'local', name: 'PLAY-PC' }],
      sessions: [{ session_id: 'local-new', game_id: 'other', state: 'running' }] });
    const actual = await h.get();
    assert.equal(actual.session_id, 'old-one');
    assert.equal(actual.live_edit, false);
    assert.notEqual(actual.game_id, 'other');
    assert.equal(h.calls.live, 0);
    assert.equal(h.calls.workers, 0);
  }
});

test('a mismatched returned record cannot authorize the selected live target', async () => {
  const h = contextHarness({ selected: 'exact-one', record: { session_id: 'other-one', state: 'running', game_id: 'other' } });
  const actual = await h.get();
  assert.equal(actual.session_id, 'exact-one');
  assert.equal(actual.live_edit, false);
  assert.equal(actual.game_id, undefined);
});

test('local fallback resolves only an exact running record on this worker', async () => {
  const h = contextHarness({ workers: [{ id: 'local', name: 'PLAY-PC' }], sessions: [
    { session_id: 'remote-new', game_id: 'remote', state: 'running', started: 100 },
    { session_id: 'local-ended', game_id: 'ended', state: 'running', ended: 10, started: 90 },
    { session_id: 'local-old', game_id: 'old', state: 'running', started: 1 },
    { session_id: 'local-current', game_id: 'current', state: 'running', started: 5, detail: { core: 'flycast' } }
  ] });
  const actual = await h.get();
  assert.equal(actual.session_id, 'local-current');
  assert.equal(actual.worker_id, 'local');
  assert.equal(actual.live_edit, true);
  assert.equal(actual.core, 'flycast');
  assert.deepEqual(h.calls.exact, []);
});

test('ordinary chat without a resolved game does not opt into live editing', async () => {
  const h = contextHarness();
  const actual = await h.get();
  assert.equal(actual.live_edit, undefined);
  assert.equal(actual.session_id, undefined);
});

test('sending a request captures one context and uses it for conversation choice and submission', async () => {
  const snapshot = { session_id: 'first-one', game_id: 'first', live_edit: true };
  const calls = { contexts: 0, quick: null, conversation: null, post: null };
  const nodes = new Map();
  const $ = key => {
    if (!nodes.has(key)) nodes.set(key, { value: 'auto', textContent: '', classList: { add() {} }, insertAdjacentHTML() {} });
    return nodes.get(key);
  };
  const context = vm.createContext({ $, CH: { cid: 'conv', imgs: [] },
    chatContext: async () => { calls.contexts++; return calls.contexts === 1 ? snapshot : { game_id: 'changed' }; },
    instantCommand: async (_, ctx) => { calls.quick = ctx; return null; },
    chatForGame: async ctx => { calls.conversation = ctx; },
    gbox: { api: async (url, body) => { calls.post = { url, body }; return { ok: true }; } },
    chatImgs() {}, chatLoad: async () => {}, chatHistory() {}, esc, setTimeout() {}, chatSave() {}
  });
  vm.runInContext(between('async function chatSend(given)', '// history ('), context);
  await context.chatSend('unlock every stage');
  assert.equal(calls.contexts, 1);
  assert.equal(calls.quick, snapshot);
  assert.equal(calls.conversation, snapshot);
  assert.equal(calls.post.body.context, snapshot);
  assert.equal(calls.post.body.text, 'unlock every stage');
});

function progressHarness() {
  const nodes = new Map();
  const $ = key => {
    if (!nodes.has(key)) nodes.set(key, { innerHTML: '', title: '', classList: { contains: () => false } });
    return nodes.get(key);
  };
  const context = vm.createContext({ $, esc, CH: { busy: true } });
  vm.runInContext(liveSource + eventSource + progressSource, context);
  return { context, $, state: () => vm.runInContext('BUSY', context) };
}

test('actual backend phases render their exact target and escape event content', () => {
  const h = progressHarness();
  const rendered = h.context.renderEvent({ type: 'live_request', phase: 'research', status: 'running', label: '<Research>',
    session_id: 'worker-one', game_id: 'soul', worker_id: 'worker', mod: 'sonic', reason: '<script>bad</script>' });
  assert.match(rendered, /data-phase="research"/);
  assert.match(rendered, /Session worker-one/);
  assert.match(rendered, /Build sonic/);
  assert.match(rendered, /&#60;Research&#62;/);
  assert.doesNotMatch(rendered, /<script>/);
  assert.equal(h.context.renderEvent({ type: 'live_request', phase: 'invented', status: 'completed' }), '');
});

test('assistant prose and successful reads do not complete a live request stage', () => {
  const h = progressHarness();
  h.context.busyStep({ type: 'user' });
  h.context.busyStep({ type: 'live_request', phase: 'verify', status: 'running', label: 'Verifying unlocks', session_id: 'w-one', game_id: 'soul', mod: 'sonic' });
  h.context.busyStep({ type: 'tool_call', name: 'read_memory', args: { session_id: 'w-one' } });
  h.context.busyStep({ type: 'tool_result', name: 'read_memory', text: '{"hex":"0000"}' });
  h.context.busyStep({ type: 'assistant', text: 'Done!' });
  assert.equal(h.state().live.state, 'run');
  assert.equal(h.state().steps[0].st, 'run');
  h.context.busyRender();
  assert.match(h.$('#chatbusy').innerHTML, /Verifying unlocks/);
  assert.match(h.$('#chatbusy').innerHTML, /class="spin"/);
  h.context.busyStep({ type: 'live_request', phase: 'pending', status: 'pending', label: 'Unlocks pending', reason: 'No verified patch' });
  h.context.busyStep({ type: 'assistant', text: 'All done' });
  h.context.busyRender();
  assert.equal(h.state().live.state, 'pending');
  assert.match(h.$('#chatbusy').innerHTML, /No verified patch/);
  assert.doesNotMatch(h.$('#chatbusy').innerHTML, /✓/);
  h.context.busyStep({ type: 'live_request', phase: 'completed', status: 'verified', label: 'Unlocks verified' });
  h.context.busyRender();
  assert.match(h.$('#chatbusy').innerHTML, /✓/);
});

test('new user turns clear previous live progress while queued turns do not replace current work', () => {
  const h = progressHarness();
  h.context.busyStep({ type: 'live_request', phase: 'research', status: 'running', game_id: 'old' });
  h.context.busyStep({ type: 'queued', text: 'another request' });
  assert.equal(h.state().live.game_id, 'old');
  h.context.busyStep({ type: 'user', text: 'next running request' });
  assert.equal(h.state().live, null);
  assert.equal(h.state().steps.length, 0);
  h.context.busyStep({ type: 'tool_call', name: 'web_search', args: { query: 'ordinary question' } });
  h.context.busyRender();
  assert.match(h.$('#chatbusy').innerHTML, /Searching the web/);
});
