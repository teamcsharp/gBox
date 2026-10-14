const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const {withPage}=require('../scripts/browser_lifecycle.cjs');

test('review before deletion retains screenshots and saves exactly one report across cleanup retry',async()=>{
 await withPage(async(evaluate,send)=>{
  await send('Emulation.setDeviceMetricsOverride',{width:1100,height:950,deviceScaleFactor:1,mobile:false});
  await evaluate(fs.readFileSync(path.join(__dirname,'../clients/web/viz/build-actions.js'),'utf8'));
  await evaluate(`document.body.style='background:#101116;color:white;font:14px system-ui';
   window.build={game_id:'fixture',name:'test-build',game_title:'Fixture game',label:'Character replacement test',
    where:[{where:'spark',label:'Spark collection'},{where:'pc',node:'i9-NUC',online:true,label:'i9-NUC (local copy)'},{where:'pc',node:'JAYBUILTFINALE',online:true,label:'JAYBUILTFINALE (local copy)'}]};
   window.calls=[];window.failCleanup=true;window.until=async fn=>{for(let n=0;n<150;n++){if(fn())return;await new Promise(r=>setTimeout(r,10));}throw Error('UI timeout');};
   window.api=async(p,body,method)=>{if(p.startsWith('/api/build-feedback?'))return {items:[]};calls.push({p,body,method});if(p.endsWith('/report'))return {id:'report-1',number:47};if(p.endsWith('/review-cleanup')){if(failCleanup)throw Error('temporary cleanup failure');return {state:'queued'};}throw Error('Unexpected '+p);};
   window.done=GBoxBuildActions.open('delete',build,{here:'JAYBUILTFINALE',api});void 0;`);
  await evaluate(`document.querySelector('[value=pcs]').click();for(const node of document.querySelectorAll('[data-ba-pc]'))node.click();document.querySelector('[data-ba=review]').click();void 0;`);
  assert.equal(await evaluate(`document.querySelectorAll('.ba-modal').length`),1);
  assert.match(await evaluate(`document.querySelector('.ba-box').textContent`),/i9-NUC, JAYBUILTFINALE/);
  await evaluate(`document.querySelector('[data-ba-note]').value='Eyes and face lost detail. Preserve the reference proportions in the next whole-cast build.';`);
  const doc=await send('DOM.getDocument');
  const found=await send('DOM.querySelector',{nodeId:doc.result.root.nodeId,selector:'[data-ba-files]'});
  await send('DOM.setFileInputFiles',{nodeId:found.result.nodeId,files:[path.resolve(__dirname,'../docs/evidence/ff7-mario-1819/battle-after.png'),path.resolve(__dirname,'../docs/evidence/ff7-mario-1819/field-after.png')]});
  await evaluate(`until(()=>document.querySelectorAll('[data-ba-role]').length===2);`);
  await evaluate(`const purpose=document.querySelector('[data-ba-role="1"]');purpose.value='reference';purpose.dispatchEvent(new Event('change',{bubbles:true}));`);
  if(process.env.GBOX_BUILD_REVIEW_EVIDENCE){
   const dir=path.resolve(process.env.GBOX_BUILD_REVIEW_EVIDENCE);fs.mkdirSync(dir,{recursive:true});
   await evaluate(`const tag=document.createElement('div');tag.textContent='UI screenshot — fixture build and static prior gameplay images; no live game or deletion';tag.style='position:fixed;bottom:0;left:0;right:0;background:#244974;color:white;padding:8px;font:12px system-ui;z-index:2147483647';document.body.appendChild(tag);`);
   const shot=await send('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(dir,'review-before-removal.png'),Buffer.from(shot.result.data,'base64'));
  }
  await evaluate(`document.querySelector('[data-ba=go]').click();until(()=>document.querySelector('[data-ba-status]').textContent.includes('Retry'));`);
  assert.equal(await evaluate(`calls.filter(c=>c.p.endsWith('/report')).length`),1);
  assert.equal(await evaluate(`document.querySelector('[data-ba-note]').disabled`),true,'saved note cannot diverge during cleanup retry');
  assert.deepEqual(await evaluate(`calls[0].body.images.map(i=>i.role)`),['screenshot','reference']);
  assert.deepEqual(await evaluate(`calls[1].body`),{scope:'pcs',nodes:['i9-NUC','JAYBUILTFINALE'],report_id:'report-1'});
  await evaluate(`failCleanup=false;document.querySelector('[data-ba=go]').click();done;`);
  assert.equal(await evaluate(`calls.filter(c=>c.p.endsWith('/report')).length`),1,'no duplicate report on retry');
  assert.equal((await evaluate('done')).scope,'review');
  assert.ok((await evaluate('calls')).every(c=>!c.p.endsWith('/delete')),'raw deletion is never called by review flow');
 });
});

test('capture for a review hides the report popup until the frame arrives',async()=>{
 await withPage(async(evaluate,send)=>{
  await evaluate(fs.readFileSync(path.join(__dirname,'../clients/web/viz/build-actions.js'),'utf8'));
  await evaluate(`window.build={game_id:'g',name:'b'};window.pending=null;window.api=async p=>p.startsWith('/api/sessions?')?[{session_id:'test',state:'running',game_id:'g',mod:'b',detail:{worker_name:'PC'}}]:new Promise((yes,no)=>pending={yes,no});window.done=GBoxBuildActions.open('report',build,{api,here:'PC'});document.querySelector('[data-ba=capture]').click();void 0;`);
  for(let n=0;n<100&&!await evaluate('!!pending');n++)await new Promise(r=>setTimeout(r,10));
  assert.equal(await evaluate(`getComputedStyle(document.querySelector('.ba-modal')).visibility`),'hidden');
  await evaluate(`pending.no(Error('Temporary capture failure'));new Promise(r=>setTimeout(r,20));`);
  assert.equal(await evaluate(`getComputedStyle(document.querySelector('.ba-modal')).visibility`),'visible');
  await evaluate(`document.querySelector('[data-ba=cancel]').click();done;`);
  await evaluate(`window.done=GBoxBuildActions.open('report',build,{api,here:'PC'});pending=null;document.querySelector('[data-ba=capture]').click();void 0;`);
  for(let n=0;n<100&&!await evaluate('!!pending');n++)await new Promise(r=>setTimeout(r,10));
  await send('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});
  assert.equal(await evaluate('done'),null);
  await evaluate(`pending.no(Error('late failure'));new Promise(r=>setTimeout(r,20));`);
  assert.equal(await evaluate(`document.querySelectorAll('.ba-modal').length`),0,'late capture never restores a cancelled popup');
 });
});


test('an old backend cannot silently discard review images or create a cleanup report',async()=>{
 await withPage(async(evaluate,send)=>{
  await evaluate(fs.readFileSync(path.join(__dirname,'../clients/web/viz/build-actions.js'),'utf8'));
  await evaluate(`window.calls=[];window.ready=false;window.until=async fn=>{for(let n=0;n<100;n++){if(fn())return;await new Promise(r=>setTimeout(r,10));}throw Error('UI timeout');};
   window.api=async(p,body)=>{if(p.startsWith('/api/build-feedback?')){if(!ready)throw Error('404');return {items:[]};}calls.push(p);return {id:'saved',number:9};};
   window.done=GBoxBuildActions.open('report',{game_id:'game',name:'build'},{api,reviewCleanup:{scope:'all'}});document.querySelector('[data-ba-note]').value='Keep these defect notes';document.querySelector('[data-ba=go]').click();void 0;`);
  await evaluate(`until(()=>!document.querySelector('[data-ba=go]').disabled);`);
  assert.equal(await evaluate('calls.length'),0,'no report or cleanup is posted to the old backend');
  assert.match(await evaluate(`document.querySelector('[data-ba-status]').textContent`),/waiting for server activation/);
  assert.equal(await evaluate(`document.querySelector('[data-ba-note]').value`),'Keep these defect notes');
  await evaluate(`ready=true;document.querySelector('[data-ba=go]').click();done;`);
  assert.deepEqual(await evaluate('calls'),['/api/builds/game/build/report','/api/builds/game/build/review-cleanup']);
  await evaluate(`ready=false;calls=[];window.done=GBoxBuildActions.open('report',{game_id:'game',name:'build'},{api});document.querySelector('[data-ba-note]').value='Screenshot-only report';void 0;`);
  const doc=await send('DOM.getDocument');
  const input=await send('DOM.querySelector',{nodeId:doc.result.root.nodeId,selector:'[data-ba-files]'});
  await send('DOM.setFileInputFiles',{nodeId:input.result.nodeId,files:[path.resolve(__dirname,'../docs/evidence/ff7-mario-1819/battle-after.png')]});
  await evaluate(`until(()=>document.querySelectorAll('[data-ba-role]').length===1);document.querySelector('[data-ba=go]').click();until(()=>!document.querySelector('[data-ba=go]').disabled);`);
  assert.equal(await evaluate('calls.length'),0,'ordinary image reports are also held until the backend supports images');
  assert.equal(await evaluate(`document.querySelectorAll('[data-ba-role]').length`),1,'the image stays attached');
  await evaluate(`ready=true;document.querySelector('[data-ba=go]').click();done;`);
  assert.deepEqual(await evaluate('calls'),['/api/builds/game/build/report']);
 });
});
