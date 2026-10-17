const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'), path=require('node:path');
const {withPage,findChrome}=require('./build_report_browser.cjs');
const UI=require('../clients/web/viz/build-report-image.js');
const read=n=>fs.readFileSync(path.join(__dirname,'../clients/web/',n),'utf8');

test('annotation coordinates respect scaling and clamp to the screenshot',()=>{
  const c={width:640,height:480,getBoundingClientRect:()=>({left:100,top:50,width:320,height:240})};
  assert.deepEqual(UI.point({clientX:260,clientY:170},c),{x:320,y:240});
  assert.deepEqual(UI.point({clientX:-10,clientY:999},c),{x:0,y:480});
});

test('Ctrl-click camera uses current matching session; ordinary click retains thumbnail action',()=>{
  const s=read('index.html');
  const branch=s.slice(s.indexOf('} else if (e.target.closest("button[data-shot]"))'),s.indexOf('} else if (mom &&'));
  assert.match(branch,/if \(e.ctrlKey\)/);
  assert.match(branch,/sessionBuild\(m, gid, session\)/);
  assert.match(branch,/if \(!build\?\.session_id\) throw/);
  assert.match(branch,/GBoxBuildReportImage.open\(build, \{ api \}\)/);
  assert.match(branch,/else \{[^}]+modShot\(m, sid, card, true\)/);
  assert.ok(s.indexOf('/viz/build-report-image.js')>s.indexOf('/viz/build-actions.js'));
  for(const src of [s,read('viz/build-report-image.js')]) assert.ok(!/[^\r]\n/.test(src),'client files retain CRLF');
});

test('browser: mark, undo, references, failure retry, submit, cancel and capture retry', {skip:!findChrome()&&'no Chromium installed'},async()=>{
  await withPage(async(evaluate,send)=>{
    await send('Emulation.setDeviceMetricsOverride',{width:1400,height:1100,deviceScaleFactor:1,mobile:false});
    const shot=fs.readFileSync(path.join(__dirname,'../docs/evidence/ff7-mario-1819/battle-after.png')).toString('base64');
    await evaluate(read('viz/build-actions.js'));
    await evaluate(read('viz/build-report-image.js'));
    await evaluate(`
      window.calls=[];window.failSubmit=true;window.failCapture=false;
      window.source=${JSON.stringify(shot)};
      window.build={game_id:'ff7-disc1',name:'ff7_mario_v2',runtime_mod:'ff7_mario_v2~copy',game_title:'Final Fantasy VII',session_id:'test-session'};
      window.api=async(p,b)=>{calls.push({p,b});if(p.endsWith('/report-frame')) {if(failCapture)throw new Error('capture unavailable');return {image_b64:source};}if(failSubmit)throw new Error('offline');return {id:'r1',number:1860};};
      window.done=GBoxBuildReportImage.open(build,{api});
      window.until=async fn=>{for(let n=0;n<100;n++){if(fn())return;await new Promise(r=>setTimeout(r,20));}throw new Error('UI timed out');};
      window.q=s=>document.querySelector(s);
      until(()=>!q('[data-send]').disabled);
    `);
    // Use real browser pointer events, including reverse-direction box drawing.
    const rect=await evaluate(`(()=>{const r=q('canvas').getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height};})()`);
    async function drag(a,b){
      const pos=p=>({x:rect.x+p[0]*rect.w,y:rect.y+p[1]*rect.h});
      await send('Input.dispatchMouseEvent',{type:'mousePressed',...pos(a),button:'left',clickCount:1});
      await send('Input.dispatchMouseEvent',{type:'mouseMoved',...pos(b),button:'left',buttons:1});
      await send('Input.dispatchMouseEvent',{type:'mouseReleased',...pos(b),button:'left',clickCount:1});
    }
    await drag([.82,.8],[.54,.22]);
    const box=await evaluate(`q('canvas').toDataURL()`);
    await evaluate(`q('[data-undo]').click()`);
    assert.notEqual(await evaluate(`q('canvas').toDataURL()`),box);
    await drag([.54,.22],[.82,.8]);
    await evaluate(`q('[data-tool=arrow]').click()`);
    await drag([.48,.25],[.66,.38]);
    await evaluate(`q('[data-note]').value='1. Unnatural black spots. 2. Compare the character reference.';
      (async()=>{const blob=await(await fetch('data:image/png;base64,'+source)).blob();
      const transfer=new DataTransfer();transfer.items.add(new File([blob],'reference-example.png',{type:'image/png'}));
      q('[data-files]').files=transfer.files;q('[data-files]').dispatchEvent(new Event('change'));await until(()=>q('.bri-refs img'));})();`);
    assert.equal(await evaluate(`q('.bri-refs img').alt`),'Reference 1');
    // Keep a UI screenshot: real captured gameplay as the canvas, simulated reference input.
    if(process.env.GBOX_REPORT_EVIDENCE){
      await evaluate(`q('section').scrollTop=0`);
      const image=await send('Page.captureScreenshot',{format:'png'});
      fs.writeFileSync(process.env.GBOX_REPORT_EVIDENCE,Buffer.from(image.result.data,'base64'));
    }
    await evaluate(`q('[data-send]').click();until(()=>q('[role=status]').textContent.includes('offline'))`);
    assert.equal(await evaluate(`q('[data-note]').value`),'1. Unnatural black spots. 2. Compare the character reference.');
    assert.equal(await evaluate(`q('.bri-refs img').alt`),'Reference 1');
    const payload=await evaluate(`calls.at(-1).b`);
    assert.equal(payload.session_id,'test-session');
    assert.equal(payload.evidence.original_image_b64,shot);
    assert.notEqual(payload.evidence.image_b64,shot);
    assert.equal(payload.evidence.reference_images.length,1);
    await evaluate(`failSubmit=false;q('[data-send]').click();done.then(r=>window.answer=r)`);
    assert.deepEqual(await evaluate('answer'),{id:'r1',number:1860});
    assert.equal(await evaluate(`!!q('.bri-modal')`),false);
    assert.equal(await evaluate(`calls.filter(c=>c.p.endsWith('/report-frame')).length`),1,'submit must keep the original captured moment');
    await evaluate(`window.done=GBoxBuildReportImage.open(build,{api});until(()=>!q('[data-send]').disabled)`);
    await send('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});
    assert.equal(await evaluate('done'),null);
    await evaluate(`failCapture=true;window.done=GBoxBuildReportImage.open(build,{api});until(()=>!q('[data-retry]').hidden)`);
    assert.equal(await evaluate(`q('[data-send]').disabled`),true);
    await evaluate(`failCapture=false;q('[data-retry]').click();until(()=>!q('[data-send]').disabled)`);
    await evaluate(`q('[data-cancel]').click()`);
    assert.equal(await evaluate('done'),null);
  });
});
