const {test} = require('node:test');
const assert = require('node:assert/strict');
const CS = require('../clients/web/viz/cast-swap.js');
const form = {source:'donors', slots:'all', mapping:'random', seed:'chosen-seed'};
const game = {gid:'target', title:'Original'};
function roster(native = false) {
  return {game:{game_id:'target',title:'Original'},source:{key:'donors',label:'Donor title'},requested_scope:'all',
    targets:[{id:'original-a',slot:'fighter:a',name:'Original A',slug:'original_a',buildable:true},
      {id:'original-b',slot:native?'fighter:b':null,name:'Original B',slug:'original_b',buildable:native}],
    donors:[{id:'sonic',slug:'sonic',name:'Sonic',source_game_id:'donors',ready:true},
      {id:'tails',slug:'tails',name:'Tails',source_game_id:'donors',ready:true}],
    capability:{status:native?'ready':'unsupported',combined_writer:native}};
}
const rows = [{target_id:'original-a',slot:'ignored-spoof',character:'sonic'},
  {target_id:'original-b',slot:'player',character:''}];
function setup(answer) {
  const calls=[], enabled={}, rendered={};
  const io={api:async(p,b)=>{calls.push([p,b]);return answer(p,b);},enable:(k,on)=>enabled[k]=on,
    render:(k,v)=>rendered[k]=v,status:()=>{},delay:async()=>{},uuid:()=> '00000000-0000-4000-8000-000000000001'};
  return {calls,enabled,rendered,c:CS.controller(io,game),io};
}

test('chart identities come from the roster, preserve blanks, and cannot invent writable slots',()=>{
  const r=roster(), reviewed=CS.chartRows(r,rows), snapshot=CS.chartSnapshot(r,reviewed);
  assert.deepEqual(reviewed,[{target_id:'original-a',slot:'fighter:a',character:'sonic'},
    {target_id:'original-b',slot:null,character:''}]);
  assert.equal(snapshot.connections.find(r=>r.target_id==='original-b').slot,null);
  assert.equal(snapshot.donors.length,1); assert.equal(snapshot.donors[0].slug,'sonic');
  assert.throws(()=>CS.chartRows(r,[{target_id:'invented',character:'sonic'}]),/different target roster/);
  assert.throws(()=>CS.chartRows(r,[{target_id:'original-a',character:'another-title'}]),/outside/);
  assert.throws(()=>CS.chartRows(r,[rows[0],rows[0]]),/one mapping row/);
});

test('native build needs the exact reviewed pairs, preserves native blanks, and edits invalidate review',async()=>{
  let alter=false;
  const x=setup((p,b)=>p.startsWith('/api/cast_swap/roster?')?roster(true):
    p==='/api/cast_swap/plan'?{status:'planned',assignments:alter?[{slot:'fighter:a',character:'tails'}]:b.assignments.filter(r=>r.character)}:
    p==='/api/jobs'?{id:'built',state:'succeeded',output:{result:{status:'built',mod:'mapped',message:'Built'}}}:null);
  await x.c.roster(form);x.c.updateChart(rows);await x.c.plan(form);
  assert.equal(x.enabled.build,true);await x.c.build({},{});
  assert.deepEqual(x.calls.find(([p])=>p==='/api/jobs')[1].input.assignments,
    [{slot:'fighter:a',character:'sonic'},{slot:'fighter:b',character:''}]);
  x.c.updateChart([{target_id:'original-a',character:'tails'}]);
  await assert.rejects(x.c.build({},{}),/plan first/);
  x.c.updateChart(rows);alter=true;await x.c.plan(form);
  assert.equal(x.enabled.build,false);assert.equal(x.c.state.requestAllowed,true);
  await assert.rejects(x.c.build({},{}),/Review the current native mapping/);
  await assert.rejects(x.c.plan({...form,slots:'main'}),/roster and scope/);
  await assert.rejects(x.c.request({...form,slots:'main'}),/roster and scope/);
});

test('different edits cannot silently share an in-flight saved request',async()=>{
  let finish;const posted=[];
  const x=setup((p,b)=>p.startsWith('/api/cast_swap/roster?')?roster():
    p==='/api/games/target/build-requests'?!b?new Promise(r=>{finish=r;}):
      (posted.push(b),{id:'saved',number:1,status:'open',kind:'build',mapping:b.mapping}):null);
  await x.c.roster(form);x.c.updateChart(rows);
  const first=x.c.request(form);assert.equal(first,x.c.request(form));
  x.c.updateChart([{target_id:'original-a',character:'tails'}]);
  assert.equal(x.enabled.request,false);
  await assert.rejects(x.c.request(form),/different mapping is still being saved/);
  finish({items:[]});await first;
  assert.equal(posted.length,1);
  assert.equal(posted[0].mapping.cast_chart.connections.find(r=>r.target_id==='original-a').character,'sonic');
  assert.equal(posted[0].mapping.cast_chart.connections.find(r=>r.target_id==='original-b').slot,null);
  assert.equal(posted[0].mapping.seed,'chosen-seed');
});

test('equivalent reviewed snapshots reuse their saved request while unrelated broad requests do not',async()=>{
  let saved,posts=0;
  const answer=(p,b)=>p.startsWith('/api/cast_swap/roster?')?roster():
    p==='/api/games/target/build-requests'?b?(posts++,saved={id:'saved',number:1,status:'open',kind:'build',mapping:b.mapping}):
      {items:[{id:'broad',status:'open',kind:'build',mapping:{source:'donors'}},...(saved?[saved]:[])]}:null;
  let x=setup(answer);await x.c.roster(form);x.c.updateChart(rows);await x.c.request(form);
  x=setup(answer);await x.c.roster(form);x.c.state.roster.targets.reverse();x.c.updateChart(rows);await x.c.request(form);
  assert.equal(posts,1);assert.equal(x.c.state.request.id,'saved');
});

test('a late or mismatched roster cannot replace a newer source or a disposed editor',async()=>{
  let finish;
  const x=setup(p=>p.includes('source=donors&')?new Promise(r=>{finish=r;}):({...roster(),source:{key:'other',label:'Other'}}));
  const first=x.c.roster(form);await x.c.roster({...form,source:'other'});finish(roster());
  assert.equal(await first,null);assert.equal(x.c.state.roster.source.key,'other');
  const pending=x.c.roster(form);x.c.dispose();finish(roster());assert.equal(await pending,null);
  const wrong=setup(()=>({...roster(),requested_scope:'enemies'}));
  await assert.rejects(wrong.c.roster(form),/different game or donor source/);
});
