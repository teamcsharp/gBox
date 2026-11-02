const assert=require('node:assert/strict');
const test=require('node:test');
const R=require('../clients/web/viz/pso-reviewer.js');
function frame(t,room=16,identity='layout-a'){
 return {verified:true,elapsed_s:t,episode:1,floor:1,players:{1:{ptr:'1',room,x:t,y:0,z:0,hp:33}},maps:[{player:1,identity}]};
}
test('paths do not join unrelated randomized room variants',()=>{
 const samples=[frame(0),frame(1),frame(2,17,'layout-b'),frame(3,17,'layout-b')];
 assert.deepEqual(R.pathSegments(samples,'1',samples[3]),[[[2,0],[3,0]]]);
});
test('paths split when a gap hides traversal or native player changes',()=>{
 const samples=[frame(0),frame(1),frame(20),frame(21)];samples[3].players[1].ptr='replacement';
 assert.deepEqual(R.pathSegments(samples,'1',samples[3]),[[[0,0],[1,0]],[[20,0]],[[21,0]]]);
});
test('metrics do not credit cross-floor teleport distance or damage',()=>{
 const a=frame(0),b=frame(1),c=frame(2);b.players[1].hp=30;c.floor=2;c.players[1].hp=1;c.players[1].x=1000;
 assert.deepEqual(R.metrics([a,b,c]),{samples:3,transitions:0,damage:3,distance:1});
});
test('empty enemies cannot produce completion in reviewer metrics',()=>{
 assert.equal(R.metrics([frame(0)]).completion,undefined);
});
test('layout or difficulty replacement does not add movement or HP loss',()=>{
 for(const changed of ['layout','difficulty']){
  const a=frame(0),b=frame(1);b.players[1].x=10000;b.players[1].hp=1;
  if(changed==='layout')b.maps[0].identity='different';else b.difficulty=2;
  assert.deepEqual(R.metrics([a,b]),{samples:2,transitions:0,damage:0,distance:0});
 }
});
