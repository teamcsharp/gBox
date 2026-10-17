const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const S=require('../clients/web/viz/selfie-models.js');
const {withPage}=require('../scripts/browser_lifecycle.cjs');
const groups=[{photo:'a'.repeat(64),tag:'selfie:'+'a'.repeat(64),label:'Bla',url:'/api/artifacts/'+'a'.repeat(64),source_kind:'selfie',models:[
 {slug:'bla_leon',name:'Bla on Leon',model:'model.glb',source:{game_title:'RE4'},preview_url:'/preview',fitted_models:[{file:'targets/sm64.gltf',name:'Mario 64 fit',bytes:12000}]},
 {slug:'bla_edit',name:'Bla edited proportions',model:'model.glb',source:{game_title:'RE4'},preview_url:'/preview',fitted_models:[]}]},
 {photo:'b'.repeat(64),tag:'selfie:'+'b'.repeat(64),label:'Second image',url:'/b',source_kind:'generated',models:[{slug:'other',name:'Other avatar',model:'model.glb',source:{},preview_url:'/preview',fitted_models:[]}]}];
// Public test evidence uses drawings, never an operator's image or model.
const picture='data:image/svg+xml;base64,'+Buffer.from('<svg xmlns="http://www.w3.org/2000/svg" width="180" height="220"><rect width="180" height="220" fill="#243448"/><ellipse cx="90" cy="74" rx="34" ry="42" fill="#ddb58c"/><path d="M33 218v-53q0-38 57-38t57 38v53" fill="#7492b8"/><path d="M60 60q0-42 30-30t30 30" fill="#73503d"/><circle cx="78" cy="75" r="3"/><circle cx="102" cy="75" r="3"/><path d="M78 96q12 10 24 0" fill="none" stroke="#744838" stroke-width="3"/></svg>').toString('base64');
for(const g of groups){g.url=picture;for(const m of g.models)m.preview_url=picture;}

test('exact image grouping, fitted search and safe names/links',()=>{
 assert.equal(S.filter(groups,{photo:'b'.repeat(64)})[0].models[0].slug,'other');
 assert.equal(S.filter(groups,{q:'mario'})[0].models[0].slug,'bla_leon');
 assert.equal(S.filter(groups,{q:'missing'}).length,0);
 const rows=structuredClone(groups);rows[0].label='<script>unsafe</script>';
 const html=S.cards(rows);assert.ok(!html.includes('<script>unsafe'));
 assert.ok(html.includes('targets%2Fsm64.gltf'));assert.ok(html.includes('Download GLB'));
});

test('browser: live filters, named image tags, fitted export and rotating analysis preserve the selected asset',async()=>{
 await withPage(async(evaluate,send)=>{
  await send('Emulation.setDeviceMetricsOverride',{width:1100,height:900,deviceScaleFactor:1,mobile:false});
  await evaluate(fs.readFileSync(path.join(__dirname,'../clients/web/viz/selfie-models.js'),'utf8'));
  await evaluate(fs.readFileSync(path.join(__dirname,'../clients/web/viz/character-popup.js'),'utf8'));
  await evaluate(`document.head.insertAdjacentHTML('beforeend','<style>'+${JSON.stringify(fs.readFileSync(path.join(__dirname,'../clients/web/index.html'),'utf8').match(/<style>([\s\S]*?)<\/style>/)[1])}+'</style>');document.documentElement.dataset.embedded='true';`);
  await evaluate(`document.body.style='background:#16161a;color:#e8e8ee;font:14px system-ui;padding:16px;--card:#1f1f25;--line:#383840';document.body.innerHTML='<h2>Models · Selfies</h2><div id="host"></div>';var groups=${JSON.stringify(groups)},calls=[],copies=[],opened=[],disposed=0;
   var io={api:async(p,b)=>{calls.push({p,b});if(p==='/api/photo-skins/collections')return structuredClone(groups);if(p.endsWith('/label')){groups.find(g=>p.includes(g.photo)).label=b.label;return b;}if(p.includes('/export'))return {sha256:'c'.repeat(64)};if(p==='/api/characters/bla_leon')return {slug:'bla_leon',name:'Bla on Leon',model:'model.glb',source:{game_title:'RE4'}};throw Error(p);},url:u=>u,
   blender:async input=>copies.push(input),openModel:async o=>{opened.push(o);return GBoxCharacterPopup.open(o,{api:io.api,blender:async(s,o)=>copies.push({s,o}),loadViewer:async()=>({createCharacterViewer:async(stage,url)=>{stage.textContent='Synthetic rotating model';return {gltf:{scene:{traverse:fn=>fn({isMesh:true,geometry:{attributes:{position:{count:9}}},material:[]})}},dispose:()=>disposed++};}})});}};
   var state={},ctl=GBoxSelfieModels.mount(document.querySelector('#host'),io,state);ctl.ready;`);
  assert.equal(await evaluate(`document.querySelectorAll('.sm-model').length`),3);
  await evaluate(`var search=document.querySelector('[data-sm-search]');search.value='Mario';search.dispatchEvent(new Event('input'));`);
  assert.equal(await evaluate(`document.querySelectorAll('.sm-model').length`),1);
  await evaluate(`document.querySelector('[data-sm-act="blender"][data-sm-file="targets/sm64.gltf"]').click();new Promise(r=>setTimeout(r,20));`);
  assert.deepEqual(await evaluate('copies[0]'),{artifact:'c'.repeat(64)});
  assert.ok(await evaluate(`calls.some(c=>c.p.endsWith('/export?file=targets%2Fsm64.gltf'))`));
  await evaluate(`document.querySelector('[data-sm-act="inspect"][data-sm-file="targets/sm64.gltf"]').click();new Promise(r=>setTimeout(r,20));`);
  assert.equal(await evaluate(`document.querySelector('.cp-info').hidden`),false);
  assert.ok(await evaluate(`document.querySelector('.cp-info').textContent.includes('triangles: 3')`));
  assert.ok(await evaluate(`document.querySelector('[data-download]').getAttribute('href').endsWith('/download?file=targets%2Fsm64.gltf')`));
  await evaluate(`document.querySelector('[data-cp="close"]').click();search.value='';search.dispatchEvent(new Event('input'));var label=document.querySelector('[data-sm-label]');label.value='Bla portrait';document.querySelector('[data-sm-act="rename"]').click();new Promise(r=>setTimeout(r,20));`);
  assert.equal(await evaluate(`document.querySelector('.sm-heading h3').textContent`),'Bla portrait');
  assert.equal(await evaluate('disposed'),1);
  assert.equal(await evaluate(`calls.some(c=>c.p==='/api/jobs')`),false);
  if(process.env.GBOX_SELFIE_EVIDENCE){const shot=await send('Page.captureScreenshot',{format:'png'});fs.mkdirSync(process.env.GBOX_SELFIE_EVIDENCE,{recursive:true});fs.writeFileSync(path.join(process.env.GBOX_SELFIE_EVIDENCE,'selfie-models.png'),Buffer.from(shot.result.data,'base64'));}
  await evaluate(`ctl.dispose();document.body.innerHTML='';`);
 });
});

test('Models tab and game Models link use the same collection controller in the embedded web client',()=>{
 const html=fs.readFileSync(path.join(__dirname,'../clients/web/index.html'),'utf8');
 assert.ok(html.includes('Models: selfieModelsView'));assert.ok(html.includes('/viz/selfie-models.js'));
 assert.ok(html.includes('$("#models-selfies").onclick = () => show("Models")'));
 assert.ok(html.includes('SELFIE_MODELS.ctl?.dispose()'));
 assert.ok(html.includes('GBoxNativeFaceEditor.open({photo}'));
 assert.ok(html.includes('/viz/face-warp-editor.js'));
 assert.ok(html.includes('/viz/native-face-editor.js'));
 for(const m of html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g))if(!m[1].includes('src=')&&!m[1].includes('importmap'))new (require('node:vm').Script)(m[2]);
});

test('browser: deforming a selfie opens the exact source photo without queuing a build',async()=>{
 await withPage(async evaluate=>{
  await evaluate(fs.readFileSync(path.join(__dirname,'../clients/web/viz/selfie-models.js'),'utf8'));
  await evaluate(`document.body.innerHTML='<div id="faces"></div>';var edits=[],calls=[];var ctl=GBoxSelfieModels.mount(document.querySelector('#faces'),{
    api:async p=>{calls.push(p);return ${JSON.stringify(groups)};},editFace:photo=>edits.push(photo)});ctl.ready;`);
  await evaluate(`document.querySelector('[data-sm-act=face]').click();new Promise(r=>setTimeout(r,0));`);
  assert.deepEqual(await evaluate('edits'),['a'.repeat(64)]);
  assert.deepEqual(await evaluate('calls'),['/api/photo-skins/collections']);
  await evaluate('ctl.dispose()');
 });
});
