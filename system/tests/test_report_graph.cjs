// Detailed report (#1011): the request as a three.js bubble graph. The model turns a request, its resolution agent's tool
// calls, a Hermes run and its automated sub-requests into task / subtask / tool bubbles with order, branch and data edges;
// the layout rings the subtasks around the task in order with the tools outside; the focus card names the tool, input and
// result; the screenshot panel slides in and out. Pure parts run on plain data, the wiring is checked as text.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../clients/desktop/report-graph.js'), 'utf8');
const desktop = fs.readFileSync(path.join(__dirname, '../clients/desktop/index.html'), 'utf8');
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);

function load() {
  const ctx = { Math, JSON, Date, Object, Array, Number, String, Set, Map, encodeURIComponent, console };
  ctx.window = ctx; vm.createContext(ctx); vm.runInContext(source, ctx);
  return ctx.GBoxReportGraph;
}
const plain = x => JSON.parse(JSON.stringify(x));
const request = {
  id: 'r1', number: 1011, title: '3js detailed report', status: 'in_progress', body: 'A flowchart-driven report', image: 'a'.repeat(64), source: 'app',
  metrics: { tools: { launch_game: 1, get_frame: 2 } },
  messages: [
    { author: 'operator', text: 'please', ts: 1 },
    { author: 'agent', text: 'Saved the moment', ts: 2, task_step: { action: 'save game moment', attempt: '1', result: 'slot 3', status: 'succeeded' },
      attachments: [{ type: 'image/png', sha256: 'b'.repeat(64), name: 'moment.png' }] },
    { author: 'system', text: 'Dispatched', ts: 3, task_step: { action: 'dispatch resolution', attempt: '1', result: 'chat-9', status: 'running' } },
  ],
  context: { resolution_chat_id: 'chat-9' },
};
const resolution = { steps: [
  { action: 'get_frame', attempt: 1, input: { session_id: 's' }, result: '{"sha256": "..."}', status: 'finished' },
  { action: 'pytest', attempt: 1, input: { file: 'tests/test_x.py' }, result: 'FAILED tests/test_x.py::test_a', status: 'failed' },
  { action: 'get_frame', attempt: 2, input: { session_id: 's' }, result: 'Awaiting tool result', status: 'running' },
] };
const run = { id: 'h1', name: 'hermes/request-1011', steps: [{ action: 'git_push', attempt: 1, input: { branch: 'x' }, result: 'pushed', status: 'finished' }] };
const children = [{ id: 'c1', number: 1012, title: 'Auto report: child', status: 'done', body: 'child body', metrics: { tools: { git_push: 2, pytest: 1 } },
  messages: [{ author: 'agent', text: 'child verified' }] }];

test('the model dissects the request into subtasks in order and the tools they used, deduplicated with counts', () => {
  const G = load(), g = G.model(request, { resolution, run, children });
  const kinds = k => g.nodes.filter(n => n.kind === k);
  assert.equal(g.title, '#1011 3js detailed report'); assert.equal(g.status, 'in_progress');
  assert.equal(kinds('task').length, 1); assert.equal(kinds('step').length, 6); assert.equal(kinds('sub').length, 1);
  assert.deepEqual(plain(kinds('tool').map(t => t.label).sort()), ['get_frame', 'git_push', 'launch_game', 'pytest']);
  const steps = kinds('step');
  assert.deepEqual(plain(steps.map(s => s.label)), ['save game moment', 'dispatch resolution', 'get_frame', 'pytest', 'get_frame · try 2', 'git_push']);
  assert.deepEqual(plain(steps.map(s => s.status)), ['done', 'running', 'done', 'failed', 'running', 'done']);
  assert.deepEqual(plain(steps.map(s => s.n)), [0, 1, 2, 3, 4, 5]);
  assert.deepEqual(plain(steps[0].images), ['b'.repeat(64)]); assert.equal(steps[0].tool, null); assert.equal(steps[0].result, 'slot 3');
  assert.equal(steps[3].tool, 'pytest'); assert.deepEqual(plain(steps[3].input), { file: 'tests/test_x.py' }); assert.equal(steps[3].text, 'Resolution agent');
  assert.equal(steps[5].text, 'Hermes run hermes/request-1011');
  const tool = n => g.nodes.find(x => x.id === 'tool:' + n);
  assert.equal(tool('get_frame').count, 2, 'two tool calls, the ticket metrics do not double count it');
  assert.equal(tool('git_push').count, 3, 'one Hermes step plus the sub-request metrics');
  assert.equal(tool('launch_game').count, 1, 'metrics-only tools hang off the task');
  assert.deepEqual(plain(tool('pytest').uses.map(u => u.label)), ['pytest']);
  const order = g.edges.filter(e => e.kind === 'order').map(e => `${e.from}>${e.to}`);
  assert.deepEqual(plain(order), ['task>msg:1', 'msg:1>msg:2', 'msg:2>resolution:0', 'resolution:0>resolution:1', 'resolution:1>resolution:2', 'resolution:2>run:0']);
  assert.deepEqual(plain(g.edges.filter(e => e.kind === 'branch').map(e => e.to)), ['req:c1']);
  const data = g.edges.filter(e => e.kind === 'data').map(e => `${e.from}>${e.to}`);
  assert.deepEqual(plain(data), ['resolution:0>tool:get_frame', 'resolution:1>tool:pytest', 'resolution:2>tool:get_frame', 'run:0>tool:git_push', 'req:c1>tool:git_push', 'req:c1>tool:pytest', 'task>tool:launch_game']);
  const sub = kinds('sub')[0];
  assert.equal(sub.label, '#1012 Auto report: child'); assert.equal(sub.status, 'done'); assert.equal(sub.result, 'child verified'); assert.equal(sub.requestId, 'c1'); assert.equal(sub.n, 6);
  assert.equal(g.nodes.find(n => n.id === 'task').color, G.COLORS.task); assert.equal(steps[3].color, G.COLORS.failed);
  assert.equal(steps[4].color, G.COLORS.running); assert.equal(steps[0].color, G.COLORS.done); assert.equal(sub.color, G.COLORS.sub); assert.equal(tool('pytest').color, G.COLORS.tool);
  const bare = G.model({ id: 'x', number: 5, title: 'empty', status: 'open', messages: [], metrics: { tools: {} } });
  assert.deepEqual(plain(bare.nodes.map(n => n.id)), ['task']); assert.deepEqual(plain(bare.edges), []);
  assert.equal(bare.nodes[0].status, 'running', 'an open ticket is still being worked');
});

test('statuses collapse to done / failed / running / step', () => {
  const { statusOf } = load();
  for (const [word, want] of [['succeeded', 'done'], ['finished', 'done'], ['verified', 'done'], ['done', 'done'], ['failed', 'failed'], ['error: x', 'failed'], ['rejected', 'failed'],
                              ['running', 'running'], ['in_progress', 'running'], ['open', 'running'], ['Awaiting tool result', 'running'], ['', 'step'], ['noted', 'step']])
    assert.equal(statusOf(word), want, word);
});

test('the layout rings the subtasks around the task in order and the tools outside, near their subtasks', () => {
  const G = load(), g = G.model(request, { resolution, run, children }), pos = G.layout(g);
  assert.deepEqual(plain(pos.task), { x: 0, y: 0, z: 0, r: 1.25, a: 0 });
  const ring = g.nodes.filter(n => n.kind !== 'task' && n.kind !== 'tool').sort((a, b) => a.n - b.n);
  const dist = p => Math.hypot(p.x, p.z);
  for (const n of ring) assert.ok(Math.abs(dist(pos[n.id]) - 5.85) < 1e-9, n.id + ' sits on the subtask ring');
  const angles = ring.map(n => pos[n.id].a);
  for (let i = 1; i < angles.length; i++) assert.ok(angles[i] > angles[i - 1], 'in order around the ring');
  assert.ok(pos[ring[0].id].y > pos[ring.at(-1).id].y, 'the spiral descends with time');
  for (const t of g.nodes.filter(n => n.kind === 'tool')) {
    assert.ok(Math.abs(dist(pos[t.id]) - 10.35) < 1e-9, t.id + ' sits on the outer ring');
    assert.ok(Number.isFinite(pos[t.id].y));
  }
  const bigger = pos['tool:git_push'].r, smaller = pos['tool:launch_game'].r;
  assert.ok(bigger > smaller && bigger <= 0.95, 'a busier tool is a bigger bubble');
  assert.ok(pos['req:c1'].r > pos['msg:1'].r, 'a sub-request is a bigger bubble than a step');
  assert.ok(pos['resolution:1'].r > pos['msg:1'].r, 'a step that used a tool grows a little');
  const one = G.model({ id: 'y', number: 2, title: 'one', status: 'done', messages: [], metrics: { tools: { pytest: 4 } } }), p1 = G.layout(one);
  assert.ok(Math.abs(p1['tool:pytest'].a - 0) < 1e-9, 'a lone tool sits beside what used it (the task, angle 0)');
  for (const v of Object.values(p1)) for (const k of ['x', 'y', 'z', 'r']) assert.ok(Number.isFinite(v[k]));
});

test('the focus card names the kind, tool, input and result, escapes text and offers the screenshot', () => {
  const G = load(), g = G.model(request, { resolution, run, children });
  const step = g.nodes.find(n => n.id === 'resolution:1'), html = G.cardHtml(step, esc);
  assert.match(html, /<span class="rg-kind">Subtask<\/span>pytest<\/h4>/);
  assert.match(html, /status failed · try 1/); assert.match(html, /<b>Tool<\/b> pytest/);
  assert.match(html, /<b>Input<\/b><pre>\{\n &#34;file&#34;: &#34;tests\/test_x.py&#34;\n\}<\/pre>/); assert.match(html, /<b>Result<\/b><pre>FAILED tests\/test_x.py::test_a<\/pre>/);
  assert.match(html, /data-rg-back/); assert.ok(!html.includes('data-rg-shot'), 'no screenshot on this step');
  const first = G.cardHtml(g.nodes.find(n => n.id === 'msg:1'), esc);
  assert.match(first, /data-rg-shot="b{64}">Show its screenshot</); assert.match(first, /Saved the moment/);
  const tool = G.cardHtml(g.nodes.find(n => n.id === 'tool:get_frame'), esc);
  assert.match(tool, /<span class="rg-kind">Tool<\/span>get_frame/); assert.match(tool, /used 2 times/); assert.match(tool, /Called by get_frame, get_frame · try 2/);
  assert.ok(!tool.includes('<b>Tool</b>'), 'a tool bubble does not repeat itself');
  const sub = G.cardHtml(g.nodes.find(n => n.id === 'req:c1'), esc);
  assert.match(sub, /data-rg-open="c1">Open this sub-request</); assert.match(sub, /child verified/);
  const odd = G.cardHtml({ kind: 'step', label: '<b>x</b>', text: 'a & b', images: [], input: 'x'.repeat(700), result: '' }, esc);
  assert.ok(!odd.includes('<b>x</b>')); assert.match(odd, /&#60;b&#62;x/); assert.match(odd, /a &#38; b/);
  assert.match(odd, /x{599}…<\/pre>/, 'long input is cut');
  assert.equal(G.cardHtml(null, esc), '');
});

test('the screenshot panel slides in and out and the thumbnails follow the shown image', () => {
  const G = load(), nodes = {};
  const mk = id => { const n = { classes: new Set(), attrs: {}, textContent: '', hidden: false, dataset: {}, buttons: [] };
    n.classList = { toggle: (c, f) => { f ? n.classes.add(c) : n.classes.delete(c); } }; n.setAttribute = (k, v) => { n.attrs[k] = v; };
    n.querySelectorAll = () => n.buttons; nodes[id] = n; return n; };
  ['#rg-shot', '#rg-shot-tog', '#rg-shot-img', '#rg-shot-empty', '#rg-shot-thumbs'].forEach(mk);
  G.state.deps = { $: s => nodes[s] };
  assert.equal(G.slide(), true); assert.equal(nodes['#rg-shot'].classes.has('on'), true);
  assert.equal(nodes['#rg-shot-tog'].attrs['aria-pressed'], 'true'); assert.equal(nodes['#rg-shot-tog'].textContent, 'Screenshot ▸');
  assert.equal(G.slide(), false); assert.equal(nodes['#rg-shot'].classes.has('on'), false); assert.equal(nodes['#rg-shot-tog'].textContent, '◂ Screenshot');
  assert.equal(G.slide(true), true); assert.equal(G.slide(true), true);
  G.state.images = [{ sha: 'aa', label: 'one', url: 'u1' }, { sha: 'bb', label: 'two', url: 'u2' }];
  nodes['#rg-shot-thumbs'].buttons = G.state.images.map(i => { const b = mk('btn:' + i.sha); b.dataset.rgSha = i.sha; return b; });
  G.showImage('bb');
  assert.equal(nodes['#rg-shot-img'].src, 'u2'); assert.equal(nodes['#rg-shot-img'].hidden, false); assert.equal(nodes['#rg-shot-empty'].hidden, true);
  assert.equal(nodes['btn:bb'].attrs['aria-pressed'], 'true'); assert.equal(nodes['btn:aa'].attrs['aria-pressed'], 'false');
  G.showImage('zz'); assert.equal(nodes['#rg-shot-img'].src, 'u1', 'an unknown image falls back to the first');
  G.state.images = []; G.showImage(); assert.equal(nodes['#rg-shot-img'].hidden, true); assert.equal(nodes['#rg-shot-empty'].hidden, false);
});

test('the story view\'s Tool graph opens the graph for that request; screenshots still open the flat evidence; the game steps aside', () => {
  assert.match(desktop, /<script src="report-graph\.js"><\/script>/);
  // Detailed report now opens the resolution story (test_report_story.cjs); its "Tool graph" button opens this graph
  assert.match(desktop, /graph: rid => reportGraphOpen\(rid\)/);
  assert.match(desktop, /if \(e\.target\.closest\("img\.shot, img\.att-img"\)\) \{/);
  assert.match(desktop, /function reportGraphOpen\(id\) \{\r?\n\s*return GBoxReportGraph\.open\(id, \{ \$, esc, api: p => gbox\.api\(p\), token: \(\) => gbox\.token\(\), apiUrl: \(\) => S\.apiUrl, loadThree: flowLoadThree,/);
  assert.match(desktop, /evidence: \(rid, sha\) => evRequest\(rid, sha\), children: rid => inboxSolverRequests\.filter\(x => x\.parent_request_id === rid\)/);
  assert.match(desktop, /\|\| FLOW\.on \|\| !!\$\("#reportgraph\.on"\)/, 'the docked game hides behind the full-window report');
  assert.match(source, /id="rg-evidence"/); assert.match(source, /id="rg-shot-tog"/); assert.match(source, /e\.key === "Escape" && RG\.on/);
});
