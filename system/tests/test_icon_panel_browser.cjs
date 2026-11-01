'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),http=require('node:http');
const {withPage}=require('../scripts/browser_lifecycle.cjs');

test('icon panel stage popup is accessible above video in compact and full browser layouts',async t=>{
  const desktop=fs.readFileSync(path.join(__dirname,'../clients/desktop/index.html'),'utf8');
  const style=desktop.match(/<style>([\s\S]*?)<\/style>/)[1];
  const html=desktop.match(/controls\.innerHTML = ('<span class="compact-title"[^\n]+?');/)[1];
  const nativeHoles=desktop.match(/querySelectorAll\(COMPACT\.on \? "([^"]+)" : EMB_HOLES\)/)[1];
  const server=http.createServer((req,res)=>{
    if(req.url==='/controls.js'){res.setHeader('Content-Type','application/javascript');res.end(fs.readFileSync(path.join(__dirname,'../clients/web/viz/stream-interventions.js')));return;}
    res.end(`<style>${style}body{margin:0}#compact-stream{background:linear-gradient(135deg,#283b42,#090b10)}#compact-controls{opacity:1;pointer-events:auto}</style><body class="gbox-compact"><div id="compact-stream" class="on"></div><div id="compact-controls" class="shown" role="toolbar" aria-label="Icon panel"></div><script src="/controls.js"></script></body>`);
  });
  await new Promise(r=>server.listen(0,'127.0.0.1',r));
  try{await withPage(async(evaluate,send)=>{
    await send('Emulation.setDeviceMetricsOverride',{width:480,height:360,deviceScaleFactor:1,mobile:false});
    await send('Page.navigate',{url:`http://127.0.0.1:${server.address().port}`});
    await evaluate(`new Promise(r=>{const check=()=>window.GBoxStreamInterventions?r():setTimeout(check,10);check();})`);
    await evaluate(`document.querySelector('#compact-controls').innerHTML=${html};
      window.posts=[];window.state={session_id:'owned-session',title:'Resident Evil 6',title_id:'re6',available:true,current_stage:0,
        stages:['Urban Chaos','Steel Beast','Mining the Depths'].map((name,id)=>({id,name,enabled:true,weight:100/3,default_enabled:true})),
        loop:{enabled:false,stage_id:null},replay_pending:false,quick_attack:{available:true,enabled:true,count:4,interval_s:24}};
      window.api=async(p,b)=>{if(b.args.op!=='status'){posts.push(b);return {...state,receipt:{request_id:b.args.request_id,status:'queued'}};}return state;};
      window.button=document.querySelector('[data-round-replay]');window.menuButton=document.querySelector('[data-stage-preferences]');
      window.panel=GBoxStreamInterventions.bindIconPanel(button,{api,sid:'owned-session',menuButton});
      new Promise(r=>setTimeout(r,20));`);
    const rect=await evaluate(`(()=>{const r=button.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom};})()`);
    assert.ok(rect.left>=0&&rect.right<=480&&rect.bottom>rect.top,'replay icon has a visible compact hit target');
    await evaluate(`menuButton.click();new Promise(r=>setTimeout(r,20))`);
    assert.equal(await evaluate(`getComputedStyle(document.querySelector('.merc-round-menu')).display`),'block');
    assert.equal(await evaluate(`document.querySelector('.merc-round-menu').scrollTop`),0,'opening begins at the title and loop controls, not a lower focused action');
    assert.equal(await evaluate(`document.querySelector('[aria-label="Quick attacks per burst"]').value`),'4');
    assert.equal(await evaluate(`document.querySelector('[aria-label="Quick attack interval in seconds"]').value`),'24');
    assert.equal(await evaluate(`(()=>{const l=document.querySelector('.merc-round-menu label'),c=l.querySelector('input'),r=c.getBoundingClientRect(),text=l.querySelector('span').getBoundingClientRect();return getComputedStyle(l).display==='inline-flex'&&Math.abs(r.top-text.top)<8&&r.right<text.left;})()`),true,'loop checkbox stays inline beside its own label despite desktop form styles');
    assert.equal(await evaluate(`document.querySelectorAll(${JSON.stringify(nativeHoles)}).length >= 2`),true,'desktop native-video cutout selector includes the actual popup');
    assert.equal(await evaluate(`(()=>{const m=document.querySelector('.merc-round-menu'),r=m.getBoundingClientRect();return m.contains(document.elementFromPoint(r.left+20,r.top+20));})()`),true,'popup hit testing stays above simulated video');
    await evaluate(`window.weight=document.querySelector('[aria-label="Urban Chaos selection weight"]');`);
    // A screenshot is a local review artifact, not native Electron acceptance.
    const dir=process.env.GBOX_ICON_PANEL_ARTIFACT_DIR;
    if(dir){fs.mkdirSync(dir,{recursive:true});const shot=await send('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(dir,'icon-panel-compact.png'),Buffer.from(shot.result.data,'base64'));}
    for(const [width,height] of [[320,180],[160,90]]){
      await send('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:false});
      await evaluate(`new Promise(r=>setTimeout(r,20))`);
      const bounds=await evaluate(`(()=>{const m=document.querySelector('.merc-round-menu'),r=m.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,scroll:m.scrollHeight>m.clientHeight,horizontalOverflow:m.scrollWidth>m.clientWidth};})()`);
      assert.ok(bounds.left>=0&&bounds.right<=width+.1&&bounds.top>=0&&bounds.bottom<=height+.1,JSON.stringify(bounds));
      assert.ok(bounds.scroll,'small viewport retains all controls by scrolling');
      assert.equal(bounds.horizontalOverflow,false,'stage grid does not clip controls horizontally');
    }
    await evaluate(`document.activeElement.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));`);
    assert.equal(await evaluate(`document.querySelector('.merc-round-menu')`),null);
    await evaluate(`document.querySelector('[data-full]').focus()`);
    assert.equal(await evaluate(`(()=>{const b=document.querySelector('[data-full]'),r=b.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth;})()`),true,'narrow icon panel scrolls to each keyboard-accessible action');
    await send('Emulation.setDeviceMetricsOverride',{width:960,height:540,deviceScaleFactor:1,mobile:false});
    await evaluate(`document.body.classList.remove('gbox-compact');document.querySelector('#compact-controls').style.display='flex';menuButton.click();new Promise(r=>setTimeout(r,20))`);
    assert.equal(await evaluate(`document.querySelector('[role="dialog"]').getAttribute('aria-label')`),'Icon panel stage preferences');
    await evaluate(`panel.dispose()`);
    t.diagnostic('Feature assertions passed before browser cleanup; native Electron cutout selection inspected, native window not launched.');
  },{timeoutMs:35000});}finally{server.closeAllConnections();await new Promise(r=>server.close(r));}
});
