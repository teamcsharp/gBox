const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {withPage}=require('../scripts/browser_lifecycle.cjs');
const G=require('../clients/web/viz/ghost-runs.js');
test('legacy data never advertises native playback; names are escaped',()=>{
 assert.match(G.tasHtml({runs:[]}),/no full|do not contain/);
 assert.doesNotMatch(G.tasHtml({runs:[]}),/class="act pri tas-play"/);
 assert.doesNotMatch(G.tasHtml({runs:[{id:'x',title:'<img onerror=alert(1)>',frames:4,state_restores:0}]}),/<img onerror/);
});
test('Runs plays a selected level with chosen sprite and loop, reports admission errors, and arms idle playback',async()=>{
 await withPage(async(evaluate,send)=>{
  await evaluate(`document.body.innerHTML='<div id="dock-side"></div>';window.calls=[];window.rejectPlay=false;
   window.fetch=async()=>({json:async()=>({on:false})});
   window.api=async(p,b)=>{calls.push({p,b});
    if(p.startsWith('/api/ghosts/game/'))return {profile:{fps:60},prefs:{},runs:[],showing:[],level_bests:{}};
    if(p.startsWith('/api/tas/runs?'))return {runs:[{id:'native-one',title:'Mario run',frames:1400,state_restores:10,segments:[{id:'level-300',label:'1-2',start_frame:300,end_frame:900}]}]};
    if(p.endsWith('/play')){if(rejectPlay)throw Error('Human gameplay is active');return {id:'replay-job',state:'succeeded',output:{session_id:'idle-pc-test'}};}
    if(p.endsWith('/idle'))return {saved:true,reason:'Armed; waiting for verified replay'};
    throw Error('Unexpected API '+p);};
   window.waitFor=async fn=>{for(let i=0;i<100;i++){if(fn())return;await new Promise(r=>setTimeout(r,20));}throw Error('Timed out');};`);
  await evaluate(fs.readFileSync(path.join(__dirname,'../clients/web/viz/ghost-runs.js'),'utf8'));
  await evaluate(`GhostRuns.mount({sid:'human-session',gid:'mario',api,tok:'fixture'});waitFor(()=>document.querySelector('.tas-play'));`);
  await evaluate(`document.querySelector('.tas-segment').value='level-300';document.querySelector('.tas-loop').checked=true;document.querySelector('.tas-sprite').value='sonic';document.querySelector('.tas-play').click();waitFor(()=>document.querySelector('.tas-result').textContent.includes('idle-pc-test'));`);
  assert.deepEqual(await evaluate(`calls.find(c=>c.p.endsWith('/play')).b`),{segment:'level-300',loop:true,sprite:'sonic'});
  await evaluate(`rejectPlay=true;document.querySelector('.tas-play').click();waitFor(()=>document.querySelector('.tas-result').textContent.includes('Human gameplay'));`);
  assert.equal(await evaluate(`document.querySelector('.tas-play').disabled`),false);
  await evaluate(`const toggle=document.querySelector('.tas-idle');toggle.checked=true;toggle.dispatchEvent(new Event('change',{bubbles:true}));waitFor(()=>calls.some(c=>c.p.endsWith('/idle')));`);
  assert.deepEqual(await evaluate(`calls.find(c=>c.p.endsWith('/idle')).b`),{enabled:true,sprite:'sonic'});
  assert.equal(await evaluate(`calls.some(c=>c.p.includes('/stop')||c.b?.op==='stop_game')`),false);
  if(process.env.GBOX_TAS_UI_EVIDENCE){
   await evaluate(`document.body.style='background:#171820;color:#eee;font:14px system-ui;padding:30px;width:480px';document.head.insertAdjacentHTML('beforeend','<style>:root{--line:#48506a;--acc:#8896ff}.mut{color:#b4bdd6}button,select{background:#292d40;color:white;border:1px solid #67749c;border-radius:4px;padding:5px}.tas-runs{margin-bottom:20px}input{accent-color:#8b99ff}</style>');document.querySelector('.tas-result').textContent='Browser test fixture. Native emulator evidence is verified separately.';`);
   const shot=await send('Page.captureScreenshot',{format:'png'});fs.mkdirSync(process.env.GBOX_TAS_UI_EVIDENCE,{recursive:true});fs.writeFileSync(path.join(process.env.GBOX_TAS_UI_EVIDENCE,'runs-playback.png'),Buffer.from(shot.result.data,'base64'));
  }
 });
});
