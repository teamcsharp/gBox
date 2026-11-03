// Headless tests for the PSO 2D map renderer (clients/web/viz/pso-map.js): the world<->pixel
// transform, turning the bot's collision grid cells into the floor, projecting the marks, drawing,
// and the polling feed. The model shape matches the feed (gbox/pso_map_feed.build_model) and the
// bot's surface format (gbox/pso_map.extract_surface). Run: node --test system/tests/test_pso_map.cjs
const test = require('node:test');
const assert = require('node:assert/strict');
const P = require('../clients/web/viz/pso-map.js');

const SIZE = { w: 400, h: 400 };

function model() {
  return {
    schema: 'gbox.pso.map/1', live: true, episode: 1, floor: 1, room: 10, units: 'pso',
    size: 100, bounds: [0, 0, 400, 400],
    cells: [[0, 0], [1, 0], [2, 0], [3, 0], [0, 1], [1, 1]],            // grid coords; world = c*size
    gates: [{ class: 'TObjDoorKey', x: 150, z: 150, room: 10, flag: 7, kind: 'switch', set: false },
            { class: 'TObjDoor', x: 250, z: 250, room: 10, flag: 13, kind: 'gate', set: true }],
    warps: [{ class: 'TObjAreaWarpForest', x: 350, z: 50, room: 10 }],
    players: [{ slot: 1, role: 'leader', x: 200, z: 200, hp: 33, heading: 90, room: 10 },
              { slot: 2, role: 'swarm', x: 220, z: 210, hp: 38, room: 10 }],
    map_directive: { op: 'goto', state: 'navigating', x: 250, z: 250 },
    objective: 'TObjLazerFenceNorm',
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

test('surfaceCells turns the bot grid cells into world rects', () => {
  const s = P.surfaceCells(model());
  assert.equal(s.rects.length, 6);
  assert.deepEqual(s.rects[0], [0, 0, 100, 100]);           // cell [0,0] -> world 0..100
  assert.deepEqual(s.rects[2], [200, 0, 300, 100]);         // cell [2,0]
  assert.equal(s.cell, 100);
  assert.equal(P.surfaceCells({ cells: [], size: 0 }), null);
  assert.equal(P.surfaceCells({}), null);
});

test('marks project gates (switch/door), warps, players, and the goal', () => {
  const v = P.viewOf(P.fitCamera(model()), SIZE);
  const ms = P.marks(model(), v);
  const kinds = ms.map(m => m.kind);
  for (const k of ['switch', 'door', 'warp', 'player', 'goal']) assert.ok(kinds.includes(k), 'missing ' + k);
  const sw = ms.find(m => m.kind === 'switch');
  assert.equal(sw.flag, 7); assert.equal(sw.wx, 150); assert.ok(sw.tip.includes('unpressed') && sw.tip.includes('flag 7'));
  const door = ms.find(m => m.kind === 'door');
  assert.equal(door.flag, 13); assert.ok(door.set === true && door.tip.includes('open'));
  const leader = ms.find(m => m.kind === 'player' && m.leader);
  assert.ok(leader && leader.tip.includes('P1'));
});

// a Proxy-based fake 2D context that records every call + style assignment
function recorder() {
  const calls = [];
  return new Proxy({}, { get(_t, k) { if (k === '_calls') return calls; return (...a) => { calls.push([k, ...a]); }; },
    set(_t, k, v) { calls.push(['=' + k, v]); return true; } });
}

test('draw paints the floor cells, the goal line and the marks', () => {
  const ctx = recorder();
  const v = P.viewOf(P.fitCamera(model()), SIZE);
  const ms = P.draw(ctx, { model: model(), view: v, theme:
    { void: '#000', floor: '#fff', ink: '#111', halo: '#fff', muted: '#888', player: '#2a78d6', leader: '#1746c9',
      plan: '#1baf7a', locked: '#e34948', open: '#1baf7a', switchOn: '#1baf7a', switchOff: '#eda100', warp: '#8a5cf6', exit: '#13b5c8' } });
  assert.ok(ms.length >= 5);
  assert.ok(ctx._calls.filter(c => c[0] === 'fillRect').length >= 6, 'drew the 6 walkable cells');
  assert.ok(ctx._calls.some(c => c[0] === 'stroke'), 'drew the goal line / marks');
});

test('planGraph places room nodes at centroids with door edges and the route to the goal', () => {
  const m = { plan: { centroids: { '2': [0, 0], '5': [100, 0], '12': [200, 0] },
    edges: { '2': { d0: 5 }, '5': { d1: 12 } }, crit_path: [2, 5, 12], current_room: 5, target_room: 12 } };
  const v = P.viewOf(P.fitCamera({ bounds: [-50, -50, 250, 50] }), SIZE);
  const g = P.planGraph(m, v);
  assert.equal(g.nodes.length, 3);
  assert.ok(g.nodes.find(n => n.room === 5).current, 'current room flagged');
  assert.ok(g.nodes.find(n => n.room === 12).goal, 'last crit-path room is the goal');
  assert.ok(g.nodes.find(n => n.room === 12).target, 'target room ringed');
  assert.ok(g.nodes.find(n => n.room === 2).visited, 'rooms before current are visited');
  assert.equal(g.edges.length, 2, 'two door edges');
  assert.equal(g.route.length, 3, 'route runs through all three centroids');
  assert.equal(P.planGraph({}, v), null);
  // first-run (no recalled crit_path): the visited path is the route, with no known goal
  const g2 = P.planGraph({ plan: { centroids: { '2': [0, 0], '7': [50, 0] }, path: [2, 7], current_room: 7 } }, v);
  assert.equal(g2.route.length, 2);
  assert.ok(!g2.nodes.some(n => n.goal), 'no goal flagged before a route is learned');
});

test('draw paints motion trails behind the players when given a trail buffer', () => {
  const theme = { void: '#000', floor: '#fff', ink: '#111', halo: '#fff', muted: '#888', player: '#2a78d6',
    leader: '#1746c9', plan: '#1baf7a', locked: '#e34948', open: '#1baf7a', switchOn: '#1baf7a',
    switchOff: '#eda100', warp: '#8a5cf6', exit: '#13b5c8', trail: '#9db7e8', trailLead: '#5a8ae0' };
  const v = P.viewOf(P.fitCamera(model()), SIZE);
  const bare = recorder(); P.draw(bare, { model: model(), view: v, theme });
  const trails = new Map([[1, [{ x: 100, z: 100 }, { x: 150, z: 120 }, { x: 200, z: 200 }]]]);
  const withT = recorder(); P.draw(withT, { model: model(), view: v, theme, trails });
  const strokes = c => c._calls.filter(x => x[0] === 'stroke').length;
  assert.ok(strokes(withT) > strokes(bare), 'trail segments add stroke calls');
  // safe when trails is absent or not a Map
  assert.doesNotThrow(() => P.draw(recorder(), { model: model(), view: v, theme, trails: null }));
});

test('draw is safe with an empty model', () => {
  const ctx = recorder();
  const ms = P.draw(ctx, { model: null, view: P.viewOf({ cx: 0, cz: 0, radius: 100, rot: 0 }, SIZE), theme: { void: '#000' } });
  assert.deepEqual(ms, []);
});

test('the feed polls the model and reports it', async () => {
  const frames = []; let fire = null;
  const setTimer = (fn) => { fire = fn; return 1; };
  const api = async (path) => { assert.ok(path.startsWith('/api/pso/map/')); return model(); };
  const feed = P.create({ sid: 'sess', api, onFrame: f => frames.push(f), setTimer, clearTimer: () => {} });
  await fire();
  assert.equal(frames.length, 1); assert.equal(frames[0].room, 10);
  feed.stop();
});

test('the feed degrades when the endpoint is down', async () => {
  const statuses = []; let fire = null;
  const setTimer = (fn) => { fire = fn; return 1; };
  P.create({ sid: 's', api: async () => { throw new Error('404'); }, onFrame: () => {}, onStatus: (_m, e) => statuses.push(e), setTimer, clearTimer: () => {} });
  await fire();
  assert.ok(statuses.some(s => String(s).includes('404')));
});
