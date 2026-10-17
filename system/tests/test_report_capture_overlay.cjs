const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const {withPage}=require('../scripts/browser_lifecycle.cjs');
const web=path.join(__dirname,'../clients/web');

test('initial capture and retries photograph game pixels without the report overlay',async()=>{
  await withPage(async(evaluate,send)=>{
    await send('Emulation.setDeviceMetricsOverride',{width:1100,height:850,deviceScaleFactor:1,mobile:false});
    const game=fs.readFileSync(path.join(__dirname,'../docs/evidence/ff7-mario-1819/battle-after.png')).toString('base64');
    await evaluate(`document.body.innerHTML='<canvas id="fixture-game" width="640" height="480" style="position:absolute;left:100px;top:80px"></canvas>';
      window.readyGame=(async()=>{const image=new Image();image.src='data:image/png;base64,${game}';await image.decode();document.querySelector('canvas').getContext('2d').drawImage(image,0,0,640,480);})();readyGame;`);
    const clip={x:100,y:80,width:640,height:480,scale:1};
    const baseline=(await send('Page.captureScreenshot',{format:'png',clip})).result.data;
    await evaluate(fs.readFileSync(path.join(web,'viz/build-actions.js'),'utf8'));
    await evaluate(fs.readFileSync(path.join(web,'viz/build-report-image.js'),'utf8'));
    await evaluate(`window.pending=[];window.until=async fn=>{for(let n=0;n<150;n++){if(fn())return;await new Promise(r=>setTimeout(r,10));}throw Error('capture UI timeout');};
      window.build={game_id:'fixture',name:'fixture-build',game_title:'Game frame fixture',session_id:'fixture-session'};
      window.api=()=>new Promise((resolve,reject)=>pending.push({resolve,reject}));
      window.done=GBoxBuildReportImage.open(build,{api});
      window.duplicate=GBoxBuildReportImage.open(build,{api});until(()=>pending.length===1);`);
    assert.equal(await evaluate('done===duplicate'),true);
    assert.equal(await evaluate(`getComputedStyle(document.querySelector('.bri-modal')).visibility`),'hidden');
    const first=(await send('Page.captureScreenshot',{format:'png',clip})).result.data;
    assert.equal(first,baseline,'the photographed pixels must equal the unobstructed game, not the report form');
    // Failure must restore a usable form; its note survives the retry.
    await evaluate(`pending.shift().reject(Error('temporary capture failure'));until(()=>!document.querySelector('[data-retry]').hidden);`);
    assert.equal(await evaluate(`getComputedStyle(document.querySelector('.bri-modal')).visibility`),'visible');
    await evaluate(`document.querySelector('[data-note]').value='Keep my issue note';document.querySelector('[data-retry]').click();until(()=>pending.length===1);`);
    assert.equal(await evaluate(`getComputedStyle(document.querySelector('.bri-modal')).visibility`),'hidden');
    const retry=(await send('Page.captureScreenshot',{format:'png',clip})).result.data;
    assert.equal(retry,baseline,'retry must also exclude the already-open report form');
    await evaluate(`pending.shift().resolve({image_b64:${JSON.stringify(retry)}});until(()=>!document.querySelector('[data-send]').disabled);`);
    assert.equal(await evaluate(`document.querySelector('[data-note]').value`),'Keep my issue note');
    assert.equal(await evaluate(`getComputedStyle(document.querySelector('.bri-modal')).visibility`),'visible');
    if(process.env.GBOX_CAPTURE_EVIDENCE){
      const out=path.resolve(process.env.GBOX_CAPTURE_EVIDENCE);fs.mkdirSync(out,{recursive:true});
      await evaluate(`const tag=document.createElement('div');tag.textContent='UI screenshot / captured static gameplay fixture / report form excluded from frame';tag.style='position:fixed;bottom:0;left:0;right:0;padding:8px;background:#244974;color:white;font:12px system-ui;z-index:2147483647';document.body.append(tag);`);
      const image=await send('Page.captureScreenshot',{format:'png'});
      fs.writeFileSync(path.join(out,'clean-report-capture.png'),Buffer.from(image.result.data,'base64'));
    }
    await evaluate(`document.querySelector('[data-cancel]').click();done;`);
    // Escape during capture never resurrects the form when its reply arrives.
    await evaluate(`window.done=GBoxBuildReportImage.open(build,{api});until(()=>pending.length===1);`);
    await send('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});
    assert.equal(await evaluate('done'),null);
    await evaluate(`pending.shift().resolve({image_b64:${JSON.stringify(baseline)}});new Promise(r=>setTimeout(r,30));`);
    assert.equal(await evaluate(`document.querySelectorAll('.bri-modal').length`),0);
  });
});
