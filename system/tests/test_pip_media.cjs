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
test('F3 toggle asks the actual selected worker and telemetry alone controls the autobot label',async()=>{
 const calls=[];const c=P.create({current:()=> 'actual-game',api:async(url,body)=>{if(url.startsWith('/api/autoplay/'))return {running:false,age_s:0};calls.push(body);return {state:'succeeded',output:{result:body.input.op==='status'?{running:true}:{stopped:true}}};},save:async()=>{}});
 await c.toggleAutobot();assert.deepEqual(calls.map(v=>[v.tool,v.require_worker,v.input.session_id,v.input.op]),[['autoplay','actual','actual-game','status'],['autoplay','actual','actual-game','stop']]);assert.equal(c.state().autobot,false);
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
 assert.match(P.ICON,/<svg/);assert.match(P.CSS,/left:10px;bottom:8px;opacity:\.5/);assert.match(P.CSS,/body:hover \.pip-replay/);assert.match(P.CSS,/prefers-reduced-motion/);
 const main=fs.readFileSync(path.join(__dirname,'../clients/desktop/main.js'),'utf8');assert.match(main,/clip\.openFolder === true/);assert.match(main,/shell\.showItemInFolder\(saved\.file\)/);assert.match(main,/system-context-menu/);
});
