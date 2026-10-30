const {test} = require('node:test');
const assert = require('node:assert/strict');
const P = require('../clients/desktop/pip-stream-picker');
const fs = require('node:fs');
const vm = require('node:vm');
const row = (sid, worker='Spark', extra={}) => ({session_id:sid,worker:'w-'+worker,state:'running',worker_online:true,detail:{worker_name:worker},title:'Resident Evil 5',...extra});
const a=row('spark-one'), b=row('i9-one','i9'), c=row('spark-two','Spark',{started:20,title:'Resident Evil 6'});
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};
function rig() {
  const values=new Map(),shown=[];let source='http://spark:8765',data={rows:[a,b,c],hosts:[]};
  const io={origin:()=>source,storage:{getItem:k=>values.get(k),setItem:(k,v)=>values.set(k,v)},read:async()=>data,
    show:async(r,current)=>{if(current())shown.push(r.session_id);return current();}};
  return {io,values,shown,setOrigin:s=>source=s,setData:v=>data=v,ctl:P.create(io)};
}
test('selection survives reload, stays scoped to server origin, and persists no credentials',async()=>{
  const x=rig();await x.ctl.select(b.session_id);
  const reloaded=P.create(x.io);assert.equal((await reloaded.target()).session_id,b.session_id);
  assert.equal(reloaded.preference.pinned,true);assert.equal(reloaded.allows(a),false);
  assert.deepEqual(Object.keys(JSON.parse([...x.values.values()][0])).sort(),['installation','pinned','sid','worker','workerId']);
  x.setOrigin('http://other:8765');assert.equal(reloaded.preference,null);assert.equal(await reloaded.target(),null);
  x.setOrigin('http://spark:8765');assert.equal(reloaded.preference.sid,b.session_id);
});
test('unselected connected stream is remembered without creating an explicit instance pin',async()=>{
  const x=rig();x.ctl.remember(a);assert.equal(P.create(x.io).preference.sid,a.session_id);assert.equal(x.ctl.allows(b),true);
  await x.ctl.select(a.session_id);x.ctl.remember(b);assert.equal(x.ctl.preference.sid,a.session_id);
});

test('a fresh local PiP dispatch supersedes an older pin, but reloads and newer choices do not replay it',async()=>{
  const x=rig();let now=1000;x.io.now=()=>now;
  const ctl=P.create(x.io);await ctl.select(a.session_id);
  const d={id:'d'.repeat(32),command:'start',pip:true,at:2};
  now=2100;assert.equal(ctl.canDispatch(d),true);
  await ctl.select(b.session_id);assert.equal(ctl.canDispatch(d),false);
  assert.equal(ctl.preference.sid,b.session_id);
  const reloaded=P.create(x.io);assert.equal(reloaded.canDispatch(d),false);
  assert.equal(reloaded.preference.sid,b.session_id);
  assert.equal(reloaded.canDispatch({...d,at:3,pip:false}),false);
  assert.equal(reloaded.canDispatch({...d,at:3,lapsed:'operator took control'}),false);
  assert.equal(reloaded.canDispatch({...d,at:3}),true);
});

test('a dispatch retries a transient lookup failure without overriding a newer manual selection',async()=>{
  const x=rig();let now=1000;x.io.now=()=>now;const ctl=P.create(x.io);
  await ctl.select(a.session_id);
  const d={id:'d'.repeat(32),command:'start',pip:true,at:2};now=2100;
  const read=x.io.read;x.io.read=async()=>{throw Error('offline');};
  await assert.rejects(ctl.select(b.session_id,()=>true,{dispatch:d}),/offline/);
  assert.equal(ctl.preference.sid,a.session_id);assert.equal(ctl.canDispatch(d),true);
  x.io.read=read;assert.equal(await ctl.select(b.session_id,()=>true,{dispatch:d}),true);
  assert.equal(ctl.canDispatch(d),false);
  now=4000;await ctl.select(a.session_id);
  assert.equal(await ctl.select(b.session_id,()=>true,{dispatch:{...d,at:3}}),false);
  assert.equal(ctl.preference.sid,a.session_id);
});

for (const pinned of [false,true]) test(`a new local PiP dispatch persists the instance once (previous pin: ${pinned})`,async()=>{
  const html=fs.readFileSync(require.resolve('../clients/desktop/index.html'),'utf8');
  const start=html.indexOf('async function mercPipPoll()');
  const code=html.slice(start,html.indexOf('setInterval(() => { if (document.visibilityState',start));
  const d={id:'d'.repeat(32),command:'start',pip:true,at:2},selected=[];
  const host={dispatch:d,current_run:{session_id:b.session_id,phase:'playing'}};
  const M=require('../clients/web/viz/mercmode'),state={busy:false,handled:'',closed:''};
  const ctx=vm.createContext({MERC_PIP:state,window:{GBoxMercMode:M},S:{workerName:'i9'},gbox:{api(){}},
    pipSelection:{revision:0,preference:{pinned},canDispatch:()=>true,
      select:async(sid,valid,opts)=>{assert.equal(opts.dispatch,d);selected.push(sid);ctx.pipSelection.preference.pinned=true;return true;}},
    mercOwnHost:async()=>host,mercPipSave(){},console});
  vm.runInContext(code,ctx);await ctx.mercPipPoll();await ctx.mercPipPoll();
  assert.deepEqual(selected,[b.session_id]);assert.equal(state.handled,d.id);
});
test('reload keeps an exact live session even with another current run on that PC',()=>{
  const saved={sid:a.session_id,worker:'Spark'};
  const hosts=[{name:'Spark',current_run:{session_id:c.session_id,phase:'playing'}}];
  assert.equal(P.resolve(saved,[a,c],hosts),a);
  assert.equal(P.resolve(saved,[{...a,state:'ended'},c],hosts),c);
  assert.equal(P.resolve(saved,[{...a,warm:true},c],hosts),c);
});
test('ended SID follows the same instance through worker restart and title rotation, never another PC',()=>{
  const saved={sid:a.session_id,worker:'Spark',workerId:a.worker};
  const next={...c,worker:'new-registration'};
  assert.equal(P.resolve(saved,[b,next]),next);
  assert.equal(P.resolve(saved,[b]),null);
  assert.equal(P.sameInstance({...saved,installation:'install-A'},{...next,federation:{authority:'install-B'}}),false);
});

for (const pinned of [false,true]) test(`native session replacement preserves pinned PiP geometry (pin: ${pinned})`,async()=>{
  const html=fs.readFileSync(require.resolve('../clients/desktop/index.html'),'utf8');
  const start=html.indexOf('async function embedTick()');
  const prefix=html.slice(start,html.indexOf('    if (COMPACT.on && !COMPACT.local)',start));
  const shown={on:true,local:true,sid:'old-local'};
  const ctx=vm.createContext({EMB:{closed:new Set()},LIVE_SESSIONS:{peek:()=>({ok:true,data:[]})},
    $:()=>({}),S:{workerName:'i9'},nativeSessionLease:null,COMPACT:shown,
    pipSelection:{preference:{pinned}},mercPipHold:()=>false,
    compactRestore:async()=>{shown.on=false;}});
  vm.runInContext(prefix+'} finally { EMB.busy=false; }}',ctx);
  await ctx.embedTick();
  assert.equal(shown.on,pinned); // only an explicit full-app action should close a pinned PiP
});

test('automatic native presentation waits while an explicit saved PiP is restoring',async()=>{
  const html=fs.readFileSync(require.resolve('../clients/desktop/index.html'),'utf8');
  const start=html.indexOf('async function embedTick()');
  const prefix=html.slice(start,html.indexOf('    if (COMPACT.on && !COMPACT.local)',start));
  const ctx=vm.createContext({EMB:{closed:new Set()},LIVE_SESSIONS:{peek:()=>({ok:true,data:[]})},
    $:()=>({}),S:{workerName:'i9'},nativeSessionLease:null,COMPACT:{on:false},
    pipSelection:{preference:{pinned:true}},clientRefresh:{pending:()=>({compact:true})}});
  vm.runInContext(prefix+'throw Error("Automatic full-app presentation stole saved PiP"); } finally { EMB.busy=false; }}',ctx);
  await ctx.embedTick();
});
test('warm predecessors and handovers never become selectable; offline and starting cards explain their state',()=>{
  const warm={...a,session_id:'parked',warm:true}, predecessor={...a,session_id:'previous'};
  const data=[warm,predecessor,c,{...b,worker_online:false}];
  let hosts=[{name:'Spark',online:true,current_run:{session_id:c.session_id,phase:'starting',mercmode_predecessor:{session_id:'previous'}}}];
  assert.deepEqual(P.candidates(data,hosts).map(e=>[e.row.session_id,e.status]),[[b.session_id,'offline'],[c.session_id,'starting']]);
  assert.equal(P.resolve({sid:'previous',worker:'Spark'},data,hosts),null);
  hosts[0].current_run.phase='playing';hosts[0].current_run.handover={};
  assert.equal(P.status(c,hosts),'switching');assert.equal(P.resolve({sid:'previous',worker:'Spark'},data,hosts),null);
});
test('previous and next wrap consistently and recover when the displayed SID expires',()=>{
  assert.equal(P.cycle([a,b,c],a.session_id,-1),c);assert.equal(P.cycle([a,b,c],c.session_id,1),a);
  assert.equal(P.cycle([a,b,c],'gone',1),a);assert.equal(P.cycle([a,b,c],'gone',-1),c);assert.equal(P.cycle([],'gone',1),null);
});
test('stale menu events and sessions that warm during the fresh lookup cannot change the view',async()=>{
  const x=rig(),read=deferred();x.io.read=()=>read.promise;
  let open=true;const choosing=x.ctl.select(a.session_id,()=>open);open=false;read.resolve({rows:[a],hosts:[]});
  assert.equal(await choosing,false);assert.deepEqual(x.shown,[]);assert.equal(x.ctl.preference,null);
  x.io.read=async()=>({rows:[{...a,warm:true}],hosts:[]});
  await assert.rejects(x.ctl.select(a.session_id),/no longer ready/);assert.deepEqual(x.shown,[]);
});
test('new selection invalidates an earlier in-flight show and commits only the newer view',async()=>{
  const x=rig(),hold=deferred();x.io.show=async(r,current)=>{if(r===a)await hold.promise;if(current())x.shown.push(r.session_id);return current();};
  const old=x.ctl.select(a.session_id);await Promise.resolve();assert.equal(x.ctl.preference.sid,a.session_id);
  await x.ctl.select(b.session_id);hold.resolve();assert.equal(await old,false);
  assert.deepEqual(x.shown,[b.session_id]);assert.equal(x.ctl.preference.sid,b.session_id);
});
test('superseding failed lookup clears obsolete pending choice and retains the last successful selection',async()=>{
  const x=rig(),hold=deferred();await x.ctl.select(b.session_id);
  x.io.show=async(r,current)=>{await hold.promise;return current();};
  const old=x.ctl.select(a.session_id);await Promise.resolve();assert.equal(x.ctl.preference.sid,a.session_id);
  x.io.read=async()=>{throw Error('connection lost');};
  await assert.rejects(x.ctl.select(c.session_id),/connection lost/);assert.equal(x.ctl.preference.sid,b.session_id);
  hold.resolve();await old;assert.equal(x.ctl.preference.sid,b.session_id);
});
test('a failed show does not overwrite the saved selection; closing during an accepted show is harmless',async()=>{
  const x=rig();await x.ctl.select(a.session_id);x.io.show=async()=>{throw Error('stream failed');};
  await assert.rejects(x.ctl.select(b.session_id),/stream failed/);assert.equal(x.ctl.preference.sid,a.session_id);
  let open=true;x.io.show=async()=>{open=false;return true;};await x.ctl.select(b.session_id,()=>open);
  assert.equal(x.ctl.preference.sid,b.session_id);
});
test('an asynchronous target read cannot return a session from a changed API origin',async()=>{
  const x=rig();x.ctl.remember(a);const hold=deferred();x.io.read=()=>hold.promise;
  const selecting=x.ctl.target();x.setOrigin('http://other');hold.resolve({rows:[a],hosts:[]});assert.equal(await selecting,null);
});
test('previews are serial, bounded to four visible cards, and scheduled only while open',async()=>{
  const loaded=[],timers=new Map();let counter=0,active=0,peak=0;
  const p=P.previews({items:()=>[1,2,3,4,5,6],load:async(item)=>{active++;peak=Math.max(peak,active);loaded.push(item);await Promise.resolve();active--;},
    setTimeout:(fn,ms)=>{timers.set(++counter,{fn,ms});return counter;},clearTimeout:id=>timers.delete(id)});
  await p.ready;assert.deepEqual(loaded,[1,2,3,4]);assert.equal(peak,1);assert.deepEqual([...timers.values()].map(t=>t.ms),[5000]);
  p.stop();assert.equal(timers.size,0);
});
test('closing previews aborts the current request and prevents any remaining frames or timers',async()=>{
  const loaded=[],timers=new Map();let aborted=false,counter=0;
  const p=P.previews({items:()=>[1,2,3],load:(item,signal)=>new Promise(resolve=>{loaded.push(item);signal.addEventListener('abort',()=>{aborted=true;resolve();});}),
    setTimeout:(fn,ms)=>{timers.set(++counter,{fn,ms});return counter;},clearTimeout:id=>timers.delete(id)});
  p.stop();await p.ready;assert.equal(aborted,true);assert.deepEqual(loaded,[1]);assert.equal(timers.size,0);
});
test('cards escape captions, identify sessions and expose selected/offline states',()=>{
  const html=P.html(P.candidates([a,{...b,worker_online:false,title:'<img onerror=attack>'}]),a.session_id);
  assert.match(html,/aria-pressed="true"/);assert.match(html,/title="Spark · Resident Evil 5 · spark-one"/);assert.match(html,/PC offline/);
  assert.doesNotMatch(html,/<img onerror=/);assert.match(html,/&lt;img onerror=attack&gt;/);
});
test('a timed-out URL lookup cannot clear a newer preview or its load handlers',async()=>{
  const old=deferred(),badge={},img={src:'',parentElement:{querySelector:()=>badge},classList:{add(){}},removeAttribute(){this.src='';}};
  const firstAbort=new AbortController(),secondAbort=new AbortController();
  const first=P.previewImage(img,()=>old.promise,()=>true,firstAbort.signal);
  await Promise.resolve();firstAbort.abort();await first;
  const second=P.previewImage(img,async()=> 'new-frame',()=>true,secondAbort.signal);
  await new Promise(resolve=>setImmediate(resolve));assert.equal(img.src,'new-frame');
  const onload=img.onload;old.resolve('old-frame');await new Promise(resolve=>setImmediate(resolve));
  assert.equal(img.src,'new-frame');assert.equal(img.onload,onload);
  img.onload();await second;assert.equal(badge.textContent,'Live');
});
test('an ordinary PiP opening is invalidated by a later explicit stream choice',async()=>{
  const html=fs.readFileSync(require.resolve('../clients/desktop/index.html'),'utf8');
  const code=html.slice(html.indexOf('const compactEnter ='),html.indexOf('const compactRestore ='));
  const pending=deferred(),selection={revision:0,preference:null,target:async()=>null};
  let requested;
  const C=require('../clients/desktop/compact-game');
  const ctl=C.create({resolve:async r=>{requested=r;await pending.promise;return {sid:'old'};},mode:()=> 'auto',
    render(){},pad(){},present(){},windowMode:async()=>({on:true})});
  const ctx=vm.createContext({pipSelection:selection,compactController:ctl});
  vm.runInContext(code+';globalThis.openPip=compactEnter;',ctx);
  const first=ctx.openPip();await new Promise(resolve=>setImmediate(resolve));
  assert.equal(typeof requested.current,'function');selection.revision++;pending.resolve();
  assert.equal(await first,false);assert.equal(ctl.state.on,false);
});
test('preview URL resolving after its menu origin changes is never attached to an image',async()=>{
  const held=deferred(),badge={},attached=[];let sameOrigin=true;
  const img={parentElement:{querySelector:()=>badge},classList:{add(){}},removeAttribute(){},set src(value){attached.push(value);}};
  const shown=P.previewImage(img,()=>held.promise,()=>sameOrigin,new AbortController().signal);
  sameOrigin=false;held.resolve('https://old-origin/frame?token=new-origin-secret');await shown;
  assert.deepEqual(attached,[]);assert.equal(img.onload,null);
});
test('actual saved-view restoration replaces only the expired PiP SID with its selected-instance successor',async()=>{
  const html=fs.readFileSync(require.resolve('../clients/desktop/index.html'),'utf8');
  const src=html.slice(html.indexOf('async function restoreClientView()'),html.indexOf('// Native desktop PiP has no browser gesture restriction.'));
  let value={sid:'old',compact:true,section:'play',guest:{tab:'Sessions',playing:'old',active:'other-view',pip:null}},entered,guestScript;
  const ctx=vm.createContext({clientViewNavigation:0,clientViewRestoring:true,EMB:{},
    pipSelection:{preference:{sid:'old',worker:'Spark'},target:async()=>c},
    clientRefresh:{pending:()=>value,retain:v=>value=v,remember(){},done:()=>value=null},loadPlay:async()=>{},
    document:{querySelector:s=>s==='#wv'?{gboxReady:Promise.resolve(),executeJavaScript:async code=>{guestScript=code;return {missing:[]};}}:{click(){}}},
    compactController:{enter:async v=>entered=v},gbox:{},toast(){}});
  vm.runInContext(src,ctx);await ctx.restoreClientView();
  assert.equal(entered.sid,c.session_id);assert.equal(entered.guest.playing,c.session_id);assert.equal(entered.guest.active,'other-view');
  assert.match(guestScript,/spark-two/);assert.equal(value,null);
});

for (const pinned of [false,true]) test(`saved PiP survives a worker-offline gap only for an explicit instance choice (pin: ${pinned})`,async()=>{
  const html=fs.readFileSync(require.resolve('../clients/desktop/index.html'),'utf8');
  const src=html.slice(html.indexOf('async function restoreClientView()'),html.indexOf('// Native desktop PiP has no browser gesture restriction.'));
  let value={sid:'old',compact:true,section:'play',guest:{tab:'Sessions',playing:'old'}},ready=false,entered;
  const ctx=vm.createContext({clientViewNavigation:0,clientViewRestoring:true,EMB:{},
    pipSelection:{preference:{sid:'old',worker:'Spark',pinned},target:async()=>ready?c:null},
    clientRefresh:{pending:()=>value,retain:v=>value=v,remember(){},done:()=>value=null},loadPlay:async()=>{},
    document:{querySelector:s=>s==='#wv'?{gboxReady:Promise.resolve(),executeJavaScript:async()=>ready?{missing:[]}:{offline:['old']}}:{click(){}}},
    compactController:{enter:async v=>{if(!ready)throw Object.assign(Error('Worker is replacing its session'),{offline:true});entered=v;}},gbox:{},toast(){}});
  vm.runInContext(src,ctx);await ctx.restoreClientView();
  if (!pinned) { assert.equal(value,null);assert.equal(entered,undefined);return; }
  assert.equal(value.compact,true);assert.equal(value.sid,'old');assert.equal(entered,undefined);
  ready=true;await ctx.restoreClientView();
  assert.equal(entered.sid,c.session_id);assert.equal(entered.compact,true);assert.equal(value,null);
});
test('old local MercMode lookup cannot override a pending explicit choice on the same instance',async()=>{
  const html=fs.readFileSync(require.resolve('../clients/desktop/index.html'),'utf8');
  const start=html.indexOf('async function mercPipPoll()');
  const code=html.slice(start,html.indexOf('setInterval(() => { if (document.visibilityState',start));
  const held=deferred(),looked=deferred(),shows=[];
  const M=require('../clients/web/viz/mercmode');
  const host={name:'Spark',id:'w',settings:{enabled:true},current_run:{session_id:'w-auto',phase:'playing',mercmode:{title:'re6'},mercmode_predecessor:{session_id:'w-old'}}};
  const selection={revision:0,preference:null,canDispatch:()=>false};
  const ctx=vm.createContext({MERC_PIP:{busy:false,last:'w-old'},window:{GBoxMercMode:M},GBoxMercMode:M,
    S:{workerName:'Spark'},gbox:{api(){}},COMPACT:{on:true,sid:'w-old'},pipSelection:selection,
    mercOwnHost:async()=>host,sessionById:async()=>{looked.resolve();return held.promise;},
    pipShow:async sid=>shows.push(sid),console});
  vm.runInContext(code,ctx);const poll=ctx.mercPipPoll();await looked.promise;
  selection.preference={sid:'w-selected',worker:'Spark',pinned:true};selection.revision++;
  held.resolve(row('w-old'));await poll;
  assert.deepEqual(shows,[]);assert.equal(ctx.COMPACT.sid,'w-old');assert.equal(ctx.MERC_PIP.busy,false);
});
