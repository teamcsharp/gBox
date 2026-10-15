const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), http = require('node:http');
const {withPage} = require('../scripts/browser_lifecycle.cjs');

test('application starts at Home, the logo returns there, and header search stays in Home', async () => {
  const web = path.resolve(__dirname, '../clients/web'), requests = [];
  const game = {game_id:'testgame', title:'Sonic the Hedgehog 2', platform:'genesis', system:'Genesis', plays:2, last_played:1792091000, media:[], models_count:0, mods_count:0};
  const detail = {game, models:[], builds:[], reports:[], activity:[], timeline:[], media:[], progress:{status:'idle',active_jobs:[]}};
  const server = http.createServer((req, res) => {
    const url = new URL(req.url, 'http://127.0.0.1');
    if (url.pathname.startsWith('/api/')) {
      requests.push({path:url.pathname, query:url.search, method:req.method});
      let data = [];
      if (url.pathname === '/api/home/games') data = {items:[game],total:1,offset:0,limit:48,platforms:[{platform:'genesis',count:1}],indexing:false};
      else if (url.pathname === '/api/home/games/testgame') data = detail;
      else if (url.pathname === '/api/catalog/facets') data = {platforms:{genesis:1}, systems:{Genesis:1}, libraries:{}};
      else if (url.pathname === '/api/catalog/platforms') data = [];
      else if (url.pathname === '/api/catalog') data = {total:1,items:[game]};
      else if (url.pathname === '/api/tasks') data = {active:[],recent:[],hermes:[]};
      else if (url.pathname === '/api/registry') data = {tools:[]};
      res.writeHead(200, {'content-type':'application/json'});res.end(JSON.stringify(data));return;
    }
    const file = path.resolve(web, '.' + (url.pathname === '/' ? '/index.html' : url.pathname));
    if (!file.startsWith(web + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {res.writeHead(404);res.end();return;}
    res.writeHead(200, {'content-type':file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':file.endsWith('.svg')?'image/svg+xml':'text/html'});res.end(fs.readFileSync(file));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  try {
    await withPage(async (evaluate, send) => {
      await send('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
      await send('Page.navigate',{url:`http://127.0.0.1:${server.address().port}/#token=fixture`});
      await evaluate(`(async()=>{for(let i=0;i<150&&!window.gboxViewReady;i++)await new Promise(r=>setTimeout(r,20));await window.gboxViewReady;await HOME.ctl?.ready;})()`);
      assert.deepEqual(await evaluate(`({view:cur,title:document.querySelector('[data-lh-title]')?.textContent,full:document.querySelector('#view').classList.contains('home-view')})`), {view:'Home',title:game.title,full:true});
      await evaluate(`show('Library')`);
      await evaluate(`document.getElementById('home-brand').click();(async()=>{for(let i=0;i<150&&!HOME.ctl;i++)await new Promise(r=>setTimeout(r,20));await HOME.ctl.ready;})()`);
      assert.equal(await evaluate('cur'),'Home');
      await evaluate(`document.getElementById('gsearch').value='sonic';document.getElementById('gsearch').dispatchEvent(new Event('input',{bubbles:true}));new Promise(r=>setTimeout(r,500));`);
      assert.deepEqual(await evaluate(`({view:cur,search:document.querySelector('[data-lh-search]').value})`),{view:'Home',search:'sonic'});
      assert.ok(requests.some(r=>r.path==='/api/home/games' && new URLSearchParams(r.query).get('q')==='sonic' && r.method==='GET'));
      await evaluate(`show('Jobs')`);
      assert.equal(await evaluate('HOME.ctl'),null,'leaving Home disposes its media and controllers');
    });
  } finally {await new Promise(resolve=>server.close(resolve));}
});
