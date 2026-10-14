const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const http=require('node:http');
const {withPage}=require('../scripts/browser_lifecycle.cjs');
const web=fs.readFileSync(path.join(__dirname,'../clients/web/index.html'),'utf8');
async function assetPage(fn){
 const server=http.createServer((req,res)=>{res.setHeader('Content-Type','text/html');res.end('<!doctype html><body></body>');});
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 try{return await withPage(async(evaluate,send)=>{
  await send('Page.navigate',{url:`http://127.0.0.1:${server.address().port}/`});
  for(let n=0;n<100;n++){if(await evaluate(`location.protocol==='http:' && document.readyState==='complete'`))break;await new Promise(r=>setTimeout(r,10));}
  return fn(evaluate,send);
 });}finally{await new Promise(r=>server.close(r));}
}

test('animation list scrolls independently beside a visible preview, and clip selection updates Blender copy source',async()=>{
 await assetPage(async(evaluate,send)=>{
  await send('Emulation.setDeviceMetricsOverride',{width:1440,height:900,deviceScaleFactor:1,mobile:false});
  await evaluate(`document.documentElement.dataset.embedded='true';document.head.innerHTML=${JSON.stringify(web.match(/<style>([\s\S]*?)<\/style>/)[0])};document.body.innerHTML='<header><b>gBox</b> · Library · Models</header><main id="view"></main>';window.tabs={};window.GAME_MODELS={models:[],selection:0};window.$=s=>document.querySelector(s);window.esc=s=>String(s||'').replaceAll('<','&lt;');window.tq=()=>'';window.viewRevision=1;`);
  await evaluate(fs.readFileSync(path.join(__dirname,'../clients/web/viz/clip-player.js'),'utf8'));
  await evaluate(fs.readFileSync(path.join(__dirname,'../clients/web/viz/asset-context.js'),'utf8'));
  const start=web.indexOf('const gameModelTile ='),end=web.indexOf('// ---------------- loading screen',start);
  await evaluate(web.slice(start,end));
  await evaluate(`window.pic=document.createElement('canvas');pic.width=24;pic.height=32;let g=pic.getContext('2d');g.fillStyle='#506cff';g.fillRect(4,2,16,16);g.fillRect(6,18,12,10);g.fillStyle='#f3cba9';g.fillRect(9,8,10,8);g.fillStyle='white';g.fillRect(12,5,6,6);g.fillStyle='#1c2233';g.fillRect(15,7,2,3);g.fillStyle='#e74434';g.fillRect(2,27,10,5);g.fillRect(14,27,10,5);window.picture=pic.toDataURL();window.meta={slug:'fixture-sprite',name:'Sprite preview',model:'overview.png',kind:'sprites',source:{game_id:'fixture',game_title:'Animation sidebar demonstration'},preview_url:picture,animations:Array.from({length:60},(_,i)=>({clip:'clip-'+i,name:['Idle','Walk','Run','Jump'][i%4]+' '+(i+1),preview:'clip-'+i+'.apng',mp4:'clip-'+i+'.mp4',frames:12,fps:60}))};window.api=async()=>[meta];tabs.GameModels('fixture','Animation sidebar demonstration').then(html=>document.querySelector('#view').innerHTML=html);`);
  await evaluate(`tabs.GameModels.after('fixture','Animation sidebar demonstration');window.oldPanel=$('#model-clips');window.oldUI=GBoxClips.mount(oldPanel,[{kind:'3d',name:'Slow old clip'}],{load:()=>new Promise((yes,no)=>window.rejectOld=no)});oldUI.select(0);$('.game-model-card').click();rejectOld(Error('late old-model failure'));new Promise(r=>setTimeout(r,10));`);
  assert.equal(await evaluate(`oldPanel.isConnected`),false,'model selection replaces the clip panel');
  assert.equal(await evaluate(`$('#model-clips').textContent.includes('late old-model failure')`),false,'old clip replies cannot overwrite the new model');
  assert.equal(await evaluate(`document.querySelectorAll('#model-clips').length`),1);
  await evaluate(`window.preview=$('#game-model-preview');preview.innerHTML='<img style="height:100%;width:100%;object-fit:contain;image-rendering:pixelated" src="'+picture+'">';window.clips=modelClips(meta,null,rel=>rel.endsWith('.mp4')?'/api/characters/fixture/file/'+rel:picture,preview);clips.select(0);`);
  const before=await evaluate(`(()=>{let p=preview.getBoundingClientRect(),s=$('#model-clips').getBoundingClientRect(),list=$('.gbc-list');return {preview:{x:p.x,y:p.y,right:p.right,height:p.height},side:{x:s.x,y:s.y,height:s.height},list:{height:list.clientHeight,scroll:list.scrollHeight},page:scrollY};})()`);
  assert.ok(before.side.x>=before.preview.right,'sidebar is next to the preview');
  assert.ok(Math.abs(before.side.height-before.preview.height)<2,'matching pane heights');
  assert.ok(before.list.scroll>before.list.height,'clip list has its own scrolling');
  assert.ok(before.list.height>before.side.height*0.65,'list fills the sidebar instead of retaining the old 180px cap');
  await evaluate(`document.querySelector('.game-model-card img').src=picture;`);
  await evaluate(`$('.gbc-q').value='Jump';$('.gbc-q').dispatchEvent(new Event('input',{bubbles:true}));`);
  assert.equal(await evaluate(`[...document.querySelectorAll('.gbc-row')].filter(b=>getComputedStyle(b).display!=='none').length`),15,'filter hides nonmatching rows despite flex styling');
  await evaluate(`$('.gbc-q').value='';$('.gbc-q').dispatchEvent(new Event('input',{bubbles:true}));`);
  await evaluate(`$('.gbc-list').scrollTop=10000;clips.select(59);`);
  assert.deepEqual(await evaluate(`({y:preview.getBoundingClientRect().y,page:scrollY})`),{y:before.preview.y,page:before.page});
  assert.equal(await evaluate(`GBoxAssetContext.find(preview.querySelector('img')).mp4`),'/api/characters/fixture/file/clip-59.mp4');
  await evaluate(`window.inputs=[];window.images=[];GBoxAssetContext.mount(document,{blender:async input=>{inputs.push(input);return {host:'Fixture PC'};},image:async data=>images.push(data)});preview.querySelector('img').dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,cancelable:true,clientX:900,clientY:240}));`);
  assert.equal(await evaluate(`document.querySelectorAll('.gbox-asset-menu [data-copy]').length`),4);
  await evaluate(`document.querySelector('[data-copy=movie_plane]').click();new Promise(r=>setTimeout(r,20));`);
  assert.deepEqual(await evaluate('inputs[0]'),{asset_url:'/api/characters/fixture/file/clip-59.mp4',paste_as:'movie_plane'});
  await evaluate(`document.querySelector('[data-copy=image_empty]').click();new Promise(r=>setTimeout(r,20));`);
  assert.equal(await evaluate('inputs[1].paste_as'),'image_empty');
  assert.ok((await evaluate('inputs[1].image_b64')).length>20);
  await evaluate(`document.querySelector('[data-copy=image_plane]').click();new Promise(r=>setTimeout(r,20));`);
  await evaluate(`document.querySelector('[data-copy=image]').click();new Promise(r=>setTimeout(r,20));`);
  assert.equal(await evaluate('inputs[2].paste_as'),'image_plane');
  assert.match(await evaluate('images[0]'),/^data:image\/png;base64,/);
  if(process.env.GBOX_ANIMATION_EVIDENCE){
   await evaluate(`document.querySelector('.gbox-asset-menu [role=status]').textContent='Choose a Blender paste format for the selected animation.';const tag=document.createElement('div');tag.textContent='UI screenshot — synthetic sprite and clip metadata; real UI, no emulator or operator clipboard';tag.style='position:fixed;bottom:0;left:0;right:0;padding:8px;background:#244974;color:white;z-index:2147483647;font:12px system-ui';document.body.append(tag);`);
   fs.mkdirSync(process.env.GBOX_ANIMATION_EVIDENCE,{recursive:true});const shot=await send('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(process.env.GBOX_ANIMATION_EVIDENCE,'animation-sidebar-clipboard.png'),Buffer.from(shot.result.data,'base64'));
  }
  for(const width of [980,700]){
   await send('Emulation.setDeviceMetricsOverride',{width,height:800,deviceScaleFactor:1,mobile:false});
   const fit=await evaluate(`(()=>{let p=preview.getBoundingClientRect(),s=$('#model-clips').getBoundingClientRect();return {right:s.right,width:innerWidth,beside:s.left>=p.right,preview:p.width};})()`);
   assert.ok(fit.beside && fit.preview>100 && fit.right<=fit.width,'sidebar remains beside preview in narrower windows');
  }
 });
});

test('asset menus keep authenticated URLs out of queued jobs and leave game reports alone',async()=>{
 await assetPage(async evaluate=>{
  await evaluate(fs.readFileSync(path.join(__dirname,'../clients/web/viz/asset-context.js'),'utf8'));
  await evaluate(`document.body.innerHTML='<div id="asset" data-asset-url="/api/assets/m/file?token=private" data-asset-format="GLB" data-asset-name="Model"><canvas></canvas></div><img class="screen" src="data:image/png;base64,iVBORw0KGgo=">';window.inputs=[];window.legacy=0;GBoxAssetContext.mount(document,{blender:async i=>{inputs.push(i);return {};}});document.addEventListener('contextmenu',()=>legacy++);document.querySelector('canvas').dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,cancelable:true}));document.querySelector('[data-copy=model]').click();new Promise(r=>setTimeout(r,10));`);
  assert.deepEqual(await evaluate('inputs'),[{asset_url:'/api/assets/m/file'}]);
  assert.equal(await evaluate('legacy'),0,'generic report menu does not also open');
  await evaluate(`document.querySelector('img').dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,cancelable:true}));`);
  assert.equal(await evaluate('legacy'),1,'game surfaces retain their existing menu');
  await evaluate(`document.querySelector('#asset').dataset.assetUrl='https://evil.example/api/assets/m/file';document.querySelector('canvas').dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,cancelable:true}));document.querySelector('[data-copy=model]').click();new Promise(r=>setTimeout(r,10));`);
  assert.equal(await evaluate('inputs.length'),1);
  assert.match(await evaluate(`document.querySelector('.gbox-asset-menu [role=status]').textContent`),/must come from/);
  await evaluate(`window.dialog=document.createElement('dialog');dialog.innerHTML='<img src="data:image/png;base64,iVBORw0KGgo=">';document.body.append(dialog);dialog.showModal();dialog.querySelector('img').dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,cancelable:true}));`);
  assert.equal(await evaluate(`!!dialog.querySelector('.gbox-asset-menu')`),true,'the menu stays in a modal dialog top layer');
 });
});
