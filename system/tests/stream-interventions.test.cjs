const {test}=require('node:test'); const assert=require('node:assert/strict');
const {create,RING_KINDS,ringKindLabel,readRingKind}=require('../clients/web/viz/stream-interventions.js');
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
