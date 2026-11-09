const {test}=require('node:test');
const assert=require('node:assert/strict');
const N=require('../clients/web/viz/native-character-use.js');
const M=require('../clients/web/viz/mercmode.js');
const pick={gameId:N.GAME,character:'re5ps3_sheva_normal',slot:'chris',sessionId:'worker-live'};
const scope={route:'native_archive_counterpart',requested_character:{name:'Sheva'},
  donor_archive:'native/uPl01ShebaNormal.arc',target_archive:'native/uPl00ChrisNormal.arc',
  collection_model_used:false,gameplay_verified:true,
  gameplay_acceptance:{coverage:'Visible Sheva and advancing combat in Chris (BSAA); other costumes remain unverified.'}};
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

test('native counterpart offers only the verified Sheva to explicit Chris BSAA pair',()=>{
  assert.throws(()=>N.input({...pick,slot:''}),/named target/);
  assert.throws(()=>N.input({...pick,slot:'player'}),/named target/);
  assert.throws(()=>N.input({...pick,character:'sonic'}),/original RE5/);
  assert.throws(()=>N.input({...pick,character:'re5ps3_chris_normal'}),/Choose original Sheva and target Chris/);
  assert.throws(()=>N.input({...pick,slot:'jill'}),/other native player pairs/);
  const html=N.fields();
  assert.match(html,/<option value="">Choose the native player slot/);
  assert.doesNotMatch(html,/selected/);
  assert.match(html,/PS3 collection model is not imported/);
  assert.doesNotMatch(html,/value="(?:sheva|jill|wesker|re5ps3_chris_normal)"/);
  assert.match(html,/value="chris">Chris \(BSAA\)/);
  assert.deepEqual(N.input(pick),{op:'live_use',game_id:N.GAME,character:pick.character,slot:'chris',session_id:pick.sessionId,launch:false});
});

test('live use waits for assigned build and child restart before reporting success',async()=>{
  const r=rig();const out=await N.apply(r.api,pick,r.hooks);
  assert.equal(r.calls.find(([p])=>p==='/api/jobs')[1].input.session_id,'worker-live');
  assert.equal(r.calls.filter(([p])=>p==='/api/jobs/child').length,2);
  assert.equal(out.session_id,'worker-new');
  assert.match(out.message,/collection GLB is not imported/);
  assert.match(out.message,/Previously verified in gameplay: Visible Sheva and advancing combat/);
  assert.match(out.message,/other costumes remain unverified/);
  assert.doesNotMatch(out.message,/verification is pending/);
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
  const fields={'[data-native-use]':button,'[data-native-slot]':{value:'chris'},
    '[data-native-donor]':{value:'re5ps3_sheva_normal'}};
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

test('receipt verification text follows the actual flag and coverage',()=>{
  const pending=N.scopeText({...scope,gameplay_verified:false});
  assert.match(pending,/Gameplay verification is pending/);
  assert.doesNotMatch(pending,/Previously verified/);
  assert.throws(()=>N.scopeText({route:'other'}),/receipt/);
});

test('original Chris library card explains the blocked reverse pair without submitting a job',async()=>{
  const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
  const source=fs.readFileSync(path.join(__dirname,'../clients/web/index.html'),'utf8');
  const script=source.slice(source.indexOf('async function charsInit()'),source.indexOf('\nasync function charExtractPanel()'));
  const calls=[],status={textContent:''},box={dataset:{i:'0',slug:'re5ps3_chris_normal'},querySelector:()=>status};
  const button={closest:()=>box},el={dataset:{gid:N.GAME,sid:'worker-live'},querySelectorAll:()=>[]};
  const context=vm.createContext({GBoxNativeCharacterUse:N,$:()=>el,esc:String,tq:()=>'',charOvlWatch(){},
    localStorage:{getItem:()=>null,setItem(){}},api:async path=>{calls.push(path);return [{slug:'re5ps3_chris_normal',name:'Chris',preview_url:'/preview'}];}});
  vm.runInContext(script,context);await context.charsInit();
  assert.match(el.innerHTML,/Replacement unavailable/);
  assert.match(el.innerHTML,/Choose original Sheva and target Chris/);
  await el.onclick({target:{closest:selector=>selector==='button[data-use]'?button:null}});
  assert.match(status.textContent,/Choose original Sheva and target Chris/);
  assert.equal(calls.length,1);
});
