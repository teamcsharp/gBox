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
   await evaluate(`document.querySelector('[data-code]').click();document.querySelector('[data-drop]').click();`);
   assert.equal(await evaluate(`calls.filter(c=>c.i&&c.i.op!=='capabilities').length`),0);
  }
  if(process.env.GBOX_PSO_EVIDENCE&&platform==='dcv2'){
   await evaluate(`document.body.style='background:#16171c;color:#eee;font:14px system-ui;padding:25px';document.head.insertAdjacentHTML('beforeend','<style>:root{--line:#444;--mut:#aab}input,select,button{background:#242735;color:#eee;border:1px solid #667;border-radius:4px;padding:5px}button{margin:3px}</style>');document.body.insertAdjacentHTML('beforeend','<p>PSO controls UI fixture — no game or imported skin shown.</p>');`);
   const shot=await send('Page.captureScreenshot',{format:'png'});fs.mkdirSync(process.env.GBOX_PSO_EVIDENCE,{recursive:true});fs.writeFileSync(path.join(process.env.GBOX_PSO_EVIDENCE,'pso-controls.png'),Buffer.from(shot.result.data,'base64'));
  }
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
