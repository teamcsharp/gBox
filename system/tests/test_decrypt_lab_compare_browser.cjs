'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),http=require('node:http');
const {withPage}=require('../scripts/browser_lifecycle.cjs');

test('comparison window renders both models and synchronizes frame, view and joint controls',async()=>{
  const folder=path.join(__dirname,'../clients/desktop');
  const files={'/compare.js':'decrypt-lab-compare.js','/style.css':'decrypt-lab.css','/three.js':'vendor/three.min.js'};
  const server=http.createServer((req,res)=>{
    if(files[req.url]){res.setHeader('Content-Type',req.url.endsWith('.css')?'text/css':'application/javascript');res.end(fs.readFileSync(path.join(folder,files[req.url])));return;}
    res.setHeader('Content-Type','text/html; charset=utf-8');res.end('<meta charset="utf-8"><link rel="stylesheet" href="/style.css"><body><script src="/three.js"></script><script src="/compare.js"></script></body>');
  });
  await new Promise(r=>server.listen(0,'127.0.0.1',r));
  try{await withPage(async(evaluate,send)=>{
    await send('Emulation.setDeviceMetricsOverride',{width:1400,height:950,deviceScaleFactor:1,mobile:false});
    await send('Page.navigate',{url:`http://127.0.0.1:${server.address().port}`});
    for(const end=Date.now()+10000;!await evaluate('!!window.GBoxModelCompare');){if(Date.now()>end)throw Error('Comparison script did not load');await new Promise(r=>setTimeout(r,30));}
    await evaluate(`window.calls=[];
      window.model=(offset)=>({triangles:[0,1,2],frames:[0,1,2].map(frame=>({frame,positions:[0,0,0,1,0,0,0,2+frame*.1,0],skeleton:{anim_ids:[0,14],parents:[255,0],bones:[[0,0,0],[offset+frame*.1,1,0]]}}))});
      window.payload={fps:30,frame_indices:[0,1,2],clip:{animation_index:0,frame_count:150},native:model(0),candidate:model(.5)};
      window.panel=GBoxModelCompare.mount({title:'re5_switch',arcPath:'nativeNXx64/ImgNX/Archive/uPl00ChrisNormal.arc',build:'candidate',
        api:async(path,body)=>{calls.push(body);return body.op==='list'?{builds:[{name:'candidate'}],selected_animation_entry:115,motions:[{entry_index:115,name:'Walk',clips:[{index:0,frame_count:150,supported:true},{index:1,frame_count:150,supported:false,raw_fk_supported:true,reason:'Game IK'}]}]}:payload;}});
      new Promise(r=>setTimeout(r,40));`);
    assert.equal(await evaluate(`document.querySelector('[data-build]').value`),'candidate');
    assert.equal(await evaluate(`document.querySelector('[data-clip] option[value="1"]').disabled`),true);
    await evaluate(`document.querySelector('[data-raw-fk]').click()`);
    assert.equal(await evaluate(`document.querySelector('[data-clip] option[value="1"]').disabled`),false);
    await evaluate(`document.querySelector('[data-clip]').value='0';document.querySelector('[data-load]').click();new Promise(r=>setTimeout(r,80));`);
    assert.match(await evaluate(`document.querySelector('[data-status]').textContent`),/Frames 0–2 of 150/);
    assert.equal(await evaluate(`document.querySelector('[data-play]').disabled`),false);
    assert.equal(await evaluate(`document.querySelector('[data-canvas]').width>0`),true);
    await evaluate(`document.querySelector('[data-next]').click()`);
    assert.match(await evaluate(`document.querySelector('[data-time]').textContent`),/Frame 1/);
    assert.match(await evaluate(`document.querySelector('[data-difference]').textContent`),/difference: X 0.50/);
    await evaluate(`document.querySelector('[data-view="x"]').click();document.querySelector('[data-frame]').value='2';document.querySelector('[data-frame]').dispatchEvent(new Event('input'));`);
    assert.match(await evaluate(`document.querySelector('[data-time]').textContent`),/Frame 2/);
    await evaluate(`document.querySelector('[data-later]').click();new Promise(r=>setTimeout(r,50));`);
    assert.equal(await evaluate(`calls.at(-1).start_frame`),3);
    assert.equal(await evaluate(`calls.at(-1).frame_count`),60);
    await evaluate(`document.querySelector('[data-clip]').dispatchEvent(new Event('change'))`);
    assert.equal(await evaluate(`document.querySelector('[data-play]').disabled`),true);
    assert.match(await evaluate(`document.querySelector('[data-status]').textContent`),/Selection changed/);
    await evaluate(`document.querySelector('[data-load]').click();new Promise(r=>setTimeout(r,50));`);
    if(process.env.GBOX_COMPARE_FIXTURE){const payload=JSON.parse(fs.readFileSync(process.env.GBOX_COMPARE_FIXTURE,'utf8'));await evaluate(`window.realPayload=${JSON.stringify(payload)};panel.setData(realPayload);document.querySelector('[data-clip]').replaceChildren(new Option(realPayload.clip.animation_index==null?'Bind pose':'Animation '+realPayload.clip.animation_index+' · '+realPayload.clip.frame_count+' frames',realPayload.clip.animation_index??''));if(realPayload.source?.build)document.querySelector('[data-build]').replaceChildren(new Option(realPayload.source.build,realPayload.source.build));document.querySelector('[data-motion]').replaceChildren(new Option('pl00wp00','115'));document.querySelector('[data-raw-fk]').checked=realPayload.evaluation_mode==='raw_fk_without_game_ik';new Promise(r=>setTimeout(r,150));`);}
    assert.ok(await evaluate(`document.querySelectorAll('[data-joints] span').length<=8`));
    if(process.env.GBOX_COMPARE_ARTIFACT_DIR){fs.mkdirSync(process.env.GBOX_COMPARE_ARTIFACT_DIR,{recursive:true});for(const [view,name] of [['z','front'],['x','side']]){await evaluate(`document.querySelector('[data-view="${view}"]').click();new Promise(r=>setTimeout(r,100));`);const shot=await send('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(process.env.GBOX_COMPARE_ARTIFACT_DIR,`model-comparison-${name}.png`),Buffer.from(shot.result.data,'base64'));}}
    await evaluate(`document.querySelector('[data-close]').click()`);
    assert.equal(await evaluate(`document.querySelector('.model-compare')`),null);
    assert.equal(await evaluate(`calls.every(row=>row.op==='list'||row.op==='sample')`),true);
  },{timeoutMs:60000,softwareGL:true});}finally{server.closeAllConnections();await new Promise(r=>server.close(r));}
});

test('standalone comparison page opens the requested build and animation without the desktop shell',async()=>{
  const folder=path.join(__dirname,'../clients/desktop');
  const allowed=new Set(['decrypt-lab-compare-window.html','decrypt-lab-compare-window.js','decrypt-lab-compare.js','decrypt-lab.css','vendor/three.min.js']);
  const server=http.createServer((req,res)=>{const file=req.url.slice(1);if(!allowed.has(file)){res.statusCode=404;res.end();return;}res.setHeader('Content-Type',file.endsWith('.html')?'text/html; charset=utf-8':file.endsWith('.css')?'text/css':'application/javascript');res.end(fs.readFileSync(path.join(folder,file)));});
  await new Promise(r=>server.listen(0,'127.0.0.1',r));
  try{await withPage(async(evaluate,send)=>{
    await send('Page.addScriptToEvaluateOnNewDocument',{source:`window.calls=[];window.wasClosed=false;window.close=()=>window.wasClosed=true;
      const model={triangles:[0,1,2],frames:[0,1].map(frame=>({positions:[0,0,0,1,0,0,0,1,0],skeleton:{bones:[[0,0,0]],parents:[255],anim_ids:[0]}}))};
      window.decryptLab={info:async()=>({title:'re5_switch',arcPath:'nativeNXx64/ImgNX/Archive/uPl00ChrisNormal.arc',build:'candidate',animationIndex:25}),
        api:async(path,body)=>{calls.push(body);return body.op==='list'?{builds:[{name:'candidate'}],selected_animation_entry:115,motions:[{entry_index:115,name:'pl00wp00',clips:[{index:25,frame_count:80,supported:true}]}]}:{fps:30,frame_indices:[0,1],clip:{animation_index:25,frame_count:80},native:model,candidate:model};}};`});
    await send('Page.navigate',{url:`http://127.0.0.1:${server.address().port}/decrypt-lab-compare-window.html`});
    for(const end=Date.now()+10000;!await evaluate(`!!document.querySelector('[data-play]')&&!document.querySelector('[data-play]').disabled`);){if(Date.now()>end)throw Error('Standalone comparison did not automatically load');await new Promise(r=>setTimeout(r,30));}
    assert.equal(await evaluate(`document.getElementById('comparison-opening').hidden`),true);
    assert.equal(await evaluate(`calls.length`),2);
    assert.equal(await evaluate(`calls[1].animation_index`),25);
    assert.equal(await evaluate(`calls[1].build`),'candidate');
    assert.match(await evaluate(`document.querySelector('[data-time]').textContent`),/Frame 0/);
    await evaluate(`document.querySelector('[data-next]').click()`);
    assert.match(await evaluate(`document.querySelector('[data-time]').textContent`),/Frame 1/);
    await evaluate(`document.querySelector('[data-close]').click()`);
    assert.equal(await evaluate(`wasClosed`),true);
  },{timeoutMs:60000,softwareGL:true});}finally{server.closeAllConnections();await new Promise(r=>server.close(r));}
});
