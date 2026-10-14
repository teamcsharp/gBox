const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const LC=require('../clients/web/viz/live-controls.js');
const {withPage}=require('../scripts/browser_lifecycle.cjs');
const source=fs.readFileSync(path.join(__dirname,'../clients/web/viz/live-controls.js'),'utf8');
const action={id:'boss_hp',category:'bosses',label:'Set boss HP to zero',scope:'Offline boss room',notes:'Fixture only: same live boss object',parameters:[{id:'hp',label:'HP',kind:'integer',min:0,max:100,default:0}]};
test('control markup escapes findings and stays disabled until checked',()=>{
 const html=LC.actionHTML({...action,notes:'<script>alert(1)</script>'},false);
 assert.match(html,/&lt;script&gt;/);assert.match(html,/<fieldset[^>]* disabled/);assert.match(html,/max="100"/);
});
async function setup(evaluate,send){
 await send('Emulation.setDeviceMetricsOverride',{width:1100,height:1000,deviceScaleFactor:1,mobile:false});
 await evaluate(`document.body.style='margin:20px;background:#15151a;color:#eee;font:14px system-ui';document.body.innerHTML='<h1>Mods</h1><div id="host"></div>';`);
 await evaluate(source);
 await evaluate(`var calls=[],available=false,pending=null;var action=${JSON.stringify(action)};var profile={revision:'rev',revision_label:'USA fixture',actions:[action]};
 var api=async(path,body)=>{calls.push({path,body});
  if(path==='/api/sessions')return [{session_id:'w-one',game_id:'g',state:'running',title:'Fixture game'},{session_id:'x-two',game_id:'g',state:'running',title:'Second PC'}];
  if(path.endsWith('/live-controls')) {if(pending && path.includes('/games/g/')) return pending;return {title:'Fixture game',profile,categories:{bosses:'Set boss HP to zero',inventory:'Add to inventory',unlocks:'Hidden content'},unlock_policy:{enabled:true}};}
  if(path.endsWith('/run'))return {id:'job',state:'succeeded',output:{result:body.op==='inspect'?{actions:[{id:'boss_hp',available}]}:{verified:true}}};
  if(path.endsWith('/discover'))return {number:42};
  if(path.endsWith('/policy'))return body;
  throw Error('Unexpected '+path);
 };var host=document.querySelector('#host'),ctl=GBoxLiveControls.mount(host,{api},{game:'g',open:true});ctl.ready;`);
}
test('browser: session selection, fingerprint availability, validated click, unlock policy, discovery, stale responses',async()=>{
 await withPage(async(evaluate,send)=>{
  await setup(evaluate,send);
  assert.equal(await evaluate(`calls.some(c=>c.path.endsWith('/run'))`),false,'reading the panel never writes or submits probes');
  assert.equal(await evaluate(`host.querySelector('[data-lc-unlocks]').checked`),true);
  await evaluate(`host.querySelector('[data-lc-session]').value='x-two';host.querySelector('[data-lc-session]').dispatchEvent(new Event('change',{bubbles:true}));ctl.checkMode();`);
  assert.equal(await evaluate(`host.querySelector('[data-lc-session]').value`),'x-two');
  assert.equal(await evaluate(`calls.filter(c=>c.path.endsWith('/run')).at(-1).body.session_id`),'x-two');
  assert.equal(await evaluate(`host.querySelector('fieldset').disabled`),true,'mode mismatch stays disabled');
  await evaluate(`available=true;ctl.checkMode();`);
  assert.equal(await evaluate(`host.querySelector('fieldset').disabled`),false);
  await evaluate(`host.querySelector('[data-lc-apply]').click();new Promise(r=>setTimeout(r,20));`);
  assert.deepEqual(await evaluate(`calls.filter(c=>c.body?.op==='apply').at(-1).body`),{session_id:'x-two',revision:'rev',op:'apply',action:'boss_hp',values:{hp:0}});
  assert.equal(await evaluate(`host.querySelector('fieldset').disabled`),true,'one-shot action requires a fresh check after scene changes');
  await evaluate(`host.querySelector('[data-lc-discover]').click();new Promise(r=>setTimeout(r,20));`);
  assert.match(await evaluate(`host.querySelector('[role=status]').textContent`),/#42/);
  await evaluate(`host.querySelector('[data-lc-unlocks]').click();new Promise(r=>setTimeout(r,20));`);
  assert.deepEqual(await evaluate(`calls.find(c=>c.path.endsWith('/policy')).body`),{enabled:false});
  // A completed request for the previous game cannot replace the new game's panel.
  await evaluate(`var finish;pending=new Promise(r=>finish=r);var old=ctl.refresh();ctl.setGame('other');pending=null;finish({title:'Old game',profile,categories:{},unlock_policy:{enabled:true}});old;`);
  assert.notEqual(await evaluate(`host.querySelector('[data-lc-game]').textContent`),'Old game · USA fixture');
  await evaluate(`ctl.dispose();`);
 });
});
test('browser: unsupported game renders pending categories; no writes, image or fake unlock claim',async()=>{
 await withPage(async(evaluate,send)=>{
  await setup(evaluate,send);
  await evaluate(`profile=null;ctl.refresh();`);
  assert.equal(await evaluate(`host.querySelectorAll('[data-lc-action]').length`),0);
  assert.match(await evaluate(`host.textContent`),/live research pending/);
  assert.match(await evaluate(`host.textContent`),/Add to inventory.*needs game-specific/s);
  if(process.env.GBOX_LIVE_CONTROLS_EVIDENCE){
   const shot=await send('Page.captureScreenshot',{format:'png'});fs.mkdirSync(process.env.GBOX_LIVE_CONTROLS_EVIDENCE,{recursive:true});fs.writeFileSync(path.join(process.env.GBOX_LIVE_CONTROLS_EVIDENCE,'pending.png'),Buffer.from(shot.result.data,'base64'));
  }
  await evaluate(`profile={revision:'rev',revision_label:'USA fixture',actions:[action]};available=true;host.querySelector('[data-lc-session]').value='w-one';host.querySelector('[data-lc-session]').dispatchEvent(new Event('change',{bubbles:true}));ctl.checkMode();`);
  if(process.env.GBOX_LIVE_CONTROLS_EVIDENCE){
   const shot=await send('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(process.env.GBOX_LIVE_CONTROLS_EVIDENCE,'checked-fixture.png'),Buffer.from(shot.result.data,'base64'));
  }
  await evaluate(`ctl.dispose();`);
 });
});
test('both clients load panel and gallery/session mount it',()=>{
 for(const file of ['../clients/desktop/index.html','../clients/web/index.html']) assert.match(fs.readFileSync(path.join(__dirname,file),'utf8'),/viz\/live-controls.js/);
 assert.match(fs.readFileSync(path.join(__dirname,'../clients/web/viz/mods-gallery.js'),'utf8'),/liveControls\?\.dispose/);
 assert.match(fs.readFileSync(path.join(__dirname,'../clients/web/index.html'),'utf8'),/GBoxLiveControls.mount\(liveHost/);
});
