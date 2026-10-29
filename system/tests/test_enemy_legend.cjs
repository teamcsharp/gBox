// The live map's enemy types: a colour per type and the legend with portraits (operator 2026-10-29).
const assert = require('node:assert/strict');
const { test } = require('node:test');
const T = require('../clients/web/viz/tactical-map.js');

test('each enemy type keeps one colour and the legend lists portraits, names, counts and threat', () => {
  assert.equal(T.kindColor('uEm10'), T.kindColor('uEm10'));
  assert.equal(T.kindColor(null), null);
  const f = { title: '010018100CD46000', kinds: { uEm23: { name: 'uEm23', count: 1, threat: 'high' },
                                                   uEm10: { name: 'Majini', count: 4, threat: 'low' } } };
  const h = T.kindsHtml(f, (title, cls) => `/api/mercs/portraits/${title}/${cls}.jpg?token=x`);
  assert.ok(h.indexOf('Majini ×4') < h.indexOf('uEm23 ×1'), 'the most numerous first');
  assert.match(h, /<img alt="" src="\/api\/mercs\/portraits\/010018100CD46000\/uEm10\.jpg\?token=x" data-face="MA">/);
  assert.match(h, /high threat/);
  assert.match(T.kindsHtml(f, null), /<span class="tm-face" aria-hidden="true">MA<\/span>/, 'no portrait source: initials');
  assert.equal(T.kindsHtml({}, null), '');
});

test('enemy marks carry the type, its colour and its name in the tooltip', () => {
  const v = T.viewOf({ cx: 0, cz: 0, radius: 2000, heading: 0 }, { w: 400, h: 300 });
  const f = { units: 'cm', player: { pos: [0, 0, 0] },
              enemies: [{ id: 3, pos: [100, 0, 100], hp: 700, hp_max: 700, cls: 'uEm10', kind: 'Majini', threat: 'low' }] };
  const m = T.marks(f, v).find(x => x.kind === 'enemy');
  assert.equal(m.cls, 'uEm10'); assert.equal(m.color, T.kindColor('uEm10'));
  assert.match(m.tip, /^Majini 3 · low threat · 700\/700 health/);
});
