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

test('texture review blocks rebuilding until decided and carries draft proportions into an approved donor',async()=>{
  const x=fakeIo(),c=E.controller(x.io,{slug:'amy',gid:'g',title:'T',slot:'player',draftProfile:{head:.75,plant_feet:true}});
  await c.load();assert.equal(c.state.profile.head,.75);assert.equal(c.state.profile.plant_feet,true);
  c.state.texturePending=true;
  await assert.rejects(c.saveAndRebuild(),/Accept or reject/);
  assert.ok(!x.calls.some(([p])=>p.includes('special_builds/rebuild')));
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

// ---- the Goals view (the Fitting pop-up's R buttons open it) ------------------------------------------------------
const GOALS = { game_id: 'g', slot: 'fighter:KAS', goals: { target: { hip: [0, 0.9, 0], head: [0, 1.6, 0], l_fore: [0.45, 1.4, 0] },
  donor: { hip: [0, 1, 0] }, target_ground: 0 } };

test('the Goals view is the default: tabs, a numbered legend, the slot\'s own skeleton from the last build', async () => {
  const x = fakeIo({ '/api/retarget/goals': GOALS });
  const c = E.controller(x.io, { slug: 'amy', gid: 'g', title: 'T', slot: 'fighter:KAS', view: 'goals' });
  await c.load();
  assert.equal(c.state.mode, 'goals'); assert.equal(c.state.goals.target.l_fore[0], 0.45);
  assert.ok(x.calls.some(([p]) => p === '/api/retarget/goals?game_id=g&slot=fighter%3AKAS'));
  assert.match(x.parts.tabs, /class="act pri" data-rt-mode="goals"/);
  assert.match(x.parts.tabs, /data-rt-tpose checked/);
  assert.match(x.parts.legend, /data-rt-joint-pick="l_fore">[\s\S]*?<i style="background:#4f8cff">7<\/i><span>Left elbow<\/span>/);
  assert.match(x.parts.legend, /data-rt-joint-pick="r_fore">[\s\S]*?not in the slot/);     // the slot's skeleton has no such joint
  assert.match(x.parts.legend, /data-rt-joint-pick="hip">[\s\S]*?<em>pelvis<\/em>/);
  assert.match(x.parts.joint, /Click a circle/);
  assert.match(x.statuses.at(-1), /Drag the circles on the donor/);
  c.setMode('fit');
  assert.equal(c.state.mode, 'fit'); assert.match(x.parts.tabs, /class="act pri" data-rt-mode="fit"/);
  c.setTpose(false); assert.match(x.parts.tabs, /data-rt-tpose>/);
  const old = E.controller(fakeIo().io, { slug: 'amy', gid: 'g', slot: 'player', view: 'fit' });
  assert.equal(old.state.mode, 'fit');
});

test('a circle: click picks its donor bone from a list, drag moves its joint; both save with the profile', async () => {
  const x = fakeIo();
  const c = E.controller(x.io, { slug: 'amy', gid: 'g', title: 'T', slot: 'fighter:KAS' });
  await c.load();
  c.setBones(['pelvis', 'spine', 'neck_01', 'upperarm_l', 'lowerarm_l', 'hand_L']);
  c.selectJoint('l_fore');                                            // clicked
  assert.match(x.parts.joint, /data-rt-joint="l_fore"><b><i style="background:#4f8cff"><\/i>7 Left elbow<\/b>/);
  assert.match(x.parts.joint, /<select data-rt-bone="l_fore"><option value="">\(none\)<\/option>[\s\S]*<option value="lowerarm_l">/);
  assert.match(x.parts.legend, /rt-goal sel[^"]*" data-rt-joint-pick="l_fore"/);
  c.setRoleBone('l_fore', 'lowerarm_l');                              // picked from the list
  assert.equal(c.state.roles.l_fore, 'lowerarm_l');
  assert.match(x.parts.joint, /<option value="lowerarm_l" selected>/);
  const pos = H.standardSkeleton(1.7), g = H.goalCircles(pos, { ground: 0 }).find(k => k.role === 'l_fore');
  c.dragJoint(g, g.at, [g.at[0], g.at[1] - 0.034, 0], 1.7, [0, 0, 0]);     // the elbow was guessed too high
  assert.deepEqual(c.state.profile.joints.l_fore, [0, -0.02, 0]); assert.ok(c.state.dirty);
  c.settle();
  assert.match(x.parts.joint, /data-rt-set="joints.l_fore.1"[^>]*value="-0.02"/);
  assert.match(x.parts.legend, /lowerarm_l · moved/);
  c.setValue('joints.l_fore.0', '0.01');
  assert.deepEqual(c.state.profile.joints.l_fore, [0.01, -0.02, 0]);
  const body = c.payload('slot');
  assert.deepEqual(body.profile.joints, { l_fore: [0.01, -0.02, 0] }); assert.equal(body.profile.roles.l_fore, 'lowerarm_l');
  c.resetJoint('l_fore'); assert.deepEqual(c.state.profile.joints, {});
});

test('save and rebuild: the pop-up job\'s own call narrowed to this slot, queued through the special-builds rebuild', async () => {
  const x = fakeIo({ '/api/games/g/special_builds/rebuild': (p, b) => ({ queued: 1, job_ids: ['j9'], jobs: [{ job_id: 'j9' }], skipped: [] }) });
  let handed = null; x.io.onRebuild = (r, st) => { handed = [r, st.slot]; };
  const job = { op: 'cast_swap', target_game: 'Dead or Alive 2', source: 'SA2', mapping: 'by_role', seed: 's1', slots: 'all',
    assignments: [{ slot: 'fighter:KAS', character: 'amy' }, { slot: 'fighter:RYU', character: 'sonic' }], launch: true };
  const c = E.controller(x.io, { slug: 'amy', gid: 'g', title: 'T', slot: 'fighter:KAS', recipe: { tool: 'characters', input: job } });
  await c.load();
  const r = await c.saveAndRebuild();
  const [p, body] = x.calls.at(-1);
  assert.equal(p, '/api/games/g/special_builds/rebuild');
  assert.deepEqual(body, { recipes: [{ tool: 'characters', input: { op: 'cast_swap', target_game: 'g', source: 'SA2', mapping: 'by_role',
    seed: 's1', slots: 'fighter:KAS', assignments: [{ slot: 'fighter:KAS', character: 'amy' }], launch: false, rebuild: true } }] });
  assert.ok(x.calls.some(([q, b]) => q === '/api/characters/amy/retarget_profile' && b && b.slot === 'fighter:KAS'));   // saved first
  assert.deepEqual(r.job_ids, ['j9']); assert.equal(handed[1], 'fighter:KAS');
  assert.match(x.statuses.at(-1), /rebuilding fighter:KAS \(job j9\)/);
});

test('the rebuild recipe: the game\'s recorded cast recipe that holds this donor, else the donor\'s own source; op=use stays use', async () => {
  const sb = { groups: [{ key: 'cast', builds: [{ rebuild_recipe: { tool: 'characters', input: { op: 'cast_swap', target_game: 'g',
    source: 'wrestlers', mapping: 'auto', seed: '', slots: 'a,fighter:KAS', assignments: [{ slot: 'fighter:KAS', character: 'amy' }] } } }] }] };
  let x = fakeIo({ '/api/games/g/special_builds': sb });
  let c = E.controller(x.io, { slug: 'amy', gid: 'g', title: 'T', slot: 'fighter:KAS' });
  await c.load();
  assert.equal((await c.rebuildRecipe()).input.source, 'wrestlers');
  x = fakeIo(); c = E.controller(x.io, { slug: 'amy', gid: 'g', title: 'T', slot: 'fighter:KAS' });
  x.io.api = (orig => async (p, b) => (p.startsWith('/api/characters/amy/retarget_profile') ? Object.assign({}, VIEW, { source: { game_id: 'fedcba9876543210' } }) : orig(p, b)))(x.io.api);
  await c.load();
  assert.equal((await c.rebuildRecipe()).input.source, 'fedcba9876543210');
  c = E.controller(fakeIo().io, { slug: 'amy', gid: 'g', slot: 'player', recipe: { tool: 'characters', input: { op: 'use', character: 'amy', game_id: 'g', slot: 'player' } } });
  await c.load();
  assert.deepEqual((await c.rebuildRecipe()).input, { op: 'use', character: 'amy', game_id: 'g', slot: 'player', launch: false, rebuild: true });
});

test('the frame has the Goals part slots and the Save and rebuild button; the shells hand rebuilds to the pop-up', () => {
  const f = E.frameHTML();
  for (const s of ['data-rt-part-slot="tabs"', 'data-rt-part-slot="joint"', 'data-rt-part-slot="legend"', 'data-rt-go="save-rebuild"',
    'data-rt="donor-cap"', 'data-rt="target-cap"', 'rt-goals-only'])
    assert.ok(f.includes(s), s);
  assert.equal(E.CAPTIONS.goals.donor[0], 'Source · donor'); assert.equal(E.CAPTIONS.goals.target[0], 'Target · goals');
  const web = read('web/index.html'), desk = read('desktop/index.html');
  assert.match(web, /onRebuild: r => window\.GBOX_PROCESS_POPUP && window\.GBOX_PROCESS_POPUP\.follow\(\(r\.job_ids \|\| \[\]\)\[0\]\)/);
  assert.match(desk, /onRebuild: \(r, st\) => \{[\s\S]{0,160}PROCESS_POPUP\.follow\(\(r\.job_ids \|\| \[\]\)\[0\]\)/);
});

// ---- the browser binding with a stand-in three.js: the Goals view draws both sides and a donor circle drags ----------
function fakeThree(models) {
  class V3 { constructor(x = 0, y = 0, z = 0) { this.x = x; this.y = y; this.z = z; }
    set(x, y, z) { this.x = x; this.y = y; this.z = z; return this; }
    fromBufferAttribute(a, i) { return this.set(a.array[3 * i], a.array[3 * i + 1], a.array[3 * i + 2]); }
    applyMatrix4() { return this; } toArray() { return [this.x, this.y, this.z]; } }
  class Obj { constructor() { this.children = []; this.parent = null; this.visible = true; this.position = new V3();
      this.matrix = { set: (...m) => { this.m = m; } }; }
    add(c) { c.parent = this; this.children.push(c); } traverse(f) { f(this); for (const c of this.children) c.traverse(f); }
    updateMatrixWorld() {} }
  class Bone extends Obj { constructor(name, at) { super(); this.isBone = true; this.name = name; this.at = at; }
    getWorldPosition(v) { return v.set(...this.at); } }
  class BufferAttribute { constructor(array, n = 3) { this.array = array; this.count = array.length / n; } }
  class BufferGeometry { constructor() { this.attributes = {}; this.index = null; } setAttribute(k, a) { this.attributes[k] = a; }
    setIndex(i) { this.index = { array: i }; } computeVertexNormals() {} computeBoundingSphere() {} dispose() {} }
  class Mesh extends Obj { constructor(g, m) { super(); this.isMesh = true; this.geometry = g; this.material = m; } }
  const THREE = { Vector3: V3, Group: Obj, Scene: Obj, Mesh, BufferGeometry, BufferAttribute, HemisphereLight: Obj,
    MeshStandardMaterial: class { dispose() {} }, DirectionalLight: Obj,
    OrthographicCamera: class extends Obj { updateProjectionMatrix() {} },
    WebGLRenderer: class { constructor() { this.domElement = { tag: 'gl' }; } setPixelRatio() {} setSize() {} render() { this.frames = (this.frames || 0) + 1; } dispose() {} } };
  // a skinned T-posed donor: one bone per role at the skeleton's joints, an arm of vertices skinned by where x falls
  function gltf(pos) {
    const scene = new Obj(), bones = Object.entries(pos).map(([r, p]) => new Bone(r === 'hip' ? 'pelvis' : r, p));
    bones.forEach((b, i) => (i ? bones[0] : scene).add(b));
    const xs = [0.25, 0.35, 0.45, 0.55, 0.65, 0.8, 0, 0, 0], ys = [1.45, 1.45, 1.45, 1.45, 1.45, 1.45, 0, 1.0, 1.75];
    const P = new Float32Array(xs.flatMap((x, i) => [x, ys[i], 0])), idx = bones.map(b => b.name);
    const bi = n => idx.indexOf(n), own = xs.map((x, i) => (i >= 6 ? (i === 8 ? bi('head') : bi('pelvis')) : x < 0.5 ? bi('l_upper') : x < 0.75 ? bi('l_fore') : bi('l_hand')));
    const g = new BufferGeometry(); g.setAttribute('position', new BufferAttribute(P));
    g.setAttribute('skinIndex', new BufferAttribute(Uint16Array.from(own.flatMap(j => [j, 0, 0, 0])), 4));
    g.setAttribute('skinWeight', new BufferAttribute(Float32Array.from(own.flatMap(() => [1, 0, 0, 0])), 4));
    g.index = { array: Uint16Array.from([0, 1, 2, 3, 4, 5, 6, 7, 8]) };
    const m = new Mesh(g); m.isSkinnedMesh = true; m.skeleton = { bones }; m.applyBoneTransform = () => {}; m.matrixWorld = null;
    bones[0].add(m);
    return { scene };
  }
  return { THREE, GLTFLoader: class { async parseAsync() { return gltf(models.shift()); } } };
}
function fakeDom() {
  const made = [];
  const el = (tag = 'div') => {
    const e = { tag, style: {}, attrs: {}, children: [], dataset: {}, textContent: '', innerHTML: '', on: {}, cache: {},
      setAttribute(k, v) { this.attrs[k] = v; }, addEventListener(k, f) { this.on[k] = f; },
      querySelector(s) { return this.cache[s] || (this.cache[s] = el('q')); }, querySelectorAll: () => [],
      append(...c) { this.children.push(...c); }, insertBefore(n) { this.children.unshift(n); }, remove() { this.removed = true; },
      getBoundingClientRect: () => ({ left: 0, top: 0, width: 400, height: 400 }), setPointerCapture() {},
      getContext: () => new Proxy({}, { get: (t, k) => (k in t ? t[k] : () => {}), set: (t, k, v) => { t[k] = v; return true; } }) };
    made.push(e); return e;
  };
  return { getElementById: () => null, createElement: el, head: el('head'), body: el('body') };
}

const near = (a, b, eps) => a.forEach((v, i) => assert.ok(Math.abs(v - b[i]) <= eps, `${a} vs ${b}`));

test('the browser binding: the Goals view T-poses the donor, numbers both sides and drags a donor joint', async () => {
  const frames = [];
  Object.assign(globalThis, { requestAnimationFrame: f => { frames.push(f); return frames.length; }, devicePixelRatio: 1,
    fetch: async () => ({ ok: true, arrayBuffer: async () => new ArrayBuffer(0) }) });
  const tick = async () => { for (let i = 0; i < 20; i++) await new Promise(r => setImmediate(r)); while (frames.length) frames.shift()(); };
  const target = JSON.parse(JSON.stringify(GOALS));
  target.goals.target = H.standardSkeleton(1.7);
  target.goals.target.l_hand = [0.45, 1.17, 0];                     // the slot's forearm hangs down
  const x = fakeIo({ '/api/retarget/goals': target, '/api/retarget/reference': { reference: null } });
  const POSE = H.standardSkeleton(1.7);
  const io = Object.assign({}, x.io, { loadModules: async () => fakeThree([POSE]) });
  const r = E.open(fakeDom(), io, { slug: 'amy', gid: 'g', title: 'T', slot: 'fighter:KAS', view: 'goals' });
  await tick(); await tick();
  const c = r.controller, dv = r.views.donor, tv = r.views.target;
  c.setRoleBone('l_upper', 'l_upper'); c.setRoleBone('l_fore', 'l_fore'); c.setRoleBone('l_hand', 'l_hand');
  r.el.on.change({ target: { closest: s => (s === '[data-rt-bone]' ? { dataset: { rtBone: 'head' }, value: 'head' } : null), matches: () => false } });
  await tick();
  assert.equal(c.state.mode, 'goals');
  assert.ok(dv.circles && dv.circles.length >= 4, 'donor circles drawn');
  assert.deepEqual(tv.circles.map(g => g.n), H.GOALS.map((_, i) => i + 1));          // the slot's 16 joints, numbered
  const elbow = dv.circles.find(g => g.role === 'l_fore');
  assert.ok(elbow, 'the elbow circle'); assert.equal(tv.circles.find(g => g.role === 'l_fore').n, elbow.n);
  near(tv.circles.find(g => g.role === 'l_hand').at, [0.70, 1.42, 0], 1e-9);              // the slot's arm T-posed
  const [sx, sy] = dv.map.toScreen(elbow.at);
  const ev = (cx, cy) => ({ clientX: cx, clientY: cy, pointerId: 1, preventDefault() {}, stopPropagation() {} });
  dv.ov.on.pointerdown(ev(sx, sy));
  const down = dv.map.s * 0.034;                                    // 0.034 model units down on the screen
  dv.ov.on.pointermove(ev(sx, sy + down));
  dv.ov.on.pointerup(ev(sx, sy + down));
  await tick();
  const j = c.state.profile.joints.l_fore, Hd = 1.75;              // the stand-in mesh spans y 0..1.75
  near(j, [0, -0.034 / Hd, 0], 1e-4);
  assert.equal(c.state.joint, 'l_fore'); assert.ok(c.state.dirty);
  const again = r.views.donor.circles.find(g => g.role === 'l_fore');
  near(again.at, [elbow.at[0], elbow.at[1] - 0.034, 0], 1e-4);     // the circle sits where it was dropped
  dv.ov.on.pointerdown(ev(...dv.map.toScreen(again.at))); dv.ov.on.pointerup(ev(...dv.map.toScreen(again.at)));
  assert.equal(c.state.joint, 'l_fore');                            // a click: that joint's bone list
  c.setMode('fit'); await tick();
  assert.equal(r.el.dataset.mode, 'fit'); assert.ok(tv.handles && tv.handles.length);   // the proportions view still works
  assert.ok(!x.statuses.some(s => /✗|unavailable/.test(s)), x.statuses.join(' | '));      // no error on the way
  r.dispose();
});

// ---- "Turn around" in the preview: the fit frame is the slot's own facing in the build times the turn ----------------
test('a slot skeleton facing the other way shows the donor backwards until Turn around, like the build', async () => {
  const frames = [];
  Object.assign(globalThis, { requestAnimationFrame: f => { frames.push(f); return frames.length; }, devicePixelRatio: 1,
    fetch: async () => ({ ok: true, arrayBuffer: async () => new ArrayBuffer(0) }) });
  const tick = async () => { for (let i = 0; i < 20; i++) await new Promise(r => setImmediate(r)); while (frames.length) frames.shift()(); };
  const target = JSON.parse(JSON.stringify(GOALS));
  // the slot as the last build loaded it faces -Z (its left on -X): the build would fit a front-facing donor backwards
  target.goals.target = Object.fromEntries(Object.entries(H.standardSkeleton(1.7)).map(([r, p]) => [r, [-p[0], p[1], -p[2]]]));
  const x = fakeIo({ '/api/retarget/goals': target, '/api/retarget/reference': { reference: null } });
  const io = Object.assign({}, x.io, { loadModules: async () => fakeThree([H.standardSkeleton(1.7)]) });
  let closed = 0;
  const r = E.open(fakeDom(), io, { slug: 'amy', gid: 'g', title: 'T', slot: 'fighter:KAS', view: 'goals', onClose: () => closed++ });
  await tick(); await tick();
  const c = r.controller;
  for (const role of ['l_upper', 'l_fore', 'l_hand']) c.setRoleBone(role, role);
  r.el.on.change({ target: { closest: s => (s === '[data-rt-bone]' ? { dataset: { rtBone: 'head' }, value: 'head' } : null), matches: () => false } });
  await tick();
  const shoulder = () => {                                 // the donor's upper-arm vertex by the shoulder (x 0.25), fitted
    const mesh = r.views.target.group.children.find(m => m.isMesh);
    return Array.from(mesh.geometry.attributes.position.array.slice(0, 3));
  };
  const before = shoulder();
  assert.ok(before[0] < 0, `backwards: the left arm starts from the slot's right shoulder (${before})`);
  r.el.on.click({ target: { closest: s => (s === '[data-rt-go]' ? { dataset: { rtGo: 'turn' } } : null) } });
  await tick();
  assert.equal(c.state.profile.turn, true); assert.ok(c.state.dirty);
  const after = shoulder();
  near(after, [0.25, 1.45, 0], 0.02);                                     // on the slot's own left shoulder
  assert.equal(c.payload('slot').profile.turn, true);
  // Swap left <-> right: the roles trade bones, the donor's facing flips and its model turns with its bone dots
  c.setRoleBone('r_upper', 'r_upper'); r.el.on.change({ target: { closest: s => (s === '[data-rt-bone]' ? { dataset: { rtBone: 'r_upper' }, value: 'r_upper' } : null), matches: () => false } });
  await tick();
  assert.equal(r.views.donor.group.m[0], 1);
  r.el.on.click({ target: { closest: s => (s === '[data-rt-go]' ? { dataset: { rtGo: 'swap-lr' } } : null) } });
  await tick();
  assert.equal(c.state.roles.l_upper, 'r_upper'); assert.equal(c.state.roles.r_upper, 'l_upper');
  assert.equal(r.views.donor.group.m[0], -1);                              // the Fit view's donor mesh follows
  assert.deepEqual(c.payload('slot').profile.roles, { head: 'head', l_upper: 'r_upper', r_upper: 'l_upper', r_fore: 'l_fore', r_hand: 'l_hand' });
  assert.equal(closed, 0); r.dispose(); assert.equal(closed, 1);          // the opener's hold goes with the editor
  r.dispose(); assert.equal(closed, 1);
});
