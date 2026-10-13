const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const E = require('../clients/web/viz/retarget-editor.js');
const H = require('../clients/web/viz/retarget-handles.js');

const VIEW = { slug: 'amy', name: 'Amy Rose', rig_roles: { hip: 'pelvis', head: 'neck_01', chest: 'spine' },
  model_url: '/api/characters/amy/file/amy.glb', profile: null, game_wide: null,
  resolved: { head: 1.2, roles: { l_hand: 'hand_L' } } };

function fakeIo(routes = {}) {
  const parts = {}, statuses = [], calls = [];
  const io = {
    api: async (p, body) => {
      calls.push([p, body]);
      for (const [k, v] of Object.entries(routes)) if (p.startsWith(k)) return typeof v === 'function' ? v(p, body) : v;
      if (p.startsWith('/api/characters/amy/retarget_profile')) return body ? Object.assign({}, VIEW, { profile: body.profile }) : VIEW;
      if (p.startsWith('/api/retarget/reference')) return { reference: { slug: 'doa2_kasumi', name: 'Kasumi', roles: {} } };
      if (p.startsWith('/api/cast_swap/sources')) return { slots: [{ slot: 'fighter:KAS', name: 'Kasumi' }, { slot: 'fighter:RYU', name: 'Ryu' }] };
      if (p.startsWith('/api/catalog/')) return { title: 'Dead or Alive 2' };
      throw new Error('no route ' + p);
    },
    render: (part, html) => { parts[part] = html; }, status: t => statuses.push(t),
  };
  return { io, parts, statuses, calls };
}

test('load: the collection roles plus the saved overrides, the slot list, the stock reference and the title', async () => {
  const x = fakeIo();
  const c = E.controller(x.io, { slug: 'amy', gid: '0123456789abcdef', slot: 'fighter:KAS' });
  await c.load();
  assert.deepEqual(c.state.roles, { hip: 'pelvis', head: 'neck_01', chest: 'spine', l_hand: 'hand_L' });
  assert.equal(c.state.profile.head, 1.2); assert.equal(c.state.title, 'Dead or Alive 2');
  assert.equal(c.state.reference.slug, 'doa2_kasumi');
  assert.match(x.parts.header, /<select data-rt="slot"><option value="fighter:KAS" selected>Kasumi<\/option>/);
  assert.match(x.parts.globals, /data-rt-set="head"[^>]*value="1.2"/);
  assert.match(x.parts.roles, /data-rt-role="l_hand"[\s\S]*?<em class="rt-from">yours<\/em>/);
  assert.match(x.parts.roles, /data-rt-role="hip"[\s\S]*?<em class="rt-from">collection<\/em>/);
  assert.match(x.statuses.at(-1), /Drag the circles/);
  assert.equal(x.calls[0][0], '/api/characters/amy/retarget_profile?game_id=0123456789abcdef&slot=fighter%3AKAS');
});

test('what is what: arm a role, click its bone in the donor view; a bone keeps one role', async () => {
  const x = fakeIo();
  const c = E.controller(x.io, { slug: 'amy', gid: 'g', title: 'T', slot: 'player' });
  await c.load();
  c.setBones(['root', 'pelvis', 'spine', 'neck_01', 'head_01', 'hand_L', 'LeftForeArm']);
  assert.equal(c.state.guessed.l_fore, 'LeftForeArm');
  assert.equal(c.clickBone('head_01'), null);                       // nothing armed: just selects
  c.arm('head');
  assert.match(x.parts.roles, /rt-role armed[^"]*" data-rt-role="head"/);
  assert.equal(c.clickBone('head_01'), 'head');
  assert.equal(c.state.roles.head, 'head_01'); assert.equal(c.state.armed, null);
  c.arm('neck'); c.clickBone('neck_01');
  assert.equal(c.state.roles.neck, 'neck_01');
  c.setRoleBone('chest', 'pelvis');                                 // pelvis moves from the hip to the chest
  assert.equal(c.state.roles.hip, undefined); assert.equal(c.state.roles.chest, 'pelvis');
  assert.match(x.parts.roles, /rt-role miss" data-rt-role="hip"/);   // the hip is now missing (required)
  assert.equal(await c.save('slot'), null);                         // and the save refuses without it
  assert.match(x.statuses.at(-1), /hip must be assigned/);
  c.setRoleBone('hip', 'root');
  c.guess();
  assert.equal(c.state.roles.l_fore, 'LeftForeArm');
  const body = c.payload('slot');
  assert.deepEqual(body.profile.roles, { hip: 'root', chest: 'pelvis', head: 'head_01', neck: 'neck_01', l_hand: 'hand_L',
    l_fore: 'LeftForeArm' });
});

test('sliders and circles change the profile; save posts it for the slot or the whole game', async () => {
  const x = fakeIo();
  const c = E.controller(x.io, { slug: 'amy', gid: 'g', title: 'T', slot: 'fighter:KAS' });
  let changes = 0; x.io.onChange = () => changes++;
  await c.load();
  c.setValue('arm_length', '1.3'); c.setValue('adjust.l_fore.girth', '0.8'); c.setValue('adjust.head.offset.1', '0.05');
  assert.equal(c.state.profile.arm_length, 1.3); assert.equal(c.state.profile.adjust.l_fore.girth, 0.8);
  assert.deepEqual(c.state.profile.adjust.head.offset, [0, 0.05, 0]);
  const pos = H.standardSkeleton(1.7), hs = H.handles(pos, c.state.profile, 0);
  const h = hs.find(k => k.id === 'width:l_upper');
  c.dragTo(h, [pos.l_upper[0] * 1.5, pos.l_upper[1], 0], pos, 0);
  assert.ok(Math.abs(c.state.profile.torso_width - 1.5) < 1e-9);
  assert.ok(changes >= 4 && c.state.dirty);
  c.selectPart('l_fore');
  assert.match(x.parts.part, /data-rt-set="adjust.l_fore.girth"[^>]*value="0.8"/);
  c.resetPart('l_fore');
  assert.equal(c.state.profile.adjust.l_fore, undefined);
  await c.save('slot');
  const [p, body] = x.calls.at(-1);
  assert.equal(p, '/api/characters/amy/retarget_profile');
  assert.equal(body.slot, 'fighter:KAS'); assert.equal(body.profile.arm_length, 1.3);
  assert.deepEqual(body.profile.roles, { l_hand: 'hand_L' });
  assert.match(x.statuses.at(-1), /Saved/); assert.equal(c.state.dirty, false);
  await c.save('game');
  assert.equal(x.calls.at(-1)[1].slot, '');
  await c.reset('slot');
  assert.ok(x.calls.some(([q, b]) => b && b.reset === true && b.slot === 'fighter:KAS'));
});

test('switching the slot reloads that slot\'s profile', async () => {
  const x = fakeIo();
  const c = E.controller(x.io, { slug: 'amy', gid: 'g', title: 'T', slot: 'fighter:KAS' });
  await c.load(); await c.setSlot('fighter:RYU');
  assert.equal(c.state.slot, 'fighter:RYU');
  assert.ok(x.calls.some(([q]) => q.endsWith('slot=fighter%3ARYU')));
});

test('the frame has both views, the side panel and the save / reset / close controls', () => {
  const f = E.frameHTML();
  for (const s of ['data-rt-stage="donor"', 'data-rt-stage="target"', 'data-rt-part-slot="roles"', 'data-rt-part-slot="globals"',
    'data-rt-go="save"', 'data-rt-go="save-all"', 'data-rt-go="reset"', 'data-rt-go="close"', 'data-rt-go="guess"'])
    assert.ok(f.includes(s), s);
  assert.ok(f.includes('class="rt-side scroll"'));                  // dragAnywhere leaves the scrolling panel alone
});

const read = f => fs.readFileSync(path.join(__dirname, '..', 'clients', f), 'utf8');

test('the editor opens from the cast plan rows, the character cards and the pick-whip menu', () => {
  const web = read('web/index.html'), desk = read('desktop/index.html'), cast = read('web/viz/cast-swap.js');
  assert.match(cast, /data-cs-rt="\$\{ESC\(r\.slot\)\}"/);
  assert.match(cast, /io\.retarget\(o\); else if \(root\.GBoxRetargetEditor\) root\.GBoxRetargetEditor\.open\(doc, io, o\)/);
  for (const [html, pre] of [[web, '/viz/'], [desk, '../web/viz/']]) {
    assert.ok(html.indexOf(`<script src="${pre}retarget-handles.js"></script>`) >= 0);
    assert.ok(html.indexOf(`<script src="${pre}retarget-handles.js"></script>`) < html.indexOf(`<script src="${pre}retarget-editor.js"></script>`));
    assert.match(html, /GBoxRetargetEditor\.open\(document, \{ api, url: u =>[\s\S]{0,120}drag: dragAnywhere/);
    assert.match(html, /retarget: retargetOpen/);
  }
  assert.match(web, /<button class="act" data-rt title="Retarget editor[^"]*">✎ Retarget…<\/button>/);
  assert.match(web, /closest\("button\[data-rt\]"\)[\s\S]{0,160}retargetOpen\(\{ slug: c\.slug, name: c\.name, gid, slot: "player" \}\)/);
  assert.match(desk, /<button data-w="retarget"><span>✎<\/span>Adjust how \$\{esc\(card\.name\)\} is retargeted…<\/button>/);
  assert.match(desk, /bt\.dataset\.w === "retarget"[\s\S]{0,300}retargetOpen\(\{ slug: card\.slug/);
  for (const f of ['web/index.html', 'desktop/index.html']) {
    const raw = fs.readFileSync(path.join(__dirname, '..', 'clients', f));
    const crlf = raw.toString('latin1').split('\r\n').length - 1, lf = raw.toString('latin1').split('\n').length - 1;
    assert.equal(crlf, lf, `${f} keeps CRLF line endings`);
  }
});

test('the browser binding mounts a draggable role=dialog and closes', async () => {
  const made = [];
  const el = () => { const e = { style: {}, attrs: {}, children: [], dataset: {}, setAttribute(k, v) { this.attrs[k] = v; },
    querySelector: () => null, querySelectorAll: () => [], addEventListener(k, f) { (this.on ||= {})[k] = f; },
    append(c) { this.children.push(c); }, remove() { this.removed = true; } }; made.push(e); return e; };
  const doc = { getElementById: () => null, createElement: el, head: el(), body: el() };
  let dragged = null;
  const io = { api: fakeIo().io.api, drag: e => { dragged = e; }, loadModules: async () => { throw new Error('no webgl'); } };
  const r = E.open(doc, io, { slug: 'amy', gid: 'g', title: 'T', slot: 'player' });
  assert.equal(r.el.id, 'rtedit'); assert.equal(r.el.attrs.role, 'dialog'); assert.equal(dragged, r.el);
  assert.ok(doc.body.children.includes(r.el));
  r.dispose(); assert.equal(r.el.removed, true);
});
