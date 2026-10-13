const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// #971 stage 2: the Examine 3D panel captures a GL / unhooked session's moment through a capture session
// (scene_capture with relay), never pauses or resumes the operator's game for it, and labels the result.
const html = fs.readFileSync(path.join(__dirname, '../clients/web/index.html'), 'utf8');
const start = html.indexOf('// ---------------- Examine 3D: the paused frame');
const end = html.indexOf('// ---------------- per-game graphics', start);
assert.ok(start >= 0 && end > start, 'Examine 3D panel code must be present');
const source = html.slice(start, end);

const SID = 'opw-job1';
const RELAY = { status: 'relaunch_under_capture', driver: 'vulkan', attach: 'layer', relay: true, reason: 'GL session' };

function element(id) {
  const el = { id, style: {}, dataset: {}, disabled: false, innerHTML: '', textContent: '', isConnected: true, children: [],
    classList: { add() {}, remove() {} }, onclick: null, onchange: null, oninput: null, checked: false, value: '1',
    insertAdjacentHTML(where, h) { this.innerHTML = where === 'afterbegin' ? h + this.innerHTML : this.innerHTML + h; } };
  Object.defineProperty(el, 'firstElementChild', { get: () => el });
  return el;
}

function harness(support, outputs) {
  const els = {}, posted = [], runs = [], shown = [];
  const get = sel => (els[sel] = els[sel] || element(sel));
  get('#exam').dataset = { sid: SID, support: JSON.stringify(support) };
  let polls = 0;
  const api = async (url, body) => {
    if (url === '/api/workers') return [{ id: 'opw', online: true, tools: ['scene_capture'] }];
    if (url === '/api/jobs') { posted.push(body); return { id: 'j1', state: 'running' }; }
    if (url === '/api/jobs/j1') { polls++; return outputs.shift() || { state: 'failed', error: 'no more' }; }
    throw new Error('unexpected ' + url);
  };
  const viewer = { load: async () => {}, setHud() {}, setWireframe() {}, setDepth() {}, gameView() {}, dispose() {} };
  const ctx = vm.createContext({ console, JSON, Math, Promise, Map, String, encodeURIComponent,
    setTimeout: f => setImmediate(f), $: get, esc: s => String(s ?? ''), tq: () => 'token=t', api,
    runJob: async j => { runs.push(j); return { state: 'succeeded' }; }, show: (...a) => shown.push(a),
    blenderCopy: async () => ({}), blenderCopyNote: () => '', viewRevision: 0,
    EXAM: { sid: null, cache: {}, viewer: null, mod: { createExaminer: async () => viewer }, busy: new Map() } });
  vm.runInContext(source, ctx);
  return { ctx, els, posted, runs, shown, polls: () => polls };
}

const relayOutput = { state: 'succeeded', output: { session_id: SID, glb: 'b'.repeat(64), paused: false, resume_on_leave: false,
  summary: { draws_exported: 42, draws_total: 50, scene_draws: 40, hud_draws: 2, api: 'Vulkan', mode: 'clip',
             timings: { capture_s: 30, extract_s: 9 } },
  capture_session: { worker: 'JAYBUILTFINALE', where: 'test PC', driver: 'vulkan', moment: 'save_state' } } };

test('entering Examine on a relay session runs Capture again through a capture session', async () => {
  const h = harness(RELAY, [relayOutput]);
  await h.ctx.examineAfter(SID);
  for (let i = 0; i < 20 && !h.ctx.EXAM.cache[SID]?.shown; i++) await new Promise(r => setImmediate(r));
  assert.equal(h.posted.length, 1);
  assert.deepEqual(JSON.parse(JSON.stringify(h.posted[0])), { tool: 'scene_capture', input: { session_id: SID, relay: true } });
  const c = h.ctx.EXAM.cache[SID];
  assert.equal(c.relay, true); assert.equal(c.resume, false);
  assert.match(h.els['#ex_info'].innerHTML, /capture session on JAYBUILTFINALE \(test PC\) · vulkan · your game kept running/);
  h.ctx.examineLeave();
  assert.equal(h.runs.length, 0, 'the operator game was never paused, so nothing is resumed');
});

test('a relay scene stays loaded when coming back; only Capture again starts another capture session', async () => {
  const h = harness(RELAY, [relayOutput]);
  await h.ctx.examineAfter(SID);
  for (let i = 0; i < 20 && !h.ctx.EXAM.cache[SID]?.shown; i++) await new Promise(r => setImmediate(r));
  h.ctx.examineLeave();
  assert.equal(h.ctx.EXAM.cache[SID].stale, true);
  await h.ctx.examineAfter(SID);
  assert.equal(h.posted.length, 1, 'returning to the tab must not launch another capture session');
  h.els['#ex_cap'].onclick();
  await new Promise(r => setImmediate(r));
  assert.equal(h.posted.length, 2);
  assert.equal(h.posted[1].input.relay, true);
});

test('a supported session still pauses, captures in place and resumes on leave', async () => {
  const h = harness({ status: 'supported', relay: false }, [{ state: 'succeeded', output: {
    session_id: SID, glb: 'c'.repeat(64), paused: true, resume_on_leave: true, summary: { draws_exported: 1 } } }]);
  await h.ctx.examineAfter(SID);
  for (let i = 0; i < 20 && !h.ctx.EXAM.cache[SID]?.shown; i++) await new Promise(r => setImmediate(r));
  assert.deepEqual(JSON.parse(JSON.stringify(h.posted[0].input)), { session_id: SID });
  assert.equal(h.ctx.EXAM.cache[SID].resume, true);
  h.ctx.examineLeave();
  assert.equal(h.runs.length, 1); assert.equal(h.runs[0].input.op, 'resume');
});

test('a failed relay shows the reason with the capture-session label and resumes nothing', async () => {
  const h = harness(RELAY, [{ state: 'failed', error: 'Unsupported: No PC can run the capture session right now: x. Your game keeps running.' }]);
  await h.ctx.examineAfter(SID);
  for (let i = 0; i < 20 && !/No PC/.test(h.els['#exv'].innerHTML); i++) await new Promise(r => setImmediate(r));
  assert.match(h.els['#exv'].innerHTML, /No PC can run the capture session right now/);
  assert.doesNotMatch(h.els['#exv'].innerHTML, /Unsupported:/);
  assert.match(h.els['#exv'].innerHTML, /separate capture session \(vulkan\) at this moment; your game keeps running/);
  assert.equal(h.runs.length, 0);
});

test('2D-only and relaunch rows fall back without starting a job', async () => {
  for (const [support, label] of [[{ status: 'unsupported', reason: 'software core' }, /2D-only/],
    [{ status: 'relaunch_under_capture', relay: false, driver: 'vulkan', reason: 'Yuzu relaunch' }, /Relaunch with Examine 3D on/]]) {
    const h = harness(support, []);
    await h.ctx.examineAfter(SID);
    assert.equal(h.posted.length, 0);
    assert.match(h.els['#exv'].innerHTML, label);
  }
});
