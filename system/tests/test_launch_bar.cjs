// Launch bar (#1635): the full-width bar above the desktop status strip while a game launch runs
// (clients/web/viz/launch-bar.js, mounted by clients/desktop/index.html).
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const factory = require('../clients/web/viz/launch-bar.js');

const LB = factory({ document: undefined });
const tick = () => new Promise(resolve => setImmediate(resolve));

// ---------- a small DOM: enough for the bar's createElement/appendChild/textContent/style/events ----------
function fakeDocument() {
  const byId = new Map();
  class El {
    constructor(tag) { this.tagName = tag.toUpperCase(); this.children = []; this.parentNode = null; this.style = { setProperty(k, v) { this[k] = v; } };
      this.attrs = {}; this.listeners = {}; this._text = ''; this._cls = ''; this._id = ''; }
    get id() { return this._id; } set id(v) { this._id = v; byId.set(v, this); }
    get className() { return this._cls; } set className(v) { this._cls = v; this.classChanges = (this.classChanges || 0) + 1; }
    get classList() { const el = this; return { contains: c => el._cls.split(/\s+/).includes(c) }; }
    get textContent() { return this._text + this.children.map(c => c.textContent).join(''); }
    set textContent(v) { this._text = String(v); this.children = []; }
    get offsetWidth() { return this.tagName === 'SPAN' && this._cls === 'lb-line' ? this._text.length * 6 + (parseInt(this.style.paddingLeft) || 0) : 0; }
    get clientWidth() { return this._cls === 'lb-view' ? 600 : 0; }
    appendChild(c) { c.parentNode = this; this.children.push(c); return c; }
    removeChild(c) { this.children = this.children.filter(x => x !== c); c.parentNode = null; return c; }
    setAttribute(k, v) { this.attrs[k] = String(v); } getAttribute(k) { return this.attrs[k]; } removeAttribute(k) { delete this.attrs[k]; }
    addEventListener(t, fn) { (this.listeners[t] ||= []).push(fn); }
    fire(t, e = {}) { for (const fn of this.listeners[t] || []) fn({ target: this, stopPropagation() {}, ...e }); }
    find(cls) { if (this._cls.split(/\s+/).includes(cls)) return this; for (const c of this.children) { const f = c.find(cls); if (f) return f; } return null; }
  }
  const doc = { createElement: tag => new El(tag), getElementById: id => byId.get(id) || null, head: new El('head'), body: new El('body') };
  return doc;
}
function bar(opts = {}) {
  const document = fakeDocument(), frames = [], timers = [], details = [];
  const env = { document, matchMedia: () => ({ matches: !!opts.reduced, addEventListener() {} }) };
  let clock = 1_000_000;
  const api = factory(env).mount({ bottom: 28, raf: opts.raf === false ? null : fn => { frames.push(fn); return frames.length; },
    setTimeout: (fn, ms) => { timers.push({ fn, ms }); return timers.length; }, clearTimeout() {},
    now: () => clock, fetchJob: opts.fetchJob || (async () => null), onDetails: (job, v) => details.push({ job, v }) });
  const part = cls => api.el.find(cls);
  return { api, document, frames, timers, details, part, advance: ms => { clock += ms; },
    lines: () => part('lb-track').children.map(c => c._text) };
}
const launch = (extra = {}) => ({ id: 'L1', tool: 'launch_game', state: 'running', created: 100,
  input: { game: { game_id: 'doa2', title: 'Dead or Alive 2' }, mod: 'doa2_roster_59d8ed0e' }, ...extra });
const fetching = (done, total = 1272, pct = 20 + Math.floor(8 * done / total)) => launch({
  progress: { pct, msg: `Fetching mod doa2_roster_59d8ed0e from the collection: ${done}/${total} MB`, ts: 5 },
  progress_log: ['Launching Dead or Alive 2', `Fetching mod doa2_roster_59d8ed0e from the collection: ${done}/${total} MB`] });

// ---------- colour ----------
test('the fill colour runs red at 0%, green at 33%, blue at 66%, white at 100%', () => {
  assert.deepEqual(LB.colorAt(0), [229, 38, 38]);
  assert.deepEqual(LB.colorAt(33), [34, 197, 94]);
  assert.deepEqual(LB.colorAt(66), [47, 107, 255]);
  assert.deepEqual(LB.colorAt(100), [255, 255, 255]);
  assert.deepEqual(LB.colorAt(16.5), [132, 118, 66], 'halfway between red and green');
  assert.deepEqual(LB.colorAt(83), [151, 181, 255], 'halfway between blue and white');
  assert.deepEqual(LB.colorAt(-5), LB.colorAt(0)); assert.deepEqual(LB.colorAt(140), LB.colorAt(100));
  assert.deepEqual(LB.colorAt(NaN), LB.colorAt(0));
});

test('the fill gradient shows every colour the bar has passed, the current one at its edge', () => {
  assert.equal(LB.fillGradient(0), 'rgb(229, 38, 38)');
  assert.equal(LB.fillGradient(20), `linear-gradient(90deg, rgb(229, 38, 38) 0.0%, ${LB.rgb(LB.colorAt(20))} 100%)`);
  assert.equal(LB.fillGradient(50), 'linear-gradient(90deg, rgb(229, 38, 38) 0.0%, rgb(34, 197, 94) 66.0%, ' + LB.rgb(LB.colorAt(50)) + ' 100%)');
  assert.equal(LB.fillGradient(100), 'linear-gradient(90deg, rgb(229, 38, 38) 0.0%, rgb(34, 197, 94) 33.0%, rgb(47, 107, 255) 66.0%, rgb(255, 255, 255) 100%)');
});

// ---------- message parsing ----------
test('"x/y MB" counters parse, with thousands separators and other units', () => {
  assert.deepEqual(LB.fraction('Fetching mod doa2_roster_59d8ed0e from the collection: 960/1272 MB'), { done: 960, total: 1272, f: 960 / 1272 });
  assert.equal(LB.fraction('Staging x.iso: 1,024 / 2,048 MB · 2 min left').f, 0.5);
  assert.equal(LB.fraction('copy 512 MB / 2 GB').f, 0.25);
  assert.equal(LB.fraction('Staging x.iso (4,300 MB) to the fast local cache'), null);
  assert.equal(LB.fraction('Starting dolphin with x.iso'), null);
  assert.equal(LB.fraction('0/0 MB'), null);
});

test('progress: the job percent, refined inside the fetch and staging stages; none means indeterminate', () => {
  const p = LB.progressOf(fetching(960));                          // the worker rounds 20 + 8 * 960/1272 down to 26
  assert.ok(Math.abs(p.pct - (20 + 8 * 960 / 1272)) < 1e-9 && p.determinate);
  const staging = LB.progressOf({ progress: { pct: 30, msg: 'Staging DOA2.gdi: 500 / 1,000 MB' } });
  assert.equal(staging.pct, 50);
  assert.equal(LB.progressOf({ progress: { pct: 72, msg: 'Starting dolphin with DOA2.iso' } }).pct, 72);
  assert.equal(LB.progressOf({ progress: { msg: 'copying 300/600 MB' } }).pct, 50, 'a counter alone is a percent');
  assert.equal(LB.progressOf({ progress: { pct: 90, msg: 'Staging DOA2.gdi: 500 / 1,000 MB' } }).pct, 90, 'outside the stage band the job percent stands');
  const none = LB.progressOf({ state: 'queued' });
  assert.equal(none.pct, null); assert.equal(none.determinate, false);
});

test('console lines: a ticking counter collapses to its newest value; ANSI codes go', () => {
  const lines = LB.linesOf({ progress_log: ['\x1b[32mLaunching DOA2\x1b[0m', 'Fetching mod m from the collection: 1/9 MB',
    'Fetching mod m from the collection: 5/9 MB', 'Staging DOA2.gdi'], progress: { msg: 'Staging DOA2.gdi' } });
  assert.deepEqual(lines, ['Launching DOA2', 'Fetching mod m from the collection: 5/9 MB', 'Staging DOA2.gdi']);
  assert.deepEqual(LB.linesOf({ progress: 'Starting…' }), ['Starting…']);
});

// ---------- model ----------
test('only launches show: launch_game and session_swap, queued or running', () => {
  const m = LB.createModel();
  m.remote([{ id: 'x', tool: 'characters', state: 'running' }, { id: 'y', tool: 'session_op', state: 'running' }]);
  assert.equal(m.view().state, 'hidden');
  m.remote([fetching(960)]);
  const v = m.view();
  assert.equal(v.state, 'running'); assert.equal(v.title, 'Launching Dead or Alive 2 · doa2_roster_59d8ed0e');
  assert.equal(v.count, 1); assert.ok(v.determinate);
  assert.equal(v.lines.at(-1), 'Fetching mod doa2_roster_59d8ed0e from the collection: 960/1272 MB');
});

test('a queued launch with no progress yet is indeterminate and says it is waiting', () => {
  const m = LB.createModel();
  m.remote([launch({ state: 'queued' })]);
  const v = m.view();
  assert.equal(v.determinate, false); assert.equal(v.pct, null); assert.deepEqual(v.lines, ['Waiting for a free PC…']);
});

test('concurrent launches show the newest with a count; a swap and its launch count once', () => {
  const m = LB.createModel();
  const swap = { id: 'S', tool: 'session_swap', state: 'running', created: 300, input: { game_id: 'doa2', mod: 'roster' },
    progress: { pct: 66, msg: 'Starting Dead or Alive 2 with roster on PC', ts: 9 } };
  const child = launch({ id: 'C', created: 310, progress: { pct: 50, msg: 'Staging DOA2.gdi: 500 / 1,000 MB', ts: 10 } });
  const other = { id: 'O', tool: 'launch_game', state: 'running', created: 200, input: { game: { game_id: 'ct', title: 'Crazy Taxi' } } };
  m.remote([swap, child, other]);
  const v = m.view();
  assert.equal(v.count, 2); assert.equal(v.title, 'Swapping Dead or Alive 2 · roster');
  assert.equal(v.pct, 66 + 34 * 0.5, 'the launch fills what is left of the swap');
  assert.equal(v.job.id, 'C', 'details open the job with the newest progress');
  m.remote([other]);                                             // the newest launch left the feed
});

test('the bar never runs backwards within one launch', () => {
  const m = LB.createModel();
  m.remote([launch({ progress: { pct: 60, msg: 'a' } })]); assert.equal(m.view().pct, 60);
  m.remote([launch({ progress: { pct: 40, msg: 'b' } })]); assert.equal(m.view().pct, 60);
});

test('a launch that leaves the feed is looked up once: success shows done, failure shows the reason', async () => {
  const asked = [];
  let answer = { id: 'L1', tool: 'launch_game', state: 'succeeded' };
  const m = LB.createModel({ fetchJob: async id => { asked.push(id); return answer; } });
  m.remote([fetching(960)]); m.remote([]); await tick();
  assert.deepEqual(asked, ['L1']); assert.equal(m.view().state, 'done');
  answer = { id: 'L2', tool: 'launch_game', state: 'failed', error: 'dolphin exited 1: missing BIOS' };
  m.remote([launch({ id: 'L2' })]); assert.equal(m.view().state, 'running', 'a new launch replaces the done flash');
  m.remote([]); await tick();
  const v = m.view();
  assert.equal(v.state, 'error'); assert.equal(v.reason, 'dolphin exited 1: missing BIOS'); assert.equal(v.job.id, 'L2');
  m.remote([]); await tick(); assert.deepEqual(asked, ['L1', 'L2'], 'a finished launch is not asked for again');
  m.remote([launch({ id: 'L3' })]); assert.equal(m.view().state, 'running', 'a new launch replaces the error');
});

test('a stale feed does not end a launch: the lookup says it is still running', async () => {
  const m = LB.createModel({ fetchJob: async () => launch({ state: 'running' }) });
  m.remote([launch()]); m.remote([]); await tick();
  assert.equal(m.view().state, 'running');
});

test('jobWait records count: a launch shows on its first answer and settles from its final record', async () => {
  let clock = 0;
  const m = LB.createModel({ now: () => clock, fetchJob: async () => { throw new Error('must not be asked'); } });
  m.observe(launch({ state: 'queued' })); assert.equal(m.view().state, 'running');
  m.remote([]); await tick(); assert.equal(m.view().state, 'running', 'jobWait is following it: the feed may lag');
  clock += 500; await m.observe(launch({ state: 'failed', error: 'no worker' }));
  assert.equal(m.view().state, 'error'); assert.equal(m.view().reason, 'no worker');
  m.observe({ id: 'g', tool: 'get_frame', state: 'running' }); assert.equal(m.view().state, 'error');
});

test('marquee feed: the latest two lines first, then only new ones; a ticking counter replaces its line', () => {
  const m = LB.createModel();
  m.remote([launch({ progress_log: ['one', 'two', 'three', 'Fetching mod m from the collection: 1/9 MB'], progress: { pct: 20, msg: 'Fetching mod m from the collection: 1/9 MB' } })]);
  assert.deepEqual(m.drain().map(x => x.text), ['three', 'Fetching mod m from the collection: 1/9 MB']);
  assert.deepEqual(m.drain(), []);
  m.remote([launch({ progress_log: ['one', 'two', 'three', 'Fetching mod m from the collection: 1/9 MB', 'Fetching mod m from the collection: 6/9 MB'],
    progress: { pct: 25, msg: 'Fetching mod m from the collection: 6/9 MB' } })]);
  assert.deepEqual(m.drain(), [{ text: 'Fetching mod m from the collection: 6/9 MB', replace: true }]);
  m.remote([launch({ progress_log: ['three', 'Fetching mod m from the collection: 9/9 MB', 'Staging DOA2.gdi', 'Starting dolphin with DOA2.iso'],
    progress: { pct: 72, msg: 'Starting dolphin with DOA2.iso' } })]);
  assert.deepEqual(m.drain(), [{ text: 'Fetching mod m from the collection: 9/9 MB', replace: true },
    { text: 'Staging DOA2.gdi', replace: false }, { text: 'Starting dolphin with DOA2.iso', replace: false }]);
});

// ---------- the bar in a page ----------
test('renders above the strip: determinate fill width, colour, percent and the scrolling console', () => {
  const b = bar();
  assert.equal(b.api.el.id, 'launchbar'); assert.equal(b.api.el.style['--lb-bottom'], '28px');
  assert.ok(b.document.getElementById('gbox-launchbar-css').textContent.includes('prefers-reduced-motion'));
  assert.equal(b.api.el.className, '', 'hidden until a launch runs');
  b.api.remote([fetching(960)]);
  const el = b.api.el, fill = b.part('lb-fill'), pct = 20 + 8 * 960 / 1272;
  assert.equal(el.className, 'on');
  assert.equal(fill.style.width, pct.toFixed(1) + '%');
  assert.equal(fill.style.background, LB.fillGradient(pct));
  assert.match(fill.style.boxShadow, /rgb\(/);
  assert.equal(b.part('lb-pct').textContent, '26%');
  assert.equal(b.part('lb-title').textContent, 'Launching Dead or Alive 2 · doa2_roster_59d8ed0e');
  assert.equal(el.attrs['aria-valuenow'], '26'); assert.equal(el.attrs.role, 'progressbar');
  assert.deepEqual(b.lines(), ['Launching Dead or Alive 2', 'Fetching mod doa2_roster_59d8ed0e from the collection: 960/1272 MB']);
  assert.equal(b.part('lb-count').style.display, 'none');
  assert.equal(b.frames.length, 1, 'the marquee animates on animation frames');
});

test('marquee: scrolls right to left, appends new lines at the end, hover pauses it', () => {
  const b = bar({ raf: false });
  b.api.remote([fetching(100)]);
  const track = b.part('lb-track');
  b.api.tick(1000);
  const x1 = parseFloat(track.style.transform.match(/-?[\d.]+/)[0]);
  b.api.tick(1000);
  const x2 = parseFloat(track.style.transform.match(/-?[\d.]+/)[0]);
  assert.ok(x2 < x1, 'moves left');
  b.api.remote([fetching(900)]);
  assert.deepEqual(b.lines(), ['Launching Dead or Alive 2', 'Fetching mod doa2_roster_59d8ed0e from the collection: 900/1272 MB'], 'the counter updates in place');
  b.api.remote([launch({ progress: { pct: 30, msg: 'Staging DOA2.gdi (1,272 MB) to the fast local cache' },
    progress_log: ['Fetching mod doa2_roster_59d8ed0e from the collection: 1272/1272 MB', 'Staging DOA2.gdi (1,272 MB) to the fast local cache'] })]);
  assert.equal(b.lines().at(-1), 'Staging DOA2.gdi (1,272 MB) to the fast local cache', 'newest appended');
  b.api.el.fire('mouseenter');
  assert.equal(b.api.tick(1000), false);
  const paused = track.style.transform; b.api.tick(1000); assert.equal(track.style.transform, paused);
  b.api.el.fire('mouseleave'); b.api.tick(500); assert.notEqual(track.style.transform, paused);
  for (let i = 0; i < 200; i++) b.api.tick(100);                // all lines read: the latest comes round again
  assert.ok(b.lines().length >= 1); assert.equal(b.lines().at(-1), 'Staging DOA2.gdi (1,272 MB) to the fast local cache');
});

test('a burst of lines keeps only the newest few waiting to scroll in', () => {
  const b = bar({ raf: false });
  const log = Array.from({ length: 12 }, (_, i) => `step ${'abcdefghijkl'[i]} of the launch with a long description`);
  b.api.remote([launch({ progress_log: log.slice(0, 1), progress: { pct: 10, msg: log[0] } })]);
  for (let i = 2; i <= 12; i++) b.api.remote([launch({ progress_log: log.slice(0, i), progress: { pct: 10 + i, msg: log[i - 1] } })]);
  assert.ok(b.lines().length <= 6, `${b.lines().length} spans`);
  assert.equal(b.lines().at(-1), log[11]);
});

test('indeterminate launches sweep instead of filling', () => {
  const b = bar();
  b.api.remote([launch({ state: 'queued' })]);
  assert.equal(b.api.el.className, 'on ind');
  assert.equal(b.part('lb-pct').textContent, '');
  assert.equal(b.api.el.attrs['aria-valuenow'], undefined);
});

test('reduced motion: the latest line stands still, nothing animates', () => {
  const b = bar({ reduced: true });
  b.api.remote([fetching(960)]);
  assert.equal(b.api.el.className, 'on still');
  assert.equal(b.part('lb-static').textContent, 'Fetching mod doa2_roster_59d8ed0e from the collection: 960/1272 MB');
  assert.equal(b.frames.length, 0);
  assert.equal(b.api.tick(1000), false);
});

test('success fills to white, then fades and hides', async () => {
  const b = bar({ fetchJob: async () => ({ id: 'L1', tool: 'launch_game', state: 'succeeded' }) });
  b.api.remote([fetching(960)]); b.api.remote([]); await tick();
  assert.equal(b.api.el.className, 'on still done');
  assert.equal(b.part('lb-fill').style.background, LB.fillGradient(100));
  assert.equal(b.part('lb-pct').textContent, '100%');
  assert.match(b.part('lb-title').textContent, /^✓ Dead or Alive 2/);
  const [fade, hide] = b.timers;
  fade.fn(); assert.equal(b.api.el.className, 'on still done fade');
  b.api.remote([]); assert.equal(b.api.el.className, 'on still done fade', 'the next poll keeps the fade');
  hide.fn(); assert.equal(b.api.el.className, '');
});

test('failure: a red line with the reason; click opens details, x closes', async () => {
  const b = bar({ fetchJob: async () => ({ id: 'L1', tool: 'launch_game', state: 'failed', error: 'dolphin exited 1: missing BIOS' }) });
  b.api.remote([fetching(960)]); b.api.remote([]); await tick();
  const el = b.api.el;
  assert.equal(el.className, 'on still err');
  assert.equal(b.part('lb-static').textContent, 'dolphin exited 1: missing BIOS');
  assert.equal(b.part('lb-title').textContent, '✕ Launch failed: Dead or Alive 2 · doa2_roster_59d8ed0e');
  assert.match(el.title, /click for details/);
  el.fire('click');
  assert.equal(b.details.length, 1); assert.equal(b.details[0].job.id, 'L1'); assert.equal(b.details[0].job.error, 'dolphin exited 1: missing BIOS');
  el.fire('click', { target: b.part('lb-x') });
  assert.equal(el.className, ''); assert.equal(b.details.length, 1);
});

test('x on a running launch hides it until that launch ends; the launch keeps going', () => {
  const b = bar();
  b.api.remote([fetching(100)]);
  b.api.el.fire('click', { target: b.part('lb-x') });
  assert.equal(b.api.el.className, '');
  b.api.remote([fetching(600)]); assert.equal(b.api.el.className, '');
});

test('two launches: the newest shows with a +1 count', () => {
  const b = bar();
  b.api.remote([launch(), { id: 'O', tool: 'launch_game', state: 'running', created: 50, input: { game: { game_id: 'ct', title: 'Crazy Taxi' } } }]);
  assert.equal(b.part('lb-count').textContent, '+1'); assert.equal(b.part('lb-count').style.display, '');
  assert.match(b.part('lb-title').textContent, /Dead or Alive 2/);
});

test('the root element only changes when the state does (the docked game window re-cuts on root mutations)', () => {
  const b = bar();
  b.api.remote([fetching(100)]); const n = b.api.el.classChanges;
  for (let i = 2; i < 9; i++) b.api.remote([fetching(i * 100)]);
  assert.equal(b.api.el.classChanges, n);
});

// ---------- desktop wiring ----------
test('the desktop mounts the bar on the strip and feeds it from the existing polls only', () => {
  const desk = fs.readFileSync(path.join(__dirname, '../clients/desktop/index.html'), 'utf8');
  assert.match(desk, /<script src="\.\.\/web\/viz\/launch-bar\.js"><\/script>/);
  assert.match(desk, /GBOX_LAUNCH_BAR = window\.GBoxLaunchBar\?\.mount\(\{ bottom: 28,/);
  assert.match(desk, /onDetails: job => tvOpen\(job\.id, "job"\)/);
  assert.match(desk, /activity\?\.remote\(jobs\.data\); globalThis\.GBOX_LAUNCH_BAR\?\.remote\(jobs\.data\);/);
  const wait = desk.slice(desk.indexOf('async function jobWait('), desk.indexOf('async function modSession('));
  assert.equal((wait.match(/GBOX_LAUNCH_BAR\?\.observe\(j\)/g) || []).length, 2);
  const bar = fs.readFileSync(path.join(__dirname, '../clients/web/viz/launch-bar.js'), 'utf8');
  assert.doesNotMatch(bar, /setInterval|fetch\(/, 'no polling of its own');
});
