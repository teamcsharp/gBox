// Other PC view (#1010): the other worker's gBox window is the default picture (Desktop expands to the full screen), the
// wheel zooms about the pointer, the middle button pans, double-click / Fit shows everything and 1:1 shows real pixels.
// The zoom maths are pure functions in the desktop shell; the wiring is checked as text.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const desktop = fs.readFileSync(path.join(__dirname, '../clients/desktop/index.html'), 'utf8');

function helpers() {
  const a = desktop.indexOf('// ---------------- Other PC (#1010)'), b = desktop.indexOf('const REMOTE = {', a);
  assert.ok(a > 0 && b > a, 'the Other PC helpers exist');
  const ctx = { Math }; vm.createContext(ctx);
  vm.runInContext(desktop.slice(a, b), ctx);
  return vm.runInContext('({ remoteZoomAt, remoteOneToOne, REMOTE_MAX_ZOOM })', ctx);
}
const plain = x => JSON.parse(JSON.stringify(x));
const under = (st, px, py) => [(px - st.panX) / st.zoom, (py - st.panY) / st.zoom];   // the picture point under a stage point

test('zooming keeps the remote pixel under the pointer still, in and out, and stays between fit and 8x', () => {
  const { remoteZoomAt, REMOTE_MAX_ZOOM } = helpers();
  assert.equal(REMOTE_MAX_ZOOM, 8);
  const fit = { zoom: 1, panX: 0, panY: 0 };
  const z1 = remoteZoomAt(fit, 1.2, 120, -40);
  assert.ok(Math.abs(z1.zoom - 1.2) < 1e-9);
  assert.deepEqual(under(z1, 120, -40).map(v => +v.toFixed(9)), under(fit, 120, -40), 'the point under the pointer is unchanged');
  const z2 = remoteZoomAt(z1, 1.2, -30, 55);
  assert.deepEqual(under(z2, -30, 55).map(v => +v.toFixed(9)), under(z1, -30, 55).map(v => +v.toFixed(9)));
  const back = remoteZoomAt(remoteZoomAt(z2, 1 / 1.2, -30, 55), 1 / 1.2, 120, -40);
  assert.deepEqual(plain(back), { zoom: 1, panX: 0, panY: 0 }, 'back at fit the pan is centred again');
  assert.deepEqual(plain(remoteZoomAt(fit, 0.5, 10, 10)), { zoom: 1, panX: 0, panY: 0 }, 'never smaller than fit');
  assert.equal(remoteZoomAt({ zoom: 7, panX: 0, panY: 0 }, 2, 0, 0).zoom, 8, 'capped at 8x');
});

test('1:1 is the zoom at which one remote pixel is one screen pixel for a contained frame', () => {
  const { remoteOneToOne } = helpers();
  assert.ok(Math.abs(remoteOneToOne(1920, 1080, 540, 360) - 1920 / 540) < 1e-9, 'the width is the tighter side');
  assert.ok(Math.abs(remoteOneToOne(1000, 1000, 540, 360) - 1000 / 360) < 1e-9, 'the height is the tighter side');
  assert.equal(remoteOneToOne(400, 300, 540, 360), 1, 'a small remote picture is already larger than real size at fit');
  assert.equal(remoteOneToOne(3840, 2160, 400, 300), 8, 'capped at 8x');
  assert.equal(remoteOneToOne(0, 0, 540, 360), 1, 'no frame yet'); assert.equal(remoteOneToOne(1920, 1080, 0, 0), 1);
});

test('the Other PC window opens on the gBox window, expands to the desktop, zooms at the pointer, pans with the middle button', () => {
  assert.match(desktop, /const REMOTE = \{[^\n]*\r?\n\s*view: "app", zoom: 1, panX: 0, panY: 0 \};/, 'app-only is the default view');
  assert.match(desktop, /if \(!workerId\) \{\r?\n\s*REMOTE\.view = "app";/, 'opening Other PC returns to the gBox window');
  assert.match(desktop, /REMOTE\.view = "app"; \$\("#rp-empty"\)\.hidden = true;/, 'closing resets it too');
  assert.match(desktop, /\$\("#rp-view"\)\.onclick = async \(\) => \{ REMOTE\.view = REMOTE\.view === "app" \? "desktop" : "app";/, 'Desktop / gBox switch');
  assert.match(desktop, /id="rp-view" title="Switch between the gBox window and the full desktop">Desktop<\/button>/);
  assert.match(desktop, /id="rp-fit" title="Fit the whole picture in the window">Fit<\/button><button class="act" id="rp-one" title="One remote pixel per screen pixel">1:1<\/button>/);
  assert.match(desktop, /Object\.assign\(REMOTE, remoteZoomAt\(REMOTE, e\.deltaY < 0 \? 1\.2 : 1 \/ 1\.2, e\.clientX - box\.left - box\.width \/ 2, e\.clientY - box\.top - box\.height \/ 2\)\);/);
  assert.match(desktop, /\$\("#rp-fit"\)\.onclick = remoteResetZoom;/);
  assert.match(desktop, /zoom: remoteOneToOne\(img\.naturalWidth, img\.naturalHeight, box\.width, box\.height\)/);
  assert.match(desktop, /\$\("#rp-stage"\)\.addEventListener\("pointerdown", e => \{\r?\n\s*if \(e\.button !== 1\) return;/, 'middle button pans');
  assert.match(desktop, /\$\("#rp-stage"\)\.addEventListener\("dblclick", remoteResetZoom\);/);
  assert.match(desktop, /desktop\/stream\?view=\$\{REMOTE\.view\}/, 'the server crops the stream to the reported gBox window');
  assert.match(desktop, /status\.data\?\.app_available === false/, 'and says when that window is not visible there');
});
