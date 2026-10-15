const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const Detail=require('../clients/web/viz/library-home-detail.js');
const {withPage}=require('../scripts/browser_lifecycle.cjs');
const source=fs.readFileSync(path.join(__dirname,'../clients/web/viz/library-home-detail.js'),'utf8');
const appStyles=fs.readFileSync(path.join(__dirname,'../clients/web/index.html'),'utf8').match(/<style>([\s\S]*?)<\/style>/)[1];
const illustration='data:image/svg+xml;base64,'+Buffer.from('<svg xmlns="http://www.w3.org/2000/svg" width="384" height="268"><defs><linearGradient id="b" x2="1" y2="1"><stop stop-color="#253966"/><stop offset="1" stop-color="#815d9a"/></linearGradient></defs><rect width="384" height="268" fill="url(#b)"/><path d="M0 210L85 80l70 98 64-105L384 220v48H0" fill="#1a2641"/><circle cx="285" cy="65" r="25" fill="#c6dbf6"/><text x="24" y="245" fill="white" font-size="20" font-family="sans-serif">Synthetic game artwork</text></svg>').toString('base64');
const data={game:{game_id:'a'.repeat(16),title:'Super Example',platform:'gamecube',system:'Nintendo GameCube',plays:9,last_played:1760000000,last_device:'Gaming PC',devices:[{name:'Gaming PC',plays:9,last_played:1760000000}],models_count:2,mods_count:1,reports_count:1},
 models:[{slug:'example',name:'Original model',format:'glb',model_url:'/api/characters/example/file/model.glb',preview_url:'/example.png'},
  {slug:'edited',name:'Edited model',format:'gltf',model_url:'/api/characters/edited/file/model.gltf',preview_url:'/edited.png',source_game_id:'b'.repeat(16)}],
 builds:[{name:'sonic_swap',title:'Sonic replacement',built:1760001000,verified:false,writer:'example_writer',changes:[{slot:'player',donor:'Sonic'}],images:[{url:'/build.png'}]}],
 reports:[{id:'report1',number:12,title:'Shoe alignment',status:'open',created:1760002000}],
 activity:[{session_id:'session1',started:1760000000,ended:1760000300,device:'Gaming PC',mod:'sonic_swap',state:'ended'}],
 timeline:[{kind:'model',ts:1760000100,title:'Model extracted',ref:'example'},{kind:'build',ts:1760001000,title:'Sonic replacement',ref:'sonic_swap'},{kind:'report',ts:1760002000,title:'Shoe alignment',ref:'report1'}],
 media:[{kind:'image',url:'/shot.png',label:'Captured gameplay'},{kind:'video',url:'/clip.mp4',label:'Recorded clip'}],progress:{status:'building',active_jobs:[{id:'job1',tool:'retarget',state:'running',progress:40,stage:'Preserving shoe volume'}]}};
const pictured=structuredClone(data);pictured.models.forEach(m=>m.preview_url=illustration);pictured.builds[0].images[0].url=illustration;pictured.media[0].url=illustration;

test('renders only recorded evidence, escapes labels and rejects executable media URLs',()=>{
 const input=structuredClone(data);input.game.title='<img src=x onerror=alert(1)>';input.models[0].name='<script>bad()</script>';input.media.push({kind:'image',url:'javascript:alert(1)',label:'unsafe'});
 const html=Detail.render(input);
 assert.ok(!html.includes('<script>bad'));assert.ok(!html.includes('<img src=x'));assert.ok(!html.includes('javascript:'));
 assert.ok(html.includes('Preserving shoe volume'));assert.ok(html.includes('progress value="40" max="100"'));assert.ok(html.includes('Sonic replacement'));
 assert.ok(html.includes('9</b><span>times played'));assert.ok(html.includes('Gaming PC'));assert.ok(html.includes('Unverified'));assert.ok(html.includes('Recorded clip'));
 assert.equal(Detail.safeURL('//evil.test/a'),'');assert.equal(Detail.safeURL('/\\evil.test/a'),'');assert.equal(Detail.safeURL('https:\\evil.test/a'),'');assert.equal(Detail.safeURL('data:text/html,bad'),'');
 assert.equal(Detail.safeURL('/api/artifacts/abc'),'/api/artifacts/abc');
});

test('timeline orders real timestamps and visualisation makes no invented completion claims',()=>{
 const rows=Detail.events(data);assert.equal(rows[0].kind,'report');assert.equal(rows.at(-1).kind,'model');
 assert.equal(Detail.timelineSVG({timeline:[]}), '');
 const html=Detail.render({game:{title:'Empty title'}});assert.ok(html.includes('No viewable 3D model has been extracted'));assert.ok(html.includes('No active work reported'));assert.ok(!html.includes('<progress'));
 assert.ok(!html.includes('wireframe'));assert.ok(!html.includes('Complete'));
 assert.equal(Detail.modelOptions({models:[...data.models,{format:'png',model_url:'/sprite.png'}]}).length,2);
});

test('selected build details are scoped to their parent game and remain distinct for repeated titles',()=>{
 const input=structuredClone(pictured);input.builds.push({...input.builds[0],name:'second_swap',title:'Second replacement'});input.selected_build={game_id:input.game.game_id,mod_name:'second_swap',title:'Second replacement'};
 const html=Detail.render(input);assert.ok(html.includes('<h2>Second replacement</h2>'));assert.ok(html.includes('Play selected build'));assert.ok(html.includes('Play original game'));assert.ok(html.includes('aria-current="true"'));
 assert.equal(Detail.selectedBuild(input).name,'second_swap');
 assert.equal(Detail.selectedBuild({...input,selected_build:{game_id:'wrong',mod_name:'second_swap'}}),null);
 assert.equal(Detail.selectedBuild({...input,selected_build:'sonic_swap'}).name,'sonic_swap');
});

test('browser: real viewer selection, build and report navigation, gallery close, media cleanup',async()=>{
 await withPage(async(evaluate,send)=>{
  await send('Emulation.setDeviceMetricsOverride',{width:1280,height:1100,deviceScaleFactor:1,mobile:false});
  await evaluate(source);
  await evaluate(`document.head.insertAdjacentHTML('beforeend','<style>'+${JSON.stringify(appStyles)}+'</style>');document.documentElement.dataset.embedded='true';`);
  await evaluate(`document.body.style='background:#111722;color:#e2e9f8;font:14px system-ui;padding:18px';document.body.innerHTML='<div id="detail"></div>';var fixture=${JSON.stringify(pictured)},opened=[],models=[],disposed=[],contexts=[];
   var ctl=GBoxHomeDetail.mount(document.querySelector('#detail'),fixture,{url:p=>p,launch:(...x)=>opened.push(['launch',...x]),models:(...x)=>opened.push(['models',...x]),builds:(...x)=>opened.push(['builds',...x]),report:x=>opened.push(['report',x]),session:x=>opened.push(['session',x]),context:(e,g)=>{e.preventDefault();contexts.push(g.game_id);},
    loadViewer:async()=>({createCharacterViewer:async(stage,url,options)=>{models.push({url,options});stage.textContent='Synthetic viewer fixture';return {gltf:{scene:{traverse:fn=>fn({isMesh:true,geometry:{attributes:{position:{count:30}},index:{count:54}}})}},dispose:()=>disposed.push(url)};}})});ctl.ready;`);
  assert.equal(await evaluate('models.length'),1);assert.equal(await evaluate(`document.querySelector('[data-ghd-model-meta]').textContent.includes('18 triangles')`),true);
  assert.equal(await evaluate(`getComputedStyle(document.querySelector('.ghd-heading')).position`),'static');
  await evaluate(`var select=document.querySelector('[data-ghd-model]');select.value='1';select.dispatchEvent(new Event('change',{bubbles:true}));new Promise(r=>setTimeout(r,10));`);
  assert.equal(await evaluate('models.length'),2);assert.equal(await evaluate('disposed.length'),1);
  await evaluate(`document.querySelector('[data-ghd-build]').click();document.querySelector('[data-ghd-build]').click();document.querySelector('[data-ghd-report]').click();document.querySelector('[data-ghd-session]').click();document.querySelector('[data-ghd-action=models]').click();new Promise(r=>setTimeout(r,10));`);
  assert.deepEqual(await evaluate('opened'),[['launch',data.game.game_id,{mod:'sonic_swap'}],['report','report1'],['session','session1'],['models',data.game.game_id,'Super Example']]);
  await evaluate(`document.querySelector('[data-ghd-media]').click();`);assert.equal(await evaluate(`document.querySelector('dialog').open`),true);
  await evaluate(`document.querySelector('dialog button').click();`);assert.equal(await evaluate(`document.querySelector('dialog')===null`),true);
  await evaluate(`document.querySelector('.ghd-heading h2').dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,cancelable:true}));`);assert.deepEqual(await evaluate('contexts'),[data.game.game_id]);
  if(process.env.GBOX_HOME_DETAIL_EVIDENCE){const shot=await send('Page.captureScreenshot',{format:'png'});fs.mkdirSync(process.env.GBOX_HOME_DETAIL_EVIDENCE,{recursive:true});fs.writeFileSync(path.join(process.env.GBOX_HOME_DETAIL_EVIDENCE,'home-detail.png'),Buffer.from(shot.result.data,'base64'));}
  await evaluate(`var video=document.querySelector('video');ctl.dispose();`);
  assert.equal(await evaluate(`document.querySelector('#detail').children.length`),0);assert.equal(await evaluate('disposed.length'),2);assert.equal(await evaluate(`video.hasAttribute('src')`),false);
 });
});

test('browser: closing during viewer download disposes its late result without changing the new page',async()=>{
 await withPage(async evaluate=>{
  await evaluate(source);
  await evaluate(`document.body.innerHTML='<div id="detail"></div>';var finish,disposed=0;var started=new Promise(resolve=>window.didStart=resolve);var ctl=GBoxHomeDetail.mount(document.querySelector('#detail'),${JSON.stringify(data)},{loadViewer:async()=>({createCharacterViewer:(stage,url)=>{didStart();return new Promise(resolve=>finish=()=>resolve({dispose:()=>disposed++}));}})});started;`);
  await evaluate(`ctl.dispose();document.querySelector('#detail').textContent='New page';finish();ctl.ready;`);
  assert.equal(await evaluate('disposed'),1);assert.equal(await evaluate(`document.querySelector('#detail').textContent`),'New page');
 });
});

test('browser: changing models while downloads finish out of order keeps the newest selection',async()=>{
 await withPage(async evaluate=>{
  await evaluate(source);
  await evaluate(`document.body.innerHTML='<div id="detail"></div>';var finishes=[],disposed=[];var ctl=GBoxHomeDetail.mount(document.querySelector('#detail'),${JSON.stringify(pictured)},{loadViewer:async()=>({createCharacterViewer:(stage,url)=>new Promise(resolve=>finishes.push(()=>{stage.textContent=url;resolve({gltf:{scene:{traverse:()=>{}}},dispose:()=>disposed.push(url)});} ))})});new Promise(r=>setTimeout(r,10));`);
  await evaluate(`var select=document.querySelector('[data-ghd-model]');select.value='1';select.dispatchEvent(new Event('change',{bubbles:true}));new Promise(r=>setTimeout(r,10));`);
  assert.equal(await evaluate('finishes.length'),2);
  await evaluate(`finishes[1]();new Promise(r=>setTimeout(r,10));`);
  await evaluate(`finishes[0]();ctl.ready;`);
  assert.ok(await evaluate(`document.querySelector('[data-ghd-stage]').textContent.includes('/edited/')`));
  assert.ok(await evaluate(`document.querySelector('[data-ghd-model-meta]').textContent.startsWith('Edited model')`));
  assert.deepEqual(await evaluate('disposed'),['/api/characters/example/file/model.glb']);
  await evaluate('ctl.dispose()');assert.equal(await evaluate('disposed.length'),2);
 });
});

test('browser: download failures show honest fallback and do not request any work',async()=>{
 await withPage(async evaluate=>{
  await evaluate(source);
  await evaluate(`document.body.innerHTML='<div id="detail"></div>';var apiCalls=[];var ctl=GBoxHomeDetail.mount(document.querySelector('#detail'),${JSON.stringify(pictured)},{api:p=>apiCalls.push(p),loadViewer:async()=>{throw Error('WebGL unavailable');}});ctl.ready;`);
  assert.equal(await evaluate(`document.querySelector('[data-ghd-stage] img').getAttribute('src')`),illustration);
  assert.ok(await evaluate(`document.querySelector('[data-ghd-model-status]').textContent.includes('WebGL unavailable')`));
  assert.deepEqual(await evaluate('apiCalls'),[]);
  await evaluate(`document.querySelector('[data-ghd-action=play]').click();new Promise(r=>setTimeout(r,10));`);
  assert.ok(await evaluate(`document.querySelector('[data-ghd-action-status]').textContent.includes('unavailable')`));
  await evaluate('ctl.dispose()');
 });
});

test('browser: live activity refresh preserves the viewer and playing media while updating indexed actions',async()=>{
 await withPage(async evaluate=>{
  await evaluate(source);
  const fresh=structuredClone(pictured);fresh.progress.active_jobs[0].progress=75;fresh.progress.active_jobs[0].stage='Writing native model';fresh.game.plays=10;fresh.builds.unshift({...fresh.builds[0],name:'new_swap',title:'Newer build'});fresh.models.push({...fresh.models[0],slug:'another'});fresh.reports.unshift({...fresh.reports[0],id:'new-report',title:'New report'});
  await evaluate(`document.body.innerHTML='<div id="detail"></div>';var calls=[],opened=[],loaded=0,disposed=0,refreshed=0;var ctl=GBoxHomeDetail.mount(document.querySelector('#detail'),${JSON.stringify(pictured)},{api:async p=>{calls.push(p);return ${JSON.stringify(fresh)}},launch:(...a)=>opened.push(a),report:id=>opened.push(id),refreshDetail:()=>refreshed++,loadViewer:async()=>({createCharacterViewer:async()=>{loaded++;return {dispose:()=>disposed++}}})});ctl.ready;`);
  await evaluate(`var canvasContainer=document.querySelector('[data-ghd-stage]'),originalVideo=document.querySelector('video');ctl.refresh();`);
  assert.equal(await evaluate('loaded'),1);assert.equal(await evaluate('disposed'),0);
  assert.equal(await evaluate(`document.querySelector('[data-ghd-stage]')===canvasContainer`),true);assert.equal(await evaluate(`document.querySelector('video')===originalVideo`),true);
  assert.equal(await evaluate(`document.querySelector('progress').getAttribute('value')`),'75');
  assert.ok(await evaluate(`document.querySelector('.ghd-work-state').textContent.includes('Writing native model')`));
  assert.ok(await evaluate(`document.querySelector('.ghd-metrics').textContent.includes('10times played')`));
  assert.equal(await evaluate(`document.querySelector('[data-ghd-assets-refresh]').hidden`),false);
  await evaluate(`document.querySelector('[data-ghd-build]').click();document.querySelector('[data-ghd-report]').click();document.querySelector('[data-ghd-action=refresh-assets]').click();new Promise(r=>setTimeout(r,10));`);
  assert.deepEqual(await evaluate('opened'),[[data.game.game_id,{mod:'new_swap'}],'new-report']);assert.equal(await evaluate('refreshed'),1);
  await evaluate('ctl.dispose();ctl.refresh()');assert.equal(await evaluate('calls.length'),1);assert.equal(await evaluate('disposed'),1);
 });
});

test('browser: selected mod launches exactly that build and stays selected across activity refresh',async()=>{
 await withPage(async evaluate=>{
  await evaluate(source);
  const selected=structuredClone(pictured);selected.builds.push({...selected.builds[0],name:'second_swap',title:'Second replacement',launch_node:'i9-NUC',changes:[{slot:'player',donor:'edited'}]});selected.selected_build={game_id:selected.game.game_id,mod_name:'second_swap',title:'Second replacement',launch_node:'stale-device'};
  const fresh=structuredClone(selected);delete fresh.selected_build;fresh.builds.unshift({...fresh.builds[0],name:'newest_swap',title:'Newest replacement'});
  await evaluate(`document.body.innerHTML='<div id="detail"></div>';var opened=[],modelURLs=[],disposed=0;var ctl=GBoxHomeDetail.mount(document.querySelector('#detail'),${JSON.stringify(selected)},{api:async()=>(${JSON.stringify(fresh)}),launch:(...x)=>opened.push(x),loadViewer:async()=>({createCharacterViewer:async(stage,url)=>{modelURLs.push(url);return {dispose:()=>disposed++}}})});ctl.ready;`);
  assert.equal(await evaluate(`document.querySelector('.ghd-heading h2').textContent`),'Second replacement');
  assert.ok(await evaluate(`document.querySelector('.ghd-heading p').textContent.includes('Super Example')`));
  assert.equal(await evaluate(`document.querySelector('.ghd-build-selected h4').textContent`),'Second replacement');
  assert.deepEqual(await evaluate('modelURLs'),['/api/characters/edited/file/model.gltf']);
  await evaluate(`document.querySelector('[data-ghd-action=play-selected]').click();new Promise(r=>setTimeout(r,0));`);
  await evaluate('ctl.refresh()');
  assert.equal(await evaluate(`document.querySelector('.ghd-heading h2').textContent`),'Second replacement');assert.equal(await evaluate('modelURLs.length'),1);
  await evaluate(`document.querySelector('[data-ghd-action=play-selected]').click();document.querySelector('.ghd-build-selected [data-ghd-build]').click();document.querySelector('[data-ghd-action=play]').click();new Promise(r=>setTimeout(r,10));`);
  assert.deepEqual(await evaluate('opened'),[...Array.from({length:3},()=>[data.game.game_id,{mod:'second_swap',node:'i9-NUC'}]),[data.game.game_id,{mod:'',slot:''}]]);
  await evaluate('ctl.dispose()');assert.equal(await evaluate('disposed'),1);
 });
});
