const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), http = require('node:http');
const {withPage} = require('../scripts/browser_lifecycle.cjs');

test('real application Home has compact controls, viewport media, dictation, and explicit Info navigation', async () => {
  const web = path.resolve(__dirname, '../clients/web'), requests = [];
  const game = {game_id:'testgame', title:'Sonic the Hedgehog 2', platform:'genesis', system:'Genesis', plays:2, last_played:1792091000, poster_url:'/test-art.svg',media:[{kind:'image',url:'/test-art.svg',label:'Test poster',source:'art'}], models_count:0, mods_count:2};
  const modRows = [{...game,key:'testgame/bla_sonic',mod_name:'bla_sonic',title:'Bla as Sonic',game_title:game.title,built:1792091200,is_mod:true,available:true,launch_node:'Test-PC'},
    {...game,key:'testgame/sonic_blue',mod_name:'sonic_blue',title:'Blue Sonic',game_title:game.title,built:1792091100,is_mod:true,available:true,launch_node:'auto'}];
  const detail = {game, models:[], builds:modRows.map(b=>({name:b.mod_name,title:b.title,built:b.built,verified:false,launch_node:b.launch_node})), reports:[], activity:[], timeline:[], media:game.media, progress:{status:'idle',active_jobs:[]}};
  const server = http.createServer((req, res) => {
    const url = new URL(req.url, 'http://127.0.0.1');
    if (url.pathname.startsWith('/api/')) {
      requests.push({path:url.pathname, query:url.search, method:req.method});
      let data = [];
      if (url.pathname === '/api/home/games') data = {items:[game],total:1,offset:0,limit:48,platforms:[{platform:'genesis',count:1}],indexing:false};
      else if (url.pathname === '/api/home/mods') data = {items:modRows,total:modRows.length,offset:0,limit:48,platforms:[{platform:'genesis',count:1}],indexing:false};
      else if (url.pathname === '/api/home/games/testgame') data = detail;
      else if (url.pathname === '/api/catalog/facets') data = {platforms:{genesis:1}, systems:{Genesis:1}, libraries:{}};
      else if (url.pathname === '/api/catalog/platforms') data = [];
      else if (url.pathname === '/api/catalog') data = {total:1,items:[game]};
      else if (url.pathname === '/api/tasks') data = {active:[],recent:[],hermes:[]};
      else if (url.pathname === '/api/registry') data = {tools:[]};
      res.writeHead(200, {'content-type':'application/json'});res.end(JSON.stringify(data));return;
    }
    if (url.pathname === '/test-art.svg') {res.writeHead(200,{'content-type':'image/svg+xml'});res.end('<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="1000"><defs><linearGradient id="b" x2="1" y2="1"><stop stop-color="#162b54"/><stop offset="1" stop-color="#65528f"/></linearGradient></defs><rect width="1600" height="1000" fill="url(#b)"/><circle cx="1150" cy="250" r="150" fill="#a4c6ed"/><path d="M0 850L420 270l250 420 350-390 580 630v70H0" fill="#14213c"/><text x="90" y="900" font-family="sans-serif" font-size="56" fill="#d2dcf2">Synthetic game artwork</text></svg>');return;}
    const file = path.resolve(web, '.' + (url.pathname === '/' ? '/index.html' : url.pathname));
    if (!file.startsWith(web + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {res.writeHead(404);res.end();return;}
    res.writeHead(200, {'content-type':file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':file.endsWith('.svg')?'image/svg+xml':'text/html'});res.end(fs.readFileSync(file));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  try {
    await withPage(async (evaluate, send) => {
      const screenshot=async name=>{if(!process.env.GBOX_HOME_EVIDENCE)return;const shot=await send('Page.captureScreenshot',{format:'png'});fs.mkdirSync(process.env.GBOX_HOME_EVIDENCE,{recursive:true});fs.writeFileSync(path.join(process.env.GBOX_HOME_EVIDENCE,name+'.png'),Buffer.from(shot.result.data,'base64'));};
      await send('Emulation.setDeviceMetricsOverride',{width:1500,height:1000,deviceScaleFactor:1,mobile:false});
      await send('Page.addScriptToEvaluateOnNewDocument',{source:`try{localStorage.setItem('gbox_asset_sidebar',JSON.stringify({closed:true}));}catch{}`});
      await send('Page.navigate',{url:`http://127.0.0.1:${server.address().port}/#token=fixture`});
      await evaluate(`(async()=>{for(let i=0;i<150&&!window.gboxViewReady;i++)await new Promise(r=>setTimeout(r,20));await window.gboxViewReady;await HOME.ctl?.ready;})()`);
      assert.deepEqual(await evaluate(`({view:cur,title:document.querySelector('[data-lh-title]')?.textContent,full:document.querySelector('#view').classList.contains('home-view')})`), {view:'Home',title:game.title,full:true});
      await evaluate(`(async()=>{for(let i=0;i<150&&(!document.querySelector('.lh-search .micbtn')||!document.querySelector('[data-lh-backdrop]')?.naturalWidth);i++)await new Promise(r=>setTimeout(r,20));await new Promise(requestAnimationFrame);})()`);
      const layout = await evaluate(`(()=>{const rect=s=>{const r=document.querySelector(s).getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height}};return {search:rect('.lh-search'),mic:rect('.lh-search .micbtn'),toolbar:rect('.lh-toolbar'),filters:rect('.lh-filters'),views:rect('.lh-views'),background:rect('.lh-backdrop'),main:rect('#view'),cards:rect('[data-lh-cards]'),backgroundPosition:getComputedStyle(document.querySelector('.lh-backdrop')).position,backgroundParent:document.querySelector('.lh-backdrop').parentElement.className,heroBackground:getComputedStyle(document.querySelector('.lh-hero')).backgroundColor,screen:document.querySelector('.lh-home').dataset.lhScreen,details:document.querySelectorAll('.ghd-root').length,micDecorated:document.querySelector('[data-lh-search]').parentElement.classList.contains('micwrap'),assetsClosed:document.querySelector('#asset-sidebar').classList.contains('closed')}})()`);
      assert.equal(layout.micDecorated,true,'the real global dictation observer wraps Home search');
      assert.equal(layout.assetsClosed,true);
      assert.ok(layout.search.right-layout.mic.right>=0&&layout.search.right-layout.mic.right<=24,'dictation mic stays at the right edge of Home search');
      assert.ok(Math.abs((layout.search.top+layout.search.bottom)/2-(layout.mic.top+layout.mic.bottom)/2)<=8,'mic is vertically centered');
      assert.ok(layout.toolbar.height<=64,'desktop controls occupy one compact row');
      for(const box of [layout.search,layout.filters,layout.views])assert.ok(box.top>=layout.toolbar.top-1&&box.bottom<=layout.toolbar.bottom+1,'search, filters and view controls share the top row');
      assert.equal(layout.backgroundPosition,'fixed');assert.equal(layout.backgroundParent,'lh-home');
      assert.ok(Math.abs(layout.background.left-layout.main.left)<=1&&Math.abs(layout.background.right-layout.main.right)<=1,'media spans Home width, excluding the separate Assets sidebar');
      assert.ok(layout.background.top<=layout.toolbar.top&&layout.background.bottom>=layout.cards.bottom,'media covers controls and the game shelf');
      assert.ok(Math.abs(layout.background.bottom-1000)<=1,'background reaches the viewport bottom');
      assert.equal(layout.heroBackground,'rgba(0, 0, 0, 0)','the preview is no longer an opaque boxed hero');
      assert.equal(layout.screen,'browse');assert.equal(layout.details,0,'Home does not expand or load a 3D workspace automatically');
      assert.equal(requests.some(r=>r.path.startsWith('/api/characters/')),false,'browsing starts no model downloads');
      await screenshot('home-compact-real-shell');
      await send('Emulation.setDeviceMetricsOverride',{width:1500,height:800,deviceScaleFactor:1,mobile:false});
      await evaluate(`new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))`);
      const shortViewport = await evaluate(`(()=>{const home=document.querySelector('.lh-home').getBoundingClientRect(),cards=document.querySelector('[data-lh-cards]').getBoundingClientRect(),background=document.querySelector('.lh-backdrop').getBoundingClientRect();return {documentHeight:document.documentElement.scrollHeight,viewport:innerHeight,homeBottom:home.bottom,cardsBottom:cards.bottom,backgroundBottom:background.bottom,toolbarHeight:document.querySelector('.lh-toolbar').getBoundingClientRect().height,scroll:scrollY}})()`);
      assert.equal(shortViewport.viewport,800);
      assert.ok(shortViewport.documentHeight<=801,'desktop browse fits a 1500 × 800 guest viewport without vertical page overflow');
      assert.ok(shortViewport.homeBottom<=801&&shortViewport.cardsBottom<=801,'the complete browsing shelf remains inside the shorter viewport');
      assert.ok(Math.abs(shortViewport.backgroundBottom-800)<=1);assert.ok(shortViewport.toolbarHeight<=64);assert.equal(shortViewport.scroll,0);
      await screenshot('home-compact-real-shell-800');
      await evaluate(`show('Library')`);
      await evaluate(`document.getElementById('home-brand').click();(async()=>{for(let i=0;i<150&&!HOME.ctl;i++)await new Promise(r=>setTimeout(r,20));await HOME.ctl.ready;})()`);
      assert.equal(await evaluate('cur'),'Home');
      await evaluate(`document.getElementById('gsearch').value='sonic';document.getElementById('gsearch').dispatchEvent(new Event('input',{bubbles:true}));new Promise(r=>setTimeout(r,500));`);
      assert.deepEqual(await evaluate(`({view:cur,search:document.querySelector('[data-lh-search]').value})`),{view:'Home',search:'sonic'});
      assert.ok(requests.some(r=>r.path==='/api/home/games' && new URLSearchParams(r.query).get('q')==='sonic' && r.method==='GET'));
      await evaluate(`window._homeLaunches=[];play=async(...args)=>_homeLaunches.push(args);const feed=document.querySelector('[data-lh-shelf-title] [data-lh-feed]');feed.value='mods';feed.dispatchEvent(new Event('change',{bubbles:true}));(async()=>{for(let i=0;i<150&&document.querySelectorAll('.lh-card').length!==2;i++)await new Promise(r=>setTimeout(r,20));})()`);
      assert.equal(await evaluate(`document.querySelector('[data-lh-title]').textContent`),'Bla as Sonic');
      assert.deepEqual(await evaluate(`Array.from(document.querySelectorAll('.lh-card'),b=>b.dataset.lhGame)`),['testgame/bla_sonic','testgame/sonic_blue']);
      await evaluate(`document.querySelector('[data-lh-play]').click();new Promise(r=>setTimeout(r,50));`);
      assert.deepEqual(await evaluate(`_homeLaunches.map(args=>({game:args[0],node:args[1],mod:args[3]?.disc}))`),[{game:'testgame',node:'Test-PC',mod:'bla_sonic'}]);
      assert.equal(await evaluate(`document.querySelectorAll('.ghd-root').length`),0,'changing feeds does not open Info');
      await evaluate(`document.querySelector('[data-lh-view-button=list]').click();var sort=document.querySelector('[data-lh-sort]');sort.value='title';sort.dispatchEvent(new Event('change',{bubbles:true}));(async()=>{for(let i=0;i<150&&document.querySelector('.lh-home').hasAttribute('aria-busy');i++)await new Promise(r=>setTimeout(r,20));})()`);
      const browse = await evaluate(`({mode:document.querySelector('.lh-home').dataset.lhMode,view:document.querySelector('.lh-home').dataset.lhView,q:document.querySelector('[data-lh-search]').value,sort:document.querySelector('[data-lh-sort]').value,platform:document.querySelector('[data-lh-platform]').value})`);
      await evaluate(`document.querySelector('.lh-list-game[data-lh-game="testgame/sonic_blue"]').click();(async()=>{for(let i=0;i<150&&!document.querySelector('.ghd-root');i++)await new Promise(r=>setTimeout(r,20));})()`);
      const info = await evaluate(`({screen:document.querySelector('.lh-home').dataset.lhScreen,visible:!document.querySelector('[data-lh-info]').hidden,browseHidden:document.querySelector('.lh-layout').hidden,pageTitle:document.querySelector('.lh-brand h1').textContent,title:document.querySelector('.ghd-heading h2')?.textContent,top:document.querySelector('.ghd-heading')?.getBoundingClientRect().top,scroll:scrollY})`);
      assert.deepEqual({screen:info.screen,visible:info.visible,browseHidden:info.browseHidden,pageTitle:info.pageTitle,title:info.title},{screen:'info',visible:true,browseHidden:true,pageTitle:'Info',title:'Blue Sonic'});
      assert.ok(info.top>=0&&info.top<320,'Info starts near the top of the viewport, ahead of the browsing shelf');assert.equal(info.scroll,0);
      await screenshot('home-info-real-shell');
      await evaluate(`document.querySelector('[data-lh-back]').click();new Promise(r=>setTimeout(r,50));`);
      assert.deepEqual(await evaluate(`({mode:document.querySelector('.lh-home').dataset.lhMode,view:document.querySelector('.lh-home').dataset.lhView,q:document.querySelector('[data-lh-search]').value,sort:document.querySelector('[data-lh-sort]').value,platform:document.querySelector('[data-lh-platform]').value})`),browse,'Back preserves feed, view and filters');
      assert.equal(await evaluate(`document.querySelector('.lh-home').dataset.lhScreen`),'browse');assert.equal(await evaluate(`document.querySelectorAll('.ghd-root').length`),0);
      assert.equal(await evaluate(`document.activeElement.closest('[data-lh-game]')?.dataset.lhGame`),'testgame/sonic_blue','Back restores the inspected title in the list');
      assert.ok(await evaluate(`document.documentElement.scrollHeight<=innerHeight+1`),'returning from Info restores the fitting desktop browse viewport');
      await screenshot('home-back-real-shell');
      await evaluate(`show('Jobs')`);
      assert.equal(await evaluate('HOME.ctl'),null,'leaving Home disposes its media and controllers');
    });
  } finally {await new Promise(resolve=>server.close(resolve));}
});
