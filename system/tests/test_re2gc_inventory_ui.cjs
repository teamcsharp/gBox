const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {withPage}=require('../scripts/browser_lifecycle.cjs');
const scripts=['re2gc-inventory.js','native-inventory.js'].map(n=>fs.readFileSync(path.join(__dirname,'../clients/web/viz',n),'utf8'));
test('RE2 panel pins edits, sends fresh token, restricts equipment and blocks unknown retries',async()=>{
 await withPage(async evaluate=>{
  for(const script of scripts)await evaluate(script);
  await evaluate(`window.calls=[];window.pending=null;window.ready={verified:true,editable:true,capacity:8,inventory_sha256:'fresh-token',equipped:{item_id:2},items:[{id:0,name:'Empty'},{id:2,name:'Leon handgun'},{id:3,name:'Claire handgun'}],weapons:[{id:0,name:'Unarmed'},{id:2,name:'Leon handgun'}],inventory:[{slot:0,item_id:2,name:'Leon handgun',quantity:18,equipped:true},{slot:1,item_id:3,name:'Claire handgun',quantity:13}],item_box:[{slot:0,item_id:3,name:'Claire handgun',quantity:13}]};
   window.waitFor=async f=>{for(let n=0;n<300;n++){if(f())return;await new Promise(r=>setTimeout(r,10));}throw Error('inventory timeout')};
   window.api=async(p,b)=>{calls.push({p,b});if(p==='/api/workers')return [{id:'jay',os:'windows',online:true,tools:['re2gc_items']}];if(b?.input.op==='set')return new Promise(r=>pending=r);return {id:'j',state:'succeeded',output:{result:ready}}};
   window.panel=GBoxNativeInventory.mount(document.body,{session_id:'jay-game',platform:'gamecube',game_id:'c6adbfa00c20aaf9',adapter:'dolphin',detail:{emulator:'dolphin (Windows)'}},{api});waitFor(()=>!document.querySelector('[data-re2-set]').disabled);`);
  assert.equal(await evaluate(`document.querySelector('[data-re2-equip]').disabled`),false);
  await evaluate(`document.querySelector('[data-re2-slot]').value='1';document.querySelector('[data-re2-slot]').dispatchEvent(new Event('change'));`);
  assert.equal(await evaluate(`document.querySelector('[data-re2-equip]').disabled`),true,'placeholder weapon cannot be equipped');
  await evaluate(`document.querySelector('[data-re2-qty]').value='250';document.querySelector('[data-re2-set]').click();document.querySelector('[data-re2-set]').click();waitFor(()=>pending!==null);`);
  const edits=await evaluate(`calls.filter(c=>c.b?.input.op==='set')`);
  assert.equal(edits.length,1);assert.equal(edits[0].b.require_worker,'jay');assert.equal(edits[0].b.tool,'re2gc_items');
  assert.deepEqual(edits[0].b.input,{session_id:'jay-game',op:'set',region:'inventory',slot:1,item_id:3,quantity:250,expected_inventory_sha256:'fresh-token'});
  await evaluate(`pending({state:'succeeded',output:{result:{verified:false,outcome:'unknown',error:'Native close unconfirmed'}}});waitFor(()=>!document.querySelector('[data-re2-refresh]').disabled);`);
  assert.equal(await evaluate(`document.querySelector('[data-re2-set]').disabled`),true);
  await evaluate(`document.querySelector('[data-re2-refresh]').click();waitFor(()=>!document.querySelector('[data-re2-set]').disabled);`);
  await evaluate(`document.querySelector('[data-re2-region]').value='box';document.querySelector('[data-re2-region]').dispatchEvent(new Event('change'));`);
  assert.equal(await evaluate(`document.querySelector('[data-re2-equip]').disabled`),true);
  await evaluate(`ready={...ready,editable:false,requirements:['Open the inventory']};document.querySelector('[data-re2-refresh]').click();waitFor(()=>!document.querySelector('[data-re2-refresh]').disabled);`);
  assert.equal(await evaluate(`document.querySelector('[data-re2-set]').disabled`),true);
  await evaluate(`panel.dispose();`);
  assert.equal(await evaluate(`document.querySelector('[data-dock=native-items]')`),null);
 });
});


test('RE2 Linux, unavailable, offline and unknown workers never receive inventory jobs',async()=>{
 await withPage(async evaluate=>{
  for(const script of scripts)await evaluate(script);
  await evaluate(`window.jobs=[];window.owner={id:'spark',os:'linux',online:true,tools:[]};
   window.waitFor=async f=>{for(let n=0;n<300;n++){if(f())return;await new Promise(r=>setTimeout(r,10));}throw Error('inventory timeout')};
   window.api=async(p,b)=>{if(p==='/api/workers')return owner?[owner]:[];jobs.push({p,b});throw Error('must not queue');};
   window.mountPanel=()=>GBoxNativeInventory.mount(document.body,{session_id:'spark-game',platform:'gamecube',game_id:'c6adbfa00c20aaf9',adapter:'dolphin',detail:{emulator:'dolphin'}},{api});
   window.panel=mountPanel();waitFor(()=>!document.querySelector('[data-re2-refresh]').disabled);`);
  assert.match(await evaluate(`document.querySelector('[data-re2-status]').textContent`),/unavailable for this linux session/);
  assert.equal(await evaluate(`document.querySelector('[data-re2-set]').disabled`),true);
  for(const owner of [{id:'spark',os:'windows',online:true,tools:[]},{id:'spark',os:'windows',online:false,tools:['re2gc_items']},null]){
   await evaluate(`owner=${JSON.stringify(owner)};document.querySelector('[data-re2-refresh]').click();waitFor(()=>!document.querySelector('[data-re2-refresh]').disabled);`);
   assert.equal(await evaluate(`document.querySelector('[data-re2-set]').disabled`),true);
  }
  await evaluate(`panel.dispose();owner={id:'spark',os:'windows',online:true,tools:['re2gc_items']};panel=GBoxNativeInventory.mount(document.body,{session_id:'spark-game',platform:'gamecube',game_id:'c6adbfa00c20aaf9'},{api});waitFor(()=>!document.querySelector('[data-re2-refresh]').disabled);`);
  assert.match(await evaluate(`document.querySelector('[data-re2-status]').textContent`),/emulator is not verified/);
  await evaluate(`panel.dispose();panel=GBoxNativeInventory.mount(document.body,{session_id:'spark-game',platform:'gamecube',game_id:'c6adbfa00c20aaf9',adapter:'retroarch',detail:{emulator:'dolphin (Windows)'}},{api});waitFor(()=>!document.querySelector('[data-re2-refresh]').disabled);`);
  assert.match(await evaluate(`document.querySelector('[data-re2-status]').textContent`),/verified standalone Dolphin/);
  assert.deepEqual(await evaluate(`jobs`),[]);
  assert.equal(await evaluate(`document.querySelector('[data-dock=native-items]').textContent.includes('game?')`),false);
  await evaluate(`panel.dispose()`);
 });
});
