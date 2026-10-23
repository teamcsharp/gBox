const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),http=require('node:http');
const R=require('../clients/web/viz/mercs-reviewer.js');

const samples=[
  {seq:0,at:100,frame:{player:{pos:[100,0,100],hp:1000,hp_max:1000},enemies:[{id:7,pos:[500,0,500],hp:800,hp_max:800}],clock:{score:0,combo:0,left:120}}},
  {seq:1,at:101,frame:{player:{pos:[300,0,100],hp:804,hp_max:1000},enemies:[],clock:{score:1000,combo:1,left:149}}},
  {seq:2,at:102,frame:{player:{pos:[500,0,100],hp:1000,hp_max:1000},enemies:[],clock:{score:2000,combo:2,left:148}}},
];
const geometry={points:[[0,0,0],[1000,0,0],[1000,0,1000],[0,0,1000]],triangles:[[0,1,2],[0,2,3]],boundaries:[[0,0,1],[0,1,2],[1,2,3],[1,3,0]],links:[[0,1,2,1],[1,0,0,1]],action_links:[]};
const run={id:'r:geometry',round_id:'r',title:'BLUS30491',geometry:'geometry',stage:'The Mines',character:'Sheva (Tribal)',started:100,ended:102,outcome:'completed',active:false,source_id:'atlas:BLUS30491:r:geometry',spatial:true,path:samples.map(s=>({at:s.at,pos:s.frame.player.pos})),review:{metrics:{score:2000}}};
const detail={run,geometry,samples,events:[{seq:0,at:101,kind:'checkpoint_acquired',data:{pos:[300,0,100],evidence:{clock_gain_s:30}}}],suggestions:[],next_after:2,more:false,
  notebook:{source_id:'gbox:mercs:BLUS30491:r',vector:[1,2,3],observed:{reflection:{acceptance:{completed_s_rank:false}}}},provenance:{semantic_search_performed:false}};

test('playback uses recorded time, HP and actor disappearance without interpolating a death or teleport',()=>{
  assert.deepEqual(R.playbackFrame(samples,100.5).player.pos,[200,0,100]);
  assert.equal(R.playbackFrame(samples,100.5).player.hp,1000);
  assert.equal(R.playbackFrame(samples,101).enemies.length,0);
  const jump=[samples[0],{...samples[1],frame:{...samples[1].frame,player:{pos:[10000,0,100]}}}];
  assert.deepEqual(R.playbackFrame(jump,100.5).player.pos,[100,0,100]);
  assert.equal(R.playbackFrame([],100),null);
});

test('overlays require exact title and geometry, and live sample pages deduplicate',()=>{
  assert.equal(R.sameGeometry([run,{...run,title:'OTHER'},{...run,geometry:'other'}],run).length,1);
  assert.deepEqual(R.appendSamples(samples.slice(0,2),samples.slice(1)).map(s=>s.seq),[0,1,2]);
  assert.equal(R.sampleIndex(samples,101.5),1);
});

test('drawn map coordinates roundtrip altitude and recorded positions',()=>{
  const view=R.transform(geometry.points,1000,700,2),pos=[300,145,650];
  const [x,y]=view.point(pos),back=view.world(x,y,145);
  back.forEach((v,i)=>assert.ok(Math.abs(v-pos[i])<1e-8));
});

test('native unused sentinel vertices cannot collapse a measured level map',()=>{
  const native={...geometry,points:[...geometry.points,[-431602080,-431602080,-431602080]]};
  assert.equal(R.geometryPoints(native).length,4);
  const view=R.transform(R.geometryPoints(native),1000,700);
  const a=view.point([0,0,0]),b=view.point([1000,0,1000]);
  assert.ok(Math.abs(a[0]-b[0])>600&&Math.abs(a[1]-b[1])>600);
});

test('browser: recorded map playback, state provenance, route drawing/save, live lifecycle and mobile fit',async()=>{
  const {withPage}=require('../scripts/browser_lifecycle.cjs');
  const server=http.createServer((req,res)=>{res.setHeader('content-type','text/html');res.end('<!doctype html><html><body style="margin:0;padding:16px;background:#16161a;color:#eee;font:14px system-ui"><main id="host"></main></body></html>');});
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  try{
    await withPage(async(evaluate,send)=>{
      await send('Page.navigate',{url:`http://127.0.0.1:${server.address().port}/`});
      for(let i=0;i<100&&!await evaluate(`document.readyState==='complete'`);i++)await new Promise(r=>setTimeout(r,10));
      await send('Emulation.setDeviceMetricsOverride',{width:1400,height:1000,deviceScaleFactor:1,mobile:false});
      const shellStyle=fs.readFileSync(path.join(__dirname,'../clients/web/index.html'),'utf8').match(/<style>([\s\S]*?)<\/style>/)[1];
      await evaluate(`document.documentElement.dataset.embedded='true';document.head.insertAdjacentHTML('beforeend','<style>'+${JSON.stringify(shellStyle)}+'</style>');`);
      await evaluate(`document.head.insertAdjacentHTML('beforeend','<style>'+${JSON.stringify(fs.readFileSync(path.join(__dirname,'../clients/web/viz/mercs-reviewer.css'),'utf8'))}+'</style>');`);
      await evaluate(fs.readFileSync(path.join(__dirname,'../clients/web/viz/mercs-reviewer.js'),'utf8'));
      await evaluate(`window.payload=${JSON.stringify(detail)};window.calls=[];window.saved=[];
        window.api=async(p,body)=>{calls.push(p);if(p.endsWith('/catalog'))return {games:[{id:'BLUS30491',name:'Resident Evil 5',visible_runs:1,stages:[{id:'geometry',name:'The Mines'}],characters:['Sheva (Tribal)']}]};
        if(p.includes('/runs?'))return {runs:[payload.run]};if(p.includes('/round?'))return payload;
        if(p.endsWith('/suggestions')){saved.push(body);return {...body,id:'annotation',bot_eligible:true,validation:[{reason:'measured directed floor support'}]};}
        if(p.includes('/live?'))return window.liveResponse||{live:false,reason:'not active'};throw Error(p);};
        window.ctl=GBoxMercsReviewer.mount(document.querySelector('#host'),{api});`);
      for(let i=0;i<80;i++){if(await evaluate(`document.querySelector('.mr-status').textContent==='Recorded run'`))break;await new Promise(r=>setTimeout(r,20));}
      assert.equal(await evaluate(`document.querySelectorAll('.mr-run').length`),1);
      assert.equal(await evaluate(`document.querySelector('.mr-map').width>500`),true);
      assert.equal(await evaluate(`document.querySelector('.mr-map-note').textContent.includes('1 paths on this geometry')`),true);
      await evaluate(`const slider=document.querySelector('.mr-controls input');slider.value='500';slider.dispatchEvent(new Event('input'));`);
      assert.equal(await evaluate(`document.querySelectorAll('.mr-kpi b')[0].textContent`),'1000');
      await evaluate(`document.querySelector('.mr-sidebar .mr-param').click()`);
      assert.equal(await evaluate(`document.querySelector('dialog').open`),true);
      assert.match(await evaluate(`document.querySelector('dialog p').textContent`),/atlas:BLUS30491/);
      await evaluate(`document.querySelector('dialog').close();document.querySelector('.mr-editbar button').click();`);
      await evaluate(`(()=>{const c=document.querySelector('.mr-map'),r=c.getBoundingClientRect();for(const [type,x,y] of [['pointerdown',.4,.4],['pointermove',.7,.6],['pointerup',.7,.6]])c.dispatchEvent(new PointerEvent(type,{clientX:r.left+r.width*x,clientY:r.top+r.height*y,pointerId:1,bubbles:true}));})()`);
      await evaluate(`document.querySelectorAll('.mr-editbar button')[2].click()`);
      for(let i=0;i<40&&!await evaluate(`saved.length`);i++)await new Promise(r=>setTimeout(r,20));
      assert.equal(await evaluate(`saved[0]?.geometry`),'geometry');
      assert.equal(await evaluate(`saved[0]?.points.length>=2`),true);
      if(process.env.GBOX_REVIEWER_EVIDENCE){fs.mkdirSync(process.env.GBOX_REVIEWER_EVIDENCE,{recursive:true});await evaluate(`document.querySelector('dialog').close()`);const shot=await send('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(process.env.GBOX_REVIEWER_EVIDENCE,'mercs-reviewer-desktop.png'),Buffer.from(shot.result.data,'base64'));}
      await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
      await new Promise(r=>setTimeout(r,100));
      const fit=await evaluate(`({scroll:document.documentElement.scrollWidth,width:innerWidth,right:document.querySelector('.mr-map').getBoundingClientRect().right})`);
      assert.ok(fit.scroll<=fit.width&&fit.right<=fit.width,JSON.stringify(fit));
      await evaluate(`payload.run.active=true;window.liveResponse={live:true,frame:{...payload.samples[2].frame,age_s:.1,player:{pos:[700,0,700],hp:250,hp_max:1000}},stats:{phase:'gather_time'},provenance:{recorded:false}};
        const live=document.querySelector('.mr-live input');live.checked=true;live.dispatchEvent(new Event('change'));`);
      for(let i=0;i<80&&!await evaluate(`document.querySelectorAll('.mr-kpi b')[2].textContent==='250 / 1000'`);i++)await new Promise(r=>setTimeout(r,20));
      assert.equal(await evaluate(`document.querySelectorAll('.mr-kpi b')[2].textContent`),'250 / 1000');
      assert.equal(await evaluate(`calls.some(p=>p.includes('/live?'))`),true);
      const before=await evaluate(`calls.length`);await evaluate(`ctl.dispose()`);await new Promise(r=>setTimeout(r,650));
      assert.equal(await evaluate(`calls.length`),before,'disposed reviewer performs no further polling');
    },{timeoutMs:45000});
  }finally{await new Promise(resolve=>server.close(resolve));}
});

test('browser: pending route saves stay disabled and cannot modify a newly selected run',async()=>{
  const {withPage}=require('../scripts/browser_lifecycle.cjs');
  const server=http.createServer((req,res)=>{res.setHeader('content-type','text/html');res.end('<!doctype html><main id="host"></main>');});
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  try{
    await withPage(async(evaluate,send)=>{
      await send('Page.navigate',{url:`http://127.0.0.1:${server.address().port}/`});
      for(let i=0;i<100&&!await evaluate(`document.readyState==='complete'`);i++)await new Promise(r=>setTimeout(r,10));
      await send('Emulation.setDeviceMetricsOverride',{width:1400,height:1000,deviceScaleFactor:1,mobile:false});
      await evaluate(`document.head.insertAdjacentHTML('beforeend','<style>'+${JSON.stringify(fs.readFileSync(path.join(__dirname,'../clients/web/viz/mercs-reviewer.css'),'utf8'))}+'</style>');`);
      await evaluate(fs.readFileSync(path.join(__dirname,'../clients/web/viz/mercs-reviewer.js'),'utf8'));
      await evaluate(`window.first=${JSON.stringify(detail)};
        window.other={...first,run:{...first.run,id:'other:other-geometry',geometry:'other-geometry',stage:'Other stage'},suggestions:[]};
        window.saved=[];window.api=async(p,body)=>{
          if(p.endsWith('/catalog'))return {games:[{id:'BLUS30491',name:'Resident Evil 5',visible_runs:2,stages:[],characters:[]}]};
          if(p.includes('/runs?'))return {runs:[first.run,other.run]};
          if(p.includes('/round?'))return new URLSearchParams(p.split('?')[1]).get('id')===other.run.id?other:first;
          if(p.endsWith('/suggestions')){saved.push(body);return new Promise(resolve=>window.finishSave=()=>resolve({...body,id:'old-annotation',bot_eligible:true,validation:[{reason:'measured directed floor support'}]}));}
          if(p.includes('/live?'))return {live:false,reason:'not active'};throw Error(p);};
        window.ctl=GBoxMercsReviewer.mount(document.querySelector('#host'),{api});`);
      for(let i=0;i<80&&!await evaluate(`document.querySelector('.mr-status').textContent==='Recorded run'`);i++)await new Promise(r=>setTimeout(r,20));
      const draw=async()=>evaluate(`(()=>{const c=document.querySelector('.mr-map'),r=c.getBoundingClientRect();for(const [type,x,y] of [['pointerdown',.4,.4],['pointermove',.7,.6],['pointerup',.7,.6]])c.dispatchEvent(new PointerEvent(type,{clientX:r.left+r.width*x,clientY:r.top+r.height*y,pointerId:1,bubbles:true}));})()`);
      await evaluate(`document.querySelector('.mr-editbar button').click()`);await draw();
      await evaluate(`document.querySelectorAll('.mr-editbar button')[2].click()`);
      await new Promise(r=>setTimeout(r,100));
      assert.equal(await evaluate(`document.querySelectorAll('.mr-editbar button')[2].disabled`),true,'animation must preserve pending save state');
      await evaluate(`document.querySelectorAll('.mr-editbar button')[2].onclick()`);
      assert.equal(await evaluate(`saved.length`),1,'handler also refuses duplicate submissions');
      await evaluate(`document.querySelector('[data-run="other:other-geometry"]').click()`);
      for(let i=0;i<80&&!await evaluate(`document.querySelector('.mr-map-note').textContent.includes('Other stage')`);i++)await new Promise(r=>setTimeout(r,20));
      await draw();
      await evaluate(`finishSave()`);await new Promise(r=>setTimeout(r,80));
      assert.equal(await evaluate(`saved[0].geometry`),'geometry');
      assert.equal(await evaluate(`document.querySelector('dialog').open`),false,'old save result must not open a dialog on the new run');
      assert.equal(await evaluate(`document.querySelectorAll('.mr-editbar button')[2].disabled`),false,'new-run drawing must survive the old save response');
      assert.equal(await evaluate(`document.querySelector('.mr-validation').textContent.includes('Validated floor suggestion')`),false);
      assert.equal(await evaluate(`other.suggestions.length`),0,'old geometry is never appended to new data');
      await evaluate(`ctl.dispose()`);
    },{timeoutMs:45000});
  }finally{await new Promise(resolve=>server.close(resolve));}
});
