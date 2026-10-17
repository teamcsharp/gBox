'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const GA=require('../clients/web/viz/game-assets.js');
const {withPage}=require('../scripts/browser_lifecycle.cjs');
const source=fs.readFileSync(path.join(__dirname,'../clients/web/viz/game-assets.js'),'utf8');
const game={game_id:'mgo/id',title:'Metal Gear Online',platform:'ps3',launch:{kind:'savemgo_bundle',source_fingerprint:'one'}};
const ws=[{id:'office-id',name:'Office',os:'windows',online:true},{id:'nuc-id',name:'NUC',os:'windows',online:true},
  {id:'spark',name:'Spark',os:'linux',online:true},{id:'offline',name:'Gone',os:'windows',online:false}];
const inv={assets:[{path:'o/stage/a.dar',kind:'archives',size:100},{path:'dbm/menu.dbm',kind:'music',size:40}],summary:{files:2,bytes:140},readiness:{decoded_models:false}};
const tick=()=>new Promise(resolve=>setTimeout(resolve,5));
async function until(fn){for(let i=0;i<200;i++){if(fn())return;await tick();}throw Error('test state timeout');}
function fixture(handler,extra={}){
  const calls=[];
  const ctl=GA.createController({gid:game.game_id,title:game.title,worker:'Office',pollMs:0,
    api:async(p,b)=>{calls.push({p,b});if(p.startsWith('/api/catalog/'))return game;if(p==='/api/workers')return ws;return handler?.(p,b);},...extra});
  return {ctl,calls};
}

test('defensive normalizers only accept online Windows and bounded artifact identities',()=>{
  assert.deepEqual(GA.workers({workers:ws}).map(w=>w.id),['office-id','nuc-id']);
  assert.deepEqual(GA.workers(null),[]);
  assert.deepEqual(GA.inventory({assets:{bad:true},issues:null}).assets,[]);
  assert.equal(GA.artifacts([{sha256:'javascript:bad'},{sha256:'a'.repeat(64),name:'report'}]).length,1);
});

test('opening reads catalog and workers only, defaults the local PC, no automatic jobs',async()=>{
  const {ctl,calls}=fixture();await ctl.load();
  assert.equal(ctl.state.worker,'office-id');assert.equal(ctl.supported(),true);
  assert.deepEqual(calls.map(c=>c.p),['/api/catalog/mgo%2Fid','/api/workers']);
  ctl.close();
});

test('explicit native inspection/index/export retains exact paths and archive-member choices',async()=>{
  let seq=0;
  const {ctl,calls}=fixture((p,b)=>{
    if(p==='/api/jobs'){
      const result=b.input.op==='inventory'?inv:b.input.op==='index'?{path:b.input.archive_path,members:[{name:'mesh.mdn',size:10},{name:'paint.txn',size:20}]}:
        {state:'exported',directory:'D:/private/export',worker:'office-id',files:[{output:'native'}],bytes:30};
      return {id:'job-'+(++seq),state:'succeeded',output:{result,report_sha256:'a'.repeat(64)},receipt_id:'receipt'};
    }
    if(p==='/api/receipts/receipt')return {artifacts:[{sha256:'b'.repeat(64),name:'savemgo-native-assets.zip',size:30}]};
    throw Error('unexpected '+p);
  });
  await ctl.load();await ctl.run('inventory');
  ctl.select('dbm/menu.dbm',true);await ctl.run('index','o/stage/a.dar');
  ctl.select('mesh.mdn',true,'o/stage/a.dar');ctl.select('not-listed',true,'o/stage/a.dar');
  await ctl.run('export');
  const submitted=calls.filter(c=>c.p==='/api/jobs');
  assert.equal(submitted.length,3);
  assert.deepEqual(submitted[2].b,{tool:'savemgo_assets',input:{game,op:'export',paths:['dbm/menu.dbm'],members:[{archive:'o/stage/a.dar',name:'mesh.mdn'}],archive_path:''},require_worker:'office-id',require_os:'windows'});
  assert.equal(ctl.state.result.directory,'D:/private/export');
  assert.deepEqual(ctl.state.artifacts.map(a=>a.name),['savemgo-native-assets.zip','savemgo-assets.json']);
  ctl.selectWorker('nuc-id');assert.equal(ctl.state.inventory,null);assert.equal(ctl.state.paths.size+ctl.state.members.size,0);
  ctl.close();
});

test('pending operations cannot submit twice; status errors retain job identity and explicit cancellation',async()=>{
  let reads=0,cancelled=false;
  const {ctl,calls}=fixture((p,b)=>{
    if(p==='/api/jobs')return {id:'one',state:'queued'};
    if(p==='/api/jobs/one/cancel'){cancelled=true;return {};}
    if(p==='/api/jobs/one'){reads++;if(reads===1)throw Error('network paused');return {id:'one',state:cancelled?'cancelled':'running'};}
  });
  await ctl.load();const first=ctl.run('inventory');
  assert.equal(await ctl.run('inventory'),false);
  await first;assert.equal(ctl.state.pollError,true);assert.equal(ctl.state.busy,true);
  assert.equal(ctl.selectWorker('nuc-id'),false);assert.equal(await ctl.run('inventory'),false);
  await ctl.cancel();await until(()=>!ctl.state.busy);
  assert.equal(calls.filter(c=>c.p==='/api/jobs').length,1);
  assert.equal(ctl.state.job.state,'cancelled');ctl.close();
});

test('rejected permission jobs finish and Extract all sends only the explicit all-path selection',async()=>{
  let reject=false;
  const {ctl,calls}=fixture((p,b)=>{
    if(p==='/api/jobs')return reject?{id:'denied',state:'rejected',error:'file_mutation is disabled'}:
      {id:'inventory',state:'succeeded',output:{result:inv}};
  });
  await ctl.load();await ctl.run('inventory');ctl.select('dbm/menu.dbm',true);reject=true;
  await ctl.exportAll();assert.equal(ctl.state.busy,false);assert.equal(ctl.state.paths.size,0);
  assert.match(ctl.state.error,/file_mutation/);
  const request=calls.filter(c=>c.p==='/api/jobs').at(-1).b.input;
  assert.deepEqual(request.paths,['*']);assert.deepEqual(request.members,[]);ctl.close();
});

test('closing a submitted job stops polling without silently cancelling or losing the global job callback',async()=>{
  let resolve,noticed=[];
  const {ctl,calls}=fixture((p,b)=>p==='/api/jobs'?new Promise(r=>resolve=r):undefined,{onJob:j=>noticed.push(j.id)});
  await ctl.load();const action=ctl.run('inventory');await until(()=>resolve);
  ctl.close();resolve({id:'background',state:'queued'});await action;
  assert.deepEqual(noticed,['background']);assert.equal(calls.some(c=>/\/cancel$/.test(c.p)),false);
  assert.equal(calls.some(c=>c.p==='/api/jobs/background'),false);
});

test('unsupported games and an offline selected PC cannot dispatch a native reader job',async()=>{
  const first=fixture(null,{api:async p=>p==='/api/workers'?ws:{...game,launch:{kind:'emulator'}}});
  await first.ctl.load();assert.equal(await first.ctl.run('inventory'),false);assert.match(first.ctl.state.error,/no verified/);first.ctl.close();
  const {ctl,calls}=fixture();await ctl.load();
  ctl.state.workers=[{id:'gone',name:'Gone'}];ctl.state.worker='gone';
  assert.equal(await ctl.run('inventory'),false);assert.match(ctl.state.error,/offline/);
  assert.equal(calls.some(c=>c.p==='/api/jobs'),false);ctl.close();
});

test('browser popup remains explicit, usable at small size, and exposes native downloads without conversion claims',async()=>{
  await withPage(async(evaluate,send)=>{
    await send('Emulation.setDeviceMetricsOverride',{width:800,height:600,deviceScaleFactor:1,mobile:false});
    await evaluate(source);
    await evaluate(`window.calls=[];window.ws=${JSON.stringify(ws)};window.game=${JSON.stringify(game)};window.inv=${JSON.stringify(inv)};window.seq=0;
      window.api=async(p,b)=>{calls.push({p,b});if(p.startsWith('/api/catalog/'))return game;if(p==='/api/workers')return ws;
        if(p==='/api/jobs'){const result=b.input.op==='inventory'?inv:b.input.op==='index'?{path:b.input.archive_path,members:[{name:'face.mdn',size:11}]}:{state:'exported',directory:'D:/private/output',worker:'office-id',files:[{}],bytes:11};
        return {id:'job-'+(++seq),state:'succeeded',output:{result},receipt_id:'receipt'};}
        if(p==='/api/receipts/receipt')return {artifacts:[{sha256:'${'c'.repeat(64)}',name:'native.zip',size:11}]};throw Error(p);};
      window.panel=GBoxGameAssets.open({gid:game.game_id,title:game.title,api,worker:'Office',pollMs:0,media:u=>u+'?token=test',models:()=>{window.models=true;}});panel.ready;`);
    assert.equal(await evaluate(`calls.some(c=>c.p==='/api/jobs')`),false);
    assert.equal(await evaluate(`document.querySelector('[data-ga-worker]').value`),'office-id');
    assert.match(await evaluate(`document.querySelector('[data-ga-readiness]').textContent`),/conversion: pending/);
    await evaluate(`document.querySelector('[data-ga-inspect]').click();new Promise(r=>setTimeout(r,20));`);
    assert.equal(await evaluate(`document.querySelectorAll('[data-ga-select]').length`),2);
    const fits=await evaluate(`(()=>{const r=document.querySelector('dialog').getBoundingClientRect();return r.width<=800&&r.height<=600&&r.top>=0&&r.bottom<=600;})()`);
    assert.equal(fits,true);
    await evaluate(`document.querySelector('[data-ga-index]').click();new Promise(r=>setTimeout(r,20));`);
    assert.match(await evaluate(`document.querySelector('[data-ga-rows]').textContent`),/face.mdn/);
    await evaluate(`document.querySelector('[data-ga-select]').click();document.querySelector('[data-ga-export]').click();new Promise(r=>setTimeout(r,20));`);
    assert.match(await evaluate(`document.querySelector('[data-ga-result]').textContent`),/D:\/private\/output/);
    assert.match(await evaluate(`document.querySelector('[data-ga-links] a').getAttribute('href')`),/api\/artifacts\/[a-f0-9]{64}\?token=test/);
    assert.equal(await evaluate(`calls.filter(c=>c.p==='/api/jobs').length`),3);
    await evaluate(`document.querySelector('[data-ga-models]').click();`);
    assert.equal(await evaluate(`window.models===true&&!document.querySelector('dialog')`),true);
  });
});

test('both clients wire extraction while the existing model collection action remains',()=>{
  const read=file=>fs.readFileSync(path.join(__dirname,'../clients',file),'utf8');
  const menu=read('web/viz/game-menu.js'),web=read('web/index.html'),desktop=read('desktop/index.html');
  assert.match(menu,/data-assets/);assert.match(menu,/id="gmcollect"/);assert.match(menu,/if \(io.assets\) io.assets\(gid, title\)/);
  assert.match(web,/src="\/viz\/game-assets.js"/);assert.match(web,/assets: \(gid,title\) => GBoxGameAssets.open/);
  assert.match(desktop,/src="..\/web\/viz\/game-assets.js"/);assert.match(desktop,/async function gameAssetsOpen/);
});

test('right-click asset action opens the latest title without starting extraction or replacing Play/Models',async()=>{
  await withPage(async evaluate=>{
    await evaluate(source);
    await evaluate(fs.readFileSync(path.join(__dirname,'../clients/web/viz/game-menu.js'),'utf8'));
    await evaluate(`document.body.innerHTML='<div id="menu"></div>';window.calls=[];
      window.api=async(p,b)=>{calls.push({p,b});if(p==='/api/workers')return ${JSON.stringify(ws)};
        if(p.startsWith('/api/catalog/'))return {...${JSON.stringify(game)},game_id:'latest',title:'Latest title'};
        if(p==='/api/characters'||p.startsWith('/api/mods'))return [];return {groups:[],total:0};};
      window.io={el:document.querySelector('#menu'),api,worker:'Office',boot:{get:()=>({}),set:()=>{}},keep:{get:()=>[],set:()=>{}},place:()=>{},models:()=>{},cover:()=>{},cast:()=>{},play:()=>{},
        assets:(gid,title)=>{window.picker=GBoxGameAssets.open({gid,title,api,worker:'Office'});}};
      GBoxGameMenu.open(io,{gid:'older',title:'Old title'});GBoxGameMenu.open(io,{gid:'latest',title:'Latest title'});`);
    assert.equal(await evaluate(`!!document.querySelector('[data-go]')&&!!document.querySelector('[data-models]')&&!!document.querySelector('#gmcollect')`),true);
    await evaluate(`document.querySelector('[data-assets]').click();new Promise(r=>setTimeout(r,20));`);
    assert.equal(await evaluate(`document.querySelector('[data-ga-game]').textContent`),'Latest title');
    assert.equal(await evaluate(`calls.filter(c=>c.p==='/api/jobs').length`),0);
    assert.equal(await evaluate(`calls.some(c=>c.p==='/api/catalog/latest')`),true);
    await evaluate(`picker.close();`);
  });
});

test('popup layout keeps actions visible at wide and 660px widths with a scrolling native table',async()=>{
  await withPage(async(evaluate,send)=>{
    await evaluate(source);
    await evaluate(`window.game=${JSON.stringify(game)};window.ws=${JSON.stringify(ws)};
      window.api=async(p,b)=>{if(p.startsWith('/api/catalog/'))return game;if(p==='/api/workers')return ws;
      return {id:'many-assets',state:'succeeded',output:{result:{assets:Array.from({length:125},(_,i)=>({path:'o/stage/character_'+i+'/long_resource_name_'+i+'.dar',kind:'archives',size:1024*400})),summary:{files:125,bytes:51200000}}}};};
      window.panel=GBoxGameAssets.open({gid:game.game_id,title:game.title,api,worker:'Office',models:()=>{}});panel.ready;`);
    await evaluate(`panel.controller.run('inventory');`);
    for(const [width,height] of [[1500,950],[660,760]]){
      await send('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:false});
      const measured=await evaluate(`(()=>{const dialog=document.querySelector('dialog'),r=dialog.getBoundingClientRect(),table=dialog.querySelector('.ga-table');return {width:r.width,height:r.height,top:r.top,bottom:r.bottom,tableScroll:table.scrollHeight>table.clientHeight,overflow:dialog.scrollWidth>dialog.clientWidth,actions:[...dialog.querySelectorAll('footer button')].filter(b=>!b.hidden).every(b=>{const x=b.getBoundingClientRect();return x.top>=r.top&&x.bottom<=r.bottom;})};})()`);
      assert.ok(measured.width<=width&&measured.bottom<=height&&measured.top>=0,JSON.stringify(measured));
      assert.equal(measured.overflow,false);assert.equal(measured.actions,true);assert.equal(measured.tableScroll,true);
      if(process.env.GBOX_GAME_ASSETS_SCREENSHOTS){
        const shot=await send('Page.captureScreenshot',{format:'png'});fs.mkdirSync(process.env.GBOX_GAME_ASSETS_SCREENSHOTS,{recursive:true});
        fs.writeFileSync(path.join(process.env.GBOX_GAME_ASSETS_SCREENSHOTS,'game-assets-'+width+'.png'),Buffer.from(shot.result.data,'base64'));
      }
    }
    await evaluate(`panel.close();`);
  });
});
