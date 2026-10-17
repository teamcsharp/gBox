const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {withPage}=require('../scripts/browser_lifecycle.cjs');
const contextSource=fs.readFileSync(path.join(__dirname,'../clients/web/viz/asset-context.js'),'utf8');
const detailSource=fs.readFileSync(path.join(__dirname,'../clients/web/viz/library-home-detail.js'),'utf8');

test('cover action requires an explicit game association and keeps original source bytes',async()=>{
 await withPage(async evaluate=>{
  await evaluate(contextSource);
  await evaluate(`document.body.innerHTML='<img id="loose" alt="Unassociated image"><img id="shot" src="/thumb.jpg?w=160" alt="Gameplay" data-asset-game="game-one" data-asset-original-url="/api/artifacts/original-jpeg"><img id="bound" alt="Bound image">';
   var saved=[],done;var ctl=GBoxAssetContext.mount(document,{image:async()=>{},blender:async()=>({}),cover:asset=>{saved.push({game_id:asset.game_id,url:asset.url,name:asset.name});return new Promise(resolve=>done=resolve);}});
   HTMLCanvasElement.prototype.getContext=()=>{throw Error('Cover must not use canvas');};
   var context=id=>document.querySelector(id).dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,cancelable:true,clientX:100,clientY:100}));context('#loose');`);
  assert.equal(await evaluate(`!!document.querySelector('[data-copy=cover]')`),false);
  await evaluate(`context('#shot');document.querySelector('[data-copy=cover]').click();document.querySelector('[data-copy=cover]').click();`);
  assert.deepEqual(await evaluate('saved'),[{game_id:'game-one',url:'/api/artifacts/original-jpeg',name:'Gameplay'}]);
  assert.equal(await evaluate(`document.querySelector('[data-copy=cover]').disabled`),true);
  await evaluate('done();new Promise(r=>setTimeout(r,0));');
  assert.equal(await evaluate(`document.querySelector('.gbox-asset-menu [role=status]').textContent`),'Game cover updated.');
  await evaluate(`GBoxAssetContext.bind(document.querySelector('#bound'),{game_id:'game-two',url:'/thumb.png',source_url:'/full.webp',name:'Bound image',format:'image'});context('#bound');document.querySelector('[data-copy=cover]').click();done();new Promise(r=>setTimeout(r,0));`);
  assert.deepEqual(await evaluate('saved[1]'),{game_id:'game-two',url:'/full.webp',name:'Bound image'});
  await evaluate('ctl.dispose()');
 });
});

test('cover failures remain visible and retryable; model and normal game menus keep their behavior',async()=>{
 await withPage(async evaluate=>{
  await evaluate(contextSource);
  await evaluate(`document.body.innerHTML='<img id="shot" src="/shot.png" data-asset-game="game-one"><div id="model"><img></div><div class="card" data-gid="game-one"><img id="game" data-asset-game="game-one"></div>';var tries=0,gameMenus=0;
   var ctl=GBoxAssetContext.mount(document,{cover:async()=>{tries++;throw Error('Storage offline');}});document.querySelector('.card').addEventListener('contextmenu',e=>{e.preventDefault();gameMenus++;});
   var context=id=>document.querySelector(id).dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,cancelable:true,clientX:100,clientY:100}));context('#shot');document.querySelector('[data-copy=cover]').click();new Promise(r=>setTimeout(r,0));`);
  assert.equal(await evaluate(`document.querySelector('.gbox-asset-menu [role=status]').textContent`),'Could not set game cover: Storage offline');
  assert.equal(await evaluate(`document.querySelector('[data-copy=cover]').disabled`),false);
  await evaluate(`document.querySelector('[data-copy=cover]').click();new Promise(r=>setTimeout(r,0));`);assert.equal(await evaluate('tries'),2);
  await evaluate(`GBoxAssetContext.bind(document.querySelector('#model'),{game_id:'game-one',url:'/model.glb',format:'glb'});context('#model img');`);
  assert.equal(await evaluate(`!!document.querySelector('[data-copy=cover]')`),false);
  await evaluate(`context('#game');`);assert.equal(await evaluate('gameMenus'),1);assert.equal(await evaluate(`!!document.querySelector('.gbox-asset-menu')`),false);
  await evaluate('ctl.dispose()');
 });
});

test('Home info gallery, build images and expanded images explicitly target their title and original source',async()=>{
 await withPage(async evaluate=>{
  await evaluate(contextSource);await evaluate(detailSource);
  const picture='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aCRsAAAAASUVORK5CYII=';
  const data={game:{game_id:'a'.repeat(16),title:'Example'},media:[{kind:'image',url:picture,original_url:'/full.jpg',label:'Game capture'}],builds:[{name:'swap',images:[{url:picture,original_url:'/build-full.png'}]}],models:[{name:'Model preview',slug:'model',format:'png',preview_url:picture}]};
  await evaluate(`document.body.innerHTML='<main id="detail"></main>';var saved=[];var menu=GBoxAssetContext.mount(document,{cover:async a=>saved.push({game_id:a.game_id,url:a.url})});var ctl=GBoxHomeDetail.mount(document.querySelector('#detail'),${JSON.stringify(data)},{});ctl.ready;`);
  assert.equal(await evaluate(`document.querySelector('[data-ghd-media] img').dataset.assetGame`),data.game.game_id);
  assert.equal(await evaluate(`document.querySelector('.ghd-build-image').dataset.assetOriginalUrl`),'/build-full.png');
  assert.equal(await evaluate(`document.querySelector('[data-ghd-model-card] img').dataset.assetGame`),data.game.game_id);
  await evaluate(`document.querySelector('[data-ghd-media]').click();var expanded=document.querySelector('dialog img');expanded.dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,cancelable:true,clientX:100,clientY:100}));document.querySelector('dialog [data-copy=cover]').click();new Promise(r=>setTimeout(r,0));`);
  assert.equal(await evaluate(`document.querySelector('dialog img').getAttribute('src')`),'/full.jpg');
  assert.deepEqual(await evaluate('saved'),[{game_id:data.game.game_id,url:'/full.jpg'}]);
  await evaluate('menu.dispose();ctl.dispose()');
 });
});
