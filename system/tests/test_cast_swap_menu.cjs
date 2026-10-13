// "Replace entire cast with..." (clients/web/viz/cast-swap.js): the source picker, the editable plan rows, the edits the
// build sends, the controller's plan -> build -> report flow, and the menu entries in both clients.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const CS = require('../clients/web/viz/cast-swap.js');

const SOURCES = [{ key: 'wrestlers', label: 'Wrestlers (No Mercy, WCW, SmackDown! 2, Def Jam)', kind: 'group', count: 6 },
                 { key: '4187aeab4d67638c', label: 'Jet Grind Radio (USA)', kind: 'game', count: 16 },
                 { key: 'x', label: '<b>evil</b>', kind: 'game', count: 1 }];
const PLAN = {
  status: 'planned', message: '2 slots of PSO get Wrestlers donors', how: 'PSO Ver.2: every enemy pack in one GD-ROM',
  donors: [{ slug: 'djv_ps2_dmx', name: 'DMX', preview_url: '/api/characters/djv_ps2_dmx/preview' },
           { slug: 'sd2_kane', name: 'Kane', preview_url: '/api/characters/sd2_kane/preview' },
           { slug: 'jgr_char06', name: 'Gum', stale: true, preview_url: '/api/characters/jgr_char06/preview' }],
  assignments: [{ slot: 'enemy:booma', slot_name: 'Booma', character: 'djv_ps2_dmx', preview_url: '/api/characters/djv_ps2_dmx/preview', why: 'body size' },
                { slot: 'enemy:gigobooma', slot_name: 'Gigobooma', character: 'sd2_kane', preview_url: '/api/characters/sd2_kane/preview', why: 'body size' }],
  skipped: [{ slot: 'player', reason: 'not_working' }], refused: [{ slug: 'djv_ps2_unmapped', name: 'Deebo', reason: 'no body roles' }],
  refreshed: [{ slug: 'jgr_char06', name: 'Gum', status: 'will be re-extracted (reader v1 -> v2)' }],
};

test('the source picker groups first, games after, labels escaped', () => {
  const html = CS.sourceOptions(SOURCES, 'wrestlers');
  assert.ok(html.indexOf('optgroup label="Groups"') < html.indexOf('optgroup label="Games"'));
  assert.match(html, /<option value="wrestlers" selected>Wrestlers \(No Mercy, WCW, SmackDown! 2, Def Jam\) \(6\)/);
  assert.ok(!html.includes('<b>evil</b>') && html.includes('&#60;b&#62;evil'));
  assert.match(CS.sourceOptions([]), /nothing in the collection/);
  const form = CS.formHTML('Phantasy Star Online', SOURCES);
  for (const k of ['source', 'mapping', 'slots', 'seed', 'status', 'plan']) assert.match(form, new RegExp(`data-cs="${k}"`));
  assert.match(form, /data-cs-go="build" type="button" disabled/);
  assert.match(form, /<option value="auto">/); assert.match(form, /<option value="enemies">Enemies only/);
});

test('plan rows: slot -> thumbnail + donor picker (selected donor, stale flagged), skipped / refused / re-extracted listed', () => {
  const html = CS.planHTML(PLAN, u => u + '?token=t');
  assert.match(html, /<tr data-row="enemy:booma"><td title="enemy:booma">Booma<\/td>/);
  assert.match(html, /src="\/api\/characters\/djv_ps2_dmx\/preview\?token=t"/);
  assert.match(html, /<select data-cs-slot="enemy:gigobooma"[^>]*>[\s\S]*<option value="sd2_kane" selected>Kane<\/option>/);
  assert.match(html, /Gum \(re-extract\)/);
  assert.match(html, /<option value="">\(leave as it is\)<\/option>/);
  assert.match(html, /Left as they are \(1\)[\s\S]*player: not_working/);
  assert.match(html, /Refused donors \(1\)[\s\S]*Deebo: no body roles/);
  assert.match(html, /Re-extracted before the build \(1\)[\s\S]*Gum: will be re-extracted/);
});

test('only the rows the operator changed are sent as edits', () => {
  assert.deepEqual(CS.edits(PLAN, { 'enemy:booma': 'djv_ps2_dmx', 'enemy:gigobooma': 'jgr_char06', 'enemy:other': 'x' }),
                   [{ slot: 'enemy:gigobooma', character: 'jgr_char06' }]);
  assert.deepEqual(CS.edits(PLAN, { 'enemy:booma': '' }), [{ slot: 'enemy:booma', character: '' }]);
  assert.deepEqual(CS.edits(PLAN, {}), []);
});

function fakeIo(answers) {
  const calls = [], parts = {}, statuses = [], enabled = {};
  return { calls, parts, statuses, enabled,
    io: { api: async (p, body) => { calls.push([p, body]); const a = answers(p, body, calls.length); if (a instanceof Error) throw a; return a; },
          render: (part, html) => { parts[part] = html; }, status: t => statuses.push(t), enable: (n, on) => { enabled[n] = on; },
          img: u => u, delay: async () => {} } };
}

test('controller: sources -> plan -> build one mod -> per-slot report', async () => {
  let polls = 0;
  const x = fakeIo((p, body) => {
    if (p.startsWith('/api/cast_swap/sources')) return { sources: SOURCES, slots: [{ slot: 'enemy:booma' }, { slot: 'enemy:gigobooma' }] };
    if (p === '/api/cast_swap/plan') return PLAN;
    if (p === '/api/jobs') return { id: 'j1', state: 'queued' };
    if (p === '/api/jobs/j1') return ++polls < 2 ? { id: 'j1', state: 'running', progress: { msg: 'Fitting DMX to Booma' } } :
      { id: 'j1', state: 'succeeded', output: { result: { status: 'partial', mod: 'cast_pso_x', message: '1/2 slots built into cast_pso_x',
        report: [{ slot: 'enemy:booma', slot_name: 'Booma', donor: 'DMX', status: 'built' },
                 { slot: 'enemy:gigobooma', slot_name: 'Gigobooma', donor: 'Gum', status: 'failed', reason: 'pack full' }] } } };
    throw new Error('unexpected ' + p);
  });
  const built = [];
  const c = CS.controller(Object.assign(x.io, { onBuilt: r => built.push(r.mod) }), { gid: 'daba7a3b195dcf6b', title: 'PSO' });
  await c.sources();
  assert.equal(x.calls[0][0], '/api/cast_swap/sources?game_id=daba7a3b195dcf6b');
  assert.match(x.parts.form, /Replace the entire cast of PSO/);
  await assert.rejects(c.build({}), /plan first/);
  await c.plan({ source: 'wrestlers', mapping: 'by_role', slots: 'enemies', seed: '7' });
  assert.deepEqual(x.calls[1], ['/api/cast_swap/plan', { game_id: 'daba7a3b195dcf6b', source: 'wrestlers', mapping: 'by_role',
                                                         seed: '7', slots: 'enemies', assignments: [] }]);
  assert.equal(x.enabled.build, true); assert.match(x.parts.plan, /data-cs-slot="enemy:booma"/);
  const res = await c.build({ 'enemy:booma': 'djv_ps2_dmx', 'enemy:gigobooma': 'jgr_char06' });
  const [jp, job] = x.calls[2];
  assert.equal(jp, '/api/jobs');
  assert.deepEqual(job, { tool: 'characters', require_os: 'linux', input: { op: 'cast_swap', target_game: 'daba7a3b195dcf6b',
    source: 'wrestlers', mapping: 'by_role', seed: '7', slots: 'enemies',
    assignments: [{ slot: 'enemy:gigobooma', character: 'jgr_char06' }], launch: false } });
  assert.equal(res.mod, 'cast_pso_x'); assert.deepEqual(built, ['cast_pso_x']);
  assert.ok(x.statuses.includes('Fitting DMX to Booma'));
  assert.match(x.parts.plan, /<b>partial<\/b> · mod <code>cast_pso_x<\/code>/);
  assert.match(x.parts.plan, /Gigobooma<\/td><td>Gum<\/td>[\s\S]*failed[\s\S]*pack full/);
  assert.match(x.statuses.at(-1), /^✓ 1\/2 slots built into cast_pso_x/);
});

test('controller: a failed job re-enables the build and says why; an empty plan keeps it disabled', async () => {
  const x = fakeIo(p => p === '/api/cast_swap/plan' ? { status: 'empty', message: 'nothing to build', assignments: [] }
    : p === '/api/jobs' ? { id: 'j', state: 'failed', error: 'collection offline' } : { sources: [] });
  const c = CS.controller(x.io, { gid: 'g', title: 'T' });
  await c.sources(); assert.match(x.statuses.at(-1), /Nothing in the collection/);
  await c.plan({ source: 's', mapping: 'auto' });
  assert.equal(x.enabled.build, false); assert.equal(x.statuses.at(-1), 'nothing to build');
  c.state.plan = PLAN; c.state.form = { source: 's', mapping: 'auto' };
  await c.build({}); assert.equal(x.statuses.at(-1), '✗ collection offline'); assert.equal(x.enabled.build, true);
});

const read = f => fs.readFileSync(path.join(__dirname, '..', 'clients', f), 'utf8');

test('the web game menu and the desktop game chip menu open the dialog', () => {
  const web = read('web/index.html'), desk = read('desktop/index.html');
  assert.match(web, /<script src="\/viz\/cast-swap.js"><\/script>/);
  assert.match(web, /<button class="act" data-cast type="button"[^>]*>Replace entire cast with…<\/button>/);
  assert.match(web, /closest\("\[data-cast\]"\)\) \{ el\.classList\.remove\("on"\); castSwapOpen\(gid, c\.dataset\.title\)/);
  assert.match(web, /function castSwapOpen\(gid, title\) \{\s*return GBoxCastSwap\.open\(document, \{ api,/);
  assert.match(desk, /<script src="\.\.\/web\/viz\/cast-swap.js"><\/script>/);
  assert.match(desk, /data-cast style="[^"]*">Replace entire cast with…<\/button>/);
  assert.match(desk, /else if \(b\.dataset\.cast !== undefined\) castSwapOpen\(chip\.dataset\.g, chip\.dataset\.t\)/);
  assert.match(desk, /async function castSwapOpen\(gid, title\)[\s\S]{0,400}GBoxCastSwap\.open\(document/);
});

test('the browser binding builds a role=dialog under body and wires plan / build / close', async () => {
  const el = { style: {}, attrs: {}, setAttribute(k, v) { this.attrs[k] = v; }, querySelector: () => null, querySelectorAll: () => [],
               remove() { this.removed = true; } };
  const doc = { getElementById: () => null, createElement: () => el, body: { append: e => { doc.appended = e; } } };
  const io = { api: async () => ({ sources: [] }) };
  const r = CS.open(doc, io, { gid: 'g', title: 'T' });
  assert.equal(doc.appended, el); assert.equal(el.id, 'castdlg'); assert.equal(el.attrs.role, 'dialog');
  assert.equal(typeof el.onclick, 'function'); assert.equal(typeof el.onchange, 'function'); assert.ok(r.controller);
  await el.onclick({ target: { closest: () => ({ dataset: { csGo: 'close' } }) } });
  assert.equal(el.removed, true);
});
