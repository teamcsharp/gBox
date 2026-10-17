// Ghost runs overlay (clients/web/viz/ghost-runs.js, #1098): which ghost frame races the live frame, sampling the
// track, the projection onto the live camera, where the native picture sits inside the game element for each aspect,
// the race timer rows, and the Auto picture scorer on a synthetic frame. Synthetic data only.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const G = require('../clients/web/viz/ghost-runs.js');

const PROFILE = { screen: [256, 240], box: { w: 16, h: 32, small_h: 16 } };
const RUN = {
  attempts: [{ level: '1-1', start: 0, end: 300, result: 'death' }, { level: '1-1', start: 400, end: 1000, result: 'clear' },
    { level: '1-2', start: 1200, end: 1500, result: 'end' }],
  splits: [{ level: '1-1', start: 0, end: 1000, frames: 1000, segment: 600, deaths: 1 }],
};
const cols = (rows) => Object.fromEntries(['f', 'x', 'y', 'lv', 'ap', 'face', 'st', 'anim', 'pw', 'joy', 'scr', 'sub']
  .map((k) => [k, rows.map((r) => r[k] ?? 0)]));

test('level sync replays the clearing attempt; run sync the same run frame', () => {
  const live = { level: '1-1', attempt_level: '1-1', level_frame: 120, run_frame: 77 };
  assert.equal(G.ghostFrame(RUN, live, 'level'), 520);
  assert.equal(G.ghostFrame(RUN, live, 'run'), 77);
  assert.equal(G.ghostFrame(RUN, { ...live, attempt_level: '1-2', level: '1-2' }, 'level'), 1320);   // its last try there
  assert.equal(G.ghostFrame(RUN, { ...live, attempt_level: '4-2', level: '4-2' }, 'level'), null);
  assert.equal(G.ghostFrame(RUN, { ...live, level_frame: null }, 'level'), null);
  assert.deepEqual(G.attemptOf(RUN, live, 'level'), RUN.attempts[1]);
  const noClear = { attempts: [{ level: '3-1', start: 0, end: 900, result: 'death' }, { level: '3-1', start: 1000, end: 1100, result: 'death' }] };
  assert.equal(G.ghostFrame(noClear, { level: '3-1', level_frame: 10 }, 'level'), 10);   // no clear: its longest try
});

test('sampleAt: the row at or before the frame, interpolating short gaps only', () => {
  const c = cols([{ f: 10, x: 100, y: 400 }, { f: 14, x: 108, y: 404 }, { f: 40, x: 300, y: 404 }]);
  assert.equal(G.sampleAt(c, 9), null);
  assert.deepEqual([G.sampleAt(c, 12).x, G.sampleAt(c, 12).y], [104, 402]);
  assert.equal(G.sampleAt(c, 20).x, 108);                                     // 26-frame gap: not invented
  assert.equal(G.sampleAt(c, 99).done, true);
});

test('ghostScreen: world x minus the live camera, small player in the lower half, off-screen sides', () => {
  const row = { x: 700, y: 256 + 160, lv: 0, ap: 0xC2, pw: 4, face: 2, anim: 8 };
  const live = { level: '1-1', ap: 0xC2, scr: 600 };
  const g = G.ghostScreen(row, live, PROFILE);
  assert.deepEqual([g.x, g.y, g.w, g.h, g.small, g.visible], [100, 176, 16, 16, true, true]);
  assert.equal(G.ghostScreen({ ...row, pw: 1 }, live, PROFILE).h, 32);
  assert.equal(G.ghostScreen(row, { ...live, scr: 100 }, PROFILE).side, 'right');
  assert.deepEqual([G.ghostScreen(row, { ...live, scr: 800 }, PROFILE).side, G.ghostScreen(row, { ...live, scr: 800 }, PROFILE).distance], ['left', 100]);
  assert.equal(G.ghostScreen(row, { ...live, ap: 0x25 }, PROFILE), null);
  assert.equal(G.ghostScreen({ ...row, lv: 5 }, live, PROFILE), null);        // 2-2 is not 1-1
  assert.equal(G.levelName(5), '2-2');
});

test('pictureRect: frame fitted in the element, the 4:3 picture letterboxed inside a 16:9 frame', () => {
  const r = G.pictureRect({ x: 10, y: 20, w: 1600, h: 900 }, { w: 1920, h: 1080 }, { aspect: '4:3' }, [256, 240]);
  assert.deepEqual([r.x, r.y, r.w, r.h], [10 + (1600 - 1200) / 2, 20, 1200, 900]);
  assert.deepEqual(r.map(0, 0), [210, 20]);
  assert.deepEqual(r.map(256, 240), [1410, 920]);
  const p87 = G.pictureRect({ x: 0, y: 0, w: 878, h: 720 }, { w: 878, h: 720 }, { aspect: '8:7' }, [256, 240]);
  assert.ok(Math.abs(p87.w - 878) < 1 && Math.abs(p87.h - 720) < 1);          // the isolated Mesen viewport, 1.219
  const fill = G.pictureRect({ x: 0, y: 0, w: 500, h: 200 }, { w: 500, h: 200 }, { aspect: 'fill' }, [256, 240]);
  assert.deepEqual([fill.w, fill.h], [500, 200]);
  const crop = G.pictureRect({ x: 0, y: 0, w: 1024, h: 896 }, { w: 1024, h: 896 }, { aspect: '1:1', crop_top: 8, crop_bottom: 8 }, [256, 240]);
  assert.deepEqual(crop.map(0, 8), [0, 0]);                                   // the first visible line is native line 8
  assert.ok(Math.abs(crop.map(256, 232)[1] - crop.h) < 1e-9);
});

test('fmtTime / raceRows: splits against the ghost, current level against its segment', () => {
  assert.equal(G.fmtTime(60.0988 * 75.5), '1:15.50');
  assert.equal(G.fmtTime(-60.0988 * 1.25), '−1.25');
  assert.equal(G.fmtTime(null), '–');
  const live = { splits: [{ level: '1-1', frames: 940 }], attempt_level: '1-2', level_frame: 300 };
  const rows = G.raceRows(live, { splits: [...RUN.splits, { level: '1-2', frames: 900, segment: 500 }] });
  assert.equal(rows.length, 2);
  assert.deepEqual([rows[0].level, rows[0].delta, rows[0].done], ['1-1', -60, true]);
  assert.match(rows[0].text, /^1-1 15\.64 −1\.00$/);
  assert.deepEqual([rows[1].level, rows[1].ghost, rows[1].delta], ['1-2', 500, null]);
});

test('aspectScore: the right picture aspect puts the predicted box on the player; near the centre it abstains', () => {
  // a synthetic 640x480 frame: sky everywhere, a 16x16 "player" drawn with the 4:3 mapping
  const W = 640, H = 480, rect = (a) => G.pictureRect({ x: 0, y: 0, w: W, h: H }, { w: W, h: H }, { aspect: a }, [256, 240]);
  const frame = (relx) => { const [x0, y0] = rect('4:3').map(relx, 193), [x1, y1] = rect('4:3').map(relx + 16, 209);
    return (x, y) => (x >= x0 && x < x1 && y >= y0 && y < y1 ? [200, 40, 30] : [146, 144, 255]); };
  const scores = (relx) => Object.fromEntries(['4:3', '8:7', '1:1'].map((a) => [a, G.aspectScore(frame(relx), rect(a), { relx, rely: 176, small: 1 }, PROFILE)]));
  const left = scores(16);                                                     // near the left edge: clear winner
  assert.ok(left['4:3'] > 0.8 && left['4:3'] - Math.max(left['8:7'], left['1:1']) > 0.1, JSON.stringify(left));
  const mid = scores(108);                                                     // near the centre every aspect fits
  assert.ok(Math.abs(mid['4:3'] - mid['8:7']) < 0.1, JSON.stringify(mid));     // (no vote; the boxes differ by ~6 px)
});
