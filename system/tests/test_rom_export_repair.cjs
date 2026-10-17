const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {withPage}=require('../scripts/browser_lifecycle.cjs');
test('browser: failed empty export requires choosing a mod before another job is submitted',async()=>{
 await withPage(async evaluate=>{
  await evaluate(fs.readFileSync(path.join(__dirname,'../clients/web/viz/rom-export-repair.js'),'utf8'));
  await evaluate(`document.body.innerHTML='<button id="before">Review export</button>';document.querySelector('#before').focus();var calls=[];var ctl;GBoxRomExportRepair.open({tool:'rom_export',game_id:'re2',retry:{input:{op:'export',game_id:'re2',mods:[]}}},{api:async(p,b)=>{calls.push({p,b});if(p==='/api/romexport')return {id:'corrected-export'};return {ready:!!b.mod_id,issues:b.mod_id?[]:[{message:'No modification selected.',next_step:'Choose a build.'}],options:[{label:'Native build',input:{op:'export',game_id:'re2',mod_id:'chosen'}}]};}}).then(c=>ctl=c);`);
  assert.equal(await evaluate(`document.querySelector('[data-export]').disabled`),true);
  assert.equal(await evaluate(`calls.some(x=>x.p==='/api/romexport')`),false);
  await evaluate(`var select=document.querySelector('select');select.value='0';select.dispatchEvent(new Event('change'));new Promise(r=>setTimeout(r,10));`);
  assert.equal(await evaluate(`document.querySelector('[data-export]').disabled`),false);
  await evaluate(`document.querySelector('[data-export]').click();new Promise(r=>setTimeout(r,10));`);
  const posts=await evaluate(`calls.filter(x=>x.p==='/api/romexport')`);
  assert.deepEqual(posts,[{p:'/api/romexport',b:{game_id:'re2',mod_id:'chosen'}}]);
  assert.ok(await evaluate(`document.querySelector('[data-status]').textContent.includes('corrected-export')`));
  await evaluate(`ctl.close()`);assert.equal(await evaluate(`document.activeElement.id`),'before');
 });
});
test('browser: review errors stay visible and never enable an unchecked retry',async()=>{
 await withPage(async evaluate=>{
  await evaluate(fs.readFileSync(path.join(__dirname,'../clients/web/viz/rom-export-repair.js'),'utf8'));
  await evaluate(`var ctl;GBoxRomExportRepair.open({game_id:'game'},{api:async()=>{throw Error('Unavailable');}}).then(c=>ctl=c);`);
  assert.equal(await evaluate(`document.querySelector('[data-export]').disabled`),true);
  assert.ok(await evaluate(`document.querySelector('[data-status]').textContent.includes('Unavailable')`));
  await evaluate('ctl.close()');
 });
});

