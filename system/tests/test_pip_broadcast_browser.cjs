'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),http=require('node:http');
const {withPage}=require('../scripts/browser_lifecycle.cjs');

test('right-click stream cards expose separate accessible broadcast actions in a compact window',async()=>{
  const desktop=fs.readFileSync(path.join(__dirname,'../clients/desktop/index.html'),'utf8');
  const style=desktop.match(/<style>([\s\S]*?)<\/style>/)[1];
  const css=fs.readFileSync(path.join(__dirname,'../clients/desktop/pip-stream-picker.css'),'utf8');
  const js=fs.readFileSync(path.join(__dirname,'../clients/desktop/pip-stream-picker.js'),'utf8');
  const server=http.createServer((req,res)=>{
    res.setHeader('Content-Type','text/html; charset=utf-8');
    res.end(`<style>${style}${css}body{margin:0}#pipmenu{display:block;left:8px;top:8px}</style><div id="pipmenu"><div id="picker" data-pip-stream-picker></div></div><script>${js}</script>`);
  });
  await new Promise(r=>server.listen(0,'127.0.0.1',r));
  try{await withPage(async(evaluate,send)=>{
    await send('Emulation.setDeviceMetricsOverride',{width:420,height:360,deviceScaleFactor:1,mobile:false});
    await send('Page.navigate',{url:`http://127.0.0.1:${server.address().port}`});
    await evaluate(`new Promise(r=>{const check=()=>window.GBoxPipStreamPicker?r():setTimeout(check,10);check();})`);
    await evaluate(`window.calls=[];window.views=[];window.data={rows:[
      {session_id:'spark-re4',state:'running',worker_online:true,worker:'spark',detail:{worker_name:'Spark'},title:'Resident Evil 4'},
      {session_id:'i9-pso',state:'running',worker_online:true,worker:'i9',detail:{worker_name:'i9'},title:'Phantasy Star Online'},
      {session_id:'off-pso',state:'running',worker_online:false,worker:'offline',detail:{worker_name:'Offline'},title:'PSO'}],hosts:[]};
      window.pick=GBoxPipStreamPicker.create({origin:()=>location.origin,read:async()=>data,show:async row=>views.push(row.session_id),broadcast:async sid=>calls.push(sid)});
      window.panel=GBoxPipStreamPicker.mount(document.querySelector('#picker'),{read:async()=>data,current:()=> 'spark-re4',
        select:(sid,valid)=>pick.select(sid,valid),broadcast:(sid,valid)=>pick.broadcast(sid,valid),
        preview:async()=> 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="160" height="90"><rect width="160" height="90" fill="%23384e61"/></svg>'});
      panel.ready;`);
    assert.equal(await evaluate(`document.querySelectorAll('button button').length`),0);
    assert.equal(await evaluate(`document.querySelector('[data-stream-broadcast="off-pso"]').disabled`),true);
    const before=await evaluate(`(()=>{const b=document.querySelector('[data-stream-broadcast="i9-pso"]'),r=b.getBoundingClientRect();return {width:r.width,height:r.height,visible:getComputedStyle(b).display};})()`);
    assert.ok(before.width>90&&before.height>=24&&before.visible!=='none');
    await evaluate(`document.querySelector('[data-stream-broadcast="i9-pso"]').click();new Promise(r=>setTimeout(r,20));`);
    assert.deepEqual(await evaluate('calls'),['i9-pso']);assert.deepEqual(await evaluate('views'),[]);
    await evaluate(`document.querySelector('[data-stream-broadcast="auto"]').click();new Promise(r=>setTimeout(r,20));`);
    assert.deepEqual(await evaluate('calls'),['i9-pso','auto']);
    if(process.env.GBOX_TEST_SCREENSHOT){const shot=await send('Page.captureScreenshot',{format:'png'});fs.writeFileSync(process.env.GBOX_TEST_SCREENSHOT,Buffer.from(shot.result.data,'base64'));}
    await evaluate('panel.stop()');
  },{timeoutMs:60000});}finally{await new Promise(r=>server.close(r));}
});
