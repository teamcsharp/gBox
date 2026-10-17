const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs');
const {withPage}=require('../scripts/browser_lifecycle.cjs');
test('selfie launch shows photo, face stages and texture slides; reduced motion uses the final snapshot',async()=>{
 await withPage(async(evaluate,send)=>{
  await send('Emulation.setDeviceMetricsOverride',{width:1300,height:850,deviceScaleFactor:1,mobile:false});
  await evaluate(fs.readFileSync(require.resolve('../clients/web/viz/launch-mods.js'),'utf8'));
  await evaluate(`document.body.style='margin:0;background:#14243c;color:#eee';document.body.innerHTML='<div id="loader" style="position:relative;width:100vw;height:100vh"><h1 style="position:absolute;left:50%;top:40%">gBox loading fixture</h1></div>';
   const c=document.createElement('canvas');c.width=c.height=32;const g=c.getContext('2d');g.fillStyle='#bf9473';g.fillRect(5,2,22,28);const png=c.toDataURL();
   const h=n=>String(n).repeat(64);window.meta={slug:'leon_photo_fixture',name:'Photo on Leon',photo_skin_approval:{source_photo:h(1),images:[{before:h(2),after:h(3)}],story:{geometry:'unchanged',frames:[0,.5,1].map((f,i)=>({kind:'texture_projection',label:'Photo texture '+(f*100)+'%',sha256:h(i+4)}))}}};
   window.ctl=GBoxLaunchMods.mount(document.querySelector('#loader'),{url:()=>png,fetchJson:async p=>p.includes('/details')?{characters:[{donors:[meta.slug],donor:{name:'Photo on Leon'}}]}:p.startsWith('/api/characters/')?meta:{items:[]}});
   ctl.start({gameId:'g',mod:'selfie-build'});`);
  assert.equal(await evaluate(`document.querySelector('.lm-selfie-stage img').alt`),'Source selfie');
  assert.equal(await evaluate(`document.querySelector('.lm-selfie-stage').getBoundingClientRect().right<innerWidth`),true);
  assert.match(await evaluate(`document.querySelector('.lm-selfie-stage').textContent`),/mesh shape unchanged/);
  assert.equal(await evaluate(`getComputedStyle(document.querySelector('.lm-uv-next')).animationName`),'lm-texture-in');
  await send('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-motion',value:'reduce'}]});
  await evaluate(`ctl.clear();ctl.start({gameId:'g',mod:'selfie-build'});`);
  assert.match(await evaluate(`document.querySelector('.lm-selfie-stage').textContent`),/Photo texture 100%/);
  assert.equal(await evaluate(`getComputedStyle(document.querySelector('.lm-uv-next')).animationName`),'none');
  await evaluate(`ctl.clear()`);assert.equal(await evaluate(`document.querySelector('.lm-layer').hidden`),true);
 });
});
