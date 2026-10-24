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
