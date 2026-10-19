// #2395: a Requests refresh must never reset the view while the operator is looking at or scrolling through it,
// and when it does refresh it keeps the scroll of the real scrolling pane and every expanded section.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const source = fs.readFileSync(path.join(__dirname, '../clients/desktop/inbox-view.js'), 'utf8');
const html = fs.readFileSync(path.join(__dirname, '../clients/desktop/index.html'), 'utf8');

test('the Requests view renders through updateInboxView and the helper defers while reading', () => {
  assert.match(html, /updateInboxView\(host, JSON\.stringify\(\[requestFilter, INBOX_PAGE\.limit/);
  assert.match(source, /window\.inboxReading\(host\)\) return false/);
  assert.match(source, /scroller\.scrollTop = scroll\.top/);
});

const { findChrome, withPage } = require('../scripts/browser_lifecycle.cjs');

test('a refresh waits for the reader and keeps the pane scroll and expanded details', { skip: !findChrome() && 'no Chromium installed' }, async () => {
  await withPage(async evaluate => {
    const out = await evaluate(`(() => {
      document.body.innerHTML = '<div id="pane" style="height:200px;overflow:auto"><div id="reqlist"></div></div>';
      ${source}
      const pane = document.getElementById('pane'), host = document.getElementById('reqlist');
      const page = v => Array.from({ length: 12 }, (_, i) =>
        '<div class="req" data-id="r' + i + '" style="height:120px"><b>#' + i + ' v' + v + '</b>' +
        '<details><summary>Token usage</summary><p>tokens ' + v + '</p></details>' +
        '<div class="thread"><input class="reply"></div></div>').join('');
      const out = {};
      out.first = updateInboxView(host, 'k1', () => page(1));
      pane.scrollTop = 400;
      host.querySelector('[data-id="r3"] details').open = true;
      host.querySelector('[data-id="r3"] .reply').value = 'draft text';
      out.same = updateInboxView(host, 'k1', () => page(1));
      // the operator is looking at the list: pointer over it, moved a moment ago
      host.dispatchEvent(new PointerEvent('pointerenter', { bubbles: false }));
      host.dispatchEvent(new PointerEvent('pointermove', { bubbles: true }));
      out.readingDefers = updateInboxView(host, 'k2', () => page(2)) === false;
      out.stillOld = host.querySelector('b').textContent === '#0 v1';
      // the pointer rests for a long time: a refresh may happen again, keeping the place
      host._gboxReading.moved = Date.now() - 60000;
      const before = pane.scrollTop;                // scroll anchoring moved it when the details opened
      out.rested = updateInboxView(host, 'k2', () => page(2));
      out.paneKept = pane.scrollTop === before && before >= 400;
      out.detailOpen = host.querySelector('[data-id="r3"] details').open;
      out.otherClosed = host.querySelector('[data-id="r4"] details').open;
      out.draft = host.querySelector('[data-id="r3"] .reply').value;
      out.fresh = host.querySelector('b').textContent === '#0 v2';
      // scrolling the pane just now defers; a held button defers until it is released
      pane.dispatchEvent(new Event('scroll'));
      out.scrollDefers = updateInboxView(host, 'k3', () => page(3)) === false;
      host._gboxReading.scrolled = 0;
      host.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
      out.downDefers = updateInboxView(host, 'k3', () => page(3)) === false;
      document.dispatchEvent(new PointerEvent('pointerup', { bubbles: true }));
      host._gboxReading.moved = 0; host.dispatchEvent(new PointerEvent('pointerleave', { bubbles: false }));
      const before3 = pane.scrollTop;
      out.afterRelease = updateInboxView(host, 'k3', () => page(3));
      out.finalKept = pane.scrollTop === before3;
      return out;
    })()`);
    assert.equal(out.first, true);
    assert.equal(out.same, false, 'an unchanged refresh must not re-render');
    assert.equal(out.readingDefers, true, 'a refresh waits while the operator is looking at the list');
    assert.equal(out.stillOld, true);
    assert.equal(out.rested, true);
    assert.equal(out.paneKept, true, 'the scrolling pane stays where the reader scrolled');
    assert.equal(out.detailOpen, true, 'an expanded section stays expanded');
    assert.equal(out.otherClosed, false);
    assert.equal(out.draft, 'draft text', 'a reply draft survives');
    assert.equal(out.fresh, true, 'the refresh really replaced the markup');
    assert.equal(out.scrollDefers, true, 'a refresh waits right after a scroll');
    assert.equal(out.downDefers, true, 'a refresh waits while a button is held');
    assert.equal(out.afterRelease, true);
    assert.equal(out.finalKept, true);
  });
});
