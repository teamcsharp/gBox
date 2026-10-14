const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),http=require('node:http');
const {withPage}=require('../scripts/browser_lifecycle.cjs');
const H=require('../clients/web/viz/retarget-handles.js');

test('shape cage math and profile data survive normalization',()=>{
 const offsets=Object.fromEntries(Array.from({length:27},(_,i)=>[i,[.1,.02,0]]));
 const input=[0,0,0,1,1,1,.5,.5,.5],bounds={min:[0,0,0],max:[1,1,1]};
 const moved=H.deformCage(input,{lattice:{offsets}},bounds,1);
 moved.forEach((v,i)=>assert.ok(Math.abs(v-input[i]-[.1,.02,0][i%3])<1e-6));
 assert.equal(H.isIdentity({lattice:{offsets}}),false);
 assert.equal(H.normalize({plant_feet:true}).plant_feet,true);
});

test('texture preview requires explicit acceptance; rejection and failed decisions retain the original',async()=>{
 await withPage(async evaluate=>{
  await evaluate(fs.readFileSync(path.join(__dirname,'../clients/web/viz/texture-review.js'),'utf8'));
  await evaluate(`document.body.innerHTML='<div id="host"></div>';window.calls=[];window.approved=[];window.pending=[];window.fail=true;
   window.waitFor=async fn=>{for(let n=0;n<200;n++){if(fn())return;await new Promise(r=>setTimeout(r,10));}throw Error('UI timeout');};
   window.io={url:u=>u,api:async(p,body)=>{calls.push({p,body});if(p.endsWith('/texture-maps'))return {maps:[{index:3,name:'Face',size:[64,64],url:'/before.png'}]};if(p.endsWith('/texture-review'))return {id:'job'};if(p.endsWith('/decision')){if(fail)throw Error('Temporary server error');return body.decision==='accept'?{state:'accepted',variant:'donor_tex',name:'Approved'}:{state:'rejected'};}return {job_state:'succeeded',result:{settings:{backend:'ai'},images:[{map:'Face',original_size:[64,64],size:[1024,1024],before:'before',after:'after'}]},decision:{state:'pending'}};}};
   window.review=GBoxTextureReview.mount(document.querySelector('#host'),io,{slug:'donor',onAccepted:r=>approved.push(r),onPending:on=>pending.push(on)});
   const enabled=document.querySelector('[data-tr=enabled]');enabled.checked=true;enabled.dispatchEvent(new Event('change'));waitFor(()=>document.querySelector('[data-tr-map]'));`);
  await evaluate(`document.querySelector('[data-tr=prepare]').click();waitFor(()=>!document.querySelector('[data-tr=decision]').hidden);`);
  assert.deepEqual(await evaluate('approved'),[]);
  assert.deepEqual(await evaluate(`calls.find(c=>c.p.endsWith('/texture-review')).body.maps`),[3]);
  assert.equal(await evaluate('pending.at(-1)'),true);
  assert.equal(await evaluate(`calls.filter(c=>c.p.endsWith('/decision')).length`),0,'preparing cannot autoapprove');
  await evaluate(`document.querySelector('[data-tr=accept]').click();waitFor(()=>document.querySelector('[data-tr=status]').textContent.includes('not saved'));`);
  assert.deepEqual(await evaluate('approved'),[]);
  assert.equal(await evaluate('pending.at(-1)'),true);
  await evaluate(`fail=false;document.querySelector('[data-tr=reject]').click();waitFor(()=>document.querySelector('[data-tr=decision]').hidden);`);
  assert.deepEqual(await evaluate('approved'),[]);assert.equal(await evaluate('pending.at(-1)'),false);
  await evaluate(`document.querySelector('[data-tr=prepare]').click();waitFor(()=>!document.querySelector('[data-tr=decision]').hidden);`);
  await evaluate(`document.querySelector('[data-tr=accept]').click();waitFor(()=>approved.length===1);`);
  assert.equal((await evaluate('approved[0]')).variant,'donor_tex');
  assert.equal(await evaluate(`calls.some(c=>/rebuild|launch/.test(c.p))`),false);
 });
});

test('real 3D reference and donor remain visible while cage controls deform the fit',{skip:!process.env.GBOX_FIT_ASSETS},async()=>{
 const assets=process.env.GBOX_FIT_ASSETS,meta=JSON.parse(fs.readFileSync(path.join(assets,'metadata.json'),'utf8'));
 const routes={'/three.mjs':path.join(assets,'three/three.mjs'),'/examples/jsm/loaders/GLTFLoader.js':path.join(assets,'three/GLTFLoader.js'),'/examples/jsm/utils/BufferGeometryUtils.js':path.join(assets,'three/BufferGeometryUtils.js'),'/donor.glb':path.join(assets,'donor.glb'),'/stock.glb':path.join(assets,'stock.glb')};
 const server=http.createServer((req,res)=>{const file=routes[req.url];if(file){res.setHeader('Content-Type',file.endsWith('.glb')?'model/gltf-binary':'application/javascript');return res.end(fs.readFileSync(file));}res.setHeader('Content-Type','text/html');res.end('<!doctype html><script type="importmap">{"imports":{"three":"/three.mjs"}}</script><body></body>');});
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 try{await withPage(async(evaluate,send)=>{
  await send('Emulation.setDeviceMetricsOverride',{width:1440,height:980,deviceScaleFactor:1,mobile:false});
  await send('Page.navigate',{url:`http://127.0.0.1:${server.address().port}/`});
  for(let n=0;n<100;n++){if(await evaluate(`location.protocol==='http:' && document.readyState==='complete'`))break;await new Promise(r=>setTimeout(r,10));}
  await evaluate(`window.meta=${JSON.stringify(meta)};document.body.style='background:#16161a;color:#eee;font:14px system-ui';document.body.innerHTML='<header>gBox · Character fitting and texture review</header>';window.modules=Promise.all([import('/three.mjs'),import('/examples/jsm/loaders/GLTFLoader.js')]);void 0;`);
  for(const file of ['retarget-handles.js','texture-review.js','retarget-editor.js'])await evaluate(fs.readFileSync(path.join(__dirname,'../clients/web/viz',file),'utf8'));
  await evaluate(`window.saved=[];window.io={url:u=>u,api:async(p,body)=>{if(p.includes('/retarget_profile')){if(body)saved.push(body);return {slug:meta.donor.slug,name:meta.donor.name,rig_roles:meta.donor.rig.roles,model_url:'/donor.glb',resolved:body?.profile||{}};}if(p.includes('/retarget/reference'))return {reference:{...meta.stock,model_url:'/stock.glb'},exact:true};if(p.includes('/retarget/goals'))return {};if(p.includes('/cast_swap/sources'))return {slots:[{slot:'ped:1',name:'Police pedestrian'}]};if(p.endsWith('/texture-maps'))return {maps:[]};return {};},loadModules:async()=>{const [THREE,loader]=await modules;return {THREE,GLTFLoader:loader.GLTFLoader};}};
   window.editor=GBoxRetargetEditor.open(document,io,{slug:meta.donor.slug,gid:'002b9dca58a18ea1',title:'Liberty City Stories',slot:'ped:1'});window.waitFor=async fn=>{for(let n=0;n<600;n++){if(fn())return;await new Promise(r=>setTimeout(r,50));}throw Error('3D UI timeout: '+document.querySelector('[data-rt=status]').textContent);};waitFor(()=>editor.views.target?.renderer && editor.views.donor?.circles?.length);`);
  await evaluate(`editor.controller.setMode('shape');waitFor(()=>editor.views.donor.cage?.length===9);`);
  const points=await evaluate(`(()=>{const v=editor.views.donor,g=v.cage[4],p=v.map.toScreen(g.at),r=v.ov.getBoundingClientRect();return {x:r.left+p[0],y:r.top+p[1]};})()`);
  const before=await evaluate(`editor.views.target.group.children.filter(o=>o.isMesh).reduce((s,o)=>s+o.geometry.attributes.position.array.reduce((a,b)=>a+b,0),0)`);
  await send('Input.dispatchMouseEvent',{type:'mouseMoved',x:points.x,y:points.y});
  await send('Input.dispatchMouseEvent',{type:'mousePressed',x:points.x,y:points.y,button:'left',clickCount:1});
  await send('Input.dispatchMouseEvent',{type:'mouseMoved',x:points.x+20,y:points.y-10,button:'left',buttons:1});
  await send('Input.dispatchMouseEvent',{type:'mouseReleased',x:points.x+20,y:points.y-10,button:'left',clickCount:1});
  await evaluate(`new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));`);
  assert.ok(await evaluate(`Object.keys(editor.controller.state.profile.lattice?.offsets||{}).length`));
  const after=await evaluate(`editor.views.target.group.children.filter(o=>o.isMesh).reduce((s,o)=>s+o.geometry.attributes.position.array.reduce((a,b)=>a+b,0),0)`);
  assert.ok(Math.abs(after-before)>.001,'the rendered target mesh changes, not only the stored profile');
  await evaluate(`editor.controller.setValue('head',.85);editor.controller.save();`);
  assert.equal((await evaluate('saved.at(-1)')).profile.head,.85);
  assert.ok((await evaluate('saved.at(-1)')).profile.lattice);
  if(process.env.GBOX_FIT_EVIDENCE){
   await evaluate(`const details=document.querySelector('[data-rt-textures] details');details.open=true;const tag=document.createElement('div');tag.textContent='UI screenshot — owned DOA donor and GTA reference, live cage preview; offline fit, no gameplay verification';tag.style='position:fixed;bottom:0;left:0;right:0;padding:8px;background:#244974;color:white;z-index:2147483647;font:12px system-ui';document.body.append(tag);`);
   fs.mkdirSync(process.env.GBOX_FIT_EVIDENCE,{recursive:true});const shot=await send('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(process.env.GBOX_FIT_EVIDENCE,'shape-cage-editor.png'),Buffer.from(shot.result.data,'base64'));
  }
  await evaluate('editor.dispose();');
 },{softwareGL:true,timeoutMs:120000});}finally{await new Promise(r=>server.close(r));}
});
