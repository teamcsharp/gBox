const { test } = require('node:test');
const assert = require('node:assert/strict');
const R = require('../clients/web/viz/session-refresh.js');

function fixture(rows = [{session_id:'main-A',state:'running'}, {session_id:'pip-B',state:'running'}]) {
  const calls=[];
  const ctl=R.create({sessions:async()=>rows,tabs:['Home','Library','Sessions'],
    show:async(...args)=>calls.push(['show',...args]),active:s=>calls.push(['active',s?.session_id||null]),pip:()=>calls.push(['pip'])});
  return {ctl,calls};
}

test('F5 restores the successor of a saved PiP instead of its ended session',async()=>{
  const x=fixture([{session_id:'old',state:'ended',replaced_by:'new'}, {session_id:'new',state:'running'}]);
  const out=await x.ctl.restore({playing:'old',active:'old',pip:'old'});
  assert.deepEqual(x.calls,[['show','Sessions','new'],['active','new'],['pip']]);
  assert.deepEqual(out.missing,[]);
});
test('two exact streams restore in their original main and PiP roles',async()=>{
  const x=fixture(); const out=await x.ctl.restore({tab:'Sessions',playing:'main-A',active:'pip-B',pip:'pip-B'});
  assert.deepEqual(x.calls,[['show','Sessions','main-A'],['active','pip-B'],['pip']]);
  assert.deepEqual(out,{restored:['main-A','pip-B'],missing:[]});
});
test('a missing main stream shows the list and retains a healthy second stream, without selecting a replacement',async()=>{
  const x=fixture([{session_id:'pip-B',state:'running'},{session_id:'new-unrelated',state:'running'}]);
  const out=await x.ctl.restore({playing:'main-A',active:'pip-B',pip:'pip-B'});
  assert.deepEqual(x.calls,[['show','Sessions'],['active','pip-B'],['pip']]);
  assert.deepEqual(out,{restored:['pip-B'],missing:['main-A']});
});
test('a saved game whose PC is offline is not reopened: the list shows instead (#2870, operator 2026-10-26)',async()=>{
  const x=fixture([{session_id:'nuc-dead',state:'running',worker_online:false},{session_id:'pip-B',state:'running'}]);
  const out=await x.ctl.restore({playing:'nuc-dead',active:'nuc-dead',pip:'pip-B'});
  assert.deepEqual(x.calls,[['show','Sessions'],['active','pip-B'],['pip']]);
  assert.deepEqual(out,{restored:['pip-B'],missing:['nuc-dead'],offline:['nuc-dead']},'offline is told apart from merely absent: the shell drops the saved view');
  const gone=fixture([{session_id:'pip-B',state:'running'}]);
  assert.deepEqual(await gone.ctl.restore({playing:'nuc-dead',pip:'pip-B'}),{restored:['pip-B'],missing:['nuc-dead']},'an absent game is retried as before');
});
test('a missing PiP does not remove the valid foreground stream or claim successful restoration',async()=>{
  const x=fixture([{session_id:'main-A',state:'running'}]);
  const out=await x.ctl.restore({playing:'main-A',active:'pip-B',pip:'pip-B'});
  assert.deepEqual(out.missing,['pip-B']); assert.deepEqual(x.calls[1],['active','main-A']);
});
test('another tab can retain PiP and unknown saved fields never reach a URL or game operation',async()=>{
  const x=fixture(); await x.ctl.restore({tab:'Library',active:'pip-B',pip:'pip-B',token:'secret',playing:'https://bad/?token=secret'});
  assert.deepEqual(x.calls,[['show','Library'],['active','pip-B'],['pip']]);
  assert.deepEqual(R.normalize({tab:'<script>',active:'a/b',pip:'ok'}),{tab:'Home',playing:null,active:null,pip:'ok'});
});
test('a cancelled or superseded restoration cannot select an old stream after the read finishes',async()=>{
  let finish; const calls=[];
  const ctl=R.create({sessions:()=>new Promise(r=>finish=r),tabs:['Home'],show:async()=>calls.push('show'),active:()=>calls.push('active'),pip:()=>calls.push('pip')});
  const pending=ctl.restore({playing:'main-A'}); ctl.cancel(); finish([{session_id:'main-A',state:'running'}]);
  assert.equal((await pending).cancelled,true);assert.deepEqual(calls,[]);
});
test('operator navigation during a delayed session lookup cancels restoration before either stream changes',async()=>{
  let finish, revision=1;const calls=[];
  const ctl=R.create({sessions:()=>new Promise(r=>finish=r),revision:()=>revision,tabs:['Home'],
    show:async()=>calls.push('show'),active:()=>calls.push('active'),pip:()=>calls.push('pip')});
  const pending=ctl.restore({playing:'main-A',pip:'pip-B'}); revision++;
  finish([{session_id:'main-A',state:'running'},{session_id:'pip-B',state:'running'}]);
  assert.equal((await pending).cancelled,true);assert.deepEqual(calls,[]);
});

test('operator navigation during stream content loading cannot restore the old PiP or leave retry intent',async()=>{
  for (const rejects of [false,true]) {
    let finish, revision=1; const calls=[];
    const ctl=R.create({sessions:async()=>[{session_id:'main-A',state:'running'},{session_id:'pip-B',state:'running'}],
      revision:()=>revision,tabs:['Home'],show:()=>{
        revision++; // the restore's own synchronous selection is allowed
        return new Promise((resolve,reject)=>{finish=()=>rejects?reject(Error('The saved stream is not available yet.')):resolve();});
      },active:()=>calls.push('active'),pip:()=>calls.push('pip')});
    const pending=ctl.restore({playing:'main-A',pip:'pip-B'});
    await new Promise(resolve=>setImmediate(resolve));
    revision++; // a later operator selection wins, even if the old load fails
    finish(); assert.deepEqual(await pending,{cancelled:true,restored:[],missing:[]}); assert.deepEqual(calls,[]);
  }
});

test('the restore own revision is allowed and genuine load failures remain retryable',async()=>{
  for (const fails of [false,true]) {
    let revision=1;const calls=[];
    const ctl=R.create({sessions:async()=>[{session_id:'main-A',state:'running'},{session_id:'pip-B',state:'running'}],
      revision:()=>revision,tabs:['Home'],show:async()=>{revision++;if(fails)throw Error('offline');},
      active:s=>calls.push(s.session_id),pip:()=>calls.push('pip')});
    const pending=ctl.restore({playing:'main-A',pip:'pip-B'});
    if(fails){await assert.rejects(pending,/offline/);assert.deepEqual(calls,[]);}
    else{assert.deepEqual(await pending,{restored:['main-A','pip-B'],missing:[]});assert.deepEqual(calls,['pip-B','pip']);}
  }
});
