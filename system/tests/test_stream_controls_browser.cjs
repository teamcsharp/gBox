'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),http=require('node:http');
const {withPage}=require('../scripts/browser_lifecycle.cjs');

test('viewer opens live controls, applies verified mods and clicks flashes without replacing the stream',async()=>{
  const files=['re5-modifiers.js','re6-modifiers.js','bot-logic-sidebar.js','stream-interventions.js'];
  const session={session_id:'worker-re6',worker_id:'worker',game_id:'115f9cdbba115432',adapter:'citron',state:'running'};
  const status={fire_rate_x:4,infinite_ammo:true,magnum_speed_x:3,throw_speed_x:20,auto_qte_ram:true};
  const posts=[],flashes=[];
  const server=http.createServer(async(req,res)=>{
    if(files.some(f=>req.url==='/'+f)){
      res.setHeader('Content-Type','application/javascript');res.end(fs.readFileSync(path.join(__dirname,'../clients/web/viz',req.url.slice(1))));return;
    }
    if(req.url.startsWith('/api/')){
      res.setHeader('Content-Type','application/json');let data;
      if(req.method==='POST'){let raw='';for await(const part of req)raw+=part;data=JSON.parse(raw);posts.push(data);}
      if(req.url.startsWith('/api/sessions?')){res.end(JSON.stringify([session]));return;}
      if(req.url==='/api/jobs'){
        const input=data.input;assert.equal(data.require_worker,'worker');assert.equal(input.session_id,session.session_id);
        if(input.op==='fire_rate')status.fire_rate_x=input.multiplier;
        const result=input.op==='bot_logic'?{verified:true,title:'re6',knobs:[]}:
          input.op==='status'?status:{verified:true};
        res.end(JSON.stringify({id:'job',state:'succeeded',output:{result}}));return;
      }
      if(req.url===`/api/sessions/${session.session_id}/interventions`){
        if(data){flashes.push({id:data.request_id,op:data.op,state:'confirmed',result:data.op==='equip_primary'?{weapon:'Hydra'}:{}});res.end(JSON.stringify({request:{id:data.request_id,state:'queued'}}));}
        else res.end(JSON.stringify({available:true,capabilities:['flash_now','equip_primary'],options:{weapons:[{item:25,weapon:'Hydra'}]},requests:flashes}));return;
      }
      res.writeHead(404);res.end('{}');return;
    }
    res.end(`<body><img id="stream" src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw=="><div id="actions"></div>${files.map(f=>`<script src="/${f}"></script>`).join('')}</body>`);
  });
  await new Promise(r=>server.listen(0,'127.0.0.1',r));
  try{await withPage(async(evaluate,send)=>{
    await send('Page.navigate',{url:`http://127.0.0.1:${server.address().port}`});
    await evaluate(`new Promise(r=>{const wait=()=>window.GBoxStreamInterventions?r():setTimeout(wait,10);wait();})`);
    await evaluate(`window.changes=[];new MutationObserver(rows=>changes.push(...rows.map(r=>r.attributeName))).observe(document.querySelector('#stream'),{attributes:true});
      window.api=async(p,b)=>{const r=await fetch(p,{method:b?'POST':'GET',headers:{'Content-Type':'application/json'},body:b?JSON.stringify(b):undefined});return r.json();};
      window.mount=GBoxStreamInterventions.mount(document.querySelector('#actions'),{sid:'worker-re6',api});
      document.querySelector('[aria-label="Open active game mods and bot behavior"]').click();
      new Promise(r=>{const wait=()=>document.querySelector('[data-bl-mod="fire_rate"]:not(:disabled)')?r():setTimeout(wait,10);wait();})`);
    assert.equal(await evaluate(`document.querySelector('#bot-logic-panel').classList.contains('open')`),true);
    assert.equal(await evaluate(`getComputedStyle(document.querySelector('#bot-logic-tab')).display`),'block');
    assert.equal(await evaluate(`document.querySelector('[data-bl-mod="auto_qte_ram"]').checked`),true);
    await evaluate(`const input=document.querySelector('[data-bl-mod="fire_rate"]');input.value='30';input.dispatchEvent(new Event('change',{bubbles:true}));
      new Promise(r=>{const wait=()=>document.querySelector('[data-bl-mod="fire_rate"]:not(:disabled)')?.value==='30'?r():setTimeout(wait,10);wait();})`);
    assert.equal(status.fire_rate_x,30);
    await evaluate(`Promise.all(Array.from({length:20},()=>mount.client.flash('worker-re6'))).then(()=>mount.client.poll())`);
    assert.equal(flashes.length,20);assert.equal(new Set(flashes.map(x=>x.id)).size,20);
    assert.equal(await evaluate(`document.querySelector('#actions [role=status]').textContent`),'Flashbang detonated.');
    await evaluate(`document.querySelector('[aria-label="Choose the primary weapon for this match"]').click();
      new Promise(r=>{const wait=()=>!document.querySelector('[aria-label="Primary weapon"]').hidden?r():setTimeout(wait,10);wait();})`);
    await evaluate(`const choice=document.querySelector('[aria-label="Primary weapon"]');choice.value='25';choice.dispatchEvent(new Event('change'));
      new Promise(r=>{const wait=()=>document.querySelector('#actions [role=status]').textContent.includes('Hydra equipped')?r():setTimeout(wait,10);wait();})`);
    assert.deepEqual(posts.find(p=>p.op==='equip_primary').args,{item:25});
    assert.deepEqual(await evaluate(`changes`),[],'game image attributes remain untouched by interaction');
    await evaluate(`mount.dispose()`);
    assert.equal(await evaluate(`document.querySelector('#bot-logic-panel')`),null);
  },{timeoutMs:30000});}finally{server.closeAllConnections();await new Promise(r=>server.close(r));}
});
