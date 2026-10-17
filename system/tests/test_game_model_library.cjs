const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {withPage}=require('../scripts/browser_lifecycle.cjs');
const source=fs.readFileSync(path.join(__dirname,'../clients/web/viz/game-model-library.js'),'utf8');
test('browser: scroll all games, search and filter, select exact title for models only',async()=>{
 await withPage(async(evaluate,send)=>{
  await send('Emulation.setDeviceMetricsOverride',{width:1100,height:900,deviceScaleFactor:1,mobile:false});
  await evaluate(source);
  await evaluate(`document.body.style='background:#16161a;color:#eee;font:14px system-ui';document.body.innerHTML='<button id="opener">Game library</button>';document.querySelector('#opener').focus();var calls=[],opened=[],state={},games=Array.from({length:203},(_,i)=>({game_id:'id'+i,title:'Game '+String(i).padStart(3,'0'),platform:i%2?'Dreamcast':'GameCube'}));games[0].title='<img src=x onerror=alert(1)>';
   var io={api:async p=>{calls.push(p);if(p.endsWith('/facets'))return {platforms:{Dreamcast:100,GameCube:103}};var u=new URL(p,'http://test'),q=u.searchParams.get('q'),plat=u.searchParams.get('platform'),offset=+u.searchParams.get('offset');var found=games.filter(g=>(!q||g.title.includes(q))&&(!plat||g.platform===plat));return {total:found.length,items:found.slice(offset,offset+100)};},openGame:(id,title)=>opened.push({id,title})};var ctl=GBoxGameModelLibrary.open(io,state);Promise.all([ctl.ready,ctl.facets]);`);
  assert.equal(await evaluate(`document.querySelectorAll('.gml-game').length`),100);
  assert.equal(await evaluate(`document.querySelector('.gml-game img')`),null);
  await evaluate(`var list=document.querySelector('.gml-scroll');list.scrollTop=list.scrollHeight;list.dispatchEvent(new Event('scroll'));new Promise(r=>setTimeout(r,30));`);
  assert.equal(await evaluate(`document.querySelectorAll('.gml-game').length`),200);
  await evaluate(`document.querySelector('.gml-more').click();new Promise(r=>setTimeout(r,30));`);
  assert.equal(await evaluate(`document.querySelectorAll('.gml-game').length`),203);
  assert.equal(await evaluate(`document.querySelector('.gml-more').hidden`),true);
  await evaluate(`var search=document.querySelector('[data-gml-search]');search.value='Game 20';search.dispatchEvent(new Event('input'));new Promise(r=>setTimeout(r,250));`);
  assert.equal(await evaluate(`document.querySelectorAll('.gml-game').length`),3);
  await evaluate(`var platform=document.querySelector('[data-gml-platform]');platform.value='Dreamcast';platform.dispatchEvent(new Event('change'));new Promise(r=>setTimeout(r,30));`);
  assert.equal(await evaluate(`document.querySelectorAll('.gml-game').length`),1);
  await evaluate(`document.querySelector('.gml-game').click()`);
  assert.deepEqual(await evaluate('opened'),[{id:'id201',title:'Game 201'}]);
  assert.equal(await evaluate(`document.activeElement.id`),'opener');
  await evaluate(`var ctl=GBoxGameModelLibrary.open(io,state);Promise.all([ctl.ready,ctl.facets]);`);
  assert.equal(await evaluate(`document.querySelector('[data-gml-search]').value`),'Game 20');
  await evaluate(`document.querySelector('dialog').dispatchEvent(new Event('cancel',{cancelable:true}));state={};ctl=GBoxGameModelLibrary.open(io,state);Promise.all([ctl.ready,ctl.facets]);`);
  if(process.env.GBOX_MODEL_LIBRARY_EVIDENCE){const shot=await send('Page.captureScreenshot',{format:'png'});fs.writeFileSync(process.env.GBOX_MODEL_LIBRARY_EVIDENCE,Buffer.from(shot.result.data,'base64'));}
  assert.ok((await evaluate('calls')).every(p=>p.startsWith('/api/catalog')));
  await evaluate('ctl.close()');
 });
});
test('browser: stale responses, retry and closing during load',async()=>{
 await withPage(async evaluate=>{
  await evaluate(source);
  await evaluate(`var pending=[],opened=[];var ctl=GBoxGameModelLibrary.open({api:p=>p.endsWith('/facets')?Promise.resolve({platforms:{}}):new Promise((resolve,reject)=>pending.push({resolve,reject})),openGame:(...a)=>opened.push(a)});var search=document.querySelector('[data-gml-search]');search.value='new';search.dispatchEvent(new Event('input'));new Promise(r=>setTimeout(r,250));`);
  await evaluate(`pending[1].resolve({total:1,items:[{game_id:'new',title:'New'}]});new Promise(r=>setTimeout(r,0));`);
  await evaluate(`pending[0].resolve({total:1,items:[{game_id:'old',title:'Old'}]});new Promise(r=>setTimeout(r,0));`);
  assert.equal(await evaluate(`document.querySelector('.gml-game strong').textContent`),'New');
  await evaluate(`search.value='empty';search.dispatchEvent(new Event('input'));new Promise(r=>setTimeout(r,250));`);
  await evaluate(`pending[2].reject(Error('Offline'));new Promise(r=>setTimeout(r,0));`);
  assert.ok(await evaluate(`document.querySelector('[data-gml-status]').textContent.includes('Offline')`));
  await evaluate(`document.querySelector('.gml-more').click();pending[3].resolve({total:0,items:[]});new Promise(r=>setTimeout(r,0));`);
  assert.equal(await evaluate(`document.querySelector('[data-gml-status]').textContent`),'No games match your search.');
  await evaluate(`search.value='closing';search.dispatchEvent(new Event('input'));new Promise(r=>setTimeout(r,250));`);
  await evaluate(`ctl.close();pending[4].resolve({total:1,items:[{game_id:'late',title:'Late'}]});new Promise(r=>setTimeout(r,0));`);
  assert.equal(await evaluate(`document.querySelector('dialog')`),null);
 });
});
test('Models button and return action open the model picker',()=>{
 const html=fs.readFileSync(path.join(__dirname,'../clients/web/index.html'),'utf8');
 assert.ok(html.includes("$('#selfie-library').onclick=openGameModelLibrary"));
 assert.ok(html.includes('$("#models-back").onclick = openGameModelLibrary'));
 assert.ok(html.includes('openGame:(gid,title)=>show("GameModels",gid,title)'));
});

