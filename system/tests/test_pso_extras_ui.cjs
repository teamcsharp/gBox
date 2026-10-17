const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {withPage}=require('../scripts/browser_lifecycle.cjs');
test('PSO survival, timed rares and coalesced MAG edits use acknowledged session RPC',async()=>{
 await withPage(async(evaluate,send)=>{
  await send('Emulation.setDeviceMetricsOverride',{width:900,height:1900,deviceScaleFactor:1,mobile:false});
  await evaluate(fs.readFileSync(path.join(__dirname,'../clients/web/viz/pso-controls.js'),'utf8'));
  await evaluate(`document.body.innerHTML='<div id="host" style="width:440px"></div>';window.calls=[];
   window.waitFor=async fn=>{for(let n=0;n<400;n++){if(fn())return;await new Promise(r=>setTimeout(r,10));}throw Error('PSO extras timeout')};
   window.mag={id:65538,form:0,stage:0,level:5,def:5,pow:0,dex:0,mind:0,iq:0,synchro:40,color:14};
   window.panel=GBoxPSO.mount(document.querySelector('#host'),{api:async(p,b)=>{
    calls.push({p,b});if(p.endsWith('/rpc')){const i=b.args.input;
     if(i.op==='capabilities')return {supported:true,version:'gc',label:'GameCube Plus US revision 2',classes:['HUnewearl'],features:{survival:true,revive:true,randomized:true,mag:true},pending:{}};
     if(i.op==='mag_set'){Object.assign(mag,i.properties);return {mag,verified:true};}
     if(i.op==='mag'||i.op==='mag_feed')return {mag,verified:true};
     if(i.op==='randomized')return {on:i.on,interval:i.interval,cycles:1,verified:true,message:'Equipment randomized'};
     if(i.op==='modes')return {randomized:{on:false,cycles:0}};
     return {verified:true};
    }
    if(p.includes('/items'))return [{code:'020000',name:'Mag',cat:'Mags',rare:false},{code:'020100',name:'Varuna',cat:'Mags',rare:false}];
    return {equip_any:true,permanent_scape:false,legendary:false};
   }},{sid:'verified-gc'});waitFor(()=>!document.querySelector('[data-scape]').matches(':disabled'));`);
  await evaluate(`document.querySelector('[data-scape]').click();waitFor(()=>calls.some(c=>c.b?.args?.input.op==='survival'));`);
  assert.equal(await evaluate(`calls.find(c=>c.b?.args?.input.op==='survival').b.args.input.on`),true);
  await evaluate(`waitFor(()=>!document.querySelector('[data-revive]').matches(':disabled'));`);
  await evaluate(`document.querySelector('[data-revive]').click();waitFor(()=>calls.some(c=>c.b?.args?.input.op==='revive'));`);
  await evaluate(`waitFor(()=>!document.querySelector('[data-legendary]').matches(':disabled'));`);
  await evaluate(`document.querySelector('[data-legendary]').click();waitFor(()=>calls.some(c=>c.p==='/api/pso/preferences'&&c.b?.legendary===true));`);
  await evaluate(`waitFor(()=>calls.some(c=>c.b?.args?.input.op==='legendary')&&!document.querySelector('[data-randomized]').disabled);`);
  await evaluate(`document.querySelector('[data-class]').value='HUnewearl';document.querySelector('[data-randomized-on]').click();waitFor(()=>document.querySelector('[data-mode-state]').textContent.includes('Running'));`);
  await evaluate(`document.querySelector('[data-interval]').value='20';document.querySelector('[data-interval]').dispatchEvent(new Event('input'));document.querySelector('[data-interval]').dispatchEvent(new Event('change'));waitFor(()=>calls.filter(c=>c.b?.args?.input.op==='randomized').length===2);`);
  assert.equal(await evaluate(`calls.filter(c=>c.b?.args?.input.op==='randomized')[1].b.args.input.interval`),20);
  await evaluate(`waitFor(()=>!document.querySelector('[data-read-mag]').matches(':disabled'));`);
  await evaluate(`document.querySelector('[data-read-mag]').click();waitFor(()=>!document.querySelector('[data-mag-values]').disabled);`);
  await evaluate(`for(const [key,value] of [['pow','25'],['iq','170']]){const el=document.querySelector('[data-mag-property="'+key+'"]');el.value=value;el.dispatchEvent(new Event('input',{bubbles:true}));}waitFor(()=>calls.some(c=>c.b?.args?.input.op==='mag_set'));`);
  const edit=await evaluate(`calls.find(c=>c.b?.args?.input.op==='mag_set').b.args.input`);
  assert.equal(edit.item_id,65538);assert.deepEqual(edit.properties,{pow:25,iq:170});
  await evaluate(`waitFor(()=>!document.querySelector('[data-feed-mag]').matches(':disabled'));`);
  await evaluate(`document.querySelector('[data-feed-mag]').click();waitFor(()=>calls.some(c=>c.b?.args?.input.op==='mag_feed'));panel.dispose();`);
  assert.equal(await evaluate(`calls.filter(c=>c.b?.args?.input.op==='mag_set').length`),1);
  if(process.env.GBOX_PSO_EXTRAS_EVIDENCE){
   await evaluate(`document.body.style='background:#171820;color:#eee;font:14px system-ui;padding:20px';document.querySelector('[data-status]').textContent='Browser UI fixture; native game verification is separate.';document.head.insertAdjacentHTML('beforeend','<style>input,select,button{background:#272a38;color:#eee;border:1px solid #667;border-radius:4px;padding:4px}</style>');document.querySelector('[data-survival]').scrollIntoView();`);
   const shot=await send('Page.captureScreenshot',{format:'png'});fs.mkdirSync(process.env.GBOX_PSO_EXTRAS_EVIDENCE,{recursive:true});fs.writeFileSync(path.join(process.env.GBOX_PSO_EXTRAS_EVIDENCE,'pso-survival-mag-ui.png'),Buffer.from(shot.result.data,'base64'));
  }
 });
});
