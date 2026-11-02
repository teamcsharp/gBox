const test = require('node:test'), assert = require('node:assert/strict');
const F = require('../clients/web/viz/picture-fit.js');

test('a 16:9 picture letterboxed in a 4:3 frame fills a 16:9 window top to bottom', () => {
  const r = F.fit({ w: 880, h: 495 }, { w: 640, h: 480 }, { x: 0, y: 60, w: 640, h: 360 });
  assert.equal(Math.round(r.width), 880); assert.equal(Math.round(r.height), 660);
  assert.equal(Math.round(r.top), -82); assert.equal(Math.round(r.left), 0);   // the bars hang outside the window
});

test('without bars the frame is simply contained and centred', () => {
  const r = F.fit({ w: 880, h: 495 }, { w: 640, h: 480 }, null);
  assert.equal(Math.round(r.height), 495); assert.equal(Math.round(r.width), 660); assert.equal(Math.round(r.left), 110);
  assert.equal(F.fit({ w: 0, h: 0 }, { w: 1, h: 1 }, null), null);
});

// The invariant the PiP relies on: whatever the content box, fit() centres the PICTURE in the window (never off to one
// side) and scales it to fill one axis. A PSO-like frame with an asymmetric black band on the left is the key case.
function centre(win, frame, content, s) {
  const r = F.fit(win, frame, content);
  const cx = r.left + (content.x + content.w / 2) * s;   // where the picture's centre lands in the window
  const cy = r.top + (content.y + content.h / 2) * s;
  return { r, cx, cy };
}

test('an asymmetric left band (PSO) still centres the picture and fills, bars pushed off-screen', () => {
  const win = { w: 629, h: 206 }, frame = { w: 629, h: 206 }, content = { x: 210, y: 0, w: 419, h: 206 };
  const s = Math.min(win.w / content.w, win.h / content.h);   // = 1 (height-bound)
  const { r, cx, cy } = centre(win, frame, content, s);
  assert.equal(Math.round(cx), Math.round(win.w / 2));        // picture centred horizontally, not shoved right
  assert.equal(Math.round(cy), Math.round(win.h / 2));
  assert.ok(r.left < 0);                                      // the left band hangs off the left edge, off-screen
  assert.equal(Math.round(content.h * s), win.h);             // the picture fills the window height
});

test('symmetric bars give symmetric margins and a centred picture', () => {
  const win = { w: 800, h: 450 }, frame = { w: 640, h: 480 }, content = { x: 40, y: 60, w: 560, h: 360 };
  const s = Math.min(win.w / content.w, win.h / content.h);
  const { cx, cy } = centre(win, frame, content, s);
  assert.equal(Math.round(cx), win.w / 2);
  assert.equal(Math.round(cy), win.h / 2);
});

test('three agreeing letterbox measurements apply a crop; a black frame keeps it; bars gone resets it', async () => {
  const applied = [];
  const measurements = [];
  const ctl = F.create({ api: async () => measurements.shift(), current: () => 'w-1', window: () => ({ w: 880, h: 495 }), apply: r => applied.push(r) });
  const boxed = { w: 640, h: 480, content: { x: 0, y: 60, w: 640, h: 360 }, bars: { top: .125, bottom: .125, left: 0, right: 0 } };
  measurements.push(boxed, boxed);
  await ctl.poll(); await ctl.poll();
  assert.deepEqual(applied, [null]);                           // a new session resets; two samples are not enough
  measurements.push(boxed); await ctl.poll();
  assert.equal(applied.length, 2); assert.equal(Math.round(applied[1].height), 660);
  measurements.push({ w: 640, h: 480, content: null, bars: { top: 1, bottom: 1, left: 1, right: 1 } }); await ctl.poll();
  assert.equal(applied.length, 2);                             // black frame: nothing changes
  const full = { w: 640, h: 480, content: { x: 0, y: 0, w: 640, h: 480 }, bars: { top: 0, bottom: 0, left: 0, right: 0 } };
  measurements.push(full, full, full); await ctl.poll(); await ctl.poll(); await ctl.poll();
  assert.equal(applied[applied.length - 1], null);
});
