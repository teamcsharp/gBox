const {test}=require('node:test'); const assert=require('node:assert/strict');
const {create,RING_KINDS,ringKindLabel,readRingKind,ammoView,createAmmoControl,ringKindOptions,bindRing}=require('../clients/web/viz/stream-interventions.js');
const {current}=require('../clients/web/viz/mercs-current.js');
test('live maps follow the playing title while the previous emulator remains warm',()=>{
  const warm={session_id:'worker-old',game_id:'re5',state:'running'},live={session_id:'worker-new',game_id:'re6',state:'running'};
  const h={id:'worker',name:'Spark',online:true,current_run:{phase:'playing',session_id:live.session_id,game_id:'re6'}};
  assert.equal(current(warm.session_id,[warm,live],[h]),live);
  assert.equal(current(null,[warm,live],[h],'Spark'),live);
  assert.equal(current('other-old',[warm,live],[h]),null);
  assert.equal(current(warm.session_id,[warm,live],[{...h,current_run:{...h.current_run,phase:'prepared'}}]),null);
  assert.equal(current(warm.session_id,[warm,{...live,game_id:'other'}],[h]),null);
});
test('twenty clicks have distinct IDs; only native receipts announce detonation',async()=>{
  const posts=[],notes=[]; let id=0, done=false;
  const c=create({uuid:()=>String(++id),schedule:()=>1,cancel:()=>{},notify:(text,row)=>notes.push(row),
    api:async(path,body)=>{
      if(body){posts.push(body);return {request:{id:body.request_id,state:'queued'}};}
      return {requests:posts.map(r=>({id:r.request_id,state:done?'confirmed':'claimed'}))};
    }});
  await Promise.all(Array.from({length:20},()=>c.flash('current-game')));
  assert.equal(new Set(posts.map(r=>r.request_id)).size,20);assert.equal(notes.length,0);
  await c.poll();assert.equal(notes.length,0); done=true;await c.poll();
  assert.equal(notes.length,20);await c.poll();assert.equal(notes.length,20);c.dispose();
});
test('receipt retry never resubmits an effect, even after the viewed session changes',async()=>{
  let posts=0, reads=0;const seen=[],notes=[];
  const c=create({uuid:()=> 'id',schedule:()=>1,cancel:()=>{},notify:(s,r)=>notes.push(r),
    api:async(path,body)=>{seen.push(path);if(body){posts++;return {request:{id:'id',state:'queued'}};}
      if(++reads===1)throw Error('network'); return {requests:[{id:'id',state:'confirmed'}]};}});
  await c.flash('old-session');await c.poll();await c.poll();
  assert.equal(posts,1);assert.equal(notes.length,1);assert.ok(seen.every(p=>p.includes('old-session')));c.dispose();
});
test('unavailable request rejects without claiming an effect',async()=>{
  const notes=[];const c=create({api:async()=>{throw Error('unsupported title');},notify:s=>notes.push(s),uuid:()=> 'id'});
  await assert.rejects(c.flash('session'),/unsupported/);assert.deepEqual(notes,[]);c.dispose();
});

test('weapon choice uses the same durable receipts and never substitutes a flash',async()=>{
  const posts=[],notes=[];const c=create({uuid:()=> 'weapon-id',schedule:()=>1,cancel:()=>{},notify:s=>notes.push(s),
    api:async(path,body)=>{if(body){posts.push(body);return {request:{id:body.request_id,state:'queued'}};}
      return {requests:[{id:'weapon-id',op:'equip_primary',state:'confirmed',result:{weapon:'Hydra'}}]};}});
  await c.equipPrimary('selected-session',25);assert.deepEqual(posts,[{op:'equip_primary',request_id:'weapon-id',args:{item:25}}]);
  assert.deepEqual(notes,[]);await c.poll();assert.match(notes[0],/Hydra equipped.*three minutes/);c.dispose();
});

test('grenade ring sends the chosen kind and announces the detonation count',async()=>{
  const posts=[],notes=[];const c=create({uuid:()=> 'ring-id',schedule:()=>1,cancel:()=>{},notify:(s,r)=>notes.push([s,r]),
    api:async(path,body)=>{if(body){posts.push(body);return {request:{id:body.request_id,state:'queued'}};}
      return {requests:[{id:'ring-id',op:'grenade_ring',state:'confirmed',result:{kind:'flash',detonated:10,requested:10}}]};}});
  await c.grenadeRing('sess','flash');
  assert.deepEqual(posts,[{op:'grenade_ring',request_id:'ring-id',args:{kind:'flash'}}]);
  assert.deepEqual(notes,[]);await c.poll();
  assert.match(notes[0][0],/Flash ring detonated \(10 grenades\)/);assert.equal(notes[0][1].op,'grenade_ring');c.dispose();
});

test('grenade ring defaults to flash when no kind is given',async()=>{
  const posts=[];const c=create({uuid:()=> 'ring-id',schedule:()=>1,cancel:()=>{},api:async(path,body)=>{
    if(body){posts.push(body);return {request:{id:body.request_id,state:'queued'}};}return {requests:[]};}});
  await c.grenadeRing('sess');assert.deepEqual(posts[0].args,{kind:'flash'});c.dispose();
});

test('ring kind chooser: only flash is selectable, remembered per viewer',()=>{
  assert.deepEqual(RING_KINDS.map(k=>[k.kind,k.available]),[['flash',true],['hand',false],['incendiary',false]]);
  assert.equal(ringKindLabel('incendiary'),'Incendiary');
  const store=(v)=>({getItem:()=>v});
  assert.equal(readRingKind(store('flash')),'flash');
  assert.equal(readRingKind(store('hand')),'flash','an unverified stored kind falls back to flash');
  assert.equal(readRingKind(store(null)),'flash');
});

const ammoReport=(enabled,extra={})=>({available:true,capabilities:['equip_primary','set_infinite_ammo'],
  options:{infinite_ammo:{available:true,enabled},weapons:[{item:7,weapon:'Not owned',in_inventory:false},{item:8,weapon:'Unknown inventory'}]},...extra});

test('infinite ammo uses explicit boolean and one durable request, with truthful operation receipts',async()=>{
  const posts=[],notes=[];let done=false;
  const c=create({uuid:()=> 'ammo-id',schedule:()=>1,cancel:()=>{},notify:(s,r)=>notes.push([s,r]),
    api:async(_path,body)=>{if(body){posts.push(body);return {request:{id:body.request_id,state:'queued'}};}
      return {requests:[{id:'ammo-id',op:'set_infinite_ammo',state:done?'confirmed':'claimed',result:{enabled:true}}]};}});
  await c.setInfiniteAmmo('selected',true);assert.deepEqual(posts,[{op:'set_infinite_ammo',request_id:'ammo-id',args:{enabled:true}}]);
  assert.equal(notes.length,0);await c.poll();assert.equal(notes.length,0);done=true;await c.poll();
  assert.equal(posts.length,1);assert.match(notes[0][0],/Infinite ammo on confirmed/);assert.equal(notes[0][1].sid,'selected');
  await assert.rejects(c.setInfiniteAmmo('selected','true'),/explicit on\/off/);assert.equal(posts.length,1);c.dispose();
});
test('ammo state is independent of inventory and never substitutes unknown for confirmed Off',()=>{
  assert.equal(ammoView(ammoReport(false)).disabled,false);
  assert.equal(ammoView(ammoReport(false)).label,'Off');assert.equal(ammoView(ammoReport(true)).label,'On');
  const unknown=ammoView(ammoReport(null));assert.equal(unknown.label,'Unknown');assert.equal(unknown.disabled,true);
  assert.doesNotMatch(unknown.reason,/inventory|unavailable/i);
  assert.equal(ammoView(null).state,'loading');
});
test('ammo click stays pending through queued and claimed states, then confirms only verified readback',async()=>{
  const calls=[],frames=[];let resolve;
  const c=createAmmoControl({sid:'re5-session',send:(sid,on)=>{calls.push([sid,on]);return new Promise(r=>resolve=r);},changed:v=>frames.push(v)});
  c.observe(ammoReport(false));const click=c.toggle();await c.toggle();assert.deepEqual(calls,[['re5-session',true]]);
  assert.equal(c.snapshot().enabled,false);assert.equal(c.snapshot().state,'pending');assert.equal(c.snapshot().disabled,true);
  resolve({request:{id:'id',state:'queued'}});await click;
  c.receipt({id:'id',sid:'re5-session',op:'set_infinite_ammo',state:'claimed',result:{enabled:true}});
  assert.equal(c.snapshot().enabled,false);assert.equal(c.snapshot().state,'pending');
  c.receipt({id:'id',sid:'re5-session',op:'set_infinite_ammo',state:'confirmed',result:{enabled:true}});
  assert.equal(c.snapshot().enabled,true);assert.equal(c.snapshot().state,'confirmed');assert.equal(c.snapshot().disabled,false);
  assert.equal(frames.some(v=>v.label==='Turning on...'),true);
});
test('a confirmed receipt without a boolean waits for live options instead of claiming success',async()=>{
  let now=0;
  const c=createAmmoControl({sid:'re4-session',now:()=>now,send:async()=>({request:{id:'id',state:'confirmed'}})});
  c.observe(ammoReport(false));await c.toggle();assert.equal(c.snapshot().state,'pending');assert.equal(c.snapshot().enabled,false);
  c.observe(ammoReport(false));assert.equal(c.snapshot().state,'pending');c.observe(ammoReport(true));assert.equal(c.snapshot().state,'confirmed');
  await c.toggle();now=16000;c.observe(ammoReport(true));assert.equal(c.snapshot().state,'error');assert.match(c.snapshot().reason,/no verified readback/);
});
test('old session and unrelated request receipts cannot paint the current ammo state',async()=>{
  let sid='old',resolve;
  const c=createAmmoControl({sid:()=>sid,send:()=>new Promise(r=>resolve=r)});
  c.observe(ammoReport(false));const click=c.toggle();sid='new';c.observe(ammoReport(false));
  resolve({request:{id:'old-id',state:'confirmed',result:{enabled:true}}});await click;
  c.receipt({sid:'old',id:'old-id',op:'set_infinite_ammo',state:'confirmed',result:{enabled:true}});
  assert.equal(c.snapshot().enabled,false);assert.equal(c.snapshot().state,'confirmed');
});
test('failed ammo change exposes error and the actual state, with no automatic resubmission',async()=>{
  let posts=0;
  const c=createAmmoControl({sid:'re6-session',send:async()=>{posts++;return {request:{id:'id',state:'failed',reason:'Native guard rejected the write'}};}});
  c.observe(ammoReport(false));await c.toggle();assert.equal(posts,1);assert.equal(c.snapshot().enabled,false);
  assert.equal(c.snapshot().state,'error');assert.match(c.snapshot().reason,/Native guard/);
  c.observe(ammoReport(false));assert.equal(posts,1);assert.equal(c.snapshot().state,'error');c.dispose();await c.toggle();assert.equal(posts,1);
});

test('mismatched native confirmation remains an error with the actual boolean state',async()=>{
  const c=createAmmoControl({sid:'session',send:async()=>({request:{id:'id',state:'confirmed',result:{enabled:false}}})});
  c.observe(ammoReport(false));await c.toggle();assert.equal(c.snapshot().enabled,false);assert.equal(c.snapshot().state,'error');
  assert.match(c.snapshot().reason,/did not match/);
});
test('another request ID cannot complete an admitted ammo change',async()=>{
  const c=createAmmoControl({sid:'session',send:async()=>({request:{id:'own',state:'queued'}})});
  c.observe(ammoReport(false));await c.toggle();c.receipt({id:'other',sid:'session',op:'set_infinite_ammo',state:'confirmed',result:{enabled:true}});
  assert.equal(c.snapshot().state,'pending');assert.equal(c.snapshot().enabled,false);
});


test('stale ammo reports never present a cached boolean as live or admit a new click',()=>{
  const v=ammoView(ammoReport(true,{available:false}));assert.equal(v.enabled,null);assert.equal(v.label,'Unknown');
  assert.equal(v.disabled,true);assert.match(v.reason,/not current/);
});

test('ring types follow optional verified native choices and retain flash-only old-worker defaults',()=>{
  const old={available:true,capabilities:['grenade_ring'],options:{}};
  assert.deepEqual(ringKindOptions(old).map(r=>r.available),[true,false,false]);
  const re4={...old,options:{grenade_kinds:[{kind:'flash',available:true},{kind:'hand',available:true}]}};
  assert.deepEqual(ringKindOptions(re4).map(r=>r.available),[true,true,false]);
  assert.equal(readRingKind({getItem:()=>'hand'},ringKindOptions(re4)),'hand');
  re4.options.grenade_kinds[1]={kind:'hand',available:false,reason:'Verified unlimited health required'};
  assert.equal(ringKindOptions(re4)[1].available,false);assert.match(ringKindOptions(re4)[1].reason,/health/);
  assert.equal(ringKindOptions({...re4,available:false}).some(r=>r.available),false);
  assert.equal(ringKindOptions({...old,options:{grenade_kinds:[]}}).some(r=>r.available),false);
});

function ringFixture(){
  const win={innerWidth:800,innerHeight:600,addEventListener(){},removeEventListener(){}};
  const doc={defaultView:win,addEventListener(){},removeEventListener(){}};
  function element(tag){return {tag,ownerDocument:doc,style:{},dataset:{},attributes:{},listeners:{},children:[],isConnected:true,offsetWidth:180,offsetHeight:100,
    setAttribute(k,v){this.attributes[k]=v;},addEventListener(k,fn){this.listeners[k]=fn;},removeEventListener(){},
    append(node){node.parent=this;this.children.push(node);},remove(){if(this.parent)this.parent.children=this.parent.children.filter(n=>n!==this);},
    getBoundingClientRect(){return {left:10,bottom:25};},querySelector(){return this.children.find(n=>n.tag==='button'&&!n.disabled);},
    contains(node){return this===node||this.children.includes(node);},focus(){}};}
  doc.createElement=element;doc.body=element('body');
  let sid='re4',report={available:true,capabilities:['grenade_ring'],options:{grenade_kinds:[{kind:'flash',available:true},{kind:'hand',available:true}]}},reader;
  const button=element('button'),kindButton=element('button'),calls=[],storage={value:null,getItem(){return this.value;},setItem(_k,v){this.value=v;}};
  const control=bindRing(button,{kindButton,storage,sid:()=>sid,api:async()=>reader?reader():report,
    ring:async(session,kind)=>{calls.push([session,kind]);return {request:{state:'queued'}};}});
  return {control,button,kindButton,calls,doc,setReport:r=>report=r,setSid:s=>sid=s,setReader:f=>reader=f};
}
const ringSettled=()=>new Promise(resolve=>setImmediate(resolve));
const event={preventDefault(){},stopPropagation(){}};

test('ring chooser enables RE4 hand grenades but rechecks protection before each click',async()=>{
  const f=ringFixture();await f.kindButton.listeners.click(event);
  const hand=f.doc.body.children[0].children.find(n=>n.textContent==='Hand');assert.equal(hand.disabled,false);
  hand.onclick(event);assert.equal(f.kindButton.textContent,'Hand');f.button.listeners.click(event);await ringSettled();
  assert.deepEqual(f.calls,[['re4','hand']]);
  f.setReport({available:true,capabilities:['grenade_ring'],options:{grenade_kinds:[{kind:'flash',available:true},{kind:'hand',available:false,reason:'Verified unlimited health required'}]}});
  f.button.listeners.click(event);await ringSettled();assert.equal(f.calls.length,1);assert.match(f.button.title,/health/);
  assert.equal(f.button.dataset.ringState,'unavailable');f.control.dispose();
});

test('late ring capability read cannot send to the next session; concurrent clicks stay distinct',async()=>{
  const f=ringFixture();let release;
  f.setReader(()=>new Promise(r=>release=r));f.button.listeners.click(event);await ringSettled();f.setSid('re6');
  release({available:true,capabilities:['grenade_ring'],options:{}});await ringSettled();assert.equal(f.calls.length,0);
  const releases=[];f.setReader(()=>new Promise(r=>releases.push(r)));
  f.button.listeners.click(event);f.button.listeners.click(event);await ringSettled();
  releases[1]({available:true,capabilities:['grenade_ring'],options:{}});releases[0]({available:true,capabilities:['grenade_ring'],options:{}});
  await ringSettled();assert.deepEqual(f.calls,[['re6','flash'],['re6','flash']]);f.control.dispose();
});
