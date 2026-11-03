// The live "task map" provider registry (clients/web/viz/live-maps.js): picks the right map renderer
// for a session by title/adapter, and lets new hooked titles register their own. Run:
//   node --test system/tests/test_live_maps.cjs
'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict');
const R=require('../clients/web/viz/live-maps.js');

test('classifies PSO as pso, RE/Mercs as mercs, and any other title as the generic fallback',()=>{
  assert.equal(R.classify({title:'Phantasy Star Online Episode I & II Plus (USA)'}),'pso');
  assert.equal(R.classify({game_id:'GPSE8P'}),'pso');            // GameCube PSO disc id
  assert.equal(R.classify({game_id:'GPOE8P'}),'pso');
  assert.equal(R.classify({title:'Resident Evil 5',game_id:'RE5'}),'mercs');
  assert.equal(R.classify({title:'Resident Evil 4 — Mercenaries'}),'mercs');
  assert.equal(R.classify({title:'Dead or Alive 2'}),'generic');  // no bespoke map -> generic view
  assert.equal(R.classify({}),'generic');
  assert.equal(R.isPso({title:'PSO Blue Burst'}),true);
  assert.equal(R.isMercs({title:'Resident Evil 6'}),true);
});

test('a newly registered title provider is tried before the fallback',()=>{
  const re4={id:'re4map',label:'RE4 map',match:s=>/resident evil 4/i.test(String(s.title||'')),
    html:()=>'',mount:()=>({stop(){}})};
  R.register(re4);
  try{
    assert.equal(R.classify({title:'Resident Evil 4'}),'re4map');  // more specific provider wins
    assert.equal(R.pick({title:'Resident Evil 4'}).id,'re4map');
    assert.equal(R.classify({title:'Resident Evil 5'}),'mercs');   // others still fall back
    assert.equal(R.pick({title:'Phantasy Star Online'}).id,'pso');
  }finally{
    R.list();                                                      // (registry is process-local to this test file)
  }
});
