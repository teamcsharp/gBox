const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const continuity=require('../clients/web/viz/session-continuity');
const html=fs.readFileSync(require.resolve('../clients/desktop/index.html'),'utf8');

test('desktop game jobs target the active PiP and retain explicit-session priority',async()=>{
  const sent=[];
  const ctx=vm.createContext({COMPACT:{on:true,sid:'worker-current'},EMB:{sid:'worker-ended'},
    gbox:{api:async(path,body)=>{sent.push(body);return {state:'succeeded',output:{}};}},
    jobOf:r=>r,jobWait:async r=>r,chatContext:async()=>({})});
  const start=html.indexOf('async function gameJob(');
  vm.runInContext(html.slice(start,html.indexOf('function toast(',start)),ctx);
  await ctx.gameJob('autoplay',{op:'status'});
  await ctx.gameJob('autoplay',{op:'start',session_id:'explicit-session'});
  ctx.COMPACT.on=false;
  await ctx.gameJob('autoplay',{op:'status'});
  assert.deepEqual(sent.map(j=>j.input.session_id),['worker-current','explicit-session','worker-ended']);
});

test('F5 repairs the running replacement encoder and sends nothing to an ended or unrelated game',async()=>{
  const old={session_id:'old-worker',state:'ended',game_id:'re5',replaced_by:'new-session'};
  const next={session_id:'new-session',state:'running',game_id:'re5'};
  for(const rows of [[old,next],[old],[old,{...next,game_id:'re4'}]]){
    const jobs=[];
    const ctx=vm.createContext({COMPACT:{on:true,sid:old.session_id},EMB:{sid:old.session_id},GPU_GAME:{},
      GBoxSessionContinuity:continuity,document:{querySelectorAll:()=>[]},gpuGameDispose:async()=>{},
      setTimeout:()=>0,gbox:{api:async(path,body)=>{
        if(path.startsWith('/api/sessions?'))return {ok:true,data:rows};
        jobs.push(body);return {ok:true};
      }}});
    const start=html.indexOf('async function recoverStreams()');
    vm.runInContext(html.slice(start,html.indexOf('async function recoverAndRefresh()',start)),ctx);
    await ctx.recoverStreams();
    assert.deepEqual(jobs.map(j=>j.input.session_id),rows[1]===next?['new-session']:[]);
    assert.ok(jobs.every(j=>j.input.op==='restart_stream'));
  }
});
