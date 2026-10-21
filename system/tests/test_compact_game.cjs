const { test } = require('node:test');
const assert = require('node:assert/strict');
const { create, fit } = require('../clients/desktop/compact-game');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync(require.resolve('../clients/desktop/index.html'), 'utf8');

function fixture(options = {}) {
  const calls = [], pads = [], frames = [];
  const io = {
    resolve: async () => ({ sid:'session-1', local:true }), mode: () => 'auto',
    windowMode: async value => { calls.push(value); return { on:value.on, aspect:16/9 }; },
    pad: value => pads.push(value), present: () => frames.push('present'), render: state => frames.push({...state}), ...options
  };
  return { ctl:create(io), calls, pads, frames };
}
test('PiP preserves the selected native session and uses its native aspect', async () => {
  const x = fixture(); await x.ctl.enter();
  assert.equal(x.ctl.state.sid, 'session-1'); assert.equal(x.ctl.state.local, true);
  assert.equal(x.ctl.state.aspect,16/9); assert.deepEqual(x.calls,[{on:true}]);
  assert.deepEqual(x.pads,[null], 'local emulators keep physical input without duplicate network injection');
  await x.ctl.restore(); assert.equal(x.ctl.state.on,false); assert.deepEqual(x.pads,[null,null]);
});
test('two enter requests and restore during opening serialize without losing the original app state', async () => {
  let finish; const x = fixture({resolve:() => new Promise(r => {finish=r;})});
  const a=x.ctl.enter(), b=x.ctl.enter(); await Promise.resolve();
  const exit=x.ctl.restore(); finish({sid:'s',local:false}); await Promise.all([a,b,exit]);
  assert.deepEqual(x.calls,[{on:true},{on:false}]); assert.equal(x.ctl.state.on,false);
});
test('a failed window transition rolls back presentation and controller targeting', async () => {
  const x = fixture({windowMode:async value => {if(value.on) throw Error('native failure'); return {on:false};}});
  await assert.rejects(x.ctl.enter(),/native failure/);
  assert.equal(x.ctl.state.on,false); assert.deepEqual(x.pads,[null,null]);
});
test('native double-click exit events restore the same presentation without another IPC', async () => {
  const x=fixture({mode:()=> 'full'}); await x.ctl.enter(); x.ctl.changed({on:false});
  assert.equal(x.ctl.state.on,false); assert.equal(x.ctl.state.returnMode,'full');
  assert.deepEqual(x.calls,[{on:true}]); assert.equal(x.pads.at(-1),null);
});
test('a failed native restore leaves the player available for another restore attempt', async () => {
  let fail=true;
  const x=fixture({windowMode:async value=>{if(!value.on && fail) throw Error('restore failed'); return {on:value.on,aspect:4/3};}});
  await x.ctl.enter(); await assert.rejects(x.ctl.restore(),/restore failed/);
  assert.equal(x.ctl.state.on,true); assert.equal(x.pads.at(-1),null);
  fail=false; await x.ctl.restore(); assert.equal(x.ctl.state.on,false);
});
test('stream frame dimensions update the ratio without taking another restore snapshot', async () => {
  const x=fixture({resolve:async()=>({sid:'remote',local:false})}); await x.ctl.enter();
  assert.deepEqual(x.pads,['remote']);
  await x.ctl.picture(640,480); assert.deepEqual(x.calls.at(-1),{on:true,aspect:4/3});
  const n=x.calls.length; await x.ctl.picture(0,0); await x.ctl.picture(640,480); assert.equal(x.calls.length,n);
});
test('intermediate window resize bounds letterbox rather than deforming the picture', () => {
  assert.deepEqual(fit(800,600,16/9),{x:0,y:75,w:800,h:450});
  const r=fit(600,300,4/3); assert.equal(r.w/r.h,4/3); assert.equal(r.x,100);
});
test('a late remote frame cannot reopen compact mode after double-click restore', async () => {
  let finish; const calls=[];
  const x=fixture({resolve:async()=>({sid:'remote',local:false}),windowMode:async value=>{
    calls.push(value); if(!value.on) await new Promise(r=>{finish=r;}); return {on:value.on,aspect:4/3};
  }});
  await x.ctl.enter(); const exit=x.ctl.restore(); await Promise.resolve();
  const image=x.ctl.picture(1920,1080); finish(); await Promise.all([exit,image]);
  assert.equal(x.ctl.state.on,false); assert.deepEqual(calls,[{on:true},{on:false}]);
});
test('both desktop PiP entry points use compact mode rather than the old streamed-only mini window', () => {
  assert.match(html,/else if \(a === "pip"\) \{ compactEnter\(\)/);
  assert.match(html,/\$\("#tb-mini"\)\.onclick = \(\) => compactEnter\(\)/);
  assert.doesNotMatch(html,/This game runs natively in its own RetroArch window/);
  const surface=fs.readFileSync(require.resolve('../clients/desktop/game-surface.js'),'utf8');
  assert.match(surface,/VIEW\.mode === "compact"/);
});
test('double click and Escape restore the app; native hover reaches the same controls', () => {
  const start=html.indexOf("gbox.onCompactView?.");
  const end=html.indexOf("setInterval(() => {",start);
  const events={},changed=[], restores=[];
  vm.runInNewContext(html.slice(start,end),{
    gbox:{onCompactView:f=>changed.push(f)},compactController:{changed(){}},COMPACT:{on:true},
    GBoxCompactCoach:require('../clients/desktop/compact-coach'),
    compactRestore:()=>{restores.push('restore'); return Promise.resolve();},compactHover(){},addEventListener:(name,fn)=>{events[name]=fn;}
  });
  let prevented=0;
  events.dblclick({preventDefault(){prevented++;},stopPropagation(){}});
  events.keydown({key:'Escape',preventDefault(){prevented++;}});
  assert.equal(restores.length,2); assert.equal(prevented,2);
  assert.match(html,/ev\.event === 'compact-hover'/);
});
function embedding({remote=false,ok=true,ended=false}={}) {
  const sessions=[{session_id:'picked',state:ended?'ended':'running',started:10,title:'Picked game',adapter:'retroarch',
    detail:{pid:123,local_window:!remote,worker_name:remote?'other':'PC'}},
    {session_id:'newer',state:'running',started:99,title:'Another game',detail:{pid:999,local_window:true,worker_name:'PC'}}];
  const seen={surfaces:[],syncs:[],restores:0};
  const compact={on:true,sid:'picked',local:!remote,aspect:16/9};
  const emb={sid:'picked',pid:123,closed:new Set()};
  const node={classList:{contains:()=>false},hidden:true};
  const ctx=vm.createContext({LIVE_SESSIONS:{peek:()=>({ok,data:sessions})},S:{workerName:'PC'},EMB:emb,COMPACT:compact,
    $:()=>node,document:{querySelector:selector=>selector==='section.on'?{id:'play'}:null},
    GPU_GAME:{pid:null},gpuGameDispose:async()=>{},pipHandle(){},gbox:{embedSync:async value=>seen.syncs.push(value)},
    compactRestore:async()=>{seen.restores++;compact.on=false;},VIEW:{mode:'compact'},FLOW:{on:false},EYE:{on:false},
    GBoxReportStory:{isFullOpen:()=>false},GBoxCompactGame:{fit},GBoxEmbedGeometry:require('../clients/desktop/embed-geometry'),
    innerWidth:800,innerHeight:600,gpuGamePresent:async(...args)=>{seen.surfaces.push(args);return true;},embedSoon(){},
    Date,console
  });
  const start=html.indexOf('async function embedTick() {');
  vm.runInContext(html.slice(start,html.indexOf('setInterval(embedTick,',start)),ctx);
  return {tick:()=>ctx.embedTick(),seen,emb,compact};
}
test('compact native view pins the selected session and fits the whole window without sidebar cut-outs',async()=>{
  const x=embedding(); await x.tick();
  assert.equal(x.seen.surfaces[0][0].session_id,'picked');
  assert.deepEqual(JSON.parse(JSON.stringify(x.seen.surfaces[0][1])),{x:0,y:75,w:800,h:450});
  assert.equal(x.seen.surfaces[0][3],false);
});
test('remote compact view hides a local native surface without stopping its game',async()=>{
  const x=embedding({remote:true}); await x.tick();
  assert.deepEqual(x.seen.syncs,[null]); assert.equal(x.seen.surfaces.length,0); assert.equal(x.compact.on,true);
});
test('session ending restores the app; a temporary service error leaves PiP intact',async()=>{
  const x=embedding({ended:true}); await x.tick(); assert.equal(x.seen.restores,1);
  const y=embedding({ok:false}); await y.tick(); assert.equal(y.seen.restores,0); assert.equal(y.compact.on,true);
});
