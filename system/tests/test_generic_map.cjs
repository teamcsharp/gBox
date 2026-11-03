// The generic fallback map renderer (clients/web/viz/generic-map.js): pulls any world positions a
// title's telemetry exposes so an unmapped title still shows live motion. Run:
//   node --test system/tests/test_generic_map.cjs
'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict');
const G=require('../clients/web/viz/generic-map.js');

test('positions() reads steering-evidence player poses',()=>{
  const tel={stats:{steering_evidence_json:JSON.stringify({events:[{players:{
    '1':{after:{x:-10,z:-130,hp:40}},'2':{before:{x:10,z:-130,hp:38}}}}]})}};
  const by=Object.fromEntries(G.positions(tel).map(p=>[p.slot,p]));
  assert.equal(by[1].x,-10);assert.equal(by[1].z,-130);assert.equal(by[1].hp,40);
  assert.equal(by[2].x,10);assert.equal(by[2].hp,38);
});

test('positions() falls back to a positions array and is safe when empty',()=>{
  assert.deepEqual(G.positions({stats:{positions:[[1,2],{x:3,z:4,hp:9}]}}).map(p=>[p.x,p.z]),[[1,2],[3,4]]);
  assert.deepEqual(G.positions({}),[]);
  assert.deepEqual(G.positions({stats:{steering_evidence_json:'bad'}}),[]);
});

test('fit() frames the points and projects inside the canvas',()=>{
  const f=G.fit([{x:0,z:0},{x:100,z:100}],400,400);
  assert.ok(f);
  const [x,y]=G.project(f,50,50);
  assert.ok(x>0&&x<400&&y>0&&y<400,'a mid point lands inside the canvas');
  assert.equal(G.fit([],400,400),null);
});
