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
   if(p==='/api/pso/faces/surfaces')return [];
   if(p.startsWith('/api/pso/faces/recipes?'))return {profiles:window.savedProfiles||{}};
   if(p==='/api/pso/faces/recipes')return {saved:true,notice:'Mapping saved'};
   if(p==='/api/workers')return [{id:'worker',online:true,os:'linux',tools:['pso_face','pso_face_build']}];
   if(p==='/api/jobs')return {id:'job1',state:'succeeded',output:{result:{maps:[{key:'known',reference_materials:['tex101'],surface_id:'${'e'.repeat(24)}',name:'face',chunk:'${'b'.repeat(64)}',image:'image',addresses:[2147614720,2147618816],size:[32,32]}],model:'model',notice:'Explicit reference model'}}};
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

test('saved UV projection and mask are restored, reviewed and reusable in a separate build',async()=>{
 await withPage(async evaluate=>{
  await mount(evaluate);
  await evaluate(`savedProfiles={'${'e'.repeat(24)}':{crop:[.1,.2,.8,.9],quad:[[.2,.2],[.6,.2],[.6,.8],[.2,.8]],opacity:.8,mask:{shape:'ellipse',inset:.12},strokes:[{x:.4,y:.5,radius:.05,erase:true}],additional_patches:[{crop:[0,0,1,1],quad:[[.1,.1],[.3,.1],[.3,.3],[.1,.3]],mask:{shape:'rectangle',inset:0}}]}};document.querySelector('[data-photo]').dispatchEvent(new Event('change'));waitFor(()=>!document.querySelector('[data-save]').disabled&&document.querySelector('[data-shape]').value==='ellipse');`);
  assert.equal(await evaluate(`document.querySelector('[data-transform=x]').value`),'40');
  const preview=await evaluate(`calls.filter(c=>c.p==='/api/pso/faces/preview').at(-1).b`);
  assert.deepEqual(preview.mask,{shape:'ellipse',inset:.12});
  assert.deepEqual(preview.settings.crop,[.1,.2,.8,.9]);
  assert.deepEqual(preview.strokes,[{x:.4,y:.5,radius:.05,erase:true}]);
  assert.equal(preview.additional_patches.length,1);
  await evaluate(`document.querySelector('[data-island]').value='1';document.querySelector('[data-island]').dispatchEvent(new Event('change'));document.querySelector('[data-transform=x]').value='25';document.querySelector('[data-transform=x]').dispatchEvent(new Event('input'));waitFor(()=>!document.querySelector('[data-save]').disabled);`);
  const island=await evaluate(`calls.filter(c=>c.p==='/api/pso/faces/preview').at(-1).b`);
  assert.equal(island.additional_patches[0].quad.reduce((n,p)=>n+p[0],0)/4,.25);
  assert.deepEqual(island.strokes,preview.strokes,'switching islands retains the first island mask');
  await evaluate(`document.querySelector('[data-save]').click();waitFor(()=>calls.some(c=>c.p==='/api/pso/faces/recipes'));`);
  assert.deepEqual(await evaluate(`calls.find(c=>c.p==='/api/pso/faces/recipes').b`),{session_id:'worker-session',key:'known',candidate:'c'.repeat(64)});
  await evaluate(`document.querySelector('[data-build]').click();waitFor(()=>calls.some(c=>c.b?.tool==='pso_face_build'));`);
  const build=await evaluate(`calls.find(c=>c.b?.tool==='pso_face_build').b`);
  assert.equal(build.require_worker,'worker');assert.equal(build.input.photo,'a'.repeat(64));
  assert.equal(await evaluate(`calls.some(c=>c.p.endsWith('/rpc'))`),false,'saving/building never writes the running session');
  await evaluate(`panel.close();`);
 });
});

test('right-click auto inspection preserves the exact click and releases its pause lease after inspection',async()=>{
 await withPage(async evaluate=>{
  await mount(evaluate);
  await evaluate(`panel.close();window.released=0;panel=GBoxPSOFaceEditor.open({sid:'worker-session'}, {...io,point:{x:.37,y:.64,window_aspect:1.8},onInspected:()=>released++,onClose:()=>released++});waitFor(()=>released===1&&!document.querySelector('[data-edit]').hidden);`);
  const request=await evaluate(`calls.filter(c=>c.b?.tool==='pso_face').at(-1).b`);
  assert.equal(request.require_worker,'worker');
  assert.equal(request.input.target_kind,'all');
  assert.equal(request.input.x,.37);assert.equal(request.input.y,.64);assert.equal(request.input.window_aspect,1.8);
  await evaluate(`document.querySelector('[data-clear-point]').click();document.querySelector('[data-inspect]').click();waitFor(()=>released===2);`);
  const manual=await evaluate(`calls.filter(c=>c.b?.tool==='pso_face').at(-1).b.input`);
  assert.equal(manual.x,undefined);assert.equal(manual.target_kind,'player');
  await evaluate(`panel.close();waitFor(()=>released===3);`);
 });
});

test('reopening a photo build retains its pinned mapping until the operator loads the newer saved recipe',async()=>{
 await withPage(async evaluate=>{
  await mount(evaluate);
  await evaluate(`panel.close();window.start=calls.length;window.baseAPI=io.api;window.pinned={crop:[.1,.2,.8,.9],quad:[[.2,.2],[.7,.2],[.7,.8],[.2,.8]],mask:{shape:'ellipse',inset:.1}};window.savedProfiles={'${'e'.repeat(24)}':{crop:[0,0,1,1],quad:[[.5,.2],[.9,.2],[.9,.8],[.5,.8]]}};
   io.api=async(p,b)=>{const r=await baseAPI(p,b);if(p==='/api/jobs'){r.output.result.photo='${'a'.repeat(64)}';r.output.result.maps[0].profile=pinned;r.output.result.maps[0].profile_source='build';}return r;};panel=GBoxPSOFaceEditor.open({sid:'worker-session'},io);document.querySelector('[data-inspect]').click();waitFor(()=>!document.querySelector('[data-apply]').disabled);`);
  assert.equal(await evaluate(`document.querySelector('[data-photo]').value`),'a'.repeat(64));
  assert.equal(await evaluate(`document.querySelector('[data-transform=x]').value`),'45');
  assert.equal(await evaluate(`calls.slice(start).some(c=>c.p.startsWith('/api/pso/faces/recipes?'))`),false);
  await evaluate(`document.querySelector('[data-load-saved]').click();waitFor(()=>document.querySelector('[data-transform=x]').value==='70');`);
  assert.equal(await evaluate(`calls.slice(start).some(c=>c.p.endsWith('/rpc'))`),false);
  await evaluate(`panel.close();`);
 });
});
