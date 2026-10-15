const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const H=require('../clients/web/viz/library-home.js');
const {withPage}=require('../scripts/browser_lifecycle.cjs');
const script=fs.readFileSync(path.join(__dirname,'../clients/web/viz/library-home.js'),'utf8');
const css=fs.readFileSync(path.join(__dirname,'../clients/web/viz/library-home.css'),'utf8');
const art=(color,title)=>'data:image/svg+xml;base64,'+Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" width="700" height="900"><rect width="700" height="900" fill="${color}"/><circle cx="350" cy="300" r="200" fill="#ffffff22"/><path d="M0 900L350 200 700 900Z" fill="#ffffff15"/><text x="350" y="760" fill="white" font-family="sans-serif" text-anchor="middle" font-size="48">${title}</text></svg>`).toString('base64');
const games=[{game_id:'a',title:'Sonic the Hedgehog 2',system:'Sega Genesis',platform:'genesis',plays:24,last_played:1792090000,last_device:'JAY',mods_count:3,models_count:2,favorite:true,playable:true,poster_url:art('#29456e','SONIC 2'),media:[{kind:'image',url:art('#1e395d','SONIC 2'),label:'Box art'},{kind:'image',url:art('#345c75','SONIC 2'),label:'Gameplay capture'},{kind:'video',url:'/captured/sonic.mp4',label:'Your latest run'}]},{game_id:'b',title:'Super Mario Bros.',system:'NES',platform:'nes',plays:11,last_played:1792080000,last_device:'i9-NUC',mods_count:2,models_count:0,favorite:true,poster_url:art('#70422d','MARIO'),media:[]},{game_id:'c',title:'Phantasy Star Online',system:'Nintendo GameCube',platform:'gamecube',plays:7,last_played:1792000000,mods_count:4,models_count:12,poster_url:art('#275951','PSO'),media:[]}];

async function setup(evaluate,send,extra=''){
 await send('Emulation.setDeviceMetricsOverride',{width:1360,height:1000,deviceScaleFactor:1,mobile:false});
 await evaluate(`document.head.innerHTML='<style>body{margin:0;background:#12151d;color:#eef;font:14px system-ui}'+${JSON.stringify(css)}+'</style>';document.body.innerHTML='<div id="home"></div>';var stored={};Object.defineProperty(window,'localStorage',{value:{getItem:k=>stored[k]||null,setItem:(k,v)=>stored[k]=v},configurable:true});var calls=[],launches=[],contexts=[],details=[],disposed=0,searches=[],scrolled=[],fixtures=${JSON.stringify(games)};Element.prototype.scrollIntoView=function(){scrolled.push(this.className);};
 // Fake only the media transport: the UI's real intent, source selection, pause,
 // visibility and disposal code run without an external video/network service.
 var nativeGet=Element.prototype.getAttribute,nativeHas=Element.prototype.hasAttribute,nativeRemove=Element.prototype.removeAttribute;
 Object.defineProperty(HTMLMediaElement.prototype,'src',{get(){return this.dataset.fixtureSrc||'';},set(v){this.dataset.fixtureSrc=v;},configurable:true});
 HTMLMediaElement.prototype.getAttribute=function(n){return n==='src'?this.dataset.fixtureSrc||null:nativeGet.call(this,n);};HTMLMediaElement.prototype.hasAttribute=function(n){return n==='src'?!!this.dataset.fixtureSrc:nativeHas.call(this,n);};HTMLMediaElement.prototype.removeAttribute=function(n){if(n==='src')delete this.dataset.fixtureSrc;else nativeRemove.call(this,n);};
 HTMLMediaElement.prototype.play=function(){this.dataset.played='true';return Promise.resolve();};HTMLMediaElement.prototype.pause=function(){this.dataset.paused='true';};HTMLMediaElement.prototype.load=function(){};
 var GBoxHomeDetail={mount:(host,data,io)=>{details.push(data.game.game_id);host.textContent='Details for '+data.game.title;return {dispose:()=>disposed++};}};
 var io={url:u=>u,api:async(p,b,opts)=>{calls.push(p);if(p.startsWith('/api/home/games?')){var params=new URLSearchParams(p.split('?')[1]);var all=fixtures.filter(g=>!params.get('q')||g.title.toLowerCase().includes(params.get('q').toLowerCase()));return {items:all,total:all.length,offset:+params.get('offset'),platforms:[{platform:'nes',count:1},{platform:'genesis',count:1}],indexing:false};}return {game:fixtures.find(g=>p.endsWith('/'+g.game_id)),media:fixtures.find(g=>p.endsWith('/'+g.game_id)).media};},launch:gid=>launches.push(gid),context:(e,g)=>contexts.push({id:g.game_id,prevented:e.defaultPrevented}),onSearch:q=>searches.push(q)};${extra}`);
 await evaluate(script);
 await evaluate(`var ctl=GBoxHome.mount(document.querySelector('#home'),io);ctl.ready;`);
}

test('Home settings and bounded query encode user filters',()=>{
 assert.deepEqual(H.settings(),{view:'shelf',sort:'recent',favorites:false,has_mods:false,platform:''});
 assert.deepEqual(H.settings(null),H.settings());
 assert.equal(H.settings({view:'evil',sort:'unknown'}).sort,'recent');
 const url=new URL('https://local'+H.query({sort:'title',q:'Mario & Sonic',favorites:true,has_mods:true,platform:'Nintendo / 64'},96));
 assert.equal(url.searchParams.get('q'),'Mario & Sonic');assert.equal(url.searchParams.get('limit'),'48');assert.equal(url.searchParams.get('offset'),'96');assert.equal(url.searchParams.get('platform'),'Nintendo / 64');
 assert.deepEqual(H.mediaOf({media:[{kind:'image',url:'/a'},{kind:'image',url:'/a'},{kind:'html',url:'/x'}],game:{media:[{kind:'video',url:'/v'}]}}).map(m=>m.url),['/a','/v']);
 assert.equal(H.safeMediaURL('//external.example/image'),'');assert.equal(H.safeMediaURL('https://external.example/image'),'');assert.equal(H.safeMediaURL('/\\external/image'),'');assert.equal(H.safeMediaURL('/api/media/example'),'/api/media/example');
});

test('Home shelf selects a game, retains the normal game menu, and changes to a persistent list view',async()=>{
 await withPage(async(evaluate,send)=>{
  await setup(evaluate,send);
  assert.equal(await evaluate(`document.querySelector('[data-lh-title]').textContent`),games[0].title);
  assert.equal(await evaluate(`document.querySelectorAll('.lh-card').length`),3);
  assert.equal(await evaluate(`document.querySelector('[data-lh-sort]').value`),'recent');
  assert.deepEqual(await evaluate('scrolled'),[]);
  await evaluate(`document.querySelector('[data-lh-game="b"]').click();new Promise(r=>setTimeout(r,0));`);
  assert.equal(await evaluate(`document.querySelector('[data-lh-details]').textContent`),'Details for Super Mario Bros.');
  assert.deepEqual(await evaluate('scrolled'),['lh-details']);
  await evaluate(`document.querySelector('[data-lh-play]').click();var e=new MouseEvent('contextmenu',{bubbles:true,cancelable:true});document.querySelector('[data-lh-game="b"] img').dispatchEvent(e);document.querySelector('[data-lh-view-button="list"]').click();`);
  assert.deepEqual(await evaluate('launches'),['b']);assert.deepEqual(await evaluate('contexts'),[{id:'b',prevented:true}]);
  assert.equal(await evaluate(`document.querySelector('.lh-list').hidden`),false);assert.equal(await evaluate(`document.querySelector('.lh-shelf').hidden`),true);
  assert.equal(await evaluate(`document.querySelector('[data-lh-view-button="list"]').getAttribute('aria-pressed')`),'true');
  await evaluate(`document.querySelector('.lh-list-game[data-lh-game="c"]').click();new Promise(r=>setTimeout(r,0));`);
  assert.deepEqual(await evaluate('scrolled'),['lh-details']);
  await evaluate(`ctl.dispose();ctl=GBoxHome.mount(document.querySelector('#home'),io);ctl.ready;`);
  assert.equal(await evaluate(`document.querySelector('.lh-home').dataset.lhView`),'list');
  await evaluate('ctl.dispose()');
 });
});

test('Home search, sort, and filters refresh immediately and a stale search cannot replace the latest results',async()=>{
 await withPage(async(evaluate,send)=>{
  await setup(evaluate,send);
  await evaluate(`var normalApi=io.api,oldResolve;io.api=(p,...args)=>p.includes('q=old')?new Promise(r=>oldResolve=r):normalApi(p,...args);ctl.setSearch('old');new Promise(r=>setTimeout(r,230));`);
  await evaluate(`ctl.setSearch('Mario');new Promise(r=>setTimeout(r,230));`);
  assert.equal(await evaluate(`document.querySelectorAll('.lh-card').length`),1);
  assert.equal(await evaluate(`document.querySelector('[data-lh-title]').textContent`),'Super Mario Bros.');
  await evaluate(`oldResolve({items:[fixtures[0]],total:1,platforms:[]});new Promise(r=>setTimeout(r,0));`);
  assert.equal(await evaluate(`document.querySelector('[data-lh-title]').textContent`),'Super Mario Bros.');
  await evaluate(`document.querySelector('[data-lh-sort]').value='plays';document.querySelector('[data-lh-sort]').dispatchEvent(new Event('change'));document.querySelector('[data-lh-mods]').click();new Promise(r=>setTimeout(r,0));`);
  assert.ok(await evaluate(`calls.some(p=>p.includes('sort=plays')&&p.includes('has_mods=true'))`));
  assert.equal(await evaluate(`searches.at(-1)`),'Mario');
  await evaluate(`ctl.setSearch('Nothing here');new Promise(r=>setTimeout(r,230));`);
  assert.equal(await evaluate(`document.querySelectorAll('.lh-card').length`),0);assert.equal(await evaluate(`document.querySelector('[data-lh-play]').disabled`),true);
  assert.ok(await evaluate(`document.querySelector('[data-lh-status]').textContent.includes('No games match')`));
  await evaluate('ctl.dispose()');
 });
});

test('Home pagination bounds the DOM for a large catalog and arrow navigation reaches another cover',async()=>{
 await withPage(async(evaluate,send)=>{
  await setup(evaluate,send,`io.api=async p=>{calls.push(p);if(p.includes('?')){var query=new URLSearchParams(p.split('?')[1]),offset=+query.get('offset');return {items:Array.from({length:48},(_,i)=>({...fixtures[0],game_id:String(offset+i),title:'Title '+(offset+i)})),total:64179,platforms:[]};}return {game:{...fixtures[0],game_id:p.split('/').at(-1)},media:[]};};`);
  assert.equal(await evaluate(`document.querySelectorAll('.lh-card').length`),48);
  await evaluate(`document.querySelector('[data-lh-page-next]').click();new Promise(r=>setTimeout(r,0));`);
  assert.equal(await evaluate(`document.querySelector('.lh-card').dataset.lhGame`),'48');
  assert.equal(await evaluate(`document.querySelectorAll('[data-lh-game]').length`),96);
  assert.ok(await evaluate(`calls.some(p=>p.includes('offset=48'))`));
  await evaluate(`document.querySelector('.lh-card').focus();document.querySelector('[data-lh-cards]').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));`);
  assert.equal(await evaluate(`document.activeElement.dataset.lhGame`),'49');
  await evaluate('ctl.dispose()');
 });
});

test('Home hover plays only the actual captured video, pauses on leave, and respects reduced motion',async()=>{
 await withPage(async(evaluate,send)=>{
  await setup(evaluate,send);
  assert.equal(await evaluate(`document.querySelector('[data-lh-video]').hasAttribute('src')`),false);
  await evaluate(`document.querySelector('.lh-card').dispatchEvent(new MouseEvent('mouseover',{bubbles:true}));new Promise(r=>setTimeout(r,700));`);
  assert.equal(await evaluate(`document.querySelector('[data-lh-video]').getAttribute('src')`),'/captured/sonic.mp4');
  assert.equal(await evaluate(`document.querySelector('[data-lh-video]').muted`),true);
  await evaluate(`document.querySelector('.lh-card').dispatchEvent(new MouseEvent('mouseout',{bubbles:true,relatedTarget:document.body}));`);
  assert.equal(await evaluate(`document.querySelector('[data-lh-video]').hasAttribute('src')`),false);
  await send('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-motion',value:'reduce'}]});
  await evaluate(`new Promise(r=>setTimeout(r,10));document.querySelector('.lh-card').dispatchEvent(new MouseEvent('mouseover',{bubbles:true}));new Promise(r=>setTimeout(r,700));`);
  assert.equal(await evaluate(`document.querySelector('[data-lh-video]').hasAttribute('src')`),false);
  await evaluate('ctl.dispose()');
 });
});

test('Home detail loading survives hovering another title; disposal cannot resurrect a late response',async()=>{
 await withPage(async(evaluate,send)=>{
  await setup(evaluate,send);
  await evaluate(`var base=io.api,bResolve,cResolve;io.api=p=>p==='/api/home/games/b'?new Promise(r=>bResolve=r):p==='/api/home/games/c'?new Promise(r=>cResolve=r):base(p);document.querySelector('.lh-card[data-lh-game="b"]').click();document.querySelector('.lh-card[data-lh-game="c"]').dispatchEvent(new MouseEvent('mouseover',{bubbles:true}));new Promise(r=>setTimeout(r,270));`);
  await evaluate(`bResolve({game:fixtures[1],media:[]});new Promise(r=>setTimeout(r,0));`);
  assert.equal(await evaluate(`document.querySelector('[data-lh-details]').textContent`),'Details for Super Mario Bros.');
  assert.equal(await evaluate(`document.querySelector('[data-lh-title]').textContent`),'Phantasy Star Online');
  await evaluate(`ctl.dispose();document.querySelector('#home').innerHTML='New page';cResolve({game:fixtures[2],media:[]});new Promise(r=>setTimeout(r,0));`);
  assert.equal(await evaluate(`document.querySelector('#home').textContent`),'New page');
 });
});

test('Home only retries an empty warming index and a superseded video play cannot stop its replacement',async()=>{
 await withPage(async(evaluate,send)=>{
  await setup(evaluate,send,`var warm=0,baseApi=io.api;io.api=p=>p.includes('?')&&warm++===0?Promise.resolve({items:[],total:0,indexing:true,platforms:[]}):baseApi(p);`);
  assert.equal(await evaluate(`document.querySelector('[data-lh-title]').textContent`),'Preparing your collection…');
  await evaluate(`new Promise(r=>setTimeout(r,4250));`);
  assert.equal(await evaluate(`document.querySelectorAll('.lh-card').length`),3);
  await evaluate(`var playReject;HTMLMediaElement.prototype.play=function(){if(!playReject)return new Promise((yes,no)=>playReject=no);return Promise.resolve();};document.querySelector('.lh-card').dispatchEvent(new MouseEvent('mouseover',{bubbles:true}));new Promise(r=>setTimeout(r,700));`);
  await evaluate(`document.querySelector('.lh-card').dispatchEvent(new MouseEvent('mouseout',{bubbles:true,relatedTarget:document.body}));document.querySelector('.lh-hero').dispatchEvent(new MouseEvent('mouseenter'));new Promise(r=>setTimeout(r,300));`);
  await evaluate(`playReject(Error('Old source interrupted'));new Promise(r=>setTimeout(r,0));`);
  assert.equal(await evaluate(`document.querySelector('[data-lh-video]').getAttribute('src')`),'/captured/sonic.mp4');
  await evaluate('ctl.dispose()');
 });
});

test('Home escapes titles and displays a usable empty/error state without invented assets',async()=>{
 await withPage(async(evaluate,send)=>{
  await setup(evaluate,send,`fixtures=[{game_id:'x',title:'<img src=x onerror=window.bad=1>',platform:'NES',media:[],poster_url:''}];`);
  assert.equal(await evaluate('window.bad'),undefined);
  assert.equal(await evaluate(`document.querySelector('.lh-card strong').textContent`),'<img src=x onerror=window.bad=1>');
  assert.equal(await evaluate(`document.querySelectorAll('.lh-cover img').length`),0);
  await evaluate(`io.api=async()=>{throw Error('Network unavailable');};ctl.refresh();`);
  assert.ok(await evaluate(`document.querySelector('[data-lh-status]').textContent.includes('Network unavailable')`));
  if(process.env.GBOX_HOME_EVIDENCE){await evaluate(`io.api=async p=>p.includes('?')?{items:${JSON.stringify(games)},total:3,platforms:[]}:({game:${JSON.stringify(games[0])},media:[]});ctl.refresh();`);const shot=await send('Page.captureScreenshot',{format:'png'});fs.mkdirSync(process.env.GBOX_HOME_EVIDENCE,{recursive:true});fs.writeFileSync(path.join(process.env.GBOX_HOME_EVIDENCE,'library-home.png'),Buffer.from(shot.result.data,'base64'));}
  await evaluate('ctl.dispose()');
 });
});
