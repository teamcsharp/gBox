const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const factory=require('../clients/web/viz/process-popup.js'),P=factory({});
const {withPage}=require('../scripts/browser_lifecycle.cjs');
const worker={id:'local',name:'i9-NUC'};
const re={id:'re',worker_id:'local',state:'running',tool:'re_agent',agent_use:true,input:{op:'reverse'},progress:{pct:1,msg:'Checking reconstructed function',ts:100},progress_log:Array.from({length:45},(_,n)=>`Inspecting function ${n}: return value + ${n};`)};
const fit={id:'mesh',worker_id:'local',state:'running',agent_use:true,tool:'characters',input:{op:'cast_swap'},fitting:{order:['old','sonic'],current:'sonic',models:{old:{snapshot:'/api/jobs/mesh/fitting/files/old.glb'},sonic:{label:'Sonic → native fighter',donor:'sonic',state:'running',current:'retarget',snapshot:'/api/jobs/mesh/fitting/files/sonic.glb',stages:{scale:{state:'done',data:{donor_height:120,fitted_height:100}},retarget:{state:'running',data:{roles:15,vertices:1800}}}}}},progress:{pct:42,msg:'Retargeting Sonic onto native fighter',ts:101}};
test('local activity includes actual RE/service jobs, excludes idle polls and remote or unassigned work',()=>{
 assert.equal(P.activityJob(re),true);assert.equal(P.classify(re),false);
 assert.equal(P.activityJob({...re,input:{op:'status'}}),false);
 assert.equal(P.onWorker(re,worker),true);assert.equal(P.onWorker({...re,worker_id:'remote'},worker),false);
 assert.equal(P.onWorker({...re,state:'queued',require_worker:null},worker),false);
 assert.equal(P.onWorker({...re,state:'queued',require_worker:'i9-NUC'},worker),true);
 assert.equal(P.onWorker(re,null),false);
});
test('current donor never displays a different character snapshot; details escape code and expose measurements',()=>{
 assert.match(P.activityModelPath(fit),/sonic.glb$/);
 const pending=JSON.parse(JSON.stringify(fit));delete pending.fitting.models.sonic.snapshot;
 assert.equal(P.activityModelPath(pending),'/api/characters/sonic/model');
 assert.match(P.detailHTML(fit,150),/49s ago/);assert.match(P.detailHTML(fit),/vertices/);
 const html=P.detailHTML({...re,admission_wait:{reason:'<script>bad</script>'}});
 assert.doesNotMatch(html,/<script>/);assert.match(html,/Verification pending/);
});
test('browser: local job selection, scrollable console, pause/resume, actual fit detail, and no fake model for RE',async()=>{
 await withPage(async(evaluate,send)=>{
  await send('Emulation.setDeviceMetricsOverride',{width:1350,height:1000,deviceScaleFactor:1,mobile:false});
  await evaluate(fs.readFileSync(path.join(__dirname,'../clients/web/viz/process-popup.js'),'utf8'));
  await evaluate(`document.body.style='background:#080e1a;color:white;font:16px system-ui';document.body.innerHTML='<h2>i9-NUC · Background automation</h2><p>Synthetic UI fixture using worker progress and fitting records.</p>';var worker=${JSON.stringify(worker)},re=${JSON.stringify(re)},fit=${JSON.stringify(fit)};var now=Date.now();re.progress.ts=now/1000;fit.progress.ts=now/1000;
   var ctl=GBoxProcessPopup.mount({activity:true,worker:()=>worker,now:()=>now});ctl.sync([re,{...re,id:'other',worker_id:'remote'}]);`);
  assert.equal(await evaluate(`document.querySelectorAll('[aria-label="Operation to inspect"] option').length`),1);
  assert.equal(await evaluate(`document.querySelector('.pp-stage').style.display`),'none');
  assert.match(await evaluate(`document.querySelector('.pp-log').textContent`),/function 0/);
  assert.equal(await evaluate(`document.querySelector('.pp-log').scrollHeight>document.querySelector('.pp-log').clientHeight`),true);
  await evaluate(`document.querySelector('.pp-controls button:last-child').click();re.progress_log.push('PAUSED NEW LINE');ctl.sync([re]);`);
  assert.doesNotMatch(await evaluate(`document.querySelector('.pp-log').textContent`),/PAUSED NEW LINE/);
  await evaluate(`document.querySelector('.pp-controls button:last-child').click()`);
  assert.match(await evaluate(`document.querySelector('.pp-log').textContent`),/PAUSED NEW LINE/);
  await evaluate(`ctl.sync([re,fit]);var select=document.querySelector('.pp-controls select');select.value='mesh';select.dispatchEvent(new Event('change'));document.querySelector('.pp-controls button').click();`);
  assert.match(await evaluate(`document.querySelector('.pp-detail').textContent`),/1800/);
  assert.equal(await evaluate(`document.querySelector('.gbox-pp').classList.contains('pp-expanded')`),true);
  assert.equal(await evaluate(`document.querySelector('.pp-cal').textContent`),'');
  // Offline renderer fallback is explicit instead of pretending the generic globe is the fitted mesh.
  await new Promise(r=>setTimeout(r,50));
  assert.match(await evaluate(`document.querySelector('.pp-f').textContent`),/renderer unavailable/);
  if(process.env.GBOX_ACTIVITY_EVIDENCE){const shot=await send('Page.captureScreenshot',{format:'png'});fs.mkdirSync(process.env.GBOX_ACTIVITY_EVIDENCE,{recursive:true});fs.writeFileSync(path.join(process.env.GBOX_ACTIVITY_EVIDENCE,'granular-activity.png'),Buffer.from(shot.result.data,'base64'));}
  await evaluate(`ctl.stale()`);assert.match(await evaluate(`document.querySelector('.pp-msg').textContent`),/unconfirmed/);
  await evaluate(`ctl.sync([fit])`);assert.equal(await evaluate(`document.querySelector('.pp-chip').textContent`),'processing');
  await evaluate(`ctl.suspend()`);assert.equal(await evaluate(`document.querySelector('.gbox-pp')===null`),true);
  await evaluate(`ctl.sync([re]);ctl.dispose()`);
 });
});
