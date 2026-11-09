const {test}=require('node:test');
const assert=require('node:assert/strict');
const N=require('../clients/web/viz/native-character-use.js');
const M=require('../clients/web/viz/mercmode.js');
const pick={gameId:N.GAME,character:'re5ps3_chris_normal',slot:'jill',sessionId:'worker-live'};
const scope={route:'native_archive_counterpart',requested_character:{name:'Chris'},
  donor_archive:'native/uPl00ChrisNormal.arc',target_archive:'native/uPl02JillNormal.arc',
  collection_model_used:false,gameplay_verified:false};
function rig({state='restarting',swapState='succeeded',session='worker-live',result={}}={}){
  const calls=[],progress=[];let polls=0;
  const api=async(path,body)=>{
    calls.push([path,body]);
    if(path.startsWith('/api/sessions?'))return [{session_id:session,state:'running',game_id:N.GAME}];
    if(path==='/api/jobs')return {id:'build',state:'assigned'};
    if(path==='/api/jobs/build')return {id:'build',state:'succeeded',output:{result:{status:state,mod:'native-build',
      replacement_scope:scope,...(state==='restarting'?{swap_job:'child'}:{}),...result}}};
    if(path==='/api/jobs/child')return ++polls===1?{id:'child',state:'running'}:
      {id:'child',state:swapState,error:swapState==='failed'?'load rejected':null,output:{session_id:'worker-new'}};
    throw Error(path);
  };
  const hooks={sleep:async()=>{},progress:text=>progress.push(text),currentSessionId:()=>pick.sessionId};
  return {api,calls,hooks,progress};
}

test('native counterpart target is explicit and the two supported donors are transparent',()=>{
  assert.throws(()=>N.input({...pick,slot:''}),/named target/);
  assert.throws(()=>N.input({...pick,slot:'player'}),/named target/);
  assert.throws(()=>N.input({...pick,character:'sonic'}),/original RE5/);
  const html=N.fields();
  assert.match(html,/<option value="">Choose the native player slot/);
  assert.doesNotMatch(html,/selected/);
  assert.match(html,/PS3 collection model is not imported/);
  assert.deepEqual(N.input(pick),{op:'live_use',game_id:N.GAME,character:pick.character,slot:'jill',session_id:pick.sessionId,launch:false});
});

test('live use waits for assigned build and child restart before reporting success',async()=>{
  const r=rig();const out=await N.apply(r.api,pick,r.hooks);
  assert.equal(r.calls.find(([p])=>p==='/api/jobs')[1].input.session_id,'worker-live');
  assert.equal(r.calls.filter(([p])=>p==='/api/jobs/child').length,2);
  assert.equal(out.session_id,'worker-new');
  assert.match(out.message,/collection GLB is not imported/);
  assert.match(out.message,/Visual verification is pending/);
  assert.match(out.message,/Restart completed in session worker-new/);
  assert.ok(r.progress.includes('Build written. Waiting for the title restart...'));
});

test('failed child preserves the built-mod distinction and never reports live success',async()=>{
  const r=rig({swapState:'failed'});
  await assert.rejects(N.apply(r.api,pick,r.hooks),/Build native-build was written, but the title restart failed: load rejected/);
});

test('stale displayed or ended session is rejected before submitting a writer',async()=>{
  let r=rig();r.hooks.currentSessionId=()=> 'worker-other';
  await assert.rejects(N.apply(r.api,pick,r.hooks),/displayed session changed/);
  assert.equal(r.calls.length,0);
  r=rig({session:'worker-other'});
  await assert.rejects(N.apply(r.api,pick,r.hooks),/no longer running/);
  assert.equal(r.calls.filter(([p])=>p==='/api/jobs').length,0);
});

test('unavailable writer and pending build do not imply a completed restart',async()=>{
  let r=rig({result:{status:'failed',reason:'Exact original source identity required'}});
  await assert.rejects(N.apply(r.api,pick,r.hooks),/Exact original source identity required/);
  assert.equal(r.calls.filter(([p])=>p==='/api/jobs/child').length,0);
  r=rig({state:'pending_restart'});
  const out=await N.apply(r.api,{...pick,sessionId:''},r.hooks);
  assert.match(out.message,/Saved pending restart/);
  assert.doesNotMatch(out.message,/Restart completed/);
  assert.equal(r.calls[0][1].input.op,'use');
  assert.equal(r.calls[0][1].input.launch,false);
});

test('MercMode library action uses its explicit target and exact current SID',async()=>{
  const events={},calls=[],messages=[],errors=[];
  const button={textContent:'Apply library counterpart and restart',addEventListener:(name,fn)=>events[name]=fn};
  const fields={'[data-native-use]':button,'[data-native-slot]':{value:'jill'},
    '[data-native-donor]':{value:'re5ps3_chris_normal'}};
  const root={querySelector:s=>fields[s]||null,querySelectorAll:()=>[]};
  const api=async(path,body)=>{
    calls.push([path,body]);
    if(path.includes('swap-matrix'))return {pairs:{}};
    if(path.startsWith('/api/sessions?'))return [{session_id:pick.sessionId,game_id:N.GAME,state:'running'}];
    if(path==='/api/jobs')return {state:'succeeded',output:{result:{status:'restarting',mod:'native-build',replacement_scope:scope,swap_job:'child'}}};
    return {state:'succeeded',output:{session_id:'worker-live'}};
  };
  M.wireSwaps(root,{api,title:'re5_switch',sessionId:pick.sessionId,currentSessionId:()=>pick.sessionId,
    done:text=>messages.push(text),fail:error=>errors.push(error.message)});
  await events.click({stopPropagation(){}});
  assert.deepEqual(errors,[]);
  assert.deepEqual(calls.find(([p])=>p==='/api/jobs')[1].input,N.input(pick));
  assert.match(messages[0],/Restart completed/);
  assert.equal(button.disabled,false);
  fields['[data-native-slot]'].value='';
  await events.click({stopPropagation(){}});
  assert.match(errors[0],/named target/);
  assert.equal(calls.filter(([p])=>p==='/api/jobs').length,1);
});
