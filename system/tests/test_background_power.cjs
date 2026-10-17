const {test}=require('node:test'),assert=require('node:assert/strict');
const {create}=require('../clients/desktop/background-power');
function fixture(){
 let time=0,fail=false,calls=[],data={online:true,background_testing:true,worker:{os:'windows',idle_seconds:600},sessions:[]};
 const power=create({status:async()=>{if(fail)throw Error('offline');return data;},now:()=>time,schedule:()=>1,cancel:()=>{},
  powerSaveBlocker:{start:type=>{calls.push(['start',type]);return 0;},stop:id=>calls.push(['stop',id]),isStarted:id=>id===0}});
 return {power,data,calls,advance:n=>time+=n,fail:()=>fail=true};
}
test('idle delegated ready and working PCs keep the physical display awake, without changing global power settings',async()=>{
 const f=fixture();await f.power.poll();assert.equal(f.power.snapshot().active,true);
 assert.deepEqual(f.calls,[['start','prevent-display-sleep']]);
 f.data.active=[{state:'running'}];await f.power.poll();assert.equal(f.calls.length,1,'one persistent blocker');
 f.power.dispose();assert.deepEqual(f.calls.at(-1),['stop',0]);assert.equal(f.power.snapshot().active,false);
});
test('pause, human activity, unknown idle state and human gameplay release the blocker',async()=>{
 for(const change of [d=>d.background_testing=false,d=>d.worker.idle_seconds=0,d=>d.worker.idle_seconds=null,
   d=>d.sessions=[{agent_owned:false}],d=>d.online=false]){
  const f=fixture();await f.power.poll();change(f.data);await f.power.poll();assert.equal(f.power.snapshot().active,false);
  assert.deepEqual(f.calls.at(-1),['stop',0]);
 }
 const f=fixture();f.data.sessions=[{agent_owned:true,local_window:true}];await f.power.poll();assert.equal(f.power.snapshot().active,true);
});
test('an executing job or owned game keeps the display awake before the idle threshold',async()=>{
 for(const kind of ['job','game']){
  const f=fixture();f.data.worker.idle_seconds=0;
  if(kind==='job')f.data.active=[{state:'running'}];else f.data.sessions=[{agent_owned:true}];
  await f.power.poll();assert.equal(f.power.snapshot().active,true);
  f.power.dispose();
 }
});
test('temporary connection loss retains a lease; persistent loss releases it',async()=>{
 const f=fixture();await f.power.poll();f.fail();f.advance(10000);await f.power.poll();assert.equal(f.power.snapshot().active,true);
 f.advance(50000);await f.power.poll();assert.equal(f.power.snapshot().active,false);assert.match(f.power.snapshot().error,/offline/);
});
test('a delayed status response cannot acquire a blocker after shutdown',async()=>{
 let release;const calls=[];
 const f=create({status:()=>new Promise(r=>release=r),schedule:()=>1,cancel:()=>{},powerSaveBlocker:{start:()=>calls.push('start')}});
 const pending=f.poll();f.dispose();release({online:true,background_testing:true,worker:{os:'windows',idle_seconds:600},sessions:[]});
 await pending;assert.deepEqual(calls,[]);
});
