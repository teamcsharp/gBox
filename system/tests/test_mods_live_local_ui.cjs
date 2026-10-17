const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {withPage}=require('../scripts/browser_lifecycle.cjs');
const MG=require('../clients/web/viz/mods-gallery.js');

test('broken icon requires an installed copy; download fill grows vertically',()=>{
 const m={key:'g/m',name:'m',game_id:'g'};
 assert.doesNotMatch(MG.cardHTML(m),/<button[^>]+mg-broken-toggle/);
 assert.match(MG.cardHTML(m,{localState:{state:'here'}}),/<button[^>]+mg-broken-toggle/);
 assert.doesNotMatch(MG.cardHTML(m,{localState:{state:'busy',pct:37}}),/<button[^>]+mg-broken-toggle/);
 assert.match(MG.cardHTML(m,{localState:{state:'busy',pct:37}}),/aria-orientation="vertical"[^>]*aria-valuenow="37"/);
 assert.match(MG.cardHTML(m,{localState:{state:'busy',pct:37}}),/height:37%/);
 assert.deepEqual(MG.filterMods([{key:'a',built:20},{key:'b',built:10}],{sort:'local',localKeys:new Set(['b'])}).map(m=>m.key),['b','a']);
});

test('computer selection immediately reorders copies and isolates a running download by PC',async()=>{
 await withPage(async(evaluate,send)=>{
  await send('Emulation.setDeviceMetricsOverride',{width:1000,height:850,deviceScaleFactor:1,mobile:false});
  for(const file of ['build-actions.js','build-local.js','mods-gallery.js'])await evaluate(fs.readFileSync(path.join(__dirname,'../clients/web/viz',file),'utf8'));
  await evaluate(`(async()=>{window.calls=[];window.downloadStep=0;window.copies={JAY:{'g/b':{built:true}},i9:{'g/a':{built:true}}};
   window.waitFor=async fn=>{for(let n=0;n<300;n++){if(fn())return;await new Promise(r=>setTimeout(r,10));}throw Error('Mods UI timeout');};
   document.body.style='background:#121317;color:#eee;font:14px system-ui';document.body.innerHTML='<style>button,select,input{background:#242936;color:#eee;border:1px solid #667;border-radius:4px;padding:5px}</style><div id="gallery"></div>';window.host=document.querySelector('#gallery');
   window.api=async(p,body)=>{calls.push({p,body});if(p==='/api/workers')return [{name:'JAY',os:'windows',online:true},{name:'i9',os:'windows',online:true}];
    if(p.startsWith('/api/builds/local?'))return {builds:copies[new URL(p,'http://fixture').searchParams.get('node')]};
    if(p==='/api/mods/built')return {items:[{key:'g/a',game_id:'g',name:'a',mod_title:'Newest build',built:Date.now()/1000-60,play_count:2,changes:[{donor:'sonic',slot:'player'}]},{key:'g/b',game_id:'g',name:'b',mod_title:'Earlier build',built:Date.now()/1000-120,play_count:0}]};
    if(p.endsWith('/local'))return {job_id:'download'};
    if(p==='/api/jobs/download'){downloadStep++;return downloadStep===1?{id:'download',state:'running',progress:{pct:37,msg:'Copying build'}}:{id:'download',state:'succeeded',output:{result:{size:1234}}};}
    return {};};
   window.ctl=GBoxModsGallery.mount(host,{api,here:'JAY',openMapping:o=>window.mapping=o,wait:()=>new Promise(r=>window.release=r)});
   await ctl.start();})()`);
  const order=()=>evaluate(`[...document.querySelectorAll('.mg-card')].map(c=>c.dataset.key)`);
  assert.deepEqual(await order(),['g/a','g/b'],'initial default remains newest first');
  await evaluate(`(()=>{const picker=host.querySelector('[data-mg-f=node]');picker.value='JAY';picker.dispatchEvent(new Event('change',{bubbles:true}));return waitFor(()=>host.querySelector('.mg-card').dataset.key==='g/b');})()`);
  assert.deepEqual(await order(),['g/b','g/a']);
  assert.deepEqual(await evaluate(`[...host.querySelectorAll('.mg-broken-toggle')].map(b=>b.closest('.mg-card').dataset.key)`),['g/b']);
  await evaluate(`(()=>{const picker=host.querySelector('[data-mg-f=node]');picker.value='i9';picker.dispatchEvent(new Event('change',{bubbles:true}));return waitFor(()=>host.querySelector('.mg-card').dataset.key==='g/a'&&host.querySelector('[data-key="g/a"] .mg-broken-toggle'));})()`);
  await evaluate(`host.querySelector('[data-mg=mapping]').click();`);
  assert.deepEqual(await evaluate('mapping'),{slug:'sonic',gid:'g',slot:'player',build_name:'a'});
  assert.deepEqual(await order(),['g/a','g/b']);
  await evaluate(`host.querySelector('[data-key="g/b"] [data-bl=main]').click();waitFor(()=>host.querySelector('[aria-valuenow="37"]'));`);
  assert.equal((await evaluate(`calls.find(c=>c.p==='/api/builds/g/b/local').body`)).node,'i9');
  assert.equal(await evaluate(`host.querySelector('[aria-valuenow="37"] i').style.height`),'37%');
  assert.equal(await evaluate(`host.querySelector('[data-key="g/b"] .mg-broken-toggle')!==null`),false);
  if(process.env.GBOX_MODS_PROGRESS_EVIDENCE){
    await evaluate(`const label=document.createElement('p');label.textContent='UI fixture: selected-PC inventory and simulated 37% transfer; no game launched';document.body.prepend(label);`);
    const picture=await send('Page.captureScreenshot',{format:'png'});fs.writeFileSync(process.env.GBOX_MODS_PROGRESS_EVIDENCE,Buffer.from(picture.result.data,'base64'));
  }
  await evaluate(`release();waitFor(()=>host.querySelector('[data-key="g/b"] .mg-broken-toggle'));`);
  assert.equal(await evaluate(`host.querySelector('.mg-download-progress')!==null`),false);
  await evaluate('ctl.stop();');
 });
});

test('a mapping opens its exact recorded fitting job from the retarget window',async()=>{
 await withPage(async evaluate=>{
  for(const file of ['retarget-handles.js','retarget-editor.js'])await evaluate(fs.readFileSync(path.join(__dirname,'../clients/web/viz',file),'utf8'));
  await evaluate(`window.calls=[];window.GBoxDecimationReview={open:async(job,model)=>window.opened=[job,model]};
   window.io={url:u=>u,api:async p=>{calls.push(p);if(p.includes('/fitting?'))return {jobs:[{job_id:'exact-job',models:[{key:'exact-model',label:'Sonic / Beat',triangles:{source_triangles:1384,result_triangles:400},comparison_available:true}]}]};return {resolved:{},rig_roles:{},reference:null};}};
   window.editor=GBoxRetargetEditor.open(document,io,{slug:'sonic',gid:'0123456789abcdef',slot:'character:beat',build_name:'sonic_cast'});
   window.waitFor=async fn=>{for(let n=0;n<200;n++){if(fn())return;await new Promise(r=>setTimeout(r,10));}throw Error('Mapping history timeout');};waitFor(()=>document.querySelector('[data-rt-fit-job]'));`);
  assert.ok((await evaluate('calls')).includes('/api/builds/0123456789abcdef/sonic_cast/fitting?donor=sonic'));
  await evaluate(`document.querySelector('[data-rt-fit-job]').click();waitFor(()=>window.opened);`);
  assert.deepEqual(await evaluate('opened'),['exact-job','exact-model']);
  await evaluate('editor.dispose();');
 });
});
