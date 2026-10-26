const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const P=require('../clients/desktop/pip-media.js');
function rig(){
 const r={sid:'worker-game',calls:[],saves:[],clock:0,telemetry:{running:true,age_s:1},clip:{audio:true,seconds:180,bytes:10,sha256:'a'.repeat(64),name:'replay.mp4'}};
 r.api=async(url,body)=>{r.calls.push({url,body});if(url.startsWith('/api/autoplay/'))return r.telemetry;
  if(body?.input.op==='status')return {state:'succeeded',output:{result:{status:{av_span_s:180}}}};
  return {state:'succeeded',output:{result:{clip:r.clip}}};};
 r.ctl=P.create({current:()=>r.sid,api:r.api,save:async clip=>{r.saves.push(clip);return {file:'configured/replay.mp4',folderOpened:true};},
  preferences:async()=>({targetMB:20}),delay:async ms=>{r.clock+=ms;},now:()=>r.clock});return r;
}
test('one click exports exactly last180 AV seconds through the existing scoped recording/artifact pipeline',async()=>{
 const r=rig();await r.ctl.exportLast();assert.equal(r.saves.length,1);assert.equal(r.saves[0].openFolder,true);
 assert.deepEqual(r.calls[1].body,{tool:'recording',agent_use:false,require_worker:'worker',input:{session_id:r.sid,op:'export',in_s:180,out_s:0,target_mb:20}});
 assert.match(r.ctl.state().message,/Replay saved.*Folder opened/);assert.equal(r.ctl.state().error,false);
});
test('partial history is disclosed, silent/unconfirmed clips are never published',async()=>{
 const short=rig();short.clip.seconds=42;await short.ctl.exportLast();assert.match(short.ctl.state().message,/42 seconds available/);
 for(const patch of [{audio:false},{audio:undefined},{seconds:600}]){const r=rig();Object.assign(r.clip,patch);await r.ctl.exportLast();assert.equal(r.saves.length,0);assert.equal(r.ctl.state().error,true);}
});
test('missing real emulator audio gives an actionable error and never exports or saves silent video',async()=>{
 const calls=[];const ctl=P.create({current:()=> 'worker-game',api:async(url,body)=>{calls.push(body);return {state:'succeeded',output:{result:{status:{av_span_s:0,audio_note:'Waiting for isolated emulator playback'}}}};},save:async()=>{throw Error('must not save');}});
 await ctl.exportLast();assert.equal(calls.length,1);assert.equal(calls[0].input.op,'status');assert.equal(ctl.state().error,true);assert.match(ctl.state().message,/isolated emulator playback/);
});
// F3 from any PC (operator 2026-10-26): one control-plane request for the shown game; the control plane asks that game's
// worker (gbox/bot_control.py), so a remote game works the same as a local one
function f3rig(answer){
 const calls=[];const api=async(url,body,method)=>{calls.push({url,body,method});
  if(url.startsWith('/api/autoplay/telemetry/'))return {running:true,age_s:0};
  if(url.endsWith('/autoplay'))return answer.post?answer.post(url,body):{id:'t1',state:'running'};
  if(url==='/api/jobs/t1')return answer.job;
  throw Error('unexpected '+url);};
 return {calls,c:P.create({current:()=> 'remote-game',api,save:async()=>{},delay:async()=>{},fade:()=>{}})};
}
test('F3 asks the control plane for the shown game and shows its answer',async()=>{
 const {calls,c}=f3rig({job:{id:'t1',state:'succeeded',output:{action:'started',running:true,
  message:'Autobot started on Resident Evil 5 (lilspark): playbook: mercs_bot.'}}});
 const out=await c.toggleAutobot();
 assert.deepEqual(calls[0],{url:'/api/sessions/remote-game/autoplay',body:{op:'toggle',source:'F3'},method:'POST'});
 assert.equal(calls[1].url,'/api/jobs/t1');
 assert.equal(out.ok,true);assert.equal(out.running,true);assert.match(out.message,/Autobot started on Resident Evil 5 \(lilspark\)/);
 assert.equal(c.state().message,out.message);assert.equal(c.state().error,false);assert.equal(c.state().autobot,true);
});
test('F3 failures carry the control plane\'s words, never raw HTTP',async()=>{
 const {c}=f3rig({post:()=>{throw Error('409 {"detail":"lilspark (running Resident Evil 5) is offline, so the autobot can\'t be reached there right now."}');}});
 const out=await c.toggleAutobot();
 assert.equal(out.ok,false);assert.match(out.message,/^lilspark \(running Resident Evil 5\) is offline/);
 assert.equal(c.state().error,true);
 const failed=f3rig({job:{id:'t1',state:'failed',error:'i9-NUC did not answer within 25 s (offline or busy). Nothing was changed.'}});
 assert.match((await failed.c.toggleAutobot()).message,/did not answer within 25 s/);
});
test('F3 pressed again while its request is on the way sends nothing more',async()=>{
 let finish;const calls=[];
 const c=P.create({current:()=> 'old-game',api:async(url,body)=>{calls.push(url);
  if(url.startsWith('/api/autoplay/'))return {running:false,age_s:0};
  return new Promise(r=>finish=r);},save:async()=>{},delay:async()=>{},fade:()=>{}});
 const pending=c.toggleAutobot();assert.equal(await c.toggleAutobot(),null);
 finish({id:'t1',state:'succeeded',output:{action:'stopped',running:false,message:'Autobot stopped: you have control.'}});
 assert.equal((await pending).message,'Autobot stopped: you have control.');
 assert.deepEqual(calls.filter(u=>u.endsWith('/autoplay')),['/api/sessions/old-game/autoplay']);
});
test('the shown game is the PiP stream, then the docked game, then what the gBox view shows',()=>{
 assert.equal(P.shownSession({compact:'w1-pip',docked:'w2-dock',guest:{session:'w3-view'}}),'w1-pip');
 assert.equal(P.shownSession({docked:'w2-dock',guest:{session:'w3-view'}}),'w2-dock');
 assert.equal(P.shownSession({docked:'w2-dock',guest:{tab:'Sessions',session:'nuc-remote'}}),'nuc-remote',
  'a remote game watched on its Sessions page beats a game docked on this PC');
 assert.equal(P.shownSession({guest:{session:'w3-view',pip:'w4-pip'}}),'w3-view');
 assert.equal(P.shownSession({guest:{session:null,pip:'w4-pip',playing:'w5-x'}}),'w4-pip');
 assert.equal(P.shownSession({guest:{playing:'w5-x'}}),'w5-x');
 assert.equal(P.shownSession({compact:'not a session',guest:{}}),null);
 assert.equal(P.shownSession(),null);
 assert.equal(P.readable(Error('500 {"detail":"boom"}')),'boom');assert.equal(P.readable(Error('plain words')),'plain words');
});
test('busy export coalesces clicks and reports worker job progress without optimistic success',async()=>{
 const r=rig();let finish;const api=r.api;
 r.ctl=P.create({current:()=>r.sid,api:async(url,body)=>body?.input.op==='export'?new Promise(resolve=>finish=resolve):api(url,body),save:async clip=>{r.saves.push(clip);return {file:'clip'};}});
 const pending=r.ctl.exportLast();await new Promise(resolve=>setImmediate(resolve));assert.equal(r.ctl.state().busy,true);
 await r.ctl.exportLast();assert.equal(r.saves.length,0);finish({state:'succeeded',output:{result:{clip:r.clip}}});await pending;assert.equal(r.saves.length,1);
});
test('autobot is shown only for fresh actual telemetry and resets across replacement/offline/stop',async()=>{
 const r=rig();await r.ctl.poll();assert.equal(r.ctl.state().autobot,true);
 r.telemetry={running:true,age_s:31};await r.ctl.poll();assert.equal(r.ctl.state().autobot,false);
 r.telemetry={running:false,age_s:0};await r.ctl.poll();assert.equal(r.ctl.state().autobot,false);
 r.sid='next-game';r.telemetry={running:true,age_s:1};await r.ctl.poll();assert.equal(r.ctl.state().sid,'next-game');assert.equal(r.ctl.state().autobot,true);
 r.sid=null;await r.ctl.poll();assert.equal(r.ctl.state().autobot,false);r.ctl.stop();await r.ctl.exportLast();assert.equal(r.saves.length,0);
});
test('late telemetry from an old stream cannot mark the replacement as an autobot',async()=>{
 let sid='old-game',finish;const c=P.create({current:()=>sid,api:()=>new Promise(resolve=>finish=resolve),save:async()=>{}});
 const request=c.poll();sid='new-game';await c.poll();finish({running:true,age_s:0});await request;assert.equal(c.state().autobot,false);assert.equal(c.state().sid,'new-game');
});
test('PiP media is available in both shells, hover export uses SVG and gentle half-opacity autobot text',()=>{
 for(const name of ['index.html','mini.html']){const src=fs.readFileSync(path.join(__dirname,'../clients/desktop',name),'utf8');assert.match(src,/<script src="pip-media.js"><\/script>/);assert.match(src,/GBoxPipMedia\.mount/);assert.match(src,/recSaveClip\(clip\)/);}
 assert.match(P.ICON,/<svg/);assert.match(P.CSS,/left:10px;bottom:8px;opacity:\.5/);assert.match(P.CSS,/\.pip-corner:hover \.pip-replay/);assert.doesNotMatch(P.CSS,/body:hover \.pip-replay|data-busy=true\] \.pip-replay/);assert.match(P.CSS,/prefers-reduced-motion/);
 const main=fs.readFileSync(path.join(__dirname,'../clients/desktop/main.js'),'utf8');assert.match(main,/clip\.openFolder === true/);assert.match(main,/shell\.showItemInFolder\(saved\.file\)/);assert.match(main,/system-context-menu/);
});

test('a status read that never answers ends the attempt instead of showing Preparing forever',async()=>{
 let clock=0;const calls=[];const c=P.create({current:()=> 'worker-game',api:async(url,body)=>{if(body)calls.push(body);return {id:'j',state:'queued'};},
  save:async()=>{throw Error('must not save');},delay:async ms=>{clock+=ms;},now:()=>clock});
 await c.exportLast();assert.equal(c.state().busy,false);assert.equal(c.state().error,true);
 assert.match(c.state().message,/did not answer; no replay was started/);assert.ok(clock<=P.ARM_MS+31000+12000);
 assert.equal(calls.length,1);assert.equal(calls[0].input.op,'status');
});
test('the mounted icon lives in a corner zone and exports only once armed by hovering it',async()=>{
 const src=fs.readFileSync(path.join(__dirname,'../clients/desktop/pip-media.js'),'utf8');
 assert.match(src,/class="pip-corner"><button class="pip-replay"/);assert.match(src,/dataset\.armed==='true'\|\|event\.detail===0/);
});
