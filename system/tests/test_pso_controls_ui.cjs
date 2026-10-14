const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {withPage}=require('../scripts/browser_lifecycle.cjs');
const PSO=require('../clients/web/viz/pso-controls.js');
test('item filters update immediately and match actual class metadata',()=>{
 const rows=[{code:'a',name:'Hunter',stars:12,rare:true,cat:'Weapons',classes:['HUmar']},{code:'b',name:'Ranger',stars:12,rare:true,cat:'Weapons',classes:['RAmar']},{code:'c',name:'COMMON',stars:1,rare:false,cat:'Weapons',classes:['HUmar']}];
 assert.deepEqual(PSO.filterItems(rows,{rare:true,characterClass:'HUmar'}).map(i=>i.code),['a']);
 assert.equal(PSO.isPSO('Phantasy Star Online Episode III'),false);
});
for(const platform of ['dcv2','gc'])test(`${platform} panel pins commands and disables unsupported writes`,async()=>{
 await withPage(async(evaluate,send)=>{
  await send('Emulation.setDeviceMetricsOverride',{width:1000,height:1050,deviceScaleFactor:1,mobile:false});
  await evaluate(fs.readFileSync(path.join(__dirname,'../clients/web/viz/pso-controls.js'),'utf8'));
  await evaluate(`document.body.innerHTML='<div id="host" style="width:430px"></div>';window.calls=[];
   window.waitFor=async fn=>{for(let n=0;n<300;n++){if(fn())return;await new Promise(r=>setTimeout(r,10));}throw Error('PSO panel timeout')};
   window.io={api:async(p,b)=>{calls.push({p,b});return p.includes('/items')?[{code:'001000',name:'Rare hunter blade',cat:'Weapons',stars:12,rare:true,classes:['HUmar'],max_grind:9,atp_required:800,mst_required:0,ata_required:0}]:{equip_any:true};},job:async(t,i)=>{calls.push({t,i});if(i.op==='capabilities')return {version:'${platform}',supported:${platform==='dcv2'},reason:'GC revision needs verification',classes:['HUmar','RAmar'],pending:{skins:'Native skin banks pending'},multi_equip_note:'One weapon model, stacked equipment effects'};if(i.op==='floor_spawn'||i.op==='floor_rares')return {spawned:i.codes?.length||i.count,codes:i.codes||Array(i.count).fill('001000')};if(i.op==='list')return {inventory:[{slot:0,code:'001000',name:'Rare hunter blade',equipped:'weapon'}]};return {verified:true};}};
   GBoxPSO.mount(document.querySelector('#host'),io,{sid:'worker-session'});waitFor(()=>document.querySelector('[data-total]').textContent.includes('1 matches'));`);
  await evaluate(`document.querySelector('[data-class]').value='HUmar';document.querySelector('[data-class]').dispatchEvent(new Event('change'));`);
  assert.equal(await evaluate(`document.querySelector('[data-random]').disabled`),platform!=='dcv2');
  if(platform==='dcv2'){
   await evaluate(`document.querySelector('[data-code]').click();document.querySelector('[data-drop]').click();waitFor(()=>calls.some(c=>c.i?.op==='floor_spawn'));`);
   assert.deepEqual(await evaluate(`calls.find(c=>c.i?.op==='floor_spawn').i`),{session_id:'worker-session',op:'floor_spawn',count:10,radius:18,max_grind:true,codes:['001000']});
   await evaluate(`document.querySelector('[data-random]').click();waitFor(()=>calls.some(c=>c.i?.op==='floor_rares'));`);
   assert.equal(await evaluate(`calls.find(c=>c.i?.op==='floor_rares').i.character_class`),'HUmar');
   await evaluate(`document.querySelector('[data-equip]').click();waitFor(()=>calls.some(c=>c.i?.op==='equip_any'));`);
   assert.deepEqual(await evaluate(`calls.find(c=>c.p==='/api/pso/preferences'&&c.b).b`),{equip_any:false});
   await evaluate(`(async()=>{document.querySelector('[data-inventory]').click();await waitFor(()=>document.querySelector('[data-multi]'));document.querySelector('[data-multi]').click();await waitFor(()=>calls.some(c=>c.i?.op==='multi_equip'));})()`);
  }else{
   assert.equal(await evaluate(`document.querySelector('[data-search]').matches(':disabled')`),false);
   assert.equal(await evaluate(`document.querySelector('[data-class]').matches(':disabled')`),false);
   await evaluate(`document.querySelector('[data-code]').click();document.querySelector('[data-drop]').click();`);
   assert.equal(await evaluate(`calls.filter(c=>c.i&&c.i.op!=='capabilities').length`),0);
  }
  if(process.env.GBOX_PSO_EVIDENCE&&platform==='dcv2'){
   await evaluate(`document.body.style='background:#16171c;color:#eee;font:14px system-ui;padding:25px';document.head.insertAdjacentHTML('beforeend','<style>:root{--line:#444;--mut:#aab}input,select,button{background:#242735;color:#eee;border:1px solid #667;border-radius:4px;padding:5px}button{margin:3px}</style>');document.body.insertAdjacentHTML('beforeend','<p>PSO controls UI fixture — no game or imported skin shown.</p>');`);
   const shot=await send('Page.captureScreenshot',{format:'png'});fs.mkdirSync(process.env.GBOX_PSO_EVIDENCE,{recursive:true});fs.writeFileSync(path.join(process.env.GBOX_PSO_EVIDENCE,'pso-controls.png'),Buffer.from(shot.result.data,'base64'));
  }
 });
});

for(const version of ['dcv2','gc'])test(`${version}: preferences 404 does not disable item browsing or supported actions`,async()=>{
 await withPage(async(evaluate,send)=>{
  await send('Emulation.setDeviceMetricsOverride',{width:900,height:1200,deviceScaleFactor:1,mobile:false});
  await evaluate(fs.readFileSync(path.join(__dirname,'../clients/web/viz/pso-controls.js'),'utf8'));
  await evaluate(`document.body.innerHTML='<div id="host" style="width:400px"></div>';var calls=[],failPrefs=true;
    var waitFor=async fn=>{for(let n=0;n<300;n++){if(fn())return;await new Promise(r=>setTimeout(r,10));}throw Error('PSO fallback timeout')};
    var io={api:async(p,b)=>{calls.push({p,b});if(p.includes('/items'))return [
      {code:'001000',name:'Rare sword',cat:'Weapons',stars:12,rare:true,classes:['HUmar'],max_grind:9},
      {code:'010100',name:'Frame',cat:'Armor',stars:1,rare:false,classes:['HUmar']}];
      if(failPrefs)throw Error('404 {"detail":"Not Found"}');return {equip_any:true};},
    job:async(t,i)=>{calls.push({t,i});return i.op==='capabilities'?{version:'${version}',supported:${version==='dcv2'},reason:'GC revision needs verification',classes:['HUmar','RAmar'],pending:{},multi_equip_note:''}:{spawned:1,codes:['001000'],verified:true}}};
    GBoxPSO.mount(document.querySelector('#host'),io,{sid:'worker-session'});waitFor(()=>document.querySelector('[data-status]').textContent.includes('Equipment default unavailable'));`);
  assert.equal(await evaluate(`document.querySelector('[data-search]').matches(':disabled')`),false);
  assert.equal(await evaluate(`document.querySelector('[data-class]').matches(':disabled')`),false);
  assert.equal(await evaluate(`document.querySelector('[data-equip]').matches(':disabled')`),true);
  assert.equal(await evaluate(`document.querySelector('[data-equip]').indeterminate`),true,'unknown saved setting is not presented as off');
  assert.doesNotMatch(await evaluate(`document.querySelector('[data-status]').textContent`),/404|Not Found/);
  await evaluate(`document.querySelector('[data-code]').click();document.querySelector('[data-search]').value='missing';document.querySelector('[data-search]').dispatchEvent(new Event('input'));`);
  assert.match(await evaluate(`document.querySelector('[data-total]').textContent`),/0 matches/);
  await evaluate(`document.querySelector('[data-search]').value='';document.querySelector('[data-search]').dispatchEvent(new Event('input'));document.querySelector('[data-class]').value='HUmar';document.querySelector('[data-class]').dispatchEvent(new Event('change'));`);
  assert.equal(await evaluate(`document.querySelector('[data-drop]').matches(':disabled')`),version==='gc');
  await evaluate(`document.querySelector('[data-drop]').click();new Promise(r=>setTimeout(r,20));`);
  assert.equal(await evaluate(`calls.filter(c=>c.i?.op==='floor_spawn').length`),version==='dcv2'?1:0);
  await evaluate(`failPrefs=false;document.querySelector('[data-retry]').click();waitFor(()=>!document.querySelector('[data-equip]').matches(':disabled'));`);
  assert.equal(await evaluate(`document.querySelector('[data-equip]').checked`),true);
  assert.equal(await evaluate(`document.querySelector('[data-class]').options.length`),3,'retry does not duplicate class choices');
  if(version==='gc'){
   await evaluate(`document.querySelector('[data-equip]').click();new Promise(r=>setTimeout(r,20));`);
   assert.deepEqual(await evaluate(`calls.filter(c=>c.p==='/api/pso/preferences'&&c.b).at(-1).b`),{equip_any:false});
   assert.equal(await evaluate(`calls.filter(c=>c.i?.op==='equip_any').length`),0,'saving the shared default must not apply DC writes to GC');
  }
  if(process.env.GBOX_PSO_PANEL_EVIDENCE&&version==='gc'){
   await evaluate(`document.body.style='background:#16171c;color:#eee;font:14px system-ui;padding:15px';document.head.insertAdjacentHTML('beforeend','<style>:root{--line:#444;--mut:#aab}input,select,button{background:#242735;color:#eee;border:1px solid #667;border-radius:4px;padding:5px}fieldset:disabled{opacity:.5}button{margin:3px}</style>');`);
   const shot=await send('Page.captureScreenshot',{format:'png'});fs.mkdirSync(process.env.GBOX_PSO_PANEL_EVIDENCE,{recursive:true});fs.writeFileSync(path.join(process.env.GBOX_PSO_PANEL_EVIDENCE,'gc-browsing.png'),Buffer.from(shot.result.data,'base64'));
  }
 });
});

test('catalog failure preserves equipment preferences and retry recovers the database',async()=>{
 await withPage(async evaluate=>{
  await evaluate(fs.readFileSync(path.join(__dirname,'../clients/web/viz/pso-controls.js'),'utf8'));
  await evaluate(`document.body.innerHTML='<div id="host"></div>';var failCatalog=true;
    var waitFor=async fn=>{for(let n=0;n<300;n++){if(fn())return;await new Promise(r=>setTimeout(r,10));}throw Error('PSO catalog retry timeout')};
    var io={job:async()=>({version:'dcv2',supported:true,classes:['HUmar'],pending:{},multi_equip_note:''}),
      api:async p=>{if(p.includes('/items')){if(failCatalog)throw Error('Disc unavailable');return [];}return {equip_any:true};}};
    GBoxPSO.mount(document.querySelector('#host'),io,{sid:'worker-session'});waitFor(()=>document.querySelector('[data-status]').textContent.includes('Item database unavailable'));`);
  assert.equal(await evaluate(`document.querySelector('[data-controls]').disabled`),true);
  assert.equal(await evaluate(`document.querySelector('[data-equip]').matches(':disabled')`),false);
  await evaluate(`failCatalog=false;document.querySelector('[data-retry]').click();waitFor(()=>!document.querySelector('[data-controls]').disabled);`);
  assert.match(await evaluate(`document.querySelector('[data-total]').textContent`),/0 matches/);
 });
});

test('a stalled preference read does not block a loaded catalog or supported drops',async()=>{
 await withPage(async evaluate=>{
  await evaluate(fs.readFileSync(path.join(__dirname,'../clients/web/viz/pso-controls.js'),'utf8'));
  await evaluate(`document.body.innerHTML='<div id="host"></div>';var calls=[],prefsReply;
    var waitFor=async fn=>{for(let n=0;n<300;n++){if(fn())return;await new Promise(r=>setTimeout(r,10));}throw Error('PSO independent load timeout')};
    var io={job:async(t,i)=>{calls.push(i);return i.op==='capabilities'?{version:'dcv2',supported:true,classes:['HUmar'],pending:{},multi_equip_note:''}:{spawned:1,codes:['001000'],verified:true}},
      api:async p=>p.includes('/items')?[{code:'001000',name:'Sword',cat:'Weapons',stars:1,classes:['HUmar']}]:new Promise(r=>prefsReply=r)};
    GBoxPSO.mount(document.querySelector('#host'),io,{sid:'worker-session'});waitFor(()=>document.querySelector('[data-code]'));`);
  await evaluate(`document.querySelector('[data-code]').click();document.querySelector('[data-drop]').click();waitFor(()=>calls.some(i=>i.op==='floor_spawn'));`);
  assert.equal(await evaluate(`document.querySelector('[data-equip]').matches(':disabled')`),true);
  await evaluate(`prefsReply({equip_any:true});waitFor(()=>!document.querySelector('[data-equip]').matches(':disabled'));`);
 });
});
test('reopening the same session discards an older capability reply',async()=>{
 await withPage(async evaluate=>{
  await evaluate(fs.readFileSync(path.join(__dirname,'../clients/web/viz/pso-controls.js'),'utf8'));
  await evaluate(`document.body.innerHTML='<div id="host"></div>';window.n=0;
   window.waitFor=async fn=>{for(let n=0;n<300;n++){if(fn())return;await new Promise(r=>setTimeout(r,10));}throw Error('PSO remount timeout')};
   window.cap={version:'dcv2',supported:true,classes:['HUmar'],pending:{},multi_equip_note:''};
   window.io={job:()=>++n===1?new Promise(r=>window.oldReply=r):Promise.resolve(cap),api:async p=>p.includes('/items')?[]:{equip_any:true}};
   const h=document.querySelector('#host');GBoxPSO.mount(h,io,{sid:'same-session'});GBoxPSO.mount(h,io,{sid:'same-session'});
   waitFor(()=>h.querySelector('[data-status]').textContent.startsWith('Choose items'));`);
  await evaluate(`oldReply({...cap,supported:false,reason:'STALE REPLY'});new Promise(r=>setTimeout(r,20));`);
  assert.doesNotMatch(await evaluate(`document.querySelector('[data-profile]').textContent`),/STALE/);
 });
});
