'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), { spawnSync } = require('node:child_process');
const { renderSVG } = require('../clients/web/viz/tactical-map.js');
const fixture = path.join(__dirname, 'fixtures/tactical_map');
function input() {
  const frame = JSON.parse(fs.readFileSync(path.join(fixture, 'BLUS30491-public-assembly.frames.jsonl'), 'utf8').split('\n')[0]);
  frame.seq = 7;
  const stage = JSON.parse(fs.readFileSync(path.join(fixture, 'BLUS30491-public-assembly.stage.json'), 'utf8'));
  return { frame, stage, width: 960, height: 720 };
}
test('report renders actual observed map geometry, enemy health and route using the existing renderer', () => {
  const value = input();
  value.frame.enemies[0].visibility = 'blocked';
  const svg = renderSVG(value);
  assert.match(svg, /<svg[^>]+width="960"/);
  assert.match(svg, /Report moment/);
  assert.match(svg, /100 HP/);
  assert.match(svg, /Cover measured/);
  assert.ok(svg.includes('stroke-width="1.5"'), 'observed mesh boundaries are drawn');
  assert.match(svg, /solid/i);
  assert.ok(Buffer.byteLength(svg) < 4 * 1024 * 1024);
  assert.doesNotMatch(svg, /NaN|Infinity|<script|href=/);
});

test('known crossing indices use the same dashed geometry as the live map', () => {
  const value = input();
  value.stage = { key: value.frame.stage, units: value.frame.units, kind: 'mesh', tris: [],
    points: [-1300, 200, -3750, -1200, 200, -3750], cross: [0, 1] };
  assert.ok(renderSVG(value).includes('stroke-dasharray="4 3"'), 'crossings are dashed');
});
test('missing stage is explicitly labelled and unverified entities are not invented', () => {
  const value = input(); value.stage = null;
  const svg = renderSVG(value);
  assert.match(svg, /Stage geometry unavailable/);
  assert.match(svg, /Shot path untested/);
  assert.doesNotMatch(svg, /window|door|grenade|mine/i);
});
test('text is escaped and no executable SVG markup is inserted', () => {
  const value = input(); value.frame.title = '<script>alert("x")</script>';
  value.frame.enemies[0].id = '<image href="https://invalid.example"/>';
  const svg = renderSVG(value);
  assert.doesNotMatch(svg, /<script|<image|onload=/);
  assert.match(svg, /&#60;script&#62;/);
});
test('mismatched geometry and invalid actors are rejected', () => {
  const wrong = input(); wrong.stage.key = 'another-stage';
  assert.throws(() => renderSVG(wrong), /mismatched/);
  const bad = input(); bad.frame.enemies[0].pos[0] = NaN;
  assert.throws(() => renderSVG(bad), /actors/);
  const indices = input(); indices.stage.tris[0] = 999999;
  assert.throws(() => renderSVG(indices), /indices/);
  const units = input(); units.frame.units = 'unknown';
  assert.throws(() => renderSVG(units), /Invalid tactical/);
});

test('wide reports retain a square 40m map extent around the player', () => {
  const value = { ...input(), width: 1920, height: 480 };
  const svg = renderSVG(value);
  assert.ok(svg.includes('<clipPath id="map"><rect width="380" height="380"/>'));
  assert.ok(svg.includes('transform="translate(620 80)"'));
});
test('CLI returns only SVG and fails closed on invalid JSON or too much input', () => {
  const cli = path.join(__dirname, '../scripts/render_tactical_map.cjs');
  const good = spawnSync(process.execPath, [cli], { input: JSON.stringify(input()), encoding: 'utf8', maxBuffer: 5 * 1024 * 1024 });
  assert.equal(good.status, 0, good.stderr);
  assert.ok(good.stdout.startsWith('<svg') && good.stdout.endsWith('</svg>'));
  for (const data of ['invalid JSON', ' '.repeat(5 * 1024 * 1024 + 1)]) {
    const result = spawnSync(process.execPath, [cli], { input: data, encoding: 'utf8', maxBuffer: 5 * 1024 * 1024 });
    assert.notEqual(result.status, 0);
    assert.equal(result.stdout, '');
  }
});
