const { test } = require('node:test');
const assert = require('node:assert/strict');
const createPopup = require('../clients/web/viz/process-popup.js');

// #1385: the pop-up animates each character's proportions adjusting from the writer's reported fit numbers
const popup = createPopup({ document: undefined, Math });

const FITTING = {
  order: ['fighter:KAS', 'fighter:BAY', 'fighter:TIN', 'fighter:GEN'], current: 'fighter:BAY', updated: 30,
  models: {
    'fighter:KAS': { label: 'Amy → Kasumi', state: 'done', current: 'write', updated: 20,
      stages: { scale: { state: 'done', data: { scale: 1.25, head_scale: 0.9 } },
        proportion: { state: 'done', data: { applied: true, height: 1.1, torso_width: 0.8 } } } },
    'fighter:BAY': { label: 'Tikal → Bayman', state: 'running', current: 'proportion', updated: 30,
      snapshot: '/api/jobs/j1/fitting/files/bay-retarget-5.glb',
      stages: { scale: { state: 'done', data: { donor_height: 100, fitted_height: 125, torso_up: 1.2, torso_down: 1.0 } },
        proportion: { state: 'skipped', data: { profile: 'none' } } } },
    'fighter:TIN': { label: 'Shadow → Tina', state: 'pending', stages: {} },
    'fighter:GEN': { label: 'Super Sonic → Gen Fu', state: 'done', updated: 10,
      stages: { scale: { state: 'done', data: { scale: 1.0 } } } },
  },
};
const job = (fitting = FITTING) => ({ id: 'j1', state: 'running', tool: 'characters', input: { op: 'use', slot: 'roster' }, fitting });

test('the current model calibrates from its scale-stage numbers (height ratio, torso stretch)', () => {
  const c = popup.calibration(job());
  assert.equal(c.key, 'fighter:BAY');
  assert.equal(c.factors.scale, 1.25);
  assert.ok(Math.abs(c.factors.height - 1.1) < 1e-9);
  assert.equal(c.factors.width, 1);
  assert.ok(Math.abs(c.from.y - 1 / (1.25 * 1.1)) < 1e-9);
  assert.ok(Math.abs(c.from.x - 0.8) < 1e-9);
  assert.equal(c.text, 'Calibrating Tikal → Bayman: size ×1.25 · height ×1.1');
});

test('proportion-stage height / torso width / head override the scale stage, clamped for display', () => {
  const c = popup.calibration(job({ ...FITTING, current: 'fighter:KAS' }));
  assert.deepEqual(c.factors, { scale: 1.25, height: 1.1, width: 0.8, head: 0.9 });
  assert.ok(Math.abs(c.from.x - 1) < 1e-9);        // 1 / (1.25 * 0.8)
  assert.ok(Math.abs(c.from.y - 1 / 1.375) < 1e-9);
  assert.equal(c.text, 'Calibrating Amy → Kasumi: size ×1.25 · height ×1.1 · width ×0.8 · head ×0.9');
  const big = popup.calibration(job({ order: ['a'], current: 'a', models: { a: { label: 'A', stages: { scale: { data: { scale: 5 } } } } } }));
  assert.equal(big.from.y, 0.55);
});

test('no animation for unchanged proportions, collection jobs or jobs without fitting', () => {
  assert.equal(popup.calibration(job({ ...FITTING, current: 'fighter:GEN' })), null);
  assert.equal(popup.calibration(job({ ...FITTING, kind: 'collect' })), null);
  assert.equal(popup.calibration({ state: 'running' }), null);
  assert.equal(popup.calibration(job({ ...FITTING, current: 'fighter:TIN' })), null);   // pending: nothing to calibrate
});

test('without a current model the most recently updated one plays', () => {
  const c = popup.calibration(job({ ...FITTING, current: null }));
  assert.equal(c.key, 'fighter:BAY');
});

test('the play-by-play phase holds donor proportions, eases to fitted, holds and repeats', () => {
  assert.equal(popup.calibrationPhase(0), 0);
  assert.equal(popup.calibrationPhase(0.49), 0);
  assert.ok(Math.abs(popup.calibrationPhase(1.2) - 0.5) < 1e-9);
  assert.equal(popup.calibrationPhase(2.0), 1);
  assert.equal(popup.calibrationPhase(2.8), 0);
  let prev = -1;
  for (let t = 0.5; t <= 1.9; t += 0.05) { const k = popup.calibrationPhase(t); assert.ok(k >= prev - 1e-12); prev = k; }
});
