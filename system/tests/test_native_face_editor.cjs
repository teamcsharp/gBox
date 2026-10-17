const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {freshWorker}=require('../clients/web/viz/native-face-editor.js');
const {withPage}=require('../scripts/browser_lifecycle.cjs');
const editor=fs.readFileSync(path.join(__dirname,'../clients/web/viz/native-face-editor.js'),'utf8');
const warp=fs.readFileSync(path.join(__dirname,'../clients/web/viz/face-warp-editor.js'),'utf8');

test('native face worker selection requires the complete current implementation',()=>{
 const implementation={'gbox/native_face_editor.py':'new','gbox/face_warp.py':'new-warp'};
 const workers=[{id:'old',online:true,tools:['native_face_editor'],build_sources:{'gbox/native_face_editor.py':'new'}},
  {id:'offline',online:false,tools:['native_face_editor'],build_sources:implementation},
  {id:'ready',online:true,tools:['native_face_editor'],build_sources:implementation}];
 assert.equal(freshWorker(workers,implementation).id,'ready');
 assert.equal(freshWorker(workers.slice(0,2),implementation),undefined);
});

async function setup(evaluate,send){
 await send('Emulation.setDeviceMetricsOverride',{width:1400,height:1400,deviceScaleFactor:1,mobile:false});
 await evaluate(warp);await evaluate(editor);
 await evaluate(`document.body.style='background:#15151a;color:#eee;font:14px system-ui';
  var ref=document.createElement('canvas'),layer=document.createElement('canvas'),coverage=document.createElement('canvas');for(const c of [ref,layer,coverage])c.width=c.height=64;
  ref.getContext('2d').fillStyle='#a5876e';ref.getContext('2d').fillRect(0,0,64,64);layer.getContext('2d').fillStyle='#f08060';layer.getContext('2d').fillRect(25,25,14,14);coverage.getContext('2d').fillStyle='#fff';coverage.getContext('2d').fillRect(0,0,64,64);
  var images={original:ref.toDataURL(),layer:layer.toDataURL(),coverage:coverage.toDataURL(),result:ref.toDataURL()};
  var calls=[],recipes=[],recipeDeferred={},pending=null,finishPreview=null,previewCount=0,photo='a'.repeat(64),game='1de2e7634f3161ff',implementation={'gbox/face_warp.py':'fresh'},initial={crop:[0,0,1,1],bounds:[-1,-1,1,1],opacity:1,feather:.12,deformation:{version:1,lattice:null,strokes:[]}};
  var api=async(p,b)=>{calls.push({p,b:structuredClone(b)});
   if(p.startsWith('/api/native-faces/catalog'))return {game_id:game,implementation,faces:[{key:'DOA2/AYA00.CHR',name:'Ayane',settings:initial},{key:'DOA2/BAS00.CHR',name:'Bass',settings:initial}],notice:'Choose a face'};
   if(p==='/api/pso/faces/photos')return [{photo,label:'Synthetic photo'}];
   if(p==='/api/workers')return [{id:'worker',online:true,tools:['native_face_editor'],build_sources:implementation}];
   if(p==='/api/jobs'){if(b.input.op==='inspect')return {id:'inspection',state:'succeeded',output:{result:{inspection:'i'.repeat(64),profile_key:b.input.profile_key,settings:structuredClone(initial),notice:'Original loaded'}}};return {id:'build-job',state:'queued'};}
   if(p.startsWith('/api/native-faces/recipes?')){const id=p.split('&photo=')[1];if(recipeDeferred[id])return recipeDeferred[id];return {recipes:structuredClone(recipes)};}
   if(p==='/api/native-faces/preview'){const n=++previewCount,r={candidate:'candidate-'+n,settings:structuredClone(b.settings),image:'result',native_sha256:'payload',original:'original',layer:'layer',coverage:'coverage',notice:'Encoded preview '+n};if(pending){pending=false;await new Promise(resolve=>finishPreview=resolve);}return r;}
   if(p==='/api/native-faces/recipes'){const old=calls.filter(c=>c.p==='/api/native-faces/preview').at(-1).b;recipes=[{id:b.candidate,profile_key:'DOA2/AYA00.CHR',settings:structuredClone(old.settings)}];return {notice:'Accepted exact mapping'};}
   throw Error(p);
  };var ctl=GBoxNativeFaceEditor.open({game_id:game,photo},{api,url:p=>images[p.split('/').at(-1)]||p});ctl.ready;`);
 await evaluate(`(async()=>{for(let i=0;i<100&&document.querySelector('[data-save]').disabled;i++)await new Promise(r=>setTimeout(r,20));})()`);
 assert.equal(await evaluate(`document.querySelector('[data-save]').disabled`),false);
}
async function mouse(send,type,p){await send('Input.dispatchMouseEvent',{type,x:p.x,y:p.y,button:'left',buttons:type==='mouseReleased'?0:1,clickCount:type==='mouseMoved'?0:1});}
async function pos(evaluate,x,y){return evaluate(`(()=>{const c=document.querySelector('[data-fw-canvas]');c.scrollIntoView({block:'center'});const b=c.getBoundingClientRect();return{x:b.left+b.width*${x},y:b.top+b.height*${y}}})()`);}

test('browser: face edits invalidate approval immediately, retain undo through native preview, and build exact accepted IDs',async()=>{
 await withPage(async(evaluate,send)=>{
  await setup(evaluate,send);
  if(process.env.GBOX_NATIVEFACE_EVIDENCE){
   await evaluate(`document.querySelector('#native-face-editor header').insertAdjacentHTML('afterend','<p style="background:#534719;padding:8px">UI interaction fixture · synthetic face layers; owned-disc codec validation is recorded separately.</p>')`);
   const shot=await send('Page.captureScreenshot',{format:'png'});fs.mkdirSync(process.env.GBOX_NATIVEFACE_EVIDENCE,{recursive:true});fs.writeFileSync(path.join(process.env.GBOX_NATIVEFACE_EVIDENCE,'native-face-editor-ui.png'),Buffer.from(shot.result.data,'base64'));
  }
  assert.equal(await evaluate(`calls.filter(c=>c.p==='/api/jobs'&&c.b.input.op==='build').length`),0,'opening and previewing never bakes a ROM');
  await evaluate(`pending=true;document.querySelector('[data-preview]').click();`);
  const start=await pos(evaluate,.5,.5),end={x:start.x+6,y:start.y};
  await mouse(send,'mousePressed',start);await mouse(send,'mouseMoved',end);
  assert.equal(await evaluate(`document.querySelector('[data-save]').disabled`),true,'a gesture invalidates the previous native candidate before release');
  await evaluate(`finishPreview();new Promise(r=>setTimeout(r,30));`);
  assert.equal(await evaluate(`document.querySelector('[data-save]').disabled`),true,'old native reply cannot approve a gesture in progress');
  await mouse(send,'mouseReleased',end);
  await evaluate(`new Promise(r=>setTimeout(r,500));`);
  assert.equal(await evaluate(`document.querySelector('[data-save]').disabled`),false);
  assert.equal(await evaluate(`document.querySelector('[data-fw-undo]').disabled`),false,'native preview does not clear local history');
  const latest=await evaluate(`calls.filter(c=>c.p==='/api/native-faces/preview').at(-1).b.settings.deformation`);
  assert.ok(latest.strokes.length>0);
  assert.equal(await evaluate(`document.querySelector('[data-build]').disabled`),true,'preview is not approval');
  await evaluate(`document.querySelector('[data-save]').click();new Promise(r=>setTimeout(r,100));`);
  assert.equal(await evaluate(`document.querySelector('[data-build]').disabled`),false,JSON.stringify(await evaluate(`({status:document.querySelector('[data-status]').textContent,calls})`)));
  await evaluate(`document.querySelector('[data-build]').click();new Promise(r=>setTimeout(r,100));`);
  const build=await evaluate(`calls.find(c=>c.p==='/api/jobs'&&c.b.input.op==='build').b`);
  assert.equal(build.require_worker,'worker');assert.equal(build.input.photo,'a'.repeat(64));
  assert.deepEqual(build.input.recipes,await evaluate('recipes.map(r=>r.id)'));
  await evaluate(`document.querySelector('[data-fw-undo]').click();new Promise(r=>setTimeout(r,500));`);
  assert.equal((await evaluate(`calls.filter(c=>c.p==='/api/native-faces/preview').at(-1).b.settings.deformation.strokes`)).length,0);
  await evaluate('ctl.close()');
 });
});

test('browser: switching native target rejects the previous face reply and closes cleanly',async()=>{
 await withPage(async(evaluate,send)=>{
  await setup(evaluate,send);
  await evaluate(`pending=true;document.querySelector('[data-preview]').click();var select=document.querySelector('[data-face]');select.value='DOA2/BAS00.CHR';select.dispatchEvent(new Event('change'));finishPreview();new Promise(r=>setTimeout(r,30));`);
  assert.equal(await evaluate(`document.querySelector('[data-work]').hidden`),true);
  assert.equal(await evaluate(`document.querySelector('[data-save]').disabled`),true);
  assert.equal(await evaluate(`document.querySelector('[data-native]').hasAttribute('src')`),false);
  await evaluate(`document.querySelector('[data-close]').click()`);
  assert.equal(await evaluate(`!!document.querySelector('#native-face-editor')`),false);
 });
});

test('browser: an earlier photo recipe response cannot overwrite the current photo or its saved blend',async()=>{
 await withPage(async(evaluate,send)=>{
  await setup(evaluate,send);
  const before=await evaluate('previewCount');
  await evaluate(`var b='b'.repeat(64),c='c'.repeat(64),finishB,finishC;recipeDeferred[b]=new Promise(r=>finishB=r);recipeDeferred[c]=new Promise(r=>finishC=r);
   var select=document.querySelector('[data-photo]');select.insertAdjacentHTML('beforeend','<option value="'+b+'">Photo B</option><option value="'+c+'">Photo C</option>');select.value=b;select.dispatchEvent(new Event('change'));select.value=c;select.dispatchEvent(new Event('change'));finishB({recipes:[{id:'old',profile_key:'DOA2/AYA00.CHR',settings:{...initial,opacity:.1}}]});new Promise(r=>setTimeout(r,30));`);
  assert.equal(await evaluate('previewCount'),before,'stale photo handler does not trigger a preview for another photo');
  await evaluate(`finishC({recipes:[{id:'correct',profile_key:'DOA2/AYA00.CHR',settings:{...initial,opacity:.37}}]});new Promise(r=>setTimeout(r,100));`);
  const latest=await evaluate(`calls.filter(c=>c.p==='/api/native-faces/preview').at(-1).b`);
  assert.equal(latest.photo,'c'.repeat(64));assert.equal(latest.settings.opacity,.37);
  await evaluate('ctl.close()');
 });
});
