const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs');
const {withPage}=require('../scripts/browser_lifecycle.cjs');
test('game text shows real progress and failure safely, and never takes mouse input',async()=>{
  await withPage(async(evaluate,send)=>{
    await evaluate(fs.readFileSync(require.resolve('../clients/web/viz/operation-console.js'),'utf8'));
    await evaluate(`document.body.innerHTML='<button id="game" style="position:absolute;left:0;top:0;width:800px;height:600px;background:#183c29">Game fixture</button><div id="hud" style="position:absolute;inset:0;pointer-events:none"></div>';
      window.clicks=0;document.querySelector('#game').onclick=()=>clicks++;
      window.view=GBoxOperationConsole.view(document,document.querySelector('#hud'));window.clock=10000;
      window.hud=GBoxOperationConsole.create({session:()=> 's',now:()=>clock,render:f=>view.draw(f)});
      hud.observe({id:'j',tool:'game_live_controls',input:{session_id:'s',op:'apply'},state:'running',progress_log:['Revision checked','Native inventory routine called']});`);
    assert.match(await evaluate(`document.querySelector('.gbox-operation-output').textContent`),/Native inventory routine called/);
    await send('Input.dispatchMouseEvent',{type:'mousePressed',x:50,y:50,button:'left',clickCount:1});
    await send('Input.dispatchMouseEvent',{type:'mouseReleased',x:50,y:50,button:'left',clickCount:1});
    assert.equal(await evaluate('clicks'),1);
    await evaluate(`hud.observe({id:'j',tool:'game_live_controls',input:{session_id:'s',op:'apply'},state:'failed',error:'<img src=x onerror=alert(1)> mode changed'});`);
    assert.equal(await evaluate(`document.querySelector('.gbox-operation-output img')===null`),true);
    assert.equal(await evaluate(`document.querySelector('.gbox-operation-output section').dataset.state`),'failed');
    await evaluate(`clock+=6500;hud.poll();`);
    assert.equal(await evaluate(`document.querySelector('.gbox-operation-output section').style.opacity`),'0.5');
    await evaluate(`clock+=501;hud.poll();`);assert.equal(await evaluate(`document.querySelector('.gbox-operation-output').children.length`),0);
    await evaluate('hud.dispose();view.dispose();');
  });
});
test('the isolated native overlay document loads its local scripts under CSP',async()=>{
  await withPage(async(evaluate,send)=>{
    const {pathToFileURL}=require('node:url');
    await send('Page.navigate',{url:pathToFileURL(require.resolve('../clients/desktop/operation-output.html')).href});
    await evaluate(`new Promise((resolve,reject)=>{let n=0;const t=setInterval(()=>{if(window.operationFrame){clearInterval(t);resolve();}else if(n++>100){clearInterval(t);reject(Error('Overlay did not load'));}},20);})`);
    await evaluate(`operationFrame({sid:'s',rows:[{label:'PSO give',state:'succeeded',opacity:1,lines:['Verified by the game worker.']}]});`);
    assert.match(await evaluate('document.body.textContent'),/Verified by the game worker/);
  });
});

test('embedded remote streams display output locally and native pictures forward it without duplicate text',async()=>{
  await withPage(async(evaluate)=>{
    await evaluate(fs.readFileSync(require.resolve('../clients/web/viz/operation-console.js'),'utf8'));
    const shell=fs.readFileSync(require.resolve('../clients/web/index.html'),'utf8');
    const start=shell.indexOf('// Native/GPU pictures'),end=shell.indexOf("if (!new URLSearchParams(location.search).has('embedded'))",start);
    assert.ok(start>0&&end>start);
    await evaluate(`window.active={sid:'s'};window.api=async()=>[];window.messages=[];console.log=x=>messages.push(x);
      document.body.innerHTML='<div id="scr" style="width:800px;height:500px"></div>';
      new Function('location',${JSON.stringify(shell.slice(start,end))})({search:'?embedded'});
      window.pending=GBOX_OPERATION_CONSOLE.request('/api/sessions/s/rpc',{op:'pso_controls',args:{input:{op:'give'}}},()=>new Promise(r=>window.finish=r));void 0;`);
    assert.equal(await evaluate(`!document.querySelector('.gbox-operation-output').parentElement.hidden`),true);
    await evaluate(`document.body.insertAdjacentHTML('beforeend','<div id="nativeslot" style="width:800px;height:500px"></div>');GBOX_OPERATION_CONSOLE.poll();`);
    assert.equal(await evaluate(`document.querySelector('.gbox-operation-output').parentElement.hidden`),true);
    await evaluate(`finish({verified:true});pending`);
    assert.equal(await evaluate(`messages.filter(x=>x.startsWith('GBOX:')).length`),2);
    assert.equal(await evaluate(`JSON.parse(messages.at(-1).slice(5)).event.state`),'succeeded');
    await evaluate(`dispatchEvent(new Event('pagehide'));`);
  });
});
