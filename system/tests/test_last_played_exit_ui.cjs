const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const {withPage}=require('../scripts/browser_lifecycle.cjs');
const popup=require('../clients/web/viz/last-played.js');
const shellStyles=(fs.readFileSync(path.join(__dirname,'../clients/web/index.html'),'utf8').match(/<style\b[^>]*>[\s\S]*?<\/style>/gi)||[]).join('\n');

test('normal close is neutral and a real exception keeps the crash warning in the browser',async()=>{
  const entry={session_id:'fixture-session',title:'Final Fantasy VII (USA) (Disc 1)',mod:'ff7_mario_v3',
    node:'JAYBUILTFINALE',node_online:true,ended:1800000000,report:{id:'existing-report',number:1864,status:'open'}};
  await withPage(async(evaluate,send)=>{
    await send('Emulation.setDeviceMetricsOverride',{width:595,height:650,deviceScaleFactor:1,mobile:false});
    const variants=[
      ['normal-close',{kind:'crash',crash:true,text:'The emulator quit unexpectedly (exit code 1).'},false],
      ['actual-crash',{kind:'crash',crash:true,text:'The emulator quit unexpectedly (exit code 3221225477).'},true]
    ];
    for(const [name,reason,crash]of variants){
      const html=popup.html({...entry,reason},{now:1800000001});
      await evaluate(`document.head.innerHTML=${JSON.stringify(shellStyles)}+'<style>'+${JSON.stringify(popup.CSS)}+'</style>';document.body.style='background:#111116;color:#e8e8ee;font:14px system-ui';document.body.innerHTML=${JSON.stringify(html)};`);
      assert.equal(await evaluate(`!!document.querySelector('.lp-box.lp-bad')`),crash);
      assert.equal(await evaluate(`document.querySelectorAll('[data-lp="reload"]').length`),1);
      const text=await evaluate(`document.querySelector('.lp-why').textContent`);
      assert.match(text,crash?/quit unexpectedly/:/The emulator closed/);
      if(!crash)assert.match(text,/Related report #1864/);
      if(process.env.GBOX_EXIT_EVIDENCE){
        const out=path.resolve(process.env.GBOX_EXIT_EVIDENCE);fs.mkdirSync(out,{recursive:true});
        await evaluate(`(()=>{const tag=document.createElement('div');tag.textContent='UI screenshot / synthetic exit data / no running game touched';tag.style='position:fixed;bottom:0;left:0;right:0;background:#244974;padding:8px;font:12px system-ui;z-index:10000';document.body.append(tag);})()`);
        const image=await send('Page.captureScreenshot',{format:'png'});
        fs.writeFileSync(path.join(out,name+'.png'),Buffer.from(image.result.data,'base64'));
      }
    }
  });
});
