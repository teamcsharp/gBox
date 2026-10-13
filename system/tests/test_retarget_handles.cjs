const { test } = require('node:test');
const assert = require('node:assert/strict');
const H = require('../clients/web/viz/retarget-handles.js');

// the same T-pose and profile as tests/test_retarget_profile.py; expected values computed by gbox/retarget_profile.py
const POS = { hip: [0, 1.0, 0], chest: [0, 1.3, 0], neck: [0, 1.5, 0], head: [0, 1.6, 0],
  l_upper: [0.2, 1.45, 0], l_fore: [0.5, 1.45, 0], l_hand: [0.75, 1.45, 0],
  r_upper: [-0.2, 1.45, 0], r_fore: [-0.5, 1.45, 0], r_hand: [-0.75, 1.45, 0],
  l_thigh: [0.1, 0.95, 0], l_shin: [0.1, 0.5, 0], l_foot: [0.1, 0.08, 0],
  r_thigh: [-0.1, 0.95, 0], r_shin: [-0.1, 0.5, 0], r_foot: [-0.1, 0.08, 0] };
const PROF = { height: 1.2, ground: 0.05, head: 1.3, torso_width: 1.4, arm_length: 1.1, leg_length: 0.9,
  adjust: { l_fore: { length: 1.5, girth: 0.8, rotate: [0, 0, 20], offset: [0.01, 0, 0] },
    chest: { scale: [1.1, 1, 1.2] }, head: { rotate: [10, 0, 0] } } };
const PY = { head: [0.078, 2.203355898, 0.194263683], l_fore: [0.884842172, 1.932825234, 0.0192],
  chest: [0.2772, 1.64, 0.072], r_shin: [-0.192, 0.896, 0.036], l_hand: [1.062, 1.808, 0.0], _other: [0.336, 1.4, 0.0] };
const PTS = { head: [0.05, 1.75, 0.1], l_fore: [0.6, 1.5, 0.02], chest: [0.15, 1.3, 0.05], r_shin: [-0.12, 0.7, 0.03],
  l_hand: [0.8, 1.44, 0.0] };
const close = (a, b, eps = 1e-6) => a.forEach((x, i) => assert.ok(Math.abs(x - b[i]) < eps, `${a} vs ${b}`));

test('the preview maths matches gbox/retarget_profile.py on the same skeleton and profile', () => {
  const tr = H.roleTransforms(POS, PROF, 0);
  for (const [role, v] of Object.entries(PTS)) close(H.applyVertex(v, [[role, 1]], tr), PY[role]);
  close(H.applyVertex([0.2, 1.1, 0], [[null, 1]], tr), PY._other);
  // the flat whole-mesh path gives the same numbers, blending by weight
  const pos = new Float32Array([...PTS.head, ...PTS.chest]);
  const out = H.applyPositions(pos, Int16Array.from([H.ROLES.indexOf('head'), -1, H.ROLES.indexOf('chest'), H.ROLES.indexOf('head')]),
    Float32Array.from([1, 0, 0.5, 0.5]), 2, tr);
  close([...out.slice(0, 3)], PY.head, 1e-5);
  const mixed = H.applyVertex(PTS.chest, [['chest', 0.5], ['head', 0.5]], tr);
  close([...out.slice(3, 6)], mixed, 1e-5);
});

test('normalize clamps like the server and drops default adjustments', () => {
  const p = H.normalize({ height: 99, ground: -3, head: '1.5', adjust: { l_fore: { length: 0.01 }, r_fore: {} , tail: { length: 2 } },
    roles: { head: ' Head ', wing: 'x' } });
  assert.equal(p.height, 4); assert.equal(p.ground, -0.5); assert.equal(p.head, 1.5);
  assert.equal(p.adjust.l_fore.length, 0.25); assert.ok(!('r_fore' in p.adjust) && !('tail' in p.adjust));
  assert.deepEqual(p.roles, { head: 'Head' });
  assert.ok(H.isIdentity({ roles: { hip: 'x' } })); assert.ok(!H.isIdentity({ head: 1.1 }));
});

// ---------- the circles ----------
const at = (list, id) => list.find(h => h.id === id);

test('dragging a limb circle along the bone sets that segment length; across it changes nothing', () => {
  let p = H.normalize({});
  const h = at(H.handles(POS, p, 0), 'len:l_fore');
  close(h.at, POS.l_hand);                                           // the circle sits on the wrist
  p = H.drag(p, h, [0.5 + 0.25 * 1.6, 1.45 + 0.3, 0], POS, 0);       // 1.6x along the forearm, off-axis in y
  assert.ok(Math.abs(p.adjust.l_fore.length - 1.6) < 1e-9);
  close(at(H.handles(POS, p, 0), 'len:l_fore').at, [0.5 + 0.25 * 1.6, 1.45, 0]);   // and the circle follows
  // with a global arm length and height the segment's own length is what's left
  const q = H.drag({ arm_length: 2, height: 1 }, h, [0.5 + 0.25 * 3, 1.45, 0], POS, 0);
  assert.ok(Math.abs(q.adjust.l_fore.length - 1.5) < 1e-9);
});

test('the head ring sets the head size; shoulders the torso width; top and ground the height and lift', () => {
  let p = H.normalize({});
  const hs = H.handles(POS, p, 0), head = at(hs, 'head');
  p = H.drag(p, head, [head.centre[0], head.centre[1] + 0.12 * 1.6 * 1.25, 0], POS, 0);
  assert.ok(Math.abs(p.head - 1.25) < 1e-9);
  p = H.drag(p, at(hs, 'width:l_upper'), [0.3, 1.45, 0], POS, 0);
  assert.ok(Math.abs(p.torso_width - 1.5) < 1e-9);
  const w = at(H.handles(POS, p, 0), 'width:r_upper');
  close(w.at, [-0.3, 1.45, 0]);                                      // both shoulders move out together
  const top = at(hs, 'height');
  close(top.at, [0, 1.6 + 0.18 * 1.6, 0]);
  p = H.drag(p, top, [0, 1.1 * (1.6 + 0.18 * 1.6), 0], POS, 0);
  assert.ok(Math.abs(p.height - 1.1) < 1e-9);
  p = H.drag(p, at(hs, 'ground'), [0.56, 0.08, 0], POS, 0);
  assert.ok(Math.abs(p.ground - 0.05) < 1e-9);
  // the dragged profile moves real vertices the way the server will
  const tr = H.roleTransforms(POS, p, 0);
  close(H.applyVertex([0, 1.0, 0], [['hip', 1]], tr), [0, 1.0 * 1.1 + 0.05 * 1.6, 0]);
});

test('an offset drag moves one part by a fraction of the figure height', () => {
  const p = H.drag({}, { kind: 'offset', role: 'head', at: [0, 1.6, 0] }, [0.16, 1.6, 0], POS, 0);
  close(p.adjust.head.offset, [0.1, 0, 0]);
});

test('hit testing picks the nearest circle within its radius', () => {
  const hs = H.handles(POS, {}, 0);
  assert.equal(H.hit(hs, [0.751, 1.451]).id, 'len:l_fore');
  assert.equal(H.hit(hs, [5, 5]), null);
  assert.equal(H.hit(hs, [0.2, 1.47], 0.001).id, 'width:l_upper');
});

test('the front view maps model points to pixels and back', () => {
  const v = H.view({ min: [-1, 0, 0], max: [1, 2, 0] }, 200, 400, 0);
  assert.deepEqual(v.toScreen([0, 1, 0]), [100, 200]);
  assert.deepEqual(v.toScreen([1, 2, 0]), [200, 100]);                // uniform scale: the narrower axis fits
  close(v.toModel([150, 100]), [0.5, 2, 0]);
});

// ---------- what is what ----------
test('bone names are guessed into roles without double use', () => {
  const bones = ['mixamorig:Hips', 'mixamorig:Spine2', 'mixamorig:Neck', 'mixamorig:Head', 'mixamorig:LeftArm',
    'mixamorig:LeftForeArm', 'mixamorig:LeftHand', 'mixamorig:RightArm', 'mixamorig:RightForeArm', 'mixamorig:RightHand',
    'mixamorig:LeftUpLeg', 'mixamorig:LeftLeg', 'mixamorig:LeftFoot', 'Bip01 R Thigh', 'Bip01 R Calf', 'Bip01 R Foot'];
  const g = H.guessRoles(bones);
  assert.equal(g.hip, 'mixamorig:Hips'); assert.equal(g.head, 'mixamorig:Head'); assert.equal(g.chest, 'mixamorig:Spine2');
  assert.equal(g.l_upper, 'mixamorig:LeftArm'); assert.equal(g.l_fore, 'mixamorig:LeftForeArm');
  assert.equal(g.r_hand, 'mixamorig:RightHand'); assert.equal(g.l_thigh, 'mixamorig:LeftUpLeg');
  assert.equal(g.r_thigh, 'Bip01 R Thigh'); assert.equal(g.r_shin, 'Bip01 R Calf');
  assert.equal(new Set(Object.values(g)).size, Object.values(g).length);
  assert.equal(H.guessRoles(bones, { head: 'mixamorig:Neck' }).head, 'mixamorig:Neck');    // known roles are kept
});

test('assigning a bone moves it off its old role; overrides round-trip against the collection roles', () => {
  let r = { hip: 'pelvis', head: 'neck_01', chest: 'spine' };
  r = H.assign(r, 'neck', 'neck_01');
  assert.deepEqual(r, { hip: 'pelvis', chest: 'spine', neck: 'neck_01' });
  r = H.assign(r, 'head', 'head_01');
  assert.deepEqual(H.issues(r).missing, []);
  assert.deepEqual(H.issues(H.assign(r, 'hip', '')).missing, ['hip']);
  assert.throws(() => H.assign(r, 'tail', 'x'));
  const base = { hip: 'pelvis', head: 'neck_01', chest: 'spine' };
  const ov = H.roleOverrides(base, r);
  assert.deepEqual(ov, { neck: 'neck_01', head: 'head_01' });
  assert.deepEqual(H.applyOverrides(base, ov), r);
  assert.deepEqual(H.roleOverrides(base, { hip: 'pelvis', head: 'neck_01' }), { chest: '' });
});

test('every bone takes its nearest assigned ancestor role', () => {
  const names = ['root', 'pelvis', 'spine', 'neck', 'head', 'jaw', 'l_arm'];
  const parents = [-1, 0, 1, 2, 3, 4, 2];
  assert.deepEqual(H.boneRoles(names, parents, { hip: 'pelvis', chest: 'spine', head: 'head' }),
    ['hip', 'hip', 'chest', 'chest', 'head', 'head', 'chest']);
});

test('the preview base fit matches figure heights and hips', () => {
  const donor = { hip: [5, 10, 0], head: [5, 18, 0] }, target = { hip: [0, 1, 0], head: [0, 1.6, 0] };
  const f = H.baseFit(donor, 2, target, 0);
  close(f.apply([5, 18, 0]), [0, 1.6, 0]); close(f.apply([5, 2, 0]), [0, 0, 0]);
  const s = H.standardSkeleton(1.7);
  assert.equal(Object.keys(s).length, 18); assert.ok(Math.abs(s.head[1] - 1.58) < 1e-9);
});
