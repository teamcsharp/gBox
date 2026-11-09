const {test}=require('node:test');
const assert=require('node:assert/strict');
const M=require('../clients/web/viz/mercmode.js');

function panel(kind,{title='re5_switch',slot='chris',donor='jill',sessionId=null,respond=()=>({ok:true}),matrix={pairs:{}},
  restart={id:'j1',state:'succeeded',output:{result:{same_session:true}}}}={}){
  const events={},calls=[],messages=[],errors=[];
  const button={dataset:{mmSwap:kind},textContent:kind,addEventListener:(event,fn)=>events[event]=fn};
  const fields={
    '[data-mm-swap-slot]':{value:slot,addEventListener(){}},
    '[data-mm-swap-donor]':{value:donor,options:[{value:donor,disabled:false}]},
    '[data-mm-retag]':{checked:false,addEventListener(){}}
  };
  const root={querySelector:s=>fields[s]||null,querySelectorAll:s=>s==='[data-mm-swap]'?[button]:[]};
  const api=async(path,body)=>{
    calls.push([path,body]);
    if(path.startsWith('/api/decrypt-lab/swap-matrix'))return matrix;
    if(path==='/api/jobs')return restart;
    return respond(path,body);
  };
  M.wireSwaps(root,{api,title,sessionId,done:text=>messages.push(text),fail:error=>errors.push(error.message)});
  return {calls,messages,errors,button,fields,click:()=>events.click({stopPropagation(){}})};
}

test('cast response calls the completion callback and reports partial failures',async()=>{
  const p=panel('from-cast',{sessionId:'worker-session',respond:()=>({ok:true,spawned:2,arcs:[
    {arc:'a/uEm10.arc',status:'swapped',donor:'jill'},
    {arc:'a/uEm11.arc',status:'failed',reason:'incompatible'}]})});
  await p.click();
  assert.deepEqual(p.errors,[]);
  assert.match(p.messages[0],/Cast textures built: 1\/2/);
  assert.match(p.messages[0],/uEm11.arc \(failed: incompatible\)/);
  assert.equal(p.calls.filter(([path])=>path==='/api/jobs').length,1);
  assert.equal(p.button.disabled,false);
});

test('an empty cast build cannot restart a game with a stale overlay',async()=>{
  const p=panel('from-cast',{sessionId:'worker-session',respond:()=>({ok:false,note:'no enemy archive fits'})});
  await p.click();
  assert.deepEqual(p.errors,['no enemy archive fits']);
  assert.equal(p.calls.filter(([path])=>path==='/api/jobs').length,0);
  assert.deepEqual(p.messages,[]);
});

test('RE6 uses its own native archive paths for both selected and zombie donors',async()=>{
  for(const kind of ['clothes','to-zombie']){
    const p=panel(kind,{title:'re6_switch',slot:'leon',donor:'helena',respond:()=>({ok:true,slot:'leon',donor:'helena'})});
    await p.click();
    assert.deepEqual(p.errors,[]);
    const body=p.calls.find(([path])=>path==='/api/decrypt-lab/model-swap')[1];
    assert.equal(body.arc_path,'nativeNXx64/arc/NX/uPl00LeonUsa.arc');
    assert.equal(body.donor_arc,kind==='clothes'?'nativeNXx64/arc/NX/uPl01HelenaUsa.arc':'nativeNXx64/arc/NX/uEm5200.arc');
  }
});

test('native replacement sends the complete archive action and states verification is pending',async()=>{
  const p=panel('character');await p.click();
  assert.deepEqual(p.errors,[]);
  assert.equal(p.calls.at(-1)[0],'/api/decrypt-lab/character-swap');
  assert.match(p.messages[0],/still needs visual verification/);
  const unsupported=panel('character',{donor:'zombie'});await unsupported.click();
  assert.match(unsupported.errors[0],/verified class binding/);
  assert.equal(unsupported.calls.length,1);
});

test('title menus show only their own swap controls and RE5 object archives',()=>{
  const host={name:'lilspark',id:'worker',settings:{enabled:true,titles:['re5','re6']}};
  const html=gid=>M.menuHTML(host,true,null,{session_id:'worker-session',game_id:gid});
  const re6=html('115f9cdbba115432');
  assert.match(re6,/value="leon" selected/);
  assert.doesNotMatch(re6,/data-mm-obj-swap|data-mm-zombie=|data-mm-swap="plain"|value="jill"/);
  assert.match(html('52d15709be0fda1a'),/data-mm-swap="character"/);
  assert.doesNotMatch(html('270a15eb98dab4d7'),/data-mm-obj-swap|data-mm-swap=/);
  assert.doesNotMatch(html('unknown'),/data-mm-obj-swap|data-mm-swap=/);
});

test('a relaunch waits for its child swap job and reports its actual outcome',async()=>{
  for(const state of ['succeeded','failed']){
    const p=panel('character',{sessionId:'worker-session',restart:{id:'outer',state:'succeeded',
      output:{result:{same_session:false,swap_job:'child'}}},respond:path=>path==='/api/jobs/child'
        ?{id:'child',state,error:state==='failed'?'boot failed':null,output:{session_id:'worker-new'}}:{ok:true}});
    await p.click();
    assert.ok(p.calls.some(([path])=>path==='/api/jobs/child'));
    assert.match(p.messages[0],state==='succeeded'?/relaunched in session worker-new/:/restart failed: boot failed/);
    assert.doesNotMatch(p.messages[0],/restarted in this session/);
  }
});

test('desktop passes the menu containing sibling object and zombie controls to the swap handler',()=>{
  const fs=require('node:fs'),path=require('node:path');
  const desktop=fs.readFileSync(path.join(__dirname,'../clients/desktop/index.html'),'utf8');
  assert.match(desktop,/if \(swaps\) GBoxMercMode\.wireSwaps\(slot, /);
});

test('texture compatibility uses the actual donor and never disables native archive selection',async()=>{
  const matrix={pairs:{'chris|jill':{ok:false},'chris|zombie':{ok:true}}};
  const native=panel('character',{matrix});await Promise.resolve();
  assert.equal(native.fields['[data-mm-swap-donor]'].options[0].disabled,false);
  await native.click();assert.deepEqual(native.errors,[]);
  const zombie=panel('to-zombie',{matrix});await Promise.resolve();await zombie.click();
  assert.deepEqual(zombie.errors,[]);
  assert.match(zombie.calls.at(-1)[1].donor_arc,/uEm6c\.arc$/);
  const blocked=panel('to-zombie',{matrix:{pairs:{'chris|jill':{ok:true},'chris|zombie':{ok:false}}}});
  await Promise.resolve();await blocked.click();
  assert.match(blocked.errors[0],/chris and zombie do not share a texture format/);
  assert.equal(blocked.calls.length,1);
});

test('object and zombie controls share the character edit lock and refuse empty edits',async()=>{
  const events={},calls=[],errors=[];
  const button=(key,dataset={})=>({dataset,disabled:false,addEventListener:(_,fn)=>{events[key]=fn;}});
  const object=button('object'),zombie=button('zombie'),character=button('character',{mmSwap:'character'});
  const fields={'[data-mm-obj-swap]':object,'[data-mm-zombie]':zombie,
    '[data-mm-swap-slot]':{value:'chris',addEventListener(){}},
    '[data-mm-swap-donor]':{value:'jill',options:[{value:'jill'}]}};
  const root={querySelector:key=>fields[key]||null,querySelectorAll:key=>key==='[data-mm-swap]'?[character]:[]};
  let release,empty=false;
  const pending=new Promise(resolve=>{release=resolve;});
  const api=async(path,body)=>{
    calls.push([path,body]);
    if(path.startsWith('/api/decrypt-lab/swap-matrix'))return {pairs:{}};
    if(empty)return {ok:false,note:'no compatible texture'};
    await pending;return {ok:true,slot:'mine',donor:'grenade'};
  };
  M.wireSwaps(root,{api,title:'re5_switch',done(){},fail:e=>errors.push(e.message)});
  const click={stopPropagation(){}};
  const action=events.object(click);
  assert.equal(object.disabled,true);
  await events.character(click);await events.zombie(click);await events.object(click);
  assert.equal(calls.filter(([path])=>path==='/api/decrypt-lab/model-swap').length,1);
  assert.equal(calls.filter(([path])=>path==='/api/decrypt-lab/character-swap').length,0);
  release();await action;
  assert.equal(object.disabled,false);
  empty=true;await events.zombie(click);
  assert.deepEqual(errors,['no compatible texture']);
  assert.equal(calls.filter(([path])=>path==='/api/decrypt-lab/model-swap').length,2);
  assert.equal(zombie.disabled,false);
});
