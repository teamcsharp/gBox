'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),http=require('node:http');
const {withPage}=require('../scripts/browser_lifecycle.cjs');
test('PSO live map, historical playback and critical events stay session-pinned',async()=>{
 const server=http.createServer((req,res)=>{
  if(req.url==='/review.js'){res.setHeader('Content-Type','application/javascript');res.end(fs.readFileSync(path.join(__dirname,'../clients/web/viz/pso-reviewer.js')));return;}
  res.setHeader('Content-Type','text/html; charset=utf-8');
  res.end('<meta charset="utf-8"><body style="background:#07111b"><script src="/review.js"></script></body>');
 });
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 try{await withPage(async(evaluate,send)=>{
  await send('Emulation.setDeviceMetricsOverride',{width:1100,height:900,deviceScaleFactor:1,mobile:false});
  await send('Page.navigate',{url:`http://127.0.0.1:${server.address().port}`});
  await send('Page.bringToFront');
  for(let end=Date.now()+10000;!await evaluate(`!!window.GBoxPSOReview`);){
   if(Date.now()>end)throw Error('Reviewer failed to load: '+JSON.stringify(await evaluate(`({url:location.href,ready:document.readyState,body:document.body?.innerText})`)));
   await new Promise(r=>setTimeout(r,40));
  }
  await evaluate(`window.requests=[];window.base={schema:'gbox.pso.run-frame/1',run_id:'a'.repeat(32),session_id:'worker-session',game_id:'pso',seq:1,verified:true,elapsed_s:1,episode:1,floor:1,difficulty:0,phase:14,
   action:'Inspect the next exit',thought:'Test fixture: container identity remains a container.',players:{1:{ptr:'1',x:550,y:0,z:560,room:16,hp:33,tp:0},2:{ptr:'2',x:590,y:0,z:560,room:16,hp:38,tp:40}},
   entities:[{kind:'object',class:'TObjContainerItem',x:583,y:1,z:570,room:16}],maps:[{player:1,identity:'same-layout',room:16,size:12,walked:[[45,46],[46,46],[47,46]],blocked:[[[46,46],[46,47]]],geometry_available:false,geometry_reason:'Native collision geometry is not verified for this layout'},{player:2,identity:'same-layout',room:16,size:12,walked:[],blocked:[]}],
   goals:[{player:1,x:610,z:580,room:16,reason:'Inspect visible forward path'}],door_requirements:{reason:'Door condition is not yet verified'},events:[{id:1,at_s:1,kind:'stationary',message:'Player 1 stationary: inspect objective'}]};
   window.io={api:async p=>{requests.push(p);if(p.includes('/runs?'))return {runs:[{id:base.run_id,started:1700000000,frames:2}]};if(p.includes('/live/'))return {frame:base,age_s:20,live:false};if(p.includes('/run/'))return {run:{id:base.run_id},samples:[base,{...base,seq:2,elapsed_s:5,players:{...base.players,1:{...base.players[1],x:560}}}],events:base.events,next_after:2,has_more:false};throw Error('Unexpected request '+p);}};
   window.panel=GBoxPSOReview.open(io,{sid:'worker-session'});new Promise(r=>setTimeout(r,40));`);
  assert.match(await evaluate(`document.querySelector('[data-pr-status]').textContent`),/Stale/);
  assert.match(await evaluate(`document.querySelector('[data-pr-geometry]').textContent`),/not verified/);
  assert.match(await evaluate(`document.querySelector('[data-pr-objective]').textContent`),/Door condition is not yet verified/);
  assert.equal(await evaluate(`document.querySelector('canvas').width>0`),true);
  await evaluate(`const select=document.querySelector('[data-pr-runs]');select.value=base.run_id;select.dispatchEvent(new Event('change'));new Promise(r=>setTimeout(r,30))`);
  assert.equal(await evaluate(`document.querySelector('[data-pr-scrub]').disabled`),false);
  await evaluate(`document.querySelector('[data-pr-scrub]').value=1;document.querySelector('[data-pr-scrub]').dispatchEvent(new Event('input'))`);
  assert.match(await evaluate(`document.querySelector('[data-pr-time]').textContent`),/Playback.*5.0s/);
  await evaluate(`document.querySelector('[data-pr-event]').click()`);
  assert.match(await evaluate(`document.querySelector('[data-pr-time]').textContent`),/Playback.*1.0s/);
  assert.equal(await evaluate(`requests.every(p=>p.includes('worker-session')||p.includes('/run/'+base.run_id))`),true);
  const dir=process.env.GBOX_PSO_REVIEW_ARTIFACT_DIR;
  if(dir){fs.mkdirSync(dir,{recursive:true});const shot=await send('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(dir,'pso-reviewer-browser-fixture.png'),Buffer.from(shot.result.data,'base64'));}
  await send('Emulation.setDeviceMetricsOverride',{width:390,height:700,deviceScaleFactor:1,mobile:false});
  await evaluate(`new Promise(r=>setTimeout(r,30))`);
  assert.equal(await evaluate(`document.querySelector('.pso-review-window').scrollWidth<=document.querySelector('.pso-review-window').clientWidth+1`),true);
  await evaluate(`document.querySelector('[data-pr-close]').click()`);
  assert.equal(await evaluate(`document.querySelector('.pso-review-window')`),null);
 },{timeoutMs:45000});}finally{server.closeAllConnections();await new Promise(r=>server.close(r));}
});
