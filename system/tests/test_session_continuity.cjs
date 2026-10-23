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
