// #993 "Auto report: apply mod failed ... Failure: Cannot read properties of undefined (reading 'state')": every job loop in
// the desktop shell read `.state` off `gbox.api(...).data` without checking the answer, so a lost request or a bodiless
// answer surfaced as a TypeError in the auto report. jobOf / jobWait turn that into words, modPlay names the step it was
// on, and gameJob (the pick-whip character drop onto a running game) goes through the same guard.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '../clients/desktop/index.html'), 'utf8');

const modsStart = html.indexOf('async function modRun(c, sid) {');
const modsEnd = html.indexOf('document.addEventListener("click", e => {', modsStart);
const gameStart = html.indexOf('async function gameJob(tool, input, wait = true) {');
const gameEnd = html.indexOf('function toast(t, ms', gameStart);
assert.ok(modsStart > 0 && modsEnd > modsStart && gameStart > 0 && gameEnd > gameStart, 'exercise the real desktop functions');

function harness(answers) {                                 // answers: path -> value | function(path, body) | Error to throw
  const calls = [], toasts = [], delays = [];
  const ctx = {
    gbox: { api: async (p, body) => {
      calls.push([p, body === undefined ? undefined : JSON.parse(JSON.stringify(body))]);
      const a = Object.entries(answers).find(([k]) => p.startsWith(k))?.[1];
      const v = typeof a === 'function' ? a(p, body) : a;
      if (v instanceof Error) throw v;
      return v;
    }, captureOS: async () => null, token: async () => 't' },
    toast: (t, ms) => toasts.push(t), S: { workerName: 'JAYBUILTFINALE', apiUrl: 'http://spark:8080' },
    document: { querySelector: () => null }, setTimeout: (fn, ms) => { delays.push(ms); fn(); }, EMB: { sid: '' },
    chatContext: async () => ({}),
    liveSessions: () => ctx.gbox.api('/api/sessions?include_ended=false'),   // #712: the shared running-sessions read
  };
  ctx.window = ctx;
  vm.createContext(ctx);
  vm.runInContext(html.slice(modsStart, modsEnd), ctx);
  vm.runInContext(html.slice(gameStart, gameEnd), ctx);
  return { ctx, calls, toasts, delays };
}
const notTypeError = err => { assert.notEqual(err.constructor.name, 'TypeError', `a TypeError leaked: ${err.message}`); assert.ok(!/reading '/.test(err.message)); return true; };

test('jobOf names the tool and says what is missing instead of dereferencing undefined', () => {
  const { ctx } = harness({}), j = ctx.jobOf;
  assert.throws(() => j({ ok: true, data: undefined }, 'session_op'), { message: 'session_op: job request failed' });
  assert.throws(() => j({ ok: true }, 'session_op', 'Could not capture desktop'), { message: 'session_op: Could not capture desktop' });
  assert.throws(() => j({ ok: false, error: 'worker JAYBUILTFINALE is offline' }, '@launch'), { message: '@launch: worker JAYBUILTFINALE is offline' });
  assert.throws(() => j(undefined, 'pick'), { message: 'pick: job request failed' });
  assert.throws(() => j({ ok: true, data: { id: 'x' } }, 'pick'), { message: 'pick: invalid job response' });
  assert.throws(() => j({ ok: true, data: 'queued' }, 'pick'), { message: 'pick: invalid job response' });
  const job = { id: 'j1', state: 'queued' };
  assert.equal(j({ ok: true, data: job }, 'x'), job);
});

test('jobWait polls until the job settles and turns a lost poll into words with the job id', async () => {
  let n = 0;
  const h = harness({ '/api/jobs/j1': () => [{ ok: true, data: { id: 'j1', state: 'running' } }, { ok: false, error: 'connection reset' }][n++] });
  await assert.rejects(h.ctx.jobWait({ id: 'j1', state: 'queued' }, 'session_op', 400), err => {
    assert.equal(err.message, 'session_op (job j1): connection reset'); return notTypeError(err); });
  assert.deepEqual(h.delays, [400, 400]);
  const empty = harness({ '/api/jobs/j2': { ok: true, data: undefined } });
  await assert.rejects(empty.ctx.jobWait({ id: 'j2', state: 'running' }, 'characters'), { message: 'characters (job j2): job status unavailable' });
  const thrown = harness({ '/api/jobs/j3': new TypeError("Cannot read properties of undefined (reading 'state')") });
  await assert.rejects(thrown.ctx.jobWait({ id: 'j3', state: 'running' }, 'characters'), err => {   // the thrown text is kept, named
    assert.equal(err.message, "characters (job j3): Cannot read properties of undefined (reading 'state')");
    assert.notEqual(err.constructor.name, 'TypeError'); return true; });
  const capped = harness({ '/api/jobs/j4': { ok: true, data: { id: 'j4', state: 'running' } } });
  const still = await capped.ctx.jobWait({ id: 'j4', state: 'running' }, 'get_frame', 500, 3);
  assert.equal(still.state, 'running'); assert.equal(capped.calls.length, 3);
  const done = await capped.ctx.jobWait({ id: 'j5', state: 'succeeded' }, 'x');
  assert.equal(done.id, 'j5'); assert.equal(capped.calls.length, 3);
});

test('#993 reproduced: modRun with a bodiless job answer fails in words, not with a TypeError', async () => {
  const h = harness({ '/api/jobs': { ok: true, data: undefined } });
  await assert.rejects(h.ctx.modRun({ tool: 'session_op', input: { op: 'load_state', args: { slot: 40 } } }, 'JAYBUILTFINALE-s1'),
    err => { assert.equal(err.message, 'session_op: job request failed'); assert.equal(err.jobId, undefined); return notTypeError(err); });
  const swap = harness({ '/api/sessions/': { ok: false, error: 'session not found' } });
  await assert.rejects(swap.ctx.modRun({ tool: '@launch', input: { mod: 'mgs_vr_hucast_fit' } }, 'JAYBUILTFINALE-s1'), { message: '@launch: session not found' });
  const lost = harness({ '/api/jobs/': { ok: false, error: 'Spark restarting' }, '/api/jobs': { ok: true, data: { id: 'j9', state: 'queued' } } });
  await assert.rejects(lost.ctx.modRun({ tool: 'session_op', input: {} }, 'w-s'), { message: 'session_op (job j9): Spark restarting' });
});

test('modPlay reports the step it was on and a readable failure to the auto report and the toast', async () => {
  const mod = { id: 'm1', title: 'HUcast in Metal Gear Solid VR Missions (Sneaking Mode)', game_id: 'afd2fc507bb69843', game_title: 'Metal Gear Solid - VR Missions',
    calls: [], state_slot: 40 };
  const h = harness({ '/api/sessions': { ok: true, data: [{ session_id: 'JAYBUILTFINALE-s1', state: 'running', game_id: 'afd2fc507bb69843' }] },
    '/api/jobs': { ok: true, data: undefined }, '/api/requests/auto-mod-failure': { ok: true, data: { number: 993 } } });
  await h.ctx.modPlay(mod, 'moment');
  const report = h.calls.find(([p]) => p === '/api/requests/auto-mod-failure')[1];
  assert.equal(report.detail.split('\n')[0], 'Could not load the saved moment: session_op: job request failed');
  assert.equal(report.job_id, ''); assert.equal(report.session_id, 'JAYBUILTFINALE-s1'); assert.equal(report.action, 'apply mod'); assert.equal(report.target, 'moment');
  assert.equal(h.toasts.at(-1), '⚠ Could not load the saved moment: session_op: job request failed · auto report #993');
  // the mod's own calls: the step names the tool
  const withCall = harness({ '/api/sessions': { ok: true, data: [{ session_id: 'w-s1', state: 'running', game_id: 'g' }] },
    '/api/jobs': { ok: false, error: 'worker w is offline' }, '/api/requests/auto-mod-failure': { ok: true, data: { number: 5 } } });
  await withCall.ctx.modPlay({ id: 'm', title: 'T', game_id: 'g', calls: [{ tool: 'characters', input: { op: 'use', character: 'hucast' } }] }, 'apply');
  assert.equal(withCall.calls.find(([p]) => p === '/api/requests/auto-mod-failure')[1].detail.split('\n')[0], 'Could not apply characters: characters: worker w is offline');
  // a launch that answers with no body, or with a body that is not a job
  const launch = harness({ '/api/sessions': { ok: true, data: [] }, '/api/games/': { ok: true }, '/api/requests/auto-mod-failure': { ok: true, data: { number: 6 } } });
  await launch.ctx.modPlay({ id: 'm', title: 'T', game_id: 'g', game_title: 'Crazy Taxi', calls: [] }, 'play');
  assert.equal(launch.calls.find(([p]) => p === '/api/requests/auto-mod-failure')[1].detail.split('\n')[0], 'Could not find or start the game: Launch of Crazy Taxi: game launch request failed');
  const odd = harness({ '/api/sessions': { ok: true, data: [] }, '/api/games/': { ok: true, data: {} }, '/api/requests/auto-mod-failure': { ok: true, data: { number: 7 } } });
  await odd.ctx.modPlay({ id: 'm', title: 'T', game_id: 'g', game_title: 'Crazy Taxi', calls: [] }, 'play');
  assert.equal(odd.calls.find(([p]) => p === '/api/requests/auto-mod-failure')[1].detail.split('\n')[0], 'Could not find or start the game: Launch of Crazy Taxi: invalid job response');
});

test('an unexpected TypeError is still reported as the app\'s own fault with the step, and a bodiless report answer cannot break the toast', async () => {
  const { ctx } = harness({});
  assert.equal(ctx.modFailureText(new TypeError("Cannot read properties of undefined (reading 'state')"), 'load the saved moment'),
    "Could not load the saved moment: gBox's app hit an internal error (Cannot read properties of undefined (reading 'state'))");
  assert.equal(ctx.modFailureText({ message: "Cannot read properties of undefined (reading 'state')" }, 'apply session_op'),   // another realm's TypeError
    "Could not apply session_op: gBox's app hit an internal error (Cannot read properties of undefined (reading 'state'))");
  assert.equal(ctx.modFailureText(new Error('session_op: native load rejected'), 'load the saved moment'), 'Could not load the saved moment: session_op: native load rejected');
  assert.equal(ctx.modFailureText(undefined, 'open the mod'), 'Could not open the mod: unknown error');
  const h = harness({ '/api/sessions': { ok: true, data: [{ session_id: 'w-s1', state: 'running', game_id: 'g' }] },
    '/api/jobs': new TypeError("Cannot read properties of undefined (reading 'state')"), '/api/requests/auto-mod-failure': { ok: true, data: undefined } });
  await h.ctx.modPlay({ id: 'm', title: 'T', game_id: 'g', calls: [], state_slot: 1 }, 'moment');
  assert.equal(h.calls.find(([p]) => p === '/api/requests/auto-mod-failure')[1].detail.split('\n')[0],
    "Could not load the saved moment: gBox's app hit an internal error (Cannot read properties of undefined (reading 'state'))");
  assert.equal(h.toasts.at(-1), "⚠ Could not load the saved moment: gBox's app hit an internal error (Cannot read properties of undefined (reading 'state'))");
});

test('gameJob (pick-whip character drop onto a running game) fails in words and keeps its success shape', async () => {
  const bodiless = harness({ '/api/jobs': { ok: true, data: undefined } });
  await assert.rejects(bodiless.ctx.gameJob('characters', { op: 'live_use', character: 'hucast', session_id: 'w-s1' }),
    err => { assert.equal(err.message, 'characters: job request failed'); return notTypeError(err); });
  let n = 0;
  const lost = harness({ '/api/jobs/c1': () => [{ ok: true, data: { id: 'c1', state: 'running' } }, undefined][n++], '/api/jobs': { ok: true, data: { id: 'c1', state: 'queued' } } });
  await assert.rejects(lost.ctx.gameJob('characters', { op: 'live_use', session_id: 'w-s1' }), { message: 'characters (job c1): job status unavailable' });
  const failed = harness({ '/api/jobs': { ok: true, data: { id: 'c2', state: 'failed', error: 'no model at that point' } } });
  await assert.rejects(failed.ctx.gameJob('characters', { session_id: 'w-s1' }), err => { assert.equal(err.message, 'no model at that point'); assert.equal(err.jobId, 'c2'); return true; });
  const ok = harness({ '/api/jobs': { ok: true, data: { id: 'c3', state: 'succeeded', output: { result: { status: 'applied', message: 'HUcast is in' } } } } });
  assert.deepEqual(JSON.parse(JSON.stringify(await ok.ctx.gameJob('characters', { session_id: 'w-s1' }))), { status: 'applied', message: 'HUcast is in', job_id: 'c3' });
  assert.equal(ok.calls[0][1].require_worker, 'w');
  const nowait = harness({ '/api/jobs': { ok: true, data: { id: 'c4', state: 'queued' } } });
  assert.equal((await nowait.ctx.gameJob('session_op', { session_id: 'w-s1', op: 'save_state' }, false)).job_id, 'c4');
  assert.equal(nowait.calls.length, 1);
  await assert.rejects(harness({}).ctx.gameJob('session_op', {}), { message: 'no game running' });
});
