const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const Detail=require('../clients/web/viz/library-home-detail.js');
const {withPage}=require('../scripts/browser_lifecycle.cjs');
const source=fs.readFileSync(path.join(__dirname,'../clients/web/viz/library-home-detail.js'),'utf8');
const gid='b8edf7040116f3aa',hash='a'.repeat(64),bundle='b'.repeat(64);
const game={game_id:gid,title:'Dead or Alive 3',platform:'xbox'};
const fixture={game,models:[],media:[],builds:[],progress:{active_jobs:[]}};
const categories=Object.fromEntries(['characters','props','textures','animations'].map(name=>[name,{state:'pending_reader',raw_state:'inventoried',full_source_verified:false}]));
const status={game_id:gid,categories,writer:null,tasks:[],inventory:{source:{archive_sha256:hash,xbe_sha256:'c'.repeat(64)}},exports:[],
 raw_coverage:{scope:'non-placeholder loadfile.afs members',expected:507,exported:0,complete:false,oversized_members:[]},playable_build_verified:false};
const complete={...status,raw_coverage:{...status.raw_coverage,exported:507,complete:true},exports:[{game_id:gid,worker_id:'office',source:{archive_sha256:hash},bundle_sha256:bundle,members:[{index:1}]}]};

test('raw assets show exact archive scope and safe portable downloads without replacement claims',()=>{
 const input=structuredClone(complete);input.categories.props.state='<img src=x onerror=bad()>';
 input.exports.push({...input.exports[0],game_id:'d'.repeat(16),bundle_sha256:'e'.repeat(64)});
 input.exports.push({...input.exports[0],bundle_sha256:'javascript:bad()'});
 const html=Detail.assetsHTML(input,game,{url:p=>p+'?token=test'});
 assert.ok(html.includes('507 / 507 non-placeholder members exported'));
 assert.ok(html.includes('not full-disc or decoded-model coverage'));
 assert.ok(html.includes('not insertable models or playable builds'));
 assert.ok(html.includes('Original title assets'));
 assert.ok(html.includes('/api/artifacts/'+bundle+'?token=test'));
 assert.ok(!html.includes('/api/artifacts/'+'e'.repeat(64))&&!html.includes('javascript:'));
 assert.ok(!html.includes('<img src=x'));
 assert.ok(html.includes('Raw exports complete')&&html.includes('data-ghd-action="asset-collect" disabled'));
 assert.ok(!html.includes('playable build verified'));
});

test('pending readers and failed jobs stay explicit with no invented completion percentage',()=>{
 const state=structuredClone(status);state.tasks=[{kind:'export',state:'failed',error:'Source changed <retry>'}];state.blocked_reason='Refresh native inventory after source changes';
 let html=Detail.assetsHTML(state,game);
 assert.ok(html.includes('Retry failed extraction')&&html.includes('Source changed &#60;retry&#62;'));
 assert.ok(html.includes('Refresh native inventory after source changes')&&html.includes('data-ghd-action="asset-inventory"'));
 state.tasks=[{kind:'export',state:'queued',worker_id:'office'}];html=Detail.assetsHTML(state,game);
 assert.ok(html.includes('queued')&&html.includes('<progress aria-label="export queued"></progress>'));
 assert.ok(!html.includes('value="0"'));
 const unknown=Detail.assetsHTML({game_id:gid,categories:Object.fromEntries(Object.keys(categories).map(k=>[k,{state:'pending_reader'}])),tasks:[]},game);
 assert.ok(unknown.includes('Reader unavailable')&&unknown.includes('data-ghd-action="asset-collect" disabled'));
});

test('browser: info view reads status only, collect advances once, progress and downloads update without a new viewer',async()=>{
 await withPage(async(evaluate,send)=>{
  await send('Emulation.setDeviceMetricsOverride',{width:1200,height:1000,deviceScaleFactor:1,mobile:false});
  await evaluate(source);
  await evaluate(`document.body.style='background:#111722;color:#e2e9f8;padding:18px';document.body.innerHTML='<div id="detail"></div>';var calls=[],opened=[],next=${JSON.stringify(status)},finish;var ctl=GBoxHomeDetail.mount(document.querySelector('#detail'),${JSON.stringify(fixture)},{url:p=>p+'?token=test',models:(...a)=>opened.push(a),api:async(p,body)=>{calls.push({p,body});if(body)return new Promise(resolve=>finish=resolve);return next;}});ctl.ready;`);
  assert.deepEqual(await evaluate('calls'),[{p:'/api/title-assets/'+gid}]);
  assert.equal(await evaluate(`document.querySelectorAll('.ghd-asset-categories>div').length`),4);
  assert.equal(await evaluate(`document.querySelector('[data-ghd-action=asset-collect]').textContent`),'Continue extraction');
  await evaluate(`document.querySelector('[data-ghd-action=asset-collect]').click();document.querySelector('[data-ghd-action=asset-collect]').click();new Promise(r=>setTimeout(r,10));`);
  assert.equal(await evaluate('calls.length'),2);
  assert.deepEqual(await evaluate('calls[1]'),{p:'/api/title-assets/'+gid+'/collect',body:{categories:['characters','props','textures','animations']}});
  await evaluate(`finish({...next,tasks:[{kind:'export',state:'running',worker_id:'office'}]});new Promise(r=>setTimeout(r,10));`);
  assert.equal(await evaluate(`document.querySelector('[data-ghd-action=asset-collect]').disabled`),true);
  assert.equal(await evaluate(`document.querySelector('.ghd-asset-jobs progress').hasAttribute('value')`),false);
  await evaluate(`next=${JSON.stringify(complete)};document.querySelector('[data-ghd-action=asset-status]').click();new Promise(r=>setTimeout(r,10));`);
  assert.equal(await evaluate(`document.querySelector('.ghd-asset-downloads a').getAttribute('href')`),'/api/artifacts/'+bundle+'?token=test');
  assert.equal(await evaluate(`document.querySelector('[data-ghd-action=asset-collect]').textContent`),'Raw exports complete');
  assert.equal(await evaluate('calls.filter(c=>c.body).length'),1);
  await evaluate(`document.querySelector('[data-ghd-title-assets] [data-ghd-action=models]').click();new Promise(r=>setTimeout(r,10));`);
  assert.deepEqual(await evaluate('opened'),[[gid,'Dead or Alive 3']]);
  assert.equal(await evaluate(`document.querySelector('[data-ghd-title-assets]').scrollWidth<=document.querySelector('[data-ghd-title-assets]').clientWidth`),true);
  if(process.env.GBOX_TITLE_ASSETS_EVIDENCE){const shot=await send('Page.captureScreenshot',{format:'png'});fs.mkdirSync(process.env.GBOX_TITLE_ASSETS_EVIDENCE,{recursive:true});fs.writeFileSync(path.join(process.env.GBOX_TITLE_ASSETS_EVIDENCE,'title-assets.png'),Buffer.from(shot.result.data,'base64'));}
  await evaluate('ctl.dispose()');
 });
});

test('browser: refreshing inventory is explicit and leaves changed-source coverage pending',async()=>{
 await withPage(async evaluate=>{
  await evaluate(source);
  const failed={...status,tasks:[{kind:'export',state:'failed',error:'Native source changed since inventory'}]};
  const reset={...status,inventory:null,exports:[],raw_coverage:{...status.raw_coverage,expected:null,exported:0},tasks:[{kind:'inventory',state:'queued',worker_id:'office'}]};
  await evaluate(`document.body.innerHTML='<div id="detail"></div>';var calls=[];var ctl=GBoxHomeDetail.mount(document.querySelector('#detail'),${JSON.stringify(fixture)},{api:async(p,body)=>{calls.push({p,body});return body?${JSON.stringify(reset)}:${JSON.stringify(failed)}}});ctl.ready;`);
  assert.equal(await evaluate('calls.filter(c=>c.body).length'),0);
  await evaluate(`document.querySelector('[data-ghd-action=asset-inventory]').click();new Promise(r=>setTimeout(r,10));`);
  assert.deepEqual(await evaluate('calls[1].body'),{categories:['characters','props','textures','animations'],refresh_inventory:true,retry_failed:true});
  assert.equal(await evaluate(`document.querySelector('.ghd-asset-source')===null`),true);
  assert.ok(await evaluate(`document.querySelector('.ghd-asset-jobs').textContent.includes('inventory')`));
  await evaluate('ctl.dispose()');
 });
});

test('browser: wrong-title replies and errors cannot start work or overwrite a disposed view',async()=>{
 await withPage(async evaluate=>{
  await evaluate(source);
  await evaluate(`document.body.innerHTML='<div id="detail"></div>';var calls=[],finish;var ctl=GBoxHomeDetail.mount(document.querySelector('#detail'),${JSON.stringify(fixture)},{api:async(p,body)=>{calls.push({p,body});return {...${JSON.stringify(status)},game_id:'wrong'};}});ctl.ready;`);
  assert.ok(await evaluate(`document.querySelector('.ghd-asset-feedback').textContent.includes('different title')`));
  assert.equal(await evaluate(`document.querySelector('[data-ghd-action=asset-collect]').disabled`),true);
  await evaluate(`ctl.dispose();var ctl2=GBoxHomeDetail.mount(document.querySelector('#detail'),${JSON.stringify(fixture)},{api:()=>new Promise(resolve=>finish=resolve)});ctl2.dispose();document.querySelector('#detail').textContent='New title';finish(${JSON.stringify(status)});ctl2.ready;`);
  assert.equal(await evaluate(`document.querySelector('#detail').textContent`),'New title');
  assert.equal(await evaluate('calls.some(c=>c.body)'),false);
 });
});
