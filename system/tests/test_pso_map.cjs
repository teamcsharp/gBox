// Headless tests for the PSO 2D map renderer (clients/web/viz/pso-map.js): the world<->pixel
// transform, decoding the walkable surface, projecting the marks, drawing, and the polling feed.
// Mirrors test_tactical_map.cjs: require the browser module (its CommonJS footer), a Proxy fake 2D
// context, a canned api, and injected timers. Run: node --test system/tests/test_pso_map.cjs
const test = require('node:test');
const assert = require('node:assert/strict');
const P = require('../clients/web/viz/pso-map.js');

const SIZE = { w: 400, h: 400 };

function model() {
  return {
    schema: 'gbox.pso.map/1', live: true, episode: 1, floor: 1, room: 5, fingerprint: 'fp',
    units: 'pso', bounds: [0, 0, 400, 400],
    surface: { origin: [0, 0], cell: 100, cols: 4, rows: 4,
               // row 0 fully walkable (0xF0 = bits 0..3), rows 1..3 empty -> 4 walkable cells
               walk_b64: Buffer.from([0xF0, 0x00]).toString('base64') },
    switches: [{ id: 'sw1', x: 150, z: 150, flag_index: 12, pressed: false }],
    doors: [{ id: 'd1', x: 250, z: 250, type: 'TObjDoor', flag_index: 13, open: false, to_room: 6 }],
    warps: [{ id: 'w1', x: 350, z: 50, kind: 'area_warp', to: 'floor_2' }],
    exit: { x: 50, z: 350, kind: 'teleporter' },
    enemies: [{ id: 'e1', x: 200, z: 100, cls: 'TObjEneBm3', class: 'Booma', alive: true, hp: 120 }],
    players: [{ slot: 1, role: 'leader', x: 200, z: 200, hp: 33, heading: 90, room: 5 },
              { slot: 2, role: 'swarm', x: 220, z: 210, hp: 38, room: 5 }],
    path: [[200, 200], [250, 250]], target: { x: 250, z: 250, kind: 'goto' },
    objective: 'reach the door',
  };
}

test('project/unproject round-trip', () => {
  const v = P.viewOf({ cx: 100, cz: 100, radius: 200, rot: 0 }, SIZE);
  for (const [x, z] of [[0, 0], [150, -30], [200, 320]]) {
    const [px, py] = P.project(v, x, z);
    const [bx, bz] = P.unproject(v, px, py);
    assert.ok(Math.abs(bx - x) < 1e-6 && Math.abs(bz - z) < 1e-6, `round-trip ${x},${z}`);
  }
});

test('fitCamera centres on the bounds', () => {
  const c = P.fitCamera({ bounds: [0, 0, 400, 400] });
  assert.equal(c.cx, 200); assert.equal(c.cz, 200);
  assert.ok(c.radius >= 200 && c.rot === 0);
});

test('zoom keeps the cursor world point fixed', () => {
  const cam = { cx: 100, cz: 100, radius: 200, rot: 0 };
  const before = P.unproject(P.viewOf(cam, SIZE), 300, 120);
  const zoomed = P.zoomView(cam, SIZE, 300, 120, 0.5);
  const after = P.unproject(P.viewOf(zoomed, SIZE), 300, 120);
  assert.ok(Math.abs(before[0] - after[0]) < 1e-6 && Math.abs(before[1] - after[1]) < 1e-6);
  assert.ok(zoomed.radius < cam.radius);
});

test('surfaceCells decodes the walkable bit grid', () => {
  const s = P.surfaceCells(model().surface);
  assert.equal(s.rects.length, 4);                 // row 0, four cells
  assert.deepEqual(s.rects[0], [0, 0, 100, 100]);
  assert.equal(s.cell, 100);
  assert.equal(P.surfaceCells(null), null);
});

test('surfaceCells falls back to a point cloud', () => {
  const s = P.surfaceCells({ cells: [[10, 20], [30, 40]], cell: 50 });
  assert.equal(s.rects.length, 2);
  assert.deepEqual(s.rects[0], [-15, -5, 35, 45]);
});

test('marks project every entity and flag the leader', () => {
  const v = P.viewOf(P.fitCamera(model()), SIZE);
  const ms = P.marks(model(), v);
  const kinds = ms.map(m => m.kind);
  for (const k of ['switch', 'door', 'warp', 'exit', 'enemy', 'player']) assert.ok(kinds.includes(k), k);
  const leader = ms.find(m => m.kind === 'player' && m.leader);
  assert.ok(leader && leader.tip.includes('P1'));
  const sw = ms.find(m => m.kind === 'switch');
  assert.equal(sw.wx, 150); assert.equal(sw.wz, 150); assert.ok(sw.tip.includes('unpressed'));
  const door = ms.find(m => m.kind === 'door');
  assert.ok(door.open === false && door.tip.includes('locked'));
});

// a Proxy-based fake 2D context that records every call + style assignment (like the tactical test)
function recorder() {
  const calls = [];
  return new Proxy({}, { get(_t, k) {
    if (k === '_calls') return calls;
    return (...args) => { calls.push([k, ...args]); };
  }, set(_t, k, v) { calls.push(['=' + k, v]); return true; } });
}

test('draw paints the floor and the marks, and returns the hittable marks', () => {
  const ctx = recorder();
  const v = P.viewOf(P.fitCamera(model()), SIZE);
  const ms = P.draw(ctx, { model: model(), view: v, theme: { void: '#000', floor: '#fff', ink: '#111', halo: '#fff',
    muted: '#888', player: '#2a78d6', leader: '#1746c9', plan: '#1baf7a', locked: '#e34948', open: '#1baf7a',
    switchOn: '#1baf7a', switchOff: '#eda100', warp: '#8a5cf6', exit: '#13b5c8' } });
  assert.ok(ms.length >= 6);
  const fills = ctx._calls.filter(c => c[0] === 'fillRect');
  assert.ok(fills.length >= 4, 'drew the walkable cells as the floor');
  assert.ok(ctx._calls.some(c => c[0] === 'stroke'), 'drew the path / marks');
});

test('draw is safe with an empty model', () => {
  const ctx = recorder();
  const ms = P.draw(ctx, { model: null, view: P.viewOf({ cx: 0, cz: 0, radius: 100, rot: 0 }, SIZE), theme: { void: '#000' } });
  assert.deepEqual(ms, []);
});

test('the feed polls the model and reports it', async () => {
  const frames = [];
  let fire = null;
  const setTimer = (fn) => { fire = fn; return 1; };
  const api = async (path) => { assert.ok(path.startsWith('/api/pso/map/')); return model(); };
  const feed = P.create({ sid: 'sess', api, onFrame: f => frames.push(f), setTimer, clearTimer: () => {} });
  await fire();                                     // run the first tick
  assert.equal(frames.length, 1);
  assert.equal(frames[0].fingerprint, 'fp');
  feed.stop();
});

test('the feed degrades when the endpoint is down', async () => {
  const statuses = [];
  let fire = null;
  const setTimer = (fn) => { fire = fn; return 1; };
  const api = async () => { throw new Error('404'); };
  P.create({ sid: 's', api, onFrame: () => {}, onStatus: (_m, e) => statuses.push(e), setTimer, clearTimer: () => {} });
  await fire();
  assert.ok(statuses.some(s => String(s).includes('404')));
});
