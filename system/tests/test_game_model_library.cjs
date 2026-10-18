const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {withPage}=require('../scripts/browser_lifecycle.cjs');
const source=fs.readFileSync(path.join(__dirname,'../clients/web/viz/game-model-library.js'),'utf8');
const sandbox={};vm.runInNewContext(source,sandbox);
const summarize=x=>JSON.parse(JSON.stringify(sandbox.GBoxGameModelLibrary.gamesFromModels(x)));
function model(gid,added,extra={}){return {slug:gid+'-'+added,model:'model.glb',model_bytes:100,added,source:{game_id:gid,game_title:gid,platform:'GameCube'},...extra};}
test('only available models with exact game identities contribute; latest recorded addition orders titles',()=>{
 const input=[model('older',10),model('newer',30),model('older',40),model('unknown',null),model('missing',100,{model_bytes:0}),model('bad',90,{model_bytes:'12'}),model('photo',200,{source:{}}),model('newer',30),model('negative',-3),model('infinite',Infinity)];
 const games=summarize(input);
 assert.deepEqual(games.map(g=>g.game_id),['older','newer','infinite','negative','unknown']);
 assert.equal(games[0].count,2);assert.equal(games[1].count,1);assert.equal(games[2].added,null);
 assert.deepEqual(summarize(null),[]);
});
test('equal names from different games stay separate and unknown timestamps sort deterministically',()=>{
 const games=summarize([model('b',null,{source:{game_id:'b',game_title:'Same title'}}),model('a',null,{source:{game_id:'a',game_title:'Same title'}})]);
 assert.deepEqual(games.map(g=>g.game_id),['a','b']);assert.equal(games[0].added,null);
});
test('browser: extracted games scroll by recency, search and filter, and choose models without launch or catalog calls',async()=>{
 await withPage(async(evaluate,send)=>{
  await send('Emulation.setDeviceMetricsOverride',{width:1100,height:900,deviceScaleFactor:1,mobile:false});
  await evaluate(source);
  const models=Array.from({length:203},(_,i)=>model('id'+i,1000+i,{source:{game_id:'id'+i,game_title:'Game '+String(i).padStart(3,'0'),platform:i%2?'Dreamcast':'GameCube'}}));
  models.push(model('not-extracted',99999,{model_bytes:0}));models[0].source.game_title='<img src=x onerror=alert(1)>';
  await evaluate(`document.body.style='background:#16161a;color:#eee;font:14px system-ui';document.body.innerHTML='<button id="opener">Game library</button>';document.querySelector('#opener').focus();var calls=[],opened=[],state={},models=${JSON.stringify(models)};var io={api:async p=>{calls.push(p);return models},openGame:(id,title)=>opened.push({id,title})};var ctl=GBoxGameModelLibrary.open(io,state);ctl.ready;`);
  assert.equal(await evaluate(`document.querySelectorAll('.gml-game').length`),100);
  assert.equal(await evaluate(`document.querySelector('.gml-game strong').textContent`),'Game 202');
  await evaluate(`var list=document.querySelector('.gml-scroll');list.scrollTop=list.scrollHeight;list.dispatchEvent(new Event('scroll'));`);
  assert.equal(await evaluate(`document.querySelectorAll('.gml-game').length`),200);
  await evaluate(`document.querySelector('.gml-more').click()`);
  assert.equal(await evaluate(`document.querySelectorAll('.gml-game').length`),203);
  assert.equal(await evaluate(`document.querySelector('.gml-game img')`),null);
  assert.equal(await evaluate(`document.querySelector('.gml-more').hidden`),true);
  await evaluate(`var search=document.querySelector('[data-gml-search]');search.value='game 20';search.dispatchEvent(new Event('input'));new Promise(r=>setTimeout(r,250));`);
  assert.equal(await evaluate(`document.querySelectorAll('.gml-game').length`),3);
  await evaluate(`var platform=document.querySelector('[data-gml-platform]');platform.value='Dreamcast';platform.dispatchEvent(new Event('change'));`);
  assert.equal(await evaluate(`document.querySelectorAll('.gml-game').length`),1);
  await evaluate(`document.querySelector('.gml-game').click()`);
  assert.deepEqual(await evaluate('opened'),[{id:'id201',title:'Game 201'}]);
  assert.equal(await evaluate(`document.activeElement.id`),'opener');
  await evaluate(`var ctl=GBoxGameModelLibrary.open(io,state);ctl.ready;`);
  assert.equal(await evaluate(`document.querySelector('[data-gml-search]').value`),'game 20');
  await evaluate(`document.querySelector('dialog').dispatchEvent(new Event('cancel',{cancelable:true}));state={};ctl=GBoxGameModelLibrary.open(io,state);ctl.ready;`);
  if(process.env.GBOX_MODEL_LIBRARY_EVIDENCE){const shot=await send('Page.captureScreenshot',{format:'png'});fs.writeFileSync(process.env.GBOX_MODEL_LIBRARY_EVIDENCE,Buffer.from(shot.result.data,'base64'));}
  assert.deepEqual(await evaluate('calls'),['/api/characters','/api/characters','/api/characters']);
  await evaluate('ctl.close()');
 });
});
test('browser: search during initial load, retry, empty state and stale closed responses',async()=>{
 await withPage(async evaluate=>{
  await evaluate(source);
  await evaluate(`var pending=[],opened=[];var io={api:p=>new Promise((resolve,reject)=>pending.push({resolve,reject})),openGame:(...a)=>opened.push(a)};var state={},ctl=GBoxGameModelLibrary.open(io,state);var search=document.querySelector('[data-gml-search]');search.value='New';search.dispatchEvent(new Event('input'));new Promise(r=>setTimeout(r,250));`);
  await evaluate(`pending[0].resolve(${JSON.stringify([model('New',20),model('Old',10)])});ctl.ready;`);
  assert.equal(await evaluate(`document.querySelectorAll('.gml-game').length`),1);
  assert.equal(await evaluate(`document.querySelector('.gml-game strong').textContent`),'New');
  await evaluate(`ctl.close();ctl=GBoxGameModelLibrary.open(io,{});pending[1].reject(Error('Offline'));ctl.ready;`);
  assert.match(await evaluate(`document.querySelector('[data-gml-status]').textContent`),/Offline/);
  await evaluate(`document.querySelector('.gml-more').click();pending[2].resolve([]);new Promise(r=>setTimeout(r,0));`);
  assert.match(await evaluate(`document.querySelector('[data-gml-status]').textContent`),/No extracted game models yet/);
  await evaluate(`ctl.close();ctl=GBoxGameModelLibrary.open(io,{});ctl.close();ctl=GBoxGameModelLibrary.open(io,{});pending[4].resolve(${JSON.stringify([model('Current',30)])});ctl.ready;pending[3].resolve(${JSON.stringify([model('Late',40)])});new Promise(r=>setTimeout(r,0));`);
  assert.equal(await evaluate(`document.querySelector('.gml-game strong').textContent`),'Current');
  await evaluate('ctl.close()');
 });
});
test('Models button and return action keep the exact game model route',()=>{
 const html=fs.readFileSync(path.join(__dirname,'../clients/web/index.html'),'utf8');
 assert.ok(html.includes("$('#selfie-library').onclick=openGameModelLibrary"));
 assert.ok(html.includes('$("#models-back").onclick = openGameModelLibrary'));
 assert.ok(html.includes('openGame:(gid,title)=>show("GameModels",gid,title)'));
});
