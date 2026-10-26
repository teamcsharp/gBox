// The Mercenaries clock control shared by the RE5 / RE4 modifier panels (operator 2026-10-26: a slider -30..+30 s,
// default -30 = subtract, with Apply; "Set clock to N s", 5 by default).
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const C = require('../clients/web/viz/mercs-clock.js');

test('the slider is -30..+30 whole seconds and never 0; the clock is set to 1..60', () => {
  assert.equal(C.delta(-30), -30); assert.equal(C.delta('7'), 7); assert.equal(C.delta(30), 30);
  for (const bad of [0, '0', 31, -31, 1.5, 'x', null, undefined, '']) assert.equal(C.delta(bad), null);
  assert.equal(C.setSeconds(5), 5); assert.equal(C.setSeconds('60'), 60); assert.equal(C.setSeconds(1), 1);
  for (const bad of [0, 61, 2.5, 'soon', null, '']) assert.equal(C.setSeconds(bad), null);
  assert.deepEqual(C.DELTA, { min: -30, max: 30, step: 1, default: -30 }); assert.deepEqual(C.SET, { min: 1, max: 60, default: 5 });
});

test('the control renders the operator defaults, the seconds left and the kept drafts; it never renders server markup', () => {
  const html = C.html({ status: { merc_seconds_left: 95.4 } });
  assert.match(html, /<fieldset class="mercs-clock" ><legend>Mercenaries clock<\/legend>/);
  assert.match(html, /data-clock-delta aria-label="[^"]*"\s+min="-30" max="30" step="1" value="-30" >/);
  assert.match(html, /data-clock-delta-out>−30 s</);
  assert.match(html, /data-clock-set aria-label="[^"]*" min="1" max="60" step="1" value="5" >/);
  assert.match(html, /data-clock-set-apply >Set clock to 5 s</);
  assert.match(html, /95 s left on the clock/);
  const kept = C.html({ delta: 12, set: 20, status: {} });
  assert.match(kept, /data-clock-delta-out>\+12 s</); assert.match(kept, /value="12"/);
  assert.match(kept, /Set clock to 20 s/); assert.match(kept, /no Mercenaries round is up/);
  assert.match(C.html({ disabled: true }), /<fieldset class="mercs-clock" disabled>/);
  assert.match(C.html({ disabled: true }), /data-clock-apply disabled>Apply/);
  const hostile = C.html({ reason: '<b>x</b>', status: { merc_seconds_left: 10 } });
  assert.doesNotMatch(hostile, /<b>/); assert.match(hostile, /&#60;b&#62;x/);
  assert.equal(C.left({ merc_seconds_left: 12.6 }), 13); assert.equal(C.left({ merc_seconds_left: null }), null); assert.equal(C.left(null), null);
});

test('describe words the verified clock_before / clock_after and the 1 s stop', () => {
  assert.equal(C.describe({ clock_before: 95.5, clock_after: 65.5 }), 'Clock 96 → 66 s.');
  assert.equal(C.describe({ clock_before: 40, clock_after: 1, clamped: true }), 'Clock 40 → 1 s (stopped at 1 s).');
  assert.equal(C.describe({ verified: true }), 'Clock changed.'); assert.equal(C.describe(null, 'none'), 'none');
});

test('input previews only relabel and hand back the draft; clicks route to the panel handlers', () => {
  const nodes = { '[data-clock-delta-out]': { textContent: '' }, '[data-clock-set-apply]': { textContent: '' },
    '[data-clock-delta]': { value: '-12' }, '[data-clock-set]': { value: '9' } };
  const host = { querySelector: s => nodes[s] || null };
  assert.deepEqual(C.onInput({ value: '-12', matches: s => s === '[data-clock-delta]' }, host), { delta: -12 });
  assert.equal(nodes['[data-clock-delta-out]'].textContent, '−12 s');
  assert.deepEqual(C.onInput({ value: '9', matches: s => s === '[data-clock-set]' }, host), { set: 9 });
  assert.equal(nodes['[data-clock-set-apply]'].textContent, 'Set clock to 9 s');
  assert.equal(C.onInput({ value: '3', matches: s => s === '[data-re5-range]' }, host), null);
  assert.equal(C.onInput(null, host), null);
  const calls = [];
  const handlers = { addTime: v => calls.push(['add', v]), setTime: v => calls.push(['set', v]) };
  const apply = { disabled: false }, set = { disabled: false }, off = { disabled: true };
  assert.equal(C.onClick({ closest: s => s === '[data-clock-apply]' ? apply : null }, host, handlers), true);
  assert.equal(C.onClick({ closest: s => s === '[data-clock-set-apply]' ? set : null }, host, handlers), true);
  assert.deepEqual(calls, [['add', '-12'], ['set', '9']]);
  assert.equal(C.onClick({ closest: s => s === '[data-clock-apply]' ? off : null }, host, handlers), true, 'a disabled button is still the clock\'s click');
  assert.equal(C.onClick({ closest: () => null }, host, handlers), false);
  assert.equal(calls.length, 2, 'disabled and unrelated clicks send nothing');
});

test('every shell loads the clock module before the panels that use it, and the module never touches RAM or tokens', () => {
  const desktop = fs.readFileSync(path.join(__dirname, '../clients/desktop/index.html'), 'utf8');
  const mini = fs.readFileSync(path.join(__dirname, '../clients/desktop/mini.html'), 'utf8');
  const web = fs.readFileSync(path.join(__dirname, '../clients/web/index.html'), 'utf8');
  assert.match(desktop, /<script src="\.\.\/web\/viz\/mercs-clock\.js"><\/script>\s*<script src="\.\.\/web\/viz\/re5-modifiers\.js"><\/script>/);
  assert.match(mini, /<script src="\.\.\/web\/viz\/mercs-clock\.js"><\/script>\s*<script src="\.\.\/web\/viz\/re5-modifiers\.js"><\/script>/);
  assert.match(web, /<script src="\/viz\/mercs-clock\.js"><\/script>\s*<script src="\/viz\/re5-modifiers\.js"><\/script>/);
  // the PiP right-click menu keeps its modifier panel (and so the clock) visible in compact mode: #pipmenu is exempt
  assert.match(desktop, /body\.gbox-compact > :not\(#gpu-game\)[^{]*:not\(#pipmenu\)/);
  const source = fs.readFileSync(require.resolve('../clients/web/viz/mercs-clock.js'), 'utf8');
  assert.doesNotMatch(source, /write_memory|read_memory|Bearer|x-gbox-actor|fetch\(/);
});
