const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const {withPage}=require('../scripts/browser_lifecycle.cjs');
const web=fs.readFileSync(path.join(__dirname,'../clients/web/index.html'),'utf8');
const cardHandler=web.match(/document\.addEventListener\("contextmenu", e => \{\s*const c = e\.target\.closest\("\.card\[data-gid\]"\)[\s\S]*?\n\}\);/)[0];
const reportStart=web.indexOf('document.addEventListener("contextmenu", e => {');
const reportHandler=web.slice(reportStart,web.indexOf('document.addEventListener("mousedown"',reportStart));

test('game cover, title and blank art retain mods and launch choices while assets keep their copy menu',async()=>{
 await withPage(async(evaluate,send)=>{
  await send('Emulation.setDeviceMetricsOverride',{width:1440,height:900,deviceScaleFactor:1,mobile:false});
  await evaluate(`document.head.innerHTML=${JSON.stringify(web.match(/<style>([\s\S]*?)<\/style>/)[0])};
   document.body.innerHTML='<header>gBox context menu regression fixture</header><main><div class="grid"><div class="card" data-gid="game-one" data-title="Game one"><div class="art"><img alt="Game one cover"></div><div class="meta"><b>Game one</b><button>Play</button></div></div><div class="card" data-gid="game-two" data-title="Game two"><div class="art">no artwork</div><div class="meta"><b>Game two</b></div></div></div><div class="game-model-card" id="sprite"><img alt="Sprite asset"></div><div class="mg-card" id="mod-card"><img alt="Build cover"></div><div data-bv-key="build-one" id="build-row"><img alt="Build thumbnail"></div><div class="tchip" id="session-chip"><img alt="Session thumbnail"></div></main><div id="gmenu" role="menu"></div>';
   window.$=s=>document.querySelector(s);window.esc=s=>String(s);window.plays=[];window.boots={};window.copies=[];window.owned=[];
   window.contextAt=selector=>{const target=document.querySelector(selector);return target.dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,cancelable:true,clientX:400,clientY:360}));};
   window.gameMenuIO=()=>({el:$('#gmenu'),worker:'Fixture PC',api:async p=>p.startsWith('/api/characters')?[]:p.startsWith('/api/mods')?[{id:'sonic',title:'Sonic player sprites',calls:[{tool:'@launch',input:{mod:'sonic_disc'}}]},{id:'jump',title:'Moon jump',calls:[{tool:'poke'}]}]:{groups:[]},
    boot:{get:gid=>boots[gid]||{disc:'',slot:'',character:''},set:(gid,b)=>boots[gid]=b},keep:{get:()=>[],set(){}},badge(){},img:u=>u,
    place:(el,x,y)=>{el.style.left=x+'px';el.style.top='100px';},refit(){},models(){},cover(){},cast(){},
    play:(gid,mode)=>plays.push({gid,mode,disc:boots[gid]?.disc||''})});
   window.fixtureCanvas=document.createElement('canvas');fixtureCanvas.width=24;fixtureCanvas.height=32;fixtureCanvas.getContext('2d').fillRect(2,2,20,28);window.fixtureImage=fixtureCanvas.toDataURL();
   document.querySelectorAll('img').forEach(im=>im.src=fixtureImage);
   Promise.all([...document.images].map(im=>im.decode()));`);
  await evaluate(fs.readFileSync(path.join(__dirname,'../clients/web/viz/game-menu.js'),'utf8'));
  // Match production registration order: existing bubble handlers first, then
  // the generic asset listener, which runs earlier in capture phase.
  await evaluate(reportHandler+'\n'+cardHandler);
  await evaluate(`for(const selector of ['#mod-card','#build-row','#session-chip'])document.querySelector(selector).addEventListener('contextmenu',e=>{e.preventDefault();e.stopPropagation();owned.push(selector);});`);
  await evaluate(fs.readFileSync(path.join(__dirname,'../clients/web/viz/asset-context.js'),'utf8'));
  await evaluate(`GBoxAssetContext.mount(document,{image:async png=>copies.push(png),blender:async()=>({}),sourceBase:'http://fixture.test/'});`);
  for(const selector of ['.card[data-gid="game-one"] img','.card[data-gid="game-one"] .art','.card[data-gid="game-one"] b','.card[data-gid="game-one"] button','.card[data-gid="game-two"] .art']){
   await evaluate(`contextAt(${JSON.stringify(selector)});new Promise(r=>setTimeout(r,0));`);
   const state=await evaluate(`({game:$('#gmenu h4').textContent,open:$('#gmenu').classList.contains('on'),assets:document.querySelectorAll('.gbox-asset-menu').length,report:!!$('#issuemenu'),mods:!!$('#gmenu input[value="sonic_disc"]'),original:!!$('#gmenu [data-go="plain"]'),spark:!!$('#gmenu [data-go="linux"]')})`);
   assert.deepEqual(state,{game:selector.includes('game-two')?'Game two':'Game one',open:true,assets:0,report:false,mods:true,original:true,spark:true},selector);
  }
  await evaluate(`contextAt('.card[data-gid="game-one"] img');new Promise(r=>setTimeout(r,0));`);
  await evaluate(`const disc=$('#gmenu input[value="sonic_disc"]');disc.checked=true;disc.dispatchEvent(new Event('change',{bubbles:true}));$('#gmenu [data-go=""]').click();`);
  assert.deepEqual(await evaluate('plays[0]'),{gid:'game-one',mode:'',disc:'sonic_disc'},'Play uses the selected boot mod');
  for(const mode of ['plain','linux']){
   await evaluate(`contextAt('.card[data-gid="game-one"] img');$('#gmenu [data-go="${mode}"]').click();`);
  }
  assert.deepEqual(await evaluate('plays.map(p=>p.mode)'),['','plain','linux'],'original and Spark launch choices still dispatch');
  // A sprite gallery card is still an asset, not a game entry.
  await evaluate(`contextAt('#sprite img');document.querySelector('[data-copy=image]').click();new Promise(r=>setTimeout(r,0));`);
  assert.match(await evaluate('copies[0]'),/^data:image\/png;base64,/);
  assert.ok(await evaluate(`!!document.querySelector('.gbox-asset-menu [data-copy=image_plane]')`));
  assert.ok(await evaluate(`!!document.querySelector('.gbox-asset-menu [data-copy=image_empty]')`));
  // Keyboard context menus need no pointerdown to dismiss a stale asset menu.
  await evaluate(`contextAt('.card[data-gid="game-one"] img');`);
  assert.equal(await evaluate(`document.querySelectorAll('.gbox-asset-menu').length`),0);
  await evaluate(`for(const selector of ['#mod-card img','#build-row img','#session-chip img'])contextAt(selector);`);
  assert.deepEqual(await evaluate('owned'),['#mod-card','#build-row','#session-chip']);
  assert.equal(await evaluate(`document.querySelectorAll('.gbox-asset-menu').length`),0);
 });
});
