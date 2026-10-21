// #2433: the Session agents panel rebuilds every 5 s; it must not close what the operator opened or is looking at.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const html = fs.readFileSync(path.join(__dirname, '../clients/web/index.html'), 'utf8');
function between(start, end) {
  const a = html.indexOf(start), b = html.indexOf(end, a + start.length);
  assert.ok(a >= 0 && b > a, `missing web shell source boundary: ${start}`);
  return html.slice(a, b);
}
const helper = between('function keepPanel(el, html)', 'function sessionObserverWatch(sid)');

test('the observers panel renders through keepPanel and its observations keep a key', () => {
  const watch = between('function sessionObserverWatch(sid)', 'async function wbInit()');
  assert.match(watch, /const panelHtml = `\$\{observerGoalsHtml\(r\)\}/);
  assert.match(watch, /if \(!keepPanel\(element, panelHtml\)\)/);
  assert.match(watch, /<details data-key="observations">/);
  assert.doesNotMatch(watch, /element\.innerHTML = `/, 'the panel must not be replaced wholesale on every tick');
});

const { findChrome, withPage } = require('../scripts/browser_lifecycle.cjs');

test('an unchanged or watched panel is left alone; a changed one keeps its open sections', { skip: !findChrome() && 'no Chromium installed' }, async () => {
  await withPage(async evaluate => {
    const out = await evaluate(`(() => {
      document.body.innerHTML = '<div id="session-observers" style="height:120px;overflow:auto"></div>';
      ${helper}
      const el = document.getElementById('session-observers');
      const page = v => '<p><b>Playing</b> v' + v + '</p><details data-key="observations"><summary>Recent observations</summary>' +
        Array.from({ length: 30 }, (_, i) => '<p>obs ' + i + ' v' + v + '</p>').join('') + '</details>';
      const out = {};
      out.first = keepPanel(el, page(1));
      out.unchanged = keepPanel(el, page(1));
      el.querySelector('details').open = true;
      el.scrollTop = 80; const before = el.scrollTop;
      el.dispatchEvent(new PointerEvent('pointerenter', { bubbles: false }));
      el.dispatchEvent(new PointerEvent('pointermove', { bubbles: true }));
      out.watchedDefers = keepPanel(el, page(2)) === false;
      out.stillOld = el.querySelector('b').nextSibling.textContent.trim() === 'v1';
      el._gboxReading.moved = Date.now() - 60000;
      out.changed = keepPanel(el, page(2));
      out.fresh = el.querySelector('b').nextSibling.textContent.trim() === 'v2';
      out.stillOpen = el.querySelector('details').open;
      out.scrollKept = el.scrollTop === before && before > 0;
      el.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
      out.heldDefers = keepPanel(el, page(3)) === false;
      document.dispatchEvent(new PointerEvent('pointerup', { bubbles: true }));
      el._gboxReading.moved = 0;
      out.afterRelease = keepPanel(el, page(3));
      return out;
    })()`);
    assert.equal(out.first, true);
    assert.equal(out.unchanged, false, 'identical markup is not replaced');
    assert.equal(out.watchedDefers, true, 'a panel the operator is looking at waits');
    assert.equal(out.stillOld, true);
    assert.equal(out.changed, true);
    assert.equal(out.fresh, true);
    assert.equal(out.stillOpen, true, 'Recent observations stays expanded across a refresh');
    assert.equal(out.scrollKept, true, 'the panel scroll survives a refresh');
    assert.equal(out.heldDefers, true);
    assert.equal(out.afterRelease, true);
  });
});
