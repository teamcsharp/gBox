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
  if(path.endsWith('/live-controls')) {if(pending && path.includes('/games/g/')) return pending;return {title:'Fixture game',profile,categories:{bosses:'Set boss HP to zero',inventory:'Add to inventory',checkpoints:'Warp to next checkpoint',unlocks:'Hidden content'},unlock_policy:{enabled:true,favorites_enabled:true,default_boot:true,idle_resolution:true},favorite_unlocks:{label:'Unlock-all pending',number:88}};}
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
  assert.equal(await evaluate(`host.querySelector('[data-lc-favorite-unlocks]').checked`),true);
  assert.match(await evaluate(`host.querySelector('[data-lc-policy]').textContent`),/Unlock-all pending #88/);
  await evaluate(`host.querySelector('[data-lc-session]').value='x-two';host.querySelector('[data-lc-session]').dispatchEvent(new Event('change',{bubbles:true}));ctl.checkMode();`);
  assert.equal(await evaluate(`host.querySelector('[data-lc-session]').value`),'x-two');
  assert.equal(await evaluate(`calls.filter(c=>c.path.endsWith('/run')).at(-1).body.session_id`),'x-two');
  assert.equal(await evaluate(`host.querySelector('fieldset').disabled`),true,'mode mismatch stays disabled');
  await evaluate(`available=true;ctl.checkMode();`);
  assert.equal(await evaluate(`host.querySelector('fieldset').disabled`),false);
  await evaluate(`host.querySelector('[data-lc-apply]').click();new Promise(r=>setTimeout(r,20));`);
  const submitted=await evaluate(`calls.filter(c=>c.body?.op==='apply').at(-1).body`);
  assert.match(submitted.command_id,/^[a-f0-9-]{36}$/);assert.ok(submitted.expires>Date.now()/1000);
  const {command_id,expires,...input}=submitted;
  assert.deepEqual(input,{session_id:'x-two',revision:'rev',op:'apply',action:'boss_hp',values:{hp:0}});
  assert.equal(await evaluate(`host.querySelector('fieldset').disabled`),true,'one-shot action requires a fresh check after scene changes');
  await evaluate(`host.querySelector('[data-lc-discover]').click();new Promise(r=>setTimeout(r,20));`);
  assert.match(await evaluate(`host.querySelector('[role=status]').textContent`),/#42/);
  await evaluate(`host.querySelector('[data-lc-unlocks]').click();new Promise(r=>setTimeout(r,20));`);
  assert.deepEqual(await evaluate(`calls.find(c=>c.path.endsWith('/policy')).body`),{enabled:false});
  await evaluate(`host.querySelector('[data-lc-favorite-unlocks]').click();new Promise(r=>setTimeout(r,20));`);
  assert.deepEqual(await evaluate(`calls.filter(c=>c.path.endsWith('/policy')).at(-1).body`),{favorites_enabled:false,default_boot:false});
  await evaluate(`host.querySelector('[data-lc-unlock-research]').click();new Promise(r=>setTimeout(r,20));`);
  assert.deepEqual(await evaluate(`calls.filter(c=>c.path.endsWith('/policy')).at(-1).body`),{idle_resolution:false});
  // A completed request for the previous game cannot replace the new game's panel.
  await evaluate(`var finish;pending=new Promise(r=>finish=r);var old=ctl.refresh();ctl.setGame('other');pending=null;finish({title:'Old game',profile,categories:{},unlock_policy:{enabled:true}});old;`);
  assert.notEqual(await evaluate(`host.querySelector('[data-lc-game]').textContent`),'Old game · USA fixture');
  await evaluate(`ctl.dispose();`);
 });
});

const switchAction={id:'noclip',category:'movement',label:'Walk through walls',scope:'Offline on-foot campaign',notes:'Fixture native toggle with checked restoration',control:'toggle',toggle_parameter:'on',parameters:[{id:'on',kind:'boolean',label:'Enabled',default:false}]};
const giveAction={id:'give_item',category:'inventory',label:'Give item',scope:'Offline on-foot campaign',notes:'Fixture item catalog',parameters:[{id:'item',kind:'choice',label:'Item',options:[{value:'pistol',label:'Pistol'},{value:'launcher',label:'Rocket launcher'}],default:'pistol'},{id:'equip',kind:'boolean',label:'Equip',default:false}]};
test('toggle markup uses a switch and ordinary boolean parameters remain editable',()=>{
 const html=LC.actionHTML(switchAction,false);
 assert.match(html,/role="switch" data-lc-toggle="noclip"/);
 assert.doesNotMatch(html,/data-lc-apply|type="number"/);
 assert.match(LC.actionHTML({...action,parameters:[{id:'equip',kind:'boolean',label:'Equip',default:true}]},false),/type="checkbox" data-lc-param="equip" checked/);
});

async function setupToggle(evaluate,send){
 await setup(evaluate,send);
 await evaluate(`ctl.dispose();var nativeOn=false,failApply=false,unknownState=false,delayedApply=false,applyCount=0,probeWait=null,loadedItems=['pistol','launcher'];var releaseApply;
  action=${JSON.stringify(switchAction)};profile={revision:'rev',revision_label:'USA fixture',actions:[action,${JSON.stringify(giveAction)}]};
  var baseApi=api;var toggleApi=async(path,body)=>{
   if(!path.endsWith('/run'))return baseApi(path,body);
   calls.push({path,body});
   if(body.op==='inspect'){if(probeWait)await probeWait;return {state:'succeeded',output:{result:{actions:[{id:'noclip',available:true,...(unknownState?{}:{value:nativeOn})},{id:'give_item',available:true,item_choices:{parameter:'item',values:loadedItems}}]}}};}
   applyCount++;if(failApply)throw Error('Connection lost; completion unknown');
   if(delayedApply)await new Promise(r=>releaseApply=r);
   if(Object.hasOwn(body.values,'on'))nativeOn=body.values.on;return {state:'succeeded',output:{result:{verified:true}}};
  };
  ctl=GBoxLiveControls.mount(host,{api:toggleApi},{game:'g',sid:'w-one',open:true,autoCheck:true});ctl.ready;`);
}

test('browser: native switches auto-check without mutations and can be enabled and restored with distinct expiring commands',async()=>{
 await withPage(async(evaluate,send)=>{
  await setupToggle(evaluate,send);
  assert.equal(await evaluate('applyCount'),0);
  assert.equal(await evaluate(`host.querySelector('[data-lc-toggle]').checked`),false);
  assert.equal(await evaluate(`host.querySelector('fieldset').disabled`),false);
  for(const desired of [true,false]){
   await evaluate(`host.querySelector('[data-lc-toggle]').click();new Promise(r=>setTimeout(r,20));`);
   assert.equal(await evaluate('nativeOn'),desired);
   assert.equal(await evaluate(`host.querySelector('[data-lc-toggle]').checked`),desired);
   assert.equal(await evaluate(`host.querySelector('fieldset').disabled`),false,'native state is read back so the user can toggle again');
  }
  const sent=await evaluate(`calls.filter(c=>c.body?.op==='apply').map(c=>c.body)`);
  assert.deepEqual(sent.map(c=>[c.session_id,c.revision,c.action,c.values]),[['w-one','rev','noclip',{on:true}],['w-one','rev','noclip',{on:false}]]);
  assert.notEqual(sent[0].command_id,sent[1].command_id);
  assert.ok(sent.every(c=>c.expires>Date.now()/1000&&c.expires<=Date.now()/1000+15));
  assert.match(await evaluate(`host.querySelector('[role=status]').textContent`),/off.*Native state checked/);
  await evaluate('ctl.dispose()');
 });
});

test('browser: changing session invalidates an in-flight mode probe',async()=>{
 await withPage(async(evaluate,send)=>{
  await setupToggle(evaluate,send);
  await evaluate(`var resolveProbe;probeWait=new Promise(r=>resolveProbe=r);var checking=ctl.checkMode();new Promise(r=>setTimeout(r,20));`);
  await evaluate(`var option=document.createElement('option');option.value='x-two';option.textContent='Second fixture session';host.querySelector('[data-lc-session]').append(option);host.querySelector('[data-lc-session]').value='x-two';host.querySelector('[data-lc-session]').dispatchEvent(new Event('change',{bubbles:true}));resolveProbe();checking;`);
  assert.equal(await evaluate(`host.querySelector('[data-lc-session]').value`),'x-two');
  assert.equal(await evaluate(`host.querySelector('fieldset').disabled`),true);
  assert.equal(await evaluate(`host.querySelector('[data-lc-check]').disabled`),false);
  assert.match(await evaluate(`host.querySelector('[role=status]').textContent`),/check mode to enable this session/);
  assert.equal(await evaluate('applyCount'),0);
  await evaluate('ctl.dispose()');
 });
});

test('browser: item dropdown and boolean option dispatch the selected catalog values once',async()=>{
 await withPage(async(evaluate,send)=>{
  await setupToggle(evaluate,send);
  await evaluate(`host.querySelector('[data-lc-param=item]').value='launcher';host.querySelector('[data-lc-param=equip]').checked=true;host.querySelector('[data-lc-apply=give_item]').click();host.querySelector('[data-lc-apply=give_item]').click();new Promise(r=>setTimeout(r,20));`);
  assert.equal(await evaluate('applyCount'),1);
  const sent=await evaluate(`calls.filter(c=>c.body?.op==='apply').at(-1).body`);
  assert.deepEqual(sent.values,{item:'launcher',equip:true});
  assert.equal(sent.action,'give_item');assert.equal(sent.session_id,'w-one');
  assert.equal(await evaluate(`host.querySelector('[data-lc-action=give_item]').disabled`),true,'a one-shot inventory action needs a fresh scene check');
  await evaluate(`loadedItems=['pistol','not-in-reviewed-catalog'];ctl.checkMode();`);
  assert.equal(await evaluate(`host.querySelector('[data-lc-param=item]').options.length`),2,'runtime findings cannot inject new item choices');
  assert.equal(await evaluate(`host.querySelector('[data-lc-param=item] option[value=launcher]').disabled`),true,'items absent from this mission cannot be selected');
  assert.equal(await evaluate(`host.querySelector('[data-lc-param=item]').value`),'pistol');
  await evaluate('ctl.dispose()');
 });
});

test('browser: item ownership distinguishes missing from unselected and native grant feedback is text',async()=>{
 await withPage(async(evaluate,send)=>{
  await setupToggle(evaluate,send);
  await evaluate(`ctl.dispose();var previousApi=toggleApi;var stateApi=async(path,body)=>{
    if(path.endsWith('/run') && body.op==='inspect')return {state:'succeeded',output:{result:{actions:[
      {id:'noclip',available:true,value:false},
      {id:'give_item',available:true,item_choices:{parameter:'item',values:['pistol','launcher'],states:{pistol:{owned:true,equipped:false},launcher:{owned:false,equipped:false}}}}
    ]}}};
    if(path.endsWith('/run') && body.op==='apply')return {state:'succeeded',output:{result:{action:'give_item',result:{result:{message:'Restored <gadget>; select it with the D-pad.'}}}}};
    return previousApi(path,body);
  };ctl=GBoxLiveControls.mount(host,{api:stateApi},{game:'g',sid:'w-one',open:true,autoCheck:true});ctl.ready;`);
  assert.match(await evaluate(`host.querySelector('[data-lc-item-status]').textContent`),/^$/,'switch has no inventory status');
  assert.match(await evaluate(`host.querySelector('[data-lc-action=give_item] [data-lc-item-status]').textContent`),/In inventory; not selected/);
  assert.match(await evaluate(`host.querySelector('[data-lc-param=item] option').textContent`),/Pistol — in inventory/);
  await evaluate(`var sel=host.querySelector('[data-lc-param=item]');sel.value='launcher';sel.dispatchEvent(new Event('change',{bubbles:true}));`);
  assert.match(await evaluate(`host.querySelector('[data-lc-action=give_item] [data-lc-item-status]').textContent`),/Not in inventory/);
  await evaluate(`host.querySelector('[data-lc-apply=give_item]').click();new Promise(r=>setTimeout(r,20));`);
  assert.match(await evaluate(`host.querySelector('[role=status]').textContent`),/Restored <gadget>; select it with the D-pad/);
  assert.equal(await evaluate(`host.querySelectorAll('gadget').length`),0);
  await evaluate(`var session=host.querySelector('[data-lc-session]');session.value='';session.dispatchEvent(new Event('change',{bubbles:true}));`);
  assert.equal(await evaluate(`host.querySelector('[data-lc-action=give_item] [data-lc-item-status]').hidden`),true);
  assert.equal(await evaluate(`host.querySelector('[data-lc-param=item] option').textContent`),'Pistol');
  await evaluate('ctl.dispose()');
 });
});

test('browser: unknown native state and uncertain mutations stay disabled until explicitly checked',async()=>{
 await withPage(async(evaluate,send)=>{
  await setupToggle(evaluate,send);
  await evaluate('unknownState=true;ctl.checkMode()');
  assert.equal(await evaluate(`host.querySelector('fieldset').disabled`),true,'an available address without boolean state cannot pretend to be an off switch');
  await evaluate('unknownState=false;ctl.checkMode()');
  await evaluate(`failApply=true;host.querySelector('[data-lc-toggle]').click();new Promise(r=>setTimeout(r,20));`);
  assert.equal(await evaluate('applyCount'),1,'failed mutation is never retried');
  assert.equal(await evaluate(`host.querySelector('fieldset').disabled`),true);
  assert.equal(await evaluate(`host.querySelector('[data-lc-toggle]').checked`),false,'uncertain result returns to last confirmed display, not a false success');
  await evaluate('failApply=false;ctl.checkMode()');
  assert.equal(await evaluate(`host.querySelector('fieldset').disabled`),false);
  await evaluate('ctl.dispose()');
 });
});

test('browser: late switch completion cannot overwrite another game or duplicate a pending click',async()=>{
 await withPage(async(evaluate,send)=>{
  await setupToggle(evaluate,send);
  await evaluate(`delayedApply=true;host.querySelector('[data-lc-toggle]').click();host.querySelector('[data-lc-toggle]').click();new Promise(r=>setTimeout(r,0));`);
  assert.equal(await evaluate('applyCount'),1);
  await evaluate(`ctl.setGame('other');new Promise(r=>setTimeout(r,0));`);
  await evaluate(`releaseApply();new Promise(r=>setTimeout(r,20));`);
  assert.equal(await evaluate(`host.querySelector('fieldset').disabled`),true);
  assert.doesNotMatch(await evaluate(`host.querySelector('[role=status]').textContent`),/Native state checked/);
  await evaluate('ctl.dispose()');
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

test('browser: scoped native inapplicability is explained without inventing a checkpoint button',async()=>{
 await withPage(async(evaluate,send)=>{
  await setup(evaluate,send);
  await evaluate(`profile.assessments={checkpoints:{status:'unsupported',scope:'Fixture on-foot missions',reason:'No ordered native checkpoint route <script>'}};ctl.refresh();`);
  assert.match(await evaluate(`host.querySelector('[data-lc-missing]').textContent`),/No ordered native checkpoint route <script>.*Fixture on-foot missions/);
  assert.equal(await evaluate(`host.querySelectorAll('[data-lc-missing] script').length`),0);
  assert.equal(await evaluate(`host.querySelectorAll('[data-lc-action]').length`),1);
  await evaluate('ctl.dispose()');
 });
});
test('both clients load panel and gallery/session mount it',()=>{
 for(const file of ['../clients/desktop/index.html','../clients/web/index.html']) assert.match(fs.readFileSync(path.join(__dirname,file),'utf8'),/viz\/live-controls.js/);
 assert.match(fs.readFileSync(path.join(__dirname,'../clients/web/viz/mods-gallery.js'),'utf8'),/liveControls\?\.dispose/);
 assert.match(fs.readFileSync(path.join(__dirname,'../clients/web/index.html'),'utf8'),/GBoxLiveControls.mount\(liveHost/);
});
