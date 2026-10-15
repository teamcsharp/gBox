const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {withPage}=require('../scripts/browser_lifecycle.cjs');
// Native WebGL import is isolated from these input/lifecycle tests; model/UV rendering has its own tests/proof.
const source=fs.readFileSync(path.join(__dirname,'../clients/web/viz/pso-face-editor.js'),'utf8')
  .replace("import('/viz/character-model.js')",'Promise.resolve({createCharacterViewer:window.createViewerStub})');
async function mount(evaluate){
 await evaluate(`window.waitFor=async f=>{for(let n=0;n<500;n++){if(f())return;await new Promise(r=>setTimeout(r,10));}throw Error('face editor timeout')};
  const c=document.createElement('canvas');c.width=c.height=32;c.getContext('2d').fillStyle='red';c.getContext('2d').fillRect(0,0,32,32);window.imageURL=c.toDataURL();
  window.calls=[];window.viewerDisposed=0;window.paintHandler=null;window.createViewerStub=async()=>({materials:()=>['tex101'],texture:()=>{},paint:f=>{paintHandler=f},dispose:()=>viewerDisposed++});
  window.pendingPreview=null;window.holdPreview=false;window.pendingApply=null;window.holdApply=false;
  window.io={url:()=>imageURL,api:async(p,b)=>{calls.push({p,b});
   if(p==='/api/pso/faces/photos')return [{photo:'${'a'.repeat(64)}',label:'My face'}];
   if(p==='/api/workers')return [{id:'worker',tools:['pso_face']}];
   if(p==='/api/jobs')return {state:'succeeded',output:{result:{maps:[{key:'known',name:'face',chunk:'${'b'.repeat(64)}',image:'image',addresses:[2147614720,2147618816],size:[32,32]}],model:'model',notice:'Explicit reference model'}}};
   if(p==='/api/pso/faces/preview'){if(holdPreview)return new Promise(r=>pendingPreview=r);return {candidate:'${'c'.repeat(64)}',image:'preview',notice:'Native preview'};}
   if(p==='/api/sessions/worker-session/rpc'){if(holdApply)return new Promise(r=>pendingApply=r);return {memory_verified:true,notice:'RAM verified, no frame comparison'};}
   throw Error('unexpected '+p);}};`);
 await evaluate(source);
 await evaluate(`window.panel=GBoxPSOFaceEditor.open({sid:'worker-session'},io);document.querySelector('[data-inspect]').click();waitFor(()=>!document.querySelector('[data-edit]').hidden&&document.querySelector('[data-map]').options.length===1);`);
 await evaluate(`document.querySelector('[data-photo]').value='${'a'.repeat(64)}';document.querySelector('[data-photo]').dispatchEvent(new Event('change'));waitFor(()=>!document.querySelector('[data-apply]').disabled);`);
}

test('face editor needs a reviewed native preview and exact address, and pins live commands',async()=>{
 await withPage(async (evaluate,send)=>{
  if(process.env.GBOX_PSO_FACE_UI_EVIDENCE)await send('Emulation.setDeviceMetricsOverride',{width:1400,height:1200,deviceScaleFactor:1,mobile:false});
  await mount(evaluate);
  assert.equal(await evaluate(`calls.some(c=>c.p.endsWith('/rpc'))`),false,'preview never implicitly mutates the running game');
  await evaluate(`document.querySelector('[data-apply]').click();`);
  assert.equal(await evaluate(`calls.some(c=>c.p.endsWith('/rpc'))`),false,'ambiguous addresses require an explicit selection');
  await evaluate(`document.querySelector('[data-address]').value='2147614720';holdApply=true;document.querySelector('[data-apply]').click();document.querySelector('[data-apply]').click();waitFor(()=>pendingApply!==null);`);
  const commands=await evaluate(`calls.filter(c=>c.p.endsWith('/rpc'))`);
  assert.equal(commands.length,1);
  assert.equal(commands[0].b.op,'pso_face');
  assert.deepEqual(commands[0].b.args.input,{op:'apply',key:'known',address:2147614720,candidate:'c'.repeat(64)});
  assert.match(commands[0].b.args.command_id,/^[0-9a-f-]{36}$/);
  assert.ok(commands[0].b.args.expires>Date.now()/1000);
  await evaluate(`pendingApply({notice:'RAM verified, no frame comparison'});waitFor(()=>!document.querySelector('[data-restore]').disabled);`);
  if(process.env.GBOX_PSO_FACE_UI_EVIDENCE){
   await evaluate(`document.body.style='background:#12141b;font:14px system-ui';document.querySelector('[data-status]').textContent='UI layout test fixture. Model renderer is stubbed; this is not native gameplay proof.';document.querySelector('[data-live]').checked=false;`);
   const shot=await send('Page.captureScreenshot',{format:'png'});
   fs.mkdirSync(path.dirname(process.env.GBOX_PSO_FACE_UI_EVIDENCE),{recursive:true});fs.writeFileSync(process.env.GBOX_PSO_FACE_UI_EVIDENCE,Buffer.from(shot.result.data,'base64'));
  }
  await evaluate(`panel.close();waitFor(()=>!document.querySelector('#pso-face-editor'));`);
  assert.equal(await evaluate('viewerDisposed'),1);
 });
});

test('editing invalidates candidate, stale preview cannot enable apply, and closing cannot apply an outstanding preview',async()=>{
 await withPage(async evaluate=>{
  await mount(evaluate);
  await evaluate(`holdPreview=true;document.querySelector('[data-transform=x]').value='52';document.querySelector('[data-transform=x]').dispatchEvent(new Event('input'));waitFor(()=>pendingPreview!==null);`);
  assert.equal(await evaluate(`document.querySelector('[data-apply]').disabled`),true);
  await evaluate(`document.querySelector('[data-transform=x]').value='54';document.querySelector('[data-transform=x]').dispatchEvent(new Event('input'));pendingPreview({candidate:'${'d'.repeat(64)}',image:'stale',notice:'STALE'});new Promise(r=>setTimeout(r,30));`);
  assert.equal(await evaluate(`document.querySelector('[data-apply]').disabled`),true);
  assert.notEqual(await evaluate(`document.querySelector('[data-status]').textContent`),'STALE');
  await evaluate(`document.querySelector('[data-live]').checked=true;panel.close();if(pendingPreview)pendingPreview({candidate:'${'d'.repeat(64)}',image:'closed',notice:'late'});new Promise(r=>setTimeout(r,400));`);
  assert.equal(await evaluate(`calls.filter(c=>c.p.endsWith('/rpc')).length`),0);
  assert.equal(await evaluate(`document.querySelector('#pso-face-editor')===null`),true);
 });
});

test('UV and mesh mask painting submit explicit strokes without silently applying',async()=>{
 await withPage(async evaluate=>{
  await mount(evaluate);
  await evaluate(`document.querySelector('[data-paint3d]').checked=true;document.querySelector('[data-paint3d]').dispatchEvent(new Event('change'));paintHandler({material:'tex101',u:.4,v:.6});waitFor(()=>calls.filter(c=>c.p==='/api/pso/faces/preview').at(-1).b.strokes.length===1);`);
  const request=await evaluate(`calls.filter(c=>c.p==='/api/pso/faces/preview').at(-1).b`);
  assert.equal(request.session_id,'worker-session');
  assert.deepEqual(request.strokes,[{x:.4,y:.6,radius:.04,erase:true}]);
  assert.equal(request.settings.photo,'a'.repeat(64));
  assert.equal(await evaluate(`calls.some(c=>c.p.endsWith('/rpc'))`),false);
  await evaluate(`panel.close();`);
 });
});
