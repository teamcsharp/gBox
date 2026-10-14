const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../clients/desktop/background-display.js'),'utf8');
function app(){
  let now=0,removed=0,frames=[],events={},state={online:true,background_testing:true,sessions:[],worker:{os:'windows',idle_seconds:600}};
  const context={Date:{now:()=>now},URL,URLSearchParams,setTimeout:()=>1,clearTimeout:()=>{},
    addEventListener:(name,fn)=>events[name]=fn,
    document:{hidden:false,body:{append:frame=>frames.push(frame)},createElement:()=>({style:{},contentWindow:{},remove(){removed++;}})},
    gbox:{settings:async()=>({apiUrl:'http://test',workerName:'PC'}),api:async()=>({ok:true,data:state}),token:async()=>'fixture'}};
  vm.createContext(context);vm.runInContext(source,context);
  return {context,events,frames,state,get removed(){return removed;},advance:()=>now+=300001,poll:()=>context.GBoxBackgroundDisplay.poll()};
}
test('idle operations display yields to input without consuming it and never covers human gameplay',async()=>{
  const a=app();await a.poll();assert.equal(a.frames.length,0);
  a.advance();a.state.sessions=[{agent_owned:false}];await a.poll();assert.equal(a.frames.length,0);
  a.state.sessions=[];a.state.worker.idle_seconds=2;await a.poll();assert.equal(a.frames.length,0);
  a.state.worker.idle_seconds=600;await a.poll();assert.equal(a.frames.length,1);
  a.events.message({source:{},data:{gboxBackgroundClosed:true}});assert.equal(a.removed,0);
  a.events.message({source:a.frames[0].contentWindow,data:{gboxBackgroundInput:true}});assert.equal(a.removed,1);
  await a.poll();assert.equal(a.frames.length,1);
  a.advance();await a.poll();assert.equal(a.frames.length,2);
  a.events.pointerdown({preventDefault(){throw Error('Input was consumed');}});assert.equal(a.removed,2);
});
test('disconnect, gaming mode and disposal remove display without starting work',async()=>{
  const a=app();a.advance();await a.poll();a.state.online=false;await a.poll();assert.equal(a.removed,1);
  a.state.online=true;a.state.background_testing=false;await a.poll();assert.equal(a.frames.length,1);
  a.state.background_testing=true;await a.poll();assert.equal(a.frames.length,2);
  a.events.pagehide();assert.equal(a.removed,2);await a.poll();assert.equal(a.frames.length,2);
});
test('input during slow token retrieval prevents a late idle overlay',async()=>{
  const a=app();a.advance();let release,ready;
  const awaiting=new Promise(r=>ready=r);
  a.context.gbox.token=()=>{ready();return new Promise(r=>release=r);};
  const poll=a.poll();await awaiting;a.events.keydown({});release('fixture');await poll;
  assert.equal(a.frames.length,0);
});
test('an owned native test selects gameplay while persistent black evidence selects diagnostics',async()=>{
  const a=app();a.advance();let selected=[];
  a.context.GBoxBackgroundGameplay=async(s,current)=>{assert.equal(current(),true);selected.push(s.session_id);return true;};
  a.state.sessions=[{session_id:'w-test',agent_owned:true,local_window:true}];
  await a.poll();assert.deepEqual(selected,['w-test']);assert.equal(a.frames.length,0);
  a.state.sessions[0].presentation={persistent:true};await a.poll();
  assert.deepEqual(selected,['w-test']);assert.equal(a.frames.length,1);
});
