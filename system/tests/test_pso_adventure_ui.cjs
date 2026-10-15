const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {withPage}=require('../scripts/browser_lifecycle.cjs');

test('selected enemy loot follows edits, persists defaults, and travel stays an explicit session action',async()=>{
 await withPage(async(evaluate,send)=>{
  await send('Emulation.setDeviceMetricsOverride',{width:900,height:1500,deviceScaleFactor:1,mobile:false});
  await evaluate(fs.readFileSync(path.join(__dirname,'../clients/web/viz/pso-controls.js'),'utf8'));
  await evaluate(`document.body.innerHTML='<div id="host" style="width:430px"></div>';window.calls=[];window.prefs={equip_any:true,enemy_drops:false,enemy_codes:[],enemy_max_grind:true,walk_through:false};
   window.waitFor=async fn=>{for(let n=0;n<500;n++){if(fn())return;await new Promise(r=>setTimeout(r,10));}throw Error('Adventure UI timeout')};
   window.io={api:async(p,b)=>{calls.push({p,b});if(p.endsWith('/rpc')){const i=b.args.input;
    if(i.op==='capabilities')return {supported:true,version:'gc',classes:['HUnewearl'],features:{enemy_drops:true,walk_through:true,boss_warp:true},pending:{}};
    if(i.op==='bosses')return {default:'barba_ray',bosses:[{id:'barba_ray',name:'Barba Ray'},{id:'olga_flow',name:'Olga Flow'}]};
    return {verified:true,message:'Acknowledged '+i.op};
   }if(p.includes('/items'))return [{code:'000100',name:'Saber',cat:'Weapons',max_grind:35},{code:'000200',name:'Sword',cat:'Weapons',max_grind:20}];
   if(b)Object.assign(prefs,b);return {...prefs};}};
   window.panel=GBoxPSO.mount(document.querySelector('#host'),io,{sid:'local-gc'});waitFor(()=>!document.querySelector('[data-enemy]').disabled&&!document.querySelector('[data-boss-warp]').disabled);`);
  assert.equal(await evaluate(`document.querySelector('[data-boss]').value`),'barba_ray');
  await evaluate(`document.querySelector('[data-code="000100"]').click();document.querySelector('[data-code="000200"]').click();document.querySelector('[data-enemy-on]').click();waitFor(()=>calls.some(c=>c.b?.args?.input.op==='enemy_drops'));`);
  assert.deepEqual(await evaluate('prefs.enemy_codes'),['000100','000200']);assert.equal(await evaluate('prefs.enemy_drops'),true);
  assert.deepEqual(await evaluate(`calls.find(c=>c.b?.args?.input.op==='enemy_drops').b.args.input.codes`),['000100','000200']);
  await evaluate(`waitFor(()=>!document.querySelector('[data-enemy]').disabled);`);
  await evaluate(`document.querySelector('[data-code="000200"]').click();document.querySelector('[data-grind]').click();waitFor(()=>calls.filter(c=>c.b?.args?.input.op==='enemy_drops').length===2);`);
  const update=await evaluate(`calls.filter(c=>c.b?.args?.input.op==='enemy_drops').at(-1).b.args.input`);
  assert.deepEqual(update.codes,['000100']);assert.equal(update.max_grind,false);assert.equal(update.count,undefined);assert.equal(update.radius,undefined);
  await evaluate(`waitFor(()=>!document.querySelector('[data-walk]').matches(':disabled'));`);
  await evaluate(`document.querySelector('[data-walk]').click();waitFor(()=>calls.some(c=>c.b?.args?.input.op==='walk_through'));`);
  assert.equal(await evaluate('prefs.walk_through'),true);
  await evaluate(`waitFor(()=>!document.querySelector('[data-boss-warp]').matches(':disabled'));`);
  assert.equal(await evaluate(`calls.some(c=>c.b?.args?.input.op==='boss_warp')`),false,'loading preferences never teleports');
  await evaluate(`document.querySelector('[data-boss]').value='olga_flow';document.querySelector('[data-boss-warp]').click();waitFor(()=>calls.some(c=>c.b?.args?.input.op==='boss_warp'));`);
  assert.equal(await evaluate(`calls.find(c=>c.b?.args?.input.op==='boss_warp').b.args.input.target`),'olga_flow');
  await evaluate(`waitFor(()=>!document.querySelector('[data-enemy]').disabled);`);
  await evaluate(`document.querySelector('[data-code="000100"]').click();waitFor(()=>prefs.enemy_drops===false);`);
  assert.deepEqual(await evaluate('prefs.enemy_codes'),[]);
  await evaluate(`waitFor(()=>!document.querySelector('[data-enemy]').disabled);panel.dispose();panel=GBoxPSO.mount(document.querySelector('#host'),io,{sid:'local-gc'});waitFor(()=>!document.querySelector('[data-enemy]').disabled);`);
  assert.equal(await evaluate(`document.querySelector('[data-walk]').checked`),true,'defaults survive remount');
  if(process.env.GBOX_PSO_ADVENTURE_EVIDENCE){
   await evaluate(`document.body.style='background:#171820;color:#eee;font:14px system-ui;padding:12px';document.querySelector('[data-enemy]').scrollIntoView();document.head.insertAdjacentHTML('beforeend','<style>input,select,button{background:#272a38;color:#eee;border:1px solid #667;border-radius:4px;padding:4px}</style>');`);
   const shot=await send('Page.captureScreenshot',{format:'png'});fs.mkdirSync(process.env.GBOX_PSO_ADVENTURE_EVIDENCE,{recursive:true});fs.writeFileSync(path.join(process.env.GBOX_PSO_ADVENTURE_EVIDENCE,'pso-adventure-ui.png'),Buffer.from(shot.result.data,'base64'));
  }
  await evaluate('panel.dispose()');
 });
});
