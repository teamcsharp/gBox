'use strict';
const {test} = require('node:test'), assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../clients/web/viz/character-model.js'), 'utf8').replace(/^import[^\n]*\n/gm, '').replace(/^export /gm, '');
const context = {}; vm.createContext(context);
vm.runInContext(source + ';this.paintHit=characterPaintHit;this.wireLines=characterUvLines;', context);
const plain = value => JSON.parse(JSON.stringify(value));
class UV { constructor(x, y) { this.x = x; this.y = y; } clone() { return new UV(this.x, this.y); } }
function attribute(points) { return {count: points.length, getX: index => points[index][0], getY: index => points[index][1]}; }
function material(channel = 0, name = 'Face') { return {name, uuid: name + '-' + channel, map: {channel, transformUv: uv => { uv.x += .05; uv.y = 1 - uv.y; }}}; }
function hit(mapMaterial, attributes) { return {object: {material: mapMaterial, geometry: {attributes}}, face: {materialIndex: 0}, uv: new UV(.1, .2), uv1: new UV(.7, .8)}; }

test('raycast painting uses the base-color material UV channel and transforms that UV without altering the intersection', () => {
  const attributes = {uv: attribute([[.1,.2]]), uv1: attribute([[.7,.8]])};
  const uv0 = hit(material(), attributes), uv1 = hit(material(1), attributes);
  assert.deepEqual(plain(context.paintHit(uv0)), {u: .15000000000000002, v: .8, material: 'Face', materialId: 'Face-0'});
  const result = context.paintHit(uv1);
  assert.equal(result.u, .75); assert.ok(Math.abs(result.v - .2) < 1e-12);
  assert.equal(result.materialId, 'Face-1');
  assert.deepEqual([uv1.uv.x, uv1.uv.y, uv1.uv1.x, uv1.uv1.y], [.1, .2, .7, .8]);
  uv1.object.material = [material(0, 'Other'), material(1, 'Head')]; uv1.face.materialIndex = 1;
  assert.equal(context.paintHit(uv1).materialId, 'Head-1', 'material-array group chooses its own base-color channel');
});

test('missing or unsupported raycast UV channels fail closed instead of falling back to UV0 or deprecated uv2', () => {
  const first = attribute([[.1,.2]]), second = attribute([[.7,.8]]);
  assert.equal(context.paintHit(hit(material(1), {uv: first})), null);
  const noIntersectionUv1 = hit(material(1), {uv: first, uv1: second}); delete noIntersectionUv1.uv1;
  assert.equal(context.paintHit(noIntersectionUv1), null);
  const alias = hit(material(2), {uv: first, uv1: second, uv2: second}); alias.uv2 = alias.uv1;
  assert.equal(context.paintHit(alias), null, 'r160 intersection.uv2 aliases UV1; it must never be treated as channel 2');
  assert.equal(context.paintHit(hit(material(-1), {uv: first})), null);
  const untextured = hit({name: 'No map'}, {uv: first}); assert.equal(context.paintHit(untextured), null);
  const invalid = hit(material(1), {uv1: second}); invalid.uv1.x = NaN; assert.equal(context.paintHit(invalid), null);
});

test('UV wire triangles follow each material channel for indexed and non-indexed groups and skip unavailable channels', () => {
  const uv0 = [[0,0],[.2,0],[0,.2],[.2,.2],[.4,.2],[.2,.4]], uv1 = [[.6,.6],[.9,.6],[.6,.9],[.5,.5],[.8,.5],[.5,.8]];
  const mesh = {isMesh: true, material: [material(0, 'Body'), material(1, 'Head')], geometry: {attributes: {position: {count:6}, uv: attribute(uv0), uv1: attribute(uv1)}, groups: [{start:0,count:3,materialIndex:0},{start:3,count:3,materialIndex:1}]}};
  const model = {traverse: fn => fn(mesh)};
  assert.deepEqual(plain(context.wireLines(model, 'Body')), [uv0.slice(0, 3)]);
  assert.deepEqual(plain(context.wireLines(model, 'Head')), [uv1.slice(3, 6)]);
  mesh.geometry.index = {count: 6, getX: index => [2,1,0,5,4,3][index]};
  assert.deepEqual(plain(context.wireLines(model, 'Head')), [[uv1[5],uv1[4],uv1[3]]]);
  delete mesh.geometry.attributes.uv1;
  assert.deepEqual(plain(context.wireLines(model, 'Head')), []);
  mesh.material[1].map.channel = 2; mesh.geometry.attributes.uv2 = attribute(uv1);
  assert.deepEqual(plain(context.wireLines(model, 'Head')), []);
});
