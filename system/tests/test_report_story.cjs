// Detailed report: the request's resolution story as a looping three.js scene (clients/web/viz/report-story.js).
// Pure parts run here without WebGL: the reel formatting and landing logic, the story -> timeline builder (phases,
// ledger entries, capped folder/file/hunk tree), and the disclosure lifecycle (create on expand, dispose on collapse,
// one renderer at a time, survive a list re-render) with an injected scene factory. The desktop wiring is checked as text.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const factory = require('../clients/web/viz/report-story.js');
const desktop = fs.readFileSync(path.join(__dirname, '../clients/desktop/index.html'), 'utf8');
const source = fs.readFileSync(path.join(__dirname, '../clients/web/viz/report-story.js'), 'utf8');
const plain = x => JSON.parse(JSON.stringify(x));
const R = factory({ document: undefined, Math });
const DASH = R.DASH;

// ---------------------------------------------------------------- a story as the server returns it
function story(over = {}) {
  const hunk = (n, a, d) => ({ old: n, new: n, added: a, deleted: d, context: `def f${n}():` });
  return {
    request: { id: 'r1', number: 1500, title: 'Detailed report', status: 'done', created: 1000, completed: 2000 },
    triage: { at: 1010, by: 'Hermes', agent: 'zai/glm-5.3', tool: 'gBox inbox task mode', evidence: 'Hermes run', wait_s: 10 },
    identification: [
      { action: 'get_request', input: 'request_id=r1', result: '', status: 'finished', source: 'Hermes run', ts: null, duration_s: null },
      { action: 'get_frame', input: 'session_id=s1', result: 'sha256=abc', status: 'finished', source: 'gBox resolution agent', ts: 1020, duration_s: 2 },
      { action: 'pytest', input: 'file=tests/test_a.py', result: 'boom', status: 'failed', source: 'gBox resolution agent', ts: 1030, duration_s: 3 },
    ],
    identification_total: 3,
    runs: [],
    changes: [{ number: 77, state: 'merged', merged_sha: 'abcdef123456', url: 'https://github.com/teamcsharp/gBox/pull/77', source: 'local git',
      files: [
        { path: 'system/gbox/a.py', folder: 'system/gbox', added: 10, deleted: 2, hunks: [hunk(1, 5, 1), hunk(9, 5, 1)], hunks_total: 2 },
        { path: 'system/tests/test_a.py', folder: 'system/tests', added: 30, deleted: 0, hunks: [hunk(1, 30, 0)], hunks_total: 1 },
      ], added: 40, deleted: 2 }],
    stages: [
      { key: 'intake', label: 'Request filed', duration_s: 10, tokens_in: null, tokens_out: null, cost: null, detail: '#1500 from app' },
      { key: 'triage', label: 'Triage', duration_s: null, tokens_in: null, tokens_out: null, cost: null, detail: 'claimed by Hermes · zai/glm-5.3' },
      { key: 'identify', label: 'Identification', duration_s: 10, tokens_in: null, tokens_out: null, cost: null, detail: '3 tool calls and steps' },
      { key: 'work', label: 'Hermes run · glm-5.3', run_id: 'a', duration_s: 300, tokens_in: 120000, tokens_out: 3000,
        cost: { usd: 0.0251, kind: 'estimate', basis: 'price table' }, detail: 'Hermes final model ledger (exact)' },
      { key: 'work', label: 'gBox resolution agent · qwen', run_id: 'c', duration_s: 12, tokens_in: 900, tokens_out: 40,
        cost: { usd: 0, kind: 'estimate', basis: 'local' }, detail: 'request metrics' },
      { key: 'changes', label: 'PR #77 · merged', pr: 77, duration_s: 600, tokens_in: null, tokens_out: null, cost: null, files: 2, folders: 2, added: 40, deleted: 2, detail: 'local git' },
      { key: 'resolution', label: 'Resolved', duration_s: 1000, tokens_in: null, tokens_out: null, cost: null, detail: 'Verified in game.' },
    ],
    totals: { tokens_in: 120900, tokens_out: 3040, cost: { usd: 0.0251, kind: 'estimate' }, duration_s: 1000, elapsed: false, added: 40, deleted: 2, files: 2 },
    resolution: { status: 'done', final_message: 'Verified in game.', verified: true },
    missing: [],
    ...over,
  };
}

// ---------------------------------------------------------------- formatting and reels
test('numbers format for the reels; anything unrecorded is a dash, never a zero', () => {
  assert.equal(R.fmtTokens(null), DASH); assert.equal(R.fmtTokens(0), '0'); assert.equal(R.fmtTokens(950), '950');
  assert.equal(R.fmtTokens(1234), '1.23k'); assert.equal(R.fmtTokens(56789), '56.8k'); assert.equal(R.fmtTokens(120900), '121k');
  assert.equal(R.fmtTokens(1_234_567), '1.23M'); assert.equal(R.fmtTokens(12_345_678), '12.3M');
  assert.equal(R.fmtCost(null), DASH); assert.equal(R.fmtCost({ usd: null, kind: 'unknown' }), DASH);
  assert.equal(R.fmtCost({ usd: 0.0251, kind: 'estimate' }), '~$0.025');
  assert.equal(R.fmtCost({ usd: 0.004, kind: 'estimate' }), '~$0.0040', 'estimates carry a tilde');
  assert.equal(R.fmtCost({ usd: 1.5, kind: 'actual' }), '$1.50', 'a billed cost has none');
  assert.equal(R.fmtCost({ usd: 0, kind: 'estimate' }), '~$0.00');
  assert.equal(R.fmtTime(null), DASH); assert.equal(R.fmtTime(42), '42s'); assert.equal(R.fmtTime(252), '4m 12s');
  assert.equal(R.fmtTime(3 * 3600 + 5 * 60), '3h 05m'); assert.equal(R.fmtTime(2 * 86400 + 4 * 3600), '2d 4h');
  assert.equal(R.reelText('tokensIn', 1500), '1.50k'); assert.equal(R.reelText('time', 61), '1m 01s'); assert.equal(R.reelText('cost', null), DASH);
});

test('a reel spins its digits, lands them left to right on the real value, then pops once', () => {
  const target = '~$0.025';
  const spinning = R.reelFace(target, 100, { land: 900, stagger: 70, seed: 3 });
  assert.equal(spinning.landed, false); assert.equal(spinning.popping, false);
  assert.equal(spinning.text.length, target.length);
  assert.deepEqual(plain(spinning.chars.filter(c => !c.spinning).map(c => c.ch)), ['~', '$', '.'], 'symbols never spin');
  assert.ok(spinning.chars.filter(c => c.spinning).every(c => /^[0-9]$/.test(c.ch)));
  assert.deepEqual(plain(R.reelFace(target, 100, { seed: 3 })), plain(spinning), 'a frame is reproducible');
  const half = R.reelFace(target, 900 + 70 + 1, { seed: 3 });           // the first two digits have landed
  assert.equal(half.chars[2].ch, '0'); assert.equal(half.chars[2].spinning, false); assert.equal(half.chars[4].ch, '0'); assert.equal(half.chars[4].spinning, false);
  assert.equal(half.chars[5].spinning, true); assert.equal(half.landed, false);
  const end = 900 + 3 * 70;                                              // four digits: the last lands 3 staggers later
  const landed = R.reelFace(target, end, { seed: 3 });
  assert.equal(landed.text, target); assert.equal(landed.landed, true); assert.equal(landed.popping, true); assert.equal(landed.end, end);
  assert.equal(R.reelFace(target, end + 400, { seed: 3 }).popping, false, 'the pop ends');
  const missing = R.reelFace(DASH, 0);
  assert.equal(missing.text, DASH); assert.equal(missing.landed, true); assert.equal(missing.popping, false); assert.equal(missing.missing, true);
  const still = R.reelFace('121k', Infinity);
  assert.equal(still.text, '121k'); assert.equal(still.landed, true); assert.equal(still.popping, false, 'reduced motion: lands without a pop');
});

// ---------------------------------------------------------------- the timeline
test('the timeline plays the story in order: filed, triage, identification, each run, the code, resolution', () => {
  const tl = R.timeline(story());
  const keys = tl.phases.map(p => p.key + (p.part ? ':' + p.part : ''));
  assert.deepEqual(plain(keys), ['intake', 'triage', 'identify', 'work', 'work', 'changes:fly', 'changes:files', 'changes:hunks',
    'changes:break', 'changes:recompile', 'resolve', 'hold']);
  for (let i = 1; i < tl.phases.length; i++) assert.equal(tl.phases[i].t0, tl.phases[i - 1].t1, 'phases are contiguous');
  assert.equal(tl.length, tl.phases.at(-1).t1);
  assert.ok(tl.length > 15 && tl.length < 40, `one loop is ${tl.length}s`);
  assert.equal(tl.phases[1].sub, 'claimed by Hermes · zai/glm-5.3');
  assert.equal(tl.phases[2].sub, '3 tool calls and steps');
  // one ledger entry per story stage, landing as its phase starts, with the stage's own numbers
  assert.deepEqual(plain(tl.entries.map(e => e.key)), ['intake', 'triage', 'identify', 'work', 'work', 'changes', 'resolve']);
  for (const e of tl.entries) assert.ok(tl.phases.some(p => p.key === e.key && e.at >= p.t0 && e.at < p.t1));
  const hermes = tl.entries[3].metrics;
  assert.deepEqual(plain(hermes), { cost: { usd: 0.0251, kind: 'estimate', basis: 'price table' }, tokensIn: 120000, tokensOut: 3000, time: 300 });
  assert.deepEqual(plain(tl.entries[0].metrics), { cost: null, tokensIn: null, tokensOut: null, time: 10 }, 'unrecorded stays null');
  assert.equal(tl.entries[5].label, 'PR #77 · merged'); assert.equal(tl.entries[5].detail, '2 files in 2 folders · +40 −2');
  assert.equal(tl.entries[5].metrics.time, 600);
  assert.equal(tl.entries[6].label, 'Resolved (filed → done)');
  assert.deepEqual(plain({ ...tl.totals, at: 0 }), { cost: { usd: 0.0251, kind: 'estimate' }, tokensIn: 120900, tokensOut: 3040, time: 1000, elapsed: false, at: 0 });
  const resolve = tl.phases.find(p => p.key === 'resolve');
  assert.ok(tl.totals.at > resolve.t0 && tl.totals.at < resolve.t1, 'the totals land during the resolution');
  assert.deepEqual(plain(tl.merged), { label: 'PR #77 · merged', sha: 'abcdef123456', url: 'https://github.com/teamcsharp/gBox/pull/77', state: 'merged' });
  assert.equal(tl.done, true);
  // the code tree: folders with their files and changed functions
  assert.deepEqual(plain(tl.folders.map(f => [f.path, f.name, f.count, f.added, f.deleted])), [['system/tests', 'system/tests', 1, 30, 0], ['system/gbox', 'system/gbox', 1, 10, 2]],
    'folders with the most changed lines first');
  assert.deepEqual(plain(tl.folders[1].files[0].hunks.map(h => h.label)), ['def f1():', 'def f9():']);
  assert.equal(tl.fileCount, 2); assert.equal(tl.moreFolders, 0);
  // phaseAt maps loop time (wrapping) to the phase and its progress
  const tri = tl.phases[1], mid = (tri.t0 + tri.t1) / 2;
  assert.equal(R.phaseAt(tl, mid).phase.key, 'triage'); assert.ok(Math.abs(R.phaseAt(tl, mid).p - 0.5) < 1e-9);
  assert.equal(R.phaseAt(tl, mid + tl.length).phase.key, 'triage', 'it loops');
  assert.equal(R.phaseAt(tl, 0).index, 0);
  assert.deepEqual(plain(R.span(tl, 'changes')), [tl.phases[5].t0, tl.phases[9].t1]);
  const still = R.stillTime(tl), at = R.phaseAt(tl, still);
  assert.equal(at.phase.part, 'hunks', 'reduced motion shows the files opened into their functions');
});

test('a story with no runs, no code and an open status still plays, and says so', () => {
  const tl = R.timeline(story({ stages: [{ key: 'intake', duration_s: null }, { key: 'triage', detail: 'not claimed yet' }, { key: 'identify' },
    { key: 'resolution', detail: '' }], changes: [], identification: [], identification_total: 0, request: { id: 'r2', number: 2, title: 'Idea', status: 'open' },
    totals: { tokens_in: 0, tokens_out: 0, cost: { usd: null, kind: 'unknown' }, duration_s: 50, elapsed: true }, missing: ['No code change'] }));
  assert.deepEqual(plain(tl.phases.map(p => p.key + (p.part ? ':' + p.part : ''))), ['intake', 'triage', 'identify', 'work', 'changes:none', 'resolve', 'hold']);
  assert.equal(tl.phases[3].sub, 'no agent run recorded'); assert.equal(tl.phases[4].sub, 'no linked code change');
  assert.equal(tl.phases[2].sub, 'no tool calls recorded');
  assert.equal(tl.entries.at(-1).label, 'Open so far'); assert.equal(tl.phases.at(-2).label, 'Status: open');
  assert.equal(tl.totals.elapsed, true); assert.equal(tl.merged, null); assert.equal(tl.folders.length, 0); assert.equal(tl.done, false);
  assert.deepEqual(plain(R.timeline(null).phases.map(p => p.key)), ['intake', 'triage', 'identify', 'work', 'changes', 'resolve', 'hold'], 'even an empty story');
  const html = R.summaryHtml(story({ missing: ['PR #9: files <unavailable>'] }));
  assert.match(html, /<th>Total<\/th><td>~\$0\.025 · 121k in · 3\.04k out · 16m 40s<\/td>/);
  assert.match(html, /Not recorded: PR #9: files &#60;unavailable&#62;/, 'escaped');
});

test('the code tree is capped: 8 folders, 24 files (5 a folder), 4 hunks a file; a path in two PRs is merged', () => {
  const files = [];
  for (let d = 0; d < 11; d++) for (let f = 0; f < 7; f++)
    files.push({ path: `system/d${d}/f${f}.py`, folder: `system/d${d}`, added: 1 + d, deleted: 0, hunks: Array.from({ length: 6 }, (_, h) => ({ new: h, added: 1, deleted: 0, context: '' })), hunks_total: 9 });
  const tree = R.foldersOf([{ files }, { files: [{ path: 'system/d10/f0.py', folder: 'system/d10', added: 5, deleted: 1, hunks: [] }] }]);
  assert.equal(tree.folders.length, 8); assert.equal(tree.moreFolders, 3); assert.equal(tree.fileCount, 77);
  assert.equal(tree.folders[0].path, 'system/d10', 'most changed first');
  assert.equal(tree.folders[0].files.find(f => f.path === 'system/d10/f0.py').added, 16, 'the second PR adds to the same file');
  assert.equal(tree.folders.reduce((n, f) => n + f.files.length, 0), 24);
  assert.ok(tree.folders.every(f => f.files.length <= 5));
  assert.ok(tree.folders.flatMap(f => f.files).every(f => f.hunks.length <= 4));
  assert.equal(tree.folders[0].files[0].moreHunks, 5, '9 hunks in the diff, 4 shown');
  assert.equal(tree.folders[0].files[0].hunks[0].label, '@@ 0', 'a hunk without a function context shows its line');
  const unknown = R.foldersOf([{ files: [{ path: 'a/b.js', added: null, deleted: null }, { path: 'a/c.js', added: 2, deleted: 1 }] }]);
  assert.equal(unknown.folders[0].added, null, 'a folder sum with an unknown file is unknown');
  const steps = R.timeline(story({ identification: Array.from({ length: 30 }, (_, i) => ({ action: 's' + i })), identification_total: 30 }));
  assert.equal(steps.steps.length, R.LIMITS.steps); assert.equal(steps.moreSteps, 20);
});

// ---------------------------------------------------------------- the disclosure lifecycle
function fakeDom() {
  const el = tag => ({
    tag, children: [], parentNode: null, className: '', innerHTML: '', open: false, dataset: {}, classList: { add() {}, remove() {}, contains: () => false },
    append(...cs) { for (const c of cs) { if (c.parentNode) c.remove(); c.parentNode = this; this.children.push(c); } },
    remove() { const p = this.parentNode; if (p) { p.children = p.children.filter(x => x !== this); this.parentNode = null; } },
    closest(sel) { for (let n = this; n; n = n.parentNode) if (sel === 'details' && n.tag === 'details') return n; return null; },
    querySelector(sel) { return sel === '.rs-slot' ? this.children.find(c => c.className === 'rs-slot') || null : null; },
    querySelectorAll(sel) { const out = []; const walk = n => { for (const c of n.children) { if (sel === 'details.rs-disclosure' && c.tag === 'details') out.push(c); walk(c); } }; walk(this); return out; },
  });
  const document = { createElement: el, getElementById: () => null, head: el('head'), body: el('body'), querySelector: () => null };
  const row = id => { const d = el('details'); d.dataset.story = id; d.open = true; const slot = el('div'); slot.className = 'rs-slot'; d.append(slot); return { details: d, slot }; };
  return { document, el, row };
}
function harness() {
  const dom = fakeDom(), S = factory({ document: dom.document, Math });
  const made = [];
  const deps = {
    api: async p => ({ ok: true, data: story({ request: { id: p.split('/')[3], number: 1, title: 't', status: 'done' } }) }),
    createScene: (panel, st, opts) => { const sc = { panel, story: st, opts, disposed: 0, kicks: 0, dispose() { this.disposed++; }, kick() { this.kicks++; } }; made.push(sc); return sc; },
  };
  return { dom, S, made, deps };
}

test('expanding a row creates its scene once, in an inline panel; collapsing disposes it', async () => {
  const { dom, S, made, deps } = harness();
  const a = dom.row('a');
  const scene = await S.expand('a', a.slot, deps);
  assert.equal(made.length, 1); assert.equal(scene, made[0]);
  assert.equal(made[0].story.request.id, 'a', 'the scene gets that request’s story');
  assert.equal(a.slot.children.length, 1); assert.equal(a.slot.children[0].className, 'rs-panel', 'inline, not a modal');
  assert.equal(made[0].panel, a.slot.children[0]); assert.equal(made[0].opts.full, false);
  assert.equal(S.state.id, 'a');
  assert.equal(S.collapse('b'), false, 'another row closing does not touch it');
  assert.equal(made[0].disposed, 0);
  assert.equal(S.collapse('a'), true);
  assert.equal(made[0].disposed, 1); assert.equal(a.slot.children.length, 0, 'the panel is removed'); assert.equal(S.state.id, null);
  assert.equal(S.collapse('a'), false, 'nothing left to dispose');
  await S.expand('a', a.slot, deps);
  assert.equal(made.length, 2, 'expanding again builds a fresh scene (the story itself is cached)');
});

test('one renderer at a time: opening another row disposes the first and closes its triangle', async () => {
  const { dom, S, made, deps } = harness();
  const a = dom.row('a'), b = dom.row('b');
  await S.expand('a', a.slot, deps);
  await S.expand('b', b.slot, deps);
  assert.equal(made.length, 2); assert.equal(made[0].disposed, 1); assert.equal(made[1].disposed, 0);
  assert.equal(a.details.open, false, 'the first disclosure closes'); assert.equal(a.slot.children.length, 0);
  assert.equal(S.collapse('a'), false, 'its toggle(closed) then finds nothing to collapse');
  assert.equal(made[1].disposed, 0);
});

test('a list re-render moves the live panel into the new row instead of rebuilding it', async () => {
  const { dom, S, made, deps } = harness();
  const a = dom.row('a');
  await S.expand('a', a.slot, deps);
  const panel = a.slot.children[0];
  const host = dom.el('div'), again = dom.row('a'); host.append(again.details);   // the inbox replaced its HTML; the row is open again
  assert.equal(S.reattach(host), true);
  assert.equal(again.slot.children[0], panel); assert.equal(made.length, 1); assert.equal(made[0].kicks, 1);
  await S.expand('a', again.slot, deps);                                           // ...and its toggle(open) arrives
  assert.equal(made.length, 1, 'no second scene'); assert.equal(made[0].disposed, 0);
  const closed = dom.row('a'); closed.details.open = false; const host2 = dom.el('div'); host2.append(closed.details);
  assert.equal(S.reattach(host2), false, 'a closed row does not take the panel');
});

test('collapsing while the story loads never builds the scene', async () => {
  const { dom, S, made, deps } = harness();
  let release;
  deps.api = () => new Promise(r => { release = () => r({ ok: true, data: story() }); });
  const a = dom.row('a');
  const pending = S.expand('a', a.slot, deps);
  assert.equal(a.slot.children[0].innerHTML.includes('Loading'), true);
  assert.equal(S.collapse('a'), true);
  release();
  assert.equal(await pending, null); assert.equal(made.length, 0);
});

test('a failed load says why in the panel; three.js missing shows the numbers instead', async () => {
  const { dom, S, made, deps } = harness();
  const a = dom.row('a');
  assert.equal(await S.expand('a', a.slot, { ...deps, api: async () => ({ ok: false, error: 'not found' }) }), null);
  assert.match(a.slot.children[0].innerHTML, /not found/);
  const b = dom.row('b');
  assert.equal(await S.expand('b', b.slot, { ...deps, createScene: undefined }), null);
  assert.match(b.slot.children[0].innerHTML, /three\.js is not available/); assert.match(b.slot.children[0].innerHTML, /rs-sum/);
  assert.equal(made.length, 0);
});

// ---------------------------------------------------------------- the desktop wiring
test('each request row has the disclosure; Detailed report opens the same view full size', () => {
  assert.match(desktop, /<script src="report-graph\.js"><\/script>\r?\n<script src="\.\.\/web\/viz\/report-story\.js"><\/script>/);
  assert.match(desktop, /out\$\{tools \? " · tools: " \+ esc\(tools\) : ""\}<\/div>\r?\n\s*\$\{GBoxReportStory\.disclosureHtml\(x\.id\)\}\r?\n\s*<div class="thread">/,
    'outside the collapsed thread, so every row shows the triangle');
  assert.match(desktop, /GBoxReportStory\.bind\(\$\("#reqlist"\), \(\) => reportStoryDeps\(\)\);/);
  assert.match(desktop, /replyAtt\);\r?\n\s*GBoxReportStory\.reattach\(host\);/);
  assert.match(desktop, /if \(e\.target\.closest\("\[data-report-detail\]"\)\) \{ e\.stopPropagation\(\); reportStoryOpen\(id\); return; \}/);
  assert.match(desktop, /function reportStoryOpen\(id\) \{ return GBoxReportStory\.openFull\(id, reportStoryDeps\(\)\); \}/);
  assert.match(desktop, /loadThree: flowLoadThree, evidence: rid => evRequest\(rid\), graph: rid => reportGraphOpen\(rid\)/);
  assert.match(desktop, /\|\| !!\$\("#reportgraph\.on"\) \|\| GBoxReportStory\.isFullOpen\(\)/, 'the docked game steps aside for the full view');
  assert.equal(R.disclosureHtml('a"b'), '<details class="rs-disclosure" data-story="a&#34;b"><summary>Detailed report</summary><div class="rs-slot"></div></details>');
});

test('the scene is cheap and polite: lazy three.js, capped particles, off-screen pause, reduced motion, full disposal', () => {
  assert.match(source, /prefers-reduced-motion: reduce/);
  assert.match(source, /new env\.IntersectionObserver\(/);
  assert.match(source, /doc\.addEventListener\("visibilitychange", onVis\)/);
  assert.match(source, /renderer\.dispose\(\); renderer\.forceContextLoss\?\.\(\);/);
  assert.match(source, /for \(const d of disposables\) d\.dispose\?\.\(\);/);
  assert.match(source, /io\?\.disconnect\(\)/);
  assert.match(source, /Math\.min\(opts\.particles \|\| LIMITS\.particles, still \? LIMITS\.particlesReduced : LIMITS\.particles\)/);
  assert.match(source, /await \(deps\.loadThree \? deps\.loadThree\(\) : null\);/, 'three.js loads only when a disclosure opens');
  assert.match(source, /if \(!container\.isConnected\) \{/, 'a panel the list dropped disposes itself');
  assert.ok(R.LIMITS.particles <= 400 && R.LIMITS.files <= 30 && R.LIMITS.folders <= 8);
});
