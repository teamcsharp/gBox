const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const {withPage}=require('../scripts/browser_lifecycle.cjs');

test('attached computer selection submits only checked PCs and keeps the dialog usable on failure',async()=>{
  await withPage(async(evaluate,send)=>{
    await send('Emulation.setDeviceMetricsOverride',{width:1000,height:800,deviceScaleFactor:1,mobile:false});
    await evaluate(fs.readFileSync(path.join(__dirname,'../clients/web/viz/build-actions.js'),'utf8'));
    await evaluate(`document.body.style='background:#111;color:white;font:14px system-ui';
      window.build={game_id:'jgr',name:'test-build',game_title:'Jet Grind Radio (USA)',label:'Amy geometry test',size:1181116006,
        where:[{where:'spark',label:'Spark collection'},{where:'pc',node:'i9-NUC',online:true,label:'i9-NUC (local copy)'},
          {where:'pc',node:'JAYBUILTFINALE',online:true,label:'JAYBUILTFINALE (local copy)'}]};
      window.calls=[];window.fail=false;window.until=async fn=>{for(let n=0;n<100;n++){if(fn())return;await new Promise(r=>setTimeout(r,10));}throw Error('UI timeout');};
      window.api=async(...args)=>{calls.push(args);if(fail)throw Error('Build is in use on selected PC');return {scope:'pcs',nodes:args[1].nodes,spark:{removed:[]},jobs:args[1].nodes.map(node=>({node}))};};
      window.done=GBoxBuildActions.open('delete',build,{here:'JAYBUILTFINALE',api});void 0;`);
    assert.equal(await evaluate(`document.querySelector('[data-ba-pcs]').disabled`),true);
    await evaluate(`document.querySelector('[value=pcs]').click();document.querySelector('[data-ba=go]').click();`);
    assert.equal(await evaluate('calls.length'),0,'empty selection never submits deletion');
    assert.match(await evaluate(`document.querySelector('[data-ba-status]').textContent`),/Choose at least one/);
    assert.equal(await evaluate(`document.querySelector('[data-ba-pcs]').disabled`),false);
    await evaluate(`document.querySelector('[data-ba-pc][value="i9-NUC"]').click();fail=true;document.querySelector('[data-ba=go]').click();until(()=>!document.querySelector('[data-ba=go]').disabled);`);
    assert.deepEqual(await evaluate('calls[0]'),['/api/builds/jgr/test-build/delete',{scope:'pcs',nodes:['i9-NUC']},'POST']);
    assert.equal(await evaluate(`document.querySelector('[data-ba-pc][value="i9-NUC"]').checked`),true);
    await evaluate(`document.querySelector('[data-ba-pc][value="JAYBUILTFINALE"]').click();fail=false;`);
    if(process.env.GBOX_DELETE_ATTACHED_EVIDENCE){
      const dir=path.resolve(process.env.GBOX_DELETE_ATTACHED_EVIDENCE);fs.mkdirSync(dir,{recursive:true});
      await evaluate(`document.querySelector('[data-ba-status]').textContent='';const label=document.createElement('div');label.textContent='UI screenshot — fixture build and PC inventory; no real files deleted';label.style='position:fixed;bottom:0;left:0;right:0;background:#244974;padding:8px;font:12px system-ui';document.body.appendChild(label);`);
      const shot=await send('Page.captureScreenshot',{format:'png'});
      fs.writeFileSync(path.join(dir,'delete-attached-computers.png'),Buffer.from(shot.result.data,'base64'));
    }
    await evaluate(`document.querySelector('[data-ba=go]').click();done;`);
    assert.deepEqual(await evaluate('calls[1][1]'),{scope:'pcs',nodes:['i9-NUC','JAYBUILTFINALE']});
    assert.match(await evaluate('done.then(r=>GBoxBuildActions.deleteResultText(build,r))'),/Spark collection kept/);
    await evaluate(`window.done=GBoxBuildActions.open('delete',build,{here:'JAYBUILTFINALE',api,onlyHere:true});void 0;`);
    assert.equal(await evaluate(`document.querySelector('[data-ba-pcs]')`),null);
    await evaluate(`document.querySelector('[data-ba=cancel]').click();done;`);
    await evaluate(`window.done=GBoxBuildActions.open('delete',{...build,where:[build.where[0]]},{here:'JAYBUILTFINALE',api});void 0;`);
    assert.equal(await evaluate(`document.querySelector('[value=pcs]').disabled`),true);
    await evaluate(`document.querySelector('[data-ba=cancel]').click();done;`);
  });
});
