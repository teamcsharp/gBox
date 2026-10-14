const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),http=require('node:http');
const {withPage}=require('../scripts/browser_lifecycle.cjs');
const web=path.join(__dirname,'../clients/web');
const snapshot={worker:{id:'fixture',name:'i9-NUC / UI fixture',os:'windows',idle_seconds:900,
  resources:{cpu_percent:37,memory_percent:48,gpus:[{name:'RTX fixture',utilization_percent:51}]}},
  online:true,mode:'working',background_testing:true,budget_percent:70,
  admission:{allowed:true,reason:null},idle_reason:null,
  active:[{id:'fixture-build',tool:'character_cast',state:'running',progress:{pct:64,msg:'Packing the fitted character into the game image'},
    parent_request_id:'fixture-request',stage_log:['Model fitted to native slot','Writing game image']}],
  eligible_queue:[{id:'fixture-verify',tool:'evidence_capture',state:'queued',admission_wait:{reason:'Waiting for the build output'}}],
  recent_results:[{id:'fixture-analysis',tool:'ghidra',state:'succeeded',receipt_id:'fixture-receipt'}],
  coordinator:{runs:[{id:'fixture-coordinator',name:'Favorite-game engineering',state:'running',progress:'Inspecting the native model reader'}]},
  sessions:[],capabilities:{available:41,unavailable:{blender:'Blender is not installed on this worker'}}};

test('operations UI renders real components, progress, deferral, offline and pause without claiming goal success',async()=>{
  const calls=[];let offline=false;
  const server=http.createServer((req,res)=>{
    const url=new URL(req.url,'http://localhost');
    if(url.pathname.startsWith('/api/')){
      calls.push(req.method+' '+url.pathname);res.setHeader('Content-Type','application/json');
      if(req.method==='POST'){res.end(JSON.stringify({ok:true}));return;}
      res.end(JSON.stringify(offline?{...snapshot,online:false,mode:'offline',idle_reason:'Worker offline. Durable queued work remains on the server.'}:snapshot));return;
    }
    const file=path.resolve(web,'.'+decodeURIComponent(url.pathname));
    if(!file.startsWith(web+path.sep)||!fs.existsSync(file)){res.writeHead(404);res.end();return;}
    res.setHeader('Content-Type',file.endsWith('.html')?'text/html':'text/javascript');res.end(fs.readFileSync(file));
  });
  await new Promise(r=>server.listen(0,'127.0.0.1',r));
  try{
    await withPage(async(evaluate,send)=>{
      await send('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
      await send('Page.navigate',{url:`http://127.0.0.1:${server.address().port}/viz/background-operations.html#worker=fixture&token=fixture`});
      for(let n=0;n<100;n++){if(await evaluate(`document.querySelector('#active')?.textContent.includes('Packing the fitted')`))break;await new Promise(r=>setTimeout(r,50));}
      const text=await evaluate('document.body.textContent');
      assert.match(text,/Inspecting the native model reader/);assert.match(text,/separate from this PC/);
      assert.match(text,/37%/);assert.match(text,/51%/);assert.match(text,/70%/);
      assert.match(text,/Writing game image/);assert.match(text,/Waiting for the build output/);
      assert.match(text,/Goal verification/);assert.match(text,/not hard-throttle/);assert.match(text,/Blender is not installed/);
      assert.equal(await evaluate(`document.querySelectorAll('.flow .now').length`),3);
      if(process.env.GBOX_BACKGROUND_EVIDENCE){
        const output=path.resolve(process.env.GBOX_BACKGROUND_EVIDENCE);fs.mkdirSync(output,{recursive:true});
        await evaluate(`let label=document.createElement('div');label.textContent='UI screenshot / synthetic worker status / no gameplay evidence';label.style='background:#244974;color:white;padding:8px;font:13px system-ui';document.body.append(label);`);
        await new Promise(r=>setTimeout(r,2500));
        const shot=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:true});
        fs.writeFileSync(path.join(output,'background-operations.png'),Buffer.from(shot.result.data,'base64'));
      }
      offline=true;
      for(let n=0;n<120;n++){if(await evaluate(`document.querySelector('#mode').textContent.includes('offline')`))break;await new Promise(r=>setTimeout(r,50));}
      assert.match(await evaluate(`document.querySelector('#notice').textContent`),/Worker offline/);
      await evaluate(`document.querySelector('#pause').click()`);
      for(let n=0;n<30&&!calls.some(s=>s.startsWith('POST'));n++)await new Promise(r=>setTimeout(r,50));
      assert.deepEqual(calls.filter(s=>s.startsWith('POST')),['POST /api/testing/workers/fixture']);
    },{softwareGL:true});
  }finally{await new Promise(r=>server.close(r));}
});
