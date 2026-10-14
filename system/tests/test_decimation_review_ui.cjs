const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),http=require('node:http');
const {withPage}=require('../scripts/browser_lifecycle.cjs');
const web=path.join(__dirname,'../clients/web');
const read=name=>fs.readFileSync(path.join(web,'viz',name),'utf8');

test('saved mesh comparisons support marked feedback, retry, original preference and expired fits',async()=>{
 await withPage(async(evaluate,send)=>{
  await send('Emulation.setDeviceMetricsOverride',{width:1400,height:1000,deviceScaleFactor:1,mobile:false});
  await evaluate(read('build-report-image.js'));await evaluate(read('decimation-review.js'));
  await evaluate(`window.calls=[];window.disposed=0;window.fail=true;window.expired=false;
   window.waitFor=async fn=>{for(let n=0;n<200;n++){if(fn())return;await new Promise(r=>setTimeout(r,10));}throw Error('Review UI timeout');};
   window.io={assetUrl:u=>u,api:async(p,body)=>{calls.push({p,body});if(body){if(fail)throw Error('Temporary feedback error');return {id:'report',number:17};}
    return {models:[{key:'m',label:'Mesh UI fixture',comparison:expired?null:{before:'/before',after:'/after',data:{source_triangles:12,result_triangles:6,reason:'Original exceeds native allocation',limits:{budget_bytes:4096},sampled:false}}}]};},
    loadViewer:async()=>({createCharacterViewer:async(host,url)=>{const c=document.createElement('canvas');c.width=400;c.height=400;host.append(c);const ctx=c.getContext('2d');ctx.fillStyle=url==='/before'?'#55aaee':'#ee9955';ctx.fillRect(30,30,300,300);return {snapshot:()=>c.toDataURL(),dispose:()=>{disposed++;c.remove();}};}})};
   GBoxDecimationReview.open('job','m',io);waitFor(()=>!document.querySelector('[data-mark]').disabled);`);
  assert.match(await evaluate(`document.querySelector('[data-before]').textContent`),/12/);
  await evaluate(`document.querySelector('[data-note]').value='The eye surface disappeared';document.querySelector('[data-mark]').click();waitFor(()=>document.querySelector('.bri-modal canvas:not([hidden])'));`);
  assert.equal(await evaluate(`document.querySelector('.bri-modal [data-note]').value`),'The eye surface disappeared');
  const rect=await evaluate(`(()=>{const r=document.querySelector('.bri-modal canvas').getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height};})()`);
  await send('Input.dispatchMouseEvent',{type:'mousePressed',button:'left',clickCount:1,x:rect.x+rect.w*.15,y:rect.y+rect.h*.2});
  await send('Input.dispatchMouseEvent',{type:'mouseMoved',button:'left',x:rect.x+rect.w*.4,y:rect.y+rect.h*.55});
  await send('Input.dispatchMouseEvent',{type:'mouseReleased',button:'left',clickCount:1,x:rect.x+rect.w*.4,y:rect.y+rect.h*.55});
  await evaluate(`document.querySelector('.bri-modal [data-send]').click();waitFor(()=>document.querySelector('.bri-status').textContent.includes('Report failed'));`);
  assert.equal(await evaluate(`document.querySelector('.bri-modal [data-note]').value`),'The eye surface disappeared');
  await evaluate(`fail=false;document.querySelector('.bri-modal [data-send]').click();waitFor(()=>!document.querySelector('.bri-modal'));`);
  const body=await evaluate('calls.filter(c=>c.body).at(-1).body');
  assert.equal(body.model,'m');assert.equal(body.prefer_original,true);
  assert.notEqual(body.evidence.image_b64,body.evidence.original_image_b64,'marked and original comparisons are distinct');
  assert.equal(await evaluate(`calls.some(c=>c.p.includes('/api/sessions/'))`),false,'no emulator capture or game input is needed');
  await send('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});
  assert.equal(await evaluate(`document.querySelectorAll('.gbox-mesh-review').length`),0);
  assert.equal(await evaluate('disposed'),2);
  await evaluate(`expired=true;GBoxDecimationReview.open('old-job','m',io);waitFor(()=>document.querySelector('[data-description]').textContent.includes('No exact'));`);
  assert.equal(await evaluate(`document.querySelector('[data-mark]').disabled`),true);
  await evaluate(`document.querySelector('[data-note]').value='Please retain the face';document.querySelector('[data-submit]').click();waitFor(()=>document.querySelector('.gmr-status').textContent.includes('Report #17'));document.querySelector('[data-close]').click();`);
 });
});

test('real saved geometry renders on both sides and can be captured without the report popup',{skip:!process.env.GBOX_MESH_REVIEW_ASSETS},async()=>{
 const assets=process.env.GBOX_MESH_REVIEW_ASSETS,three=process.env.GBOX_THREE_ASSETS;
 const meta=JSON.parse(fs.readFileSync(path.join(assets,'metadata.json'),'utf8'));
 const files={'/before.glb':path.join(assets,'before.glb'),'/after.glb':path.join(assets,'after.glb'),'/three.mjs':path.join(three,'three.mjs'),
  '/examples/jsm/loaders/GLTFLoader.js':path.join(three,'GLTFLoader.js'),'/examples/jsm/utils/BufferGeometryUtils.js':path.join(three,'BufferGeometryUtils.js'),'/examples/jsm/controls/OrbitControls.js':path.join(three,'OrbitControls.js')};
 const server=http.createServer((req,res)=>{
  if(req.url==='/character-model.js'){let src=read('character-model.js').replace(/https:\/\/cdn\.jsdelivr\.net\/npm\/three@0\.160\.0\/\+esm/g,'/three.mjs').replace(/https:\/\/cdn\.jsdelivr\.net\/npm\/three@0\.160\.0\/examples\/jsm\/(.*?)\/\+esm/g,'/examples/jsm/$1');res.setHeader('Content-Type','text/javascript');res.end(src);return;}
  if(files[req.url]){res.setHeader('Content-Type',req.url.endsWith('.glb')?'model/gltf-binary':'text/javascript');res.end(fs.readFileSync(files[req.url]));return;}
  res.setHeader('Content-Type','text/html');res.end('<!doctype html><script type="importmap">{"imports":{"three":"/three.mjs"}}</script><body>Saved geometry comparison</body>');
 });
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 try{await withPage(async(evaluate,send)=>{
  await send('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
  await send('Page.navigate',{url:`http://127.0.0.1:${server.address().port}/`});
  await evaluate(read('build-report-image.js'));await evaluate(read('decimation-review.js'));
  await evaluate(`window.views=[];window.meta=${JSON.stringify(meta)};window.until=async fn=>{for(let n=0;n<400;n++){if(fn())return;await new Promise(r=>setTimeout(r,25));}throw Error(document.querySelector('.gmr-status')?.textContent||'Preview timeout');};
   GBoxDecimationReview.open('native-proof','m',{assetUrl:u=>u,api:async()=>({models:[{key:'m',label:meta.label,comparison:{before:'/before.glb',after:'/after.glb',data:{source_triangles:meta.before_triangles,result_triangles:meta.after_triangles,reason:meta.reason,limits:meta.limits,sampled:false}}}]}),
    loadViewer:async()=>{const m=await import('/character-model.js');return {createCharacterViewer:async(...args)=>{const v=await m.createCharacterViewer(...args);views.push(v);return v;}};}});until(()=>!document.querySelector('[data-mark]').disabled);`);
  const counts=await evaluate(`views.map(v=>{let n=0;v.gltf.scene.traverse(o=>{if(o.isMesh)n+=o.geometry.index.count/3;});return n;})`);
  assert.deepEqual(counts.sort((a,b)=>b-a),[meta.before_triangles,meta.after_triangles].sort((a,b)=>b-a));
  await evaluate(`views[0].setView({position:[.55,.3,1.55],target:[0,0,0]});`);
  const poses=await evaluate(`views.map(v=>v.getView())`);
  for(let i=0;i<3;i++)assert.ok(Math.abs(poses[0].position[i]-poses[1].position[i])<1e-5,'both views orbit and zoom together');
  if(process.env.GBOX_MESH_REVIEW_EVIDENCE){
   const output=path.resolve(process.env.GBOX_MESH_REVIEW_EVIDENCE);fs.mkdirSync(output,{recursive:true});
   await evaluate(`const tag=document.createElement('div');tag.textContent=${JSON.stringify(meta.note)};tag.style='position:fixed;bottom:0;left:0;right:0;padding:8px;background:#244974;color:white;z-index:2147483647;font:12px system-ui';document.body.append(tag);`);
   const shot=await send('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(output,'mesh-comparison.png'),Buffer.from(shot.result.data,'base64'));
  }
  await evaluate(`document.querySelector('[data-mark]').click();until(()=>document.querySelector('.bri-modal canvas:not([hidden])'));`);
  assert.equal(await evaluate(`document.querySelector('.bri-modal canvas').width`),1600);
  await evaluate(`document.querySelector('.bri-modal [data-cancel]').click();document.querySelector('[data-close]').click();`);
 },{softwareGL:true});}finally{await new Promise(r=>server.close(r));}
});
