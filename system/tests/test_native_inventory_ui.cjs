const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {withPage}=require('../scripts/browser_lifecycle.cjs');
const source=fs.readFileSync(path.join(__dirname,'../clients/web/viz/native-inventory.js'),'utf8');
test('native weapons stay pinned, unknown completion blocks repeats until a successful refresh',async()=>{
 await withPage(async evaluate=>{
  await evaluate(source);
  await evaluate(`window.calls=[];window.pending=null;window.fail=false;window.waitFor=async f=>{for(let n=0;n<300;n++){if(f())return;await new Promise(r=>setTimeout(r,10));}throw Error('inventory timeout')};
   window.api=async(p,b)=>{calls.push({p,b});if(fail&&b?.input.op!=='list')throw Error('Worker disconnected');if(b?.input.op==='all_weapons')return new Promise(r=>pending=r);return {id:'j',state:'succeeded',output:{result:{verified:true,weapons:[{id:0,name:'Unarmed'},{id:1,name:'Baseball bat'},{id:2,name:'Pistol'},{id:12,name:'Detonator'}],inventory:[{slot:2,present:true,name:'Pistol',ammo:100}]}}};};
   window.panel=GBoxNativeInventory.mount(document.body,{session_id:'native-game',platform:'ps2',game_id:'265819390074bb4e'},{api});waitFor(()=>!document.querySelector('[data-all]').disabled);`);
  assert.equal(await evaluate(`document.querySelector('[data-weapon]').options.length`),2);
  await evaluate(`document.querySelector('[data-all]').click();document.querySelector('[data-all]').click();waitFor(()=>pending!==null);`);
  const commands=await evaluate(`calls.filter(c=>c.b?.input.op==='all_weapons')`);
  assert.equal(commands.length,1);assert.equal(commands[0].b.require_worker,'native');
  assert.deepEqual(commands[0].b.input,{session_id:'native-game',op:'all_weapons',ammo:9999});
  await evaluate(`pending({state:'failed',error:'Native read-back unavailable'});waitFor(()=>!document.querySelector('[data-refresh]').disabled);`);
  assert.equal(await evaluate(`document.querySelector('[data-all]').disabled`),true);
  await evaluate(`document.querySelector('[data-refresh]').click();waitFor(()=>!document.querySelector('[data-give]').disabled);`);
  await evaluate(`fail=true;document.querySelector('[data-give]').click();waitFor(()=>!document.querySelector('[data-refresh]').disabled);`);
  assert.equal(await evaluate(`document.querySelector('[data-give]').disabled`),true,'lost responses never allow a second mutation without refresh');
  await evaluate(`panel.dispose();`);
  assert.equal(await evaluate(`document.querySelector('[data-dock=native-items]')`),null);
 });
});
test('unverified titles do not expose GTA native weapon writes',async()=>{
 await withPage(async evaluate=>{
  await evaluate(source);
  assert.equal(await evaluate(`GBoxNativeInventory.mount(document.body,{session_id:'w-s',platform:'gamecube',game_id:'265819390074bb4e'},{api:()=>{throw Error('must not dispatch')}})`),null);
  assert.equal(await evaluate(`GBoxNativeInventory.supported({platform:'ps2',game_id:'unknown'})`),false);
 });
});
