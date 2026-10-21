// #2799: Models image previews (sprite sheets, tile atlases) zoom around the cursor with the wheel and pan by dragging.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { zoomAt, fit, MIN, MAX } = require('../clients/web/viz/image-pan-zoom.js');

test('zooming keeps the image point under the cursor fixed', () => {
  const view = { scale: 2, x: 10, y: 20 }, px = 110, py = 70;
  const before = { x: (px - view.x) / view.scale, y: (py - view.y) / view.scale };
  const next = zoomAt(view, 3, px, py);
  assert.equal(next.scale, 6);
  assert.deepEqual({ x: (px - next.x) / next.scale, y: (py - next.y) / next.scale }, before);
});

test('zoom is clamped and fit centres the whole image', () => {
  assert.equal(zoomAt({ scale: 1, x: 0, y: 0 }, 1e6, 0, 0).scale, MAX);
  assert.equal(zoomAt({ scale: 1, x: 0, y: 0 }, 1e-6, 0, 0).scale, MIN);
  assert.deepEqual(fit(800, 400, 1024, 512), { scale: 0.78125, x: 0, y: 0 });
  assert.deepEqual(fit(800, 600, 100, 100), { scale: 6, x: 100, y: 0 });
});

test('the Models tab mounts image previews in the pan-zoom viewer', () => {
  const html = fs.readFileSync(path.join(__dirname, '..', 'clients', 'web', 'index.html'), 'utf8');
  assert.ok(html.includes('<script src="/viz/image-pan-zoom.js"></script>'));
  assert.ok(html.includes('GBoxImagePanZoom.mount(preview, `${model.preview_url}?${tq()}`, model.name)'));
});
