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
    $:()=>null,
    compactRestore:()=>{restores.push('restore'); return Promise.resolve();},compactHover(){},addEventListener:(name,fn)=>{events[name]=fn;}
  });
  let prevented=0;
  events.dblclick({target:{closest:()=>null},preventDefault(){prevented++;},stopPropagation(){}});
  events.keydown({key:'Escape',preventDefault(){prevented++;}});
  assert.equal(restores.length,2); assert.equal(prevented,2);
  assert.match(html,/ev\.event === 'compact-hover'/);
});
function embedding({remote=false,ok=true,ended=false,offline=false,pip=true,docked=true,single=false}={}) {
  const sessions=[{session_id:'picked',state:ended?'ended':'running',started:10,title:'Picked game',adapter:'retroarch',
    ...(offline?{worker_online:false}:{}),detail:{pid:123,local_window:!remote,worker_name:remote?'other':'PC'}},
    ...(single?[]:[{session_id:'newer',state:'running',started:99,title:'Another game',detail:{pid:999,local_window:true,worker_name:'PC'}}])];
  const seen={surfaces:[],syncs:[],restores:0,shown:[]};
  const compact={on:pip,sid:pip?'picked':null,local:!remote,aspect:16/9};
  const emb={sid:docked?'picked':null,pid:docked?123:null,closed:new Set()};
  const node={classList:{contains:()=>false},hidden:true};
  const wv={dataset:{ready:'false'},executeJavaScript:async code=>{seen.shown.push(code);},getBoundingClientRect:()=>({})};
  const ctx=vm.createContext({nativeSessionLease:null,LIVE_SESSIONS:{peek:()=>({ok,data:sessions})},S:{workerName:'PC'},EMB:emb,COMPACT:compact,
    $:()=>node,document:{querySelector:selector=>selector==='section.on'?{id:'play'}:selector==='#wv'?wv:null},
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

test('remote compact PiP remains open through a game restart',async()=>{
  const x=embedding({remote:true,ended:true});await x.tick();
  assert.equal(x.seen.restores,0);assert.equal(x.compact.on,true);
});

function followRig({ready='true',look,health={state:'running',age_s:.1},timers=globalThis}={}){
  let io;const image={style:{backgroundImage:'old-picture'}};
  const state={on:true,sid:'old',local:false};const changes=[],reads=[];
  const wv={dataset:{ready},executeJavaScript:async code=>{if(code.includes('.picture('))return look(state);}};
  const context=vm.createContext({GBoxSessionContinuity:{create:value=>{io=value;return {}; }},COMPACT:state,
    compactSession:null,compactTitle:'old',compactStreamUrl:'old-url',sessionTitle:s=>s.title,closePipMenu:()=>changes.push('closed modifiers'),
    S:{apiUrl:'http://spark'},gbox:{token:async()=> 'test'},document:{querySelector:()=>wv},$:()=>image,
    compactApi:async(path,body,method)=>{reads.push([path,method]);if(health instanceof Error)throw health;return health;},
    setTimeout:timers.setTimeout,clearTimeout:timers.clearTimeout,
    compactController:{follow:async(from,s)=>{changes.push(s.sid);state.sid=s.sid;}}});
  const start=html.indexOf('const compactContinuity =');
  vm.runInContext(html.slice(start,html.indexOf('setInterval(() => compactContinuity',start)),context);
  return {follow:(session,from)=>io.follow(session,from),changes,reads,image,state};
}
test('desktop handoff waits for a visible successor frame and respects a PiP closed during the probe',async()=>{
  for(const visible of [false,true,'closed']){
    const x=followRig({look:state=>{
      if(visible==='closed')state.on=false;
      return {visible:visible!==false,poster:'data:image/jpeg;base64,frame'};
    }});
    await x.follow({session_id:'new',title:'RE5'},'old');
    assert.deepEqual(x.changes,visible===true?['closed modifiers','new']:[]);
    if(visible!==true)assert.equal(x.image.style.backgroundImage,'old-picture');
    assert.deepEqual(x.reads,[],'a view that answered decides alone');
  }
});

// operator 2026-10-27: after a Spark restart the PiP kept the ended session's last frame on "Reconnecting..." for 6+ min
// while MercMode played: the main window's view behind the PiP was never ready, and following waited for it forever.
test('a view behind the PiP that is not ready or silent never holds it on an ended game: a live stream is followed',async()=>{
  for(const ready of ['false',undefined]){
    const live=followRig({ready,look:()=>{throw Error('a view that is not ready is not asked');}});
    await live.follow({session_id:'w2-re4',title:'RE4'},'old');
    assert.deepEqual(live.changes,['closed modifiers','w2-re4']);
    assert.deepEqual(live.reads,[['/api/sessions/w2-re4/stream/health','GET']]);
    assert.equal(live.image.style.backgroundImage,'','the dead game\'s last frame never stays under the new one');
  }
  for(const health of [{state:'running',age_s:9},{state:'running',age_s:null},{state:'ended'},Error('offline')]){
    const booting=followRig({ready:'false',health});                      // no fresh frame yet: asked again next poll
    await booting.follow({session_id:'w2-re4',title:'RE4'},'old');
    assert.deepEqual(booting.changes,[]); assert.equal(booting.image.style.backgroundImage,'old-picture');
  }
  // a view that never answers (a hung guest) is given 5 s, then the stream's health decides
  const waits=[];
  const fake={setTimeout:(fn,ms)=>{waits.push(ms);fn();return waits.length;},clearTimeout(){}};
  const silent=followRig({look:()=>new Promise(()=>{}),timers:fake});
  await silent.follow({session_id:'w2-re4',title:'RE4'},'old');
  assert.deepEqual(waits,[5000]); assert.deepEqual(silent.changes,['closed modifiers','w2-re4']);
  const failing=followRig({look:()=>{throw Error('Waiting for game picture');},health:{state:'running',age_s:40}});
  await failing.follow({session_id:'w2-re4',title:'RE4'},'old');
  assert.deepEqual(failing.changes,[],'a stale stream is not followed either');
});

test('replacement changes only the game stream and pad target, preserving PiP window state',async()=>{
  const x=fixture({resolve:async()=>({sid:'remote-old',local:false}),mode:()=> 'full'});
  await x.ctl.enter();await x.ctl.picture(1920,1080);
  const calls=x.calls.length;
  assert.equal(await x.ctl.follow('remote-old',{sid:'remote-new',local:false}),true);
  assert.equal(x.ctl.state.sid,'remote-new');assert.equal(x.ctl.state.aspect,16/9);
  assert.equal(x.ctl.state.returnMode,'full');assert.equal(x.calls.length,calls);
  assert.equal(x.pads.at(-1),'remote-new');
  await x.ctl.restore();assert.equal(await x.ctl.follow('remote-new',{sid:'late',local:false}),false);
});
test('session ending restores the app; a temporary service error leaves PiP intact',async()=>{
  const x=embedding({ended:true}); await x.tick(); assert.equal(x.seen.restores,1);
  const y=embedding({ok:false}); await y.tick(); assert.equal(y.seen.restores,0); assert.equal(y.compact.on,true);
});

// #2870 / operator 2026-10-26 (i9-NUC): a "running" native game here whose worker is offline was docked and shown in the
// Sessions view after every reload, a black view that never came. It is never auto-docked or auto-opened.
test('a native game here whose worker is offline is never docked or shown; a game on a PC that answers still is',async()=>{
  const live=embedding({pip:false,docked:false,single:true}); await live.tick();
  assert.equal(live.emb.sid,'picked'); assert.equal(live.seen.shown.length,1); assert.match(live.seen.shown[0],/show\("Sessions", "picked"\)/);
  const dead=embedding({offline:true,pip:false,docked:false,single:true}); await dead.tick();
  assert.equal(dead.emb.sid,null,'not docked'); assert.deepEqual(dead.seen.shown,[],'the Sessions view is not moved to it');
  assert.deepEqual(dead.seen.syncs,[]); assert.equal(dead.seen.surfaces.length,0);
  // the lease that normally resolves the docked game applies the same rule (clients/desktop/session-lease.js)
  const lease=require('../clients/desktop/session-lease.js').create({probe:async()=>({ok:true,alive:true})});
  const offlineRow={session_id:'nuc-dead',state:'running',worker_online:false,started:5,detail:{pid:7,local_window:true,worker_name:'PC'}};
  assert.equal(await lease.resolve('http://spark',{ok:true,data:[offlineRow]},{worker:'PC'}),null);
  const healthy={...offlineRow,session_id:'nuc-live',worker_online:undefined};
  assert.equal((await lease.resolve('http://spark',{ok:true,data:[offlineRow,healthy]},{worker:'PC'})).session.session_id,'nuc-live');
});

test('picture-in-picture never opens a game whose PC is offline, and never moves the Sessions view to it',async()=>{
  const shown=[];
  const wv={gboxReady:Promise.resolve(),executeJavaScript:async code=>{shown.push(code);}};
  const rows=[{session_id:'nuc-dead',state:'running',title:'Resident Evil: The Mercenaries 3D (USA)',worker_online:false,started:20,
    detail:{local_window:true,worker_name:'i9-NUC'}},{session_id:'spark-live',state:'running',title:'Resident Evil 5',started:9,detail:{worker_name:'lilspark'}}];
  const ctx=vm.createContext({GBoxCompactGame:{create},GBoxSessionContinuity:require('../clients/web/viz/session-continuity.js'),
    VIEW:{mode:'auto'},S:{apiUrl:'http://spark',workerName:'i9-NUC'},EMB:{sid:null},EYE:{on:false},clientViewNavigation:0,
    gboxState:async()=>({}),sessionById:async sid=>rows.find(s=>s.session_id===sid)||null,liveSessions:async()=>({ok:true,data:rows}),
    gbox:{api:async()=>({ok:true,data:rows}),token:async()=>'t',compactView:async v=>({...v})},sessionTitle:s=>s?.title||'',closePops(){},
    document:{fullscreenElement:null,querySelector:sel=>sel==='#wv'?wv:null},window:{},miniPadTarget(){},embedTick(){},renderClientUpdate(){},
    updateCompactMedia(){},compactCoach:{update(){}},$:()=>null,gboxStreamWatchdog:{healthUrl:()=>''},compactHover(){},compactRestore:async()=>{},toast(){},console});
  const start=html.indexOf('const compactController = GBoxCompactGame.create({');
  const compactController=vm.runInContext(html.slice(start,html.indexOf('const COMPACT = compactController.state;',start))+'\ncompactController',ctx);
  await assert.rejects(compactController.enter({sid:'nuc-dead'}),/runs on a PC that is offline; it was not opened\. Your view was not changed\./);
  assert.deepEqual(shown,[],'the Sessions view is not moved to it'); assert.equal(compactController.state.on,false);
  // with nothing requested, the newest game on a PC that answers is the one shown, never the dead one
  assert.match(html,/r\.data\.filter\(s => s\.state === 'running' && s\.worker_online !== false\)\.sort\(\(a,b\) => \(b\.started \|\| 0\) - \(a\.started \|\| 0\)\)\[0\]/);
  // a saved view of such a game is dropped instead of retried every 2 s (the guest reports it offline), and the PiP error carries the offline mark
  assert.match(html,/if \(restored\?\.offline\?\.length\) \{ clientRefresh\.done\(\); toast\(/);
  assert.match(html,/if \(error\.offline\) \{ clientRefresh\.done\(\); toast\(error\.message, 8000\); return; \}/);
  assert.match(html,/throw Object\.assign\(Error\(`\$\{sessionTitle\(session\) \|\| 'This game'\} runs on a PC that is offline/);
});
