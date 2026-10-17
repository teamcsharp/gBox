'use strict';

const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {withPage}=require('../scripts/browser_lifecycle.cjs');

const source=fs.readFileSync(path.join(__dirname,'../clients/web/viz/pso-controls.js'),'utf8');
const setup=`
 window.calls=[];
 window.waitFor=async predicate=>{
   for(let n=0;n<500;n++){
     if(predicate())return;
     await new Promise(resolve=>setTimeout(resolve,10));
   }
   throw Error('PSO reconnect UI did not settle');
 };
 window.capabilities={version:'gc',label:'GameCube test revision',supported:true,
   classes:[],features:{always_hit:true},pending:{}};
 window.catalog=[{name:'Saber',code:'000100',cat:'Weapons',stars:1}];
 window.preferences={equip_any:true,always_hit:true};
 window.host=document.createElement('section');document.body.append(host);
 window.q=selector=>host.querySelector(selector);
 window.rpc=()=>calls.filter(call=>call.b?.op==='pso_controls');
 window.nativeOps=()=>rpc().map(call=>call.b.args.input.op);
 window.dispose=()=>{panel.dispose();host.remove();};
`;

test('PSO reconnect remains usable during a hung check, pins one RPC and rejects its stale response',async()=>{
 await withPage(async evaluate=>{
  await evaluate(source);
  await evaluate(setup+`
    window.io={api:async(p,b)=>{
      calls.push({p,b});
      if(b?.op==='pso_controls'){
        if(b.args.input.op==='capabilities')return new Promise(resolve=>window.staleCheck=resolve);
        if(b.args.input.op==='rehook')return new Promise(resolve=>window.finishRehook=resolve);
        throw Error('Unexpected native mutation');
      }
      if(p.startsWith('/api/pso/items?version='))return catalog;
      if(p==='/api/pso/preferences')return preferences;
      throw Error('Unexpected endpoint '+p);
    }};
    window.panel=GBoxPSO.mount(host,io,{sid:'original-worker/session:7'});
    waitFor(()=>nativeOps().includes('capabilities'));
  `);
  assert.equal(await evaluate(`q('[data-rehook]').disabled`),false,'a hung version check must not trap the reload button');
  assert.equal(await evaluate(`q('[data-spawn]').disabled`),true);
  await evaluate(`q('[data-rehook]').click();q('[data-rehook]').click();waitFor(()=>typeof finishRehook==='function');`);
  assert.deepEqual(await evaluate('nativeOps()'),['capabilities','rehook']);
  assert.equal(await evaluate(`q('[data-rehook]').disabled`),true);
  assert.equal(await evaluate(`q('[data-rehook]').getAttribute('aria-busy')`),'true');
  const command=await evaluate(`rpc().find(call=>call.b.args.input.op==='rehook')`);
  assert.equal(command.p,'/api/sessions/original-worker%2Fsession%3A7/rpc');
  assert.equal(command.b.args.input.session_id,'original-worker/session:7');
  assert.match(command.b.args.command_id,/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/);
  await evaluate(`
    finishRehook({ready:true,verified:true,capabilities,steps:[{message:'same process'}],message:'ready'});
    waitFor(()=>!q('[data-controls]').disabled && !q('[data-live]').disabled && q('[data-status]').textContent.includes('ready'));
  `);
  assert.equal(await evaluate(`q('[data-rehook-report]').textContent`),'same process\nready');
  assert.equal(await evaluate(`q('[data-always-hit]').checked`),true);
  assert.equal(await evaluate(`q('[data-always-hit]').matches(':disabled')`),false);
  assert.equal(await evaluate(`calls.filter(call=>call.p==='/api/pso/items?version=gc').length`),1);
  assert.equal(await evaluate(`calls.filter(call=>call.p==='/api/pso/preferences').length`),1);
  const status=await evaluate(`q('[data-status]').textContent`);
  await evaluate(`
    staleCheck({...capabilities,supported:false,reason:'old unsupported response',features:{}});
    new Promise(resolve=>setTimeout(resolve,50));
  `);
  assert.equal(await evaluate(`q('[data-profile]').textContent.includes('old unsupported response')`),false);
  assert.equal(await evaluate(`q('[data-status]').textContent`),status);
  assert.equal(await evaluate(`q('[data-live]').disabled`),false);
  await evaluate(`q('[data-code]').click();`);
  assert.equal(await evaluate(`q('[data-drop]').matches(':disabled')`),false);
  assert.deepEqual(await evaluate('nativeOps()'),['capabilities','rehook'],'rehooking must not replay a previous mutation');
  await evaluate('dispose()');
 });
});

for(const outcome of ['pending','failure'])test(`PSO ${outcome} reconnect reports the problem and leaves another reconnect available`,async()=>{
 await withPage(async evaluate=>{
  await evaluate(source);
  await evaluate(setup+`
    window.outcome=${JSON.stringify(outcome)};
    window.io={api:async(p,b)=>{
      calls.push({p,b});
      if(b?.op==='pso_controls'){
        const op=b.args.input.op;
        if(op==='capabilities')return capabilities;
        if(op==='rehook'){
          if(outcome==='failure')throw Error('The emulator hook could not be verified');
          return {ready:false,verified:false,capabilities,
            steps:[{message:'Located the same emulator process'}],message:'Waiting for the player to finish loading'};
        }
        throw Error('Unexpected native mutation '+op);
      }
      if(p.startsWith('/api/pso/items?version='))return catalog;
      if(p==='/api/pso/preferences')return preferences;
      throw Error('Unexpected endpoint '+p);
    }};
    window.panel=GBoxPSO.mount(host,io,{sid:'pinned-pso-session'});
    waitFor(()=>!q('[data-live]').disabled && !q('[data-defaults]').disabled);
  `);
  await evaluate(`q('[data-rehook]').click();waitFor(()=>!q('[data-rehook]').disabled && q('[data-rehook-report]').textContent.includes(${JSON.stringify(outcome==='failure'?'could not be verified':'Waiting for the player')}));`);
  assert.equal(await evaluate(`q('[data-live]').disabled`),true,'failed recovery must not leave stale native capabilities enabled');
  assert.equal(await evaluate(`q('[data-spawn]').disabled`),true);
  assert.equal(await evaluate(`q('[data-travel]').disabled`),true);
  assert.equal(await evaluate(`q('[data-always-hit]').matches(':disabled')`),true);
  assert.equal(await evaluate(`q('[data-rehook]').getAttribute('aria-busy')`),'false');
  await evaluate(`q('[data-clear]').click();new Promise(resolve=>setTimeout(resolve,80));`);
  assert.deepEqual(await evaluate('nativeOps()'),['capabilities','rehook'],'a pending or failed reconnect must never retry commands automatically');
  assert.equal(await evaluate(`rpc().every(call=>call.b.args.input.session_id==='pinned-pso-session')`),true);
  await evaluate('dispose()');
 });
});

test('always-hit loads the saved default and saves a toggle before one session-pinned native command',async()=>{
 await withPage(async evaluate=>{
  await evaluate(source);
  await evaluate(setup+`
    window.io={api:async(p,b)=>{
      calls.push({p,b});
      if(b?.op==='pso_controls'){
        if(b.args.input.op==='capabilities')return capabilities;
        if(b.args.input.op==='always_hit')return {verified:true,message:'Accuracy patch disabled'};
        throw Error('Unexpected native mutation');
      }
      if(p.startsWith('/api/pso/items?version='))return catalog;
      if(p==='/api/pso/preferences'){
        if(b)return new Promise(resolve=>window.finishPreferenceSave=()=>{Object.assign(preferences,b);resolve(preferences);});
        return preferences;
      }
      throw Error('Unexpected endpoint '+p);
    }};
    window.panel=GBoxPSO.mount(host,io,{sid:'accuracy-worker/session:4'});
    waitFor(()=>!q('[data-always-hit]').matches(':disabled'));
  `);
  assert.equal(await evaluate(`q('[data-always-hit]').checked`),true);
  await evaluate(`q('[data-always-hit]').click();waitFor(()=>typeof finishPreferenceSave==='function');`);
  assert.deepEqual(await evaluate(`calls.filter(call=>call.p==='/api/pso/preferences' && call.b).map(call=>call.b)`),[{always_hit:false}]);
  assert.deepEqual(await evaluate('nativeOps()'),['capabilities'],'a native write must wait for the saved preference');
  assert.equal(await evaluate(`q('[data-always-hit]').matches(':disabled')`),true);
  await evaluate(`finishPreferenceSave();waitFor(()=>q('[data-status]').textContent.includes('Accuracy patch disabled'));`);
  const native=await evaluate(`rpc().filter(call=>call.b.args.input.op==='always_hit')`);
  assert.equal(native.length,1);
  assert.equal(native[0].p,'/api/sessions/accuracy-worker%2Fsession%3A4/rpc');
  assert.deepEqual(native[0].b.args.input,{session_id:'accuracy-worker/session:4',op:'always_hit',on:false});
  assert.equal(await evaluate(`q('[data-always-hit]').checked`),false);
  assert.equal(await evaluate(`q('[data-always-hit]').matches(':disabled')`),false);
  await evaluate('dispose()');
 });
});

test('an unanswered reconnect has a bounded wait, leaves recovery available and never repeats the command',async()=>{
 await withPage(async evaluate=>{
  await evaluate(source);
  await evaluate(setup+`
    const originalSetTimeout=window.setTimeout.bind(window);
    window.setTimeout=(callback,ms,...args)=>originalSetTimeout(callback,ms===12000?45:ms,...args);
    window.io={api:async(p,b)=>{
      calls.push({p,b});
      if(b?.op==='pso_controls'){
        if(b.args.input.op==='capabilities')return capabilities;
        if(b.args.input.op==='rehook')return new Promise(()=>{});
        throw Error('Unexpected native mutation');
      }
      if(p.startsWith('/api/pso/items?version='))return catalog;
      if(p==='/api/pso/preferences')return preferences;
      throw Error('Unexpected endpoint '+p);
    }};
    window.panel=GBoxPSO.mount(host,io,{sid:'timeout-session'});
    waitFor(()=>!q('[data-live]').disabled && !q('[data-defaults]').disabled);
  `);
  await evaluate(`q('[data-rehook]').click();waitFor(()=>!q('[data-rehook]').disabled && q('[data-rehook-report]').textContent.includes('no action was retried'));`);
  assert.equal(await evaluate(`q('[data-live]').disabled`),true);
  assert.equal(await evaluate(`q('[data-spawn]').disabled`),true);
  assert.equal(await evaluate(`q('[data-always-hit]').matches(':disabled')`),true);
  await evaluate(`new Promise(resolve=>setTimeout(resolve,80));`);
  assert.deepEqual(await evaluate('nativeOps()'),['capabilities','rehook']);
  await evaluate('dispose()');
 });
});
