const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {withPage}=require('../scripts/browser_lifecycle.cjs');
const PSO=require('../clients/web/viz/pso-controls.js');

test('families preserve special variants and search finds named specials',()=>{
 const rows=[0,10,14].map(n=>({code:'00a9'+n.toString(16).padStart(2,'0'),name:'AXE',cat:'Weapons',family_name:'S-Rank Axe',family_key:'Weapons:esaxe',variant_name:n===10?'Hell':n===14?'Gush':'No special',display_name:'S-Rank Axe — '+(n===10?'Hell':n===14?'Gush':'No special'),stars:12}));
 assert.equal(PSO.groupItems(rows).length,1);assert.equal(PSO.groupItems(rows)[0].items.length,3);
 assert.deepEqual(PSO.filterItems(rows,{query:'hell'}).map(r=>r.code),['00a90a']);
});

async function setup(evaluate){
 await evaluate(fs.readFileSync(path.join(__dirname,'../clients/web/viz/pso-controls.js'),'utf8'));
 await evaluate(`document.body.innerHTML='<div id="host" style="width:390px"></div>';window.calls=[];window.fail=false;window.unverified=false;
  window.waitFor=async fn=>{for(let n=0;n<300;n++){if(fn())return;await new Promise(r=>setTimeout(r,10));}throw Error('PSO grouping timeout')};
  window.rows=[0,10,14].map(n=>({code:'00a9'+n.toString(16).padStart(2,'0'),name:'AXE',cat:'Weapons',family_name:'S-Rank Axe',family_key:'Weapons:esaxe',variant_name:n===10?'Hell':n===14?'Gush':'No special',display_name:'S-Rank Axe — '+(n===10?'Hell':n===14?'Gush':'No special'),stars:12,classes:['HUmar'],rare:true,
    thumbnail_url:'https://wiki.pioneer2.net/images/b/b2/ES_Axe.png',reference_url:'https://wiki.pioneer2.net/w/ES_Axe'}));
  window.io={api:async(p,b)=>{calls.push({p,b});if(p.endsWith('/rpc')){
   const input=b.args.input;if(input.op==='capabilities')return {version:'gc',supported:true,classes:['HUmar','RAmar'],pending:{},features:{enemy_drops:true},multi_equip_note:''};
   if(input.op==='floor_spawn'){await new Promise(r=>setTimeout(r,40));if(fail)throw Error('Outcome unknown');return {codes:input.codes,spawned:input.codes.length,verified:!unverified};}return {verified:true};
  }if(p.includes('/items'))return rows;
  if(p==='/api/pso/loadouts/plan')return {label:'Researched axe example',codes:['00a90a','00a90e'],items:[rows[1],rows[2]],sources:['https://example.com/pso?x=<img>'],warnings:['Not available: Example'],note:'This is a UI fixture.'};
  return {equip_any:true,enemy_drops:true,enemy_codes:['00a90a']};}};
  window.mount=GBoxPSO.mount(document.querySelector('#host'),io,{sid:'pso'});waitFor(()=>document.querySelector('[data-total]').textContent.includes('3 matches'));`);
}

test('expandable family, exact special drop, verified-only check clearing and retained enemy policy',async()=>{
 await withPage(async evaluate=>{
  await setup(evaluate);
  assert.equal(await evaluate(`document.querySelectorAll('[data-family]').length`),1);
  assert.match(await evaluate(`document.querySelector('[data-family] summary').textContent`),/S-Rank Axe.*3 variants/s);
  await evaluate(`document.querySelector('[data-family]').open=true;document.querySelector('[data-code="00a90a"]').click();document.querySelector('[data-code="00a90e"]').click();`);
  // Preferences initially select Hell, so choose it again after the explicit toggle.
  await evaluate(`if(!document.querySelector('[data-code="00a90a"]').checked)document.querySelector('[data-code="00a90a"]').click();`);
  // Drop immediately, before the selection's debounced enemy-policy write.
  await evaluate(`waitFor(()=>!document.querySelector('[data-drop]').disabled);document.querySelector('[data-drop]').click();waitFor(()=>document.querySelector('[data-status]').textContent.includes('items created'));`);
  assert.deepEqual(await evaluate(`calls.filter(c=>c.b?.args?.input.op==='floor_spawn').at(-1).b.args.input.codes.sort()`),['00a90a','00a90e']);
  assert.equal(await evaluate(`document.querySelectorAll('[data-code]:checked').length`),0);
  assert.equal(await evaluate(`document.querySelector('[data-enemy-on]').checked`),true);
  await evaluate(`new Promise(r=>setTimeout(r,550));waitFor(()=>calls.some(c=>c.p==='/api/pso/preferences'&&c.b?.enemy_drops));`);
  assert.equal(await evaluate(`calls.some(c=>c.p==='/api/pso/preferences'&&c.b?.enemy_drops===false)`),false,'manual drop clearing must not cancel a pending enemy policy');
  assert.match(await evaluate(`document.querySelector('[data-enemy-pool]').textContent`),/Hell/);
  const saved=await evaluate(`calls.filter(c=>c.p==='/api/pso/preferences'&&c.b).length`);
  await evaluate(`fail=true;document.querySelector('[data-code="00a90e"]').click();document.querySelector('[data-drop]').click();waitFor(()=>document.querySelector('[data-status]').textContent.includes('Outcome unknown'));`);
  assert.equal(await evaluate(`document.querySelector('[data-code="00a90e"]').checked`),true);
  assert.equal(await evaluate(`calls.filter(c=>c.b?.args?.input.op==='floor_spawn').length`),2);
  assert.equal(await evaluate(`calls.filter(c=>c.p==='/api/pso/preferences'&&c.b).length`),saved,'no preference mutation triggered by clearing manual checks');
  await evaluate(`mount.dispose()`);
 });
});

test('researched preview resolves separately, drops through live channel and invalidates when class changes',async()=>{
 await withPage(async(evaluate,send)=>{
  await setup(evaluate);
  await evaluate(`document.querySelector('[data-loadout-preset]').value='import';document.querySelector('[data-loadout-preset]').dispatchEvent(new Event('change'));document.querySelector('[data-loadout-names]').value='1. S-Rank Axe — Hell\\n2. 00a90e';document.querySelector('[data-loadout-source]').value='https://example.org/tier-list';document.querySelector('[data-loadout-preview]').click();waitFor(()=>!document.querySelector('[data-loadout-drop]').disabled);`);
  const plan=await evaluate(`calls.find(c=>c.p==='/api/pso/loadouts/plan').b`);
  assert.deepEqual(plan.names,['S-Rank Axe — Hell','00a90e']);assert.deepEqual(plan.source_urls,['https://example.org/tier-list']);
  assert.equal(await evaluate(`calls.filter(c=>c.b?.args?.input.op==='floor_spawn').length`),0);
  assert.equal(await evaluate(`document.querySelector('[data-loadout-result]').querySelector('img')`),null,'source URLs are escaped');
  await evaluate(`document.querySelector('[data-loadout-drop]').click();waitFor(()=>document.querySelector('[data-status]').textContent.includes('2 / 2'));`);
  assert.deepEqual(await evaluate(`calls.find(c=>c.b?.args?.input.op==='floor_spawn').b.args.input.codes`),['00a90a','00a90e']);
  await evaluate(`document.querySelector('[data-class]').value='RAmar';document.querySelector('[data-class]').dispatchEvent(new Event('change'));`);
  assert.equal(await evaluate(`document.querySelector('[data-loadout-drop]').disabled`),true);
  await evaluate(`mount.dispose()`);
 });
});
