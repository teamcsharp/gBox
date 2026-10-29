const {test} = require('node:test');
const assert = require('node:assert/strict');
const C = require('../clients/web/viz/session-continuity');
const old = {session_id:'worker-old',state:'ended',game_id:'re5',mod:'',started:1,detail:{worker_name:'Spark'}};
const fresh = {...old,session_id:'newworker-new',state:'running',started:5,last_frame_age:.2};

test('black reboot frames are held back while dim gameplay and boot logos can appear',()=>{
  const pixels=new Uint8Array(32*18*4);
  assert.equal(C.hasPicture(pixels),false);
  for(let i=0;i<4;i++)pixels[i*4]=15;
  assert.equal(C.hasPicture(pixels),true);
});

test('multiple restarts follow the replacement chain to the current stream',()=>{
  const middle={...old,session_id:'worker-middle',replaced_by:fresh.session_id};
  assert.equal(C.resolve(old.session_id,[{...old,replaced_by:middle.session_id},middle,fresh]),fresh);
});
test('a worker reboot can recover the same game without a replacement link',()=>{
  assert.equal(C.resolve(old.session_id,[old,fresh]),fresh);
  assert.equal(C.resolve(old.session_id,[fresh],old),fresh);
});
test('another game, build or computer never takes over the watched picture',()=>{
  for(const change of [{game_id:'re4'},{mod:'different'},{detail:{worker_name:'Other'}}])
    assert.equal(C.resolve(old.session_id,[old,{...fresh,...change}]),null);
});
test('a healthy running stream remains selected; a stale orphan can recover',()=>{
  const live={...old,state:'running',last_frame_age:.1};
  assert.equal(C.resolve(old.session_id,[live,fresh]),live);
  assert.equal(C.resolve(old.session_id,[{...live,last_frame_age:40},fresh]),fresh);
});
test('replacement cycles terminate and a reboot gap retains selection',()=>{
  assert.equal(C.resolve(old.session_id,[{...old,replaced_by:'middle'},{...old,session_id:'middle',replaced_by:old.session_id}]),null);
  assert.equal(C.resolve(old.session_id,[old]),null);
});
test('offline recovery retries, keeps its game, and never sends a game operation',async()=>{
  let rows,selected=old,followed=[];
  const ctl=C.create({current:()=>selected,read:async()=>{if(!rows)throw Error('offline');return rows;},
    follow:async next=>{followed.push(next.session_id);selected=next;}});
  await ctl.poll();assert.deepEqual(followed,[]);assert.equal(selected,old);
  rows=[old,fresh];await ctl.poll();assert.deepEqual(followed,[fresh.session_id]);
});
test('closing or changing PiP during a delayed read cannot reopen the old game',async()=>{
  for(const replacement of [null,{session_id:'user-chosen-other'}]){
    let finish,selected=old;const followed=[];
    const ctl=C.create({current:()=>selected,read:()=>new Promise(r=>finish=r),follow:s=>followed.push(s)});
    const pending=ctl.poll();selected=replacement;finish([old,fresh]);await pending;
    assert.deepEqual(followed,[]);
  }
});

test('recovery commands follow the current same-game replacement and reject stale or mismatched targets',()=>{
  const replaced={...old,replaced_by:fresh.session_id};
  assert.equal(C.commandSession(old.session_id,[replaced,fresh]),fresh);
  assert.equal(C.commandSession(fresh.session_id,[fresh]),fresh);
  assert.equal(C.commandSession(old.session_id,[old]),null);
  assert.equal(C.commandSession(old.session_id,[replaced,{...fresh,game_id:'other-game'}]),null);
  assert.equal(C.commandSession(old.session_id,[replaced,{...fresh,worker_online:false}]),null);
});

test('a game on a PC that is offline is not running for a viewer: never selected, followed or recovered (#2870)',async()=>{
  const dead={...fresh,worker_online:false};
  assert.equal(C.resolve(dead.session_id,[dead]),null);
  assert.equal(C.resolve(old.session_id,[{...old,replaced_by:dead.session_id},dead]),null,'a replacement on an offline PC is not followed');
  assert.equal(C.resolve(old.session_id,[old,dead]),null,'nor is a same-game relaunch there');
  const followed=[];
  const ctl=C.create({current:()=>old,read:async()=>[old,dead],follow:async next=>followed.push(next.session_id)});
  await ctl.poll();assert.deepEqual(followed,[]);
  assert.equal(C.commandSession(dead.session_id,[dead]),null);
  assert.equal(C.resolve(fresh.session_id,[fresh]),fresh,'a PC that answers is unchanged');
});

test('a warm MercMode view follows both turns while commands keep their selected game',()=>{
  const a={...fresh,session_id:'worker-a',game_id:'re5'};
  const b={...fresh,session_id:'worker-b',game_id:'re4'};
  const parkedA={...a,warm:true,replaced_by:b.session_id,mercmode_display_successor:true};
  assert.equal(C.resolve(a.session_id,[parkedA,b]),b);
  assert.equal(C.commandSession(a.session_id,[parkedA,b]),null);
  const parkedB={...b,warm:true,replaced_by:a.session_id,mercmode_display_successor:true};
  assert.equal(C.resolve(b.session_id,[a,parkedB]),a);
  assert.equal(C.resolve(a.session_id,[a,parkedB]),a);
});

test('automatic continuity never selects a fresh parked game as a replacement',()=>{
  const warm={...fresh,session_id:'worker-warm',started:10,warm:true};
  for(const origin of [old,{...old,state:'running',last_frame_age:40}]){
    assert.equal(C.resolve(origin.session_id,[origin,warm]),origin.state==='running'?origin:null);
    assert.equal(C.resolve(origin.session_id,[origin,fresh,warm]),fresh,'a newer parked game cannot displace the live replacement');
    assert.equal(C.resolve(origin.session_id,[{...origin,replaced_by:warm.session_id},warm])?.session_id,
      origin.state==='running'?origin.session_id:undefined,'an explicit link cannot finish on a parked target');
  }
  assert.equal(C.resolve(warm.session_id,[warm]),null,'a parked origin without a live successor is not a view target');
});

test('replacement chains still traverse parked intermediates to the live game',()=>{
  const middle={...fresh,session_id:'worker-warm',warm:true,replaced_by:fresh.session_id};
  assert.equal(C.resolve(old.session_id,[{...old,replaced_by:middle.session_id},middle,fresh]),fresh);
});
