// Launch failure reports in the clients (docs/launch-failure-reports.md): a failed launch's ticket shows as
// "Reported as #N, being investigated" / "Fixed, verified (#N)" on the desktop launch bar (clients/web/viz/launch-bar.js),
// on the Mods page cards (clients/web/viz/mods-gallery.js) and in the web Library / launch screen.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const factory = require('../clients/web/viz/launch-bar.js');
const MG = require('../clients/web/viz/mods-gallery.js');

const LB = factory({ document: undefined });
const tick = () => new Promise(resolve => setImmediate(resolve));

function fakeDocument() {
  const byId = new Map();
  class El {
    constructor(tag) { this.tagName = tag.toUpperCase(); this.children = []; this.parentNode = null; this.style = { setProperty(k, v) { this[k] = v; } };
      this.attrs = {}; this.listeners = {}; this._text = ''; this._cls = ''; this._id = ''; }
    get id() { return this._id; } set id(v) { this._id = v; byId.set(v, this); }
    get className() { return this._cls; } set className(v) { this._cls = v; }
    get textContent() { return this._text + this.children.map(c => c.textContent).join(''); }
    set textContent(v) { this._text = String(v); this.children = []; }
    get offsetWidth() { return 0; } get clientWidth() { return 600; }
    appendChild(c) { c.parentNode = this; this.children.push(c); return c; }
    removeChild(c) { this.children = this.children.filter(x => x !== c); c.parentNode = null; return c; }
    setAttribute(k, v) { this.attrs[k] = String(v); } getAttribute(k) { return this.attrs[k]; } removeAttribute(k) { delete this.attrs[k]; }
    addEventListener(t, fn) { (this.listeners[t] ||= []).push(fn); }
    fire(t, e = {}) { for (const fn of this.listeners[t] || []) fn({ target: this, stopPropagation() {}, ...e }); }
    find(cls) { if (this._cls.split(/\s+/).includes(cls)) return this; for (const c of this.children) { const f = c.find(cls); if (f) return f; } return null; }
  }
  return { createElement: tag => new El(tag), getElementById: id => byId.get(id) || null, head: new El('head'), body: new El('body') };
}

const DOA2 = { game_id: '1de2e7634f3161ff', title: 'Dead or Alive 2' };
const launch = extra => ({ id: 'L1', tool: 'launch_game', state: 'running', created: 100, input: { game: DOA2, mod: 'doa2_roster_59d8ed0e' },
  progress: { pct: 80, msg: 'Starting retroarch with DOA2.gdi', ts: 5 }, ...extra });
const ERR = 'RuntimeError: retroarch started but content not running after 30s: [WARN] GDROM not ready';
const REPORT = { request_id: 'r12', number: 12, status: 'in_progress', state: 'investigating', verified: false,
                 label: 'retroarch content not running after 30s', text: 'Reported as #12, being investigated' };

function bar(fetchJob) {
  const document = fakeDocument(), timers = [], reports = [], details = [];
  const api = factory({ document, matchMedia: () => ({ matches: true, addEventListener() {} }) }).mount({
    bottom: 28, raf: null, now: () => 1_000_000, fetchJob,
    setTimeout: (fn, ms) => { timers.push({ fn, ms }); return timers.length; }, clearTimeout() {},
    onDetails: job => details.push(job), onReport: (r, job) => reports.push({ r, job }) });
  return { api, timers, reports, details, part: cls => api.el.find(cls) };
}

test('the badge words match the server (gbox/launch_failures.badge)', () => {
  assert.equal(LB.reportText(null), '');
  assert.equal(LB.reportText({ number: 12 }), 'Reported as #12, being investigated');
  assert.equal(LB.reportText({ number: 12, verified: true }), 'Fixed, verified (#12)');
  assert.equal(MG.reportText({ number: 7 }), 'Reported as #7, being investigated');
  assert.equal(MG.reportText({ number: 7, verified: true }), 'Fixed, verified (#7)');
});

test('launch bar: a failed launch asks again until its report is filed, then shows "Reported as #N"; a click opens it', async () => {
  let answers = 0;
  const b = bar(async () => { answers++; return answers < 3 ? { id: 'L1', tool: 'launch_game', state: 'failed', error: ERR }
    : { id: 'L1', tool: 'launch_game', state: 'failed', error: ERR, launch_report: REPORT }; });
  b.api.remote([launch()]); b.api.remote([]); await tick();
  assert.match(b.api.el.className, /err/);
  const rep = b.part('lb-rep');
  assert.equal(rep.textContent, ''); assert.doesNotMatch(rep.className, /\bon\b/);
  const follow = b.timers.filter(t => [2500, 6000, 15000].includes(t.ms));
  assert.equal(follow.length, 3, 'three follow-up reads of the failed job');
  await follow[0].fn(); await tick();
  assert.equal(rep.textContent, '', 'not filed yet');
  await follow[1].fn(); await tick();
  assert.equal(rep.textContent, 'Reported as #12, being investigated');
  assert.match(rep.className, /lb-rep on/); assert.doesNotMatch(rep.className, /ok/);
  assert.match(b.api.el.title, /Reported as #12, being investigated/);
  assert.equal(b.part('lb-static').textContent, ERR, 'the reason stays');
  const asked = answers; await follow[2].fn(); assert.equal(answers, asked, 'no more reads once the report is known');
  rep.fire('click');
  assert.equal(b.reports.length, 1); assert.equal(b.reports[0].r.number, 12); assert.equal(b.reports[0].job.id, 'L1');
  assert.equal(b.details.length, 0, 'the badge opens the request, not the job details');
});

test('launch bar: a report already on the failed job shows at once; a verified one is green', async () => {
  const b = bar(async () => ({ id: 'L1', tool: 'launch_game', state: 'failed', error: ERR,
                               launch_report: { ...REPORT, verified: true, state: 'verified', status: 'done' } }));
  b.api.remote([launch()]); b.api.remote([]); await tick();
  const rep = b.part('lb-rep');
  assert.equal(rep.textContent, 'Fixed, verified (#12)'); assert.match(rep.className, /on/); assert.match(rep.className, /ok/);
  assert.equal(b.timers.filter(t => [2500, 6000, 15000].includes(t.ms)).length, 0, 'nothing to follow');
});

test('launch bar model: refresh() only updates the failure on show', () => {
  const m = LB.createModel({});
  m.observe(launch({ state: 'failed', error: ERR }));
  assert.equal(m.view().report, null);
  assert.equal(m.refresh({ id: 'other', launch_report: REPORT }), false);
  assert.equal(m.refresh({ id: 'L1', launch_report: REPORT }), true);
  assert.equal(m.view().report.number, 12); assert.equal(m.view().reason, ERR);
});

const CARD = {
  key: '1de2e7634f3161ff/doa2_roster_59d8ed0e', name: 'doa2_roster_59d8ed0e', game_id: '1de2e7634f3161ff', title: 'Dead or Alive 2',
  mod_title: 'DOA2 roster', writer: 'doa2_swap', built: 1000, size: 10, own_size: 10, verified: false, changes: [], images: [],
  donor_previews: [], shots: [], card_id: 'c1', state_slot: null,
  tickets: [{ number: 5, id: 'r5', title: 'Put Ayane in DOA2' }, { number: 12, id: 'r12', title: 'Launch failed: …' }],
  last_launch: { state: 'failed', error: 'retroarch started but content not running after 30s', ts: 900, job_id: 'L1' },
  launch_report: REPORT,
};

test('Mods page card: the failed build shows "Reported as #12, being investigated", linked to the request', () => {
  const html = MG.cardHTML(CARD, { now: 1000 });
  assert.match(html, /class="mg-lfr"/);
  assert.match(html, /data-mg="request" data-n="12"[^>]*>⚠ Reported as #12, being investigated</s);
  assert.match(html, /mg-lf-bad/);
  assert.match(html, /Open request #5/, 'other tickets keep their buttons');
  assert.doesNotMatch(html, />Open request #12/, 'the report is not listed twice');
  assert.match(html, /last launch failed: retroarch started but content not running after 30s/);
  const fixed = MG.cardHTML({ ...CARD, launch_report: { ...REPORT, verified: true } }, { now: 1000 });
  assert.match(fixed, /✓ Fixed, verified \(#12\)/); assert.match(fixed, /mg-lf-ok/);
  assert.doesNotMatch(MG.cardHTML({ ...CARD, launch_report: null }), /mg-lfr/);
});

test('both clients wire the badge: desktop opens the request from the bar, web shows it in the Library and launch screen', () => {
  const desk = fs.readFileSync(path.join(__dirname, '../clients/desktop/index.html'), 'utf8');
  assert.match(desk, /onReport: r => modsGalleryRequest\(\{ id: r\.request_id, number: r\.number \}\)/);
  assert.match(desk, /function launchError\(j\) \{ const err = new Error\(j\.error \|\| "launch failed"\); err\.jobId = j\.id; return err; \}/);
  assert.ok(!/throw new Error\(j\.error \|\| "launch failed"\)/.test(desk), 'every failed launch keeps its job id');
  const web = fs.readFileSync(path.join(__dirname, '../clients/web/index.html'), 'utf8');
  assert.match(web, /function launchReportText\(r\)/);
  assert.match(web, /\$\{launchReportBadge\(g\)\}<\/div>/);
  assert.match(web, /launchReportFollow\(j, r => \{ if \(LAST_LAUNCH === launch && !LOADING\) loader\.report\(r\); \}\)/);
});
